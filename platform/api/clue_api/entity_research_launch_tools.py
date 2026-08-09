"""R10 toolbelt surfaces for separate account/contact research launches and returns."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from pydantic import Field

from clue_api.account_research_fleet import (
    AccountResearchFleetProjection,
    AccountResearchFleetService,
)
from clue_api.account_research_fleet_launch import (
    AccountResearchFleetLauncher,
    AccountResearchFleetLaunchRequest,
)
from clue_api.auth_tool_context import require_human_authority
from clue_api.contact_research_fleet import ContactResearchFleetService
from clue_api.contact_research_fleet_launch import (
    ContactResearchFleetLauncher,
    ContactResearchFleetLaunchRequest,
    ContactResearchSelectionApprovalRequest,
    ContactResearchSelectionApprover,
)
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


class AccountResearchLaunchService(Protocol):
    async def launch(
        self,
        request: AccountResearchFleetLaunchRequest,
        *,
        actor: str,
        source_action_ref: str,
        source_operation_id: UUID,
    ) -> AccountResearchFleetProjection: ...


@dataclass(frozen=True, slots=True)
class EntityResearchLaunchServices:
    account_launcher: AccountResearchFleetLauncher
    account_fleets: AccountResearchFleetService
    contact_approver: ContactResearchSelectionApprover
    contact_launcher: ContactResearchFleetLauncher
    contact_fleets: ContactResearchFleetService


class LaunchAccountResearchInput(ToolInput):
    project_run_id: str
    research_directive_id: str
    account_entity_ids: tuple[str, ...] = Field(min_length=1, max_length=500)
    approved_budget_cap_cents: Decimal = Field(gt=0)
    expected_estimated_cost_cents: Decimal = Field(gt=0)
    concurrency_limit: int = Field(default=16, ge=1, le=64)


class LaunchAccountResearchOutput(ToolOutput):
    research_run_id: str
    fleet_state: str
    selected_accounts: int
    budget_cap_cents: str
    contact_research_started: bool


class ReadEntityResearchRunInput(ToolInput):
    research_run_id: str


class EntityResearchRunOutput(ToolOutput):
    projection: dict[str, object]


class ApproveEntityContactResearchSelectionInput(ToolInput):
    request: ContactResearchSelectionApprovalRequest
    approved_at: datetime


class ApproveEntityContactResearchSelectionOutput(ToolOutput):
    selection_id: str
    selection_sha256: str
    selected_contacts: int


class LaunchContactResearchInput(ToolInput):
    selection_id: str
    selection_sha256: str
    approved_budget_cap_cents: Decimal = Field(gt=0)
    expected_estimated_cost_cents: Decimal = Field(gt=0)
    concurrency_limit: int = Field(default=8, ge=1, le=64)
    confirmed_at: datetime


class LaunchContactResearchOutput(ToolOutput):
    research_run_id: str
    selected_contacts: int
    run_state: str


def _not_composed() -> tuple[PreconditionFailure, ...]:
    return (
        PreconditionFailure(
            reason_code="entity_research_agent_not_composed",
            message="the R10 entity-research launch services are not composed",
        ),
    )


def _trusted_action(ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
    if ctx.action_ref is None:
        return (
            PreconditionFailure(
                reason_code="launch_action_ref_missing",
                message="entity research launch requires the captured user action reference",
            ),
        )
    return ()


class LaunchAccountResearchTool(Tool):
    name = "launch_account_research"
    version = "1"
    model_description = (
        "Launch (or exactly replay) the separately confirmed account research run: one "
        "create_agent account unit per selected account on the shared fleet. Call only after the "
        "current user action explicitly approves the exact confirmed directive, account set, "
        "estimate, and budget cap. A successful result means launched/enqueued or replayed; it "
        "never means account or committee research has completed, and it never authorizes "
        "contact research."
    )
    input_model = LaunchAccountResearchInput
    output_model = LaunchAccountResearchOutput
    effect_class = ToolEffectClass.SPEND
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="confirmed directive + exact account selection + approved budget",
        external_boundary=ExternalReplayBoundary.NONE,
    )
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=(
            "project_run_id",
            "research_directive_id",
            "account_entity_ids",
            "approved_budget_cap_cents",
            "expected_estimated_cost_cents",
        )
    )
    pin_requirements = ("project_run", "research_directive", "account_research_selection")

    def __init__(self, service: AccountResearchLaunchService | None) -> None:
        self._service = service

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> tuple[PreconditionFailure, ...]:
        del inputs
        return _not_composed() if self._service is None else _trusted_action(ctx)

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        assert isinstance(inputs, LaunchAccountResearchInput)
        return ToolEstimate(
            cost_cents=inputs.expected_estimated_cost_cents,
            detail={"basis": "confirmed_account_research_directive"},
        )

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, LaunchAccountResearchInput)
        assert self._service is not None and ctx.action_ref is not None
        projection = await self._service.launch(
            AccountResearchFleetLaunchRequest(
                workspace_id=ctx.workspace_id,
                project_run_id=UUID(inputs.project_run_id),
                research_directive_id=UUID(inputs.research_directive_id),
                account_entity_ids=tuple(UUID(value) for value in inputs.account_entity_ids),
                approved_budget_cap_cents=inputs.approved_budget_cap_cents,
                expected_estimated_cost_cents=inputs.expected_estimated_cost_cents,
                concurrency_limit=inputs.concurrency_limit,
            ),
            actor=ctx.actor_id or ctx.actor,
            source_action_ref=ctx.action_ref,
            source_operation_id=ctx.operation_id,
        )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "research_run_id": str(projection.research_run_id),
                "fleet_state": projection.fleet_state.value,
                "selected_accounts": projection.selected_accounts,
                "budget_cap_cents": str(projection.budget_cap_cents),
                "contact_research_started": projection.contact_research_started,
            },
        )


class ReadAccountResearchRunTool(Tool):
    name = "read_account_research_run"
    version = "1"
    input_model = ReadEntityResearchRunInput
    output_model = EntityResearchRunOutput
    effect_class = ToolEffectClass.READ
    replay = ReplaySafety(
        policy=ReplayPolicy.EFFECT_FREE,
        durable_identity="current scoped account research fleet projection",
    )
    parameter_policy = JournalParameterPolicy(safe_display_fields=("research_run_id",))
    pin_requirements = ("account_research_run",)

    def __init__(self, service: AccountResearchFleetService | None) -> None:
        self._service = service

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> tuple[PreconditionFailure, ...]:
        del inputs, ctx
        return _not_composed() if self._service is None else ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ReadEntityResearchRunInput)
        assert self._service is not None
        projection = await self._service.read(
            UUID(inputs.research_run_id), workspace_id=ctx.workspace_id
        )
        if projection is None:
            raise ValueError("account research run is absent")
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={"projection": projection.model_dump(mode="json")},
        )


class ApproveEntityContactResearchSelectionTool(Tool):
    name = "approve_contact_research_selection"
    version = "2"
    input_model = ApproveEntityContactResearchSelectionInput
    output_model = ApproveEntityContactResearchSelectionOutput
    effect_class = ToolEffectClass.STEERING
    replay = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity="R7 exact contact selection approval",
        operation_id_required=True,
        external_boundary=ExternalReplayBoundary.NONE,
    )
    parameter_policy = JournalParameterPolicy(safe_display_fields=())
    pin_requirements = ("project_run", "account", "research_directive", "contact_selection")

    def __init__(self, service: ContactResearchSelectionApprover | None) -> None:
        self._service = service

    async def audit_snapshot(self, inputs: ToolInput, ctx: ToolContext) -> dict[str, object]:
        assert isinstance(inputs, ApproveEntityContactResearchSelectionInput)
        return {
            "workspace_id": ctx.workspace_id,
            "project_run_id": str(inputs.request.project_run_id),
            "account_entity_id": str(inputs.request.account_entity_id),
            "selected_contact_ids": [
                str(target.contact_entity_id) for target in inputs.request.targets
            ],
            "approved_at": inputs.approved_at.isoformat(),
        }

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> tuple[PreconditionFailure, ...]:
        assert isinstance(inputs, ApproveEntityContactResearchSelectionInput)
        if self._service is None:
            return _not_composed()
        authority = require_human_authority(
            ctx,
            action_ref_required=True,
            message="only an authenticated human may approve the exact contact selection",
        )
        if authority:
            return authority
        if inputs.request.workspace_id != ctx.workspace_id:
            return (
                PreconditionFailure(
                    reason_code="contact_selection_not_found",
                    message="contact selection is absent from this workspace",
                ),
            )
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ApproveEntityContactResearchSelectionInput)
        assert self._service is not None and ctx.actor_id is not None and ctx.action_ref is not None
        selection = await self._service.approve(
            inputs.request,
            approved_by=ctx.actor_id,
            action_ref=ctx.action_ref,
            approval_operation_id=ctx.operation_id,
            approved_at=inputs.approved_at,
        )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "selection_id": str(selection.selection_id),
                "selection_sha256": selection.selection_sha256,
                "selected_contacts": len(selection.body.targets),
            },
        )


class LaunchContactResearchTool(Tool):
    name = "launch_contact_research"
    version = "1"
    model_description = (
        "Launch (or exactly replay) the separately confirmed contact research run: one "
        "create_agent contact unit per explicitly selected contact on the shared fleet. Call "
        "only after the current user action explicitly approves the exact durable selection, "
        "estimate, and budget cap; committee membership alone never authorizes it. A successful "
        "result means launched/enqueued or replayed; it never means any contact research has "
        "completed."
    )
    input_model = LaunchContactResearchInput
    output_model = LaunchContactResearchOutput
    effect_class = ToolEffectClass.SPEND
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="approved R7 contact selection + exact launch confirmation",
        external_boundary=ExternalReplayBoundary.NONE,
    )
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=(
            "selection_id",
            "approved_budget_cap_cents",
            "expected_estimated_cost_cents",
        )
    )
    pin_requirements = ("contact_research_selection", "contact_research_budget")

    def __init__(self, service: ContactResearchFleetLauncher | None) -> None:
        self._service = service

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> tuple[PreconditionFailure, ...]:
        del inputs
        return _not_composed() if self._service is None else _trusted_action(ctx)

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        assert isinstance(inputs, LaunchContactResearchInput)
        return ToolEstimate(
            cost_cents=inputs.expected_estimated_cost_cents,
            detail={"basis": "approved_exact_contact_selection"},
        )

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, LaunchContactResearchInput)
        assert self._service is not None and ctx.action_ref is not None
        launched = await self._service.launch(
            ContactResearchFleetLaunchRequest(
                workspace_id=ctx.workspace_id,
                selection_id=UUID(inputs.selection_id),
                selection_sha256=inputs.selection_sha256,
                approved_budget_cap_cents=inputs.approved_budget_cap_cents,
                expected_estimated_cost_cents=inputs.expected_estimated_cost_cents,
                concurrency_limit=inputs.concurrency_limit,
            ),
            actor=ctx.actor_id or ctx.actor,
            source_action_ref=ctx.action_ref,
            source_operation_id=ctx.operation_id,
            confirmed_at=inputs.confirmed_at,
        )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "research_run_id": str(launched.research_run_id),
                "selected_contacts": len(launched.jobs),
                "run_state": launched.run_state,
            },
        )


class ReadContactResearchRunTool(Tool):
    name = "read_contact_research_run"
    version = "1"
    input_model = ReadEntityResearchRunInput
    output_model = EntityResearchRunOutput
    effect_class = ToolEffectClass.READ
    replay = ReplaySafety(
        policy=ReplayPolicy.EFFECT_FREE,
        durable_identity="current scoped contact research fleet projection",
    )
    parameter_policy = JournalParameterPolicy(safe_display_fields=("research_run_id",))
    pin_requirements = ("contact_research_run",)

    def __init__(self, service: ContactResearchFleetService | None) -> None:
        self._service = service

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> tuple[PreconditionFailure, ...]:
        del inputs, ctx
        return _not_composed() if self._service is None else ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ReadEntityResearchRunInput)
        assert self._service is not None
        projection = await self._service.read(
            UUID(inputs.research_run_id), workspace_id=ctx.workspace_id
        )
        if projection is None:
            raise ValueError("contact research run is absent")
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={"projection": projection.model_dump(mode="json")},
        )


def build_entity_research_launch_tools(
    services: EntityResearchLaunchServices | None,
) -> tuple[Tool, ...]:
    return (
        LaunchAccountResearchTool(services.account_launcher if services is not None else None),
        ReadAccountResearchRunTool(services.account_fleets if services is not None else None),
        ApproveEntityContactResearchSelectionTool(
            services.contact_approver if services is not None else None
        ),
        LaunchContactResearchTool(services.contact_launcher if services is not None else None),
        ReadContactResearchRunTool(services.contact_fleets if services is not None else None),
    )


__all__ = [
    "ApproveEntityContactResearchSelectionInput",
    "ApproveEntityContactResearchSelectionOutput",
    "EntityResearchLaunchServices",
    "EntityResearchRunOutput",
    "LaunchAccountResearchInput",
    "LaunchAccountResearchOutput",
    "LaunchContactResearchInput",
    "LaunchContactResearchOutput",
    "ReadEntityResearchRunInput",
    "build_entity_research_launch_tools",
]
