from __future__ import annotations

from pydantic import BaseModel, ConfigDict


def to_dollars(value: str | int | float | None) -> float | None:
    """Kalshi now returns prices as dollar strings ("0.0700"). Older payloads
    used integer cents; accept both."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return float(value)
    return value / 100


def to_count(value: str | int | float | None) -> float:
    if value is None or value == "":
        return 0.0
    return float(value)


class CandlestickPrice(BaseModel):
    model_config = ConfigDict(extra="ignore")

    open: str | int | float | None = None
    high: str | int | float | None = None
    low: str | int | float | None = None
    close: str | int | float | None = None
    mean: str | int | float | None = None
    previous: str | int | float | None = None
    close_dollars: str | None = None
    mean_dollars: str | None = None
    previous_dollars: str | None = None

    def implied_probability(self) -> float | None:
        """Closing trade price for the period, falling back to its mean trade
        price. `previous` (the last trade before the period) is deliberately
        ignored: on quiet days it can be weeks old and far from the live book."""
        for v in (self.close_dollars or self.close, self.mean_dollars or self.mean):
            price = to_dollars(v)
            if price is not None:
                return price
        return None


class CandlestickQuote(BaseModel):
    model_config = ConfigDict(extra="ignore")

    close: str | int | float | None = None
    close_dollars: str | None = None

    def closing(self) -> float | None:
        return to_dollars(self.close_dollars or self.close)


class Candlestick(BaseModel):
    model_config = ConfigDict(extra="ignore")

    end_period_ts: int
    price: CandlestickPrice
    yes_bid: CandlestickQuote | None = None
    yes_ask: CandlestickQuote | None = None
    volume: str | int | float | None = None
    volume_fp: str | None = None

    def contracts_traded(self) -> float:
        return to_count(self.volume_fp or self.volume)

    def closing_quote(self) -> tuple[float | None, float | None]:
        """Closing YES bid and ask for the period, if the book had them."""
        return (
            self.yes_bid.closing() if self.yes_bid else None,
            self.yes_ask.closing() if self.yes_ask else None,
        )

    def implied_probability(self, max_spread: float) -> tuple[float, str] | None:
        """(probability, source). Prefers a price traded during the period; when
        nothing traded, uses the closing YES bid/ask midpoint if the book was
        tight enough to be informative. Otherwise there is no current price."""
        traded = self.price.implied_probability()
        if traded is not None:
            return traded, "trade"
        bid, ask = self.closing_quote()
        if bid is not None and ask is not None and 0 <= ask - bid <= max_spread + 1e-9:
            return (bid + ask) / 2, "quote"
        return None


class Headline(BaseModel):
    ticker: str
    headline: str


class HeadlineBatch(BaseModel):
    headlines: list[Headline]
