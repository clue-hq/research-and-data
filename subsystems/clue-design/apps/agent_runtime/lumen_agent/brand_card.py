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

from .brand_brief import (
    BRAND_BRIEF_TOKEN_BUDGET,
    GRAMMAR_AUDIT_CHAR_BUDGET,
    read_brief,
    read_grammar_audit,
    render_brand_grammar,
    render_grammar_audit,
)
from .engine_mirror import (
    ALIAS_DEPTH_CAP,
    record_pixel_dims,
    resolve_kit_color,
    sanitize_token_name,
)

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
MAX_TYPE_SIZE_LIST = 32
#: How many missing glyphs a font-gap note spells out before summarizing the
#: rest as "(+N more)" — keeps the note short on heavily-subset faces.
MAX_GLYPHS_IN_NOTE = 16
#: Alias-chain bound. The engine's own cap (`engine_mirror.ALIAS_DEPTH_CAP`), so
#: a color the card shows is a color the compiled theme resolves.
MAX_ALIAS_HOPS = ALIAS_DEPTH_CAP

#: The one line that kills the transposition trap. The card lists kit ROLE names
#: (`text.brand`); a class is `<utility-prefix>-<token>`, and the token for a
#: role is its sanitized name — so `text.brand` is the class `text-text-brand`
#: (prefix `text-` + token `text-brand`), never `text-brand`. Writing the role
#: as if it were a token is what produced 153 live LUMW0212 rejections
#: (`brand`/`secondary` are not tokens), so every role row now carries the token
#: name outright and this note states which list is authoritative.
COLOR_ROLE_NOTE = (
    "These are kit ROLE names, not class tokens. Build a class from `token`: "
    "<utility-prefix>-<token>, e.g. bg-surface-brand, text-text-brand, "
    "border-border-brand. The author prompt's THEME TOKENS list is authoritative "
    "for what exists."
)

SCENE_COLOR_ROLE_NOTE = (
    "Use the exact `token` in native Scene DSL, e.g. fill($surface.brand) "
    "or fill($text.primary). Preserve dots; CSS utility names are not scene "
    "tokens. Values shown are kit defaults; preflight resolves the active mode."
)

SCENE_TYPE_SIZE_NOTE = (
    "These are concrete size steps declared by this kit, in the listed units. "
    "Choose a supplied token from measured copy and reference proportions; these "
    "values are not minimum sizes. Keep the typography role for family/weight "
    "with style($type.display) and set font_size($<token>) using an exact key "
    "below. The size token survives role resolution; a raw font_size(n) beside "
    "style(...) can be replaced by the role's default during preflight. "
    "Values shown are kit defaults. If no suitable step is supplied, record "
    "the gap instead of inventing a token."
)


