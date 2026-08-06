"""M8D R3 contracts for the shared ``langchain.agents.create_agent`` runtime.

The R0 shared-kernel module freezes product authority.  This module adds only runtime-local
construction records: exact resource bodies/pins, the immutable context handed to one entity
mind, bounded facet identity, execution limits, and append-only journal events.  Provider and
claim contracts remain in :mod:`clue_core.entity_research` and are implemented by R4 tools.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal, Self, cast
from uuid import UUID

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from clue_agents.contracts import ModelPolicy
from clue_core.entity_research import (
    EntityAgentToolSurface,
    EntityResearchJobAuthorization,
    FacetDelegationContract,
    ResearchFinalizationProposal,
    ResearchFinalizationReceipt,
    ResearchSubjectType,
)

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
NonEmptyStr = Annotated[str, Field(min_length=1)]


def canonical_sha256(value: object) -> str:
    """Hash one JSON-compatible value with the platform's stable JSON representation."""

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", exclude_none=False)
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()


class FrozenRuntimeModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)


class EntityAgentRole(StrEnum):
    ACCOUNT = "account"
    CONTACT = "contact"
    FACET = "facet"


class EntityAgentJournalEventKind(StrEnum):
    EXECUTION_STARTED = "execution_started"
    MODEL_STARTED = "model_started"
    MODEL_COMPLETED = "model_completed"
    TOOL_STARTED = "tool_started"
    TOOL_COMPLETED = "tool_completed"
    TOOL_FAILED = "tool_failed"
    FINALIZATION_PROPOSED = "finalization_proposed"
    FINALIZATION_ACCEPTED = "finalization_accepted"
    FACET_COMPLETED = "facet_completed"
    EXECUTION_SUSPENDED = "execution_suspended"
    EXECUTION_FAILED = "execution_failed"
    EXECUTION_CANCELLED = "execution_cancelled"


class EntityResearchResource(FrozenRuntimeModel):
    """One exact profile, prompt, or skill body used to construct the mind."""

    kind: Literal["profile", "prompt", "skill"]
    ref: NonEmptyStr
    version: NonEmptyStr
    sha256: Sha256
    body: NonEmptyStr

    @model_validator(mode="after")
    def _body_matches_pin(self) -> Self:
        if hashlib.sha256(self.body.encode()).hexdigest() != self.sha256:
            raise ValueError(f"{self.kind} body differs from its exact digest")
        return self


class EntityResearchResourceBundle(FrozenRuntimeModel):
    profile: EntityResearchResource
    prompt: EntityResearchResource
    skills: tuple[EntityResearchResource, ...] = ()

    @model_validator(mode="after")
    def _resource_shape(self) -> Self:
        if self.profile.kind != "profile" or self.prompt.kind != "prompt":
            raise ValueError("resource bundle requires exact profile and prompt resources")
        if any(skill.kind != "skill" for skill in self.skills):
            raise ValueError("resource bundle skills must have kind=skill")
        identities = [(item.ref, item.version) for item in self.skills]
        if len(identities) != len(set(identities)):
            raise ValueError("entity research skill pins must be unique")
        return self

    def manifest(self) -> dict[str, JsonValue]:
        def ref(resource: EntityResearchResource) -> dict[str, JsonValue]:
            return {
                "kind": resource.kind,
                "ref": resource.ref,
                "version": resource.version,
                "sha256": resource.sha256,
            }

        return {
            "profile": ref(self.profile),
            "prompt": ref(self.prompt),
            "skills": [ref(skill) for skill in self.skills],
        }


class EntityResearchStopPolicy(FrozenRuntimeModel):
    max_model_rounds: int = Field(ge=1, le=64)
    max_tool_calls: int = Field(ge=1, le=256)
    max_runtime_s: float = Field(gt=0, le=1800)
    max_parallel_tools: int = Field(ge=1, le=16)
    max_consecutive_zero_yield: int = Field(ge=1, le=16)


class EntityFacetScope(FrozenRuntimeModel):
    parent_agent_execution_id: UUID
    parent_agent_turn_id: UUID
    facet_key: NonEmptyStr
    depth: Literal[1]
    child_ordinal: int = Field(ge=1, le=2)
    parent_budget_envelope_ref: NonEmptyStr
    children_may_delegate: Literal[False] = False


