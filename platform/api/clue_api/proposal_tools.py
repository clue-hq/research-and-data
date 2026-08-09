"""Lane-local Phase-C proposal tools.

Integration registers these four tools centrally after C1→C2 lands. This module intentionally does
not edit ``build_toolbelt`` or the shared router aggregation.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from clue_api.auth_tool_context import require_human_authority
from clue_api.dynamic_client_kb import DynamicClientKbMaterializer, MaterializedFieldRefs
from clue_api.tool_outputs import (
    FieldProposalDecisionOutput,
    FieldProposalOutput,
    SourceProposalDecisionOutput,
    SourceProposalOutput,
)
from clue_config.proposals import (
    DEFAULT_PROPOSAL_POLICY,
    ClientFieldPromotionMode,
    ProposalPolicy,
)
from clue_core.proposals import (
    FieldProposalId,
    ProposalAuthority,
    ProposalStatus,
    SourceProposalId,
)
from clue_research.proposals import (
    FieldProposalPayload,
    ProposalDecision,
    ProposalScope,
    SourceProposalPayload,
    decide_field_proposal,
    decide_source_proposal,
    evaluate_safe_client_field,
    get_field_proposal,
    get_source_proposal,
    propose_field,
    propose_source,
    scope_exists,
    source_yields_personal_data,
)
from clue_toolbelt import (
    JournalParameterPolicy,
    PreconditionFailure,
    ReplayPolicy,
    ReplaySafety,
    Tool,
    ToolContext,
    ToolEffectClass,
    ToolInput,
    ToolResult,
)


class ProposalScopeInput(BaseModel):
    """The narrowing part of a proposal's scope: what the proposal is *about*.

    ``brand_id`` and ``project_id`` deliberately do **not** live here (PC-C8 task 1.4). They are
    :data:`~clue_agents.contracts.MODEL_FORBIDDEN_AUTHORITY_KEYS` — this execution's brand, this
    execution's project — and the strip/inject seam is top-level only, so a nested copy was neither
    hidden from the model nor served from the constitution. Hoisting them onto the tool input
    (rather than teaching the seam to recurse) means there is no nested authority left to strip:
    the invalid state is unrepresentable instead of defended against.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    product_id: str | None = None
    icp_key: str | None = None
    icp_spec_version: int | None = Field(default=None, ge=1)

    def for_execution(
        self,
        *,
        workspace_id: str,
        brand_id: str,
        project_id: str | None,
    ) -> ProposalScope:
        """Rejoin the model-authored narrowing with the engine's trusted scope authority."""

        return ProposalScope(
            workspace_id=workspace_id,
            brand_id=brand_id,
            project_id=project_id,
            **self.model_dump(),
        )


class ProposeFieldInput(ToolInput):
    brand_id: str = Field(
        description="Trusted brand authority; supplied by the platform, never by you."
    )
    scope: ProposalScopeInput
    payload: FieldProposalPayload
    proposed_by_ref: str | None = None
    project_id: str | None = Field(
        default=None,
        description="Trusted project authority; supplied by the platform, never by you.",
    )


class DecideFieldProposalInput(ToolInput):
    field_proposal_id: str
    decision: ProposalDecision
    reason: str = Field(min_length=1)


class ProposeSourceInput(ToolInput):
    brand_id: str = Field(
        description="Trusted brand authority; supplied by the platform, never by you."
    )
    scope: ProposalScopeInput
    payload: SourceProposalPayload
    proposed_by_ref: str | None = None
    project_id: str | None = Field(
        default=None,
        description="Trusted project authority; supplied by the platform, never by you.",
    )


class DecideSourceProposalInput(ToolInput):
    source_proposal_id: str
    decision: ProposalDecision
    reason: str = Field(min_length=1)
    assigned_tier: int | None = Field(default=None, ge=1, le=4)


def _failure(code: str, message: str) -> tuple[PreconditionFailure, ...]:
    return (PreconditionFailure(reason_code=code, message=message),)


