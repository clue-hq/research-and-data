"""CSS Color 4 colour functions → the sRGB hex Chromium paints (review finding S6-3).

Tailwind v4 and shadcn/ui write every colour as `oklch()`; other sites use `lab()`, `lch()`,
`hwb()` and `color(display-p3 …)`. The browser paints each by converting to sRGB and clipping any
channel outside 0..1 (it does not reduce chroma), so this module does the same — checked against
Chromium 149's painted pixels (tests/test_css_color4.py). Channels only: the alpha slot is the
caller's (`capture.parse.parse_color_value` reads it, following `var()`).
"""

from __future__ import annotations

import math
import re

from .colorspace import _linear_to_srgb, _srgb_to_linear, oklab_to_linear

COLOR4_FUNCTIONS = ("oklch", "oklab", "lch", "lab", "hwb", "color")

# CSS Color 4 sample-code matrices (https://www.w3.org/TR/css-color-4/#color-conversion-code).
_XYZ_D65_TO_LINEAR_SRGB = (
    (3.2409699419045226, -1.537383177570094, -0.4986107602930034),
    (-0.9692436362808796, 1.8759675015077202, 0.04155505740717559),
    (0.05563007969699366, -0.20397695888897652, 1.0569715142428786),
)
_D50_TO_D65 = (
    (0.955473421488075, -0.02309845494876471, 0.06325924320057072),
    (-0.0283697093338637, 1.0099953980813041, 0.021041441191917323),
    (0.012314014864481998, -0.020507649298898964, 1.330365926242124),
)
_LINEAR_P3_TO_XYZ_D65 = (
    (0.4865709486482162, 0.26566769316909306, 0.1982172852343625),
    (0.2289745640697488, 0.6917385218365064, 0.079286914093745),
    (0.0, 0.04511338185890264, 1.043944368900976),
)
_D50_WHITE = (0.3457 / 0.3585, 1.0, (1.0 - 0.3457 - 0.3585) / 0.3585)
_HUE_UNITS = {"deg": 1.0, "grad": 0.9, "rad": 180.0 / math.pi, "turn": 360.0}


def _mul(matrix, vector) -> tuple[float, float, float]:
    return tuple(sum(matrix[row][col] * vector[col] for col in range(3)) for row in range(3))  # type: ignore[return-value]


# The CSS <number> grammar, ASCII only. Python's float() is looser: it reads `1_0`, `nan`, `inf`
# and non-ASCII digits, none of which a browser accepts — and a colour the browser refuses must be
# refused here, never turned into a made-up hex.
_CSS_NUMBER = re.compile(r"[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", re.ASCII)


def _css_number(text: str, token: str) -> float:
    """`text` read as a CSS <number>. Raises ValueError for anything else."""
    if _CSS_NUMBER.fullmatch(text) is None:
        raise ValueError(token)
    return _finite(float(text), token)


def _finite(value: float, token: str) -> float:
    if not math.isfinite(value):
        raise ValueError(token)
    return value


def _number(token: str, percent_of: float) -> float:
    """A channel: `none` is 0, a percentage is a share of `percent_of`. Raises ValueError."""
    text = token.strip().lower()
    if text == "none":
        return 0.0
    if text.endswith("%"):
        return _finite(_css_number(text[:-1], token) / 100.0 * percent_of, token)
    return _css_number(text, token)


def _hue(token: str) -> float:
    """A hue in degrees: `none` is 0, a bare number is degrees. Raises ValueError."""
    text = token.strip().lower()
    if text == "none":
        return 0.0
    for unit, factor in _HUE_UNITS.items():
        if text.endswith(unit):
            return _finite(_css_number(text[: -len(unit)], token) * factor, token)
    return _css_number(text, token)


def _channel(value: float) -> int:
    return max(0, min(255, round(max(0.0, min(1.0, value)) * 255)))


def _srgb_hex(rgb) -> str:
    return "#%02X%02X%02X" % tuple(_channel(c) for c in rgb)


def _linear_hex(linear) -> str:
    return _srgb_hex([_linear_to_srgb(max(0.0, min(1.0, c))) for c in linear])


def _lab_to_linear(lightness: float, a: float, b: float) -> tuple[float, float, float]:
    kappa, epsilon = 24389 / 27, 216 / 24389
    f1 = (lightness + 16) / 116
    f0, f2 = a / 500 + f1, f1 - b / 200
    x = f0 ** 3 if f0 ** 3 > epsilon else (116 * f0 - 16) / kappa
    y = f1 ** 3 if lightness > kappa * epsilon else lightness / kappa
    z = f2 ** 3 if f2 ** 3 > epsilon else (116 * f2 - 16) / kappa
    xyz_d50 = (x * _D50_WHITE[0], y * _D50_WHITE[1], z * _D50_WHITE[2])
    return _mul(_XYZ_D65_TO_LINEAR_SRGB, _mul(_D50_TO_D65, xyz_d50))


def _hwb_hex(hue: float, white: float, black: float) -> str:
    if white + black >= 1:
        grey = white / (white + black)
        return _srgb_hex((grey, grey, grey))
    def channel(n: int) -> float:
        k = (n + hue / 30) % 12
        pure = 0.5 - 0.5 * max(-1.0, min(k - 3, 9 - k, 1.0))
        return pure * (1 - white - black) + white
    return _srgb_hex((channel(0), channel(8), channel(4)))


def color4_to_hex(name: str, parts: list[str]) -> str | None:
    """`#RRGGBB` for the channels of one CSS Color 4 function, or None when they are unreadable or
    name a colour space we do not convert."""
    try:
        if name == "color":
            if len(parts) != 4:  # a colour space and exactly three channels
                return None
            space, values = parts[0].strip().lower(), [_number(p, 1.0) for p in parts[1:4]]
            if space == "srgb":
                return _srgb_hex(values)
            if space == "srgb-linear":
                return _linear_hex(values)
            if space == "display-p3":
                linear = [math.copysign(_srgb_to_linear(abs(v)), v) for v in values]
                xyz = _mul(_LINEAR_P3_TO_XYZ_D65, linear)
                return _linear_hex(_mul(_XYZ_D65_TO_LINEAR_SRGB, xyz))
            return None
        if len(parts) != 3:  # exactly three channels; alpha only after `/`
            return None
        if name == "oklab":
            lab = (_number(parts[0], 1.0), _number(parts[1], 0.4), _number(parts[2], 0.4))
            return _linear_hex(oklab_to_linear(lab))
        if name == "oklch":
            lightness, chroma = _number(parts[0], 1.0), _number(parts[1], 0.4)
            hue = math.radians(_hue(parts[2]))
            lab = (lightness, chroma * math.cos(hue), chroma * math.sin(hue))
            return _linear_hex(oklab_to_linear(lab))
        if name == "lab":
            lightness, a, b = (
                _number(parts[0], 100.0), _number(parts[1], 125.0), _number(parts[2], 125.0)
            )
            return _linear_hex(_lab_to_linear(lightness, a, b))
        if name == "lch":
            lightness, chroma = _number(parts[0], 100.0), _number(parts[1], 150.0)
            hue = math.radians(_hue(parts[2]))
            a, b = chroma * math.cos(hue), chroma * math.sin(hue)
            return _linear_hex(_lab_to_linear(lightness, a, b))
        if name == "hwb":
            white, black = _number(parts[1], 100.0) / 100.0, _number(parts[2], 100.0) / 100.0
            return _hwb_hex(_hue(parts[0]) % 360, white, black)
    except (ValueError, OverflowError):
        return None
    return None
