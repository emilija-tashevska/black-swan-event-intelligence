"""Data pipeline: collect settled markets, score each YES market's implied
probability a week before close, then enrich the black swans with trade depth."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import aiosqlite

import config
import database as dbq
from kalshi import KalshiClient
from models import Candlestick, to_count, to_dollars

logger = logging.getLogger(__name__)

DAY = 86_400
SCORING_CONCURRENCY = 5
SCORING_BATCH = 100


# ── Pure helpers ──

def parse_ts(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def series_prefix(event_ticker: str) -> str:
    """Kalshi event tickers are SERIES-SUFFIX, e.g. KXBTC-26FEB2717 -> KXBTC."""
    return event_ticker.split("-", 1)[0]


def lookback_ts(close_ts: int, days: int = config.LOOKBACK_DAYS) -> int:
    return close_ts - days * DAY


def pick_prediction_candle(candles: Iterable[Candlestick], as_of_ts: int) -> Candlestick | None:
    """The latest daily candle that had fully closed by `as_of_ts`. Candles that
    end after it are ignored so the price never includes later information."""
    eligible = [c for c in candles if c.end_period_ts <= as_of_ts]
    return max(eligible, key=lambda c: c.end_period_ts, default=None)


def contracts_near_price(trades: Iterable[dict], price: float, tolerance: float) -> float:
    total = 0.0
    for t in trades:
        trade_price = to_dollars(t.get("yes_price_dollars"))
        if trade_price is not None and abs(trade_price - price) <= tolerance + 1e-9:
            total += to_count(t.get("count_fp"))
    return total


def is_historical(market: aiosqlite.Row | dict, cutoff_ts: int | None) -> bool:
    """Markets settled before Kalshi's archive cutoff are only served by /historical."""
    settled = parse_ts(market["settlement_ts"]) or parse_ts(market["close_time"])
    return cutoff_ts is not None and settled is not None and settled < cutoff_ts


def market_to_row(m: dict, series_ticker: str, category: str) -> dict:
    return {
        "ticker": m["ticker"],
        "event_ticker": m["event_ticker"],
        "series_ticker": series_ticker,
        "category": category,
        "title": m.get("title") or "",
        "yes_sub_title": m.get("yes_sub_title") or "",
        "rules_primary": m.get("rules_primary") or "",
        "open_time": m.get("open_time"),
        "close_time": m.get("close_time"),
        "settlement_ts": m.get("settlement_ts"),
        "result": m.get("result") or "",
        "last_price": to_dollars(m.get("last_price_dollars")) or 0.0,
        "volume": to_count(m.get("volume_fp")),
        "open_interest": to_count(m.get("open_interest_fp")),
    }


# ── Categories ──

class CategoryResolver:
    """Maps markets to Kalshi's official series category. Uses the full series
    list, falling back to an event lookup when a ticker prefix isn't a series."""

    def __init__(self, client: KalshiClient, series: list[dict]) -> None:
        self._client = client
        self._by_series = {s["ticker"]: s.get("category") or "" for s in series}
        self._by_event: dict[str, tuple[str, str]] = {}

    @classmethod
    async def load(cls, client: KalshiClient) -> CategoryResolver:
        series = await client.get_all_series()
        logger.info("Loaded categories for %d series", len(series))
        return cls(client, series)

    async def resolve(self, event_ticker: str) -> tuple[str, str]:
        prefix = series_prefix(event_ticker)
        if prefix in self._by_series:
            return prefix, self._by_series[prefix]
        if event_ticker not in self._by_event:
            try:
                event = await self._client.get_event(event_ticker)
                series_ticker = event.get("series_ticker") or prefix
                category = event.get("category") or self._by_series.get(series_ticker, "")
            except Exception as e:
                logger.warning("Could not resolve category for %s: %s", event_ticker, e)
                series_ticker, category = prefix, ""
            self._by_event[event_ticker] = (series_ticker, category)
        return self._by_event[event_ticker]


