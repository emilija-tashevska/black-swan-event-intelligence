import pytest
from conftest import DAY, candle, load_fixture, make_market

import collector
from models import Candlestick


def candles(*specs) -> list[Candlestick]:
    return [Candlestick.model_validate(candle(ts, close)) for ts, close in specs]


def test_parse_ts():
    assert collector.parse_ts("2026-01-31T19:34:31Z") == 1769888071
    assert collector.parse_ts("2026-09-13T17:07:58.451125Z") == 1789319278
    assert collector.parse_ts(None) is None
    assert collector.parse_ts("not a date") is None


@pytest.mark.parametrize(
    ("event_ticker", "expected"),
    [("KXBTC-26FEB2717", "KXBTC"), ("KXCABOUT-29", "KXCABOUT"), ("NODASH", "NODASH")],
)
def test_series_prefix(event_ticker, expected):
    assert collector.series_prefix(event_ticker) == expected


def test_lookback_is_seven_days():
    assert collector.lookback_ts(1_000_000) == 1_000_000 - 7 * DAY


class TestPickPredictionCandle:
    def test_picks_latest_candle_closed_by_lookback(self):
        cs = candles((1000, "0.02"), (2000, "0.04"), (3000, "0.50"))
        assert collector.pick_prediction_candle(cs, as_of_ts=2500).end_period_ts == 2000

    def test_candle_ending_exactly_at_lookback_is_eligible(self):
        cs = candles((2000, "0.04"))
        assert collector.pick_prediction_candle(cs, as_of_ts=2000).end_period_ts == 2000

    def test_never_uses_a_candle_that_ends_after_lookback(self):
        # The old code took the *nearest* candle, which could be up to a day
        # after the lookback point and leak later information into the price.
        cs = candles((1000, "0.02"), (2100, "0.90"))
        assert collector.pick_prediction_candle(cs, as_of_ts=2000).end_period_ts == 1000

    def test_none_when_no_candle_before_lookback(self):
        assert collector.pick_prediction_candle(candles((5000, "0.1")), as_of_ts=2000) is None
        assert collector.pick_prediction_candle([], as_of_ts=2000) is None


def test_contracts_near_price_uses_inclusive_tolerance_on_real_trades():
    trades = load_fixture("trades_page.json")["trades"]
    prices = sorted({float(t["yes_price_dollars"]) for t in trades})
    target = prices[0]
    expected = sum(
        float(t["count_fp"]) for t in trades
        if abs(float(t["yes_price_dollars"]) - target) <= 0.02 + 1e-9
    )
    assert collector.contracts_near_price(trades, target, 0.02) == pytest.approx(expected)


def test_contracts_near_price_boundaries():
    trades = [
        {"yes_price_dollars": "0.0500", "count_fp": "10.00"},
        {"yes_price_dollars": "0.0700", "count_fp": "5.00"},   # exactly +0.02
        {"yes_price_dollars": "0.0800", "count_fp": "99.00"},  # outside
        {"yes_price_dollars": None, "count_fp": "1000.00"},    # malformed
    ]
    assert collector.contracts_near_price(trades, 0.05, 0.02) == 15.0


def test_is_historical_uses_settlement_time_against_cutoff():
    m = {"settlement_ts": "2026-07-14T00:00:00Z", "close_time": "2026-07-20T00:00:00Z"}
    cutoff = collector.parse_ts("2026-07-15T00:00:00Z")
    assert collector.is_historical(m, cutoff) is True
    assert collector.is_historical({**m, "settlement_ts": "2026-07-16T00:00:00Z"}, cutoff) is False
    assert collector.is_historical({**m, "settlement_ts": None}, cutoff) is False  # falls back
    assert collector.is_historical(m, None) is False


def test_market_to_row_from_real_payload():
    raw = load_fixture("markets_live_page.json")["markets"][0]
    row = collector.market_to_row(raw, "KXSERIES", "Sports")
    assert row["ticker"] == raw["ticker"]
    assert row["series_ticker"] == "KXSERIES" and row["category"] == "Sports"
    assert isinstance(row["volume"], float) and isinstance(row["last_price"], float)
    assert row["volume"] == float(raw["volume_fp"])


def test_market_to_row_handles_missing_optional_fields():
    raw = make_market()
    for key in ("title", "yes_sub_title", "rules_primary", "last_price_dollars", "volume_fp"):
        raw.pop(key)
    row = collector.market_to_row(raw, "KX", "")
    assert row["title"] == "" and row["last_price"] == 0.0 and row["volume"] == 0.0


class TestCategoryResolver:
    async def test_uses_series_list_for_known_prefix(self):
        from conftest import FakeKalshi

        k = FakeKalshi(series=load_fixture("series.json")["series"])
        resolver = collector.CategoryResolver(k, k.series)
        assert await resolver.resolve("KXBTC-26FEB2717") == ("KXBTC", "Crypto")
        assert await resolver.resolve("KXELITESERIENSPREAD-26SEP13HAKMFK") == (
            "KXELITESERIENSPREAD", "Sports")
        assert await resolver.resolve("KXMVESPORTSMULTIGAMEEXTENDED-S1") == (
            "KXMVESPORTSMULTIGAMEEXTENDED", "Exotics")
        assert not [c for c in k.calls if c[0] == "event"]

    async def test_falls_back_to_event_lookup_and_caches(self):
        from conftest import FakeKalshi

        k = FakeKalshi(events={"ODD-1": {"series_ticker": "KXREAL", "category": "Politics"}})
        resolver = collector.CategoryResolver(k, [])
        assert await resolver.resolve("ODD-1") == ("KXREAL", "Politics")
        assert await resolver.resolve("ODD-1") == ("KXREAL", "Politics")
        assert k.calls.count(("event", "ODD-1")) == 1

    async def test_unresolvable_event_gets_empty_category(self):
        from conftest import FakeKalshi

        resolver = collector.CategoryResolver(FakeKalshi(), [])
        assert await resolver.resolve("GONE-1") == ("GONE", "")
