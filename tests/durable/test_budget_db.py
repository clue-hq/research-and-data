"""DB-gated tests for the M7.5 cost-governance persistence — the ``budget_event`` table, the
``account_run.budget_cap_cents`` / ``campaign_run.estimated_cents`` columns, and the cost-accounting
repository helpers.

These need a reachable, migrated Postgres and ``pytest.skip`` without one. They cover: the two enum
parities (``budget_scope`` vs the *core* :class:`BudgetScope`; the durable-internal
:class:`BudgetEventKind`), the ``budget_event`` append-only round-trip (insert/list ordered by the
monotonic ``seq`` + the immutability trigger), the run/account spend counters + the cap/estimate
setters, and the new column CHECKs. Repo calls run in a rolled-back transaction, so no rows leak.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.core import (
    BudgetScope,
    new_campaign_run_id,
    new_entity_id,
    new_run_id,
)
from clue_research.durable import (
    AccountRunStatus,
    BudgetEventKind,
    add_account_spend,
    add_run_spend,
    ensure_campaign_run,
    get_account_budget_state,
    get_run_budget_state,
    insert_account_run,
    insert_budget_event,
    list_budget_events,
    set_account_budget_cap,
    set_estimated_cents,
)
from tests.db.conftest import run_async
from tests.durable.conftest import rollback_conn

pytestmark = pytest.mark.usefixtures("require_durable_db")


async def _enum_labels(conn: AsyncConnection, typname: str) -> list[str]:
    rows = await conn.execute(
        text(
            "SELECT e.enumlabel FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid "
            "WHERE t.typname = :t ORDER BY e.enumsortorder"
        ),
        {"t": typname},
    )
    return [r[0] for r in rows.all()]


# --- enum parity -----------------------------------------------------------------------------


def test_budget_scope_enum_matches_core() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            labels = await _enum_labels(conn, "budget_scope")
        assert labels == [s.value for s in BudgetScope]

    run_async(_run())


def test_budget_event_kind_enum_matches_db() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            labels = await _enum_labels(conn, "budget_event_kind")
        assert labels == [k.value for k in BudgetEventKind]

    run_async(_run())


# --- budget_event append-only round-trip -----------------------------------------------------


def test_budget_event_insert_and_list_ordered_by_seq() -> None:
    async def _run() -> None:
        run_id = new_campaign_run_id()
        async with rollback_conn(seed_pack=False) as conn:
            await insert_budget_event(
                conn,
                campaign_run_id=run_id,
                scope=BudgetScope.ACCOUNT,
                kind=BudgetEventKind.CHECK_DENY,
                projected_cents=Decimal("120"),
                cap_cents=Decimal("100"),
                detail={"entity_id": "e1"},
            )
            await insert_budget_event(
                conn,
                campaign_run_id=run_id,
                scope=BudgetScope.RUN,
                kind=BudgetEventKind.GRACEFUL_STOP,
                projected_cents=Decimal("0"),
                cap_cents=Decimal("500"),
                detail=None,
            )
            rows = await list_budget_events(conn, run_id)
        assert [r.kind for r in rows] == [
            BudgetEventKind.CHECK_DENY,
            BudgetEventKind.GRACEFUL_STOP,
        ]
        assert rows[0].scope is BudgetScope.ACCOUNT
        assert rows[0].projected_cents == Decimal("120")
        assert rows[0].cap_cents == Decimal("100")
        assert rows[0].detail == {"entity_id": "e1"}
        assert rows[1].cap_cents == Decimal("500")
        assert rows[1].detail == {}
        # the monotonic seq strictly increases (the stable audit order)
        assert rows[0].seq < rows[1].seq

    run_async(_run())


def test_budget_event_nullable_cap() -> None:
    async def _run() -> None:
        run_id = new_campaign_run_id()
        async with rollback_conn(seed_pack=False) as conn:
            await insert_budget_event(
                conn,
                campaign_run_id=run_id,
                scope=BudgetScope.PASS,
                kind=BudgetEventKind.CHECK_DENY,
                projected_cents=Decimal("9"),
                cap_cents=None,
                detail=None,
            )
            rows = await list_budget_events(conn, run_id)
        assert rows[0].cap_cents is None

    run_async(_run())


def test_budget_event_kind_scope_check_rejects_mismatch() -> None:
    # The DB refuses a semantically impossible (scope, kind): cap_raised is run-scoped, not account.
    async def _run() -> None:
        run_id = new_campaign_run_id()
        async with rollback_conn(seed_pack=False) as conn:
            with pytest.raises(Exception, match="budget_event_kind_scope"):
                await insert_budget_event(
                    conn,
                    campaign_run_id=run_id,
                    scope=BudgetScope.ACCOUNT,  # mismatched: cap_raised is RUN-only
                    kind=BudgetEventKind.CAP_RAISED,
                    projected_cents=Decimal("0"),
                    cap_cents=Decimal("100"),
                )

    run_async(_run())


def test_budget_event_is_immutable_update() -> None:
    async def _run() -> None:
        run_id = new_campaign_run_id()
        async with rollback_conn(seed_pack=False) as conn:
            await insert_budget_event(
                conn,
                campaign_run_id=run_id,
                scope=BudgetScope.RUN,
                kind=BudgetEventKind.CAP_RAISED,
                projected_cents=Decimal("0"),
                cap_cents=Decimal("1000"),
            )
            with pytest.raises(Exception, match="append-only"):
                await conn.execute(
                    text("UPDATE budget_event SET kind = 'check_deny' WHERE campaign_run_id = :r"),
                    {"r": run_id},
                )

    run_async(_run())


def test_budget_event_rejects_delete() -> None:
    async def _run() -> None:
        run_id = new_campaign_run_id()
        async with rollback_conn(seed_pack=False) as conn:
            await insert_budget_event(
                conn,
                campaign_run_id=run_id,
                scope=BudgetScope.RUN,
                kind=BudgetEventKind.CAP_RAISED,
                projected_cents=Decimal("0"),
                cap_cents=Decimal("1000"),
            )
            with pytest.raises(Exception, match="append-only"):
                await conn.execute(
                    text("DELETE FROM budget_event WHERE campaign_run_id = :r"),
                    {"r": run_id},
                )

    run_async(_run())


# --- run-scope counters / cap / estimate (campaign_run columns) ------------------------------


def test_run_budget_state_spend_and_estimate() -> None:
    async def _run() -> None:
        run_id = new_campaign_run_id()
        async with rollback_conn(seed_pack=False) as conn:
            await ensure_campaign_run(
                conn,
                campaign_run_id=run_id,
                client_id="c",
                icp_key="k",
                icp_version=1,
                budget_cap_cents=Decimal("1000"),
            )
            # fresh run: spent 0, cap 1000, estimate not yet set
            state = await get_run_budget_state(conn, run_id)
            assert state is not None
            assert state.spent_cents == Decimal("0")
            assert state.cap_cents == Decimal("1000")
            assert state.estimated_cents is None

            await add_run_spend(conn, run_id, Decimal("250"))
            await add_run_spend(conn, run_id, Decimal("75"))
            await set_estimated_cents(conn, run_id, Decimal("900"))
            state = await get_run_budget_state(conn, run_id)
        assert state is not None
        assert state.spent_cents == Decimal("325")  # accumulated
        assert state.estimated_cents == Decimal("900")

    run_async(_run())


def test_run_budget_state_missing_is_none() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            state = await get_run_budget_state(conn, new_campaign_run_id())
        assert state is None

    run_async(_run())


def test_campaign_run_estimated_nonneg_check() -> None:
    async def _run() -> None:
        run_id = new_campaign_run_id()
        async with rollback_conn(seed_pack=False) as conn:
            await ensure_campaign_run(
                conn, campaign_run_id=run_id, client_id="c", icp_key="k", icp_version=1
            )
            with pytest.raises(Exception, match="estimated_nonneg"):
                await conn.execute(
                    text("UPDATE campaign_run SET estimated_cents = -1 WHERE id = :id"),
                    {"id": run_id},
                )

    run_async(_run())


# --- account-scope counter / cap (account_run columns) --------------------------------------


async def _seed_account(conn: AsyncConnection, *, tier: str) -> tuple[object, object]:
    run_id = new_run_id()
    await insert_account_run(
        conn,
        account_run_id=run_id,
        campaign_run_id=new_campaign_run_id(),
        entity_id=new_entity_id(),
        tier=tier,
        status=AccountRunStatus.RUNNING,
    )
    return run_id, None


def test_account_budget_state_spend_and_cap() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            run_id, _ = await _seed_account(conn, tier="top")
            state = await get_account_budget_state(conn, run_id)
            assert state is not None
            assert state.cost_cents == Decimal("0")
            assert state.tier == "top"
            assert state.budget_cap_cents is None  # the new column defaults NULL

            await add_account_spend(conn, run_id, Decimal("40"))
            await add_account_spend(conn, run_id, Decimal("10"))
            await set_account_budget_cap(conn, run_id, Decimal("500"))
            state = await get_account_budget_state(conn, run_id)
        assert state is not None
        assert state.cost_cents == Decimal("50")
        assert state.budget_cap_cents == Decimal("500")

    run_async(_run())


def test_account_budget_cap_can_be_cleared() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            run_id, _ = await _seed_account(conn, tier="high")
            await set_account_budget_cap(conn, run_id, Decimal("100"))
            await set_account_budget_cap(conn, run_id, None)  # clear it
            state = await get_account_budget_state(conn, run_id)
        assert state is not None
        assert state.budget_cap_cents is None

    run_async(_run())


def test_account_run_budget_cap_nonneg_check() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            run_id, _ = await _seed_account(conn, tier="top")
            with pytest.raises(Exception, match="budget_cap_nonneg"):
                await conn.execute(
                    text("UPDATE account_run SET budget_cap_cents = -5 WHERE id = :id"),
                    {"id": run_id},
                )

    run_async(_run())


def test_account_budget_state_missing_is_none() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            state = await get_account_budget_state(conn, new_run_id())
        assert state is None

    run_async(_run())
