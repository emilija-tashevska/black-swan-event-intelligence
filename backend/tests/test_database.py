import aiosqlite
import pytest
from conftest import db_row, insert_rows

import database as dbq


def swan(ticker, price, category="Crypto", **kw):
    return db_row(ticker, category, prediction_status="ok", prediction_price=price, **kw)


async def test_threshold_is_strict_and_only_scored_yes_markets_count(db):
    await insert_rows(db, [
        swan("KX-A", 0.05),
        swan("KX-B", 0.10),                                   # at threshold: excluded
        swan("KX-C", 0.02, result="no"),                      # didn't happen
        db_row("KX-D", prediction_status="short_lived"),      # out of scope
        db_row("KX-E", prediction_status="no_data"),
    ])
    rows = await dbq.query_black_swans(db, threshold=0.10)
    assert [r["ticker"] for r in rows] == ["KX-A"]
    assert len(await dbq.query_black_swans(db, threshold=0.11)) == 2


async def test_sorting_ordering_and_nulls_last(db):
    await insert_rows(db, [
        swan("KX-A", 0.05, volume_fp="100.00", volume_at_price=10.0),
        swan("KX-B", 0.02, volume_fp="300.00"),
        swan("KX-C", 0.08, volume_fp="200.00", volume_at_price=50.0),
    ])
    async def tickers(**kw):
        return [r["ticker"] for r in await dbq.query_black_swans(db, 0.10, **kw)]

    assert await tickers() == ["KX-B", "KX-C", "KX-A"]  # default: volume desc
    assert await tickers(sort="prediction_price", order="asc") == ["KX-B", "KX-A", "KX-C"]
    assert await tickers(sort="volume_at_price", order="asc") == ["KX-A", "KX-C", "KX-B"]
    assert await tickers(sort="volume_at_price", order="desc") == ["KX-C", "KX-A", "KX-B"]


async def test_unknown_sort_column_cannot_inject_sql(db):
    await insert_rows(db, [swan("KX-A", 0.05)])
    rows = await dbq.query_black_swans(db, 0.10, sort="volume; DROP TABLE markets", order="x")
    assert [r["ticker"] for r in rows] == ["KX-A"]
    assert await dbq.query_black_swans(db, 0.10)


async def test_category_filter_limit_offset(db):
    await insert_rows(db, [swan("KX-A", 0.01, "Crypto"), swan("KX-B", 0.02, "Politics"),
                           swan("KX-C", 0.03, "Politics")])
    assert [r["ticker"] for r in await dbq.query_black_swans(
        db, 0.1, sort="prediction_price", order="asc", category="Politics")] == ["KX-B", "KX-C"]
    page = await dbq.query_black_swans(db, 0.1, sort="prediction_price", order="asc",
                                       limit=1, offset=1)
    assert [r["ticker"] for r in page] == ["KX-B"]


async def test_stats(db):
    await insert_rows(db, [
        swan("KX-A", 0.05, "Crypto", volume_fp="1000.00", volume_at_price=100.0),
        swan("KX-B", 0.01, "Politics", volume_fp="3000.00"),
        db_row("KX-C", "Crypto", prediction_status="ok", prediction_price=0.7),
        db_row("KX-D", "Crypto", prediction_status="ok", prediction_price=0.9),
        db_row("KX-E", "Crypto", prediction_status="short_lived"),
        db_row("KX-F", "Crypto", result="no"),
    ])
    s = await dbq.query_stats(db, 0.10)
    assert s["total_black_swans"] == 2
    assert s["avg_prediction_price"] == pytest.approx(0.03)
    assert s["lowest_prediction_price"] == 0.01
    assert s["total_volume"] == 4000.0
    assert s["yes_side_upside"] == pytest.approx(95.0)  # (1 - 0.05) * 100
    assert s["markets_collected"] == 6
    assert s["yes_markets"] == 5
    assert s["markets_scored"] == 4
    assert s["short_lived_excluded"] == 1
    assert s["category_stats"] == [
        {"category": "Crypto", "count": 1, "scored": 3, "rate": pytest.approx(1 / 3)},
        {"category": "Politics", "count": 1, "scored": 1, "rate": 1.0},
    ]


async def test_stats_on_empty_database(db):
    s = await dbq.query_stats(db, 0.10)
    assert s["total_black_swans"] == 0 and s["avg_prediction_price"] is None
    assert s["markets_collected"] == 0 and s["category_stats"] == []


async def test_summary_queue_respects_force(db):
    await insert_rows(db, [swan("KX-A", 0.05, ai_summary="Done."), swan("KX-B", 0.05)])
    assert [r["ticker"] for r in await dbq.black_swans_needing_summary(db, 0.25)] == ["KX-B"]
    assert len(await dbq.black_swans_needing_summary(db, 0.25, force=True)) == 2


async def test_old_schema_is_rejected_with_a_clear_message(tmp_path):
    path = tmp_path / "old.db"
    async with aiosqlite.connect(path) as raw:
        await raw.execute("CREATE TABLE markets (ticker TEXT PRIMARY KEY, is_sports INTEGER)")
        await raw.commit()
    with pytest.raises(dbq.SchemaMismatchError, match="delete the database"):
        async with dbq.connect(path):
            pass


async def test_reopening_current_schema_is_fine(tmp_path):
    path = tmp_path / "ok.db"
    async with dbq.connect(path) as db:
        await dbq.set_meta(db, "k", "v")
    async with dbq.connect(path) as db:
        assert await dbq.get_meta(db, "k") == "v"
