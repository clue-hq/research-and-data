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


class ClaimProvenanceKind(StrEnum):
    """Who asserted or derived a field value, independent of transport/extraction method.

    ``ExtractionMethod.API`` alone cannot distinguish a literal provider attribute from a
    relationship/category modeled by that provider. Likewise, an LLM or deterministic platform
    rule is not provider evidence. This typed claim-level discriminator preserves that distinction
    without relying on prose in ``evidence_span`` or structure inside ``value_json``.
    """

    PROVIDER_RETURNED = "provider_returned"
    PROVIDER_MODELED = "provider_modeled"
    PLATFORM_INFERRED = "platform_inferred"
    HUMAN_ASSERTED = "human_asserted"


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
    CONVERSATION = "conversation"


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
    """The structurally different kinds of provenance one claim substrate carries.

    * ``DISCOVERY`` — *discovery-provenance* (modes M1/M3): where an entity was found and why it
      matched (the existence-gate evidence). Carries a :class:`DiscoveryProvenance` envelope; it is
      admission evidence, not a field value, so the merge view (M1.2) never treats it as truth.
    * ``FIELD_CLAIM`` — *field-claim provenance* (modes M2/M4): a value + span + tier (plus
      ``identity_binding`` + ``use_class`` for contacts). The default flavor.
    * ``DERIVED`` — a C7 interpretation supported by an immutable ordered set of other claims.
      Its evidence lives in ``claim_derivation`` edges and an entailment verdict, never in a
      fabricated external URL/evidence span. It is excluded from factual ``current_value``."""

    DISCOVERY = "discovery"
    FIELD_CLAIM = "field_claim"
    DERIVED = "derived"


class ResearchStatementKind(StrEnum):
    """Whether a C7 research-view statement is a direct fact or a supported inference.

    This is the presentation/read-contract taxonomy corresponding to direct field claims and C7
    derived claims.
    """

    DIRECT = "direct"
    DERIVED = "derived"


class ResearchAvailability(StrEnum):
    """What the research-view reader may reveal for an item or section."""

    AVAILABLE = "available"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"
    REDACTED = "redacted"
    RESTRICTED = "restricted"


class ResearchConflictState(StrEnum):
    """Whether a statement is clear or requires conflict review."""

    NONE = "none"
    REVIEW_REQUIRED = "review_required"


class DisplayDecision(StrEnum):
    """Whether a resolved research statement may be displayed to this workspace actor."""

    ALLOWED = "allowed"
    DENIED = "denied"
    NOT_APPLICABLE = "not_applicable"


class OutreachDecision(StrEnum):
    """Whether a resolved research statement may drive external outreach."""

    ALLOWED = "allowed"
    DENIED = "denied"
    NOT_APPLICABLE = "not_applicable"


class ResearchDataSpecies(StrEnum):
    """The authoritative species aggregated by C7 without changing their ownership."""

    IDENTITY = "identity"
    EXECUTION = "execution"
    SCORE = "score"
    CLAIM_DERIVATION = "claim_derivation"
    COMMITTEE = "committee"
    COVERAGE = "coverage"
    ACTIVITY = "activity"


class ResearchSectionKind(StrEnum):
    """Semantic account/contact sections; frontend labels and layout remain downstream."""

    IDENTITY = "identity"
    RESEARCH_STATUS = "research_status"
    SUMMARY = "summary"
    ABOUT = "about"
    FIT = "fit"
    INSIGHTS = "insights"
    COMMITTEE = "committee"
    ACTIVITY = "activity"
    PROFESSIONAL_SIGNALS = "professional_signals"
    EVIDENCE = "evidence"
    QUOTES = "quotes"
    BACKGROUND = "background"
    CAREER = "career"
    EDUCATION = "education"
    PUBLICATIONS = "publications"
    AWARDS = "awards"
    PERSONALIZATION = "personalization"
    VALUE_NARRATIVE = "value_narrative"
    FEASIBILITY = "feasibility"
    COVERAGE_GAPS = "coverage_gaps"


