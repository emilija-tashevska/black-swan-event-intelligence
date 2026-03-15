from __future__ import annotations

import aiosqlite

DB_PATH = "black_swan.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS markets (
    ticker            TEXT PRIMARY KEY,
    event_ticker      TEXT NOT NULL,
    market_type       TEXT NOT NULL,
    title             TEXT NOT NULL DEFAULT '',
    subtitle          TEXT NOT NULL DEFAULT '',
    yes_sub_title     TEXT NOT NULL DEFAULT '',
    no_sub_title      TEXT NOT NULL DEFAULT '',
    open_time         TEXT,
    close_time        TEXT,
    created_time      TEXT,
    status            TEXT NOT NULL,
    result            TEXT NOT NULL DEFAULT '',

    last_price_dollars TEXT NOT NULL DEFAULT '0.0000',
    yes_bid_dollars    TEXT NOT NULL DEFAULT '0.0000',
    yes_ask_dollars    TEXT NOT NULL DEFAULT '0.0000',
    no_bid_dollars     TEXT NOT NULL DEFAULT '0.0000',
    no_ask_dollars     TEXT NOT NULL DEFAULT '0.0000',
    volume_fp          TEXT NOT NULL DEFAULT '0.00',
    open_interest_fp   TEXT NOT NULL DEFAULT '0.00',
    notional_value_dollars TEXT NOT NULL DEFAULT '0.0000',

    settlement_ts           TEXT,
    settlement_value_dollars TEXT,
    rules_primary           TEXT NOT NULL DEFAULT '',

    prediction_price  REAL,
    prediction_ts     INTEGER,
    prediction_volume INTEGER,
    is_black_swan     INTEGER NOT NULL DEFAULT 0,
    category          TEXT NOT NULL DEFAULT '',
    ai_summary        TEXT NOT NULL DEFAULT '',
    volume_at_price   INTEGER,
    is_sports         INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_markets_result ON markets(result);
CREATE INDEX IF NOT EXISTS idx_markets_black_swan ON markets(is_black_swan);
CREATE INDEX IF NOT EXISTS idx_markets_event ON markets(event_ticker);
CREATE INDEX IF NOT EXISTS idx_markets_bs_pred ON markets(is_black_swan, prediction_price);
CREATE INDEX IF NOT EXISTS idx_markets_result_pred ON markets(result, prediction_price);

