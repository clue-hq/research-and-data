"""The CRM agent tools (CRM integration Tasks 7–8). ``connect_crm@1``: report the workspace's
connection, or open one connect card per presenting turn (R-3.10)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from clue_api.crm.connections import activate_from_attempt, start_attempt
from clue_api.crm.tools import ConnectCrmInput, ConnectCrmTool
from clue_api.turn_action import derive_turn_action_ref
from clue_config import Settings
from clue_core import new_operation_id
from clue_toolbelt import ToolContext
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


def _settings(*, hubspot: str = "ac_h", salesforce: str = "ac_s") -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        crm_integration_enabled=True,
        composio_hubspot_auth_config_id=hubspot,
        composio_salesforce_auth_config_id=salesforce,
    )


def _tool(
    conn: Any, *, configured: bool = True, settings: Settings | None = None
) -> ConnectCrmTool:
    return ConnectCrmTool(
        settings=settings or _settings(),
        configured=configured,
        conn_factory=conn_session_factory(conn),
    )


def _ctx(conn: Any, workspace_id: str) -> ToolContext:
    return ToolContext(
        workspace_id=workspace_id,
        actor="agent",
        conn_factory=conn_session_factory(conn),
        operation_id=new_operation_id(),
    )


def _input(seeded: Any, *, switch: bool = False) -> ConnectCrmInput:
    return ConnectCrmInput(switch=switch, source_turn_ref=derive_turn_action_ref(seeded.turn_id))


async def _connect(conn: Any, workspace_id: str, provider: str = "hubspot") -> Any:
    seeded_turn_request = await conn.execute(
        text(
            "INSERT INTO crm_connect_request (request_id, workspace_id, project_id, thread_id, "
            "turn_id, requested_by_user_id, mode) VALUES (gen_random_uuid(), :ws, 'p', 't', "
            "gen_random_uuid(), :user, 'connect') RETURNING request_id"
        ),
        {"ws": workspace_id, "user": USER_ID},
    )
    request_id = seeded_turn_request.scalar_one()
    await start_attempt(
        conn,
        request_id=request_id,
        workspace_id=workspace_id,
        provider=provider,  # type: ignore[arg-type]
        connected_account_id=f"ca_{provider}",
        started_by_user_id=USER_ID,
    )
    activated = await activate_from_attempt(
        conn,
        request_id=request_id,
        workspace_id=workspace_id,
        connected_account_id=f"ca_{provider}",
        auth_config_id="ac_h",
    )
    assert activated is not None
    return activated[0]


def _run(tmp_path: Path, label: str, body: Any) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id=f"ws-crm-{label}", label=label)
            await body(conn, seeded)

    run_async(scenario())


def test_an_unconnected_workspace_gets_one_card_per_turn(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any) -> None:
        tool = _tool(conn)
        ctx = _ctx(conn, seeded.workspace_id)
        assert await tool.preconditions(_input(seeded), ctx) == ()
        first = (await tool.invoke(_input(seeded), ctx)).references
        again = (await tool.invoke(_input(seeded), _ctx(conn, seeded.workspace_id))).references
        assert first["state"] == "card" and first["mode"] == "connect"
        assert first["request_id"] == again["request_id"]
        assert first["providers"] == ["hubspot", "salesforce"]
        assert first["can_connect"] is True
        assert first["connection"] is None

    _run(tmp_path, "card", body)


def test_a_connected_workspace_is_reported_without_a_card(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any) -> None:
        await _connect(conn, seeded.workspace_id)
        refs = (
            await _tool(conn).invoke(_input(seeded), _ctx(conn, seeded.workspace_id))
        ).references
        assert refs["state"] == "connected" and refs["request_id"] is None
        assert refs["connection"]["provider"] == "hubspot"
        assert refs["connection"]["status"] == "active"
        assert "ca_hubspot" not in str(refs)  # no Composio ids reach the model

    _run(tmp_path, "connected", body)


def test_an_expired_connection_opens_a_reconnect_card(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any) -> None:
        connection = await _connect(conn, seeded.workspace_id)
        await conn.execute(
            text(
                "UPDATE workspace_integration_connection SET status = 'expired' "
                "WHERE connection_id = :id"
            ),
            {"id": connection.connection_id},
        )
        refs = (
            await _tool(conn).invoke(_input(seeded), _ctx(conn, seeded.workspace_id))
        ).references
        assert refs["state"] == "card" and refs["mode"] == "reconnect"
        assert refs["connection"]["status"] == "expired"

    _run(tmp_path, "reconnect", body)


def test_switching_opens_a_switch_card(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any) -> None:
        await _connect(conn, seeded.workspace_id)
        refs = (
            await _tool(conn).invoke(_input(seeded, switch=True), _ctx(conn, seeded.workspace_id))
        ).references
        assert refs["state"] == "card" and refs["mode"] == "switch"

    _run(tmp_path, "switch", body)


def test_a_member_without_manage_settings_cannot_connect(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any) -> None:
        await conn.execute(
            text(
                "UPDATE workspace_membership SET role_key = 'operator' "
                "WHERE workspace_id = :ws AND user_id = :user"
            ),
            {"ws": seeded.workspace_id, "user": USER_ID},
        )
        refs = (
            await _tool(conn).invoke(_input(seeded), _ctx(conn, seeded.workspace_id))
        ).references
        assert refs["state"] == "card" and refs["can_connect"] is False

    _run(tmp_path, "operator", body)


def test_only_crms_with_an_auth_config_are_offered(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any) -> None:
        tool = _tool(conn, settings=_settings(salesforce=""))
        refs = (await tool.invoke(_input(seeded), _ctx(conn, seeded.workspace_id))).references
        assert refs["providers"] == ["hubspot"]

    _run(tmp_path, "offered", body)


@pytest.mark.parametrize(
    ("configured", "hubspot", "salesforce"),
    [(False, "ac_h", "ac_s"), (True, "", "")],
    ids=["no-composio-key", "no-auth-config"],
)
def test_not_configured_refuses(
    tmp_path: Path, configured: bool, hubspot: str, salesforce: str
) -> None:
    async def body(conn: Any, seeded: Any) -> None:
        tool = _tool(
            conn, configured=configured, settings=_settings(hubspot=hubspot, salesforce=salesforce)
        )
        codes = [
            failure.reason_code
            for failure in await tool.preconditions(_input(seeded), _ctx(conn, seeded.workspace_id))
        ]
        assert codes == ["crm_not_configured"]

    _run(tmp_path, f"notconfigured-{configured}", body)