class EntityResearchRuntimeContext(FrozenRuntimeModel):
    """Exact, immutable authority and input manifest for one constructed agent unit."""

    agent_execution_id: UUID
    agent_turn_id: UUID
    role: EntityAgentRole
    authorization: EntityResearchJobAuthorization
    resources: EntityResearchResourceBundle
    tool_surface: EntityAgentToolSurface
    stop_policy: EntityResearchStopPolicy
    facet_contract: FacetDelegationContract
    current_state_sha256: Sha256
    job_budget_cap_cents: Decimal = Field(ge=0)
    job_spent_cents: Decimal = Field(ge=0)
    run_budget_remaining_cents: Decimal = Field(ge=0)
    facet_scope: EntityFacetScope | None = None

    @model_validator(mode="after")
    def _exact_authority(self) -> Self:
        authorization = self.authorization
        if self.job_spent_cents > self.job_budget_cap_cents:
            raise ValueError("entity agent context spend exceeds the exact job cap")
        if self.agent_execution_id != authorization.attempt_id:
            raise ValueError("entity agent execution must use the authorized attempt id")
        if self.resources.profile.ref != authorization.agent_profile_ref:
            raise ValueError("resolved profile reference differs from job authorization")
        if self.resources.profile.sha256 != authorization.agent_profile_sha256:
            raise ValueError("resolved profile digest differs from job authorization")
        if self.tool_surface.subject_type is not authorization.subject_type:
            raise ValueError("tool surface differs from the authorized subject axis")
        expected_role = (
            EntityAgentRole.ACCOUNT
            if authorization.subject_type is ResearchSubjectType.ACCOUNT
            else EntityAgentRole.CONTACT
        )
        if self.role is EntityAgentRole.FACET:
            scope = self.facet_scope
            if scope is None:
                raise ValueError("facet agent requires exact parent/facet authority")
            if not self.facet_contract.enabled:
                raise ValueError("facet agent cannot be constructed when delegation is disabled")
            if scope.child_ordinal > self.facet_contract.max_children:
                raise ValueError("facet child exceeds the admitted child count")
            if scope.facet_key not in authorization.selection.facet_keys:
                raise ValueError("facet child key is absent from the exact selection")
            if scope.parent_budget_envelope_ref != authorization.selection.budget_envelope_ref:
                raise ValueError("facet child must share the selected parent budget")
        else:
            if self.role is not expected_role:
                raise ValueError("entity agent role differs from the authorized subject axis")
            if self.facet_scope is not None:
                raise ValueError("parent entity agent cannot carry child facet scope")
        return self

    def model_context(self) -> dict[str, JsonValue]:
        """Body-free exact context block embedded into the resolved system prompt."""

        authorization = self.authorization
        selection = authorization.selection
        value: dict[str, Any] = {
            "agent_execution_id": str(self.agent_execution_id),
            "agent_turn_id": str(self.agent_turn_id),
            "role": self.role.value,
            "subject_type": authorization.subject_type.value,
            "subject_entity_id": str(authorization.subject_entity_id),
            "parent_account_id": (
                str(authorization.parent_account_id)
                if authorization.parent_account_id is not None
                else None
            ),
            "workspace_id": str(authorization.workspace_id),
            "project_id": str(authorization.project_id),
            "product_id": str(authorization.product_id),
            "project_run_id": str(authorization.project_run_id),
            "research_run_id": str(authorization.research_run_id),
            "job_id": str(authorization.job_id),
            "directive_ref": selection.directive_ref,
            "directive_sha256": selection.directive_sha256,
            "selection_id": str(selection.selection_id),
            "field_plan_ref": selection.field_plan_ref,
            "source_plan_ref": selection.source_plan_ref,
            "admitted_field_keys": list(selection.admitted_field_keys),
            "admitted_source_keys": list(selection.admitted_source_keys),
            "field_source_authority": [
                item.model_dump(mode="json") for item in selection.field_source_authority
            ],
            "research_questions": list(selection.research_questions),
            "facet_keys": list(selection.facet_keys),
            "channel_permissions": [item.value for item in selection.channel_permissions],
            "policy_refs": list(selection.policy_refs),
            "budget_envelope_ref": selection.budget_envelope_ref,
            "job_budget_cap_cents": str(self.job_budget_cap_cents),
            "job_spent_cents": str(self.job_spent_cents),
            "run_budget_remaining_cents": str(self.run_budget_remaining_cents),
            "approval_refs": list(selection.approval_refs),
            "job_checkpoint_thread_id": authorization.checkpoint_thread_id,
            "checkpoint_thread_id": self.effective_checkpoint_thread_id,
            "current_state_sha256": self.current_state_sha256,
            "resource_manifest": self.resources.manifest(),
            "tool_names": list(self.tool_surface.tool_names),
            "stop_policy": self.stop_policy.model_dump(mode="json"),
            "facet_contract": self.facet_contract.model_dump(mode="json"),
            "facet_scope": (
                self.facet_scope.model_dump(mode="json") if self.facet_scope is not None else None
            ),
        }
        return value

    @property
    def effective_checkpoint_thread_id(self) -> str:
        # LangGraph's Postgres saver keys checkpoints globally by ``thread_id``.  The human-readable
        # authorization value is unique only inside one research run, so it must never be used as
        # the physical key by itself.  Content-address the structured tenant/run/job authority so
        # opaque ids containing delimiters cannot alias another physical saver thread.
        root = "entity-research:" + canonical_sha256(
            {
                "workspace_id": str(self.authorization.workspace_id),
                "research_run_id": str(self.authorization.research_run_id),
                "job_id": str(self.authorization.job_id),
                "authorized_thread_id": self.authorization.checkpoint_thread_id,
            }
        )
        if self.facet_scope is None:
            return root
        return "entity-research-facet:" + canonical_sha256(
            {
                "parent_thread_id": root,
                "facet_key": self.facet_scope.facet_key,
                "child_ordinal": self.facet_scope.child_ordinal,
            }
        )


