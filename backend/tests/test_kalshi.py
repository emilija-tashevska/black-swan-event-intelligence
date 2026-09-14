from datetime import UTC, datetime

import httpx
import pytest
import respx
from conftest import load_fixture

from kalshi import BASE_URL, KalshiClient, KalshiError


def client() -> KalshiClient:
    return KalshiClient(rate_limit_delay=0, retry_backoff=0)


@respx.mock(base_url=BASE_URL)
async def test_paginate_follows_cursor_until_exhausted(respx_mock):
    route = respx_mock.get("/markets").mock(side_effect=[
        httpx.Response(200, json={"markets": [{"ticker": "A"}], "cursor": "c1"}),
        httpx.Response(200, json={"markets": [{"ticker": "B"}], "cursor": "c2"}),
        httpx.Response(200, json={"markets": [{"ticker": "C"}], "cursor": ""}),
    ])
    async with client() as k:
        pages = [p async for p in k.settled_markets(min_settled_ts=123)]

    assert [m["ticker"] for p, _ in pages for m in p] == ["A", "B", "C"]
    assert [c for _, c in pages] == ["c1", "c2", None]
    assert route.call_count == 3
    first, second = route.calls[0].request.url.params, route.calls[1].request.url.params
    assert first["status"] == "settled" and first["min_settled_ts"] == "123"
    assert "cursor" not in first and second["cursor"] == "c1"


@respx.mock(base_url=BASE_URL)
async def test_short_page_with_cursor_is_not_treated_as_the_end(respx_mock):
    # The old client stopped when a page had fewer items than `limit`,
    # silently truncating results.
    respx_mock.get("/markets/trades").mock(side_effect=[
        httpx.Response(200, json={"trades": [{"count_fp": "1"}], "cursor": "next"}),
        httpx.Response(200, json={"trades": [{"count_fp": "2"}], "cursor": ""}),
    ])
    async with client() as k:
        trades = await k.get_trades("T", 0, 10, historical=False)
    assert len(trades) == 2


@respx.mock(base_url=BASE_URL)
async def test_empty_page_with_cursor_stops(respx_mock):
    respx_mock.get("/historical/markets").mock(
        return_value=httpx.Response(200, json={"markets": [], "cursor": "loop"})
    )
    async with client() as k:
        assert [p async for p in k.historical_markets(0)] == [([], None)]


@respx.mock(base_url=BASE_URL)
async def test_retries_rate_limits_and_server_errors(respx_mock):
    route = respx_mock.get("/historical/cutoff").mock(side_effect=[
        httpx.Response(429),
        httpx.Response(503),
        httpx.Response(200, json={"market_settled_ts": "2026-07-15T00:00:00Z"}),
    ])
    async with client() as k:
        assert await k.get_cutoff_ts() == "2026-07-15T00:00:00Z"
    assert route.call_count == 3


@respx.mock(base_url=BASE_URL)
async def test_raises_after_exhausting_retries_instead_of_returning_empty(respx_mock):
    respx_mock.get("/series").mock(return_value=httpx.Response(500))
    async with client() as k:
        with pytest.raises(KalshiError):
            await k.get_all_series()


@respx.mock(base_url=BASE_URL)
async def test_client_errors_are_not_retried(respx_mock):
    route = respx_mock.get("/events/NOPE").mock(return_value=httpx.Response(404))
    async with client() as k:
        with pytest.raises(httpx.HTTPStatusError):
            await k.get_event("NOPE")
    assert route.call_count == 1


@respx.mock(base_url=BASE_URL)
async def test_candlestick_endpoints(respx_mock):
    payload = load_fixture("candles_historical.json")
    hist = respx_mock.get("/historical/markets/T1/candlesticks").mock(
        return_value=httpx.Response(200, json=payload))
    live = respx_mock.get("/series/KXS/markets/T1/candlesticks").mock(
        return_value=httpx.Response(200, json=payload))
    async with client() as k:
        h = await k.get_candlesticks("T1", 100, 200, historical=True)
        lv = await k.get_candlesticks("T1", 100, 200, historical=False, series_ticker="KXS")
        with pytest.raises(ValueError):
            await k.get_candlesticks("T1", 100, 200, historical=False)

    assert h[0].end_period_ts == lv[0].end_period_ts == 1769230800
    params = hist.calls[0].request.url.params
    assert params["start_ts"] == "100" and params["end_ts"] == "200"
    assert params["period_interval"] == "1440"
    assert live.called


