"""The ``ProjectPhase.REVIEW`` composition root (M13.1) — wires the concrete seams.

``api`` is the import-linter-exempt seam, so it may import both the otherwise-independent ``review``
package and the ``verification``/``compliance``/``durable`` packages whose data the review surface
displays / whose state machine it resumes. This module assembles:

* :class:`DbVerificationAnnotationReader` — the production
  :class:`~clue_core.VerificationAnnotationReader` over the ``faithfulness_verdict``
  (M9.3), ``use_decision`` (M10.3), and ``conflict_flag`` (M9.2) side tables. Faithfulness reads go
  through the claimstore's shared A/Q attribution seam; the other two remain composition-root SQL;
* :class:`ProjectRunResumeHook` — the ``finalize → resume`` seam over
  ``ProjectRun.submit_checkpoint`` (``review`` may not import ``durable``);
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
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.fleet_wiring import enqueue_run_drive
from clue_api.handoff_wiring import DurableHandoffReadinessReader
from clue_api.project_execution_router import ProjectExecutionRouter
from clue_api.review.handler import ReviewAccountResolver, ReviewPhaseHandler
from clue_core import (
    ClaimId,
    EntityId,
    PhaseContext,
    ProjectRunId,
    ReviewActionOutcome,
    UseDecision,
    UseReason,
)
from clue_core.review import (
    ClaimAnnotation,
    FieldConflict,
    ReviewDispositionEmitter,
    VerificationAnnotationReader,
)
from clue_db import ConnFactory, connection, transaction
from clue_research.claimstore import (
    WorkspaceScope,
    claims_by_ids,
    read_faithfulness_attributions,
)
from clue_research.durable import (
    AccountSpec,
    BudgetEngine,
    DbIdempotencyStore,
    DbProjectRunStore,
    get_project_run,
    register_phase_handler,
)
from clue_research.durable.project import CheckpointNotAwaiting, ProjectRun
from clue_research.review import (
    ReviewProjector,
    ReviewProjectScope,
    ReviewProjectScopeNotFound,
    ReviewSurfaceImpl,
)


class DbVerificationAnnotationReader:
    """The production :class:`~clue_core.VerificationAnnotationReader` over the M9/M10 side
    tables. Manages its own short read transaction (the seam carries no connection). It resolves
    the requested ids through the tenant-scoped claim store first; side-table rows can therefore
    never manufacture visibility for an unknown, superseded, expired, or cross-tenant claim."""

    def __init__(self, *, conn_factory: ConnFactory = connection) -> None:
        self._conn_factory = conn_factory

    async def annotations_for_claims(
        self, *, claim_ids: Sequence[ClaimId], workspace_id: str
    ) -> dict[ClaimId, ClaimAnnotation]:
        if not claim_ids:
            return {}
        async with self._conn_factory() as conn:
            visible_claims = await claims_by_ids(
                conn,
                claim_ids,
                scope=WorkspaceScope.for_workspace(workspace_id),
            )
            if not visible_claims:
                return {}
            actual_claims = tuple(visible_claims.values())
            faith_map = await read_faithfulness_attributions(conn, actual_claims)
            ids = [str(claim.id) for claim in actual_claims]
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
                faithfulness_verdict=f.verdict if f is not None else None,
                faithfulness_score=f.score if f is not None else None,
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
        self, *, account_entity_id: EntityId, workspace_id: str
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


class DurableReviewProjectScopeReader:
    """Resolve the exact product pinned by the review session's owning project run."""

    async def read_scope(
        self,
        conn: AsyncConnection,
        *,
        project_run_id: ProjectRunId,
        workspace_id: str,
    ) -> ReviewProjectScope:
        run = await get_project_run(conn, project_run_id)
        if run is None or run.workspace_id != workspace_id:
            raise ReviewProjectScopeNotFound(str(project_run_id))
        return ReviewProjectScope(product_id=run.product_id)


def _default_resume_run() -> ProjectRun:
    """The fleet-parity ``ProjectRun`` the resume hook drives when none is injected — the shared M7
    store + the M7.4 exactly-once ledger + a budget engine, exactly as
    :func:`~clue_api.fleet_wiring.build_fleet_run_driver` constructs the worker's driver. Closes the
    ``[B1×M13.2]`` gap: the prior bare ``ProjectRun()`` resumed with **no** ledger/budget, so a
    resumed phase finalized off the checkpoint-only path (no exactly-once charge record) and
    ``pre_run_estimate``/``burn_down`` at resume raised ``BudgetEngineNotConfigured``."""
    return ProjectRun(
        store=DbProjectRunStore(), budget_engine=BudgetEngine(), ledger=DbIdempotencyStore()
    )


