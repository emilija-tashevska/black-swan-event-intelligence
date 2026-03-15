from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import aiosqlite

from database import (
    DB_PATH,
    get_black_swans_for_enrichment,
    get_meta,
    get_yes_markets_needing_prediction,
    init_db,
    set_meta,
    set_short_market_predictions,
    update_ai_summary,
    update_category_batch,
    update_prediction,
    update_prediction_volume,
    update_volume_at_price,
    upsert_markets,
)
from kalshi import KalshiClient

logger = logging.getLogger(__name__)

LOOKBACK_DAYS = 7
MIN_VOLUME = 1000.0
COLLECTION_WINDOW_DAYS = 180

SPORTS_PREFIXES = (
    # US major leagues
    "KXNBA", "KXNHL", "KXNCAA", "KXNFL", "KXMLB", "KXMLBST", "KXMLS",
    "KXWNBA", "KXCFL", "KXUSL",
    # NFL coaching / trades
    "KXNEXTNFL", "KXNEXTTEAMNBA",
    # European soccer
    "KXEPL", "KXUCL", "KXLALIGA", "KXSERIEA", "KXBUNDESLIGA", "KXLIGUE1",
    "KXLIGAMX", "KXCHAMPIONSLEAGUE", "KXEUROPALEAGUE", "KXEFLCHAMPIONSHIP",
    "KXCOPA", "KXSOCCER", "KXUEL",
    # Other soccer leagues
    "KXVENFUTVE", "KXCHLLDP", "KXAPFDDH", "KXSERIEAGAME", "KXSERIEABTTS",
    "KXSERIEATOTAL", "KXLALIGABTTS", "KXLALIGATOTAL",
    # Tennis / golf / combat / racing
    "KXATP", "KXWTA", "KXPGA", "KXLPGA", "KXDPWORLDTOUR",
    "KXUFC", "KXNASCAR", "KXWWE", "KXBOXING", "KXF1", "KXFORMULA",
    "KXCRICKET", "KXRUGBY", "KXTENNIS", "KXGOLF",
    # International / basketball / hockey
    "KXFIBA", "KXAHL", "KXKHL", "KXWBC", "KXWOXC",
    # Winter Olympics (KXWO* but NOT KXWTI etc.)
    "KXWO",
    # Esports
    "KXCS2", "KXLOL", "KXVALORANT", "KXDOTA2", "KXR6",
    # T20 cricket
    "KXT20",
)


def _is_sports(ticker: str) -> bool:
    t = ticker.upper()
    return any(t.startswith(p) for p in SPORTS_PREFIXES)


