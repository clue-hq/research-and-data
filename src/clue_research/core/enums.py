"""Closed taxonomies shared across the subsystem (M0.2).

These are the *fixed* enums of conventions §3 — entity types, source extraction
methods, research modes, the use-class and identity-binding taxonomies, etc. They are
closed by design (unlike field-keys, which are an open registry — see ``field.py``).
``StrEnum`` is used so each member serializes to its canonical string in ``value_json``,
JSON, and the DB.
"""

from __future__ import annotations

from enum import StrEnum


class EntityType(StrEnum):
    """What a claim/entity is about (substrate §1). Contacts resolve under accounts."""

    ACCOUNT = "account"
    CONTACT = "contact"


class ExtractionMethod(StrEnum):
    """How a claim's value was obtained (substrate §1)."""

    API = "api"
    SCRAPE = "scrape"
    LLM_SYNTHESIS = "llm_synthesis"
    HUMAN = "human"
    CRM_IMPORT = "crm_import"


class ResearchMode(StrEnum):
    """The 2x2 of research modes (staged-flow §1). Discovery modes (M1/M3) attach
    discovery-provenance; profiling modes (M2/M4) produce field claims."""

    ACCOUNT_DISCOVERY = "account_discovery"  # mode M1
    ACCOUNT_PROFILING = "account_profiling"  # mode M2
    COMMITTEE_DISCOVERY = "committee_discovery"  # mode M3
    CONTACT_PROFILING = "contact_profiling"  # mode M4


class VerificationStatus(StrEnum):
    """Promotion-state lifecycle of a claim (the M1.1 ``claim.verification_status`` column;
    conventions §4 extension). The faithfulness/corroboration layer (M9) and the use gate
    (M10) drive transitions; a tier-4 claim with no evidence span cannot leave ``UNVERIFIED``
    (see ``claim.can_be_promoted``). ``FLAGGED`` marks a claim the verification/merge layer
    surfaced for human review (e.g. a conflict between authoritative sources) rather than
    silently resolving it (substrate §1/§6)."""

    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    REJECTED = "rejected"
    FLAGGED = "flagged"


class Modality(StrEnum):
    """The shape of a source's content (staged-flow §7a)."""

    TEXT = "text"
    VIDEO = "video"
    AUDIO = "audio"
    PDF = "pdf"
    STRUCTURED = "structured"


class EntityScope(StrEnum):
    """Which entity kinds a source can populate (staged-flow §7a)."""

    ACCOUNT = "account"
    CONTACT = "contact"
    BOTH = "both"


class UseClass(StrEnum):
    """Use-class taxonomy for personal data (Doc D §2). ``SENSITIVE`` (special-category)
    is excluded from outreach by default; the appropriateness/use gate (M10) reads this."""

    PROFESSIONAL_PUBLIC = "professional-public"
    PERSONAL_PUBLIC_NON_SENSITIVE = "personal-public-non-sensitive"
    SENSITIVE = "sensitive"


class IdentityBinding(StrEnum):
    """How tightly a personal claim is bound to *this* person (staged-flow §6).
    A ``WEAK`` (same-name-only) binding never promotes and never drives outreach."""

    STRONG = "strong"
    WEAK = "weak"


class ClaimFlavor(StrEnum):
    """The two structurally different kinds of provenance one substrate carries (staged-flow §9).

    * ``DISCOVERY`` — *discovery-provenance* (modes M1/M3): where an entity was found and why it
      matched (the existence-gate evidence). Carries a :class:`DiscoveryProvenance` envelope; it is
      admission evidence, not a field value, so the merge view (M1.2) never treats it as truth.
    * ``FIELD_CLAIM`` — *field-claim provenance* (modes M2/M4): a value + span + tier (plus
      ``identity_binding`` + ``use_class`` for contacts). The default flavor."""

    DISCOVERY = "discovery"
    FIELD_CLAIM = "field_claim"


class FreshnessState(StrEnum):
    """Whether the claim that won a merge satisfies its field's freshness TTL (substrate §1/§6).
    Stale winners are never dropped — they are returned ``STALE`` so the scoring layer can discount
    them and a refresh can be scheduled (the merge surfaces, never silently drops, staleness)."""

    FRESH = "fresh"
    STALE = "stale"


class PassKind(StrEnum):
    """Two-pass economics (substrate §3): cheap ``SCORING`` on every account vs
    expensive ``DEEP`` synthesis only after tiering."""

    SCORING = "scoring"
    DEEP = "deep"


class AccountStatus(StrEnum):
    """Lifecycle of a resolved account entity (substrate §2)."""

    CANDIDATE = "candidate"
    ACTIVE = "active"
    MERGED = "merged"


class ReuseScope(StrEnum):
    """Cross-tenant reuse class of a claim (substrate §2 — the moat, made safe; M2.5).

    * ``PUBLIC_FOOTPRINT`` — a public fact about a company (employee count, tech stack, funding)
      partially reusable across clients that amortizes cost; carries no ``tenant_id``.
    * ``TENANT_PRIVATE`` — client-specific scoring, CRM-imported facts, client-knowledge-derived
      claims, and any contact ``facet`` / personal / resonance data; strictly tenant-isolated and so
      always carries a ``tenant_id``.

    The reuse-class is *derived from policy at write* (the classifier maps ``(field_key namespace,
    extraction_method, source_tier) → scope``) and stored for fast filtering; the tenant-scoped read
    returns public-footprint (any tenant) ∪ this tenant's private, and never another tenant's
    private. A claim is ``TENANT_PRIVATE`` iff it has a ``tenant_id``."""

    PUBLIC_FOOTPRINT = "public_footprint"
    TENANT_PRIVATE = "tenant_private"


class Persona(StrEnum):
    """Buying-committee personas/roles (conventions §3)."""

    CHAMPION = "champion"
    ECONOMIC_BUYER = "economic_buyer"
    TECHNICAL_EVALUATOR = "technical_evaluator"
    BLOCKER = "blocker"
