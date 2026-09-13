from __future__ import annotations

import asyncio
import os
import stat
from collections.abc import Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

import pytest

from clue_agents import (
    AgentWorkspaceBackend,
    AgentWorkspaceFactory,
    AnchoredAgentWorkspaceBackend,
    ArtifactRef,
    MountMode,
    MountRequest,
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
