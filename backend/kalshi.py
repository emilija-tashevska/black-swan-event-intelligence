from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from models import Candlestick

logger = logging.getLogger(__name__)

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
DEFAULT_LIMIT = 1000
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0
RATE_LIMIT_DELAY = 0.15  # seconds between requests


class KalshiClient:
    def __init__(self, base_url: str = BASE_URL) -> None:
        self._base_url = base_url.rstrip("/")
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
        assert self._client is not None
        for attempt in range(MAX_RETRIES):
            try:
                await asyncio.sleep(RATE_LIMIT_DELAY)
                resp = await self._client.get(path, params=params)
                if resp.status_code == 429:
                    wait = RETRY_BACKOFF * (attempt + 1)
                    logger.warning("Rate limited, waiting %.1fs", wait)
                    await asyncio.sleep(wait)
                    continue
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as e:
                if attempt == MAX_RETRIES - 1:
                    raise
                logger.warning("HTTP %s on %s, retrying", e.response.status_code, path)
                await asyncio.sleep(RETRY_BACKOFF * (attempt + 1))
            except httpx.RequestError as e:
                if attempt == MAX_RETRIES - 1:
                    raise
                logger.warning("Request error on %s: %s, retrying", path, e)
                await asyncio.sleep(RETRY_BACKOFF * (attempt + 1))
        return {}

    async def _paginate(self, path: str, key: str, params: dict | None = None) -> list[dict]:
        all_items: list[dict] = []
        params = dict(params or {})
        params.setdefault("limit", DEFAULT_LIMIT)

        while True:
            data = await self._get(path, params)
            items = data.get(key, [])
            all_items.extend(items)
            cursor = data.get("cursor", "")
            if not cursor or len(items) < params["limit"]:
                break
            params["cursor"] = cursor
            logger.info("Fetched %d %s so far (cursor: %s…)", len(all_items), key, cursor[:20])

        return all_items

    async def paginate_batches(self, path: str, key: str, params: dict | None = None, batch_size: int = DEFAULT_LIMIT):
        """Yield pages of results as they come in, for streaming into the DB."""
        params = dict(params or {})
        params.setdefault("limit", batch_size)
        total = 0

        while True:
            data = await self._get(path, params)
            items = data.get(key, [])
            if items:
                total += len(items)
                yield items
            cursor = data.get("cursor", "")
            if not cursor or len(items) < params["limit"]:
                break
            params["cursor"] = cursor
            logger.info("Fetched %d %s so far", total, key)

    # ── Market endpoints ──

    async def get_cutoff(self) -> dict:
        return await self._get("/historical/cutoff")

    async def get_settled_markets(self) -> list[dict]:
        logger.info("Fetching settled markets from live endpoint…")
        return await self._paginate("/markets", "markets", {"status": "settled"})

    async def get_historical_markets(self) -> list[dict]:
        logger.info("Fetching historical markets…")
        return await self._paginate("/historical/markets", "markets")

    # ── Candlestick endpoints ──

    async def get_historical_candlesticks(
        self,
        ticker: str,
        start_ts: int,
        end_ts: int,
        period_interval: int = 1440,
    ) -> list[Candlestick]:
        data = await self._get(
            f"/historical/markets/{ticker}/candlesticks",
            {
                "start_ts": start_ts,
                "end_ts": end_ts,
                "period_interval": period_interval,
            },
        )
        raw = data.get("candlesticks", [])
        return [Candlestick.model_validate(c) for c in raw]

    async def get_live_candlesticks(
        self,
        series_ticker: str,
        ticker: str,
        start_ts: int,
        end_ts: int,
        period_interval: int = 1440,
    ) -> list[Candlestick]:
        data = await self._get(
            f"/series/{series_ticker}/markets/{ticker}/candlesticks",
            {
                "start_ts": start_ts,
                "end_ts": end_ts,
                "period_interval": period_interval,
            },
        )
        raw = data.get("candlesticks", [])
        return [Candlestick.model_validate(c) for c in raw]

    # ── Trade endpoints ──

    async def get_historical_trades(
        self, ticker: str, min_ts: int, max_ts: int,
    ) -> list[dict]:
        return await self._paginate(
            "/historical/trades", "trades",
            {"ticker": ticker, "min_ts": min_ts, "max_ts": max_ts},
        )

    async def get_live_trades(
        self, ticker: str, min_ts: int, max_ts: int,
    ) -> list[dict]:
        return await self._paginate(
            "/markets/trades", "trades",
            {"ticker": ticker, "min_ts": min_ts, "max_ts": max_ts},
        )

    async def get_event(self, event_ticker: str) -> dict:
        data = await self._get(f"/events/{event_ticker}")
        return data.get("event", data)
