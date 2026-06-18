"""The typed claim with provenance — the atomic unit of the whole subsystem (M0.2 + M1.4).

This is the architecture's one bet made concrete: *verifiability is a property of the
data model* (substrate §0/§1). A fact is a ``Claim`` row, never a field on a free-text
dossier. One substrate carries **two provenance flavors** (staged-flow §9), discriminated by
``claim_flavor``:

* **field-claim provenance** (``FIELD_CLAIM``, the default) — the value + span + source + tier,
  plus ``identity_binding`` + ``use_class`` for contact claims (modes M2/M4);
* **discovery-provenance** (``DISCOVERY``) — a :class:`DiscoveryProvenance` envelope recording
  *where an entity was found and why it matched* (modes M1/M3), carried in the same row.

Invariants are enforced at construction (you cannot build an ill-formed claim) and the
promotion precondition is a pure predicate (:func:`can_be_promoted`). Claims are **frozen**
— append-only by construction, never UPDATE-in-place (substrate §1); a new observation
supersedes via ``superseded_by`` rather than mutating.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from clue_research.core.enums import (
    ClaimFlavor,
    EntityType,
    ExtractionMethod,
    IdentityBinding,
    ResearchMode,
    UseClass,
    VerificationStatus,
)
from clue_research.core.field import FieldClass, FieldKey, classify_field_key
from clue_research.core.primitives import (
    ClaimId,
    Confidence,
    Corroborations,
    CostCents,
    EntityId,
    RunId,
    SourceTier,
    UtcDatetime,
    new_claim_id,
)

# Extraction methods that must cite where the value came from. ``human`` and ``crm_import``
# may carry an internal/no URL; web/synthesis sources must point at a source_url.
_URL_REQUIRED_METHODS = frozenset(
    {ExtractionMethod.API, ExtractionMethod.SCRAPE, ExtractionMethod.LLM_SYNTHESIS}
)
_DISCOVERY_MODES = frozenset({ResearchMode.ACCOUNT_DISCOVERY, ResearchMode.COMMITTEE_DISCOVERY})


class DiscoveryProvenance(BaseModel):
    """Why a discovered candidate became an entity (staged-flow §6/§9) — the discovery-provenance
    envelope carried on a ``DISCOVERY``-flavored claim.

    Records where it was found (``found_via`` = the discovered-via channel), the signal that matched
    the ICP, and the discovery confidence. A hallucinated entity has nothing to resolve to and never
    acquires this — it dies at the existence/identity gate before any profiling spend. Stored as the
    claim's ``discovery_provenance`` JSONB; ``entity_id`` / ``run_id`` / ``research_mode`` mirror
    the claim's own columns (a self-contained provenance record) and must agree with them.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_id: EntityId
    found_via: str  # the source/where it was found, e.g. "exa_search" | "import:row#42"
    matched_signal: str  # why it matched the ICP
    discovery_confidence: Confidence
    source_url: str | None = None  # the channel / source_key
    run_id: RunId
    research_mode: ResearchMode

    @model_validator(mode="after")
    def _check_mode(self) -> DiscoveryProvenance:
        if self.research_mode not in _DISCOVERY_MODES:
            raise ValueError(
                "discovery-provenance only applies to discovery modes "
                "(account_discovery / committee_discovery)"
            )
        return self


