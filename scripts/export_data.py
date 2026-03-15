#!/usr/bin/env python3
"""Export black swan data from SQLite to static JSON files for GitHub Pages."""

import json
import os
import sqlite3
import sys

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "backend", "black_swan.db")
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend", "public", "data")

THRESHOLDS = [0.05, 0.10, 0.15, 0.20, 0.25]


def export():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    os.makedirs(OUT_DIR, exist_ok=True)

    for threshold in THRESHOLDS:
        rows = db.execute(
            """
            SELECT ticker, event_ticker, title, yes_sub_title,
                   prediction_price, prediction_ts, prediction_volume,
                   last_price_dollars,
                   volume_fp, open_interest_fp, close_time, settlement_ts, result,
                   yes_bid_dollars, yes_ask_dollars, rules_primary,
                   category, ai_summary, volume_at_price
            FROM markets
            WHERE result = 'yes' AND prediction_price IS NOT NULL
                  AND prediction_price < ? AND is_sports = 0
            ORDER BY CAST(volume_fp AS REAL) DESC
            LIMIT 500
            """,
            (threshold,),
        ).fetchall()

        black_swans = [dict(r) for r in rows]

        stats_row = db.execute(
            """
            SELECT
                COUNT(*) as total_black_swans,
                AVG(prediction_price) as avg_prediction_price,
                MIN(prediction_price) as lowest_prediction_price,
                SUM(CAST(volume_fp AS REAL)) as total_volume,
                SUM((1.0 - prediction_price) * COALESCE(volume_at_price, 0)) as total_profit_at_price,
                MIN(settlement_ts) as earliest_settlement,
                MAX(settlement_ts) as latest_settlement
            FROM markets
            WHERE result = 'yes' AND prediction_price IS NOT NULL
                  AND prediction_price < ? AND is_sports = 0
            """,
            (threshold,),
        ).fetchone()

        total_row = db.execute(
            "SELECT COUNT(*) FROM markets WHERE prediction_price IS NOT NULL AND is_sports = 0"
        ).fetchone()

        cat_rows = db.execute(
            """
            SELECT
                CASE WHEN category = '' THEN 'Other' ELSE category END as cat,
                COUNT(*) as cnt
            FROM markets
            WHERE result = 'yes' AND prediction_price IS NOT NULL
                  AND prediction_price < ? AND is_sports = 0
            GROUP BY cat ORDER BY cnt DESC
            """,
            (threshold,),
        ).fetchall()

        stats = {
            "total_black_swans": stats_row["total_black_swans"] or 0,
            "total_markets_analyzed": total_row[0],
            "avg_prediction_price": stats_row["avg_prediction_price"],
            "lowest_prediction_price": stats_row["lowest_prediction_price"],
            "total_volume": stats_row["total_volume"] or 0.0,
            "total_profit_at_price": stats_row["total_profit_at_price"] or 0.0,
            "earliest_settlement": stats_row["earliest_settlement"],
            "latest_settlement": stats_row["latest_settlement"],
            "category_stats": [{"category": r["cat"], "count": r["cnt"]} for r in cat_rows],
        }

        pct = int(threshold * 100)
        bs_path = os.path.join(OUT_DIR, f"black-swans-{pct}.json")
        stats_path = os.path.join(OUT_DIR, f"stats-{pct}.json")

        with open(bs_path, "w") as f:
            json.dump({"black_swans": black_swans, "count": len(black_swans)}, f)
        with open(stats_path, "w") as f:
            json.dump(stats, f)

        print(f"  threshold={pct}%: {len(black_swans)} black swans exported")

    db.close()
    print(f"Data exported to {OUT_DIR}")


if __name__ == "__main__":
    export()