def build_brand_card(
    brand_kit: Optional[JsonObject],
    *,
    source: Optional[str] = None,
    notice: Optional[str] = None,
    include_brief: bool = False,
    include_grammar_audit: bool = False,
    asset_manifest: Optional[JsonObject] = None,
    scene_dsl: bool = False,
) -> Optional[JsonObject]:
    """The compact card, or None when the run has no attached kit.

    ``include_brief`` (slice 4, D4) adds the kit's Creative Brief and its
    measured geometry, rendered to bounded prose. It defaults OFF: the scene/ad
    path keeps today's card byte for byte until the ad-editor lane rules, and a
    kit that carries no `BrandBrief@1` renders today's card either way — the
    brief and the geometry ride together, so "no brief" is one clean switch
    back to pre-slice-4 behavior rather than two half-states.

    ``include_grammar_audit`` (clone-fidelity F2.4) adds the kit's
    `BrandGrammarAudit@1` — the measured law for sections the agent COMPOSES.
    Its own switch rather than a ride-along on ``include_brief``: the two are
    independently owned (a model writes the brief, arithmetic extracts the
    audit), a kit can carry either, both or neither, and folding them together
    would make a kit with one and not the other unrepresentable. It also defaults
    OFF, so the scene/ad card stays byte-identical.

    ``asset_manifest`` is the run's by-value kit asset manifest (the same
    ``config.brand_kit_assets`` ``use_brand_asset`` reads: ``{asset_id: {"record":
    AssetRecord}}``). The kit's own asset entries carry only an ``asset_id``, so
    the pixel dimensions the author needs to tell a 2460px panel from a 296px
    crop exist ONLY on those records. Omitted → the rows simply carry no size,
    exactly as before.

    ``scene_dsl`` exposes native token handles and the kit's numeric type-size
    steps. Only the candidate scene substrate opts in; the default keeps the
    established website and legacy card serialization unchanged.
    """
    if not isinstance(brand_kit, dict) or not brand_kit.get("id"):
        return None

    colors = (brand_kit.get("tokens") or {}).get("colors") or {}
    typography = (brand_kit.get("tokens") or {}).get("typography") or {}
    assets = brand_kit.get("assets") or {}
    constraints = brand_kit.get("constraints") or {}
    manifest = asset_manifest if isinstance(asset_manifest, dict) else {}

    roles: JsonObject = {}
    for role in CARD_COLOR_ROLES:
        resolved = _resolve_color(role, colors)
        if resolved:
            roles[role] = {
                "token": role if scene_dsl else sanitize_token_name(role),
                "value": resolved,
            }
    color_roles = {
        "note": SCENE_COLOR_ROLE_NOTE if scene_dsl else COLOR_ROLE_NOTE,
        "roles": roles,
    }

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
        "type_roles": _type_roles(typography, include_font_asset=scene_dsl),
        "logos": _logo_inventory(assets.get("logos") or {}, manifest),
        "images": _image_inventory(assets.get("images") or {}, manifest),
    }
    if scene_dsl:
        card["color_catalog"] = {
            "path": "brand_colors.json",
            "count": len(colors),
            "note": (
                "The compact roles are a shortlist, not the entire palette. "
                "Read this file in the run workspace when their values do not "
                "fit the inspected reference; it contains the pinned kit's "
                "other color tokens, aliases and modes. Choose by actual value "
                "and purpose. Preflight resolves the active mode; token names "
                "alone do not establish visual fidelity or logo compatibility."
            ),
        }
        card["type_sizes"] = _scene_type_sizes(
            (brand_kit.get("tokens") or {}).get("numbers") or {}
        )
        card["font_bindings"] = _scene_font_bindings(assets.get("fonts") or {})
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
    if include_grammar_audit:
        audit = read_grammar_audit(brand_kit)
        if audit is not None:
            rendered = render_grammar_audit(audit)
            card["grammar_audit"] = {
                "schema": "BrandGrammarAudit@1",
                "rendered": rendered.markdown,
                "truncated": rendered.truncated,
                "dropped_rules": rendered.dropped_rules,
                "dropped_from": list(rendered.dropped_from),
                "characters": rendered.characters,
                "char_budget": GRAMMAR_AUDIT_CHAR_BUDGET,
            }
    return card


def _scene_type_sizes(numbers: JsonObject) -> JsonObject:
    steps: JsonObject = {}
    for name, entry in numbers.items():
        if not name.startswith("type.size.") or not isinstance(entry, dict):
            continue
        default = (entry.get("value") or {}).get("default") or {}
        value = default.get("value")
        if (
            default.get("kind") == "number"
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
            and value > 0
            and default.get("unit") in {"px", "pt"}
        ):
            steps[name] = {"value": value, "unit": default["unit"]}
    ordered = sorted(steps, key=lambda name: (steps[name]["value"], name))
    result: JsonObject = {
        "note": SCENE_TYPE_SIZE_NOTE,
        "tokens": {name: steps[name] for name in ordered[:MAX_TYPE_SIZE_LIST]},
    }
    if len(ordered) > MAX_TYPE_SIZE_LIST:
        result["omitted_count"] = len(ordered) - MAX_TYPE_SIZE_LIST
    return result


