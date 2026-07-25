"""Tier-1 review-surface contracts (M13.1) — the ``REVIEW`` campaign-phase seam.

M13.1 puts a human review surface immediately before the M12 handoff. The chosen design (locked
2026-06-26) models Tier-1 review as a **new ``ProjectPhase.REVIEW`` between ``VERIFICATION`` and
``HANDOFF``** that suspends via the existing durable ``AWAITING_INPUT`` checkpoint (M7.3) — *not* a
new per-account-graph ``interrupt()`` node. This reuses tested, crash-safe, idempotent machinery the
state machine already reserves for M13 (the ``PhaseCheckpointStatus.AWAITING_INPUT`` docstring names
"the review payload the surface (M13) reads back"). Divergence from the spec's literal
"interrupt() on the per-account graph" is deliberate and documented; the ``finalize → resume`` seam
preserves the eventual Temporal swap (phases ↦ activities, the gate ↦ a human-task signal).

This module is the **frozen contract** — exactly like ``core.execution`` (the durable seams) and
``core.compliance`` (the use gate): the contract lives in ``core`` while the implementation lives in
its package (``review``), wired at the ``api`` composition root. It lives here, not in ``review``,
because the ``review`` impl, the ``api`` ``ReviewPhaseHandler``, and the handoff gate must all bind
to one definition and ``review`` may not be imported by ``api``'s sibling packages (the
import-linter independence contract).

The per-claim verification annotations the surface shows (faithfulness verdict M9.3, use-gate result
M10.3, conflict flag M9.2) live in tables owned by ``verification``/``compliance`` — packages
``review`` may not import — so they arrive through the injected
:class:`VerificationAnnotationReader` seam, whose concrete impl is built at the ``api`` root. The
disposition emitted per action is the M13.2 contract; M13.1 calls the narrow
:class:`ReviewDispositionEmitter` seam (a no-op until M13.2 supplies the ``DispositionStore``-backed
impl) and does not define the disposition record here.

Architecture sources: substrate §10 (Tier-1 review is a designed checkpoint; approve/correct/reject
per claim; corrections become labeled training data), §6 (the verification outputs each claim
shows), §5c (durable crash-resumability); Doc D §3/§5 (per personal claim: ``identity_binding`` +
``use_class`` + use-gate result); docs/specs/M13-review-feedback-observability.md §M13.1.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import NewType, Protocol, runtime_checkable
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from clue_core.compliance import UseDecision
from clue_core.enums import (
    FreshnessState,
    IdentityBinding,
    JudgeVerdict,
    Persona,
    ReviewAction,
    ReviewRejectReason,
    ReviewSessionStatus,
    UseClass,
    VerificationStatus,
)
from clue_core.field import FieldKey
from clue_core.handoff import ProvenanceRef, Score, ValueNarrativeItem
from clue_core.primitives import (
    ClaimId,
    Confidence,
    EntityId,
    ProjectRunId,
    SourceTier,
    UtcDatetime,
)

# The durable id of one ``review_session`` row (M13.1). Distinct NewType so a session id is never
# transposed with a claim/entity/run id.
ReviewSessionId = NewType("ReviewSessionId", UUID)


# --- per-claim annotations (the cross-package M9/M10 seam return type) -------


class ClaimAnnotation(BaseModel):
    """The per-claim verification/governance verdicts shown beside a claim value (M9.3/M10.3).

    All optional — absent when the relevant gate never ran for that claim (an un-judged tier≤3
    account claim has no faithfulness verdict; a non-personal claim has no use decision). Produced
    by the :class:`VerificationAnnotationReader` seam (the tables live in
    ``verification``/``compliance`` which ``review`` cannot import)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    faithfulness_verdict: JudgeVerdict | None = None  # M9.3, tier-4 synthesis claims
    faithfulness_score: Confidence | None = None
    use_decision: UseDecision | None = None  # M10.3, contact personal claims


