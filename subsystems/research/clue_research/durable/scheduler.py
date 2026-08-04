"""The deep-phase account scheduler (M7.3) — bounded parallelism + per-entity single-flight.

The campaign state machine owns phase ordering; within the ``deep`` phase it must also own
*concurrency*: how many per-account graphs (M7.1) run at once, and the guarantee that two campaign
runs never deep-research the **same** ``entity_id`` simultaneously (Doc C §4; substrate §5c). This
module is that scheduler.

* **Parallelism cap** — an ``asyncio.Semaphore(max_parallel)`` bounds in-flight per-account graphs
  (the cost dial's "accounts per pass" half; tuned by tier/budget).
* **Single-flight per entity** — each account runs inside a Redis in-flight lock (M2.4
  :func:`~clue_locks.entity_lock`) keyed on its ``entity_id``, so a second run for the same
  account waits rather than double-researching it (and double-spending). The lock is acquired
  through an injectable ``lock_factory`` seam, so the scheduler is testable without Redis and the
  lock backend stays swappable (conventions §2); :func:`account_entity_lock_factory` is the
  production factory the api root wires from ``get_redis()``.

The per-account work itself (planning, fan-out, recursion, claim writes) is entirely M7.1/M7.2 +
M8 behind :meth:`~clue_research.durable.graph.AccountResearchGraph.run`; this scheduler only bounds
and serializes it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Sequence
from contextlib import AbstractAsyncContextManager
from typing import Any, TypeVar, overload

from langgraph.checkpoint.base import BaseCheckpointSaver
from pydantic import BaseModel, ConfigDict, Field

from clue_core import CostCents, EntityId, EntityType, ProjectRunId, ResearchDirectivePin
from clue_locks import DEFAULT_TTL_MS, entity_lock
from clue_research.durable.graph import AccountResearchGraph, AccountRunResult

# A factory the scheduler calls per entity to obtain the in-flight lock context manager. Injectable
# so tests can supply a process-local lock (no Redis) and prod supplies the Redis entity lock.
LockFactory = Callable[[EntityId], AbstractAsyncContextManager[Any]]

_RunResultT = TypeVar("_RunResultT")


class AccountSpec(BaseModel):
    """One account to deep-research in the ``deep`` phase (M7.3) — the entity, its tier, and the
    tenant/field scope the per-account graph runs under."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_id: EntityId
    tier: str
    workspace_id: str | None = None
    field_keys: tuple[str, ...] | None = None
    research_directive: ResearchDirectivePin | None = None
    budget_cap_cents: CostCents | None = Field(default=None, ge=0)


# A per-account callback the deep handler (M8A.2) supplies to drive a *custom* pipeline — the M8A.1
# account→committee→contact sequence — inside the scheduler's bounded-parallelism + per-entity
# single-flight slot, in place of the default ``AccountResearchGraph.run``. It receives the resolved
# spec and returns the per-account result (the ``project_run_id`` / ``checkpointer`` it needs are
# bound by the caller's closure, so the scheduler stays agnostic to the pipeline's shape). Omitting
# it preserves today's ``graph.run`` path exactly.
RunOne = Callable[[AccountSpec], Awaitable[_RunResultT]]


def account_entity_lock_factory(redis: Any, *, ttl_ms: int = DEFAULT_TTL_MS) -> LockFactory:
    """The production :data:`LockFactory`: a Redis in-flight account lock per entity (M2.4).

    Wired at the api composition root from ``get_redis()``; uses the auto-renewing ``async with``
    form so a long deep-research run never has its lease preempted (the M2.4 heartbeat)."""

    def _factory(entity_id: EntityId) -> AbstractAsyncContextManager[Any]:
        return entity_lock(redis, EntityType.ACCOUNT, entity_id, ttl_ms=ttl_ms)

    return _factory


class AccountScheduler:
    """Bounded, single-flighted scheduler for per-account graphs in the ``deep`` phase (M7.3).

    Construct with the :class:`~clue_research.durable.graph.AccountResearchGraph`, a parallelism
    cap, and (in prod) a ``lock_factory``; call :meth:`run_accounts` with the accounts to research.
    Each account is gated by the semaphore *and* its per-entity lock, so neither the in-process
    fan-out nor a concurrent project run can exceed the cap or double-research an entity."""

    def __init__(
        self,
        graph: AccountResearchGraph,
        *,
        max_parallel: int,
        lock_factory: LockFactory | None = None,
    ) -> None:
        if max_parallel < 1:
            raise ValueError(f"max_parallel must be >= 1 (got {max_parallel})")
        self._graph = graph
        self._semaphore = asyncio.Semaphore(max_parallel)
        self._lock_factory = lock_factory

    @overload
    async def run_accounts(
        self,
        specs: Iterable[AccountSpec],
        *,
        project_run_id: ProjectRunId,
        checkpointer: BaseCheckpointSaver[Any],
        run_one: None = None,
    ) -> list[AccountRunResult]: ...

    @overload
    async def run_accounts(
        self,
        specs: Iterable[AccountSpec],
        *,
        project_run_id: ProjectRunId,
        checkpointer: BaseCheckpointSaver[Any],
        run_one: RunOne[_RunResultT],
    ) -> list[_RunResultT]: ...

    async def run_accounts(
        self,
        specs: Iterable[AccountSpec],
        *,
        project_run_id: ProjectRunId,
        checkpointer: BaseCheckpointSaver[Any],
        run_one: RunOne[Any] | None = None,
    ) -> list[Any]:
        """Research every account, at most ``max_parallel`` at a time, each single-flighted by its
        entity lock. Results come back in input order (``asyncio.gather``). One account raising
        propagates — the caller (the M8A ``deep`` handler) decides per-account isolation policy.

        ``run_one`` (M8A.0) overrides what runs *inside* each account's semaphore + single-flight
        slot: when supplied, the scheduler invokes ``run_one(spec)`` (the M8A.1 per-account
        ``account → committee → contact`` pipeline) instead of :meth:`AccountResearchGraph.run`, so
        the same bounded + entity-lock guarantees cover the three-stage sequence. Omitted (the
        default), the account axis behaves exactly as before."""
        ordered: Sequence[AccountSpec] = tuple(specs)
        return list(
            await asyncio.gather(
                *(
                    self._run_one(
                        spec,
                        project_run_id=project_run_id,
                        checkpointer=checkpointer,
                        run_one=run_one,
                    )
                    for spec in ordered
                )
            )
        )

    async def _run_one(
        self,
        spec: AccountSpec,
        *,
        project_run_id: ProjectRunId,
        checkpointer: BaseCheckpointSaver[Any],
        run_one: RunOne[Any] | None,
    ) -> Any:
        async def _go() -> Any:
            if run_one is not None:
                return await run_one(spec)
            return await self._invoke(spec, project_run_id, checkpointer)

        async with self._semaphore:
            if self._lock_factory is None:
                return await _go()
            async with self._lock_factory(spec.entity_id):
                return await _go()

    async def _invoke(
        self,
        spec: AccountSpec,
        project_run_id: ProjectRunId,
        checkpointer: BaseCheckpointSaver[Any],
    ) -> AccountRunResult:
        kwargs: dict[str, Any] = {
            "tier": spec.tier,
            "project_run_id": project_run_id,
            "checkpointer": checkpointer,
            "workspace_id": spec.workspace_id,
            "field_keys": spec.field_keys,
        }
        if spec.research_directive is not None:
            kwargs["research_directive"] = spec.research_directive
        return await self._graph.run(spec.entity_id, **kwargs)
