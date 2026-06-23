"""M8A.3 — the per-contact fan-out budget admission, driven by fakes (no DB).

These prove the *admission seam* at the single fan-out chokepoint: before each ``profile_contact``,
the orchestrator asks ``BudgetEngine.check(scope=ACCOUNT)`` projecting the config's
``per_contact_estimate_cents`` and launches only an ``ALLOW``. The halting verdict is surfaced on
:class:`AccountDeepResult.budget_stop` — an ``ACCOUNT``-scope ``DENY`` is a *partial committee*
(coverage-confidence, not completeness), a ``RUN``-scope ``GRACEFUL_STOP`` is surfaced for the M8A.2
handler to turn into ``PhaseResult(PAUSED)``. Neither is a FAILED account.

The four fan-out bounds (Doc C §3/§5) are all config-driven, none hardcoded: (a) committee-size
truncation and (d) the in-flight semaphore are exercised by ``test_orchestrator``; (b) this budget
admission and (c) the per-tier facet sub-worker budget are exercised here.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any

import pytest

from clue_research.api.deep import deep_account_run_id
from clue_research.config import DeepPhaseConfig, RecursionPolicy, TierRecursionCaps
from clue_research.core import (
    BudgetScope,
    BudgetVerdict,
    EntityId,
    WorkerStatus,
    new_campaign_run_id,
    new_entity_id,
)
from clue_research.durable import AccountRunStatus, AccountRunSubPhase, AccountSpec
from clue_research.profiling import ContactProfileResult
from tests.api.deep.test_orchestrator import (
    FakeAccountRunIO,
    FakeBudgetEngine,
    FakeProfileContact,
    Recorder,
    _orchestrator,
    make_discover_committee,
    make_profile_account,
)
from tests.db.conftest import run_async


def test_deny_stops_admitting_and_records_partial_not_failed() -> None:
    """An ACCOUNT-scope DENY stops admitting further contacts → a finished *partial*, not FAILED."""
    io = FakeAccountRunIO()
    rec = Recorder()
    budget = FakeBudgetEngine(
        verdicts=[BudgetVerdict.ALLOW, BudgetVerdict.ALLOW, BudgetVerdict.DENY]
    )
    orch = _orchestrator(
        io,
        make_profile_account(rec),
        make_discover_committee(rec, n_members=5),
        FakeProfileContact(rec),
        config=DeepPhaseConfig(committee_size_cap=8),
        budget=budget,
    )
    campaign = new_campaign_run_id()
    entity = new_entity_id()
    spec = AccountSpec(entity_id=entity, tier="top", tenant_id="client-1")

    async def _run() -> None:
        result = await orch.run_one(spec, campaign_run_id=campaign)
        # two ALLOWs admitted, the third check DENY-ed → admission stopped, the rest never checked
        assert len(rec.contact_ids) == 2
        assert len(result.contacts) == 2
        assert len(budget.checks) == 3  # the DENY short-circuits the remaining members
        assert result.budget_stop is BudgetVerdict.DENY
        # the committee was fully discovered (5) but only 2 profiled — a partial, NOT a failure
        assert result.committee is not None and len(result.committee.members) == 5
        assert result.account is not None and result.account.status is WorkerStatus.OK
        # a finished partial: the marker advances and the run is DONE (never FAILED)
        assert result.sub_phase is AccountRunSubPhase.CONTACTS_COMPLETE
        assert io.saves[-1][1] is AccountRunStatus.DONE

    run_async(_run())


def test_graceful_stop_is_surfaced_for_the_handler_to_pause() -> None:
    """A RUN-scope GRACEFUL_STOP finishes the in-flight contacts and surfaces the pause signal."""
    io = FakeAccountRunIO()
    rec = Recorder()
    budget = FakeBudgetEngine(verdicts=[BudgetVerdict.ALLOW, BudgetVerdict.GRACEFUL_STOP])
    orch = _orchestrator(
        io,
        make_profile_account(rec),
        make_discover_committee(rec, n_members=4),
        FakeProfileContact(rec),
        budget=budget,
    )
    spec = AccountSpec(entity_id=new_entity_id(), tier="top", tenant_id="client-1")

    async def _run() -> None:
        result = await orch.run_one(spec, campaign_run_id=new_campaign_run_id())
        # one admitted before the run-cap breach; the second check GRACEFUL_STOP-ed
        assert len(result.contacts) == 1
        assert result.budget_stop is BudgetVerdict.GRACEFUL_STOP
        # still a finished partial at the account level — the handler maps the signal to PAUSED
        assert result.sub_phase is AccountRunSubPhase.CONTACTS_COMPLETE
        assert result.committee is not None
        assert io.saves[-1][1] is AccountRunStatus.DONE

    run_async(_run())


def test_all_allow_profiles_every_in_cap_member_with_no_stop() -> None:
    """Every check ALLOW → the whole (in-cap) committee is profiled and ``budget_stop`` is None."""
    io = FakeAccountRunIO()
    rec = Recorder()
    budget = FakeBudgetEngine()  # ALLOW by default
    orch = _orchestrator(
        io,
        make_profile_account(rec),
        make_discover_committee(rec, n_members=3),
        FakeProfileContact(rec),
        budget=budget,
    )
    spec = AccountSpec(entity_id=new_entity_id(), tier="top", tenant_id="client-1")

    async def _run() -> None:
        result = await orch.run_one(spec, campaign_run_id=new_campaign_run_id())
        assert len(result.contacts) == 3
        assert result.budget_stop is None
        assert len(budget.checks) == 3  # one admission check per admitted member
        assert result.sub_phase is AccountRunSubPhase.CONTACTS_COMPLETE

    run_async(_run())


def test_admission_projects_per_contact_estimate_from_config() -> None:
    """Bound (b): the projection + scope + account keys are config-driven, never hardcoded."""
    io = FakeAccountRunIO()
    rec = Recorder()
    budget = FakeBudgetEngine()
    config = DeepPhaseConfig(per_contact_estimate_cents=Decimal(77), committee_size_cap=8)
    orch = _orchestrator(
        io,
        make_profile_account(rec),
        make_discover_committee(rec, n_members=2),
        FakeProfileContact(rec),
        config=config,
        budget=budget,
    )
    campaign = new_campaign_run_id()
    entity = new_entity_id()
    spec = AccountSpec(entity_id=entity, tier="top", tenant_id="client-1")

    async def _run() -> None:
        await orch.run_one(spec, campaign_run_id=campaign)
        run_id = deep_account_run_id(campaign, entity)
        assert len(budget.checks) == 2
        for call in budget.checks:
            # the projected amount is the CONFIG value, not a literal baked into the orchestrator
            assert call["projected_cents"] == Decimal(77)
            assert call["scope"] is BudgetScope.ACCOUNT
            # keyed to the ACCOUNT entity + the deterministic account_run id (the cost-dial axis)
            assert call["entity_id"] == entity
            assert call["account_run_id"] == run_id
            assert call["campaign_run_id"] == campaign

    run_async(_run())


def test_facet_subworker_budget_is_read_from_recursion_policy_bound_c() -> None:
    """Bound (c): each contact gets the tier's per-aspect facet budget from ``RecursionPolicy``."""
    io = FakeAccountRunIO()
    rec = Recorder()
    seen: list[int] = []

    async def _recording_contact(
        conn: Any, *, contact_entity_id: EntityId, **kwargs: Any
    ) -> ContactProfileResult:
        seen.append(kwargs["facet_subworker_budget"])
        return ContactProfileResult(
            contact_entity_id=contact_entity_id,
            account_entity_id=kwargs["account_entity_id"],
            profile_claims=(),
            cost_cents=Decimal(0),
        )

    policy = RecursionPolicy(by_tier={"top": TierRecursionCaps(max_facet_workers_per_aspect=4)})
    orch = _orchestrator(
        io,
        make_profile_account(rec),
        make_discover_committee(rec, n_members=2),
        _recording_contact,
        recursion_policy=policy,
    )
    spec = AccountSpec(entity_id=new_entity_id(), tier="top", tenant_id="client-1")

    async def _run() -> None:
        await orch.run_one(spec, campaign_run_id=new_campaign_run_id())
        # the value flows from the policy's tier caps (4), not a hardcoded constant
        assert seen == [4, 4]

    run_async(_run())


