"""Answering the CRM write permission card, and its progress read (CRM integration Phase 2, Task 7).

The card is opened by the real ``propose_crm_changes@1`` (over a fake CRM) and answered through the
real turn route as a ``gate_response``. Proves: Allow queues the ticked changes, records each
"Always allow" as a standing permission of the proposal's connection and offers the connection's
write executor; Don't allow declines the whole proposal, changes a standing permission covered
included; a replaced card, a card whose CRM was reconnected, an unknown change, an empty selection
and an overwrite's scope are refused with nothing written; any member of the workspace answers,
once; and ``GET /crm/proposals/{id}`` reports the outcome with the CRM's own messages.

DB-backed and rollback-only, on the lane's test DB.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import Request
from httpx import ASGITransport
from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from clue_api.agent_gate import (
    KIND_DIRECTIVE_CONFIRMATION,
    get_gate,
    insert_gate,
    insert_gate_answer,
    open_gates_for_thread,
)
from clue_api.chat import CHAT_PERMISSIONS, RequestPrincipal
from clue_api.crm import writes
from clue_api.crm.connections import mark_expired
from clue_api.crm.lists import store_list
from clue_api.crm.write_executor import close_replaced_connection_proposals
from clue_api.crm.write_tools import (
    CrmChangeInput,
    ProposeCrmChangesInput,
    ProposeCrmChangesTool,
)
from clue_api.execution_wiring import build_tool_invoker
from clue_api.frontend_read import FRONTEND_READ_PREFIX
from clue_api.frontend_read.app import frontend_read_workspace_resolver
from clue_api.projections_app import create_projections_app
from clue_api.thread_wiring import register_thread_tools
from clue_api.turn_action import derive_turn_action_ref
from clue_auth.policy import permissions_for_role
from clue_config import load_settings
from clue_core import new_operation_id
from clue_projections import open_gate_kinds_for_threads, thread_gates
from clue_storage import FsStorage
from clue_toolbelt import DbIdempotencyStore, ToolContext, ToolRegistry
from tests.api._crm_people import clear_people
from tests.api.test_crm_tools_db import _connect
from tests.api.test_crm_write_prepare_db import _FakeCrm
from tests.api.test_lane_d4_agent_gate_db import OTHER_USER_ID, USER_ID, _seed
from tests.api.test_lane_d4_gate_response_route_db import _AUTHENTICATED_AT, _MemoryStorage
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)
from tests.projections._helpers import build_surface

PROPOSALS = f"{FRONTEND_READ_PREFIX}/crm/proposals"


@pytest.fixture(autouse=True)
def require_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


class _FakeQueue:
    async def enqueue(self, **_: Any) -> bool:
        return True


def _settings() -> Any:
    return load_settings(_env_file=None, chat_enabled=True, frontend_read_enabled=True)


def _app(conn: Any, seeded: Any, user_id: str) -> Any:
    cf = conn_session_factory(conn)
    registry = ToolRegistry()
    register_thread_tools(registry, conn_factory=cf)
    settings = _settings()

    def chat_principal(workspace_id: str) -> RequestPrincipal:
        return RequestPrincipal(
            user_id=user_id,
            membership_id=f"wsm_d4_{seeded.label}_{user_id}",
            workspace_id=workspace_id,
            role_key="operator",
            permissions=CHAT_PERMISSIONS,
            authenticated_at=_AUTHENTICATED_AT,
        )

    app = create_projections_app(
        surface=build_surface(conn),
        tool_invoker=build_tool_invoker(
            registry=registry,
            idempotency_store=DbIdempotencyStore(conn_factory=cf),
            storage=_MemoryStorage(),
            settings=settings,
            conn_factory=cf,
        ),
        settings=settings,
        conn_factory=cf,
        manage_db_lifespan=False,
        ingestion_storage=seeded.storage,
        chat_principal_resolver=chat_principal,
    )

    async def workspace(request: Request) -> str:
        workspace_id = request.headers["X-Workspace-Id"]
        request.state.clue_principal = RequestPrincipal(
            user_id=user_id,
            membership_id=f"wsm_d4_{seeded.label}_{user_id}",
            workspace_id=workspace_id,
            role_key="viewer",
            permissions=permissions_for_role("viewer"),
            authenticated_at=_AUTHENTICATED_AT,
        )
        return workspace_id

    app.dependency_overrides[frontend_read_workspace_resolver] = workspace
    return app


def _set_tier(record: str, tier: str) -> CrmChangeInput:
    return CrmChangeInput(
        slug="HUBSPOT_UPDATE_COMPANY",
        arguments={"companyId": record, "properties": {"icp_tier": tier}},
        reason="The ICP tiers Clue scored for this project.",
    )


def _set_title(record: str) -> CrmChangeInput:
    return CrmChangeInput(
        slug="HUBSPOT_UPDATE_CONTACTS",
        arguments={"inputs": [{"id": record, "properties": {"jobtitle": "VP Revenue"}}]},
        reason="The title the research found.",
    )


def _add_to_list(record: str) -> CrmChangeInput:
    return CrmChangeInput(
        slug="HUBSPOT_UPDATE_LIST_MEMBERSHIPS",
        arguments={"list_id": "9", "operation": "add", "record_ids": [record]},
        reason="The buying committee Clue found.",
    )


#: 101 and 103 hold no tier (fills); 102 holds a tier a person set (an overwrite); contact 104
#: holds a job title a person set (an overwrite whose scope no fill on the card shares).
_RECORDS = {
    "101": {"icp_tier": None},
    "102": {"icp_tier": "Tier 3"},
    "103": {"icp_tier": ""},
    "104": {"jobtitle": "Sales lead"},
}


async def _propose(conn: Any, seeded: Any, *changes: CrmChangeInput) -> dict[str, Any]:
    tool = ProposeCrmChangesTool(
        settings=_settings(),
        gateway=_FakeCrm(records=_RECORDS),  # type: ignore[arg-type]
        conn_factory=conn_session_factory(conn),
        work_queue=_FakeQueue(),  # type: ignore[arg-type]
    )
    inputs = ProposeCrmChangesInput(
        changes=await clear_people(conn, seeded, changes),
        source_turn_ref=derive_turn_action_ref(seeded.turn_id),
    )
    ctx = ToolContext(
        workspace_id=seeded.workspace_id,
        actor="agent",
        conn_factory=conn_session_factory(conn),
        operation_id=new_operation_id(),
    )
    return (await tool.invoke(inputs, ctx)).references


async def _snapshot(conn: Any, seeded: Any, proposed: dict[str, Any]) -> dict[str, Any]:
    view = await get_gate(conn, workspace_id=seeded.workspace_id, gate_id=UUID(proposed["gate_id"]))
    assert view is not None
    return {"digest": view.gate.expected_subject_sha256, **view.gate.subject_snapshot}


def _ids_in(snapshot: dict[str, Any], record: str) -> list[str]:
    ids = [
        item["write_id"]
        for group in snapshot["groups"]
        for item in group["records"]
        if item["record_ref"] == record
    ]
    ids += [item["write_id"] for item in snapshot["overwrites"] if item["record_ref"] == record]
    return ids


async def _answer(
    client: httpx.AsyncClient,
    seeded: Any,
    proposed: dict[str, Any],
    snapshot: dict[str, Any],
    *,
    key: str,
    decision: str = "approved",
    selected: list[str] | None = None,
    always_allow: list[str] | None = None,
) -> httpx.Response:
    response: dict[str, Any] = {
        "gate_id": proposed["gate_id"],
        "decision": decision,
        "expected_subject_sha256": snapshot["digest"],
    }
    if selected is not None or always_allow is not None:
        response["crm_write"] = {
            "selected_write_ids": selected or [],
            "always_allow": always_allow or [],
        }
    return await client.post(
        f"/api/v1/projects/{seeded.project_id}/threads/{seeded.thread_id}/turns",
        json={"gate_response": response},
        headers={"X-Workspace-Id": seeded.workspace_id, "Idempotency-Key": key},
    )


async def _writes(conn: Any, proposal_id: str) -> dict[str, tuple[bool, str | None]]:
    rows = await conn.execute(
        text("SELECT record_ref, selected, covered_by FROM crm_write WHERE proposal_id = :id"),
        {"id": UUID(proposal_id)},
    )
    return {row.record_ref: (row.selected, row.covered_by) for row in rows}


async def _proposal(conn: Any, proposal_id: str) -> Any:
    return (
        await conn.execute(
            text(
                "SELECT status, answered_by_user_id, answered_at FROM crm_write_proposal "
                "WHERE proposal_id = :id"
            ),
            {"id": UUID(proposal_id)},
        )
    ).one()


async def _offers(conn: Any, connection_id: UUID) -> int:
    result = await conn.execute(
        text("SELECT count(*) FROM fleet_task WHERE kind = 'crm_write' AND work_id = :id"),
        {"id": str(connection_id)},
    )
    return int(result.scalar_one())


async def _grants(conn: Any, workspace_id: str) -> list[tuple[str, UUID, str]]:
    rows = await conn.execute(
        text(
            "SELECT scope_kind, connection_id, granted_by_user_id FROM crm_write_grant "
            "WHERE workspace_id = :ws AND revoked_at IS NULL ORDER BY granted_at"
        ),
        {"ws": workspace_id},
    )
    return [(row.scope_kind, row.connection_id, row.granted_by_user_id) for row in rows]


async def _answers(conn: Any, workspace_id: str) -> int:
    result = await conn.execute(
        text("SELECT count(*) FROM agent_gate_answer WHERE workspace_id = :ws"),
        {"ws": workspace_id},
    )
    return int(result.scalar_one())


def _run(tmp_path: Path, label: str, body: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id=f"ws-crma-{label}", label=label)
            seeded.label = label
            seeded.storage = FsStorage(tmp_path / f"crm-answer-{label}")
            connection = await _connect(conn, seeded.workspace_id)
            # The contact list these tests add to is one Clue keeps (Phase 3, fix round 1 #1).
            await store_list(
                conn,
                workspace_id=seeded.workspace_id,
                connection_id=connection.connection_id,
                provider="hubspot",
                crm_object="contact",
                crm_list_id="9",
                name="Q4 committee",
                kind="hubspot_list",
                created_by_clue=True,
                created_by_write_id=None,
                project_id=seeded.project_id,
            )
            await body(conn, seeded, connection)

    run_async(scenario())


def _client(conn: Any, seeded: Any, user_id: str = USER_ID) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=ASGITransport(app=_app(conn, seeded, user_id)), base_url="http://t"
    )


def test_allow_queues_the_selected_changes_and_records_always_allow(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        proposed = await _propose(
            conn,
            seeded,
            _set_tier("101", "Tier 1"),
            _set_tier("102", "Tier 1"),
            _set_tier("103", "Tier 2"),
            _add_to_list("501"),
        )
        snapshot = await _snapshot(conn, seeded, proposed)
        chosen = _ids_in(snapshot, "101") + _ids_in(snapshot, "102") + _ids_in(snapshot, "501")
        async with _client(conn, seeded) as client:
            response = await _answer(
                client,
                seeded,
                proposed,
                snapshot,
                key="allow",
                # A repeated id is the same choice.
                selected=[*chosen, chosen[0]],
                always_allow=["kind:list_membership", "kind:list_membership"],
            )
        assert response.status_code == 202, response.text

        gate_cover = f"gate:{proposed['gate_id']}"
        assert await _writes(conn, proposed["proposal_id"]) == {
            "101": (True, gate_cover),
            "102": (True, gate_cover),
            "103": (False, None),
            "501": (True, gate_cover),
        }
        proposal = await _proposal(conn, proposed["proposal_id"])
        assert proposal.status == "queued"
        assert proposal.answered_by_user_id == USER_ID and proposal.answered_at is not None
        assert await _grants(conn, seeded.workspace_id) == [
            ("kind", connection.connection_id, USER_ID)
        ]
        assert await _offers(conn, connection.connection_id) == 1

        # The agent reads what was decided, in words.
        message = await conn.scalar(
            text(
                "SELECT a.decision_payload::text FROM agent_gate_answer a WHERE a.gate_id = :gate"
            ),
            {"gate": UUID(proposed["gate_id"])},
        )
        assert json.loads(message) == {
            "selected_write_ids": sorted(chosen, key=chosen.index),
            "always_allow": ["kind:list_membership"],
        }
        captured = await _captured_message(conn, seeded, "allow")
        assert captured["crm_write"]["summary"] == (
            "Allowed 3 of 4 changes; always allow adding records to Clue lists and campaigns."
        )

    _run(tmp_path, "allow", body)


async def _captured_message(conn: Any, seeded: Any, key: str) -> dict[str, Any]:
    """The bytes the answering turn was captured as (what the agent receives)."""
    from clue_api.agent_turn_submission import turn_id_for_submission

    turn_id = turn_id_for_submission(
        workspace_id=seeded.workspace_id, thread_id=seeded.thread_id, idempotency_key=key
    )
    key_row = (
        await conn.execute(
            text("SELECT message_artifact_key FROM agent_turn_submission WHERE turn_id = :id"),
            {"id": turn_id},
        )
    ).scalar_one()
    captured: dict[str, Any] = json.loads(await seeded.storage.get(key_row))
    return captured


def test_dont_allow_declines_and_sends_nothing(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        # Adding to lists is already allowed: that change waits in the batch with the asked ones.
        await writes.insert_grant(
            conn,
            workspace_id=seeded.workspace_id,
            connection_id=connection.connection_id,
            scope_key="kind:list_membership",
            granted_by_user_id=USER_ID,
        )
        proposed = await _propose(conn, seeded, _set_tier("101", "Tier 1"), _add_to_list("501"))
        assert (proposed["covered"], proposed["needs_permission"]) == (1, 1)
        snapshot = await _snapshot(conn, seeded, proposed)
        async with _client(conn, seeded) as client:
            response = await _answer(
                client, seeded, proposed, snapshot, key="decline", decision="rejected"
            )
        assert response.status_code == 202, response.text
        proposal = await _proposal(conn, proposed["proposal_id"])
        assert proposal.status == "declined"
        assert proposal.answered_by_user_id == USER_ID
        assert await _offers(conn, connection.connection_id) == 0
        statuses = await conn.execute(
            text("SELECT DISTINCT status FROM crm_write WHERE proposal_id = :id"),
            {"id": UUID(proposed["proposal_id"])},
        )
        assert {row.status for row in statuses} == {"proposed"}
        captured = await _captured_message(conn, seeded, "decline")
        assert captured["crm_write"]["summary"] == (
            "Did not allow these changes; nothing was sent, including the 1 change a standing "
            "permission covered."
        )

    _run(tmp_path, "decline", body)


def test_a_replaced_card_cannot_be_answered(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        first = await _propose(conn, seeded, _set_tier("101", "Tier 1"))
        first_snapshot = await _snapshot(conn, seeded, first)
        await _propose(conn, seeded, _set_tier("101", "Tier 2"))
        async with _client(conn, seeded) as client:
            response = await _answer(
                client,
                seeded,
                first,
                first_snapshot,
                key="old",
                selected=_ids_in(first_snapshot, "101"),
            )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "GATE_REPLACED"
        assert (await _proposal(conn, first["proposal_id"])).status == "replaced"
        assert await _answers(conn, seeded.workspace_id) == 0

    _run(tmp_path, "replaced", body)


def test_a_card_whose_crm_was_reconnected_cannot_be_answered(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        proposed = await _propose(conn, seeded, _set_tier("101", "Tier 1"))
        snapshot = await _snapshot(conn, seeded, proposed)
        await _connect(conn, seeded.workspace_id, provider="salesforce")
        async with _client(conn, seeded) as client:
            response = await _answer(
                client,
                seeded,
                proposed,
                snapshot,
                key="moved",
                selected=_ids_in(snapshot, "101"),
            )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "CRM_CONNECTION_CHANGED"
        assert await _answers(conn, seeded.workspace_id) == 0

    _run(tmp_path, "reconnected", body)


@pytest.mark.parametrize(
    ("selection", "code"),
    [("unknown", "CRM_WRITE_UNKNOWN_CHANGE"), ("nothing", "CRM_WRITE_NOTHING_SELECTED")],
)
def test_a_selection_must_name_changes_of_this_card(
    tmp_path: Path, selection: str, code: str
) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        proposed = await _propose(conn, seeded, _set_tier("101", "Tier 1"))
        snapshot = await _snapshot(conn, seeded, proposed)
        chosen = [*_ids_in(snapshot, "101"), str(uuid4())] if selection == "unknown" else []
        async with _client(conn, seeded) as client:
            response = await _answer(
                client, seeded, proposed, snapshot, key=selection, selected=chosen
            )
            assert response.status_code == 422, response.text
            assert response.json()["error"]["code"] == code
            # An approval with no choices at all is the same refusal.
            if selection == "nothing":
                bare = await _answer(client, seeded, proposed, snapshot, key="bare")
                assert bare.json()["error"]["code"] == code
        assert await _answers(conn, seeded.workspace_id) == 0
        assert (await _proposal(conn, proposed["proposal_id"])).status == "awaiting_permission"

    _run(tmp_path, f"sel-{selection}", body)


def test_an_overwrite_scope_is_never_granted(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        proposed = await _propose(conn, seeded, _set_tier("101", "Tier 1"), _set_title("104"))
        snapshot = await _snapshot(conn, seeded, proposed)
        assert [o["record_ref"] for o in snapshot["overwrites"]] == ["104"]
        async with _client(conn, seeded) as client:
            response = await _answer(
                client,
                seeded,
                proposed,
                snapshot,
                key="overwrite-scope",
                selected=_ids_in(snapshot, "101") + _ids_in(snapshot, "104"),
                always_allow=["field:contact.jobtitle"],
            )
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "CRM_WRITE_SCOPE_NOT_OFFERED"
        assert await _grants(conn, seeded.workspace_id) == []
        assert await _answers(conn, seeded.workspace_id) == 0

    _run(tmp_path, "overwrite-scope", body)


def test_a_card_is_answered_once_by_any_member(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        proposed = await _propose(conn, seeded, _set_tier("101", "Tier 1"))
        snapshot = await _snapshot(conn, seeded, proposed)
        chosen = _ids_in(snapshot, "101")
        # The card asked USER_ID; a colleague answers it (R-6.8).
        async with _client(conn, seeded, OTHER_USER_ID) as client:
            first = await _answer(client, seeded, proposed, snapshot, key="m1", selected=chosen)
            assert first.status_code == 202, first.text
            replay = await _answer(client, seeded, proposed, snapshot, key="m1", selected=chosen)
            assert replay.status_code == 202 and replay.json()["data"]["replayed"] is True
        # The addressee, in another tab, is too late.
        async with _client(conn, seeded) as client:
            second = await _answer(
                client, seeded, proposed, snapshot, key="m2", decision="rejected"
            )
        assert second.status_code == 409, second.text
        assert second.json()["error"]["code"] == "GATE_ALREADY_ANSWERED"
        proposal = await _proposal(conn, proposed["proposal_id"])
        assert (proposal.status, proposal.answered_by_user_id) == ("queued", OTHER_USER_ID)
        assert await _answers(conn, seeded.workspace_id) == 1

    _run(tmp_path, "once", body)


@pytest.mark.parametrize("status", ["queued", "sending", "finished", "declined"])
def test_an_answer_that_lost_the_race_says_someone_answered_first(
    tmp_path: Path, status: str
) -> None:
    """Final review M-1: a colleague's answer moved the proposal on a moment before this one (its
    gate answer not yet visible to this request): the click is told someone answered first, never
    that the card is stale."""

    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        proposed = await _propose(conn, seeded, _set_tier("101", "Tier 1"))
        snapshot = await _snapshot(conn, seeded, proposed)
        await writes.set_proposal_status(
            conn,
            proposal_id=UUID(proposed["proposal_id"]),
            status=status,
            answered_by_user_id=OTHER_USER_ID,
        )
        async with _client(conn, seeded) as client:
            response = await _answer(
                client, seeded, proposed, snapshot, key="late", selected=_ids_in(snapshot, "101")
            )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "CRM_WRITE_ALREADY_ANSWERED"
        assert await _answers(conn, seeded.workspace_id) == 0

    _run(tmp_path, f"race-{status}", body)


def test_a_card_closed_unanswered_is_stale_not_answered(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        proposed = await _propose(conn, seeded, _set_tier("101", "Tier 1"))
        snapshot = await _snapshot(conn, seeded, proposed)
        # Closed by the system (a reconnect), with nobody's answer.
        await writes.set_proposal_status(
            conn, proposal_id=UUID(proposed["proposal_id"]), status="finished"
        )
        async with _client(conn, seeded) as client:
            response = await _answer(
                client, seeded, proposed, snapshot, key="closed", selected=_ids_in(snapshot, "101")
            )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "GATE_SUBJECT_STALE"

    _run(tmp_path, "closed-unanswered", body)


def test_the_turn_list_names_the_gate_a_turn_answered(tmp_path: Path) -> None:
    """R-11.4: the chat hides a card answer's message bubble by the answer row, never by text.

    The turn list carries ``answered_gate_id`` for the turn that answered a card and ``None`` for
    every other turn, so the client can render no user bubble for the answer. A card whose answer
    the agent replies to (here a research directive) is the one that has such a turn: a CRM write
    card's answer is recorded with no turn at all (R-11.6).
    """

    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        await _seeded_turn_ran(conn, seeded)
        gate = await _directive_gate(conn, seeded)
        async with _client(conn, seeded) as client:
            answered = await client.post(
                f"/api/v1/projects/{seeded.project_id}/threads/{seeded.thread_id}/turns",
                json={
                    "gate_response": {
                        "gate_id": str(gate.gate_id),
                        "decision": "rejected",
                        "expected_subject_sha256": gate.expected_subject_sha256,
                    }
                },
                headers={"X-Workspace-Id": seeded.workspace_id, "Idempotency-Key": "r114"},
            )
            assert answered.status_code == 202, answered.text
            listing = await client.get(
                f"/api/v1/projects/{seeded.project_id}/threads/{seeded.thread_id}/turns",
                headers={"X-Workspace-Id": seeded.workspace_id},
            )
        assert listing.status_code == 200, listing.text
        by_turn = {item["turn_id"]: item for item in listing.json()["data"]}
        answer_turn = answered.json()["data"]["turn_id"]
        assert by_turn[answer_turn]["answered_gate_id"] == str(gate.gate_id)
        others = [item for turn_id, item in by_turn.items() if turn_id != answer_turn]
        assert all(item["answered_gate_id"] is None for item in others)
        # The agent replies to this card's answer: the route says so and the turn is offered.
        assert answered.json()["data"]["agent_reply"] == "expected"
        assert await _agent_turn_tasks(conn, seeded, UUID(answer_turn)) == 1

    _run(tmp_path, "answered-gate-id", body)


# --- R-11.3 / R-11.6: answering the write card starts no agent turn --------------------------


async def _seeded_turn_ran(conn: Any, seeded: Any) -> None:
    """Mark the seeded turn (the one that showed the card) as run, as it is in production."""
    from clue_api.agent_turn_submission import agent_turn_dedup_key, thread_work_id
    from clue_core import ProjectRunId
    from clue_fleet import FleetTaskKind, enqueue_task

    await enqueue_task(
        conn,
        kind=FleetTaskKind.AGENT_TURN,
        project_run_id=ProjectRunId(
            thread_work_id(workspace_id=seeded.workspace_id, thread_id=seeded.thread_id)
        ),
        dedup_key=agent_turn_dedup_key(seeded.turn_id),
    )
    await conn.execute(
        text("UPDATE fleet_task SET status = 'done' WHERE dedup_key = :key"),
        {"key": agent_turn_dedup_key(seeded.turn_id)},
    )


async def _directive_gate(conn: Any, seeded: Any) -> Any:
    gate, _ = await insert_gate(
        conn,
        gate_id=uuid4(),
        workspace_id=seeded.workspace_id,
        project_id=seeded.project_id,
        thread_id=seeded.thread_id,
        turn_id=seeded.turn_id,
        kind=KIND_DIRECTIVE_CONFIRMATION,
        subject_ref="research-directive:33333333-3333-4333-8333-333333333333:v1",
        subject_revision=1,
        expected_subject_sha256="d" * 64,
        subject_snapshot={"research_directive_id": str(uuid4())},
        max_spend_cents=None,
        currency=None,
        addressee_user_id=USER_ID,
    )
    return gate


async def _agent_turn_tasks(conn: Any, seeded: Any, turn_id: UUID | None = None) -> int:
    from clue_api.agent_turn_submission import agent_turn_dedup_key, thread_work_id

    result = await conn.execute(
        text(
            "SELECT count(*) FROM fleet_task WHERE kind = 'agent_turn' AND work_id = :work "
            "AND (CAST(:key AS text) IS NULL OR dedup_key = :key)"
        ),
        {
            "work": str(
                thread_work_id(workspace_id=seeded.workspace_id, thread_id=seeded.thread_id)
            ),
            "key": None if turn_id is None else agent_turn_dedup_key(turn_id),
        },
    )
    return int(result.scalar_one())


async def _turn_list(client: httpx.AsyncClient, seeded: Any) -> list[str]:
    listing = await client.get(
        f"/api/v1/projects/{seeded.project_id}/threads/{seeded.thread_id}/turns",
        headers={"X-Workspace-Id": seeded.workspace_id},
    )
    assert listing.status_code == 200, listing.text
    return [item["turn_id"] for item in listing.json()["data"]]


async def _assert_no_turn(conn: Any, client: httpx.AsyncClient, seeded: Any, turn_id: str) -> None:
    """The answer is recorded and nothing runs, and nothing waits on it."""
    from clue_api.agent_turn_submission import dispatch_next_thread_turn

    assert await _agent_turn_tasks(conn, seeded, UUID(turn_id)) == 0
    # Only the seeded turn ever ran on this thread.
    assert await _agent_turn_tasks(conn, seeded) == 1
    assert (
        await dispatch_next_thread_turn(
            conn, workspace_id=seeded.workspace_id, thread_id=seeded.thread_id
        )
        is None
    )
    assert await _agent_turn_tasks(conn, seeded) == 1
    assert turn_id not in await _turn_list(client, seeded)
    assert await _thread_status(client, seeded) != "running"
    accepted = await conn.scalar(
        text("SELECT count(*) FROM agent_turn_event_stream WHERE turn_id = :turn"),
        {"turn": UUID(turn_id)},
    )
    assert accepted == 0


def test_allow_records_the_answer_and_starts_no_turn(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        await _seeded_turn_ran(conn, seeded)
        proposed = await _propose(conn, seeded, _set_tier("101", "Tier 1"))
        snapshot = await _snapshot(conn, seeded, proposed)
        async with _client(conn, seeded) as client:
            response = await _answer(
                client,
                seeded,
                proposed,
                snapshot,
                key="nr-allow",
                selected=_ids_in(snapshot, "101"),
            )
            assert response.status_code == 202, response.text
            assert response.json()["data"]["agent_reply"] == "none"
            assert await _answers(conn, seeded.workspace_id) == 1
            assert await _offers(conn, connection.connection_id) == 1
            assert (await _proposal(conn, proposed["proposal_id"])).status == "queued"
            await _assert_no_turn(conn, client, seeded, response.json()["data"]["turn_id"])

            # A retried click answers once and queues once, and still starts no turn.
            replay = await _answer(
                client,
                seeded,
                proposed,
                snapshot,
                key="nr-allow",
                selected=_ids_in(snapshot, "101"),
            )
            assert replay.status_code == 202, replay.text
            assert replay.json()["data"]["replayed"] is True
            assert replay.json()["data"]["agent_reply"] == "none"
            assert replay.json()["data"]["turn_id"] == response.json()["data"]["turn_id"]
            assert await _answers(conn, seeded.workspace_id) == 1
            assert await _offers(conn, connection.connection_id) == 1
            await _assert_no_turn(conn, client, seeded, response.json()["data"]["turn_id"])

    _run(tmp_path, "no-reply-allow", body)


def test_dont_allow_records_the_answer_and_starts_no_turn(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        await _seeded_turn_ran(conn, seeded)
        proposed = await _propose(conn, seeded, _set_tier("101", "Tier 1"))
        snapshot = await _snapshot(conn, seeded, proposed)
        async with _client(conn, seeded) as client:
            response = await _answer(
                client, seeded, proposed, snapshot, key="nr-decline", decision="rejected"
            )
            assert response.status_code == 202, response.text
            assert response.json()["data"]["agent_reply"] == "none"
            assert await _answers(conn, seeded.workspace_id) == 1
            assert await _offers(conn, connection.connection_id) == 0
            assert (await _proposal(conn, proposed["proposal_id"])).status == "declined"
            await _assert_no_turn(conn, client, seeded, response.json()["data"]["turn_id"])

    _run(tmp_path, "no-reply-decline", body)


async def _name(conn: Any, user_id: str, name: str) -> None:
    await conn.execute(
        text("UPDATE platform_user SET display_name = :name WHERE user_id = :user"),
        {"name": name, "user": user_id},
    )


def test_the_results_message_names_who_allowed_what(tmp_path: Path) -> None:
    from clue_api.agent_turn_wiring import DurableAgentArtifactStore
    from clue_api.crm.wake import queue_crm_writes_finished_turn

    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        await _name(conn, USER_ID, "Aryan Keshri")
        proposed = await _propose(
            conn,
            seeded,
            _set_tier("101", "Tier 1"),
            _set_tier("103", "Tier 2"),
            _add_to_list("501"),
        )
        snapshot = await _snapshot(conn, seeded, proposed)
        async with _client(conn, seeded) as client:
            response = await _answer(
                client,
                seeded,
                proposed,
                snapshot,
                key="nr-wake",
                selected=_ids_in(snapshot, "101") + _ids_in(snapshot, "501"),
                always_allow=["kind:list_membership"],
            )
        assert response.status_code == 202, response.text
        await conn.execute(
            text("UPDATE crm_write SET status = 'succeeded' WHERE proposal_id = :id AND selected"),
            {"id": UUID(proposed["proposal_id"])},
        )
        proposal = await writes.get_proposal(conn, proposal_id=UUID(proposed["proposal_id"]))
        assert proposal is not None
        artifacts = DurableAgentArtifactStore(
            storage=seeded.storage, conn_factory=conn_session_factory(conn)
        )
        assert await queue_crm_writes_finished_turn(conn, artifacts, proposal=proposal)
        from clue_api.agent_turn_submission import turn_id_for_submission

        wake = turn_id_for_submission(
            workspace_id=seeded.workspace_id,
            thread_id=seeded.thread_id,
            idempotency_key=f"crm-writes-finished:{proposed['proposal_id']}",
        )
        key = await conn.scalar(
            text("SELECT message_artifact_key FROM agent_turn_submission WHERE turn_id = :id"),
            {"id": wake},
        )
        message = (await seeded.storage.get(key)).decode()
        assert message.startswith(
            "Aryan Keshri allowed 2 of 3 changes and granted: always allow adding records to "
            "Clue lists and campaigns. The CRM changes are finished: 2 done, 0 failed, 0 skipped"
        ), message

    _run(tmp_path, "wake-names", body)


async def _send(client: httpx.AsyncClient, seeded: Any, key: str) -> str:
    response = await client.post(
        f"/api/v1/projects/{seeded.project_id}/threads/{seeded.thread_id}/turns",
        json={"message": f"Next message {key}."},
        headers={"X-Workspace-Id": seeded.workspace_id, "Idempotency-Key": key},
    )
    assert response.status_code == 202, response.text
    assert response.json()["data"]["agent_reply"] == "expected"
    return str(response.json()["data"]["turn_id"])


def test_a_decline_reaches_the_agent_once_on_its_next_turn(tmp_path: Path) -> None:
    from clue_api.crm.write_answer import card_answers_since_last_turn

    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        await _seeded_turn_ran(conn, seeded)
        await _name(conn, OTHER_USER_ID, "Priya Rao")
        proposed = await _propose(
            conn, seeded, _set_tier("101", "Tier 1"), _set_tier("103", "Tier 2")
        )
        snapshot = await _snapshot(conn, seeded, proposed)
        card_at = await conn.scalar(
            text("SELECT created_at FROM agent_gate WHERE gate_id = :gate"),
            {"gate": UUID(proposed["gate_id"])},
        )
        async with _client(conn, seeded, OTHER_USER_ID) as colleague:
            declined = await _answer(
                colleague, seeded, proposed, snapshot, key="nr-d", decision="rejected"
            )
            assert declined.status_code == 202, declined.text
        async with _client(conn, seeded) as client:
            next_turn = await _send(client, seeded, "after-decline")
            later_turn = await _send(client, seeded, "later")

        async def lines(turn_id: str) -> tuple[str, ...]:
            return await card_answers_since_last_turn(
                conn,
                workspace_id=seeded.workspace_id,
                thread_id=seeded.thread_id,
                turn_id=UUID(turn_id),
            )

        assert await lines(next_turn) == (
            f"Since your last turn: the CRM write card from {card_at:%Y-%m-%d %H:%M} UTC "
            "(2 changes) was declined by Priya Rao.",
        )
        # Only once: the turn after that has already been told.
        assert await lines(later_turn) == ()
        # The answer itself is no turn the agent runs, so it has no lines of its own.
        assert await lines(declined.json()["data"]["turn_id"]) == ()

    _run(tmp_path, "decline-line", body)


def test_an_allowed_card_still_sending_is_named_on_the_next_turn(tmp_path: Path) -> None:
    from clue_api.crm.write_answer import card_answers_since_last_turn

    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        await _seeded_turn_ran(conn, seeded)
        await _name(conn, USER_ID, "Aryan Keshri")
        proposed = await _propose(conn, seeded, _set_tier("101", "Tier 1"))
        snapshot = await _snapshot(conn, seeded, proposed)
        async with _client(conn, seeded) as client:
            allowed = await _answer(
                client, seeded, proposed, snapshot, key="nr-a", selected=_ids_in(snapshot, "101")
            )
            assert allowed.status_code == 202, allowed.text
            next_turn = await _send(client, seeded, "after-allow")
        (line,) = await card_answers_since_last_turn(
            conn,
            workspace_id=seeded.workspace_id,
            thread_id=seeded.thread_id,
            turn_id=UUID(next_turn),
        )
        assert line.endswith(
            "(1 change) was allowed by Aryan Keshri; the changes are still being sent."
        )

    _run(tmp_path, "allow-line", body)


def test_the_progress_read_reports_counts_and_crm_messages(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        proposed = await _propose(
            conn,
            seeded,
            _set_tier("101", "Tier 1"),
            _set_tier("103", "Tier 2"),
            _set_tier("102", "Tier 1"),
            _add_to_list("501"),
            _add_to_list("502"),
        )
        snapshot = await _snapshot(conn, seeded, proposed)
        chosen = [
            *_ids_in(snapshot, "101"),
            *_ids_in(snapshot, "103"),
            *_ids_in(snapshot, "501"),
            *_ids_in(snapshot, "502"),
        ]
        async with _client(conn, seeded) as client:
            asking = await client.get(
                f"{PROPOSALS}/{proposed['proposal_id']}",
                headers={"X-Workspace-Id": seeded.workspace_id},
            )
            assert asking.status_code == 200, asking.text
            assert asking.json()["state"] == "asking"
            answered = await _answer(
                client, seeded, proposed, snapshot, key="progress", selected=chosen
            )
            assert answered.status_code == 202, answered.text
            sending = (
                await client.get(
                    f"{PROPOSALS}/{proposed['proposal_id']}",
                    headers={"X-Workspace-Id": seeded.workspace_id},
                )
            ).json()
            assert sending["state"] == "sending"
            assert sending["counts"] == {"done": 0, "failed": 0, "skipped": 0, "pending": 4}

            # What the executor would leave behind.
            await _settle(conn, proposed["proposal_id"], "101", "succeeded")
            await _settle(
                conn,
                proposed["proposal_id"],
                "103",
                "failed",
                kind="validation_rule",
                message="Property value is not a valid option",
            )
            await _settle(
                conn,
                proposed["proposal_id"],
                "501",
                "skipped",
                kind="conflict",
                message="Changed in HubSpot since it was proposed.",
            )
            await _settle(conn, proposed["proposal_id"], "502", "succeeded")
            await conn.execute(
                text(
                    "UPDATE crm_write SET status = 'skipped' WHERE proposal_id = :id "
                    "AND NOT selected"
                ),
                {"id": UUID(proposed["proposal_id"])},
            )
            await writes.set_proposal_status(
                conn, proposal_id=UUID(proposed["proposal_id"]), status="finished"
            )
            done = await client.get(
                f"{PROPOSALS}/{proposed['proposal_id']}",
                headers={"X-Workspace-Id": seeded.workspace_id},
            )
            assert done.status_code == 200, done.text
            outcome = done.json()

            missing = await client.get(
                f"{PROPOSALS}/{uuid4()}", headers={"X-Workspace-Id": seeded.workspace_id}
            )
            assert missing.status_code == 404

        assert outcome["state"] == "done"
        assert outcome["provider"] == "hubspot"
        assert outcome["counts"] == {"done": 2, "failed": 1, "skipped": 1, "pending": 0}
        assert outcome["failed"] == [
            {
                "writeId": _ids_in(snapshot, "103")[0],
                "label": _label(snapshot, "103"),
                "field": "ICP tier",
                "crmMessage": "Property value is not a valid option",
            }
        ]
        assert outcome["skipped"] == [
            {
                "writeId": _ids_in(snapshot, "501")[0],
                "label": _label(snapshot, "501"),
                "reason": "Changed in HubSpot since it was proposed.",
            }
        ]
        tier, members = outcome["groups"]
        assert (tier["title"], tier["chosen"], tier["done"], tier["failed"]) == (
            snapshot["groups"][0]["title"],
            2,
            1,
            1,
        )
        assert (members["chosen"], members["done"], members["skipped"]) == (2, 1, 1)
        assert outcome["answeredBy"] == USER_ID
        assert outcome["answeredByName"]
        assert outcome["answeredAt"]

    _run(tmp_path, "progress", body)


def _label(snapshot: dict[str, Any], record: str) -> str:
    for group in snapshot["groups"]:
        for item in group["records"]:
            if item["record_ref"] == record:
                return str(item["name"])
    raise AssertionError(record)


async def _settle(
    conn: Any,
    proposal_id: str,
    record: str,
    status: str,
    *,
    kind: str | None = None,
    message: str | None = None,
) -> None:
    await conn.execute(
        text(
            "UPDATE crm_write SET status = :status, failure_kind = :kind, crm_message = :message, "
            "finished_at = now() WHERE proposal_id = :id AND record_ref = :record"
        ),
        {
            "id": UUID(proposal_id),
            "record": record,
            "status": status,
            "kind": kind,
            "message": message,
        },
    )


def test_the_database_lifts_the_addressee_rule_for_crm_write_cards_only(tmp_path: Path) -> None:
    """Revision 0e92986934d3: a colleague's answer reaches the later checks on a CRM write card,
    and is still refused as not the addressee on every other kind."""

    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        proposed = await _propose(conn, seeded, _set_tier("101", "Tier 1"))
        crm_gate = (await _snapshot(conn, seeded, proposed))["digest"]
        directive_digest = "d" * 64
        directive, _ = await insert_gate(
            conn,
            gate_id=uuid4(),
            workspace_id=seeded.workspace_id,
            project_id=seeded.project_id,
            thread_id=seeded.thread_id,
            turn_id=seeded.turn_id,
            kind=KIND_DIRECTIVE_CONFIRMATION,
            subject_ref="research-directive:33333333-3333-4333-8333-333333333333:v1",
            subject_revision=1,
            expected_subject_sha256=directive_digest,
            subject_snapshot={"research_directive_id": str(uuid4())},
            max_spend_cents=None,
            currency=None,
            addressee_user_id=USER_ID,
        )
        cases: list[tuple[UUID, str, dict[str, JsonValue], str]] = [
            (directive.gate_id, directive_digest, {}, "only the gate addressee may answer"),
            (
                UUID(proposed["gate_id"]),
                crm_gate,
                {"selected_write_ids": [], "always_allow": []},
                "answering turn was not submitted by the gate addressee",
            ),
        ]
        for gate_id, digest, payload, refusal in cases:
            with pytest.raises(DBAPIError, match=refusal):
                async with conn.begin_nested():
                    await insert_gate_answer(
                        conn,
                        gate_id=gate_id,
                        workspace_id=seeded.workspace_id,
                        turn_id=seeded.turn_id,
                        action_ref=derive_turn_action_ref(seeded.turn_id),
                        decision="approved",
                        expected_subject_sha256=digest,
                        decision_payload=payload,
                        answered_by_user_id=OTHER_USER_ID,
                    )

    _run(tmp_path, "trigger", body)


def test_a_card_on_an_expired_connection_cannot_be_answered(tmp_path: Path) -> None:
    """An answer queued on an expired connection could never be sent: reconnecting always makes a
    new connection row and closes this one's proposals."""

    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        proposed = await _propose(conn, seeded, _set_tier("101", "Tier 1"))
        snapshot = await _snapshot(conn, seeded, proposed)
        await mark_expired(conn, connection_id=connection.connection_id)
        async with _client(conn, seeded) as client:
            response = await _answer(
                client,
                seeded,
                proposed,
                snapshot,
                key="expired",
                selected=_ids_in(snapshot, "101"),
                always_allow=["field:company.icp_tier"],
            )
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "CRM_CONNECTION_CHANGED"
        assert await _answers(conn, seeded.workspace_id) == 0
        assert await _grants(conn, seeded.workspace_id) == []

    _run(tmp_path, "expired", body)


