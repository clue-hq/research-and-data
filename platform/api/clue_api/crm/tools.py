"""The Head of ABM's CRM tools (spec docs/superpowers/specs/crm-integration/, design §4–§5).

``connect_crm@1`` reports the workspace's CRM connection or shows a connect card (R-3.10): the
card is drawn by the chat from this tool's own result, and the person's login happens in another
tab; when the connection becomes active every chat waiting on a card is woken with a
``crm_connected`` turn, so after showing a card the agent simply ends its turn.

``find_crm_actions@1`` searches the connected CRM's read actions, and ``run_crm_action@1`` runs
one. A read's whole result is written to ``reads/<operation_id>.json`` in the thread's workspace,
however small, and the model is told only where it is and what it holds (§5): the records are
analysed in the code sandbox, never pasted into the conversation.

Composio account ids never reach the model; it sees the CRM name, the status and when/by whom.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Annotated, Any, ClassVar, Literal

from pydantic import BaseModel, Field, StringConstraints

from clue_agents.manual import tool_manual_link
from clue_api.crm.composio_gateway import (
    ComposioError,
    ComposioGateway,
    CrmProvider,
    build_composio_gateway,
    composio_user_id,
)
from clue_api.crm.connections import (
    CrmConnection,
    latest_connection,
    mark_expired,
    open_connect_request,
)
from clue_api.crm.read_actions import is_readable, summarize
from clue_api.crm.read_sinks import CrmReadSinks
from clue_api.crm.salesforce_budget import (
    API_DISABLED_MESSAGE,
    CrmBudgetExhausted,
    SalesforceBudget,
    is_api_disabled,
)
from clue_api.turn_action import TurnActionUnresolvable, load_turn_identity, parse_turn_action_ref
from clue_api.turn_binding import TRUSTED_TURN_FIELD
from clue_auth import get_workspace_membership, permissions_for_role
from clue_config import Secrets, Settings
from clue_db import ConnFactory, transaction
from clue_spine import get_project
from clue_toolbelt import (
    ExternalReplayBoundary,
    JournalParameterPolicy,
    PreconditionFailed,
    PreconditionFailure,
    ReplayPolicy,
    ReplaySafety,
    Tool,
    ToolContext,
    ToolEffectClass,
    ToolEstimate,
    ToolInput,
    ToolOutput,
    ToolResult,
)

__all__ = [
    "ConnectCrmInput",
    "ConnectCrmOutput",
    "ConnectCrmTool",
    "CrmActionView",
    "CrmConnectionView",
    "FindCrmActionsInput",
    "FindCrmActionsOutput",
    "FindCrmActionsTool",
    "RunCrmActionInput",
    "RunCrmActionOutput",
    "RunCrmActionTool",
    "build_crm_tools",
]

_MANAGE: str = "workspace.manage_settings"
_PROVIDERS: tuple[CrmProvider, ...] = ("hubspot", "salesforce")


class ConnectCrmInput(ToolInput):
    #: Only when the person asked to replace the connected CRM with another one.
    switch: bool = False
    source_turn_ref: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000),
    ] = Field(json_schema_extra={TRUSTED_TURN_FIELD: True})


class CrmConnectionView(BaseModel):
    provider: CrmProvider
    status: str
    connected_at: datetime
    connected_by_user_id: str


class ConnectCrmOutput(ToolOutput):
    state: Literal["connected", "card"]
    mode: Literal["connect", "reconnect", "switch"] | None
    request_id: str | None
    providers: list[CrmProvider]
    can_connect: bool
    connection: CrmConnectionView | None


class _Refused(ValueError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


def _offered(settings: Settings) -> list[CrmProvider]:
    configured = {
        "hubspot": settings.composio_hubspot_auth_config_id.strip(),
        "salesforce": settings.composio_salesforce_auth_config_id.strip(),
    }
    return [provider for provider in _PROVIDERS if configured[provider]]


def _view(connection: CrmConnection | None) -> CrmConnectionView | None:
    if connection is None:
        return None
    return CrmConnectionView(
        provider=connection.provider,
        status=connection.status,
        connected_at=connection.connected_at,
        connected_by_user_id=connection.connected_by_user_id,
    )


class ConnectCrmTool(Tool):
    name = "connect_crm"
    version = "1"
    model_description = (
        "Report the workspace's CRM connection (HubSpot or Salesforce), or show the person a card "
        "to connect it. When the result's state is 'card', tell the person to use the card and end "
        "your turn: the chat continues by itself once the CRM is connected. Pass switch=true only "
        "when the person asked to replace the connected CRM with another one. "
        + tool_manual_link("connect_crm")
    )
    input_model: ClassVar[type[ToolInput]] = ConnectCrmInput
    output_model: ClassVar[type[ToolOutput]] = ConnectCrmOutput
    effect_class = ToolEffectClass.WRITE
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="one connect card per presenting turn (crm_connect_request.turn_id)",
        external_boundary=ExternalReplayBoundary.NONE,
    )
    parameter_policy = JournalParameterPolicy(safe_display_fields=("switch",))
    pin_requirements = ("project",)

    def __init__(
        self,
        *,
        settings: Settings,
        configured: bool,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._settings = settings
        self._configured = configured
        self._conn_factory = conn_factory

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        del inputs
        return ToolEstimate.free()

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, ConnectCrmInput)
        try:
            self._require_configured()
            await self._turn(inputs, ctx)
        except _Refused as exc:
            return (PreconditionFailure(reason_code=exc.reason_code, message=str(exc)),)
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ConnectCrmInput)
        self._require_configured()
        turn_id, project_id, thread_id, user_id = await self._turn(inputs, ctx)
        async with self._conn_factory() as conn:
            current = await latest_connection(conn, workspace_id=ctx.workspace_id)
            active = current is not None and current.status == "active"
            if active and not inputs.switch:
                output = ConnectCrmOutput(
                    state="connected",
                    mode=None,
                    request_id=None,
                    providers=_offered(self._settings),
                    can_connect=False,
                    connection=_view(current),
                )
                return self._result(output)
            mode: Literal["connect", "reconnect", "switch"] = (
                "switch"
                if active
                else "reconnect"
                if current is not None and current.status == "expired"
                else "connect"
            )
            request = await open_connect_request(
                conn,
                workspace_id=ctx.workspace_id,
                project_id=project_id,
                thread_id=thread_id,
                turn_id=turn_id,
                requested_by_user_id=user_id,
                mode=mode,
            )
            membership = await get_workspace_membership(
                conn, workspace_id=ctx.workspace_id, user_id=user_id
            )
        can_connect = (
            membership is not None
            and membership.status == "active"
            and _MANAGE in permissions_for_role(membership.role_key)
        )
        output = ConnectCrmOutput(
            state="card",
            mode=request.mode,  # type: ignore[arg-type]
            request_id=str(request.request_id),
            providers=_offered(self._settings),
            can_connect=can_connect,
            connection=_view(current),
        )
        return self._result(output)

    def _result(self, output: ConnectCrmOutput) -> ToolResult:
        return ToolResult(
            tool=self.name, version=self.version, references=output.model_dump(mode="json")
        )

    def _require_configured(self) -> None:
        if not self._configured or not _offered(self._settings):
            raise _Refused(
                "crm_not_configured",
                "The CRM integration is not configured in this deployment.",
            )

    async def _turn(self, inputs: ConnectCrmInput, ctx: ToolContext) -> tuple:  # type: ignore[type-arg]
        try:
            turn_id = parse_turn_action_ref(inputs.source_turn_ref)
        except TurnActionUnresolvable as exc:
            raise _Refused("crm_turn_not_found", "The current turn is unavailable.") from exc
        async with self._conn_factory() as conn:
            turn = await load_turn_identity(conn, workspace_id=ctx.workspace_id, turn_id=turn_id)
            if turn is None or not turn.submitted_by_user_id:
                raise _Refused("crm_turn_not_found", "The current turn has no person to ask.")
            project = await get_project(conn, turn.project_id)
        if project is None or project.workspace_id != ctx.workspace_id:
            raise _Refused("crm_project_unavailable", "The current turn's project is unavailable.")
        return turn_id, turn.project_id, turn.thread_id, turn.submitted_by_user_id


class FindCrmActionsInput(ToolInput):
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    limit: int = Field(default=10, ge=1, le=25)


class CrmActionView(BaseModel):
    slug: str
    description: str
    input_schema: dict[str, Any]


class FindCrmActionsOutput(ToolOutput):
    provider: CrmProvider
    actions: list[CrmActionView]


class RunCrmActionInput(ToolInput):
    slug: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    arguments: dict[str, Any] = Field(default_factory=dict)


class RunCrmActionOutput(ToolOutput):
    provider: CrmProvider
    slug: str
    #: Where the whole result was written; read it with the file tools or ``run_python``.
    path: str
    record_count: int | None
    total: int | None
    fields: list[str]
    next_cursor: str | None
    done: bool


def _refuse(code: str, message: str) -> PreconditionFailed:
    return PreconditionFailed([PreconditionFailure(code, message)])


async def _active_connection(conn_factory: ConnFactory, workspace_id: str) -> CrmConnection:
    async with conn_factory() as conn:
        current = await latest_connection(conn, workspace_id=workspace_id)
    if current is None or current.status != "active":
        raise _Refused(
            "crm_not_connected",
            "No CRM is connected"
            + (" (the last connection has expired)" if current is not None else "")
            + ". Call connect_crm to ask the person to connect one.",
        )
    return current


class FindCrmActionsTool(Tool):
    name = "find_crm_actions"
    version = "1"
    model_description = (
        "Search the connected CRM's read actions by what you want to read, e.g. 'search deals', "
        "'deal pipeline stages', 'contacts of a company', 'run a SOQL query'. Returns each "
        "action's name and its input schema; run one with run_crm_action. Only read actions are "
        "listed. " + tool_manual_link("find_crm_actions")
    )
    input_model: ClassVar[type[ToolInput]] = FindCrmActionsInput
    output_model: ClassVar[type[ToolOutput]] = FindCrmActionsOutput
    effect_class = ToolEffectClass.READ
    replay = ReplaySafety(
        policy=ReplayPolicy.EFFECT_FREE,
        durable_identity="none: a catalogue search writes nothing",
        external_boundary=ExternalReplayBoundary.NONE,
    )
    parameter_policy = JournalParameterPolicy(safe_display_fields=("query", "limit"))
    #: The execution's own project, like every tool of the conversation recipe (its body is a
    #: search text and names no project).
    pin_requirements = ("project",)

    def __init__(
        self, *, gateway: ComposioGateway | None, conn_factory: ConnFactory = transaction
    ) -> None:
        self._gateway = gateway
        self._conn_factory = conn_factory

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        del inputs
        return ToolEstimate.free()

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        del inputs
        try:
            _require_gateway(self._gateway)
            await _active_connection(self._conn_factory, ctx.workspace_id)
        except _Refused as exc:
            return (PreconditionFailure(reason_code=exc.reason_code, message=str(exc)),)
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, FindCrmActionsInput)
        gateway = _require_gateway(self._gateway)
        connection = await _active_connection(self._conn_factory, ctx.workspace_id)
        try:
            # Ask for more than the limit: the search is over every action, writes included.
            found = await gateway.search_tools(
                toolkit=connection.provider, query=inputs.query, limit=min(inputs.limit * 4, 100)
            )
        except ComposioError as exc:
            raise _refuse(
                "crm_unavailable", f"The CRM action search failed: {exc.message}"
            ) from exc
        actions = [
            CrmActionView(
                slug=tool.slug, description=tool.description, input_schema=dict(tool.input_schema)
            )
            for tool in found
            if is_readable(connection.provider, tool.slug)
        ][: inputs.limit]
        output = FindCrmActionsOutput(provider=connection.provider, actions=actions)
        return ToolResult(
            tool=self.name, version=self.version, references=output.model_dump(mode="json")
        )


class RunCrmActionTool(Tool):
    name = "run_crm_action"
    version = "1"
    model_description = (
        "Run one read action on the connected CRM (find it first with find_crm_actions). The "
        "whole result is written to a file in reads/ and you get back its path, how many records "
        "it holds, their field names and, when there are more pages, next_cursor to pass back as "
        "the page argument (HubSpot: 'after'; Salesforce: run SALESFORCE_QUERY_MORE with it). "
        "Analyse the file with run_python; do not paste records into the chat. "
        + tool_manual_link("run_crm_action")
    )
    input_model: ClassVar[type[ToolInput]] = RunCrmActionInput
    output_model: ClassVar[type[ToolOutput]] = RunCrmActionOutput
    effect_class = ToolEffectClass.SPEND
    replay = ReplaySafety(
        policy=ReplayPolicy.AT_LEAST_ONCE,
        durable_identity="reads/<operation_id>.json, rewritten by a re-run of the same operation",
        operation_id_required=True,
        external_boundary=ExternalReplayBoundary.AT_LEAST_ONCE,
        notes=(
            "A retry repeats one CRM read (and, on Salesforce, counts it against the org's daily "
            "API share again); the file it writes is named by the operation, so it is replaced, "
            "not duplicated."
        ),
    )
    #: The arguments can name people and companies, so only the action's name is displayed.
    parameter_policy = JournalParameterPolicy(safe_display_fields=("slug",))
    pin_requirements = ("project",)

    def __init__(
        self,
        *,
        settings: Settings,
        gateway: ComposioGateway | None,
        read_sinks: CrmReadSinks | None,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._settings = settings
        self._gateway = gateway
        self._read_sinks = read_sinks
        self._conn_factory = conn_factory
        self._budget = (
            None
            if gateway is None
            else SalesforceBudget(
                gateway,
                share_pct=settings.crm_salesforce_api_share_pct,
                version=settings.composio_salesforce_toolkit_version,
            )
        )

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        del inputs
        return ToolEstimate.free()

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, RunCrmActionInput)
        try:
            _require_gateway(self._gateway)
            connection = await _active_connection(self._conn_factory, ctx.workspace_id)
            _require_readable(connection.provider, inputs.slug)
            self._sink(ctx)
        except _Refused as exc:
            return (PreconditionFailure(reason_code=exc.reason_code, message=str(exc)),)
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, RunCrmActionInput)
        try:
            gateway = _require_gateway(self._gateway)
            connection = await _active_connection(self._conn_factory, ctx.workspace_id)
            _require_readable(connection.provider, inputs.slug)
            sink = self._sink(ctx)
        except _Refused as exc:
            raise _refuse(exc.reason_code, str(exc)) from exc
        try:
            if connection.provider == "salesforce":
                await self._take_salesforce_call(connection)
            result = await gateway.execute(
                slug=inputs.slug,
                arguments=inputs.arguments,
                connected_account_id=connection.composio_connected_account_id,
                user_id=composio_user_id(connection.workspace_id),
                version=self._version(connection.provider),
            )
        except ComposioError as exc:
            raise await self._composio_refusal(exc, connection) from exc
        if not result.successful:
            if connection.provider == "salesforce" and is_api_disabled(result.error):
                raise _refuse("salesforce_api_disabled", API_DISABLED_MESSAGE)
            raise _refuse(
                "crm_action_failed",
                f"The CRM refused the read: {result.error or 'no reason given'}",
            )
        path = sink.write_spill(
            str(ctx.operation_id),
            json.dumps(result.data, ensure_ascii=False, indent=2, default=str).encode(),
        )
        summary = summarize(connection.provider, inputs.slug, result.data)
        output = RunCrmActionOutput(
            provider=connection.provider,
            slug=inputs.slug,
            path=path,
            record_count=summary.record_count,
            total=summary.total,
            fields=summary.fields,
            next_cursor=summary.next_cursor,
            done=summary.done,
        )
        return ToolResult(
            tool=self.name, version=self.version, references=output.model_dump(mode="json")
        )

    def _sink(self, ctx: ToolContext) -> Any:
        sink = (
            None
            if self._read_sinks is None or ctx.execution_id is None
            else self._read_sinks.sink_for(ctx.execution_id)
        )
        if sink is None:
            raise _Refused(
                "crm_reads_unavailable",
                "This call is not part of a chat turn with a workspace, so a CRM read has "
                "nowhere to be written.",
            )
        return sink

    def _version(self, provider: CrmProvider) -> str:
        if provider == "hubspot":
            return self._settings.composio_hubspot_toolkit_version
        return self._settings.composio_salesforce_toolkit_version

    async def _take_salesforce_call(self, connection: CrmConnection) -> None:
        assert self._budget is not None
        refusal: CrmBudgetExhausted | None = None
        async with self._conn_factory() as conn:
            try:
                await self._budget.take_call(
                    conn, connection=connection, today=datetime.now(UTC).date()
                )
            except CrmBudgetExhausted as exc:
                refusal = exc  # keep the limits lookup counted: it did reach Salesforce
        if refusal is not None:
            raise _refuse(refusal.reason_code, str(refusal))

    async def _composio_refusal(
        self, exc: ComposioError, connection: CrmConnection
    ) -> PreconditionFailed:
        if exc.kind == "connection_expired":
            async with self._conn_factory() as conn:
                await mark_expired(conn, connection_id=connection.connection_id)
            return _refuse(
                "crm_connection_expired",
                "The CRM connection has expired or was revoked. Call connect_crm to ask the "
                "person to reconnect it.",
            )
        if exc.kind == "rate_limited":
            return _refuse("crm_rate_limited", "The CRM is rate-limiting reads; try again shortly.")
        if exc.kind == "unavailable":
            return _refuse("crm_unavailable", f"The CRM could not be reached: {exc.message}")
        return _refuse("crm_action_failed", f"The CRM read failed: {exc.message}")


def _require_gateway(gateway: ComposioGateway | None) -> ComposioGateway:
    if gateway is None:
        raise _Refused(
            "crm_not_configured", "The CRM integration is not configured in this deployment."
        )
    return gateway


def _require_readable(provider: CrmProvider, slug: str) -> None:
    if not is_readable(provider, slug):
        raise _Refused(
            "crm_action_not_allowed",
            f"{slug} is not one of the read actions Clue may run on "
            f"{'HubSpot' if provider == 'hubspot' else 'Salesforce'}. Use find_crm_actions to "
            "see the ones it can.",
        )


def build_crm_tools(
    *,
    settings: Settings,
    secrets: Secrets | None,
    conn_factory: ConnFactory = transaction,
    read_sinks: CrmReadSinks | None = None,
) -> tuple[Tool, ...]:
    """The CRM tools, always registered (one registry shape); they refuse when not configured.

    ``read_sinks`` is the registry the conversation engine binds each turn's workspace into; it
    exists only where turns are driven (the fleet worker), and ``run_crm_action`` refuses
    ``crm_reads_unavailable`` everywhere else.
    """
    gateway = build_composio_gateway(settings=settings, secrets=secrets)
    return (
        ConnectCrmTool(
            settings=settings, configured=gateway is not None, conn_factory=conn_factory
        ),
        FindCrmActionsTool(gateway=gateway, conn_factory=conn_factory),
        RunCrmActionTool(
            settings=settings, gateway=gateway, read_sinks=read_sinks, conn_factory=conn_factory
        ),
    )
