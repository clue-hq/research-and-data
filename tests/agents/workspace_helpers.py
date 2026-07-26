from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from clue_agents import (
    AgentWorkspaceFactory,
    AgentWorkspaceLease,
    ArtifactRef,
    WorkspacePolicy,
    WorkspaceRootPolicy,
)
from clue_core import ExecutionId

EXECUTION_ID = ExecutionId(UUID("00000000-0000-0000-0000-000000000611"))


@dataclass
class RecordingArtifactSink:
    records: list[tuple[str, str, bytes, str]] = field(default_factory=list)
    workspace_override: str | None = None
    digest_override: str | None = None

    async def persist(
        self,
        *,
        workspace_id: str,
        logical_path: str,
        data: bytes,
        media_type: str,
    ) -> ArtifactRef:
        self.records.append((workspace_id, logical_path, data, media_type))
        digest = self.digest_override or hashlib.sha256(data).hexdigest()
        scope = self.workspace_override or workspace_id
        return ArtifactRef(
            workspace_id=scope,
            artifact_key=f"{scope}/{digest}",
            sha256=digest,
            media_type=media_type,
            byte_count=len(data),
        )


def policy(
    *,
    max_total_bytes: int = 4096,
    max_file_bytes: int = 2048,
    max_file_count: int = 20,
) -> WorkspacePolicy:
    return WorkspacePolicy(
        max_total_bytes=max_total_bytes,
        max_file_bytes=max_file_bytes,
        max_file_count=max_file_count,
        allowed_extensions=(".json", ".md", ".txt", ".yaml"),
        readable_prefixes=(
            ".deepagent",
            "inputs",
            "context",
            "work",
            "delegations",
            "outputs",
        ),
        writable_prefixes=("work", "delegations", "outputs"),
        retention_class="agent-ephemeral-v1",
    )


@dataclass
class WorkspaceHarness:
    root: Path
    factory: AgentWorkspaceFactory
    sink: RecordingArtifactSink
    lease: AgentWorkspaceLease
    execution_path: Path

    def close(self) -> None:
        self.lease.backend.close()
        self.factory.close()


def make_workspace(
    tmp_path: Path,
    *,
    active_policy: WorkspacePolicy | None = None,
    sink: RecordingArtifactSink | None = None,
    execution_id: ExecutionId = EXECUTION_ID,
    workspace_id: str = "ws-1",
    project_id: str = "project-1",
) -> WorkspaceHarness:
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = tmp_path / "source"
    home = tmp_path / "home"
    source.mkdir(mode=0o700)
    home.mkdir(mode=0o700)
    root = tmp_path / "agent-runtime"
    prepared = WorkspaceRootPolicy(
        configured_root=root,
        source_root=source,
        home_root=home,
    ).prepare()
    recording_sink = sink or RecordingArtifactSink()
    factory = AgentWorkspaceFactory(
        prepared_root=prepared,
        artifact_sink=recording_sink,
    )
    lease = factory.create(
        workspace_id=workspace_id,
        project_id=project_id,
        execution_id=execution_id,
        policy=active_policy or policy(),
    )
    return WorkspaceHarness(
        root=root,
        factory=factory,
        sink=recording_sink,
        lease=lease,
        execution_path=root / workspace_id / project_id / str(execution_id),
    )