@respx.mock(base_url=BASE_URL)
async def test_get_event_unwraps_event(respx_mock):
    respx_mock.get("/events/KXBTC-26FEB2717").mock(
        return_value=httpx.Response(200, json=load_fixture("event.json")))
    async with client() as k:
        event = await k.get_event("KXBTC-26FEB2717")
    assert event["series_ticker"] == "KXBTC"
    assert event["category"] == "Crypto"


def settled(ticker, iso):
    return {"ticker": ticker, "settlement_ts": iso}


@respx.mock(base_url=BASE_URL)
async def test_historical_markets_filters_client_side_and_stops_past_the_window(respx_mock):
    # The archive ignores min_settled_ts, so the client must filter and stop itself.
    route = respx_mock.get("/historical/markets").mock(side_effect=[
        httpx.Response(200, json={"cursor": "c1", "markets": [
            settled("NEW", "2026-07-14T23:00:00Z"), settled("OLD", "2026-07-01T00:00:00Z"),
        ]}),
        httpx.Response(200, json={"cursor": "c2", "markets": [
            settled("EDGE", "2026-07-10T00:00:00Z"),        # after window start
            settled("SLACK", "2026-07-09T12:00:00Z"),       # before start, within slack
        ]}),
        httpx.Response(200, json={"cursor": "c3", "markets": [
            settled("GONE", "2026-07-08T00:00:00Z"),        # whole page older than slack
        ]}),
        httpx.Response(200, json={"cursor": "", "markets": [
            settled("NEVER", "2026-07-14T00:00:00Z"),
        ]}),
    ])
    window_start = int(datetime(2026, 7, 10, tzinfo=UTC).timestamp())
    async with client() as k:
        pages = [p async for p in k.historical_markets(window_start)]

    assert [([m["ticker"] for m in p], c) for p, c in pages] == [
        (["NEW"], "c1"), (["EDGE"], "c2"), ([], None)]
    assert route.call_count == 3
    assert "min_settled_ts" not in route.calls[0].request.url.params


@respx.mock(base_url=BASE_URL)
async def test_open_markets_filters_by_close_window(respx_mock):
    route = respx_mock.get("/markets").mock(
        return_value=httpx.Response(200, json={"markets": [{"ticker": "O"}], "cursor": ""}))
    async with client() as k:
        pages = [p async for p in k.open_markets(100, 200)]
    assert pages == [[{"ticker": "O"}]]
    params = route.calls[0].request.url.params
    assert params["status"] == "open" and params["mve_filter"] == "exclude"
    assert (params["min_close_ts"], params["max_close_ts"]) == ("100", "200")


@respx.mock(base_url=BASE_URL)
async def test_settled_markets_resumes_from_cursor(respx_mock):
    route = respx_mock.get("/markets").mock(
        return_value=httpx.Response(200, json={"markets": [{"ticker": "Z"}], "cursor": ""}))
    async with client() as k:
        pages = [p async for p in k.settled_markets(1, cursor="saved")]
    assert pages == [([{"ticker": "Z"}], None)]
    assert route.calls[0].request.url.params["cursor"] == "saved"


@respx.mock(base_url=BASE_URL)
async def test_backoff_is_exponential_capped_and_honours_retry_after(respx_mock, monkeypatch):
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr("kalshi.asyncio.sleep", fake_sleep)
    respx_mock.get("/historical/cutoff").mock(side_effect=[
        httpx.Response(503), httpx.Response(503), httpx.Response(429, headers={"Retry-After": "7"}),
        httpx.Response(503), httpx.Response(503), httpx.Response(503), httpx.Response(503),
        httpx.Response(200, json={"market_settled_ts": "x"}),
    ])
    async with KalshiClient(rate_limit_delay=0, retry_backoff=2.0) as k:
        assert await k.get_cutoff_ts() == "x"
    assert sleeps == [2.0, 4.0, 7.0, 16.0, 32.0, 60.0, 60.0]
