import aiosqlite
import pytest
from conftest import DAY, FakeKalshi, candle, db_row, insert_rows, load_fixture, make_market

import collector
import database as dbq
from calibration import midpoint_check
from models import Candlestick
from watchlist import build_calibration

SERIES = load_fixture("series.json")["series"]
CLOSE = 1_780_000_000
LOOKBACK = CLOSE - 7 * DAY


def quoted(end_ts, close="0.0500", bid="0.0300", ask="0.0500"):
    c = candle(end_ts, close)
    c["yes_bid"] = {"close_dollars": bid}
    c["yes_ask"] = {"close_dollars": ask}
    return c


def test_closing_quote_from_real_live_candle():
    raw = load_fixture("candles_live_no_trades.json")["candlesticks"][0]
    assert Candlestick.model_validate(raw).closing_quote() == (0.0, 0.06)
    assert Candlestick.model_validate(candle(1, "0.05")).closing_quote() == (None, None)


async def test_existing_database_is_migrated_in_place(tmp_path):
    path = tmp_path / "v2.db"
    async with dbq.connect(path) as db:
        await insert_rows(db, [db_row("KX-OLD-A", prediction_status="ok", prediction_price=0.05)])
    # Simulate a database created before the quote columns existed
    async with aiosqlite.connect(path) as raw:
        await raw.execute("ALTER TABLE markets DROP COLUMN quote_checked")
        await raw.execute("ALTER TABLE markets DROP COLUMN prediction_yes_bid")
        await raw.commit()

    async with dbq.connect(path) as db:
        (row,) = await (await db.execute(
            "SELECT ticker, prediction_price, quote_checked, prediction_yes_bid FROM markets"
        )).fetchall()
    assert tuple(row) == ("KX-OLD-A", 0.05, 0, None)


async def test_scoring_captures_the_closing_quote(db):
    kalshi = FakeKalshi(series=SERIES, live=[[make_market("KXBTC-26SEP01-Q", close_ts=CLOSE)]])
    await collector.collect_markets(kalshi, db, collector.CategoryResolver(kalshi, SERIES))
    book = {"KXBTC-26SEP01-Q": [quoted(LOOKBACK, "0.0600", "0.0400", "0.0500")]}
    await collector.score_predictions(FakeKalshi(candles=book), db)
    row = await (await db.execute(
        "SELECT prediction_price, prediction_yes_bid, prediction_yes_ask, quote_checked "
        "FROM markets"
    )).fetchone()
    assert tuple(row) == (0.06, 0.04, 0.05, 1)
    assert await dbq.markets_needing_quotes(db) == []


async def test_backfill_uses_the_scored_candle_and_retries_errors(db):
    await insert_rows(db, [
        db_row("KXA-1-A", close_ts=CLOSE, prediction_status="ok", prediction_price=0.05,
               prediction_ts=LOOKBACK - DAY),
        db_row("KXB-1-A", close_ts=CLOSE, prediction_status="ok", prediction_price=0.2,
               prediction_ts=LOOKBACK),
        db_row("KXC-1-A", close_ts=CLOSE, prediction_status="ok", prediction_price=0.3,
               prediction_ts=LOOKBACK),
        db_row("KXD-1-A", close_ts=CLOSE, prediction_status="no_data"),
    ])
    kalshi = FakeKalshi(
        candles={
            # Two candles: the one matching prediction_ts must be used, not the latest
            "KXA-1-A": [quoted(LOOKBACK - DAY, bid="0.0400", ask="0.0600"),
                        quoted(LOOKBACK, bid="0.5000", ask="0.5200")],
            "KXB-1-A": [candle(LOOKBACK, "0.20")],  # no book data
        },
        failing_tickers={"KXC-1-A"},
    )
    counts = await collector.backfill_quotes(kalshi, db)
    assert counts == {"with_quote": 1, "no_quote": 1, "errors": 1}

    rows = {r[0]: tuple(r[1:]) for r in await (await db.execute(
        "SELECT ticker, prediction_yes_bid, prediction_yes_ask, quote_checked FROM markets"
    )).fetchall()}
    assert rows["KXA-1-A"] == (0.04, 0.06, 1)
    assert rows["KXB-1-A"] == (None, None, 1)
    assert rows["KXC-1-A"] == (None, None, 0)  # retried next run
    assert rows["KXD-1-A"] == (None, None, 0)  # unscored markets aren't touched
    assert [r["ticker"] for r in await dbq.markets_needing_quotes(db)] == ["KXC-1-A"]


async def test_backfill_limit(db):
    await insert_rows(db, [
        db_row(f"KX{i}-1-A", close_ts=CLOSE + i, prediction_status="ok", prediction_price=0.1,
               prediction_ts=LOOKBACK)
        for i in range(5)
    ])
    counts = await collector.backfill_quotes(FakeKalshi(), db, limit=2)
    assert sum(counts.values()) == 2
    assert len(await dbq.markets_needing_quotes(db)) == 3


