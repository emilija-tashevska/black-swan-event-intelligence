"""Command-line entry point for the pipeline.

    uv run python cli.py run            # collect → score → structure → depth → headlines
                                        #   → watchlist → export
    uv run python cli.py collect        # individual steps
    uv run python cli.py headlines --force
    uv run python cli.py stats --threshold 0.05
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys

import anthropic

import collector
import config
import database as dbq
from export import export_static
from kalshi import KalshiClient
from structure import enrich_structures
from summaries import generate_summaries
from watchlist import collect_open_markets

logger = logging.getLogger("cli")

STEPS = ("collect", "score", "structure", "depth", "headlines", "watchlist", "export")


def claude_client() -> anthropic.AsyncAnthropic:
    """Keys that aren't scoped to a workspace must name one on every request."""
    headers = {}
    if workspace := os.environ.get("ANTHROPIC_WORKSPACE_ID", "").strip():
        headers["anthropic-workspace-id"] = workspace
    return anthropic.AsyncAnthropic(default_headers=headers)


async def run_steps(steps: list[str], force_headlines: bool = False) -> None:
    async with dbq.connect() as db, KalshiClient() as kalshi:
        if "collect" in steps:
            resolver = await collector.CategoryResolver.load(kalshi)
            logger.info("Collect: %s", await collector.collect_markets(kalshi, db, resolver))
        if "score" in steps:
            logger.info("Score: %s", await collector.score_predictions(kalshi, db))
        if "structure" in steps:
            logger.info("Structure: %s", await enrich_structures(kalshi, db))
        if "depth" in steps:
            logger.info("Depth: %d markets", await collector.enrich_depth(kalshi, db))
        if "headlines" in steps:
            if os.environ.get("ANTHROPIC_API_KEY"):
                async with claude_client() as claude:
                    n = await generate_summaries(db, claude, force=force_headlines)
                logger.info("Headlines: %d written", n)
            else:
                logger.warning("ANTHROPIC_API_KEY not set (backend/.env); skipping headlines")
        if "watchlist" in steps:
            resolver = await collector.CategoryResolver.load(kalshi)
            logger.info("Watchlist: %d markets", await collect_open_markets(kalshi, db, resolver))
            logger.info("Watchlist structures: %s", await enrich_structures(kalshi, db))
        if "export" in steps:
            logger.info("Export: %s", await export_static(db))


async def print_stats(threshold: float) -> None:
    async with dbq.connect() as db:
        print(json.dumps(await dbq.query_stats(db, threshold), indent=2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Black Swan Event Intelligence pipeline")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="run every step in order")
    for step in STEPS:
        p = sub.add_parser(step, help=f"run only the {step} step")
        if step == "headlines":
            p.add_argument("--force", action="store_true", help="regenerate existing headlines")
    stats = sub.add_parser("stats", help="print summary stats from the database")
    stats.add_argument("--threshold", type=float, default=config.DEFAULT_THRESHOLD)
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if args.command == "stats":
        asyncio.run(print_stats(args.threshold))
    elif args.command == "run":
        asyncio.run(run_steps(list(STEPS)))
    else:
        asyncio.run(run_steps([args.command], force_headlines=getattr(args, "force", False)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
