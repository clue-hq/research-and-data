"""The candidate value types — grounded by construction (M6.1 / ENG-128).

A discovered candidate is a **hypothesis, not an account** (staged-flow §3): it carries where it was
found and why it matched, but it is not an ``account_entity`` until the existence/identity gate
(M6.2) resolves it. The one non-negotiable encoded here is the **anti-fabrication invariant**: a
candidate cannot be constructed without a grounding handle — a ``source_record_ref`` (the channel's
record id) or a ``source_url`` from a real channel call. An LLM may *plan queries* (M6.1 query
planning) but can never mint a candidate, because there is no grounded record behind an invention.
This is the structural answer to the prototype's "name 50 companies that fit" fabrication.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, model_validator

from clue_research.core import Confidence, CostCents, EntityId

# The reserved channel label for lookalike expansion from seed/customer/import entities (staged-flow
# §3; Doc B §4 hybrid). Distinct from a structured-DB/web channel's ``source_key`` so the gate and
# coverage layers can tell a seed-expanded candidate from a directly-searched one.
LOOKALIKE_CHANNEL = "lookalike"


def _is_grounded(source_record_ref: str | None, source_url: str | None) -> bool:
    """A candidate is grounded iff it carries a real record handle or URL from a channel call."""
    return bool(source_record_ref) or bool(source_url)


class CandidateRecord(BaseModel):
    """One grounded record a ``DiscoveryChannel`` returns for a query — exactly what the *source*
    knows, never a channel-agnostic blob.

    Construction enforces the anti-fabrication invariant: a record with neither
    ``source_record_ref`` nor ``source_url`` is rejected (a channel that cannot ground a candidate
    must not return one). The orchestrator wraps each record into a :class:`CandidateHypothesis`,
    adding the matched channel + (for lookalike) the seed it expanded from.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_record_ref: str = ""  # the channel's record id/handle (e.g. "apollo:org/123")
    source_url: str | None = None  # the candidate's domain/URL where applicable
    raw_name: str | None = None  # the unresolved company name as the source returned it
    candidate_domain: str | None = None  # the candidate's web domain, if the source returned one
    matched_signal: str = ""  # which ICP filter/signal this record matched (for provenance)
    confidence: Confidence = 0.5  # the channel's confidence the record is a real, relevant company
    cost_cents: CostCents = Decimal(0)  # the spend attributed to producing this record

    @model_validator(mode="after")
    def _check_grounded(self) -> CandidateRecord:
        if not _is_grounded(self.source_record_ref, self.source_url):
            raise ValueError(
                "a CandidateRecord must carry a source_record_ref or source_url — a candidate "
                "with no grounding is a fabrication discovery never emits (staged-flow §3/§8)"
            )
        return self


class CandidateHypothesis(BaseModel):
    """A proposed account from discovery — *not* an ``account_entity`` until M6.2 admits it.

    This is the convergence contract the existence/identity gate (M6.2) reads, and the same shape an
    imported account (M5, Scenario B) is wrapped in so both entry scenarios meet at the gate. Like
    :class:`CandidateRecord` it cannot exist without grounding; it adds ``matched_channel`` (the
    ``source_key`` it came from, or ``"lookalike"``/``"import"``) and, for lookalike, the
    ``seed_entity_id`` it expanded from.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    matched_channel: str  # the source_key that produced it (or LOOKALIKE_CHANNEL / "import")
    source_record_ref: str = ""
    source_url: str | None = None
    raw_name: str | None = None
    candidate_domain: str | None = None
    matched_signal: str = ""
    resolver_confidence: Confidence = 0.5
    cost_cents: CostCents = Decimal(0)
    seed_entity_id: EntityId | None = None  # set when matched_channel == LOOKALIKE_CHANNEL

    @model_validator(mode="after")
    def _check_grounded(self) -> CandidateHypothesis:
        if not _is_grounded(self.source_record_ref, self.source_url):
            raise ValueError(
                "a CandidateHypothesis must carry a source_record_ref or source_url originating "
                "from a real channel call (grounded-only; the LLM plans queries, never entities — "
                "staged-flow §3/§8)"
            )
        return self

    @classmethod
    def from_record(
        cls,
        record: CandidateRecord,
        *,
        matched_channel: str,
        seed_entity_id: EntityId | None = None,
    ) -> CandidateHypothesis:
        """Wrap a channel's :class:`CandidateRecord` into a hypothesis tagged with its channel."""
        return cls(
            matched_channel=matched_channel,
            source_record_ref=record.source_record_ref,
            source_url=record.source_url,
            raw_name=record.raw_name,
            candidate_domain=record.candidate_domain,
            matched_signal=record.matched_signal,
            resolver_confidence=record.confidence,
            cost_cents=record.cost_cents,
            seed_entity_id=seed_entity_id,
        )


__all__ = ["CandidateRecord", "CandidateHypothesis", "LOOKALIKE_CHANNEL"]
