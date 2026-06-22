"""The deep-phase account scheduler (M7.3) — bounded parallelism + per-entity single-flight.

The campaign state machine owns phase ordering; within the ``deep`` phase it must also own
*concurrency*: how many per-account graphs (M7.1) run at once, and the guarantee that two campaign
runs never deep-research the **same** ``entity_id`` simultaneously (Doc C §4; substrate §5c). This
module is that scheduler.

* **Parallelism cap** — an ``asyncio.Semaphore(max_parallel)`` bounds in-flight per-account graphs
  (the cost dial's "accounts per pass" half; tuned by tier/budget).
* **Single-flight per entity** — each account runs inside a Redis in-flight lock (M2.4
  :func:`~clue_research.locks.entity_lock`) keyed on its ``entity_id``, so a second run for the same
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
from collections.abc import Callable, Iterable, Sequence
from contextlib import AbstractAsyncContextManager
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from pydantic import BaseModel, ConfigDict

from clue_research.core import CampaignRunId, EntityId, EntityType
from clue_research.durable.graph import AccountResearchGraph, AccountRunResult
from clue_research.locks import DEFAULT_TTL_MS, entity_lock

# A factory the scheduler calls per entity to obtain the in-flight lock context manager. Injectable
# so tests can supply a process-local lock (no Redis) and prod supplies the Redis entity lock.
LockFactory = Callable[[EntityId], AbstractAsyncContextManager[Any]]


class AccountSpec(BaseModel):
    """One account to deep-research in the ``deep`` phase (M7.3) — the entity, its tier, and the
    tenant/field scope the per-account graph runs under."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_id: EntityId
    tier: str
    tenant_id: str | None = None
    field_keys: tuple[str, ...] | None = None


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
    fan-out nor a concurrent campaign run can exceed the cap or double-research an entity."""

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

    async def run_accounts(
        self,
        specs: Iterable[AccountSpec],
        *,
        campaign_run_id: CampaignRunId,
        checkpointer: BaseCheckpointSaver[Any],
    ) -> list[AccountRunResult]:
        """Research every account, at most ``max_parallel`` at a time, each single-flighted by its
        entity lock. Results come back in input order (``asyncio.gather``). One account raising
        propagates — the caller (the M8 ``deep`` handler) decides per-account isolation policy."""
        ordered: Sequence[AccountSpec] = tuple(specs)
        return list(
            await asyncio.gather(
                *(
                    self._run_one(spec, campaign_run_id=campaign_run_id, checkpointer=checkpointer)
                    for spec in ordered
                )
            )
        )

    async def _run_one(
        self,
        spec: AccountSpec,
        *,
        campaign_run_id: CampaignRunId,
        checkpointer: BaseCheckpointSaver[Any],
    ) -> AccountRunResult:
        async with self._semaphore:
            if self._lock_factory is None:
                return await self._invoke(spec, campaign_run_id, checkpointer)
            async with self._lock_factory(spec.entity_id):
                return await self._invoke(spec, campaign_run_id, checkpointer)

    async def _invoke(
        self,
        spec: AccountSpec,
        campaign_run_id: CampaignRunId,
        checkpointer: BaseCheckpointSaver[Any],
    ) -> AccountRunResult:
        return await self._graph.run(
            spec.entity_id,
            tier=spec.tier,
            campaign_run_id=campaign_run_id,
            checkpointer=checkpointer,
            tenant_id=spec.tenant_id,
            field_keys=spec.field_keys,
        )