class ProjectRunResumeHook:
    """The ``finalize → resume`` seam (M13.1): resumes the paused campaign by submitting the REVIEW
    checkpoint and offering the owning driver fresh work. ``review`` may not import ``durable``,
    so the project machine is injected here. Idempotent — a re-fire after the run has already
    advanced is a no-op (``CheckpointNotAwaiting`` is swallowed).

    The default driver is now the fleet-parity :func:`_default_resume_run` (shared store + ledger +
    budget engine), so checkpoint finalization writes the same durable phase-ledger record the
    detached worker's driver does (``[B1×M13.2]``). C5.3 then routes the fresh offer through
    :func:`~clue_api.fleet_wiring.enqueue_run_drive`: a Recipe-#1-owned run resumes its graph;
    an unowned run resumes the legacy drive task. The injectable ``project_run`` seam remains for
    tests and alternate composition, but no caller races the detached driver in-process."""

    def __init__(
        self,
        *,
        project_run: ProjectRun | None = None,
        project_execution_router: ProjectExecutionRouter | None = None,
    ) -> None:
        self._run = project_run
        self._project_execution_router = project_execution_router

    async def resume_review(self, project_run_id: ProjectRunId) -> None:
        run = self._run if self._run is not None else _default_resume_run()
        try:
            await run.submit_checkpoint(project_run_id, decision={"action": "approve"})
        except CheckpointNotAwaiting:
            return  # already resumed/advanced (idempotent re-fire)
        routed = (
            await self._project_execution_router.resume_owned(project_run_id, actor="human")
            if self._project_execution_router is not None
            else False
        )
        if not routed:
            await enqueue_run_drive(project_run_id)


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
        project_run_id: ProjectRunId,
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
            project_run_id=ctx.project_run_id, workspace_id=ctx.workspace_id
        )
        return [
            AccountSpec(
                entity_id=r.account_entity_id, tier=r.tier or "top", workspace_id=ctx.workspace_id
            )
            for r in ready
        ]

    return resolve


def build_review_surface(
    *,
    conn_factory: ConnFactory = connection,
    session_factory: ConnFactory = transaction,
    project_run: ProjectRun | None = None,
    annotation_reader: VerificationAnnotationReader | None = None,
    disposition_emitter: ReviewDispositionEmitter | None = None,
    project_execution_router: ProjectExecutionRouter | None = None,
) -> ReviewSurfaceImpl:
    """Construct the production :class:`~clue_research.review.ReviewSurfaceImpl` — the projection
    over the durable annotation reader, the campaign resume hook, and the M13.2 disposition emitter.

    ``disposition_emitter`` defaults to the :class:`NoopReviewDispositionEmitter` (M13.1
    standalone — review actions are still durably recorded as ``review_action`` rows); the
    integration root passes the concrete emitter (``build_review_disposition_emitter``) so every
    action is mirrored into a ``disposition`` at the moment it occurs (the M13.1 ↔ M13.2 seam)."""
    reader = annotation_reader or DbVerificationAnnotationReader(conn_factory=conn_factory)
    return ReviewSurfaceImpl(
        projector=ReviewProjector(
            annotation_reader=reader,
            project_scope_reader=DurableReviewProjectScopeReader(),
        ),
        session_factory=session_factory,
        resume_hook=ProjectRunResumeHook(
            project_run=project_run,
            project_execution_router=project_execution_router,
        ),
        disposition_emitter=disposition_emitter or NoopReviewDispositionEmitter(),
    )


def build_review_phase_handler(
    *,
    account_resolver: ReviewAccountResolver | None = None,
    surface: ReviewSurfaceImpl | None = None,
    conn_factory: ConnFactory = connection,
    session_factory: ConnFactory = transaction,
    project_run: ProjectRun | None = None,
    disposition_emitter: ReviewDispositionEmitter | None = None,
    project_execution_router: ProjectExecutionRouter | None = None,
) -> ReviewPhaseHandler:
    """Construct the ``ProjectPhase.REVIEW`` handler with the concrete seams (mirrors
    ``build_verification_phase_handler``). ``disposition_emitter`` is threaded into the default
    surface (None → the M13.1 no-op); the integration root passes M13.2's concrete emitter."""
    return ReviewPhaseHandler(
        account_resolver=account_resolver
        or build_review_account_resolver(conn_factory=conn_factory),
        surface=surface
        or build_review_surface(
            conn_factory=conn_factory,
            session_factory=session_factory,
            project_run=project_run,
            disposition_emitter=disposition_emitter,
            project_execution_router=project_execution_router,
        ),
    )


def register_review_phase_handler(
    *,
    account_resolver: ReviewAccountResolver | None = None,
    surface: ReviewSurfaceImpl | None = None,
    conn_factory: ConnFactory = connection,
    session_factory: ConnFactory = transaction,
    project_run: ProjectRun | None = None,
    disposition_emitter: ReviewDispositionEmitter | None = None,
    project_execution_router: ProjectExecutionRouter | None = None,
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
        project_run=project_run,
        disposition_emitter=disposition_emitter,
        project_execution_router=project_execution_router,
    )
    register_phase_handler(handler)
    return handler


# Static-time conformance: the durable reader satisfies the core annotation-reader seam.
_READER_IS_AN_ANNOTATION_READER: type[VerificationAnnotationReader] = DbVerificationAnnotationReader
