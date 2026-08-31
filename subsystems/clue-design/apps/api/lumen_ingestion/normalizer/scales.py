"""Spacing / radius / stroke-width / opacity scales (§3.5).

The base scales below are the platform's FALLBACK rhythm. Where the capture
measured the brand's own geometry (design-brief slice 2), the measured clusters
claim the steps they can honestly fill and the rest keep the base value —
so a token is either `website:<page> :: <what was measured>` at
`MEASURED_CONFIDENCE`, or the old `derived:<scale>` at 0.6. Nothing in between,
and nothing fabricated to fill a gap.

Each builder returns `(values, provenance)`: `provenance` maps a token path to
the evidence pointer that measured it, and is EMPTY for a site (or a PDF, or an
upload) that measured nothing — which is exactly today's behaviour.
Hard base-5 spacing rhythm still raises an informational LUMI0204.
"""

from __future__ import annotations

from statistics import median

from ..evidence import NumberSample
from .geometry import (
    NumberCluster,
    assign_steps,
    hinted_cluster,
    pill_cluster,
    scale_clusters,
)

_SPACE_SCALE = {
    # Semantic steps: the styles compiler's vocabulary (two producers, one
    # contract — same rule as the type.size ramp; probed 2026-07-07).
    "space.xs": 4.0,
    "space.sm": 8.0,
    "space.md": 12.0,
    "space.lg": 16.0,
    "space.xl": 24.0,
    "space.0": 0.0,
    "space.1": 4.0,
    "space.2": 8.0,
    "space.3": 12.0,
    "space.4": 16.0,
    "space.5": 20.0,
    "space.6": 24.0,
    "space.8": 32.0,
    "space.10": 40.0,
    "space.12": 48.0,
    "space.16": 64.0,
}
_SPACE_STEPS = sorted(v for v in _SPACE_SCALE.values() if v > 0)

_RADII_BASE = {
    "radius.none": 0.0,
    "radius.xs": 2.0,
    "radius.sm": 4.0,
    "radius.md": 8.0,
    "radius.lg": 12.0,
    "radius.xl": 16.0,
    "radius.full": 9999.0,
}
# The ladder measurement may claim; `none` is structural and `full` is claimed
# only by an actual pill measurement.
_RADII_LADDER = {
    key: value for key, value in _RADII_BASE.items() if key not in ("radius.none", "radius.full")
}

_STROKE = {
    "stroke.width.hairline": 0.5,
    "stroke.width.thin": 1.0,
    "stroke.width.default": 1.0,
    "stroke.width.firm": 2.0,
    "stroke.width.bold": 3.0,
    "stroke.width.divider": 1.0,
    "stroke.width.card": 1.0,
    "stroke.width.focus": 2.0,
}
# The generic weight ladder measurement may claim; the three semantic roles
# below it are claimed by their own hinted clusters instead.
_STROKE_LADDER = {
    key: value
    for key, value in _STROKE.items()
    if key not in ("stroke.width.divider", "stroke.width.card", "stroke.width.focus")
}

_OPACITY = {
    "opacity.disabled": 0.4,
    "opacity.subtle": 0.72,
    "opacity.muted": 0.56,
    "opacity.overlay": 0.48,
    "opacity.scrim": 0.64,
    "opacity.emphasis": 0.88,
}

ScaleResult = tuple[dict[str, dict], dict[str, str]]


def _snap(value: float, steps: list[float]) -> float:
    return min(steps, key=lambda step: abs(step - value))


def _hinted(samples: list[NumberSample], kind: str, hint: str) -> list[float]:
    return [s.value for s in samples if s.kind == kind and hint in s.role_hints]


_SPACING_TOLERANCE = {"abs_tolerance": 2.0, "rel_tolerance": 0.04}
_RADIUS_TOLERANCE = {"abs_tolerance": 1.0, "rel_tolerance": 0.15}
_STROKE_TOLERANCE = {"abs_tolerance": 0.25, "rel_tolerance": 0.1}

# The LAYOUT spacing family — what the `space.N` ladder is allowed to be built
# from. Component padding is excluded by construction (it is hinted by its
# surface class only), so a button's inner inset can never become a rung of the
# page's scale.
_LAYOUT_HINTS = ("section", "gap")


def _layout_clusters(numbers: list[NumberSample]):
    return scale_clusters(
        numbers, "spacing", any_hints=_LAYOUT_HINTS, **_SPACING_TOLERANCE
    )


def _spacing_role(numbers: list[NumberSample], *hints: str):
    return hinted_cluster(numbers, "spacing", *hints, **_SPACING_TOLERANCE)


def _claim(
    values: dict[str, float],
    provenance: dict[str, str],
    path: str,
    cluster: NumberCluster | None,
) -> bool:
    """Let one measured cluster claim one token path. False when there is none."""
    if cluster is None:
        return False
    values[path] = cluster.value
    provenance[path] = cluster.provenance
    return True


