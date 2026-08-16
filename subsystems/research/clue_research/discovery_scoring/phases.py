"""M6's project-run phase handlers (M6.1+M6.2 → DISCOVERY; M6.3 → SCORING; M6.4 → TIER_CHECKPOINT).

The frozen ``PhaseHandler`` seam (Beat-0, ``core.execution``) lets the M7 state machine drive a
phase without importing this package. ``DiscoveryPhaseHandler`` is the integrated DISCOVERY phase:
it loads the campaign's ICP spec, runs mode-M1 :func:`discover` (M6.1), and passes each grounded
candidate through the :func:`admit` gate (M6.2) — discovery proposes, the gate admits/reviews/drops
and stamps discovery-provenance. ``ScoringPhaseHandler`` (M6.3) scores every admitted account.
``TierCheckpointPhaseHandler`` (M6.4) tiers the scores and is the durable human gate: it suspends
via ``PhaseResult(status=PAUSED)`` with a review payload + pre-run cost estimate, and resumes (into
``deep``) only on an approved decision threaded back through the phase ``params``. Each persists the
per-(source) yield / decision by reference (never blobs). The concrete handlers are constructed +
registered into ``ProjectRun`` at the ``api`` composition root (Beat-0); nothing here imports
``durable``.

Idempotency (M7 replay): every phase ``run_id`` is **derived deterministically** from the campaign
run + ICP version (+ the cutoff version, for the checkpoint), so a re-entry reuses it and its
effects are committed at most once — discovery re-admission, score writes, and tier writes all
no-op on replay, and the checkpoint re-presents byte-identical state.
"""

from __future__ import annotations

from decimal import Decimal
from typing import cast
from uuid import NAMESPACE_URL, uuid5

from pydantic import JsonValue
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    ICPSpec,
    LLMGateway,
    PhaseContext,
    PhaseResult,
    PhaseStatus,
    PreSpendGate,
    ProjectPhase,
    ProjectRunId,
    RunId,
    SealedDiscoveryAccountReader,
    SealedDiscoveryAccounts,
)
from clue_db import ConnFactory, transaction
from clue_research.claimstore import ALL_WORKSPACES, record_run_lineage
from clue_research.discovery_scoring.coverage import (
    DEFAULT_COVERAGE_CONFIG,
    CoverageConfig,
    coverage_report,
)
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
from clue_research.discovery_scoring.tiering import (
    DEFAULT_TIERING_CONFIG,
    AccountTierView,
    CheckpointAction,
    CheckpointDecision,
    CheckpointReview,
    CheckpointStatus,
    DiscoveryCriteriaCheckpointReview,
    DiscoverySelectionDisposition,
    DiscoverySelectionPolicy,
    ScoringMode,
    TieringConfig,
    assign_tiers,
    cutoff_version,
    estimate_cost,
    load_discovery_criteria_selection,
    load_score_views,
    persist_discovery_selection_tier,
    persist_tier,
    selection_decision_version,
    tier_distribution,
)
from clue_research.icp.compiler import compile_field_plan
from clue_research.icp.rubric import RubricValidationError, rubric_from_slot, validate_rubric
from clue_research.icp.spec import get_icp_version
from clue_research.sources import DEFAULT_CONFIDENCE_THRESHOLDS, ConfidenceThresholds
from clue_research.sources.source_yield import record_source_yield


def discovery_run_id(ctx: PhaseContext) -> RunId:
    """A deterministic discovery run id per ``(project_run, icp_key, icp_version)`` — stable across
    M7 phase replays (so the gate's idempotency holds) and distinct per ICP (D5 multi-ICP)."""
    return project_discovery_run_id(
        project_run_id=ctx.project_run_id,
        icp_key=ctx.icp_key,
        icp_version=ctx.icp_version,
    )


def project_discovery_run_id(
    *,
    project_run_id: ProjectRunId,
    icp_key: str,
    icp_version: int,
) -> RunId:
    """The shared discovery identity for callers admitting imports before the phase is driven."""

    return RunId(
        uuid5(
            NAMESPACE_URL,
            f"clue:discovery-run:{project_run_id}:{icp_key}:{icp_version}",
        )
    )


