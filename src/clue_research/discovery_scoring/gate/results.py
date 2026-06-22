"""The admission-gate result types (M6.2 / ENG-133)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from clue_research.core import ClaimId, EntityId


class AdmissionStatus(StrEnum):
    """The three-way outcome of the existence/identity gate (staged-flow §3)."""

    ADMITTED = "admitted"  # resolved to a real canonical account_entity (status=candidate)
    NEEDS_REVIEW = (
        "needs_review"  # mid-band confidence → routed to the M2 review queue, not guessed
    )
    REJECTED = "rejected"  # no live domain / nothing to resolve to → fabricated/dead, dropped


class AdmissionResult(BaseModel):
    """What :func:`~clue_research.discovery_scoring.gate.admission.admit` returns for one candidate.

    For ``ADMITTED``, ``account_entity_id`` is the resolved survivor and
    ``discovery_provenance_claim_id`` the (single, idempotent) provenance claim. For
    ``NEEDS_REVIEW``, ``review_task_id`` is the enqueued M2 task. For ``REJECTED``, ``reason`` says
    why — and **no** ``account_entity`` and **no** claim were written (the anti-fabrication
    guarantee)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: AdmissionStatus
    account_entity_id: EntityId | None = None
    discovery_provenance_claim_id: ClaimId | None = None
    review_task_id: EntityId | None = None
    reason: str | None = None


__all__ = ["AdmissionStatus", "AdmissionResult"]
