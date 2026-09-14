"""One-line, past-tense headlines for black swan markets, generated with Claude."""

from __future__ import annotations

import json
import logging

import aiosqlite
import anthropic

import config
import database as dbq
from models import HeadlineBatch

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You write headlines for a dashboard of prediction-market "black swans": Kalshi \
markets that resolved YES even though traders priced that outcome as unlikely a \
week before the market closed.

For each market, write one factual, past-tense headline of at most 18 words \
stating what actually happened. The YES outcome is what occurred. Use the rules \
text to pin down specifics such as the asset, city, company, person, threshold \
or date, and include them. Describe the real-world event, not the market: don't \
mention probabilities, prices, trading or Kalshi, and don't speculate about causes.

Make every number self-explanatory. Say what it measures, using the rules text. \
When the rules define it by a named data source or index, name that source and \
don't add units or scale the rules don't state: "Carbon Arc's Amazon credit card \
spend index topped 109 for August 2026", not "Amazon spending exceeded $109". \
For word-mention markets, quote the word and say who said it where.

Return exactly one headline per input ticker, using the ticker unchanged."""

RULES_CHAR_LIMIT = 800
# Stop after this many failed batches in a row: that's a configuration problem
# (bad key, missing workspace, ...), not a flaky request.
MAX_CONSECUTIVE_FAILURES = 3


class HeadlineGenerationError(RuntimeError):
    pass


def build_user_message(markets: list[aiosqlite.Row | dict]) -> str:
    payload = [
        {
            "ticker": m["ticker"],
            "category": m["category"],
            "title": m["title"],
            "yes_outcome": m["yes_sub_title"],
            "close_date": (m["close_time"] or "")[:10],
            "rules": (m["rules_primary"] or "")[:RULES_CHAR_LIMIT],
        }
        for m in markets
    ]
    return "Markets:\n" + json.dumps(payload, indent=1, ensure_ascii=False)


async def headline_batch(
    client: anthropic.AsyncAnthropic, model: str, markets: list[aiosqlite.Row | dict],
) -> dict[str, str]:
    """Headlines keyed by ticker. Tickers the model invents or omits are dropped,
    so a skipped item can never shift another market's headline."""
    response = await client.messages.parse(
        model=model,
        max_tokens=4000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_user_message(markets)}],
        output_format=HeadlineBatch,
    )
    if response.stop_reason != "end_turn" or response.parsed_output is None:
        logger.warning("Headline batch stopped with %s; skipping", response.stop_reason)
        return {}
    wanted = {m["ticker"] for m in markets}
    return {
        h.ticker: h.headline.strip()
        for h in response.parsed_output.headlines
        if h.ticker in wanted and h.headline.strip()
    }


async def generate_summaries(
    db: aiosqlite.Connection,
    client: anthropic.AsyncAnthropic,
    model: str = config.SUMMARY_MODEL,
    force: bool = False,
    batch_size: int = config.SUMMARY_BATCH_SIZE,
) -> int:
    markets = await dbq.black_swans_needing_summary(db, config.MAX_THRESHOLD, force=force)
    logger.info("Generating headlines for %d markets with %s", len(markets), model)
    written = 0
    failures = 0
    for start in range(0, len(markets), batch_size):
        batch = markets[start : start + batch_size]
        try:
            headlines = await headline_batch(client, model, batch)
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError,
                anthropic.NotFoundError):
            raise  # misconfiguration: stop instead of failing every batch
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
            failures += 1
            logger.warning("Headline batch at %d failed: %s", start, e)
            if failures >= MAX_CONSECUTIVE_FAILURES:
                raise HeadlineGenerationError(
                    f"{failures} headline batches failed in a row; last error: {e}"
                ) from e
            continue
        failures = 0
        await dbq.set_ai_summaries(db, headlines.items(), model)
        written += len(headlines)
        if len(headlines) < len(batch):
            logger.warning("Batch at %d: %d of %d headlines returned", start,
                           len(headlines), len(batch))
        logger.info("Headlines: %d / %d", start + len(batch), len(markets))
    return written
