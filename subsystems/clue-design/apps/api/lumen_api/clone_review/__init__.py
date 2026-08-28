"""The behavioural clone-review gate (clone-fidelity F3.3, founder rulings D-F6 / D-F7).

Four modules, in the order a review runs:

* :mod:`.walk` — what to capture and what was captured. Six classes, always all six, honest
  abstention when one cannot be made. The browser half lives in :mod:`.browser` so everything
  else is exercisable with no chromium.
* :mod:`.compare` — our full-page capture against F0's reference screenshot, measured per band
  wherever the fragment map places one on both sides.
* :mod:`.findings` — what the numbers mean. Durable verdicts about a CLONE (written to the
  fragment's ``degraded`` marker with the gate's own reason codes); everything about the PAGE is
  advice.
* :mod:`.blind` — the founder acceptance artifact: both screenshots, unlabelled, with the answer
  key sealed separately.

The rubric those findings are READ under is not here. It is a shared artifact in the agent
runtime (``lumen_agent/rubrics/``), consumed by the reviewer subagent's prompt and — behind the
web lane's fast-loop flag — by the orchestrator self-reviewing. D-F7 is explicit that review
knowledge never lives inside one agent's private prompt, and it equally must not live inside the
measurement: the flag changes WHO checks, and nothing at all changes WHAT is measured.
"""

from __future__ import annotations

from .blind import (
    BLIND_SCHEMA_VERSION,
    PANEL_LABELS,
    BlindComparison,
    build_blind_side_by_side,
    key_matches,
)
from .compare import (
    COMPARISON_SCHEMA_VERSION,
    ReferenceBand,
    RenderedBand,
    compare_to_reference,
    reference_bands_from_fragments,
)
from .findings import (
    ADVICE_UNAVAILABLE_CODE,
    CRITIQUE_SCHEMA_VERSION,
    BrokenClone,
    CloneReviewCritique,
    PageFinding,
    broken_clones,
    compose_critique,
    console_findings,
    safe_critique,
)
from .walk import (
    BROWSER_UNAVAILABLE_CODE,
    DESKTOP_VIEWPORT,
    MOBILE_VIEWPORT,
    WALK_CLASS_FULL_PAGE,
    WALK_CLASS_HEIGHT_COLLAPSE,
    WALK_CLASS_MOBILE,
    WALK_CLASSES,
    WALK_SCHEMA_VERSION,
    BehaviouralWalk,
    CaptureShot,
    CloneReviewRefused,
    ConsoleEntry,
    SectionMeasurement,
    SectionProbe,
    WalkObservation,
    WalkPlan,
    abstained,
    capture_behavioural_walk,
    measurements_from_probe,
    walk_plan,
)

__all__ = [
    "ADVICE_UNAVAILABLE_CODE",
    "BLIND_SCHEMA_VERSION",
    "BROWSER_UNAVAILABLE_CODE",
    "COMPARISON_SCHEMA_VERSION",
    "CRITIQUE_SCHEMA_VERSION",
    "DESKTOP_VIEWPORT",
    "MOBILE_VIEWPORT",
    "PANEL_LABELS",
    "WALK_CLASSES",
    "WALK_CLASS_FULL_PAGE",
    "WALK_CLASS_HEIGHT_COLLAPSE",
    "WALK_CLASS_MOBILE",
    "WALK_SCHEMA_VERSION",
    "BehaviouralWalk",
    "BlindComparison",
    "BrokenClone",
    "CaptureShot",
    "CloneReviewCritique",
    "CloneReviewRefused",
    "ConsoleEntry",
    "PageFinding",
    "ReferenceBand",
    "RenderedBand",
    "SectionMeasurement",
    "SectionProbe",
    "WalkObservation",
    "WalkPlan",
    "abstained",
    "broken_clones",
    "build_blind_side_by_side",
    "capture_behavioural_walk",
    "compare_to_reference",
    "compose_critique",
    "console_findings",
    "key_matches",
    "measurements_from_probe",
    "reference_bands_from_fragments",
    "safe_critique",
    "walk_plan",
]
