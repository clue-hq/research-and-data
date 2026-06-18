"""Reserved canonical span names (M0.5).

Later milestones emit the *steps*; M0.5 reserves the *names* so spans are consistent and queryable
from day one. The single most important reservation (Doc D §5): the faithfulness judge and the
appropriateness/use gate are **distinct** spans — "we fabricated something" (accuracy) and "we used
something we shouldn't have" (appropriateness) must be separately measurable.
"""

from __future__ import annotations

# --- source layer (M4) ------------------------------------------------------
SPAN_RESOLVE = "resolve"  # base name; resolve spans are tagged by source_tier + source_key


def resolve_span(source_key: str) -> str:
    """Span name for a single resolver call (M4), e.g. ``resolve.apollo``."""
    return f"{SPAN_RESOLVE}.{source_key}"


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
# not part of the token). M7 owns the state machine that opens these spans.
CAMPAIGN_PHASES: tuple[str, ...] = (
    "reverse_profiling",
    "icp_confirmed",
    "discovery",
    "scoring",
    "tier_checkpoint",
    "deep",
    "verification",
    "handoff",
)


def phase_span(phase: str) -> str:
    """Span name for a campaign-run phase (M7), e.g. ``campaign.phase.discovery``."""
    if phase not in CAMPAIGN_PHASES:
        raise ValueError(f"unknown campaign phase {phase!r}; expected one of {CAMPAIGN_PHASES}")
    return f"campaign.phase.{phase}"