class DossierBlockKind(StrEnum):
    """The frozen nine-block compatibility vocabulary from the frontend treaty.

    Blocks are adapters over research-view references, never a canonical dossier document.
    """

    EXECUTIVE_SUMMARY = "executive_summary"
    COMPANY_PROFILE = "company_profile"
    FIT_ASSESSMENT = "fit_assessment"
    SIGNAL = "signal"
    COMMITTEE_MEMBER = "committee_member"
    PERSONALIZATION = "personalization"
    VALUE_NARRATIVE = "value_narrative"
    FEASIBILITY = "feasibility"
    COVERAGE_GAP = "coverage_gap"


class EvidenceActionKind(StrEnum):
    """A safe evidence action descriptor; URLs and storage keys are not contract fields."""

    OPEN_PUBLIC_SOURCE = "open_public_source"
    VIEW_API_PROVENANCE = "view_api_provenance"
    REQUEST_ARTIFACT_PREVIEW = "request_artifact_preview"
    UNAVAILABLE = "unavailable"
    REDACTED = "redacted"


class ResearchSupportRole(StrEnum):
    """Why a supporting claim is allowed to participate in one derived statement."""

    DIRECT_EVIDENCE = "direct_evidence"
    CORROBORATION = "corroboration"
    ACCOUNT_SIGNAL = "account_signal"
    EMPLOYER_CONTEXT = "employer_context"
    CLIENT_CAPABILITY = "client_capability"


class ResearchReferenceRelation(StrEnum):
    """How an owner-held reference relates to the research view's exact subject."""

    SUBJECT = "subject"
    PARENT_ACCOUNT = "parent_account"
    COMMITTEE_MEMBER = "committee_member"


class EntailmentVerdictKind(StrEnum):
    """The C7 derived-claim judge result. Errors fail closed and never promote."""

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    ERROR = "error"


class EntailmentReasonCode(StrEnum):
    """Bounded audit reasons for entailment; raw model rationale is not persisted."""

    ENTAILED = "entailed"
    MISSING_SUPPORT = "missing_support"
    SUBJECT_MISMATCH = "subject_mismatch"
    PRODUCT_MISMATCH = "product_mismatch"
    NOT_ENTAILED = "not_entailed"
    CONTRADICTED = "contradicted"
    MALFORMED_RESPONSE = "malformed_response"
    MODEL_ERROR = "model_error"


