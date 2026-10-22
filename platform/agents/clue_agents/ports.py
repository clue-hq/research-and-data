"""Frozen C6 dependency-inverted ports.

The agent package owns orchestration policy, not providers or durable implementations.  These
protocols keep model egress, workspace bytes, history, context assembly, and C5 execution behind
injected seams.  In particular, ``AgentWorkspaceBackend`` has no host-path or command-execution
surface.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from typing import Any, Literal, Protocol, runtime_checkable
from uuid import UUID

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from clue_agents.contracts import (
    AgentConstitution,
    AgentFinalizeEnvelope,
    AgentPlan,
    AgentProfile,
    AgentTurnRequest,
    ArtifactRef,
    ContextBundleManifest,
    ContinuationRef,
    DelegationRequest,
    DelegationResult,
    DomainObjectRef,
    FinalizeStatus,
    ValidatedPlan,
    normalize_virtual_path,
)
from clue_agents.workspace_snapshot import (
    LeaseFence,
    SaveStatus,
    SnapshotEntry,
    SnapshotManifest,
    SnapshotPointer,
)
from clue_core import ExecutionId

INTERRUPTED_ASSISTANT_NOTICE = (
    "The following assistant message was interrupted by the user. "
    "It is an incomplete response, not a completed action or final answer."
)

__all__ = [
    "AgentArtifactSink",
    "AgentArtifactReader",
    "AgentContextAssembler",
    "AgentExecutionAdapter",
    "AgentHistoryStore",
    "AgentModelProvider",
    "AgentWorkspaceBackend",
    "AssembledAgentContext",
    "ContextMaterialization",
    "ExecutionProgress",
    "HistoryMessageRef",
    "OperationFailure",
    "SpillSink",
    "TurnBinding",
    "WorkspaceSnapshotStore",
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
    message_id: UUID
    turn_id: UUID
    sequence: int = Field(ge=1)
    role: Literal["system", "user", "assistant", "tool"]
    body_ref: ArtifactRef
    #: The attachments this message was sent with (spec 2026-09-18, ruling 2). History loaders
    #: that can read them fill this; the ones that cannot leave it empty, and the conversation
    #: layer then carries no images for that message rather than guessing.
    attachment_refs: tuple[ArtifactRef, ...] = ()
    interrupted: bool = False


class ContextMaterialization(PortValue):
    """Ephemeral bytes to freeze into the isolated read-only workspace."""

    path: str
    data: bytes
    sha256: str
    media_type: str

    @field_validator("path")
    @classmethod
    def path_is_read_only_and_relative(cls, value: str) -> str:
        normalized = normalize_virtual_path(value)
        if not normalized.startswith(("context/", "inputs/")):
            raise ValueError("context materialization must stay under context/ or inputs/")
        return normalized

    @field_validator("sha256")
    @classmethod
    def sha_is_well_formed(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("context materialization sha256 is malformed")
        return value

    @model_validator(mode="after")
    def bytes_match_digest(self) -> ContextMaterialization:
        if hashlib.sha256(self.data).hexdigest() != self.sha256:
            raise ValueError("context materialization bytes differ from its digest")
        return self


class AssembledAgentContext(PortValue):
    """Ephemeral model input paired with the body-free durable manifest."""

    manifest: ContextBundleManifest
    messages: tuple[BaseMessage, ...]
    materializations: tuple[ContextMaterialization, ...] = ()
    #: Set when the turn continues a saved conversation instead of opening a fresh one.
    continuation: ContinuationRef | None = None


class OperationFailure(PortValue):
    """Why exactly one governed operation did not complete.

    The durable record of a failed operation is a *code* (the toolbelt journal stamps the exception
    class; the plan journal stamps ``operation_failed``), which is enough to audit a run and not
    enough to repair one: the sentence a tool refuses with ("claim value is not textually entailed
    by the exact interview quote") exists only as the raised exception. Carrying it on the progress
    stream — the channel that already reports *which* node failed — lets the caller hand the model
    back the reason it can act on, without a side channel and without loosening any durable record.
    """

    node_key: str
    address: str
    error_type: str
    message: str


class ExecutionProgress(PortValue):
    execution_id: ExecutionId
    status: str
    completed_node_keys: tuple[str, ...] = ()
    failed_node_keys: tuple[str, ...] = ()
    failures: tuple[OperationFailure, ...] = ()


@runtime_checkable
class AgentArtifactSink(Protocol):
    """Persist one finalized workspace file without exposing a storage implementation."""

    async def persist(
        self,
        *,
        workspace_id: str,
        logical_path: str,
        data: bytes,
        media_type: str,
    ) -> ArtifactRef: ...


@runtime_checkable
class AgentArtifactReader(Protocol):
    """Read an exact live workspace artifact or fail closed if it is missing/erased."""

    async def read(self, ref: ArtifactRef) -> bytes: ...


@runtime_checkable
class SpillSink(Protocol):
    """Somewhere for a governed result that will not fit inside its own receipt to land.

    A receipt is bounded on purpose, and a read whose references overflow that bound used to be
    discarded *after* the read had already run — the model asked for an account and was told the
    platform could not show it one.  A sink turns that into a file: the runtime hands over the
    result's canonical bytes, the sink stores them somewhere the model is allowed to read, and
    the receipt carries the returned path instead of the payload.

    The thread's own workspace is the implementation (``reads/<operation_id>.json``); the write
    is the runtime's, never the model's, so the sink is deliberately *not* part of
    :class:`AgentWorkspaceBackend`'s model-visible surface.
    """

    def write_spill(self, operation_id: str, data: bytes) -> str: ...


@runtime_checkable
class TurnBinding(Protocol):
    """A per-turn, in-process registry told which workspace a running execution holds (WS-14).

    The workspace factory binds every lease it hands out through ``acquire_restored`` and unbinds
    it on release, so no caller binds a folder on its own (AW-8.2). The CRM read sinks and the
    code sandbox's mount registry are the two today.
    """

    def bind(self, execution_id: ExecutionId, lease: Any) -> None: ...

    def unbind(self, execution_id: ExecutionId) -> None: ...


@runtime_checkable
class WorkspaceSnapshotStore(Protocol):
    """Where a chat's agent-folder snapshots live: a version record plus content-addressed files.

    F3 (spec WS-1–WS-3, WS-8): ``save`` moves the record with a compare-and-set on the version the
    turn restored, and only while the fence still holds the chat's fleet lease. Implemented over
    Postgres and the artifact store in ``clue_api.agent_workspace_snapshots``.

    The files live in the chat's own storage area (WS-30), so ``save`` and ``forget`` also erase
    the ones they released that no other snapshot still holds. Nothing outside that area is ever
    erased — bytes a person can see (uploads, Gallery artifacts, evidence snapshots) are some
    other owner's, however exactly they match a chat's file (ruling AW-26).
    """

    async def current(self, *, workspace_id: str, thread_id: str) -> SnapshotPointer | None: ...

    async def read_manifest(
        self, *, workspace_id: str, pointer: SnapshotPointer
    ) -> SnapshotManifest: ...

    async def read_file(self, *, workspace_id: str, entry: SnapshotEntry) -> bytes: ...

    async def store_files(
        self, *, workspace_id: str, files: Sequence[tuple[SnapshotEntry, bytes]]
    ) -> int: ...

    async def save(
        self,
        *,
        workspace_id: str,
        project_id: str,
        thread_id: str,
        expected_version: int | None,
        manifest: SnapshotManifest,
        fence: LeaseFence | None,
    ) -> tuple[SaveStatus, SnapshotPointer | None]: ...

    async def touch(self, *, workspace_id: str, thread_id: str) -> None: ...

    async def forget(self, *, workspace_id: str, thread_id: str) -> None: ...


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
        role: str | None = None,
        call_deadline_s: float | None = None,
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

    async def stat_entry(self, path: str) -> WorkspaceEntry: ...

    async def write_text(self, path: str, content: str) -> WorkspaceEntry: ...

    async def edit_text(self, path: str, *, old: str, new: str) -> WorkspaceEntry: ...

    async def snapshot_outputs(self, *, reopen_after: bool = False) -> Sequence[ArtifactRef]: ...


@runtime_checkable
class AgentHistoryStore(Protocol):
    async def load(self, *, workspace_id: str, thread_id: str) -> Sequence[HistoryMessageRef]: ...

    async def append(
        self,
        *,
        message_id: UUID,
        turn_id: UUID,
        workspace_id: str,
        thread_id: str,
        role: Literal["system", "user", "assistant", "tool"],
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

    async def check_finalizable(
        self,
        *,
        status: FinalizeStatus,
        open_gate_refs: Sequence[DomainObjectRef] = (),
    ) -> None:
        """Refuse a finalization this execution cannot accept yet — before anything is frozen.

        Raises ``ValueError`` (a refusal the model can repair, e.g. unresolved failed tool
        attempts for ``completed``, or an ``open_gate_refs`` entry that names a gate under any
        object type but ``agent_gate``); never changes state. ``finalize_turn`` calls it first,
        because once ``outputs/`` is snapshotted the repair the refusal asks for is impossible
        (production 2026-10-03, McKee).
        """
        ...

    async def finalize(self, *, envelope: AgentFinalizeEnvelope) -> ArtifactRef: ...

    def checkpointer(
        self,
        *,
        execution_id: ExecutionId,
    ) -> AbstractAsyncContextManager[BaseCheckpointSaver[str]]: ...

    async def recover(self, *, execution_id: ExecutionId) -> Mapping[str, object]: ...
