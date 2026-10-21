"""F3 Phase 1, plan Task 10: the worker-area cache sweep (spec WS-16, WS-17; AW-9, AW-11, AW-17,
AW-19) and the one-off removal of the layout from before F3 (WS-22)."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from clue_agents.worker_area import ChatScope, WorkerArea, claim_worker_area
from clue_api.agent_workspace_cache import AgentWorkspaceCacheJob

REPO = Path(__file__).resolve().parents[2]
NOW = 1_800_000_000.0


def _area(tmp_path: Path) -> WorkerArea:
    root = tmp_path / "workspaces"
    root.mkdir(mode=0o700)
    return claim_worker_area(root)


def _chat(area: WorkerArea, thread: str, *, idle_s: float, size: int = 10) -> Path:
    folder = area.path / "chats" / "ws-1" / "project-1" / thread
    (folder / "agent" / "scratch").mkdir(parents=True, mode=0o700)
    (folder / "agent" / "scratch" / "n.md").write_bytes(b"x" * size)
    (folder / "snapshot-note.json").write_text("{}")
    stamp = folder / "last-used"
    stamp.write_text("")
    os.utime(stamp, (NOW - idle_s, NOW - idle_s))
    # A frozen recipe tree, the way a real chat folder holds one.
    (folder / "agent" / "inputs").mkdir(mode=0o700)
    (folder / "agent" / "inputs" / "m.txt").write_text("hi")
    (folder / "agent" / "inputs" / "m.txt").chmod(0o400)
    (folder / "agent" / "inputs").chmod(0o500)
    return folder


def test_an_idle_chat_is_removed_after_the_idle_window(tmp_path: Path) -> None:
    area = _area(tmp_path)
    try:
        old = _chat(area, "old", idle_s=31 * 60)
        fresh = _chat(area, "fresh", idle_s=5 * 60)
        result = AgentWorkspaceCacheJob(area=area, idle_s=1800, max_bytes=10**9).run_once(now=NOW)
        assert not old.exists()
        assert fresh.exists()
        assert result.removed == ("ws-1/project-1/old",)
        assert result.bytes_freed > 0
    finally:
        area.close()


def test_a_chat_in_use_is_kept_even_when_old(tmp_path: Path) -> None:
    area = _area(tmp_path)
    try:
        busy = _chat(area, "busy", idle_s=10 * 3600)
        area.mark_in_use(ChatScope("ws-1", "project-1", "busy"))
        AgentWorkspaceCacheJob(area=area, idle_s=1800, max_bytes=10**9).run_once(now=NOW)
        assert busy.exists()
    finally:
        area.close()


def test_the_size_cap_removes_the_oldest_idle_chats_first(tmp_path: Path) -> None:
    area = _area(tmp_path)
    try:
        oldest = _chat(area, "oldest", idle_s=600, size=4000)
        middle = _chat(area, "middle", idle_s=400, size=4000)
        newest = _chat(area, "newest", idle_s=200, size=4000)
        result = AgentWorkspaceCacheJob(area=area, idle_s=1800, max_bytes=9000).run_once(now=NOW)
        assert not oldest.exists()
        assert middle.exists() and newest.exists()
        assert result.removed == ("ws-1/project-1/oldest",)
    finally:
        area.close()


def test_the_sweep_never_leaves_its_own_area(tmp_path: Path) -> None:
    area = _area(tmp_path)
    try:
        other = area.path.parent / "area-9" / "chats" / "ws-1" / "project-1" / "t"
        other.mkdir(parents=True)
        (other / "last-used").write_text("")
        os.utime(other / "last-used", (NOW - 10**6, NOW - 10**6))
        AgentWorkspaceCacheJob(area=area, idle_s=1, max_bytes=1).run_once(now=NOW)
        assert other.exists()
    finally:
        area.close()


def test_an_empty_area_is_a_no_op(tmp_path: Path) -> None:
    area = _area(tmp_path)
    try:
        result = AgentWorkspaceCacheJob(area=area, idle_s=1800, max_bytes=10**9).run_once(now=NOW)
        assert result.removed == () and result.bytes_freed == 0
    finally:
        area.close()


def _legacy(root: Path, *, age_s: float) -> Path:
    thread = root / "ws_abc" / "projects" / "prj_1" / "threads" / "thr_1"
    (thread / "scratch").mkdir(parents=True)
    (thread / "scratch" / "n.md").write_text("old")
    library = root / "ws_abc" / "library" / "brand" / "b" / "v1"
    library.mkdir(parents=True)
    (library / "kit.md").write_text("kit")
    (root / "ws_abc" / "projects" / "prj_1" / "pinned-0123456789ab").mkdir()
    stamp = time.time() - age_s
    for path in [*root.rglob("*")]:
        os.utime(path, (stamp, stamp))
    return thread


def _script(root: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "remove_legacy_agent_workspaces.py"),
            "--root",
            str(root),
            *extra,
        ],
        capture_output=True,
        text=True,
        check=True,
    )


def test_the_legacy_script_dry_run_lists_and_keeps(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    thread = _legacy(root, age_s=3 * 86400)
    (root / "workers" / "area-0").mkdir(parents=True)
    out = _script(root).stdout
    assert "ws_abc" in out and "dry run" in out.lower()
    assert thread.exists()


def test_the_legacy_script_apply_removes_only_the_old_layout(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    _legacy(root, age_s=3 * 86400)
    (root / "workers" / "area-0" / "chats").mkdir(parents=True)
    (root / "local").mkdir()
    _script(root, "--apply")
    assert not (root / "ws_abc").exists()
    assert (root / "workers" / "area-0" / "chats").exists()
    assert (root / "local").exists()


def test_the_legacy_script_keeps_what_was_used_recently(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    thread = _legacy(root, age_s=60)
    _script(root, "--apply", "--older-than-hours", "48")
    assert thread.exists()


@pytest.mark.parametrize("bad", ["", "/"])
def test_the_legacy_script_refuses_a_missing_root(bad: str, tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "remove_legacy_agent_workspaces.py"),
            "--root",
            bad or str(tmp_path / "missing"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0


# --- the fleet worker's side: the sweep loop and the start-up cleanup -------------------------


def _settings(tmp_path: Path, *, snapshots: bool) -> object:
    from clue_config import Settings

    return Settings(
        _env_file=None,
        agent_workspace_root=str(tmp_path / "workspaces"),
        agent_workspace_snapshots_enabled=snapshots,
    )


@pytest.mark.parametrize(("snapshots", "idle_s"), [(True, 1800.0), (False, 86400.0)])
def test_the_sweep_job_idle_window_follows_the_snapshot_switch(
    tmp_path: Path, snapshots: bool, idle_s: float
) -> None:
    from clue_api.fleet_main import _workspace_cache_job

    area = _area(tmp_path)
    try:
        job = _workspace_cache_job(_settings(tmp_path, snapshots=snapshots), area)  # type: ignore[arg-type]
        assert job is not None
        assert job.idle_s == idle_s
    finally:
        area.close()


def test_there_is_no_sweep_without_an_area(tmp_path: Path) -> None:
    from clue_api.fleet_main import _start_workspace_cache_sweep

    assert _start_workspace_cache_sweep(_settings(tmp_path, snapshots=True), None) is None  # type: ignore[arg-type]


def test_the_sweep_loop_runs_the_job_each_interval_and_survives_a_fault(tmp_path: Path) -> None:
    import asyncio

    from clue_api.fleet_main import _workspace_cache_sweep_loop

    calls: list[str] = []

    class _Job:
        def run_once(self) -> object:
            calls.append("run")
            if len(calls) == 1:
                raise OSError("disk hiccup")
            return None

    sleeps: list[float] = []

    async def _sleep(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) > 2:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_workspace_cache_sweep_loop(300.0, _Job(), sleep=_sleep))  # type: ignore[arg-type]
    assert calls == ["run", "run"]
    assert sleeps == [300.0, 300.0, 300.0]


def test_start_up_removes_this_users_old_media_temp_folders_only(tmp_path: Path) -> None:
    from clue_api.fleet_main import _remove_stale_media_dirs

    old = tmp_path / "arv2-media-old"
    new = tmp_path / "arv2-media-new"
    other = tmp_path / "something-else"
    for folder in (old, new, other):
        folder.mkdir()
        (folder / "clip.mp4").write_bytes(b"x")
    os.utime(old, (NOW - 7 * 3600, NOW - 7 * 3600))
    os.utime(new, (NOW - 3600, NOW - 3600))
    os.utime(other, (NOW - 7 * 3600, NOW - 7 * 3600))

    assert _remove_stale_media_dirs(tmp_path, now=NOW) == 1
    assert not old.exists()
    assert new.exists()
    assert other.exists()


# --- review I2: a turn holds its chat before the lease, while it syncs the library copies --------


def test_a_held_chat_is_never_swept_and_is_sweepable_again_after(tmp_path: Path) -> None:
    from clue_agents.workspace import AgentWorkspaceFactory
    from clue_agents.workspace_policy import PreparedWorkspaceRoot
    from tests.agents.workspace_helpers import RecordingArtifactSink

    area = _area(tmp_path)
    factory = AgentWorkspaceFactory(
        prepared_root=PreparedWorkspaceRoot(path=area.path),
        artifact_sink=RecordingArtifactSink(),
        area=area,
    )
    try:
        folder = _chat(area, "returning", idle_s=10 * 3600)
        # The factory refuses a chat folder with any non-private directory in or above it.
        for private in (folder, folder / "agent", *list(folder.parents)[:3]):
            private.chmod(0o700)
        chat = ChatScope("ws-1", "project-1", "returning")
        job = AgentWorkspaceCacheJob(area=area, idle_s=1800, max_bytes=10**9)
        with factory.hold_chat(chat):
            # The turn is syncing brand/, project/ and attachments/ before it takes its lease.
            assert job.run_once(now=NOW).removed == ()
            assert folder.is_dir()
        assert area.in_use() == frozenset()
        # Holding stamped the folder as used just now, so it is not idle any more...
        assert job.run_once(now=time.time()).removed == ()
        # ...and it goes once it has been idle for the window.
        assert job.run_once(now=time.time() + 1801).removed == ("ws-1/project-1/returning",)
    finally:
        factory.close()
        area.close()


def test_the_turn_holds_its_chat_before_syncing_the_library_copies() -> None:
    source = (REPO / "platform/api/clue_api/agent_turn_fleet_wiring.py").read_text()
    held = source.index("hold_chat(chat)")
    for sync in (
        "ensure_brand_library(",
        "ensure_project_library(",
        "sync_pinned_project_library(",
        "sync_project_attachments(",
        "acquire_restored(",
    ):
        assert source.index(sync) > held, sync
