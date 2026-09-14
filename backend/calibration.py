"""Calibration: when the market priced something at p a week out, how often did it happen?

Markets are grouped by price bucket. Because several markets can come from one
event (seven Emmy nominees, a ladder of CPI thresholds), intervals treat events,
not markets, as the independent unit.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field

# Finer buckets at the extremes, where longshots and near-certainties live.
BUCKET_EDGES = (
    0.0, 0.02, 0.05, 0.10, 0.15, 0.20, 0.30, 0.40, 0.50,
    0.60, 0.70, 0.80, 0.85, 0.90, 0.95, 0.98, 1.0,
)
LONGSHOT_MAX_PRICE = 0.10
# A category, structure, or category × structure gets its own curve only with
# enough scored markets to be meaningful.
MIN_GROUP_MARKETS = 100
Z_95 = 1.959964


def bucket_index(price: float) -> int:
    """Index into BUCKET_EDGES; each bucket is [lo, hi) except the last, which includes 1.0."""
    return min(max(bisect_right(BUCKET_EDGES, price) - 1, 0), len(BUCKET_EDGES) - 2)


def wilson_interval(successes: float, n: float, z: float = Z_95) -> tuple[float, float] | None:
    """95% Wilson score interval: well behaved near 0 and 1, where longshots sit.
    Accepts fractional counts so it can be used with an effective sample size."""
    if n <= 0:
        return None
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(max(p * (1 - p) / n + z * z / (4 * n * n), 0.0)) / denom
    return max(0.0, centre - margin), min(1.0, centre + margin)


def clustered_interval(clusters: Iterable[tuple[int, int]]) -> tuple[float, float, float] | None:
    """Wilson interval widened for clustering. `clusters` holds (markets, yes)
    per event. The design effect compares the between-event variance of the
    hit rate (a ratio estimator) with what independent markets would give, and
    shrinks the sample to an effective size n / deff. Returns (low, high, n_eff).

    When every market resolved the same way the variance estimate is
    degenerate, so the number of events is used as the effective size."""
    clusters = [(m, y) for m, y in clusters if m > 0]
    g = len(clusters)
    n = sum(m for m, _ in clusters)
    if g == 0:
        return None
    yes = sum(y for _, y in clusters)
    p = yes / n
    if 0 < p < 1 and g > 1:
        var_clustered = g / (g - 1) * sum((y - p * m) ** 2 for m, y in clusters) / (n * n)
        var_independent = p * (1 - p) / n
        deff = max(1.0, var_clustered / var_independent)
        n_eff = n / deff
    else:
        n_eff = float(g)
    low, high = wilson_interval(p * n_eff, n_eff)
    return low, high, n_eff


@dataclass
class _Tally:
    price_sum: float = 0.0
    squared_error: float = 0.0
    by_event: dict[str, list[int]] = field(default_factory=lambda: defaultdict(lambda: [0, 0]))

    def add(self, event: str, price: float, resolved_yes: bool) -> None:
        cell = self.by_event[event]
        cell[0] += 1
        cell[1] += int(resolved_yes)
        self.price_sum += price
        self.squared_error += (price - resolved_yes) ** 2

    @property
    def n(self) -> int:
        return sum(m for m, _ in self.by_event.values())

    def as_dict(self) -> dict:
        n = self.n
        yes = sum(y for _, y in self.by_event.values())
        ci = clustered_interval(self.by_event.values())
        return {
            "n": n,
            "events": len(self.by_event),
            "yes": yes,
            "mean_price": self.price_sum / n if n else None,
            "rate": yes / n if n else None,
            "ci_low": ci[0] if ci else None,
            "ci_high": ci[1] if ci else None,
            "n_effective": round(ci[2], 1) if ci else None,
        }


Outcome = tuple[str, float, bool]  # (event, price, resolved YES)


def curve(outcomes: list[Outcome]) -> dict:
    total = _Tally()
    longshots = _Tally()
    buckets = [_Tally() for _ in range(len(BUCKET_EDGES) - 1)]
    for event, price, resolved_yes in outcomes:
        total.add(event, price, resolved_yes)
        buckets[bucket_index(price)].add(event, price, resolved_yes)
        if price < LONGSHOT_MAX_PRICE:
            longshots.add(event, price, resolved_yes)
    summary = total.as_dict()
    return {
        "n": summary["n"],
        "events": summary["events"],
        "brier": total.squared_error / summary["n"] if summary["n"] else None,
        "longshots": longshots.as_dict(),
        "buckets": [
            {"lo": BUCKET_EDGES[i], "hi": BUCKET_EDGES[i + 1], **b.as_dict()}
            for i, b in enumerate(buckets)
            if b.n
        ],
    }


def summarize(rows: Iterable[tuple[str, str, str, float, bool]]) -> dict:
    """rows: (category, structure, event_ticker, price a week before close, resolved YES)."""
    groups: dict[tuple[str | None, str | None], list[Outcome]] = defaultdict(list)
    for category, structure, event, price, resolved_yes in rows:
        outcome = (event, float(price), bool(resolved_yes))
        category = category or "Uncategorized"
        structure = structure or "unknown"
        for key in ((None, None), (category, None), (None, structure), (category, structure)):
            groups[key].append(outcome)

    def named(key_filter) -> list[dict]:
        out = [
            {"category": c, "structure": s, **curve(outcomes)}
            for (c, s), outcomes in groups.items()
            if key_filter(c, s) and len(outcomes) >= MIN_GROUP_MARKETS
        ]
        return sorted(out, key=lambda g: (-g["n"], g["category"] or "", g["structure"] or ""))

    return {
        "bucket_edges": list(BUCKET_EDGES),
        "longshot_max_price": LONGSHOT_MAX_PRICE,
        "min_group_markets": MIN_GROUP_MARKETS,
        "overall": curve(groups.get((None, None), [])),
        "categories": named(lambda c, s: c is not None and s is None),
        "structures": named(lambda c, s: c is None and s is not None),
        "segments": named(lambda c, s: c is not None and s is not None),
    }
