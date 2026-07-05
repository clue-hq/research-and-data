"""Spacing / radius / stroke-width / opacity quantization (§3.5).

Base scales are fixed; evidence only tunes the derived roles (section spacing,
card padding, card/button radius, etc.). Values are emitted as number token
values; the emitter wraps them in mode-value shape. Hard base-5 spacing rhythm
raises an informational LUMI0204 but does not change the base-4 emission.
"""

from __future__ import annotations

from statistics import median

from ..evidence import NumberSample

_SPACE_SCALE = {
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

_OPACITY = {
    "opacity.disabled": 0.4,
    "opacity.subtle": 0.72,
    "opacity.muted": 0.56,
    "opacity.overlay": 0.48,
    "opacity.scrim": 0.64,
    "opacity.emphasis": 0.88,
}


def _snap(value: float, steps: list[float]) -> float:
    return min(steps, key=lambda step: abs(step - value))


def _hinted(samples: list[NumberSample], kind: str, hint: str) -> list[float]:
    return [s.value for s in samples if s.kind == kind and hint in s.role_hints]


def build_spacing(numbers: list[NumberSample]) -> tuple[dict[str, dict], list[dict]]:
    diagnostics: list[dict] = []
    values = dict(_SPACE_SCALE)
    values["space.stack.tight"] = 8.0
    values["space.stack.default"] = 16.0
    values["space.stack.loose"] = 24.0

    section = _hinted(numbers, "spacing", "section")
    values["space.section"] = _snap(median(section), _SPACE_STEPS) if section else 64.0
    page_margin = _hinted(numbers, "spacing", "margin")
    values["space.page.margin"] = _snap(median(page_margin), _SPACE_STEPS) if page_margin else 48.0
    card_padding = _hinted(numbers, "spacing", "padding") or _hinted(numbers, "spacing", "card")
    values["space.card.padding"] = _snap(median(card_padding), _SPACE_STEPS) if card_padding else 24.0

    spacing_all = [s.value for s in numbers if s.kind == "spacing" and s.value > 0]
    if spacing_all and _looks_base5(spacing_all):
        diagnostics.append(
            {"code": "LUMI0204", "severity": "info", "message": "spacing rhythm looks base-5; kept base-4 scale"}
        )
    return _as_px(values), diagnostics


def build_radii(numbers: list[NumberSample]) -> dict[str, dict]:
    values = dict(_RADII_BASE)
    radius_all = [s.value for s in numbers if s.kind == "radius"]
    if radius_all and median(radius_all) >= 20:
        values["radius.xl"] = min(median(radius_all), 32.0)

    card = _hinted(numbers, "radius", "card")
    values["radius.card"] = _snap(median(card), sorted(set(_RADII_BASE.values()) - {9999.0})) if card else 12.0
    button = _hinted(numbers, "radius", "button")
    values["radius.button"] = _snap(median(button), sorted(set(_RADII_BASE.values()) - {9999.0})) if button else 8.0
    badge = _hinted(numbers, "radius", "badge")
    values["radius.badge"] = median(badge) if badge else 9999.0
    return _as_px(values)


def build_strokes() -> dict[str, dict]:
    return _as_px(dict(_STROKE))


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