class ReviewClaimRow(BaseModel):
    """One claim as the Tier-1 reviewer sees it (M13.1): the value, its full provenance, its
    verification annotations, and — for an empty/flagged field — the reason it is empty (an empty,
    flagged field is a *correct* output, conventions §5; it is not a defect).

    Composes the claim's own columns (value/source/tier/confidence/span/corroborations/binding/
    use_class) with the cross-package :class:`ClaimAnnotation` and the field's merged freshness
    state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: ClaimId
    field_key: FieldKey
    value_json: JsonValue
    source_url: str | None = None
    source_tier: SourceTier
    confidence: Confidence
    evidence_span: str | None = None
    corroborations: int = 0
    observed_at: UtcDatetime | None = None
    freshness_state: FreshnessState | None = (
        None  # the field's merged TTL state (M9.5), where known
    )
    verification_status: VerificationStatus
    is_current: bool = False  # whether this claim currently wins ``current_value`` for its field
    # contact-claim governance provenance (present for contact claims; None for account claims)
    identity_binding: IdentityBinding | None = None
    use_class: UseClass | None = None
    # cross-package annotations (via the VerificationAnnotationReader seam)
    annotation: ClaimAnnotation = Field(default_factory=ClaimAnnotation)
    # why an empty/flagged field is empty (no evidence span / weak binding / disallowed use-class /
    # unsupported by the judge); None when the field carries a usable value.
    empty_reason: str | None = None


class ReviewCommitteeMember(BaseModel):
    """A buying-committee contact as it appears in the review surface — persona/role plus each of
    its profile claims as a reviewable :class:`ReviewClaimRow` (carrying ``identity_binding`` +
    ``use_class`` + the use-gate result for every personal hook, Doc D §5)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contact_entity_id: EntityId
    persona: Persona | None = None
    role_on_committee: str | None = None
    profile_claims: tuple[ReviewClaimRow, ...] = ()


class FieldConflict(BaseModel):
    """An OPEN ``conflict_flag`` for an ``(entity, field)`` — the authoritative, mode-aware review
    signal (M9.2), NOT ``CurrentValue.conflict`` (which over-flags under exact equality). The
    surface forces a flagged/conflict claim to an explicit disposition (batch ergonomic, §33)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_id: EntityId
    field_key: FieldKey
    conflicting_claim_ids: tuple[ClaimId, ...] = ()


class ReviewSession(BaseModel):
    """The read projection for one ``account_handoff`` candidate under review (M13.1) — one
    high-tier ``account_entity_id`` within a ``project_run`` at a ``review_round``.

    A pure projection over the claim store (M1), identity (M2), the decomposed scores (M6), and the
    verification results (M9/M10 via the annotation seam). ``value_narrative`` is best-effort (the
    M12 narrative claims may not exist before the handoff phase). ``provenance_index`` mirrors the
    M12.2 shape so "every fact links to its source" holds in the review surface too."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    session_id: ReviewSessionId
    account_entity_id: EntityId
    project_run_id: ProjectRunId
    review_round: int = 1
    status: ReviewSessionStatus = ReviewSessionStatus.OPEN
    fit_score: Score | None = None
    intent_score: Score | None = None
    account_claims: tuple[ReviewClaimRow, ...] = ()
    committee: tuple[ReviewCommitteeMember, ...] = ()
    value_narrative: tuple[ValueNarrativeItem, ...] = ()  # best-effort (absent pre-handoff)
    field_conflicts: tuple[FieldConflict, ...] = ()
    provenance_index: dict[str, ProvenanceRef] = {}


