"""R10 toolbelt surfaces for separate account/contact research launches and returns."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Protocol
from uuid import UUID

from pydantic import Field, StringConstraints

from clue_api.account_research_discovery_readiness import (
    AccountResearchDiscoveryNotReady,
    require_sealed_account_discovery,
)
from clue_api.account_research_estimate import compute_account_research_estimate
from clue_api.account_research_fleet import (
    AccountResearchFleetProjection,
    AccountResearchFleetService,
)
from clue_api.account_research_fleet_launch import (
    AccountResearchFleetLauncher,
    AccountResearchFleetLaunchRequest,
)
from clue_api.agent_turn_submission import submission_context_refs
from clue_api.auth_tool_context import require_human_authority
from clue_api.contact_research_fleet import ContactResearchFleetService
from clue_api.contact_research_fleet_launch import (
    ContactResearchFleetLauncher,
    ContactResearchFleetLaunchRequest,
    ContactResearchSelectionApprovalRequest,
    ContactResearchSelectionApprover,
)
from clue_api.turn_action import load_turn_identity, parse_turn_action_ref
from clue_api.turn_binding import TRUSTED_TURN_FIELD
from clue_auth import get_membership, role_has_permission
from clue_core import EntityId, ProjectRunId, ResearchDirectiveId, ResearchDirectiveStatus
from clue_db import ConnFactory, transaction
from clue_research.directives import (
    confirm_research_directive,
    get_latest_research_directive,
    get_research_directive,
    research_directive_account_ids,
)
from clue_research.durable import get_project_run
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


class LaunchSelectedAccountResearchInput(ToolInput):
    """A direct launch whose subject is the captured turn's exact Account references."""

    project_run_id: str
    research_directive_id: str
    account_entity_ids: tuple[str, ...] = Field(min_length=1, max_length=100)
    concurrency_limit: int = Field(default=16, ge=1, le=64)
    source_turn_ref: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000),
    ] = Field(json_schema_extra={TRUSTED_TURN_FIELD: True})


@dataclass(frozen=True, slots=True)
class _SelectedAccountLaunch:
    project_run_id: ProjectRunId
    directive_id: ResearchDirectiveId
    account_ids: tuple[EntityId, ...]
    estimated_cost_cents: Decimal
    submitted_by_user_id: str
    source_turn_ref: str
    directive_sha256: str
    directive_status: ResearchDirectiveStatus


class _SelectedAccountLaunchRefused(ValueError):
    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code


