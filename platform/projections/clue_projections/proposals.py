"""Workspace-scoped, read-only proposal cards for Phase C2."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from clue_core import FieldClass
from clue_core.proposals import ProposalAuthority, ProposalStatus
from clue_db import ConnFactory
from clue_research.proposals import list_field_proposals, list_source_proposals


class ProposalScopeCard(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str
    brand_id: str
    product_id: str | None = None
    project_id: str | None = None
    icp_key: str | None = None
    icp_spec_version: int | None = None


class FieldProposalCard(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    field_proposal_id: str
    scope: ProposalScopeCard
    field_key: str
    field_class: FieldClass
    value_type: str
    gate: str | None = None
    sensitive: bool = False
    description: str | None = None
    rationale: str
    evidence_refs: tuple[str, ...] = ()
    required_authority: ProposalAuthority
    status: ProposalStatus
    proposed_by_actor: str
    decided_by: str | None = None
    decision_authority: ProposalAuthority | None = None
    decision_reason: str | None = None
    applied_field_key: str | None = None
    applied_version: int | None = None


class SourceProposalCard(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_proposal_id: str
    scope: ProposalScopeCard
    source_key: str
    discovery_domain: str
    capability_description: str
    yields: tuple[str, ...]
    requires_credentials: bool
    rationale: str
    evidence_refs: tuple[str, ...] = ()
    required_authority: ProposalAuthority
    assigned_tier: int | None = None
    status: ProposalStatus
    proposed_by_actor: str
    decided_by: str | None = None
    decision_authority: ProposalAuthority | None = None
    decision_reason: str | None = None
    applied_source_key: str | None = None
    applied_version: int | None = None
    yield_observations: int = 0
    yield_rate: float | None = None
    demoted: bool = False
    demotion_reason: str | None = None


def _scope_card(scope: object) -> ProposalScopeCard:
    return ProposalScopeCard.model_validate(scope, from_attributes=True)


async def field_proposals(
    *,
    conn_factory: ConnFactory,
    workspace_id: str,
    brand_id: str | None = None,
    status: ProposalStatus | None = None,
) -> tuple[FieldProposalCard, ...]:
    async with conn_factory() as conn:
        rows = await list_field_proposals(
            conn, workspace_id=workspace_id, brand_id=brand_id, status=status
        )
    return tuple(
        FieldProposalCard(
            field_proposal_id=str(row.id),
            scope=_scope_card(row.scope),
            field_key=row.payload.field_def.field_key,
            field_class=row.payload.field_def.field_class,
            value_type=row.payload.field_def.value_type,
            gate=row.payload.field_def.gate,
            sensitive=row.payload.sensitive,
            description=row.payload.description,
            rationale=row.payload.rationale,
            evidence_refs=row.payload.evidence_refs,
            required_authority=row.required_authority,
            status=row.status,
            proposed_by_actor=row.proposed_by_actor,
            decided_by=row.decided_by,
            decision_authority=row.decision_authority,
            decision_reason=row.decision_reason,
            applied_field_key=row.applied_field_key,
            applied_version=row.applied_version,
        )
        for row in rows
    )


async def source_proposals(
    *,
    conn_factory: ConnFactory,
    workspace_id: str,
    brand_id: str | None = None,
    status: ProposalStatus | None = None,
) -> tuple[SourceProposalCard, ...]:
    async with conn_factory() as conn:
        rows = await list_source_proposals(
            conn, workspace_id=workspace_id, brand_id=brand_id, status=status
        )
    return tuple(
        SourceProposalCard(
            source_proposal_id=str(row.id),
            scope=_scope_card(row.scope),
            source_key=row.payload.manifest.source_key,
            discovery_domain=row.payload.discovery_domain,
            capability_description=row.payload.capability_description,
            yields=row.payload.manifest.yields,
            requires_credentials=row.payload.manifest.auth_ref is not None,
            rationale=row.payload.rationale,
            evidence_refs=row.payload.evidence_refs,
            required_authority=row.required_authority,
            assigned_tier=row.assigned_tier,
            status=row.status,
            proposed_by_actor=row.proposed_by_actor,
            decided_by=row.decided_by,
            decision_authority=row.decision_authority,
            decision_reason=row.decision_reason,
            applied_source_key=row.applied_source_key,
            applied_version=row.applied_version,
            yield_observations=row.yield_observations,
            yield_rate=row.yield_rate,
            demoted=row.demoted_at is not None,
            demotion_reason=row.demotion_reason,
        )
        for row in rows
    )


__all__ = [
    "FieldProposalCard",
    "ProposalScopeCard",
    "SourceProposalCard",
    "field_proposals",
    "source_proposals",
]
