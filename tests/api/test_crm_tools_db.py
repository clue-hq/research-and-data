"""The CRM agent tools (CRM integration Tasks 7–8). ``connect_crm@1``: report the workspace's
connection, or open one connect card per presenting turn (R-3.10). ``find_crm_actions@1`` /
``run_crm_action@1``: reads only, every result written to ``reads/``, the Salesforce budget kept."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from clue_api.crm.composio_gateway import ComposioError, ExecuteResult, ToolInfo
from clue_api.crm.connections import activate_from_attempt, latest_connection, start_attempt
from clue_api.crm.read_sinks import CrmReadSinks
from clue_api.crm.tools import (
    ConnectCrmInput,
    ConnectCrmTool,
    FindCrmActionsInput,
    FindCrmActionsTool,
    RunCrmActionInput,
    RunCrmActionTool,
)
from clue_api.turn_action import derive_turn_action_ref
from clue_config import Settings
from clue_core import new_execution_id, new_operation_id
from clue_toolbelt import PreconditionFailed, ToolContext
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


# --- reads (Task 8) -------------------------------------------------------------------------

_DEALS = {"results": [{"id": "1", "properties": {"dealname": "Acme"}}], "total": 1}


class _FakeComposio:
    def __init__(
        self,
        *,
        result: ExecuteResult | None = None,
        error: ComposioError | None = None,
        limits: dict[str, Any] | None = None,
        tools: list[ToolInfo] | None = None,
    ) -> None:
        self.result = result or ExecuteResult(successful=True, data=_DEALS, error=None)
        self.error = error
        self.limits = limits or {"DailyApiRequests": {"Max": 15000, "Remaining": 14000}}
        self.tools = tools or []
        self.executed: list[dict[str, Any]] = []

    async def search_tools(self, **_: Any) -> list[ToolInfo]:
        return self.tools

    async def execute(self, **kwargs: Any) -> ExecuteResult:
        self.executed.append(kwargs)
        if kwargs["slug"] == "SALESFORCE_GET_ORG_LIMITS":
            return ExecuteResult(successful=True, data=self.limits, error=None)
        if self.error is not None:
            raise self.error
        return self.result


class _Sink:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    def write_spill(self, operation_id: str, data: bytes) -> str:
        self.files[operation_id] = data
        return f"reads/{operation_id}.json"


def _reader(conn: Any, gateway: _FakeComposio, sinks: CrmReadSinks | None) -> RunCrmActionTool:
    return RunCrmActionTool(
        settings=_settings(),
        gateway=gateway,  # type: ignore[arg-type]
        read_sinks=sinks,
        conn_factory=conn_session_factory(conn),
    )


def _turn_ctx(conn: Any, workspace_id: str, sinks: CrmReadSinks) -> tuple[ToolContext, _Sink]:
    execution_id = new_execution_id()
    sink = _Sink()
    sinks.register(execution_id, sink)
    ctx = ToolContext(
        workspace_id=workspace_id,
        actor="agent",
        conn_factory=conn_session_factory(conn),
        operation_id=new_operation_id(),
        execution_id=execution_id,
    )
    return ctx, sink


async def _codes(tool: RunCrmActionTool, slug: str, ctx: ToolContext) -> list[str]:
    inputs = RunCrmActionInput(slug=slug, arguments={})
    failures = list(await tool.preconditions(inputs, ctx))
    if failures:
        return [failure.reason_code for failure in failures]
    try:
        await tool.invoke(inputs, ctx)
    except PreconditionFailed as exc:
        return list(exc.reason_codes)
    return []


def test_run_writes_reads_file_even_when_small(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any) -> None:
        await _connect(conn, seeded.workspace_id)
        sinks = CrmReadSinks()
        ctx, sink = _turn_ctx(conn, seeded.workspace_id, sinks)
        gateway = _FakeComposio()
        tool = _reader(conn, gateway, sinks)
        inputs = RunCrmActionInput(slug="HUBSPOT_SEARCH_DEALS", arguments={"limit": 100})
        assert await tool.preconditions(inputs, ctx) == ()
        refs = (await tool.invoke(inputs, ctx)).references
        assert refs["path"] == f"reads/{ctx.operation_id}.json"
        assert json.loads(sink.files[str(ctx.operation_id)]) == _DEALS
        assert refs["record_count"] == 1 and refs["total"] == 1 and refs["done"] is True
        assert refs["fields"] == ["id", "properties.dealname"]
        assert "Acme" not in json.dumps(refs)  # the model never gets the records
        assert gateway.executed[0]["version"] == "20261020_01"
        assert gateway.executed[0]["user_id"] == f"ws_{seeded.workspace_id}"

    _run(tmp_path, "read-small", body)


def test_unlisted_action_and_missing_sink_refuse(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any) -> None:
        await _connect(conn, seeded.workspace_id)
        sinks = CrmReadSinks()
        ctx, _sink = _turn_ctx(conn, seeded.workspace_id, sinks)
        gateway = _FakeComposio()
        tool = _reader(conn, gateway, sinks)
        assert await _codes(tool, "HUBSPOT_CREATE_DEAL", ctx) == ["crm_action_not_allowed"]
        unbound = _reader(conn, gateway, CrmReadSinks())
        assert await _codes(unbound, "HUBSPOT_SEARCH_DEALS", ctx) == ["crm_reads_unavailable"]
        assert gateway.executed == []

    _run(tmp_path, "read-refused", body)


def test_no_connection_refuses(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any) -> None:
        sinks = CrmReadSinks()
        ctx, _sink = _turn_ctx(conn, seeded.workspace_id, sinks)
        tool = _reader(conn, _FakeComposio(), sinks)
        assert await _codes(tool, "HUBSPOT_SEARCH_DEALS", ctx) == ["crm_not_connected"]

    _run(tmp_path, "read-unconnected", body)


def test_expired_connection_marks_row_and_refuses(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any) -> None:
        await _connect(conn, seeded.workspace_id)
        sinks = CrmReadSinks()
        ctx, _sink = _turn_ctx(conn, seeded.workspace_id, sinks)
        expired = ComposioError("connection_expired", 410, "Connected account is EXPIRED")
        tool = _reader(conn, _FakeComposio(error=expired), sinks)
        assert await _codes(tool, "HUBSPOT_SEARCH_DEALS", ctx) == ["crm_connection_expired"]
        current = await latest_connection(conn, workspace_id=seeded.workspace_id)
        assert current is not None and current.status == "expired"
        # connect_crm now offers a reconnect card
        refs = (
            await _tool(conn).invoke(_input(seeded), _ctx(conn, seeded.workspace_id))
        ).references
        assert refs["mode"] == "reconnect"

    _run(tmp_path, "read-expired", body)


def test_a_failed_read_returns_the_crms_reason(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any) -> None:
        await _connect(conn, seeded.workspace_id)
        sinks = CrmReadSinks()
        ctx, sink = _turn_ctx(conn, seeded.workspace_id, sinks)
        failed = ExecuteResult(successful=False, data=None, error="Property 'x' does not exist")
        tool = _reader(conn, _FakeComposio(result=failed), sinks)
        inputs = RunCrmActionInput(slug="HUBSPOT_SEARCH_DEALS", arguments={})
        with pytest.raises(PreconditionFailed) as refused:
            await tool.invoke(inputs, ctx)
        assert refused.value.reason_codes == ("crm_action_failed",)
        assert "Property 'x' does not exist" in refused.value.failures[0].message
        assert sink.files == {}

    _run(tmp_path, "read-failed", body)


async def _calls_today(conn: Any, workspace_id: str) -> int:
    return int(
        (
            await conn.execute(
                text(
                    "SELECT api_calls_count FROM workspace_integration_connection "
                    "WHERE workspace_id = :ws AND status = 'active'"
                ),
                {"ws": workspace_id},
            )
        ).scalar_one()
    )


def test_salesforce_reads_are_counted(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any) -> None:
        await _connect(conn, seeded.workspace_id, "salesforce")
        sinks = CrmReadSinks()
        gateway = _FakeComposio(
            result=ExecuteResult(successful=True, data={"records": [], "done": True}, error=None)
        )
        tool = _reader(conn, gateway, sinks)
        for _ in range(2):
            ctx, _sink = _turn_ctx(conn, seeded.workspace_id, sinks)
            assert await _codes(tool, "SALESFORCE_RUN_SOQL_QUERY", ctx) == []
        # one limits lookup (cached for the second read) + two reads
        assert await _calls_today(conn, seeded.workspace_id) == 3
        assert [call["slug"] for call in gateway.executed].count("SALESFORCE_GET_ORG_LIMITS") == 1
        assert gateway.executed[-1]["version"] == "20261018_00"

    _run(tmp_path, "sf-counted", body)


def test_salesforce_share_exhausted_refuses(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any) -> None:
        await _connect(conn, seeded.workspace_id, "salesforce")
        sinks = CrmReadSinks()
        # 10% of Max = 10 calls; the limits lookup is call 1, then nine reads fit.
        gateway = _FakeComposio(limits={"DailyApiRequests": {"Max": 100, "Remaining": 90}})
        tool = _reader(conn, gateway, sinks)
        for _ in range(9):
            ctx, _sink = _turn_ctx(conn, seeded.workspace_id, sinks)
            assert await _codes(tool, "SALESFORCE_RUN_SOQL_QUERY", ctx) == []
        ctx, _sink = _turn_ctx(conn, seeded.workspace_id, sinks)
        assert await _codes(tool, "SALESFORCE_RUN_SOQL_QUERY", ctx) == [
            "salesforce_api_share_exhausted"
        ]
        assert await _calls_today(conn, seeded.workspace_id) == 10

    _run(tmp_path, "sf-share", body)


def test_salesforce_org_low_remaining_refuses(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any) -> None:
        await _connect(conn, seeded.workspace_id, "salesforce")
        sinks = CrmReadSinks()
        ctx, _sink = _turn_ctx(conn, seeded.workspace_id, sinks)
        gateway = _FakeComposio(limits={"DailyApiRequests": {"Max": 15000, "Remaining": 1499}})
        tool = _reader(conn, gateway, sinks)
        assert await _codes(tool, "SALESFORCE_RUN_SOQL_QUERY", ctx) == [
            "salesforce_api_share_exhausted"
        ]
        assert [call["slug"] for call in gateway.executed] == ["SALESFORCE_GET_ORG_LIMITS"]

    _run(tmp_path, "sf-org-low", body)


def test_salesforce_without_api_access_refuses_plainly(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any) -> None:
        await _connect(conn, seeded.workspace_id, "salesforce")
        sinks = CrmReadSinks()
        ctx, _sink = _turn_ctx(conn, seeded.workspace_id, sinks)
        disabled = ExecuteResult(
            successful=False, data=None, error="API_DISABLED_FOR_ORG: API is not enabled"
        )
        gateway = _FakeComposio(result=disabled)
        gateway.limits = {}  # the limits lookup fails too on such an org
        original = gateway.execute

        async def execute(**kwargs: Any) -> ExecuteResult:
            if kwargs["slug"] == "SALESFORCE_GET_ORG_LIMITS":
                gateway.executed.append(kwargs)
                return disabled
            return await original(**kwargs)

        gateway.execute = execute  # type: ignore[method-assign]
        tool = _reader(conn, gateway, sinks)
        inputs = RunCrmActionInput(slug="SALESFORCE_RUN_SOQL_QUERY", arguments={})
        with pytest.raises(PreconditionFailed) as refused:
            await tool.invoke(inputs, ctx)
        assert refused.value.reason_codes == ("salesforce_api_disabled",)
        assert "Professional Edition" in refused.value.failures[0].message

    _run(tmp_path, "sf-disabled", body)


def test_find_filters_to_read_allowlist(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any) -> None:
        await _connect(conn, seeded.workspace_id)
        tools = [
            ToolInfo("HUBSPOT_SEARCH_DEALS", "Search deals", {"type": "object"}, ("readOnlyHint",)),
            ToolInfo("HUBSPOT_CREATE_DEAL", "Create a deal", {}, ()),
            ToolInfo("HUBSPOT_SEARCH_DEALS_FROM_NL", "Ask in words", {}, ("readOnlyHint",)),
            ToolInfo("HUBSPOT_LIST_DEALS", "List deals", {}, ("readOnlyHint",)),
        ]
        find = FindCrmActionsTool(
            gateway=_FakeComposio(tools=tools),  # type: ignore[arg-type]
            conn_factory=conn_session_factory(conn),
        )
        ctx = _ctx(conn, seeded.workspace_id)
        inputs = FindCrmActionsInput(query="deals", limit=10)
        assert await find.preconditions(inputs, ctx) == ()
        refs = (await find.invoke(inputs, ctx)).references
        assert refs["provider"] == "hubspot"
        assert [action["slug"] for action in refs["actions"]] == [
            "HUBSPOT_SEARCH_DEALS",
            "HUBSPOT_LIST_DEALS",
        ]
        assert refs["actions"][0]["input_schema"] == {"type": "object"}
        assert {action["access"] for action in refs["actions"]} == {"read"}

    _run(tmp_path, "find", body)


def test_find_crm_actions_lists_writes_and_run_crm_action_refuses_them(tmp_path: Path) -> None:
    async def body(conn: Any, seeded: Any) -> None:
        await _connect(conn, seeded.workspace_id)
        tools = [
            ToolInfo("HUBSPOT_UPDATE_COMPANY", "Update a company", {"type": "object"}, ()),
            ToolInfo("HUBSPOT_UPDATE_CONTACT", "Update a contact", {}, ()),
            ToolInfo("HUBSPOT_MERGE_CONTACTS", "Merge contacts", {}, ()),
            ToolInfo("HUBSPOT_SEARCH_COMPANIES", "Search companies", {}, ("readOnlyHint",)),
            ToolInfo("HUBSPOT_CREATE_CONTACT", "Create a contact", {}, ()),
        ]
        find = FindCrmActionsTool(
            gateway=_FakeComposio(tools=tools),  # type: ignore[arg-type]
            conn_factory=conn_session_factory(conn),
        )
        refs = (
            await find.invoke(
                FindCrmActionsInput(query="companies", limit=10), _ctx(conn, seeded.workspace_id)
            )
        ).references
        assert [(a["slug"], a["access"]) for a in refs["actions"]] == [
            ("HUBSPOT_UPDATE_COMPANY", "write"),
            ("HUBSPOT_SEARCH_COMPANIES", "read"),
            ("HUBSPOT_CREATE_CONTACT", "write"),
        ]

        sinks = CrmReadSinks()
        ctx, _sink = _turn_ctx(conn, seeded.workspace_id, sinks)
        gateway = _FakeComposio()
        tool = _reader(conn, gateway, sinks)
        assert await _codes(tool, "HUBSPOT_UPDATE_COMPANY", ctx) == ["crm_action_is_a_write"]
        failures = await tool.preconditions(
            RunCrmActionInput(slug="HUBSPOT_CREATE_CONTACT", arguments={}), ctx
        )
        assert "propose_crm_changes" in failures[0].message
        assert gateway.executed == []

    _run(tmp_path, "find-writes", body)
