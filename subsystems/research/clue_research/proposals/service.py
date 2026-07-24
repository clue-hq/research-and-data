"""One governed decision service over the field and source proposal stores."""

from __future__ import annotations

import hashlib
from collections.abc import Callable

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_config.proposals import DEFAULT_PROPOSAL_POLICY, ProposalPolicy
from clue_core import (
    FieldDef,
    PassKind,
    SourceManifest,
    canonical_json,
    classify_field_key,
)
from clue_core.proposals import (
    FieldProposalId,
    ProposalAuthority,
    ProposalStatus,
    SourceProposalId,
)
from clue_research.claimstore import register_field
from clue_research.proposals.models import (
    FieldProposal,
    FieldProposalPayload,
    ProposalDecision,
    ProposalScope,
    SourceDemotionResult,
    SourceProposal,
    SourceProposalPayload,
    source_yields_personal_data,
)
from clue_research.proposals.store import (
    ProposalAlreadyDecided,
    ProposalNotFound,
    ProposalScopeError,
    get_field_proposal,
    get_source_proposal,
    insert_field_proposal,
    insert_source_proposal,
    scope_exists,
    stamp_field_decision,
    stamp_source_decision,
    stamp_source_yield_review,
)
from clue_research.sources import RegistrySourceManifest, get_source, register_source
from clue_research.sources.source_yield import get_source_yield


class InsufficientProposalAuthority(PermissionError):
    """The deciding authority is below the proposal's policy-computed floor."""


class AssignedTierRequired(ValueError):
    """A source promotion omitted its policy/human-assigned trust tier."""


class CredentialSetupRequired(PermissionError):
    """A credentialed source lacks an administrator-confirmed runnable credential."""


class ComplianceApprovalRequired(PermissionError):
    """A personal-data source lacks explicit compliance-policy approval."""


def _payload_hash(payload: FieldProposalPayload | SourceProposalPayload) -> str:
    dumped = payload.model_dump(mode="json")
    return hashlib.sha256(canonical_json(dumped).encode("utf-8")).hexdigest()


def field_required_authority(
    payload: FieldProposalPayload, policy: ProposalPolicy
) -> ProposalAuthority:
    if (
        payload.sensitive
        or classify_field_key(payload.field_def.field_key) in policy.human_field_classes
    ):
        return ProposalAuthority.HUMAN
    return ProposalAuthority.POLICY


def source_required_authority(payload: SourceProposalPayload) -> ProposalAuthority:
    if payload.manifest.auth_ref is not None or source_yields_personal_data(payload):
        return ProposalAuthority.HUMAN
    return ProposalAuthority.POLICY


def _has_authority(actual: ProposalAuthority, required: ProposalAuthority) -> bool:
    return actual is ProposalAuthority.HUMAN or required is ProposalAuthority.POLICY


async def _validate_scope(conn: AsyncConnection, scope: ProposalScope) -> None:
    if not await scope_exists(conn, scope):
        raise ProposalScopeError("proposal scope not found")


async def propose_field(
    conn: AsyncConnection,
    *,
    scope: ProposalScope,
    payload: FieldProposalPayload,
    proposed_by_actor: str,
    proposed_by_ref: str | None = None,
    policy: ProposalPolicy = DEFAULT_PROPOSAL_POLICY,
) -> FieldProposal:
    await _validate_scope(conn, scope)
    return await insert_field_proposal(
        conn,
        scope=scope,
        payload=payload,
        payload_hash=_payload_hash(payload),
        required_authority=field_required_authority(payload, policy),
        proposed_by_actor=proposed_by_actor,
        proposed_by_ref=proposed_by_ref,
    )


