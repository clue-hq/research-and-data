"""Body-free durable-turn, model-call, replay and privacy value contracts."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from clue_agents.contracts import (
    AgentResourceRef,
    AgentRole,
    ArtifactRef,
    ContextBundleManifest,
)
from clue_core import ExecutionId

__all__ = [
    "AgentArtifactState",
    "AgentColdReplayReceipt",
    "AgentContextReplayReceipt",
    "AgentModelCallReceipt",
    "AgentModelCallStatus",
    "AgentReplayUnavailable",
    "AgentTurnReceipt",
    "AgentTurnStatus",
    "PrivacyEraseResult",
    "ReplayArtifactRef",
]


class TurnValue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class AgentTurnStatus(StrEnum):
    REQUESTED = "requested"
    CONTEXT_READY = "context_ready"
    RUNNING = "running"
    AWAITING_INPUT = "awaiting_input"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ABANDONED = "abandoned"
    PRIVACY_TOMBSTONED = "privacy_tombstoned"


class AgentModelCallStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentArtifactState(StrEnum):
    LIVE = "live"
    ERASED = "erased"
    PURGED = "purged"
    MISSING = "missing"


class AgentTurnReceipt(TurnValue):
    turn_id: UUID
    execution_id: ExecutionId
    parent_execution_id: ExecutionId | None = None
    workspace_id: str
    project_id: str
    thread_id: str
    actor_id: str
    role: AgentRole
    workspace_root_id: str
    profile_ref: AgentResourceRef
    resource_manifest_ref: ArtifactRef
    resource_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    retention_class: str
    requested_at: AwareDatetime
    current_status: AgentTurnStatus


class AgentModelCallReceipt(TurnValue):
    model_call_id: UUID
    turn_id: UUID
    execution_id: ExecutionId
    workspace_id: str
    sequence: int = Field(ge=1)
    requested_model: str
    answering_model: str | None = None
    status: AgentModelCallStatus
    input_tokens: int = Field(ge=0)
    cache_read_input_tokens: int = Field(default=0, ge=0)
    cache_creation_input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(ge=0)
    cost_millicredits: int = Field(ge=0)
    latency_ms: float = Field(ge=0)
    error_code: str | None = None
    started_at: AwareDatetime
    completed_at: AwareDatetime

    @model_validator(mode="after")
    def status_shape(self) -> AgentModelCallReceipt:
        if self.status is AgentModelCallStatus.COMPLETED:
            if self.answering_model is None or self.error_code is not None:
                raise ValueError("completed model call needs answering model and no error")
        elif self.status is AgentModelCallStatus.FAILED and self.error_code is None:
            raise ValueError("failed model call needs a stable error code")
        return self


class ReplayArtifactRef(TurnValue):
    ref: ArtifactRef
    state: AgentArtifactState
    ref_role: str


class AgentContextReplayReceipt(TurnValue):
    manifest: ContextBundleManifest
    policy_version: str
    token_counter_version: str
    layer_token_budgets: tuple[int, int, int, int, int, int, int]


class AgentColdReplayReceipt(TurnValue):
    """A body-free explanation of the exact frozen inputs needed for replay."""

    turn: AgentTurnReceipt
    context: AgentContextReplayReceipt | None
    artifacts: tuple[ReplayArtifactRef, ...]
    blocker_codes: tuple[str, ...] = ()

    @property
    def replayable(self) -> bool:
        return self.context is not None and not self.blocker_codes


class PrivacyEraseResult(TurnValue):
    workspace_id: str
    subject_entity_id: UUID
    tombstoned_artifact_keys: tuple[str, ...] = ()
    redacted_gate_ids: tuple[UUID, ...] = ()
    affected_turn_ids: tuple[UUID, ...] = ()
    purged_workspace_root_ids: tuple[str, ...] = ()


class AgentReplayUnavailable(RuntimeError):
    def __init__(self, receipt: AgentColdReplayReceipt) -> None:
        self.receipt = receipt
        super().__init__("agent turn cannot be replayed: " + ", ".join(receipt.blocker_codes))