CATEGORY_MAP = {
    # Crypto
    "KXBTC": "Crypto", "KXETH": "Crypto", "KXSOL": "Crypto",
    "KXXRP": "Crypto", "KXDOGE": "Crypto", "KXSHIBA": "Crypto",
    "KXADA": "Crypto", "KXBNB": "Crypto", "KXAVAX": "Crypto",
    "KXLINK": "Crypto", "KXMATIC": "Crypto", "KXDOT": "Crypto",
    # Finance / markets
    "KXINX": "Finance", "KXNASDAQ": "Finance", "KXWTI": "Finance",
    "KXTNOTE": "Finance", "KXUSDJPY": "Finance", "KXEURUSD": "Finance",
    "KXGBPUSD": "Finance", "KXTBILL": "Finance", "KXSPX": "Finance",
    "KXGOLD": "Finance", "KXSILVER": "Finance", "KXDXY": "Finance",
    "KXFED": "Finance", "KXCPI": "Finance", "KXGDP": "Finance",
    "KXJOBLESS": "Finance", "KXNFP": "Finance", "KXPCE": "Finance",
    "KXUNEMPLOY": "Finance",
    # Weather / energy
    "KXHIGH": "Weather", "KXLOW": "Weather", "KXAAGAS": "Weather",
    "KXRAIN": "Weather", "KXSNOW": "Weather", "KXHURRICANE": "Weather",
    # Entertainment / awards
    "KXGRAM": "Entertainment", "KXBAFTA": "Entertainment",
    "KXSAGAWARD": "Entertainment", "KXBILLBOARD": "Entertainment",
    "KXRT": "Entertainment", "KXDGA": "Entertainment",
    "KXWHATSONSTAGE": "Entertainment", "KXOSCAR": "Entertainment",
    "KXEMMY": "Entertainment", "KXGOLDENGLOBE": "Entertainment",
    "KXTONY": "Entertainment",
    # Politics / government
    "KXCAB": "Politics", "KXLDP": "Politics", "KXTXPRIMARY": "Politics",
    "KXTRUTHSOCIAL": "Politics", "KXHOCHUL": "Politics",
    "KXTRUMP": "Politics", "KXBIDEN": "Politics", "KXSENATE": "Politics",
    "KXHOUSE": "Politics", "KXGOV": "Politics", "KXELECT": "Politics",
    "KXPRIMARY": "Politics", "KXEXECORDER": "Politics",
    "KXPARDON": "Politics", "KXCEASEFIRE": "Politics",
    "KXTARIFF": "Politics",
    # Business / M&A
    "KXACQU": "Business", "KXIPO": "Business", "KXEARNINGS": "Business",
    # Mentions (press conferences, speeches)
    "KXMENTION": "Culture", "KXWOMENTION": "Culture",
}


def categorize_ticker(ticker: str) -> str:
    t = ticker.upper()
    for prefix, cat in CATEGORY_MAP.items():
        if t.startswith(prefix):
            return cat
    return "Other"


def _market_to_row(m: dict) -> dict:
    return {
        "ticker": m["ticker"],
        "event_ticker": m["event_ticker"],
        "market_type": m.get("market_type", ""),
        "title": m.get("title", ""),
        "subtitle": m.get("subtitle", ""),
        "yes_sub_title": m.get("yes_sub_title", ""),
        "no_sub_title": m.get("no_sub_title", ""),
        "open_time": m.get("open_time"),
        "close_time": m.get("close_time"),
        "created_time": m.get("created_time"),
        "status": m.get("status", ""),
        "result": m.get("result", ""),
        "last_price_dollars": m.get("last_price_dollars", "0.0000"),
        "yes_bid_dollars": m.get("yes_bid_dollars", "0.0000"),
        "yes_ask_dollars": m.get("yes_ask_dollars", "0.0000"),
        "no_bid_dollars": m.get("no_bid_dollars", "0.0000"),
        "no_ask_dollars": m.get("no_ask_dollars", "0.0000"),
        "volume_fp": m.get("volume_fp", "0.00"),
        "open_interest_fp": m.get("open_interest_fp", "0.00"),
        "notional_value_dollars": m.get("notional_value_dollars", "0.0000"),
        "settlement_ts": m.get("settlement_ts"),
        "settlement_value_dollars": m.get("settlement_value_dollars"),
        "rules_primary": m.get("rules_primary", ""),
    }


def _parse_ts(iso_str: str | None) -> int | None:
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return int(dt.timestamp())
    except (ValueError, TypeError):
        return None


async def _determine_cutoff_ts(client: KalshiClient) -> int | None:
    try:
        data = await client.get_cutoff()
        ts = data.get("market_settled_ts")
        if ts:
            return int(ts)
    except Exception:
        logger.warning("Could not fetch cutoff, treating all as historical")
    return None


def _filter_batch(batch: list[dict]) -> list[dict]:
    """Drop sports markets and zero/low-volume markets from a batch."""
    kept = []
    for m in batch:
        if _is_sports(m.get("ticker", "")):
            continue
        kept.append(m)
    return kept