class EntityResearchToolBinding(FrozenRuntimeModel):
    tool: BaseTool
    version: int = Field(ge=1)

    @property
    def name(self) -> str:
        return self.tool.name

    @property
    def input_schema_sha256(self) -> str:
        return canonical_sha256(self.tool.get_input_jsonschema())


class EntityResearchToolCall(FrozenRuntimeModel):
    tool_call_id: NonEmptyStr
    tool_name: NonEmptyStr
    tool_version: int = Field(ge=1)
    tool_input_sha256: Sha256
    arguments: dict[str, JsonValue]


class EntityResearchJournalEvent(FrozenRuntimeModel):
    event_id: UUID
    agent_execution_id: UUID
    agent_turn_id: UUID
    kind: EntityAgentJournalEventKind
    payload: dict[str, JsonValue]
    tool_call_id: str | None = None
    tool_name: str | None = None
    tool_version: int | None = Field(default=None, ge=1)
    tool_input_sha256: Sha256 | None = None

    @model_validator(mode="after")
    def _tool_event_shape(self) -> Self:
        is_tool = self.kind in {
            EntityAgentJournalEventKind.TOOL_STARTED,
            EntityAgentJournalEventKind.TOOL_COMPLETED,
            EntityAgentJournalEventKind.TOOL_FAILED,
        }
        tool_values = (
            self.tool_call_id,
            self.tool_name,
            self.tool_version,
            self.tool_input_sha256,
        )
        if is_tool != all(value is not None for value in tool_values):
            raise ValueError("tool journal events require exact call identity and input digest")
        if not is_tool and any(value is not None for value in tool_values):
            raise ValueError("non-tool journal event cannot carry tool call identity")
        return self


class EntityResearchAgentResult(FrozenRuntimeModel):
    role: EntityAgentRole
    proposal: ResearchFinalizationProposal
    finalization_receipt: ResearchFinalizationReceipt | None = None

    @model_validator(mode="after")
    def _receipt_authority(self) -> Self:
        if self.role is EntityAgentRole.FACET:
            if self.finalization_receipt is not None:
                raise ValueError("facet child cannot accept terminal job authority")
        elif self.finalization_receipt is None:
            raise ValueError("entity agent success requires an accepted engine receipt")
        elif self.finalization_receipt.proposal != self.proposal:
            raise ValueError("accepted receipt differs from the model's typed proposal")
        return self


class EntityResearchAgentSuspension(FrozenRuntimeModel):
    role: EntityAgentRole
    wait_ref: NonEmptyStr
    checkpoint_ref: NonEmptyStr
    checkpoint_sha256: Sha256
    current_state_sha256: Sha256


class EntityResearchAgentDefinition(FrozenRuntimeModel):
    """Role configuration consumed by the one shared factory."""

    context: EntityResearchRuntimeContext
    model_policy: ModelPolicy
    tools: tuple[EntityResearchToolBinding, ...]
    task_instruction: NonEmptyStr

    @model_validator(mode="after")
    def _tools_match_role(self) -> Self:
        names = tuple(binding.name for binding in self.tools)
        if len(names) != len(set(names)):
            raise ValueError("entity agent tool bindings must be unique")
        surface = self.context.tool_surface
        if self.context.role is not EntityAgentRole.FACET:
            if frozenset(names) != frozenset(surface.tool_names):
                raise ValueError(
                    "entity agent bindings must exactly match its admitted tool surface"
                )
        else:
            if not names:
                raise ValueError("facet agent requires at least one bounded semantic tool")
            forbidden = {
                "delegate_account_facet",
                "delegate_contact_facet",
                "finalize_account_research",
                "finalize_contact_research",
                "reveal_contact_channel",
                "validate_contact_channel",
            }
            if not set(names).issubset(surface.tool_names) or set(names).intersection(forbidden):
                raise ValueError("facet child tools must be a non-recursive subset of the parent")
        return self

    def tool_manifest(self) -> list[dict[str, JsonValue]]:
        return [
            {
                "name": binding.name,
                "version": binding.version,
                "input_schema_sha256": binding.input_schema_sha256,
            }
            for binding in self.tools
        ]

    def exact_model_context(self) -> dict[str, JsonValue]:
        value = self.context.model_context()
        value["tool_names"] = [binding.name for binding in self.tools]
        value["tool_manifest"] = cast(JsonValue, self.tool_manifest())
        value["model_policy"] = cast(
            JsonValue,
            self.model_policy.model_dump(mode="json", exclude_none=False),
        )
        value["task_instruction_sha256"] = canonical_sha256(self.task_instruction)
        return value


__all__ = [
    "EntityAgentJournalEventKind",
    "EntityAgentRole",
    "EntityFacetScope",
    "EntityResearchAgentDefinition",
    "EntityResearchAgentResult",
    "EntityResearchAgentSuspension",
    "EntityResearchJournalEvent",
    "EntityResearchResource",
    "EntityResearchResourceBundle",
    "EntityResearchRuntimeContext",
    "EntityResearchStopPolicy",
    "EntityResearchToolBinding",
    "EntityResearchToolCall",
    "canonical_sha256",
]
