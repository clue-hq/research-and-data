"""The deep-phase :class:`AccountScheduler` (M7.3) — parallelism cap + per-entity single-flight.

M7.3 AC: "two concurrent runs cannot deep-research the same ``entity_id`` at once; the parallel
account concurrency limit is enforced." These drive the scheduler with a tracking stand-in graph (no
DB / LangGraph) that records peak concurrency and per-entity overlap, proving the semaphore bounds
fan-out and the injected entity lock single-flights an entity (while distinct entities overlap).
"""

from __future__ import annotations

import asyncio
from collections import Counter
from contextlib import AbstractAsyncContextManager
from typing import Any

import pytest

from clue_core import EntityId, new_campaign_run_id, new_entity_id, new_run_id
from clue_research.durable import (
    AccountRunResult,
    AccountRunStatus,
    AccountScheduler,
    AccountSpec,
)
from tests.db.conftest import run_async


class _TrackingGraph:
    """A stand-in for :class:`AccountResearchGraph` (duck-typed; tests are not mypy-checked).

    Records peak in-flight concurrency and whether two runs for the *same* entity were ever in
    flight at once, then sleeps briefly to create an interleaving window."""

    def __init__(self, *, delay: float = 0.02) -> None:
        self._delay = delay
        self.in_flight = 0
        self.peak = 0
        self._entity_counts: Counter[EntityId] = Counter()
        self.same_entity_overlap = False
        self.ran: list[EntityId] = []

    async def run(
        self,
        entity_id: EntityId,
        *,
        tier: str,
        campaign_run_id: Any,
        checkpointer: Any,
        account_run_id: Any = None,
        workspace_id: str | None = None,
        field_keys: Any = None,
    ) -> AccountRunResult:
        self.ran.append(entity_id)
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        self._entity_counts[entity_id] += 1
        if self._entity_counts[entity_id] > 1:
            self.same_entity_overlap = True
        try:
            await asyncio.sleep(self._delay)
        finally:
            self._entity_counts[entity_id] -= 1
            self.in_flight -= 1
        return AccountRunResult(
            account_run_id=account_run_id or new_run_id(),
            entity_id=entity_id,
            tier=tier,
            status=AccountRunStatus.DONE,
        )


def _per_entity_lock_factory() -> Any:
    """A process-local per-entity lock factory (an ``asyncio.Lock`` per entity) — the testable
    analogue of the Redis entity lock, serializing same-entity runs."""
    locks: dict[EntityId, asyncio.Lock] = {}

    def factory(entity_id: EntityId) -> AbstractAsyncContextManager[Any]:
        return locks.setdefault(entity_id, asyncio.Lock())

    return factory


def test_parallelism_is_capped() -> None:
    graph = _TrackingGraph()
    scheduler = AccountScheduler(graph, max_parallel=2)
    specs = [AccountSpec(entity_id=new_entity_id(), tier="top") for _ in range(6)]

    async def _run() -> None:
        results = await scheduler.run_accounts(
            specs, campaign_run_id=new_campaign_run_id(), checkpointer=None
        )
        assert len(results) == 6
        assert graph.peak <= 2  # the semaphore held the line
        assert graph.peak == 2  # ...and it actually reached the cap (real concurrency)

    run_async(_run())


def test_results_preserve_input_order() -> None:
    graph = _TrackingGraph(delay=0.0)
    scheduler = AccountScheduler(graph, max_parallel=4)
    specs = [AccountSpec(entity_id=new_entity_id(), tier="top") for _ in range(5)]

    async def _run() -> None:
        results = await scheduler.run_accounts(
            specs, campaign_run_id=new_campaign_run_id(), checkpointer=None
        )
        assert [r.entity_id for r in results] == [s.entity_id for s in specs]

    run_async(_run())