async def _thread_status(client: httpx.AsyncClient, seeded: Any) -> str:
    listing = await client.get(
        f"/api/v1/projects/{seeded.project_id}/threads",
        headers={"X-Workspace-Id": seeded.workspace_id},
    )
    assert listing.status_code == 200, listing.text
    statuses = {item["id"]: str(item["status"]) for item in listing.json()["data"]}
    return statuses[seeded.thread_id]


async def _open_gate_ids(conn: Any, seeded: Any) -> set[str]:
    rows = await open_gates_for_thread(
        conn, workspace_id=seeded.workspace_id, thread_id=seeded.thread_id
    )
    kinds = await open_gate_kinds_for_threads(
        workspace_id=seeded.workspace_id,
        thread_ids=(seeded.thread_id,),
        conn_factory=conn_session_factory(conn),
    )
    views = await thread_gates(
        workspace_id=seeded.workspace_id,
        thread_id=seeded.thread_id,
        conn_factory=conn_session_factory(conn),
    )
    opened = {str(row.gate_id) for row in rows}
    # Every derivation of openness agrees.
    assert {view.gate_id for view in views if view.is_open} == opened
    assert len(kinds.get(seeded.thread_id, ())) == len(opened)
    return opened


def test_a_replaced_card_is_no_longer_open_anywhere(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        first = await _propose(conn, seeded, _set_tier("101", "Tier 1"))
        second = await _propose(conn, seeded, _set_tier("101", "Tier 2"))
        assert await _open_gate_ids(conn, seeded) == {second["gate_id"]}
        second_snapshot = await _snapshot(conn, seeded, second)
        async with _client(conn, seeded) as client:
            gates = await client.get(
                f"/api/v1/projects/{seeded.project_id}/threads/{seeded.thread_id}/gates",
                headers={"X-Workspace-Id": seeded.workspace_id},
            )
            assert gates.status_code == 200, gates.text
            withdrawn = {item["gate_id"]: item["withdrawn"] for item in gates.json()["data"]}
            assert withdrawn == {first["gate_id"]: True, second["gate_id"]: False}
            replaced = await client.get(
                f"{PROPOSALS}/{first['proposal_id']}",
                headers={"X-Workspace-Id": seeded.workspace_id},
            )
            assert replaced.json()["state"] == "replaced"

            answered = await _answer(
                client,
                seeded,
                second,
                second_snapshot,
                key="newer",
                selected=_ids_in(second_snapshot, "101"),
            )
            assert answered.status_code == 202, answered.text
            # The replaced card asks nothing: the chat is not waiting on an approval any more.
            assert await _thread_status(client, seeded) != "approval"
        assert await _open_gate_ids(conn, seeded) == set()

    _run(tmp_path, "withdrawn", body)


def test_a_reconnect_closes_a_card_nobody_answered(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        proposed = await _propose(conn, seeded, _set_tier("101", "Tier 1"))
        reconnected = await _connect(conn, seeded.workspace_id, provider="salesforce")
        closed = await close_replaced_connection_proposals(
            conn,
            None,
            workspace_id=seeded.workspace_id,
            active_connection_id=reconnected.connection_id,
        )
        assert closed == [UUID(proposed["proposal_id"])]
        assert (await _proposal(conn, proposed["proposal_id"])).status == "finished"
        assert await _open_gate_ids(conn, seeded) == set()
        async with _client(conn, seeded) as client:
            assert await _thread_status(client, seeded) != "approval"
            progress = await client.get(
                f"{PROPOSALS}/{proposed['proposal_id']}",
                headers={"X-Workspace-Id": seeded.workspace_id},
            )
        assert progress.json()["state"] == "closed"
        assert progress.json()["counts"]["done"] == 0

    _run(tmp_path, "reconnect-closes", body)


def test_a_newer_card_never_replaces_a_proposal_an_answer_queued(tmp_path: Path) -> None:
    """The replace step is one guarded UPDATE: whichever order the answer and the next proposal
    land in, a proposal the answer queued stays queued."""

    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        first = await _propose(conn, seeded, _set_tier("101", "Tier 1"))
        snapshot = await _snapshot(conn, seeded, first)
        async with _client(conn, seeded) as client:
            answered = await _answer(
                client, seeded, first, snapshot, key="first", selected=_ids_in(snapshot, "101")
            )
        assert answered.status_code == 202, answered.text
        await _propose(conn, seeded, _set_tier("103", "Tier 2"))
        assert (await _proposal(conn, first["proposal_id"])).status == "queued"

    _run(tmp_path, "race-order", body)


# --- Task 3b (R-12.7): a new list and its adds through the real card ---------------------------


def _create_list(name: str = "Clue: Q4") -> CrmChangeInput:
    return CrmChangeInput(
        slug="HUBSPOT_CREATE_LIST",
        arguments={"name": name, "object_type_id": "0-1", "processing_type": "MANUAL"},
        reason="The project's committee list.",
    )


def _add_to_new(record: str, name: str = "Clue: Q4") -> CrmChangeInput:
    return CrmChangeInput(
        slug="HUBSPOT_UPDATE_LIST_MEMBERSHIPS",
        arguments={"list_id": f"new:{name}", "operation": "add", "record_ids": [record]},
        reason="The buying committee Clue found.",
    )


def _executor(conn: Any, tmp_path: Path) -> tuple[Any, Any]:
    from tests.api.test_crm_write_executor_db import _handler, _WritingCrm

    gateway = _WritingCrm(lists={"501": []})
    return gateway, _handler(conn, tmp_path, gateway)


async def _list_writes(conn: Any, proposal_id: str) -> dict[str, tuple[str, str | None]]:
    rows = await conn.execute(
        text("SELECT kind, status, crm_message FROM crm_write WHERE proposal_id = :id"),
        {"id": UUID(proposal_id)},
    )
    return {row.kind: (row.status, row.crm_message) for row in rows}


def test_a_covered_create_waits_with_its_adds_for_the_card(tmp_path: Path) -> None:
    """Review #2: an "Always allow" on creating lists does not send the create ahead of the card
    that asks about its adds; nothing is sent before the answer, then the create goes first."""
    from tests.api.test_crm_write_executor_db import _context

    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        await writes.insert_grant(
            conn,
            workspace_id=seeded.workspace_id,
            connection_id=connection.connection_id,
            scope_key="kind:list_create",
            granted_by_user_id=USER_ID,
        )
        proposed = await _propose(conn, seeded, _create_list(), _add_to_new("501"))
        assert proposed["state"] == "awaiting_permission"
        snapshot = await _snapshot(conn, seeded, proposed)
        assert [g["title"] for g in snapshot["groups"]] == ['Add 1 contact to the list "Clue: Q4"']

        gateway, handler = _executor(conn, tmp_path)
        await handler.handle(_context(connection))
        assert gateway.writes == []  # the proposal waits for its card, create included

        async with _client(conn, seeded) as client:
            response = await _answer(
                client, seeded, proposed, snapshot, key="allow", selected=_ids_in(snapshot, "501")
            )
        assert response.status_code == 202, response.text
        await handler.handle(_context(connection))

        assert [slug for slug, _ in gateway.writes] == [
            "HUBSPOT_CREATE_LIST",
            "HUBSPOT_UPDATE_LIST_MEMBERSHIPS",
        ]
        assert gateway.writes[1][1]["list_id"] == "17"
        assert (await _list_writes(conn, proposed["proposal_id"]))["list_membership"][0] == (
            "succeeded"
        )

    _run(tmp_path, "newlistcovered", body)


def test_unticking_the_create_on_the_card_skips_its_adds(tmp_path: Path) -> None:
    """Review #3: the person allows the add but unticks the list it goes into."""
    from tests.api.test_crm_write_executor_db import NOT_CREATED, _context

    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        proposed = await _propose(conn, seeded, _create_list(), _add_to_new("501"))
        snapshot = await _snapshot(conn, seeded, proposed)
        assert [g["title"] for g in snapshot["groups"]] == [
            'Create the list "Clue: Q4"',
            'Add 1 contact to the list "Clue: Q4"',
        ]
        async with _client(conn, seeded) as client:
            response = await _answer(
                client, seeded, proposed, snapshot, key="allow", selected=_ids_in(snapshot, "501")
            )
        assert response.status_code == 202, response.text

        gateway, handler = _executor(conn, tmp_path)
        await handler.handle(_context(connection))

        logged = await _list_writes(conn, proposed["proposal_id"])
        assert logged["list_create"][0] == "skipped"
        assert logged["list_membership"] == ("skipped", NOT_CREATED)
        assert gateway.writes == []

    _run(tmp_path, "newlistunticked", body)
