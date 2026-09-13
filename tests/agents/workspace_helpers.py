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


DEFAULT_READABLE_PREFIXES: tuple[str, ...] = (
    ".deepagent",
    "inputs",
    "context",
    "scratch",
    "reads",
    "work",
    "outputs",
)
DEFAULT_WRITABLE_PREFIXES: tuple[str, ...] = ("scratch", "work", "outputs")


def expected_root_id(workspace_id: str, project_id: str, thread_id: str) -> str:
    """The opaque workspace root id the factory derives for one thread."""

    digest = hashlib.sha256(f"{workspace_id}\0{project_id}\0{thread_id}".encode()).hexdigest()
    return f"awr_{digest}"


def policy(
    *,
    max_total_bytes: int = 4096,
    max_file_bytes: int = 2048,
    max_file_count: int = 20,
    readable: tuple[str, ...] | None = None,
    writable: tuple[str, ...] | None = None,
) -> WorkspacePolicy:
    return WorkspacePolicy(
        max_total_bytes=max_total_bytes,
        max_file_bytes=max_file_bytes,
        max_file_count=max_file_count,
        allowed_extensions=(".json", ".md", ".txt", ".yaml"),
        readable_prefixes=DEFAULT_READABLE_PREFIXES if readable is None else readable,
        writable_prefixes=DEFAULT_WRITABLE_PREFIXES if writable is None else writable,
        retention_class="agent-ephemeral-v1",
    )


def make_factory(
    tmp_path: Path,
    *,
    sink: RecordingArtifactSink | None = None,
) -> tuple[Path, AgentWorkspaceFactory, RecordingArtifactSink]:
    """A prepared private root plus its factory, with no lease opened yet."""

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
    factory = AgentWorkspaceFactory(prepared_root=prepared, artifact_sink=recording_sink)
    return root, factory, recording_sink


@dataclass
class WorkspaceHarness:
    root: Path
    factory: AgentWorkspaceFactory
    sink: RecordingArtifactSink
    lease: AgentWorkspaceLease
    thread_path: Path

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
    thread_id: str = "thread-1",
) -> WorkspaceHarness:
    root, factory, recording_sink = make_factory(tmp_path, sink=sink)
    lease = factory.create(
        workspace_id=workspace_id,
        project_id=project_id,
        thread_id=thread_id,
        execution_id=execution_id,
        policy=active_policy or policy(),
    )
    return WorkspaceHarness(
        root=root,
        factory=factory,
        sink=recording_sink,
        lease=lease,
        thread_path=root / workspace_id / "projects" / project_id / "threads" / thread_id,
    )
