"""The M13.1 per-account review read projection (the ``ReviewSession`` assembler).

Pure store reads (the claim store M1 + identity M2) plus the injected cross-package
:class:`~clue_core.VerificationAnnotationReader` seam (the M9/M10 per-claim verdicts live
in tables ``review`` may not import). Reuses the frozen ``core`` projection value types — it invents
no shape. ``review`` MAY import ``claimstore``/``identity`` (the M1-M4 services) + ``core`` (the
import-linter independence rule allows the shared base + services; it bans only sibling *workers*).
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    CampaignRunId,
    Claim,
    ClaimId,
    CurrentValue,
    EntityId,
    EntityType,
    JudgeVerdict,
    Persona,
    ProvenanceRef,
    ReviewClaimRow,
    ReviewCommitteeMember,
    ReviewSession,
    ReviewSessionStatus,
    Score,
    VerificationStatus,
    can_be_promoted,
)
from clue_core.review import (
    ClaimAnnotation,
    FieldConflict,
    ReviewSessionId,
    VerificationAnnotationReader,
)
from clue_research.claimstore import (
    WorkspaceScope,
    claims_by_ids,
    claims_for,
    current_value,
    current_values,
)
from clue_research.identity import contact_ids_for_account, surviving_id

# The reserved score field-keys (M6.3). Read by STRING — ``review`` must not import
# ``discovery_scoring`` (independence contract); these are stable reserved fields (M1.3/ENG-165).
FIT_FIELD = "account.scoring.fit"
INTENT_FIELD = "account.scoring.intent"
_SCORE_FIELDS = frozenset({FIT_FIELD, INTENT_FIELD})
# Shown via the decomposed scores / narrative section, not as raw reviewable claim rows.
_NARRATIVE_FIELD = "account.value_narrative"
# Committee header fields (surfaced as persona/role, not as profile claim rows).
_PERSONA_FIELD = "contact.persona"
_ROLE_FIELD = "contact.role_on_committee"

_Winners = dict[tuple[EntityId, str], CurrentValue]


def _parse_persona(value: object) -> Persona | None:
    if isinstance(value, str):
        try:
            return Persona(value)
        except ValueError:
            return None
    return None


def _parse_role(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        role = value.get("role")
        return str(role) if role is not None else None
    return None


def _empty_reason(claim: Claim, annotation: ClaimAnnotation) -> str | None:
    """Why this claim cannot serve as its field's value (an empty/flagged field is a *correct*
    output, conventions §5 — not a defect). ``None`` when the claim is usable."""
    if claim.verification_status is VerificationStatus.REJECTED:
        return "rejected"
    if claim.source_tier == 4 and not claim.evidence_span:
        return "no evidence span (tier-4)"
    if not can_be_promoted(claim):
        return "weak identity binding"
    if annotation.faithfulness_verdict in (JudgeVerdict.UNSUPPORTED, JudgeVerdict.CONTRADICTED):
        return f"faithfulness: {annotation.faithfulness_verdict.value}"
    if annotation.use_decision is not None and not annotation.use_decision.usable_for_outreach:
        return f"use-gate: {annotation.use_decision.reason.value}"
    return None


class ReviewProjector:
    """Builds the :class:`~clue_core.ReviewSession` read projection for one account.

    The cross-package per-claim annotations (faithfulness M9.3, use-gate M10.3) and the open
    conflict flags (M9.2) arrive through the injected :class:`VerificationAnnotationReader` (the
    production impl is built at the ``api`` root; tests inject the in-memory reader)."""

    def __init__(self, *, annotation_reader: VerificationAnnotationReader) -> None:
        self._annotations = annotation_reader

    async def build(
        self,
        conn: AsyncConnection,
        *,
        session_id: ReviewSessionId,
        account_entity_id: EntityId,
        campaign_run_id: CampaignRunId,
        workspace_id: str,
        review_round: int,
        status: ReviewSessionStatus,
    ) -> ReviewSession:
        scope = WorkspaceScope.for_workspace(workspace_id)
        account_id = await surviving_id(conn, account_entity_id, EntityType.ACCOUNT)

        fit = await self._read_score(conn, account_id, FIT_FIELD, scope=scope)
        intent = await self._read_score(conn, account_id, INTENT_FIELD, scope=scope)

        account_live = [
            c
            for c in await claims_for(conn, account_id, scope=scope)
            if c.field_key not in _SCORE_FIELDS and c.field_key != _NARRATIVE_FIELD
        ]
        committee_raw: list[tuple[EntityId, list[Claim]]] = [
            (contact_id, list(await claims_for(conn, contact_id, scope=scope)))
            for contact_id in await contact_ids_for_account(conn, account_id)
        ]

        winners = await self._winners(conn, account_id, account_live, committee_raw, scope=scope)

        all_claim_ids: list[ClaimId] = [c.id for c in account_live]
        for _cid, cclaims in committee_raw:
            all_claim_ids.extend(c.id for c in cclaims)
        annotations = await self._annotations.annotations_for_claims(
            claim_ids=all_claim_ids, workspace_id=workspace_id
        )
        field_conflicts = await self._annotations.open_conflicts_for_account(
            account_entity_id=account_id, workspace_id=workspace_id
        )

        account_rows = tuple(
            self._claim_row(c, winners=winners, annotations=annotations) for c in account_live
        )
        committee = tuple(
            self._committee_member(cid, cclaims, winners=winners, annotations=annotations)
            for cid, cclaims in committee_raw
        )

        prov = await claims_by_ids(conn, all_claim_ids, scope=scope)
        provenance_index = {
            str(cid): ProvenanceRef(
                source_url=cl.source_url,
                source_tier=cl.source_tier,
                evidence_span=cl.evidence_span,
            )
            for cid, cl in prov.items()
        }

        return ReviewSession(
            session_id=session_id,
            account_entity_id=account_id,
            campaign_run_id=campaign_run_id,
            review_round=review_round,
            status=status,
            fit_score=fit,
            intent_score=intent,
            account_claims=account_rows,
            committee=committee,
            # Best-effort: the M12 value-narrative claims are assembled at the HANDOFF phase, which
            # runs *after* REVIEW — so they do not exist yet here. The reviewer reviews the claims
            # that *feed* the narrative; the handoff then assembles it from the corrected/approved
            # current_value. Populated once narrative claims exist for the field.
            value_narrative=(),
            field_conflicts=field_conflicts,
            provenance_index=provenance_index,
        )

    async def _read_score(
        self, conn: AsyncConnection, account_id: EntityId, field_key: str, *, scope: WorkspaceScope
    ) -> Score | None:
        cv = await current_value(conn, account_id, field_key, scope=scope)
        if cv is None or not isinstance(cv.value_json, dict):
            return None
        payload = cv.value_json
        value = payload.get("value")
        if value is None:
            return None
        return Score.model_validate({"value": value, "components": payload.get("components", [])})

    async def _winners(
        self,
        conn: AsyncConnection,
        account_id: EntityId,
        account_live: list[Claim],
        committee_raw: list[tuple[EntityId, list[Claim]]],
        *,
        scope: WorkspaceScope,
    ) -> _Winners:
        winners: _Winners = {}
        acct_fields = {c.field_key for c in account_live}
        if acct_fields:
            winners.update(await current_values(conn, [account_id], acct_fields, scope=scope))
        contact_ids = [cid for cid, _ in committee_raw]
        contact_fields = {c.field_key for _cid, cclaims in committee_raw for c in cclaims}
        if contact_ids and contact_fields:
            winners.update(await current_values(conn, contact_ids, contact_fields, scope=scope))
        return winners

    def _claim_row(
        self,
        claim: Claim,
        *,
        winners: _Winners,
        annotations: dict[ClaimId, ClaimAnnotation],
    ) -> ReviewClaimRow:
        annotation = annotations.get(claim.id, ClaimAnnotation())
        cv = winners.get((claim.entity_id, claim.field_key))
        is_current = cv is not None and cv.provenance.claim_id == claim.id
        return ReviewClaimRow(
            claim_id=claim.id,
            field_key=claim.field_key,
            value_json=claim.value_json,
            source_url=claim.source_url,
            source_tier=claim.source_tier,
            confidence=claim.confidence,
            evidence_span=claim.evidence_span,
            corroborations=claim.corroborations,
            observed_at=claim.observed_at,
            freshness_state=cv.freshness_state if (cv is not None and is_current) else None,
            verification_status=claim.verification_status,
            is_current=is_current,
            identity_binding=claim.identity_binding,
            use_class=claim.use_class,
            annotation=annotation,
            empty_reason=_empty_reason(claim, annotation),
        )

    def _committee_member(
        self,
        contact_id: EntityId,
        cclaims: list[Claim],
        *,
        winners: _Winners,
        annotations: dict[ClaimId, ClaimAnnotation],
    ) -> ReviewCommitteeMember:
        profile = tuple(
            self._claim_row(c, winners=winners, annotations=annotations)
            for c in cclaims
            if c.field_key not in (_PERSONA_FIELD, _ROLE_FIELD)
        )
        persona_cv = winners.get((contact_id, _PERSONA_FIELD))
        role_cv = winners.get((contact_id, _ROLE_FIELD))
        return ReviewCommitteeMember(
            contact_entity_id=contact_id,
            persona=_parse_persona(persona_cv.value_json) if persona_cv is not None else None,
            role_on_committee=_parse_role(role_cv.value_json) if role_cv is not None else None,
            profile_claims=profile,
        )


class InMemoryVerificationAnnotationReader:
    """A fixture :class:`~clue_core.VerificationAnnotationReader` (no DB) — lets M13.1
    build and test the projection with zero ``verification``/``compliance`` imports (mirrors
    ``narrative.InMemoryCommitteeReader``). The production impl is wired at the ``api`` root."""

    def __init__(
        self,
        *,
        annotations: dict[ClaimId, ClaimAnnotation] | None = None,
        conflicts: dict[EntityId, tuple[FieldConflict, ...]] | None = None,
    ) -> None:
        self._annotations = annotations or {}
        self._conflicts = conflicts or {}

    async def annotations_for_claims(
        self, *, claim_ids: Sequence[ClaimId], workspace_id: str
    ) -> dict[ClaimId, ClaimAnnotation]:
        return {cid: self._annotations[cid] for cid in claim_ids if cid in self._annotations}

    async def open_conflicts_for_account(
        self, *, account_entity_id: EntityId, workspace_id: str
    ) -> tuple[FieldConflict, ...]:
        return self._conflicts.get(account_entity_id, ())


# Static-time conformance: the fixture must satisfy the core seam, so the projection tests exercise
# the same surface the production api-root reader implements.
_READER_IS_AN_ANNOTATION_READER: type[VerificationAnnotationReader] = (
    InMemoryVerificationAnnotationReader
)
