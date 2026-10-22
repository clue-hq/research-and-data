"""``propose_crm_changes@1`` (CRM integration Phase 2, Task 5).

Covered changes are queued and the connection's write executor offered, with no card. Otherwise one
``crm_write_permission`` card asks the turn's person, and an earlier card of the same chat still
waiting for its answer is replaced. The proposal id is derived from the turn and the exact batch, so
a replayed call returns the same proposal without reading the CRM again. The CRM is a fake gateway;
the database is the lane's test DB.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text

from clue_api.agent_gate import KIND_CRM_WRITE_PERMISSION, get_gate
from clue_api.crm import writes
from clue_api.crm.composio_gateway import ExecuteResult
from clue_api.crm.write_tools import (
    CrmChangeInput,
    ProposeCrmChangesInput,
    ProposeCrmChangesTool,
)
from clue_api.turn_action import derive_turn_action_ref
from clue_core import new_operation_id
from clue_fleet import FleetTaskKind
from clue_toolbelt import PreconditionFailed, ToolContext
from tests.api.test_crm_tools_db import _connect, _settings
from tests.api.test_crm_write_prepare_db import _FakeCrm
from tests.api.test_lane_d4_agent_gate_db import USER_ID, _seed
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)


@pytest.fixture(autouse=True)
def require_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


class _FakeQueue:
    def __init__(self) -> None:
        self.offers: list[dict[str, Any]] = []

    async def enqueue(self, **kwargs: Any) -> bool:
        self.offers.append(kwargs)
        return True


def _tool(conn: Any, gateway: _FakeCrm, queue: _FakeQueue) -> ProposeCrmChangesTool:
    return ProposeCrmChangesTool(
        settings=_settings(),
        gateway=gateway,  # type: ignore[arg-type]
        conn_factory=conn_session_factory(conn),
        work_queue=queue,  # type: ignore[arg-type]
    )


def _ctx(conn: Any, workspace_id: str) -> ToolContext:
    return ToolContext(
        workspace_id=workspace_id,
        actor="agent",
        conn_factory=conn_session_factory(conn),
        operation_id=new_operation_id(),
    )


def _set_tier(record: str, tier: str) -> CrmChangeInput:
    return CrmChangeInput(
        slug="HUBSPOT_UPDATE_COMPANY",
        arguments={"companyId": record, "properties": {"icp_tier": tier}},
        reason="The ICP tiers Clue scored for this project.",
    )


def _input(seeded: Any, *changes: CrmChangeInput) -> ProposeCrmChangesInput:
    return ProposeCrmChangesInput(
        changes=list(changes), source_turn_ref=derive_turn_action_ref(seeded.turn_id)
    )


async def _proposal_status(conn: Any, proposal_id: str) -> str:
    result = await conn.execute(
        text("SELECT status FROM crm_write_proposal WHERE proposal_id = :id"),
        {"id": UUID(proposal_id)},
    )
    return str(result.scalar_one())


async def _count(conn: Any, table: str, workspace_id: str) -> int:
    result = await conn.execute(
        text(f"SELECT count(*) FROM {table} WHERE workspace_id = :ws"),  # noqa: S608
        {"ws": workspace_id},
    )
    return int(result.scalar_one())


def _run(tmp_path: Path, label: str, body: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id=f"ws-crmp-{label}", label=label)
            connection = await _connect(conn, seeded.workspace_id)
            await body(conn, seeded, connection)

    run_async(scenario())


def test_covered_changes_are_queued_without_a_card(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        await writes.insert_grant(
            conn,
            workspace_id=seeded.workspace_id,
            connection_id=connection.connection_id,
            scope_key="field:company.icp_tier",
            granted_by_user_id=USER_ID,
        )
        queue = _FakeQueue()
        gateway = _FakeCrm(records={"101": {"icp_tier": None}, "102": {"icp_tier": ""}})
        tool = _tool(conn, gateway, queue)
        inputs = _input(seeded, _set_tier("101", "Tier 1"), _set_tier("102", "Tier 2"))
        assert await tool.preconditions(inputs, _ctx(conn, seeded.workspace_id)) == ()

        refs = (await tool.invoke(inputs, _ctx(conn, seeded.workspace_id))).references

        assert refs["state"] == "queued"
        assert refs["gate_id"] is None and refs["gate_kind"] is None
        assert (refs["covered"], refs["needs_permission"], refs["overwrites"]) == (2, 0, 0)
        assert refs["groups"] == [
            {
                "kind": "field_update",
                "object": "company",
                "field": "icp_tier",
                "count": 2,
                "covered": True,
                "overwrites_person": False,
            }
        ]
        assert await _proposal_status(conn, refs["proposal_id"]) == "queued"
        assert await _count(conn, "agent_gate", seeded.workspace_id) == 0
        assert queue.offers == [
            {
                "kind": FleetTaskKind.CRM_WRITE,
                "work_id": connection.connection_id,
                "dedup_key": f"crm-write:{connection.connection_id}",
                "reopen_terminal": True,
            }
        ]

    _run(tmp_path, "covered", body)


def test_uncovered_changes_open_one_card_and_replace_an_open_one(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        queue = _FakeQueue()
        gateway = _FakeCrm(records={"101": {"icp_tier": None}, "102": {"icp_tier": "Tier 3"}})
        tool = _tool(conn, gateway, queue)
        ctx = _ctx(conn, seeded.workspace_id)

        first = (await tool.invoke(_input(seeded, _set_tier("101", "Tier 1")), ctx)).references
        assert first["state"] == "awaiting_permission"
        assert first["gate_kind"] == KIND_CRM_WRITE_PERMISSION
        assert first["gate_ref"].endswith(first["gate_id"])

        # A second batch in the same chat: the earlier card, still unanswered, is replaced.
        second = (
            await tool.invoke(
                _input(seeded, _set_tier("101", "Tier 2"), _set_tier("102", "Tier 1")), ctx
            )
        ).references
        assert second["state"] == "awaiting_permission"
        assert second["proposal_id"] != first["proposal_id"]
        assert second["gate_id"] != first["gate_id"]
        assert (second["covered"], second["needs_permission"], second["overwrites"]) == (0, 2, 1)
        assert await _proposal_status(conn, first["proposal_id"]) == "replaced"
        assert await _proposal_status(conn, second["proposal_id"]) == "awaiting_permission"
        assert queue.offers == []

        gate = await get_gate(
            conn, workspace_id=seeded.workspace_id, gate_id=UUID(second["gate_id"])
        )
        assert gate is not None and gate.is_open
        assert gate.gate.kind == KIND_CRM_WRITE_PERMISSION
        assert gate.gate.addressee_user_id == USER_ID
        assert tuple(gate.gate.permitted_decisions) == ("approved", "rejected")
        assert gate.gate.max_spend_cents is None
        snapshot: Any = gate.gate.subject_snapshot
        assert snapshot["state"] == "asking"
        assert [g["count"] for g in snapshot["groups"]] == [1]
        assert [o["record_ref"] for o in snapshot["overwrites"]] == ["102"]

    _run(tmp_path, "replace", body)


def test_a_replayed_call_returns_the_same_proposal(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        queue = _FakeQueue()
        gateway = _FakeCrm(records={"101": {"icp_tier": None}})
        tool = _tool(conn, gateway, queue)
        inputs = _input(seeded, _set_tier("101", "Tier 1"))

        first = (await tool.invoke(inputs, _ctx(conn, seeded.workspace_id))).references
        reads = len(gateway.calls)
        again = (await tool.invoke(inputs, _ctx(conn, seeded.workspace_id))).references

        assert again == first
        assert len(gateway.calls) == reads  # the replay read nothing
        assert await _count(conn, "crm_write_proposal", seeded.workspace_id) == 1
        assert await _count(conn, "crm_write", seeded.workspace_id) == 1
        assert await _count(conn, "agent_gate", seeded.workspace_id) == 1
        assert await _proposal_status(conn, first["proposal_id"]) == "awaiting_permission"

    _run(tmp_path, "replay", body)


def test_a_forbidden_change_refuses_the_whole_batch(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        gateway = _FakeCrm(records={"101": {}, "201": {}})
        tool = _tool(conn, gateway, _FakeQueue())
        phone = CrmChangeInput(
            slug="HUBSPOT_UPDATE_CONTACTS",
            arguments={"inputs": [{"id": "201", "properties": {"phone": "+1 555 0100"}}]},
            reason="x",
        )
        with pytest.raises(PreconditionFailed) as refused:
            await tool.invoke(
                _input(seeded, _set_tier("101", "Tier 1"), phone),
                _ctx(conn, seeded.workspace_id),
            )
        assert refused.value.failures[0].reason_code == "crm_field_forbidden"
        assert await _count(conn, "crm_write_proposal", seeded.workspace_id) == 0
        assert await _count(conn, "agent_gate", seeded.workspace_id) == 0

    _run(tmp_path, "forbidden", body)


def test_a_missing_record_is_refused_and_the_rest_go_on_the_card(tmp_path: Path) -> None:
    """R-11.7 (live check L6): one company HubSpot does not have no longer refuses the batch."""

    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        gateway = _FakeCrm(
            records={"101": {"icp_tier": None}, "102": {"icp_tier": None}},
            missing=frozenset({"999999999999"}),
        )
        tool = _tool(conn, gateway, _FakeQueue())
        refs = (
            await tool.invoke(
                _input(
                    seeded,
                    _set_tier("101", "Tier 1"),
                    _set_tier("999999999999", "Tier 1"),
                    _set_tier("102", "Tier 2"),
                ),
                _ctx(conn, seeded.workspace_id),
            )
        ).references

        assert refs["state"] == "awaiting_permission"
        assert (refs["covered"], refs["needs_permission"]) == (0, 2)
        assert refs["refused"] == [
            {
                "index": 1,
                "slug": "HUBSPOT_UPDATE_COMPANY",
                "record_ref": "999999999999",
                "reason_code": "crm_record_not_found",
                "message": "HubSpot has no company 999999999999.",
            }
        ]
        gate = await get_gate(conn, workspace_id=seeded.workspace_id, gate_id=UUID(refs["gate_id"]))
        assert gate is not None
        snapshot: Any = gate.gate.subject_snapshot
        assert [r["record_ref"] for g in snapshot["groups"] for r in g["records"]] == [
            "101",
            "102",
        ]
        assert await _count(conn, "crm_write", seeded.workspace_id) == 2

    _run(tmp_path, "missing", body)


def test_a_batch_whose_every_record_is_missing_makes_no_proposal(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        gateway = _FakeCrm(missing=frozenset({"901", "902"}))
        tool = _tool(conn, gateway, _FakeQueue())
        with pytest.raises(PreconditionFailed) as refused:
            await tool.invoke(
                _input(seeded, _set_tier("901", "Tier 1"), _set_tier("902", "Tier 1")),
                _ctx(conn, seeded.workspace_id),
            )
        assert [(f.reason_code, f.message) for f in refused.value.failures] == [
            ("crm_record_not_found", "HubSpot has no company 901."),
            ("crm_record_not_found", "HubSpot has no company 902."),
        ]
        assert await _count(conn, "crm_write_proposal", seeded.workspace_id) == 0
        assert await _count(conn, "agent_gate", seeded.workspace_id) == 0

    _run(tmp_path, "allmissing", body)


def test_a_failed_read_still_refuses_the_whole_batch(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        unauthorized = ExecuteResult(
            False,
            {"http_error": "401", "status_code": 401},
            '{"status":"error","message":"Authentication credentials not found.",'
            '"category":"INVALID_AUTHENTICATION"}',
        )
        gateway = _FakeCrm(
            records={"101": {"icp_tier": None}},
            missing=frozenset({"999999999999"}),
            failing={"HUBSPOT_READ_CRM_OBJECT_BY_ID": unauthorized},
        )
        tool = _tool(conn, gateway, _FakeQueue())
        with pytest.raises(PreconditionFailed) as refused:
            await tool.invoke(
                _input(seeded, _set_tier("101", "Tier 1"), _set_tier("999999999999", "Tier 1")),
                _ctx(conn, seeded.workspace_id),
            )
        assert refused.value.reason_codes == ("crm_read_failed",)
        assert await _count(conn, "crm_write_proposal", seeded.workspace_id) == 0

    _run(tmp_path, "readfail", body)


def test_an_unconnected_workspace_is_refused(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-crmp-none", label="none")
            tool = _tool(conn, _FakeCrm(), _FakeQueue())
            failures = await tool.preconditions(
                _input(seeded, _set_tier("101", "Tier 1")), _ctx(conn, seeded.workspace_id)
            )
            assert [f.reason_code for f in failures] == ["crm_not_connected"]

    run_async(scenario())


def test_a_person_value_is_proposed_only_as_clue_researched_it(tmp_path: Path) -> None:
    """Phase 3 Task 5 through the tool: the change naming its Clue contact with the researched
    title goes on the card with its claim id; one with a title the agent made up is refused on
    its own, without its value; a person change naming no contact is refused too."""
    from tests.api.test_crm_write_prepare_db import _researched

    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        world = await _researched(conn, seeded)
        gateway = _FakeCrm(records={"101": {"icp_tier": None}, "201": {"jobtitle": None}})

        def title(value: str, clue_entity_id: str | None) -> CrmChangeInput:
            return CrmChangeInput(
                slug="HUBSPOT_UPDATE_CONTACTS",
                arguments={"inputs": [{"id": "201", "properties": {"jobtitle": value}}]},
                reason="The title Clue found.",
                clue_entity_id=clue_entity_id,
            )

        refs = (
            await _tool(conn, gateway, _FakeQueue()).invoke(
                _input(
                    seeded,
                    _set_tier("101", "Tier 1"),
                    title("Head of Everything", str(world.nick)),
                    CrmChangeInput(
                        slug="HUBSPOT_UPDATE_CONTACTS",
                        arguments={"inputs": [{"id": "202", "properties": {"jobtitle": "X"}}]},
                        reason="x",
                    ),
                ),
                _ctx(conn, seeded.workspace_id),
            )
        ).references
        assert [(r["index"], r["reason_code"]) for r in refs["refused"]] == [
            (1, "crm_personal_data_not_allowed"),
            (2, "crm_personal_data_not_allowed"),
        ]
        assert "Head of Everything" not in str(refs["refused"])

        cleared = (
            await _tool(conn, gateway, _FakeQueue()).invoke(
                _input(seeded, title("VP Marketing", str(world.nick))),
                _ctx(conn, seeded.workspace_id),
            )
        ).references
        assert cleared["refused"] == []
        row = (
            await conn.execute(
                text(
                    "SELECT source_claim_ids, clue_entity_id FROM crm_write WHERE proposal_id = :p"
                ),
                {"p": UUID(cleared["proposal_id"])},
            )
        ).one()
        assert row.source_claim_ids == [world.claims["nick_title"]]
        assert row.clue_entity_id == str(world.nick)

    _run(tmp_path, "persongate", body)


def test_a_change_naming_no_clue_entity_keeps_its_proposal_id() -> None:
    """``clue_entity_id`` joins a change's identity only when given, so a batch proposed before
    the field existed derives the same proposal id on replay."""
    from clue_api.crm.write_tools import _identity, proposal_id_for

    change = _set_tier("101", "Tier 1")
    named = change.model_copy(update={"clue_entity_id": "00000000-0000-0000-0000-000000000001"})
    ref = "turn-action:00000000-0000-0000-0000-000000000002"
    assert "clue_entity_id" not in _identity(change)
    assert proposal_id_for(ref, [change]) != proposal_id_for(ref, [named])
