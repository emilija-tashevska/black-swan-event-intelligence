"""Async client for Kalshi's public (unauthenticated) trade API."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import httpx

from models import Candlestick

logger = logging.getLogger(__name__)

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
DEFAULT_LIMIT = 1000
MAX_RETRIES = 8
RETRY_BACKOFF = 2.0  # doubles each attempt
MAX_BACKOFF = 60.0
RATE_LIMIT_DELAY = 0.15  # seconds between requests
DAILY = 1440  # candlestick period in minutes
HISTORICAL_ORDER_SLACK = 86_400  # archive pages overlap in settlement time


class KalshiError(RuntimeError):
    pass


def _retry_after(resp: httpx.Response) -> float | None:
    value = resp.headers.get("retry-after", "")
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


def _settled_ts(market: dict) -> int | None:
    iso = market.get("settlement_ts") or market.get("close_time")
    if not iso:
        return None
    try:
        return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


class KalshiClient:
    def __init__(
        self,
        base_url: str = BASE_URL,
        rate_limit_delay: float = RATE_LIMIT_DELAY,
        retry_backoff: float = RETRY_BACKOFF,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._rate_limit_delay = rate_limit_delay
        self._retry_backoff = retry_backoff
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> KalshiClient:
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=30.0,
            headers={"Accept": "application/json"},
        )
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._client:
            await self._client.aclose()

    async def _get(self, path: str, params: dict | None = None) -> dict:
        """GET with retries on 429, 5xx and network errors, backing off
        exponentially (or as long as Retry-After asks). Other 4xx raise
        immediately; exhausting retries raises rather than returning an empty
        payload that would silently drop data."""
        assert self._client is not None, "use KalshiClient as an async context manager"
        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES):
            if self._rate_limit_delay:
                await asyncio.sleep(self._rate_limit_delay)
            wait = min(self._retry_backoff * 2**attempt, MAX_BACKOFF)
            try:
                resp = await self._client.get(path, params=params)
            except httpx.RequestError as e:
                last_error = e
                logger.warning("Request error on %s: %s (attempt %d)", path, e, attempt + 1)
            else:
                if resp.status_code != 429 and resp.status_code < 500:
                    resp.raise_for_status()
                    return resp.json()
                last_error = KalshiError(f"HTTP {resp.status_code} on {path}")
                retry_after = _retry_after(resp)
                if retry_after is not None:
                    wait = min(retry_after, MAX_BACKOFF)
                logger.warning("%s; retrying in %.0fs (attempt %d)", last_error, wait, attempt + 1)
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(wait)
        raise KalshiError(f"Giving up on {path} after {MAX_RETRIES} attempts") from last_error

    async def paginate_with_cursor(
        self, path: str, key: str, params: dict | None = None,
        cursor: str | None = None, limit: int = DEFAULT_LIMIT,
    ) -> AsyncIterator[tuple[list[dict], str | None]]:
        """Yield (page, cursor for the next page). Pass a saved cursor to resume."""
        params = {**(params or {}), "limit": limit}
        if cursor:
            params["cursor"] = cursor
        while True:
            data = await self._get(path, params)
            items = data.get(key, [])
            next_cursor = data.get("cursor") or None
            if not items:
                next_cursor = None
            yield items, next_cursor
            if not next_cursor:
                return
            params["cursor"] = next_cursor

    async def paginate(
        self, path: str, key: str, params: dict | None = None, limit: int = DEFAULT_LIMIT,
    ) -> AsyncIterator[list[dict]]:
        """Yield non-empty pages until the API stops returning a cursor."""
        async for items, _ in self.paginate_with_cursor(path, key, params, limit=limit):
            if items:
                yield items

    async def _collect(self, path: str, key: str, params: dict) -> list[dict]:
        out: list[dict] = []
        async for page in self.paginate(path, key, params):
            out.extend(page)
        return out

    # ── Reference data ──

    async def get_cutoff_ts(self) -> str | None:
        """ISO timestamp before which settled markets live under /historical."""
        data = await self._get("/historical/cutoff")
        return data.get("market_settled_ts")

    async def get_all_series(self) -> list[dict]:
        data = await self._get("/series")
        return data.get("series", [])

    async def get_event(self, event_ticker: str) -> dict:
        data = await self._get(f"/events/{event_ticker}")
        return data.get("event", data)

    # ── Markets ──

    def settled_markets(
        self, min_settled_ts: int, cursor: str | None = None,
    ) -> AsyncIterator[tuple[list[dict], str | None]]:
        return self.paginate_with_cursor(
            "/markets", "markets",
            {"status": "settled", "mve_filter": "exclude", "min_settled_ts": min_settled_ts},
            cursor=cursor,
        )

    def open_markets(self, min_close_ts: int, max_close_ts: int) -> AsyncIterator[list[dict]]:
        return self.paginate(
            "/markets", "markets",
            {"status": "open", "mve_filter": "exclude",
             "min_close_ts": min_close_ts, "max_close_ts": max_close_ts},
        )

    async def historical_markets(
        self, min_settled_ts: int, cursor: str | None = None,
    ) -> AsyncIterator[tuple[list[dict], str | None]]:
        """The archive endpoint ignores time filters, but returns markets roughly
        newest-settled first. Filter each page client-side and stop once a whole
        page (plus a safety margin for out-of-order pages) predates the window."""
        stop_before = min_settled_ts - HISTORICAL_ORDER_SLACK
        pages = self.paginate_with_cursor(
            "/historical/markets", "markets", {"mve_filter": "exclude"}, cursor=cursor,
        )
        async for page, next_cursor in pages:
            settled = [(m, _settled_ts(m)) for m in page]
            newest = max((ts for _, ts in settled if ts is not None), default=None)
            finished = newest is not None and newest < stop_before
            in_window = [m for m, ts in settled if ts is None or ts >= min_settled_ts]
            yield in_window, None if finished else next_cursor
            if finished:
                return

    async def markets_for_event(self, event_ticker: str, *, historical: bool) -> list[dict]:
        path = "/historical/markets" if historical else "/markets"
        return await self._collect(path, "markets", {"event_ticker": event_ticker})

    # ── Candlesticks ──

    async def get_candlesticks(
        self,
        ticker: str,
        start_ts: int,
        end_ts: int,
        *,
        historical: bool,
        series_ticker: str | None = None,
    ) -> list[Candlestick]:
        params = {"start_ts": start_ts, "end_ts": end_ts, "period_interval": DAILY}
        if historical:
            path = f"/historical/markets/{ticker}/candlesticks"
        else:
            if not series_ticker:
                raise ValueError("live candlesticks require series_ticker")
            path = f"/series/{series_ticker}/markets/{ticker}/candlesticks"
        data = await self._get(path, params)
        return [Candlestick.model_validate(c) for c in data.get("candlesticks", [])]

    # ── Trades ──

    async def get_trades(
        self, ticker: str, min_ts: int, max_ts: int, *, historical: bool,
    ) -> list[dict]:
        path = "/historical/trades" if historical else "/markets/trades"
        return await self._collect(
            path, "trades", {"ticker": ticker, "min_ts": min_ts, "max_ts": max_ts},
        )
