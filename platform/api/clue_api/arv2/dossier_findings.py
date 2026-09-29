"""Shared finding contract for agent-authored dossiers and deterministic storage.

These checks concern transport shape and references, never research quality.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from clue_api.arv2.quality_claims import SemanticAssessment


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal[
        "supported", "duplicate", "wrong_entity", "insufficient_context", "potential_conflict"
    ]
    reason: str = Field(min_length=1)
    duplicate_of: UUID | None = None
    conflicts_with: list[UUID] = Field(default_factory=list)
    expected_entity: dict[str, JsonValue] | None = None

    @model_validator(mode="after")
    def linked(self) -> Review:
        if (self.status == "duplicate") != (self.duplicate_of is not None):
            raise ValueError(
                "Only duplicate status requires duplicate_of, using a returned claim ID."
            )
        if self.status == "potential_conflict" and not self.conflicts_with:
            raise ValueError("potential_conflict requires conflicts_with returned claim IDs.")
        self.conflicts_with = sorted(set(self.conflicts_with))
        return self


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: str = Field(min_length=1)
    claim_type: Literal["observation", "reported_statement"]
    finding: JsonValue
    source_paths: list[str] = Field(default_factory=list)
    attribution: str | None = None
    time_context: str | None = None
    qualifications: list[str] = Field(default_factory=list)
    review: Review
    agent_interpretation: str | None = None


def assessment_for(args: Finding) -> SemanticAssessment:
    status = args.review.status
    notes = list(args.qualifications)
    if status == "duplicate":
        notes.append(f"Duplicate of {args.review.duplicate_of}")
    if args.review.conflicts_with:
        notes.append(
            "Potential conflict with claims: "
            + ", ".join(str(claim_id) for claim_id in args.review.conflicts_with)
            + "; both records remain retained. "
            + args.review.reason
        )
    if not args.source_paths:
        notes.append("No original source reference attached.")
    return SemanticAssessment(
        entity="contradicted" if status == "wrong_entity" else "supported",
        field_meaning="supported",
        entailment="uncertain" if status == "insufficient_context" else "supported",
        relationship_direction="not_applicable",
        temporal_scope="supported",
        explanation=args.review.reason,
        qualifications=tuple(notes),
    )
