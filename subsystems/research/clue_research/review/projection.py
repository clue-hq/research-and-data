"""The M13.1 per-account review read projection (the ``ReviewSession`` assembler).

Pure store reads (the claim store M1 + identity M2) plus the injected cross-package
:class:`~clue_core.VerificationAnnotationReader` seam (the M9/M10 per-claim verdicts live
in tables ``review`` may not import). Reuses the frozen ``core`` projection value types — it invents
no shape. ``review`` MAY import ``claimstore``/``identity`` (the M1-M4 services) + ``core`` (the
import-linter independence rule allows the shared base + services; it bans only sibling *workers*).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    Claim,
    ClaimId,
    CurrentValue,
    EntityId,
    EntityType,
    JudgeVerdict,
    Persona,
    ProjectRunId,
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
    DEFAULT_MERGE_POLICY,
    WorkspaceScope,
    claims_by_ids,
    claims_for,
    current_values_resolved_for_product,
    merge_claims,
)
from clue_research.identity import contact_ids_for_account, get_contact, surviving_id

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


@dataclass(frozen=True)
class ReviewProjectScope:
    """The project-run authority needed to keep a review projection product-exact."""

    product_id: str | None


class ReviewProjectScopeNotFound(LookupError):
    """The review session's project run is absent or belongs to another workspace."""


class ReviewProjectScopeReader(Protocol):
    async def read_scope(
        self,
        conn: AsyncConnection,
        *,
        project_run_id: ProjectRunId,
        workspace_id: str,
    ) -> ReviewProjectScope: ...