class TestMidpointCheck:
    def test_premium_and_curves_on_the_tight_subset(self):
        rows = (
            # Traded at 5c, book 3c/5c: mid 4c, premium +1c
            [(f"E{i}", 0.05, i == 0, 0.03, 0.05) for i in range(50)]
            # Wide book: excluded from the comparison
            + [(f"W{i}", 0.05, False, 0.01, 0.40) for i in range(10)]
            # No book at all
            + [(f"N{i}", 0.30, True, None, None) for i in range(5)]
        )
        result = midpoint_check(rows, max_spread=0.10)

        assert (result["markets"], result["with_quotes"], result["tight_quotes"]) == (65, 60, 50)
        assert result["mean_premium"] == pytest.approx(0.01)
        assert result["premium_by_bucket"] == [
            {"lo": 0.05, "hi": 0.10, "n": 50, "mean_premium": pytest.approx(0.01)}]
        assert result["by_trade"]["n"] == result["by_mid"]["n"] == 50
        assert result["by_trade"]["longshots"]["mean_price"] == pytest.approx(0.05)
        assert result["by_mid"]["longshots"]["mean_price"] == pytest.approx(0.04)
        assert result["by_trade"]["longshots"]["rate"] == result["by_mid"]["longshots"]["rate"]

    def test_mid_moves_markets_between_buckets(self):
        # Traded at 10c but mid 9c: the trade bucket is 10-15, the mid bucket 5-10
        result = midpoint_check([("E", 0.10, False, 0.08, 0.10)], max_spread=0.10)
        assert [b["lo"] for b in result["by_trade"]["buckets"]] == [0.10]
        assert [b["lo"] for b in result["by_mid"]["buckets"]] == [0.05]

    def test_no_quotes(self):
        result = midpoint_check([("E", 0.5, True, None, None)], max_spread=0.10)
        assert result["tight_quotes"] == 0 and result["mean_premium"] is None
        assert result["by_mid"]["n"] == 0


async def test_build_calibration_includes_midpoint_check_for_traded_prices(db):
    await insert_rows(db, [
        db_row("KXA-1-A", prediction_status="ok", prediction_price=0.05, prediction_source="trade",
               prediction_yes_bid=0.02, prediction_yes_ask=0.04),
        db_row("KXB-1-A", prediction_status="ok", prediction_price=0.5, result="no",
               prediction_source="trade"),
        # Priced from the book already: excluded, it can't differ from its midpoint
        db_row("KXC-1-A", prediction_status="ok", prediction_price=0.03, prediction_source="quote",
               prediction_yes_bid=0.02, prediction_yes_ask=0.04),
    ])
    check = (await build_calibration(db))["midpoint_check"]
    assert (check["markets"], check["tight_quotes"]) == (2, 1)
    assert check["mean_premium"] == pytest.approx(0.02)


async def test_reprice_stale_trades(db):
    stale = {"prediction_status": "ok", "prediction_source": "trade", "prediction_volume": 0,
             "quote_checked": 1, "volume_at_price": 12.0}
    await insert_rows(db, [
        # Stale 2c with a tight 83/90 book: repriced to the midpoint
        db_row("KXS-1-A", prediction_price=0.02, prediction_yes_bid=0.83, prediction_yes_ask=0.90,
               **stale),
        # Stale with a wide book: no usable price
        db_row("KXW-1-A", prediction_price=0.02, prediction_yes_bid=0.01, prediction_yes_ask=0.60,
               **stale),
        # Stale, no book: no usable price
        db_row("KXN-1-A", prediction_price=0.04, **stale),
        # Traded that day: untouched
        db_row("KXT-1-A", prediction_price=0.05, prediction_yes_bid=0.30, prediction_yes_ask=0.32,
               **{**stale, "prediction_volume": 40}),
        # Stale but quotes not fetched yet: untouched until they are
        db_row("KXU-1-A", prediction_price=0.03, **{**stale, "quote_checked": 0}),
    ])
    assert await dbq.reprice_stale_trades(db, 0.10) == {
        "repriced_from_book": 1, "dropped_no_price": 2}
    rows = {r[0]: tuple(r[1:]) for r in await (await db.execute(
        "SELECT ticker, prediction_status, prediction_price, prediction_source, volume_at_price "
        "FROM markets")).fetchall()}
    assert rows["KXS-1-A"] == ("ok", pytest.approx(0.865), "quote", None)
    assert rows["KXW-1-A"] == ("no_data", None, None, None)
    assert rows["KXN-1-A"] == ("no_data", None, None, None)
    assert rows["KXT-1-A"] == ("ok", 0.05, "trade", 12.0)
    assert rows["KXU-1-A"] == ("ok", 0.03, "trade", 12.0)
    # Idempotent
    assert await dbq.reprice_stale_trades(db, 0.10) == {
        "repriced_from_book": 0, "dropped_no_price": 0}
