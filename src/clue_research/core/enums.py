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


class ICPStatus(StrEnum):
    """Lifecycle of a versioned ICP spec (M3.1; staged-flow §2). An ``ACTIVE`` spec is immutable;
    an edit appends a new version and activating it ``ARCHIVED``s the prior — never deletes."""

    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class ICPCreatedFrom(StrEnum):
    """Provenance of an ICP-spec version (M3.1). ``IMPORT_REDERIVE`` is the optional D6 hook — a
    re-derive of the ICP from an imported list (the default flag-and-proceed adds no spec)."""

    SYNTHESIS = "synthesis"
    CLIENT_EDIT = "client_edit"
    IMPORT_REDERIVE = "import_rederive"


# ---------------------------------------------------------------------------
# Beat-0 contract-freeze additions (M5-M9 parallelisation).
#
# These are the *closed taxonomies* the cross-milestone seams added in Beat-0 exchange — the
# durable-execution contracts (``core.execution``) and the verification gates
# (``core.verification``). They live here, with every other closed enum, because ``core`` is the
# only package every milestone may import; an enum that crosses a package boundary cannot live in
# the milestone that owns the behaviour (M7 ``durable`` / M9 ``verification``) without breaking
# worker independence (the import-linter contract). The *implementations* and the mirrored DB enum
# types land in the owning milestone branch; these Python members are the shared vocabulary the
# branches fork against. (M7's ``campaign_run`` / ``account_run`` lifecycle enums are NOT here —
# they are table-column taxonomies internal to ``durable``, added by the M7 branch with its tables.)
# ---------------------------------------------------------------------------


class CampaignPhase(StrEnum):
    """The campaign-run phase sequence (Doc C §4 / conventions §3) — the ordered states the M7.3
    state machine advances through. Each phase is owned by a registered ``PhaseHandler`` (M5 owns
    ``REVERSE_PROFILING``/``ICP_CONFIRMED``; M6 ``DISCOVERY``/``SCORING``/``TIER_CHECKPOINT``; M8
    ``DEEP``; M9 ``VERIFICATION``; M12 ``HANDOFF``). Single source of truth for the phase tokens:
    ``obs.spans.CAMPAIGN_PHASES`` is derived from this enum, and the M7 ``campaign_run.phase`` DB
    enum mirrors it (parity-tested in the M7 branch)."""

    REVERSE_PROFILING = "reverse_profiling"
    ICP_CONFIRMED = "icp_confirmed"
    DISCOVERY = "discovery"
    SCORING = "scoring"
    TIER_CHECKPOINT = "tier_checkpoint"  # the human gate (M6.4, interrupt-style)
    DEEP = "deep"
    VERIFICATION = "verification"
    HANDOFF = "handoff"


class PhaseStatus(StrEnum):
    """Outcome of one phase handler run (the ``PhaseResult`` status, ``core.execution``). ``PAUSED``
    is how a phase signals a durable stop the state machine must hold at — the human
    ``TIER_CHECKPOINT`` gate, or a budget graceful-stop (M7.5) — without failing the run."""

    COMPLETED = "completed"
    PAUSED = "paused"
    FAILED = "failed"


class WorkerStatus(StrEnum):
    """Outcome of one aspect/facet worker (the ``WorkerResult`` status, ``core.execution``).
    ``BUDGET_EXCEEDED`` is distinct from ``FAILED`` so the orchestrator can tell "we stopped on the
    cost cap" (a correct, governed outcome) from "the worker errored" (substrate §5/§3)."""

    OK = "ok"
    PARTIAL = "partial"
    FAILED = "failed"
    BUDGET_EXCEEDED = "budget_exceeded"


class IdempotencyScope(StrEnum):
    """The two idempotency-key shapes the durable layer keys on (M7.4): a per-account research
    *step* ``(account_run, entity, field, tier)`` and a per-campaign *phase* ``(campaign_run,
    phase)``. See :mod:`clue_research.core.idempotency` for the pure key-derivation helpers."""

    ACCOUNT_STEP = "account_step"
    CAMPAIGN_PHASE = "campaign_phase"


class BudgetScope(StrEnum):
    """The scope a budget check / charge applies to (M7.5): one account, one pass (Pass A / Pass B),
    or the whole campaign run. The cost dial is fan-out-per-account × accounts-per-pass."""

    ACCOUNT = "account"
    PASS = "pass"
    RUN = "run"


class BudgetVerdict(StrEnum):
    """The result of a pre-spend budget check (M7.5, the ``BudgetDecision`` verdict).
    ``GRACEFUL_STOP`` means a run-level cap is breached: finish the in-flight unit and stop at the
    next checkpoint rather than hard-killing mid-account (a clean, resumable stop)."""

    ALLOW = "allow"
    DENY = "deny"
    GRACEFUL_STOP = "graceful_stop"


class PreSpendVerdict(StrEnum):
    """The pre-spend gate verdict (M9.1, the ``PreSpendDecision`` verdict). The cheapest
    verification is the one that prevents spend on a doomed claim — a request that fails
    schema/identity checks is ``REJECT``ed *before* any resolver call. Named distinctly from
    ``core.modality.GateDecision`` (the M4.6 adapter run/skip gate), a different decision."""

    PASS = "pass"
    REJECT = "reject"


class JudgeVerdict(StrEnum):
    """The faithfulness judge's claim-level entailment verdict (M9.3, the ``JudgeResult`` verdict):
    is ``value_json`` entailed by the claim's ``evidence_span`` (not the wider document)?
    ``UNSUPPORTED``/``CONTRADICTED`` reject the claim and signal re-retrieval; ``PARTIAL`` leaves it
    ``UNVERIFIED`` and flagged."""

    SUPPORTED = "supported"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"
    CONTRADICTED = "contradicted"