# ── Phase 1: collect ──

@dataclass
class CollectionResult:
    scanned: int = 0
    stored: int = 0
    skipped_thin: int = 0
    skipped_category: dict[str, int] = field(default_factory=dict)


RESUME_PREFIX = "collect:"


async def collect_markets(
    client: KalshiClient,
    db: aiosqlite.Connection,
    resolver: CategoryResolver,
    now: datetime | None = None,
) -> CollectionResult:
    """Fetch settled markets (live + archive) since the last run, keeping liquid,
    in-scope markets. The first run looks back COLLECTION_WINDOW_DAYS.

    Progress (window and page cursors) is checkpointed after every page, so an
    interrupted collection resumes where it stopped instead of rescanning."""
    started = await dbq.get_meta(db, RESUME_PREFIX + "started_ts")
    if started:
        started_ts = int(started)
        min_settled_ts = int(await dbq.get_meta(db, RESUME_PREFIX + "min_settled_ts"))
        logger.info("Resuming interrupted collection (window since %s)",
                    datetime.fromtimestamp(min_settled_ts, UTC))
    else:
        now = now or datetime.now(UTC)
        started_ts = int(now.timestamp())
        last = await dbq.get_meta(db, "last_collection_ts")
        if last:
            min_settled_ts = int(last)
            logger.info("Incremental collection since %s",
                        datetime.fromtimestamp(min_settled_ts, UTC))
        else:
            min_settled_ts = int((now - timedelta(days=config.COLLECTION_WINDOW_DAYS)).timestamp())
            logger.info("First collection: last %d days", config.COLLECTION_WINDOW_DAYS)
        await dbq.set_meta(db, RESUME_PREFIX + "started_ts", str(started_ts))
        await dbq.set_meta(db, RESUME_PREFIX + "min_settled_ts", str(min_settled_ts))

    result = CollectionResult()
    sources: list[tuple[str, Callable[[int, str | None], AsyncIterator]]] = [
        ("live", client.settled_markets),
    ]
    cutoff_ts = parse_ts(await client.get_cutoff_ts())
    if cutoff_ts is None or min_settled_ts < cutoff_ts:
        sources.append(("historical", client.historical_markets))
    else:
        logger.info("Window starts after the archive cutoff; skipping /historical")

    for label, source in sources:
        if await dbq.get_meta(db, f"{RESUME_PREFIX}{label}:done"):
            logger.info("%s: already collected in this run", label)
            continue
        cursor = await dbq.get_meta(db, f"{RESUME_PREFIX}{label}:cursor")
        async for page, next_cursor in source(min_settled_ts, cursor):
            rows = []
            for m in page:
                result.scanned += 1
                if to_count(m.get("volume_fp")) < config.MIN_VOLUME:
                    result.skipped_thin += 1
                    continue
                series_ticker, category = await resolver.resolve(m["event_ticker"])
                if category in config.EXCLUDED_CATEGORIES:
                    result.skipped_category[category] = result.skipped_category.get(category, 0) + 1
                    continue
                rows.append(market_to_row(m, series_ticker, category))
            if rows:
                result.stored += await dbq.upsert_markets(db, rows)
            if next_cursor:
                await dbq.set_meta(db, f"{RESUME_PREFIX}{label}:cursor", next_cursor)
            logger.info(
                "%s: scanned %d, stored %d, thin %d, excluded %s",
                label, result.scanned, result.stored, result.skipped_thin, result.skipped_category,
            )
        await dbq.set_meta(db, f"{RESUME_PREFIX}{label}:done", "1")

    # Next run starts from when this one started, so nothing settling mid-run is missed.
    await dbq.set_meta(db, "last_collection_ts", str(started_ts))
    await dbq.delete_meta_prefix(db, RESUME_PREFIX)
    return result


# ── Phase 2: score ──