class Claim(BaseModel):
    """A typed, provenance-bearing assertion about an entity's field (substrate §1).

    Construction enforces the structural invariants; it does **not** require an
    ``evidence_span`` for tier-4 (a span-less tier-4 claim is allowed to *exist* as
    ``UNVERIFIED`` — it simply cannot be promoted; see :func:`can_be_promoted`).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: ClaimId = Field(default_factory=new_claim_id)
    entity_id: EntityId
    entity_type: EntityType
    field_key: FieldKey
    value_json: JsonValue
    source_url: str | None = None
    source_tier: SourceTier
    extraction_method: ExtractionMethod
    evidence_span: str | None = None  # mandatory for tier-4 *promotion*, not construction
    confidence: Confidence
    corroborations: Corroborations = 0
    observed_at: UtcDatetime | None = None  # when the source published / was seen
    collected_at: UtcDatetime = Field(default_factory=lambda: datetime.now(UTC))
    cost_cents: CostCents = Decimal(0)
    run_id: RunId
    research_mode: ResearchMode
    superseded_by: ClaimId | None = None
    # --- field-claim provenance for personal data (contact claims only) ---
    identity_binding: IdentityBinding | None = None
    use_class: UseClass | None = None
    # --- provenance flavor (staged-flow §9): discovery vs field-claim ---
    claim_flavor: ClaimFlavor = ClaimFlavor.FIELD_CLAIM
    discovery_provenance: DiscoveryProvenance | None = None
    # --- promotion state (additive; driven by M9, not a conventions §4 field) ---
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED

    @model_validator(mode="after")
    def _check_provenance(self) -> Claim:
        # A contact *personal* field claim MUST carry its governance provenance. "Personal" is the
        # ``contact.facet.*`` field-class (conventions §3: contact.facet.* = rich personal hooks
        # governed by Doc D / M10); plain ``contact.*`` facts (role_on_committee, persona…) are not
        # personal hooks and do not require it. Account claims do not require it either (D3), nor
        # does a contact *discovery* claim (mode M3 admission evidence) — binding/use-class are
        # field-claim provenance for personal data (staged-flow §6/§9, Doc D §2).
        if (
            self.entity_type is EntityType.CONTACT
            and self.claim_flavor is ClaimFlavor.FIELD_CLAIM
            and classify_field_key(self.field_key) is FieldClass.CONTACT_FACET
            and (self.identity_binding is None or self.use_class is None)
        ):
            raise ValueError(
                "contact personal (contact.facet.*) field claims require both identity_binding "
                "and use_class (field-claim provenance for personal data — staged-flow §6, Doc D)"
            )

        # Tier-4 is LLM synthesis and vice versa (substrate §4 tier table).
        is_tier4 = self.source_tier == 4
        is_synth = self.extraction_method is ExtractionMethod.LLM_SYNTHESIS
        if is_tier4 != is_synth:
            raise ValueError(
                "source_tier 4 and extraction_method 'llm_synthesis' must agree "
                f"(got tier={self.source_tier}, method={self.extraction_method})"
            )

        # Web/synthesis claims must cite a source.
        if self.extraction_method in _URL_REQUIRED_METHODS and not self.source_url:
            raise ValueError(f"extraction_method {self.extraction_method} requires a source_url")

        # Provenance-flavor coherence (staged-flow §9).
        if self.claim_flavor is ClaimFlavor.DISCOVERY:
            if self.discovery_provenance is None:
                raise ValueError("a discovery-flavored claim requires a discovery_provenance")
            if self.research_mode not in _DISCOVERY_MODES:
                raise ValueError(
                    "a discovery-flavored claim must use a discovery research_mode "
                    "(account_discovery / committee_discovery)"
                )
            dp = self.discovery_provenance
            if (dp.entity_id, dp.run_id, dp.research_mode) != (
                self.entity_id,
                self.run_id,
                self.research_mode,
            ):
                raise ValueError(
                    "discovery_provenance entity_id/run_id/research_mode must match the claim's"
                )
        elif self.discovery_provenance is not None:
            raise ValueError("a field-claim-flavored claim must not carry discovery_provenance")
        return self

    @property
    def is_promotable(self) -> bool:
        """Convenience for :func:`can_be_promoted`."""
        return can_be_promoted(self)


def can_be_promoted(claim: Claim) -> bool:
    """Whether a claim is *structurally* eligible to be promoted past ``UNVERIFIED``.

    Encodes the accuracy/identity preconditions (the use/appropriateness gate is separate —
    M10). M9 calls this; it does not re-implement the rules:

    * a tier-4 (LLM-synthesized) claim with no ``evidence_span`` can never be promoted —
      this is the schema-level kill switch for fabricated facts (substrate §1/§6);
    * a contact claim with only a ``WEAK`` identity binding can never be promoted — better
      an empty hook than someone else's fact (staged-flow §6).

    Returning ``True`` means "eligible", not "verified": corroboration / the faithfulness
    judge (M9) still decide the actual transition.
    """
    tier4_without_span = claim.source_tier == 4 and not claim.evidence_span
    weakly_bound_contact = (
        claim.entity_type is EntityType.CONTACT and claim.identity_binding is IdentityBinding.WEAK
    )
    return not (tier4_without_span or weakly_bound_contact)
