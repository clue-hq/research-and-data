"""Shared resource initialization is serialized across threads and fleet processes."""

from __future__ import annotations

import fcntl
import multiprocessing
import os
import queue
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from lumen_agent import materialize

_ACTORS = ("first", "second", "third")
_EVENT_TIMEOUT_SECONDS = 10
# The holder pauses while the controller starts and observes two contenders,
# each with its own event timeout. Its release deadline must cover that whole
# sequence plus one controller/cleanup allowance, not just one contender wait.
_RELEASE_TIMEOUT_SECONDS = len(_ACTORS) * _EVENT_TIMEOUT_SECONDS


def _source_tree(root):
    source = root / "source"
    (source / "skills" / "create-design").mkdir(parents=True)
    (source / "skills" / "create-design" / "SKILL.md").write_text("create")
    (source / "knowledge" / "nested").mkdir(parents=True)
    (source / "knowledge" / "nested" / "facts.md").write_text("facts")
    (source / "AGENT.md").write_text("agent")
    return source


def _files(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def _assert_complete(source, workspace):
    assert _files(workspace / "knowledge_docs") == _files(source)
    assert _files(workspace / ".deepagent" / "skills") == _files(source / "skills")
    assert (workspace / ".deepagent" / "AGENTS.md").read_bytes() == (
        source / "AGENT.md"
    ).read_bytes()
    assert (workspace / ".deepagent" / ".sync-stamp").read_text() == materialize._content_stamp(
        source
    )


def _instrument(events, release, actor):
    """Expose the second caller's real lock contention or overlapping copy.

    The first caller pauses before copying. A contender either demonstrably
    blocks on the kernel lock or reaches copytree while the first is paused.
    No timing window, sleep, or stress loop determines which behavior occurred.
    """
    real_copytree = materialize.shutil.copytree
    real_flock = fcntl.flock

    def copytree(source, destination, *args, **kwargs):
        if Path(destination).name == "knowledge_docs":
            events.put((actor(), "copy"))
            if not release.wait(_RELEASE_TIMEOUT_SECONDS):
                raise TimeoutError("test controller did not release materialization")
        return real_copytree(source, destination, *args, **kwargs)

    def flock(fd, operation):
        if operation == fcntl.LOCK_EX and actor() != "first":
            try:
                real_flock(fd, operation | fcntl.LOCK_NB)
            except BlockingIOError:
                events.put((actor(), "blocked"))
            else:
                events.put((actor(), "uncontended"))
                return
        return real_flock(fd, operation)

    return patch.object(materialize.shutil, "copytree", copytree), patch.object(
        fcntl, "flock", flock
    )


def _call(source, workspace, events, name):
    try:
        materialize.materialize_agent_workspace(
            SimpleNamespace(workspace_root=workspace), source_knowledge_docs=source
        )
        _assert_complete(source, workspace)
    except Exception as error:
        events.put((name, "error", repr(error)))
    else:
        events.put((name, "done"))


def _process_call(source, workspace, events, release, name):
    copy_patch, lock_patch = _instrument(events, release, lambda: name)
    with copy_patch, lock_patch:
        _call(source, workspace, events, name)


@pytest.mark.parametrize("workers", ["threads", "processes"])
@pytest.mark.parametrize("stale", [False, True], ids=["first-init", "stale-resync"])
def test_concurrent_materializers_share_one_complete_refresh(tmp_path, workers, stale):
    source = _source_tree(tmp_path)
    workspace = tmp_path / "workspace"
    if stale:
        materialize.materialize_agent_workspace(
            SimpleNamespace(workspace_root=workspace), source_knowledge_docs=source
        )
        (source / "skills" / "create-design" / "SKILL.md").unlink()
        (source / "knowledge" / "nested" / "facts.md").write_text("new facts")
    original_sources = _files(source)
    context = multiprocessing.get_context("spawn")
    events = context.Queue() if workers == "processes" else queue.Queue()
    release = context.Event() if workers == "processes" else threading.Event()
    started = []

    def exercise():
        for name in _ACTORS:
            if workers == "processes":
                worker = context.Process(
                    target=_process_call, args=(source, workspace, events, release, name)
                )
            else:
                worker = threading.Thread(
                    target=_call, args=(source, workspace, events, name), name=name
                )
            worker.start()
            started.append(worker)
            expected = "copy" if name == "first" else "blocked"
            assert events.get(timeout=_EVENT_TIMEOUT_SECONDS) == (name, expected)
        release.set()
        assert {events.get(timeout=_EVENT_TIMEOUT_SECONDS) for _ in started} == {
            (name, "done") for name in _ACTORS
        }

    try:
        if workers == "threads":
            copy_patch, lock_patch = _instrument(
                events, release, lambda: threading.current_thread().name
            )
            with copy_patch, lock_patch:
                try:
                    exercise()
                finally:
                    release.set()
                    for worker in started:
                        worker.join(timeout=10)
        else:
            exercise()
    finally:
        release.set()
        for worker in started:
            worker.join(timeout=10)
            if workers == "processes" and worker.is_alive():
                worker.terminate()
                worker.join(timeout=10)
            assert not worker.is_alive()
        if workers == "processes":
            events.close()
            events.join_thread()
    _assert_complete(source, workspace)
    assert _files(source) == original_sources


@pytest.mark.parametrize("stale", [False, True], ids=["first-init", "stale-resync"])
def test_failed_copy_is_loud_and_next_caller_recovers(tmp_path, monkeypatch, stale):
    source = _source_tree(tmp_path)
    workspace = tmp_path / "workspace"
    config = SimpleNamespace(workspace_root=workspace)
    if stale:
        materialize.materialize_agent_workspace(config, source_knowledge_docs=source)
        (source / "AGENT.md").write_text("changed agent")
    original_sources = _files(source)
    with monkeypatch.context() as failure:

        def fail_copy(source, destination, *args, **kwargs):
            raise OSError("injected copy failure")

        failure.setattr(materialize.shutil, "copy2", fail_copy)
        with pytest.raises(RuntimeError, match="injected copy failure"):
            materialize.materialize_agent_workspace(config, source_knowledge_docs=source)
    assert not (workspace / ".deepagent" / ".sync-stamp").exists()
    materialize.materialize_agent_workspace(config, source_knowledge_docs=source)
    _assert_complete(source, workspace)
    assert _files(source) == original_sources


def test_matching_stamp_keeps_cached_resources(tmp_path):
    source = _source_tree(tmp_path)
    workspace = tmp_path / "workspace"
    config = SimpleNamespace(workspace_root=workspace)
    materialize.materialize_agent_workspace(config, source_knowledge_docs=source)
    cached_files = {
        p: p.stat().st_mtime_ns
        for root in (workspace / ".deepagent", workspace / "knowledge_docs")
        for p in root.rglob("*")
        if p.is_file()
    }
    materialize.materialize_agent_workspace(config, source_knowledge_docs=source)
    assert {p: p.stat().st_mtime_ns for p in cached_files} == cached_files
    _assert_complete(source, workspace)


def test_failed_removal_cannot_leave_a_valid_stamp(tmp_path, monkeypatch):
    source = _source_tree(tmp_path)
    workspace = tmp_path / "workspace"
    config = SimpleNamespace(workspace_root=workspace)
    materialize.materialize_agent_workspace(config, source_knowledge_docs=source)
    (source / "AGENT.md").write_text("updated agent")

    def partial_removal(path):
        (path / "AGENTS.md").unlink()
        raise OSError("injected removal failure")

    with monkeypatch.context() as failure:
        failure.setattr(materialize.shutil, "rmtree", partial_removal)
        with pytest.raises(RuntimeError, match="injected removal failure"):
            materialize.materialize_agent_workspace(config, source_knowledge_docs=source)
    assert not (workspace / ".deepagent" / ".sync-stamp").exists()
    # Even a source rollback must repair the interrupted derived tree.
    (source / "AGENT.md").write_text("agent")
    materialize.materialize_agent_workspace(config, source_knowledge_docs=source)
    _assert_complete(source, workspace)


def _crash_during_copy(source, workspace):
    def crash(*args, **kwargs):
        os._exit(17)

    with patch.object(materialize.shutil, "copy2", crash):
        materialize.materialize_agent_workspace(
            SimpleNamespace(workspace_root=workspace), source_knowledge_docs=source
        )


def test_process_exit_releases_lock_and_next_process_repairs(tmp_path):
    source = _source_tree(tmp_path)
    workspace = tmp_path / "workspace"
    context = multiprocessing.get_context("spawn")
    crashed = context.Process(target=_crash_during_copy, args=(source, workspace))
    crashed.start()
    crashed.join(timeout=10)
    if crashed.is_alive():
        crashed.terminate()
        crashed.join(timeout=10)
        pytest.fail("crash worker did not finish")
    assert crashed.exitcode == 17
    assert not (workspace / ".deepagent" / ".sync-stamp").exists()
    events = context.Queue()
    successor = context.Process(target=_call, args=(source, workspace, events, "successor"))
    try:
        successor.start()
        assert events.get(timeout=10) == ("successor", "done")
        successor.join(timeout=10)
        assert successor.exitcode == 0
    finally:
        if successor.is_alive():
            successor.terminate()
            successor.join(timeout=10)
        events.close()
        events.join_thread()
    _assert_complete(source, workspace)


def test_agent_cannot_write_materialization_lock():
    from deepagents.middleware.filesystem import _check_fs_permission
    from lumen_agent.harness import _filesystem_permissions

    permissions = _filesystem_permissions()
    assert _check_fs_permission(permissions, "write", "/.materialize.lock") == "deny"
    assert _check_fs_permission(permissions, "write", "/run_1/workspace/brief.md") == "allow"