class FreshnessState(StrEnum):
    """Whether the claim that won a merge satisfies its field's freshness TTL (substrate §1/§6).
    Stale winners are never dropped — they are returned ``STALE`` so the scoring layer can discount
    them and a refresh can be scheduled (the merge surfaces, never silently drops, staleness).

    ``EXPIRED`` is the *retention age-out* disposition (M9.5 / Doc D §4): a claim past its retention
    horizon — distinct from merely past its freshness TTL — surfaced to M10.5 for personal-claim
    age-out and never allowed to win a merge. The M1.2 merge view sets ``FRESH``/``STALE`` (the
    winning claim's freshness relative to now); the M9.5 freshness engine is what assigns
    ``EXPIRED``. Kept orthogonal to ``VerificationStatus`` (the accuracy verdict): going stale or
    expired never erases a claim's accuracy verdict."""

    FRESH = "fresh"
    STALE = "stale"
    EXPIRED = "expired"


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
      partially reusable across clients that amortizes cost; carries no ``workspace_id``.
    * ``TENANT_PRIVATE`` — client-specific scoring, CRM-imported facts, client-knowledge-derived
      claims, and any contact ``facet`` / personal / resonance data; strictly tenant-isolated and so
      always carries a ``workspace_id``.

    The reuse-class is *derived from policy at write* (the classifier maps ``(field_key namespace,
    extraction_method, source_tier) → scope``) and stored for fast filtering; the tenant-scoped read
    returns public-footprint (any tenant) ∪ this tenant's private, and never another tenant's
    private. A claim is ``TENANT_PRIVATE`` iff it has a ``workspace_id``."""

    PUBLIC_FOOTPRINT = "public_footprint"
    TENANT_PRIVATE = "tenant_private"


class ResearchScope(StrEnum):
    """Field **species** — is this field's value a world-fact or a project-relative answer?
    (contract-delta 2026-08-08, FI-2 slice 0; spec ``FI-2-workspace-account-layer.md`` §4/§5.)

    * ``PROJECT_NEUTRAL`` — the value is a fact about the account/contact in the world, invariant
      to which client product, ICP, or campaign is asking. Readable in every project lens; spend is
      TTL-governed (fresh ⇒ skip, and the refresh benefits every project).
    * ``PROJECT_RELATIVE`` — the value is defined *relative to* an ICP/product/campaign (a score, a
      targeting decision, an argument). Read through the run-lineage filter, always researched per
      project (never skipped because another project's answer is fresh), and superseded only within
      its own project.

    Orthogonal to :class:`ReuseScope`: species drives economics and lens membership, never privacy
    — a neutral fact still respects every governance gate (§5.3). Persisted as ``text`` (not a DB
    enum) on ``field_definition`` / ``workspace_field_definition`` behind a named CHECK."""

    PROJECT_NEUTRAL = "project_neutral"
    PROJECT_RELATIVE = "project_relative"


class ProductScopePolicy(StrEnum):
    """Whether claims for one field may carry a spine ``product_id``.

    This is independent of :class:`ReuseScope` (privacy/tenant reuse) and
    :class:`ResearchScope` (project-neutral versus project-relative economics).

    * ``FORBIDDEN`` — claims must have ``product_id IS NULL``;
    * ``REQUIRED`` — claims must carry one exact ``product_id``;
    * ``OPTIONAL`` — both forms are legitimate, for compatibility and dual-scope marker fields.
    """

    FORBIDDEN = "forbidden"
    REQUIRED = "required"
    OPTIONAL = "optional"


class Persona(StrEnum):
    """Buying-committee personas/roles (conventions §3)."""

    CHAMPION = "champion"
    ECONOMIC_BUYER = "economic_buyer"
    TECHNICAL_EVALUATOR = "technical_evaluator"
    BLOCKER = "blocker"
    # Appended 2026-09-07 (ARV2 master plan D8): the person who operates the tool daily. Not a DB
    # enum — the value lives in registered value schemas; migration arv2_d1 rewrites stored rows.
    USER = "user"


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
    # M13.3: a new ICP-spec version written by promoting a learning-loop scoring-rubric reweight (so
    # "which versions came from the feedback loop" is queryable). Appended last — the DB enum's
    # ALTER ... ADD VALUE appends, keeping enum-parity.
    FEEDBACK_REWEIGHT = "feedback_reweight"


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
# branches fork against. (M7's ``project_run`` / ``account_run`` lifecycle enums are NOT here —
# they are table-column taxonomies internal to ``durable``, added by the M7 branch with its tables.)
# ---------------------------------------------------------------------------


class ProjectPhase(StrEnum):
    """The project-run phase sequence (Doc C §4 / conventions §3) — the ordered states the M7.3
    state machine advances through. Each phase is owned by a registered ``PhaseHandler`` (M5 owns
    ``REVERSE_PROFILING``/``ICP_CONFIRMED``; M6 ``DISCOVERY``/``SCORING``/``TIER_CHECKPOINT``; M8
    ``DEEP``; M9 ``VERIFICATION``; M13 ``REVIEW`` — the Tier-1 human gate; M12 ``HANDOFF``). Single
    source of truth for the phase tokens:
    ``obs.spans.PROJECT_PHASES`` is derived from this enum, and the M7 ``project_run.phase`` DB
    enum mirrors it (parity-tested in the M7 branch)."""

    REVERSE_PROFILING = "reverse_profiling"
    ICP_CONFIRMED = "icp_confirmed"
    DISCOVERY = "discovery"
    SCORING = "scoring"
    TIER_CHECKPOINT = "tier_checkpoint"  # the human gate (M6.4, interrupt-style)
    DEEP = "deep"
    VERIFICATION = "verification"
    REVIEW = "review"  # the Tier-1 human review gate (M13.1, interrupt-style via AWAITING_INPUT)
    HANDOFF = "handoff"


class PhaseStatus(StrEnum):
    """Outcome of one phase handler run (the ``PhaseResult`` status, ``core.execution``). ``PAUSED``
    is how a phase signals a durable stop the state machine must hold at — the human
    ``TIER_CHECKPOINT`` gate, or a budget graceful-stop (M7.5) — without failing the run."""

    COMPLETED = "completed"
    WAITING_EXTERNAL = "waiting_external"
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
    *step* ``(account_run, entity, field, tier)`` and a per-run *phase* ``(project_run, phase)``.
    See :mod:`clue_core.idempotency` for the pure key-derivation helpers.

    The §1a stage-2 rename flipped the member NAME (``CAMPAIGN_PHASE`` → ``PROJECT_PHASE``); the
    value string is durable ledger data, not vocabulary — see the pin below."""

    ACCOUNT_STEP = "account_step"
    # value frozen: baked into ledger keys at rest — never rename; see PB-rename playbook §4.5
    PROJECT_PHASE = "campaign_phase"


class BudgetScope(StrEnum):
    """The scope a budget check / charge applies to (M7.5): one account, one pass (Pass A / Pass B),
    or the whole project run. The cost dial is fan-out-per-account × accounts-per-pass."""

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


class PreSpendKind(StrEnum):
    """The two shapes of a pre-spend request (M9.1, Option C).

    ``FIELD`` (the original, default) is a single ``(entity, field, tier)`` spend — fill one claim;
    it carries a ``field_key``. ``ENUMERATION`` governs a *discovery* spend that fans out over a
    ``scope`` to enumerate members that do not yet exist as entities (committee people-discovery:
    "find the people AT this account") — so it carries a ``scope``, not a ``field_key`` (there is no
    single field being filled). Mirrored by the ``pre_spend_kind`` DB enum (parity-tested)."""

    FIELD = "field"
    ENUMERATION = "enumeration"


class EnumerationScope(StrEnum):
    """The scope an ``ENUMERATION`` pre-spend fans out over (M9.1, Option C). ``COMMITTEE`` — the
    buying-committee people-discovery within a known account (M8.3 ``discover_committee``) — is the
    only scope today; account-channel discovery is M6's ``DiscoveryChannel`` (a different seam), not
    an enumeration spend. Mirrored by the ``enumeration_scope`` DB enum (parity-tested)."""

    COMMITTEE = "committee"


class JudgeVerdict(StrEnum):
    """The faithfulness judge's claim-level entailment verdict (M9.3, the ``JudgeResult`` verdict):
    is ``value_json`` entailed by the claim's ``evidence_span`` (not the wider document)?
    ``UNSUPPORTED``/``CONTRADICTED`` reject the claim and signal re-retrieval; ``PARTIAL`` leaves it
    ``UNVERIFIED`` and flagged."""

    SUPPORTED = "supported"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"
    CONTRADICTED = "contradicted"


class UseReason(StrEnum):
    """Why the appropriateness/use gate (M10.3, Doc D §3/§5) reached its ``usable_for_outreach``
    verdict on a personal claim — the closed reason vocabulary M10 emits and M12/M13 switch on.
    Mirrors the ``JudgeVerdict``/``PreSpendVerdict`` pattern so the cross-package boundary carries a
    *typed* verdict, never free text (the same latent-drift class as the pre-A3 split tenancy-id
    naming and the strong-binding-share metric in the backlog).

    Note the deliberate *absence* of an ``objected`` member: a data-subject objection (GDPR Art. 21)
    is handled at the **merge/eligibility substrate** (M10.5 tombstones the contact's claims before
    the merge read), not in the per-claim ``UseGate.evaluate`` — so an objected claim never reaches
    the gate to be given a reason. Likewise retention age-out (``FreshnessState.EXPIRED``) is a
    substrate exclusion, not a use reason. These reasons are purely the appropriateness axis."""

    ALLOWED = "allowed"
    SENSITIVE_LOCKED = "sensitive_locked"
    USE_CLASS_DISALLOWED_FOR_REGIME = "use_class_disallowed_for_regime"


# ---------------------------------------------------------------------------
# M13.1 review-surface taxonomies.
#
# These cross the package boundary — the ``core.review.ReviewSurface`` contract (which the
# ``review`` impl and the ``api`` composition root both bind to) switches on ``ReviewAction`` /
# ``ReviewSessionStatus``, so they live here with every other closed enum, not in ``review`` (the
# same reason the Beat-0 execution/verification enums above live in ``core``). Each is mirrored by a
# Postgres ``ENUM`` (``review_action_kind`` / ``review_session_status`` / ``review_reject_reason``)
# created in the M13.1 migration; a per-enum parity test asserts the Python members and DB labels
# stay aligned. (The *disposition* taxonomy is M13.2's and lives in the ``review`` package — its
# producers/consumers are all inside ``review`` and it crosses no package boundary into ``core``.)
# ---------------------------------------------------------------------------


class ReviewAction(StrEnum):
    """A Tier-1 reviewer's per-claim action (M13.1, substrate §10).

    * ``APPROVE`` — records assent; the claim flows to the handoff unchanged.
    * ``CORRECT`` — the reviewer supplies a corrected value; written as a new ``human``-extraction
      claim that *supersedes* the original (append-only, never an in-place edit), so
      ``current_value`` returns the human-tier value.
    * ``REJECT`` — excludes the claim from the finalized handoff; written as a ``REJECTED``
      superseding claim so the merge drops it (an empty field is a correct output, conventions §5).
    """

    APPROVE = "approve"
    CORRECT = "correct"
    REJECT = "reject"


class ReviewSessionStatus(StrEnum):
    """Lifecycle of a Tier-1 review session over one ``account_handoff`` candidate (M13.1).

    A session opens at the ``REVIEW`` phase per ready high-tier account; ``FINALIZED`` is what gates
    that account's handoff (per-account session finalization); ``ABANDONED`` is a session closed
    without finalizing (it does not unblock the handoff)."""

    OPEN = "open"
    FINALIZED = "finalized"
    ABANDONED = "abandoned"


class ReviewRejectReason(StrEnum):
    """Why a reviewer rejected a claim (M13.1, the ``review_action.reason_code`` vocabulary). Closed
    so the disposition/learning loop (M13.2/M13.3) can switch on a typed reason, never free text."""

    INACCURATE = "inaccurate"
    OUTDATED = "outdated"
    MISATTRIBUTED = "misattributed"
    INAPPROPRIATE = "inappropriate"
    UNSUPPORTED = "unsupported"
    OTHER = "other"


class ConfigRevisionTarget(StrEnum):
    """What an M13.3 learning-loop ``config_revision`` reweights — a source profile (M4.6) or the
    fit/intent scoring rubric (M3.4). The two reweight targets the one disposition signal drives
    (staged-flow §9). The loop emits versioned revisions; the engine reads the existing config
    stores, never ``config_revision`` (the ledger)."""

    SOURCE_PROFILE = "source_profile"
    SCORING_RUBRIC = "scoring_rubric"


class ConfigRevisionStatus(StrEnum):
    """An M13.3 config_revision's lifecycle: ``PROPOSED`` by the loop, then ``PROMOTED`` (written
    to the versioned store, active for new runs) or ``REJECTED`` (never applied). Reweighting only
    ever *proposes*; promotion is a separate step (substrate §9 — never autonomous mutation)."""

    PROPOSED = "proposed"
    PROMOTED = "promoted"
    REJECTED = "rejected"


class PromotionMode(StrEnum):
    """How an M13.3 revision promotion is authorized: ``AUTO`` (an in-bounds move the loop may
    promote itself) or ``HUMAN`` (an out-of-bounds move needing explicit approval). Policy is data —
    the bound is configurable; the mode records which gate cleared the promotion."""

    AUTO = "auto"
    HUMAN = "human"
