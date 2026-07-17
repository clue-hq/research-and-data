"""M8A.4 — exactly-once spend + concurrent-admit reservation, driven by fakes (no DB).

These prove the *orchestration-level* exactly-once contract: every deep stage's spend routes through
the injected :class:`~clue_research.api.deep.spend.ExactlyOnceSpend` (so the budget charge, claim
writes, and ledger ``succeed`` commit together) keyed once per stage; a resumed fan-out **replays**
already-committed contacts without re-charging; the references-fold never carries cost (the budget
engine's ``record`` is the single writer); and the per-account reservation stops admitting before
concurrent in-flight peers can collectively breach the per-account cap. The DB-backed atomicity
(crash-injection → ``spent_cents == SUM(ledger charges)``) lives in ``test_exactly_once_spend_db``.
"""

from __future__ import annotations

from decimal import Decimal

from clue_config import DeepPhaseConfig
from clue_core import (
    BudgetVerdict,
    new_campaign_run_id,
    new_entity_id,
)
from clue_research.api.deep import deep_account_run_id, deep_step_key
from clue_research.durable import AccountRunStatus, AccountRunSubPhase, AccountSpec
from tests.api.deep.test_orchestrator import (
    FakeAccountRunIO,
    FakeBudgetEngine,
    FakeExactlyOnceSpend,
    FakeProfileContact,
    Recorder,
    _orchestrator,
    make_discover_committee,
    make_profile_account,
)
from tests.db.conftest import run_async


def test_each_stage_charges_exactly_once_through_the_spend_seam() -> None:
    """Account, committee, and every contact each route through ``run_step`` exactly once — keyed to
    the deterministic step key + the ACCOUNT entity/run (so ``record`` moves the counters once)."""
    io = FakeAccountRunIO()
    rec = Recorder()
    spend = FakeExactlyOnceSpend()
    orch = _orchestrator(
        io,
        make_profile_account(rec),
        make_discover_committee(rec, n_members=3),
        FakeProfileContact(rec),
        spend=spend,
    )
    campaign = new_campaign_run_id()
    entity = new_entity_id()
    spec = AccountSpec(entity_id=entity, tier="top", workspace_id="client-1")

    async def _run() -> None:
        result = await orch.run_one(spec, campaign_run_id=campaign)
        run_id = deep_account_run_id(campaign, entity)
        keys = [c["key"] for c in spend.charges]
        # one account + one committee + one per admitted contact, each charged exactly once
        assert deep_step_key(run_id, "account") in keys
        assert deep_step_key(run_id, "committee") in keys
        assert len(keys) == len(set(keys)) == 5  # account + committee + 3 contacts, no dup
        # every charge is keyed to the ACCOUNT entity + the deterministic account_run id
        for charge in spend.charges:
            assert charge["account_run_id"] == run_id
            assert charge["entity_id"] == entity
            assert charge["campaign_run_id"] == campaign
        # cost = account 5 + committee 3 + 3 contacts × 2 — the sum of the spend steps
        assert result.cost_cents == Decimal("5") + Decimal("3") + Decimal("6")

    run_async(_run())


