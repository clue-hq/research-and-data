"""One governed decision service over the field and source proposal stores."""

from __future__ import annotations

import hashlib
from collections.abc import Callable

from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_config.proposals import (
    DEFAULT_PROPOSAL_POLICY,
    ClientFieldPromotionMode,
    ProposalPolicy,
)
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
from clue_research.claimstore import (
    ValueSchemaError,
    WorkspaceFieldDefinitionError,
    get_field,
    get_workspace_field,
    register_field,
    register_workspace_field,
    validate_value_against_schema,
    validate_workspace_field_schema,
)
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


class ClientFieldPromotionDisabled(PermissionError):
    """The selected policy posture permits proposals but not promotion."""


class ClientFieldPolicyRefused(PermissionError):
    """Policy authority attempted to promote a field outside the safe autonomous class."""


class ClientFieldEvidenceRefused(ValueError):
    """A dynamic field proposal does not cite a live statement in its own object-spine scope."""


def _payload_hash(payload: FieldProposalPayload | SourceProposalPayload) -> str:
    dumped = payload.model_dump(mode="json")
    return hashlib.sha256(canonical_json(dumped).encode("utf-8")).hexdigest()


def field_required_authority(
    payload: FieldProposalPayload, policy: ProposalPolicy
) -> ProposalAuthority:
    if payload.field_def.field_key.startswith("client."):
        eligible, _ = evaluate_safe_client_field(payload, policy)
        if policy.client_field_mode is ClientFieldPromotionMode.SAFE_AUTO_PROMOTE and eligible:
            return ProposalAuthority.POLICY
        return ProposalAuthority.HUMAN
    if (
        payload.sensitive
        or classify_field_key(payload.field_def.field_key) in policy.human_field_classes
    ):
        return ProposalAuthority.HUMAN
    return ProposalAuthority.POLICY


def evaluate_safe_client_field(
    payload: FieldProposalPayload, policy: ProposalPolicy
) -> tuple[bool, tuple[str, ...]]:
    """Return the complete, bounded safe-auto predicate as explicit reason codes."""

    details = payload.client_kb
    reasons: list[str] = []
    if not payload.field_def.field_key.startswith("client.") or details is None:
        reasons.append("not_dynamic_client_field")
        return False, tuple(reasons)
    if (
        payload.field_def.reuse_scope is None
        or payload.field_def.reuse_scope.value != "tenant_private"
    ):
        reasons.append("reuse_scope_not_tenant_private")
    if payload.pack != "client" or details.client_kb_role != "extended":
        reasons.append("not_supplemental_client_kb")
    if payload.sensitive:
        reasons.append("sensitive")
    if details.contains_personal_data:
        reasons.append("personal_data")
    if details.readiness_requested:
        reasons.append("readiness_authority")
    if details.scoring_authoritative:
        reasons.append("scoring_authority")
    if details.qualification_authoritative:
        reasons.append("qualification_authority")
    if details.outreach_authoritative:
        reasons.append("outreach_authority")
    if details.compliance_authoritative:
        reasons.append("compliance_authority")
    if payload.field_def.pass_kind is PassKind.SCORING:
        reasons.append("scoring_pass")
    if payload.field_def.gate is not None:
        reasons.append("use_gate")
    if payload.field_def.signal_class is not None:
        reasons.append("signal_class_authority")
    if details.introduces_new_source:
        reasons.append("new_source")
    if details.elevates_source_trust:
        reasons.append("trust_elevation")
    # The first autonomous posture intentionally admits no refresh-source authority. A non-empty
    # plan is not necessarily unsafe, but deciding that its sources/tier are appropriate belongs
    # to a human until a source-visibility policy seam is available here.
    if payload.field_def.tier_plan:
        reasons.append("source_plan_requires_human")
    if not payload.evidence_refs:
        reasons.append("missing_evidence")
    if len(payload.evidence_refs) > policy.max_client_field_evidence_refs:
        reasons.append("too_many_evidence_refs")
    if payload.value_schema is None:
        reasons.append("missing_value_schema")
    else:
        if (
            len(canonical_json(payload.value_schema).encode("utf-8"))
            > policy.max_client_field_schema_bytes
        ):
            reasons.append("schema_over_cap")
        try:
            validate_workspace_field_schema(payload.value_schema)
        except WorkspaceFieldDefinitionError:
            reasons.append("invalid_schema")
        try:
            validate_value_against_schema(details.candidate_value, payload.value_schema)
        except ValueSchemaError:
            reasons.append("candidate_schema_mismatch")
    return not reasons, tuple(reasons)


def source_required_authority(payload: SourceProposalPayload) -> ProposalAuthority:
    if payload.manifest.auth_ref is not None or source_yields_personal_data(payload):
        return ProposalAuthority.HUMAN
    return ProposalAuthority.POLICY


def _has_authority(actual: ProposalAuthority, required: ProposalAuthority) -> bool:
    return actual is ProposalAuthority.HUMAN or required is ProposalAuthority.POLICY


async def _validate_scope(conn: AsyncConnection, scope: ProposalScope) -> None:
    if not await scope_exists(conn, scope):
        raise ProposalScopeError("proposal scope not found")