class DiscoveryPhaseHandler:
    """The DISCOVERY ``PhaseHandler`` (M6): ``discover`` (M6.1) → ``admit`` (M6.2) per candidate."""

    phase = ProjectPhase.DISCOVERY

    def __init__(
        self,
        *,
        channels: ChannelRegistry,
        gateway: LLMGateway | None = None,
        config: DiscoveryConfig = DEFAULT_DISCOVERY_CONFIG,
        redis: Redis | None = None,
        existence: ExistenceCheck = DEFAULT_EXISTENCE_CHECK,
        session_factory: ConnFactory = transaction,
    ) -> None:
        self._channels = channels
        self._gateway = gateway
        self._config = config
        self._redis = redis
        self._existence = existence
        self._session_factory = session_factory

    async def run(self, ctx: PhaseContext) -> PhaseResult:
        run_id = discovery_run_id(ctx)
        async with self._session_factory() as conn:
            spec = await get_icp_version(conn, ctx.workspace_id, ctx.icp_key, ctx.icp_version)
            if spec is None:
                return PhaseResult(
                    status=PhaseStatus.FAILED,
                    payload={
                        "error": (
                            f"no ICP spec for ({ctx.workspace_id!r}, {ctx.icp_key!r}, "
                            f"v{ctx.icp_version})"
                        )
                    },
                )
            # FI-2 P2 (spec §3): attribute the run to its project once, in the same transaction as
            # the admission writes below — never per claim. Idempotent, so an M7 replay (which
            # re-derives the same run id) re-registers harmlessly.
            await record_run_lineage(
                conn,
                run_id=run_id,
                workspace_id=ctx.workspace_id,
                kind="discovery",
                project_id=ctx.project_id,
                project_run_id=ctx.project_run_id,
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
                        workspace_id=ctx.workspace_id,
                        # FI-2 P1 (spec §2): an account discovered *for this project* joins its
                        # target list in the admission's own savepoint — so a rolled-back candidate
                        # leaves neither a provenance claim nor a membership.
                        project_id=ctx.project_id,
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
            # The run-level facts coverage needs to be queryable by run_id alone — the stopping
            # reason and the admitted-vs-seen counts (M6.2) — are denormalised onto each discovery
            # row (they agree across rows); M6.5 reads them off the latest row per channel.
            for channel_yield in result.per_channel_yield:
                await record_source_yield(
                    conn,
                    workspace_id=ctx.workspace_id,
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
                        "stopping_reason": result.stopping_reason.value,
                        "admitted": admitted,
                        "needs_review": needs_review,
                        "rejected": rejected,
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
    """A deterministic Pass-A scoring run id per ``(project_run, icp_key, icp_version)`` — stable
    across M7 phase replays (so the waterfall + score-write idempotency hold) and distinct per ICP
    *version* (so a new rubric version re-scores). Distinct namespace from the discovery run id."""
    return RunId(
        uuid5(
            NAMESPACE_URL,
            f"clue:scoring-run:{ctx.project_run_id}:{ctx.icp_key}:{ctx.icp_version}",
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
    ``ProjectRun`` at the ``api`` composition root (Beat-0); nothing here imports ``durable``.

    Idempotency (M7 replay): the scoring ``run_id`` is derived deterministically, so a re-entered
    SCORING phase reuses it — the waterfall and the score write both no-op on replay, and
    ``accounts_processed`` is stable.
    """

    phase = ProjectPhase.SCORING

    def __init__(
        self,
        *,
        config: ScoringConfig = DEFAULT_SCORING_CONFIG,
        thresholds: ConfidenceThresholds = DEFAULT_CONFIDENCE_THRESHOLDS,
        session_factory: ConnFactory = transaction,
        pre_spend_gate: PreSpendGate | None = None,
        sealed_account_reader: SealedDiscoveryAccountReader | None = None,
    ) -> None:
        self._config = config
        self._thresholds = thresholds
        self._session_factory = session_factory
        self._pre_spend_gate = pre_spend_gate
        self._sealed_account_reader = sealed_account_reader

    async def run(self, ctx: PhaseContext) -> PhaseResult:
        discovery_run = discovery_run_id(ctx)
        scoring_run = _scoring_run_id(ctx)
        sealed_accounts = (
            await self._sealed_account_reader.read(
                workspace_id=ctx.workspace_id,
                project_run_id=ctx.project_run_id,
                icp_key=ctx.icp_key,
                icp_version=ctx.icp_version,
            )
            if self._sealed_account_reader is not None
            else None
        )
        async with self._session_factory() as conn:
            spec = await get_icp_version(conn, ctx.workspace_id, ctx.icp_key, ctx.icp_version)
            if spec is None:
                return PhaseResult(
                    status=PhaseStatus.FAILED,
                    payload={
                        "error": (
                            f"no ICP spec for ({ctx.workspace_id!r}, {ctx.icp_key!r}, "
                            f"v{ctx.icp_version})"
                        )
                    },
                )
            try:
                selection_policy = DiscoverySelectionPolicy.from_slot(spec.discovery_strategy)
            except ValueError as exc:
                return PhaseResult(
                    status=PhaseStatus.FAILED,
                    payload={"error": f"invalid discovery selection policy: {exc}"},
                )
            if selection_policy.scoring_mode is ScoringMode.DISABLED:
                if sealed_accounts is None:
                    return PhaseResult(
                        status=PhaseStatus.FAILED,
                        payload={
                            "error": (
                                "discovery-criteria selection requires the exact current sealed "
                                "discovery generation"
                            )
                        },
                    )
                try:
                    selection = await load_discovery_criteria_selection(
                        conn,
                        sealed=sealed_accounts,
                        workspace_id=ctx.workspace_id,
                        policy=selection_policy,
                    )
                except ValueError as exc:
                    return PhaseResult(
                        status=PhaseStatus.FAILED,
                        payload={"error": f"invalid sealed discovery selection: {exc}"},
                    )
                return PhaseResult(
                    status=PhaseStatus.COMPLETED,
                    accounts_processed=len(selection.accounts),
                    cost_cents=Decimal(0),
                    payload={
                        "scoring_mode": selection_policy.scoring_mode.value,
                        "selection_mode": selection_policy.selection_mode.value,
                        "selection_policy_version": selection.policy_version,
                        "discovery_batch_id": str(sealed_accounts.discovery_batch_id),
                        "discovery_seal_sha256": sealed_accounts.seal_sha256,
                        "account_manifest_ref": sealed_accounts.account_manifest_ref,
                        "claim_manifest_ref": sealed_accounts.claim_manifest_ref,
                        "selection_distribution": cast(
                            "dict[str, JsonValue]", selection.distribution
                        ),
                        "accounts": [row.model_dump(mode="json") for row in selection.accounts],
                        "numeric_scores_written": 0,
                        "external_calls": 0,
                    },
                )
            rubric = rubric_from_slot(spec.scoring_rubric)
            if rubric is None:
                # No rubric: cannot score; surface it, never fabricate a default (empty is correct).
                return PhaseResult(
                    status=PhaseStatus.FAILED,
                    payload={
                        "error": (
                            f"ICP spec ({ctx.workspace_id!r}, {ctx.icp_key!r}, v{ctx.icp_version}) "
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
            account_ids = (
                sealed_accounts.account_ids
                if sealed_accounts is not None
                else await admitted_account_ids(conn, run_id=discovery_run, scope=ALL_WORKSPACES)
            )

            # FI-2 P2 (spec §3): one attribution row for the scoring run, in the same transaction
            # as the score writes below. Idempotent, so an M7 replay re-registers harmlessly.
            await record_run_lineage(
                conn,
                run_id=scoring_run,
                workspace_id=ctx.workspace_id,
                kind="scoring",
                project_id=ctx.project_id,
                project_run_id=ctx.project_run_id,
            )

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
                        workspace_id=ctx.workspace_id,
                        icp_key=ctx.icp_key,
                        icp_version=ctx.icp_version,
                        project_run_id=ctx.project_run_id,
                        product_id=spec.product_id,
                        budget_envelope=ctx.budget_cap_cents,
                        thresholds=self._thresholds,
                        pre_spend_gate=self._pre_spend_gate,
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
                    workspace_id=ctx.workspace_id,
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
                "discovery_batch_id": (
                    str(sealed_accounts.discovery_batch_id) if sealed_accounts is not None else None
                ),
                "discovery_batch_seal_ref": (
                    sealed_accounts.seal_sha256 if sealed_accounts is not None else None
                ),
            },
        )


def _tier_checkpoint_run_id(ctx: PhaseContext, cversion: str) -> RunId:
    """A deterministic tier-checkpoint run id per ``(project_run, icp_key, icp_version,
    cutoff_version)``. Encoding the cutoff version is what makes the tier write idempotent on
    ``(account, cutoff_version)``: a re-entered checkpoint with the *same* approved cutoffs reuses
    it (the tier write no-ops), while a human cutoff adjustment yields a *new* run id whose tier
    write supersedes the prior tier (one live winner per ICP). Distinct ns from disc/scoring."""
    return RunId(
        uuid5(
            NAMESPACE_URL,
            f"clue:tier-checkpoint:{ctx.project_run_id}:{ctx.icp_key}:{ctx.icp_version}:{cversion}",
        )
    )


class TierCheckpointPhaseHandler:
    """The TIER_CHECKPOINT ``PhaseHandler`` (M6.4): tier the Pass-A scores and run the durable human
    gate that makes the two-pass unit economics legible *before* any Pass-B spend.

    Re-entrant by design (the secure-input pause/resume pattern, substrate §10): the M7 state
    machine invokes :meth:`run` with no decision to obtain the durable suspension (``PAUSED`` + the
    review payload — provisional fit/intent with working evidence links, the proposed cutoffs, the
    tier distribution, and the pre-run cost estimate), then re-invokes it with the client's decision
    in ``ctx.params`` (under ``checkpoint_decision``). On ``approve`` (within the effective budget
    cap) the handler persists the per-account tier decision and returns ``COMPLETED`` (the run
    advances to ``deep``); on ``pause``, an unset action, or a projected-spend-over-cap condition it
    stays ``PAUSED`` (a cutoff/budget adjustment re-tiers and re-estimates with **no** Pass-A
    re-spend, and an over-cap approve halts gracefully — to raise the cap or tighten cutoffs).

    Idempotency on ``(project_run, 'tier_checkpoint')`` (Doc C §4): the review is deterministic in
    (the stored scores × cutoffs × config), so crash re-entry re-presents identical state, and the
    tier write is idempotent on the cutoff-derived ``run_id``, so the resume action applies at most
    once. The durable suspend/resume primitive + the checkpoint record (``payload``) are M7's; this
    handler only implements the phase behaviour. Registered into ``ProjectRun`` at the ``api``
    composition root (Beat-0); nothing here imports ``durable``.
    """

    phase = ProjectPhase.TIER_CHECKPOINT

    def __init__(
        self,
        *,
        config: TieringConfig = DEFAULT_TIERING_CONFIG,
        coverage_config: CoverageConfig = DEFAULT_COVERAGE_CONFIG,
        session_factory: ConnFactory = transaction,
        sealed_account_reader: SealedDiscoveryAccountReader | None = None,
        enforce_budget: bool = True,
    ) -> None:
        self._config = config
        self._coverage_config = coverage_config
        self._session_factory = session_factory
        self._sealed_account_reader = sealed_account_reader
        # FI pilot budget-controls (ratified 2026-08-11), threaded from
        # ``Settings.budget_controls_enabled`` at the composition root. False means a human
        # ``approve`` is honoured even when the projected Pass-B cost exceeds the effective cap: the
        # ruling is that nothing stops a *pre-approved* action on budget grounds, and this gate is
        # the most literal case of that — the person with the authority has just clicked approve.
        # The estimate is still computed and still travels in the review payload (recording and
        # legibility are unaffected); it simply no longer overrides the decision.
        self._enforce_budget = enforce_budget

    def _over_cap(self, estimated_cost_cents: Decimal, effective_cap: Decimal | None) -> bool:
        """Whether the projected Pass-B spend exceeds the effective cap *and* may stop the run."""

        if not self._enforce_budget:
            return False
        return effective_cap is not None and estimated_cost_cents > effective_cap

    async def _run_discovery_criteria_checkpoint(
        self,
        conn: AsyncConnection,
        *,
        ctx: PhaseContext,
        spec: ICPSpec,
        sealed: SealedDiscoveryAccounts,
        policy: DiscoverySelectionPolicy,
        decision: CheckpointDecision,
    ) -> PhaseResult:
        try:
            selection = await load_discovery_criteria_selection(
                conn,
                sealed=sealed,
                workspace_id=ctx.workspace_id,
                policy=policy,
            )
        except ValueError as exc:
            return PhaseResult(
                status=PhaseStatus.FAILED,
                payload={"error": f"invalid sealed discovery selection: {exc}"},
            )
        selected = {
            row.account_id: row
            for row in selection.accounts
            if row.disposition is DiscoverySelectionDisposition.SELECTED
        }
        approval_error = decision.approval_selection_error
        requested = decision.approved_account_ids
        if requested is None:
            effective_ids = tuple(sorted(selected, key=str))
        else:
            unknown = sorted(set(requested) - set(selected), key=str)
            if unknown:
                approval_error = (
                    "approved_account_ids contains accounts that are not selected by every "
                    "required discovery criterion"
                )
            effective_ids = tuple(value for value in requested if value in selected)

        if self._config.band_cents(policy.approved_tier) <= 0:
            return PhaseResult(
                status=PhaseStatus.FAILED,
                payload={
                    "error": (
                        f"approved discovery tier {policy.approved_tier!r} has no positive "
                        "Pass-B cost band"
                    )
                },
            )
        deep_distribution = {policy.approved_tier: len(effective_ids)}
        estimate = estimate_cost(deep_distribution, self._config).model_copy(
            update={"discovered_count": len(selection.accounts)}
        )
        effective_cap = (
            decision.budget_cap_cents
            if decision.budget_cap_cents is not None
            else ctx.budget_cap_cents
        )
        over_cap = self._over_cap(estimate.estimated_cost_cents, effective_cap)
        approved = (
            decision.action is CheckpointAction.APPROVE and approval_error is None and not over_cap
        )
        decision_version = selection_decision_version(
            policy_version=selection.policy_version,
            seal_sha256=sealed.seal_sha256,
            approved_account_ids=effective_ids,
        )

        tier_run: RunId | None = None
        tiered = replayed = errors = 0
        if approved:
            tier_run = _tier_checkpoint_run_id(ctx, decision_version)
            # FI-2 P2 (spec §3): attribute the tiering run before the per-account tier writes
            # below, in the same transaction. Idempotent under replay of the same decision.
            await record_run_lineage(
                conn,
                run_id=tier_run,
                workspace_id=ctx.workspace_id,
                kind="tiering",
                project_id=ctx.project_id,
                project_run_id=ctx.project_run_id,
            )
            for account_id in effective_ids:
                savepoint = await conn.begin_nested()
                try:
                    _, written = await persist_discovery_selection_tier(
                        conn,
                        view=selected[account_id],
                        tier=policy.approved_tier,
                        selection_policy_version=selection.policy_version,
                        decision_version=decision_version,
                        discovery_batch_id=str(sealed.discovery_batch_id),
                        discovery_seal_sha256=sealed.seal_sha256,
                        project_run_id=ctx.project_run_id,
                        run_id=tier_run,
                        workspace_id=ctx.workspace_id,
                        icp_key=ctx.icp_key,
                        icp_version=ctx.icp_version,
                        # FI-2 §6.4: stamp the project too, so this writer never lands in the
                        # unstamped class an absorbing write is allowed to take.
                        project_id=ctx.project_id,
                    )
                except Exception:  # noqa: BLE001 - isolate and make the gate retryable.
                    await savepoint.rollback()
                    errors += 1
                    continue
                await savepoint.commit()
                if written:
                    tiered += 1
                else:
                    replayed += 1

        coverage = await coverage_report(
            conn,
            run_id=discovery_run_id(ctx),
            spec=spec,
            config=self._coverage_config,
        )
        coverage_json: JsonValue = coverage.model_dump(mode="json") if coverage else None
        completed = approved and errors == 0
        status = CheckpointStatus.RESUMED if completed else CheckpointStatus.AWAITING
        review = DiscoveryCriteriaCheckpointReview(
            status=status,
            selection_policy_version=selection.policy_version,
            discovery_batch_id=str(sealed.discovery_batch_id),
            discovery_seal_sha256=sealed.seal_sha256,
            approved_tier=policy.approved_tier,
            selection_distribution=selection.distribution,
            accounts=selection.accounts,
            approval_candidate_account_ids=tuple(sorted(selected, key=str)),
            requested_approved_account_ids=requested,
            approval_selection_error=approval_error,
            estimate=estimate,
            cap_cents=effective_cap,
            projected_over_cap=over_cap,
            coverage=coverage_json,
        )
        payload: dict[str, JsonValue] = {
            "checkpoint_status": status.value,
            "decision_action": decision.action.value if decision.action else None,
            "decision_basis": "discovery_criteria",
            "scoring_mode": policy.scoring_mode.value,
            "selection_mode": policy.selection_mode.value,
            "selection_policy_version": selection.policy_version,
            "decision_version": decision_version,
            "discovery_batch_id": str(sealed.discovery_batch_id),
            "discovery_seal_sha256": sealed.seal_sha256,
            "selection_distribution": cast("dict[str, JsonValue]", selection.distribution),
            "approved_account_count": len(effective_ids),
            "approved_account_ids": [str(value) for value in effective_ids],
            "approval_selection_error": approval_error,
            "approved_tier": policy.approved_tier,
            "estimate": estimate.model_dump(mode="json"),
            "projected_over_cap": over_cap,
            "numeric_scores_written": 0,
            "coverage": coverage_json,
            "review": review.model_dump(mode="json"),
        }
        if approved:
            assert tier_run is not None
            payload["tier_checkpoint_run_id"] = str(tier_run)
            payload["tiered"] = tiered
            payload["replayed"] = replayed
            payload["errors"] = errors
        if completed:
            return PhaseResult(
                status=PhaseStatus.COMPLETED,
                accounts_processed=tiered + replayed,
                payload=payload,
            )
        return PhaseResult(status=PhaseStatus.PAUSED, payload=payload)

    async def run(self, ctx: PhaseContext) -> PhaseResult:
        scoring_run = _scoring_run_id(ctx)
        sealed_accounts = (
            await self._sealed_account_reader.read(
                workspace_id=ctx.workspace_id,
                project_run_id=ctx.project_run_id,
                icp_key=ctx.icp_key,
                icp_version=ctx.icp_version,
            )
            if self._sealed_account_reader is not None
            else None
        )
        async with self._session_factory() as conn:
            spec = await get_icp_version(conn, ctx.workspace_id, ctx.icp_key, ctx.icp_version)
            if spec is None:
                return PhaseResult(
                    status=PhaseStatus.FAILED,
                    payload={
                        "error": (
                            f"no ICP spec for ({ctx.workspace_id!r}, {ctx.icp_key!r}, "
                            f"v{ctx.icp_version})"
                        )
                    },
                )
            try:
                selection_policy = DiscoverySelectionPolicy.from_slot(spec.discovery_strategy)
            except ValueError as exc:
                return PhaseResult(
                    status=PhaseStatus.FAILED,
                    payload={"error": f"invalid discovery selection policy: {exc}"},
                )
            decision = CheckpointDecision.from_params(ctx.params)
            if selection_policy.scoring_mode is ScoringMode.DISABLED:
                if sealed_accounts is None:
                    return PhaseResult(
                        status=PhaseStatus.FAILED,
                        payload={
                            "error": (
                                "discovery-criteria checkpoint requires the exact current sealed "
                                "discovery generation"
                            )
                        },
                    )
                return await self._run_discovery_criteria_checkpoint(
                    conn,
                    ctx=ctx,
                    spec=spec,
                    sealed=sealed_accounts,
                    policy=selection_policy,
                    decision=decision,
                )
            rubric = rubric_from_slot(spec.scoring_rubric)
            if rubric is None:
                # No rubric → no cutoffs and no scores to tier; surface it, never fabricate cutoffs.
                return PhaseResult(
                    status=PhaseStatus.FAILED,
                    payload={
                        "error": (
                            f"ICP spec ({ctx.workspace_id!r}, {ctx.icp_key!r}, v{ctx.icp_version}) "
                            "carries no scoring rubric"
                        )
                    },
                )

            # Cutoffs are the client's adjustment if present, else the rubric's proposal (D7:
            # cutoffs are data; adjusting them re-tiers without touching the rubric version).
            cutoffs = decision.cutoffs if decision.cutoffs is not None else rubric.tier_cutoffs
            cversion = cutoff_version(cutoffs)

            views = await load_score_views(
                conn, scoring_run=scoring_run, workspace_id=ctx.workspace_id
            )
            assignments = assign_tiers(views, cutoffs)
            distribution = tier_distribution(assignments, cutoffs)
            estimate = estimate_cost(distribution, self._config)

            # The effective cap honours a raise/lower in the decision over the run's standing cap.
            effective_cap = (
                decision.budget_cap_cents
                if decision.budget_cap_cents is not None
                else ctx.budget_cap_cents
            )
            over_cap = self._over_cap(estimate.estimated_cost_cents, effective_cap)

            rows = tuple(
                AccountTierView.from_view(view, assignments[view.account_id]) for view in views
            )

            # Approve within cap → persist the decision + advance to `deep`. Anything else (no/pause
            # action, or a projected-over-cap approve) → stay durably suspended (graceful stop).
            approved = decision.action is CheckpointAction.APPROVE and not over_cap
            tier_run: RunId | None = None
            tiered = replayed = errors = 0
            if approved:
                tier_run = _tier_checkpoint_run_id(ctx, cversion)
                # FI-2 P2 (spec §3): attribute the tiering run before the per-account tier writes
                # below, in the same transaction. A resume with the same approved cutoffs re-derives
                # the same run id and re-registers harmlessly.
                await record_run_lineage(
                    conn,
                    run_id=tier_run,
                    workspace_id=ctx.workspace_id,
                    kind="tiering",
                    project_id=ctx.project_id,
                    project_run_id=ctx.project_run_id,
                )
                for view in views:
                    savepoint = await conn.begin_nested()
                    try:
                        _, written = await persist_tier(
                            conn,
                            view=view,
                            tier=assignments[view.account_id],
                            cutoff_version=cversion,
                            run_id=tier_run,
                            workspace_id=ctx.workspace_id,
                            icp_key=ctx.icp_key,
                            icp_version=ctx.icp_version,
                            # FI-2 §6.4: pin the tier to the approving project so a second
                            # project's checkpoint never supersedes this one's tier.
                            project_id=ctx.project_id,
                            # The account-research launch boundary consumes the exact run-local
                            # selection authority, not a mutable project-wide tier.
                            project_run_id=ctx.project_run_id,
                        )
                    except Exception:  # noqa: BLE001 — isolate one account; continue the approve.
                        # Commit is outside the try so a commit failure is never double-rolled-back.
                        await savepoint.rollback()
                        errors += 1
                        continue
                    await savepoint.commit()
                    if written:
                        tiered += 1
                    else:
                        replayed += 1

            # M6.5: surface the discovery-run coverage estimate through the checkpoint payload (the
            # M6.4 hook — the client sees "~X–Y% found via these channels" + the channels not yet
            # searched alongside the tier/cost review). Read-only over the discovery telemetry the
            # DISCOVERY phase wrote; ``None`` when that run has no telemetry / no source registry is
            # seeded, so the coverage placeholder stays unpopulated — it never fails the gate.
            coverage = await coverage_report(
                conn,
                run_id=discovery_run_id(ctx),
                spec=spec,
                config=self._coverage_config,
            )
            coverage_json: JsonValue = (
                coverage.model_dump(mode="json") if coverage is not None else None
            )

            status = CheckpointStatus.RESUMED if approved else CheckpointStatus.AWAITING
            review = CheckpointReview(
                status=status,
                proposed_cutoffs=cutoffs,
                cutoff_version=cversion,
                tier_distribution=distribution,
                accounts=rows,
                estimate=estimate,
                cap_cents=effective_cap,
                projected_over_cap=over_cap,
                scored_count=len(views),
                coverage=coverage_json,
            )
            payload: dict[str, JsonValue] = {
                "checkpoint_status": status.value,
                "decision_action": decision.action.value if decision.action else None,
                "cutoff_version": cversion,
                "tier_distribution": cast("dict[str, JsonValue]", distribution),
                "estimate": estimate.model_dump(mode="json"),
                "projected_over_cap": over_cap,
                "scored_count": len(views),
                "coverage": coverage_json,
                "review": review.model_dump(mode="json"),
            }
            if approved:
                assert tier_run is not None
                payload["tier_checkpoint_run_id"] = str(tier_run)
                payload["tiered"] = tiered
                payload["replayed"] = replayed
                payload["errors"] = errors
                return PhaseResult(
                    status=PhaseStatus.COMPLETED,
                    accounts_processed=tiered + replayed,
                    payload=payload,
                )
            return PhaseResult(status=PhaseStatus.PAUSED, payload=payload)


__all__ = [
    "DiscoveryPhaseHandler",
    "ScoringPhaseHandler",
    "TierCheckpointPhaseHandler",
    "discovery_run_id",
    "project_discovery_run_id",
]
