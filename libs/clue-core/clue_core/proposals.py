"""Phase-C proposal references and governance vocabulary.

These types cross the research, toolbelt, and projection lanes, so they live in the shared kernel.
Proposal row models and mutation logic remain in ``clue_research.proposals``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import NewType
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict

from clue_core.field import FieldKey

FieldProposalId = NewType("FieldProposalId", UUID)
SourceProposalId = NewType("SourceProposalId", UUID)


def new_field_proposal_id() -> FieldProposalId:
    return FieldProposalId(uuid4())


def new_source_proposal_id() -> SourceProposalId:
    return SourceProposalId(uuid4())


class ProposalStatus(StrEnum):
    PROPOSED = "proposed"
    PROMOTED = "promoted"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


class ProposalAuthority(StrEnum):
    POLICY = "policy"
    HUMAN = "human"


class FieldProposalRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    proposal_id: FieldProposalId
    field_key: FieldKey
    status: ProposalStatus


class SourceProposalRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    proposal_id: SourceProposalId
    source_key: str
    status: ProposalStatus


__all__ = [
    "FieldProposalId",
    "FieldProposalRef",
    "ProposalAuthority",
    "ProposalStatus",
    "SourceProposalId",
    "SourceProposalRef",
    "new_field_proposal_id",
    "new_source_proposal_id",
]