class ReviewActionOutcome(BaseModel):
    """What :meth:`ReviewSurface.apply_action` returns — the durable result of one review action.

    Every action appends exactly one ``review_action`` audit row (``review_action_id``); a
    ``CORRECT`` writes a new ``human`` claim that supersedes the original and an ``REJECT`` writes a
    ``REJECTED`` superseding claim (``superseding_claim_id`` — ``None`` for ``APPROVE``)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    action: ReviewAction
    claim_id: ClaimId
    review_action_id: UUID
    superseding_claim_id: ClaimId | None = None


# --- seams (Protocols; concrete impls wired at the api composition root) -----


@runtime_checkable
class VerificationAnnotationReader(Protocol):
    """Reads the per-claim faithfulness (M9.3) + use-gate (M10.3) verdicts and the open conflict
    flags (M9.2) for the claims/fields in a review session — the M13.1 ↔ M9/M10 seam.

    ``review`` cannot import ``verification``/``compliance`` (the independence contract), so the
    production impl (which reads ``faithfulness_verdict`` / ``use_decision`` / ``conflict_flag``) is
    constructed and injected at the ``api`` composition root, exactly like ``core.UseGate`` /
    ``core.FaithfulnessJudge``. ``workspace_id`` lets the impl scope-check the underlying claims
    even
    though the side tables carry no tenant column."""

    async def annotations_for_claims(
        self, *, claim_ids: Sequence[ClaimId], workspace_id: str
    ) -> dict[ClaimId, ClaimAnnotation]: ...

    async def open_conflicts_for_account(
        self, *, account_entity_id: EntityId, workspace_id: str
    ) -> tuple[FieldConflict, ...]: ...


@runtime_checkable
class ReviewSurface(Protocol):
    """The Tier-1 review surface contract (M13.1). A pure client (an internal admin UI today, a
    client portal later) drives this; the surface is swappable behind it.

    ``open_session`` is idempotent on ``(account_entity_id, project_run_id, review_round)``: it
    ensures the durable ``review_session`` row exists (status ``OPEN``) and returns its read
    projection — so the ``REVIEW`` phase handler can open a session per ready account, and the UI
    can re-read the same session. ``apply_action`` records the action (and writes the
    correction/reject claim) and emits the M13.2 disposition. ``finalize`` marks the session
    finalized (unblocking that account's handoff) and, when every open session for the run is
    finalized, resumes the campaign."""

    async def open_session(
        self,
        *,
        account_entity_id: EntityId,
        project_run_id: ProjectRunId,
        workspace_id: str,
        review_round: int = 1,
        opened_by: str | None = None,
    ) -> ReviewSession: ...

    async def apply_action(
        self,
        *,
        session_id: ReviewSessionId,
        claim_id: ClaimId,
        action: ReviewAction,
        actor: str,
        corrected_value_json: JsonValue | None = None,
        reason_code: ReviewRejectReason | None = None,
        note: str | None = None,
    ) -> ReviewActionOutcome: ...

    async def finalize(self, *, session_id: ReviewSessionId, actor: str) -> ReviewSession: ...


@runtime_checkable
class ReviewResumeHook(Protocol):
    """Resumes the paused campaign once review is complete (the ``finalize → resume`` seam, M13.1).

    ``review`` cannot import ``durable``, so the campaign resume (``ProjectRun.submit_checkpoint``)
    is injected as this hook at the ``api`` root. Called by ``finalize`` when the last open session
    for the run is finalized; a ``None`` hook (unit tests / account-only runs) just leaves the
    campaign suspended for an explicit operator resume."""

    async def resume_review(self, project_run_id: ProjectRunId) -> None: ...


@runtime_checkable
class ReviewDispositionEmitter(Protocol):
    """The seam to M13.2 disposition capture (substrate §9/§10): M13.1 calls this on every review
    action so the disposition becomes labeled training data.

    The ``Disposition`` record and the ``DispositionStore`` are M13.2's contract — *not* defined
    here (spec §42). M13.1 only needs a callable seam; the ``api`` root wires a **no-op** until
    M13.2 supplies the ``DispositionStore``-backed emitter. The ``review_action`` rows are the
    durable audit M13.2 reads/mirrors, so no disposition is lost while the emitter is a no-op."""

    async def on_review_action(
        self,
        outcome: ReviewActionOutcome,
        *,
        account_entity_id: EntityId,
        contact_entity_id: EntityId | None,
        project_run_id: ProjectRunId,
        actor: str,
    ) -> None: ...
