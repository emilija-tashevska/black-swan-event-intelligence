from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel


class Market(BaseModel):
    ticker: str
    event_ticker: str
    market_type: str
    title: str
    subtitle: str
    yes_sub_title: str
    no_sub_title: str
    open_time: datetime
    close_time: datetime
    created_time: datetime
    status: str
    result: str

    last_price_dollars: str
    yes_bid_dollars: str
    yes_ask_dollars: str
    no_bid_dollars: str
    no_ask_dollars: str
    volume_fp: str
    open_interest_fp: str
    notional_value_dollars: str

    settlement_ts: datetime | None = None
    settlement_value_dollars: str | None = None
    rules_primary: str = ""

    prediction_price: float | None = None
    prediction_ts: int | None = None
    is_black_swan: bool = False

    class Config:
        extra = "ignore"


def _to_dollar_str(v: str | int | float | None) -> str | None:
    """Normalize cent ints or dollar strings into dollar strings."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return f"{v / 100:.4f}"
    return str(v)


class CandlestickPrice(BaseModel):
    open: str | int | float | None = None
    high: str | int | float | None = None
    low: str | int | float | None = None
    close: str | int | float | None = None
    mean: str | int | float | None = None
    previous: str | int | float | None = None
    open_dollars: str | None = None
    high_dollars: str | None = None
    low_dollars: str | None = None
    close_dollars: str | None = None
    mean_dollars: str | None = None
    previous_dollars: str | None = None

    class Config:
        extra = "ignore"

    def get_close(self) -> str | None:
        return self.close_dollars or _to_dollar_str(self.close)

    def get_mean(self) -> str | None:
        return self.mean_dollars or _to_dollar_str(self.mean)

    def get_previous(self) -> str | None:
        return self.previous_dollars or _to_dollar_str(self.previous)


class CandlestickBidAsk(BaseModel):
    open: str | int | float | None = None
    high: str | int | float | None = None
    low: str | int | float | None = None
    close: str | int | float | None = None
    open_dollars: str | None = None
    high_dollars: str | None = None
    low_dollars: str | None = None
    close_dollars: str | None = None

    class Config:
        extra = "ignore"


class Candlestick(BaseModel):
    end_period_ts: int
    price: CandlestickPrice
    yes_bid: CandlestickBidAsk
    yes_ask: CandlestickBidAsk
    volume: str | int | float | None = None
    volume_fp: str | None = None
    open_interest: str | int | float | None = None
    open_interest_fp: str | None = None

    class Config:
        extra = "ignore"


class BlackSwanEvent(BaseModel):
    ticker: str
    event_ticker: str
    title: str
    yes_sub_title: str
    prediction_price: float
    prediction_ts: int | None
    last_price_dollars: str
    volume_fp: str
    close_time: datetime
    settlement_ts: datetime | None
    result: str
    yes_bid_dollars: str
    yes_ask_dollars: str
    rules_primary: str


class BlackSwanStats(BaseModel):
    total_black_swans: int
    total_markets_analyzed: int
    avg_prediction_price: float | None
    lowest_prediction_price: float | None
    total_volume: float
    earliest_settlement: datetime | None
    latest_settlement: datetime | None
