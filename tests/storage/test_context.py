"""The run-scoped snapshot binding (audit finding 5) — pure, no DB.

The contract: a sink bound with ``bind_snapshots`` is visible to everything below on the same
task, invisible to sibling tasks (two concurrent runs each capture into their own
workspace-bound sink), shadowed by nesting, and restored on exit.
"""

from __future__ import annotations

import asyncio

from clue_storage import (
    SnapshotSink,
    bind_snapshots,
    current_snapshot_sink,
    current_storage,
)
from tests.storage.conftest import run_async


def test_bind_and_restore() -> None:
    assert current_snapshot_sink() is None
    sink = SnapshotSink(workspace_id="ws_1")
    with bind_snapshots(sink):
        assert current_snapshot_sink() is sink
        assert current_storage() is None
        inner = SnapshotSink(workspace_id="ws_2")
        with bind_snapshots(inner):  # nesting shadows…
            assert current_snapshot_sink() is inner
        assert current_snapshot_sink() is sink  # …and restores
        with bind_snapshots(None):  # an explicit None fences a sub-scope off
            assert current_snapshot_sink() is None
    assert current_snapshot_sink() is None


def test_concurrent_runs_see_their_own_sink() -> None:
    """The exact failure the audit called out: two concurrent runs must never share (or swap)
    workspace-bound sinks. ContextVars are task-local, so each run's binding is invisible to
    the other even while both are in flight."""

    async def scenario() -> None:
        barrier = asyncio.Barrier(2)

        async def one_run(workspace: str) -> str | None:
            sink = SnapshotSink(workspace_id=workspace)
            with bind_snapshots(sink):
                await barrier.wait()  # both runs are inside their bindings simultaneously
                seen = current_snapshot_sink()
                await barrier.wait()
                return seen.workspace_id if seen is not None else None

        seen_a, seen_b = await asyncio.gather(one_run("ws_a"), one_run("ws_b"))
        assert (seen_a, seen_b) == ("ws_a", "ws_b")

    run_async(scenario())
