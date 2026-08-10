"""The M13.1 Tier-1 review surface implementation (:class:`ReviewSurfaceImpl`).

Drives the human gate behind the frozen :class:`~clue_core.ReviewSurface` contract:

* ``open_session`` — idempotently opens the durable ``review_session`` for one account_handoff
  candidate and returns its read projection (the REVIEW phase handler opens one per ready account;
  the UI re-reads the same session).
* ``apply_action`` — records the action and writes the claim mutation: a **correction** is a new
  ``human`` (tier-1) claim that supersedes the original so ``current_value`` returns the human-tier
  value; a **reject** is a ``REJECTED`` superseding claim so the merge drops it from the handoff. An
  **approve** writes no claim. Every action appends one ``review_action`` audit row and emits the
  M13.2 disposition through the injected seam.
* ``finalize`` — marks the session finalized (unblocking that account's handoff) and, when this call
  closed the run's *last* open session, resumes the paused campaign via the injected hook.

Each method runs in one ``transaction()`` so the claim write + the audit row + the disposition emit
commit atomically (a replay is idempotent on the session/append-only audit). The correction's
``source_tier=1`` is load-bearing: ``merge._winner`` ranks by tier (lowest = most trusted) and does
*not* privilege ``HUMAN``, so only a tier-1 human claim is guaranteed to win ``current_value``.
"""

from __future__ import annotations

from pydantic import JsonValue

from clue_core import (
    Claim,
    ClaimId,
    EntityId,
    EntityType,
    ExtractionMethod,
    FieldClass,
    IdentityBinding,
    ProjectRunId,
    ResearchMode,
    ReviewAction,
    ReviewActionOutcome,
    ReviewRejectReason,
    ReviewSession,
    ReviewSessionStatus,
    ReviewSurface,
    RunId,
    VerificationStatus,
    classify_field_key,
    new_run_id,
)
from clue_core.review import (
    ReviewDispositionEmitter,
    ReviewResumeHook,
    ReviewSessionId,
    VerificationAnnotationReader,
)
from clue_db import ConnFactory
from clue_research.claimstore import (
    WorkspaceScope,
    claims_by_ids,
    record_run_lineage,
    supersede_claim,
)
from clue_research.review.projection import ReviewProjector
from clue_research.review.repository import (
    count_open_sessions,
    ensure_review_session,
    finalize_review_session,
    get_review_session,
    project_id_for_run,
    record_review_action,
)

# The redaction sentinel a reject writes as the superseding claim's value (distinct from DSAR's
# ``__erased__``). The original stays queryable on the superseded claim + the review_action row.
_REJECT_SENTINEL: JsonValue = {"__rejected__": True}


class ReviewError(Exception):
    """Base error for the review surface (M13.1)."""


class ReviewSessionNotFound(ReviewError):
    """No ``review_session`` exists for the given id."""


class SessionNotOpen(ReviewError):
    """An action/finalize was attempted on a session that is not ``OPEN``."""


class ClaimNotInSession(ReviewError):
    """The acted-on claim is not live in the session's tenant scope (e.g. already superseded)."""


def _research_mode(entity_type: EntityType) -> ResearchMode:
    return (
        ResearchMode.CONTACT_PROFILING
        if entity_type is EntityType.CONTACT
        else ResearchMode.ACCOUNT_PROFILING
    )


def _build_correction(
    target: Claim, corrected_value: JsonValue, *, run_id: RunId, note: str | None
) -> Claim:
    """A ``human``, tier-1, VERIFIED claim that supersedes ``target`` and wins ``current_value``.

    tier-1 is required (``merge._winner`` ranks by tier and does not privilege HUMAN). A
    ``contact.facet.*`` correction must carry STRONG binding (a human vouching for the value being
    this person) + the target's ``use_class`` (else it is non-promotable and ``insert_claim`` raises
    on a VERIFIED non-promotable claim)."""
    is_facet = classify_field_key(target.field_key) is FieldClass.CONTACT_FACET
    return Claim(
        entity_id=target.entity_id,
        entity_type=target.entity_type,
        field_key=target.field_key,
        value_json=corrected_value,
        source_tier=1,
        extraction_method=ExtractionMethod.HUMAN,
        evidence_span=note or "human review correction",
        confidence=1.0,
        run_id=run_id,
        research_mode=_research_mode(target.entity_type),
        verification_status=VerificationStatus.VERIFIED,
        identity_binding=(IdentityBinding.STRONG if is_facet else target.identity_binding),
        use_class=target.use_class,
        reuse_scope=target.reuse_scope,
        workspace_id=target.workspace_id,
        product_id=target.product_id,
    )


