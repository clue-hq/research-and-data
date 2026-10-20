"""The Head of ABM's CRM tools (spec docs/superpowers/specs/crm-integration/, design §4–§5).

``connect_crm@1`` reports the workspace's CRM connection or shows a connect card (R-3.10): the
card is drawn by the chat from this tool's own result, and the person's login happens in another
tab; when the connection becomes active every chat waiting on a card is woken with a
``crm_connected`` turn, so after showing a card the agent simply ends its turn.

Composio account ids never reach the model; it sees the CRM name, the status and when/by whom.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, Field, StringConstraints

from clue_agents.manual import tool_manual_link
from clue_api.crm.composio_gateway import CrmProvider, build_composio_gateway
from clue_api.crm.connections import CrmConnection, latest_connection, open_connect_request
from clue_api.turn_action import TurnActionUnresolvable, load_turn_identity, parse_turn_action_ref
from clue_api.turn_binding import TRUSTED_TURN_FIELD
from clue_auth import get_workspace_membership, permissions_for_role
from clue_config import Secrets, Settings
from clue_db import ConnFactory, transaction
from clue_spine import get_project
from clue_toolbelt import (
    ExternalReplayBoundary,
    JournalParameterPolicy,
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
    "CrmConnectionView",
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


def build_crm_tools(
    *,
    settings: Settings,
    secrets: Secrets | None,
    conn_factory: ConnFactory = transaction,
) -> tuple[Tool, ...]:
    """The CRM tools, always registered (one registry shape); they refuse when not configured."""
    configured = build_composio_gateway(settings=settings, secrets=secrets) is not None
    return (ConnectCrmTool(settings=settings, configured=configured, conn_factory=conn_factory),)
