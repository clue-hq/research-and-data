"""The ``ProjectPhase.DEEP`` phase handler (M8A.2) — drives the deep phase end-to-end.

The :class:`~clue_core.PhaseHandler` for ``ProjectPhase.DEEP``. Registering it at the api
composition root makes ``ProjectRun.advance()`` dispatch ``DEEP`` with zero new dispatch code — the
run no longer raises ``NoPhaseHandlerRegistered(DEEP)`` the moment it enters Pass B.

The handler is thin: it (1) resolves the human-approved high-tier account set via the injected
:data:`HighTierResolver`, (2) drives the M7 :class:`~clue_research.durable.AccountScheduler` with
the M8A.1 :class:`~clue_api.deep.AccountDeepOrchestrator` bound as the per-account
``run_one`` callback — so each account's ``account → committee → contact`` sequence runs inside the
scheduler's bounded-parallelism + per-entity single-flight slot — and (3) aggregates the
references-only per-account outcomes into a deep-complete manifest. **It owns the per-account
isolation policy the scheduler delegates** (the scheduler ``gather``\\ s and one account raising
would otherwise sink the batch): each account runs inside a try/except so a single failure marks
that ``account_run`` FAILED and the remaining accounts still process (coverage-confidence, not
all-or-nothing).

**Budget verdict mapping (the seam M8A.3 surfaces, this handler consumes):** an ``ACCOUNT``-scope
``DENY`` leaves a *partial* committee with coverage metadata — a COMPLETED-but-partial account, not
a failure; a ``RUN``-scope ``GRACEFUL_STOP`` returns ``PhaseResult(PAUSED)`` so the campaign
suspends cleanly and re-enters ``DEEP`` fresh on resume (the sub-phase markers skip the accounts
already done). M8A.3 records the ``budget_stop`` verdict on ``AccountDeepResult``;
:func:`_budget_stop` reads it and :meth:`DeepPhaseHandler.run` maps it to the phase status.

**Handoff payload (M8A.5, folded in here):** each account's references-only payload entry is the
M8A.5 ``DeepCompleteManifest`` — ``build_handoff_skeleton(result).manifest()`` — carrying the
account-run id, admitted member ids, coverage band, cost, and the per-section claim-id index
(``account`` / ``committee`` / ``contact:<id>``), **ids only, never a claim body** (substrate §5b);
the handler stamps the budget-derived ``status``. The rich ``(account, persona)`` join with
``profile_claims`` stays in-memory on the ``AccountHandoffSkeleton`` for M12.2 to recompute on read.

**Out of scope (later M8A issues):** the per-account sequence itself (M8A.1, injected); the fan-out
budget admission + ``DeepPhaseConfig`` (M8A.3, on the orchestrator); the exactly-once spend
transaction (M8A.4); injecting the concrete scheduler/orchestrator/resolver/gate + the AC-6/AC-4
enforcement (M8A.6 composition root).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from langgraph.checkpoint.base import BaseCheckpointSaver
from pydantic import JsonValue

from clue_api.deep.handoff_skeleton import build_handoff_skeleton
from clue_api.deep.orchestrator import (
    AccountDeepOrchestrator,
    AccountDeepResult,
    deep_account_run_id,
)
from clue_core import (
    BudgetVerdict,
    CostCents,
    PhaseContext,
    PhaseHandler,
    PhaseResult,
    PhaseStatus,
    ProjectPhase,
    ProjectRunId,
    RunId,
)
from clue_db import ConnFactory, transaction
from clue_research.durable import (
    AccountRunStatus,
    AccountScheduler,
    AccountSpec,
    RunOne,
    get_account_run,
    set_status,
)

# --- injected seams ----------------------------------------------------------

# Resolve the human-approved high-tier account set for this run (D-B). The concrete reads
# ``account.scoring.tier ≥ cutoff`` from the claim store keyed by the committed ``cutoff_version``
# carried in the COMPLETED tier-checkpoint payload (`ctx.params` / the checkpoint row), mapping each
# to a ``durable.AccountSpec``. Injected so this handler imports no claim store and stays
# unit-testable with a fake; the concrete is wired at the M8A.6 composition root.
HighTierResolver = Callable[[PhaseContext], Awaitable[Sequence[AccountSpec]]]

# Yields the LangGraph checkpointer the scheduler threads through ``run_accounts``. The M8A.1
# ``run_one`` path drives the three deep callables directly (not the M7 graph), so the checkpointer
# is unused on this path — but ``run_accounts`` still requires it, so the handler supplies one.
# Production wires ``durable.postgres_checkpointer``; tests inject an in-memory saver.
CheckpointerFactory = Callable[[], AbstractAsyncContextManager[BaseCheckpointSaver[Any]]]

# Finalize one *failed* ``account_run`` (the per-account isolation backstop): mark it FAILED **and
# return the cost it had already persisted** before the fault. The production binding
# (:func:`db_finalize_failed_account`) reads ``account_run.cost_cents`` then advances the status via
# ``durable.set_status`` in one transaction; tests inject a recorder. Separate from the
# orchestrator's own status writes so a *crash* (an exception the orchestrator never got to handle)
# still leaves a FAILED row rather than a stuck RUNNING one — and so the phase still counts the
# spend that crash incurred (an exception returns no result, so the only surviving cost signal is
# the row the orchestrator committed stage-by-stage). Under-counting here understates the burn-down.
FinalizeFailedAccount = Callable[[RunId], Awaitable[CostCents]]


@runtime_checkable
class DeepAccountScheduler(Protocol):
    """The slice of :class:`~clue_research.durable.AccountScheduler` this handler drives (M8A.2).

    Typed as a structural seam (conventions §2) so the handler is fake-testable without constructing
    the real scheduler's heavy :class:`~clue_research.durable.AccountResearchGraph`. The real
    scheduler satisfies it (asserted below). Only the ``run_one`` (M8A.0 callback) variant is used —
    the deep phase always supplies the M8A.1 per-account pipeline."""

    async def run_accounts(
        self,
        specs: Iterable[AccountSpec],
        *,
        project_run_id: ProjectRunId,
        checkpointer: BaseCheckpointSaver[Any],
        run_one: RunOne[Any],
    ) -> list[Any]: ...


@runtime_checkable
class DeepAccountOrchestrator(Protocol):
    """The per-account sequence the handler binds as the scheduler's ``run_one`` (M8A.2).

    Typed as a seam so the handler is fake-testable; the M8A.1
    :class:`~clue_api.deep.AccountDeepOrchestrator` satisfies it (asserted below)."""

    async def run_one(
        self, spec: AccountSpec, *, project_run_id: ProjectRunId
    ) -> AccountDeepResult: ...


def db_finalize_failed_account(
    *, session_factory: ConnFactory = transaction
) -> FinalizeFailedAccount:
    """The production :data:`FinalizeFailedAccount`: read the run's persisted cost, mark it FAILED,
    return that cost — all in one transaction.

    Reading the cost *before* advancing the status recovers whatever the orchestrator committed
    stage-by-stage before the fault (M7.1 ``account_run.cost_cents``), so a crash mid-account is not
    reported as zero-cost. Both steps are M7.1 repo calls; if the row was never created (a fault
    *before* the orchestrator's ``ensure``) the read returns ``None`` → ``0`` and the status UPDATE
    matches nothing — a harmless no-op."""

    async def _finalize(account_run_id: RunId) -> CostCents:
        async with session_factory() as conn:
            row = await get_account_run(conn, account_run_id)
            await set_status(conn, account_run_id, AccountRunStatus.FAILED)
            return row.cost_cents if row is not None else Decimal(0)

    return _finalize


# Module-default binding so the handler is usable without explicit wiring; the M8A.6 composition
# root may override it. Lazy — it only opens a session when an account actually fails.
_DB_FINALIZE_FAILED_ACCOUNT: FinalizeFailedAccount = db_finalize_failed_account()


# --- per-account outcome (internal aggregation unit) -------------------------


@dataclass(frozen=True, slots=True)
class _AccountOutcome:
    """One account's contribution to the phase result — cost, success, the budget-stop signal, and
    the references-only manifest entry. Internal: the handler aggregates a list of these."""

    cost_cents: CostCents
    succeeded: bool
    budget_stop: BudgetVerdict | None
    manifest: dict[str, JsonValue]


def _budget_stop(result: AccountDeepResult) -> BudgetVerdict | None:
    """The ``ACCOUNT``-DENY / ``RUN``-GRACEFUL_STOP verdict M8A.3 records on the result.

    ``None`` when the contact fan-out admitted every in-cap member within budget; a ``DENY`` → a
    partial-but-COMPLETED account; a ``RUN``-scope ``GRACEFUL_STOP`` → ``PhaseResult(PAUSED)``
    (mapped in :meth:`DeepPhaseHandler.run`)."""
    return result.budget_stop


def _failed_manifest(
    spec: AccountSpec, run_id: RunId, *, cost_cents: CostCents
) -> dict[str, JsonValue]:
    # A FAILED account produced no ``AccountDeepResult`` to fold a skeleton from, so it cannot run
    # ``build_handoff_skeleton`` — emit the same references-only ``DeepCompleteManifest`` shape
    # (M8A.5) with empty member/coverage/index sections and the ``failed`` status the handler owns.
    return {
        "account_entity_id": str(spec.entity_id),
        "account_run_id": str(run_id),
        "tier": spec.tier,
        "committee_member_ids": [],
        "coverage": None,
        "cost_cents": str(cost_cents),
        "references_index": {},
        "status": "failed",
    }


def _succeeded_outcome(result: AccountDeepResult) -> _AccountOutcome:
    """Fold the M8A.5 handoff skeleton into this account's references-only payload entry.

    ``build_handoff_skeleton(result).manifest()`` is the references-only ``DeepCompleteManifest``
    (account-run id, admitted member ids, coverage band, cost, and the per-section claim-id index —
    **ids only, never a ``value_json``**); the rich ``(account, persona)`` join with joined
    ``profile_claims`` stays in-memory for M12.2 to recompute on read. The handler stamps the only
    field the skeleton can't know — the budget-derived ``status``: an ``ACCOUNT``-DENY (or
    ``RUN``-GRACEFUL_STOP) account did real work but stopped early → ``partial``; an un-capped
    account that ran to ``CONTACTS_COMPLETE`` is ``completed`` (Doc C §7 coverage-confidence)."""
    stop = _budget_stop(result)
    manifest = build_handoff_skeleton(result).manifest().model_dump(mode="json")
    manifest["status"] = "partial" if stop is not None else "completed"
    return _AccountOutcome(
        cost_cents=result.cost_cents,
        succeeded=True,
        budget_stop=stop,
        manifest=manifest,
    )


class DeepPhaseHandler:
    """The ``ProjectPhase.DEEP`` :class:`~clue_core.PhaseHandler` (M8A.2).

    Resolves the approved high-tier accounts and drives the scheduler with the M8A.1 orchestrator as
    the per-account callback, owning per-account FAILED isolation and the budget-verdict → phase-
    status mapping. Construct once per campaign with the injected collaborators and register it at
    the api composition root (M8A.6)."""

    phase = ProjectPhase.DEEP

    def __init__(
        self,
        *,
        scheduler: DeepAccountScheduler,
        orchestrator: DeepAccountOrchestrator,
        high_tier_resolver: HighTierResolver,
        checkpointer_factory: CheckpointerFactory,
        finalize_failed_account: FinalizeFailedAccount = _DB_FINALIZE_FAILED_ACCOUNT,
    ) -> None:
        self._scheduler = scheduler
        self._orchestrator = orchestrator
        self._high_tier_resolver = high_tier_resolver
        self._checkpointer_factory = checkpointer_factory
        self._finalize_failed_account = finalize_failed_account

    async def run(self, ctx: PhaseContext) -> PhaseResult:
        """Deep-research every approved high-tier account, isolated per account, then aggregate.

        COMPLETED with a references-only manifest of every account; PAUSED if any account hit a
        ``RUN``-scope ``GRACEFUL_STOP`` (the campaign re-enters ``DEEP`` and resumes). A high-tier
        set of zero is a clean COMPLETED no-op."""
        specs = tuple(await self._high_tier_resolver(ctx))
        if not specs:
            return PhaseResult(
                status=PhaseStatus.COMPLETED,
                accounts_processed=0,
                cost_cents=Decimal(0),
                payload={"deep_count": 0, "accounts_failed": 0, "accounts": []},
            )

        project_run_id = ctx.project_run_id

        async def _isolated(spec: AccountSpec) -> _AccountOutcome:
            # The per-account isolation boundary the scheduler delegates: one account's fault must
            # not sink the batch. Runs inside the scheduler's semaphore + per-entity lock slot.
            run_id = deep_account_run_id(project_run_id, spec.entity_id)
            try:
                result = await self._orchestrator.run_one(spec, project_run_id=project_run_id)
            except Exception:  # noqa: BLE001 — isolate one account; record FAILED and continue
                # The call raised, so there is no result to read the cost from — recover whatever
                # the orchestrator committed stage-by-stage before the crash so the burn-down stays
                # honest (finalize also flips the row to FAILED).
                cost = await self._finalize_failed_account(run_id)
                return _AccountOutcome(
                    cost_cents=cost,
                    succeeded=False,
                    budget_stop=None,
                    manifest=_failed_manifest(spec, run_id, cost_cents=cost),
                )
            if result.sub_phase is None:
                # The account did not resolve — ``profile_account`` returned FAILED with no aspects
                # and the orchestrator short-circuited before discovery without advancing the marker
                # (a clean hard-stop, no exception). Record it FAILED; the returned result carries
                # the accurate cost (the orchestrator short-circuits before persisting), so use it.
                await self._finalize_failed_account(run_id)
                return _AccountOutcome(
                    cost_cents=result.cost_cents,
                    succeeded=False,
                    budget_stop=None,
                    manifest=_failed_manifest(spec, run_id, cost_cents=result.cost_cents),
                )
            return _succeeded_outcome(result)

        async with self._checkpointer_factory() as checkpointer:
            outcomes: list[_AccountOutcome] = await self._scheduler.run_accounts(
                specs,
                project_run_id=project_run_id,
                checkpointer=checkpointer,
                run_one=_isolated,
            )

        cost = sum((outcome.cost_cents for outcome in outcomes), Decimal(0))
        processed = sum(1 for outcome in outcomes if outcome.succeeded)
        failed = sum(1 for outcome in outcomes if not outcome.succeeded)
        paused = any(outcome.budget_stop is BudgetVerdict.GRACEFUL_STOP for outcome in outcomes)
        payload: dict[str, JsonValue] = {
            "deep_count": len(specs),
            "accounts_failed": failed,
            "accounts": [outcome.manifest for outcome in outcomes],
        }
        return PhaseResult(
            status=PhaseStatus.PAUSED if paused else PhaseStatus.COMPLETED,
            accounts_processed=processed,
            cost_cents=cost,
            payload=payload,
        )


# Static-time conformance (mirroring ``run_io._DB_ACCOUNT_RUN_IO_IS_AN_IO``): the registered handler
# must satisfy ``core.PhaseHandler``, and the real durable scheduler + M8A.1 orchestrator must
# satisfy the seams this handler is typed against — so the fake-driven tests exercise the same
# surface the composition root (M8A.6) wires.
_HANDLER_IS_A_PHASE_HANDLER: type[PhaseHandler] = DeepPhaseHandler
_ACCOUNT_SCHEDULER_IS_A_DEEP_SCHEDULER: type[DeepAccountScheduler] = AccountScheduler
_ORCHESTRATOR_IS_A_DEEP_ORCHESTRATOR: type[DeepAccountOrchestrator] = AccountDeepOrchestrator
