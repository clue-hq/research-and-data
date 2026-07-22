"""The idempotency ledger + ``idempotent()`` context manager (M7.4) — exactly-once durable work.

At 5k-account scale research *is defined by* partial failure, rate limits, and long steps; retries
and crash-resumes are constant (substrate §5c, Doc C §4). Without idempotency a retry double-charges
a paid resolver and double-writes claims, and a re-entered phase double-spends. This module is the
runtime that makes M7.1's resumable graph and M7.3's resumable state machine *safe*, not merely
restartable: a single Postgres ``idempotency_ledger`` row per derived key, and an
``idempotent(...)`` context manager that consults it before executing and records the outcome after.

The two key *shapes* are the stable contract and live in ``core`` (pure, dependency-free):
:func:`~clue_core.idempotency.account_step_key` ``(account_run, entity, field, tier)`` and
:func:`~clue_core.idempotency.phase_key` ``(project_run, phase)``. The ledger *backend*
sits behind the :class:`IdempotencyStore` seam, so the dedup mechanism is swappable (Postgres now,
Temporal-native activity dedup later) without changing a single caller — exactly the conventions §2
replaceability rule the rest of M7 follows.

Usage (a worker step or a phase body wraps its effectful section)::

    key = account_step_key(run, entity, field, tier)
    async with idempotent(key, IdempotencyScope.ACCOUNT_STEP) as step:
        if step.is_replay:
            return step.result_ref          # already done — the recorded claim ids, no re-spend
        claim_ids = await do_the_resolver_call_and_write_claims(...)
        step.record(result_ref={"claim_ids": [str(c) for c in claim_ids]}, cost_cents=spent)
        return step.result_ref

The claim is **atomic**: :func:`claim_idempotency_step` inserts ``in_progress`` (or re-owns a
``failed`` / stale row) in one upsert, so two racing holders can never both execute. On a clean exit
the ledger is marked ``succeeded`` with the recorded ``result_ref`` + ``cost_cents_charged`` (the
single charge record M7.5 counts once); on an exception the key is released (``failed``) so a retry
re-executes; on a crash the row is left ``in_progress`` and recovered after a staleness window.

Scope of the guarantee: an **account-step** is exactly-once end to end when its caller writes the
claim and finishes the ledger in one transaction (M8). The **phase** wiring in
:class:`~clue_research.durable.project.ProjectRun` brackets the finalize on ``phase_key`` but
keeps the ``project_phase_checkpoint`` as the authoritative "phase done" record, so a crash in the
narrow window between the durable ``COMMITTED`` checkpoint and the ledger ``succeed`` can leave a
(nominal) phase charge unrecorded — see ``_finalize_phase`` for the precise boundary.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    CostCents,
    IdempotencyScope,
    UtcDatetime,
    parse_value_json,
    serialize_value_json,
)
from clue_db import transaction
from clue_research.durable.enums import IdempotencyStatus

# An ``in_progress`` ledger row older than this is presumed crashed (its holder died mid-step) and
# is re-owned by the next claimant — the stale-recovery window (substrate §5c). Generous by default
# so a legitimately long step is never stolen mid-flight; tune per call site via ``idempotent(...,
# stale_after=…)``. Policy-as-data: a caller passes a shorter window for cheap, fast steps.
DEFAULT_STALE_AFTER = timedelta(minutes=15)


# --- row model -------------------------------------------------------------------------------


class IdempotencyLedgerRow(BaseModel):
    """One ``idempotency_ledger`` row (M7.4) — the exactly-once record of a keyed unit of work.

    ``result_ref`` is the recorded output by reference (claim ids for an account step, a phase
    payload ref for a phase — never blobs); ``cost_cents_charged`` is what the step actually spent
    (the single charge record M7.5's burn-down counts once). ``completed_at`` is non-NULL iff
    ``status`` is ``SUCCEEDED`` (the DB CHECK)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    scope: IdempotencyScope
    status: IdempotencyStatus
    result_ref: dict[str, JsonValue]
    cost_cents_charged: CostCents
    first_seen_at: UtcDatetime
    completed_at: UtcDatetime | None
    updated_at: UtcDatetime


class ClaimOutcome(StrEnum):
    """The verdict of claiming an idempotency key (M7.4) — what the caller should do next.

    * ``EXECUTE`` — the key is now owned by this caller (a fresh insert, or a re-owned ``failed`` /
      stale-``in_progress`` row): run the effectful body, then record the result.
    * ``REPLAY`` — the key already ``succeeded``: skip the body and return the recorded
      ``result_ref`` (the idempotency short-circuit — no re-spend).
    * ``CONFLICT`` — the key is held ``in_progress`` by a *live* holder (not stale): a concurrent
      duplicate. The caller must not execute (it would double-run); :func:`idempotent` raises
      :class:`IdempotencyConflict`.
    """

    EXECUTE = "execute"
    REPLAY = "replay"
    CONFLICT = "conflict"


class ClaimResult(BaseModel):
    """The result of :meth:`IdempotencyStore.claim` — the :class:`ClaimOutcome` plus, for a
    ``REPLAY``, the recorded ``result_ref`` / ``cost_cents_charged`` to return without re-spend."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: ClaimOutcome
    result_ref: dict[str, JsonValue] = {}
    cost_cents_charged: CostCents = Decimal(0)


# --- the repository (the only sanctioned SQL path to idempotency_ledger) ----------------------

# Atomic claim: insert ``in_progress`` if absent, else re-own ONLY a ``failed`` or stale
# ``in_progress`` row (the DO UPDATE ``WHERE``). When the conflict row is succeeded or a live
# ``in_progress``, the predicate is false → no row is updated → ``RETURNING`` is empty, and the
# caller classifies via a follow-up read. This is what makes the claim atomic: two racing holders
# cannot both get a returned row, so they cannot both execute.
_CLAIM_SQL = text(
    """
    INSERT INTO idempotency_ledger (key, scope, status, first_seen_at, updated_at)
    VALUES (:key, CAST(:scope AS idempotency_scope), 'in_progress', now(), now())
    ON CONFLICT (key) DO UPDATE
        SET status = 'in_progress',
            first_seen_at = now(),
            completed_at = NULL,
            result_ref = '{}'::jsonb,
            cost_cents_charged = 0,
            updated_at = now()
        WHERE idempotency_ledger.status = 'failed'
           OR (idempotency_ledger.status = 'in_progress'
               AND idempotency_ledger.first_seen_at <= now() - CAST(:stale AS interval))
    RETURNING key
    """
)

_CLASSIFY_SQL = text(
    "SELECT status, result_ref, cost_cents_charged FROM idempotency_ledger WHERE key = :key"
)

_FINISH_SQL = text(
    """
    UPDATE idempotency_ledger
    SET status = CAST(:status AS idempotency_status),
        result_ref = CAST(:result_ref AS jsonb),
        cost_cents_charged = :cost_cents,
        completed_at = CASE WHEN :status = 'succeeded' THEN now() ELSE NULL END,
        updated_at = now()
    WHERE key = :key
    """
)

_SELECT_COLUMNS = (
    "key, scope, status, result_ref, cost_cents_charged, first_seen_at, completed_at, updated_at"
)

_GET_SQL = text(f"SELECT {_SELECT_COLUMNS} FROM idempotency_ledger WHERE key = :key")


async def claim_idempotency_step(
    conn: AsyncConnection,
    *,
    key: str,
    scope: IdempotencyScope,
    stale_after: timedelta = DEFAULT_STALE_AFTER,
) -> ClaimResult:
    """Atomically claim ``key`` and return what the caller should do (:class:`ClaimResult`).

    One upsert decides ownership: a fresh key, or a ``failed`` / stale-``in_progress`` one, is
    (re-)claimed ``in_progress`` and returns ``EXECUTE``; a ``succeeded`` key returns ``REPLAY``
    with its recorded result; a live ``in_progress`` key returns ``CONFLICT``. The atomicity is in
    the single ``INSERT … ON CONFLICT DO UPDATE … WHERE`` — no read-then-write race window."""
    owned = (
        await conn.execute(_CLAIM_SQL, {"key": key, "scope": scope.value, "stale": stale_after})
    ).first()
    if owned is not None:
        return ClaimResult(outcome=ClaimOutcome.EXECUTE)
    # The conflict row was not re-owned: it is either succeeded (replay) or a live in_progress
    # (conflict). Classify with a follow-up read.
    row = (await conn.execute(_CLASSIFY_SQL, {"key": key})).mappings().one()
    if IdempotencyStatus(row["status"]) is IdempotencyStatus.SUCCEEDED:
        return ClaimResult(
            outcome=ClaimOutcome.REPLAY,
            result_ref=_decode_object(row["result_ref"]),
            cost_cents_charged=row["cost_cents_charged"],
        )
    return ClaimResult(outcome=ClaimOutcome.CONFLICT)


async def finish_idempotency_step(
    conn: AsyncConnection,
    *,
    key: str,
    status: IdempotencyStatus,
    result_ref: dict[str, JsonValue],
    cost_cents: CostCents,
) -> None:
    """Mark a claimed step terminal: ``SUCCEEDED`` (records ``result_ref`` + ``cost_cents`` and
    stamps ``completed_at``) or ``FAILED`` (releases the key for retry; ``completed_at`` cleared).
    ``status`` must not be ``IN_PROGRESS`` (a finish is terminal)."""
    if status is IdempotencyStatus.IN_PROGRESS:
        raise ValueError("finish_idempotency_step records a terminal status, not in_progress")
    await conn.execute(
        _FINISH_SQL,
        {
            "key": key,
            "status": status.value,
            "result_ref": serialize_value_json(result_ref),
            "cost_cents": cost_cents,
        },
    )


async def get_idempotency_ledger(conn: AsyncConnection, key: str) -> IdempotencyLedgerRow | None:
    """Read the ledger row for ``key``, or ``None`` if the key has never been claimed."""
    row = (await conn.execute(_GET_SQL, {"key": key})).mappings().one_or_none()
    return _row_to_ledger(dict(row)) if row is not None else None


def _decode_object(raw: object) -> dict[str, JsonValue]:
    """Decode a JSONB object column to a dict (asyncpg returns it already decoded; bytes from some
    drivers are parsed via the one ``core`` path)."""
    decoded = parse_value_json(bytes(raw)) if isinstance(raw, (bytes, bytearray)) else raw
    return decoded if isinstance(decoded, dict) else {}


def _row_to_ledger(row: dict[str, object]) -> IdempotencyLedgerRow:
    return IdempotencyLedgerRow.model_validate(
        {
            "key": row["key"],
            "scope": row["scope"],
            "status": row["status"],
            "result_ref": _decode_object(row["result_ref"]),
            "cost_cents_charged": row["cost_cents_charged"],
            "first_seen_at": row["first_seen_at"],
            "completed_at": row["completed_at"],
            "updated_at": row["updated_at"],
        }
    )


# --- the persistence seam --------------------------------------------------------------------


@runtime_checkable
class IdempotencyStore(Protocol):
    """The seam :func:`idempotent` drives the ledger through (M7.4).

    Abstracting persistence keeps the context-manager logic testable on an in-memory store and keeps
    the dedup backend swappable (Postgres now → Temporal-native later), per conventions §2. The
    production implementation is :class:`DbIdempotencyStore`."""

    async def claim(
        self, *, key: str, scope: IdempotencyScope, stale_after: timedelta
    ) -> ClaimResult: ...

    async def succeed(
        self, *, key: str, result_ref: dict[str, JsonValue], cost_cents: CostCents
    ) -> None: ...

    async def fail(self, *, key: str) -> None: ...

    async def get(self, key: str) -> IdempotencyLedgerRow | None: ...


class DbIdempotencyStore:
    """The Postgres :class:`IdempotencyStore` — the production dedup path (M7.4).

    Each method runs in its own ``db.transaction()`` (mirroring :class:`DbProjectRunStore`). The
    ``claim`` and the terminal ``succeed`` / ``fail`` are deliberately separate transactions: a
    crash *between* a claim and its finish leaves the row ``in_progress``, recovered by the next
    claimant's staleness check — there is no orphan. For crash-atomicity of the *effect itself*
    (e.g. a claim write committing exactly with the ledger ``succeed``), a caller writes the claim
    and calls the underlying :func:`finish_idempotency_step` inside one transaction; the M1
    append-only/supersede policy dedups any equivalent observation a partial-failure replay
    re-emits."""

    async def claim(
        self, *, key: str, scope: IdempotencyScope, stale_after: timedelta
    ) -> ClaimResult:
        async with transaction() as conn:
            return await claim_idempotency_step(conn, key=key, scope=scope, stale_after=stale_after)

    async def succeed(
        self, *, key: str, result_ref: dict[str, JsonValue], cost_cents: CostCents
    ) -> None:
        async with transaction() as conn:
            await finish_idempotency_step(
                conn,
                key=key,
                status=IdempotencyStatus.SUCCEEDED,
                result_ref=result_ref,
                cost_cents=cost_cents,
            )

    async def fail(self, *, key: str) -> None:
        async with transaction() as conn:
            await finish_idempotency_step(
                conn,
                key=key,
                status=IdempotencyStatus.FAILED,
                result_ref={},
                cost_cents=Decimal(0),
            )

    async def get(self, key: str) -> IdempotencyLedgerRow | None:
        async with transaction() as conn:
            return await get_idempotency_ledger(conn, key)


# --- the context manager ---------------------------------------------------------------------


class IdempotencyConflict(Exception):
    """The key is held ``in_progress`` by a live holder (not stale) — a concurrent duplicate.

    :func:`idempotent` raises this rather than executing (which would double-run). Under M7's
    single-driver-per-run model a fresh-``in_progress`` conflict is rare (a dead holder's row is
    stale, not fresh); a caller that genuinely races can back off and retry (the holder will finish,
    turning the next claim into a ``REPLAY``)."""


class IdempotentStep:
    """The handle :func:`idempotent` yields — tells the caller whether to execute or replay, and
    collects the result to record on a clean exit.

    On a ``REPLAY`` the body is skipped and :attr:`result_ref` / :attr:`cost_cents` are the
    *recorded* values from the prior success. On an ``EXECUTE`` the caller runs its body and calls
    :meth:`record` to stash what to persist; the context manager writes it to the ledger when the
    ``with`` block exits without raising."""

    def __init__(
        self, *, outcome: ClaimOutcome, result_ref: dict[str, JsonValue], cost_cents: CostCents
    ) -> None:
        self._outcome = outcome
        self._prior_result_ref = result_ref
        self._prior_cost = cost_cents
        self._recorded_ref: dict[str, JsonValue] = {}
        self._recorded_cost: CostCents = Decimal(0)

    @property
    def is_replay(self) -> bool:
        """``True`` when the step already succeeded — the caller must skip its body and return
        :attr:`result_ref`."""
        return self._outcome is ClaimOutcome.REPLAY

    @property
    def result_ref(self) -> dict[str, JsonValue]:
        """The recorded output: the prior success's ``result_ref`` on a replay, else what the caller
        has :meth:`record`\\ed this run."""
        return self._prior_result_ref if self.is_replay else self._recorded_ref

    @property
    def cost_cents(self) -> CostCents:
        """The recorded charge: the prior success's on a replay, else what the caller recorded."""
        return self._prior_cost if self.is_replay else self._recorded_cost

    def record(
        self,
        *,
        result_ref: dict[str, JsonValue] | None = None,
        cost_cents: CostCents = Decimal(0),
    ) -> None:
        """Record this step's output (claim ids / a phase payload ref — never blobs) and the cost it
        charged. Persisted to the ledger as ``succeeded`` when the ``with`` block exits cleanly.

        **Optional, with an explicit default.** Omitting ``record`` succeeds the step with an empty
        ``result_ref`` and a zero ``cost_cents_charged`` — the right outcome for a side-effect-only
        idempotent section that produces nothing to replay and charges nothing. A step that *does*
        produce a result a replay must return (a worker writing claims) MUST call ``record`` on the
        EXECUTE path, or its replay returns ``{}`` and its charge is undercounted. A no-op on a
        replay (the prior success's record stands)."""
        if self.is_replay:
            return
        self._recorded_ref = dict(result_ref) if result_ref else {}
        self._recorded_cost = cost_cents


@asynccontextmanager
async def idempotent(
    key: str,
    scope: IdempotencyScope,
    *,
    store: IdempotencyStore | None = None,
    stale_after: timedelta = DEFAULT_STALE_AFTER,
) -> AsyncIterator[IdempotentStep]:
    """Run an effectful section exactly once for ``key`` (M7.4 — the shared idempotency primitive).

    Wrap a worker step or a phase body in ``async with idempotent(key, scope) as step:`` and branch
    on :attr:`step.is_replay <IdempotentStep.is_replay>`:

    * **replay** (the key already ``succeeded``) — the block runs but the caller returns
      ``step.result_ref`` without re-spending; nothing is written back.
    * **execute** — the caller does its work and calls ``step.record(result_ref=…, cost_cents=…)``
      (optional — see :meth:`IdempotentStep.record`; omitting it succeeds with an empty result +
      zero cost, the right default for a side-effect-only step). On a clean exit the ledger is
      marked ``succeeded`` with that result + charge. If the block raises, the key is released
      (``failed``) so a retry (same key) re-executes — the ledger is a dedup gate, never a poison
      pill.
    * **conflict** — a live holder has the key; :class:`IdempotencyConflict` is raised before the
      block runs (executing would double-run).

    ``store`` defaults to :class:`DbIdempotencyStore`; tests/callers inject their own.
    ``stale_after`` overrides how long an ``in_progress`` row is honoured before it is treated as a
    crashed holder."""
    the_store: IdempotencyStore = store if store is not None else DbIdempotencyStore()
    claim = await the_store.claim(key=key, scope=scope, stale_after=stale_after)
    if claim.outcome is ClaimOutcome.CONFLICT:
        raise IdempotencyConflict(key)
    step = IdempotentStep(
        outcome=claim.outcome,
        result_ref=claim.result_ref,
        cost_cents=claim.cost_cents_charged,
    )
    if claim.outcome is ClaimOutcome.REPLAY:
        # Already done — let the caller observe is_replay/result_ref; there is nothing to finalize.
        yield step
        return
    try:
        yield step
    except Exception:
        # The body raised an ordinary error — release the key (``failed``) so an immediate retry
        # under the same key re-executes (the ledger is a dedup gate, never a poison pill). A true
        # cancellation / process kill (``BaseException``) is deliberately *not* caught: it
        # propagates so the run resumes from its checkpoint, and the row left ``in_progress`` is
        # recovered by the staleness window — never a DB write during async teardown (mirrors the
        # M7.1 graph's catch-``Exception``-only convention).
        await the_store.fail(key=key)
        raise
    else:
        # On the EXECUTE path ``result_ref`` / ``cost_cents`` return exactly what the caller
        # recorded (the public properties; no private reach-in).
        await the_store.succeed(key=key, result_ref=step.result_ref, cost_cents=step.cost_cents)


# --- retry-with-backoff (substrate §5c — composes with idempotent over a stable key) ----------


async def retry_async[T](
    factory: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    base_delay: float = 0.2,
    max_delay: float = 10.0,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    """Invoke ``factory`` with bounded exponential backoff, re-raising the last error after
    ``attempts`` tries (substrate §5c — per-step retry with backoff).

    Composes with :func:`idempotent`: because the idempotency key is derived from stable inputs, a
    retried step re-claims the *same* ledger row (a prior ``failed`` is re-owned; a prior success
    becomes a ``REPLAY``), so a retry never charges twice. ``sleep`` is injectable so tests advance
    without real delay. ``attempts`` must be ≥ 1."""
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    last: BaseException | None = None
    for attempt in range(attempts):
        try:
            return await factory()
        except retry_on as exc:
            last = exc
            if attempt + 1 >= attempts:
                break
            await sleep(min(base_delay * (2**attempt), max_delay))
    assert last is not None  # the loop only breaks after setting ``last``
    raise last
