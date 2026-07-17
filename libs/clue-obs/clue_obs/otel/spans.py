"""Reserved canonical span names (M0.5).

Later milestones emit the *steps*; M0.5 reserves the *names* so spans are consistent and queryable
from day one. The single most important reservation (Doc D §5): the faithfulness judge and the
appropriateness/use gate are **distinct** spans — "we fabricated something" (accuracy) and "we used
something we shouldn't have" (appropriateness) must be separately measurable.
"""

from __future__ import annotations

from clue_core.enums import CampaignPhase

# --- source layer (M4) ------------------------------------------------------
SPAN_RESOLVE = "resolve"  # base name; resolve spans are tagged by source_tier + source_key

# The config-bounded Source Planner (M4.6): one span per `plan_sources` call, tagged with the ICP,
# the field, the research mode, and how many sources the plan selected — the per-plan substrate the
# cost surface (M7.5) and the learning loop (M13) read alongside the per-source `resolve` spans.
SPAN_SOURCE_PLAN = "source.plan"


def resolve_span(source_key: str) -> str:
    """Span name for a single resolver call (M4), e.g. ``resolve.apollo``."""
    return f"{SPAN_RESOLVE}.{source_key}"


# --- modality adapters (M4.3) -----------------------------------------------
# Each of fetch / adapt / extract is its own span (with cost + latency) so the per-stage cost — in
# particular *transcription* (the ``adapt`` span for audio/video) — is a distinct, queryable cost
# for the M7.5/M13 surfaces (staged-flow §7e). ``pipeline`` wraps the whole fetch→adapt→extract run
# for one source/ref and carries the cost estimate + gate decision + cache-hit.
SPAN_ADAPTER_PIPELINE = "adapter.pipeline"
SPAN_ADAPTER_FETCH = "adapter.fetch"  # transport stage
SPAN_ADAPTER_ADAPT = "adapter.adapt"  # normalization (transcription / OCR / parse) — distinct cost
SPAN_ADAPTER_EXTRACT = "adapter.extract"  # claim-extraction stage

_ADAPTER_STAGES: frozenset[str] = frozenset({"pipeline", "fetch", "adapt", "extract"})


def adapter_span(stage: str, source_key: str) -> str:
    """Span name for one modality-adapter stage (M4.3), e.g. ``adapter.adapt.firecrawl_site``."""
    if stage not in _ADAPTER_STAGES:
        raise ValueError(
            f"unknown adapter stage {stage!r}; expected one of {sorted(_ADAPTER_STAGES)}"
        )
    return f"adapter.{stage}.{source_key}"


# --- llm gateway (M0.4) -----------------------------------------------------
# Every *direct* LLM call through the shared OpenRouter gateway (conventions §2/§4) emits this one
# span, carrying ``model``, token usage, and ``cost_cents`` — so per-call-site model spend is
# queryable from day one. Exa Deep / Parallel Task (M11) are resolvers, NOT gateway calls.
SPAN_LLM_GATEWAY_CALL = "llm.gateway_call"


# --- claim store (M1) -------------------------------------------------------
SPAN_MERGE_CURRENT_VALUE = "merge.current_value"

# --- verification (M9) — accuracy/identity ---------------------------------
# The five M9 gate spans, in pipeline order: the pre-spend entry gate (M9.1), corroboration
# (M9.2), the faithfulness judge (M9.3), identity-binding (M9.4), and freshness (M9.5). All
# distinct from the M10 use-gate span below — accuracy/identity vs appropriateness (Doc D §5).
SPAN_VERIFICATION_PRE_SPEND_GATE = "verification.pre_spend_gate"
SPAN_VERIFICATION_CORROBORATION = "verification.corroboration"
SPAN_VERIFICATION_FAITHFULNESS_JUDGE = "verification.faithfulness_judge"
SPAN_VERIFICATION_IDENTITY_BINDING = "verification.identity_binding"
SPAN_VERIFICATION_FRESHNESS = "verification.freshness"

# --- compliance (M10) — appropriateness/use. DISTINCT from the judge (Doc D §5) ---
SPAN_COMPLIANCE_USE_GATE = "compliance.use_gate"
# Jurisdiction resolution (M10.1): resolve one data-protection regime per contact from its location
# evidence. Its own span so "which regime governs this person, and how confidently" is queryable
# (Doc D §1) — separate from the use gate's per-claim appropriateness decision.
SPAN_COMPLIANCE_JURISDICTION = "compliance.jurisdiction"
# Lawful-basis recording (M10.5): the basis a personal claim is held under (Doc D §4 —
# legitimate_interest for professional B2B; none for sensitive). Its own span so "why are we allowed
# to hold this" is queryable as a distinct compliance event.
SPAN_COMPLIANCE_LAWFUL_BASIS = "compliance.lawful_basis"
# Data-subject rights / erasure (M10.5): one span per access / rectify / erase / object operation —
# the audited "stop holding this" surface (Doc D §4). Tombstoning is append-only supersession, so
# erasure is a queryable, replayable compliance event, distinct from the retention age-out sweep.
SPAN_COMPLIANCE_DSAR = "compliance.dsar"
# Retention age-out sweep (M10.5): the periodic pass that tombstones personal claims past their
# retention horizon (FreshnessState.EXPIRED, surfaced by the M9.5 core.Freshness seam) before the
# merge read — a substrate exclusion, not a use-gate reason (D-EXP).
SPAN_COMPLIANCE_RETENTION_SWEEP = "compliance.retention_sweep"

# --- campaign-run phases (Doc C §4) ----------------------------------------
# Exactly the Doc C §4 / conventions §3 phase sequence (annotations like "(Pass A)"/"(human)" are
# not part of the token). M7 owns the state machine that opens these spans. Derived from the
# canonical ``core.enums.CampaignPhase`` (Beat-0) so the phase tokens have one source of truth —
# the span names, the state-machine enum, and the M7 ``campaign_run.phase`` DB enum cannot drift.
CAMPAIGN_PHASES: tuple[str, ...] = tuple(phase.value for phase in CampaignPhase)


def phase_span(phase: str) -> str:
    """Span name for a campaign-run phase (M7), e.g. ``campaign.phase.discovery``."""
    if phase not in CAMPAIGN_PHASES:
        raise ValueError(f"unknown campaign phase {phase!r}; expected one of {CAMPAIGN_PHASES}")
    return f"campaign.phase.{phase}"