def test_entity_lock_single_flights_the_same_entity() -> None:
    graph = _TrackingGraph()
    scheduler = AccountScheduler(graph, max_parallel=8, lock_factory=_per_entity_lock_factory())
    shared = new_entity_id()
    other = new_entity_id()
    # three runs for one entity (must serialize) interleaved with two for another (may overlap)
    specs = [
        AccountSpec(entity_id=shared, tier="top"),
        AccountSpec(entity_id=other, tier="top"),
        AccountSpec(entity_id=shared, tier="top"),
        AccountSpec(entity_id=other, tier="top"),
        AccountSpec(entity_id=shared, tier="top"),
    ]

    async def _run() -> None:
        await scheduler.run_accounts(
            specs, campaign_run_id=new_campaign_run_id(), checkpointer=None
        )
        # the lock prevented two concurrent runs for the same entity...
        assert graph.same_entity_overlap is False
        # ...but distinct entities still overlapped (real parallelism, not accidental serialization)
        assert graph.peak >= 2

    run_async(_run())


def test_without_lock_same_entity_overlaps() -> None:
    # The control: with NO lock factory (semaphore only), same-entity runs DO overlap — proving the
    # single-flight in the previous test is the lock's doing, not an artifact of the harness.
    graph = _TrackingGraph()
    scheduler = AccountScheduler(graph, max_parallel=4)
    shared = new_entity_id()
    specs = [AccountSpec(entity_id=shared, tier="top") for _ in range(3)]

    async def _run() -> None:
        await scheduler.run_accounts(
            specs, campaign_run_id=new_campaign_run_id(), checkpointer=None
        )
        assert graph.same_entity_overlap is True

    run_async(_run())


def test_max_parallel_must_be_positive() -> None:
    with pytest.raises(ValueError, match="max_parallel"):
        AccountScheduler(_TrackingGraph(), max_parallel=0)


# --- M8A.0: the per-account run_one callback -------------------------------------------------
# The deep handler (M8A.2) supplies a custom pipeline (the M8A.1 account→committee→contact
# sequence) that the scheduler must run inside the SAME semaphore + per-entity single-flight slot as
# the default graph.run, so the three-stage sequence inherits the cap + the no-double-research lock.


class _CallbackTracker:
    """Records peak concurrency + per-entity overlap for an injected ``run_one`` callback (the
    callable analogue of :class:`_TrackingGraph`), proving the callback runs inside the scheduler's
    semaphore + entity-lock slot."""

    def __init__(self, *, delay: float = 0.02) -> None:
        self._delay = delay
        self.in_flight = 0
        self.peak = 0
        self._entity_counts: Counter[EntityId] = Counter()
        self.same_entity_overlap = False
        self.seen: list[EntityId] = []

    async def __call__(self, spec: AccountSpec) -> AccountRunResult:
        self.seen.append(spec.entity_id)
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        self._entity_counts[spec.entity_id] += 1
        if self._entity_counts[spec.entity_id] > 1:
            self.same_entity_overlap = True
        try:
            await asyncio.sleep(self._delay)
        finally:
            self._entity_counts[spec.entity_id] -= 1
            self.in_flight -= 1
        return AccountRunResult(
            account_run_id=new_run_id(),
            entity_id=spec.entity_id,
            tier=spec.tier,
            status=AccountRunStatus.DONE,
        )


def test_run_one_callback_runs_capped_in_order_and_bypasses_the_graph() -> None:
    # With run_one supplied, the scheduler drives the callback (NOT the graph) under the semaphore,
    # returning results in input order.
    graph = _TrackingGraph()
    scheduler = AccountScheduler(graph, max_parallel=2)
    run_one = _CallbackTracker()
    specs = [AccountSpec(entity_id=new_entity_id(), tier="top") for _ in range(6)]

    async def _run() -> None:
        results = await scheduler.run_accounts(
            specs, campaign_run_id=new_campaign_run_id(), checkpointer=None, run_one=run_one
        )
        assert len(results) == 6
        assert [r.entity_id for r in results] == [s.entity_id for s in specs]  # input order
        assert run_one.peak == 2  # the semaphore bounded the callback fan-out (reached the cap)
        assert sorted(run_one.seen) == sorted(s.entity_id for s in specs)  # every spec dispatched
        assert graph.ran == []  # the default graph.run was bypassed entirely

    run_async(_run())


