"""End-to-end pipeline behaviour against a fake Kalshi and a real SQLite file."""

from datetime import UTC, datetime, timedelta

import pytest
from conftest import DAY, FakeKalshi, candle, iso, load_fixture, make_market

import collector
import database as dbq

SERIES = load_fixture("series.json")["series"]
NOW = datetime(2026, 9, 13, tzinfo=UTC)


async def collect(db, kalshi, now=NOW):
    resolver = collector.CategoryResolver(kalshi, kalshi.series)
    return await collector.collect_markets(kalshi, db, resolver, now=now)


async def all_tickers(db):
    cur = await db.execute("SELECT ticker FROM markets ORDER BY 1")
    return [r[0] for r in await cur.fetchall()]


class TestCollect:
    async def test_keeps_liquid_in_scope_markets_from_both_sources(self, db):
        kalshi = FakeKalshi(
            series=SERIES,
            live=[[
                make_market("KXBTC-26SEP01-A"),
                make_market("KXBTC-26SEP01-THIN", volume_fp="999.99"),
                make_market("KXELITESERIENSPREAD-26SEP13-X"),
            ]],
            historical=[[
                make_market("KXCABOUT-29-SM"),
                make_market("KXMVESPORTSMULTIGAMEEXTENDED-S1-Y"),
            ]],
        )
        result = await collect(db, kalshi)

        assert await all_tickers(db) == ["KXBTC-26SEP01-A", "KXCABOUT-29-SM"]
        assert result.scanned == 5 and result.stored == 2 and result.skipped_thin == 1
        assert result.skipped_category == {"Sports": 1, "Exotics": 1}
        cats = dict(await (await db.execute("SELECT ticker, category FROM markets")).fetchall())
        assert cats == {"KXBTC-26SEP01-A": "Crypto", "KXCABOUT-29-SM": "Politics"}

    async def test_first_run_uses_window_then_incremental(self, db, monkeypatch):
        monkeypatch.setattr("config.COLLECTION_WINDOW_DAYS", 180)
        kalshi = FakeKalshi(series=SERIES)
        await collect(db, kalshi, now=NOW)
        first_min = kalshi.calls[0][1]
        assert first_min == int((NOW - timedelta(days=180)).timestamp())

        later = NOW + timedelta(days=2)
        kalshi2 = FakeKalshi(series=SERIES)
        await collect(db, kalshi2, now=later)
        assert kalshi2.calls[0] == ("live", int(NOW.timestamp()), None)
        assert await dbq.get_meta(db, "last_collection_ts") == str(int(later.timestamp()))

    async def test_interrupted_collection_resumes_from_saved_cursor(self, db):
        pages = [[make_market(f"KXBTC-26SEP01-P{i}")] for i in range(4)]
        crashing = FakeKalshi(series=SERIES, live=pages, fail_at=("live", 2))
        with pytest.raises(RuntimeError, match="page 2"):
            await collect(db, crashing, now=NOW)
        assert await all_tickers(db) == ["KXBTC-26SEP01-P0", "KXBTC-26SEP01-P1"]
        assert await dbq.get_meta(db, "last_collection_ts") is None  # not marked complete

        # Resumed later: same window, continues at page 2, no rescanning
        resumed = FakeKalshi(series=SERIES, live=pages)
        result = await collect(db, resumed, now=NOW + timedelta(hours=3))
        window = int((NOW - timedelta(days=180)).timestamp())
        assert resumed.calls[0] == ("live", window, "live2")
        assert result.scanned == 2
        assert len(await all_tickers(db)) == 4
        # The next incremental run starts from when the *interrupted* run began
        assert await dbq.get_meta(db, "last_collection_ts") == str(int(NOW.timestamp()))
        assert await dbq.get_meta(db, "collect:live:cursor") is None

    async def test_resume_skips_sources_already_finished(self, db):
        crashing = FakeKalshi(series=SERIES, live=[[make_market("KXBTC-26SEP01-L")]],
                              historical=[[make_market("KXBTC-26JUL01-H0")],
                                          [make_market("KXBTC-26JUL01-H1")]],
                              fail_at=("historical", 1))
        with pytest.raises(RuntimeError):
            await collect(db, crashing, now=NOW)
        resumed = FakeKalshi(series=SERIES, historical=crashing.historical_pages)
        await collect(db, resumed, now=NOW)
        assert [c[0] for c in resumed.calls] == ["historical"]
        assert resumed.calls[0][2] == "historical1"
        assert len(await all_tickers(db)) == 3

    async def test_skips_archive_when_window_starts_after_cutoff(self, db):
        kalshi = FakeKalshi(series=SERIES, cutoff_ts="2026-07-15T00:00:00Z",
                            historical=[[make_market("KXBTC-26JUL01-OLD")]])
        await collect(db, kalshi, now=NOW)  # first run: window reaches before the cutoff
        assert ("historical", int((NOW - timedelta(days=180)).timestamp()), None) in kalshi.calls

        kalshi2 = FakeKalshi(series=SERIES, cutoff_ts="2026-07-15T00:00:00Z",
                             historical=[[make_market("KXBTC-26JUL01-OLD2")]])
        await collect(db, kalshi2, now=NOW + timedelta(days=1))
        assert [c[0] for c in kalshi2.calls] == ["live"]
        assert "KXBTC-26JUL01-OLD2" not in await all_tickers(db)

    async def test_recollecting_updates_settlement_fields_without_duplicates(self, db):
        m = make_market("KXBTC-26SEP01-A")
        await collect(db, FakeKalshi(series=SERIES, live=[[m]]))
        await collect(db, FakeKalshi(series=SERIES, historical=[[{**m, "volume_fp": "8000.00"}]]))
        rows = await (await db.execute("SELECT ticker, volume FROM markets")).fetchall()
        assert [tuple(r) for r in rows] == [("KXBTC-26SEP01-A", 8000.0)]