def _resolved_scope(
    inputs: ProposeFieldInput | ProposeSourceInput,
    ctx: ToolContext,
) -> ProposalScope:
    """Join the model-authored narrowing with the trusted brand/project/workspace authority."""

    return inputs.scope.for_execution(
        workspace_id=ctx.workspace_id,
        brand_id=inputs.brand_id,
        project_id=inputs.project_id,
    )


def _field_id(raw: str) -> FieldProposalId | None:
    try:
        return FieldProposalId(UUID(raw))
    except (TypeError, ValueError, AttributeError):
        return None


def _source_id(raw: str) -> SourceProposalId | None:
    try:
        return SourceProposalId(UUID(raw))
    except (TypeError, ValueError, AttributeError):
        return None


class _ProposalTool(Tool):
    def __init__(
        self,
        *,
        policy: ProposalPolicy = DEFAULT_PROPOSAL_POLICY,
        credential_ready: Callable[[str], bool] | None = None,
        personal_source_allowed: Callable[[SourceProposalPayload], bool] | None = None,
        dynamic_client_kb_materializer: DynamicClientKbMaterializer | None = None,
    ) -> None:
        self._policy = policy
        self._credential_ready = credential_ready
        self._personal_source_allowed = personal_source_allowed
        self._dynamic_client_kb_materializer = dynamic_client_kb_materializer


class ProposeFieldTool(_ProposalTool):
    name = "propose_field"
    version = "2"
    input_model = ProposeFieldInput
    output_model = FieldProposalOutput
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity=(
            "workspace + complete proposal scope + field key + immutable payload hash"
        ),
    )
    effect_class = ToolEffectClass.WRITE
    parameter_policy = JournalParameterPolicy(safe_display_fields=("scope", "proposed_by_ref"))
    pin_requirements = ("proposal_policy", "brand", "field_registry")

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, ProposeFieldInput)
        async with ctx.conn_factory() as conn:
            valid = await scope_exists(conn, _resolved_scope(inputs, ctx))
        if not valid:
            return _failure("proposal_scope_not_found", "proposal scope not found")
        is_dynamic = inputs.payload.field_def.field_key.startswith("client.")
        eligible, _ = evaluate_safe_client_field(inputs.payload, self._policy)
        if (
            is_dynamic
            and self._policy.client_field_mode is ClientFieldPromotionMode.SAFE_AUTO_PROMOTE
            and eligible
            and self._dynamic_client_kb_materializer is None
        ):
            return _failure(
                "dynamic_client_kb_materializer_not_configured",
                "safe autonomous field promotion requires statement-evidence materialization",
            )
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ProposeFieldInput)
        async with ctx.conn_factory() as conn:
            proposal = await propose_field(
                conn,
                scope=_resolved_scope(inputs, ctx),
                payload=inputs.payload,
                proposed_by_actor=ctx.actor,
                proposed_by_ref=inputs.proposed_by_ref,
                policy=self._policy,
            )
        materialized: MaterializedFieldRefs | None = None
        if proposal.status is ProposalStatus.PROMOTED and proposal.payload.client_kb is not None:
            if self._dynamic_client_kb_materializer is None:
                raise RuntimeError("dynamic Client-KB materializer is not configured")
            materialized = await self._dynamic_client_kb_materializer.materialize(
                proposal=proposal,
                workspace_id=ctx.workspace_id,
                conn_factory=ctx.conn_factory,
            )
        references = {
            "field_proposal_id": str(proposal.id),
            "field_key": proposal.payload.field_def.field_key,
            "status": proposal.status.value,
        }
        if materialized is not None:
            references.update(materialized.model_dump(exclude_none=True))
        return ToolResult(
            tool=self.name,
            version=self.version,
            references=references,
        )


class LegacyProposeFieldTool(ProposeFieldTool):
    """Exact v1 compatibility for historical recipes; dynamic client fields require v2."""

    version = "1"

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, ProposeFieldInput)
        if inputs.payload.field_def.field_key.startswith("client."):
            return _failure(
                "dynamic_client_kb_requires_v2",
                "tenant-local dynamic Client-KB proposals require propose_field@2",
            )
        return await super().preconditions(inputs, ctx)

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ProposeFieldInput)
        if inputs.payload.field_def.field_key.startswith("client."):
            raise RuntimeError("dynamic Client-KB proposals require propose_field@2")
        return await super().invoke(inputs, ctx)


