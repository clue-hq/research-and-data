"""Pure (no-DB) tests for the M7.4 idempotency primitive — the ``idempotent`` context manager, the
:class:`IdempotencyStore` seam, and ``retry_async``.

These exercise the acceptance criteria on the in-memory :class:`FakeIdempotencyStore`: a step runs
exactly once and a retry-after-success replays the recorded result (no re-spend); a live
``in_progress`` key is a conflict; a stale (crashed) holder is recovered; an exception releases the
key for retry; and key derivation is deterministic. The real Postgres ledger + atomic claim are
covered in ``test_idempotency_db.py``.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from clue_core import (
    IdempotencyScope,
    ProjectPhase,
    new_claim_id,
    new_entity_id,
    new_project_run_id,
    new_run_id,
)
from clue_core.field import FieldKey
from clue_core.idempotency import account_step_key, phase_key
from clue_research.durable import (
    IdempotencyConflict,
    IdempotencyStatus,
    IdempotencyStore,
    idempotent,
    retry_async,
)
from tests.db.conftest import run_async
from tests.durable.conftest import FakeIdempotencyStore

_FIFTEEN_MIN = timedelta(minutes=15)


def _account_key() -> str:
    return account_step_key(new_run_id(), new_entity_id(), FieldKey("account.recent_funding"), 2)


# --- the account-step exactly-once AC ----------------------------------------


def test_account_step_executes_once_then_replays() -> None:
    """The headline AC: the same (account, field, tier) step run twice → exactly one claim write and
    one cost charge; the second call returns the recorded ``result_ref`` without re-spending."""
    store = FakeIdempotencyStore()
    key = _account_key()
    writes: list[str] = []

    async def step() -> dict[str, object]:
        async with idempotent(key, IdempotencyScope.ACCOUNT_STEP, store=store) as s:
            if s.is_replay:
                return s.result_ref
            claim_id = new_claim_id()
            writes.append(str(claim_id))  # the (simulated) claim write — the effectful body
            s.record(result_ref={"claim_ids": [str(claim_id)]}, cost_cents=Decimal("7"))
            return s.result_ref

    first = run_async(step())
    second = run_async(step())

    assert len(writes) == 1  # exactly one claim write
    assert first == second == {"claim_ids": [writes[0]]}  # replay returns the recorded result_ref
    row = run_async(store.get(key))
    assert row is not None
    assert row.status is IdempotencyStatus.SUCCEEDED
    assert row.cost_cents_charged == Decimal("7")  # exactly one charge, not doubled


def test_step_key_is_run_scoped_not_a_global_freshness_lock() -> None:
    """AC #4: idempotency suppresses duplicate work for the *same run's* step, but a later run with
    a genuinely new observation for the same (entity, field, tier) is NOT suppressed — the step key
    is run-scoped, so M1's supersede policy still governs refreshes. Two distinct ``account_run``
    ids → distinct keys → both execute; only a key's *own* retry replays."""
    store = FakeIdempotencyStore()
    entity = new_entity_id()
    field = FieldKey("account.recent_funding")
    key_run_a = account_step_key(new_run_id(), entity, field, 2)
    key_run_b = account_step_key(new_run_id(), entity, field, 2)
    assert key_run_a != key_run_b  # run-scoped, not a global (entity, field, tier) lock

    executed: list[str] = []

    async def step(key: str, run_label: str) -> bool:
        async with idempotent(key, IdempotencyScope.ACCOUNT_STEP, store=store) as s:
            if s.is_replay:
                return False
            executed.append(run_label)
            s.record(result_ref={"run": run_label})
            return True

    assert run_async(step(key_run_a, "A")) is True  # run A executes
    assert run_async(step(key_run_a, "A")) is False  # A's own retry replays (suppressed)
    # a genuinely new observation under a *different* run is NOT masked by A's success
    assert run_async(step(key_run_b, "B")) is True
    assert executed == ["A", "B"]


def test_replay_does_not_re_execute_body() -> None:
    store = FakeIdempotencyStore()
    key = _account_key()
    runs = 0

    async def step() -> None:
        nonlocal runs
        async with idempotent(key, IdempotencyScope.ACCOUNT_STEP, store=store) as s:
            if s.is_replay:
                return
            runs += 1
            s.record(result_ref={"ok": True})

    run_async(step())
    run_async(step())
    run_async(step())
    assert runs == 1


# --- conflict, stale recovery, failure release -------------------------------


def test_fresh_in_progress_is_a_conflict() -> None:
    """A live ``in_progress`` holder (not stale) → the second claimant must not execute."""
    store = FakeIdempotencyStore()
    key = _account_key()
    # Claim and leave it in_progress (the first holder is still "running").
    run_async(store.claim(key=key, scope=IdempotencyScope.ACCOUNT_STEP, stale_after=_FIFTEEN_MIN))

    async def second() -> None:
        async with idempotent(
            key, IdempotencyScope.ACCOUNT_STEP, store=store, stale_after=_FIFTEEN_MIN
        ):
            pass  # pragma: no cover - we never get here

    with pytest.raises(IdempotencyConflict):
        run_async(second())


