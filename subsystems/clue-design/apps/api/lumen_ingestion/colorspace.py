"""Pure color-space math for the ingestion normalizer. No external deps.

sRGB <-> linear <-> OKLab <-> OKLCH uses Bjorn Ottosson's reference matrices
(https://bottosson.github.io/posts/oklab/). WCAG 2.x relative-luminance and
contrast ratio. Gamut clamping is done by reducing chroma until the OKLCH color
maps back into the sRGB cube.
"""

from __future__ import annotations

import math

_GAMUT_EPSILON = 1e-4


def hex_to_rgb(value: str) -> tuple[float, float, float]:
    """Return sRGB channels in 0..1 (alpha, if present, is ignored)."""
    body = value.lstrip("#")
    r = int(body[0:2], 16) / 255.0
    g = int(body[2:4], 16) / 255.0
    b = int(body[4:6], 16) / 255.0
    return r, g, b


def hex_alpha(value: str) -> float:
    body = value.lstrip("#")
    if len(body) >= 8:
        return int(body[6:8], 16) / 255.0
    return 1.0


def rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    def channel(component: float) -> int:
        return max(0, min(255, round(component * 255.0)))

    r, g, b = rgb
    return "#{:02X}{:02X}{:02X}".format(channel(r), channel(g), channel(b))


def _srgb_to_linear(c: float) -> float:
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(c: float) -> float:
    if c <= 0.0031308:
        return 12.92 * c
    return 1.055 * (c ** (1.0 / 2.4)) - 0.055


def linear_rgb(rgb: tuple[float, float, float]) -> tuple[float, float, float]:
    r, g, b = rgb
    return _srgb_to_linear(r), _srgb_to_linear(g), _srgb_to_linear(b)


def linear_to_oklab(lin: tuple[float, float, float]) -> tuple[float, float, float]:
    r, g, b = lin
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b

    l_ = _cbrt(l)
    m_ = _cbrt(m)
    s_ = _cbrt(s)

    return (
        0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
        1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
        0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_,
    )


def oklab_to_linear(lab: tuple[float, float, float]) -> tuple[float, float, float]:
    L, a, b = lab
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b

    l = l_ * l_ * l_
    m = m_ * m_ * m_
    s = s_ * s_ * s_

    return (
        +4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
        -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
        -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s,
    )


def _cbrt(x: float) -> float:
    if x < 0:
        return -((-x) ** (1.0 / 3.0))
    return x ** (1.0 / 3.0)


def hex_to_oklab(value: str) -> tuple[float, float, float]:
    return linear_to_oklab(linear_rgb(hex_to_rgb(value)))


def oklab_to_oklch(lab: tuple[float, float, float]) -> tuple[float, float, float]:
    L, a, b = lab
    c = math.hypot(a, b)
    h = math.degrees(math.atan2(b, a)) % 360.0
    return L, c, h


def oklch_to_oklab(lch: tuple[float, float, float]) -> tuple[float, float, float]:
    L, c, h = lch
    radians = math.radians(h)
    return L, c * math.cos(radians), c * math.sin(radians)


def hex_to_oklch(value: str) -> tuple[float, float, float]:
    return oklab_to_oklch(hex_to_oklab(value))


def _lab_to_hex_exact(lab: tuple[float, float, float]) -> tuple[str, bool]:
    lin = oklab_to_linear(lab)
    in_gamut = all(-_GAMUT_EPSILON <= c <= 1.0 + _GAMUT_EPSILON for c in lin)
    srgb = tuple(_linear_to_srgb(min(1.0, max(0.0, c))) for c in lin)
    return rgb_to_hex(srgb), in_gamut


def oklab_to_hex(lab: tuple[float, float, float]) -> str:
    return _lab_to_hex_exact(lab)[0]


def oklch_to_hex(lch: tuple[float, float, float]) -> str:
    """OKLCH -> hex, clamping into the sRGB gamut by reducing chroma."""
    L, c, h = lch
    lab = oklch_to_oklab((L, c, h))
    hex_value, in_gamut = _lab_to_hex_exact(lab)
    if in_gamut or c <= 0.0:
        return hex_value
    lo, hi = 0.0, c
    for _ in range(48):
        mid = (lo + hi) / 2.0
        _, ok = _lab_to_hex_exact(oklch_to_oklab((L, mid, h)))
        if ok:
            lo = mid
        else:
            hi = mid
        if hi - lo < _GAMUT_EPSILON:
            break
    return oklab_to_hex(oklch_to_oklab((L, lo, h)))


def with_lch(l: float, c: float, h: float) -> str:
    return oklch_to_hex((l, c, h))


def with_lightness(hex_value: str, L: float) -> str:
    _, c, h = hex_to_oklch(hex_value)
    return oklch_to_hex((L, c, h))


def oklab_distance(a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def hue_distance(h1: float, h2: float) -> float:
    diff = abs((h1 - h2) % 360.0)
    return min(diff, 360.0 - diff)


def relative_luminance(hex_value: str) -> float:
    r, g, b = linear_rgb(hex_to_rgb(hex_value))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg_hex: str, bg_hex: str) -> float:
    l1 = relative_luminance(fg_hex)
    l2 = relative_luminance(bg_hex)
    lighter, darker = (l1, l2) if l1 >= l2 else (l2, l1)
    return (lighter + 0.05) / (darker + 0.05)
