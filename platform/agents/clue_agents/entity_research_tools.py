"""Model-facing schemas for M8D R4 semantic research tools.

These inputs contain research intent only.  Tenant, project, run, job, target, budget, policy,
agent-turn, and provider-operation authority is injected from the governed R3 runtime and is never
accepted from model-authored arguments.
"""

from __future__ import annotations

from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clue_core.entity_research import ResearchFollowUpReason

NonEmptyStr = Annotated[str, Field(min_length=1)]


class EntityResearchSemanticToolInput(BaseModel):
    """A bounded field/source/question choice within the immutable job selection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field_keys: tuple[NonEmptyStr, ...] = ()
    source_keys: tuple[NonEmptyStr, ...] = Field(min_length=1)
    questions: tuple[NonEmptyStr, ...] = ()
    parent_operation_ref: NonEmptyStr | None = None
    parent_observation_ref: NonEmptyStr | None = None
    follow_up_reason: ResearchFollowUpReason | None = None

    @model_validator(mode="after")
    def _bounded_choice(self) -> Self:
        for values, message in (
            (self.field_keys, "semantic research fields must be unique"),
            (self.source_keys, "semantic research sources must be unique"),
            (self.questions, "semantic research questions must be unique"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(message)
        lineage = (self.parent_operation_ref, self.parent_observation_ref, self.follow_up_reason)
        if any(value is not None for value in lineage) and not all(
            value is not None for value in lineage
        ):
            raise ValueError("additive follow-up requires complete parent observation lineage")
        return self


class ReadResearchResultInput(BaseModel):
    """Losslessly retrieve one persisted result visible to the current exact job."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    result_ref: NonEmptyStr


class ReadResearchEvidenceInput(BaseModel):
    """Read a bounded UTF-8 section of one retained evidence artifact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_ref: NonEmptyStr
    offset: int = Field(default=0, ge=0)
    max_bytes: int = Field(default=16_384, ge=1, le=65_536)


__all__ = [
    "EntityResearchSemanticToolInput",
    "ReadResearchEvidenceInput",
    "ReadResearchResultInput",
]
