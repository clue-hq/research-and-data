"""Exactly-once spend on the deep committee/contact path (M8A.4) — claim+charge+ledger in one txn.

The M7.5 budget engine's :meth:`~clue_research.durable.budget.BudgetEngine.record` docstring
**explicitly deferred** airtight exactly-once to "the M8 claim-write path … commit the charge and
finish the ledger in one transaction." This module is that path: a single
:meth:`ExactlyOnceSpend.run_step` brackets one deep stage's spend so the worker's claim write(s),
the :meth:`BudgetEngine.record` charge, and the M7.4 idempotency-ledger ``succeed`` all commit on
the **caller's connection** — one transaction. A crash anywhere rolls the whole unit back (the
``in_progress`` ledger insert) → the stage re-executes fresh, never double-charging the client hard
cap; a clean commit makes the stage a ``REPLAY`` that returns the recorded references without
re-spending.

Why this and not the M7.4 :func:`~clue_research.durable.idempotency.idempotent` context manager:
that CM deliberately uses *separate* transactions for the claim and finalize (a crash leaves an
``in_progress`` row recovered by the staleness window) — correct for restartability but it does not
make the *effect* (claim + charge) atomic with the ledger. M8A.4 needs effect-atomicity on the
client-cap counters, so it composes the lower-level conn-taking primitives the substrate exposes
precisely for this (``DbIdempotencyStore`` blesses it: "a caller writes the claim and calls
``finish_idempotency_step`` inside one transaction").

The orchestrator (M8A.1) opens the connection per stage (the committee stage and each ``profile_
contact`` each get one ``session_factory()`` transaction) and threads it through both the worker
*and* ``run_step``; the worker writes its claims on that conn, then ``run_step`` records + finishes
on the same conn. The seam is injected so the orchestrator stays unit-testable with a fake (no DB).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    BudgetScope,
    ClaimId,
    CostCents,
    EntityId,
    IdempotencyScope,
    ProjectRunId,
    RunId,
    idempotency_key,
)
from clue_research.durable import BudgetEngine, IdempotencyConflict
from clue_research.durable.enums import IdempotencyStatus
from clue_research.durable.idempotency import (
    DEFAULT_STALE_AFTER,
    ClaimOutcome,
    claim_idempotency_step,
    finish_idempotency_step,
    get_idempotency_ledger,
)


def deep_step_key(account_run_id: RunId, step: str) -> str:
    """The idempotency key for one deep spend step (M8A.4) — ``(account_run, step)`` under the
    ``ACCOUNT_STEP`` scope, where ``step`` is ``"account"`` / ``"committee"`` / ``"contact:<id>"``.

    Distinct from the M4 :func:`~clue_core.idempotency.account_step_key` (which keys
    ``(account_run, entity, field, tier)`` for one field-fill): a deep stage is a coarser unit — one
    whole committee discovery, or one whole contact profile — so it gets its own stable key.
    Deterministic (no clock, no randomness) so a resumed stage re-derives the same key and
    ``REPLAY``\\s rather than re-spending."""
    return idempotency_key(IdempotencyScope.ACCOUNT_STEP, account_run_id, step)


class Spendable(Protocol):
    """A unit of deep work whose charge the exactly-once step records: it exposes the cost it spent
    and the claim ids it wrote (references only). ``AccountProfileResult`` / ``CommitteeResult`` /
    ``ContactProfileResult`` all satisfy it structurally; :func:`already_done` wraps work whose
    effect already committed on its own transaction (the account axis)."""

    @property
    def cost_cents(self) -> CostCents: ...

    @property
    def claim_refs(self) -> tuple[ClaimId, ...]: ...


@dataclass(frozen=True, slots=True)
class StepInfo:
    """The references-only metadata of one exactly-once spend step (M8A.4).

    ``claim_ids`` and ``cost_cents`` come from the worker on an ``EXECUTE`` and from the recorded
    ledger row on a ``REPLAY`` — so a resumed stage recovers exactly what the original run committed
    without re-spending. ``replayed`` tells the caller whether the charge moved this run (so it does
    not double-count the cost it already booked on the prior run)."""

    replayed: bool
    claim_ids: tuple[str, ...]
    cost_cents: CostCents


class ExactlyOnceSpend(Protocol):
    """The injected exactly-once spend seam the deep orchestrator drives (M8A.4).

    One method brackets a deep stage's spend on the caller's connection. Injected (typed
    structurally, conventions §2) so the orchestrator is unit-testable with an in-memory fake; the
    production binding is :class:`DbExactlyOnceSpend`."""

    async def run_step[R: Spendable](
        self,
        conn: AsyncConnection,
        *,
        key: str,
        project_run_id: ProjectRunId,
        account_run_id: RunId,
        entity_id: EntityId,
        work: Callable[[AsyncConnection], Awaitable[R]],
        stale_after: timedelta = DEFAULT_STALE_AFTER,
    ) -> tuple[R | None, StepInfo]:
        """Run ``work`` exactly once for ``key`` and record its charge — all on ``conn`` (one txn).

        Returns ``(result, info)``: on ``EXECUTE`` ``result`` is what ``work`` produced and the
        charge was recorded this run; on ``REPLAY`` ``result`` is ``None`` and ``info`` carries the
        recorded claim ids + cost (no re-spend). Raises
        :class:`~clue_research.durable.IdempotencyConflict` if a live holder owns the key."""
        ...

    async def recorded(self, conn: AsyncConnection, key: str) -> StepInfo | None:
        """The recorded :class:`StepInfo` if ``key`` already committed a charge (its ledger row is
        ``SUCCEEDED``), else ``None`` — a read-only ledger probe; no claim, charge, or side effect.

        The orchestrator uses this on a resumed contact fan-out to **recover already-paid contacts'
        references directly from the durable ledger, independent of the budget gate** — so a
        cap-saturated resume (every contact already charged → the account is at its cap, so
        ``check`` would ``DENY`` re-admission) cannot drop those contacts' references from
        ``account_run.references_index`` (which M8A.5/M12 read). Only members with **no**
        ``SUCCEEDED`` row go through the budget-admitted :meth:`run_step` path."""
        ...


def already_done[R: Spendable](result: R) -> Callable[[AsyncConnection], Awaitable[R]]:
    """A ``work`` callable for :meth:`ExactlyOnceSpend.run_step` whose effect already committed on
    its own transaction(s) — the account axis: ``profile_account`` opens its own sessions and writes
    the account/resonance claims itself, then this hands the already-computed result to ``run_step``
    so it records the charge + a ledger anchor on the orchestrator's conn. The account axis's
    *claim-write* atomicity stays the M7 graph's domain (spec §M8A.4 keeps it out of scope); this
    only gives its cost a reconciliation anchor and guards a double-record on resume (the ledger
    ``REPLAY``\\s)."""

    async def _work(_conn: AsyncConnection) -> R:
        return result

    return _work


class DbExactlyOnceSpend:
    """The production :class:`ExactlyOnceSpend` (M8A.4).

    Composes the M7.4 ledger (``claim_idempotency_step`` / ``finish_idempotency_step``) with the
    conn-aware M7.5 charge (:meth:`BudgetEngine.record(conn=…)`), so a deep stage's claim writes,
    its budget charge, and its ledger ``succeed`` all commit on the caller's connection — one
    transaction, the airtight exactly-once boundary the V1 caveat deferred. Holds the **concrete**
    :class:`~clue_research.durable.budget.BudgetEngine` (so ``record`` accepts the connection); the
    orchestrator keeps a separate core-typed reference for the admission ``check``."""

    def __init__(self, budget: BudgetEngine) -> None:
        self._budget = budget

    async def run_step[R: Spendable](
        self,
        conn: AsyncConnection,
        *,
        key: str,
        project_run_id: ProjectRunId,
        account_run_id: RunId,
        entity_id: EntityId,
        work: Callable[[AsyncConnection], Awaitable[R]],
        stale_after: timedelta = DEFAULT_STALE_AFTER,
    ) -> tuple[R | None, StepInfo]:
        claim = await claim_idempotency_step(
            conn, key=key, scope=IdempotencyScope.ACCOUNT_STEP, stale_after=stale_after
        )
        if claim.outcome is ClaimOutcome.CONFLICT:
            # A live holder owns the key (a concurrent duplicate). Under M7's single-driver-per-run
            # model this is rare; raising (never executing) is the safe choice — executing would
            # double-run. The conn rolls back; the holder finishes and the next claim REPLAYs.
            raise IdempotencyConflict(key)
        if claim.outcome is ClaimOutcome.REPLAY:
            # Already committed on a prior run — return the recorded refs + charge, no re-spend.
            return None, StepInfo(
                replayed=True,
                claim_ids=_claim_ids(claim.result_ref),
                cost_cents=claim.cost_cents_charged,
            )
        # EXECUTE: run the worker (it writes its claims on ``conn``), charge on the SAME conn, then
        # finish the ledger on it — so all three commit together when the caller's ``with`` exits.
        result = await work(conn)
        claim_ids = tuple(str(c) for c in result.claim_refs)
        await self._budget.record(
            cost_cents=result.cost_cents,
            scope=BudgetScope.ACCOUNT,
            project_run_id=project_run_id,
            entity_id=entity_id,
            account_run_id=account_run_id,
            conn=conn,
        )
        await finish_idempotency_step(
            conn,
            key=key,
            status=IdempotencyStatus.SUCCEEDED,
            result_ref={"claim_ids": list(claim_ids)},
            cost_cents=result.cost_cents,
        )
        return result, StepInfo(replayed=False, claim_ids=claim_ids, cost_cents=result.cost_cents)

    async def recorded(self, conn: AsyncConnection, key: str) -> StepInfo | None:
        row = await get_idempotency_ledger(conn, key)
        if row is None or row.status is not IdempotencyStatus.SUCCEEDED:
            # No row (never run), or in_progress/failed (a crash mid-step) — not a recorded charge,
            # so the caller must run it through run_step (which re-claims / re-executes safely).
            return None
        return StepInfo(
            replayed=True,
            claim_ids=_claim_ids(row.result_ref),
            cost_cents=row.cost_cents_charged,
        )


def _claim_ids(result_ref: dict[str, JsonValue]) -> tuple[str, ...]:
    """The recorded claim ids from a ledger ``result_ref`` (``{"claim_ids": [...]}``), ids-only."""
    ids = result_ref.get("claim_ids", [])
    return tuple(str(c) for c in ids) if isinstance(ids, list) else ()


# Static-time conformance (mirroring ``run_io._DB_ACCOUNT_RUN_IO_IS_AN_IO``): the production binding
# must satisfy the protocol the orchestrator is typed against.
_DB_SPEND_IS_EXACTLY_ONCE: type[ExactlyOnceSpend] = DbExactlyOnceSpend
