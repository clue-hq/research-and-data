"""Evidence-quality gate: decide whether a static capture is thin enough to
warrant a rendered (Tier-2) re-capture."""

from __future__ import annotations

from dataclasses import dataclass, field

from .parse import ParsedSite
from .snapshot import SiteSnapshot


@dataclass
class GateResult:
    score: float
    escalate: bool
    reasons: list[str] = field(default_factory=list)


def evaluate(snapshot: SiteSnapshot, parsed: ParsedSite) -> GateResult:
    reasons: list[str] = []

    text_len = len(parsed.narrative.text_excerpt or "")
    html_len = len(snapshot.html or "")
    if text_len < 400 and html_len < 20 * 1024:
        reasons.append("client-rendered shell (little text, tiny html)")

    distinct_colors = {c.value for c in parsed.colors}
    if len(distinct_colors) < 4:
        reasons.append("fewer than 4 distinct colors")

    if not any(sample.family for sample in parsed.type_samples):
        reasons.append("no type sample with a font family")

    if len(snapshot.stylesheets) == 0:
        reasons.append("zero stylesheets fetched")

    # Score is a rough evidence-richness signal (higher = better); only the
    # boolean escalate decision is contractual.
    score = min(
        1.0,
        (len(distinct_colors) / 8.0) * 0.4
        + (1.0 if any(s.family for s in parsed.type_samples) else 0.0) * 0.3
        + (min(len(snapshot.stylesheets), 3) / 3.0) * 0.3,
    )

    # Only the static tier can escalate.
    escalate = bool(reasons) and snapshot.tier == "static"
    return GateResult(score=score, escalate=escalate, reasons=reasons)