async def collect_markets(client: KalshiClient, db: aiosqlite.Connection) -> int:
    """Phase 1: Fetch settled markets incrementally. On first run fetches
    the last COLLECTION_WINDOW_DAYS, on subsequent runs only fetches
    markets settled since the last successful collection."""
    total = 0
    skipped = 0

    last_run = await get_meta(db, "last_collection_ts")
    if last_run:
        min_settled_ts = int(last_run)
        logger.info("Incremental run: fetching markets settled since ts=%s", last_run)
    else:
        cutoff = datetime.now(timezone.utc) - timedelta(days=COLLECTION_WINDOW_DAYS)
        min_settled_ts = int(cutoff.timestamp())
        logger.info("First run: fetching markets from last %d days (since %s)", COLLECTION_WINDOW_DAYS, cutoff.date())

    now_ts = int(datetime.now(timezone.utc).timestamp())

    async for batch in client.paginate_batches(
        "/markets", "markets",
        {"status": "settled", "mve_filter": "exclude", "min_settled_ts": min_settled_ts},
    ):
        filtered = _filter_batch(batch)
        skipped += len(batch) - len(filtered)
        if filtered:
            rows = [_market_to_row(m) for m in filtered]
            count = await upsert_markets(db, rows)
            total += count
        logger.info("Live: stored %d (skipped %d sports), total: %d", len(filtered), skipped, total)

    async for batch in client.paginate_batches(
        "/historical/markets", "markets",
        {"min_settled_ts": min_settled_ts},
    ):
        filtered = _filter_batch(batch)
        skipped += len(batch) - len(filtered)
        if filtered:
            rows = [_market_to_row(m) for m in filtered]
            count = await upsert_markets(db, rows)
            total += count
        logger.info("Historical: stored %d (skipped %d sports total), total: %d", len(filtered), skipped, total)

    await set_meta(db, "last_collection_ts", str(now_ts))
    logger.info("Phase 1 complete: %d markets stored, %d sports skipped", total, skipped)
    return total


ENRICHMENT_CONCURRENCY = 5


async def _enrich_one(
    client: KalshiClient,
    sem: asyncio.Semaphore,
    market: dict,
    cutoff_ts: int | None,
    event_series_cache: dict[str, str | None],
    event_lock: asyncio.Lock,
    threshold: float,
) -> tuple[str, float | None, int | None]:
    """Fetch candlestick for one market. Returns (ticker, pred_price, pred_ts)."""
    ticker = market["ticker"]
    event_ticker = market["event_ticker"]
    close_ts = _parse_ts(market["close_time"])
    open_ts = _parse_ts(market["open_time"])

    if close_ts is None or _is_sports(ticker):
        return ticker, None, None

    lookback_ts = close_ts - (LOOKBACK_DAYS * 86400)
    if open_ts and lookback_ts < open_ts:
        lookback_ts = open_ts

    start_ts = lookback_ts - 86400
    end_ts = lookback_ts + 86400

    try:
        async with sem:
            is_historical = cutoff_ts is not None and close_ts < cutoff_ts
            if is_historical:
                candles = await client.get_historical_candlesticks(
                    ticker, start_ts, end_ts, 1440,
                )
            else:
                async with event_lock:
                    if event_ticker not in event_series_cache:
                        try:
                            event = await client.get_event(event_ticker)
                            event_series_cache[event_ticker] = event.get("series_ticker")
                        except Exception:
                            event_series_cache[event_ticker] = None

                series_ticker = event_series_cache.get(event_ticker)
                if not series_ticker:
                    return ticker, None, None

                candles = await client.get_live_candlesticks(
                    series_ticker, ticker, start_ts, end_ts, 1440,
                )

        if candles:
            best = min(candles, key=lambda c: abs(c.end_period_ts - lookback_ts))
            close_price_str = best.price.get_close() or best.price.get_mean() or best.price.get_previous()
            if close_price_str:
                return ticker, float(close_price_str), best.end_period_ts

    except Exception as e:
        logger.warning("Error enriching %s: %s", ticker, e)

    return ticker, None, None


