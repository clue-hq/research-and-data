"""Proposing to set up Clue's own fields in the connected CRM, and answering its card (CRM
integration Phase 4, Task 2; rulings R-13.1, R-13.3, R-13.4).

``propose_clue_fields_setup@1`` builds the one fixed ``clue_fields_setup`` change from
``CLUE_FIELDS[provider]`` (the agent names only the project) and opens a permission card that lists
every field, says on Salesforce that Clue creates a permission set, and never offers "Always
allow". Only a workspace owner or admin may allow it: an operator's Allow is refused
``crm_setup_needs_admin`` with nothing queued. A connection whose fields are already ``ready`` is
refused. The setup run itself is tested in ``test_crm_clue_fields_setup_run_db.py`` (Task 3).

DB-backed and rollback-only, on the lane's test DB.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text

from clue_api.crm import writes
from clue_api.crm.clue_fields import CLUE_FIELDS, record_clue_fields
from clue_api.crm.write_tools import (
    ProposeClueFieldsSetupInput,
    ProposeClueFieldsSetupTool,
)
from clue_api.turn_action import derive_turn_action_ref
from clue_core import new_operation_id
from clue_storage import FsStorage
from clue_toolbelt import PreconditionFailed, ToolContext
from tests.api.test_crm_tools_db import _connect
from tests.api.test_crm_write_answer_db import (
    _answer,
    _answers,
    _client,
    _offers,
    _proposal,
    _settings,
    _snapshot,
)
from tests.api.test_crm_write_prepare_db import _FakeCrm
from tests.api.test_lane_d4_agent_gate_db import OTHER_USER_ID, USER_ID, _seed
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)

SALESFORCE_LINE = (
    "Creates a 'Clue fields' permission set and gives your connected Salesforce user access to "
    "these fields."
)


@pytest.fixture(autouse=True)
def require_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


def _tool(conn: Any) -> ProposeClueFieldsSetupTool:
    return ProposeClueFieldsSetupTool(
        settings=_settings(),
        gateway=_FakeCrm(records={}),  # type: ignore[arg-type]
        conn_factory=conn_session_factory(conn),
    )


def _ctx(conn: Any, seeded: Any) -> ToolContext:
    return ToolContext(
        workspace_id=seeded.workspace_id,
        actor="agent",
        conn_factory=conn_session_factory(conn),
        operation_id=new_operation_id(),
    )


async def _propose(conn: Any, seeded: Any, project_id: str | None = None) -> dict[str, Any]:
    inputs = ProposeClueFieldsSetupInput(
        project_id=project_id or seeded.project_id,
        source_turn_ref=derive_turn_action_ref(seeded.turn_id),
    )
    references: dict[str, Any] = (await _tool(conn).invoke(inputs, _ctx(conn, seeded))).references
    return references


async def _refusal(conn: Any, seeded: Any, project_id: str | None = None) -> tuple[str, str]:
    with pytest.raises(PreconditionFailed) as refused:
        await _propose(conn, seeded, project_id)
    failure = refused.value.failures[0]
    return failure.reason_code, failure.message


async def _set_role(conn: Any, seeded: Any, user_id: str, role_key: str) -> None:
    await conn.execute(
        text(
            "UPDATE workspace_membership SET role_key = :role "
            "WHERE workspace_id = :ws AND user_id = :user"
        ),
        {"role": role_key, "ws": seeded.workspace_id, "user": user_id},
    )


async def _write_rows(conn: Any, proposal_id: str) -> list[Any]:
    rows = await conn.execute(
        text(
            "SELECT write_id, slug, kind, object, record_ref, scope_key, covered_by, selected, "
            "status, crm_message FROM crm_write WHERE proposal_id = :id ORDER BY ordinal"
        ),
        {"id": UUID(proposal_id)},
    )
    return list(rows.all())


def _run(tmp_path: Path, label: str, body: Any, provider: str = "hubspot") -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id=f"ws-crmcf-{label}", label=label)
            seeded.label = label
            seeded.storage = FsStorage(tmp_path / f"crm-clue-fields-{label}")
            connection = await _connect(conn, seeded.workspace_id, provider)
            await body(conn, seeded, connection)

    run_async(scenario())


def _setup_group(snapshot: dict[str, Any]) -> dict[str, Any]:
    (group,) = snapshot["groups"]
    assert group["kind"] == "clue_fields_setup"
    return dict(group)


@pytest.mark.parametrize("provider", ["hubspot", "salesforce"])
def test_the_card_lists_every_clue_field_and_offers_no_always_allow(
    tmp_path: Path, provider: str
) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        proposed = await _propose(conn, seeded)
        assert proposed["state"] == "awaiting_permission"
        assert proposed["gate_id"] is not None

        (row,) = await _write_rows(conn, proposed["proposal_id"])
        assert (row.kind, row.slug, row.record_ref, row.covered_by) == (
            "clue_fields_setup",
            "CLUE_FIELDS_SETUP",
            None,
            None,
        )
        assert row.scope_key == "kind:clue_fields_setup"

        snapshot = await _snapshot(conn, seeded, proposed)
        name = "HubSpot" if provider == "hubspot" else "Salesforce"
        assert snapshot["crm"] == provider
        assert name in snapshot["title"]
        assert snapshot["standing_permissions"] == []
        assert snapshot["overwrites"] == []
        assert snapshot["caption"] == "Only a workspace owner or admin can allow this."
        group = _setup_group(snapshot)
        assert group["title"] == f"Set up Clue's fields in {name}"
        assert [record["write_id"] for record in group["records"]] == [str(row.write_id)]
        listed = [(item["object"], item["label"]) for item in group["setup_fields"]]
        # The card shows labels only, never the CRM's API names (founder, 2026-10-25).
        assert all(set(item) == {"object", "label", "type"} for item in group["setup_fields"])
        expected_objects = {"company": "Company" if provider == "hubspot" else "Account"}
        assert listed == [
            (expected_objects.get(field.object, "Contact"), field.label)
            for field in CLUE_FIELDS[provider]  # type: ignore[index]
        ]
        if provider == "salesforce":
            assert SALESFORCE_LINE in group["setup_notes"]
        else:
            assert SALESFORCE_LINE not in group["setup_notes"]

        # A replayed call finds its own proposal.
        again = await _propose(conn, seeded)
        assert again["proposal_id"] == proposed["proposal_id"]

    _run(tmp_path, f"card-{provider}", body, provider)


def test_no_standing_permission_covers_the_setup(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        # Fully automatic covers every other change; never this one (R-13.3).
        await writes.insert_grant(
            conn,
            workspace_id=seeded.workspace_id,
            connection_id=connection.connection_id,
            scope_key=writes.FULLY_AUTOMATIC,
            granted_by_user_id=USER_ID,
        )
        proposed = await _propose(conn, seeded)
        assert proposed["state"] == "awaiting_permission"
        (row,) = await _write_rows(conn, proposed["proposal_id"])
        assert row.covered_by is None
        assert await _offers(conn, connection.connection_id) == 0
        grants = await writes.live_grants(conn, connection_id=connection.connection_id)
        assert writes.covering_grant(grants, "kind:clue_fields_setup", "clue_fields_setup") is None

        # And the card cannot be made to grant it.
        snapshot = await _snapshot(conn, seeded, proposed)
        async with _client(conn, seeded) as client:
            response = await _answer(
                client,
                seeded,
                proposed,
                snapshot,
                key="always",
                selected=[str(row.write_id)],
                always_allow=["kind:clue_fields_setup"],
            )
        assert response.status_code == 422, response.text
        assert response.json()["error"]["code"] == "CRM_WRITE_SCOPE_NOT_OFFERED"

    _run(tmp_path, "no-grant", body)


def test_an_operators_allow_is_refused_and_nothing_is_queued(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        await _set_role(conn, seeded, OTHER_USER_ID, "operator")
        proposed = await _propose(conn, seeded)
        snapshot = await _snapshot(conn, seeded, proposed)
        (row,) = await _write_rows(conn, proposed["proposal_id"])
        async with _client(conn, seeded, OTHER_USER_ID) as client:
            response = await _answer(
                client, seeded, proposed, snapshot, key="operator", selected=[str(row.write_id)]
            )
        assert response.status_code == 403, response.text
        error = response.json()["error"]
        assert error["code"] == "crm_setup_needs_admin"
        assert error["message"] == "Only a workspace owner or admin can set up Clue's fields."
        assert (await _proposal(conn, proposed["proposal_id"])).status == "awaiting_permission"
        assert await _offers(conn, connection.connection_id) == 0
        assert await _answers(conn, seeded.workspace_id) == 0
        (row,) = await _write_rows(conn, proposed["proposal_id"])
        assert (row.covered_by, row.status) == (None, "proposed")

    _run(tmp_path, "operator", body)


@pytest.mark.parametrize("role", ["admin", "owner"])
def test_an_owner_or_admins_allow_queues_the_setup(tmp_path: Path, role: str) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        await _set_role(conn, seeded, OTHER_USER_ID, role)
        proposed = await _propose(conn, seeded)
        snapshot = await _snapshot(conn, seeded, proposed)
        (row,) = await _write_rows(conn, proposed["proposal_id"])
        async with _client(conn, seeded, OTHER_USER_ID) as client:
            response = await _answer(
                client, seeded, proposed, snapshot, key=role, selected=[str(row.write_id)]
            )
        assert response.status_code == 202, response.text
        proposal = await _proposal(conn, proposed["proposal_id"])
        assert (proposal.status, proposal.answered_by_user_id) == ("queued", OTHER_USER_ID)
        assert await _offers(conn, connection.connection_id) == 1
        (row,) = await _write_rows(conn, proposed["proposal_id"])
        assert (row.selected, row.covered_by) == (True, f"gate:{proposed['gate_id']}")

    _run(tmp_path, f"allow-{role}", body)


def test_an_operator_may_still_decline(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        await _set_role(conn, seeded, OTHER_USER_ID, "operator")
        proposed = await _propose(conn, seeded)
        snapshot = await _snapshot(conn, seeded, proposed)
        async with _client(conn, seeded, OTHER_USER_ID) as client:
            response = await _answer(
                client, seeded, proposed, snapshot, key="decline", decision="rejected"
            )
        assert response.status_code == 202, response.text
        assert (await _proposal(conn, proposed["proposal_id"])).status == "declined"
        assert await _offers(conn, connection.connection_id) == 0

    _run(tmp_path, "operator-declines", body)


@pytest.mark.parametrize("provider", ["hubspot", "salesforce"])
def test_proposing_again_when_ready_is_refused(tmp_path: Path, provider: str) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        await record_clue_fields(
            conn,
            connection_id=connection.connection_id,
            workspace_id=seeded.workspace_id,
            provider=provider,  # type: ignore[arg-type]
            created=CLUE_FIELDS[provider],  # type: ignore[index]
            permission_set_id="0PS1" if provider == "salesforce" else None,
            label_type_id="7" if provider == "hubspot" else None,
            status="ready",
        )
        name = "HubSpot" if provider == "hubspot" else "Salesforce"
        code, message = await _refusal(conn, seeded)
        assert code == "crm_clue_fields_ready"
        assert message == f"Clue's fields are already set up in {name}."
        count = await conn.scalar(
            text("SELECT count(*) FROM crm_write_proposal WHERE workspace_id = :ws"),
            {"ws": seeded.workspace_id},
        )
        assert count == 0

    _run(tmp_path, f"ready-{provider}", body, provider)


def test_a_partial_setup_may_be_proposed_again(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        await record_clue_fields(
            conn,
            connection_id=connection.connection_id,
            workspace_id=seeded.workspace_id,
            provider="hubspot",
            created=CLUE_FIELDS["hubspot"][:2],
            permission_set_id=None,
            label_type_id=None,
            status="partial",
        )
        proposed = await _propose(conn, seeded)
        assert proposed["state"] == "awaiting_permission"

    _run(tmp_path, "partial", body)


def test_another_project_is_refused(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        code, _ = await _refusal(conn, seeded, "prj_not_this_one")
        assert code == "project_not_found"

    _run(tmp_path, "other-project", body)
