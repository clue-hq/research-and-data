from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path

import pytest

from clue_agents import (
    AgentResourceMaterializer,
    AgentResourceSnapshot,
    AgentRole,
    ResourceBody,
    ResourceKind,
    WorkspaceConflict,
    WorkspaceQuotaExceeded,
    WorkspaceSecurityError,
    WorkspaceSeedFile,
    build_agent_resource_manifest,
    resource_manifest_sha256,
)
from clue_agents.contracts import AgentResourceRef
from tests.agents.workspace_helpers import make_workspace, policy


def _ref(kind: ResourceKind, name: str, content: bytes) -> AgentResourceRef:
    return AgentResourceRef(
        kind=kind,
        name=name,
        version="1.0.0",
        sha256=hashlib.sha256(content).hexdigest(),
    )


def _snapshot() -> tuple[AgentResourceSnapshot, tuple[WorkspaceSeedFile, ...]]:
    profile_bytes = b"role: head_of_abm\n"
    prompt_bytes = b"You are the governed Head of ABM.\n"
    skill_bytes = b"# Project planning\nUse evidence.\n"
    profile = _ref(ResourceKind.PROFILE, "head-of-abm", profile_bytes)
    prompt = _ref(ResourceKind.PROMPT, "head-of-abm", prompt_bytes)
    skill = _ref(ResourceKind.SKILL, "project-planning", skill_bytes)
    manifest = build_agent_resource_manifest(
        role=AgentRole.HEAD_OF_ABM,
        profile=profile,
        prompt=prompt,
        skills=(skill,),
        tools=(),
    )
    snapshot = AgentResourceSnapshot(
        manifest=manifest,
        bodies=(
            ResourceBody(profile, profile_bytes, "application/yaml"),
            ResourceBody(prompt, prompt_bytes, "text/markdown"),
            ResourceBody(skill, skill_bytes, "text/markdown"),
        ),
    )
    context = b'{"project":"project-1"}'
    seeds = (
        WorkspaceSeedFile(
            path="context/project.json",
            content=context,
            sha256=hashlib.sha256(context).hexdigest(),
            media_type="application/json",
        ),
    )
    return snapshot, seeds


def test_exact_resources_and_context_are_copied_frozen_and_manifested_last(
    tmp_path: Path,
) -> None:
    harness = make_workspace(tmp_path)
    snapshot, seeds = _snapshot()
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

        # A cold process never trusts directory modes alone: every expected byte is re-hashed.
        context_path = harness.thread_path / "context"
        seed_path = context_path / "project.json"
        context_path.chmod(0o700)
        seed_path.chmod(0o600)
        seed_path.write_text('{"project":"tampered"}')
        seed_path.chmod(0o400)
        context_path.chmod(0o500)
        with pytest.raises(WorkspaceSecurityError, match="immutable snapshot"):
            materializer.verify_materialized(
                lease=harness.lease,
                snapshot=snapshot,
                seed_files=seeds,
            )
    finally:
        harness.close()


def test_wrong_hash_and_manifest_body_mismatch_fail_before_materialization() -> None:
    profile = _ref(ResourceKind.PROFILE, "head-of-abm", b"expected")
    with pytest.raises(WorkspaceSecurityError):
        ResourceBody(profile, b"different", "application/yaml")

    prompt = _ref(ResourceKind.PROMPT, "head-of-abm", b"prompt")
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
    snapshot, seeds = _snapshot()
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