def test_run_one_callback_is_single_flighted_by_the_entity_lock() -> None:
    # The callback inherits the per-entity lock: two runs for the same entity never overlap, while
    # distinct entities still run in parallel.
    graph = _TrackingGraph()
    scheduler = AccountScheduler(graph, max_parallel=8, lock_factory=_per_entity_lock_factory())
    run_one = _CallbackTracker()
    shared = new_entity_id()
    other = new_entity_id()
    specs = [
        AccountSpec(entity_id=shared, tier="top"),
        AccountSpec(entity_id=other, tier="top"),
        AccountSpec(entity_id=shared, tier="top"),
        AccountSpec(entity_id=other, tier="top"),
        AccountSpec(entity_id=shared, tier="top"),
    ]

    async def _run() -> None:
        await scheduler.run_accounts(
            specs, campaign_run_id=new_campaign_run_id(), checkpointer=None, run_one=run_one
        )
        assert run_one.same_entity_overlap is False  # the lock serialized the same entity...
        assert run_one.peak >= 2  # ...but distinct entities still overlapped

    run_async(_run())


def test_run_one_callback_may_return_a_non_account_run_result() -> None:
    # The scheduler is generic over the callback's result type: the M8A.1 orchestrator returns a
    # richer references-only AccountDeepResult, not an AccountRunResult. Prove results come
    # back, in input order.
    graph = _TrackingGraph()
    scheduler = AccountScheduler(graph, max_parallel=4)
    specs = [AccountSpec(entity_id=new_entity_id(), tier="top") for _ in range(4)]

    async def deep_run_one(spec: AccountSpec) -> str:
        return f"deep:{spec.entity_id}"

    async def _run() -> None:
        results = await scheduler.run_accounts(
            specs, campaign_run_id=new_campaign_run_id(), checkpointer=None, run_one=deep_run_one
        )
        assert results == [f"deep:{s.entity_id}" for s in specs]
        assert graph.ran == []

    run_async(_run())


def test_run_one_omitted_drives_the_graph_unchanged() -> None:
    # The control: with run_one omitted, the scheduler uses AccountResearchGraph.run exactly as
    # before (the additive callback never perturbs the default account axis).
    graph = _TrackingGraph(delay=0.0)
    scheduler = AccountScheduler(graph, max_parallel=2)
    specs = [AccountSpec(entity_id=new_entity_id(), tier="top") for _ in range(3)]

    async def _run() -> None:
        results = await scheduler.run_accounts(
            specs, campaign_run_id=new_campaign_run_id(), checkpointer=None
        )
        assert [r.entity_id for r in results] == [s.entity_id for s in specs]
        assert sorted(graph.ran) == sorted(s.entity_id for s in specs)  # the graph WAS driven

    run_async(_run())


def test_spec_carries_tenant_and_field_scope() -> None:
    # The per-account graph receives the spec's tenant + field scope (so private resonance/facet
    # claims are read under the right tenant). A recording graph captures what it was handed.
    captured: dict[str, Any] = {}

    class _CapturingGraph(_TrackingGraph):
        async def run(self, entity_id: EntityId, **kwargs: Any) -> AccountRunResult:
            captured.update(kwargs)
            return await super().run(entity_id, **kwargs)

    graph = _CapturingGraph(delay=0.0)
    scheduler = AccountScheduler(graph, max_parallel=1)
    spec = AccountSpec(
        entity_id=new_entity_id(),
        tier="high",
        workspace_id="client-7",
        field_keys=("account.resonance.culture",),
    )

    async def _run() -> None:
        await scheduler.run_accounts(
            [spec], campaign_run_id=new_campaign_run_id(), checkpointer=None
        )
        assert captured["tier"] == "high"
        assert captured["workspace_id"] == "client-7"
        assert captured["field_keys"] == ("account.resonance.culture",)

    run_async(_run())
