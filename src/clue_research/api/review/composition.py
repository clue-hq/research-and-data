"""The ``CampaignPhase.REVIEW`` composition root (M13.1) — wires the concrete seams.

``api`` is the import-linter-exempt seam, so it may import both the otherwise-independent ``review``
package and the ``verification``/``compliance``/``durable`` packages whose data the review surface
displays / whose state machine it resumes. This module assembles:

* :class:`DbVerificationAnnotationReader` — the production
  :class:`~clue_research.core.VerificationAnnotationReader` over the ``faithfulness_verdict``
  (M9.3), ``use_decision`` (M10.3), and ``conflict_flag`` (M9.2) side tables (read by raw SQL, the
  composition root — these could be promoted to public reader fns in
  ``verification``/``compliance`` later; tracked follow-up);
* :class:`CampaignRunResumeHook` — the ``finalize → resume`` seam over
  ``CampaignRun.submit_checkpoint`` (``review`` may not import ``durable``);
* :class:`NoopReviewDispositionEmitter` — the M13.2 seam, a no-op until M13.2 supplies the
  ``DispositionStore``-backed emitter (review actions are still recorded as ``review_action`` rows,
  so no disposition is lost);
* :func:`build_review_phase_handler` / :func:`register_review_phase_handler` — the ``REVIEW``
  ``PhaseHandler`` over the M12-ready account set (the readiness reader *without* the review gate),
  registered into the M7.3 ``PhaseHandlerRegistry`` (mirrors the verification registrant).
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import bindparam, text

from clue_research.api.handoff_wiring import DurableHandoffReadinessReader
from clue_research.api.review.handler import ReviewAccountResolver, ReviewPhaseHandler
from clue_research.core import (
    CampaignRunId,
    ClaimId,
    EntityId,
    JudgeVerdict,
    PhaseContext,
    ReviewActionOutcome,
    UseDecision,
    UseReason,
)
from clue_research.core.review import (
    ClaimAnnotation,
    FieldConflict,
    ReviewDispositionEmitter,
    VerificationAnnotationReader,
)
from clue_research.db import ConnFactory, connection, transaction
from clue_research.durable import AccountSpec, register_phase_handler
from clue_research.durable.campaign import CampaignRun, CheckpointNotAwaiting
from clue_research.review import ReviewProjector, ReviewSurfaceImpl


class DbVerificationAnnotationReader:
    """The production :class:`~clue_research.core.VerificationAnnotationReader` over the M9/M10 side
    tables. Manages its own short read transaction (the seam carries no connection). The claim ids
    are already tenant-scoped by the projection (it reads only tenant-visible claims), so the side
    tables — which carry no tenant column — are read by ``claim_id`` directly."""

    def __init__(self, *, conn_factory: ConnFactory = connection) -> None:
        self._conn_factory = conn_factory

    async def annotations_for_claims(
        self, *, claim_ids: Sequence[ClaimId], tenant_id: str
    ) -> dict[ClaimId, ClaimAnnotation]:
        ids = [str(cid) for cid in claim_ids]
        if not ids:
            return {}
        async with self._conn_factory() as conn:
            # The latest faithfulness verdict per claim (one row per judge_model/prompt_version).
            faith = (
                (
                    await conn.execute(
                        text(
                            "SELECT DISTINCT ON (claim_id) claim_id, verdict, score "
                            "FROM faithfulness_verdict WHERE claim_id IN :ids "
                            "ORDER BY claim_id, judged_at DESC"
                        ).bindparams(bindparam("ids", expanding=True)),
                        {"ids": ids},
                    )
                )
                .mappings()
                .all()
            )
            faith_map = {ClaimId(r["claim_id"]): r for r in faith}
            # The latest use decision per claim (one row per policy_version).
            use = (
                (
                    await conn.execute(
                        text(
                            "SELECT DISTINCT ON (claim_id) claim_id, usable_for_outreach, reason, "
                            "policy_version FROM use_decision WHERE claim_id IN :ids "
                            "ORDER BY claim_id, policy_version DESC"
                        ).bindparams(bindparam("ids", expanding=True)),
                        {"ids": ids},
                    )
                )
                .mappings()
                .all()
            )
            use_map = {ClaimId(r["claim_id"]): r for r in use}

        out: dict[ClaimId, ClaimAnnotation] = {}
        for cid in {*faith_map, *use_map}:
            f = faith_map.get(cid)
            u = use_map.get(cid)
            out[cid] = ClaimAnnotation(
                faithfulness_verdict=JudgeVerdict(f["verdict"]) if f is not None else None,
                faithfulness_score=f["score"] if f is not None else None,
                use_decision=(
                    UseDecision(
                        claim_id=cid,
                        usable_for_outreach=u["usable_for_outreach"],
                        reason=UseReason(u["reason"]),
                        policy_version=u["policy_version"],
                    )
                    if u is not None
                    else None
                ),
            )
        return out

    async def open_conflicts_for_account(
        self, *, account_entity_id: EntityId, tenant_id: str
    ) -> tuple[FieldConflict, ...]:
        async with self._conn_factory() as conn:
            rows = (
                (
                    await conn.execute(
                        text(
                            "SELECT field_key, conflicting_claim_ids FROM conflict_flag "
                            "WHERE entity_id = :acct AND resolved_by IS NULL ORDER BY field_key"
                        ),
                        {"acct": account_entity_id},
                    )
                )
                .mappings()
                .all()
            )
        return tuple(
            FieldConflict(
                entity_id=account_entity_id,
                field_key=r["field_key"],
                conflicting_claim_ids=tuple(ClaimId(c) for c in (r["conflicting_claim_ids"] or [])),
            )
            for r in rows
        )


class CampaignRunResumeHook:
    """The ``finalize → resume`` seam (M13.1): resumes the paused campaign by submitting the REVIEW
    checkpoint and driving the run to completion (through HANDOFF). ``review`` may not import
    ``durable``, so the campaign machine is injected here. Idempotent — a re-fire after the run has
    already advanced is a no-op (``CheckpointNotAwaiting`` is swallowed)."""

    def __init__(self, *, campaign_run: CampaignRun | None = None) -> None:
        self._run = campaign_run

    async def resume_review(self, campaign_run_id: CampaignRunId) -> None:
        run = self._run if self._run is not None else CampaignRun()
        try:
            await run.submit_checkpoint(campaign_run_id, decision={"action": "approve"})
        except CheckpointNotAwaiting:
            return  # already resumed/advanced (idempotent re-fire)
        await run.run_to_completion(campaign_run_id)


class NoopReviewDispositionEmitter:
    """The M13.2 disposition-emit seam, as a no-op (M13.1). Until M13.2 supplies the
    ``DispositionStore``-backed emitter, review actions are still recorded as ``review_action`` rows
    (the audit M13.2 reads/mirrors), so no disposition is lost while this is a no-op."""

    async def on_review_action(
        self,
        outcome: ReviewActionOutcome,
        *,
        account_entity_id: EntityId,
        contact_entity_id: EntityId | None,
        campaign_run_id: CampaignRunId,
        actor: str,
    ) -> None:
        return None


def build_review_account_resolver(
    *, conn_factory: ConnFactory = connection
) -> ReviewAccountResolver:
    """Resolve the M12-ready accounts (DONE + CONTACTS_COMPLETE) for the REVIEW phase — the
    readiness reader *without* the review-finalized gate (which would be circular: no session is
    finalized when REVIEW opens them)."""
    reader = DurableHandoffReadinessReader(conn_factory=conn_factory)

    async def resolve(ctx: PhaseContext) -> Sequence[AccountSpec]:
        ready = await reader.ready_accounts(
            campaign_run_id=ctx.campaign_run_id, client_id=ctx.client_id
        )
        return [
            AccountSpec(
                entity_id=r.account_entity_id, tier=r.tier or "top", tenant_id=ctx.client_id
            )
            for r in ready
        ]

    return resolve


def build_review_surface(
    *,
    conn_factory: ConnFactory = connection,
    session_factory: ConnFactory = transaction,
    campaign_run: CampaignRun | None = None,
    annotation_reader: VerificationAnnotationReader | None = None,
    disposition_emitter: ReviewDispositionEmitter | None = None,
) -> ReviewSurfaceImpl:
    """Construct the production :class:`~clue_research.review.ReviewSurfaceImpl` — the projection
    over the durable annotation reader, the campaign resume hook, and the M13.2 disposition emitter.

    ``disposition_emitter`` defaults to the :class:`NoopReviewDispositionEmitter` (M13.1
    standalone — review actions are still durably recorded as ``review_action`` rows); the
    integration root passes the concrete emitter (``build_review_disposition_emitter``) so every
    action is mirrored into a ``disposition`` at the moment it occurs (the M13.1 ↔ M13.2 seam)."""
    reader = annotation_reader or DbVerificationAnnotationReader(conn_factory=conn_factory)
    return ReviewSurfaceImpl(
        projector=ReviewProjector(annotation_reader=reader),
        session_factory=session_factory,
        resume_hook=CampaignRunResumeHook(campaign_run=campaign_run),
        disposition_emitter=disposition_emitter or NoopReviewDispositionEmitter(),
    )


def build_review_phase_handler(
    *,
    account_resolver: ReviewAccountResolver | None = None,
    surface: ReviewSurfaceImpl | None = None,
    conn_factory: ConnFactory = connection,
    session_factory: ConnFactory = transaction,
    campaign_run: CampaignRun | None = None,
    disposition_emitter: ReviewDispositionEmitter | None = None,
) -> ReviewPhaseHandler:
    """Construct the ``CampaignPhase.REVIEW`` handler with the concrete seams (mirrors
    ``build_verification_phase_handler``). ``disposition_emitter`` is threaded into the default
    surface (None → the M13.1 no-op); the integration root passes M13.2's concrete emitter."""
    return ReviewPhaseHandler(
        account_resolver=account_resolver
        or build_review_account_resolver(conn_factory=conn_factory),
        surface=surface
        or build_review_surface(
            conn_factory=conn_factory,
            session_factory=session_factory,
            campaign_run=campaign_run,
            disposition_emitter=disposition_emitter,
        ),
    )


def register_review_phase_handler(
    *,
    account_resolver: ReviewAccountResolver | None = None,
    surface: ReviewSurfaceImpl | None = None,
    conn_factory: ConnFactory = connection,
    session_factory: ConnFactory = transaction,
    campaign_run: CampaignRun | None = None,
    disposition_emitter: ReviewDispositionEmitter | None = None,
) -> ReviewPhaseHandler:
    """Build + register the REVIEW handler into the M7.3 process-default ``PhaseHandlerRegistry``
    (the api-root binder; mirrors ``register_verification_phase_handler``). Pass
    ``disposition_emitter`` to mirror review actions into dispositions (the M13.2 join); see
    ``api.review_feedback_wiring.register_reviewed_phase_handler`` for the production binder."""
    handler = build_review_phase_handler(
        account_resolver=account_resolver,
        surface=surface,
        conn_factory=conn_factory,
        session_factory=session_factory,
        campaign_run=campaign_run,
        disposition_emitter=disposition_emitter,
    )
    register_phase_handler(handler)
    return handler


# Static-time conformance: the durable reader satisfies the core annotation-reader seam.
_READER_IS_AN_ANNOTATION_READER: type[VerificationAnnotationReader] = DbVerificationAnnotationReader