async def reject_field_concept(
    conn: AsyncConnection,
    *,
    scope: ProposalScope,
    raw_input: JsonValue,
    reason: str,
    proposed_by_actor: str,
    proposed_by_ref: str | None = None,
    evidence_refs: tuple[str, ...] = (),
    policy: ProposalPolicy = DEFAULT_PROPOSAL_POLICY,
) -> FieldProposal:
    """Durably preserve malformed/unsafe synthesis output as a terminal rejected proposal.

    A malformed key cannot inhabit ``FieldDef``. The record therefore uses a deterministic,
    non-promotable ``account.rejected_concept_<hash>`` key and keeps the exact untrusted input in
    the field validation payload. It is immediately policy-rejected in the same transaction, so
    it remains visible/auditable without ever becoming eligible for registry promotion.
    """
    raw_hash = hashlib.sha256(canonical_json(raw_input).encode("utf-8")).hexdigest()
    display_key = raw_input.get("field_key") if isinstance(raw_input, dict) else None
    payload = FieldProposalPayload(
        field_def=FieldDef(
            field_key=f"account.rejected_concept_{raw_hash[:16]}",
            value_type="invalid",
            validation={"rejected_input": raw_input},
            pass_kind=PassKind.DEEP,
        ),
        description=(
            f"Rejected field concept {display_key!r}"
            if isinstance(display_key, str)
            else "Rejected malformed field concept"
        ),
        rationale=reason,
        evidence_refs=evidence_refs,
    )
    proposal = await propose_field(
        conn,
        scope=scope,
        payload=payload,
        proposed_by_actor=proposed_by_actor,
        proposed_by_ref=proposed_by_ref,
        policy=policy,
    )
    return await decide_field_proposal(
        conn,
        proposal_id=proposal.id,
        workspace_id=scope.workspace_id,
        decision=ProposalDecision.REJECT,
        reason=reason,
        authority=ProposalAuthority.POLICY,
        decided_by="policy:field_concept_validation",
        policy=policy,
    )


async def propose_source(
    conn: AsyncConnection,
    *,
    scope: ProposalScope,
    payload: SourceProposalPayload,
    proposed_by_actor: str,
    proposed_by_ref: str | None = None,
    policy: ProposalPolicy = DEFAULT_PROPOSAL_POLICY,
) -> SourceProposal:
    await _validate_scope(conn, scope)
    proposal = await insert_source_proposal(
        conn,
        scope=scope,
        payload=payload,
        payload_hash=_payload_hash(payload),
        required_authority=source_required_authority(payload),
        proposed_by_actor=proposed_by_actor,
        proposed_by_ref=proposed_by_ref,
    )
    if (
        proposal.status is ProposalStatus.PROPOSED
        and policy.auto_promote_tier3_sources
        and proposal.required_authority is ProposalAuthority.POLICY
    ):
        return await decide_source_proposal(
            conn,
            proposal_id=proposal.id,
            workspace_id=scope.workspace_id,
            decision=ProposalDecision.PROMOTE,
            reason="policy auto-promotion of an audited public tier-3 source",
            authority=ProposalAuthority.POLICY,
            decided_by="policy:proposal_auto_promote",
            assigned_tier=3,
            policy=policy,
        )
    return proposal


async def decide_field_proposal(
    conn: AsyncConnection,
    *,
    proposal_id: FieldProposalId,
    workspace_id: str,
    decision: ProposalDecision,
    reason: str,
    authority: ProposalAuthority,
    decided_by: str,
    policy: ProposalPolicy = DEFAULT_PROPOSAL_POLICY,
) -> FieldProposal:
    proposal = await get_field_proposal(
        conn, proposal_id, workspace_id=workspace_id, for_update=True
    )
    if proposal is None:
        raise ProposalNotFound(str(proposal_id))
    if proposal.status is not ProposalStatus.PROPOSED:
        target = {
            ProposalDecision.PROMOTE: ProposalStatus.PROMOTED,
            ProposalDecision.REJECT: ProposalStatus.REJECTED,
            ProposalDecision.WITHDRAW: ProposalStatus.WITHDRAWN,
        }[decision]
        if proposal.status is target:
            return proposal
        raise ProposalAlreadyDecided(str(proposal_id))
    required = field_required_authority(proposal.payload, policy)
    if not _has_authority(authority, required):
        raise InsufficientProposalAuthority(
            f"{proposal.payload.field_def.field_key} requires {required.value} authority"
        )
    if decision is ProposalDecision.PROMOTE:
        payload = proposal.payload
        await register_field(
            conn,
            payload.field_def,
            value_schema=payload.value_schema,
            corroboration_min=payload.corroboration_min,
            single_source_sufficient=payload.single_source_sufficient,
            equality_mode=payload.equality_mode.value,
            description=payload.description,
            version=payload.version,
            pack=payload.pack,
        )
        return await stamp_field_decision(
            conn,
            proposal_id=proposal.id,
            status="promoted",
            decided_by=decided_by,
            authority=authority,
            reason=reason,
            applied_field_key=payload.field_def.field_key,
            applied_version=payload.version,
        )
    if decision is ProposalDecision.REJECT:
        return await stamp_field_decision(
            conn,
            proposal_id=proposal.id,
            status="rejected",
            decided_by=decided_by,
            authority=authority,
            reason=reason,
        )
    return await stamp_field_decision(
        conn,
        proposal_id=proposal.id,
        status="withdrawn",
        decided_by=decided_by,
        authority=authority,
        reason=reason,
    )


