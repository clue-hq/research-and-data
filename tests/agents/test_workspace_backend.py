from __future__ import annotations

import asyncio
import os
import stat
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import UUID

import pytest

from clue_agents import (
    AgentWorkspaceBackend,
    AnchoredAgentWorkspaceBackend,
    ArtifactRef,
    WorkspaceConflict,
    WorkspaceQuotaExceeded,
    WorkspaceSecurityError,
)
from clue_core import ExecutionId
from tests.agents.workspace_helpers import (
    RecordingArtifactSink,
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

        host_file = harness.execution_path / entry.path
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
        execution_id=second_id,
        policy=policy(),
    )
    try:
        second.backend.write_text_sync("work/private.md", "other")
        for target in (
            str(harness.root / "ws-1" / "project-1" / str(second_id) / "work/private.md"),
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
        injected = harness.execution_path / "work/injected.md"
        injected.write_text("executable")
        os.chmod(injected, 0o700)
        with pytest.raises(WorkspaceSecurityError):
            backend.read_text_sync("work/injected.md")
        assert stat.S_IMODE((harness.execution_path / "context/card.json").stat().st_mode) == 0o400
        assert stat.S_IMODE((harness.execution_path / "context").stat().st_mode) == 0o500
    finally:
        harness.close()


def test_symlinks_hardlinks_and_special_entries_fail_closed(tmp_path: Path) -> None:
    harness = make_workspace(tmp_path)
    backend = harness.lease.backend
    outside = tmp_path / "outside.md"
    outside.write_text("host secret")
    try:
        (harness.execution_path / "work/link.md").symlink_to(outside)
        with pytest.raises(WorkspaceSecurityError):
            backend.read_text_sync("work/link.md")
        with pytest.raises((WorkspaceConflict, WorkspaceSecurityError)):
            backend.write_text_sync("work/link.md", "replace")

        real = harness.execution_path / "work/real.md"
        real.write_text("same")
        os.chmod(real, 0o600)
        os.link(real, harness.execution_path / "work/hard.md")
        with pytest.raises(WorkspaceSecurityError):
            backend.read_text_sync("work/real.md")
        with pytest.raises(WorkspaceSecurityError):
            backend.list_entries_sync("work")

        fifo = harness.execution_path / "outputs/pipe.txt"
        os.mkfifo(fifo, 0o600)
        with pytest.raises(WorkspaceSecurityError):
            backend.list_entries_sync("outputs")
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
            for path in (harness.execution_path / "outputs").iterdir()
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
        assert not (harness.execution_path / "work/plan.md").is_symlink()
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
        assert not (harness.execution_path / "outputs/result.md").exists()
        assert not tuple((harness.execution_path / "outputs").iterdir())
    finally:
        harness.close()


def test_output_snapshot_is_single_flight_durable_and_cleanup_gated(tmp_path: Path) -> None:
    sink = RecordingArtifactSink()
    harness = make_workspace(tmp_path, sink=sink)
    backend = harness.lease.backend
    backend.write_text_sync("outputs/report.md", "final")
    try:
        with pytest.raises(WorkspaceSecurityError):
            harness.factory.cleanup(harness.lease)

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
        harness.factory.cleanup(harness.lease)
        assert not harness.execution_path.exists()
    finally:
        harness.factory.close()


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
            harness.factory.cleanup(harness.lease)
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
