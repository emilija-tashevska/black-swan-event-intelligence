"""SQLite schema and every query the pipeline, API and export share."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

import config

SCHEMA_VERSION = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS markets (
    ticker             TEXT PRIMARY KEY,
    event_ticker       TEXT NOT NULL,
    series_ticker      TEXT NOT NULL DEFAULT '',
    category           TEXT NOT NULL DEFAULT '',
    title              TEXT NOT NULL DEFAULT '',
    yes_sub_title      TEXT NOT NULL DEFAULT '',
    rules_primary      TEXT NOT NULL DEFAULT '',
    open_time          TEXT,
    close_time         TEXT,
    settlement_ts      TEXT,
    result             TEXT NOT NULL DEFAULT '',
    last_price         REAL NOT NULL DEFAULT 0,
    volume             REAL NOT NULL DEFAULT 0,
    open_interest      REAL NOT NULL DEFAULT 0,

    -- NULL = not scored yet; 'ok' | 'no_data' | 'short_lived'
    prediction_status  TEXT,
    prediction_price   REAL,
    prediction_source  TEXT,              -- 'trade' | 'quote'
    prediction_ts      INTEGER,
    prediction_volume  REAL,
    volume_at_price    REAL,
    ai_summary         TEXT NOT NULL DEFAULT '',
    ai_model           TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_markets_scoring
    ON markets(result, prediction_status, prediction_price);
CREATE INDEX IF NOT EXISTS idx_markets_category ON markets(category);

-- Snapshot of currently open, low-priced markets; replaced on every watchlist run.
CREATE TABLE IF NOT EXISTS open_markets (
    ticker         TEXT PRIMARY KEY,
    event_ticker   TEXT NOT NULL,
    series_ticker  TEXT NOT NULL DEFAULT '',
    category       TEXT NOT NULL DEFAULT '',
    title          TEXT NOT NULL DEFAULT '',
    yes_sub_title  TEXT NOT NULL DEFAULT '',
    rules_primary  TEXT NOT NULL DEFAULT '',
    close_time     TEXT,
    price          REAL NOT NULL,
    price_source   TEXT NOT NULL,
    yes_bid        REAL,
    yes_ask        REAL,
    last_price     REAL,
    volume         REAL NOT NULL DEFAULT 0
);

-- How an event's markets relate to each other; see structure.py.
CREATE TABLE IF NOT EXISTS events (
    event_ticker        TEXT PRIMARY KEY,
    series_ticker       TEXT NOT NULL DEFAULT '',
    title               TEXT NOT NULL DEFAULT '',
    mutually_exclusive  INTEGER,
    market_count        INTEGER NOT NULL,
    strike_type         TEXT,
    structure           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS metadata (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

RESOLVED = "result IN ('yes', 'no')"

BLACK_SWAN_WHERE = (
    "result = 'yes' AND prediction_status = 'ok' AND prediction_price < :threshold"
)

SORTABLE_COLUMNS = {
    "prediction_price", "volume", "close_time", "open_interest",
    "volume_at_price", "category", "title",
}

BLACK_SWAN_COLUMNS = """
    ticker, event_ticker, series_ticker, category, title, yes_sub_title, rules_primary,
    open_time, close_time, settlement_ts, last_price, volume, open_interest,
    prediction_price, prediction_source, prediction_ts, prediction_volume, volume_at_price,
    ai_summary
"""


class SchemaMismatchError(RuntimeError):
    pass


@asynccontextmanager
async def connect(path: Path | str | None = None) -> AsyncIterator[aiosqlite.Connection]:
    db = await aiosqlite.connect(str(path or config.DB_PATH))
    db.row_factory = aiosqlite.Row
    try:
        await _init(db)
        yield db
    finally:
        await db.close()


async def _init(db: aiosqlite.Connection) -> None:
    version = (await (await db.execute("PRAGMA user_version")).fetchone())[0]
    has_tables = await (
        await db.execute("SELECT 1 FROM sqlite_master WHERE name = 'markets'")
    ).fetchone()
    if has_tables and version != SCHEMA_VERSION:
        raise SchemaMismatchError(
            f"Database schema v{version} is from an older version of this project; "
            "delete the database file and re-run the pipeline."
        )
    await db.executescript(SCHEMA)
    await db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    await db.commit()


# ── Metadata ──

async def get_meta(db: aiosqlite.Connection, key: str) -> str | None:
    row = await (await db.execute("SELECT value FROM metadata WHERE key = ?", (key,))).fetchone()
    return row[0] if row else None


async def set_meta(db: aiosqlite.Connection, key: str, value: str) -> None:
    await db.execute(
        "INSERT INTO metadata (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    await db.commit()


async def delete_meta_prefix(db: aiosqlite.Connection, prefix: str) -> None:
    await db.execute("DELETE FROM metadata WHERE key LIKE ? || '%'", (prefix,))
    await db.commit()


# ── Collection ──

UPSERT_MARKET = """
INSERT INTO markets (
    ticker, event_ticker, series_ticker, category, title, yes_sub_title, rules_primary,
    open_time, close_time, settlement_ts, result, last_price, volume, open_interest
) VALUES (
    :ticker, :event_ticker, :series_ticker, :category, :title, :yes_sub_title, :rules_primary,
    :open_time, :close_time, :settlement_ts, :result, :last_price, :volume, :open_interest
)
ON CONFLICT(ticker) DO UPDATE SET
    result = excluded.result,
    close_time = excluded.close_time,
    settlement_ts = excluded.settlement_ts,
    last_price = excluded.last_price,
    volume = excluded.volume,
    open_interest = excluded.open_interest
