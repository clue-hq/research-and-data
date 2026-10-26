"""F3 Phase 1, plan Task 9 (spec WS-14; AW-8.2): per-turn registries are bound by the one
workspace hook, never by a caller."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

from clue_agents.workspace import AgentWorkspaceFactory, AgentWorkspaceLease
from clue_agents.workspace_policy import WorkspaceRootPolicy
from clue_core import ExecutionId
from tests.agents.workspace_helpers import RecordingArtifactSink, policy

EXECUTION = ExecutionId(UUID("00000000-0000-0000-0000-000000000b01"))


@dataclass
class RecordingBinding:
    events: list[tuple[str, ExecutionId]] = field(default_factory=list)

    def bind(self, execution_id: ExecutionId, lease: AgentWorkspaceLease) -> None:
        assert lease.identity.execution_id == execution_id
        self.events.append(("bind", execution_id))

    def unbind(self, execution_id: ExecutionId) -> None:
        self.events.append(("unbind", execution_id))


def _factory(tmp_path: Path, binding: RecordingBinding) -> AgentWorkspaceFactory:
    (tmp_path / "source").mkdir(mode=0o700)
    (tmp_path / "home").mkdir(mode=0o700)
    prepared = WorkspaceRootPolicy(
        configured_root=tmp_path / "root",
        source_root=tmp_path / "source",
        home_root=tmp_path / "home",
    ).prepare()
    return AgentWorkspaceFactory(
        prepared_root=prepared,
        artifact_sink=RecordingArtifactSink(),
        turn_bindings=(binding,),
    )


def _acquire(factory: AgentWorkspaceFactory) -> AgentWorkspaceLease:
    return asyncio.run(
        factory.acquire_restored(
            workspace_id="ws-1",
            project_id="project-1",
            thread_id="thread-1",
            execution_id=EXECUTION,
            policy=policy(),
        )
    )


def test_acquire_restored_binds_and_release_saved_unbinds(tmp_path: Path) -> None:
    binding = RecordingBinding()
    factory = _factory(tmp_path, binding)
    try:
        lease = _acquire(factory)
        assert binding.events == [("bind", EXECUTION)]
        asyncio.run(factory.release_saved(lease))
        assert binding.events == [("bind", EXECUTION), ("unbind", EXECUTION)]
    finally:
        factory.close()


def test_a_plain_release_also_unbinds(tmp_path: Path) -> None:
    binding = RecordingBinding()
    factory = _factory(tmp_path, binding)
    try:
        lease = _acquire(factory)
        lease.release()
        assert binding.events[-1] == ("unbind", EXECUTION)
    finally:
        factory.close()


def test_a_plain_acquire_binds_nothing(tmp_path: Path) -> None:
    binding = RecordingBinding()
    factory = _factory(tmp_path, binding)
    try:
        factory.acquire(
            workspace_id="ws-1",
            project_id="project-1",
            thread_id="thread-1",
            execution_id=EXECUTION,
            policy=policy(),
        ).release()
        assert ("bind", EXECUTION) not in binding.events
    finally:
        factory.close()