def test_resumed_fan_out_replays_committed_contacts_without_recharge() -> None:
    """A fan-out resumed mid-flight: the contact that already committed REPLAYs (its work is not
    re-run and its charge is not re-recorded); only the still-pending contacts spend afresh."""
    io = FakeAccountRunIO()
    rec = Recorder()
    campaign = new_campaign_run_id()
    entity = new_entity_id()
    run_id = deep_account_run_id(campaign, entity)
    done_contact, pending_a, pending_b = new_entity_id(), new_entity_id(), new_entity_id()
    # The prior run profiled the account (5) + committee (3) + the first contact (2) → 10 booked.
    io.seed(
        run_id,
        sub_phase=AccountRunSubPhase.COMMITTEE_DISCOVERED,
        references_index={
            "committee_contacts": [str(done_contact), str(pending_a), str(pending_b)]
        },
        cost_cents=Decimal("10"),
    )
    # The already-committed contact REPLAYs: its recorded refs + charge come from the ledger.
    spend = FakeExactlyOnceSpend(
        replay={deep_step_key(run_id, f"contact:{done_contact}"): (("rc-done",), Decimal("2"))}
    )
    orch = _orchestrator(
        io,
        make_profile_account(rec),
        make_discover_committee(rec),
        FakeProfileContact(rec),
        spend=spend,
    )
    spec = AccountSpec(entity_id=entity, tier="top", workspace_id="client-1")

    async def _run() -> None:
        result = await orch.run_one(spec, campaign_run_id=campaign)
        # the replayed contact's work was NOT re-run; only the two pending contacts were profiled
        assert sorted(str(c) for c in rec.contact_ids) == sorted([str(pending_a), str(pending_b)])
        # exactly two fresh charges (the two pending) — the replayed contact was NOT re-charged
        charged_keys = {c["key"] for c in spend.charges}
        assert deep_step_key(run_id, f"contact:{done_contact}") not in charged_keys
        assert charged_keys == {
            deep_step_key(run_id, f"contact:{pending_a}"),
            deep_step_key(run_id, f"contact:{pending_b}"),
        }
        # cost = the 10 already booked + the two fresh contacts (2 each); the replay is NOT re-added
        assert result.cost_cents == Decimal("10") + Decimal("4")
        # the replayed contact's references are recovered from the ledger; the fresh ones from work
        refs = io.runs[run_id]["references_index"]
        assert refs[f"contact:{done_contact}"] == ["rc-done"]
        assert f"contact:{pending_a}" in refs and f"contact:{pending_b}" in refs
        # only the two freshly-profiled contacts carry a result object (the replay yields None)
        assert len(result.contacts) == 2
        assert result.sub_phase is AccountRunSubPhase.CONTACTS_COMPLETE

    run_async(_run())


def test_reservation_guard_stops_admitting_when_reservations_would_breach_the_cap() -> None:
    """The reservation guard's arithmetic: admission stops once committed + reserved + one-more
    would breach the per-account cap, even though the engine ``check`` (seeing only committed spend)
    still ALLOWs. This exercises the guard deterministically (the fake ``check`` does not yield, so
    no peer settles mid-admission); production concurrency-safety rests on single-threaded asyncio
    mutating the reservation only at await boundaries, documented on :class:`_Reservation`."""
    io = FakeAccountRunIO()
    rec = Recorder()
    # ALLOW everything, but report a real per-account cap so the reservation guard is live. Account
    # 5 + committee 3 = 8 committed; estimate 50; cap 120 admits exactly two (8+0+50, 8+50+50 fit;
    # 8+100+50 = 158 > 120 stops) while the in-flight contacts have not yet settled their charge.
    budget = FakeBudgetEngine(cap_cents=Decimal("120"))
    config = DeepPhaseConfig(
        per_contact_estimate_cents=Decimal("50"),
        committee_size_cap=8,
        max_contacts_in_flight=5,
    )
    orch = _orchestrator(
        io,
        make_profile_account(rec),
        make_discover_committee(rec, n_members=5),
        FakeProfileContact(rec, delay=0.05),  # slow → they do not settle during admission
        config=config,
        budget=budget,
    )
    spec = AccountSpec(entity_id=new_entity_id(), tier="top", workspace_id="client-1")

    async def _run() -> None:
        result = await orch.run_one(spec, campaign_run_id=new_campaign_run_id())
        # the cap admitted only two of the five members before the reservation guard fired
        assert len(result.contacts) == 2
        assert result.budget_stop is BudgetVerdict.DENY
        # a finished partial, never FAILED: the committee was fully discovered (5), two profiled
        assert result.committee is not None and len(result.committee.members) == 5
        assert result.sub_phase is AccountRunSubPhase.CONTACTS_COMPLETE
        assert io.saves[-1][1] is AccountRunStatus.DONE

    run_async(_run())