class DecideFieldProposalTool(_ProposalTool):
    name = "decide_field_proposal"
    version = "2"
    input_model = DecideFieldProposalInput
    output_model = FieldProposalDecisionOutput

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, DecideFieldProposalInput)
        authority = require_human_authority(
            ctx,
            reason_code="insufficient_proposal_authority",
            message="field proposal decisions require authenticated human authority",
        )
        if authority:
            return authority
        proposal_id = _field_id(inputs.field_proposal_id)
        if proposal_id is None:
            return _failure("proposal_not_found", "no such field proposal")
        async with ctx.conn_factory() as conn:
            proposal = await get_field_proposal(conn, proposal_id, workspace_id=ctx.workspace_id)
        if proposal is None:
            return _failure("proposal_not_found", "no such field proposal")
        if (
            inputs.decision is ProposalDecision.PROMOTE
            and proposal.payload.client_kb is not None
            and self._dynamic_client_kb_materializer is None
        ):
            return _failure(
                "dynamic_client_kb_materializer_not_configured",
                "dynamic Client-KB promotion requires statement-evidence materialization",
            )
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, DecideFieldProposalInput)
        proposal_id = _field_id(inputs.field_proposal_id)
        assert proposal_id is not None
        async with ctx.conn_factory() as conn:
            proposal = await decide_field_proposal(
                conn,
                proposal_id=proposal_id,
                workspace_id=ctx.workspace_id,
                decision=inputs.decision,
                reason=inputs.reason,
                authority=ProposalAuthority.HUMAN,
                decided_by=f"human:{ctx.workspace_id}",
                policy=self._policy,
            )
        materialized: MaterializedFieldRefs | None = None
        if (
            inputs.decision is ProposalDecision.PROMOTE
            and proposal.status is ProposalStatus.PROMOTED
            and proposal.payload.client_kb is not None
        ):
            assert self._dynamic_client_kb_materializer is not None
            materialized = await self._dynamic_client_kb_materializer.materialize(
                proposal=proposal,
                workspace_id=ctx.workspace_id,
                conn_factory=ctx.conn_factory,
            )
        references = {
            "field_proposal_id": str(proposal.id),
            "status": proposal.status.value,
            "applied_field_key": proposal.applied_field_key,
        }
        if materialized is not None:
            references.update(materialized.model_dump(exclude_none=True))
        return ToolResult(
            tool=self.name,
            version=self.version,
            references=references,
        )


class LegacyDecideFieldProposalTool(DecideFieldProposalTool):
    """Exact v1 compatibility; it cannot promote a tenant-local dynamic field."""

    version = "1"

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        failures = await super().preconditions(inputs, ctx)
        if failures:
            return failures
        assert isinstance(inputs, DecideFieldProposalInput)
        proposal_id = _field_id(inputs.field_proposal_id)
        assert proposal_id is not None
        async with ctx.conn_factory() as conn:
            proposal = await get_field_proposal(conn, proposal_id, workspace_id=ctx.workspace_id)
        if (
            inputs.decision is ProposalDecision.PROMOTE
            and proposal is not None
            and proposal.payload.client_kb is not None
        ):
            return _failure(
                "dynamic_client_kb_requires_v2",
                "tenant-local dynamic Client-KB promotion requires decide_field_proposal@2",
            )
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, DecideFieldProposalInput)
        proposal_id = _field_id(inputs.field_proposal_id)
        assert proposal_id is not None
        async with ctx.conn_factory() as conn:
            proposal = await get_field_proposal(conn, proposal_id, workspace_id=ctx.workspace_id)
        if (
            inputs.decision is ProposalDecision.PROMOTE
            and proposal is not None
            and proposal.payload.client_kb is not None
        ):
            raise RuntimeError("dynamic Client-KB promotion requires decide_field_proposal@2")
        return await super().invoke(inputs, ctx)