@dataclass(frozen=True)
class Score:
    status: str
    price: float | None = None
    source: str | None = None
    ts: int | None = None
    volume: float | None = None


NO_DATA = Score("no_data")


async def score_market(
    client: KalshiClient, market: aiosqlite.Row | dict, cutoff_ts: int | None,
) -> Score | None:
    """The market's implied probability a week before close, or None on a
    transient error so the market is retried next run."""
    close_ts = parse_ts(market["close_time"])
    if close_ts is None:
        return NO_DATA
    as_of = lookback_ts(close_ts)
    try:
        candles = await client.get_candlesticks(
            market["ticker"], as_of - 3 * DAY, as_of,
            historical=is_historical(market, cutoff_ts),
            series_ticker=market["series_ticker"],
        )
    except Exception as e:
        logger.warning("Candlestick fetch failed for %s: %s", market["ticker"], e)
        return None
    candle = pick_prediction_candle(candles, as_of)
    implied = candle.implied_probability(config.MAX_QUOTE_SPREAD) if candle else None
    if candle is None or implied is None:
        return NO_DATA
    price, source = implied
    return Score("ok", price, source, candle.end_period_ts, candle.contracts_traded())


async def score_predictions(client: KalshiClient, db: aiosqlite.Connection) -> dict:
    short = await dbq.mark_short_lived(db, config.MIN_MARKET_DURATION_DAYS)
    logger.info("Excluded %d short-lived YES markets (< %d days)", short,
                config.MIN_MARKET_DURATION_DAYS)

    cutoff_ts = parse_ts(await client.get_cutoff_ts())
    markets = await dbq.markets_needing_prediction(db)
    logger.info("Scoring %d YES markets", len(markets))

    sem = asyncio.Semaphore(SCORING_CONCURRENCY)

    async def bounded(m):
        async with sem:
            return m["ticker"], await score_market(client, m, cutoff_ts)

    counts = {
        "short_lived": short, "ok": 0, "no_data": 0, "errors": 0,
        "from_quotes": 0, "black_swans": 0,
    }
    for start in range(0, len(markets), SCORING_BATCH):
        batch = markets[start : start + SCORING_BATCH]
        for ticker, scored in await asyncio.gather(*(bounded(m) for m in batch)):
            if scored is None:
                counts["errors"] += 1
                continue
            await dbq.set_prediction(
                db, ticker, scored.status, scored.price, scored.source, scored.ts, scored.volume,
            )
            counts[scored.status] += 1
            if scored.source == "quote":
                counts["from_quotes"] += 1
            if scored.price is not None and scored.price < config.DEFAULT_THRESHOLD:
                counts["black_swans"] += 1
        await db.commit()
        logger.info("Scored %d / %d %s", start + len(batch), len(markets), counts)
    return counts


# ── Phase 3: trade depth at the prediction price ──

async def enrich_depth(client: KalshiClient, db: aiosqlite.Connection) -> int:
    """Contracts traded within ±PRICE_TOLERANCE of the prediction price during the
    prediction candle's day — how much money actually backed that price."""
    cutoff_ts = parse_ts(await client.get_cutoff_ts())
    markets = await dbq.black_swans_needing_depth(db, config.MAX_THRESHOLD)
    logger.info("Fetching trade depth for %d black swans", len(markets))
    done = 0
    for m in markets:
        end = m["prediction_ts"]
        try:
            trades = await client.get_trades(
                m["ticker"], end - DAY, end, historical=is_historical(m, cutoff_ts),
            )
        except Exception as e:
            logger.warning("Trade fetch failed for %s: %s", m["ticker"], e)
            continue
        depth = contracts_near_price(trades, m["prediction_price"], config.PRICE_TOLERANCE)
        await dbq.set_volume_at_price(db, m["ticker"], depth)
        done += 1
        if done % 25 == 0:
            logger.info("Depth: %d / %d", done, len(markets))
    return done
