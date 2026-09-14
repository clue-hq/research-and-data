"""Real filesystem mutations must not overwrite another successful tool call."""

from __future__ import annotations

import asyncio
import os
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from deepagents.backends import filesystem as stock_filesystem
from lumen_agent import fs_backend
from lumen_agent.fs_backend import AgentWorkspaceBackend


class MutationSchedule:
    """Pause A after its read; start B before releasing A.

    Observing the real lock's acquisition lets the same schedule test both
    implementations: without a transaction B completes against stale bytes;
    with one B reaches the lock and waits. No timing sleeps are required.
    """

    def __init__(self, monkeypatch):
        self.holder_paused = threading.Event()
        self.contender_reached = threading.Event()
        self.release_holder = threading.Event()
        schedule = self

        class ObservedRLock:
            def __init__(self):
                self.lock = threading.RLock()

            def __enter__(self):
                if schedule.holder_paused.is_set():
                    schedule.contender_reached.set()
                self.lock.acquire()
                return self

            def __exit__(self, *_):
                self.lock.release()

        monkeypatch.setattr(fs_backend, "RLock", ObservedRLock, raising=False)

    def pause_holder(self):
        self.holder_paused.set()
        assert self.release_holder.wait(timeout=10)

    def run(self, holder, contender):
        def run_contender():
            try:
                return contender()
            finally:
                # The original backend has no lock and completes B before A.
                self.contender_reached.set()

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(holder)
            try:
                assert self.holder_paused.wait(timeout=5)
                second = pool.submit(run_contender)
                assert self.contender_reached.wait(timeout=5)
            finally:
                self.release_holder.set()
            return first.result(timeout=5), second.result(timeout=5)


@pytest.mark.parametrize("alias", ["virtual", "relative", "host", "legacy", "symlink"])
def test_disjoint_same_file_edits_both_survive(tmp_path, monkeypatch, alias):
    path = tmp_path / "run_1/workspace/creative-direction.json"
    path.parent.mkdir(parents=True)
    path.write_text('"role": "eyebrow", "height": 400\n')
    link = tmp_path / "alias.json"
    link.symlink_to(path)
    second_key = {
        "virtual": "/run_1/workspace/creative-direction.json",
        "relative": "run_1/workspace/creative-direction.json",
        "host": str(path),
        "legacy": "/.lumen-runs/run_1/workspace/creative-direction.json",
        "symlink": "/alias.json",
    }[alias]
    schedule = MutationSchedule(monkeypatch)
    replace = stock_filesystem.perform_string_replacement

    def paused_replacement(content, old, new, replace_all):
        if old == '"eyebrow"':
            schedule.pause_holder()
        return replace(content, old, new, replace_all)

    monkeypatch.setattr(stock_filesystem, "perform_string_replacement", paused_replacement)
    backend = AgentWorkspaceBackend(tmp_path)
    first, second = schedule.run(
        lambda: backend.edit("/run_1/workspace/creative-direction.json", '"eyebrow"', '"label"'),
        lambda: backend.edit(second_key, "400", "520"),
    )
    assert first.error is None and second.error is None
    assert first.occurrences == second.occurrences == 1
    assert path.read_text() == '"role": "label", "height": 520\n'


def test_concurrent_stale_replacement_is_refused_after_prior_edit(tmp_path, monkeypatch):
    path = tmp_path / "direction.txt"
    path.write_text("height=400\n")
    schedule = MutationSchedule(monkeypatch)
    replace = stock_filesystem.perform_string_replacement

    def paused_replacement(content, old, new, replace_all):
        if new == "520":
            schedule.pause_holder()
        return replace(content, old, new, replace_all)

    monkeypatch.setattr(stock_filesystem, "perform_string_replacement", paused_replacement)
    backend = AgentWorkspaceBackend(tmp_path)
    first, second = schedule.run(
        lambda: backend.edit("/direction.txt", "400", "520"),
        lambda: backend.edit("/direction.txt", "400", "600"),
    )
    assert first.error is None
    assert second.error and "not found" in second.error
    assert path.read_text() == "height=520\n"


def test_concurrent_creates_cannot_both_report_success(tmp_path, monkeypatch):
    schedule = MutationSchedule(monkeypatch)
    real_open = stock_filesystem.os.open

    def paused_open(path, flags, *args, **kwargs):
        if flags & os.O_CREAT and threading.current_thread().name.endswith("_0"):
            schedule.pause_holder()
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(stock_filesystem.os, "open", paused_open)
    backend = AgentWorkspaceBackend(tmp_path)
    first, second = schedule.run(
        lambda: backend.write("/new/note.txt", "first"),
        lambda: backend.write(str(tmp_path / "new/note.txt"), "second"),
    )
    assert first.error is None
    assert second.error and "already exists" in second.error
    assert (tmp_path / "new/note.txt").read_text() == "first"


def test_critique_observer_sees_each_committed_revision_before_next_mutation(tmp_path, monkeypatch):
    path = tmp_path / "critique.json"
    path.write_text('{"headline": 0, "layout": 0}')
    schedule = MutationSchedule(monkeypatch)
    observations = []

    def observe(observed_path, raw):
        if raw == '{"headline": 1, "layout": 0}':
            schedule.pause_holder()
        observations.append((raw, observed_path.read_text()))

    backend = AgentWorkspaceBackend(tmp_path, critique_observer=observe)
    first, second = schedule.run(
        lambda: backend.edit("/critique.json", '"headline": 0', '"headline": 1'),
        lambda: backend.edit(str(path), '"layout": 0', '"layout": 1'),
    )
    assert first.error is None and second.error is None
    assert observations == [
        ('{"headline": 1, "layout": 0}', '{"headline": 1, "layout": 0}'),
        ('{"headline": 1, "layout": 1}', '{"headline": 1, "layout": 1}'),
    ]