async def enrich_predictions(
    client: KalshiClient,
    db: aiosqlite.Connection,
    threshold: float = 0.10,
) -> int:
    """Phase 2: For YES-resolved markets with volume >= 1000 and without a
    prediction_price, fetch the daily candlestick from 7 days before close.
    Runs up to ENRICHMENT_CONCURRENCY requests in parallel."""
    short_count = await set_short_market_predictions(db, MIN_VOLUME, threshold)
    logger.info("Phase 2a: set prediction for %d short-lived markets (< 7 days) using last_price", short_count)

    cutoff_ts = await _determine_cutoff_ts(client)
    markets = await get_yes_markets_needing_prediction(db, MIN_VOLUME)
    logger.info("Phase 2b: %d long-lived markets (>= 7 days, volume >= %d) need candlestick enrichment", len(markets), int(MIN_VOLUME))

    sem = asyncio.Semaphore(ENRICHMENT_CONCURRENCY)
    event_series_cache: dict[str, str | None] = {}
    event_lock = asyncio.Lock()
    enriched = 0
    black_swans = 0

    batch_size = 50
    for batch_start in range(0, len(markets), batch_size):
        batch = markets[batch_start : batch_start + batch_size]
        tasks = [
            _enrich_one(client, sem, dict(m), cutoff_ts, event_series_cache, event_lock, threshold)
            for m in batch
        ]
        results = await asyncio.gather(*tasks)

        for ticker, pred_price, pred_ts in results:
            await update_prediction(db, ticker, pred_price, pred_ts, threshold)
            if pred_price is not None:
                enriched += 1
                if pred_price < threshold:
                    black_swans += 1
                    logger.info("BLACK SWAN: price=%.4f ticker=%s", pred_price, ticker)

        done = min(batch_start + batch_size, len(markets))
        logger.info("Enrichment progress: %d / %d (%d enriched, %d black swans)", done, len(markets), enriched, black_swans)

    logger.info("Phase 2 complete: %d enriched, %d black swans found", enriched, black_swans)
    return enriched


async def run_full_collection(threshold: float = 0.10) -> dict:
    await init_db()

    async with KalshiClient() as client:
        db = await aiosqlite.connect(DB_PATH)
        db.row_factory = aiosqlite.Row
        try:
            total_markets = await collect_markets(client, db)
            enriched = await enrich_predictions(client, db, threshold)
            return {
                "total_markets_fetched": total_markets,
                "yes_markets_enriched": enriched,
            }
        finally:
            await db.close()


async def populate_categories(db: aiosqlite.Connection) -> int:
    """Set category for all black swan markets based on ticker prefix."""
    rows = await get_black_swans_for_enrichment(db)
    updates: list[tuple[str, str]] = []
    for r in rows:
        cat = categorize_ticker(r["ticker"])
        if cat != (r["category"] or ""):
            updates.append((cat, r["ticker"]))
    if updates:
        await update_category_batch(db, updates)
    logger.info("Categorized %d black swan markets", len(updates))
    return len(updates)


async def tag_sports_markets(db: aiosqlite.Connection) -> int:
    """Tag all sports markets with is_sports=1 and unflag them as black swans."""
    result = await db.execute(
        "SELECT ticker FROM markets WHERE is_sports = 0"
    )
    rows = await result.fetchall()
    tagged = 0
    for r in rows:
        if _is_sports(r["ticker"]):
            await db.execute(
                "UPDATE markets SET is_sports = 1, is_black_swan = 0 WHERE ticker = ?",
                (r["ticker"],),
            )
            tagged += 1
    if tagged:
        await db.commit()
    logger.info("Tagged %d sports markets", tagged)
    return tagged