def _registry_entry(payload: SourceProposalPayload, assigned_tier: int) -> RegistrySourceManifest:
    draft = payload.manifest
    return RegistrySourceManifest(
        manifest=SourceManifest(
            source_key=draft.source_key,
            modality=draft.modality,
            entity_scope=draft.entity_scope,
            yields=draft.yields,
            tier=assigned_tier,
            cost_cents=draft.cost_cents,
            latency_ms=draft.latency_ms,
            geo_coverage=draft.geo_coverage,
            freshness_profile=draft.freshness_profile,
            identity_binding_strength=draft.identity_binding_strength,
        ),
        active=draft.active,
        provider=draft.provider,
        auth_ref=draft.auth_ref,
        rate_limit=draft.rate_limit,
        requires_adapter=draft.requires_adapter,
        version=draft.version,
    )


async def decide_source_proposal(
    conn: AsyncConnection,
    *,
    proposal_id: SourceProposalId,
    workspace_id: str,
    decision: ProposalDecision,
    reason: str,
    authority: ProposalAuthority,
    decided_by: str,
    assigned_tier: int | None = None,
    policy: ProposalPolicy = DEFAULT_PROPOSAL_POLICY,
    credential_ready: Callable[[str], bool] | None = None,
    personal_source_allowed: Callable[[SourceProposalPayload], bool] | None = None,
) -> SourceProposal:
    proposal = await get_source_proposal(
        conn, proposal_id, workspace_id=workspace_id, for_update=True
    )
    if proposal is None:
        raise ProposalNotFound(str(proposal_id))
    if proposal.status is not ProposalStatus.PROPOSED:
        target = {
            ProposalDecision.PROMOTE: ProposalStatus.PROMOTED,
            ProposalDecision.REJECT: ProposalStatus.REJECTED,
            ProposalDecision.WITHDRAW: ProposalStatus.WITHDRAWN,
        }[decision]
        if proposal.status is target:
            return proposal
        raise ProposalAlreadyDecided(str(proposal_id))
    required = source_required_authority(proposal.payload)
    if decision is ProposalDecision.PROMOTE:
        if assigned_tier is None:
            raise AssignedTierRequired("source promotion requires assigned_tier")
        if assigned_tier < 1 or assigned_tier > 4:
            raise ValueError("assigned_tier must be in 1..4")
        if assigned_tier != 3 or assigned_tier in policy.human_source_tiers:
            required = ProposalAuthority.HUMAN
    if not _has_authority(authority, required):
        raise InsufficientProposalAuthority(
            f"{proposal.payload.manifest.source_key} requires {required.value} authority"
        )
    if decision is ProposalDecision.PROMOTE:
        assert assigned_tier is not None
        auth_ref = proposal.payload.manifest.auth_ref
        if auth_ref is not None and (credential_ready is None or not credential_ready(auth_ref)):
            raise CredentialSetupRequired(
                f"credential setup is not confirmed for auth_ref {auth_ref!r}"
            )
        if source_yields_personal_data(proposal.payload) and (
            personal_source_allowed is None or not personal_source_allowed(proposal.payload)
        ):
            raise ComplianceApprovalRequired(
                "personal-data source promotion requires explicit compliance-policy approval"
            )
        entry = _registry_entry(proposal.payload, assigned_tier)
        await register_source(conn, entry)
        return await stamp_source_decision(
            conn,
            proposal_id=proposal.id,
            status="promoted",
            decided_by=decided_by,
            authority=authority,
            reason=reason,
            assigned_tier=assigned_tier,
            applied_source_key=entry.source_key,
            applied_version=entry.version,
        )
    if decision is ProposalDecision.REJECT:
        return await stamp_source_decision(
            conn,
            proposal_id=proposal.id,
            status="rejected",
            decided_by=decided_by,
            authority=authority,
            reason=reason,
        )
    return await stamp_source_decision(
        conn,
        proposal_id=proposal.id,
        status="withdrawn",
        decided_by=decided_by,
        authority=authority,
        reason=reason,
    )


