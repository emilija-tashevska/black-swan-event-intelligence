import pytest

from calibration import (
    BUCKET_EDGES,
    MIN_GROUP_MARKETS,
    bucket_index,
    clustered_interval,
    summarize,
    wilson_interval,
)


@pytest.mark.parametrize(
    ("price", "bucket"),
    [(0.0, (0.0, 0.02)), (0.019, (0.0, 0.02)), (0.02, (0.02, 0.05)), (0.0999, (0.05, 0.10)),
     (0.10, (0.10, 0.15)), (0.5, (0.5, 0.6)), (0.99, (0.98, 1.0)), (1.0, (0.98, 1.0))],
)
def test_bucket_index_is_left_closed_and_includes_one(price, bucket):
    i = bucket_index(price)
    assert (BUCKET_EDGES[i], BUCKET_EDGES[i + 1]) == bucket


def test_wilson_interval_matches_reference_values():
    assert wilson_interval(5, 100) == pytest.approx((0.021544, 0.111750), abs=1e-5)
    lo, hi = wilson_interval(0, 50)
    assert lo == 0.0 and hi == pytest.approx(0.071348, abs=1e-5)  # zero hits still has a ceiling
    assert wilson_interval(50, 50)[1] == pytest.approx(1.0)
    assert wilson_interval(0, 0) is None


class TestClusteredInterval:
    def test_independent_markets_match_plain_wilson(self):
        singletons = [(1, 1)] * 5 + [(1, 0)] * 95
        lo, hi, n_eff = clustered_interval(singletons)
        assert n_eff == pytest.approx(100, rel=0.02)
        assert (lo, hi) == pytest.approx(wilson_interval(5, 100), abs=0.002)

    def test_markets_that_move_together_widen_the_interval(self):
        # 10 events of 10 markets each; all markets in an event resolve alike.
        together = [(10, 10)] + [(10, 0)] * 9
        lo, hi, n_eff = clustered_interval(together)
        # Effectively ~10 draws, not 100 (9 after the small-sample g/(g-1) correction)
        assert n_eff == pytest.approx(9)
        plain = wilson_interval(10, 100)
        assert lo < plain[0] and hi > plain[1]

    def test_one_winner_per_event_is_not_penalised(self):
        # "Pick one" events: exactly 1 of 5 wins each time. Very consistent, so
        # the design effect floors at 1 rather than narrowing below Wilson.
        pick_one = [(5, 1)] * 40
        lo, hi, n_eff = clustered_interval(pick_one)
        assert n_eff == pytest.approx(200)
        assert (lo, hi) == pytest.approx(wilson_interval(40, 200))

    def test_all_same_outcome_uses_event_count(self):
        lo, hi, n_eff = clustered_interval([(20, 0)] * 5)
        assert n_eff == 5
        assert lo == 0 and hi == pytest.approx(wilson_interval(0, 5)[1])

    def test_empty(self):
        assert clustered_interval([]) is None


def rows(category, structure, price, n, yes, per_event=1, prefix="E"):
    out = []
    for i in range(n):
        out.append((category, structure, f"{prefix}{category}{structure}{i // per_event}",
                    price, i < yes))
    return out


def test_overall_curve_buckets_rates_events_and_brier():
    data = (rows("Crypto", "ladder", 0.05, 100, 2, per_event=4)
            + rows("Crypto", "ladder", 0.95, 10, 10, prefix="F"))
    result = summarize(data)["overall"]

    assert (result["n"], result["events"]) == (110, 35)
    low, high = result["buckets"]
    assert (low["lo"], low["hi"], low["n"], low["events"], low["yes"]) == (0.05, 0.10, 100, 25, 2)
    assert low["rate"] == pytest.approx(0.02) and low["mean_price"] == pytest.approx(0.05)
    assert low["ci_low"] < 0.02 < low["ci_high"]
    assert low["n_effective"] <= 100
    assert (high["lo"], high["n"], high["rate"]) == (0.95, 10, 1.0)
    expected_brier = (98 * 0.05**2 + 2 * 0.95**2 + 10 * 0.05**2) / 110
    assert result["brier"] == pytest.approx(expected_brier)


def test_longshots_summary():
    data = rows("X", "standalone", 0.01, 40, 1) + rows("X", "standalone", 0.08, 60, 6, prefix="F")
    ls = summarize(data)["overall"]["longshots"]
    assert (ls["n"], ls["events"], ls["yes"]) == (100, 100, 7)
    assert ls["mean_price"] == pytest.approx((40 * 0.01 + 60 * 0.08) / 100)


def test_groups_by_category_structure_and_both():
    big = MIN_GROUP_MARKETS
    data = (
        rows("Politics", "standalone", 0.05, big, 3)
        + rows("Politics", "pick_one", 0.05, big, 3)
        + rows("Crypto", "ladder", 0.05, big + 50, 3)
        + rows("Tiny", "ladder", 0.05, 10, 0)
        + rows("", None, 0.05, big, 0)
    )
    result = summarize(data)

    assert [c["category"] for c in result["categories"]] == ["Politics", "Crypto", "Uncategorized"]
    assert all(c["structure"] is None for c in result["categories"])
    structures = {s["structure"]: s["n"] for s in result["structures"]}
    assert structures == {"ladder": big + 60, "standalone": big, "pick_one": big, "unknown": big}
    segments = {(s["category"], s["structure"]) for s in result["segments"]}
    assert segments == {("Crypto", "ladder"), ("Politics", "standalone"),
                        ("Politics", "pick_one"), ("Uncategorized", "unknown")}
    assert result["overall"]["n"] == 4 * big + 60  # small groups still count overall


def test_empty_input():
    result = summarize([])
    assert result["overall"]["n"] == 0 and result["overall"]["buckets"] == []
    assert result["overall"]["longshots"]["rate"] is None
    assert result["categories"] == result["structures"] == result["segments"] == []