async def _validate_client_field_evidence(
    conn: AsyncConnection, *, scope: ProposalScope, payload: FieldProposalPayload
) -> None:
    details = payload.client_kb
    if details is None:
        return
    found = (
        await conn.execute(
            text(
                """
                SELECT 1
                FROM volunteered_statement statement
                WHERE statement.id = :statement_id
                  AND statement.workspace_id = :workspace_id
                  AND statement.brand_id = :brand_id
                  AND statement.product_id IS NOT DISTINCT FROM :product_id
                  AND statement.project_id IS NOT DISTINCT FROM :project_id
                  AND statement.client_entity_id IS NOT NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM volunteered_statement correction
                      WHERE correction.workspace_id = statement.workspace_id
                        AND correction.correction_of_id = statement.id
                  )
                """
            ),
            {
                "statement_id": details.source_statement_id,
                "workspace_id": scope.workspace_id,
                "brand_id": scope.brand_id,
                "product_id": scope.product_id,
                "project_id": scope.project_id,
            },
        )
    ).scalar_one_or_none()
    if found is None:
        raise ClientFieldEvidenceRefused(
            "dynamic Client-KB source statement is absent, superseded, or outside the "
            "proposal's trusted workspace/object-spine scope"
        )


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
    is_client_field = payload.field_def.field_key.startswith("client.")
    global_collision = False
    local_collision = False
    if is_client_field:
        await _validate_client_field_evidence(conn, scope=scope, payload=payload)
        global_collision = await get_field(conn, payload.field_def.field_key) is not None
        local_collision = (
            await get_workspace_field(
                conn,
                workspace_id=scope.workspace_id,
                field_key=payload.field_def.field_key,
                include_retired=True,
            )
            is not None
        )
    required_authority = field_required_authority(payload, policy)
    if global_collision or local_collision:
        required_authority = ProposalAuthority.HUMAN
    proposal = await insert_field_proposal(
        conn,
        scope=scope,
        payload=payload,
        payload_hash=_payload_hash(payload),
        required_authority=required_authority,
        proposed_by_actor=proposed_by_actor,
        proposed_by_ref=proposed_by_ref,
    )
    if not is_client_field:
        return proposal
    # Exact proposal replay returns its already-promoted row before collision checks. A different
    # proposal may never squat on platform vocabulary or an existing local meaning.
    if proposal.status is ProposalStatus.PROMOTED:
        return proposal
    if global_collision or local_collision:
        return proposal
    if (
        policy.client_field_mode is ClientFieldPromotionMode.SAFE_AUTO_PROMOTE
        and proposal.required_authority is ProposalAuthority.POLICY
    ):
        eligible, reasons = evaluate_safe_client_field(payload, policy)
        if eligible:
            return await decide_field_proposal(
                conn,
                proposal_id=proposal.id,
                workspace_id=scope.workspace_id,
                decision=ProposalDecision.PROMOTE,
                reason=(f"{policy.client_field_policy_version}:safe_auto_promote:eligible"),
                authority=ProposalAuthority.POLICY,
                decided_by="policy:dynamic_client_kb",
                policy=policy,
            )
        # Defensive: ``field_required_authority`` and this predicate are the same function. If they
        # ever drift, fail closed and preserve the pending proposal for a human.
        if reasons:
            return proposal
    return proposal


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
    is_client_field = proposal.payload.field_def.field_key.startswith("client.")
    if (
        decision is ProposalDecision.PROMOTE
        and is_client_field
        and policy.client_field_mode is ClientFieldPromotionMode.PROPOSAL_ONLY
    ):
        raise ClientFieldPromotionDisabled(
            "proposal policy permits staging dynamic Client-KB fields but not promotion"
        )
    required = field_required_authority(proposal.payload, policy)
    if not _has_authority(authority, required):
        raise InsufficientProposalAuthority(
            f"{proposal.payload.field_def.field_key} requires {required.value} authority"
        )
    if decision is ProposalDecision.PROMOTE:
        payload = proposal.payload
        if is_client_field:
            if authority is ProposalAuthority.POLICY:
                eligible, reasons = evaluate_safe_client_field(payload, policy)
                if (
                    policy.client_field_mode is not ClientFieldPromotionMode.SAFE_AUTO_PROMOTE
                    or not eligible
                ):
                    reason_codes = ",".join(reasons) if reasons else "policy_mode"
                    raise ClientFieldPolicyRefused(
                        f"dynamic Client-KB field is not safe-auto eligible: {reason_codes}"
                    )
            await register_workspace_field(
                conn,
                payload.field_def,
                workspace_id=proposal.scope.workspace_id,
                promoted_from_proposal_id=proposal.id,
                promotion_policy_version=policy.client_field_policy_version,
                promoted_by=decided_by,
                value_schema=payload.value_schema,
                corroboration_min=payload.corroboration_min,
                single_source_sufficient=payload.single_source_sufficient,
                equality_mode=payload.equality_mode.value,
                description=payload.description,
                definition_version=payload.version,
            )
        else:
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