def test_uncapped_account_runs_the_reservation_guard_inert() -> None:
    """``decision.cap_cents == 0`` (uncapped) leaves the reservation guard inert — the whole in-cap
    committee is profiled, so the guard never narrows an uncapped account."""
    io = FakeAccountRunIO()
    rec = Recorder()
    budget = FakeBudgetEngine()  # cap_cents defaults to 0 → uncapped
    orch = _orchestrator(
        io,
        make_profile_account(rec),
        make_discover_committee(rec, n_members=4),
        FakeProfileContact(rec),
        config=DeepPhaseConfig(per_contact_estimate_cents=Decimal("1000"), committee_size_cap=8),
        budget=budget,
    )
    spec = AccountSpec(entity_id=new_entity_id(), tier="top", workspace_id="client-1")

    async def _run() -> None:
        result = await orch.run_one(spec, campaign_run_id=new_campaign_run_id())
        assert len(result.contacts) == 4  # all admitted despite a huge estimate — no cap to breach
        assert result.budget_stop is None

    run_async(_run())


def test_cap_saturated_resume_recovers_all_committed_contact_references() -> None:
    """Regression for the resume reference-drop: a prior run charged every contact (so the account
    is AT its per-account cap) and crashed before the contacts_complete fold, leaving no
    ``contact:*`` keys in the index. On resume the budget would DENY re-admission of every member —
    but the contacts are recovered straight from the durable ledger, *independent of the budget
    gate*, so no committed contact's references drop (the handoff keeps the buying committee)."""
    io = FakeAccountRunIO()
    rec = Recorder()
    campaign = new_campaign_run_id()
    entity = new_entity_id()
    run_id = deep_account_run_id(campaign, entity)
    members = [new_entity_id() for _ in range(5)]
    # All 5 were charged on the prior run (50 each); the crash happened before the contacts_complete
    # fold, so the durable index has the work-list but NO contact:* reference keys yet.
    io.seed(
        run_id,
        sub_phase=AccountRunSubPhase.COMMITTEE_DISCOVERED,
        references_index={"committee_contacts": [str(m) for m in members]},
        cost_cents=Decimal("258"),
    )
    spend = FakeExactlyOnceSpend(
        replay={
            deep_step_key(run_id, f"contact:{m}"): ((f"rc-{i}",), Decimal("50"))
            for i, m in enumerate(members)
        }
    )
    # The account is at its cap → every admission check would DENY (modelled as a DENY default).
    budget = FakeBudgetEngine(default=BudgetVerdict.DENY)
    orch = _orchestrator(
        io,
        make_profile_account(rec),
        make_discover_committee(rec),
        FakeProfileContact(rec),
        budget=budget,
        spend=spend,
    )
    spec = AccountSpec(entity_id=entity, tier="top", workspace_id="client-1")

    async def _run() -> None:
        result = await orch.run_one(spec, campaign_run_id=campaign)
        refs = io.runs[run_id]["references_index"]
        # every committed contact's references are recovered from the ledger — none dropped
        for i, m in enumerate(members):
            assert refs[f"contact:{m}"] == [f"rc-{i}"]
        # ...without re-running the worker, re-charging, or even consulting the budget gate
        assert rec.contact_ids == []  # no contact worker re-ran
        assert spend.charges == []  # nothing re-charged
        assert budget.checks == []  # no admission was attempted for the recovered contacts
        # the already-booked cost is unchanged and the account resumes to a clean DONE
        assert result.cost_cents == Decimal("258")
        assert result.sub_phase is AccountRunSubPhase.CONTACTS_COMPLETE
        assert io.saves[-1][1] is AccountRunStatus.DONE

    run_async(_run())


def test_references_fold_does_not_write_cost_record_is_single_writer() -> None:
    """The references-fold carries no ``cost_cents`` — the budget engine's ``record`` is the single
    live writer (the fake io leaves its stored cost at 0 across the run, while the spend steps
    account the real cost on the returned result)."""
    io = FakeAccountRunIO()
    rec = Recorder()
    orch = _orchestrator(
        io,
        make_profile_account(rec),
        make_discover_committee(rec, n_members=2),
        FakeProfileContact(rec),
    )
    campaign = new_campaign_run_id()
    entity = new_entity_id()
    spec = AccountSpec(entity_id=entity, tier="top", workspace_id="client-1")

    async def _run() -> None:
        result = await orch.run_one(spec, campaign_run_id=campaign)
        run_id = deep_account_run_id(campaign, entity)
        # the fold never touched cost_cents (record owns it); the run still accounts the real total
        assert io.runs[run_id]["cost_cents"] == Decimal(0)
        assert result.cost_cents == Decimal("5") + Decimal("3") + Decimal("4")

    run_async(_run())
