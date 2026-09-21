from __future__ import annotations

import asyncio
import hashlib
import json
import os
import stat
from collections.abc import Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

import pytest

from clue_agents import (
    AgentResourceMaterializer,
    AgentWorkspaceBackend,
    AgentWorkspaceFactory,
    AgentWorkspaceLease,
    AnchoredAgentWorkspaceBackend,
    ArtifactRef,
    LibraryFile,
    LibraryTree,
    MountMode,
    MountRequest,
    VersionedWriteOutcome,
    VersionedWriteRefused,
    WorkspaceConfigurationError,
    WorkspaceConflict,
    WorkspaceMount,
    WorkspaceQuotaExceeded,
    WorkspaceRootPolicy,
    WorkspaceSecurityError,
)
from clue_core import ExecutionId
from tests.agents.workspace_helpers import (
    DEFAULT_READABLE_PREFIXES,
    DEFAULT_WRITABLE_PREFIXES,
    EXECUTION_ID,
    RecordingArtifactSink,
    expected_root_id,
    make_factory,
    make_workspace,
    policy,
    resource_snapshot,
)


@pytest.mark.parametrize(
    "path",
    [
        "/etc/passwd",
        "../secret.txt",
        "work/../secret.txt",
        "work//note.md",
        "work\\note.md",
        "C:/secret.txt",
        "work/\x00note.md",
        "work/\u2215etc.md",
        "work/\uff0fetc.md",
    ],
)
def test_hostile_paths_fail_without_disclosing_host_root(tmp_path: Path, path: str) -> None:
    harness = make_workspace(tmp_path)
    try:
        with pytest.raises((ValueError, WorkspaceSecurityError)) as raised:
            harness.lease.backend.write_text_sync(path, "secret")
        assert str(harness.root) not in str(raised.value)
    finally:
        harness.close()


def test_file_surface_is_relative_private_atomic_and_non_executable(tmp_path: Path) -> None:
    harness = make_workspace(tmp_path)
    backend = harness.lease.backend
    try:
        entry = backend.write_text_sync("work/notes/plan.md", "first")
        assert entry.path == "work/notes/plan.md"
        assert entry.sha256
        assert backend.read_text_sync(entry.path) == "first"
        assert backend.stat_entry_sync(entry.path) == entry

        edited = backend.edit_text_sync(entry.path, old="first", new="second")
        assert backend.read_text_sync(entry.path) == "second"
        assert edited.byte_count == len("second")
        assert [item.path for item in backend.list_entries_sync("work")] == [entry.path]

        host_file = harness.thread_path / entry.path
        assert stat.S_IMODE(host_file.stat().st_mode) == 0o600
        assert not host_file.stat().st_mode & 0o111
        assert not any(path.name.startswith(".clue-tmp-") for path in host_file.parent.iterdir())
        assert isinstance(backend, AgentWorkspaceBackend)
        assert backend.virtual_mode is True
        assert not hasattr(backend, "execute")

        framework_write = backend.write("/outputs/framework.md", "framework")
        assert framework_write.error is None
        assert backend.read("/outputs/framework.md").file_data is not None
        hostile = backend.write("/../escape.md", "escape")
        assert hostile.error is not None
        assert "permission_denied" in hostile.error
    finally:
        harness.close()


def test_agent_cannot_read_repository_environment_or_other_execution(tmp_path: Path) -> None:
    harness = make_workspace(tmp_path)
    second_id = ExecutionId(UUID("00000000-0000-0000-0000-000000000612"))
    second = harness.factory.create(
        workspace_id="ws-1",
        project_id="project-1",
        thread_id="thread-2",
        execution_id=second_id,
        policy=policy(),
    )
    try:
        second.backend.write_text_sync("work/private.md", "other")
        for target in (
            str(harness.thread_path.parent / "thread-2" / "work/private.md"),
            "../../source/pyproject.toml",
            "../../.env",
            "/proc/self/environ",
        ):
            with pytest.raises((ValueError, WorkspaceSecurityError)):
                harness.lease.backend.read_text_sync(target)
        assert os.environ.get("PATH") not in repr(harness.lease.backend.list_entries_sync())
        with pytest.raises(WorkspaceConflict):
            harness.factory.create(
                workspace_id="ws-1",
                project_id="project-1",
                thread_id="thread-2",
                execution_id=second_id,
                policy=policy(),
            )
    finally:
        second.backend.close()
        harness.close()


def test_readonly_prefixes_and_source_extensions_are_rejected(tmp_path: Path) -> None:
    harness = make_workspace(tmp_path)
    backend = harness.lease.backend
    try:
        backend.materialize_bytes("context/card.json", b'{"safe":true}')
        backend.freeze_materialized_trees()
        with pytest.raises(WorkspaceSecurityError):
            backend.write_text_sync("context/new.json", "{}")
        with pytest.raises(WorkspaceSecurityError):
            backend.edit_text_sync("context/card.json", old="true", new="false")
        with pytest.raises(WorkspaceSecurityError):
            backend.write_text_sync("work/attack.py", "import os")
        injected = harness.thread_path / "work/injected.md"
        injected.write_text("executable")
        os.chmod(injected, 0o700)
        with pytest.raises(WorkspaceSecurityError):
            backend.read_text_sync("work/injected.md")
        assert stat.S_IMODE((harness.thread_path / "context/card.json").stat().st_mode) == 0o400
        assert stat.S_IMODE((harness.thread_path / "context").stat().st_mode) == 0o500
    finally:
        harness.close()


def test_symlinks_hardlinks_and_special_entries_fail_closed(tmp_path: Path) -> None:
    harness = make_workspace(tmp_path)
    backend = harness.lease.backend
    outside = tmp_path / "outside.md"
    outside.write_text("host secret")
    try:
        (harness.thread_path / "work/link.md").symlink_to(outside)
        with pytest.raises(WorkspaceSecurityError):
            backend.read_text_sync("work/link.md")
        with pytest.raises((WorkspaceConflict, WorkspaceSecurityError)):
            backend.write_text_sync("work/link.md", "replace")

        real = harness.thread_path / "work/real.md"
        real.write_text("same")
        os.chmod(real, 0o600)
        os.link(real, harness.thread_path / "work/hard.md")
        with pytest.raises(WorkspaceSecurityError):
            backend.read_text_sync("work/real.md")
        with pytest.raises(WorkspaceSecurityError):
            backend.list_entries_sync("work")

        fifo = harness.thread_path / "outputs/pipe.txt"
        os.mkfifo(fifo, 0o600)
        with pytest.raises(WorkspaceSecurityError):
            backend.list_entries_sync("outputs")
    finally:
        harness.close()


def test_privacy_erasure_closes_live_backend_and_removes_materialized_tree(
    tmp_path: Path,
) -> None:
    harness = make_workspace(tmp_path)
    backend = harness.lease.backend
    backend.materialize_bytes("context/contact.md", b"personal context")
    try:
        assert harness.factory.erase_for_privacy(
            workspace_id=harness.lease.identity.workspace_id,
            project_id=harness.lease.identity.project_id,
            thread_id=harness.lease.identity.thread_id,
        )
        assert not harness.thread_path.exists()
        with pytest.raises(WorkspaceSecurityError, match="closed"):
            backend.read_text_sync("context/contact.md")
        assert not harness.factory.erase_for_privacy(
            workspace_id=harness.lease.identity.workspace_id,
            project_id=harness.lease.identity.project_id,
            thread_id=harness.lease.identity.thread_id,
        )
    finally:
        harness.close()