def test_stale_in_progress_recovers_and_executes() -> None:
    """A crashed holder (stale ``in_progress``) is re-owned and the step re-executes safely."""
    store = FakeIdempotencyStore()
    key = _account_key()
    run_async(store.claim(key=key, scope=IdempotencyScope.ACCOUNT_STEP, stale_after=_FIFTEEN_MIN))
    store.mark_stale(key)  # the holder crashed long ago

    ran = 0

    async def step() -> None:
        nonlocal ran
        async with idempotent(
            key, IdempotencyScope.ACCOUNT_STEP, store=store, stale_after=_FIFTEEN_MIN
        ) as s:
            assert not s.is_replay
            ran += 1
            s.record(result_ref={"recovered": True})

    run_async(step())
    assert ran == 1
    row = run_async(store.get(key))
    assert row is not None and row.status is IdempotencyStatus.SUCCEEDED


def test_exception_releases_key_and_retry_re_executes() -> None:
    """An exception inside the block marks the ledger ``failed`` (not a poison pill) so a retry
    under the same key re-executes; a clean second run then succeeds."""
    store = FakeIdempotencyStore()
    key = _account_key()
    attempts = 0

    async def step(*, boom: bool) -> None:
        nonlocal attempts
        async with idempotent(key, IdempotencyScope.ACCOUNT_STEP, store=store) as s:
            if s.is_replay:
                return
            attempts += 1
            if boom:
                raise RuntimeError("transient")
            s.record(result_ref={"ok": True})

    with pytest.raises(RuntimeError):
        run_async(step(boom=True))
    failed = run_async(store.get(key))
    assert failed is not None and failed.status is IdempotencyStatus.FAILED

    run_async(step(boom=False))  # same key — failed row is re-owned and re-executes
    done = run_async(store.get(key))
    assert done is not None and done.status is IdempotencyStatus.SUCCEEDED
    assert attempts == 2


# --- retry-with-backoff (composes with idempotent over a stable key) ---------


def test_retry_async_retries_then_succeeds() -> None:
    calls = 0
    delays: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        delays.append(seconds)

    async def flaky() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise RuntimeError("transient")
        return "ok"

    result = run_async(retry_async(flaky, attempts=3, base_delay=0.5, sleep=fake_sleep))
    assert result == "ok"
    assert calls == 3
    assert delays == [0.5, 1.0]  # exponential backoff (0.5 * 2**0, 0.5 * 2**1)


def test_retry_async_exhausts_and_raises_last() -> None:
    async def fake_sleep(seconds: float) -> None:
        return None

    async def always() -> None:
        raise ValueError("nope")

    with pytest.raises(ValueError, match="nope"):
        run_async(retry_async(always, attempts=2, sleep=fake_sleep))


def test_retry_async_rejects_zero_attempts() -> None:
    async def noop() -> None:
        return None

    with pytest.raises(ValueError, match="attempts"):
        run_async(retry_async(noop, attempts=0))


def test_retry_over_idempotent_reuses_key_no_double_charge() -> None:
    """A flaky step (fails once, then succeeds) wrapped in ``idempotent`` under a stable key and
    driven by ``retry_async`` records one success/charge — the retry reuses the ledger row."""
    store = FakeIdempotencyStore()
    key = _account_key()
    calls = 0

    async def fake_sleep(seconds: float) -> None:
        return None

    async def step() -> dict[str, object]:
        nonlocal calls
        async with idempotent(key, IdempotencyScope.ACCOUNT_STEP, store=store) as s:
            if s.is_replay:
                return s.result_ref
            calls += 1
            if calls < 2:
                raise RuntimeError("transient")
            s.record(result_ref={"claim_ids": ["c1"]}, cost_cents=Decimal("4"))
            return s.result_ref

    result = run_async(retry_async(step, attempts=3, sleep=fake_sleep))
    assert result == {"claim_ids": ["c1"]}
    assert calls == 2
    row = run_async(store.get(key))
    assert row is not None and row.cost_cents_charged == Decimal("4")  # charged once, not twice


# --- key determinism + protocol conformance ---------------------------------


def test_key_derivation_is_deterministic_and_scope_separated() -> None:
    run_id = new_run_id()
    entity_id = new_entity_id()
    field = FieldKey("account.recent_funding")
    crun = new_project_run_id()

    assert account_step_key(run_id, entity_id, field, 2) == account_step_key(
        run_id, entity_id, field, 2
    )
    assert phase_key(crun, ProjectPhase.DEEP) == phase_key(crun, ProjectPhase.DEEP)
    # Different tier → different key; scope prefixes keep the two shapes disjoint.
    assert account_step_key(run_id, entity_id, field, 2) != account_step_key(
        run_id, entity_id, field, 3
    )
    assert account_step_key(run_id, entity_id, field, 2).startswith("account_step:")
    assert phase_key(crun, ProjectPhase.DEEP).startswith("campaign_phase:")


def test_fake_store_satisfies_protocol() -> None:
    assert isinstance(FakeIdempotencyStore(), IdempotencyStore)