def _product_allowed(claim: Claim, product_id: str | None) -> bool:
    return claim.product_id is None or claim.product_id == product_id


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

    def __init__(
        self,
        *,
        annotation_reader: VerificationAnnotationReader,
        project_scope_reader: ReviewProjectScopeReader,
    ) -> None:
        self._annotations = annotation_reader
        self._project_scope = project_scope_reader

    async def build(
        self,
        conn: AsyncConnection,
        *,
        session_id: ReviewSessionId,
        account_entity_id: EntityId,
        project_run_id: ProjectRunId,
        workspace_id: str,
        review_round: int,
        status: ReviewSessionStatus,
    ) -> ReviewSession:
        scope = WorkspaceScope.for_workspace(workspace_id)
        project_scope = await self._project_scope.read_scope(
            conn,
            project_run_id=project_run_id,
            workspace_id=workspace_id,
        )
        account_id = await surviving_id(conn, account_entity_id, EntityType.ACCOUNT)

        fit = await self._read_score(
            conn,
            account_id,
            FIT_FIELD,
            project_run_id=project_run_id,
            product_id=project_scope.product_id,
            scope=scope,
        )
        intent = await self._read_score(
            conn,
            account_id,
            INTENT_FIELD,
            project_run_id=project_run_id,
            product_id=project_scope.product_id,
            scope=scope,
        )

        account_live = [
            c
            for c in await claims_for(conn, account_id, scope=scope)
            if c.field_key not in _SCORE_FIELDS
            and c.field_key != _NARRATIVE_FIELD
            and _product_allowed(c, project_scope.product_id)
        ]
        committee_raw: list[tuple[EntityId, list[Claim]]] = []
        for contact_id in await contact_ids_for_account(conn, account_id):
            contact_claims = [
                claim
                for claim in await claims_for(conn, contact_id, scope=scope)
                if _product_allowed(claim, project_scope.product_id)
            ]
            if contact_claims:
                committee_raw.append((contact_id, contact_claims))

        winners = await self._winners(
            conn,
            account_id,
            account_live,
            committee_raw,
            product_id=project_scope.product_id,
            scope=scope,
        )

        all_claim_ids: list[ClaimId] = [c.id for c in account_live]
        for _cid, cclaims in committee_raw:
            all_claim_ids.extend(c.id for c in cclaims)
        annotations = await self._annotations.annotations_for_claims(
            claim_ids=all_claim_ids, workspace_id=workspace_id
        )
        field_conflicts = self._product_scoped_conflicts(
            await self._annotations.open_conflicts_for_account(
                account_entity_id=account_id, workspace_id=workspace_id
            ),
            claim_ids=all_claim_ids,
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
            project_run_id=project_run_id,
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

    @staticmethod
    def _product_scoped_conflicts(
        conflicts: Sequence[FieldConflict],
        *,
        claim_ids: Sequence[ClaimId],
    ) -> tuple[FieldConflict, ...]:
        """Remove conflicts whose evidence does not survive this product-exact projection."""

        allowed = frozenset(claim_ids)
        scoped: list[FieldConflict] = []
        for conflict in conflicts:
            surviving = tuple(
                claim_id for claim_id in conflict.conflicting_claim_ids if claim_id in allowed
            )
            if len(surviving) < 2:
                continue
            scoped.append(conflict.model_copy(update={"conflicting_claim_ids": surviving}))
        return tuple(scoped)

    async def _read_score(
        self,
        conn: AsyncConnection,
        account_id: EntityId,
        field_key: str,
        *,
        project_run_id: ProjectRunId,
        product_id: str | None,
        scope: WorkspaceScope,
    ) -> Score | None:
        candidates = []
        for claim in await claims_for(conn, account_id, field_key, scope=scope):
            value = claim.value_json
            if not isinstance(value, dict):
                continue
            if product_id is None:
                if claim.product_id is not None:
                    continue
            elif claim.product_id != product_id:
                continue
            pinned_run = value.get("project_run_id")
            if pinned_run is not None and pinned_run != str(project_run_id):
                continue
            if product_id is not None and pinned_run != str(project_run_id):
                continue
            candidates.append(claim)
        cv = merge_claims(
            candidates,
            None,
            DEFAULT_MERGE_POLICY,
            datetime.now(UTC),
        )
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
        product_id: str | None,
        scope: WorkspaceScope,
    ) -> _Winners:
        acct_fields = {c.field_key for c in account_live}
        contact_ids = [cid for cid, _ in committee_raw]
        contact_fields = {c.field_key for _cid, cclaims in committee_raw for c in cclaims}
        return await current_values_resolved_for_product(
            conn,
            entity_ids=(account_id, *contact_ids),
            field_keys=tuple(str(value) for value in acct_fields | contact_fields),
            scope=scope,
            product_id=product_id,
        )

    async def claim_is_reviewable(
        self,
        conn: AsyncConnection,
        *,
        claim: Claim,
        account_entity_id: EntityId,
        project_run_id: ProjectRunId,
        workspace_id: str,
    ) -> bool:
        """Fail closed when an action targets a claim outside the rendered session scope."""

        project_scope = await self._project_scope.read_scope(
            conn,
            project_run_id=project_run_id,
            workspace_id=workspace_id,
        )
        if not _product_allowed(claim, project_scope.product_id):
            return False
        if claim.field_key in _SCORE_FIELDS or claim.field_key in {
            _NARRATIVE_FIELD,
            _PERSONA_FIELD,
            _ROLE_FIELD,
        }:
            return False
        scope = WorkspaceScope.for_workspace(workspace_id)
        live_ids = {
            candidate.id
            for candidate in await claims_for(
                conn,
                claim.entity_id,
                claim.field_key,
                scope=scope,
            )
        }
        if claim.id not in live_ids:
            return False
        account_id = await surviving_id(conn, account_entity_id, EntityType.ACCOUNT)
        if claim.entity_type is EntityType.ACCOUNT:
            return claim.entity_id == account_id
        if claim.entity_type is not EntityType.CONTACT:
            return False
        contact = await get_contact(conn, claim.entity_id)
        return (
            contact is not None
            and contact.workspace_id == workspace_id
            and contact.merged_into is None
            and await surviving_id(
                conn,
                contact.account_entity_id,
                EntityType.ACCOUNT,
            )
            == account_id
        )

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
