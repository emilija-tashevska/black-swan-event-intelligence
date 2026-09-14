import pytest
from conftest import load_fixture

from models import Candlestick, CandlestickPrice, to_count, to_dollars


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("0.0700", 0.07), (7, 0.07), (0, 0.0), (None, None), ("", None)],
)
def test_to_dollars_accepts_dollar_strings_and_legacy_cents(raw, expected):
    assert to_dollars(raw) == expected


def test_to_count():
    assert to_count("160.00") == 160.0
    assert to_count(None) == 0.0


def test_parses_real_historical_candlestick_payload():
    raw = load_fixture("candles_historical.json")["candlesticks"][0]
    c = Candlestick.model_validate(raw)
    assert c.end_period_ts == 1769230800
    assert c.price.implied_probability() == pytest.approx(0.01)
    assert c.contracts_traded() == 1.0


def test_implied_probability_falls_back_to_mean_but_never_to_a_stale_previous_trade():
    assert CandlestickPrice(close=None, mean="0.04", previous="0.09").implied_probability() == 0.04
    # "previous" is the last trade before the period, possibly weeks old
    assert CandlestickPrice(close=None, mean=None, previous="0.09").implied_probability() is None


def test_quiet_day_uses_the_live_book_not_the_stale_last_trade():
    # Real case: KXUSGASCPI-26APR10-T320 last traded at 2c, but the book that day was 83c/90c
    c = Candlestick.model_validate({
        "end_period_ts": 1, "volume_fp": "0.00",
        "price": {"previous_dollars": "0.0200"},
        "yes_bid": {"close_dollars": "0.8300"}, "yes_ask": {"close_dollars": "0.9000"},
    })
    assert c.implied_probability(max_spread=0.10) == (pytest.approx(0.865), "quote")
    wide = c.model_copy(update={"yes_ask": c.yes_ask.model_copy(update={"close_dollars": "0.99"})})
    assert wide.implied_probability(max_spread=0.10) is None
    assert CandlestickPrice().implied_probability() is None


def test_zero_close_is_a_real_price_not_missing():
    assert CandlestickPrice(close="0.0000", previous="0.50").implied_probability() == 0.0


def test_real_live_candle_without_trades_uses_quote_midpoint():
    raw = load_fixture("candles_live_no_trades.json")["candlesticks"][0]
    c = Candlestick.model_validate(raw)
    assert c.price.implied_probability() is None
    bid, ask = float(raw["yes_bid"]["close_dollars"]), float(raw["yes_ask"]["close_dollars"])
    assert c.implied_probability(max_spread=0.10) == (pytest.approx((bid + ask) / 2), "quote")
    assert c.implied_probability(max_spread=ask - bid - 0.01) is None


@pytest.mark.parametrize(
    ("price", "bid", "ask", "expected"),
    [
        ({"close": "0.0400"}, "0.0100", "0.0900", (0.04, "trade")),   # trades win over quotes
        ({}, "0.0200", "0.1200", (0.07, "quote")),                    # spread exactly at max
        ({}, "0.0000", "1.0000", None),                               # empty book
        ({}, "0.3000", "0.2000", None),                               # crossed/invalid
        ({}, None, "0.0500", None),                                   # one-sided
    ],
)
def test_implied_probability_source_selection(price, bid, ask, expected):
    raw = {"end_period_ts": 1, "price": price}
    if bid is not None:
        raw["yes_bid"] = {"close_dollars": bid}
    raw["yes_ask"] = {"close_dollars": ask}
    result = Candlestick.model_validate(raw).implied_probability(max_spread=0.10)
    if expected is None:
        assert result is None
    else:
        assert result == (pytest.approx(expected[0]), expected[1])
