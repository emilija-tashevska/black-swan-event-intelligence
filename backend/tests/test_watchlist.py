from datetime import UTC, datetime, timedelta

import pytest
from conftest import FakeKalshi, db_row, insert_rows, iso, load_fixture

import collector
import database as dbq
import watchlist
from calibration import summarize

SERIES = load_fixture("series.json")["series"]
NOW = datetime(2026, 9, 13, tzinfo=UTC)


def open_market(ticker, bid="0.0400", ask="0.0600", last="0.0500", volume="5000.00", **kw):
    return {
        "ticker": ticker,
        "event_ticker": ticker.rsplit("-", 1)[0],
        "title": f"Will {ticker} happen?",
        "yes_sub_title": "Yes",
        "rules_primary": "Rules.",
        "close_time": iso(int((NOW + timedelta(days=7)).timestamp())),
        "yes_bid_dollars": bid,
        "yes_ask_dollars": ask,
        "last_price_dollars": last,
        "volume_fp": volume,
        **kw,
    }


@pytest.mark.parametrize(
    ("bid", "ask", "last", "expected"),
    [
        ("0.0400", "0.0600", "0.2000", (0.05, "quote")),      # tight book beats stale last trade
        ("0.0200", "0.1200", "0.0300", (0.07, "quote")),      # exactly 10c spread
        ("0.0100", "0.5000", "0.0300", (0.03, "last_trade")),  # wide book
        ("0.0000", "0.0000", "0.0300", (0.03, "last_trade")),  # empty book
        (None, None, "0.0000", None),                           # never traded
    ],
)
def test_current_price(bid, ask, last, expected):
    result = watchlist.current_price(
        {"yes_bid_dollars": bid, "yes_ask_dollars": ask, "last_price_dollars": last})
    if expected is None:
        assert result is None
    else:
        assert result == (pytest.approx(expected[0]), expected[1])


async def test_collect_open_markets_filters_and_replaces_snapshot(db):
    kalshi = FakeKalshi(series=SERIES, open_pages=[[
        open_market("KXBTC-26SEP20-CHEAP"),
        open_market("KXBTC-26SEP20-THIN", volume="10.00"),
        open_market("KXBTC-26SEP20-PRICEY", bid="0.4000", ask="0.4400"),
        open_market("KXELITESERIENSPREAD-26SEP20-X"),
        open_market("KXCABOUT-29-ZZ", bid=None, ask=None, last="0.0800"),
    ]])
    resolver = collector.CategoryResolver(kalshi, SERIES)
    assert await watchlist.collect_open_markets(kalshi, db, resolver, now=NOW) == 2

    lo, hi = kalshi.calls[0][1:]
    assert lo == int((NOW + timedelta(days=4)).timestamp())
    assert hi == int((NOW + timedelta(days=10)).timestamp())
    rows = {r["ticker"]: r for r in await dbq.query_open_markets(db)}
    assert set(rows) == {"KXBTC-26SEP20-CHEAP", "KXCABOUT-29-ZZ"}
    assert rows["KXBTC-26SEP20-CHEAP"]["category"] == "Crypto"
    assert rows["KXCABOUT-29-ZZ"]["price_source"] == "last_trade"

    # A later run replaces the snapshot instead of accumulating closed markets
    await watchlist.collect_open_markets(FakeKalshi(series=SERIES), db, resolver, now=NOW)
    assert await dbq.query_open_markets(db) == []


def history(category, structure, price, n, yes, per_event=1):
    return [(category, structure, f"{category}{structure}{i // per_event}", price, i < yes)
            for i in range(n)]


