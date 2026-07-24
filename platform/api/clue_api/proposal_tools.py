"""Lane-local Phase-C proposal tools.

Integration registers these four tools centrally after C1→C2 lands. This module intentionally does
not edit ``build_toolbelt`` or the shared router aggregation.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from clue_config.proposals import DEFAULT_PROPOSAL_POLICY, ProposalPolicy
from clue_core.proposals import FieldProposalId, ProposalAuthority, SourceProposalId
from clue_research.proposals import (
    FieldProposalPayload,
    ProposalDecision,
    ProposalScope,
    SourceProposalPayload,
    decide_field_proposal,
    decide_source_proposal,
    get_field_proposal,
    get_source_proposal,
    propose_field,
    propose_source,
    scope_exists,
    source_yields_personal_data,
)
from clue_toolbelt import PreconditionFailure, Tool, ToolContext, ToolInput, ToolResult


class ProposalScopeInput(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    brand_id: str
    product_id: str | None = None
    project_id: str | None = None
    icp_key: str | None = None
    icp_spec_version: int | None = Field(default=None, ge=1)

    def for_workspace(self, workspace_id: str) -> ProposalScope:
        return ProposalScope(workspace_id=workspace_id, **self.model_dump())


class ProposeFieldInput(ToolInput):
    scope: ProposalScopeInput
    payload: FieldProposalPayload
    proposed_by_ref: str | None = None


class DecideFieldProposalInput(ToolInput):
    field_proposal_id: str
    decision: ProposalDecision
    reason: str = Field(min_length=1)


class ProposeSourceInput(ToolInput):
    scope: ProposalScopeInput
    payload: SourceProposalPayload
    proposed_by_ref: str | None = None


class DecideSourceProposalInput(ToolInput):
    source_proposal_id: str
    decision: ProposalDecision
    reason: str = Field(min_length=1)
    assigned_tier: int | None = Field(default=None, ge=1, le=4)


def _failure(code: str, message: str) -> tuple[PreconditionFailure, ...]:
    return (PreconditionFailure(reason_code=code, message=message),)


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
    ) -> None:
        self._policy = policy
        self._credential_ready = credential_ready
        self._personal_source_allowed = personal_source_allowed


class ProposeFieldTool(_ProposalTool):
    name = "propose_field"
    input_model = ProposeFieldInput

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, ProposeFieldInput)
        async with ctx.conn_factory() as conn:
            valid = await scope_exists(conn, inputs.scope.for_workspace(ctx.workspace_id))
        if not valid:
            return _failure("proposal_scope_not_found", "proposal scope not found")
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ProposeFieldInput)
        async with ctx.conn_factory() as conn:
            proposal = await propose_field(
                conn,
                scope=inputs.scope.for_workspace(ctx.workspace_id),
                payload=inputs.payload,
                proposed_by_actor=ctx.actor,
                proposed_by_ref=inputs.proposed_by_ref,
                policy=self._policy,
            )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "field_proposal_id": str(proposal.id),
                "field_key": proposal.payload.field_def.field_key,
                "status": proposal.status.value,
            },
        )


class DecideFieldProposalTool(_ProposalTool):
    name = "decide_field_proposal"
    input_model = DecideFieldProposalInput

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, DecideFieldProposalInput)
        if ctx.actor != "human":
            return _failure(
                "insufficient_proposal_authority",
                "field proposal decisions require a human actor or the policy service",
            )
        proposal_id = _field_id(inputs.field_proposal_id)
        if proposal_id is None:
            return _failure("proposal_not_found", "no such field proposal")
        async with ctx.conn_factory() as conn:
            proposal = await get_field_proposal(conn, proposal_id, workspace_id=ctx.workspace_id)
        if proposal is None:
            return _failure("proposal_not_found", "no such field proposal")
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
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "field_proposal_id": str(proposal.id),
                "status": proposal.status.value,
                "applied_field_key": proposal.applied_field_key,
            },
        )


class ProposeSourceTool(_ProposalTool):
    name = "propose_source"
    input_model = ProposeSourceInput

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, ProposeSourceInput)
        async with ctx.conn_factory() as conn:
            valid = await scope_exists(conn, inputs.scope.for_workspace(ctx.workspace_id))
        if not valid:
            return _failure("proposal_scope_not_found", "proposal scope not found")
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ProposeSourceInput)
        async with ctx.conn_factory() as conn:
            proposal = await propose_source(
                conn,
                scope=inputs.scope.for_workspace(ctx.workspace_id),
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

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, DecideSourceProposalInput)
        if ctx.actor != "human":
            return _failure(
                "insufficient_proposal_authority",
                "source proposal decisions require a human actor or the policy service",
            )
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
    "DecideSourceProposalInput",
    "DecideSourceProposalTool",
    "ProposalScopeInput",
    "ProposeFieldInput",
    "ProposeFieldTool",
    "ProposeSourceInput",
    "ProposeSourceTool",
]
