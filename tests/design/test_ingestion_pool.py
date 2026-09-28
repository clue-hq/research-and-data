"""Isolation and lifecycle regressions; no provider calls."""

import asyncio
from types import SimpleNamespace
from uuid import uuid4

from lumen_api.fleet_handler import build_design_job_handler
from lumen_api.ingestion_pool import desired_roles, supervise
from lumen_api.ingestion_tasks import AssetAnalysisWorkHandler, collect_summary, image_envelope
from py_lumen_config import settings

from clue_fleet.queue import TaskCapability


def test_execution_pools_are_disjoint_and_fail_closed():
    handlers = {
        "primary": build_design_job_handler(),
        "ingestion": build_design_job_handler(ingestion_only=True),
        "analysis": AssetAnalysisWorkHandler(),
    }
    for name, handler in handlers.items():
        for kind in ["agent_turn", "web_turn", "ingestion", "asset_analysis", "future", None]:
            payload = {"kind": kind} if kind is not None else {}
            admitted = all(cap.permits(payload) for cap in handler.task_capabilities)
            expected = kind in (
                {"agent_turn", "web_turn"}
                if name == "primary"
                else {"ingestion"}
                if name == "ingestion"
                else {"asset_analysis"}
            )
            assert admitted == expected, (name, kind)
    required = TaskCapability(field="kind", supported=frozenset({"ingestion"}), required=True)
    assert not required.permits({"kind": []})
    assert not required.permits({"kind": None})


def test_image_identity_dedupes_replay_but_changes_with_parent_generation():
    first = image_envelope("ws", "job", 1, "image", {"kind": "photo"})
    assert first == image_envelope("ws", "job", 1, "image", {"kind": "photo"})
    assert first.work_id != image_envelope("ws", "job", 2, "image", {"kind": "photo"}).work_id
    assert first.work_id != image_envelope("other", "job", 1, "image", {"kind": "photo"}).work_id


def test_failed_child_does_not_hang_or_reuse_an_old_ready_row():
    work_id = uuid4()
    result = collect_summary(
        {"image": work_id}, {work_id: {"status": "failed"}}, {"image": {"status": "ready"}}
    )
    assert result["failed"] == 1 and result["pending"] == result["ready"] == 0
    assert result["results"]["image"]["status"] == "failed"


def test_multiple_ingestions_share_four_workers(monkeypatch):
    monkeypatch.setattr(settings, "lumen_ingestion_pool_workers", 4)
    assert desired_roles(8, 1000) == ["coordinator"] + ["analysis"] * 4
    assert desired_roles(1, 0) == ["coordinator"]
    assert desired_roles(0, 0) == []


def test_pool_idle_shutdown_and_reactivation(monkeypatch):
    from lumen_api import ingestion_pool

    monkeypatch.setattr(settings, "lumen_ingestion_pool_idle_seconds", 1)
    monkeypatch.setattr(settings, "lumen_ingestion_pool_poll_seconds", 0.001)
    batches = iter([(1, 0), (1, 50), (0, 0), (0, 0), (1, 20)])
    ticks = iter([0, 2])
    stopped = asyncio.Event()
    events = []

    class Processes:
        children = []

        def reconcile(self, roles):
            self.children = roles
            events.append(tuple(roles))
            if len(events) == 4:
                stopped.set()

        async def stop(self):
            self.children = []
            events.append("zero")

    async def counts(conn):
        return next(batches)

    async def commit():
        pass

    monkeypatch.setattr(ingestion_pool, "pending_counts", counts)
    asyncio.run(
        supervise(SimpleNamespace(commit=commit), Processes(), stopped, now=lambda: next(ticks))
    )
    assert events == [
        ("coordinator",),
        ("coordinator",) + ("analysis",) * 4,
        "zero",
        ("coordinator",) + ("analysis",) * 4,
    ]


def test_dead_worker_is_replaced_after_backoff_without_exceeding_pool(monkeypatch, tmp_path):
    from lumen_api import ingestion_pool

    created = []
    killed = []
    now = [10.0]

    class Child:
        def __init__(self, args, **kwargs):
            assert kwargs["start_new_session"] is True
            self.pid = 1000 + len(created)
            self.returncode = None
            created.append(self)

        def poll(self):
            return self.returncode

    monkeypatch.setattr(ingestion_pool.subprocess, "Popen", Child)
    monkeypatch.setattr(ingestion_pool.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(ingestion_pool.os, "killpg", lambda pid, sig: killed.append(pid))
    processes = ingestion_pool.LocalProcesses()
    processes.log_dir = tmp_path
    roles = ["coordinator"] + ["analysis"] * 4
    processes.reconcile(roles)
    processes.reconcile(roles)
    assert len(created) == len(processes.children) == 5
    created[1].returncode = 1
    processes.reconcile(roles)
    assert len(processes.children) == 4 and killed == [1001]
    now[0] += 2
    processes.reconcile(roles)
    assert len(created) == 6 and len(processes.children) == 5
    assert [role for role, _ in processes.children].count("analysis") == 4
