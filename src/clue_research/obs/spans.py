"""Reserved canonical span names (M0.5).

Later milestones emit the *steps*; M0.5 reserves the *names* so spans are consistent and queryable
from day one. The single most important reservation (Doc D §5): the faithfulness judge and the
appropriateness/use gate are **distinct** spans — "we fabricated something" (accuracy) and "we used
something we shouldn't have" (appropriateness) must be separately measurable.
"""

from __future__ import annotations

from clue_research.core.enums import CampaignPhase

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
SPAN_VERIFICATION_CORROBORATION = "verification.corroboration"
SPAN_VERIFICATION_FAITHFULNESS_JUDGE = "verification.faithfulness_judge"
SPAN_VERIFICATION_IDENTITY_BINDING = "verification.identity_binding"

# --- compliance (M10) — appropriateness/use. DISTINCT from the judge (Doc D §5) ---
SPAN_COMPLIANCE_USE_GATE = "compliance.use_gate"

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
