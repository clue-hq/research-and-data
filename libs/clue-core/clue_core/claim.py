"""The typed claim with provenance — the atomic unit of the whole subsystem (M0.2 + M1.4).

This is the architecture's one bet made concrete: *verifiability is a property of the
data model* (substrate §0/§1). A fact is a ``Claim`` row, never a field on a free-text
dossier. One substrate carries distinct provenance flavors, discriminated by
``claim_flavor``:

* **field-claim provenance** (``FIELD_CLAIM``, the default) — the value + span + source + tier,
  plus ``identity_binding`` + ``use_class`` for contact claims (modes M2/M4);
* **discovery-provenance** (``DISCOVERY``) — a :class:`DiscoveryProvenance` envelope recording
  *where an entity was found and why it matched* (modes M1/M3), carried in the same row.
* **derived provenance** (``DERIVED``) — a C7 inference whose evidence is an immutable ordered
  support-claim set plus an entailment verdict.

Invariants are enforced at construction (you cannot build an ill-formed claim) and the
promotion precondition is a pure predicate (:func:`can_be_promoted`). Claims are **frozen**
— append-only by construction, never UPDATE-in-place (substrate §1); a new observation
supersedes via ``superseded_by`` rather than mutating.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from annotated_types import Ge, Le
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from clue_core.enums import (
    ClaimFlavor,
    ClaimProvenanceKind,
    EntityType,
    ExtractionMethod,
    IdentityBinding,
    ResearchMode,
    ReuseScope,
    UseClass,
    VerificationStatus,
)
from clue_core.field import FieldClass, FieldKey, classify_field_key
from clue_core.primitives import (
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

# Extraction methods that must cite where the value came from to be *promotable* (ARV2 D1 moved
# this from construction to :func:`can_be_promoted`). ``human`` and ``crm_import`` may carry an
# internal/no URL; a web/synthesis claim without a source_url exists but stays ``UNVERIFIED``.
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
    ``UNVERIFIED`` — it simply cannot be promoted; see :func:`can_be_promoted`). Since ARV2 D1
    (master plan §2) it does **not** require a ``source_url`` for api/scrape/synthesis claims
    either — such a claim exists ``UNVERIFIED`` with a ``source_missing`` write marker and cannot
    be promoted, so the lenient write gate can keep the honest, uncitable observation instead of
    throwing it away.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: ClaimId = Field(default_factory=new_claim_id)
    entity_id: EntityId
    entity_type: EntityType
    field_key: FieldKey
    value_json: JsonValue
    source_url: str | None = None
    # The registered source that produced this claim (the M4.2 ``source_manifest.source_key``). The
    # waterfall (M4.1) stamps it so per-source yield/idempotency keys on the source, not the tier
    # (a tier_plan may list >1 source per tier). Nullable: non-resolver writers leave it None.
    source_key: str | None = None
    # The durable evidence snapshot this claim was extracted from (PB-B2 / REQ-07): the
    # content-addressed ``artifact.storage_key`` of the bytes the fetch saw, so the evidence_span
    # resolves offline even after the live source_url rots. Nullable: pre-B2 rows and
    # non-snapshotting writers (tier-1 APIs) leave it None. Immutable provenance (DB trigger).
    artifact_key: str | None = None
    # Durable external-acquisition lineage for a claim materialized from an already-settled
    # provider snapshot.  These are provider-neutral opaque references: the source adapter owns
    # their concrete format, while the claim preserves the exact operation, immutable snapshot,
    # and provider request that yielded its evidence.  All three are born together or omitted.
    source_operation_ref: str | None = None
    source_snapshot_ref: str | None = None
    source_request_ref: str | None = None
    # Typed assertion/derivation provenance. This is orthogonal to extraction_method: an API may
    # return a literal attribute or a provider-modeled relationship, and both are still API
    # extraction. Nullable for legacy and claim classes that have not adopted this discriminator.
    provenance_kind: ClaimProvenanceKind | None = None
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
    # --- cross-tenant reuse class (M2.5; substrate §2) ---
    # Public-footprint by default (firmographic/technographic facts amortize across clients);
    # tenant-private claims (scoring, CRM-import, personal/facet/resonance) carry a workspace_id.
    # The
    # classifier (identity.classify_reuse_scope) stamps these at write; the merge read scopes on it.
    reuse_scope: ReuseScope = ReuseScope.PUBLIC_FOOTPRINT
    workspace_id: str | None = None
    # Product-scoped client truth (REQ-22 / Phase C4). Product-neutral target facts and legacy
    # client claims leave this null. Born immutable: product context is provenance, not metadata
    # that may be attached after a claim exists.
    product_id: str | None = None
    # --- promotion state (additive; driven by M9, not a conventions §4 field) ---
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    # --- ARV2 D1 (master plan §4) ---
    # 1 = active buying intent, 2 = qualifying fact, 3 = context. Orders display items; never gates.
    signal_priority: Annotated[int, Ge(1), Le(3)] = 3
    # Appropriateness, distinct from accuracy: False confines the claim to restricted display
    # sections and bars it from outreach copy.
    outreach_safe: bool = True
    # Lenient-write annotations stamped at insert (schema_valid, source_missing, proposed_field,
    # identity_binding_defaulted, use_class_defaulted, pipe_joined_key, evidence_verbatim,
    # unevidenced, entailment). None = nothing to note.
    write_markers: dict[str, JsonValue] | None = None

    @model_validator(mode="after")
    def _check_provenance(self) -> Claim:
        external_refs = (
            self.source_operation_ref,
            self.source_snapshot_ref,
            self.source_request_ref,
        )
        if any(ref is not None for ref in external_refs):
            if not all(isinstance(ref, str) and ref.strip() for ref in external_refs):
                raise ValueError(
                    "external source operation/snapshot/request references must be present "
                    "together and non-empty"
                )
            if self.artifact_key is None:
                raise ValueError("external snapshot lineage requires an evidence artifact_key")

        # A contact *personal* field claim MUST carry its governance provenance. "Personal" is the
        # ``contact.facet.*`` field-class (conventions §3: contact.facet.* = rich personal hooks
        # governed by Doc D / M10); plain ``contact.*`` facts (role_on_committee, persona…) are not
        # personal hooks and do not require it. Account claims do not require it either (D3), nor
        # does a contact *discovery* claim (mode M3 admission evidence) — binding/use-class are
        # non-discovery claim provenance for personal data (staged-flow §6/§9, Doc D §2).
        # C7 derived contact facets remain personal statements and therefore carry the same
        # born-governed identity/use provenance as direct field claims.
        if (
            self.entity_type is EntityType.CONTACT
            and self.claim_flavor is not ClaimFlavor.DISCOVERY
            and classify_field_key(self.field_key) is FieldClass.CONTACT_FACET
            and (self.identity_binding is None or self.use_class is None)
        ):
            raise ValueError(
                "contact personal (contact.facet.*) claims require both identity_binding and "
                "use_class (personal-data provenance — staged-flow §6, Doc D)"
            )

        # Tier-4 is LLM synthesis and vice versa (substrate §4 tier table).
        is_tier4 = self.source_tier == 4
        is_synth = self.extraction_method is ExtractionMethod.LLM_SYNTHESIS
        if is_tier4 != is_synth:
            raise ValueError(
                "source_tier 4 and extraction_method 'llm_synthesis' must agree "
                f"(got tier={self.source_tier}, method={self.extraction_method})"
            )

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
            raise ValueError("a non-discovery claim must not carry discovery_provenance")

        if self.claim_flavor is ClaimFlavor.DERIVED:
            if (
                self.source_tier != 4
                or self.extraction_method is not ExtractionMethod.LLM_SYNTHESIS
            ):
                raise ValueError(
                    "a derived claim must be tier-4/model-authored; its evidence is its support set"
                )
            if self.source_url is not None or self.evidence_span is not None:
                raise ValueError(
                    "a derived claim uses claim-support edges, not source_url or evidence_span"
                )

        # Reuse-class ⟺ tenant binding (M2.5, substrate §2): a tenant-private claim is always
        # attributed to a tenant; a public-footprint claim never is (so it amortizes across
        # clients). Mirrors the DB CHECK; "a private claim is never silently shared" is invariant.
        if self.reuse_scope is ReuseScope.TENANT_PRIVATE and self.workspace_id is None:
            raise ValueError("a tenant_private claim must carry a workspace_id")
        if self.reuse_scope is ReuseScope.PUBLIC_FOOTPRINT and self.workspace_id is not None:
            raise ValueError("a public_footprint claim must not carry a workspace_id")
        if self.product_id is not None and (
            self.reuse_scope is not ReuseScope.TENANT_PRIVATE or self.workspace_id is None
        ):
            raise ValueError(
                "a product-scoped claim must be tenant_private and carry a workspace_id"
            )
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
      an empty hook than someone else's fact (staged-flow §6);
    * an ``api``/``scrape``/``llm_synthesis`` claim with no ``source_url`` can never be promoted —
      a web/synthesis fact nobody can go and check stays ``UNVERIFIED`` (ARV2 D1, master plan §2;
      until then this was a *construction* rule, which the lenient write gate cannot use).

    Returning ``True`` means "eligible", not "verified": corroboration / the faithfulness
    judge (M9) still decide the actual transition.
    """
    tier4_without_span = (
        claim.source_tier == 4
        and claim.claim_flavor is not ClaimFlavor.DERIVED
        and not claim.evidence_span
    )
    weakly_bound_contact = (
        claim.entity_type is EntityType.CONTACT and claim.identity_binding is IdentityBinding.WEAK
    )
    url_required_but_missing = (
        claim.claim_flavor is not ClaimFlavor.DERIVED
        and claim.extraction_method in _URL_REQUIRED_METHODS
        and not claim.source_url
    )
    return not (tier4_without_span or weakly_bound_contact or url_required_but_missing)


def reference_time(claim: Claim) -> datetime:
    """The time a claim's freshness is measured from: when the source was observed, else when it
    was collected (M9.5 DRY consolidation — the one definition the merge view (M1.2) and the
    freshness engine (M9.5) share, so they can never disagree on a claim's age)."""
    return claim.observed_at or claim.collected_at
