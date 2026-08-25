"""W1.5 — ``reference_fidelity`` always lands in the TYPED field.

THE DEFECT (Cursor pilot, `.context/ref-ads-pilot-cursor-report.md` §6c). On a
fast-loop reference turn the author DID judge fidelity — and wrote it as the
prose line ``"reference_fidelity: 2 — dark flat field, …"`` inside
``acceptance_notes`` while the typed ``VisualCritique.reference_fidelity`` field
stayed ``null``. The Apollo pilot stamped the typed field. Same code, two
outcomes, because nothing in the fast loop ever REQUIRED the typed field.

WHY IT DIVERGED. In the fast loop there is no reviewer and no typed writer: the
author writes ``critique.json`` with the generic ``write_file`` tool, and the
only thing shaping it is ``prompts._AUTHOR_SELF_AUDIT_CONTRACT`` — whose JSON
template names ``accepted``/``summary``/``issues``/``acceptance_notes``/
``confidence`` and never named ``reference_fidelity``. The field is
``Optional[...] = None`` on the model, so an omission is valid; the only thing
that punishes it is ``finalize_run``'s RC gate, which refuses an accepted
finalize without ``score >= 2``. So the honest judgment the author actually made
could not reach the gate, and could not reach metrics.

THE FIX IS STRUCTURAL, NOT AN EXHORTATION. This module is the one place that
knows how to get a typed judgment out of a self-audit, and it is applied at the
two seams a critique passes through on a reference turn:

1. the write seam — ``fs_backend.AgentWorkspaceBackend.write`` normalizes any
   ``critique.json`` written on a reference turn, so the durable artifact
   metrics read is always typed;
2. the gate seam — ``tools.substrate.finalize_run`` normalizes the critique it
   was handed before the RC check, so a judgment the author really made cannot
   be lost by a re-serialization on the way to the gate.

WHAT IT DOES AND DOES NOT DO. It promotes a score the author WROTE; it never
invents one. When prose carries a score, that score becomes the typed field.
When nothing carries a score, the typed field is stamped ``score: 0`` with
reasons that say so — 0 is the model's own default, and the RC gate refuses an
accepted finalize at ``score <= 1`` exactly as before. So this can never turn an
unjudged run into an accepted one; it can only stop a judged run from being
refused for a serialization accident, and it makes the field present for
metrics in every case.
"""

from __future__ import annotations

import json
import re
from typing import Any

# The prose forms observed across the pilots, plus the obvious neighbours:
#   "reference_fidelity: 2 — dark flat field, …"
#   "reference_fidelity 2/3"
#   "reference fidelity - 2 / 3 — …"
# The bounded, digit-free run between the label and the score is what keeps this
# from binding the label to some unrelated number later in the sentence.
_FIDELITY_IN_PROSE = re.compile(
    r"reference[ _-]?fidelity\b[^0-9\n]{0,16}([0-3])(?:\s*/\s*3)?",
    re.IGNORECASE,
)

# Leading separators between the score and the reasons the author gave for it.
_REASON_LEAD = re.compile(r"^[\s:,.;\-–—/]*(?:3\b)?[\s:,.;\-–—]*")

UNJUDGED_REASONS = (
    "no explicit reference_fidelity judgment was recorded in this self-audit"
)

CRITIQUE_FILENAME = "critique.json"


def _text_candidates(critique: dict[str, Any]) -> list[str]:
    """Every string in the critique that could be carrying a prose score.

    Ordered by where the pilots actually put it: the acceptance checklist first,
    then the coverage notes, then the summary paragraph.
    """
    candidates: list[str] = []
    for key in ("acceptance_notes", "requirement_coverage_notes"):
        value = critique.get(key)
        if isinstance(value, list):
            candidates.extend(entry for entry in value if isinstance(entry, str))
        elif isinstance(value, str):
            candidates.append(value)
    for key in ("summary", "repair_instruction"):
        value = critique.get(key)
        if isinstance(value, str):
            candidates.append(value)
    return candidates


