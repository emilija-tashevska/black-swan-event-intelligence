from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

import database as dbq
from models import Candlestick

FIXTURES = Path(__file__).parent / "fixtures"
DAY = 86_400


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, UTC).isoformat().replace("+00:00", "Z")


def candle(end_ts: int, close: str | None = "0.0500", volume: str = "100.00", **price) -> dict:
    return {
        "end_period_ts": end_ts,
        "price": {"close": close, **price},
        "volume": volume,
    }


def make_market(ticker: str = "KXTEST-26JAN01-A", **overrides) -> dict:
    """A raw Kalshi market payload (API shape, string-typed numbers)."""
    close = overrides.pop("close_ts", 1_770_000_000)
    duration_days = overrides.pop("duration_days", 30)
    base = {
        "ticker": ticker,
        "event_ticker": ticker.rsplit("-", 1)[0],
        "title": f"Title for {ticker}",
        "yes_sub_title": "Yes outcome",
        "rules_primary": "If X happens, resolves Yes.",
        "open_time": iso(close - duration_days * DAY),
        "close_time": iso(close),
        "settlement_ts": iso(close + 3600),
        "result": "yes",
        "last_price_dollars": "0.9900",
        "volume_fp": "5000.00",
        "open_interest_fp": "1200.00",
    }
    base.update(overrides)
    return base


def db_row(ticker: str = "KXTEST-26JAN01-A", category: str = "Crypto", **overrides) -> dict:
    """A row ready for dbq.upsert_markets, optionally pre-scored."""
    from collector import market_to_row

    scoring = {k: overrides.pop(k) for k in list(overrides) if k.startswith(("prediction_", "ai_"))
               or k == "volume_at_price"}
    row = market_to_row(make_market(ticker, **overrides), ticker.split("-")[0], category)
    row["_scoring"] = scoring
    return row


async def insert_rows(db, rows: list[dict]) -> None:
    scorings = [(r["ticker"], r.pop("_scoring", {})) for r in rows]
    await dbq.upsert_markets(db, rows)
    for ticker, scoring in scorings:
        if scoring:
            sets = ", ".join(f"{k} = ?" for k in scoring)
            await db.execute(f"UPDATE markets SET {sets} WHERE ticker = ?",
                             (*scoring.values(), ticker))
    await db.commit()


@pytest.fixture
async def db(tmp_path):
    async with dbq.connect(tmp_path / "test.db") as conn:
        yield conn


class FakeKalshi:
    """In-memory stand-in for KalshiClient with the same public methods."""

    def __init__(self, *, live=(), historical=(), series=(), events=None, candles=None,
                 trades=None, cutoff_ts: str | None = None, failing_tickers=(), fail_at=None,
                 open_pages=()):
        self.live_pages = [list(p) for p in live]
        self.historical_pages = [list(p) for p in historical]
        self.series = list(series)
        self.events = events or {}
        self.candles = candles or {}
        self.trades = trades or {}
        self.cutoff_ts = cutoff_ts
        self.failing = set(failing_tickers)
        self.open_pages = [list(p) for p in open_pages]
        self.fail_at = fail_at  # (source label, page index) that raises, to simulate a crash
        self.calls: list[tuple] = []

    async def get_cutoff_ts(self):
        return self.cutoff_ts

    async def get_all_series(self):
        return self.series

    async def get_event(self, event_ticker):
        self.calls.append(("event", event_ticker))
        if event_ticker not in self.events:
            raise RuntimeError("404")
        return self.events[event_ticker]

    async def _pages(self, label, pages, cursor):
        start = int(cursor.removeprefix(label)) if cursor else 0
        for i in range(start, len(pages)):
            if self.fail_at == (label, i):
                raise RuntimeError(f"{label} page {i} unavailable")
            yield pages[i], f"{label}{i + 1}" if i + 1 < len(pages) else None

    def settled_markets(self, min_settled_ts, cursor=None):
        self.calls.append(("live", min_settled_ts, cursor))
        return self._pages("live", self.live_pages, cursor)

    def historical_markets(self, min_settled_ts, cursor=None):
        self.calls.append(("historical", min_settled_ts, cursor))
        return self._pages("historical", self.historical_pages, cursor)

    def open_markets(self, min_close_ts, max_close_ts):
        self.calls.append(("open", min_close_ts, max_close_ts))
        return self._plain_pages(self.open_pages)

    async def _plain_pages(self, pages):
        for p in pages:
            yield p

    async def get_candlesticks(self, ticker, start_ts, end_ts, *, historical, series_ticker=None):
        self.calls.append(("candles", ticker, start_ts, end_ts, historical))
        if ticker in self.failing:
            raise RuntimeError("boom")
        return [Candlestick.model_validate(c) for c in self.candles.get(ticker, [])]

    async def get_trades(self, ticker, min_ts, max_ts, *, historical):
        self.calls.append(("trades", ticker, min_ts, max_ts, historical))
        if ticker in self.failing:
            raise RuntimeError("boom")
        return self.trades.get(ticker, [])
