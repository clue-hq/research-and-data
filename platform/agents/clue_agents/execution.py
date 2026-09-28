"""Bounded agent-plan policy and body-free execution receipts.

This module deliberately knows nothing about C5, Postgres, or concrete platform tools.  It owns
the policy that is safe to enforce inside the agent package; the API composition root translates
an accepted proposal into the C5 graph language and performs every durable/domain operation.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict, deque
from collections.abc import Mapping
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from clue_agents.contracts import (
    AgentConstitution,
    AgentPlan,
    AgentProfile,
    ArtifactRef,
    DomainObjectRef,
    PlanDelegationStep,
    PlanToolStep,
)
from clue_core import ExecutionId, OperationId, operation_id_from_key

__all__ = [
    "RECEIPT_REFERENCE_VALUES_MAX_BYTES",
    "SPILL_THRESHOLD_BYTES",
    "AgentExecutionStatus",
    "AgentPlanIssue",
    "AgentPlanPolicy",
    "AgentPlanRejected",
    "AgentPlanReview",
    "AgentTurnOutcome",
    "GovernedOperationReceipt",
    "authority_sha256",
    "operation_id_for_plan_node",
    "review_agent_plan",
    "spill_stub",
]

#: The bound on one governed receipt's ``reference_values``, measured as canonical JSON bytes.
#: Substantive output stays behind references, so a tool that would return a lot hands back
#: ``artifact_refs``/``domain_refs`` and the model reads the file or the domain object instead.
RECEIPT_REFERENCE_VALUES_MAX_BYTES = 16_384

#: The point at which a governed result stops travelling inside its receipt and starts travelling
#: as a file.  It sits below the receipt bound on purpose: the bound is a refusal, and a refusal
#: arrives *after* the tool has already run and spent, so nothing may be allowed to reach it.  The
#: same number is the read tools' own page ceiling, so a paged read that fills its page exactly
#: still leaves the receipt's envelope room and a spilled read is the honestly-oversized one.
SPILL_THRESHOLD_BYTES = 12 * 1024

# A trusted composition root may authorize a larger per-run budget than a profile default. The
# operator settings (``CLUE_ARV2_ACCOUNT_MAX_MODEL_ROUNDS``, ``CLUE_HEAD_OF_ABM_MAX_MODEL_ROUNDS``)
# carry the same upper bound, so a value this refuses is refused at start-up instead.
MAX_RUNTIME_MODEL_ROUNDS = 500

#: How much of a spilled result's prose the stub is allowed to keep.  Enough for the model to
#: recognise what it asked for; far too little to be mistaken for the result itself.
_SPILL_SUMMARY_MAX_CHARS = 300


class _Value(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class AgentExecutionStatus(StrEnum):
    COMPLETED = "completed"
    AWAITING_INPUT = "awaiting_input"
    BLOCKED = "blocked"
    FAILED = "failed"


class AgentPlanPolicy(_Value):
    """Hard limits applied before a model proposal obtains execution authority."""

    max_nodes: int = Field(ge=1, le=256)
    max_dependency_depth: int = Field(ge=1, le=64)
    max_fanout: int = Field(ge=1, le=32)
    max_parallelism: int = Field(ge=1, le=32)
    max_rounds: int = Field(ge=1, le=MAX_RUNTIME_MODEL_ROUNDS)
    max_delegations: int = Field(ge=0, le=32)
    max_delegation_depth: int = Field(ge=0, le=4)
    budget_limit_millicents: int = Field(ge=0)
    budget_mode: Literal["enforced", "record_only"] = "enforced"

    @classmethod
    def from_profile(
        cls,
        profile: AgentProfile,
        *,
        budget_limit_millicents: int,
        budget_mode: Literal["enforced", "record_only"] = "enforced",
        max_dependency_depth: int = 16,
        max_fanout: int = 8,
        max_parallelism: int = 8,
        max_rounds: int = 24,
    ) -> AgentPlanPolicy:
        return cls(
            max_nodes=profile.max_plan_nodes,
            max_dependency_depth=max_dependency_depth,
            max_fanout=max_fanout,
            max_parallelism=max_parallelism,
            max_rounds=max_rounds,
            max_delegations=profile.max_delegations,
            max_delegation_depth=profile.max_delegation_depth,
            budget_limit_millicents=budget_limit_millicents,
            budget_mode=budget_mode,
        )


class AgentPlanIssue(_Value):
    code: str
    location: str
    message: str


class AgentPlanReview(_Value):
    proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    issues: tuple[AgentPlanIssue, ...]
    dependency_depth: int = Field(ge=0)
    maximum_fanout: int = Field(ge=0)

    @property
    def valid(self) -> bool:
        return not self.issues


class AgentPlanRejected(ValueError):
    def __init__(self, review: AgentPlanReview) -> None:
        self.review = review
        super().__init__(
            "agent plan rejected: "
            + ", ".join(f"{issue.location}:{issue.code}" for issue in review.issues)
        )


class GovernedOperationReceipt(_Value):
    """Bounded receipt returned to the model; substantive output remains behind references."""

    node_key: str
    operation_id: OperationId
    kind: Literal["tool", "delegation"]
    address: str
    status: AgentExecutionStatus
    replayed: bool = False
    artifact_refs: tuple[ArtifactRef, ...] = ()
    domain_refs: tuple[DomainObjectRef, ...] = ()
    reference_values: dict[str, JsonValue] = Field(default_factory=dict)
    failure_code: str | None = None

    @model_validator(mode="after")
    def status_shape(self) -> GovernedOperationReceipt:
        if self.status is AgentExecutionStatus.FAILED and self.failure_code is None:
            raise ValueError("failed governed operation requires a stable failure code")
        if self.status is not AgentExecutionStatus.FAILED and self.failure_code is not None:
            raise ValueError("only failed governed operations may carry a failure code")
        if (
            self.kind == "delegation"
            and self.status is AgentExecutionStatus.COMPLETED
            and not (self.artifact_refs or self.domain_refs)
        ):
            raise ValueError("completed delegation receipt requires a durable reference")
        encoded = json.dumps(
            self.reference_values,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
        if len(encoded) > RECEIPT_REFERENCE_VALUES_MAX_BYTES:
            raise ValueError("bounded operation receipt exceeds 16 KiB")
        return self


class AgentTurnOutcome(_Value):
    turn_id: UUID
    execution_id: ExecutionId
    status: AgentExecutionStatus
    finalization_ref: ArtifactRef | None = None
    operation_receipts: tuple[GovernedOperationReceipt, ...] = ()
    failure_code: str | None = None

    @model_validator(mode="after")
    def finalization_is_required_for_nonfailure(self) -> AgentTurnOutcome:
        if self.status is AgentExecutionStatus.FAILED:
            if self.failure_code is None:
                raise ValueError("failed turn outcome requires a failure code")
        elif self.finalization_ref is None:
            raise ValueError("a non-failed turn outcome requires a durable finalization")
        return self


def _canonical_bytes(value: object) -> bytes:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", exclude_none=False)
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def spill_stub(
    *,
    address: str,
    path: str,
    references: Mapping[str, JsonValue],
) -> dict[str, JsonValue]:
    """What the receipt says in place of a result that went to a file instead.

    Four things, and no fifth: where the bytes are, how many of the thing there were, a sliver of
    prose so the model can tell at a glance that this is the read it asked for, and which tool
    produced it.  The count is the length of the longest list the result carries — a read's
    payload is its rows, and "48 claims are in this file" is the sentence the model needs to
    decide whether to open it.  The summary prefers the result's own ``summary`` field when it
    wrote one, because a tool describes itself better than a JSON prefix does.

    The stub is deliberately tiny.  It is not a lossy version of the result; it is a pointer, and
    the whole result is one ``read_file`` away.
    """

    counts = [len(value) for value in references.values() if isinstance(value, list)]
    stated = references.get("summary")
    summary = stated if isinstance(stated, str) else _canonical_bytes(dict(references)).decode()
    return {
        "spilled_to": path,
        "count": max(counts) if counts else 1,
        "summary": summary[:_SPILL_SUMMARY_MAX_CHARS],
        "tool": address,
    }


def operation_id_for_plan_node(execution_id: ExecutionId, node_key: str) -> OperationId:
    """Stable logical operation identity: execution plus immutable plan-node position."""

    return operation_id_from_key(str(execution_id), f"agent-plan-node:{node_key}")


def authority_sha256(
    *,
    constitution: AgentConstitution,
    profile: AgentProfile,
    node_key: str,
    address: str,
) -> str:
    """Commit the trusted authority used to admit one operation."""

    return hashlib.sha256(
        _canonical_bytes(
            {
                "workspace_id": constitution.workspace_id,
                "project_id": constitution.project_id,
                "execution_id": str(constitution.execution_id),
                "actor_id": constitution.actor_id,
                "role": constitution.role.value,
                "profile": f"{profile.name}@{profile.version}",
                "profile_sha256": constitution.profile_ref.sha256,
                "resource_manifest_sha256": constitution.resource_manifest_sha256,
                "node_key": node_key,
                "address": address,
            }
        )
    ).hexdigest()


def _graph_metrics(plan: AgentPlan) -> tuple[int, int]:
    outgoing: dict[str, list[str]] = defaultdict(list)
    indegree: dict[str, int] = {}
    depth: dict[str, int] = {}
    for step in plan.steps:
        indegree[step.node_key] = len(step.depends_on)
        for dependency in step.depends_on:
            outgoing[dependency].append(step.node_key)
    ready = deque(sorted(key for key, count in indegree.items() if count == 0))
    maximum_fanout = len(ready)
    while ready:
        key = ready.popleft()
        step = next(item for item in plan.steps if item.node_key == key)
        depth[key] = 1 + max((depth[item] for item in step.depends_on), default=0)
        newly_ready: list[str] = []
        for child in sorted(outgoing[key]):
            indegree[child] -= 1
            if indegree[child] == 0:
                newly_ready.append(child)
        ready.extend(newly_ready)
        maximum_fanout = max(maximum_fanout, len(ready))
    return max(depth.values(), default=0), maximum_fanout


def review_agent_plan(
    *,
    plan: AgentPlan,
    constitution: AgentConstitution,
    profile: AgentProfile,
    policy: AgentPlanPolicy,
) -> AgentPlanReview:
    """Apply the package-local authority/scope/shape checks to the whole proposal."""

    issues: list[AgentPlanIssue] = []
    if plan.execution_id != constitution.execution_id:
        issues.append(
            AgentPlanIssue(
                code="execution_scope",
                location="plan.execution_id",
                message="proposal execution differs from the trusted constitution",
            )
        )
    if plan.role is not constitution.role or profile.role is not constitution.role:
        issues.append(
            AgentPlanIssue(
                code="role_scope",
                location="plan.role",
                message="proposal/profile role differs from the trusted constitution",
            )
        )
    if plan.goal_ref.workspace_id != constitution.workspace_id:
        issues.append(
            AgentPlanIssue(
                code="workspace_scope",
                location="plan.goal_ref",
                message="plan goal belongs to another workspace",
            )
        )
    if len(plan.steps) > policy.max_nodes:
        issues.append(
            AgentPlanIssue(
                code="node_ceiling",
                location="plan.steps",
                message=f"{len(plan.steps)} nodes exceed the ceiling {policy.max_nodes}",
            )
        )

    tool_by_address = {tool.address: tool for tool in profile.tools}
    delegation_count = 0
    for ordinal, step in enumerate(plan.steps):
        location = f"plan.steps[{ordinal}]"
        if isinstance(step, PlanToolStep):
            exact = tool_by_address.get(step.tool.address)
            if exact != step.tool:
                issues.append(
                    AgentPlanIssue(
                        code="tool_not_allowed",
                        location=f"{location}.tool",
                        message=f"{step.tool.address} is absent from exact effective authority",
                    )
                )
        elif isinstance(step, PlanDelegationStep):
            delegation_count += 1
            if step.role not in profile.delegation_roles:
                issues.append(
                    AgentPlanIssue(
                        code="delegation_not_allowed",
                        location=f"{location}.role",
                        message=f"role {step.role.value} is not delegated by this profile",
                    )
                )
            if step.task_artifact_ref.workspace_id != constitution.workspace_id or any(
                ref.workspace_id != constitution.workspace_id for ref in step.domain_refs
            ):
                issues.append(
                    AgentPlanIssue(
                        code="workspace_scope",
                        location=location,
                        message="delegation inputs cross the trusted workspace",
                    )
                )
            for path in step.granted_paths:
                if not any(
                    path == prefix or path.startswith(f"{prefix}/")
                    for prefix in profile.workspace.readable_prefixes
                ):
                    issues.append(
                        AgentPlanIssue(
                            code="path_grant",
                            location=f"{location}.granted_paths",
                            message=f"path {path!r} exceeds parent readable authority",
                        )
                    )

    if delegation_count > min(policy.max_delegations, profile.max_delegations):
        issues.append(
            AgentPlanIssue(
                code="delegation_ceiling",
                location="plan.steps",
                message="delegation count exceeds the effective profile ceiling",
            )
        )
    if delegation_count and (policy.max_delegation_depth < 1 or profile.max_delegation_depth < 1):
        issues.append(
            AgentPlanIssue(
                code="delegation_depth",
                location="plan.steps",
                message="delegation depth is exhausted",
            )
        )

    dependency_depth, maximum_fanout = _graph_metrics(plan)
    if dependency_depth > policy.max_dependency_depth:
        issues.append(
            AgentPlanIssue(
                code="depth_ceiling",
                location="plan.steps",
                message=(
                    f"dependency depth {dependency_depth} exceeds {policy.max_dependency_depth}"
                ),
            )
        )
    if maximum_fanout > policy.max_fanout:
        issues.append(
            AgentPlanIssue(
                code="fanout_ceiling",
                location="plan.steps",
                message=f"ready fanout {maximum_fanout} exceeds {policy.max_fanout}",
            )
        )
    return AgentPlanReview(
        proposal_sha256=hashlib.sha256(_canonical_bytes(plan)).hexdigest(),
        issues=tuple(sorted(issues, key=lambda item: (item.location, item.code, item.message))),
        dependency_depth=dependency_depth,
        maximum_fanout=maximum_fanout,
    )