def test_quota_enforces_per_file_total_and_count(tmp_path: Path) -> None:
    per_file = make_workspace(
        tmp_path / "per-file",
        active_policy=policy(max_total_bytes=20, max_file_bytes=5, max_file_count=5),
    )
    try:
        with pytest.raises(WorkspaceQuotaExceeded):
            per_file.lease.backend.write_text_sync("work/large.txt", "123456")
    finally:
        per_file.close()

    total = make_workspace(
        tmp_path / "total",
        active_policy=policy(max_total_bytes=8, max_file_bytes=8, max_file_count=5),
    )
    try:
        total.lease.backend.write_text_sync("work/a.txt", "12345")
        with pytest.raises(WorkspaceQuotaExceeded):
            total.lease.backend.write_text_sync("work/b.txt", "6789")
    finally:
        total.close()

    count = make_workspace(
        tmp_path / "count",
        active_policy=policy(max_total_bytes=20, max_file_bytes=10, max_file_count=1),
    )
    try:
        count.lease.backend.write_text_sync("work/a.txt", "a")
        with pytest.raises(WorkspaceQuotaExceeded):
            count.lease.backend.write_text_sync("work/b.txt", "b")
    finally:
        count.close()


def test_workspace_usage_snapshot_reports_outputs_and_policy_ceilings(tmp_path: Path) -> None:
    harness = make_workspace(
        tmp_path,
        active_policy=policy(max_total_bytes=100, max_file_bytes=50, max_file_count=5),
    )
    try:
        harness.lease.backend.write_text_sync("work/notes.md", "work")
        harness.lease.backend.write_text_sync("outputs/report.md", "report")
        usage = harness.lease.usage_snapshot()
        assert usage.file_count == 2
        assert usage.total_bytes == 10
        assert usage.output_file_count == 1
        assert usage.output_bytes == 6
        assert usage.max_file_count == 5
        assert usage.max_total_bytes == 100
    finally:
        harness.close()


def test_factory_securely_reopens_same_frozen_execution_after_process_restart(
    tmp_path: Path,
) -> None:
    active_policy = policy()
    harness = make_workspace(tmp_path, active_policy=active_policy)
    identity = harness.lease.identity
    harness.lease.backend.materialize_bytes("context/account.md", b"account context")
    harness.lease.backend.freeze_materialized_trees()
    harness.lease.mark_resources_frozen()
    harness.factory.close()

    prepared = WorkspaceRootPolicy(
        configured_root=harness.root,
        source_root=tmp_path / "source",
        home_root=tmp_path / "home",
    ).prepare()
    reopened_factory = AgentWorkspaceFactory(
        prepared_root=prepared,
        artifact_sink=harness.sink,
    )
    reopened = reopened_factory.acquire(
        workspace_id=identity.workspace_id,
        project_id=identity.project_id,
        thread_id=identity.thread_id,
        execution_id=identity.execution_id,
        policy=active_policy,
    )
    try:
        assert reopened.identity.workspace_root_id == identity.workspace_root_id
        assert reopened.resources_frozen
        assert reopened.backend.read_text_sync("context/account.md") == "account context"
        with pytest.raises(WorkspaceSecurityError):
            reopened.backend.write_text_sync("context/other.md", "blocked")
    finally:
        reopened_factory.close()


def test_concurrent_same_path_write_has_one_winner_and_no_partial_file(tmp_path: Path) -> None:
    harness = make_workspace(tmp_path)
    backend = harness.lease.backend

    def write(value: str) -> str:
        try:
            backend.write_text_sync("outputs/result.md", value)
        except WorkspaceConflict:
            return "conflict"
        return "written"

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(write, [f"value-{index}" for index in range(8)]))
        assert results.count("written") == 1
        assert results.count("conflict") == 7
        assert backend.read_text_sync("outputs/result.md").startswith("value-")
        assert not any(
            path.name.startswith(".clue-tmp-")
            for path in (harness.thread_path / "outputs").iterdir()
        )
    finally:
        harness.close()


def test_concurrent_edits_are_compare_and_swap_not_lost_updates(tmp_path: Path) -> None:
    harness = make_workspace(tmp_path)
    backend = harness.lease.backend
    backend.write_text_sync("work/plan.md", "original")

    def edit(value: str) -> str:
        try:
            backend.edit_text_sync("work/plan.md", old="original", new=value)
        except WorkspaceConflict:
            return "conflict"
        return "edited"

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(edit, [f"edit-{index}" for index in range(8)]))
        assert results.count("edited") == 1
        assert results.count("conflict") == 7
        assert backend.read_text_sync("work/plan.md").startswith("edit-")
    finally:
        harness.close()


def test_anchored_replace_overwrites_swapped_link_not_its_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = make_workspace(tmp_path)
    backend = harness.lease.backend
    backend.write_text_sync("work/plan.md", "original")
    outside = tmp_path / "outside.md"
    outside.write_text("host secret")
    real_replace = os.replace

    def swap_then_replace(
        source: str,
        destination: str,
        *,
        src_dir_fd: int,
        dst_dir_fd: int,
    ) -> None:
        os.unlink(destination, dir_fd=dst_dir_fd)
        os.symlink(outside, destination, dir_fd=dst_dir_fd)
        real_replace(
            source,
            destination,
            src_dir_fd=src_dir_fd,
            dst_dir_fd=dst_dir_fd,
        )

    monkeypatch.setattr("clue_agents.workspace.os.replace", swap_then_replace)
    try:
        backend.edit_text_sync("work/plan.md", old="original", new="safe")
        assert backend.read_text_sync("work/plan.md") == "safe"
        assert outside.read_text() == "host secret"
        assert not (harness.thread_path / "work/plan.md").is_symlink()
    finally:
        harness.close()


def test_concurrent_quota_decisions_are_serialized(tmp_path: Path) -> None:
    harness = make_workspace(
        tmp_path,
        active_policy=policy(max_total_bytes=10, max_file_bytes=10, max_file_count=1),
    )
    backend = harness.lease.backend

    def write(index: int) -> str:
        try:
            backend.write_text_sync(f"work/{index}.txt", "x")
        except WorkspaceQuotaExceeded:
            return "quota"
        return "written"

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(write, range(8)))
        assert results.count("written") == 1
        assert results.count("quota") == 7
        assert len(backend.list_entries_sync("work")) == 1
    finally:
        harness.close()


def test_factory_rejects_unexpected_entries_between_scope_levels(tmp_path: Path) -> None:
    harness = make_workspace(tmp_path)
    other_id = ExecutionId(UUID("00000000-0000-0000-0000-000000000613"))
    unexpected = harness.root / "ws-1/unexpected.txt"
    unexpected.write_text("not a project directory")
    try:
        with pytest.raises(WorkspaceSecurityError):
            harness.factory.create(
                workspace_id="ws-1",
                project_id="project-2",
                thread_id="thread-1",
                execution_id=other_id,
                policy=policy(),
            )
    finally:
        harness.close()


def test_failed_atomic_install_leaves_no_target_or_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = make_workspace(tmp_path)

    def fail_link(*args: object, **kwargs: object) -> None:
        raise OSError("injected crash")

    monkeypatch.setattr("clue_agents.workspace.os.link", fail_link)
    try:
        with pytest.raises(WorkspaceSecurityError):
            harness.lease.backend.write_text_sync("outputs/result.md", "complete")
        assert not (harness.thread_path / "outputs/result.md").exists()
        assert not tuple((harness.thread_path / "outputs").iterdir())
    finally:
        harness.close()