def test_base_rate_prefers_the_most_specific_group_with_enough_history():
    cal = summarize(
        history("Crypto", "ladder", 0.06, 150, 20)
        + history("Politics", "standalone", 0.06, 200, 5)
        + history("Politics", "pick_one", 0.06, 120, 5)
    )
    b = watchlist.base_rate(cal, "Crypto", 0.07, "ladder")
    assert b["scope"] == "Crypto · ladder" and b["n"] == 150

    # No Crypto × pick_one segment: fall back to pick_one across categories
    b = watchlist.base_rate(cal, "Crypto", 0.07, "pick_one")
    assert b["scope"] == "All categories · pick_one" and b["n"] == 120

    # Unknown structure: category, then everything
    assert watchlist.base_rate(cal, "Politics", 0.08)["scope"] == "Politics"
    b = watchlist.base_rate(cal, "Weather", 0.05, "bundle")
    assert b["scope"] == "All markets" and b["n"] == 470
    assert watchlist.base_rate(cal, "Crypto", 0.50, "ladder") is None  # nothing priced there


def test_base_rate_needs_enough_markets_and_events():
    few_markets = summarize(history("Crypto", "ladder", 0.06, 20, 10))
    assert watchlist.base_rate(few_markets, "Crypto", 0.06, "ladder") is None
    # 200 markets but only 5 events: not enough independent history
    few_events = summarize(history("Crypto", "ladder", 0.06, 200, 10, per_event=40))
    assert watchlist.base_rate(few_events, "Crypto", 0.06, "ladder") is None


@pytest.mark.parametrize(
    ("mean_price", "ci", "expected"),
    [
        (0.05, (0.08, 0.15), "happens_more_often"),
        (0.20, (0.08, 0.15), "happens_less_often"),
        (0.10, (0.08, 0.15), "in_line"),
        (0.08, (0.08, 0.15), "in_line"),  # touching the interval is not a signal
    ],
)
def test_assess_judges_the_group_against_its_own_average_price(mean_price, ci, expected):
    group = {"mean_price": mean_price, "ci_low": ci[0], "ci_high": ci[1]}
    assert watchlist.assess(group) == expected
    assert watchlist.assess(None) == "insufficient_history"


async def test_market_at_bucket_edge_is_not_flagged_when_group_is_fair(db):
    # 20-30% bucket averaging 25% that resolved YES 25% of the time: fairly priced.
    history = [
        db_row(f"KXBTC-H{i}-A", "Crypto", prediction_status="ok", prediction_price=0.25,
               result="yes" if i % 4 == 0 else "no")
        for i in range(400)
    ]
    await insert_rows(db, history)
    kalshi = FakeKalshi(series=SERIES, open_pages=[[open_market("KXBTC-26SEP20-EDGE",
                                                              bid="0.1900", ask="0.2100")]])
    await watchlist.collect_open_markets(
        kalshi, db, collector.CategoryResolver(kalshi, SERIES), now=NOW)
    (market,) = (await watchlist.build_watchlist(db))["markets"]
    assert market["price"] == pytest.approx(0.20)
    # The bucket's interval (~21-29%) excludes 20%, but the group itself is fair
    assert market["base_rate"]["ci_low"] > 0.20
    assert market["assessment"] == "in_line"


async def test_build_watchlist_end_to_end(db):
    history = [
        db_row(f"KXBTC-H{i}-A", "Crypto", prediction_status="ok", prediction_price=0.06,
               result="yes" if i < 30 else "no")
        for i in range(150)
    ]
    await insert_rows(db, history)
    kalshi = FakeKalshi(series=SERIES, open_pages=[[
        open_market("KXBTC-26SEP20-A"),
        open_market("KXCABOUT-29-B", bid="0.1600", ask="0.2000"),
    ]])
    await watchlist.collect_open_markets(
        kalshi, db, collector.CategoryResolver(kalshi, SERIES), now=NOW)

    result = await watchlist.build_watchlist(db)
    assert result["fetched_at"].startswith("2026-09-13")
    first, second = result["markets"]
    assert first["ticker"] == "KXBTC-26SEP20-A"
    assert first["assessment"] == "happens_more_often"  # group priced 6%, happened 20%
    assert first["base_rate"]["scope"] == "Crypto" and first["base_rate"]["n"] == 150
    assert first["structure"] == "unknown"
    assert second["assessment"] == "insufficient_history"
