"""Export diagnostic severity policy — BLOCKING vs ADVISORY.

Why this module exists
----------------------
Preflight diagnostics historically had exactly one consequence at the export
gate: any diagnostic with ``severity == "error"`` refused the export outright,
producing no bytes at all. That conflates two genuinely different failures:

* **Blocking** — the render is *impossible*. A missing page, an unresolvable
  token paint, a licence that forbids this export. There is nothing to hand
  the user, so refusing is the only honest answer.
* **Advisory** — the render is *fine*, but the scene trips a policy lint. The
  pixels exist and are correct; something about the document's *metadata* is
  below the bar we would like to hold. Refusing here bricks a document that
  renders perfectly.

The live failure that forced the split (2026-08-24, run ``run_7d4ba182…``):
a scene generated previews cleanly for its entire 43-minute run, finalized as
"succeeded", and then refused *every* export — PNG, SVG, PDF and preview —
because one slot tripped ``LUMV0820``. The scene was never unrenderable. It was
unexportable on a lint, which is a policy decision nobody made deliberately.

The rule
--------
``is_blocking_export_diagnostic`` is **fail-closed**: a diagnostic blocks if it
is an error, *unless* its code is explicitly listed in
:data:`ADVISORY_EXPORT_DIAGNOSTIC_CODES` below. An unrecognised code — a new
one, a typo, a code from a future engine version — blocks. Widening the
advisory set is always a deliberate, reviewed act; nothing becomes advisory by
accident or by omission.

Non-error severities (``warning``, ``advice``) never blocked export and still
never do. This module only ever *narrows* what blocks, never widens it.

Ruling R5 (founder, 2026-08-24) governs where the advisory warnings surface:
**the editor's export menu only.** They are an authoring-surface signal. The
end client who receives the artifact never sees them.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

JsonObject = Dict[str, object]


# ---------------------------------------------------------------------------
# The classification
# ---------------------------------------------------------------------------

#: Diagnostic codes that are error-severity in preflight but must NOT block an
#: export. Every entry needs a written justification answering one question:
#: *can the engine still render correct bytes with this diagnostic present?*
#: If the answer is anything other than a demonstrated yes, the code does not
#: belong here.
ADVISORY_EXPORT_DIAGNOSTIC_CODES: frozenset[str] = frozenset(
    {
        # LUMV0820 — "image-like slot <key> needs an image policy".
        # (crates/lumen-core/src/layout.rs, the ContentType::Image | Logo arm.)
        #
        # Render impact: none, demonstrated. An image slot with no policy lays
        # out and rasterizes exactly as one with the default policy does; the
        # policy governs fit / focal point / print-DPI *intent*, which the
        # renderer falls back on sensibly when absent. The 2026-08-24 run
        # produced preview after preview from a scene carrying this error.
        #
        # Why it was unrepairable, and why that is now fixed: the DSL's only
        # slot constructor is `Slot::text_short`, so every `image … slot(key)`
        # line was born with `image_policy: None` and an instant preflight
        # error the author had no operation to clear. Both halves are now
        # repaired upstream — image-like slots are born with
        # `ImagePolicy::default()`, and `#slot:key image_policy(...)` sets one
        # on an existing slot. It stays advisory here regardless, because
        # documents authored *before* that fix still exist and must not be
        # permanently unexportable.
        "LUMV0820",
    }
)


#: Error-severity codes that do NOT block a person's export from the editor, though the design
#: agent must still clear them before it may finish (founder ruling 2026-10-19). Each says a
#: text does not fit its box. The engine paints overflowing text exactly as the canvas shows it,
#: so the person sees what they will get: a fixed-height "x" between two logos (LUMV0903)
#: refused every PNG export of a design the canvas showed correctly, and the PNG rendered with
#: the gate bypassed matched the canvas. The agent keeps the strict rule because overflow in
#: its own layout is a defect it should fix, not a choice a person made.
EDITOR_EXPORT_ADVISORY_CODES: frozenset[str] = frozenset(
    {
        "LUMV0902",  # non-wrapping text runs past its box's width
        "LUMV0903",  # text is taller than its box
        "LUMV0904",  # text has more lines than its max_lines
    }
)


#: Codes reviewed for advisory status and deliberately LEFT BLOCKING, recorded
#: so the next reader does not have to re-derive the reasoning. This set is
#: documentation; it is not consulted at runtime (the fail-closed default
#: already blocks everything absent from the advisory set).
_REVIEWED_AND_LEFT_BLOCKING: Dict[str, str] = {
    "LUMV0821": (
        "Image focal point outside 0..1. Unlike a missing policy, a present-"
        "but-invalid focal point makes the crop computation meaningless — the "
        "renderer would produce a confidently wrong crop rather than a "
        "sensible default. Bad bytes are worse than no bytes."
    ),
    "LUMV0822": (
        "Image aspect ratio is non-positive. Same reasoning as LUMV0821: a "
        "zero or negative ratio is not a missing opinion, it is an "
        "arithmetically impossible one."
    ),
    "LUMV0823": (
        "Print-sensitive image slot lacks a min_dpi policy. Adjacent to "
        "LUMV0820 and a plausible future candidate, but held back "
        "deliberately: this fires only on print intent, where the whole point "
        "of the gate is to stop a physically unusable artifact reaching a "
        "press. Revisit only with a print stakeholder in the room."
    ),
    "LUMV0810": (
        "Text fixture overflows under an Error overflow policy. The slot's "
        "OWN declared policy says overflow is an error; honoring it is not a "
        "lint. Note the engine already downgrades this to a warning when the "
        "slot's policy sanctions content loss (Clip / Ellipsis / "
        "AskAgentToRepair) — see instance.rs relayout_final — so the "
        "error-severity case is exactly the one the author asked us to block."
    ),
}


# ---------------------------------------------------------------------------
# Predicates
# ---------------------------------------------------------------------------


def is_error_diagnostic(diagnostic: JsonObject) -> bool:
    """True when the engine marked this diagnostic ``error`` severity."""
    return diagnostic.get("severity") == "error"


def is_blocking_export_diagnostic(
    diagnostic: JsonObject, *, editor_export: bool = False
) -> bool:
    """True when this diagnostic must refuse an export.

    Fail-closed: an error-severity diagnostic blocks unless its code is
    explicitly classified advisory. Unknown codes block. `editor_export` is a
    person exporting from the editor, who also gets
    :data:`EDITOR_EXPORT_ADVISORY_CODES` through; the design agent never passes it.
    """
    if not is_error_diagnostic(diagnostic):
        return False
    code = diagnostic.get("code")
    if not isinstance(code, str):
        # A malformed diagnostic we cannot classify is treated as blocking —
        # the same fail-closed posture as an unknown code.
        return True
    if code in ADVISORY_EXPORT_DIAGNOSTIC_CODES:
        return False
    return not (editor_export and code in EDITOR_EXPORT_ADVISORY_CODES)


def is_advisory_export_diagnostic(
    diagnostic: JsonObject, *, editor_export: bool = False
) -> bool:
    """True for an error-severity diagnostic that is a policy lint, not a
    render blocker — the set surfaced to the editor under ruling R5."""
    return is_error_diagnostic(diagnostic) and not is_blocking_export_diagnostic(
        diagnostic, editor_export=editor_export
    )


def has_blocking_export_diagnostics(
    diagnostics: List[JsonObject], *, editor_export: bool = False
) -> bool:
    """The export gate's predicate. Replaces a bare ``has_error_diagnostics``
    check at every point where the consequence is *refusing to produce
    bytes*."""
    return any(
        is_blocking_export_diagnostic(item, editor_export=editor_export)
        for item in diagnostics
    )


def partition_export_diagnostics(
    diagnostics: List[JsonObject], *, editor_export: bool = False
) -> Tuple[List[JsonObject], List[JsonObject]]:
    """Split into ``(blocking, advisory)``.

    Only error-severity diagnostics appear in either list; warnings and advice
    were never export-relevant and are left to the general diagnostics channel.
    """
    blocking: List[JsonObject] = []
    advisory: List[JsonObject] = []
    for item in diagnostics:
        if not is_error_diagnostic(item):
            continue
        if is_blocking_export_diagnostic(item, editor_export=editor_export):
            blocking.append(item)
        else:
            advisory.append(item)
    return blocking, advisory


def draft_verification_note(verification: object) -> str:
    """Describe a retained draft only from runtime evidence, including legacy gaps.

    This is presentation of receipts, not an export or persistence gate. Missing
    metadata cannot certify validity or make historical review feedback current.
    """
    data = verification if isinstance(verification, dict) else {}
    evidence = {
        name: data[name] if isinstance(data.get(name), dict) else {}
        for name in ("preflight", "preview", "review")
    }
    parts = ["Draft retained without design acceptance."]
    preflight = evidence["preflight"]
    if preflight.get("status") != "current" or not isinstance(preflight.get("has_blocking_errors"), bool):
        parts.append("Current draft preflight is unverified.")
    elif preflight["has_blocking_errors"]:
        parts.append("Current draft has blocking preflight errors.")
    if evidence["preview"].get("status") != "current":
        parts.append("Current draft preview is unverified.")
    if evidence["review"].get("status") != "current":
        parts.append("Current draft awaits review.")
    return " ".join(parts)


def export_warning_views(
    diagnostics: List[JsonObject], *, editor_export: bool = False
) -> List[JsonObject]:
    """The ``warnings`` payload carried on an export response.

    Ruling R5: this is an **editor-surface** channel. It rides the API response
    so the export menu can show "exported, with N advisories"; it is never
    stamped into the artifact or shown to an end client.
    """
    _, advisory = partition_export_diagnostics(diagnostics, editor_export=editor_export)
    return [
        {
            "code": item.get("code"),
            "message": item.get("message"),
            "severity": "advisory",
            "engine_severity": item.get("severity"),
            "subject": item.get("subject"),
            "hint": item.get("hint"),
        }
        for item in advisory
    ]