class LaunchSelectedAccountResearchTool(Tool):
    """Confirm and launch one exact Account set from an explicit captured user command.

    This is the no-extra-confirmation path ratified for the FI pilot. It is deliberately a new
    tool rather than a relaxation of ``launch_account_research@1``: deployments with budget
    controls enabled retain the durable gate unchanged, and historical profiles keep their exact
    semantics. The model proposes ids for legibility, but the durable turn references are the
    authority and equality is enforced server-side before confirmation or spend.
    """

    name = "launch_selected_account_research"
    version = "1"
    model_description = (
        "Confirm and launch account research directly from the current human message only when "
        "that message explicitly commands research and carries the exact Account references. "
        "The server requires your proposed account ids to equal those durable references, refuses "
        "Contact or widened sets, derives the human receipt from the captured turn, computes the "
        "estimate itself, and is unavailable when budget controls require the normal gate."
    )
    input_model = LaunchSelectedAccountResearchInput
    output_model = LaunchAccountResearchOutput
    effect_class = ToolEffectClass.SPEND
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="captured command + exact turn Account set + directive revision",
        external_boundary=ExternalReplayBoundary.NONE,
    )
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=(
            "project_run_id",
            "research_directive_id",
            "account_entity_ids",
        )
    )
    pin_requirements = ("project_run", "research_directive", "account_research_selection")

    def __init__(
        self,
        service: AccountResearchLaunchService | None,
        *,
        budget_controls_enabled: bool,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._service = service
        self._budget_controls_enabled = budget_controls_enabled
        self._conn_factory = conn_factory

    async def _resolve(
        self,
        inputs: LaunchSelectedAccountResearchInput,
        ctx: ToolContext,
    ) -> _SelectedAccountLaunch:
        if self._service is None:
            raise _SelectedAccountLaunchRefused(
                "entity_research_agent_not_composed",
                "the R10 entity-research launch services are not composed",
            )
        if self._budget_controls_enabled:
            raise _SelectedAccountLaunchRefused(
                "direct_launch_requires_budget_controls_disabled",
                "this deployment requires the normal research confirmation gate",
            )
        if ctx.action_ref != inputs.source_turn_ref:
            raise _SelectedAccountLaunchRefused(
                "selected_launch_turn_mismatch",
                "the selected Account launch must cite the current captured user message",
            )
        try:
            turn_id = parse_turn_action_ref(inputs.source_turn_ref)
            project_run_id = ProjectRunId(UUID(inputs.project_run_id))
            directive_id = ResearchDirectiveId(UUID(inputs.research_directive_id))
            proposed_ids = tuple(EntityId(UUID(value)) for value in inputs.account_entity_ids)
        except ValueError as exc:
            raise _SelectedAccountLaunchRefused(
                "selected_launch_identifier_invalid",
                "selected Account launch identifiers must be canonical UUIDs",
            ) from exc
        if len(proposed_ids) != len(set(proposed_ids)):
            raise _SelectedAccountLaunchRefused(
                "selected_launch_scope_mismatch",
                "the selected Account launch set must not contain duplicates",
            )

        async with self._conn_factory() as conn:
            turn = await load_turn_identity(
                conn,
                workspace_id=ctx.workspace_id,
                turn_id=turn_id,
            )
            if (
                turn is None
                or turn.submitted_by_user_id is None
                or turn.submitted_via_membership_id is None
            ):
                raise _SelectedAccountLaunchRefused(
                    "selected_launch_human_turn_required",
                    "direct research launch requires one attributable captured human message",
                )
            membership = await get_membership(
                conn,
                workspace_id=ctx.workspace_id,
                membership_id=turn.submitted_via_membership_id,
            )
            if (
                membership is None
                or membership.status != "active"
                or membership.user_id != turn.submitted_by_user_id
                or not role_has_permission(membership.role_key, "research.launch")
            ):
                raise _SelectedAccountLaunchRefused(
                    "selected_launch_permission_denied",
                    "the submitting membership may not launch account research",
                )
            refs = await submission_context_refs(
                conn,
                workspace_id=ctx.workspace_id,
                turn_id=turn_id,
            )
            if not refs or any(ref.object_type != "account" for ref in refs):
                raise _SelectedAccountLaunchRefused(
                    "selected_launch_accounts_required",
                    "direct account research requires only Account references on this message",
                )
            captured_ids = tuple(EntityId(UUID(ref.object_id)) for ref in refs)
            if proposed_ids != captured_ids:
                raise _SelectedAccountLaunchRefused(
                    "selected_launch_scope_mismatch",
                    "research targets must exactly equal the current message's ordered Accounts",
                )

            project_run = await get_project_run(conn, project_run_id)
            if (
                project_run is None
                or project_run.workspace_id != ctx.workspace_id
                or project_run.project_id != turn.project_id
                or project_run.product_id is None
            ):
                raise _SelectedAccountLaunchRefused(
                    "selected_launch_project_run_mismatch",
                    "the research run must belong to the captured message's project",
                )
            try:
                await require_sealed_account_discovery(
                    conn,
                    workspace_id=ctx.workspace_id,
                    project_run_id=project_run_id,
                    icp_key=project_run.icp_key,
                    icp_version=project_run.icp_version,
                )
            except AccountResearchDiscoveryNotReady as exc:
                raise _SelectedAccountLaunchRefused(exc.reason_code, str(exc)) from exc
            directive = await get_research_directive(
                conn,
                directive_id,
                workspace_id=ctx.workspace_id,
            )
            latest = await get_latest_research_directive(
                conn,
                workspace_id=ctx.workspace_id,
                project_id=project_run.project_id,
                product_id=project_run.product_id,
                icp_key=project_run.icp_key,
                icp_version=project_run.icp_version,
            )
            if directive is None or latest is None or latest.directive_id != directive.directive_id:
                raise _SelectedAccountLaunchRefused(
                    "selected_launch_directive_stale",
                    "direct research launch requires the latest project research directive",
                )
            directive_ids = await research_directive_account_ids(
                conn,
                workspace_id=ctx.workspace_id,
                directive_id=directive.directive_id,
            )
            if set(directive_ids) != set(captured_ids) or len(directive_ids) != len(captured_ids):
                raise _SelectedAccountLaunchRefused(
                    "selected_launch_scope_mismatch",
                    "the directive's Account scope differs from the current message",
                )
            if directive.status is ResearchDirectiveStatus.CONFIRMED:
                # The directive confirmation and the launch command are distinct durable acts.
                # A prior launch attempt may fail after confirmation but before fleet state is
                # written. A later attributable human turn may retry that same latest directive
                # and exact Account set; the frozen selection records both approval references.
                allow_draft = False
            elif directive.status is not ResearchDirectiveStatus.DRAFT:
                raise _SelectedAccountLaunchRefused(
                    "selected_launch_directive_not_draft",
                    "only the current draft can be directly confirmed and launched",
                )
            else:
                allow_draft = True
            estimate = await compute_account_research_estimate(
                conn,
                workspace_id=ctx.workspace_id,
                project_run_id=project_run_id,
                directive_id=directive.directive_id,
                account_ids=captured_ids,
                allow_draft=allow_draft,
            )
        return _SelectedAccountLaunch(
            project_run_id=project_run_id,
            directive_id=directive_id,
            account_ids=captured_ids,
            estimated_cost_cents=estimate.total_cents,
            submitted_by_user_id=turn.submitted_by_user_id,
            source_turn_ref=inputs.source_turn_ref,
            directive_sha256=directive.canonical_json_sha256,
            directive_status=directive.status,
        )

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> tuple[PreconditionFailure, ...]:
        assert isinstance(inputs, LaunchSelectedAccountResearchInput)
        try:
            await self._resolve(inputs, ctx)
        except _SelectedAccountLaunchRefused as exc:
            return (PreconditionFailure(reason_code=exc.reason_code, message=str(exc)),)
        except Exception as exc:
            return (
                PreconditionFailure(
                    reason_code="selected_launch_not_admissible",
                    message=str(exc),
                ),
            )
        return ()

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        del inputs
        return ToolEstimate.free()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, LaunchSelectedAccountResearchInput)
        assert self._service is not None
        resolved = await self._resolve(inputs, ctx)
        if resolved.directive_status is ResearchDirectiveStatus.DRAFT:
            async with self._conn_factory() as conn:
                await confirm_research_directive(
                    conn,
                    workspace_id=ctx.workspace_id,
                    directive_id=resolved.directive_id,
                    expected_sha256=resolved.directive_sha256,
                    confirmed_by=resolved.submitted_by_user_id,
                    confirming_turn_ref=resolved.source_turn_ref,
                    operation_id=ctx.operation_id,
                )
        projection = await self._service.launch(
            AccountResearchFleetLaunchRequest(
                workspace_id=ctx.workspace_id,
                project_run_id=UUID(str(resolved.project_run_id)),
                research_directive_id=UUID(str(resolved.directive_id)),
                account_entity_ids=tuple(UUID(str(value)) for value in resolved.account_ids),
                approved_budget_cap_cents=resolved.estimated_cost_cents,
                expected_estimated_cost_cents=resolved.estimated_cost_cents,
                concurrency_limit=inputs.concurrency_limit,
            ),
            actor=resolved.submitted_by_user_id,
            source_action_ref=resolved.source_turn_ref,
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
    *,
    budget_controls_enabled: bool = True,
    conn_factory: ConnFactory = transaction,
) -> tuple[Tool, ...]:
    return (
        LaunchAccountResearchTool(services.account_launcher if services is not None else None),
        LaunchSelectedAccountResearchTool(
            services.account_launcher if services is not None else None,
            budget_controls_enabled=budget_controls_enabled,
            conn_factory=conn_factory,
        ),
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
    "LaunchSelectedAccountResearchInput",
    "LaunchSelectedAccountResearchTool",
    "LaunchContactResearchInput",
    "LaunchContactResearchOutput",
    "ReadEntityResearchRunInput",
    "build_entity_research_launch_tools",
]
