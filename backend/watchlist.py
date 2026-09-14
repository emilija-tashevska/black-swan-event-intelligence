"""Open low-priced markets, each compared with how similar markets actually resolved.

This is a base-rate check, not a forecast: it says how often markets in the same
category and price range happened when priced like this a week before close.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import aiosqlite

import config
import database as dbq
from calibration import bucket_index, summarize
from collector import CategoryResolver
from kalshi import KalshiClient
from models import to_count, to_dollars

logger = logging.getLogger(__name__)

# Calibration is measured on prices 7 days before close, so only watch markets
# closing around that horizon.
HORIZON_MIN_DAYS = 4
HORIZON_MAX_DAYS = 10
WATCH_MAX_PRICE = 0.25
MIN_GROUP_MARKETS = 30
MIN_GROUP_EVENTS = 10


def current_price(m: dict) -> tuple[float, str] | None:
    """Tight order-book midpoint if available (it reflects now), else last trade."""
    bid = to_dollars(m.get("yes_bid_dollars"))
    ask = to_dollars(m.get("yes_ask_dollars"))
    tight = bid is not None and ask is not None and 0 <= ask - bid <= config.MAX_QUOTE_SPREAD + 1e-9
    if tight and ask > 0:
        return (bid + ask) / 2, "quote"
    last = to_dollars(m.get("last_price_dollars"))
    if last:
        return last, "last_trade"
    return None


async def collect_open_markets(
    client: KalshiClient,
    db: aiosqlite.Connection,
    resolver: CategoryResolver,
    now: datetime | None = None,
) -> int:
    now = now or datetime.now(UTC)
    lo = int((now + timedelta(days=HORIZON_MIN_DAYS)).timestamp())
    hi = int((now + timedelta(days=HORIZON_MAX_DAYS)).timestamp())
    rows: list[dict] = []
    async for page in client.open_markets(lo, hi):
        for m in page:
            if to_count(m.get("volume_fp")) < config.MIN_VOLUME:
                continue
            priced = current_price(m)
            if priced is None or priced[0] >= WATCH_MAX_PRICE:
                continue
            series_ticker, category = await resolver.resolve(m["event_ticker"])
            if category in config.EXCLUDED_CATEGORIES:
                continue
            rows.append({
                "ticker": m["ticker"],
                "event_ticker": m["event_ticker"],
                "series_ticker": series_ticker,
                "category": category,
                "title": m.get("title") or "",
                "yes_sub_title": m.get("yes_sub_title") or "",
                "rules_primary": m.get("rules_primary") or "",
                "close_time": m.get("close_time"),
                "price": priced[0],
                "price_source": priced[1],
                "yes_bid": to_dollars(m.get("yes_bid_dollars")),
                "yes_ask": to_dollars(m.get("yes_ask_dollars")),
                "last_price": to_dollars(m.get("last_price_dollars")),
                "volume": to_count(m.get("volume_fp")),
            })
    await dbq.replace_open_markets(db, rows)
    await dbq.set_meta(db, "watchlist_ts", str(int(now.timestamp())))
    logger.info("Watchlist: %d open markets priced under %.0f%%", len(rows), WATCH_MAX_PRICE * 100)
    return len(rows)


def base_rate(
    calibration: dict, category: str, price: float, structure: str = "unknown",
) -> dict | None:
    """The historical bucket for this price, from the most specific group with
    enough history: category × structure, then structure, then category, then
    everything. Structure outranks category because it drives the mechanics
    (an award also-ran and a lone yes/no market behave differently at 5%)."""
    edges = calibration["bucket_edges"]
    idx = bucket_index(price)
    lo, hi = edges[idx], edges[idx + 1]

    def find(curve: dict) -> dict | None:
        for b in curve["buckets"]:
            if (b["lo"] == lo and b["hi"] == hi and b["n"] >= MIN_GROUP_MARKETS
                    and b["events"] >= MIN_GROUP_EVENTS):
                return b
        return None

    def group(key: str, c: str | None, s: str | None) -> dict | None:
        return next((g for g in calibration[key]
                     if g["category"] == c and g["structure"] == s), None)

    known = structure if structure != "unknown" else None
    candidates = [
        (group("segments", category, known) if known else None, f"{category} · {known}"),
        (group("structures", None, known) if known else None, f"All categories · {known}"),
        (group("categories", category, None), category),
        (calibration["overall"], "All markets"),
    ]
    for curve, scope in candidates:
        if curve and (b := find(curve)):
            return {**b, "scope": scope}
    return None


def assess(base: dict | None) -> str:
    """Whether the comparable group was itself mispriced. The group is judged
    against its own average price, not this market's: a market at the bottom
    edge of a fairly priced 20–30% bucket shouldn't look underpriced just
    because the bucket's hit rate reflects prices around 25%."""
    if base is None:
        return "insufficient_history"
    if base["ci_low"] > base["mean_price"]:
        return "happens_more_often"
    if base["ci_high"] < base["mean_price"]:
        return "happens_less_often"
    return "in_line"


async def build_calibration(db: aiosqlite.Connection) -> dict:
    rows = await dbq.scored_outcomes(db)
    return summarize(
        (r["category"], r["structure"], r["event_ticker"], r["prediction_price"],
         bool(r["resolved_yes"]))
        for r in rows
    )


async def build_watchlist(db: aiosqlite.Connection, calibration: dict | None = None) -> dict:
    calibration = calibration or await build_calibration(db)
    markets = []
    for m in await dbq.query_open_markets(db):
        base = base_rate(calibration, m["category"], m["price"], m["structure"])
        markets.append({**m, "base_rate": base, "assessment": assess(base)})
    order = {"happens_more_often": 0, "in_line": 1, "happens_less_often": 2,
             "insufficient_history": 3}
    markets.sort(key=lambda m: (order[m["assessment"]], m["close_time"] or "", m["ticker"]))
    fetched = await dbq.get_meta(db, "watchlist_ts")
    return {
        "fetched_at": datetime.fromtimestamp(int(fetched), UTC).isoformat() if fetched else None,
        "horizon_days": [HORIZON_MIN_DAYS, HORIZON_MAX_DAYS],
        "max_price": WATCH_MAX_PRICE,
        "min_group_markets": MIN_GROUP_MARKETS,
        "min_group_events": MIN_GROUP_EVENTS,
        "markets": markets,
    }