#: The card keys whose value is PROSE, in the order they are appended below.
#: Serializing prose inside the JSON escapes every newline and hands the model a
#: thousand-token single line, so each one is spliced out and set beside it.
_PROSE_BLOCKS = ("creative_brief", "grammar_audit")


def render_brand_card_text(card: JsonObject) -> str:
    """The card as it is INJECTED into a role prompt.

    The card is JSON; the brief and the grammar audit are prose. A card carrying
    neither renders exactly the `json.dumps(card, indent=2)` this seam has always
    injected — byte for byte, which is the back-compat guarantee.
    """
    prose = [
        rendered
        for rendered in (
            (card.get(key) or {}).get("rendered")
            if isinstance(card.get(key), dict)
            else None
            for key in _PROSE_BLOCKS
        )
        if isinstance(rendered, str) and rendered
    ]
    if not prose:
        return json.dumps(card, indent=2)
    body = {key: value for key, value in card.items() if key not in _PROSE_BLOCKS}
    return json.dumps(body, indent=2) + "\n\n" + "\n\n".join(prose)


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


def _scene_font_bindings(fonts: JsonObject) -> JsonObject:
    """Declared kit bindings, not a duplicate of the engine's font resolver.

    The image/logo manifest deliberately excludes fonts. Neither its absence
    nor an empty kit face list establishes actual runtime font availability.
    Glyph metrics describe one representative face and a limited probe set.
    """
    entries = {
        name: font for name, font in fonts.items() if isinstance(font, dict)
    } if isinstance(fonts, dict) else {}
    inventory: JsonObject = {}
    for name, font in list(entries.items())[:MAX_LIST]:
        faces = [
            face for face in (font.get("faces") or [])
            if isinstance(face, dict)
            and isinstance(face.get("asset_id"), str)
            and face["asset_id"].strip()
        ]
        row: JsonObject = {
            "family": font.get("family"),
            "declared_face_count": len(faces),
            "declared_faces": [
                {key: face.get(key) for key in ("asset_id", "weight", "style")}
                for face in faces[:MAX_LIST]
            ],
            "glyph_coverage": "not_established",
        }
        if len(faces) > MAX_LIST:
            row["omitted_faces"] = len(faces) - MAX_LIST
        metrics = font.get("metrics")
        missing = metrics.get("missing_glyphs") if isinstance(metrics, dict) else None
        if isinstance(missing, list) and missing:
            row["known_missing_glyphs"] = missing[:MAX_GLYPHS_IN_NOTE]
            if len(missing) > MAX_GLYPHS_IN_NOTE:
                row["omitted_missing_glyphs"] = len(missing) - MAX_GLYPHS_IN_NOTE
        inventory[name] = row
    result: JsonObject = {
        "note": (
            "Raw kit declarations, not loaded-font verification. The role's "
            "font_asset is a raw reference; a resolved font slot can override "
            "the role's family. Preflight resolves aliases, active modes, "
            "actual font bytes and weight substitutions. Zero kit faces may "
            "still be supplied by bundled/library fonts; declared faces may "
            "fail to load. Known missing glyphs are a representative-face "
            "audit, not coverage for every face or character. No recorded gap "
            "does not prove coverage. Inspect the rendered copy; use a "
            "separate native vector for an unsupported decorative symbol."
        ),
        "assets": inventory,
    }
    if len(entries) > MAX_LIST:
        result["omitted_font_assets"] = len(entries) - MAX_LIST
    return result


def _type_roles(typography: JsonObject, *, include_font_asset: bool = False) -> JsonObject:
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
            if include_font_asset:
                roles[role]["font_asset"] = default.get("font_asset")
    return roles


def _logo_inventory(logos: JsonObject, manifest: JsonObject) -> list[JsonObject]:
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
                        # A wordmark's pixels decide whether it survives a small
                        # header slot — same honesty as the image rows.
                        **_pixel_field(v.get("asset_id"), manifest),
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


