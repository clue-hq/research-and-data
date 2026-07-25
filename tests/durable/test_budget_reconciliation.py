"""DB-gated tests for M8A.4 exactly-once spend — the conn-aware charge + the single-transaction
``run_step`` (claim + charge + ledger ``succeed``) + cost reconciliation.

These prove the airtight property the M7.5 ``record`` docstring deferred to "the M8 claim-write
path": the spend commits on the **caller's** connection, so a crash (a rolled-back savepoint) leaves
NO charge and NO orphan ledger row, a replay never re-charges, and ``account_run.cost_cents`` ==
``project_run.spent_cents`` == ``SUM(ledger cost_cents_charged)``. Need a reachable migrated
Postgres; ``pytest.skip`` without one. The outer work runs in a rolled-back transaction (and each
simulated crash in a savepoint), so no rows leak.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.deep import DbExactlyOnceSpend, already_done, deep_step_key
from clue_core import (
    BudgetScope,
    ClaimId,
    CostCents,
    ProjectRunId,
    RunId,
    new_claim_id,
    new_entity_id,
    new_project_run_id,
    new_run_id,
)
from clue_research.durable import (
    AccountRunStatus,
    BudgetEngine,
    ensure_project_run,
    get_account_budget_state,
    get_idempotency_ledger,
    get_run_budget_state,
    insert_account_run,
)
from tests._workspace import seed_project
from tests.db.conftest import run_async
from tests.durable.conftest import rollback_conn

pytestmark = pytest.mark.usefixtures("require_durable_db")


class _Boom(Exception):
    """A sentinel crash for the savepoint-rollback tests (distinct so the test catches only it)."""


@dataclass(frozen=True)
class _Work:
    """A minimal :class:`~clue_api.deep.spend.Spendable` for one deep spend step."""

    cost_cents: CostCents
    claim_refs: tuple[ClaimId, ...] = ()


async def _seed(
    conn: AsyncConnection, *, cap: CostCents = Decimal("100000")
) -> tuple[ProjectRunId, RunId]:
    """Seed a fresh project_run (capped) + account_run (RUNNING) so the charge has rows to move."""
    campaign = new_project_run_id()
    account = new_run_id()
    project = await seed_project(conn, "client-1")
    await ensure_project_run(
        conn,
        project_run_id=campaign,
        project_id=project.project_id,
        workspace_id="client-1",
        icp_key="icp-a",
        icp_version=1,
        budget_cap_cents=cap,
    )
    await insert_account_run(
        conn,
        account_run_id=account,
        project_run_id=campaign,
        entity_id=new_entity_id(),
        tier="top",
        status=AccountRunStatus.RUNNING,
    )
    return campaign, account


def _spend() -> DbExactlyOnceSpend:
    return DbExactlyOnceSpend(BudgetEngine())


async def _spent(conn: AsyncConnection, campaign: ProjectRunId) -> CostCents:
    state = await get_run_budget_state(conn, campaign)
    assert state is not None
    return state.spent_cents


async def _account_cost(conn: AsyncConnection, account: RunId) -> CostCents:
    state = await get_account_budget_state(conn, account)
    assert state is not None
    return state.cost_cents


def test_record_with_conn_charges_on_the_callers_transaction() -> None:
    """``record(conn=…)`` increments on the caller's connection — and a rolled-back savepoint
    reverts the charge with it (the atomicity the exactly-once step relies on)."""

    async def _run() -> None:
        engine = BudgetEngine()
        async with rollback_conn(seed_pack=False) as conn:
            campaign, account = await _seed(conn)
            await engine.record(
                cost_cents=Decimal("40"),
                scope=BudgetScope.ACCOUNT,
                project_run_id=campaign,
                account_run_id=account,
                conn=conn,
            )
            assert await _spent(conn, campaign) == Decimal("40")
            assert await _account_cost(conn, account) == Decimal("40")
            # a charge in a savepoint that rolls back leaves no trace — bound to the caller's txn
            try:
                async with conn.begin_nested():
                    await engine.record(
                        cost_cents=Decimal("10"),
                        scope=BudgetScope.ACCOUNT,
                        project_run_id=campaign,
                        account_run_id=account,
                        conn=conn,
                    )
                    raise _Boom
            except _Boom:
                pass
            assert await _spent(conn, campaign) == Decimal("40")  # the 10 was rolled back

    run_async(_run())


def test_run_step_execute_then_replay_charges_exactly_once() -> None:
    """The first ``run_step`` EXECUTEs (charge + ledger ``succeed``); a second on the same key
    REPLAYs (no re-charge, no work) and returns the recorded references + cost."""

    async def _run() -> None:
        spend = _spend()
        cid = new_claim_id()
        async with rollback_conn(seed_pack=False) as conn:
            campaign, account = await _seed(conn)
            key = deep_step_key(account, "contact:x")
            work = already_done(_Work(cost_cents=Decimal("40"), claim_refs=(cid,)))

            result, info = await spend.run_step(
                conn,
                key=key,
                project_run_id=campaign,
                account_run_id=account,
                entity_id=new_entity_id(),
                work=work,
            )
            assert not info.replayed and info.cost_cents == Decimal("40")
            assert info.claim_ids == (str(cid),)
            assert result is not None
            assert await _spent(conn, campaign) == Decimal("40")
            ledger = await get_idempotency_ledger(conn, key)
            assert ledger is not None and ledger.cost_cents_charged == Decimal("40")
            assert ledger.result_ref == {"claim_ids": [str(cid)]}

            # a second run for the same key replays — no re-charge, the recorded refs/cost returned
            again_result, again_info = await spend.run_step(
                conn,
                key=key,
                project_run_id=campaign,
                account_run_id=account,
                entity_id=new_entity_id(),
                work=already_done(_Work(cost_cents=Decimal("999"))),  # would be wrong if it ran
            )
            assert again_info.replayed and again_result is None
            assert again_info.cost_cents == Decimal("40")
            assert again_info.claim_ids == (str(cid),)
            assert await _spent(conn, campaign) == Decimal("40")  # counted exactly once

    run_async(_run())


def test_crash_inside_a_step_rolls_back_the_whole_unit_then_reexecutes_once() -> None:
    """A crash mid-step (the worker raises) rolls back the claim + charge together — no orphan
    ledger row, no charge — and the retried step EXECUTEs exactly once: ``spent_cents`` ends == one
    charge, proving no under-count (a committed claim with an unmoved counter) and no double-pay."""

    async def _run() -> None:
        spend = _spend()

        async def _boom(_conn: AsyncConnection) -> _Work:
            raise _Boom

        async with rollback_conn(seed_pack=False) as conn:
            campaign, account = await _seed(conn)
            key = deep_step_key(account, "contact:x")
            # the worker raises after the ledger claim, before charge/finish — a savepoint rollback
            # un-does the in_progress insert, so there is no orphan and no charge
            try:
                async with conn.begin_nested():
                    await spend.run_step(
                        conn,
                        key=key,
                        project_run_id=campaign,
                        account_run_id=account,
                        entity_id=new_entity_id(),
                        work=_boom,
                    )
            except _Boom:
                pass
            assert await get_idempotency_ledger(conn, key) is None  # the claim row rolled back
            assert await _spent(conn, campaign) == Decimal("0")  # nothing charged

            # the retry re-executes from scratch and charges exactly once
            _, info = await spend.run_step(
                conn,
                key=key,
                project_run_id=campaign,
                account_run_id=account,
                entity_id=new_entity_id(),
                work=already_done(_Work(cost_cents=Decimal("40"), claim_refs=(new_claim_id(),))),
            )
            assert not info.replayed
            assert await _spent(conn, campaign) == Decimal("40")  # exactly one charge

    run_async(_run())


def test_cost_cents_reconciles_with_the_ledger_charge_sum() -> None:
    """After the account/committee/contact spend steps, ``account_run.cost_cents`` ==
    ``project_run.spent_cents`` == ``SUM(ledger cost_cents_charged)`` — ``record`` is the single
    writer (AC2)."""

    async def _run() -> None:
        spend = _spend()
        steps = {
            "account": Decimal("12"),
            "committee": Decimal("7"),
            "contact:a": Decimal("3"),
            "contact:b": Decimal("5"),
        }
        async with rollback_conn(seed_pack=False) as conn:
            campaign, account = await _seed(conn)
            for step, cost in steps.items():
                await spend.run_step(
                    conn,
                    key=deep_step_key(account, step),
                    project_run_id=campaign,
                    account_run_id=account,
                    entity_id=new_entity_id(),
                    work=already_done(_Work(cost_cents=cost, claim_refs=(new_claim_id(),))),
                )
            total = sum(steps.values(), Decimal(0))
            ledger_sum = Decimal(0)
            for step in steps:
                row = await get_idempotency_ledger(conn, deep_step_key(account, step))
                assert row is not None
                ledger_sum += row.cost_cents_charged
            assert ledger_sum == total
            assert await _spent(conn, campaign) == total
            assert await _account_cost(conn, account) == total  # single writer, no clobber

    run_async(_run())
