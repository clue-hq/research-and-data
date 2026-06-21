"""M6's campaign-run phase handlers (M6.1+M6.2 → the DISCOVERY phase; ENG-128 + ENG-133).

The frozen ``PhaseHandler`` seam (Beat-0, ``core.execution``) lets the M7 state machine drive a
phase without importing this package. ``DiscoveryPhaseHandler`` is the integrated DISCOVERY phase:
it loads the campaign's ICP spec, runs mode-M1 :func:`discover` (M6.1), and passes each grounded
candidate through the :func:`admit` gate (M6.2) — discovery proposes, the gate admits/reviews/drops
and stamps discovery-provenance. It persists the per-channel yield to the shared ``source_yield``
telemetry (the substrate M6.5 coverage reads) and returns a compact summary by reference (never
candidate blobs). The concrete handler is constructed + registered into ``CampaignRun`` at the
``api`` composition root (Beat-0); nothing here imports ``durable``.

Idempotency (M7 replay): the discovery ``run_id`` is **derived deterministically** from the campaign
run + ICP version, so a re-entered DISCOVERY phase reuses it and the gate's per-(entity, run)
provenance check makes re-admission a no-op — the phase commits its effects at most once.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.claimstore import ALL_TENANTS
from clue_research.core import (
    CampaignPhase,
    LLMGateway,
    PhaseContext,
    PhaseResult,
    PhaseStatus,
    RunId,
)
from clue_research.db import transaction
from clue_research.discovery_scoring.discovery import (
    DEFAULT_DISCOVERY_CONFIG,
    ChannelRegistry,
    DiscoveryConfig,
    discover,
)
from clue_research.discovery_scoring.gate import (
    DEFAULT_EXISTENCE_CHECK,
    AdmissionStatus,
    ExistenceCheck,
    admit,
)
from clue_research.discovery_scoring.scoring import (
    DEFAULT_SCORING_CONFIG,
    ScoringConfig,
    SourceYieldRow,
    admitted_account_ids,
    aggregate_yield,
    pass_a_fill_fields,
    score_account,
)
from clue_research.icp.compiler import compile_field_plan
from clue_research.icp.rubric import RubricValidationError, rubric_from_slot, validate_rubric
from clue_research.icp.spec import get_icp_version
from clue_research.sources import DEFAULT_CONFIDENCE_THRESHOLDS, ConfidenceThresholds
from clue_research.sources.source_yield import record_source_yield

# A session is an async context manager yielding a connection (db.transaction in production; a
# rollback-scoped connection in tests). Injected so the handler is testable without committing.
SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncConnection]]


def _discovery_run_id(ctx: PhaseContext) -> RunId:
    """A deterministic discovery run id per ``(campaign_run, icp_key, icp_version)`` — stable across
    M7 phase replays (so the gate's idempotency holds) and distinct per ICP (D5 multi-ICP)."""
    return RunId(
        uuid5(
            NAMESPACE_URL,
            f"clue:discovery-run:{ctx.campaign_run_id}:{ctx.icp_key}:{ctx.icp_version}",
        )
    )


class DiscoveryPhaseHandler:
    """The DISCOVERY ``PhaseHandler`` (M6): ``discover`` (M6.1) → ``admit`` (M6.2) per candidate."""

    phase = CampaignPhase.DISCOVERY

    def __init__(
        self,
        *,
        channels: ChannelRegistry,
        gateway: LLMGateway | None = None,
        config: DiscoveryConfig = DEFAULT_DISCOVERY_CONFIG,
        redis: Redis | None = None,
        existence: ExistenceCheck = DEFAULT_EXISTENCE_CHECK,
        session_factory: SessionFactory = transaction,
    ) -> None:
        self._channels = channels
        self._gateway = gateway
        self._config = config
        self._redis = redis
        self._existence = existence
        self._session_factory = session_factory

    async def run(self, ctx: PhaseContext) -> PhaseResult:
        run_id = _discovery_run_id(ctx)
        async with self._session_factory() as conn:
            spec = await get_icp_version(conn, ctx.client_id, ctx.icp_key, ctx.icp_version)
            if spec is None:
                return PhaseResult(
                    status=PhaseStatus.FAILED,
                    payload={
                        "error": (
                            f"no ICP spec for ({ctx.client_id!r}, {ctx.icp_key!r}, "
                            f"v{ctx.icp_version})"
                        )
                    },
                )
            result = await discover(
                spec=spec,
                run_id=run_id,
                channels=self._channels,
                gateway=self._gateway,
                config=self._config,
            )
            admitted = needs_review = rejected = errors = 0
            for candidate in result.candidates:
                savepoint = await conn.begin_nested()
                try:
                    outcome = await admit(
                        conn,
                        candidate,
                        run_id,
                        redis=self._redis,
                        existence=self._existence,
                    )
                except Exception:  # noqa: BLE001 — best-effort: isolate one candidate's fault
                    # Isolate a per-candidate write fault (e.g. a concurrent-admit collision with no
                    # Redis lock) — roll back just this candidate and continue the phase. The commit
                    # is outside the try so a commit failure is never double-rolled-back.
                    await savepoint.rollback()
                    errors += 1
                    continue
                await savepoint.commit()
                if outcome.status is AdmissionStatus.ADMITTED:
                    admitted += 1
                elif outcome.status is AdmissionStatus.NEEDS_REVIEW:
                    needs_review += 1
                else:
                    rejected += 1

            # Persist the per-channel discovery yield to the shared telemetry (keyed by run_id) the
            # coverage estimator (M6.5) and the learning loop (M13) read. Discovery produces no
            # field claims, so the candidate/error/query counts go in the free-form `disposition`
            # hook (not the claim-precision columns), with only the channel's spend in cost_cents.
            for channel_yield in result.per_channel_yield:
                await record_source_yield(
                    conn,
                    client_id=ctx.client_id,
                    icp_key=ctx.icp_key,
                    icp_version=ctx.icp_version,
                    source_key=channel_yield.source_key,
                    run_id=run_id,
                    cost_cents=channel_yield.cost_cents,
                    disposition={
                        "kind": "discovery",
                        "records_returned": channel_yield.records_returned,
                        "new_candidates": channel_yield.new_candidates,
                        "queries_issued": channel_yield.queries_issued,
                        "errors": channel_yield.errors,
                    },
                )

        return PhaseResult(
            status=PhaseStatus.COMPLETED,
            accounts_processed=admitted,
            cost_cents=result.total_cost_cents,
            payload={
                "discovery_run_id": str(run_id),
                "stopping_reason": result.stopping_reason.value,
                "candidates": result.candidate_count,
                "admitted": admitted,
                "needs_review": needs_review,
                "rejected": rejected,
                "errors": errors,
            },
        )


def _scoring_run_id(ctx: PhaseContext) -> RunId:
    """A deterministic Pass-A scoring run id per ``(campaign_run, icp_key, icp_version)`` — stable
    across M7 phase replays (so the waterfall + score-write idempotency hold) and distinct per ICP
    *version* (so a new rubric version re-scores). Distinct namespace from the discovery run id."""
    return RunId(
        uuid5(
            NAMESPACE_URL,
            f"clue:scoring-run:{ctx.campaign_run_id}:{ctx.icp_key}:{ctx.icp_version}",
        )
    )


class ScoringPhaseHandler:
    """The SCORING ``PhaseHandler`` (M6.3): cheap, deterministic-first Pass-A fit/intent scoring
    over every account admitted in this campaign's discovery run.

    Loads the campaign's pinned ICP spec + scoring rubric, validates the rubric against the compiled
    field plan, then for each admitted account (resolved from the discovery-provenance the gate
    wrote) fills the scoring proxies via the tier-1–3 waterfall and persists a decomposed, evidenced
    fit/intent score (M6.3 :func:`score_account`). Per-account work is isolated in a savepoint (one
    account's fault never aborts the phase). The per-source yield is persisted to the shared
    ``source_yield`` telemetry (the substrate M6.5 coverage + M13 reweighting read). Registered into
    ``CampaignRun`` at the ``api`` composition root (Beat-0); nothing here imports ``durable``.

    Idempotency (M7 replay): the scoring ``run_id`` is derived deterministically, so a re-entered
    SCORING phase reuses it — the waterfall and the score write both no-op on replay, and
    ``accounts_processed`` is stable.
    """

    phase = CampaignPhase.SCORING

    def __init__(
        self,
        *,
        config: ScoringConfig = DEFAULT_SCORING_CONFIG,
        thresholds: ConfidenceThresholds = DEFAULT_CONFIDENCE_THRESHOLDS,
        session_factory: SessionFactory = transaction,
    ) -> None:
        self._config = config
        self._thresholds = thresholds
        self._session_factory = session_factory

    async def run(self, ctx: PhaseContext) -> PhaseResult:
        discovery_run = _discovery_run_id(ctx)
        scoring_run = _scoring_run_id(ctx)
        async with self._session_factory() as conn:
            spec = await get_icp_version(conn, ctx.client_id, ctx.icp_key, ctx.icp_version)
            if spec is None:
                return PhaseResult(
                    status=PhaseStatus.FAILED,
                    payload={
                        "error": (
                            f"no ICP spec for ({ctx.client_id!r}, {ctx.icp_key!r}, "
                            f"v{ctx.icp_version})"
                        )
                    },
                )
            rubric = rubric_from_slot(spec.scoring_rubric)
            if rubric is None:
                # No rubric: cannot score; surface it, never fabricate a default (empty is correct).
                return PhaseResult(
                    status=PhaseStatus.FAILED,
                    payload={
                        "error": (
                            f"ICP spec ({ctx.client_id!r}, {ctx.icp_key!r}, v{ctx.icp_version}) "
                            "carries no scoring rubric"
                        )
                    },
                )
            field_plan = await compile_field_plan(conn, spec)
            try:
                validate_rubric(rubric, field_plan)
            except RubricValidationError as exc:
                return PhaseResult(status=PhaseStatus.FAILED, payload={"error": str(exc)})

            fill_fields = await pass_a_fill_fields(
                conn, field_plan, rubric, max_source_tier=self._config.max_source_tier
            )
            account_ids = await admitted_account_ids(conn, run_id=discovery_run, scope=ALL_TENANTS)

            scored = written = replayed = errors = 0
            total_cost = Decimal(0)
            yield_rows: list[SourceYieldRow] = []
            for account_id in account_ids:
                savepoint = await conn.begin_nested()
                try:
                    outcome = await score_account(
                        conn,
                        account_id,
                        rubric=rubric,
                        fill_fields=fill_fields,
                        run_id=scoring_run,
                        client_id=ctx.client_id,
                        icp_key=ctx.icp_key,
                        icp_version=ctx.icp_version,
                        budget_envelope=ctx.budget_cap_cents,
                        thresholds=self._thresholds,
                    )
                except Exception:  # noqa: BLE001 — isolate one account's fault; continue the phase.
                    # The commit is outside the try so a commit failure is never double-rolled-back.
                    await savepoint.rollback()
                    errors += 1
                    continue
                await savepoint.commit()
                scored += 1
                if outcome.written:
                    written += 1
                else:
                    replayed += 1
                total_cost += outcome.cost_cents
                yield_rows.extend(outcome.yield_steps)

            # Persist the run's per-(source, field_class) scoring yield to the shared telemetry the
            # coverage estimator (M6.5) and the learning loop (M13) read. Unlike discovery (no field
            # claims → disposition hook), scoring fills real claims, so the counts go in the
            # precision columns; the `disposition` tags the kind for the consumers.
            for row in aggregate_yield(yield_rows):
                await record_source_yield(
                    conn,
                    client_id=ctx.client_id,
                    icp_key=ctx.icp_key,
                    icp_version=ctx.icp_version,
                    source_key=row.source_key,
                    field_class=row.field_class,
                    run_id=scoring_run,
                    claims_total=row.claims_total,
                    fields_filled=row.fields_filled,
                    cost_cents=row.cost_cents,
                    disposition={"kind": "scoring"},
                )

        return PhaseResult(
            status=PhaseStatus.COMPLETED,
            accounts_processed=scored,
            cost_cents=total_cost,
            payload={
                "scoring_run_id": str(scoring_run),
                "rubric_version": rubric.version,
                "accounts": len(account_ids),
                "scored": scored,
                "written": written,
                "replayed": replayed,
                "errors": errors,
            },
        )


__all__ = ["DiscoveryPhaseHandler", "ScoringPhaseHandler"]
