"""Deterministic role assignment (§3.2) + dark colorway (§3.6).

Light-theme semantic roles are assigned from clustered evidence by fixed rules;
the dark colorway is assigned from captured dark evidence when present, else
synthesized from the light palette. Every decision records a `basis`
("evidence" | "derived" | "default") and a compact provenance string so the
emitter can stamp per-token provenance and the report can explain choices.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..colorspace import (
    contrast_ratio,
    hex_to_oklch,
    hue_distance,
    with_lch,
    with_lightness,
)
from .cluster import ColorCluster

NEAR_NEUTRAL_C = 0.03
SATURATED_C = 0.07
_CONTRAST_MIN = 4.5

_SATURATED_HINTS = {"button-bg", "accent", "link"}
_BRAND_FALLBACK = "#0F766E"


@dataclass
class RoleAssignment:
    hex: str
    basis: str            # "evidence" | "derived" | "default"
    provenance: str       # compact provenance string
    cluster: ColorCluster | None = None


@dataclass
class LightRoles:
    assignments: dict[str, RoleAssignment]
    extras: list[ColorCluster]
    diagnostics: list[dict] = field(default_factory=list)


def _pointer(cluster: ColorCluster) -> str:
    return f"{cluster.pointer_source}:{cluster.pointer_locator}"


def _is_near_neutral(cluster: ColorCluster) -> bool:
    return hex_to_oklch(cluster.representative)[1] < NEAR_NEUTRAL_C


def _is_saturated(cluster: ColorCluster) -> bool:
    return hex_to_oklch(cluster.representative)[1] >= SATURATED_C


def _has_hint(cluster: ColorCluster, *hints: str) -> bool:
    return any(hint in cluster.role_hints for hint in hints)


def _has_custom_prop(cluster: ColorCluster) -> bool:
    return any(hint.startswith("custom-prop:") for hint in cluster.role_hints)


def assign_light_roles(clusters: list[ColorCluster]) -> LightRoles:
    light = [c for c in clusters if c.theme == "light"]
    diagnostics: list[dict] = []
    assignments: dict[str, RoleAssignment] = {}
    chosen_ids: set[int] = set()

    # 1. page_bg
    page_hinted = _first(light, lambda c: _has_hint(c, "page-bg"))
    if page_hinted is not None:
        page = RoleAssignment(page_hinted.representative, "evidence", _pointer(page_hinted), page_hinted)
        chosen_ids.add(id(page_hinted))
    else:
        bright_neutral = _first(
            light,
            lambda c: _is_near_neutral(c) and hex_to_oklch(c.representative)[0] > 0.9,
        )
        if bright_neutral is not None:
            page = RoleAssignment(bright_neutral.representative, "evidence", _pointer(bright_neutral), bright_neutral)
            chosen_ids.add(id(bright_neutral))
        else:
            page = RoleAssignment("#FFFFFF", "default", "default:surface.page defaulted")
            diagnostics.append(_diag("LUMI0201", "info", "surface.page defaulted"))
    assignments["surface.page"] = page

    # 2. text_primary
    text_hinted = _first(
        light,
        lambda c: _has_hint(c, "body-text") and contrast_ratio(c.representative, page.hex) >= _CONTRAST_MIN,
    )
    if text_hinted is not None:
        text = RoleAssignment(text_hinted.representative, "evidence", _pointer(text_hinted), text_hinted)
        chosen_ids.add(id(text_hinted))
    else:
        dark_neutral = _last(
            sorted(
                [c for c in light if _is_near_neutral(c) and c.weight > 0],
                key=lambda c: (-hex_to_oklch(c.representative)[0],),
            )
        )
        if dark_neutral is not None:
            text = RoleAssignment(dark_neutral.representative, "evidence", _pointer(dark_neutral), dark_neutral)
            chosen_ids.add(id(dark_neutral))
        else:
            derived = with_lightness(page.hex, 0.25)
            text = RoleAssignment(derived, "derived", "derived:text.primary(page-25)")
    text = _ensure_contrast_light(text, page.hex, diagnostics)
    assignments["text.primary"] = text

    # 3. brand
    brand_hinted = _first(
        light,
        lambda c: _is_saturated(c) and (_has_hint(c, *_SATURATED_HINTS) or _has_custom_prop(c)),
    )
    if brand_hinted is not None:
        brand = RoleAssignment(brand_hinted.representative, "evidence", _pointer(brand_hinted), brand_hinted)
        chosen_ids.add(id(brand_hinted))
    else:
        brand_any = _first(light, _is_saturated)
        if brand_any is not None:
            brand = RoleAssignment(brand_any.representative, "evidence", _pointer(brand_any), brand_any)
            chosen_ids.add(id(brand_any))
        else:
            brand = RoleAssignment(_BRAND_FALLBACK, "default", "default:no brand color found")
            diagnostics.append(_diag("LUMI0203", "warning", "no brand color found — platform teal used"))
    assignments["surface.brand"] = brand

    # 4. accent_secondary. Named clusters are author-labelled swatches destined
    # for the extras list (rule 5), so they are not auto-promoted to accent here;
    # accent auto-selection only considers unnamed saturated evidence.
    brand_h = hex_to_oklch(brand.hex)[2]
    accent_cluster = _first(
        light,
        lambda c: _is_saturated(c)
        and id(c) not in chosen_ids
        and c.name is None
        and not any(h.startswith("named:") for h in c.role_hints)
        and hue_distance(hex_to_oklch(c.representative)[2], brand_h) > 30.0,
    )
    if accent_cluster is not None:
        assignments["surface.accent"] = RoleAssignment(
            accent_cluster.representative, "evidence", _pointer(accent_cluster), accent_cluster
        )
        chosen_ids.add(id(accent_cluster))

    # 5. extras — named clusters not otherwise chosen
    extras = [
        c
        for c in light
        if id(c) not in chosen_ids and (c.name or any(h.startswith("named:") for h in c.role_hints))
    ]

    return LightRoles(assignments=assignments, extras=extras, diagnostics=diagnostics)


def _ensure_contrast_light(role: RoleAssignment, bg_hex: str, diagnostics: list[dict]) -> RoleAssignment:
    if contrast_ratio(role.hex, bg_hex) >= _CONTRAST_MIN:
        return role
    original = role.hex
    _, _, h = hex_to_oklch(role.hex)
    c = min(hex_to_oklch(role.hex)[1], 0.02)
    # Walk toward the endpoint (black vs white) that yields more contrast on the
    # page. WCAG luminance, not OKLCH L, decides — saturated mid-L swatches read
    # dark, so probing both ends is more reliable than a lightness threshold.
    direction = -1.0 if contrast_ratio("#000000", bg_hex) >= contrast_ratio("#FFFFFF", bg_hex) else 1.0
    L = hex_to_oklch(role.hex)[0]
    steps = 0
    while 0.0 <= L <= 1.0 and steps < 60:
        L = min(1.0, max(0.0, L + direction * 0.02))
        candidate = with_lch(L, c, h)
        steps += 1
        if contrast_ratio(candidate, bg_hex) >= _CONTRAST_MIN:
            diagnostics.append(
                _diag("LUMI0202", "warning", f"text.primary adjusted for contrast (was {original})")
            )
            return RoleAssignment(candidate, "derived", "derived:text.primary(contrast-adjusted)", role.cluster)
        if L in (0.0, 1.0):
            break
    diagnostics.append(
        _diag("LUMI0202", "warning", f"text.primary adjusted for contrast (was {original})")
    )
    endpoint = 0.0 if direction < 0 else 1.0
    return RoleAssignment(with_lch(endpoint, c, h), "derived", "derived:text.primary(contrast-adjusted)", role.cluster)


# --- dark colorway ---------------------------------------------------------


@dataclass
class DarkColorway:
    values: dict[str, str]           # token path -> hex
    basis: str                       # "captured" | "synthesized"
    diagnostics: list[dict] = field(default_factory=list)


def build_dark_colorway(
    clusters: list[ColorCluster],
    light: LightRoles,
    primary_ramp: dict[str, str],
) -> DarkColorway:
    dark_clusters = [c for c in clusters if c.theme == "dark"]
    if dark_clusters:
        return _capture_dark(dark_clusters, light)
    return _synthesize_dark(light, primary_ramp)


_DARK_PAGE_MAX_L = 0.30


def _capture_dark(dark_clusters: list[ColorCluster], light: LightRoles) -> DarkColorway:
    # dark page_bg = darkest high-weight cluster. If the darkest captured "dark"
    # swatch is not actually dark enough to seat AA text, clamp its lightness
    # down (keeping hue/chroma) so the dark colorway remains usable.
    page = min(dark_clusters, key=lambda c: (hex_to_oklch(c.representative)[0], -c.weight)).representative
    page_L, page_c, page_h = hex_to_oklch(page)
    if page_L > _DARK_PAGE_MAX_L:
        page = with_lch(_DARK_PAGE_MAX_L, page_c, page_h)
    # dark text = lightest cluster with contrast on page
    text_candidates = sorted(dark_clusters, key=lambda c: -hex_to_oklch(c.representative)[0])
    text = text_candidates[0].representative
    for candidate in text_candidates:
        if contrast_ratio(candidate.representative, page) >= _CONTRAST_MIN:
            text = candidate.representative
            break
    text = _ensure_contrast(text, page)
    # brand = highest-weight saturated dark cluster else light brand
    brand_cluster = _first(dark_clusters, _is_saturated)
    brand = brand_cluster.representative if brand_cluster else light.assignments["surface.brand"].hex

    values = _dark_semantic_map(page, text, brand, light)
    return DarkColorway(values=values, basis="captured")


def _synthesize_dark(light: LightRoles, primary_ramp: dict[str, str]) -> DarkColorway:
    brand_hex = light.assignments["surface.brand"].hex
    _, brand_c, brand_h = hex_to_oklch(brand_hex)
    c_d = min(brand_c * 0.25, 0.04)

    page = with_lch(0.18, c_d, brand_h)
    text = _ensure_contrast(with_lch(0.95, min(c_d, 0.02), brand_h), page)

    values: dict[str, str] = {
        "surface.page": page,
        "surface.canvas": with_lch(0.15, c_d, brand_h),
        "surface.card": with_lch(0.22, c_d, brand_h),
        "surface.elevated": with_lch(0.26, c_d, brand_h),
        "surface.muted": with_lch(0.24, c_d, brand_h),
        "surface.brand": primary_ramp["400"],
        "surface.brand.subtle": with_lch(0.28, c_d * 1.5, brand_h),
        "surface.inverse": light.assignments["surface.page"].hex,
        "text.primary": text,
        "text.secondary": with_lch(0.78, min(c_d, 0.02), brand_h),
        "text.muted": with_lch(0.62, min(c_d, 0.02), brand_h),
        "text.inverse": light.assignments["text.primary"].hex,
        "text.brand": primary_ramp["300"],
        "border.subtle": with_lch(0.30, c_d, brand_h),
        "border.default": with_lch(0.38, c_d, brand_h),
        "border.strong": with_lch(0.48, c_d, brand_h),
        "border.brand": primary_ramp["500"],
        "focus.ring": primary_ramp["400"],
    }

    accent = light.assignments.get("surface.accent")
    if accent is not None:
        _, a_c, a_h = hex_to_oklch(accent.hex)
        values["surface.accent"] = with_lch(0.75, a_c, a_h)
        values["text.accent"] = with_lch(0.8, a_c, a_h)
    else:
        values["surface.accent"] = primary_ramp["300"]
        values["text.accent"] = primary_ramp["300"]

    diagnostics = [_diag("LUMI0210", "info", "dark colorway synthesized from light palette")]
    return DarkColorway(values=values, basis="synthesized", diagnostics=diagnostics)


def _dark_semantic_map(page: str, text: str, brand: str, light: LightRoles) -> dict[str, str]:
    _, brand_c, brand_h = hex_to_oklch(brand)
    c_d = min(brand_c * 0.25, 0.04)
    values = {
        "surface.page": page,
        "surface.canvas": with_lch(max(0.05, hex_to_oklch(page)[0] - 0.03), c_d, brand_h),
        "surface.card": with_lch(hex_to_oklch(page)[0] + 0.04, c_d, brand_h),
        "surface.elevated": with_lch(hex_to_oklch(page)[0] + 0.08, c_d, brand_h),
        "surface.muted": with_lch(hex_to_oklch(page)[0] + 0.06, c_d, brand_h),
        "surface.brand": brand,
        "surface.brand.subtle": with_lch(0.28, c_d * 1.5, brand_h),
        "surface.accent": brand,
        "surface.inverse": light.assignments["surface.page"].hex,
        "text.primary": text,
        "text.secondary": with_lch(0.78, min(c_d, 0.02), brand_h),
        "text.muted": with_lch(0.62, min(c_d, 0.02), brand_h),
        "text.inverse": light.assignments["text.primary"].hex,
        "text.brand": brand,
        "text.accent": brand,
        "border.subtle": with_lch(0.30, c_d, brand_h),
        "border.default": with_lch(0.38, c_d, brand_h),
        "border.strong": with_lch(0.48, c_d, brand_h),
        "border.brand": brand,
        "focus.ring": brand,
    }
    return values


def _ensure_contrast(text_hex: str, page_hex: str) -> str:
    """Return a text color that meets AA contrast on `page_hex`, walking the text
    lightness toward whichever end (up to white / down to black) is farther from
    the page lightness. Works whether the captured/synth page is light or dark."""
    if contrast_ratio(text_hex, page_hex) >= _CONTRAST_MIN:
        return text_hex
    _, _, h = hex_to_oklch(text_hex)
    direction = 1.0 if contrast_ratio("#FFFFFF", page_hex) >= contrast_ratio("#000000", page_hex) else -1.0
    c = min(hex_to_oklch(text_hex)[1], 0.02)
    L = hex_to_oklch(text_hex)[0]
    steps = 0
    while 0.0 <= L <= 1.0 and steps < 60:
        L = min(1.0, max(0.0, L + direction * 0.02))
        candidate = with_lch(L, c, h)
        steps += 1
        if contrast_ratio(candidate, page_hex) >= _CONTRAST_MIN:
            return candidate
        if L in (0.0, 1.0):
            break
    return with_lch(1.0 if direction > 0 else 0.0, c, h)


def _first(items, predicate):
    for item in items:
        if predicate(item):
            return item
    return None


def _last(items):
    return items[-1] if items else None


def _diag(code: str, severity: str, message: str) -> dict:
    return {"code": code, "severity": severity, "message": message}