class ProposeSourceTool(_ProposalTool):
    name = "propose_source"
    input_model = ProposeSourceInput
    output_model = SourceProposalOutput
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity=(
            "workspace + complete proposal scope + source key + immutable payload hash"
        ),
    )
    effect_class = ToolEffectClass.WRITE
    parameter_policy = JournalParameterPolicy(safe_display_fields=("scope", "proposed_by_ref"))
    pin_requirements = ("proposal_policy", "brand", "source_registry")

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, ProposeSourceInput)
        async with ctx.conn_factory() as conn:
            valid = await scope_exists(conn, _resolved_scope(inputs, ctx))
        if not valid:
            return _failure("proposal_scope_not_found", "proposal scope not found")
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ProposeSourceInput)
        async with ctx.conn_factory() as conn:
            proposal = await propose_source(
                conn,
                scope=_resolved_scope(inputs, ctx),
                payload=inputs.payload,
                proposed_by_actor=ctx.actor,
                proposed_by_ref=inputs.proposed_by_ref,
                policy=self._policy,
            )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "source_proposal_id": str(proposal.id),
                "source_key": proposal.payload.manifest.source_key,
                "status": proposal.status.value,
            },
        )


class DecideSourceProposalTool(_ProposalTool):
    name = "decide_source_proposal"
    input_model = DecideSourceProposalInput
    output_model = SourceProposalDecisionOutput

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, DecideSourceProposalInput)
        authority = require_human_authority(
            ctx,
            reason_code="insufficient_proposal_authority",
            message="source proposal decisions require authenticated human authority",
        )
        if authority:
            return authority
        proposal_id = _source_id(inputs.source_proposal_id)
        if proposal_id is None:
            return _failure("proposal_not_found", "no such source proposal")
        if inputs.decision is ProposalDecision.PROMOTE and inputs.assigned_tier is None:
            return _failure(
                "assigned_tier_required",
                "source promotion requires a policy/human-assigned tier",
            )
        async with ctx.conn_factory() as conn:
            proposal = await get_source_proposal(conn, proposal_id, workspace_id=ctx.workspace_id)
        if proposal is None:
            return _failure("proposal_not_found", "no such source proposal")
        auth_ref = proposal.payload.manifest.auth_ref
        if (
            inputs.decision is ProposalDecision.PROMOTE
            and auth_ref is not None
            and (self._credential_ready is None or not self._credential_ready(auth_ref))
        ):
            return _failure(
                "credential_setup_required",
                "credentialed source promotion requires confirmed administrator setup",
            )
        if (
            inputs.decision is ProposalDecision.PROMOTE
            and source_yields_personal_data(proposal.payload)
            and (
                self._personal_source_allowed is None
                or not self._personal_source_allowed(proposal.payload)
            )
        ):
            return _failure(
                "compliance_approval_required",
                "personal-data source promotion requires compliance-policy approval",
            )
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, DecideSourceProposalInput)
        proposal_id = _source_id(inputs.source_proposal_id)
        assert proposal_id is not None
        async with ctx.conn_factory() as conn:
            proposal = await decide_source_proposal(
                conn,
                proposal_id=proposal_id,
                workspace_id=ctx.workspace_id,
                decision=inputs.decision,
                reason=inputs.reason,
                authority=ProposalAuthority.HUMAN,
                decided_by=f"human:{ctx.workspace_id}",
                assigned_tier=inputs.assigned_tier,
                policy=self._policy,
                credential_ready=self._credential_ready,
                personal_source_allowed=self._personal_source_allowed,
            )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "source_proposal_id": str(proposal.id),
                "status": proposal.status.value,
                "applied_source_key": proposal.applied_source_key,
            },
        )


__all__ = [
    "DecideFieldProposalInput",
    "DecideFieldProposalTool",
    "LegacyDecideFieldProposalTool",
    "LegacyProposeFieldTool",
    "DecideSourceProposalInput",
    "DecideSourceProposalTool",
    "ProposalScopeInput",
    "ProposeFieldInput",
    "ProposeFieldTool",
    "ProposeSourceInput",
    "ProposeSourceTool",
]
