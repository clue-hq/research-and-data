"""Closed C5 execution vocabularies and compatibility value objects."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clue_core import ExecutionId, ProjectRunId


class RecipeScopeType(StrEnum):
    SYSTEM = "system"
    WORKSPACE = "workspace"


class RecipeRevisionEventType(StrEnum):
    PROPOSED = "proposed"
    PROMOTED = "promoted"
    RETIRED = "retired"
    SUPERSEDED = "superseded"


class ExecutionStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_INPUT = "awaiting_input"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


class ExecutionNodeKind(StrEnum):
    TOOL = "tool"
    GATE = "gate"
    MAP = "map"
    BARRIER = "barrier"
    ACTIVITY = "activity"


class EdgeKind(StrEnum):
    DEPENDENCY = "dependency"
    DATA = "data"
    PARENT = "parent"


class ExecutionEventType(StrEnum):
    EXECUTION_QUEUED = "execution.queued"
    EXECUTION_STARTED = "execution.started"
    EXECUTION_PAUSED = "execution.paused"
    EXECUTION_RESUMED = "execution.resumed"
    EXECUTION_COMPLETED = "execution.completed"
    EXECUTION_FAILED = "execution.failed"
    NODE_SCHEDULED = "node.scheduled"
    NODE_STARTED = "node.started"
    NODE_BLOCKED = "node.blocked"
    NODE_COMPLETED = "node.completed"
    NODE_FAILED = "node.failed"
    NODE_RECOVERED = "node.recovered"
    NODE_ABANDONED = "node.abandoned"
    GATE_OPENED = "gate.opened"
    GATE_DECIDED = "gate.decided"
    STEERING_BEFORE = "steering.before"
    STEERING_AFTER = "steering.after"
    SUPERVISOR_OBSERVED = "supervisor.observed"
    SUPERVISOR_DIAGNOSED = "supervisor.diagnosed"
    SUPERVISOR_ACTIONED = "supervisor.actioned"


class ControlKind(StrEnum):
    ACCOUNT_QUARANTINE = "account_quarantine"
    SOURCE_BREAKER = "source_breaker"
    ENVELOPE = "envelope"
    ESCALATION = "escalation"


class ControlAction(StrEnum):
    APPLY = "apply"
    RELEASE = "release"
    ACKNOWLEDGE = "acknowledge"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class PinRequest(_FrozenModel):
    kind: str = Field(min_length=1)
    key: str = Field(min_length=1)
    version: str | None = Field(default=None, min_length=1)
    digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    required: bool = True

    @model_validator(mode="after")
    def _exact_requirement(self) -> PinRequest:
        if self.version is None and self.digest is None:
            raise ValueError("pin request requires a version or digest")
        return self


class ResolvedPin(_FrozenModel):
    kind: str = Field(min_length=1)
    key: str = Field(min_length=1)
    version: str | None = None
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: str = Field(min_length=1)
    metadata: dict[str, str | int | bool | None] = Field(default_factory=dict)


class Incompatibility(_FrozenModel):
    kind: str = Field(min_length=1)
    key: str = Field(min_length=1)
    requested_version: str | None = None
    requested_digest: str | None = None
    observed_status: str | None = None
    observed_version: str | None = None
    reason: str = Field(min_length=1)


class RunAggregateSnapshot(_FrozenModel):
    execution_id: ExecutionId
    project_run_id: ProjectRunId
    policy_version: str = Field(min_length=1)
    labels: dict[str, str] = Field(default_factory=dict)
    counts: dict[str, int] = Field(default_factory=dict)
    rates: dict[str, float] = Field(default_factory=dict)
    source_counts: dict[str, dict[str, int]] = Field(default_factory=dict)
    source_rates: dict[str, dict[str, float]] = Field(default_factory=dict)
    source_account_refs: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    affected_refs: tuple[str, ...] = ()
    trigger_codes: tuple[str, ...] = ()


class AggregateRequest(_FrozenModel):
    workspace_id: str = Field(min_length=1)
    execution_id: ExecutionId
    project_run_id: ProjectRunId
    policy_version: str = Field(min_length=1)


class RunAggregateReader(Protocol):
    async def snapshot(self, request: AggregateRequest) -> RunAggregateSnapshot: ...


class RunControlReader(Protocol):
    async def account_allowed(self, execution_id: ExecutionId, account_id: str) -> bool: ...

    async def source_allowed(self, execution_id: ExecutionId, source_key: str) -> bool: ...


class ExecutionRunViewReader(Protocol):
    async def read_execution(
        self, *, workspace_id: str, execution_id: ExecutionId
    ) -> object | None: ...


__all__ = [
    "AggregateRequest",
    "ControlAction",
    "ControlKind",
    "EdgeKind",
    "ExecutionEventType",
    "ExecutionNodeKind",
    "ExecutionRunViewReader",
    "ExecutionStatus",
    "Incompatibility",
    "PinRequest",
    "RecipeRevisionEventType",
    "RecipeScopeType",
    "ResolvedPin",
    "RunAggregateSnapshot",
    "RunAggregateReader",
    "RunControlReader",
]
