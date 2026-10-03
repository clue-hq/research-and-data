from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from typing import Literal
from uuid import UUID

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver

from clue_agents.contracts import (
    AgentConstitution,
    AgentFinalizeEnvelope,
    AgentPlan,
    AgentProfile,
    AgentTurnRequest,
    ArtifactRef,
    DelegationRequest,
    DelegationResult,
    ValidatedPlan,
)
from clue_agents.ports import (
    AgentContextAssembler,
    AgentExecutionAdapter,
    AgentHistoryStore,
    AgentModelProvider,
    AgentWorkspaceBackend,
    AssembledAgentContext,
    ExecutionProgress,
    HistoryMessageRef,
    WorkspaceEntry,
)
from clue_core import ExecutionId


class _ModelPort:
    def build(
        self,
        *,
        model_id: str,
        timeout_s: float,
        max_retries: int,
        max_output_tokens: int,
        temperature: float,
        role: str | None = None,
    ) -> BaseChatModel:
        raise NotImplementedError


class _WorkspacePort:
    workspace_root_id = "opaque-root"
    virtual_mode = True

    async def list_entries(self, prefix: str = "") -> Sequence[WorkspaceEntry]:
        raise NotImplementedError

    async def read_text(self, path: str) -> str:
        raise NotImplementedError

    async def stat_entry(self, path: str) -> WorkspaceEntry:
        raise NotImplementedError

    async def write_text(self, path: str, content: str) -> WorkspaceEntry:
        raise NotImplementedError

    async def edit_text(self, path: str, *, old: str, new: str) -> WorkspaceEntry:
        raise NotImplementedError

    async def snapshot_outputs(self, *, empty_after: bool = False) -> Sequence[ArtifactRef]:
        raise NotImplementedError


class _HistoryPort:
    async def load(self, *, workspace_id: str, thread_id: str) -> Sequence[HistoryMessageRef]:
        raise NotImplementedError

    async def append(
        self,
        *,
        message_id: UUID,
        turn_id: UUID,
        workspace_id: str,
        thread_id: str,
        role: Literal["system", "user", "assistant", "tool"],
        body_ref: ArtifactRef,
    ) -> HistoryMessageRef:
        raise NotImplementedError


class _ContextPort:
    async def assemble(
        self,
        *,
        request: AgentTurnRequest,
        profile: AgentProfile,
        history: Sequence[HistoryMessageRef],
    ) -> AssembledAgentContext:
        raise NotImplementedError


class _ExecutionPort:
    async def validate_plan(
        self,
        *,
        plan: AgentPlan,
        constitution: AgentConstitution,
    ) -> ValidatedPlan:
        raise NotImplementedError

    def execute(self, *, plan: ValidatedPlan) -> AsyncIterator[ExecutionProgress]:
        raise NotImplementedError

    async def delegate(self, *, request: DelegationRequest) -> DelegationResult:
        raise NotImplementedError

    async def check_finalizable(self, *, status: object) -> None:
        del status

    async def finalize(self, *, envelope: AgentFinalizeEnvelope) -> ArtifactRef:
        raise NotImplementedError

    def checkpointer(
        self,
        *,
        execution_id: ExecutionId,
    ) -> AbstractAsyncContextManager[BaseCheckpointSaver[str]]:
        raise NotImplementedError

    async def recover(self, *, execution_id: ExecutionId) -> Mapping[str, object]:
        raise NotImplementedError


def test_frozen_ports_are_structurally_injectable() -> None:
    assert isinstance(_ModelPort(), AgentModelProvider)
    assert isinstance(_WorkspacePort(), AgentWorkspaceBackend)
    assert isinstance(_HistoryPort(), AgentHistoryStore)
    assert isinstance(_ContextPort(), AgentContextAssembler)
    assert isinstance(_ExecutionPort(), AgentExecutionAdapter)


def test_workspace_port_has_no_host_or_execute_surface() -> None:
    names = set(AgentWorkspaceBackend.__dict__)
    assert "host_path" not in names
    assert "root_path" not in names
    assert "execute" not in names
    assert "subprocess" not in names
