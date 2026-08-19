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

import json
import math
from typing import Any, Optional

from .brand_brief import BRAND_BRIEF_TOKEN_BUDGET, read_brief, render_brand_grammar

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
#: Images are the agent's visual MENU — it can only choose what it can see, and
#: real kits carry ~13 image slots (Insight Health), well past the generic
#: MAX_LIST=8. 16 covers realistic kits whole while still bounding worst-case
#: card bloat; anything beyond it gets an explicit truncation line (no-silent-
#: caps) rather than vanishing.
MAX_IMAGE_LIST = 16
#: How many missing glyphs a font-gap note spells out before summarizing the
#: rest as "(+N more)" — keeps the note short on heavily-subset faces.
MAX_GLYPHS_IN_NOTE = 16
MAX_ALIAS_HOPS = 8


def build_brand_card(
    brand_kit: Optional[JsonObject],
    *,
    source: Optional[str] = None,
    notice: Optional[str] = None,
    include_brief: bool = False,
) -> Optional[JsonObject]:
    """The compact card, or None when the run has no attached kit.

    ``include_brief`` (slice 4, D4) adds the kit's Creative Brief and its
    measured geometry, rendered to bounded prose. It defaults OFF: the scene/ad
    path keeps today's card byte for byte until the ad-editor lane rules, and a
    kit that carries no `BrandBrief@1` renders today's card either way — the
    brief and the geometry ride together, so "no brief" is one clean switch
    back to pre-slice-4 behavior rather than two half-states.
    """
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
    # Font honesty: subset webfaces silently lack glyphs (× / — …). Surface the
    # ingestion audit so the author chooses copy with open eyes. Omitted when no
    # face reports a gap, and tolerant of old kits that predate the audit field.
    font_gaps = _font_gaps(assets.get("fonts") or {})
    if font_gaps:
        card["font_gaps"] = font_gaps
    if notice:
        card["notice"] = notice
    if include_brief:
        brief = read_brief(brand_kit)
        if brief is not None:
            render = render_brand_grammar(brand_kit, brief)
            card["creative_brief"] = {
                "schema": "BrandBrief@1",
                "rendered": render.markdown,
                "truncated": render.truncated,
                "omitted_sections": list(render.omitted),
                "estimated_tokens": render.estimated_tokens,
                "token_budget": BRAND_BRIEF_TOKEN_BUDGET,
            }
    return card


def render_brand_card_text(card: JsonObject) -> str:
    """The card as it is INJECTED into a role prompt.

    The card is JSON; the brief is prose. Serializing the prose inside the JSON
    would escape every newline and hand the model a 6,000-token single line, so
    the brief is spliced out and appended beside it. A card with no brief
    renders exactly the `json.dumps(card, indent=2)` this seam has always
    injected — byte for byte, which is the back-compat guarantee.
    """
    brief_block = card.get("creative_brief")
    if not isinstance(brief_block, dict):
        return json.dumps(card, indent=2)
    body = {key: value for key, value in card.items() if key != "creative_brief"}
    rendered = brief_block.get("rendered")
    prose = rendered if isinstance(rendered, str) else ""
    return json.dumps(body, indent=2) + "\n\n" + prose


def _font_gaps(fonts: JsonObject) -> list[str]:
    """Short per-face glyph-coverage notes (e.g. 'Aeonik lacks: × / —') read
    from ``fonts.<key>.metrics.missing_glyphs`` (stamped at ingestion). Empty
    when no face carries the field — old kits and fully-covering fonts alike."""
    notes: list[str] = []
    if not isinstance(fonts, dict):
        return notes
    for font in fonts.values():
        if not isinstance(font, dict):
            continue
        missing = (font.get("metrics") or {}).get("missing_glyphs")
        if not isinstance(missing, list) or not missing:
            continue
        chars = [str(c) for c in missing]
        if len(chars) > MAX_GLYPHS_IN_NOTE:
            shown = " ".join(chars[:MAX_GLYPHS_IN_NOTE])
            spelled = f"{shown} (+{len(chars) - MAX_GLYPHS_IN_NOTE} more)"
        else:
            spelled = " ".join(chars)
        family = font.get("family") or "font"
        notes.append(f"{family} lacks: {spelled}")
    return notes


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
                # Imagery slice 1: design-usage guidance is its OWN capped field
                # (kit `usage_note`) — never folded into a description a cap
                # can eat. Distinct from "usage", the slot kind above.
                **_usage_note_field(logo),
            }
        )
    return inventory


def _image_inventory(images: JsonObject) -> list[JsonObject]:
    inventory = []
    items = list(images.items())
    for image_id, image in items[:MAX_IMAGE_LIST]:
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
        # Imagery slice 1: usage guidance rides as its own capped field so the
        # description cap above can never eat it (the old " Usage: …" fold put
        # it exactly where truncation bites first).
        entry.update(_usage_note_field(image))
        tags = list(image.get("style_tags") or [])[:4]
        if tags:
            entry["style_tags"] = tags
        inventory.append(entry)
    # No-silent-caps: if the kit carries more image slots than the card shows,
    # tell the agent explicitly rather than letting them vanish.
    overflow = len(items) - MAX_IMAGE_LIST
    if overflow > 0:
        inventory.append(
            {"note": f"{overflow} more asset(s) available — full manifest via the asset tool"}
        )
    return inventory


def _usage_note_field(entry: JsonObject) -> JsonObject:
    usage_note = entry.get("usage_note")
    if isinstance(usage_note, str) and usage_note:
        return {"usage_note": usage_note[:120]}
    return {}


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
