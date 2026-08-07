"""Palette ramp derivation (§3.3).

`derive_ramp` builds a 12-stop OKLCH ramp from an anchor hex. Lightness targets
are fixed; chroma is flat-clamped for neutral ramps and scaled per-stop for the
primary ramp; hue is constant. The stop whose lightness target is nearest the
anchor's lightness is replaced with the exact anchor hex so the brand color
appears verbatim in its own ramp.
"""

from __future__ import annotations

from ..colorspace import hex_to_oklch, with_lch

_STOPS = ("50", "100", "200", "300", "400", "500", "600", "700", "800", "900", "950")

_L_TARGETS: dict[str, float] = {
    "50": 0.985,
    "100": 0.955,
    "200": 0.90,
    "300": 0.82,
    "400": 0.72,
    "500": 0.62,
    "600": 0.53,
    "700": 0.45,
    "800": 0.38,
    "900": 0.30,
    "950": 0.22,
}

_C_SCALE: dict[str, float] = {
    "50": 0.15,
    "100": 0.25,
    "200": 0.45,
    "300": 0.65,
    "400": 0.85,
    "500": 1.0,
    "600": 1.0,
    "700": 0.9,
    "800": 0.75,
    "900": 0.6,
    "950": 0.45,
}

_NEUTRAL_MAX_C = 0.02


def derive_ramp(anchor_hex: str, *, neutral: bool, hue_override: float | None = None) -> dict[str, str]:
    anchor_L, anchor_C, anchor_H = hex_to_oklch(anchor_hex)
    hue = hue_override if hue_override is not None else anchor_H

    ramp: dict[str, str] = {}
    for stop in _STOPS:
        L = _L_TARGETS[stop]
        if neutral:
            c = min(anchor_C, _NEUTRAL_MAX_C)
        else:
            c = anchor_C * _C_SCALE[stop]
        ramp[stop] = with_lch(L, c, hue)

    nearest = min(_STOPS, key=lambda stop: abs(_L_TARGETS[stop] - anchor_L))
    ramp[nearest] = anchor_hex
    return ramp


def neutral_hue(page_bg_hex: str) -> float:
    _, c, h = hex_to_oklch(page_bg_hex)
    return h if c > 0.005 else 250.0