async def evaluate_source_demotion(
    conn: AsyncConnection,
    *,
    proposal_id: SourceProposalId,
    workspace_id: str,
    actor: str = "policy:yield_guard",
    policy: ProposalPolicy = DEFAULT_PROPOSAL_POLICY,
) -> SourceDemotionResult:
    """Audit yield and disable a policy-promoted tier-3 source when it stays below the floor."""
    proposal = await get_source_proposal(
        conn, proposal_id, workspace_id=workspace_id, for_update=True
    )
    if proposal is None:
        raise ProposalNotFound(str(proposal_id))
    if (
        proposal.status is not ProposalStatus.PROMOTED
        or proposal.decision_authority is not ProposalAuthority.POLICY
        or proposal.assigned_tier != 3
    ):
        raise InsufficientProposalAuthority(
            "automatic yield demotion applies only to policy-promoted tier-3 sources"
        )
    stats = await get_source_yield(
        conn,
        workspace_id=workspace_id,
        icp_key=proposal.scope.icp_key,
        icp_version=proposal.scope.icp_spec_version,
        source_key=proposal.payload.manifest.source_key,
    )
    observations = sum(item.measurements for item in stats)
    fields_filled = sum(item.fields_filled for item in stats)
    yield_rate = fields_filled / observations if observations else None
    if observations < policy.min_observations_for_yield:
        await stamp_source_yield_review(
            conn,
            proposal_id=proposal.id,
            observations=observations,
            yield_rate=yield_rate,
        )
        return SourceDemotionResult(
            proposal_id=proposal.id,
            source_key=proposal.payload.manifest.source_key,
            observations=observations,
            yield_rate=yield_rate,
        )
    if yield_rate is not None and yield_rate < policy.demotion_yield_floor:
        current = await get_source(conn, proposal.payload.manifest.source_key)
        if current is None:
            raise RuntimeError("promoted source is missing from the live registry")
        next_version = current.version + 1
        await register_source(
            conn,
            current.model_copy(update={"active": False, "version": next_version}),
        )
        reason = (
            f"yield {yield_rate:.6f} below policy floor "
            f"{policy.demotion_yield_floor:.6f} after {observations} observations"
        )
        await stamp_source_yield_review(
            conn,
            proposal_id=proposal.id,
            observations=observations,
            yield_rate=yield_rate,
            demoted_by=actor,
            demotion_reason=reason,
            demoted_version=next_version,
        )
        return SourceDemotionResult(
            proposal_id=proposal.id,
            source_key=proposal.payload.manifest.source_key,
            observations=observations,
            yield_rate=yield_rate,
            demoted=True,
            applied_version=next_version,
        )
    await stamp_source_yield_review(
        conn,
        proposal_id=proposal.id,
        observations=observations,
        yield_rate=yield_rate,
    )
    return SourceDemotionResult(
        proposal_id=proposal.id,
        source_key=proposal.payload.manifest.source_key,
        observations=observations,
        yield_rate=yield_rate,
    )


__all__ = [
    "AssignedTierRequired",
    "ComplianceApprovalRequired",
    "CredentialSetupRequired",
    "InsufficientProposalAuthority",
    "decide_field_proposal",
    "decide_source_proposal",
    "evaluate_source_demotion",
    "field_required_authority",
    "propose_field",
    "propose_source",
    "reject_field_concept",
    "source_required_authority",
]
