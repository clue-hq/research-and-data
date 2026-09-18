"""Conversation naming — the metered call writes only placeholders and always drains its spend."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import text

from clue_api.conversation_naming import (
    NAMING_LABEL,
    NamingRequest,
    OpenRouterConversationNamer,
)
from clue_api.thread_store import create_thread, get_thread, set_thread_title
from clue_spend.transport import HttpResponse, ScriptedTransport, TransportFailure
from clue_spine import UNTITLED_PROJECT_NAME, get_project
from tests._identity import seed_principal
from tests._workspace import seed_project
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)


def _reply(chat_title: str, project_name: str) -> HttpResponse:
    body = {
        "choices": [
            {
                "message": {
                    "content": json.dumps({"chat_title": chat_title, "project_name": project_name})
                }
            }
        ],
        "usage": {"prompt_tokens": 250, "completion_tokens": 12, "cost": 0.00006},
    }
    return HttpResponse(
        status=200,
        headers={"content-type": "application/json"},
        body=json.dumps(body).encode(),
    )


def _namer(
    conn, script: list[HttpResponse | TransportFailure]
) -> tuple[OpenRouterConversationNamer, ScriptedTransport]:
    transport = ScriptedTransport(script)
    namer = OpenRouterConversationNamer(
        api_key=SecretStr("test-key"),
        base_url="https://openrouter.invalid/api/v1",
        model="openai/gpt-5.6-luna",
        timeout_s=60.0,
        artifacts=None,
        conn_factory=conn_session_factory(conn),
        transport_factory=lambda: transport,
    )
    return namer, transport


async def _scope(conn, *, project_name: str, thread_title: str | None = None):
    workspace_id = f"ws-namer-{uuid4().hex[:8]}"
    project = await seed_project(conn, workspace_id, name=project_name)
    principal = await seed_principal(
        conn, workspace_id=workspace_id, user_id="usr-namer", membership_id="mem-namer"
    )
    thread = await create_thread(
        conn,
        thread_id=f"thr-namer-{uuid4().hex[:8]}",
        workspace_id=workspace_id,
        project_id=project.project_id,
        title=thread_title,
        created_by_user_id=principal.user_id,
        created_via_membership_id=principal.membership_id,
    )
    return workspace_id, project, thread


def _request(workspace_id: str, project_id: str, thread_id: str) -> NamingRequest:
    return NamingRequest(
        workspace_id=workspace_id,
        project_id=project_id,
        thread_id=thread_id,
        turn_id=uuid4(),
        user_message="Which GI practices in Texas should we go after first?",
        assistant_message="Start with the independent GI groups in Dallas and Houston.",
    )


async def _ledger_rows(conn, turn_id) -> list[dict]:
    rows = (
        (
            await conn.execute(
                text(
                    "SELECT label, phase, outcome, project_id FROM provider_call_ledger "
                    # The turn id is stamped through ``LedgerStamp.job_id``, whose column is
                    # ``entity_research_job_id`` (clue_spend.ledger._INSERT_LEDGER).
                    "WHERE entity_research_job_id = :job ORDER BY recorded_at"
                ),
                {"job": turn_id},
            )
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


def test_home_path_names_both_and_drains_the_ledger(migrated_db: bool) -> None:  # noqa: F811
    if not migrated_db:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            workspace_id, project, thread = await _scope(conn, project_name=UNTITLED_PROJECT_NAME)
            namer, transport = _namer(
                conn, [_reply("Find GI target accounts", "GI practice outreach")]
            )
            request = _request(workspace_id, project.project_id, thread.id)

            outcome = await namer.name(request)

            assert outcome.skipped_reason is None
            assert outcome.chat_title == "Find GI target accounts"
            assert outcome.project_name == "GI practice outreach"
            fetched = await get_thread(conn, workspace_id=workspace_id, thread_id=thread.id)
            assert fetched.title == "Find GI target accounts"
            assert (await get_project(conn, project.project_id)).name == "GI practice outreach"

            sent = json.loads(transport.requests[0].body)
            assert sent["model"] == "openai/gpt-5.6-luna"
            assert sent["reasoning"] == {"effort": "none"}
            assert sent["max_tokens"] == 60
            assert "Needed: chat_title, project_name" in sent["messages"][1]["content"]

            rows = await _ledger_rows(conn, request.turn_id)
            assert [row["label"] for row in rows] == [NAMING_LABEL, NAMING_LABEL]
            assert rows[-1]["phase"] == "result"
            assert rows[-1]["project_id"] == project.project_id

    run_async(scenario())


def test_named_project_asks_only_for_the_chat_title(migrated_db: bool) -> None:  # noqa: F811
    if not migrated_db:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            workspace_id, project, thread = await _scope(conn, project_name="GI practice outreach")
            namer, transport = _namer(conn, [_reply("Texas GI shortlist", "")])

            outcome = await namer.name(_request(workspace_id, project.project_id, thread.id))

            assert outcome == type(outcome)(
                chat_title="Texas GI shortlist", project_name=None, skipped_reason=None
            )
            body = json.loads(transport.requests[0].body)["messages"][1]["content"]
            assert "Project: GI practice outreach" in body
            assert "Needed: chat_title\n" in body
            assert (await get_project(conn, project.project_id)).name == "GI practice outreach"

    run_async(scenario())


def test_already_named_thread_and_project_make_no_call(migrated_db: bool) -> None:  # noqa: F811
    if not migrated_db:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            workspace_id, project, thread = await _scope(
                conn, project_name="Named", thread_title="Mine"
            )
            namer, transport = _namer(conn, [])
            outcome = await namer.name(_request(workspace_id, project.project_id, thread.id))
            assert outcome.skipped_reason == "already_named"
            assert transport.requests == []

    run_async(scenario())


def test_manual_rename_during_the_call_wins(migrated_db: bool) -> None:  # noqa: F811
    if not migrated_db:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            workspace_id, project, thread = await _scope(conn, project_name=UNTITLED_PROJECT_NAME)
            namer, _ = _namer(conn, [_reply("Bot title", "Bot project")])
            # A human title present at call time means the chat slot is not asked for and never
            # written, while the still-untitled project is. The narrower race (the namer READ a
            # null title, the rename landed before its conditional write) is decided by the WHERE
            # clause and is pinned by tests/api/test_thread_naming_store_db.py.
            await set_thread_title(
                conn, workspace_id=workspace_id, thread_id=thread.id, title="Mine"
            )
            outcome = await namer.name(_request(workspace_id, project.project_id, thread.id))
            assert outcome.chat_title is None
            assert outcome.project_name == "Bot project"
            fetched = await get_thread(conn, workspace_id=workspace_id, thread_id=thread.id)
            assert fetched.title == "Mine"

    run_async(scenario())


@pytest.mark.parametrize(
    ("script", "reason"),
    [
        ([TransportFailure("connection reset")], "provider_error"),
        ([HttpResponse(status=500, body=b"{}")], "provider_error"),
        (
            [HttpResponse(status=200, body=b'{"choices":[{"message":{"content":"not json"}}]}')],
            "invalid_reply",
        ),
        ([_reply("", "")], "names_rejected"),
        (
            [_reply("one two three four five six seven eight nine", "Untitled project")],
            "names_rejected",
        ),
    ],
)
def test_failures_skip_loudly_and_leave_placeholders(
    migrated_db: bool,  # noqa: F811
    script,
    reason,
) -> None:
    if not migrated_db:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            workspace_id, project, thread = await _scope(conn, project_name=UNTITLED_PROJECT_NAME)
            namer, _ = _namer(conn, list(script))
            request = _request(workspace_id, project.project_id, thread.id)
            outcome = await namer.name(request)
            assert outcome.skipped_reason == reason
            fetched = await get_thread(conn, workspace_id=workspace_id, thread_id=thread.id)
            assert fetched.title is None
            assert (await get_project(conn, project.project_id)).name == UNTITLED_PROJECT_NAME
            # Money trail is complete even when nothing was written.
            assert await _ledger_rows(conn, request.turn_id)

    run_async(scenario())
