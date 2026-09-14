import json
from types import SimpleNamespace

import anthropic
import httpx
import pytest
from conftest import db_row, insert_rows

import summaries
from models import Headline, HeadlineBatch


class FakeMessages:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    async def parse(self, **kwargs):
        self.requests.append(kwargs)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def fake_client(*responses):
    return SimpleNamespace(messages=FakeMessages(responses))


def parsed(*pairs, stop_reason="end_turn"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        parsed_output=HeadlineBatch(headlines=[Headline(ticker=t, headline=h) for t, h in pairs]),
    )


def api_error(cls, status):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("err", response=httpx.Response(status, request=req), body=None)


async def seed(db, n):
    rows = [db_row(f"KX-{i}", prediction_status="ok", prediction_price=0.05) for i in range(n)]
    await insert_rows(db, rows)


async def summaries_in(db):
    rows = await (await db.execute(
        "SELECT ticker, ai_summary, ai_model FROM markets ORDER BY ticker")).fetchall()
    return {r[0]: (r[1], r[2]) for r in rows}


async def test_headlines_are_matched_by_ticker_not_position(db):
    await seed(db, 3)
    client = fake_client(parsed(
        ("KX-2", "  Third happened.  "),
        ("KX-0", "First happened."),
        ("KX-INVENTED", "Should be ignored."),
        ("KX-1", "   "),
    ))
    written = await summaries.generate_summaries(db, client, model="claude-haiku-4-5")

    assert written == 2
    assert await summaries_in(db) == {
        "KX-0": ("First happened.", "claude-haiku-4-5"),
        "KX-1": ("", ""),
        "KX-2": ("Third happened.", "claude-haiku-4-5"),
    }
    req = client.messages.requests[0]
    assert req["model"] == "claude-haiku-4-5"
    assert req["output_format"] is HeadlineBatch
    assert req["system"] == summaries.SYSTEM_PROMPT


async def test_request_payload_contains_market_context(db):
    await seed(db, 1)
    client = fake_client(parsed())
    await summaries.generate_summaries(db, client)
    content = client.messages.requests[0]["messages"][0]["content"]
    payload = json.loads(content.split("\n", 1)[1])
    assert payload == [{
        "ticker": "KX-0", "category": "Crypto", "title": "Title for KX-0",
        "yes_outcome": "Yes outcome", "close_date": "2026-02-02",
        "rules": "If X happens, resolves Yes.",
    }]


async def test_batches_and_continues_past_transient_errors(db):
    await seed(db, 5)
    client = fake_client(
        api_error(anthropic.InternalServerError, 500),
        parsed(("KX-2", "c"), ("KX-3", "d")),
        parsed(("KX-4", "e")),
    )
    assert await summaries.generate_summaries(db, client, batch_size=2) == 3
    assert len(client.messages.requests) == 3
    # Failed batch stays queued for the next run
    assert [r["ticker"] for r in await summaries.dbq.black_swans_needing_summary(db, 0.25)] == [
        "KX-0", "KX-1"]


async def test_truncated_or_refused_responses_are_skipped(db):
    await seed(db, 1)
    client = fake_client(parsed(("KX-0", "x"), stop_reason="max_tokens"))
    assert await summaries.generate_summaries(db, client) == 0


@pytest.mark.parametrize(
    ("cls", "status"),
    [(anthropic.AuthenticationError, 401), (anthropic.NotFoundError, 404)],
)
async def test_configuration_errors_abort(db, cls, status):
    await seed(db, 3)
    client = fake_client(api_error(cls, status), parsed())
    with pytest.raises(cls):
        await summaries.generate_summaries(db, client, batch_size=1)


async def test_force_regenerates_existing(db):
    await insert_rows(db, [db_row("KX-0", prediction_status="ok", prediction_price=0.05,
                                  ai_summary="old")])
    assert await summaries.generate_summaries(db, fake_client()) == 0
    assert await summaries.generate_summaries(db, fake_client(parsed(("KX-0", "new"))),
                                              force=True) == 1
    assert (await summaries_in(db))["KX-0"][0] == "new"


async def test_repeated_failures_stop_the_run_instead_of_failing_every_batch(db):
    await seed(db, 10)
    bad_request = api_error(anthropic.BadRequestError, 400)
    client = fake_client(bad_request, bad_request, bad_request, parsed())
    with pytest.raises(summaries.HeadlineGenerationError, match="3 headline batches"):
        await summaries.generate_summaries(db, client, batch_size=2)
    assert len(client.messages.requests) == 3


async def test_a_success_resets_the_failure_count(db):
    await seed(db, 10)
    err = api_error(anthropic.InternalServerError, 500)
    client = fake_client(err, err, parsed(("KX-4", "e")), err, err)
    assert await summaries.generate_summaries(db, client, batch_size=2) == 1
    assert len(client.messages.requests) == 5


def test_claude_client_sends_workspace_header_only_when_configured(monkeypatch):
    import cli

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.delenv("ANTHROPIC_WORKSPACE_ID", raising=False)
    assert "anthropic-workspace-id" not in cli.claude_client().default_headers
    monkeypatch.setenv("ANTHROPIC_WORKSPACE_ID", " wrkspc_123 ")
    assert cli.claude_client().default_headers["anthropic-workspace-id"] == "wrkspc_123"