def test_independent_files_can_replace_concurrently(tmp_path, monkeypatch):
    for name in ("a.txt", "b.txt"):
        (tmp_path / name).write_text("before")
    entered = threading.Barrier(2)
    replace = stock_filesystem.perform_string_replacement

    def concurrent_replacement(*args):
        entered.wait(timeout=5)
        return replace(*args)

    monkeypatch.setattr(stock_filesystem, "perform_string_replacement", concurrent_replacement)
    backend = AgentWorkspaceBackend(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(backend.edit, name, "before", "after")
                   for name in ("a.txt", "b.txt")]
        assert all(future.result(timeout=5).error is None for future in futures)
    assert (tmp_path / "a.txt").read_text() == (tmp_path / "b.txt").read_text() == "after"


def test_edit_errors_do_not_notify_or_modify_and_append_keeps_contract(tmp_path):
    seen = []
    backend = AgentWorkspaceBackend(tmp_path, critique_observer=lambda path, raw: seen.append(raw))
    assert backend.edit("/critique.json", "missing", "new").error
    assert backend.write("/critique.json", "same\nsame\nend").error is None
    assert backend.write("/critique.json", "overwrite").error
    assert backend.edit("/critique.json", "missing", "new").error
    assert backend.edit("/critique.json", "same", "new").error
    assert seen == ["same\nsame\nend"]
    result = backend.edit("/critique.json", "same", "new", replace_all=True)
    assert result.error is None and result.occurrences == 2
    assert backend.edit("/critique.json", "end", "end\nappended").error is None
    assert (tmp_path / "critique.json").read_text() == "new\nnew\nend\nappended"
    assert seen == ["same\nsame\nend", "new\nnew\nend", "new\nnew\nend\nappended"]


def test_async_file_tools_use_same_transaction(tmp_path, monkeypatch):
    """The middleware's async route must use the protected sync operation."""
    path = tmp_path / "direction.txt"
    path.write_text("first=0 second=0")
    schedule = MutationSchedule(monkeypatch)
    replace = stock_filesystem.perform_string_replacement

    def paused_replacement(content, old, new, replace_all):
        if old == "first=0":
            schedule.pause_holder()
        return replace(content, old, new, replace_all)

    monkeypatch.setattr(stock_filesystem, "perform_string_replacement", paused_replacement)
    backend = AgentWorkspaceBackend(tmp_path)
    first, second = schedule.run(
        lambda: asyncio.run(backend.aedit("/direction.txt", "first=0", "first=1")),
        lambda: asyncio.run(backend.aedit("/direction.txt", "second=0", "second=1")),
    )
    assert first.error is None and second.error is None
    assert path.read_text() == "first=1 second=1"


@pytest.mark.parametrize("operation", ["write", "edit"])
@pytest.mark.parametrize("key_kind", ["traversal", "symlink_escape", "projection", "runtime_lock"])
def test_rejected_paths_never_allocate_mutation_locks(tmp_path, monkeypatch, operation, key_kind):
    root = tmp_path / "workspace"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("private")
    (root / "escape").symlink_to(outside)
    projection = root / "run_1/custom_components"
    projection.mkdir(parents=True)
    source = projection / "source.tsx"
    source.write_text("typed source")
    coordination = root / ".materialize.lock"
    coordination.touch()
    key = {
        "traversal": "/../outside.txt",
        "symlink_escape": "/escape",
        "projection": str(source),
        "runtime_lock": str(coordination),
    }[key_kind]

    def invalid_lock_allocation():
        raise AssertionError("rejected paths must not allocate transaction locks")

    monkeypatch.setattr(fs_backend, "RLock", invalid_lock_allocation)
    backend = AgentWorkspaceBackend(root, custom_components_root=projection)
    result = (backend.write(key, "overwrite") if operation == "write"
              else backend.edit(key, "private", "overwrite"))
    assert result.error
    assert outside.read_text() == "private"
    assert source.read_text() == "typed source"
    assert coordination.read_bytes() == b""


def test_failed_io_releases_lock_and_does_not_notify(tmp_path, monkeypatch):
    path = tmp_path / "critique.json"
    path.write_text("before")
    seen = []
    backend = AgentWorkspaceBackend(tmp_path, critique_observer=lambda path, raw: seen.append(raw))
    real_open = stock_filesystem.os.open

    def denied_write(path, flags, *args, **kwargs):
        if flags & os.O_WRONLY:
            raise PermissionError("fixture filesystem denied write")
        return real_open(path, flags, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(stock_filesystem.os, "open", denied_write)
        result = backend.edit("/critique.json", "before", "after")
    assert result.error and "denied write" in result.error
    assert not seen
    assert path.read_text() == "before"
    # A different thread must be able to use this same lock after an error.
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(backend.edit, "/critique.json", "before", "after")
        assert future.result(timeout=5).error is None
    assert path.read_text() == "after"
    assert seen == ["after"]