"""


async def upsert_markets(db: aiosqlite.Connection, rows: list[dict]) -> int:
    await db.executemany(UPSERT_MARKET, rows)
    await db.commit()
    return len(rows)


# ── Scoring ──

async def mark_short_lived(db: aiosqlite.Connection, min_duration_days: float) -> int:
    """Markets open for less than the lookback have no 7-day-prior price; they
    are recorded as out of scope rather than scored on a stale last trade.
    Both outcomes are scored: NO markets are what make calibration possible."""
    cur = await db.execute(
        f"""UPDATE markets SET prediction_status = 'short_lived'
           WHERE {RESOLVED} AND prediction_status IS NULL
             AND julianday(close_time) - julianday(open_time) < ?""",
        (min_duration_days,),
    )
    await db.commit()
    return cur.rowcount


async def markets_needing_prediction(db: aiosqlite.Connection) -> list[aiosqlite.Row]:
    cur = await db.execute(
        f"""SELECT ticker, series_ticker, result, open_time, close_time, settlement_ts
            FROM markets WHERE {RESOLVED} AND prediction_status IS NULL
            ORDER BY close_time"""
    )
    return list(await cur.fetchall())


async def set_prediction(
    db: aiosqlite.Connection,
    ticker: str,
    status: str,
    price: float | None = None,
    source: str | None = None,
    ts: int | None = None,
    volume: float | None = None,
) -> None:
    await db.execute(
        """UPDATE markets SET prediction_status = ?, prediction_price = ?,
                  prediction_source = ?, prediction_ts = ?, prediction_volume = ?
           WHERE ticker = ?""",
        (status, price, source, ts, volume, ticker),
    )
    # Callers commit once per batch.


# ── Post-detection enrichment ──

async def black_swans_needing_depth(
    db: aiosqlite.Connection, threshold: float,
) -> list[aiosqlite.Row]:
    cur = await db.execute(
        f"""SELECT ticker, close_time, settlement_ts, prediction_price, prediction_ts FROM markets
            WHERE {BLACK_SWAN_WHERE} AND volume_at_price IS NULL""",
        {"threshold": threshold},
    )
    return list(await cur.fetchall())


async def set_volume_at_price(db: aiosqlite.Connection, ticker: str, volume: float) -> None:
    await db.execute("UPDATE markets SET volume_at_price = ? WHERE ticker = ?", (volume, ticker))
    await db.commit()


async def black_swans_needing_summary(
    db: aiosqlite.Connection, threshold: float, force: bool = False,
) -> list[aiosqlite.Row]:
    cur = await db.execute(
        f"""SELECT ticker, category, title, yes_sub_title, rules_primary, close_time
            FROM markets WHERE {BLACK_SWAN_WHERE}
            {"" if force else "AND ai_summary = ''"}
            ORDER BY ticker""",
        {"threshold": threshold},
    )
    return list(await cur.fetchall())


async def set_ai_summaries(
    db: aiosqlite.Connection, summaries: Iterable[tuple[str, str]], model: str,
) -> None:
    await db.executemany(
        "UPDATE markets SET ai_summary = ?, ai_model = ? WHERE ticker = ?",
        [(summary, model, ticker) for ticker, summary in summaries],
    )
    await db.commit()


# ── Read queries (API + static export) ──

async def query_black_swans(
    db: aiosqlite.Connection,
    threshold: float = config.DEFAULT_THRESHOLD,
    sort: str = "volume",
    order: str = "desc",
    limit: int = 500,
    offset: int = 0,
    category: str | None = None,
) -> list[dict]:
    col = sort if sort in SORTABLE_COLUMNS else "volume"
    direction = "ASC" if order.lower() == "asc" else "DESC"
    where = BLACK_SWAN_WHERE + (" AND category = :category" if category else "")
    cur = await db.execute(
        f"""SELECT m.*, COALESCE(e.structure, 'unknown') AS structure
            FROM (SELECT {BLACK_SWAN_COLUMNS} FROM markets WHERE {where}) m
            LEFT JOIN events e USING (event_ticker)
            ORDER BY m.{col} IS NULL, m.{col} {direction}, m.ticker
            LIMIT :limit OFFSET :offset""",
        {"threshold": threshold, "category": category, "limit": limit, "offset": offset},
    )
    return [dict(r) for r in await cur.fetchall()]


async def query_stats(
    db: aiosqlite.Connection, threshold: float = config.DEFAULT_THRESHOLD,
) -> dict:
    params = {"threshold": threshold}
    row = await (await db.execute(
        f"""SELECT COUNT(*) AS total_black_swans,
                   AVG(prediction_price) AS avg_prediction_price,
                   MIN(prediction_price) AS lowest_prediction_price,
                   COALESCE(SUM(volume), 0) AS total_volume,
                   COALESCE(SUM((1.0 - prediction_price) * volume_at_price), 0)
                       AS yes_side_upside,
                   MIN(close_time) AS earliest_close,
                   MAX(close_time) AS latest_close
            FROM markets WHERE {BLACK_SWAN_WHERE}""",
        params,
    )).fetchone()

    counts = await (await db.execute(
        """SELECT COUNT(*) AS markets_collected,
                  SUM(result = 'yes') AS yes_markets,
                  SUM(result = 'yes' AND prediction_status = 'ok') AS markets_scored,
                  SUM(result = 'yes' AND prediction_status = 'short_lived')
                      AS short_lived_excluded
           FROM markets"""
    )).fetchone()

    cats = await (await db.execute(
        f"""SELECT category,
                   SUM(result = 'yes' AND prediction_status = 'ok') AS scored,
                   SUM({BLACK_SWAN_WHERE}) AS black_swans
            FROM markets GROUP BY category
            HAVING black_swans > 0
            ORDER BY black_swans DESC, category""",
        params,
    )).fetchall()

    return {
        "threshold": threshold,
        "total_black_swans": row["total_black_swans"],
        "avg_prediction_price": row["avg_prediction_price"],
        "lowest_prediction_price": row["lowest_prediction_price"],
        "total_volume": row["total_volume"],
        "yes_side_upside": row["yes_side_upside"],
        "earliest_close": row["earliest_close"],
        "latest_close": row["latest_close"],
        "markets_collected": counts["markets_collected"] or 0,
        "yes_markets": counts["yes_markets"] or 0,
        "markets_scored": counts["markets_scored"] or 0,
        "short_lived_excluded": counts["short_lived_excluded"] or 0,
        "category_stats": [
            {
                "category": c["category"] or "Uncategorized",
                "count": c["black_swans"],
                "scored": c["scored"],
                "rate": c["black_swans"] / c["scored"] if c["scored"] else None,
            }
            for c in cats
        ],
    }


# ── Calibration and watchlist ──

async def scored_outcomes(db: aiosqlite.Connection) -> list[aiosqlite.Row]:
    """Every scored, resolved market: the raw material for calibration."""
    cur = await db.execute(
        f"""SELECT m.category, COALESCE(e.structure, 'unknown') AS structure, m.event_ticker,
                   m.prediction_price, m.result = 'yes' AS resolved_yes
            FROM markets m LEFT JOIN events e USING (event_ticker)
            WHERE m.{RESOLVED} AND m.prediction_status = 'ok'"""
    )
    return list(await cur.fetchall())


async def events_missing_structure(db: aiosqlite.Connection) -> list[aiosqlite.Row]:
    """Events of scored markets or open watchlist markets not yet classified,
    with how many of their markets we hold locally (a lower bound)."""
    cur = await db.execute(
        """SELECT event_ticker, MAX(series_ticker) AS series_ticker, COUNT(*) AS local_count
           FROM (
               SELECT event_ticker, series_ticker FROM markets WHERE prediction_status = 'ok'
               UNION ALL
               SELECT event_ticker, series_ticker FROM open_markets
           )
           WHERE event_ticker NOT IN (SELECT event_ticker FROM events)
           GROUP BY event_ticker ORDER BY event_ticker"""
    )
    return list(await cur.fetchall())


async def upsert_events(db: aiosqlite.Connection, rows: list[dict]) -> None:
    await db.executemany(
        """INSERT INTO events (event_ticker, series_ticker, title, mutually_exclusive,
                               market_count, strike_type, structure)
           VALUES (:event_ticker, :series_ticker, :title, :mutually_exclusive,
                   :market_count, :strike_type, :structure)
           ON CONFLICT(event_ticker) DO UPDATE SET
               title = excluded.title, mutually_exclusive = excluded.mutually_exclusive,
               market_count = excluded.market_count, strike_type = excluded.strike_type,
               structure = excluded.structure""",
        rows,
    )
    await db.commit()


UPSERT_OPEN_MARKET = """
INSERT INTO open_markets (
    ticker, event_ticker, series_ticker, category, title, yes_sub_title, rules_primary,
    close_time, price, price_source, yes_bid, yes_ask, last_price, volume
) VALUES (
    :ticker, :event_ticker, :series_ticker, :category, :title, :yes_sub_title, :rules_primary,
    :close_time, :price, :price_source, :yes_bid, :yes_ask, :last_price, :volume
)
"""


async def replace_open_markets(db: aiosqlite.Connection, rows: list[dict]) -> None:
    await db.execute("DELETE FROM open_markets")
    await db.executemany(UPSERT_OPEN_MARKET, rows)
    await db.commit()


async def query_open_markets(db: aiosqlite.Connection) -> list[dict]:
    cur = await db.execute(
        """SELECT o.*, COALESCE(e.structure, 'unknown') AS structure
           FROM open_markets o LEFT JOIN events e USING (event_ticker)
           ORDER BY o.close_time, o.ticker"""
    )
    return [dict(r) for r in await cur.fetchall()]
