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
MAX_RETRIES = 4
RETRY_BACKOFF = 2.0
RATE_LIMIT_DELAY = 0.15  # seconds between requests
DAILY = 1440  # candlestick period in minutes
HISTORICAL_ORDER_SLACK = 86_400  # archive pages overlap in settlement time


class KalshiError(RuntimeError):
    pass


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
        """GET with retries on 429, 5xx and network errors. 4xx other than 429
        raise immediately; exhausting retries raises rather than returning
        an empty payload that would silently drop data."""
        assert self._client is not None, "use KalshiClient as an async context manager"
        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES):
            if self._rate_limit_delay:
                await asyncio.sleep(self._rate_limit_delay)
            try:
                resp = await self._client.get(path, params=params)
            except httpx.RequestError as e:
                last_error = e
                logger.warning("Request error on %s: %s (attempt %d)", path, e, attempt + 1)
            else:
                if resp.status_code == 429 or resp.status_code >= 500:
                    last_error = KalshiError(f"HTTP {resp.status_code} on {path}")
                    logger.warning("%s (attempt %d)", last_error, attempt + 1)
                    retry_after = resp.headers.get("retry-after")
                    if retry_after and retry_after.isdigit():
                        await asyncio.sleep(int(retry_after))
                        continue
                else:
                    resp.raise_for_status()
                    return resp.json()
            await asyncio.sleep(self._retry_backoff * (attempt + 1))
        raise KalshiError(f"Giving up on {path} after {MAX_RETRIES} attempts") from last_error

    async def paginate(
        self, path: str, key: str, params: dict | None = None, limit: int = DEFAULT_LIMIT,
    ) -> AsyncIterator[list[dict]]:
        """Yield pages until the API stops returning a cursor."""
        params = {**(params or {}), "limit": limit}
        while True:
            data = await self._get(path, params)
            items = data.get(key, [])
            if items:
                yield items
            cursor = data.get("cursor")
            if not cursor or not items:
                return
            params["cursor"] = cursor

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

    def settled_markets(self, min_settled_ts: int) -> AsyncIterator[list[dict]]:
        return self.paginate(
            "/markets", "markets",
            {"status": "settled", "mve_filter": "exclude", "min_settled_ts": min_settled_ts},
        )

    async def historical_markets(self, min_settled_ts: int) -> AsyncIterator[list[dict]]:
        """The archive endpoint ignores time filters, but returns markets roughly
        newest-settled first. Filter each page client-side and stop once a whole
        page (plus a safety margin for out-of-order pages) predates the window."""
        stop_before = min_settled_ts - HISTORICAL_ORDER_SLACK
        pages = self.paginate("/historical/markets", "markets", {"mve_filter": "exclude"})
        async for page in pages:
            settled = [(m, _settled_ts(m)) for m in page]
            in_window = [m for m, ts in settled if ts is None or ts >= min_settled_ts]
            if in_window:
                yield in_window
            newest = max((ts for _, ts in settled if ts is not None), default=None)
            if newest is not None and newest < stop_before:
                return

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
