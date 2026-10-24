"""Reconciliation says what it found of the source run (F3 Phase 3, WS-33).

A reconciling research turn copies the notes and raw reads of an earlier ("source") run into its
own folders, restoring that run from its snapshot so any worker can do it. When the source never
saved a snapshot the restore hands back an empty workspace and nothing is copied. That is not an
error, but the reconciling agent must be told: the reconciliation input carries a
``source_snapshot`` block — the source thread, the version restored (``None`` when there was
none) and how many files were copied — and the same three values go to the log.

These drive the two pieces the quality-research wiring calls, with real leases from two worker
areas over one database and one filesystem storage, built by the scenario harness.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from structlog.testing import capture_logs

from clue_api.quality_research_wiring import copy_source_run_files, write_reconciliation_files
from tests.api.test_agent_workspace_scenarios_db import _open, _policy, _world, _write
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_profiling_db")

RECONCILIATION = {
    "claims": [{"id": "c-1", "status": "stale"}],
    "_editorial_system": "Reconcile the claims against the source run's notes.",
}


def _source_thread() -> str:
    return f"research-quality-{uuid.uuid4()}"


def _events(logs: list[dict[str, object]]) -> list[dict[str, object]]:
    return [r for r in logs if r["event"] == "research.reconciliation.source_snapshot"]


def test_a_source_run_with_no_snapshot_is_reported_not_silently_empty(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with _world(tmp_path) as world:
            source_thread = _source_thread()
            source = await _open(world, world.machine(), thread=source_thread)
            lease = await _open(world, world.machine())
            assert source.snapshot_base is not None
            assert source.snapshot_base.pointer is None
            with capture_logs() as logs:
                block = await copy_source_run_files(
                    lease=lease,
                    source_lease=source,
                    readable_prefixes=_policy().readable_prefixes,
                    source_thread_id=source_thread,
                )
            await write_reconciliation_files(
                lease=lease, reconciliation=RECONCILIATION, source_snapshot=block
            )
            expected = {"thread_id": source_thread, "version": None, "files_copied": 0}
            written = json.loads(await lease.backend.read_text("work/reconciliation/input.json"))
            assert written["source_snapshot"] == expected
            assert written["claims"] == RECONCILIATION["claims"]
            assert "_editorial_system" not in written
            [event] = _events(logs)
            assert {k: event[k] for k in expected} == expected

    run_async(scenario())


def test_a_source_with_a_snapshot_reports_its_version_and_count(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with _world(tmp_path) as world:
            source_thread = _source_thread()
            first = world.machine()
            saved = await _open(world, first, fence=await world.fence("w-a"), thread=source_thread)
            try:
                _write(saved, {"work/notes.md": b"cycle ~42 days", "work/plan.md": b"1. read"})
                assert (await saved.save_snapshot()).status == "saved"
            finally:
                await first.factory.release_saved(saved)

            source = await _open(world, world.machine(), thread=source_thread)
            lease = await _open(world, world.machine())
            with capture_logs() as logs:
                block = await copy_source_run_files(
                    lease=lease,
                    source_lease=source,
                    readable_prefixes=_policy().readable_prefixes,
                    source_thread_id=source_thread,
                )
            await write_reconciliation_files(
                lease=lease, reconciliation=RECONCILIATION, source_snapshot=block
            )
            expected = {"thread_id": source_thread, "version": 1, "files_copied": 2}
            written = json.loads(await lease.backend.read_text("work/reconciliation/input.json"))
            assert written["source_snapshot"] == expected
            assert await lease.backend.read_text("work/notes.md") == "cycle ~42 days"
            assert await lease.backend.read_text("work/plan.md") == "1. read"
            [event] = _events(logs)
            assert {k: event[k] for k in expected} == expected

    run_async(scenario())