def test_deny_on_first_contact_admits_zero_records_partial() -> None:
    """DENY on the very first check admits zero contacts — a finished partial, never FAILED."""
    io = FakeAccountRunIO()
    rec = Recorder()
    budget = FakeBudgetEngine(verdicts=[BudgetVerdict.DENY])
    orch = _orchestrator(
        io,
        make_profile_account(rec),
        make_discover_committee(rec, n_members=4),
        FakeProfileContact(rec),
        budget=budget,
    )
    spec = AccountSpec(entity_id=new_entity_id(), tier="top", tenant_id="client-1")

    async def _run() -> None:
        result = await orch.run_one(spec, campaign_run_id=new_campaign_run_id())
        # the first check denied → nothing admitted, the rest never checked
        assert len(result.contacts) == 0
        assert len(budget.checks) == 1
        assert result.budget_stop is BudgetVerdict.DENY
        # a committee WAS discovered (4) but zero profiled — a finished partial, not a failure
        assert result.committee is not None and len(result.committee.members) == 4
        assert result.sub_phase is AccountRunSubPhase.CONTACTS_COMPLETE
        assert io.saves[-1][1] is AccountRunStatus.DONE

    run_async(_run())


def test_budget_check_exception_cancels_admitted_tasks_no_orphans() -> None:
    """If ``budget.check`` raises mid-admission, the already-launched contact tasks are cancelled
    and drained — never left pending after ``run_one`` re-raises (the admit-then-launch cleanup)."""
    io = FakeAccountRunIO()
    rec = Recorder()
    budget = FakeBudgetEngine(raise_after=2)  # two ALLOWs launch two tasks; the third check raises
    contact = FakeProfileContact(rec, delay=0.05)  # an un-cancelled task would still be pending
    orch = _orchestrator(
        io,
        make_profile_account(rec),
        make_discover_committee(rec, n_members=5),
        contact,
        config=DeepPhaseConfig(committee_size_cap=8),
        budget=budget,
    )
    spec = AccountSpec(entity_id=new_entity_id(), tier="top", tenant_id="client-1")

    async def _run() -> None:
        with pytest.raises(RuntimeError, match="budget engine unavailable"):
            await orch.run_one(spec, campaign_run_id=new_campaign_run_id())
        await asyncio.sleep(0)  # let the loop settle after the re-raise
        # no admitted contact task is left running detached (the cleanup cancelled + drained them)
        leftover = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        assert leftover == []

    run_async(_run())
