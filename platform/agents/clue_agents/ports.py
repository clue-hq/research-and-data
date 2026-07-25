"""Frozen C6 dependency-inverted ports.

The agent package owns orchestration policy, not providers or durable implementations.  These
protocols keep model egress, workspace bytes, history, context assembly, and C5 execution behind
injected seams.  In particular, ``AgentWorkspaceBackend`` has no host-path or command-execution
surface.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from typing import Literal, Protocol, runtime_checkable

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from pydantic import BaseModel, ConfigDict, Field

from clue_agents.contracts import (
    AgentConstitution,
    AgentFinalizeEnvelope,
    AgentPlan,
    AgentProfile,
    AgentTurnRequest,
    ArtifactRef,
    ContextBundleManifest,
    DelegationRequest,
    DelegationResult,
    ValidatedPlan,
)
from clue_core import ExecutionId

__all__ = [
    "AgentContextAssembler",
    "AgentExecutionAdapter",
    "AgentHistoryStore",
    "AgentModelProvider",
    "AgentWorkspaceBackend",
    "AssembledAgentContext",
    "ExecutionProgress",
    "HistoryMessageRef",
    "WorkspaceEntry",
]


class PortValue(BaseModel):
    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        strict=True,
        arbitrary_types_allowed=True,
    )


class WorkspaceEntry(PortValue):
    path: str
    kind: str
    byte_count: int = Field(ge=0)
    sha256: str | None = None
    read_only: bool


class HistoryMessageRef(PortValue):
    sequence: int = Field(ge=1)
    role: str
    body_ref: ArtifactRef


class AssembledAgentContext(PortValue):
    """Ephemeral model input paired with the body-free durable manifest."""

    manifest: ContextBundleManifest
    messages: tuple[BaseMessage, ...]


class ExecutionProgress(PortValue):
    execution_id: ExecutionId
    status: str
    completed_node_keys: tuple[str, ...] = ()
    failed_node_keys: tuple[str, ...] = ()


@runtime_checkable
class AgentModelProvider(Protocol):
    """Build a provider-neutral LangChain tool-calling model behind the gateway boundary."""

    def build(
        self,
        *,
        model_id: str,
        timeout_s: float,
        max_retries: int,
        max_output_tokens: int,
        temperature: float,
    ) -> BaseChatModel: ...


@runtime_checkable
class AgentWorkspaceBackend(Protocol):
    """Relative-path, artifact-backed workspace surface.

    The required ``virtual_mode`` value is part of the runtime contract.  Deliberately absent:
    host path resolution, shell/process execution, environment access, links, or arbitrary bytes
    outside the policy-controlled file types.
    """

    @property
    def workspace_root_id(self) -> str: ...

    @property
    def virtual_mode(self) -> Literal[True]: ...

    async def list_entries(self, prefix: str = "") -> Sequence[WorkspaceEntry]: ...

    async def read_text(self, path: str) -> str: ...

    async def write_text(self, path: str, content: str) -> WorkspaceEntry: ...

    async def edit_text(self, path: str, *, old: str, new: str) -> WorkspaceEntry: ...

    async def snapshot_outputs(self) -> Sequence[ArtifactRef]: ...


@runtime_checkable
class AgentHistoryStore(Protocol):
    async def load(self, *, workspace_id: str, thread_id: str) -> Sequence[HistoryMessageRef]: ...

    async def append(
        self,
        *,
        workspace_id: str,
        thread_id: str,
        role: str,
        body_ref: ArtifactRef,
    ) -> HistoryMessageRef: ...


@runtime_checkable
class AgentContextAssembler(Protocol):
    async def assemble(
        self,
        *,
        request: AgentTurnRequest,
        profile: AgentProfile,
        history: Sequence[HistoryMessageRef],
    ) -> AssembledAgentContext: ...


@runtime_checkable
class AgentExecutionAdapter(Protocol):
    """The only route from model proposals to the durable C5 execution spine."""

    async def validate_plan(
        self,
        *,
        plan: AgentPlan,
        constitution: AgentConstitution,
    ) -> ValidatedPlan: ...

    def execute(self, *, plan: ValidatedPlan) -> AsyncIterator[ExecutionProgress]: ...

    async def delegate(self, *, request: DelegationRequest) -> DelegationResult: ...

    async def finalize(self, *, envelope: AgentFinalizeEnvelope) -> ArtifactRef: ...

    def checkpointer(
        self,
        *,
        execution_id: ExecutionId,
    ) -> AbstractAsyncContextManager[BaseCheckpointSaver[str]]: ...

    async def recover(self, *, execution_id: ExecutionId) -> Mapping[str, object]: ...
