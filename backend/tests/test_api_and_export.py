import json

import pytest
from conftest import db_row, insert_rows
from fastapi.testclient import TestClient

import config
import database as dbq
import main
from export import export_static


@pytest.fixture
async def seeded_path(tmp_path):
    path = tmp_path / "api.db"
    async with dbq.connect(path) as db:
        await insert_rows(db, [
            db_row("KX-A", "Crypto", prediction_status="ok", prediction_price=0.04),
            db_row("KX-B", "Politics", prediction_status="ok", prediction_price=0.18),
        ])
        await dbq.set_meta(db, "last_collection_ts", "1789300000")
    return path


def test_api_endpoints(seeded_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", seeded_path)
    with TestClient(main.app) as client:
        assert client.get("/api/health").json() == {"status": "ok"}

        body = client.get("/api/black-swans", params={"threshold": 0.2}).json()
        assert body["count"] == 2 and {r["ticker"] for r in body["black_swans"]} == {"KX-A", "KX-B"}

        body = client.get("/api/black-swans", params={"category": "Politics", "threshold": 0.2})
        assert [r["ticker"] for r in body.json()["black_swans"]] == ["KX-B"]

        stats = client.get("/api/stats").json()
        assert stats["total_black_swans"] == 1 and stats["threshold"] == 0.10

        cal = client.get("/api/calibration").json()
        assert cal["overall"]["n"] == 2
        wl = client.get("/api/watchlist").json()
        assert wl["markets"] == [] and wl["horizon_days"] == [4, 10]

        assert client.get("/api/black-swans", params={"threshold": 0}).status_code == 422
        assert client.post("/api/black-swans").status_code == 405


async def test_export_writes_every_threshold_and_meta(seeded_path, tmp_path):
    out = tmp_path / "data"
    async with dbq.connect(seeded_path) as db:
        counts = await export_static(db, out)

    assert counts == {5: 1, 10: 1, 15: 1, 20: 2, 25: 2}
    for pct in (5, 10, 15, 20, 25):
        bs = json.loads((out / f"black-swans-{pct}.json").read_text())
        stats = json.loads((out / f"stats-{pct}.json").read_text())
        assert bs["count"] == len(bs["black_swans"]) == stats["total_black_swans"]
    calibration = json.loads((out / "calibration.json").read_text())
    assert calibration["overall"]["n"] == 2
    assert json.loads((out / "watchlist.json").read_text())["markets"] == []
    meta = json.loads((out / "meta.json").read_text())
    assert meta["data_as_of"].startswith("2026-09-13")
    assert meta["first_close"] and meta["first_close"] <= meta["last_close"]
    assert meta["thresholds"] == list(config.STATIC_THRESHOLDS)