CREATE TABLE IF NOT EXISTS metadata (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    return db


MIGRATIONS = [
    "ALTER TABLE markets ADD COLUMN prediction_volume INTEGER",
    "ALTER TABLE markets ADD COLUMN category TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE markets ADD COLUMN ai_summary TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE markets ADD COLUMN volume_at_price INTEGER",
    "ALTER TABLE markets ADD COLUMN is_sports INTEGER NOT NULL DEFAULT 0",
]


async def init_db() -> None:
    db = await get_db()
    try:
        await db.executescript(SCHEMA)
        for sql in MIGRATIONS:
            try:
                await db.execute(sql)
            except Exception:
                pass  # column already exists
        await db.commit()
    finally:
        await db.close()


async def get_meta(db: aiosqlite.Connection, key: str) -> str | None:
    cursor = await db.execute("SELECT value FROM metadata WHERE key = ?", (key,))
    row = await cursor.fetchone()
    return row[0] if row else None


async def set_meta(db: aiosqlite.Connection, key: str, value: str) -> None:
    await db.execute(
        "INSERT INTO metadata (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    await db.commit()


UPSERT_MARKET = """
INSERT INTO markets (
    ticker, event_ticker, market_type, title, subtitle,
    yes_sub_title, no_sub_title, open_time, close_time, created_time,
    status, result, last_price_dollars, yes_bid_dollars, yes_ask_dollars,
    no_bid_dollars, no_ask_dollars, volume_fp, open_interest_fp,
    notional_value_dollars, settlement_ts, settlement_value_dollars,
    rules_primary
) VALUES (
    :ticker, :event_ticker, :market_type, :title, :subtitle,
    :yes_sub_title, :no_sub_title, :open_time, :close_time, :created_time,
    :status, :result, :last_price_dollars, :yes_bid_dollars, :yes_ask_dollars,
    :no_bid_dollars, :no_ask_dollars, :volume_fp, :open_interest_fp,
    :notional_value_dollars, :settlement_ts, :settlement_value_dollars,
    :rules_primary
)
ON CONFLICT(ticker) DO UPDATE SET
    status = excluded.status,
    result = excluded.result,
    last_price_dollars = excluded.last_price_dollars,
    yes_bid_dollars = excluded.yes_bid_dollars,
    yes_ask_dollars = excluded.yes_ask_dollars,
    no_bid_dollars = excluded.no_bid_dollars,
    no_ask_dollars = excluded.no_ask_dollars,
    volume_fp = excluded.volume_fp,
    open_interest_fp = excluded.open_interest_fp,
    settlement_ts = excluded.settlement_ts,
    settlement_value_dollars = excluded.settlement_value_dollars;
"""


UPDATE_PREDICTION = """
UPDATE markets
SET prediction_price = :prediction_price,
    prediction_ts = :prediction_ts,
    is_black_swan = :is_black_swan
WHERE ticker = :ticker;
"""


async def upsert_markets(db: aiosqlite.Connection, rows: list[dict]) -> int:
    await db.executemany(UPSERT_MARKET, rows)
    await db.commit()
    return len(rows)


async def update_prediction(
    db: aiosqlite.Connection,
    ticker: str,
    prediction_price: float | None,
    prediction_ts: int | None,
    threshold: float = 0.10,
) -> None:
    is_black_swan = (
        1
        if prediction_price is not None and prediction_price < threshold
        else 0
    )
    await db.execute(
        UPDATE_PREDICTION,
        {
            "ticker": ticker,
            "prediction_price": prediction_price,
            "prediction_ts": prediction_ts,
            "is_black_swan": is_black_swan,
        },
    )
    await db.commit()


async def get_yes_markets_needing_prediction(
    db: aiosqlite.Connection,
    min_volume: float = 1000.0,
) -> list[aiosqlite.Row]:
    """Get YES-resolved markets that need candlestick enrichment.
    Only returns markets open for 7+ days (shorter ones use last_price directly)."""
    cursor = await db.execute(
        "SELECT ticker, event_ticker, close_time, open_time "
        "FROM markets WHERE result = 'yes' AND prediction_price IS NULL "
        "AND CAST(volume_fp AS REAL) >= ? "
        "AND (julianday(close_time) - julianday(open_time)) >= 7",
        (min_volume,),
    )
    return await cursor.fetchall()


async def set_short_market_predictions(
    db: aiosqlite.Connection,
    min_volume: float = 1000.0,
    threshold: float = 0.10,
) -> int:
    """For YES markets open < 7 days, use last_price_dollars as the prediction
    price since there's no meaningful 7-day lookback for these."""
    result = await db.execute(
        """
        UPDATE markets
        SET prediction_price = CAST(last_price_dollars AS REAL),
            prediction_ts = CAST(strftime('%s', close_time) AS INTEGER),
            is_black_swan = CASE WHEN CAST(last_price_dollars AS REAL) < ? THEN 1 ELSE 0 END
        WHERE result = 'yes' AND prediction_price IS NULL
        AND CAST(volume_fp AS REAL) >= ?
        AND (julianday(close_time) - julianday(open_time)) < 7
        """,
        (threshold, min_volume),
    )
    await db.commit()
    return result.rowcount


async def get_black_swans(
    db: aiosqlite.Connection,
    threshold: float = 0.10,
    sort: str = "prediction_price",
    order: str = "asc",
    limit: int = 50,
    offset: int = 0,
) -> list[aiosqlite.Row]:
    allowed_sorts = {
        "prediction_price", "volume_fp", "close_time", "settlement_ts", "title",
        "open_interest_fp", "category",
    }
    col = sort if sort in allowed_sorts else "prediction_price"
    if col in ("volume_fp", "open_interest_fp"):
        col = f"CAST({col} AS REAL)"
    direction = "DESC" if order.lower() == "desc" else "ASC"

    cursor = await db.execute(
        f"""
        SELECT ticker, event_ticker, title, yes_sub_title,
               prediction_price, prediction_ts, prediction_volume,
               last_price_dollars,
               volume_fp, open_interest_fp, close_time, settlement_ts, result,
               yes_bid_dollars, yes_ask_dollars, rules_primary,
               category, ai_summary, volume_at_price
        FROM markets
        WHERE result = 'yes' AND prediction_price IS NOT NULL
              AND prediction_price < ? AND is_sports = 0
        ORDER BY {col} {direction}
        LIMIT ? OFFSET ?
        """,
        (threshold, limit, offset),
    )
    return await cursor.fetchall()


async def update_prediction_volume(
    db: aiosqlite.Connection, ticker: str, volume: int | None,
) -> None:
    await db.execute(
        "UPDATE markets SET prediction_volume = ? WHERE ticker = ?",
        (volume, ticker),
    )
    await db.commit()


async def update_category_batch(
    db: aiosqlite.Connection, updates: list[tuple[str, str]],
) -> int:
    await db.executemany(
        "UPDATE markets SET category = ? WHERE ticker = ?", updates,
    )
    await db.commit()
    return len(updates)


async def update_volume_at_price(
    db: aiosqlite.Connection, ticker: str, volume: int | None,
) -> None:
    await db.execute(
        "UPDATE markets SET volume_at_price = ? WHERE ticker = ?",
        (volume, ticker),
    )
    await db.commit()


async def update_ai_summary(
    db: aiosqlite.Connection, ticker: str, summary: str,
) -> None:
    await db.execute(
        "UPDATE markets SET ai_summary = ? WHERE ticker = ?",
        (summary, ticker),
    )
    await db.commit()


async def get_black_swans_for_enrichment(
    db: aiosqlite.Connection,
    threshold: float = 0.25,
) -> list[aiosqlite.Row]:
    cursor = await db.execute(
        """SELECT ticker, event_ticker, title, yes_sub_title,
                  close_time, open_time, rules_primary,
                  prediction_price, prediction_volume, ai_summary, category,
                  volume_at_price
           FROM markets
           WHERE result = 'yes' AND prediction_price IS NOT NULL
                 AND prediction_price < ? AND is_sports = 0""",
        (threshold,),
    )
    return await cursor.fetchall()


async def get_stats(
    db: aiosqlite.Connection, threshold: float = 0.10,
) -> dict:
    cursor = await db.execute(
        """
        SELECT
            COUNT(*) as total_black_swans,
            AVG(prediction_price) as avg_prediction_price,
            MIN(prediction_price) as lowest_prediction_price,
            SUM(CAST(volume_fp AS REAL)) as total_volume,
            SUM((1.0 - prediction_price) * COALESCE(volume_at_price, 0)) as total_profit_at_price,
            MIN(settlement_ts) as earliest_settlement,
            MAX(settlement_ts) as latest_settlement
        FROM markets
        WHERE result = 'yes' AND prediction_price IS NOT NULL
              AND prediction_price < ? AND is_sports = 0
        """,
        (threshold,),
    )
    row = await cursor.fetchone()

    total_cursor = await db.execute(
        "SELECT COUNT(*) FROM markets WHERE prediction_price IS NOT NULL AND is_sports = 0"
    )
    total_row = await total_cursor.fetchone()

    cat_cursor = await db.execute(
        """
        SELECT
            CASE WHEN category = '' THEN 'Other' ELSE category END as cat,
            COUNT(*) as cnt
        FROM markets
        WHERE result = 'yes' AND prediction_price IS NOT NULL
              AND prediction_price < ? AND is_sports = 0
        GROUP BY cat ORDER BY cnt DESC
        """,
        (threshold,),
    )
    cat_rows = await cat_cursor.fetchall()

    return {
        "total_black_swans": row["total_black_swans"] or 0,
        "total_markets_analyzed": total_row[0],
        "avg_prediction_price": row["avg_prediction_price"],
        "lowest_prediction_price": row["lowest_prediction_price"],
        "total_volume": row["total_volume"] or 0.0,
        "total_profit_at_price": row["total_profit_at_price"] or 0.0,
        "earliest_settlement": row["earliest_settlement"],
        "latest_settlement": row["latest_settlement"],
        "category_stats": [{"category": r["cat"], "count": r["cnt"]} for r in cat_rows],
    }
