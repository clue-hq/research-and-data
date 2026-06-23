"""The ``CampaignPhase.DEEP`` phase handler (M8A.2) — drives the deep phase end-to-end.

The :class:`~clue_research.core.PhaseHandler` for ``CampaignPhase.DEEP``. Registering it at the api
composition root makes ``CampaignRun.advance()`` dispatch ``DEEP`` with zero new dispatch code — the
run no longer raises ``NoPhaseHandlerRegistered(DEEP)`` the moment it enters Pass B.

The handler is thin: it (1) resolves the human-approved high-tier account set via the injected
:data:`HighTierResolver`, (2) drives the M7 :class:`~clue_research.durable.AccountScheduler` with
the M8A.1 :class:`~clue_research.api.deep.AccountDeepOrchestrator` bound as the per-account
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
already done). M8A.3 adds the ``budget_stop`` signal to ``AccountDeepResult``; until it merges this
handler reads the signal forward-compatibly (see :func:`_budget_stop`) so it is correct on the
current trunk (no admission yet → never paused) and lights up automatically once M8A.3 lands.

**Out of scope (later M8A issues):** the per-account sequence itself (M8A.1, injected); the fan-out
budget admission + ``DeepPhaseConfig`` (M8A.3, on the orchestrator); the exactly-once spend
transaction (M8A.4); the rich ``(account, persona)``-keyed handoff skeleton with joined
``profile_claims`` (M8A.5 — folded into this payload when it lands); injecting the concrete
scheduler/orchestrator/resolver/gate + the AC-6/AC-4 enforcement (M8A.6 composition root). The
payload is **references-only** — account-run ids, admitted member ids, coverage bands, costs — never
claim bodies (substrate §5b).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable

from langgraph.checkpoint.base import BaseCheckpointSaver
from pydantic import JsonValue

from clue_research.api.deep.orchestrator import (
    AccountDeepOrchestrator,
    AccountDeepResult,
    deep_account_run_id,
)
from clue_research.core import (
    BudgetVerdict,
    CampaignPhase,
    CampaignRunId,
    CostCents,
    PhaseContext,
    PhaseHandler,
    PhaseResult,
    PhaseStatus,
    RunId,
)
from clue_research.db import transaction
from clue_research.durable import (
    AccountRunStatus,
    AccountScheduler,
    AccountSpec,
    RunOne,
    get_account_run,
    set_status,
)
from clue_research.profiling.runtime import SessionFactory

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
        campaign_run_id: CampaignRunId,
        checkpointer: BaseCheckpointSaver[Any],
        run_one: RunOne[Any],
    ) -> list[Any]: ...


@runtime_checkable
class DeepAccountOrchestrator(Protocol):
    """The per-account sequence the handler binds as the scheduler's ``run_one`` (M8A.2).

    Typed as a seam so the handler is fake-testable; the M8A.1
    :class:`~clue_research.api.deep.AccountDeepOrchestrator` satisfies it (asserted below)."""

    async def run_one(
        self, spec: AccountSpec, *, campaign_run_id: CampaignRunId
    ) -> AccountDeepResult: ...


def db_finalize_failed_account(
    *, session_factory: SessionFactory = transaction
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
    """The ``ACCOUNT``-DENY / ``RUN``-GRACEFUL_STOP signal M8A.3 surfaces on the result.

    Read structurally (``getattr``) rather than as a typed attribute so this handler compiles and
    runs on the current M8A.1 trunk — where ``AccountDeepResult`` has no ``budget_stop`` field and
    there is no budget admission yet, so it is always ``None`` (never paused, correctly) — and
    lights up automatically once M8A.3 adds the field. A non-:class:`BudgetVerdict` value is
    ignored."""
    stop = getattr(result, "budget_stop", None)
    return stop if isinstance(stop, BudgetVerdict) else None


def _committee_member_ids(result: AccountDeepResult) -> list[JsonValue]:
    """The admitted committee member contact-ids (references only). On a fresh run they come from
    the committee result; on a resumed run (``committee is None``) from the profiled contacts."""
    # Declared ``list[JsonValue]`` so the id strings flow into the references-only payload (a bare
    # ``list[str]`` is invariant-incompatible with the ``dict[str, JsonValue]`` manifest).
    ids: list[JsonValue]
    if result.committee is not None:
        ids = [str(member.contact_entity_id) for member in result.committee.members]
    else:
        ids = [str(contact.contact_entity_id) for contact in result.contacts]
    return ids


def _coverage_view(result: AccountDeepResult) -> dict[str, JsonValue] | None:
    """The committee coverage band + named unsearched channels (Doc C §7) — partial, not failed.

    ``None`` on a resumed run that skipped discovery (the committee result is not re-materialised);
    the durable coverage still lives on the claim store for M12."""
    if result.committee is None:
        return None
    coverage = result.committee.coverage
    return {
        "confidence": str(coverage.confidence),
        "estimate_point": coverage.estimate_point,
        "estimate_low": coverage.estimate_low,
        "estimate_high": coverage.estimate_high,
        "channels_not_searched": list(coverage.channels_not_searched),
    }


def _failed_manifest(
    spec: AccountSpec, run_id: RunId, *, cost_cents: CostCents
) -> dict[str, JsonValue]:
    return {
        "account_run_id": str(run_id),
        "entity_id": str(spec.entity_id),
        "tier": spec.tier,
        "status": "failed",
        "cost_cents": str(cost_cents),
        "committee_member_ids": [],
        "coverage": None,
        "claim_ref_count": 0,
    }


def _succeeded_outcome(result: AccountDeepResult) -> _AccountOutcome:
    # M8A.5 fold-point: this is the references-only per-account manifest the spec's "deep-complete"
    # payload requires (account-run id, admitted member ids, coverage band, cost). M8A.5 ships
    # ``build_handoff_skeleton(result)`` — the richer ``(account, persona)``-keyed view with each
    # member's ``profile_claims`` joined by ``contact_entity_id``; when it merges, this manifest is
    # replaced/augmented by that skeleton (ids only, still no claim bodies). M8A.5 is a parallel
    # branch, so the function does not exist on this base — the inline manifest is the interim form.
    stop = _budget_stop(result)
    return _AccountOutcome(
        cost_cents=result.cost_cents,
        succeeded=True,
        budget_stop=stop,
        manifest={
            "account_run_id": str(result.account_run_id),
            "entity_id": str(result.entity_id),
            "tier": result.tier,
            # A budget-DENY (or GRACEFUL_STOP) account did real work but stopped early → partial,
            # not failed; an un-capped account that ran to CONTACTS_COMPLETE is completed.
            "status": "partial" if stop is not None else "completed",
            "cost_cents": str(result.cost_cents),
            "committee_member_ids": _committee_member_ids(result),
            "coverage": _coverage_view(result),
            "claim_ref_count": len(result.claim_refs),
        },
    )


class DeepPhaseHandler:
    """The ``CampaignPhase.DEEP`` :class:`~clue_research.core.PhaseHandler` (M8A.2).

    Resolves the approved high-tier accounts and drives the scheduler with the M8A.1 orchestrator as
    the per-account callback, owning per-account FAILED isolation and the budget-verdict → phase-
    status mapping. Construct once per campaign with the injected collaborators and register it at
    the api composition root (M8A.6)."""

    phase = CampaignPhase.DEEP

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

        campaign_run_id = ctx.campaign_run_id

        async def _isolated(spec: AccountSpec) -> _AccountOutcome:
            # The per-account isolation boundary the scheduler delegates: one account's fault must
            # not sink the batch. Runs inside the scheduler's semaphore + per-entity lock slot.
            run_id = deep_account_run_id(campaign_run_id, spec.entity_id)
            try:
                result = await self._orchestrator.run_one(spec, campaign_run_id=campaign_run_id)
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
                campaign_run_id=campaign_run_id,
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
