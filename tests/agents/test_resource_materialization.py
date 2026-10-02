from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path
from uuid import UUID

import pytest

from clue_agents import (
    AgentResourceMaterializer,
    AgentResourceSnapshot,
    AgentRole,
    AgentWorkspaceLease,
    AnchoredAgentWorkspaceBackend,
    ResourceBody,
    ResourceKind,
    WorkspaceConflict,
    WorkspaceQuotaExceeded,
    WorkspaceSecurityError,
    WorkspaceSeedFile,
    build_agent_resource_manifest,
    resource_manifest_sha256,
)
from clue_core import ExecutionId
from tests.agents.workspace_helpers import (
    WorkspaceHarness,
    make_workspace,
    policy,
    resource_ref,
    resource_snapshot,
)

_SECOND_EXECUTION = ExecutionId(UUID("00000000-0000-0000-0000-000000000622"))


def test_exact_resources_and_context_are_copied_frozen_and_manifested_last(
    tmp_path: Path,
) -> None:
    harness = make_workspace(tmp_path)
    snapshot, seeds = resource_snapshot()
    try:
        materializer = AgentResourceMaterializer()
        materializer.materialize(
            lease=harness.lease,
            snapshot=snapshot,
            seed_files=seeds,
        )
        materializer.verify_materialized(
            lease=harness.lease,
            snapshot=snapshot,
            seed_files=seeds,
        )

        assert harness.lease.resources_frozen
        manifest_path = harness.thread_path / ".deepagent/manifest.json"
        materialized = json.loads(manifest_path.read_text())
        assert materialized["aggregate_sha256"] == snapshot.manifest.aggregate_sha256
        assert resource_manifest_sha256(snapshot.manifest) == snapshot.manifest.aggregate_sha256
        expected_paths = {
            ".deepagent/manifest.json",
            ".deepagent/profiles/head-of-abm/1.0.0/profile.yaml",
            ".deepagent/prompts/head-of-abm/1.0.0/SYSTEM.md",
            ".deepagent/skills/project-planning/1.0.0/SKILL.md",
            "context/project.json",
        }
        assert expected_paths <= {entry.path for entry in harness.lease.backend.list_entries_sync()}
        for relative in expected_paths:
            mode = (harness.thread_path / relative).stat().st_mode
            assert stat.S_IMODE(mode) == 0o400
            assert not mode & 0o111
        for directory in (".deepagent", "inputs", "context"):
            assert stat.S_IMODE((harness.thread_path / directory).stat().st_mode) == 0o500

        with pytest.raises(WorkspaceConflict):
            AgentResourceMaterializer().materialize(
                lease=harness.lease,
                snapshot=snapshot,
                seed_files=seeds,
            )
        with pytest.raises(WorkspaceSecurityError):
            harness.lease.backend.edit_text_sync(
                ".deepagent/manifest.json",
                old='"schema_version":"1"',
                new='"schema_version":"2"',
            )

        # A cold process never trusts directory modes alone: every expected byte is re-hashed,
        # and a byte that differs from the pinned snapshot is rewritten from that snapshot.
        context_path = harness.thread_path / "context"
        seed_path = context_path / "project.json"
        context_path.chmod(0o700)
        seed_path.chmod(0o600)
        seed_path.write_text('{"project":"tampered"}')
        seed_path.chmod(0o400)
        context_path.chmod(0o500)
        materializer.verify_materialized(
            lease=harness.lease,
            snapshot=snapshot,
            seed_files=seeds,
        )
        assert seed_path.read_bytes() == seeds[0].content
        assert stat.S_IMODE(context_path.stat().st_mode) == 0o500
        assert stat.S_IMODE(seed_path.stat().st_mode) == 0o400
    finally:
        harness.close()


def test_wrong_hash_and_manifest_body_mismatch_fail_before_materialization() -> None:
    profile = resource_ref(ResourceKind.PROFILE, "head-of-abm", b"expected")
    with pytest.raises(WorkspaceSecurityError):
        ResourceBody(profile, b"different", "application/yaml")

    prompt = resource_ref(ResourceKind.PROMPT, "head-of-abm", b"prompt")
    manifest = build_agent_resource_manifest(
        role=AgentRole.HEAD_OF_ABM,
        profile=profile,
        prompt=prompt,
        skills=(),
        tools=(),
    )
    with pytest.raises(WorkspaceSecurityError):
        AgentResourceSnapshot(
            manifest=manifest,
            bodies=(ResourceBody(profile, b"expected", "application/yaml"),),
        )

    with pytest.raises(WorkspaceSecurityError):
        AgentResourceSnapshot(
            manifest=manifest.model_copy(update={"aggregate_sha256": "0" * 64}),
            bodies=(
                ResourceBody(profile, b"expected", "application/yaml"),
                ResourceBody(prompt, b"prompt", "text/markdown"),
            ),
        )


def test_failed_materialization_never_writes_readiness_manifest_and_is_discardable(
    tmp_path: Path,
) -> None:
    snapshot, seeds = resource_snapshot()
    harness = make_workspace(
        tmp_path,
        active_policy=policy(max_total_bytes=20, max_file_bytes=20, max_file_count=20),
    )
    try:
        with pytest.raises(WorkspaceQuotaExceeded):
            AgentResourceMaterializer().materialize(
                lease=harness.lease,
                snapshot=snapshot,
                seed_files=seeds,
            )
        assert harness.lease.materialization_failed
        assert not harness.lease.resources_frozen
        assert not (harness.thread_path / ".deepagent/manifest.json").exists()

        harness.factory.discard_failed_materialization(harness.lease)
        # The thread workspace persists; only this turn's lease is dropped, and the next
        # turn's materialization resets and rewrites the trusted trees.
        assert harness.thread_path.exists()
        assert not (harness.thread_path / ".deepagent/manifest.json").exists()
    finally:
        harness.factory.close()