def _typed_score(critique: dict[str, Any]) -> int | None:
    """The score already present in the typed field, if it is really typed.

    ``bool`` is excluded deliberately: ``isinstance(True, int)`` is true, and the
    RC gate's own ``isinstance(score, int)`` check would read ``True`` as a
    score. A float that happens to be integral (``2.0``, entirely plausible from
    free-form JSON) is NOT accepted here either — it is left for the promotion
    path below to rewrite as a real int, which is what the gate demands.
    """
    fidelity = critique.get("reference_fidelity")
    if not isinstance(fidelity, dict):
        return None
    score = fidelity.get("score")
    if isinstance(score, bool) or not isinstance(score, int):
        return None
    return score


def _coerced_score(critique: dict[str, Any]) -> tuple[int, str] | None:
    """A score the author typed in a shape the gate cannot read (e.g. ``2.0``)."""
    fidelity = critique.get("reference_fidelity")
    if not isinstance(fidelity, dict):
        return None
    score = fidelity.get("score")
    reasons = fidelity.get("reasons")
    reasons_text = reasons if isinstance(reasons, str) else ""
    if isinstance(score, bool):
        return None
    if isinstance(score, float) and float(score).is_integer():
        return int(score), reasons_text
    if isinstance(score, str):
        stripped = score.strip()
        if stripped.isdigit():
            return int(stripped), reasons_text
    return None


def extract_reference_fidelity(critique: dict[str, Any]) -> tuple[int, str] | None:
    """Find a fidelity judgment the author wrote as prose. ``None`` if there is none."""
    for text in _text_candidates(critique):
        match = _FIDELITY_IN_PROSE.search(text)
        if match is None:
            continue
        score = int(match.group(1))
        reasons = _REASON_LEAD.sub("", text[match.end() :]).strip()
        return score, reasons or text.strip()
    return None


def stamp_reference_fidelity(critique: Any) -> Any:
    """Return the critique with a typed ``reference_fidelity``, promoting prose.

    A non-dict is returned untouched — this must never be the thing that breaks a
    turn. An already-typed integer score is left exactly as the author wrote it.
    """
    if not isinstance(critique, dict):
        return critique
    if _typed_score(critique) is not None:
        return critique

    stamped = dict(critique)
    existing = critique.get("reference_fidelity")
    regressed = bool(
        existing.get("regressed_to_house_style") if isinstance(existing, dict) else False
    )

    coerced = _coerced_score(critique)
    promoted = coerced if coerced is not None else extract_reference_fidelity(critique)
    if promoted is None:
        score, reasons = 0, UNJUDGED_REASONS
    else:
        score, reasons = promoted
        reasons = reasons or UNJUDGED_REASONS

    stamped["reference_fidelity"] = {
        "score": max(0, min(3, score)),
        "reasons": reasons,
        "regressed_to_house_style": regressed,
    }
    return stamped


def normalize_critique_document(text: str) -> str | None:
    """Normalize the bytes of a ``critique.json`` document.

    Handles both shapes the file is written in: the bare ``VisualCritique``
    object the fast-loop author writes, and the ``{"status": …, "critique": {…}}``
    envelope ``submit_visual_critique`` writes. Returns ``None`` when there is
    nothing to change or the bytes are not a JSON object — an unparseable
    self-audit is written through verbatim, exactly as it is today, so the
    orchestrator still sees the real failure.
    """
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None

    inner = payload.get("critique")
    if isinstance(inner, dict):
        stamped_inner = stamp_reference_fidelity(inner)
        if stamped_inner is inner:
            return None
        normalized: Any = dict(payload)
        normalized["critique"] = stamped_inner
    else:
        normalized = stamp_reference_fidelity(payload)
        if normalized is payload:
            return None

    return json.dumps(normalized, indent=2)