def _build_reject(
    target: Claim, *, reason: ReviewRejectReason, run_id: RunId, note: str | None
) -> Claim:
    """A ``REJECTED`` redacted claim that supersedes ``target`` so ``merge._is_eligible`` drops it —
    the field returns empty (a correct output) unless another eligible claim wins. Models
    ``dsar.build_tombstone``; a ``contact.facet.*`` reject carries WEAK binding (a second
    ineligibility mechanism)."""
    is_facet = classify_field_key(target.field_key) is FieldClass.CONTACT_FACET
    span = f"rejected: {reason.value}" + (f" — {note}" if note else "")
    return Claim(
        entity_id=target.entity_id,
        entity_type=target.entity_type,
        field_key=target.field_key,
        value_json=_REJECT_SENTINEL,
        source_tier=1,
        extraction_method=ExtractionMethod.HUMAN,
        evidence_span=span,
        confidence=0.0,
        run_id=run_id,
        research_mode=_research_mode(target.entity_type),
        verification_status=VerificationStatus.REJECTED,
        identity_binding=(IdentityBinding.WEAK if is_facet else target.identity_binding),
        use_class=target.use_class,
        reuse_scope=target.reuse_scope,
        workspace_id=target.workspace_id,
        product_id=target.product_id,
    )


class ReviewSurfaceImpl:
    """The production :class:`~clue_core.ReviewSurface` (M13.1). Construct once with a
    :class:`~clue_research.review.projection.ReviewProjector`, a ``session_factory``
    (``transaction``) and (optionally) the resume hook + disposition emitter; wired at the ``api``
    composition root."""

    def __init__(
        self,
        *,
        projector: ReviewProjector,
        session_factory: ConnFactory,
        resume_hook: ReviewResumeHook | None = None,
        disposition_emitter: ReviewDispositionEmitter | None = None,
    ) -> None:
        self._projector = projector
        self._session_factory = session_factory
        self._resume = resume_hook
        self._emit = disposition_emitter

    async def open_session(
        self,
        *,
        account_entity_id: EntityId,
        project_run_id: ProjectRunId,
        workspace_id: str,
        review_round: int = 1,
        opened_by: str | None = None,
    ) -> ReviewSession:
        async with self._session_factory() as conn:
            row = await ensure_review_session(
                conn,
                account_entity_id=account_entity_id,
                project_run_id=project_run_id,
                workspace_id=workspace_id,
                review_round=review_round,
                opened_by=opened_by,
            )
            return await self._projector.build(
                conn,
                session_id=row.id,
                account_entity_id=row.account_entity_id,
                project_run_id=row.project_run_id,
                workspace_id=row.workspace_id,
                review_round=row.review_round,
                status=row.status,
            )

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
    ) -> ReviewActionOutcome:
        async with self._session_factory() as conn:
            row = await get_review_session(conn, session_id)
            if row is None:
                raise ReviewSessionNotFound(str(session_id))
            if row.status is not ReviewSessionStatus.OPEN:
                raise SessionNotOpen(f"{session_id}: {row.status.value}")
            scope = WorkspaceScope.for_workspace(row.workspace_id)
            target = (await claims_by_ids(conn, [claim_id], scope=scope)).get(claim_id)
            if target is None or not await self._projector.claim_is_reviewable(
                conn,
                claim=target,
                account_entity_id=row.account_entity_id,
                project_run_id=row.project_run_id,
                workspace_id=row.workspace_id,
            ):
                raise ClaimNotInSession(str(claim_id))

            superseding_id: ClaimId | None = None
            row_reason: ReviewRejectReason | None = None
            row_corrected: JsonValue | None = None
            if action in {ReviewAction.CORRECT, ReviewAction.REJECT}:
                # FI-2 P2 (spec §3): a human action mints its own one-claim run, so "register at
                # the mint site" is per action here — one lineage row per correction/reject, not a
                # registration inside a write loop. Minted once for the action and registered in
                # the same transaction as the superseding claim below, attributed to the session's
                # project run. ``approve`` writes no claim, so it mints and registers nothing.
                #
                # ``review_session.project_run_id`` is a *soft* FK (no REFERENCES, mirroring
                # ``claim``), so the run row may legitimately be absent. When it is, the action is
                # recorded as a workspace-level ``manual`` run rather than failing: a human
                # correction must never be blocked by a lineage-attribution lookup.
                run_id = new_run_id()
                run_project_id = await project_id_for_run(conn, row.project_run_id)
                await record_run_lineage(
                    conn,
                    run_id=run_id,
                    workspace_id=row.workspace_id,
                    kind="manual",
                    project_id=run_project_id,
                    project_run_id=(row.project_run_id if run_project_id is not None else None),
                )
            if action is ReviewAction.CORRECT:
                if corrected_value_json is None:
                    raise ReviewError("a correction requires corrected_value_json")
                row_corrected = corrected_value_json
                superseding_id = await supersede_claim(
                    conn,
                    target.id,
                    _build_correction(target, corrected_value_json, run_id=run_id, note=note),
                )
            elif action is ReviewAction.REJECT:
                row_reason = reason_code or ReviewRejectReason.OTHER
                superseding_id = await supersede_claim(
                    conn,
                    target.id,
                    _build_reject(target, reason=row_reason, run_id=run_id, note=note),
                    validate_field=False,
                )

            action_id = await record_review_action(
                conn,
                review_session_id=session_id,
                claim_id=claim_id,
                action=action,
                actor=actor,
                reason_code=row_reason,
                corrected_value_json=row_corrected,
                note=note,
                superseding_claim_id=superseding_id,
            )
            outcome = ReviewActionOutcome(
                action=action,
                claim_id=claim_id,
                review_action_id=action_id,
                superseding_claim_id=superseding_id,
            )
        # Emit the M13.2 disposition OUTSIDE the write transaction (mirrors ``finalize``'s resume
        # hook below). The production emitter opens its OWN transaction to mirror the now-committed
        # ``review_action`` row; emitting in-txn would hide that row from a separate-connection
        # emitter (it would fall back to a null reason_code / wrong occurred_at), and a rollback
        # after a committed emit would orphan the disposition. The ``review_action`` is the durable
        # backstop, so a failed/replayed emit loses no signal.
        if self._emit is not None:
            contact_id = target.entity_id if target.entity_type is EntityType.CONTACT else None
            await self._emit.on_review_action(
                outcome,
                account_entity_id=row.account_entity_id,
                contact_entity_id=contact_id,
                project_run_id=row.project_run_id,
                actor=actor,
            )
        return outcome

    async def finalize(self, *, session_id: ReviewSessionId, actor: str) -> ReviewSession:
        async with self._session_factory() as conn:
            row, transitioned = await finalize_review_session(conn, session_id)
            if row is None:
                raise ReviewSessionNotFound(str(session_id))
            remaining = (
                await count_open_sessions(conn, row.project_run_id) if transitioned else None
            )
            session = await self._projector.build(
                conn,
                session_id=row.id,
                account_entity_id=row.account_entity_id,
                project_run_id=row.project_run_id,
                workspace_id=row.workspace_id,
                review_round=row.review_round,
                status=row.status,
            )
        # Resume the paused campaign OUTSIDE the read transaction (the hook drives the state
        # machine, which manages its own transactions) — only when *this* call closed the run's
        # last open session (``transitioned`` guards an idempotent re-finalize re-firing resume).
        if transitioned and remaining == 0 and self._resume is not None:
            await self._resume.resume_review(row.project_run_id)
        return session


# Static-time conformance: the impl must satisfy the frozen core seam (mypy-checked).
_IMPL_IS_A_REVIEW_SURFACE: type[ReviewSurface] = ReviewSurfaceImpl

# Re-exported so the api composition root can name the annotation-reader seam without importing the
# projection module directly (kept here as the package's surface aggregation point).
__all__ = [
    "ReviewSurfaceImpl",
    "ReviewError",
    "ReviewSessionNotFound",
    "SessionNotOpen",
    "ClaimNotInSession",
    "VerificationAnnotationReader",
]
