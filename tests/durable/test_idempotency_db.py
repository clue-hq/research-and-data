"""DB-gated tests for the M7.4 idempotency ledger — the real Postgres ``idempotency_ledger`` table
and the atomic claim upsert.

These need a reachable, migrated Postgres and ``pytest.skip`` without one. They cover: the two enum
parities (``idempotency_scope`` vs the *core* :class:`IdempotencyScope`; ``idempotency_status`` vs
the durable-internal :class:`IdempotencyStatus`), the ledger round-trip via the repository, the
atomic claim semantics (execute → conflict → replay), ``failed`` re-ownership, stale-``in_progress``
recovery, and the ``completed_at``-iff-``succeeded`` CHECK. All repo calls run inside a rolled-back
transaction, so no committed rows leak.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import IdempotencyScope
from clue_core.field import FieldKey
from clue_core.idempotency import account_step_key
from clue_core.primitives import new_entity_id, new_run_id
from clue_research.durable import IdempotencyStatus
from clue_research.durable.idempotency import (
    ClaimOutcome,
    claim_idempotency_step,
    finish_idempotency_step,
    get_idempotency_ledger,
)
from tests.db.conftest import run_async
from tests.durable.conftest import rollback_conn

pytestmark = pytest.mark.usefixtures("require_durable_db")

_FIFTEEN_MIN = timedelta(minutes=15)


async def _enum_labels(conn: AsyncConnection, typname: str) -> list[str]:
    rows = await conn.execute(
        text(
            "SELECT e.enumlabel FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid "
            "WHERE t.typname = :t ORDER BY e.enumsortorder"
        ),
        {"t": typname},
    )
    return [r[0] for r in rows.all()]


def _a_key() -> str:
    return account_step_key(new_run_id(), new_entity_id(), FieldKey("account.recent_funding"), 2)


def test_idempotency_scope_enum_matches_core() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            labels = await _enum_labels(conn, "idempotency_scope")
        assert labels == [s.value for s in IdempotencyScope]

    run_async(_run())


def test_idempotency_status_enum_matches_db() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            labels = await _enum_labels(conn, "idempotency_status")
        assert labels == [s.value for s in IdempotencyStatus]

    run_async(_run())


def test_ledger_round_trip() -> None:
    async def _run() -> None:
        key = _a_key()
        async with rollback_conn(seed_pack=False) as conn:
            result = await claim_idempotency_step(
                conn, key=key, scope=IdempotencyScope.ACCOUNT_STEP, stale_after=_FIFTEEN_MIN
            )
            assert result.outcome is ClaimOutcome.EXECUTE
            staged = await get_idempotency_ledger(conn, key)
            assert staged is not None
            assert staged.scope is IdempotencyScope.ACCOUNT_STEP
            assert staged.status is IdempotencyStatus.IN_PROGRESS
            assert staged.completed_at is None
            assert staged.cost_cents_charged == Decimal(0)

            await finish_idempotency_step(
                conn,
                key=key,
                status=IdempotencyStatus.SUCCEEDED,
                result_ref={"claim_ids": ["c1", "c2"]},
                cost_cents=Decimal("12"),
            )
            done = await get_idempotency_ledger(conn, key)
            assert done is not None
            assert done.status is IdempotencyStatus.SUCCEEDED
            assert done.completed_at is not None  # the iff invariant
            assert done.result_ref == {"claim_ids": ["c1", "c2"]}
            assert done.cost_cents_charged == Decimal("12")

    run_async(_run())


def test_atomic_claim_execute_then_conflict_then_replay() -> None:
    async def _run() -> None:
        key = _a_key()
        async with rollback_conn(seed_pack=False) as conn:
            first = await claim_idempotency_step(
                conn, key=key, scope=IdempotencyScope.ACCOUNT_STEP, stale_after=_FIFTEEN_MIN
            )
            assert first.outcome is ClaimOutcome.EXECUTE
            # a second claim while the first holder is live (fresh in_progress) is a conflict
            second = await claim_idempotency_step(
                conn, key=key, scope=IdempotencyScope.ACCOUNT_STEP, stale_after=_FIFTEEN_MIN
            )
            assert second.outcome is ClaimOutcome.CONFLICT
            # once it succeeds, a later claim replays the recorded result without re-spending
            await finish_idempotency_step(
                conn,
                key=key,
                status=IdempotencyStatus.SUCCEEDED,
                result_ref={"claim_ids": ["x"]},
                cost_cents=Decimal("5"),
            )
            third = await claim_idempotency_step(
                conn, key=key, scope=IdempotencyScope.ACCOUNT_STEP, stale_after=_FIFTEEN_MIN
            )
            assert third.outcome is ClaimOutcome.REPLAY
            assert third.result_ref == {"claim_ids": ["x"]}
            assert third.cost_cents_charged == Decimal("5")

    run_async(_run())


def test_failed_step_is_re_owned_on_next_claim() -> None:
    async def _run() -> None:
        key = _a_key()
        async with rollback_conn(seed_pack=False) as conn:
            await claim_idempotency_step(
                conn, key=key, scope=IdempotencyScope.ACCOUNT_STEP, stale_after=_FIFTEEN_MIN
            )
            await finish_idempotency_step(
                conn,
                key=key,
                status=IdempotencyStatus.FAILED,
                result_ref={},
                cost_cents=Decimal(0),
            )
            retry = await claim_idempotency_step(
                conn, key=key, scope=IdempotencyScope.ACCOUNT_STEP, stale_after=_FIFTEEN_MIN
            )
            assert retry.outcome is ClaimOutcome.EXECUTE  # failed → re-executable
            row = await get_idempotency_ledger(conn, key)
            assert row is not None and row.status is IdempotencyStatus.IN_PROGRESS

    run_async(_run())


def test_stale_in_progress_is_recovered() -> None:
    async def _run() -> None:
        key = _a_key()
        async with rollback_conn(seed_pack=False) as conn:
            await claim_idempotency_step(
                conn, key=key, scope=IdempotencyScope.ACCOUNT_STEP, stale_after=_FIFTEEN_MIN
            )
            # age the row so its holder looks crashed (older than the staleness window)
            await conn.execute(
                text(
                    "UPDATE idempotency_ledger SET first_seen_at = now() - interval '1 hour' "
                    "WHERE key = :k"
                ),
                {"k": key},
            )
            recovered = await claim_idempotency_step(
                conn, key=key, scope=IdempotencyScope.ACCOUNT_STEP, stale_after=_FIFTEEN_MIN
            )
            assert recovered.outcome is ClaimOutcome.EXECUTE  # stale in_progress re-owned

    run_async(_run())


def test_completed_at_iff_succeeded_check_rejects_violation() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            # a succeeded row with a NULL completed_at violates the iff invariant
            with pytest.raises(Exception, match="completed_at_iff_succeeded"):
                await conn.execute(
                    text(
                        "INSERT INTO idempotency_ledger (key, scope, status, completed_at) "
                        "VALUES (:k, 'account_step', 'succeeded', NULL)"
                    ),
                    {"k": _a_key()},
                )

    run_async(_run())