def test_output_snapshot_is_single_flight_and_release_keeps_the_thread(tmp_path: Path) -> None:
    sink = RecordingArtifactSink()
    harness = make_workspace(tmp_path, sink=sink)
    backend = harness.lease.backend
    backend.write_text_sync("outputs/report.md", "final")
    try:
        first, second = asyncio.run(_snapshot_twice(backend))
        assert first == second
        assert len(sink.records) == 1
        assert sink.records[0][1:] == ("outputs/report.md", b"final", "text/markdown")
        with pytest.raises(WorkspaceConflict):
            backend.edit_text_sync("outputs/report.md", old="final", new="changed")

        finalization = ArtifactRef(
            workspace_id="ws-1",
            artifact_key="ws-1/finalization",
            sha256="f" * 64,
            media_type="application/json",
            byte_count=2,
        )
        harness.lease.authorize_cleanup(finalization_ref=finalization)
        # Releasing the lease ends the turn; the persistent thread directory survives it.
        harness.factory.cleanup(harness.lease)
        assert harness.thread_path.exists()
        assert (harness.thread_path / "outputs/report.md").exists()
        with pytest.raises(WorkspaceSecurityError, match="closed"):
            backend.read_text_sync("outputs/report.md")
    finally:
        harness.factory.close()


def test_output_snapshot_can_empty_the_folder_for_the_next_turn(tmp_path: Path) -> None:
    sink = RecordingArtifactSink()
    harness = make_workspace(tmp_path, sink=sink)
    backend = harness.lease.backend
    backend.write_text_sync("outputs/report.md", "final")
    backend.write_text_sync("outputs/drafts/note.md", "draft")
    backend.write_text_sync("scratch/notes.md", "kept across turns")
    outputs = harness.thread_path / "outputs"
    try:
        refs = asyncio.run(backend.snapshot_outputs(empty_after=True))
        assert [record[1] for record in sink.records] == [
            "outputs/drafts/note.md",
            "outputs/report.md",
        ]
        assert len(refs) == 2
        assert backend.outputs_snapshotted
        # The durable copies are made; the turn's folder starts the next turn empty and writable.
        assert tuple(outputs.iterdir()) == ()
        assert stat.S_IMODE(outputs.stat().st_mode) == 0o700

        replay = asyncio.run(backend.snapshot_outputs(empty_after=True))
        assert list(replay) == list(refs)
        assert len(sink.records) == 2

        # Nothing outside outputs/ is touched.
        assert backend.read_text_sync("scratch/notes.md") == "kept across turns"
    finally:
        harness.close()


@pytest.mark.parametrize("failure", ["workspace", "digest"])
def test_output_snapshot_rejects_untrusted_artifact_refs(
    tmp_path: Path,
    failure: str,
) -> None:
    sink = RecordingArtifactSink(
        workspace_override="ws-other" if failure == "workspace" else None,
        digest_override="0" * 64 if failure == "digest" else None,
    )
    harness = make_workspace(tmp_path, sink=sink)
    harness.lease.backend.write_text_sync("outputs/report.md", "final")
    try:
        with pytest.raises(WorkspaceSecurityError):
            asyncio.run(harness.lease.backend.snapshot_outputs())
        assert not harness.lease.backend.outputs_snapshotted
        with pytest.raises(WorkspaceSecurityError):
            harness.lease.authorize_cleanup(
                finalization_ref=ArtifactRef(
                    workspace_id="ws-1",
                    artifact_key="ws-1/finalization",
                    sha256="f" * 64,
                    media_type="application/json",
                    byte_count=2,
                )
            )
    finally:
        harness.close()


async def _snapshot_twice(
    backend: AnchoredAgentWorkspaceBackend,
) -> tuple[Sequence[ArtifactRef], Sequence[ArtifactRef]]:
    first, second = await asyncio.gather(
        backend.snapshot_outputs(),
        backend.snapshot_outputs(),
    )
    return first, second


# --- mount table -------------------------------------------------------------------------


_MOUNT_READABLE = (
    ".deepagent",
    "inputs",
    "context",
    "scratch",
    "reads",
    "work",
    "outputs",
    "library",
)
_MOUNT_WRITABLE = ("scratch", "work", "outputs", "library")


