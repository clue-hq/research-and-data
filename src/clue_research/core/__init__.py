"""`clue_research.core` — Core domain types & shared contracts (M0.2).

**This package IS the seam** (conventions §2): the single, shared, DRY definition of the
typed claim with provenance and every contract built around it. Resolvers, adapters,
judges, scorers, the merge view, and the handoff all import from here and never
re-implement these shapes — which is what lets a provider, a judge model, or the durable
backend be swapped without touching the types. ``core`` imports nothing else inside
``clue_research`` (enforced by import-linter, M0.1).

Implements ENG-108 (docs/specs/M00-foundations-and-shared-contracts.md §M0.2).
"""

from __future__ import annotations

from clue_research.core.claim import Claim, DiscoveryProvenance, can_be_promoted
from clue_research.core.entity import AccountEntity, Entity
from clue_research.core.enums import (
    AccountStatus,
    ClaimFlavor,
    EntityScope,
    EntityType,
    ExtractionMethod,
    FreshnessState,
    IdentityBinding,
    Modality,
    PassKind,
    Persona,
    ResearchMode,
    UseClass,
    VerificationStatus,
)
from clue_research.core.factories import (
    TIER_ORDER,
    account_claim,
    by_tier_ascending,
    contact_claim,
    contact_field_claim,
    discovery_claim,
    field_claim,
    first_confident_claim,
    parse_value_json,
    serialize_value_json,
    to_value_json,
)
from clue_research.core.field import (
    NS_ACCOUNT,
    NS_ACCOUNT_RESONANCE,
    NS_CONTACT,
    NS_CONTACT_FACET,
    NS_CORE,
    FieldClass,
    FieldDef,
    FieldKey,
    classify_field_key,
    field_key,
    field_namespace,
    is_field_key_or_class,
    is_pack_registered,
    is_valid_field_key,
    register_pack,
)
from clue_research.core.handoff import (
    AccountHandoff,
    CommitteeMember,
    CurrentValue,
    ICPSpec,
    NarrativeSupport,
    ProfileClaimView,
    ProvenanceRef,
    Score,
    ScoreComponent,
    ValueNarrativeItem,
    WinningProvenance,
)
from clue_research.core.primitives import (
    ClaimId,
    Confidence,
    Corroborations,
    CostCents,
    EntityId,
    RunId,
    SourceTier,
    UnitInterval,
    UtcDatetime,
    new_claim_id,
    new_entity_id,
    new_run_id,
)
from clue_research.core.resolver import Resolver
from clue_research.core.source import SourceManifest

__all__ = [
    # primitives
    "EntityId",
    "ClaimId",
    "RunId",
    "new_entity_id",
    "new_claim_id",
    "new_run_id",
    "SourceTier",
    "Confidence",
    "Corroborations",
    "CostCents",
    "UnitInterval",
    "UtcDatetime",
    # enums
    "EntityType",
    "ExtractionMethod",
    "ResearchMode",
    "VerificationStatus",
    "FreshnessState",
    "ClaimFlavor",
    "Modality",
    "EntityScope",
    "UseClass",
    "IdentityBinding",
    "PassKind",
    "AccountStatus",
    "Persona",
    # fields
    "FieldClass",
    "FieldKey",
    "FieldDef",
    "is_valid_field_key",
    "is_field_key_or_class",
    "classify_field_key",
    "field_namespace",
    "field_key",
    "register_pack",
    "is_pack_registered",
    "NS_CORE",
    "NS_ACCOUNT",
    "NS_ACCOUNT_RESONANCE",
    "NS_CONTACT",
    "NS_CONTACT_FACET",
    # entities
    "Entity",
    "AccountEntity",
    # claims
    "Claim",
    "DiscoveryProvenance",
    "can_be_promoted",
    # source / resolver
    "SourceManifest",
    "Resolver",
    # composite contracts
    "WinningProvenance",
    "CurrentValue",
    "ICPSpec",
    "Score",
    "ScoreComponent",
    "ProfileClaimView",
    "CommitteeMember",
    "NarrativeSupport",
    "ValueNarrativeItem",
    "ProvenanceRef",
    "AccountHandoff",
    # helpers
    "TIER_ORDER",
    "to_value_json",
    "serialize_value_json",
    "parse_value_json",
    "by_tier_ascending",
    "first_confident_claim",
    "account_claim",
    "contact_claim",
    "discovery_claim",
    "field_claim",
    "contact_field_claim",
]