def _image_area(image: Any, manifest: JsonObject) -> int:
    """A kit image slot's pixel area from its asset record, or 0.

    Same lookup `_pixel_field` does — the card ranks by exactly the number it
    prints. A slot with no manifest entry, no record, or no dimensions has no
    evidence of being large and ranks as 0 rather than being guessed at."""
    if not isinstance(image, dict):
        return 0
    entry = manifest.get(image.get("asset_id")) if isinstance(manifest, dict) else None
    record = (entry or {}).get("record") if isinstance(entry, dict) else None
    dims = record_pixel_dims(record) if isinstance(record, dict) else None
    return dims[0] * dims[1] if dims else 0


def _image_inventory(images: JsonObject, manifest: JsonObject) -> list[JsonObject]:
    inventory = []
    # W1.5: rank by pixel area before the cap bites, ties keeping kit order, so
    # the card's sixteen are the sixteen LARGEST assets rather than the sixteen
    # the kit happened to list first. Insertion order is not quality order for a
    # PDF or manual kit, and taking its head showed the agent sixteen small
    # crops while the large assets — the ones that can carry a band — never
    # appeared at all.
    #
    # This ranks on the RECORD's raster dimensions (the same numbers the row
    # prints as `px`). Be precise about what that does and does not align with:
    #
    #   - The W1.4 describe bound (`lumen_ingestion.describe._select_for_describe`)
    #     uses the same SHAPE of rule — `(-area, position)` — but its area comes
    #     from the CAPTURE evidence (DOM-attribute sizes), not from the record.
    #   - A website kit's birth order (`capture/parse.py`'s candidate sort) is
    #     `(DOM-attr area, file_size)` descending, and CSS-background art is
    #     appended with area 0.
    #
    # So this is NOT a no-op for website kits, and it does NOT make the card and
    # describe agree: a large CSS-background hero can rank into the card's
    # top-16 on its record dimensions while describe, ranking on DOM attributes
    # it never had, left it uncaptioned. That divergence is real and is the
    # ledgered describe-ranking-source item, not something this sort can close.
    # Record dims are nonetheless the truer ranking — they are the asset's
    # actual pixels — so the card ranks on them and states the size it ranked by.
    items = sorted(
        images.items(),
        key=lambda item: -_image_area(item[1], manifest),
    )
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
            # The size the row could not state before: a 2460px panel and a
            # 296px crop read identically without it, and 512px is the floor a
            # style anchor must clear.
            **_pixel_field(image.get("asset_id"), manifest),
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


def _pixel_field(asset_id: Any, manifest: JsonObject) -> JsonObject:
    """`{"px": "2460x1060"}` for an asset whose record states its dimensions,
    else `{}` — never a guess. The key carries the unit so the value stays a
    plain WxH the agent can compare at a glance."""
    entry = manifest.get(asset_id) if isinstance(asset_id, str) else None
    record = (entry or {}).get("record") if isinstance(entry, dict) else None
    dims = record_pixel_dims(record) if isinstance(record, dict) else None
    return {"px": f"{dims[0]}x{dims[1]}"} if dims else {}


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
            resolved = _resolve_color(name, colors)
            if resolved:
                best = (float(c), name, resolved)
    if best is None:
        return None
    return {"token": best[1], "value": best[2]}


def _resolve_color(name: str, colors: JsonObject) -> Optional[str]:
    """A kit color role as the HEX the design will actually paint, or None when
    the compiled theme would carry no color for it.

    The alias walk itself is the engine's (`engine_mirror.resolve_kit_color`), so
    the card can never show a color the theme skipped; only the presentation —
    oklch converted to hex, because the card quotes pixels — lives here."""
    default = resolve_kit_color(name, colors)
    if default is None:
        return None
    if default.get("kind") == "hex":
        raw = default.get("value")
        return raw if isinstance(raw, str) else None
    return _oklch_to_hex(
        float(default["l"]), float(default["c"]), float(default["h"])
    )


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
