"""The Clue-fields registry (CRM integration Phase 4, Task 1; R-13.1, R-13.2).

One ``crm_clue_fields`` row per connection records what Clue set up in that CRM: the fields it
created, the Salesforce permission set id, the HubSpot duplicate label type id, and whether
everything is there (``ready``), only some of it (``partial``) or a field has since disappeared
(``gone``). The database is the lane's test DB; nothing calls a CRM.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from clue_api.crm.clue_fields import (
    clue_fields_state,
    mark_clue_field_gone,
    record_clue_fields,
)
from clue_api.crm.connections import CrmConnection
from tests.api.test_crm_tools_db import _connect
from tests.api.test_lane_d4_agent_gate_db import USER_ID, _seed
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)


@pytest.fixture(autouse=True)
def require_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


def _run(tmp_path: Path, label: str, body: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id=f"ws-crmcf-{label}", label=label)
            connection = await _connect(conn, seeded.workspace_id)
            await body(conn, seeded, connection)

    run_async(scenario())


async def _other_connection(conn: Any, workspace_id: str, provider: str) -> UUID:
    connection_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO workspace_integration_connection (connection_id, workspace_id, provider, "
            "composio_connected_account_id, composio_auth_config_id, status, connected_by_user_id) "
            "VALUES (:id, :ws, :provider, :acct, 'ac_test', 'disconnected', :u)"
        ),
        {
            "id": connection_id,
            "ws": workspace_id,
            "provider": provider,
            "acct": f"ca_{uuid4().hex[:8]}",
            "u": USER_ID,
        },
    )
    return connection_id


_HUBSPOT_NAMES = (
    "clue_tier",
    "clue_research_link",
    "clue_id",
    "clue_committee_role",
    "clue_contact_link",
)


def test_nothing_is_recorded_before_setup(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        assert await clue_fields_state(conn, connection_id=connection.connection_id) is None

    _run(tmp_path, "none", body)


def test_setup_is_recorded_per_connection(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        await record_clue_fields(
            conn,
            connection_id=connection.connection_id,
            workspace_id=seeded.workspace_id,
            provider="hubspot",
            created=_HUBSPOT_NAMES,
            permission_set_id=None,
            label_type_id="42",
            status="ready",
        )
        state = await clue_fields_state(conn, connection_id=connection.connection_id)
        assert state is not None
        assert state.status == "ready"
        assert state.provider == "hubspot"
        assert state.created_names == _HUBSPOT_NAMES
        assert state.gone_names == ()
        assert state.label_type_id == "42"
        assert state.permission_set_id is None
        assert state.gone_at is None

        other = await _other_connection(conn, seeded.workspace_id, "hubspot")
        assert await clue_fields_state(conn, connection_id=other) is None

    _run(tmp_path, "perconn", body)


def test_recording_again_replaces_the_row(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        sf = await _other_connection(conn, seeded.workspace_id, "salesforce")
        common = {
            "connection_id": sf,
            "workspace_id": seeded.workspace_id,
            "provider": "salesforce",
            "label_type_id": None,
        }
        await record_clue_fields(
            conn,
            **common,
            created=("Clue_Tier__c",),
            permission_set_id=None,
            status="partial",
        )
        await mark_clue_field_gone(conn, connection_id=sf, crm_name="Clue_Tier__c")
        await record_clue_fields(
            conn,
            **common,
            created=("Clue_Tier__c", "Clue_Id__c"),
            permission_set_id="0PS000000000001",
            status="ready",
        )
        state = await clue_fields_state(conn, connection_id=sf)
        assert state is not None
        assert state.status == "ready"
        assert state.created_names == ("Clue_Tier__c", "Clue_Id__c")
        assert state.permission_set_id == "0PS000000000001"
        # A completed setup put the field back: nothing is gone any more.
        assert state.gone_names == ()
        assert state.gone_at is None

    _run(tmp_path, "again", body)


def test_a_field_found_gone_flips_the_state_to_gone(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        await record_clue_fields(
            conn,
            connection_id=connection.connection_id,
            workspace_id=seeded.workspace_id,
            provider="hubspot",
            created=_HUBSPOT_NAMES,
            permission_set_id=None,
            label_type_id="42",
            status="ready",
        )
        await mark_clue_field_gone(
            conn, connection_id=connection.connection_id, crm_name="clue_tier"
        )
        first = await clue_fields_state(conn, connection_id=connection.connection_id)
        assert first is not None
        assert first.status == "gone"
        assert first.gone_names == ("clue_tier",)
        assert first.gone_at is not None
        # Still recorded as created: Clue made it; the CRM no longer has it.
        assert first.created_names == _HUBSPOT_NAMES

        await mark_clue_field_gone(
            conn, connection_id=connection.connection_id, crm_name="clue_tier"
        )
        await mark_clue_field_gone(conn, connection_id=connection.connection_id, crm_name="clue_id")
        second = await clue_fields_state(conn, connection_id=connection.connection_id)
        assert second is not None
        assert second.gone_names == ("clue_tier", "clue_id")
        assert second.gone_at == first.gone_at  # when it was FIRST found gone

    _run(tmp_path, "gone", body)


def test_marking_gone_without_a_setup_records_nothing(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any, connection: CrmConnection) -> None:
        await mark_clue_field_gone(
            conn, connection_id=connection.connection_id, crm_name="clue_tier"
        )
        assert await clue_fields_state(conn, connection_id=connection.connection_id) is None

    _run(tmp_path, "nosetup", body)