@contextmanager
def _mounted_backend(
    tmp_path: Path,
    *,
    mode: MountMode = "read_only",
) -> Iterator[tuple[AnchoredAgentWorkspaceBackend, Path]]:
    """A backend over a real execution root plus one anchored ``library`` mount."""

    active = policy(readable=_MOUNT_READABLE, writable=_MOUNT_WRITABLE)
    harness = make_workspace(tmp_path, active_policy=active)
    # The mounted backend owns the same execution root through its own descriptor.
    harness.lease.backend.close()
    mount_dir = tmp_path / "mount"
    mount_dir.mkdir(mode=0o700)
    (mount_dir / "plan.md").write_text("# Plan\n")
    os.chmod(mount_dir / "plan.md", 0o400)
    mount_fd = os.open(mount_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    root_fd = os.open(harness.thread_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    backend: AnchoredAgentWorkspaceBackend | None = None
    try:
        backend = AnchoredAgentWorkspaceBackend(
            execution_fd=root_fd,
            identity=harness.lease.identity,
            policy=active,
            artifact_sink=RecordingArtifactSink(),
            mounts=(WorkspaceMount(name="library", directory_fd=mount_fd, mode=mode),),
        )
        yield backend, mount_dir
    finally:
        if backend is None:
            os.close(root_fd)
            os.close(mount_fd)
        else:
            backend.close()
        harness.factory.close()


def test_a_read_only_mount_is_readable_by_its_virtual_name_and_never_writable(
    tmp_path: Path,
) -> None:
    with _mounted_backend(tmp_path) as (backend, mount_dir):
        assert backend.read_text_sync("library/plan.md") == "# Plan\n"
        assert backend.stat_entry_sync("library/plan.md").read_only is True

        with pytest.raises(WorkspaceSecurityError) as raised:
            backend.write_text_sync("library/new.md", "nope")
        assert "read-only mount" in str(raised.value)
        assert not (mount_dir / "new.md").exists()

        write_error = backend.write("library/new.md", "nope").error or ""
        assert write_error.startswith("permission_denied")
        edit_error = backend.edit("library/plan.md", "# Plan", "# Other").error or ""
        assert edit_error.startswith("permission_denied")

        # A mount root is a directory, never a file.
        with pytest.raises(WorkspaceSecurityError):
            backend.read_text_sync("library")

        # The thread root is unaffected.
        assert backend.write_text_sync("work/note.md", "mine").path == "work/note.md"


def test_root_listing_shows_mounts_as_directories(tmp_path: Path) -> None:
    with _mounted_backend(tmp_path) as (backend, _mount_dir):
        backend.write_text_sync("work/note.md", "mine")
        entries = backend.ls("/").entries or []
        assert {"path": "library", "is_dir": True, "size": 0} in entries
        assert {"path": "library/plan.md", "is_dir": False, "size": 7} in entries
        assert {"path": "work/note.md", "is_dir": False, "size": 4} in entries
        assert [item.path for item in backend.list_entries_sync("library")] == ["library/plan.md"]
        matches = backend.glob("*.md", "library").matches or []
        assert {"path": "library/plan.md", "is_dir": False, "size": 7} in matches
        root_matches = backend.glob("**").matches or []
        assert {"path": "library", "is_dir": True, "size": 0} in root_matches
        # A bare glob sweeps the mount root in, but grep has no bytes to read there.
        grepped = backend.grep("Plan")
        assert grepped.error is None
        assert grepped.matches == [{"path": "library/plan.md", "line": 1, "text": "# Plan"}]


@pytest.mark.parametrize("pattern", ["**/*", "**/*.md", "**/**/SKILL.md", "*.md"])
def test_recursive_manual_search_includes_direct_and_nested_files(
    tmp_path: Path, pattern: str
) -> None:
    harness = make_workspace(tmp_path)
    backend = harness.lease.backend
    prefix = ".deepagent/skills/manual-tools/v7"
    try:
        backend.materialize_bytes(f"{prefix}/SKILL.md", b"open_design_leg\n")
        backend.materialize_bytes(f"{prefix}/nested/SKILL.md", b"open_design_leg\n")
        backend.freeze_materialized_trees()

        listed = backend.glob(pattern, prefix)
        assert listed.error is None
        assert {entry["path"] for entry in listed.matches or []} == {
            f"{prefix}/SKILL.md",
            f"{prefix}/nested/SKILL.md",
        }
        searched = backend.grep("open_design_leg", prefix, glob=pattern)
        assert searched.error is None
        assert {match["path"] for match in searched.matches or []} == {
            f"{prefix}/SKILL.md",
            f"{prefix}/nested/SKILL.md",
        }
    finally:
        harness.close()


@pytest.mark.parametrize("include", [None, "**/*", "*.md", "*.txt"])
def test_grep_file_path_searches_only_that_file_and_honors_filter(
    tmp_path: Path, include: str | None
) -> None:
    with _mounted_backend(tmp_path) as (backend, _mount_dir):
        backend.write_text_sync("work/unrelated.md", "# Plan\n")
        result = backend.grep("Plan", "/library/plan.md", glob=include)
        assert result.error is None
        assert result.matches == (
            [] if include == "*.txt" else [{"path": "library/plan.md", "line": 1, "text": "# Plan"}]
        )


@pytest.mark.parametrize("unsafe", ["symlink", "hardlink", "public", "executable"])
def test_grep_file_path_refuses_unsafe_files(tmp_path: Path, unsafe: str) -> None:
    harness = make_workspace(tmp_path)
    try:
        backend = harness.lease.backend
        backend.write_text_sync("work/secret.md", "private marker\n")
        source = harness.thread_path / "work/secret.md"
        target = harness.thread_path / "work/target.md"
        if unsafe == "symlink":
            target.symlink_to(source)
        elif unsafe == "hardlink":
            os.link(source, target)
        else:
            target.write_text("private marker\n")
            target.chmod(0o644 if unsafe == "public" else 0o700)
        result = backend.grep("private marker", "work/target.md")
        assert result.error is not None
        assert result.error.startswith("permission_denied")
        assert not result.matches
        assert str(harness.root) not in result.error
    finally:
        harness.close()


def test_a_mount_cannot_be_escaped_or_shadowed(tmp_path: Path) -> None:
    # The shadowing half of this guarantee — a mount may not claim a layout name — is
    # proven by test_a_mount_name_may_not_shadow_the_layout_or_be_malformed below.
    with _mounted_backend(tmp_path) as (backend, mount_dir):
        with pytest.raises(WorkspaceSecurityError):
            backend.read_text_sync("library/../inputs/seed.md")
        with pytest.raises(WorkspaceSecurityError):
            backend.materialize_bytes("library/x.md", b"trusted")
        assert not (mount_dir / "x.md").exists()

        os.symlink("/etc/passwd", mount_dir / "escape.md")
        with pytest.raises(WorkspaceSecurityError):
            backend.read_text_sync("library/escape.md")
        with pytest.raises(WorkspaceSecurityError):
            backend.list_entries_sync("library")


@pytest.mark.parametrize(
    "names",
    [
        ("outputs",),
        (".deepagent",),
        ("inputs",),
        ("Library",),
        ("-bad",),
        ("x" * 33,),
        ("",),
        ("library", "library"),
    ],
)
def test_a_mount_name_may_not_shadow_the_layout_or_be_malformed(
    tmp_path: Path,
    names: tuple[str, ...],
) -> None:
    active = policy(readable=_MOUNT_READABLE, writable=_MOUNT_WRITABLE)
    harness = make_workspace(tmp_path, active_policy=active)
    harness.lease.backend.close()
    mount_dir = tmp_path / "mount"
    mount_dir.mkdir(mode=0o700)
    fds = [
        os.open(harness.thread_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW),
        *(os.open(mount_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW) for _ in names),
    ]
    try:
        with pytest.raises(WorkspaceConfigurationError):
            AnchoredAgentWorkspaceBackend(
                execution_fd=fds[0],
                identity=harness.lease.identity,
                policy=active,
                artifact_sink=RecordingArtifactSink(),
                mounts=tuple(
                    WorkspaceMount(name=name, directory_fd=fd, mode="read_only")
                    for name, fd in zip(names, fds[1:], strict=True)
                ),
            )
    finally:
        for fd in fds:
            os.close(fd)
        harness.factory.close()


def test_a_read_write_mount_takes_writes_under_the_thread_quota(tmp_path: Path) -> None:
    with _mounted_backend(tmp_path, mode="read_write") as (backend, mount_dir):
        # The mount already holds one file; the single policy quota counts it.
        assert backend.usage_snapshot().file_count == 1
        for index in range(18):
            backend.write_text_sync(f"work/note-{index}.md", "x")
        entry = backend.write_text_sync("library/added.md", "fresh")
        assert entry.path == "library/added.md"
        assert (mount_dir / "added.md").read_text() == "fresh"
        # The bytes land in the mount, never in a same-named folder under the thread root.
        assert sorted(os.listdir(mount_dir)) == ["added.md", "plan.md"]
        assert stat.S_IMODE((mount_dir / "added.md").stat().st_mode) == 0o600

        edited = backend.edit_text_sync("library/added.md", old="fresh", new="edited")
        assert edited.path == "library/added.md"
        assert (mount_dir / "added.md").read_text() == "edited"

        snapshot = backend.usage_snapshot()
        assert snapshot.file_count == 20
        with pytest.raises(WorkspaceQuotaExceeded):
            backend.write_text_sync("work/overflow.md", "x")
        with pytest.raises(WorkspaceQuotaExceeded):
            backend.write_text_sync("library/overflow.md", "x")


# --- the thread-rooted workspace ----------------------------------------------------------


_SECOND_EXECUTION = ExecutionId(UUID("00000000-0000-0000-0000-000000000621"))


def test_the_factory_roots_the_workspace_at_the_thread(tmp_path: Path) -> None:
    root, factory, _sink = make_factory(tmp_path)
    try:
        lease = factory.create(
            workspace_id="ws_a",
            project_id="prj_a",
            thread_id="thr_a",
            execution_id=EXECUTION_ID,
            policy=policy(),
        )
        thread = root / "ws_a" / "projects" / "prj_a" / "threads" / "thr_a"
        assert sorted(path.name for path in thread.iterdir()) == [
            ".deepagent",
            "context",
            "inputs",
            "outputs",
            "reads",
            "scratch",
            "work",
        ]
        for path in (
            thread,
            thread.parent,
            thread.parent.parent,
            thread.parent.parent.parent,
            thread.parent.parent.parent.parent,
        ):
            assert stat.S_IMODE(path.stat().st_mode) == 0o700
        assert lease.identity.thread_id == "thr_a"
        assert lease.identity.execution_id == EXECUTION_ID
        assert lease.identity.workspace_root_id == expected_root_id("ws_a", "prj_a", "thr_a")
    finally:
        factory.close()


def test_scratch_and_reads_survive_across_turns_of_the_thread(tmp_path: Path) -> None:
    root, factory, _sink = make_factory(tmp_path)
    try:
        first = factory.create(
            workspace_id="ws-1",
            project_id="project-1",
            thread_id="thread-1",
            execution_id=EXECUTION_ID,
            policy=policy(),
        )
        first.backend.write_text_sync("scratch/notes.md", "one\n")
        # ``reads/`` is a trusted-writer folder: the policy's writable prefixes exclude it.
        read_back = root / "ws-1/projects/project-1/threads/thread-1/reads/account.md"
        read_back.write_text("read-back\n")
        os.chmod(read_back, 0o600)
        first.backend.write_text_sync("outputs/report.md", "final\n")
        asyncio.run(first.backend.snapshot_outputs())
        first.release()
        assert first.backend._closed is True

        second = factory.acquire(
            workspace_id="ws-1",
            project_id="project-1",
            thread_id="thread-1",
            execution_id=_SECOND_EXECUTION,
            policy=policy(),
        )
        assert second.backend is not first.backend
        assert second.identity.execution_id == _SECOND_EXECUTION
        assert second.identity.workspace_root_id == first.identity.workspace_root_id
        assert second.backend.read_text_sync("scratch/notes.md") == "one\n"
        assert second.backend.read_text_sync("reads/account.md") == "read-back\n"
        second.backend.edit_text_sync("scratch/notes.md", old="one\n", new="one\ntwo\n")
        assert (root / "ws-1/projects/project-1/threads/thread-1/scratch/notes.md").read_text() == (
            "one\ntwo\n"
        )
    finally:
        factory.close()


def test_a_partially_frozen_thread_reopens_unfrozen_and_is_rebuilt(tmp_path: Path) -> None:
    """A crash between the three freezes must be repairable, not a permanently dead thread."""

    root, factory, _sink = make_factory(tmp_path)
    materializer = AgentResourceMaterializer()
    snapshot, seeds = resource_snapshot()
    try:
        first = factory.create(
            workspace_id="ws-1",
            project_id="project-1",
            thread_id="thread-1",
            execution_id=EXECUTION_ID,
            policy=policy(),
        )
        materializer.materialize(lease=first, snapshot=snapshot, seed_files=seeds)
        first.release()
        # The crash: ``context/`` was frozen and the other two never were, so the three
        # trusted trees disagree and ``materialized_trees_frozen`` refuses to answer.
        thread_root = root / "ws-1/projects/project-1/threads/thread-1"
        os.chmod(thread_root / "inputs", 0o700)
        os.chmod(thread_root / ".deepagent", 0o700)

        second = factory.acquire(
            workspace_id="ws-1",
            project_id="project-1",
            thread_id="thread-1",
            execution_id=_SECOND_EXECUTION,
            policy=policy(),
        )
        with pytest.raises(WorkspaceSecurityError):
            second.backend.materialized_trees_frozen()
        assert second.resources_frozen is False

        # Either branch of the turn wiring repairs it; this is the resume branch.
        materializer.verify_materialized(lease=second, snapshot=snapshot, seed_files=seeds)
        assert second.resources_frozen is True
        assert second.materialized is True
        assert second.backend.materialized_trees_frozen() is True
        assert second.backend.read_text_sync("context/project.json") == '{"project":"project-1"}'
    finally:
        factory.close()


def test_one_live_lease_per_thread(tmp_path: Path) -> None:
    root, factory, _sink = make_factory(tmp_path)
    try:
        first = factory.create(
            workspace_id="ws-1",
            project_id="project-1",
            thread_id="thread-1",
            execution_id=EXECUTION_ID,
            policy=policy(),
        )
        with pytest.raises(WorkspaceConflict):
            factory.acquire(
                workspace_id="ws-1",
                project_id="project-1",
                thread_id="thread-1",
                execution_id=_SECOND_EXECUTION,
                policy=policy(),
            )
        # The same execution re-acquiring is in-process crash resume, not a second turn.
        resumed = factory.acquire(
            workspace_id="ws-1",
            project_id="project-1",
            thread_id="thread-1",
            execution_id=EXECUTION_ID,
            policy=policy(),
        )
        assert resumed.backend is first.backend
        # A sibling thread of the same project is unaffected.
        sibling = factory.acquire(
            workspace_id="ws-1",
            project_id="project-1",
            thread_id="thread-2",
            execution_id=_SECOND_EXECUTION,
            policy=policy(),
        )
        assert sibling.backend is not first.backend
        assert (root / "ws-1/projects/project-1/threads/thread-2").is_dir()
        # Releasing the first lease frees the thread for the next turn, and releasing twice
        # is a no-op rather than an error.
        first.release()
        first.release()
        after = factory.acquire(
            workspace_id="ws-1",
            project_id="project-1",
            thread_id="thread-1",
            execution_id=_SECOND_EXECUTION,
            policy=policy(),
        )
        assert after.backend is not first.backend
        # A late second release from the finished turn must not close the new turn's backend.
        first.release()
        assert after.backend.write_text_sync("scratch/next.md", "two").path == "scratch/next.md"
    finally:
        factory.close()


def test_purge_thread_removes_the_directory_and_reports_absence_the_second_time(
    tmp_path: Path,
) -> None:
    harness = make_workspace(tmp_path)
    try:
        harness.lease.backend.write_text_sync("scratch/notes.md", "one\n")
        assert harness.factory.purge_thread(
            workspace_id="ws-1",
            project_id="project-1",
            thread_id="thread-1",
        )
        assert not harness.thread_path.exists()
        # The now-empty scope levels go with it, up to the prepared root itself.
        assert not (harness.root / "ws-1").exists()
        assert harness.root.is_dir()
        with pytest.raises(WorkspaceSecurityError, match="closed"):
            harness.lease.backend.read_text_sync("scratch/notes.md")
        assert not harness.factory.purge_thread(
            workspace_id="ws-1",
            project_id="project-1",
            thread_id="thread-1",
        )
    finally:
        harness.factory.close()


@pytest.mark.parametrize("thread_id", ["../thr", "", "thr/one", "thr thread"])
def test_a_thread_id_is_validated_like_every_other_segment(tmp_path: Path, thread_id: str) -> None:
    root, factory, _sink = make_factory(tmp_path)
    try:
        with pytest.raises(WorkspaceConfigurationError):
            factory.create(
                workspace_id="ws-1",
                project_id="project-1",
                thread_id=thread_id,
                execution_id=EXECUTION_ID,
                policy=policy(),
            )
        assert not (root / "ws-1" / "projects" / "project-1" / "threads").exists()
    finally:
        factory.close()


# --- requested mounts ---------------------------------------------------------------------


def _library(root: Path, *parts: str) -> Path:
    path = root
    for part in parts:
        path = path / part
        if not path.exists():
            path.mkdir(mode=0o700)
    return path


def test_a_mount_request_opens_the_brand_and_project_libraries_read_only(
    tmp_path: Path,
) -> None:
    root, factory, _sink = make_factory(tmp_path)
    brand = _library(root, "ws-1", "library", "brand", "brand-1", "v3")
    (brand / "kit.md").write_text("# Kit\n")
    os.chmod(brand / "kit.md", 0o400)
    project = _library(root, "ws-1", "projects", "project-1", "library")
    (project / "brief.md").write_text("# Brief\n")
    os.chmod(project / "brief.md", 0o400)
    active = policy(
        readable=(*DEFAULT_READABLE_PREFIXES, "brand", "project"),
        writable=DEFAULT_WRITABLE_PREFIXES,
    )
    try:
        lease = factory.create(
            workspace_id="ws-1",
            project_id="project-1",
            thread_id="thread-1",
            execution_id=EXECUTION_ID,
            policy=active,
            mounts=MountRequest(brand=("brand-1", "v3"), project_library=True),
        )
        assert lease.backend.read_text_sync("brand/kit.md") == "# Kit\n"
        assert lease.backend.read_text_sync("project/brief.md") == "# Brief\n"
        with pytest.raises(WorkspaceSecurityError):
            lease.backend.write_text_sync("brand/new.md", "nope")
        with pytest.raises(WorkspaceSecurityError):
            lease.backend.write_text_sync("project/new.md", "nope")
        # The mounts are outside the thread root and are never copied into it.
        assert not (root / "ws-1/projects/project-1/threads/thread-1/brand").exists()
    finally:
        factory.close()


@pytest.mark.parametrize(
    "request_",
    [
        MountRequest(brand=("brand-1", "v3")),
        MountRequest(project_library=True),
    ],
)
def test_a_mount_request_for_an_unmaterialized_library_is_refused(
    tmp_path: Path, request_: MountRequest
) -> None:
    _root, factory, _sink = make_factory(tmp_path)
    try:
        with pytest.raises(WorkspaceConfigurationError, match="library is not materialized"):
            factory.create(
                workspace_id="ws-1",
                project_id="project-1",
                thread_id="thread-1",
                execution_id=EXECUTION_ID,
                policy=policy(),
                mounts=request_,
            )
    finally:
        factory.close()


def test_a_named_project_tree_is_mounted_as_project_and_can_be_removed(tmp_path: Path) -> None:
    """One turn's own tree, beside the project's library, under the same virtual name.

    A turn whose pinned library generation is no longer the installed one materializes that
    generation beside the library and mounts it instead, so ``project/`` means "what this turn
    pinned" and every path the model was told to read still resolves. Two rules make that safe and
    are asserted here: the name is a segment the factory validates (never a path), and the shared
    library is not something a turn may remove.
    """

    root, factory, _sink = make_factory(tmp_path)
    _library(root, "ws-1", "projects", "project-1", "library")
    pinned = _library(root, "ws-1", "projects", "project-1", "pinned-0123456789ab")
    (pinned / "status.md").write_text("# Pinned\n")
    os.chmod(pinned / "status.md", 0o400)
    active = policy(readable=(*DEFAULT_READABLE_PREFIXES, "project"))
    try:
        lease = factory.create(
            workspace_id="ws-1",
            project_id="project-1",
            thread_id="thread-1",
            execution_id=EXECUTION_ID,
            policy=active,
            mounts=MountRequest(project_library=True, project_library_name="pinned-0123456789ab"),
        )
        assert lease.backend.read_text_sync("project/status.md") == "# Pinned\n"
        lease.release()

        # The project's shared library belongs to every thread of the project: no turn removes it.
        with pytest.raises(WorkspaceConfigurationError):
            factory.remove_project_tree("ws-1", "project-1", "library")
        # …and the name is one segment, never a path out of the project.
        with pytest.raises(WorkspaceConfigurationError):
            factory.remove_project_tree("ws-1", "project-1", "../library")
        assert (root / "ws-1/projects/project-1/library").is_dir()

        # …and the tree's own superseded/crashed-build residue goes with it: nothing else ever
        # replaces a per-turn tree, so nothing else would ever reclaim it.
        residue = _library(root, "ws-1", "projects", "project-1", "pinned-0123456789ab.old-999")
        factory.remove_project_tree("ws-1", "project-1", "pinned-0123456789ab")
        assert not pinned.exists()
        assert not residue.exists()
        # Idempotent: the turn's ``finally`` runs whether or not the tree was ever built.
        factory.remove_project_tree("ws-1", "project-1", "pinned-0123456789ab")
    finally:
        factory.close()


def test_reacquiring_a_live_thread_with_another_mount_request_conflicts(tmp_path: Path) -> None:
    root, factory, _sink = make_factory(tmp_path)
    _library(root, "ws-1", "projects", "project-1", "library")
    active = policy(readable=(*DEFAULT_READABLE_PREFIXES, "project"))
    try:
        first = factory.create(
            workspace_id="ws-1",
            project_id="project-1",
            thread_id="thread-1",
            execution_id=EXECUTION_ID,
            policy=active,
            mounts=MountRequest(project_library=True),
        )
        with pytest.raises(WorkspaceConflict):
            factory.acquire(
                workspace_id="ws-1",
                project_id="project-1",
                thread_id="thread-1",
                execution_id=EXECUTION_ID,
                policy=active,
                mounts=MountRequest(),
            )
        resumed = factory.acquire(
            workspace_id="ws-1",
            project_id="project-1",
            thread_id="thread-1",
            execution_id=EXECUTION_ID,
            policy=active,
            mounts=MountRequest(project_library=True),
        )
        assert resumed.backend is first.backend
    finally:
        factory.close()


# --- the versioned project mount ----------------------------------------------------------


_DOCUMENT_ID = UUID("00000000-0000-0000-0000-0000000009a1")
_VERSIONED_READABLE = (*DEFAULT_READABLE_PREFIXES, "project")
_VERSIONED_WRITABLE = (*DEFAULT_WRITABLE_PREFIXES, "project")
_REFUSAL = "plan.md is at version 3, you read version 2 — read it again"


def _generation(bodies: Mapping[str, str], versions: Mapping[str, int]) -> list[LibraryFile]:
    """One whole library generation: the documents, plus the manifest that versions them.

    The manifest is shaped like the real ``ProjectLibraryIndexCard`` — a tree-relative ``path``
    beside the ``workspace_path`` the mount serves it at, and a null ``version`` for a compiled
    file — because the backend reads its version map straight out of it.
    """

    digest = hashlib.sha256(repr(sorted(versions.items())).encode("utf-8")).hexdigest()
    index = {
        "schema_version": "1",
        "card_kind": "project_library_index",
        "project_id": "project-1",
        "library_sha256": digest,
        "artifacts": 0,
        "files": [
            {
                "path": path,
                "workspace_path": f"project/{path}",
                "kind": "plan",
                "version": versions.get(path),
                "status": "ready",
                "summary": body.splitlines()[0] if body else "",
                "artifact_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            }
            for path, body in sorted(bodies.items())
        ],
    }
    return [
        *(LibraryFile(path, body.encode("utf-8")) for path, body in sorted(bodies.items())),
        LibraryFile("index.json", json.dumps(index).encode("utf-8")),
    ]


def _install(factory: AgentWorkspaceFactory, writer: _RecordingWriter) -> None:
    """Install the writer's current documents as the project library's live generation."""

    files = _generation(writer.bodies, writer.versions)
    digest = json.loads(bytes(files[-1].content))["library_sha256"]
    parent_fd = factory.project_parent_fd("ws-1", "project-1")
    try:
        LibraryTree(parent_fd=parent_fd, name="library").replace(files, digest=digest)
    finally:
        os.close(parent_fd)


@dataclass
class _RecordingWriter:
    """A stand-in document store: it versions what it is given and rebuilds the library.

    It is the whole of the seam the backend depends on — take a write against the version the
    reader had, then re-materialize the tree — so the tests can prove the backend's half without
    a database behind it.
    """

    factory: AgentWorkspaceFactory | None = None
    bodies: dict[str, str] = field(default_factory=dict)
    versions: dict[str, int] = field(default_factory=dict)
    calls: list[tuple[str, str, int | None]] = field(default_factory=list)
    refuse: bool = False

    def write(
        self,
        *,
        path: str,
        content: str,
        expected_version: int | None,
    ) -> VersionedWriteOutcome:
        self.calls.append((path, content, expected_version))
        if self.refuse:
            raise VersionedWriteRefused("revision_conflict", _REFUSAL)
        version = self.versions.get(path, 0) + 1
        self.versions[path] = version
        self.bodies[path] = content
        return VersionedWriteOutcome(
            path=path,
            version=version,
            document_id=_DOCUMENT_ID,
            kind="plan",
            status="ready",
            replayed=False,
        )

    def refresh(self) -> dict[str, int]:
        assert self.factory is not None
        _install(self.factory, self)
        return dict(self.versions)


@contextmanager
def _versioned_project(tmp_path: Path) -> Iterator[tuple[AgentWorkspaceLease, _RecordingWriter]]:
    """A thread whose ``project`` mount is versioned, over a real installed library tree."""

    _root, factory, _sink = make_factory(tmp_path)
    writer = _RecordingWriter(bodies={"plan.md": "# Plan\nfirst\n"}, versions={"plan.md": 2})
    writer.factory = factory
    _install(factory, writer)
    try:
        lease = factory.create(
            workspace_id="ws-1",
            project_id="project-1",
            thread_id="thread-1",
            execution_id=EXECUTION_ID,
            policy=policy(readable=_VERSIONED_READABLE, writable=_VERSIONED_WRITABLE),
            mounts=MountRequest(project_library=True, project_writer=writer),
        )
        yield lease, writer
    finally:
        factory.close()


def test_a_versioned_write_carries_the_read_version_and_re_reads_the_refreshed_library(
    tmp_path: Path,
) -> None:
    with _versioned_project(tmp_path) as (lease, writer):
        backend = lease.backend
        # The mount's map comes from the generation's own manifest, so the first write tells the
        # writer which version the model was looking at.
        entry = backend.write_text_sync("project/plan.md", "# Plan\nsecond\n")
        assert writer.calls == [("plan.md", "# Plan\nsecond\n", 2)]
        assert entry.path == "project/plan.md"

        # The entry, and every later read, come from the tree the writer just rebuilt.
        assert backend.read_text_sync("project/plan.md") == "# Plan\nsecond\n"
        assert entry.byte_count == len("# Plan\nsecond\n")

        # …and the map moved with it: the next write is optimistic about version 3, not 2.
        backend.write_text_sync("project/plan.md", "# Plan\nthird\n")
        assert writer.calls[-1] == ("plan.md", "# Plan\nthird\n", 3)
        # A path the library has never versioned is written with no expectation at all.
        backend.write_text_sync("project/audience/icp.md", "# ICP\n")
        assert writer.calls[-1][:2] == ("audience/icp.md", "# ICP\n")
        assert writer.calls[-1][2] is None

        assert [
            (outcome.path, outcome.version, outcome.replayed)
            for outcome in backend.written_documents
        ] == [("plan.md", 3, False), ("plan.md", 4, False), ("audience/icp.md", 1, False)]
        assert backend.written_documents[0].document_id == _DOCUMENT_ID

        listed = [item.path for item in backend.list_entries_sync("project")]
        assert listed == ["project/audience/icp.md", "project/index.json", "project/plan.md"]
        assert {"path": "project/plan.md", "is_dir": False, "size": len("# Plan\nthird\n")} in (
            backend.ls("project").entries or []
        )


def test_a_versioned_edit_replaces_one_occurrence_and_writes_the_whole_document(
    tmp_path: Path,
) -> None:
    with _versioned_project(tmp_path) as (lease, writer):
        backend = lease.backend
        entry = backend.edit_text_sync("project/plan.md", old="first", new="second")
        # The edit is read-then-write: the library's bytes decide what the new document says,
        # and the writer takes the whole of it as one version.
        assert writer.calls == [("plan.md", "# Plan\nsecond\n", 2)]
        assert entry.path == "project/plan.md"
        assert backend.read_text_sync("project/plan.md") == "# Plan\nsecond\n"
        assert [outcome.version for outcome in backend.written_documents] == [3]

        # The single-occurrence rule is the thread root's, unchanged, and nothing reaches the
        # writer when it is not met.
        with pytest.raises(WorkspaceConflict, match="edit source text was not found"):
            backend.edit_text_sync("project/plan.md", old="absent", new="x")
        backend.write_text_sync("project/plan.md", "# Plan\ntwice twice\n")
        with pytest.raises(WorkspaceConflict, match="edit source text is not unique"):
            backend.edit_text_sync("project/plan.md", old="twice", new="x")
        assert len(writer.calls) == 2


def test_a_refused_versioned_write_reaches_the_model_as_a_readable_conflict(
    tmp_path: Path,
) -> None:
    with _versioned_project(tmp_path) as (lease, writer):
        backend = lease.backend
        writer.refuse = True
        with pytest.raises(WorkspaceConflict) as raised:
            backend.write_text_sync("project/plan.md", "# Plan\nsecond\n")
        assert str(raised.value) == f"revision_conflict: {_REFUSAL}"

        # The facade is what the model actually sees: the code rides in front of the sentence so
        # the model can tell "you are behind" from "you may not write this".
        assert backend.write("project/plan.md", "# Plan\nsecond\n").error == (
            f"conflict: revision_conflict: {_REFUSAL}"
        )
        assert backend.edit("project/plan.md", "first", "second").error == (
            f"conflict: revision_conflict: {_REFUSAL}"
        )
        # Nothing was recorded and the library still reads as it did.
        assert backend.written_documents == ()
        assert backend.read_text_sync("project/plan.md") == "# Plan\nfirst\n"


def test_a_versioned_mount_is_read_only_to_everything_but_its_writer(tmp_path: Path) -> None:
    with _versioned_project(tmp_path) as (lease, writer):
        backend = lease.backend
        # Trusted platform bytes — materialized resources, a spilled read — never land in a
        # mount, versioned or not.
        with pytest.raises(WorkspaceSecurityError, match="cannot hold a trusted platform write"):
            backend.materialize_bytes("project/pinned.md", b"trusted")
        # The mount is not the thread's to spend: its bytes are the document store's.
        assert backend.usage_snapshot().file_count == 0
        # …and the writer is the only way in, so nothing was written beside it.
        assert writer.calls == []


def test_a_project_mount_without_a_writer_stays_read_only(tmp_path: Path) -> None:
    _root, factory, _sink = make_factory(tmp_path)
    writer = _RecordingWriter(bodies={"plan.md": "# Plan\n"}, versions={"plan.md": 1})
    writer.factory = factory
    _install(factory, writer)
    try:
        lease = factory.create(
            workspace_id="ws-1",
            project_id="project-1",
            thread_id="thread-1",
            execution_id=EXECUTION_ID,
            policy=policy(readable=_VERSIONED_READABLE, writable=_VERSIONED_WRITABLE),
            mounts=MountRequest(project_library=True),
        )
        with pytest.raises(WorkspaceSecurityError, match="read-only mount"):
            lease.backend.write_text_sync("project/plan.md", "nope")
        assert (lease.backend.write("project/plan.md", "nope").error or "").startswith(
            "permission_denied"
        )
        assert writer.calls == []
    finally:
        factory.close()


def test_a_versioned_mount_carries_its_writer_and_reopen_or_is_refused(tmp_path: Path) -> None:
    """Both halves or neither — a versioned mount with no writer would write to a real tree."""

    harness = make_workspace(tmp_path)
    harness.lease.backend.close()
    mount_dir = tmp_path / "mount"
    mount_dir.mkdir(mode=0o700)
    writer = _RecordingWriter()
    partial = [
        {"mode": "versioned"},
        {"mode": "versioned", "writer": writer},
        {"mode": "versioned", "reopen": lambda: -1},
        {"mode": "read_only", "writer": writer, "reopen": lambda: -1},
    ]
    try:
        for fields in partial:
            root_fd = os.open(harness.thread_path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            mount_fd = os.open(mount_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                with pytest.raises(WorkspaceConfigurationError, match="versioned mount"):
                    AnchoredAgentWorkspaceBackend(
                        execution_fd=root_fd,
                        identity=harness.lease.identity,
                        policy=policy(),
                        artifact_sink=RecordingArtifactSink(),
                        mounts=(
                            WorkspaceMount(name="project", directory_fd=mount_fd, **fields),  # type: ignore[arg-type]
                        ),
                    )
            finally:
                os.close(root_fd)
                os.close(mount_fd)
    finally:
        harness.factory.close()


# --- anchored library parents -------------------------------------------------------------


def test_the_library_parents_are_private_directories_the_scope_audit_accepts(
    tmp_path: Path,
) -> None:
    root, factory, _sink = make_factory(tmp_path)
    try:
        library_fd = factory.library_parent_fd("ws-1")
        try:
            assert stat.S_IMODE(os.fstat(library_fd).st_mode) == 0o700
            brand_fd = factory.ensure_child_directory(library_fd, "brand")
            try:
                assert stat.S_IMODE(os.fstat(brand_fd).st_mode) == 0o700
            finally:
                os.close(brand_fd)
        finally:
            os.close(library_fd)
        project_fd = factory.project_parent_fd("ws-1", "project-1")
        try:
            assert stat.S_IMODE(os.fstat(project_fd).st_mode) == 0o700
        finally:
            os.close(project_fd)

        assert stat.S_IMODE((root / "ws-1/library").stat().st_mode) == 0o700
        assert stat.S_IMODE((root / "ws-1/library/brand").stat().st_mode) == 0o700
        assert stat.S_IMODE((root / "ws-1/projects/project-1").stat().st_mode) == 0o700
        # Both helpers are idempotent and a thread still opens beside them.
        os.close(factory.library_parent_fd("ws-1"))
        os.close(factory.project_parent_fd("ws-1", "project-1"))
        lease = factory.create(
            workspace_id="ws-1",
            project_id="project-1",
            thread_id="thread-1",
            execution_id=EXECUTION_ID,
            policy=policy(),
        )
        assert lease.identity.thread_id == "thread-1"
    finally:
        factory.close()


@pytest.mark.parametrize("segment", ["../escape", "with space", ".hidden", "", "a/b"])
def test_the_library_parents_refuse_a_hostile_segment(tmp_path: Path, segment: str) -> None:
    root, factory, _sink = make_factory(tmp_path)
    try:
        with pytest.raises(WorkspaceConfigurationError):
            factory.library_parent_fd(segment)
        with pytest.raises(WorkspaceConfigurationError):
            factory.project_parent_fd("ws-1", segment)
        # Nothing on the refused path was created on the way to the refusal.
        assert not (root / "ws-1").exists()

        library_fd = factory.library_parent_fd("ws-1")
        try:
            with pytest.raises(WorkspaceConfigurationError):
                factory.ensure_child_directory(library_fd, segment)
        finally:
            os.close(library_fd)
        assert list((root / "ws-1/library").iterdir()) == []
        assert not (root / "ws-1/projects").exists()
    finally:
        factory.close()


def test_a_frozen_library_beside_threads_does_not_break_the_scope_audit(tmp_path: Path) -> None:
    """A materialized 0500 project library must not lock every thread out of its project."""

    root, factory, _sink = make_factory(tmp_path)
    try:
        first = factory.create(
            workspace_id="ws-1",
            project_id="project-1",
            thread_id="thread-1",
            execution_id=EXECUTION_ID,
            policy=policy(),
        )
        library = root / "ws-1/projects/project-1/library"
        library.mkdir(mode=0o700)
        (library / "brief.md").write_text("# Brief\n")
        os.chmod(library / "brief.md", 0o400)
        os.chmod(library, 0o500)

        sibling = factory.create(
            workspace_id="ws-1",
            project_id="project-1",
            thread_id="thread-2",
            execution_id=ExecutionId(UUID("00000000-0000-0000-0000-0000000006f1")),
            policy=policy(),
        )
        assert sibling.identity.thread_id == "thread-2"
        first.release()
        resumed = factory.acquire(
            workspace_id="ws-1",
            project_id="project-1",
            thread_id="thread-1",
            execution_id=EXECUTION_ID,
            policy=policy(),
        )
        assert resumed.identity.thread_id == "thread-1"
        os.close(factory.project_parent_fd("ws-1", "project-1"))
    finally:
        factory.close()


@pytest.mark.parametrize("mode", [0o600, 0o755, 0o770])
def test_any_other_sibling_directory_mode_is_still_refused(tmp_path: Path, mode: int) -> None:
    root, factory, _sink = make_factory(tmp_path)
    try:
        factory.create(
            workspace_id="ws-1",
            project_id="project-1",
            thread_id="thread-1",
            execution_id=EXECUTION_ID,
            policy=policy(),
        )
        odd = root / "ws-1/projects/project-1/library"
        odd.mkdir(mode=0o700)
        os.chmod(odd, mode)
        try:
            with pytest.raises(WorkspaceSecurityError):
                factory.create(
                    workspace_id="ws-1",
                    project_id="project-1",
                    thread_id="thread-2",
                    execution_id=ExecutionId(UUID("00000000-0000-0000-0000-0000000006f2")),
                    policy=policy(),
                )
            with pytest.raises(WorkspaceSecurityError):
                factory.project_parent_fd("ws-1", "project-1")
        finally:
            os.chmod(odd, 0o700)
    finally:
        factory.close()


_SPILL_OPERATION = "00000000-0000-0000-0000-0000000006aa"


def test_a_spilled_read_lands_in_reads_where_the_model_can_open_it(tmp_path: Path) -> None:
    """The whole point of the spill: bytes the model could not be handed, it can now open.

    ``reads/`` is readable authority and nobody's writable authority, so the same call has to
    succeed for the runtime and stay impossible for the model — both halves are asserted here.
    """

    harness = make_workspace(tmp_path)
    backend = harness.lease.backend
    try:
        payload = json.dumps({"claims": ["a" * 40 for _ in range(20)]}).encode()
        path = backend.write_spill(_SPILL_OPERATION, payload)

        assert path == f"reads/{_SPILL_OPERATION}.json"
        assert backend.read_text_sync(path) == payload.decode()
        assert (harness.thread_path / path).read_bytes() == payload
        assert [entry.path for entry in backend.list_entries_sync("reads")] == [path]
        with pytest.raises(WorkspaceSecurityError):
            backend.write_text_sync(path, "the model's own hand")
    finally:
        harness.close()


def test_a_respilled_operation_replaces_its_own_file_rather_than_colliding(tmp_path: Path) -> None:
    """A replayed or resumed turn re-runs the same operation; that must not be a hard failure."""

    harness = make_workspace(tmp_path)
    backend = harness.lease.backend
    try:
        backend.write_spill(_SPILL_OPERATION, b'{"claims":["first"]}')
        path = backend.write_spill(_SPILL_OPERATION, b'{"claims":["second","third"]}')

        assert backend.read_text_sync(path) == '{"claims":["second","third"]}'
        assert len(backend.list_entries_sync("reads")) == 1
    finally:
        harness.close()


def test_a_spill_is_charged_to_the_thread_quota_like_any_other_file(tmp_path: Path) -> None:
    """A spill is not free storage. It spends the same budget the agent's own writes spend."""

    harness = make_workspace(
        tmp_path,
        active_policy=policy(max_total_bytes=64, max_file_bytes=64, max_file_count=5),
    )
    backend = harness.lease.backend
    try:
        backend.write_spill(_SPILL_OPERATION, b"x" * 40)
        assert backend.usage_snapshot().total_bytes == 40
        with pytest.raises(WorkspaceQuotaExceeded):
            backend.write_spill("00000000-0000-0000-0000-0000000006ab", b"y" * 40)
    finally:
        harness.close()


@pytest.mark.parametrize(
    "operation_id",
    ["../escape", "reads/nested", "a/b", ".hidden", "Op-1", "", "x" * 129],
)
def test_a_spill_name_that_is_not_one_safe_segment_is_refused(
    tmp_path: Path,
    operation_id: str,
) -> None:
    """The file name is the only caller-supplied part of a spill path, so it is the whole attack
    surface: no traversal, no nesting, no dotfile, no second extension."""

    harness = make_workspace(tmp_path)
    try:
        with pytest.raises(WorkspaceSecurityError):
            harness.lease.backend.write_spill(operation_id, b"{}")
        assert harness.lease.backend.list_entries_sync("reads") == ()
    finally:
        harness.close()


def test_a_spill_is_refused_where_the_policy_cannot_even_read_it(tmp_path: Path) -> None:
    """A trusted write bypasses the *writable* prefixes and nothing else. Writing a file the
    profile could never open would be storage the model cannot use and quota it still pays."""

    harness = make_workspace(
        tmp_path,
        active_policy=policy(readable=("scratch", "work", "outputs")),
    )
    try:
        with pytest.raises(WorkspaceSecurityError):
            harness.lease.backend.write_spill(_SPILL_OPERATION, b"{}")
    finally:
        harness.close()
