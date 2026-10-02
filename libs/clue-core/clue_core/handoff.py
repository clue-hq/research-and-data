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

from pydantic import BaseModel, ConfigDict, JsonValue, model_validator

from clue_core.enums import (
    FreshnessState,
    ICPCreatedFrom,
    ICPStatus,
    IdentityBinding,
    Persona,
    UseClass,
)
from clue_core.field import FieldKey
from clue_core.primitives import (
    ClaimId,
    Confidence,
    EntityId,
    ProjectRunId,
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

    @property
    def evidence_backed(self) -> bool:
        """Whether this merged value *answers* its field: fresh, unconflicted, evidence-backed.

        The one satisfaction test every consumer must agree on. A merge winner with no evidence
        span is not an answer (conventions §5: a claim with no evidence span cannot be promoted),
        so treating it as one is how a field becomes simultaneously unbuyable ("already resolved")
        and unsatisfiable ("no evidence") — a state nothing can leave. Species is deliberately not
        part of it: reusability across projects is a property of the *field*, and callers that need
        it apply it beside this test rather than folding it in here.
        """

        return (
            self.freshness_state is FreshnessState.FRESH
            and not self.conflict
            and bool((self.provenance.evidence_span or "").strip())
        )


class ICPSpec(BaseModel):
    """The versioned ICP spec (staged-flow §2 / Doc B; conventions §4) — the single contract M3.2 /
    M3.4 read and M5 writes, keyed ``(workspace_id, icp_key, version)``.

    M3.1 owns its durable, append-only storage (an ``active`` spec is immutable; an edit appends a
    new ``version`` with ``parent_version`` and activating it archives the prior). M3.2 compiles
    ``field_keys`` ∪ ``enabled_packs`` into a field plan; the rubric / discovery / source-profile
    slots are stored here as opaque config whose internals are owned by M3.4 / M6 / M4 respectively
    (the slots are referenced by name so each evolves independently)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # identity & versioning (M3.1)
    workspace_id: str
    icp_key: str  # distinguishes segments under one client (D5: multi-ICP)
    created_from: ICPCreatedFrom
    version: int = 1
    parent_version: int | None = None  # the version this was derived from (append-only lineage)
    status: ICPStatus = ICPStatus.DRAFT
    label: str | None = None
    description: str | None = None
    created_by: str | None = None
    created_at: UtcDatetime | None = None  # set by the store on write

    # C4 harness lineage. Legacy/manual specs may leave these null; every C4 confirmation stamps
    # all three so post-confirmation run entry can prove the exact KB -> ICP -> product chain.
    client_entity_id: EntityId | None = None
    client_kb_version: int | None = None
    product_id: str | None = None

    # the four sub-contract slots (conventions §4), referenced by name
    field_keys: tuple[FieldKey, ...] = ()  # active field set (core + packs)
    enabled_packs: tuple[str, ...] = ()  # M3.3 packs enabled for this ICP
    discovery_strategy: dict[str, JsonValue] = {}  # mode-M1 strategy (M6 interprets)
    source_profile_ref: dict[
        str, JsonValue
    ] = {}  # per-ICP source-profile config ref (M4 interprets)
    scoring_rubric: dict[str, JsonValue] = {}  # fit + intent weights (M3.4 interprets)

    @model_validator(mode="after")
    def _lineage_is_complete(self) -> ICPSpec:
        lineage = (self.client_entity_id, self.client_kb_version, self.product_id)
        if any(item is not None for item in lineage) and not all(
            item is not None for item in lineage
        ):
            raise ValueError(
                "ICP lineage is all-or-none: client_entity_id, client_kb_version, and "
                "product_id must be set together"
            )
        if self.client_kb_version is not None and self.client_kb_version < 1:
            raise ValueError("client_kb_version must be at least 1")
        return self


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

    The ``icp_spec_version`` / ``project_run_id`` / ``assembled_at`` stamps are **additive +
    defaulted** (phase-3 pre-flight contract-delta) so M13's existing reads don't break, but M12's
    assembler MUST set them — ``(account_entity_id, icp_spec_version)`` is the handoff scope. They
    are added here, not as M12-runtime extras, because the model is ``frozen, extra="forbid"`` and
    M12 must not edit ``core``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    account_entity_id: EntityId
    fit_score: Score
    intent_score: Score
    account_profile_claims: tuple[ProfileClaimView, ...] = ()
    committee: tuple[CommitteeMember, ...] = ()
    value_narrative: tuple[ValueNarrativeItem, ...] = ()
    provenance_index: dict[str, ProvenanceRef] = {}  # claim_id -> its source
    # phase-3 pre-flight additive stamps — M12's assembler sets the first three (the scope key +
    # provenance of *when/which run* assembled this); defaulted so M13's reads stay back-compatible.
    icp_spec_version: int | None = None  # with account_entity_id, the handoff scope
    project_run_id: ProjectRunId | None = None
    assembled_at: UtcDatetime | None = None
    coverage_confidence: UnitInterval | None = (
        None  # M6.5 coverage estimate (confidence, not a guarantee)
    )
    field_conflicts: dict[
        FieldKey, tuple[ClaimId, ...]
    ] = {}  # account field_key -> disagreeing tier<=2 claims