CLOSE = 1_780_000_000
LOOKBACK = CLOSE - 7 * DAY


async def seed_for_scoring(db, *markets):
    kalshi = FakeKalshi(series=SERIES, live=[list(markets)])
    await collect(db, kalshi)


async def status_of(db):
    rows = await (await db.execute(
        "SELECT ticker, prediction_status, prediction_price, prediction_ts, prediction_volume "
        "FROM markets ORDER BY ticker")).fetchall()
    return {r[0]: tuple(r[1:]) for r in rows}


class TestScore:
    async def test_scores_long_lived_resolved_markets_from_the_seven_day_candle(self, db):
        await seed_for_scoring(
            db,
            make_market("KXBTC-26SEP01-SWAN", close_ts=CLOSE),
            make_market("KXBTC-26SEP01-FAV", close_ts=CLOSE),
            make_market("KXBTC-26SEP01-NO", close_ts=CLOSE, result="no"),
        )
        kalshi = FakeKalshi(candles={
            "KXBTC-26SEP01-SWAN": [candle(LOOKBACK - DAY, "0.0300", volume="250.00"),
                                   candle(LOOKBACK + DAY, "0.9900")],
            "KXBTC-26SEP01-FAV": [candle(LOOKBACK, "0.8000")],
            "KXBTC-26SEP01-NO": [candle(LOOKBACK, "0.0200")],
        })
        counts = await collector.score_predictions(kalshi, db)

        status = await status_of(db)
        assert status["KXBTC-26SEP01-SWAN"] == ("ok", 0.03, LOOKBACK - DAY, 250.0)
        assert status["KXBTC-26SEP01-FAV"][:2] == ("ok", 0.8)
        # NO markets are scored (for calibration) but a cheap NO is not a black swan
        assert status["KXBTC-26SEP01-NO"][:2] == ("ok", 0.02)
        assert counts["ok"] == 3 and counts["black_swans"] == 1
        assert [r["ticker"] for r in await dbq.query_black_swans(db, 0.10)] == [
            "KXBTC-26SEP01-SWAN"]

        candle_call = next(c for c in kalshi.calls if c[1] == "KXBTC-26SEP01-SWAN")
        assert candle_call[3] == LOOKBACK  # request window never extends past the lookback

    async def test_falls_back_to_tight_quotes_when_nothing_traded(self, db):
        await seed_for_scoring(
            db,
            make_market("KXBTC-26SEP01-QUOTED", close_ts=CLOSE),
            make_market("KXBTC-26SEP01-WIDE", close_ts=CLOSE),
        )
        no_trades = {"price": {}, "volume_fp": "0.00"}
        kalshi = FakeKalshi(candles={
            "KXBTC-26SEP01-QUOTED": [{**no_trades, "end_period_ts": LOOKBACK,
                                      "yes_bid": {"close_dollars": "0.0000"},
                                      "yes_ask": {"close_dollars": "0.0600"}}],
            "KXBTC-26SEP01-WIDE": [{**no_trades, "end_period_ts": LOOKBACK,
                                    "yes_bid": {"close_dollars": "0.1500"},
                                    "yes_ask": {"close_dollars": "0.9000"}}],
        })
        counts = await collector.score_predictions(kalshi, db)

        rows = await (await db.execute(
            "SELECT ticker, prediction_status, prediction_price, prediction_source "
            "FROM markets ORDER BY ticker")).fetchall()
        assert [tuple(r) for r in rows] == [
            ("KXBTC-26SEP01-QUOTED", "ok", pytest.approx(0.03), "quote"),
            ("KXBTC-26SEP01-WIDE", "no_data", None, None),
        ]
        assert counts["from_quotes"] == 1

    async def test_short_lived_markets_are_excluded_not_scored_on_last_price(self, db):
        await seed_for_scoring(
            db,
            make_market("KXBTC-26SEP01-HOURLY", close_ts=CLOSE, duration_days=0.04,
                        last_price_dollars="0.0100"),
            make_market("KXBTC-26SEP01-6D", close_ts=CLOSE, duration_days=6.9),
            # Open exactly 7 days: the lookback point is the open, so no candle precedes it
            make_market("KXBTC-26SEP01-7D", close_ts=CLOSE, duration_days=7),
            make_market("KXBTC-26SEP01-8D", close_ts=CLOSE, duration_days=8),
        )
        kalshi = FakeKalshi(candles={"KXBTC-26SEP01-8D": [candle(LOOKBACK, "0.05")]})
        counts = await collector.score_predictions(kalshi, db)

        status = await status_of(db)
        assert status["KXBTC-26SEP01-HOURLY"][0] == "short_lived"
        assert status["KXBTC-26SEP01-HOURLY"][1] is None
        assert status["KXBTC-26SEP01-6D"][0] == "short_lived"
        assert status["KXBTC-26SEP01-7D"][0] == "short_lived"
        assert status["KXBTC-26SEP01-8D"][:2] == ("ok", 0.05)
        assert counts["short_lived"] == 3
        assert not [c for c in kalshi.calls if c[0] == "candles" and "HOURLY" in c[1]]

    async def test_no_candles_is_final_but_transient_errors_are_retried(self, db):
        await seed_for_scoring(
            db,
            make_market("KXBTC-26SEP01-EMPTY", close_ts=CLOSE),
            make_market("KXBTC-26SEP01-FLAKY", close_ts=CLOSE),
        )
        counts = await collector.score_predictions(
            FakeKalshi(failing_tickers={"KXBTC-26SEP01-FLAKY"}), db)
        status = await status_of(db)
        assert status["KXBTC-26SEP01-EMPTY"][0] == "no_data"
        assert status["KXBTC-26SEP01-FLAKY"][0] is None
        assert counts["errors"] == 1

        retry = FakeKalshi(candles={"KXBTC-26SEP01-FLAKY": [candle(LOOKBACK, "0.02")]})
        await collector.score_predictions(retry, db)
        assert (await status_of(db))["KXBTC-26SEP01-FLAKY"][:2] == ("ok", 0.02)
        assert [c[1] for c in retry.calls if c[0] == "candles"] == ["KXBTC-26SEP01-FLAKY"]

    async def test_routes_archived_markets_to_historical_endpoint(self, db):
        cutoff = CLOSE  # settlement is CLOSE + 1h, so this market is live
        await seed_for_scoring(
            db,
            make_market("KXBTC-26SEP01-LIVE", close_ts=CLOSE),
            make_market("KXBTC-26SEP01-OLD", close_ts=CLOSE - 30 * DAY),
        )
        kalshi = FakeKalshi(cutoff_ts=iso(cutoff))
        await collector.score_predictions(kalshi, db)
        routed = {c[1]: c[4] for c in kalshi.calls if c[0] == "candles"}
        assert routed == {"KXBTC-26SEP01-LIVE": False, "KXBTC-26SEP01-OLD": True}


