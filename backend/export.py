"""Export the database to static JSON consumed by the GitHub Pages build."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

import config
import database as dbq
from watchlist import build_calibration, build_watchlist

logger = logging.getLogger(__name__)

DEFAULT_OUT_DIR = config.BACKEND_DIR.parent / "frontend" / "public" / "data"


async def export_static(db: aiosqlite.Connection, out_dir: Path = DEFAULT_OUT_DIR) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    counts = {}
    for threshold in config.STATIC_THRESHOLDS:
        pct = round(threshold * 100)
        rows = await dbq.query_black_swans(db, threshold, sort="volume", order="desc", limit=1000)
        stats = await dbq.query_stats(db, threshold)
        _write(out_dir / f"black-swans-{pct}.json", {"black_swans": rows, "count": len(rows)})
        _write(out_dir / f"stats-{pct}.json", stats)
        counts[pct] = len(rows)
        logger.info("threshold %d%%: %d black swans", pct, len(rows))

    calibration = await build_calibration(db)
    _write(out_dir / "calibration.json", calibration)
    _write(out_dir / "watchlist.json", await build_watchlist(db, calibration))
    logger.info("calibration: %d scored markets", calibration["overall"]["n"])

    coverage = await (await db.execute(
        "SELECT MIN(close_time), MAX(close_time) FROM markets WHERE prediction_status = 'ok'"
    )).fetchone()
    last = await dbq.get_meta(db, "last_collection_ts")
    _write(out_dir / "meta.json", {
        "exported_at": datetime.now(UTC).isoformat(),
        "data_as_of": datetime.fromtimestamp(int(last), UTC).isoformat() if last else None,
        "first_close": coverage[0],
        "last_close": coverage[1],
        "thresholds": list(config.STATIC_THRESHOLDS),
        "lookback_days": config.LOOKBACK_DAYS,
        "min_volume": config.MIN_VOLUME,
        "summary_model": config.SUMMARY_MODEL,
    })
    return counts


def _write(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, separators=(",", ":")))
