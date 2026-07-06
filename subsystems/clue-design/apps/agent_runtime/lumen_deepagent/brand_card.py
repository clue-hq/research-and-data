"""K1: the compact brand context card.

A run with an attached Brand Kit gets a small, hard-capped digest of the kit
— tone, the resolved values of the semantic roles that drive taste, the type
roles, and the logo/image inventory with usage guidance — injected into the
coordinator/author/reviewer context. The FULL kit JSON never enters model
history (the 3a context-blowup lesson); preflight keeps using the full kit
engine-side. The card exists so the agent can exercise brand JUDGMENT
(which accent for a CTA, which logo variant on a dark surface), not just
token discipline.
"""

from __future__ import annotations

import math
from typing import Any, Optional

JsonObject = dict[str, Any]

# Semantic color roles that drive composition taste, in card order.
CARD_COLOR_ROLES = [
    "surface.page",
    "surface.card",
    "surface.brand",
    "surface.brand.subtle",
    "surface.accent",
    "surface.inverse",
    "text.primary",
    "text.inverse",
    "text.brand",
    "border.brand",
]
CARD_TYPE_ROLES = ["type.display", "type.headline", "type.body", "type.cta", "type.eyebrow"]
MAX_LIST = 8
MAX_ALIAS_HOPS = 8


def build_brand_card(
    brand_kit: Optional[JsonObject],
    *,
    source: Optional[str] = None,
    notice: Optional[str] = None,
) -> Optional[JsonObject]:
    """The compact card, or None when the run has no attached kit."""
    if not isinstance(brand_kit, dict) or not brand_kit.get("id"):
        return None

    colors = (brand_kit.get("tokens") or {}).get("colors") or {}
    typography = (brand_kit.get("tokens") or {}).get("typography") or {}
    assets = brand_kit.get("assets") or {}
    constraints = brand_kit.get("constraints") or {}

    color_roles: JsonObject = {}
    for role in CARD_COLOR_ROLES:
        resolved = _resolve_color(role, colors, set())
        if resolved:
            color_roles[role] = resolved

    accent = _brightest_accent(colors)

    card: JsonObject = {
        "kit": {
            "id": brand_kit.get("id"),
            "version": brand_kit.get("version"),
            "name": brand_kit.get("name"),
            "source": source,
        },
        "tone": list(constraints.get("tone") or [])[:MAX_LIST],
        "imagery_rules": list(constraints.get("imagery") or [])[:MAX_LIST],
        "color_roles": color_roles,
        # The taste-critical fact: the kit's most vivid brand color. CTAs and
        # emphasis reach for THIS (see brand-application.md), not ink.
        "accent": accent,
        "type_roles": _type_roles(typography),
        "logos": _logo_inventory(assets.get("logos") or {}),
        "images": _image_inventory(assets.get("images") or {}),
    }
    if notice:
        card["notice"] = notice
    return card


def _type_roles(typography: JsonObject) -> JsonObject:
    roles: JsonObject = {}
    for role in CARD_TYPE_ROLES:
        value = (typography.get(role) or {}).get("value") or {}
        default = value.get("default") or {}
        if default.get("kind") == "style":
            roles[role] = {
                "family": default.get("font_family"),
                "size": default.get("font_size"),
                "weight": default.get("font_weight"),
            }
    return roles


def _logo_inventory(logos: JsonObject) -> list[JsonObject]:
    inventory = []
    for logo_id, logo in list(logos.items())[:MAX_LIST]:
        if not isinstance(logo, dict):
            continue
        inventory.append(
            {
                "logo": logo_id,
                "usage": logo.get("usage"),
                "variants": [
                    {
                        "name": v.get("name"),
                        "color_mode": v.get("color_mode"),
                        # K2: the placement handle — pass to
                        # asset(action="use_brand_asset", asset_id=…).
                        "asset_id": v.get("asset_id"),
                    }
                    for v in (logo.get("variants") or [])[:4]
                    if isinstance(v, dict)
                ],
                "allowed_backgrounds": list(logo.get("allowed_backgrounds") or [])[:4],
                "min_size": logo.get("min_size"),
                "title": logo.get("title"),
            }
        )
    return inventory


