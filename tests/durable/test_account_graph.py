"""Orchestration tests for :class:`AccountResearchGraph` (M7.1) — LangGraph in-memory saver, no DB.

These exercise the M7.1 acceptance criteria on the in-memory checkpointer with a fake account-run
store and recording stub workers: references-only output, plan-before-spawn, parallel fan-out with
failing-worker isolation, per-node spans, and checkpoint-resume (a completed run re-runs nothing; a
crashed run resumes without re-planning).
"""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from clue_core import new_campaign_run_id, new_entity_id, new_run_id
from clue_research.durable import (
    AccountResearchGraph,
    AccountRunStatus,
    AspectPlan,
    ResearchPlan,
    WorkerRegistry,
)
from clue_research.obs import collect_spans
from tests.db.conftest import run_async
from tests.durable.conftest import FakeAccountRunStore, StubAspectWorker


def _two_aspect_plan() -> ResearchPlan:
    return ResearchPlan(
        tier="top",
        aspects=(
            AspectPlan(aspect="account", field_keys=("account.recent_funding",)),
            AspectPlan(aspect="account.resonance", field_keys=("account.resonance.culture",)),
        ),
    )


def _graph(store: FakeAccountRunStore, *workers: StubAspectWorker) -> AccountResearchGraph:
    registry = WorkerRegistry()
    for worker in workers:
        registry.register(worker)
    return AccountResearchGraph(store=store, workers=registry)


def test_run_produces_references_only() -> None:
    store = FakeAccountRunStore(_two_aspect_plan())
    graph = _graph(
        store,
        StubAspectWorker("account", n_claims=2),
        StubAspectWorker("account.resonance", n_claims=1),
    )

    async def _run() -> None:
        result = await graph.run(
            new_entity_id(),
            tier="top",
            campaign_run_id=new_campaign_run_id(),
            checkpointer=InMemorySaver(),
        )
        assert result.status is AccountRunStatus.DONE
        # references only: ids grouped by aspect, never claim bodies.
        assert set(result.references_index) == {"account", "account.resonance"}
        assert len(result.references_index["account"]) == 2
        assert len(result.references_index["account.resonance"]) == 1
        assert len(result.claim_refs) == 3
        assert result.cost_cents == Decimal("6")  # 2 workers x 3 cents
        # the result payload is bounded by aspect/ref counts, independent of claim content.
        assert all(
            isinstance(ref, str) for refs in result.references_index.values() for ref in refs
        )

    run_async(_run())


def test_plan_is_persisted_before_any_worker_spawns() -> None:
    events: list[str] = []
    store = FakeAccountRunStore(_two_aspect_plan(), events=events)
    graph = _graph(
        store,
        StubAspectWorker("account", events=events),
        StubAspectWorker("account.resonance", events=events),
    )

    async def _run() -> None:
        await graph.run(
            new_entity_id(),
            tier="top",
            campaign_run_id=new_campaign_run_id(),
            checkpointer=InMemorySaver(),
        )
        # the lead's plan (begin) is committed before any worker runs, and collect runs last.
        assert events[0] == "plan"
        assert events[-1] == "collect"
        first_work = next(i for i, e in enumerate(events) if e.startswith("work:"))
        assert events.index("plan") < first_work
        assert store.begin_calls == 1

    run_async(_run())


def test_failing_worker_is_isolated_run_continues() -> None:
    store = FakeAccountRunStore(_two_aspect_plan())
    graph = _graph(
        store,
        StubAspectWorker("account", n_claims=2),
        StubAspectWorker("account.resonance", raise_exc=RuntimeError("boom")),
    )

    async def _run() -> None:
        result = await graph.run(
            new_entity_id(),
            tier="top",
            campaign_run_id=new_campaign_run_id(),
            checkpointer=InMemorySaver(),
        )
        # one aspect failed, but the run completes and the sibling's claims survive.
        assert result.status is AccountRunStatus.DONE
        assert len(result.references_index["account"]) == 2
        assert result.references_index["account.resonance"] == []

    run_async(_run())


def test_all_workers_failing_marks_run_failed() -> None:
    store = FakeAccountRunStore(_two_aspect_plan())
    graph = _graph(
        store,
        StubAspectWorker("account", raise_exc=RuntimeError("a")),
        StubAspectWorker("account.resonance", raise_exc=RuntimeError("b")),
    )

    async def _run() -> None:
        result = await graph.run(
            new_entity_id(),
            tier="top",
            campaign_run_id=new_campaign_run_id(),
            checkpointer=InMemorySaver(),
        )
        assert result.status is AccountRunStatus.FAILED
        assert all(refs == [] for refs in result.references_index.values())

    run_async(_run())


def test_workers_run_in_parallel() -> None:
    # A 2-party barrier: each worker blocks until the other has also started. If the fan-out ran the
    # two workers serially, the first would block forever and wait_for would time out — so reaching
    # the barrier proves they run concurrently (substrate §5b parallel aspect workers).
    barrier = asyncio.Barrier(2)

    async def _wait() -> None:
        await barrier.wait()

    store = FakeAccountRunStore(_two_aspect_plan())
    graph = _graph(
        store,
        StubAspectWorker("account", before=_wait),
        StubAspectWorker("account.resonance", before=_wait),
    )

    async def _run() -> None:
        result = await asyncio.wait_for(
            graph.run(
                new_entity_id(),
                tier="top",
                campaign_run_id=new_campaign_run_id(),
                checkpointer=InMemorySaver(),
            ),
            timeout=5.0,
        )
        assert result.status is AccountRunStatus.DONE

    run_async(_run())


