"""Fast-loop tuning (2026-08-24) — the text-collision advisory preflight cannot give.

THE DEFECT THIS EXISTS FOR. Acceptance run #1 shipped a LinkedIn ad whose
headline visibly ran into the body copy beneath it, and every automated surface
in the run called that scene clean: `preflight_design` returned
`has_errors: false` on the offending iteration, and not one of the engine's 477
diagnostic codes has anything to say about two pieces of content colliding.

WHY THE ENGINE CANNOT SEE IT, precisely. `line_height` is a MULTIPLIER model.
`lumen-skia/src/measure.rs` sets SkParagraph's height override, so every line is
made exactly `font_size * line_height` tall and a paragraph's measured height is
`line_count * font_size * line_height` by construction. Set `line_height(1.0)` on
80pt type and the engine measures the box at 160pt for two lines — while the real
Latin line box a font needs is around 1.2em, so the glyphs actually occupy ~192pt
and spill 32pt past the bottom of a box the engine considers a perfect fit.
`LUMV0903` ("text node exceeds available height") therefore CANNOT fire: the
measured height shrank in lockstep with the box. `render_bounds` does not help
either — `layout.rs::render_bounds_for` returns `layout_bounds` verbatim for any
unrotated node and never adds glyph ink.

So the spill is invisible to geometry, invisible to preflight, and lands on
whatever sits below. That is the whole bug, and it is why this module measures
what the engine deliberately does not.

WHAT IS DELIBERATELY NOT HERE. Two checks were considered and cut. A general
sibling-overlap sweep across every node kind would fire on text over a photo and
a badge over a card corner — the two most common intentional overlays in the
craft — so it is restricted to text-versus-text, where overlap is essentially
never on purpose. And a bare "line_height is tight" warning was rejected outright:
tight leading on display type is good typography, not a defect. The defect is
tight leading with no room for the spill, which is why the clearance below the
node is half of every verdict.

ADVISORY, NOT A GATE. Nothing here blocks a compile, fails a preflight or edits a
scene. It appends a line the author reads, in a loop whose §5.2 contract is that
the author looks at its own work. The eyes remain the real check — the author
prompt's LOOK step now names collisions explicitly — because a font whose metrics
differ from the 1.2 assumption below will still fool this arithmetic. An engine
lint over real ascent/descent is the durable fix and is recorded as a follow-up.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

#: The line box a Latin face actually paints, as a multiple of font size.
#: Inter — the engine's own fallback family, and what acceptance run #1 rendered
#: in — sits near 1.21em (ascent + descent + line gap). 1.2 is the long-standing
#: CSS `normal` approximation and is deliberately a ROUND, CONSERVATIVE number
#: rather than a per-face metric: the point is to catch the leading that is
#: obviously too tight for its gap, not to predict the last pixel. Real per-face
#: metrics live in the engine's measurer, which is where the eventual lint
#: belongs; `TextMeasureOutput` does not carry them out to Python today.
NATURAL_LINE_RATIO = 1.2

#: Sub-point differences are rounding noise from a layout solve that reports
#: whole points, not collisions anybody can see.
TOLERANCE_PT = 1.0


def _bounds(node: dict) -> Optional[dict]:
    computed = node.get("computed") or {}
    box = computed.get("layout_bounds")
    if not isinstance(box, dict):
        return None
    try:
        return {
            "x": float(box["x"]),
            "y": float(box["y"]),
            "width": float(box["width"]),
            "height": float(box["height"]),
        }
    except (KeyError, TypeError, ValueError):
        return None


def _text_style(node: dict) -> Optional[dict]:
    """The node's text style, or None when it is not a text node."""
    kind = node.get("kind")
    if not isinstance(kind, dict) or kind.get("kind") != "text":
        return None
    return kind