def _image_inventory(images: JsonObject) -> list[JsonObject]:
    inventory = []
    for image_id, image in list(images.items())[:MAX_LIST]:
        if not isinstance(image, dict):
            continue
        entry: JsonObject = {
            "asset": image_id,
            # K2: the placement handle — pass to
            # asset(action="use_brand_asset", asset_id=…).
            "asset_id": image.get("asset_id"),
            "role": image.get("role"),
            "title": image.get("title"),
        }
        description = image.get("description")
        if isinstance(description, str) and description:
            entry["description"] = description[:160]
        tags = list(image.get("style_tags") or [])[:4]
        if tags:
            entry["style_tags"] = tags
        inventory.append(entry)
    return inventory


def _brightest_accent(colors: JsonObject) -> Optional[JsonObject]:
    """The kit's most vivid brand color: highest-chroma palette/accent entry
    with mid-to-high lightness — e.g. Insight Health's #30D8A7 — resolved to
    hex, with the token name so the author can reference it."""
    best: Optional[tuple[float, str, str]] = None
    for name in colors:
        if not (name.startswith("palette.") or "accent" in name):
            continue
        value = (colors.get(name) or {}).get("value") or {}
        default = value.get("default") or {}
        if default.get("kind") != "oklch":
            continue
        l, c = default.get("l"), default.get("c")
        if not isinstance(l, (int, float)) or not isinstance(c, (int, float)):
            continue
        if l < 0.55 or l > 0.92:
            continue
        if best is None or c > best[0]:
            resolved = _resolve_color(name, colors, set())
            if resolved:
                best = (float(c), name, resolved)
    if best is None:
        return None
    return {"token": best[1], "value": best[2]}


def _resolve_color(name: str, colors: JsonObject, seen: set[str]) -> Optional[str]:
    if name in seen or len(seen) >= MAX_ALIAS_HOPS:
        return None
    seen.add(name)
    value = (colors.get(name) or {}).get("value") or {}
    default = value.get("default") or {}
    kind = default.get("kind")
    if kind == "hex":
        raw = default.get("value")
        return raw if isinstance(raw, str) else None
    if kind == "oklch":
        try:
            return _oklch_to_hex(
                float(default["l"]), float(default["c"]), float(default["h"])
            )
        except (KeyError, TypeError, ValueError):
            return None
    if kind == "alias":
        target = default.get("token")
        return _resolve_color(target, colors, seen) if isinstance(target, str) else None
    return None


def _oklch_to_hex(l: float, c: float, h: float) -> str:
    """Same OKLab math the engine and the editor's tokenColors use, so the
    card quotes the exact pixel the design will render."""
    h_rad = math.radians(h)
    lab_a = c * math.cos(h_rad)
    lab_b = c * math.sin(h_rad)
    l_p = l + 0.3963377774 * lab_a + 0.2158037573 * lab_b
    m_p = l - 0.1055613458 * lab_a - 0.0638541728 * lab_b
    s_p = l - 0.0894841775 * lab_a - 1.291485548 * lab_b
    l3, m3, s3 = l_p**3, m_p**3, s_p**3
    channels = (
        4.0767416621 * l3 - 3.3077115913 * m3 + 0.2309699292 * s3,
        -1.2684380046 * l3 + 2.6097574011 * m3 - 0.3413193965 * s3,
        -0.0041960863 * l3 - 0.7034186147 * m3 + 1.707614701 * s3,
    )

    def encode(linear: float) -> str:
        clamped = min(1.0, max(0.0, linear))
        encoded = (
            clamped * 12.92
            if clamped <= 0.0031308
            else 1.055 * clamped ** (1 / 2.4) - 0.055
        )
        return format(round(encoded * 255), "02x")

    return "#" + "".join(encode(ch) for ch in channels)
