"""Body-free durable-turn, model-call, replay and privacy value contracts."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Literal
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
    "ModelCostSource",
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


#: Which cost authority answered a model call, as the gateway stamped it: ``metered`` (the
#: provider reported the charge), ``estimate`` (our price sheet), ``unpriced`` (no rate — a
#: blank, never a zero). Spelled here rather than imported so this package gains no new edge; the
#: gateway's ``CostSource`` is the same three words.
ModelCostSource = Literal["metered", "estimate", "unpriced"]


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
    # Lane 3 slice 1: the gateway-measured cost of THIS call, in USD, read off the answer's
    # ``clue_cost_cents`` stamp. Beside ``cost_millicredits`` (still 0: the credits milestone's
    # policy), never derived from it. None = unpriced or recorded before the column existed.
    cost_usd: Decimal | None = Field(default=None, ge=0)
    cost_source: ModelCostSource | None = None
    # Lane 3 slice 3: the Langfuse generation this call became (D4) — stamped by the durable
    # recorder from the run registry the LangChain handler fills at model-call start. None when
    # Langfuse is off, and on every receipt replayed from a pre-migration row.
    langfuse_trace_id: str | None = None
    langfuse_observation_id: str | None = None
    latency_ms: float = Field(ge=0)
    error_code: str | None = None
    # P3.2: the agent-role attribution of THIS call — from the governed model's per-call
    # clue_role metadata when the instance is role-labelled (the design trio runs three
    # roles inside one turn), else the turn's constitution role. None only on receipts
    # replayed from pre-attribution rows.
    role: AgentRole | None = None
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