def test_seed_paths_are_normalized_scoped_utf8_and_content_addressed() -> None:
    content = b"safe"
    digest = hashlib.sha256(content).hexdigest()
    for path in ("work/file.md", "../context/file.md", "context//file.md"):
        with pytest.raises((ValueError, WorkspaceSecurityError)):
            WorkspaceSeedFile(path, content, digest, "text/markdown")
    with pytest.raises(WorkspaceSecurityError):
        WorkspaceSeedFile("context/file.md", b"\xff", hashlib.sha256(b"\xff").hexdigest(), "text")
    with pytest.raises(WorkspaceSecurityError):
        WorkspaceSeedFile("context/file.md", content, "0" * 64, "text/markdown")


def _seed(path: str, text: str) -> WorkspaceSeedFile:
    content = text.encode("utf-8")
    return WorkspaceSeedFile(
        path=path,
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
        media_type="text/markdown",
    )


def _next_turn(harness: WorkspaceHarness) -> AgentWorkspaceLease:
    """End this turn's hold on the thread and take the next turn's lease over it."""

    harness.lease.release()
    return harness.factory.acquire(
        workspace_id="ws-1",
        project_id="project-1",
        thread_id="thread-1",
        execution_id=_SECOND_EXECUTION,
        policy=policy(),
    )


def test_a_new_turn_rewrites_the_materialized_trees_of_a_persistent_thread(
    tmp_path: Path,
) -> None:
    harness = make_workspace(tmp_path)
    snapshot, _ = resource_snapshot()
    first_seeds = (_seed("inputs/user-message.md", "the first turn's ask"),)
    second_seeds = (_seed("inputs/current-context/summary.md", "the second turn's ask"),)
    materializer = AgentResourceMaterializer()
    second: AgentWorkspaceLease | None = None
    try:
        materializer.materialize(
            lease=harness.lease,
            snapshot=snapshot,
            seed_files=first_seeds,
        )
        harness.lease.backend.write_text_sync("scratch/notes.md", "kept across turns\n")

        second = _next_turn(harness)
        # The finished turn left the trees frozen on disk, and the fresh lease reads that.
        assert second.resources_frozen
        materializer.materialize(
            lease=second,
            snapshot=snapshot,
            seed_files=second_seeds,
        )

        assert not (harness.thread_path / "inputs/user-message.md").exists()
        assert (harness.thread_path / "inputs/current-context/summary.md").read_bytes() == (
            second_seeds[0].content
        )
        assert (harness.thread_path / ".deepagent/manifest.json").exists()
        for directory in (".deepagent", "inputs", "context"):
            assert stat.S_IMODE((harness.thread_path / directory).stat().st_mode) == 0o500
        assert second.backend.materialized_trees_frozen()
        assert second.resources_frozen

        # scratch/ is the agent's own memory across turns: a reset never touches it.
        assert second.backend.read_text_sync("scratch/notes.md") == "kept across turns\n"
    finally:
        if second is not None:
            second.release()
        harness.factory.close()


def test_verify_rebuilds_a_materialized_tree_that_lost_a_file(tmp_path: Path) -> None:
    harness = make_workspace(tmp_path)
    snapshot, seeds = resource_snapshot()
    materializer = AgentResourceMaterializer()
    second: AgentWorkspaceLease | None = None
    try:
        materializer.materialize(lease=harness.lease, snapshot=snapshot, seed_files=seeds)
        harness.lease.backend.write_text_sync("scratch/notes.md", "kept across turns\n")

        # A crash between the resource writes and the manifest: the readiness marker is gone.
        deepagent = harness.thread_path / ".deepagent"
        deepagent.chmod(0o700)
        (deepagent / "manifest.json").unlink()
        deepagent.chmod(0o500)

        second = _next_turn(harness)
        materializer.verify_materialized(lease=second, snapshot=snapshot, seed_files=seeds)

        manifest_path = deepagent / "manifest.json"
        assert manifest_path.exists()
        assert stat.S_IMODE(manifest_path.stat().st_mode) == 0o400
        assert json.loads(manifest_path.read_text())["aggregate_sha256"] == (
            snapshot.manifest.aggregate_sha256
        )
        assert second.backend.materialized_trees_frozen()
        assert second.resources_frozen
        assert second.backend.read_text_sync("scratch/notes.md") == "kept across turns\n"
    finally:
        if second is not None:
            second.release()
        harness.factory.close()


def test_verify_still_fails_loudly_when_the_rebuilt_bytes_are_wrong(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = make_workspace(tmp_path)
    snapshot, seeds = resource_snapshot()
    materializer = AgentResourceMaterializer()
    try:
        materializer.materialize(lease=harness.lease, snapshot=snapshot, seed_files=seeds)
        context_path = harness.thread_path / "context"
        seed_path = context_path / "project.json"
        context_path.chmod(0o700)
        seed_path.chmod(0o600)
        seed_path.write_text('{"project":"tampered"}')
        seed_path.chmod(0o400)
        context_path.chmod(0o500)

        original = AnchoredAgentWorkspaceBackend.materialize_bytes

        def corrupt(self: AnchoredAgentWorkspaceBackend, path: str, data: bytes) -> object:
            payload = b'{"project":"still-wrong"}' if path == seeds[0].path else data
            return original(self, path, payload)

        monkeypatch.setattr(AnchoredAgentWorkspaceBackend, "materialize_bytes", corrupt)
        with pytest.raises(WorkspaceSecurityError, match="verification failed"):
            materializer.verify_materialized(
                lease=harness.lease,
                snapshot=snapshot,
                seed_files=seeds,
            )
    finally:
        harness.close()