class TestDepth:
    async def test_counts_trades_near_price_in_the_prediction_day(self, db):
        await seed_for_scoring(
            db,
            make_market("KXBTC-26SEP01-SWAN", close_ts=CLOSE),
            make_market("KXBTC-26SEP01-FAV", close_ts=CLOSE),
        )
        await collector.score_predictions(FakeKalshi(candles={
            "KXBTC-26SEP01-SWAN": [candle(LOOKBACK, "0.05")],
            "KXBTC-26SEP01-FAV": [candle(LOOKBACK, "0.60")],
        }), db)

        kalshi = FakeKalshi(trades={"KXBTC-26SEP01-SWAN": [
            {"yes_price_dollars": "0.0400", "count_fp": "30.00"},
            {"yes_price_dollars": "0.2000", "count_fp": "500.00"},
        ]})
        assert await collector.enrich_depth(kalshi, db) == 1

        (depth,) = await (await db.execute(
            "SELECT volume_at_price FROM markets WHERE ticker = 'KXBTC-26SEP01-SWAN'")).fetchone()
        assert depth == 30.0
        trade_call = next(c for c in kalshi.calls if c[0] == "trades")
        assert (trade_call[2], trade_call[3]) == (LOOKBACK - DAY, LOOKBACK)
        # Enriched markets are not fetched again
        assert await collector.enrich_depth(FakeKalshi(), db) == 0


@pytest.mark.parametrize("close", [None, "garbage"])
async def test_score_market_without_close_time_is_no_data(close):
    m = {"ticker": "T", "close_time": close, "settlement_ts": None, "series_ticker": "KX"}
    assert await collector.score_market(FakeKalshi(), m, None) == collector.NO_DATA
