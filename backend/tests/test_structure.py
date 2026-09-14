import pytest
from conftest import FakeKalshi, db_row, insert_rows

import database as dbq
import structure


@pytest.mark.parametrize(
    ("exclusive", "count", "strike", "expected"),
    [
        (False, 1, None, "standalone"),
        (True, 1, "custom", "standalone"),     # one market, whatever the flags
        (True, 7, "custom", "pick_one"),       # award nominees
        (True, 12, "between", "pick_one"),     # exclusive price ranges
        (False, 11, "greater", "ladder"),      # "above 107 / 108 / 109"
        (False, 8, "less", "ladder"),
        (False, 27, "custom", "bundle"),       # words said in a speech
        (None, 5, None, "bundle"),             # unknown flags on a multi-market event
    ],
)
def test_classify(exclusive, count, strike, expected):
    assert structure.classify(exclusive, count, strike) == expected


class StructureKalshi(FakeKalshi):
    def __init__(self, events, live_markets=None, archived_markets=None, failing=()):
        super().__init__(events=events)
        self.live_markets = live_markets or {}
        self.archived_markets = archived_markets or {}
        self.failing_events = set(failing)

    async def get_event(self, event_ticker):
        if event_ticker in self.failing_events:
            raise RuntimeError("timeout")
        return await super().get_event(event_ticker)

    async def markets_for_event(self, event_ticker, *, historical):
        self.calls.append(("event_markets", event_ticker, historical))
        source = self.archived_markets if historical else self.live_markets
        return source.get(event_ticker, [])


def markets(n, strike):
    return [{"ticker": f"M{i}", "strike_type": strike} for i in range(n)]


async def test_enrich_structures_classifies_scored_events(db):
    await insert_rows(db, [
        db_row("KXEMMY-GAD-A", prediction_status="ok", prediction_price=0.05),
        db_row("KXEMMY-GAD-B", prediction_status="ok", prediction_price=0.4),
        db_row("KXAMZNCC-AUG-T109", prediction_status="ok", prediction_price=0.04),
        db_row("KXAPOLOGY-26-X", prediction_status="ok", prediction_price=0.08),
        db_row("KXFLAKY-1-X", prediction_status="ok", prediction_price=0.5),
        db_row("KXUNSCORED-1-X"),  # not scored: not looked up
    ])
    kalshi = StructureKalshi(
        events={
            "KXEMMY-GAD": {"mutually_exclusive": True, "series_ticker": "KXEMMY", "title": "Emmy"},
            "KXAMZNCC-AUG": {"mutually_exclusive": False, "series_ticker": "KXAMZNCC"},
            "KXAPOLOGY-26": {"mutually_exclusive": False},
            "KXFLAKY-1": {"mutually_exclusive": False},
        },
        live_markets={"KXEMMY-GAD": markets(7, "custom")},
        archived_markets={"KXAMZNCC-AUG": markets(11, "greater"),
                          "KXAPOLOGY-26": markets(1, None)},
        failing={"KXFLAKY-1"},
    )
    counts = await structure.enrich_structures(kalshi, db)

    assert counts == {"pick_one": 1, "ladder": 1, "standalone": 1, "errors": 1}
    cur = await db.execute("SELECT * FROM events")
    rows = {r["event_ticker"]: dict(r) for r in await cur.fetchall()}
    assert rows["KXEMMY-GAD"]["market_count"] == 7 and rows["KXEMMY-GAD"]["title"] == "Emmy"
    assert rows["KXAMZNCC-AUG"]["strike_type"] == "greater"
    assert "KXFLAKY-1" not in rows
    # Live lookup first; the archive only when the live endpoint has nothing
    assert ("event_markets", "KXEMMY-GAD", True) not in kalshi.calls
    assert ("event_markets", "KXAMZNCC-AUG", True) in kalshi.calls

    # Classified events aren't fetched again; the failed one is retried
    assert [r["event_ticker"] for r in await dbq.events_missing_structure(db)] == ["KXFLAKY-1"]


async def test_local_count_is_a_floor_when_kalshi_lists_nothing(db):
    await insert_rows(db, [
        db_row("KXODD-1-A", prediction_status="ok", prediction_price=0.1),
        db_row("KXODD-1-B", prediction_status="ok", prediction_price=0.2),
    ])
    kalshi = StructureKalshi(events={"KXODD-1": {"mutually_exclusive": False}})
    await structure.enrich_structures(kalshi, db)
    (row,) = await (await db.execute("SELECT market_count, structure FROM events")).fetchall()
    assert tuple(row) == (2, "bundle")


async def test_scored_outcomes_join_structure(db):
    await insert_rows(db, [
        db_row("KXEMMY-GAD-A", prediction_status="ok", prediction_price=0.05, result="no"),
        db_row("KXNEW-1-A", prediction_status="ok", prediction_price=0.5),
    ])
    await dbq.upsert_events(db, [{
        "event_ticker": "KXEMMY-GAD", "series_ticker": "KXEMMY", "title": "",
        "mutually_exclusive": 1, "market_count": 7, "strike_type": "custom",
        "structure": "pick_one",
    }])
    outcomes = await dbq.scored_outcomes(db)
    got = {r["event_ticker"]: (r["structure"], r["resolved_yes"]) for r in outcomes}
    assert got == {"KXEMMY-GAD": ("pick_one", 0), "KXNEW-1": ("unknown", 1)}


async def test_black_swans_carry_their_structure(db):
    await insert_rows(db, [
        db_row("KXEMMY-GAD-A", prediction_status="ok", prediction_price=0.05),
        db_row("KXNEW-1-A", prediction_status="ok", prediction_price=0.04),
    ])
    await dbq.upsert_events(db, [{
        "event_ticker": "KXEMMY-GAD", "series_ticker": "KXEMMY", "title": "",
        "mutually_exclusive": 1, "market_count": 7, "strike_type": "custom",
        "structure": "pick_one",
    }])
    rows = await dbq.query_black_swans(db, 0.10, sort="prediction_price", order="asc")
    assert [(r["ticker"], r["structure"]) for r in rows] == [
        ("KXNEW-1-A", "unknown"), ("KXEMMY-GAD-A", "pick_one")]
