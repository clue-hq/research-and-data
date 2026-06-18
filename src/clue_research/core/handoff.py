"""Composite output contracts (M0.2).

These name the larger shapes so later milestones *extend one shared definition* instead
of inventing their own:

* :class:`CurrentValue` — the result shape of the deterministic merge (substrate §1); the
  merge *algorithm* is M1.
* :class:`ICPSpec` — the compiler output (staged-flow §2); the *compiler* is M3.
* :class:`AccountHandoff` — the output contract this subsystem ends at (overview §3); the
  *assembly* (and the value narrative *generation*) is M12.

M0.2 ships shapes and field-level validation only — no merge, no compilation, no assembly.
Open decisions: **D1** the handoff stops at the value narrative (recommended default) but
``value_narrative`` is its own list so the boundary can move without breaking the type;
**D2** no content-schema type lives here (that is downstream of this repo).
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, JsonValue

from clue_research.core.enums import FreshnessState, IdentityBinding, Persona, UseClass
from clue_research.core.field import FieldKey
from clue_research.core.primitives import (
    ClaimId,
    Confidence,
    EntityId,
    SourceTier,
    UnitInterval,
    UtcDatetime,
)


class WinningProvenance(BaseModel):
    """The provenance of the claim that won a merge (substrate §1)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: ClaimId
    source_url: str | None = None
    source_tier: SourceTier
    evidence_span: str | None = None
    confidence: Confidence
    collected_at: UtcDatetime
    corroborations: int = 0


class CurrentValue(BaseModel):
    """``current_value(entity, field)`` result: value + winning provenance + conflict flag.

    The *policy* that computes it (highest-trust tier satisfying freshness, tie-break on
    corroborations/confidence/recency, conflict flag when two tier<=2 sources disagree) is M1.2.
    A merge that finds no eligible claim returns ``None`` (an empty field is a correct output —
    conventions §5), not a ``CurrentValue`` with a null value.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_id: EntityId
    field_key: FieldKey
    value_json: JsonValue
    provenance: WinningProvenance
    freshness_state: FreshnessState  # whether the winning claim is within its field's TTL
    conflict: bool = False  # set when two tier<=2 sources disagree
    conflicting_claim_ids: tuple[
        ClaimId, ...
    ] = ()  # the disagreeing tier<=2 claims (review surface)


class ICPSpec(BaseModel):
    """Versioned ICP compiler output (staged-flow §2 / Doc B). Stub: M3 enriches the
    discovery strategy / source profile / scoring rubric into typed structures."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: UUID
    version: int = 1
    field_keys: tuple[FieldKey, ...] = ()  # the active field set (core + packs)
    discovery_strategy: dict[str, JsonValue] = {}  # mode-M1 strategy
    source_profile: dict[str, JsonValue] = {}  # per-pack source weights (M2/M4)
    scoring_rubric: dict[str, JsonValue] = {}  # fit + intent weights (M3.4/M6)


class ScoreComponent(BaseModel):
    """One decomposed contributor to a fit/intent score, linked to its evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    weight: UnitInterval
    value: UnitInterval
    evidence_claim_ids: tuple[ClaimId, ...] = ()  # "no score without its evidence"


class Score(BaseModel):
    """A fit or intent score, decomposed (overview §1: each linked to its claims)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: UnitInterval
    components: tuple[ScoreComponent, ...] = ()


class ProfileClaimView(BaseModel):
    """A claim as it appears in the handoff: value + the provenance that proves it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: ClaimId
    value_json: JsonValue
    evidence_span: str | None = None
    source_tier: SourceTier
    identity_binding: IdentityBinding | None = None  # present for contact claims
    use_class: UseClass | None = None  # present for contact claims


class CommitteeMember(BaseModel):
    """A buying-committee member, identity-resolved and persona-tagged (Output 3)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contact_entity_id: EntityId
    persona: Persona
    role_on_committee: str
    profile_claims: tuple[ProfileClaimView, ...] = ()


class NarrativeSupport(BaseModel):
    """The two-sided evidence behind a narrative line (account × client knowledge)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_evidence_ids: tuple[ClaimId, ...] = ()
    client_knowledge_ids: tuple[str, ...] = ()  # ids into the Client Knowledge Base (M5)


class ValueNarrativeItem(BaseModel):
    """A per-(account, persona) argument — itself a provenance-backed claim (Output 4)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claim_id: ClaimId
    persona: Persona
    argument: str  # the grounded "why we matter / which angle"
    supporting: NarrativeSupport


class ProvenanceRef(BaseModel):
    """A fact's source, for the handoff's provenance index ("every line is sourced")."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_url: str | None = None
    source_tier: SourceTier
    evidence_span: str | None = None


class AccountHandoff(BaseModel):
    """The contract object handed downstream per high-tier account (overview §3).

    The four required outputs, assembled: scored list (Output 1), verified profile
    (Output 2), governed committee (Output 3), and the value narrative (Output 4), with a
    ``provenance_index`` that makes "every fact links to its source" literally true.
    Assembly is M12; this is the shape only.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_entity_id: EntityId
    fit_score: Score
    intent_score: Score
    account_profile_claims: tuple[ProfileClaimView, ...] = ()
    committee: tuple[CommitteeMember, ...] = ()
    value_narrative: tuple[ValueNarrativeItem, ...] = ()
    provenance_index: dict[str, ProvenanceRef] = {}  # claim_id -> its source