def build_spacing(numbers: list[NumberSample]) -> tuple[dict[str, dict], dict[str, str], list[dict]]:
    diagnostics: list[dict] = []
    values = dict(_SPACE_SCALE)
    values["space.stack.tight"] = 8.0
    values["space.stack.default"] = 16.0
    values["space.stack.loose"] = 24.0
    provenance: dict[str, str] = {}

    # The measured ladder: the brand's LAYOUT rhythm — section gaps, section
    # padding, container gaps — seated in ascending order.
    ladder = {path: step for path, step in _SPACE_SCALE.items() if step > 0}
    for path, cluster in assign_steps(ladder, _layout_clusters(numbers)).items():
        _claim(values, provenance, path, cluster)

    # Semantic roles, measured where hinted; the old snapped medians otherwise.
    section = _spacing_role(numbers, "section")
    if not _claim(values, provenance, "space.section", section):
        hinted = _hinted(numbers, "spacing", "section")
        values["space.section"] = _snap(median(hinted), _SPACE_STEPS) if hinted else 64.0

    margin = _spacing_role(numbers, "margin")
    if not _claim(values, provenance, "space.page.margin", margin):
        hinted = _hinted(numbers, "spacing", "margin")
        values["space.page.margin"] = _snap(median(hinted), _SPACE_STEPS) if hinted else 48.0

    # A card's OWN padding (both hints), falling back to any surface's padding.
    card = _spacing_role(numbers, "padding", "card") or _spacing_role(numbers, "padding")
    if not _claim(values, provenance, "space.card.padding", card):
        hinted = _hinted(numbers, "spacing", "card") or _hinted(numbers, "spacing", "padding")
        values["space.card.padding"] = _snap(median(hinted), _SPACE_STEPS) if hinted else 24.0

    spacing_all = [s.value for s in numbers if s.kind == "spacing" and s.value > 0]
    if spacing_all and _looks_base5(spacing_all):
        diagnostics.append(
            {"code": "LUMI0204", "severity": "info", "message": "spacing rhythm looks base-5; kept base-4 scale"}
        )
    return _as_px(values), provenance, diagnostics


def build_radii(numbers: list[NumberSample]) -> ScaleResult:
    values = dict(_RADII_BASE)
    provenance: dict[str, str] = {}

    ladder_clusters = scale_clusters(numbers, "radius", **_RADIUS_TOLERANCE)
    for path, cluster in assign_steps(_RADII_LADDER, ladder_clusters).items():
        _claim(values, provenance, path, cluster)

    # A measured pill confirms radius.full rather than assuming it.
    _claim(values, provenance, "radius.full", pill_cluster(numbers))

    non_pill = sorted(set(_RADII_BASE.values()) - {9999.0})
    for path, hint, fallback in (
        ("radius.card", "card", 12.0),
        ("radius.button", "button", 8.0),
    ):
        cluster = hinted_cluster(numbers, "radius", hint, **_RADIUS_TOLERANCE)
        if cluster is not None and cluster.value >= 9999.0:
            cluster = None  # a pill button is radius.full, not a scale step
        if not _claim(values, provenance, path, cluster):
            hinted = _hinted(numbers, "radius", hint)
            values[path] = _snap(median(hinted), non_pill) if hinted else fallback

    badge = hinted_cluster(numbers, "radius", "badge", **_RADIUS_TOLERANCE)
    if not _claim(values, provenance, "radius.badge", badge):
        hinted = _hinted(numbers, "radius", "badge")
        values["radius.badge"] = median(hinted) if hinted else 9999.0

    return _as_px(values), provenance


def build_strokes(numbers: list[NumberSample] | None = None) -> ScaleResult:
    numbers = numbers or []
    values = dict(_STROKE)
    provenance: dict[str, str] = {}

    for path, cluster in assign_steps(
        _STROKE_LADDER,
        scale_clusters(numbers, "stroke_width", **_STROKE_TOLERANCE),
    ).items():
        _claim(values, provenance, path, cluster)

    for path, hint in (
        ("stroke.width.divider", "divider"),
        ("stroke.width.card", "card"),
        ("stroke.width.focus", "focus"),
    ):
        _claim(
            values,
            provenance,
            path,
            hinted_cluster(numbers, "stroke_width", hint, **_STROKE_TOLERANCE),
        )

    return _as_px(values), provenance


def build_opacity() -> dict[str, dict]:
    return {path: _number(value, "ratio") for path, value in _OPACITY.items()}


def _as_px(values: dict[str, float]) -> dict[str, dict]:
    return {path: _number(value, "px") for path, value in values.items()}


def _number(value: float, unit: str) -> dict:
    return {"kind": "number", "value": float(value), "unit": unit}


def _looks_base5(values: list[float]) -> bool:
    positive = [v for v in values if v > 0]
    if not positive:
        return False
    base5 = sum(1 for v in positive if abs(v % 5) < 0.5 and abs(v % 4) >= 0.5)
    return base5 >= max(2, len(positive) // 2 + 1)