async def enrich_prediction_volumes(
    client: KalshiClient, db: aiosqlite.Connection,
) -> int:
    """For black swan markets missing prediction_volume, re-fetch the
    7-day-prior candlestick and store the trading volume for that day."""
    cutoff_ts = await _determine_cutoff_ts(client)
    rows = await get_black_swans_for_enrichment(db)
    need = [r for r in rows if r["prediction_volume"] is None]
    logger.info("Fetching prediction-day volume for %d black swans", len(need))

    event_series_cache: dict[str, str | None] = {}
    enriched = 0

    for i, market in enumerate(need):
        ticker = market["ticker"]
        close_ts = _parse_ts(market["close_time"])
        open_ts = _parse_ts(market["open_time"])
        if close_ts is None:
            continue

        lookback_ts = close_ts - (LOOKBACK_DAYS * 86400)
        if open_ts and lookback_ts < open_ts:
            lookback_ts = open_ts

        start_ts = lookback_ts - 86400
        end_ts = lookback_ts + 86400

        try:
            is_historical = cutoff_ts is not None and close_ts < cutoff_ts
            if is_historical:
                candles = await client.get_historical_candlesticks(
                    ticker, start_ts, end_ts, 1440,
                )
            else:
                event_ticker = market["event_ticker"]
                if event_ticker not in event_series_cache:
                    try:
                        event = await client.get_event(event_ticker)
                        event_series_cache[event_ticker] = event.get("series_ticker")
                    except Exception:
                        event_series_cache[event_ticker] = None
                series_ticker = event_series_cache.get(event_ticker)
                if not series_ticker:
                    continue
                candles = await client.get_live_candlesticks(
                    series_ticker, ticker, start_ts, end_ts, 1440,
                )

            if candles:
                best = min(candles, key=lambda c: abs(c.end_period_ts - lookback_ts))
                vol_raw = best.volume_fp or best.volume
                vol = int(float(vol_raw)) if vol_raw is not None else 0
                await update_prediction_volume(db, ticker, vol)
                enriched += 1
        except Exception as e:
            logger.warning("Error fetching volume for %s: %s", ticker, e)

        if (i + 1) % 25 == 0:
            logger.info("Prediction volume progress: %d / %d", i + 1, len(need))

    logger.info("Prediction volume enrichment complete: %d updated", enriched)
    return enriched


PRICE_TOLERANCE = 0.02  # ±$0.02 when matching trades to prediction price


async def enrich_volume_at_price(
    client: KalshiClient, db: aiosqlite.Connection,
) -> int:
    """For black swan markets, fetch individual trades on the prediction day
    and count how many contracts traded at/near the prediction price."""
    cutoff_ts = await _determine_cutoff_ts(client)
    rows = await get_black_swans_for_enrichment(db)
    need = [r for r in rows if r["volume_at_price"] is None and r["prediction_price"] is not None]
    logger.info("Fetching volume-at-price for %d markets", len(need))

    enriched = 0
    for i, market in enumerate(need):
        ticker = market["ticker"]
        pred_price = market["prediction_price"]
        close_ts = _parse_ts(market["close_time"])
        open_ts = _parse_ts(market["open_time"])
        if close_ts is None:
            continue

        lookback_ts = close_ts - (LOOKBACK_DAYS * 86400)
        if open_ts and lookback_ts < open_ts:
            lookback_ts = open_ts

        day_start = lookback_ts - 43200  # noon-to-noon window
        day_end = lookback_ts + 43200

        try:
            is_historical = cutoff_ts is not None and close_ts < cutoff_ts
            if is_historical:
                trades = await client.get_historical_trades(ticker, day_start, day_end)
            else:
                trades = await client.get_live_trades(ticker, day_start, day_end)

            vol = 0
            for t in trades:
                trade_price = float(t.get("yes_price_dollars", "0"))
                if abs(trade_price - pred_price) <= PRICE_TOLERANCE:
                    count_str = t.get("count_fp", "0")
                    vol += int(float(count_str))

            await update_volume_at_price(db, ticker, vol)
            enriched += 1
        except Exception as e:
            logger.warning("Error fetching trades for %s: %s", ticker, e)

        if (i + 1) % 25 == 0:
            logger.info("Volume-at-price progress: %d / %d", i + 1, len(need))

    logger.info("Volume-at-price enrichment complete: %d updated", enriched)
    return enriched


