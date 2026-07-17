"""M7.5 budget engine — check / record / set_campaign_cap / burn_down / estimate on an in-memory
store (no DB). Exercises the three-scope enforcement, the exactly-once charge accounting (and that
it ties to the M7.4 ledger), the client raise/lower loop, and the live burn-down surface.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from clue_config import BudgetCaps
from clue_core import (
    BudgetScope,
    BudgetVerdict,
    IdempotencyScope,
    account_step_key,
    new_campaign_run_id,
    new_entity_id,
    new_run_id,
)
from clue_obs.otel import METRIC_COST_CENTS, InMemorySink, set_metric_sink
from clue_research.durable.budget import (
    BudgetEngine,
    BudgetStateNotFound,
    BudgetStore,
    DbBudgetStore,
)
from clue_research.durable.enums import BudgetEventKind
from clue_research.durable.idempotency import idempotent
from tests.db.conftest import run_async
from tests.durable.conftest import FakeBudgetStore, FakeIdempotencyStore


def test_stores_conform_to_the_budget_store_protocol() -> None:
    # Both the in-memory fake and the production DB store satisfy the runtime-checkable seam, so a
    # test exercising the fake proves the same surface production runs (constructing DbBudgetStore
    # touches no DB).
    assert isinstance(FakeBudgetStore(), BudgetStore)
    assert isinstance(DbBudgetStore(), BudgetStore)


_POLICY = BudgetCaps(
    pass_a_cap_cents_per_account=Decimal("5"),
    per_account_cap_cents={"top": Decimal("1000"), "high": Decimal("400")},
)


def _engine(store: FakeBudgetStore, *, policy: BudgetCaps = _POLICY) -> BudgetEngine:
    return BudgetEngine(policy=policy, store=store)


# --- ACCOUNT scope (the M7.2 spawn-denial) --------------------------------------------------


def test_account_check_allows_within_tier_band() -> None:
    async def _run() -> None:
        store = FakeBudgetStore()
        ar = new_run_id()
        store.set_account(ar, tier="top", cost=Decimal("600"))  # band 1000, 400 head-room
        engine = _engine(store)
        decision = await engine.check(
            scope=BudgetScope.ACCOUNT,
            projected_cents=Decimal("300"),
            campaign_run_id=new_campaign_run_id(),
            account_run_id=ar,
        )
        assert decision.verdict is BudgetVerdict.ALLOW
        assert decision.cap_cents == Decimal("1000")
        assert store.events == []  # an ALLOW records no governance event

    run_async(_run())


def test_account_check_denies_over_tier_band_and_records_event() -> None:
    async def _run() -> None:
        store = FakeBudgetStore()
        cr, ar, entity = new_campaign_run_id(), new_run_id(), new_entity_id()
        store.set_account(ar, tier="top", cost=Decimal("900"))  # band 1000, 100 head-room
        engine = _engine(store)
        decision = await engine.check(
            scope=BudgetScope.ACCOUNT,
            projected_cents=Decimal("200"),  # 900 + 200 = 1100 > 1000
            campaign_run_id=cr,
            entity_id=entity,
            account_run_id=ar,
        )
        assert decision.verdict is BudgetVerdict.DENY
        assert store.kinds() == [BudgetEventKind.CHECK_DENY]
        ev = store.events[0]
        assert ev.scope is BudgetScope.ACCOUNT
        assert ev.detail["entity_id"] == str(entity)
        assert ev.detail["account_run_id"] == str(ar)

    run_async(_run())


def test_account_check_exact_fit_is_allowed_strict_gt() -> None:
    async def _run() -> None:
        store = FakeBudgetStore()
        ar = new_run_id()
        store.set_account(ar, tier="top", cost=Decimal("700"))
        engine = _engine(store)
        decision = await engine.check(
            scope=BudgetScope.ACCOUNT,
            projected_cents=Decimal("300"),  # 700 + 300 = 1000 == cap → allowed (strict >)
            campaign_run_id=new_campaign_run_id(),
            account_run_id=ar,
        )
        assert decision.verdict is BudgetVerdict.ALLOW

    run_async(_run())


def test_account_row_cap_override_takes_precedence_over_policy_band() -> None:
    async def _run() -> None:
        store = FakeBudgetStore()
        ar = new_run_id()
        # Row override 100 (a tight per-account cap) beats the policy band 1000 for "top".
        store.set_account(ar, tier="top", cost=Decimal("50"), cap=Decimal("100"))
        engine = _engine(store)
        decision = await engine.check(
            scope=BudgetScope.ACCOUNT,
            projected_cents=Decimal("80"),  # 50 + 80 = 130 > 100 override
            campaign_run_id=new_campaign_run_id(),
            account_run_id=ar,
        )
        assert decision.verdict is BudgetVerdict.DENY
        assert decision.cap_cents == Decimal("100")

    run_async(_run())


def test_account_no_cap_allows_unlisted_tier() -> None:
    async def _run() -> None:
        store = FakeBudgetStore()
        ar = new_run_id()
        store.set_account(ar, tier="cold", cost=Decimal("99999"))  # no band, no override
        engine = _engine(store)
        decision = await engine.check(
            scope=BudgetScope.ACCOUNT,
            projected_cents=Decimal("99999"),
            campaign_run_id=new_campaign_run_id(),
            account_run_id=ar,
        )
        assert decision.verdict is BudgetVerdict.ALLOW  # per-campaign cap is the backstop

    run_async(_run())


def test_account_check_requires_account_run_id() -> None:
    async def _run() -> None:
        engine = _engine(FakeBudgetStore())
        with pytest.raises(ValueError, match="account_run_id"):
            await engine.check(
                scope=BudgetScope.ACCOUNT,
                projected_cents=Decimal("1"),
                campaign_run_id=new_campaign_run_id(),
            )

    run_async(_run())


def test_account_check_missing_row_raises() -> None:
    async def _run() -> None:
        engine = _engine(FakeBudgetStore())
        with pytest.raises(BudgetStateNotFound):
            await engine.check(
                scope=BudgetScope.ACCOUNT,
                projected_cents=Decimal("1"),
                campaign_run_id=new_campaign_run_id(),
                account_run_id=new_run_id(),
            )

    run_async(_run())


# --- PASS scope (the cheap Pass-A per-account ceiling) --------------------------------------


def test_pass_check_against_pass_a_ceiling() -> None:
    async def _run() -> None:
        store = FakeBudgetStore()
        engine = _engine(store)
        cr = new_campaign_run_id()
        ok = await engine.check(
            scope=BudgetScope.PASS, projected_cents=Decimal("5"), campaign_run_id=cr
        )
        assert ok.verdict is BudgetVerdict.ALLOW  # 5 == pass_a cap → exact fit allowed
        deny = await engine.check(
            scope=BudgetScope.PASS, projected_cents=Decimal("6"), campaign_run_id=cr
        )
        assert deny.verdict is BudgetVerdict.DENY
        assert deny.cap_cents == Decimal("5")
        assert store.kinds() == [BudgetEventKind.CHECK_DENY]

    run_async(_run())


# --- RUN scope (the per-campaign hard cap → graceful stop) ----------------------------------


def test_run_check_graceful_stop_inclusive_boundary() -> None:
    async def _run() -> None:
        store = FakeBudgetStore()
        cr = new_campaign_run_id()
        store.set_run(cr, spent=Decimal("800"), cap=Decimal("1000"))
        engine = _engine(store)
        # 800 + 200 = 1000 >= cap → GRACEFUL_STOP (inclusive: keep spend strictly under the cap).
        decision = await engine.check(
            scope=BudgetScope.RUN, projected_cents=Decimal("200"), campaign_run_id=cr
        )
        assert decision.verdict is BudgetVerdict.GRACEFUL_STOP
        assert store.kinds() == [BudgetEventKind.GRACEFUL_STOP]
        # 800 + 199 = 999 < 1000 → ALLOW.
        ok = await engine.check(
            scope=BudgetScope.RUN, projected_cents=Decimal("199"), campaign_run_id=cr
        )
        assert ok.verdict is BudgetVerdict.ALLOW

    run_async(_run())


def test_run_check_uncapped_allows() -> None:
    async def _run() -> None:
        store = FakeBudgetStore()
        cr = new_campaign_run_id()
        store.set_run(cr, spent=Decimal("10000"), cap=None)
        engine = _engine(store)
        decision = await engine.check(
            scope=BudgetScope.RUN, projected_cents=Decimal("9999"), campaign_run_id=cr
        )
        assert decision.verdict is BudgetVerdict.ALLOW
        assert store.events == []

    run_async(_run())


def test_run_check_pregate_fires_when_cap_below_spend() -> None:
    async def _run() -> None:
        store = FakeBudgetStore()
        cr = new_campaign_run_id()
        store.set_run(cr, spent=Decimal("900"), cap=Decimal("500"))  # cap lowered below spend
        engine = _engine(store)
        # projected=0 (the M7.3 pre-gate question "is the run exhausted?"): 900 + 0 >= 500 → stop.
        decision = await engine.check(
            scope=BudgetScope.RUN, projected_cents=Decimal("0"), campaign_run_id=cr
        )
        assert decision.verdict is BudgetVerdict.GRACEFUL_STOP

    run_async(_run())


def test_run_check_missing_row_raises() -> None:
    async def _run() -> None:
        engine = _engine(FakeBudgetStore())
        with pytest.raises(BudgetStateNotFound):
            await engine.check(
                scope=BudgetScope.RUN,
                projected_cents=Decimal("1"),
                campaign_run_id=new_campaign_run_id(),
            )

    run_async(_run())


# --- record() — the single live increment ----------------------------------------------------


def test_record_increments_run_and_account_spend() -> None:
    async def _run() -> None:
        store = FakeBudgetStore()
        cr, ar = new_campaign_run_id(), new_run_id()
        store.set_run(cr, spent=Decimal("0"), cap=Decimal("1000"))
        store.set_account(ar, tier="top", cost=Decimal("0"))
        engine = _engine(store)
        await engine.record(
            cost_cents=Decimal("30"),
            scope=BudgetScope.ACCOUNT,
            campaign_run_id=cr,
            account_run_id=ar,
        )
        assert (await store.run_state(cr)).spent_cents == Decimal("30")
        assert (await store.account_state(ar)).cost_cents == Decimal("30")

    run_async(_run())


def test_record_rejects_negative() -> None:
    async def _run() -> None:
        engine = _engine(FakeBudgetStore())
        with pytest.raises(ValueError, match=">= 0"):
            await engine.record(
                cost_cents=Decimal("-1"),
                scope=BudgetScope.RUN,
                campaign_run_id=new_campaign_run_id(),
            )

    run_async(_run())


def test_record_missing_run_raises() -> None:
    # A charge against a non-existent run fails loud (symmetric with check) — never silently lost.
    async def _run() -> None:
        engine = _engine(FakeBudgetStore())
        with pytest.raises(BudgetStateNotFound):
            await engine.record(
                cost_cents=Decimal("10"),
                scope=BudgetScope.RUN,
                campaign_run_id=new_campaign_run_id(),
            )

    run_async(_run())


def test_record_missing_account_raises_and_does_not_move_run() -> None:
    async def _run() -> None:
        store = FakeBudgetStore()
        cr = new_campaign_run_id()
        store.set_run(cr, spent=Decimal("0"), cap=Decimal("1000"))
        engine = _engine(store)
        with pytest.raises(BudgetStateNotFound):
            await engine.record(
                cost_cents=Decimal("10"),
                scope=BudgetScope.ACCOUNT,
                campaign_run_id=cr,
                account_run_id=new_run_id(),  # not seeded
            )
        # the run counter must not have moved (the fake checks both rows first, like the DB txn)
        assert (await store.run_state(cr)).spent_cents == Decimal("0")

    run_async(_run())


def test_charge_ties_to_ledger_exactly_once_on_retry() -> None:
    # The exactly-once-charge AC: a retried step (same idempotency key) increments spend ONCE and
    # the increment equals the ledger's recorded cost — record() runs only in the EXECUTE branch.
    async def _run() -> None:
        store = FakeBudgetStore()
        ledger = FakeIdempotencyStore()
        cr, ar, entity = new_campaign_run_id(), new_run_id(), new_entity_id()
        store.set_run(cr, spent=Decimal("0"), cap=Decimal("10000"))
        store.set_account(ar, tier="top", cost=Decimal("0"))
        engine = _engine(store)
        key = account_step_key(ar, entity, "core.employee_count", 1)

        async def step_once() -> None:
            async with idempotent(key, IdempotencyScope.ACCOUNT_STEP, store=ledger) as step:
                if step.is_replay:
                    return
                await engine.record(
                    cost_cents=Decimal("40"),
                    scope=BudgetScope.ACCOUNT,
                    campaign_run_id=cr,
                    account_run_id=ar,
                )
                step.record(result_ref={"claim_ids": ["x"]}, cost_cents=Decimal("40"))

        await step_once()
        await step_once()  # the retry — replays, does NOT re-charge

        assert (await store.run_state(cr)).spent_cents == Decimal("40")  # counted once
        row = await ledger.get(key)
        assert row is not None
        assert row.cost_cents_charged == Decimal("40")  # ties exactly to the spend counter

    run_async(_run())


# --- set_campaign_cap — the client raise/lower loop -----------------------------------------


def test_set_cap_records_cap_raised() -> None:
    async def _run() -> None:
        store = FakeBudgetStore()
        cr = new_campaign_run_id()
        store.set_run(cr, spent=Decimal("100"), cap=Decimal("500"))
        engine = _engine(store)
        await engine.set_campaign_cap(cr, Decimal("900"))  # raise; spent 100 < 900 → no breach
        assert store.kinds() == [BudgetEventKind.CAP_RAISED]
        assert (await store.run_state(cr)).cap_cents == Decimal("900")

    run_async(_run())


def test_set_cap_below_spend_records_breach_pending() -> None:
    async def _run() -> None:
        store = FakeBudgetStore()
        cr = new_campaign_run_id()
        store.set_run(cr, spent=Decimal("700"), cap=Decimal("1000"))
        engine = _engine(store)
        await engine.set_campaign_cap(cr, Decimal("500"))  # lower below spend (700 > 500)
        assert store.kinds() == [BudgetEventKind.CAP_RAISED, BudgetEventKind.BREACH_PENDING]

    run_async(_run())


def test_set_cap_exactly_at_spend_records_breach_pending() -> None:
    # The boundary: cap set to EXACTLY current spend. The RUN pre-gate (spent + 0 >= cap) will
    # graceful-stop here, so set_campaign_cap must record BREACH_PENDING too (inclusive >=) — the
    # two boundaries are provably consistent (the audit isn't silent about a run that gets stopped).
    async def _run() -> None:
        store = FakeBudgetStore()
        cr = new_campaign_run_id()
        store.set_run(cr, spent=Decimal("500"), cap=Decimal("1000"))
        engine = _engine(store)
        await engine.set_campaign_cap(cr, Decimal("500"))  # cap == spent
        assert store.kinds() == [BudgetEventKind.CAP_RAISED, BudgetEventKind.BREACH_PENDING]
        # and the pre-gate's question agrees: at spent==cap the run is out of budget.
        decision = await engine.check(
            scope=BudgetScope.RUN, projected_cents=Decimal("0"), campaign_run_id=cr
        )
        assert decision.verdict is BudgetVerdict.GRACEFUL_STOP

    run_async(_run())


def test_set_cap_rejects_negative() -> None:
    async def _run() -> None:
        engine = _engine(FakeBudgetStore())
        with pytest.raises(ValueError, match=">= 0"):
            await engine.set_campaign_cap(new_campaign_run_id(), Decimal("-1"))

    run_async(_run())


# --- estimate persistence + burn_down --------------------------------------------------------


def test_estimate_persists_for_burndown() -> None:
    async def _run() -> None:
        store = FakeBudgetStore()
        cr = new_campaign_run_id()
        store.set_run(cr, spent=Decimal("0"), cap=Decimal("100000"))
        engine = _engine(store)
        est = await engine.estimate(cr, discovered_count=1000, tier_cutoffs={"top": 0.9})
        assert est.projected_deep_count == 100
        # estimate() persisted the projection so burn_down can show spent-vs-estimate.
        assert (await store.run_state(cr)).estimated_cents == est.estimated_cost_cents

    run_async(_run())


def test_estimate_before_run_exists_is_pure_no_persist() -> None:
    async def _run() -> None:
        store = FakeBudgetStore()
        cr = new_campaign_run_id()  # no run row seeded (a true pre-start estimate)
        engine = _engine(store)
        est = await engine.estimate(cr, discovered_count=10, tier_cutoffs={"top": 0.8})
        assert est.discovered_count == 10  # math still returned
        assert await store.run_state(cr) is None  # persistence no-oped

    run_async(_run())


def test_burn_down_spent_estimate_cap_remaining() -> None:
    async def _run() -> None:
        store = FakeBudgetStore()
        cr = new_campaign_run_id()
        store.set_run(cr, spent=Decimal("300"), cap=Decimal("1000"), estimated=Decimal("750"))
        engine = _engine(store)
        bd = await engine.burn_down(cr)
        assert bd.spent_cents == Decimal("300")
        assert bd.cap_cents == Decimal("1000")
        assert bd.estimated_cents == Decimal("750")
        assert bd.remaining_cents == Decimal("700")

    run_async(_run())


def test_burn_down_over_budget_clamps_remaining_to_zero() -> None:
    async def _run() -> None:
        store = FakeBudgetStore()
        cr = new_campaign_run_id()
        store.set_run(cr, spent=Decimal("1200"), cap=Decimal("1000"))  # over budget
        engine = _engine(store)
        bd = await engine.burn_down(cr)
        # remaining is non-negative (CostCents) — clamped to 0, never a negative.
        assert bd.remaining_cents == Decimal("0")

    run_async(_run())


def test_burn_down_uncapped_reads_zeros() -> None:
    async def _run() -> None:
        store = FakeBudgetStore()
        cr = new_campaign_run_id()
        store.set_run(cr, spent=Decimal("50"), cap=None)
        engine = _engine(store)
        bd = await engine.burn_down(cr)
        assert bd.spent_cents == Decimal("50")
        assert bd.cap_cents == Decimal("0")
        assert bd.remaining_cents == Decimal("0")

    run_async(_run())


def test_burn_down_emits_cost_gauge() -> None:
    async def _run() -> None:
        sink = InMemorySink()
        set_metric_sink(sink)
        try:
            store = FakeBudgetStore()
            cr = new_campaign_run_id()
            store.set_run(cr, spent=Decimal("250"), cap=Decimal("1000"))
            engine = _engine(store)
            await engine.burn_down(cr)
            from clue_obs.otel import ATTR_CAMPAIGN_RUN_ID, METRIC_COST_CAP_CENTS

            assert sink.gauge_value(METRIC_COST_CENTS, **{ATTR_CAMPAIGN_RUN_ID: str(cr)}) == 250.0
            # the cap gauge is emitted when a cap is set (the burn-down's cap line for M13.4)
            assert (
                sink.gauge_value(METRIC_COST_CAP_CENTS, **{ATTR_CAMPAIGN_RUN_ID: str(cr)}) == 1000.0
            )
        finally:
            set_metric_sink(InMemorySink())

    run_async(_run())


def test_burn_down_missing_row_raises() -> None:
    async def _run() -> None:
        engine = _engine(FakeBudgetStore())
        with pytest.raises(BudgetStateNotFound):
            await engine.burn_down(new_campaign_run_id())

    run_async(_run())


def test_caps_are_config_driven_no_code_change() -> None:
    # Changing a band is a config change: two engines with different policies decide differently on
    # the same inputs (the "all caps config-driven" AC).
    async def _run() -> None:
        store = FakeBudgetStore()
        ar = new_run_id()
        store.set_account(ar, tier="top", cost=Decimal("0"))
        loose = BudgetEngine(
            policy=BudgetCaps(per_account_cap_cents={"top": Decimal("1000")}), store=store
        )
        tight = BudgetEngine(
            policy=BudgetCaps(per_account_cap_cents={"top": Decimal("100")}), store=store
        )
        cr = new_campaign_run_id()
        assert (
            await loose.check(
                scope=BudgetScope.ACCOUNT,
                projected_cents=Decimal("500"),
                campaign_run_id=cr,
                account_run_id=ar,
            )
        ).verdict is BudgetVerdict.ALLOW
        assert (
            await tight.check(
                scope=BudgetScope.ACCOUNT,
                projected_cents=Decimal("500"),
                campaign_run_id=cr,
                account_run_id=ar,
            )
        ).verdict is BudgetVerdict.DENY

    run_async(_run())
