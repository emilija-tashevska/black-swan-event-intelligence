"""Classify events by how their markets relate, because that changes what a
low price means.

- standalone: a single yes/no market ("Will Trump apologize before 2027?")
- pick_one:   mutually exclusive outcomes, exactly one wins (award nominees, price ranges)
- ladder:     nested thresholds on one number ("CPI above 4.4% / 4.5% / 4.6%")
- bundle:     several independent-looking markets on one occasion (words said in a speech)

Markets inside an event are not independent draws, which calibration intervals
must account for; see calibration.clustered_interval.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter

import aiosqlite

import database as dbq
from kalshi import KalshiClient

logger = logging.getLogger(__name__)

STRUCTURES = ("standalone", "pick_one", "ladder", "bundle")
THRESHOLD_STRIKES = frozenset({"greater", "greater_or_equal", "less", "less_or_equal", "between"})
LOOKUP_CONCURRENCY = 3


def classify(mutually_exclusive: bool | None, market_count: int, strike_type: str | None) -> str:
    if market_count <= 1:
        return "standalone"
    if mutually_exclusive:
        return "pick_one"
    if strike_type in THRESHOLD_STRIKES:
        return "ladder"
    return "bundle"


async def describe_event(client: KalshiClient, event_ticker: str, local_count: int) -> dict:
    event = await client.get_event(event_ticker)
    markets = await client.markets_for_event(event_ticker, historical=False)
    if not markets:
        markets = await client.markets_for_event(event_ticker, historical=True)
    strikes = Counter(m.get("strike_type") for m in markets if m.get("strike_type"))
    strike_type = strikes.most_common(1)[0][0] if strikes else None
    market_count = max(len(markets), local_count)
    mutually_exclusive = event.get("mutually_exclusive")
    return {
        "event_ticker": event_ticker,
        "series_ticker": event.get("series_ticker") or "",
        "title": event.get("title") or "",
        "mutually_exclusive": None if mutually_exclusive is None else int(bool(mutually_exclusive)),
        "market_count": market_count,
        "strike_type": strike_type,
        "structure": classify(mutually_exclusive, market_count, strike_type),
    }


async def enrich_structures(client: KalshiClient, db: aiosqlite.Connection) -> dict:
    """Classify every event behind a scored or watchlist market that isn't
    classified yet. Failed lookups are skipped and retried on the next run."""
    pending = await dbq.events_missing_structure(db)
    logger.info("Classifying %d events", len(pending))
    sem = asyncio.Semaphore(LOOKUP_CONCURRENCY)

    async def one(row) -> dict | None:
        async with sem:
            try:
                return await describe_event(client, row["event_ticker"], row["local_count"])
            except Exception as e:
                logger.warning("Structure lookup failed for %s: %s", row["event_ticker"], e)
                return None

    counts: Counter[str] = Counter()
    batch = 100
    for start in range(0, len(pending), batch):
        results = await asyncio.gather(*(one(r) for r in pending[start : start + batch]))
        rows = [r for r in results if r]
        await dbq.upsert_events(db, rows)
        counts.update(r["structure"] for r in rows)
        counts["errors"] += len(results) - len(rows)
        logger.info("Structures: %d / %d %s", start + len(results), len(pending), dict(counts))
    return dict(counts)