async def generate_ai_summaries(
    db: aiosqlite.Connection, api_key: str, force_all: bool = False,
) -> int:
    """Generate concise one-liner summaries for black swan markets using Gemini."""
    import httpx as _httpx

    rows = await get_black_swans_for_enrichment(db)
    if force_all:
        need = list(rows)
    else:
        need = [r for r in rows if not r["ai_summary"]]
    logger.info("Generating AI summaries for %d markets (force_all=%s)", len(need), force_all)

    generated = 0
    batch_size = 10

    async with _httpx.AsyncClient(timeout=60.0) as http:
        for batch_start in range(0, len(need), batch_size):
            batch = need[batch_start : batch_start + batch_size]
            items = []
            for m in batch:
                close_date = (m["close_time"] or "")[:10]
                rules_snippet = (m["rules_primary"] or "")[:200]
                items.append(
                    f"- ticker={m['ticker']} title=\"{m['title']}\" "
                    f"outcome=\"{m['yes_sub_title']}\" close_date={close_date} "
                    f"rules=\"{rules_snippet}\""
                )

            prompt = (
                "For each prediction market below, write a single concise "
                "headline (max 15 words) describing what actually happened. "
                "The outcome column resolved YES. Write it as a factual past-tense "
                "statement, not a question. Include key specifics: city names for "
                "weather markets, asset names for finance, company names for business, "
                "candidate names for politics, amounts, and dates where relevant. "
                "Use the rules field for additional context (e.g. which city, which asset). "
                "Return ONLY one line per market, in the same order, no numbering.\n\n"
                + "\n".join(items)
            )

            try:
                resp = await http.post(
                    "https://generativelanguage.googleapis.com/v1beta/models/"
                    "gemini-2.0-flash:generateContent",
                    params={"key": api_key},
                    json={
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {"temperature": 0.3},
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                lines = [l.strip() for l in text.strip().split("\n") if l.strip()]

                for j, m in enumerate(batch):
                    summary = lines[j] if j < len(lines) else ""
                    summary = summary.lstrip("- ").lstrip("* ")
                    if summary:
                        await update_ai_summary(db, m["ticker"], summary)
                        generated += 1

                logger.info("AI summaries: %d / %d done", batch_start + len(batch), len(need))
                await asyncio.sleep(1)  # rate limit Gemini
            except Exception as e:
                logger.warning("AI summary batch error: %s", e)

    logger.info("AI summary generation complete: %d generated", generated)
    return generated


async def run_enrichment_only(threshold: float = 0.10) -> dict:
    """Run only Phase 2 enrichment on existing data in the DB."""
    await init_db()

    async with KalshiClient() as client:
        db = await aiosqlite.connect(DB_PATH)
        db.row_factory = aiosqlite.Row
        try:
            enriched = await enrich_predictions(client, db, threshold)
            return {"yes_markets_enriched": enriched}
        finally:
            await db.close()


async def run_black_swan_enrichment(
    api_key: str | None = None, regenerate_summaries: bool = False,
) -> dict:
    """Run post-detection enrichment: sports cleanup, categories,
    prediction volumes, trade volume at price, and AI summaries."""
    await init_db()

    async with KalshiClient() as client:
        db = await aiosqlite.connect(DB_PATH)
        db.row_factory = aiosqlite.Row
        try:
            unflagged = await tag_sports_markets(db)
            categorized = await populate_categories(db)
            volumes = await enrich_prediction_volumes(client, db)
            vol_at_price = await enrich_volume_at_price(client, db)
            summaries = 0
            if api_key:
                summaries = await generate_ai_summaries(
                    db, api_key, force_all=regenerate_summaries,
                )
            return {
                "sports_unflagged": unflagged,
                "categorized": categorized,
                "volumes_enriched": volumes,
                "volume_at_price_enriched": vol_at_price,
                "ai_summaries": summaries,
            }
        finally:
            await db.close()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    result = asyncio.run(run_full_collection())
    print(f"Collection complete: {result}")