def test_missing_worker_marks_aspect_failed() -> None:
    store = FakeAccountRunStore(_two_aspect_plan())
    # only register a worker for "account"; "account.resonance" has none.
    graph = _graph(store, StubAspectWorker("account", n_claims=1))

    async def _run() -> None:
        result = await graph.run(
            new_entity_id(),
            tier="top",
            campaign_run_id=new_campaign_run_id(),
            checkpointer=InMemorySaver(),
        )
        assert result.status is AccountRunStatus.DONE
        assert len(result.references_index["account"]) == 1
        assert result.references_index["account.resonance"] == []

    run_async(_run())


def test_no_aspects_routes_straight_to_collect() -> None:
    store = FakeAccountRunStore(ResearchPlan(tier="low", aspects=()))
    graph = _graph(store)  # no workers needed

    async def _run() -> None:
        result = await graph.run(
            new_entity_id(),
            tier="low",
            campaign_run_id=new_campaign_run_id(),
            checkpointer=InMemorySaver(),
        )
        assert result.status is AccountRunStatus.DONE
        assert result.references_index == {}
        assert store.begin_calls == 1
        assert store.completed is not None  # collect still ran

    run_async(_run())


def test_per_node_trace_spans_are_emitted() -> None:
    store = FakeAccountRunStore(_two_aspect_plan())
    graph = _graph(
        store,
        StubAspectWorker("account"),
        StubAspectWorker("account.resonance"),
    )

    async def _run() -> None:
        with collect_spans() as spans:
            await graph.run(
                new_entity_id(),
                tier="top",
                campaign_run_id=new_campaign_run_id(),
                checkpointer=InMemorySaver(),
            )
        names = {s.name for s in spans.get_finished_spans()}
        assert {"account.graph.plan", "account.graph.collect", "account.graph.handoff"} <= names
        assert "account.graph.fan_out" in names  # one per aspect worker

    run_async(_run())


def test_resume_completed_run_reruns_nothing() -> None:
    store = FakeAccountRunStore(_two_aspect_plan())
    worker_a = StubAspectWorker("account", n_claims=2)
    worker_b = StubAspectWorker("account.resonance", n_claims=1)
    graph = _graph(store, worker_a, worker_b)

    async def _run() -> None:
        saver = InMemorySaver()
        run_id = new_run_id()
        entity_id = new_entity_id()
        campaign_run_id = new_campaign_run_id()
        first = await graph.run(
            entity_id,
            tier="top",
            campaign_run_id=campaign_run_id,
            checkpointer=saver,
            account_run_id=run_id,
        )
        assert worker_a.calls == 1 and worker_b.calls == 1 and store.begin_calls == 1

        # Re-invoke the SAME thread (account_run_id) + checkpointer: the run already finished, so
        # nothing re-runs — no re-planned plan, no re-spawned workers (checkpoint resume).
        second = await graph.run(
            entity_id,
            tier="top",
            campaign_run_id=campaign_run_id,
            checkpointer=saver,
            account_run_id=run_id,
        )
        assert worker_a.calls == 1 and worker_b.calls == 1 and store.begin_calls == 1
        assert second.references_index == first.references_index
        assert second.status is first.status

    run_async(_run())


def test_crash_mid_fan_out_resumes_without_replanning() -> None:
    # A worker that aborts the run by raising a BaseException (which the node deliberately does NOT
    # catch — only Exception is isolated) on its first attempt, then succeeds. After the crash, the
    # plan super-step is already checkpointed, so resuming re-runs the fan-out but NOT the lead's
    # plan (begin stays at one call) — the M7.1 "resume from the last checkpoint" guarantee. The
    # per-step worker dedup of the re-run fan-out is layered on by M7.4.
    class _Crash(BaseException):
        pass

    state = {"crashed": False}

    async def _crash_once() -> None:
        if not state["crashed"]:
            state["crashed"] = True
            raise _Crash()

    store = FakeAccountRunStore(
        ResearchPlan(
            tier="top",
            aspects=(AspectPlan(aspect="account", field_keys=("account.recent_funding",)),),
        )
    )
    graph = _graph(store, StubAspectWorker("account", before=_crash_once))

    async def _run() -> None:
        saver = InMemorySaver()
        run_id = new_run_id()
        entity_id = new_entity_id()
        campaign_run_id = new_campaign_run_id()
        with pytest.raises(BaseException):  # noqa: B017,PT011 — the deliberate crash aborts run 1
            await graph.run(
                entity_id,
                tier="top",
                campaign_run_id=campaign_run_id,
                checkpointer=saver,
                account_run_id=run_id,
            )
        assert store.begin_calls == 1  # the plan was committed before the crash

        result = await graph.run(
            entity_id,
            tier="top",
            campaign_run_id=campaign_run_id,
            checkpointer=saver,
            account_run_id=run_id,
        )
        # resumed to completion; the lead never re-planned (still one begin call).
        assert result.status is AccountRunStatus.DONE
        assert store.begin_calls == 1
        assert len(result.references_index["account"]) == 1

    run_async(_run())
