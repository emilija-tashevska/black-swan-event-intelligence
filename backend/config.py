"""Central configuration. Every tunable lives here so the pipeline, API, CLI
and export script agree on paths and definitions."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
load_dotenv(BACKEND_DIR / ".env")

DB_PATH = Path(os.environ.get("BLACK_SWAN_DB", BACKEND_DIR / "black_swan.db"))

# How far before close the "prediction price" is sampled.
LOOKBACK_DAYS = 7
# Markets must have traded for at least a full day before the lookback point;
# a market open exactly 7 days has no candle that closed before it.
MIN_MARKET_DURATION_DAYS = LOOKBACK_DAYS + 1
# Ignore thin markets: lifetime contracts traded.
MIN_VOLUME = 1000.0
# First run fetches markets settled within this window; later runs are incremental.
COLLECTION_WINDOW_DAYS = int(os.environ.get("COLLECTION_WINDOW_DAYS", "180"))

DEFAULT_THRESHOLD = 0.10
# Enrichment (depth, summaries) covers every threshold the dashboard offers.
MAX_THRESHOLD = 0.25
STATIC_THRESHOLDS = (0.05, 0.10, 0.15, 0.20, 0.25)

# Kalshi series categories that are out of scope: sports outcomes and
# multi-leg parlays ("Exotics").
EXCLUDED_CATEGORIES = frozenset({"Sports", "Exotics"})

# When no contracts traded, a bid/ask midpoint is used only if the spread is this tight.
MAX_QUOTE_SPREAD = 0.10

# ±$ tolerance when counting trades "at" the prediction price.
PRICE_TOLERANCE = 0.02

SUMMARY_MODEL = os.environ.get("SUMMARY_MODEL", "claude-haiku-4-5")
SUMMARY_BATCH_SIZE = 20

CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",")