def _painted_overhang(style: dict, box: dict) -> float:
    """How far this text's ink falls below the box the engine measured.

    Zero whenever the leading is at or above the natural line box, which is the
    common case and the reason this stays quiet on ordinary scenes.
    """
    try:
        font_size = float(style.get("font_size") or 0.0)
        line_height = float(style.get("line_height") or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if font_size <= 0.0 or line_height <= 0.0:
        return 0.0
    if line_height >= NATURAL_LINE_RATIO:
        return 0.0

    # Recover the line count from the engine's own arithmetic rather than by
    # re-wrapping the string: the box IS `lines * font_size * line_height`, so
    # dividing gives back exactly the line count the engine laid out — including
    # the effect of `max_lines`, wrapping and any font substitution.
    measured_line = font_size * line_height
    lines = round(box["height"] / measured_line) if measured_line > 0 else 0
    lines = max(1, int(lines))
    natural_height = lines * font_size * NATURAL_LINE_RATIO
    return max(0.0, natural_height - box["height"])


def _boxes_intersect(a: dict, b: dict) -> bool:
    return (
        a["x"] < b["x"] + b["width"] - TOLERANCE_PT
        and b["x"] < a["x"] + a["width"] - TOLERANCE_PT
        and a["y"] < b["y"] + b["height"] - TOLERANCE_PT
        and b["y"] < a["y"] + a["height"] - TOLERANCE_PT
    )


def _children(node: dict) -> list:
    children = node.get("children")
    return list(children) if isinstance(children, list) else []


def find_text_collisions(scene: Any) -> list[str]:
    """Every text-versus-text collision this scene's own geometry can prove.

    Two findings, both between siblings — nodes that share a parent are the ones
    a layout decision put next to each other, and the ones an author can fix by
    changing that decision:

    1. OVERLAP. Their measured boxes intersect. Only reachable when a parent
       positions its children freely, since an auto-layout parent flows them and
       cannot produce it — which is exactly why it is worth reporting when it
       does happen.
    2. SPILL. One sits above the other and its painted ink, per the module
       docstring's arithmetic, reaches further down than the gap between them.
       This is the acceptance-run defect.

    Returns human-readable lines, empty when the scene is clean. Never raises: a
    malformed or partly-computed scene yields fewer findings, never a failed
    preflight.
    """
    if not isinstance(scene, dict):
        return []
    nodes = scene.get("nodes")
    if not isinstance(nodes, dict):
        return []

    findings: list[str] = []

    # Pages parent their top-level nodes too, so they are scanned as containers.
    containers: Iterable[dict] = [
        value
        for value in list(nodes.values()) + list((scene.get("pages") or {}).values())
        if isinstance(value, dict)
    ]

    for parent in containers:
        siblings = []
        for child_id in _children(parent):
            child = nodes.get(child_id)
            if not isinstance(child, dict):
                continue
            style = _text_style(child)
            box = _bounds(child)
            if style is None or box is None or box["height"] <= 0 or box["width"] <= 0:
                continue
            siblings.append((child_id, style, box))

        for i, (a_id, a_style, a_box) in enumerate(siblings):
            for b_id, _b_style, b_box in siblings[i + 1 :]:
                if _boxes_intersect(a_box, b_box):
                    findings.append(
                        f"text nodes {a_id} and {b_id} overlap: their boxes "
                        f"intersect. Two text blocks on top of each other is "
                        f"almost never intended — separate them or remove one."
                    )
                    continue

                # Which one is above? Only the upper node's ink can fall onto the
                # lower one.
                upper, upper_id, upper_style = a_box, a_id, a_style
                lower, lower_id = b_box, b_id
                if b_box["y"] < a_box["y"]:
                    upper, upper_id, upper_style = b_box, b_id, _b_style
                    lower, lower_id = a_box, a_id

                gap = lower["y"] - (upper["y"] + upper["height"])
                if gap < 0:
                    continue  # not stacked; the overlap branch above owns this
                overhang = _painted_overhang(upper_style, upper)
                if overhang > gap + TOLERANCE_PT:
                    findings.append(
                        f"text node {upper_id} paints about "
                        f"{overhang:.0f}pt below the box the engine measured for "
                        f"it, and only {gap:.0f}pt of clear space separates it "
                        f"from {lower_id}, so the two collide on screen. Its "
                        f"line_height is "
                        f"{float(upper_style.get('line_height') or 0.0):.2f} at "
                        f"{float(upper_style.get('font_size') or 0.0):.0f}pt: the "
                        f"engine measures a line as font_size x line_height, so "
                        f"leading below {NATURAL_LINE_RATIO} shrinks the measured "
                        f"box without shrinking the glyphs. Raise line_height "
                        f"towards {NATURAL_LINE_RATIO}, widen the gap, or cut "
                        f"words. Confirm it in the render."
                    )

    return findings


def collision_advisory(scene: Any) -> Optional[str]:
    """The findings as one block for a tool result, or None when there are none.

    Silence on a clean scene is the point: an advisory that prints something
    every time is an advisory nobody reads by the third round.
    """
    findings = find_text_collisions(scene)
    if not findings:
        return None
    lines = [
        "TEXT COLLISION ADVISORY (geometry-derived, not from the engine's "
        "diagnostics — the engine cannot detect this class):"
    ]
    lines.extend(f"  - {finding}" for finding in findings)
    lines.append(
        "  Verify each one against the render before you fix it, and score it "
        "in your self-audit either way."
    )
    return "\n".join(lines)
