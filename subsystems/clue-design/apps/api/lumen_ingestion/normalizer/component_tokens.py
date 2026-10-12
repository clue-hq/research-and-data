"""Measured component styles → brand-scoped kit tokens (Wave 2 A9; founder rulings 2026-10-12).

Every value the capture measured on a style — fill, label colour, border, corners, padding, font,
case, decoration, shadow, transform, opacity, cursor, outline, icon, in rest and in each state, and
the timing of its transitions — becomes a token of THIS kit, and the page's CSS animations and
reveals become named motion entries. Three rules, each enforced here:

* Exact-match reuse. A token of this kit that already holds exactly that value (same group, same
  value, no tolerance) is named instead of minting a second; among several, the one whose family
  suits the slot wins (a fill prefers `surface.*`, a label `text.*`, a border `border.*`), then a
  token that was not minted, then the name. Identical values used by several styles of one component
  share one token when they fill the same kind of slot (hover fills across buttons, shadows,
  durations); a minted token is never reused for another kind (a 2px outline offset is not a link's
  underline thickness) or another component (a link's text is not a button's label), since its name
  says what it is.
* Stable names made by code from where the value was measured: `button.solid-047464.fill`,
  `button.solid-047464.hover.fill`, `motion.button.solid-047464.duration-1`, `motion.keyframes.pulse`,
  `motion.reveal.<digest>`. The same page yields the same names on every extraction; no model names
  anything.
* A per-kit cap. The web author's prompt lists every colour token of the kit
  (`web_theme_token_names`) and the brief agent reads every token row, so a kit's ~60-token
  vocabulary may grow by at most `MAX_MINTED_TOKENS` (and `MAX_MINTED_COLORS` colours); buttons are
  minted first, so the cap costs the least-used styles, and what it skips is named (LUMI0607).

Values the engine cannot hold are refused here with the engine's own rules
(`crates/lumen-core/src/brand.rs` `validate_style_tokens`); a mint never fails a kit's validation.
"""

from __future__ import annotations

import hashlib
import json
import re
import string
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from ..colorspace import hex_alpha
from ..evidence import EvidencePointer, MeasuredAnimation, MeasuredReveal, MeasuredStyle, MotionEvidence, StyleLook
from .emit import _color_value, _mode_value, _provenance
from .geometry import MEASURED_CONFIDENCE, PILL_RADIUS_PX, _shadow_value

# The capture helpers this module shares (`capture.motion`, `capture.geometry`) are imported where
# they are used: importing any capture module loads the capture package and httpx with it, and every
# `lumen_ingestion` import loads this normalizer (`test_import_pulls_no_pil_or_httpx`).

COMPONENT_ROOTS = {
    "button": "button", "link": "link", "nav_link": "navlink", "card": "card",
    "chip": "chip", "input": "input", "image": "image",
}
MOTION_ROOT = "motion"
TOKEN_ROOTS = frozenset({*COMPONENT_ROOTS.values(), MOTION_ROOT})
MAX_MINTED_TOKENS = 192
MAX_MINTED_COLORS = 48
STATES = ("hover", "pressed", "focus", "disabled")
SIDES = ("top", "right", "bottom", "left")
CORNERS = ("tl", "tr", "br", "bl")
STYLE_KEYWORD_PROPERTIES = frozenset({
    "text-transform", "text-decoration-line", "text-decoration-thickness", "text-underline-offset",
    "cursor", "border-style", "outline-style", "transition-property", "filter", "box-shadow",
})
_KEYWORD = re.compile(r"[A-Za-z0-9 ,.()%#+\-/]{1,200}")
_EASING_WORDS = frozenset({"linear", "ease", "ease-in", "ease-out", "ease-in-out", "step-start", "step-end"})
_MATRIX = re.compile(r"(?:matrix|matrix3d)\([0-9 ,.\-e]+\)")
_PROPERTY = re.compile(r"^(?:all|[a-z-]{1,60})$")
_DIRECTIONS = frozenset({"normal", "reverse", "alternate", "alternate-reverse"})
_FILL_MODES = frozenset({"none", "forwards", "backwards", "both"})
_SVG_BANNED = ("<script", "javascript:", "url(", "href", "<foreignobject", "<!", "<?", "<style", "<use", "<image", "<a ", "<a>")
#: The engine's `has_event_attribute`: an `on<letters>` attribute counts after whitespace, a `/` or a
#: quote, with only whitespace before its `=`. Whitespace is HTML's (and Rust's `is_ascii_whitespace`):
#: never `\s`, which also matches \x0b and Unicode spaces.
_EVENT_ATTRIBUTE = re.compile(r"[ \t\n\r\x0c/\"']on[a-z]+[ \t\n\r\x0c]*=")
#: The engine lowercases ASCII only (`to_ascii_lowercase`); `str.lower` would also fold non-ASCII.
_ASCII_LOWER = str.maketrans(string.ascii_uppercase, string.ascii_lowercase)
_SLUG = re.compile(r"[^a-z0-9]+")
#: A side, corner or ordinal suffix: `padding-top`, `radius-tl`, `shadow-1` and `duration-2` are the
#: slot kinds `padding`, `radius`, `shadow` and `duration`.
_SLOT_SUFFIX = re.compile(r"-(?:top|right|bottom|left|tl|tr|br|bl|\d+)$")
#: Values a rest look carries that are no choice of the brand's; never minted at rest. A rest
#: `text-decoration-line: none` IS a choice (the browser underlines links), so it is minted.
_REST_DEFAULTS = {"text-transform": {"none"}, "cursor": {"auto", "default"}, "filter": {"none"}}
_FAMILY_PREFERENCE = {
    "fill": ("surface.", "palette.", "border.", "text."),
    "label": ("text.", "surface.", "palette.", "border."),
    "border": ("border.", "text.", "surface.", "palette."),
    "outline": ("focus.", "border.", "text.", "surface."),
    "icon-color": ("text.", "surface.", "palette.", "border."),
    # A pill is the kit's fully-round radius, not another 9999px token that sorts first (`radius.badge`).
    "radius": ("radius.full",),
}
#: Groups whose engine token has a `role` field (shadows and styles have none).
_ROLE_BY_GROUP = {
    "colors": "component", "spacing": "spacing", "radii": "radius", "stroke_widths": "stroke",
    "opacity": "visibility", "numbers": "dimension", "typography": "component",
}
_SHADOW_POINTER = EvidencePointer(source="website", locator="component style box-shadow")


def is_component_token(name: str) -> bool:
    """A token this module mints (`button.*`, `link.*`, … `motion.*`)."""
    return str(name).split(".", 1)[0] in TOKEN_ROOTS


def _slot_kind(name: str) -> str:
    """The kind of slot a name is for: `button.solid-047464.hover.fill` → `fill`."""
    return _SLOT_SUFFIX.sub("", name.rsplit(".", 1)[-1])


def _component(name: str) -> str:
    """The component a name is for: its first segment, or its second under `motion.`.

    `button.solid-047464.hover.fill` → `button`; `motion.button.solid-047464.duration-1` → `button`.
    """
    parts = name.split(".")
    return parts[1] if parts[0] == MOTION_ROOT else parts[0]


def keyword_ok(prop: str, value: object) -> bool:
    return (
        prop in STYLE_KEYWORD_PROPERTIES and isinstance(value, str) and bool(_KEYWORD.fullmatch(value))
        and bool(value.strip())
        and "url(" not in value.lower() and "var(" not in value.lower() and "expression" not in value.lower()
        and (prop != "box-shadow" or value == "none")
    )


def easing_ok(function: object) -> bool:
    from ..capture.motion import safe_style_value

    return isinstance(function, str) and (
        function in _EASING_WORDS
        or (function.startswith(("cubic-bezier(", "steps(", "linear(")) and function.endswith(")")
            and len(function) <= 400 and safe_style_value(function))
    )


def transform_ok(value: object) -> bool:
    return value == "none" or (isinstance(value, str) and len(value) <= 400 and bool(_MATRIX.fullmatch(value)))


def glyph_ok(text: object) -> bool:
    return isinstance(text, str) and 1 <= len(text) <= 4 and not any(
        c in "<>&\"'" or ord(c) < 32 or unicodedata.category(c) == "Cc" for c in text
    )


def svg_ok(markup: object) -> bool:
    from ..capture.motion import MAX_ICON_SVG_BYTES

    if not isinstance(markup, str) or len(markup.encode()) > MAX_ICON_SVG_BYTES:
        return False
    lower = markup.translate(_ASCII_LOWER)
    trimmed = lower.strip()
    return (
        trimmed.startswith("<svg") and trimmed.endswith("</svg>")
        and not any(bad in lower for bad in _SVG_BANNED) and not _EVENT_ATTRIBUTE.search(lower)
    )


def _px(value: float) -> dict:
    return {"kind": "number", "unit": "px", "value": round(float(value), 2)}


def _ratio(value: float) -> dict:
    return {"kind": "number", "unit": "ratio", "value": round(float(value), 4)}


def _keyword(prop: str, value: object) -> dict | None:
    return {"kind": "keyword", "property": prop, "value": value} if keyword_ok(prop, value) else None


def _same(group: str, a: Any, b: Any) -> bool:
    """Exact equality of two token values, as the engine stores them."""
    if not isinstance(a, dict) or not isinstance(b, dict):
        return False
    if group == "colors":
        return a.get("kind") == b.get("kind") == "hex" and str(a.get("value")).upper() == str(b.get("value")).upper()
    if a.get("kind") == b.get("kind") == "number":
        return a.get("unit") == b.get("unit") and float(a.get("value", "nan")) == float(b.get("value", "nan"))
    if group == "typography":
        keys = ("font_family", "font_size", "font_weight", "line_height", "letter_spacing")
        return a.get("kind") == b.get("kind") == "style" and all(a.get(k) == b.get(k) for k in keys)
    if group == "shadows":
        numbers = ("x", "y", "blur", "spread")
        return all(float(a.get(k, 0)) == float(b.get(k, 0)) for k in numbers) and str(a.get("color")).upper() == str(b.get("color")).upper()
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


@dataclass
class _Minter:
    kit: dict
    minted: list[str] = field(default_factory=list)
    colors: int = 0
    dropped: list[str] = field(default_factory=list)

    def entries(self, group: str) -> dict:
        return self.kit.setdefault("tokens", {}).setdefault(group, {})

    def name(self, path: str, group: str, value: dict, *, pointer: str, slot: str = "", description: str | None = None) -> str | None:
        """The token holding `value`: an existing exact match, a new token at `path`, or None (cap)."""
        existing = self._exact(group, value, slot, path)
        if existing:
            return existing
        if len(self.minted) >= MAX_MINTED_TOKENS or (group == "colors" and self.colors >= MAX_MINTED_COLORS):
            self.dropped.append(path)
            return None
        entries = self.entries(group)
        name, suffix = path, 2
        while name in entries:
            name, suffix = f"{path}-{suffix}", suffix + 1
        entry: dict[str, Any] = {"value": _mode_value(value, {})}
        if group in _ROLE_BY_GROUP:
            entry["role"] = _ROLE_BY_GROUP[group]
        entry["description"] = description
        entry["provenance"] = _provenance(pointer, MEASURED_CONFIDENCE)
        entries[name] = entry
        self.minted.append(name)
        if group == "colors":
            self.colors += 1
        return name

    def _exact(self, group: str, value: dict, slot: str, path: str) -> str | None:
        prefs = _FAMILY_PREFERENCE.get(slot, ())
        kind, component = _slot_kind(path), _component(path)
        matches = [
            name for name, entry in self.entries(group).items()
            if isinstance(entry, dict) and _same(group, (entry.get("value") or {}).get("default"), value)
            # The type scale's size steps live in `numbers` too; a button's height is never one.
            and not (group == "numbers" and name.startswith("type."))
            # A minted token names only its own kind of slot of its own component (a link's text is
            # not a button's label); the kit's own tokens serve any slot of any component.
            and not (is_component_token(name) and (_slot_kind(name) != kind or _component(name) != component))
        ]
        if not matches:
            return None

        def rank(name: str) -> tuple:
            family = next((i for i, prefix in enumerate(prefs) if name.startswith(prefix)), len(prefs))
            return (is_component_token(name), family, name)

        return min(matches, key=rank)


def _font(look: StyleLook, fonts: dict[str, str]) -> dict | None:
    if not (look.font_family and look.font_size and look.font_weight):
        return None
    size, weight = round(look.font_size, 2), int(round(look.font_weight))
    if size <= 0 or not 0 < weight <= 1000:
        return None
    return {
        "kind": "style", "font_family": look.font_family, "font_size": size, "font_weight": weight,
        "line_height": round(look.line_height / size, 2) if look.line_height else None,
        "letter_spacing": round((look.letter_spacing or 0.0) / size, 3), "color": None,
        "font_asset": fonts.get(look.font_family.lower()),
    }


def _slots(look: StyleLook, *, at_rest: bool, fonts: dict[str, str]) -> list[tuple[str, str, dict]]:
    """`(slot, group, value)` for every measured value of one look, in a fixed order."""
    out: list[tuple[str, str, dict]] = []

    def color(slot: str, hex_value: str | None) -> None:
        # At rest a fully transparent colour paints nothing. In a state it is the state clearing the
        # rest colour (the capture records that as `#00000000`), which the state must draw.
        if hex_value and (hex_alpha(hex_value) > 0 or not at_rest):
            out.append((slot, "colors", _color_value(hex_value)))

    color("fill", look.background)
    color("label", look.label_color or look.color)
    # A rest look carries a border colour only when a border is drawn and visible (a 1px
    # transparent border is no border); a state may recolour or re-weigh the rest border.
    color("border", look.border_color)
    widths = look.border_width
    if (look.border_color or not at_rest) and any(w > 0 for w in widths) \
            and (look.border_style or "solid") not in ("none", "hidden"):
        if len(set(widths)) == 1:
            out.append(("border-width", "stroke_widths", _px(widths[0])))
        else:
            out.extend((f"border-width-{side}", "stroke_widths", _px(w)) for side, w in zip(SIDES, widths))
        style = _keyword("border-style", look.border_style) if look.border_style else None
        if style:
            out.append(("border-style", "styles", style))
    if look.pill:
        out.append(("radius", "radii", _px(PILL_RADIUS_PX)))
    elif look.radius:
        if len(set(look.radius)) == 1:
            out.append(("radius", "radii", _px(look.radius[0])))
        else:
            out.extend((f"radius-{corner}", "radii", _px(r)) for corner, r in zip(CORNERS, look.radius))
    out.extend((f"padding-{side}", "spacing", _px(v)) for side, v in zip(SIDES, look.padding))
    if at_rest and look.height:
        out.append(("height", "numbers", _px(look.height)))
    if look.gap is not None:
        out.append(("gap", "spacing", _px(look.gap)))
    font = _font(look, fonts)
    if font:
        out.append(("font", "typography", font))
    for slot, prop, value in (
        ("case", "text-transform", look.text_transform), ("decoration", "text-decoration-line", look.decoration_line),
        ("cursor", "cursor", look.cursor), ("filter", "filter", look.filter),
    ):
        if value is None or (at_rest and value in _REST_DEFAULTS.get(prop, ())):
            continue
        keyword = _keyword(prop, value)
        if keyword:
            out.append((slot, "styles", keyword))
    for slot, prop, value in (
        ("decoration-thickness", "text-decoration-thickness", look.decoration_thickness),
        ("underline-offset", "text-underline-offset", look.underline_offset),
    ):
        if value is None or (at_rest and value == "auto"):
            continue
        if value.endswith("px"):
            try:
                out.append((slot, "numbers", _px(float(value[:-2]))))
                continue
            except ValueError:
                pass
        keyword = _keyword(prop, value)
        if keyword:
            out.append((slot, "styles", keyword))
    if look.box_shadow == "none":
        out.append(("shadow", "styles", {"kind": "keyword", "property": "box-shadow", "value": "none"}))
    elif look.box_shadow:
        from ..capture.geometry import _parse_box_shadow

        for index, sample in enumerate(_parse_box_shadow(look.box_shadow, _SHADOW_POINTER), 1):
            out.append((f"shadow-{index}", "shadows", _shadow_value(sample)))
    if look.opacity is not None and not (at_rest and look.opacity == 1):
        out.append(("opacity", "opacity", _ratio(look.opacity)))
    if look.transform and transform_ok(look.transform) and not (at_rest and look.transform == "none"):
        out.append(("transform", "styles", {"kind": "transform", "value": look.transform}))
    if look.outline_style not in (None, "none", "auto"):
        color("outline", look.outline_color)
        if look.outline_width is not None:
            out.append(("outline-width", "stroke_widths", _px(look.outline_width)))
        style = _keyword("outline-style", look.outline_style)
        if style:
            out.append(("outline-style", "styles", style))
        if look.outline_offset is not None:
            out.append(("outline-offset", "numbers", _px(look.outline_offset)))
    if look.icon_color and (not at_rest or look.icon_color != (look.label_color or look.color)):
        color("icon-color", look.icon_color)
    if look.icon_transform and transform_ok(look.icon_transform):
        out.append(("icon-transform", "styles", {"kind": "transform", "value": look.icon_transform}))
    if look.icon_opacity is not None and not (at_rest and look.icon_opacity == 1):
        out.append(("icon-opacity", "opacity", _ratio(look.icon_opacity)))
    return out


def _state_font(rest: StyleLook, state: StyleLook, fonts: dict[str, str]) -> dict | None:
    """A state's font when the state changes one of its parts (a bolder hover)."""
    changed = {k: getattr(state, k) for k in ("font_family", "font_size", "font_weight", "line_height", "letter_spacing") if getattr(state, k) is not None}
    return _font(rest.model_copy(update=changed), fonts) if changed else None


def _mint_style(m: _Minter, style: MeasuredStyle, fonts: dict[str, str], page: str) -> dict:
    root = COMPONENT_ROOTS[style.surface]
    slug = style.variant.replace(".", "-")
    base, stem = f"{root}.{slug}", f"{MOTION_ROOT}.{root}.{slug}"
    where = f"website:{page} :: {style.surface} {style.variant}"
    recipe: dict[str, Any] = {
        "component": style.surface, "variant": style.variant, "count": style.count, "probed": style.probed,
        "source": f"website:{page}", "rest": {}, "states": {}, "motion": [], "icon": None, "browser_focus_ring": False,
    }
    for slot, group, value in _slots(style.rest, at_rest=True, fonts=fonts):
        token = m.name(f"{base}.{slot}", group, value, pointer=f"{where} rest {slot}", slot=slot)
        if token:
            recipe["rest"][slot] = token
    for state in STATES:
        look = getattr(style, state)
        if look is None:
            continue
        if state == "focus" and look.browser_focus_ring:
            recipe["browser_focus_ring"] = True
        slots: dict[str, str] = {}
        pairs = [s for s in _slots(look, at_rest=False, fonts=fonts) if s[0] != "font"]
        font = _state_font(style.rest, look, fonts)
        if font:
            pairs.append(("font", "typography", font))
        for slot, group, value in pairs:
            token = m.name(f"{base}.{state}.{slot}", group, value, pointer=f"{where} {state} {slot}", slot=slot)
            if token:
                slots[slot] = token
        if slots:
            recipe["states"][state] = slots
    for index, transition in enumerate(style.transitions, 1):
        if not _PROPERTY.match(transition.property) or not easing_ok(transition.easing):
            continue
        if not 0 < transition.duration_ms <= 60_000 or not 0 <= transition.delay_ms <= 60_000:
            continue
        at = f"{where} transition {transition.property}"
        duration = m.name(f"{stem}.duration-{index}", "styles", {"kind": "duration", "ms": transition.duration_ms}, pointer=at)
        easing = m.name(f"{stem}.easing-{index}", "styles", {"kind": "easing", "function": transition.easing}, pointer=at)
        delay = (
            m.name(f"{stem}.delay-{index}", "styles", {"kind": "duration", "ms": transition.delay_ms}, pointer=at)
            if transition.delay_ms > 0 else None
        )
        if duration and easing:
            recipe["motion"].append({
                "target": transition.target, "property": transition.property,
                "duration": duration, "easing": easing, "delay": delay,
            })
    icon, value = style.icon, None
    if icon and icon.kind == "glyph" and glyph_ok(icon.glyph):
        value = {"kind": "glyph", "text": icon.glyph}
    elif icon and icon.kind == "svg" and svg_ok(icon.svg) and icon.width and icon.height \
            and 1 <= icon.width <= 256 and 1 <= icon.height <= 256:
        value = {"kind": "svg", "markup": icon.svg, "width": round(icon.width, 2), "height": round(icon.height, 2)}
    if icon and value:
        token = m.name(f"{base}.icon", "styles", value, pointer=f"{where} icon", slot="icon")
        if token:
            recipe["icon"] = {"token": token, "position": icon.position}
    return recipe


def _slug(name: str, used: set[str]) -> str:
    slug = _SLUG.sub("-", name.lower()).strip("-")[:40] or "animation"
    candidate, n = slug, 2
    while candidate in used:
        candidate, n = f"{slug}-{n}", n + 1
    used.add(candidate)
    return candidate


def _iterations_ok(value: str) -> bool:
    if value == "infinite":
        return True
    try:
        return 0 < float(value) <= 1000
    except ValueError:
        return False


def _mint_animation(m: _Minter, animation: MeasuredAnimation, used: set[str], page: str) -> str | None:
    if (
        len(animation.frames) < 2 or not easing_ok(animation.easing) or not _iterations_ok(animation.iterations)
        or animation.direction not in _DIRECTIONS or animation.fill_mode not in _FILL_MODES
        or not 0 < animation.duration_ms <= 60_000 or not 0 <= animation.delay_ms <= 60_000
    ):
        return None
    from ..capture.motion import KEYFRAME_PROPERTIES, safe_style_value

    frames = [
        {"offset": step.offset, "declarations": {k: v for k, v in step.declarations.items() if k in KEYFRAME_PROPERTIES and safe_style_value(v)}}
        for step in animation.frames
    ]
    if any(not frame["declarations"] for frame in frames):
        return None
    slug = _slug(animation.name, used)
    where = f"website:{page} :: animation {animation.name}"
    keyframes = m.name(f"motion.keyframes.{slug}", "styles", {"kind": "keyframes", "frames": frames}, pointer=f"{where} keyframes")
    duration = m.name(f"motion.animation.{slug}.duration", "styles", {"kind": "duration", "ms": animation.duration_ms}, pointer=f"{where} duration")
    easing = m.name(f"motion.animation.{slug}.easing", "styles", {"kind": "easing", "function": animation.easing}, pointer=f"{where} easing")
    delay = (
        m.name(f"motion.animation.{slug}.delay", "styles", {"kind": "duration", "ms": animation.delay_ms}, pointer=f"{where} delay")
        if animation.delay_ms > 0 else None
    )
    if not (keyframes and duration and easing):
        return None
    plural = "s" if animation.count != 1 else ""
    return m.name(
        f"motion.animation.{slug}", "styles",
        {"kind": "animation", "keyframes": keyframes, "duration": duration, "easing": easing, "delay": delay,
         "iterations": animation.iterations, "direction": animation.direction, "fill_mode": animation.fill_mode},
        pointer=where, description=f"{animation.count} element{plural}: {animation.where}",
    )


def _mint_reveal(m: _Minter, reveal: MeasuredReveal, page: str) -> str | None:
    if not easing_ok(reveal.easing) or not 0 < reveal.duration_ms <= 60_000:
        return None
    if reveal.from_transform is not None and not transform_ok(reveal.from_transform):
        return None
    digest = hashlib.sha256(
        json.dumps([reveal.from_opacity, reveal.from_transform, reveal.duration_ms, reveal.easing]).encode()
    ).hexdigest()[:8]
    base = f"motion.reveal.{digest}"
    where = f"website:{page} :: reveal {reveal.where}"
    opacity = (
        m.name(f"{base}.from-opacity", "opacity", _ratio(reveal.from_opacity), pointer=f"{where} from-opacity")
        if reveal.from_opacity is not None and reveal.from_opacity < 1 else None
    )
    transform = (
        m.name(f"{base}.from-transform", "styles", {"kind": "transform", "value": reveal.from_transform}, pointer=f"{where} from-transform")
        if reveal.from_transform else None
    )
    duration = m.name(f"{base}.duration", "styles", {"kind": "duration", "ms": reveal.duration_ms}, pointer=f"{where} duration")
    easing = m.name(f"{base}.easing", "styles", {"kind": "easing", "function": reveal.easing}, pointer=f"{where} easing")
    if not (duration and easing) or not (opacity or transform):
        return None
    plural = "s" if reveal.count != 1 else ""
    return m.name(
        base, "styles",
        {"kind": "reveal", "from_opacity": opacity, "from_transform": transform, "duration": duration, "easing": easing},
        pointer=where, description=f"{reveal.count} element{plural}: {reveal.where}",
    )


@dataclass
class MintResult:
    #: The `measured_components` payload (validated in `lumen_ingestion.measured_components`), or None.
    section: dict | None
    minted: list[str]
    diagnostics: list[dict]


def mint_component_tokens(kit: dict, styles: list[MeasuredStyle], motion: MotionEvidence) -> MintResult:
    """Mint every measured value into `kit["tokens"]` (in place) and return the measured recipes."""
    if not styles and not motion.animations and not motion.reveals and not motion.scripted:
        return MintResult(None, [], [])
    pointers = [s.pointer for s in styles] + [a.pointer for a in motion.animations] + [r.pointer for r in motion.reveals] + [n.pointer for n in motion.scripted]
    page = pointers[0].locator.split(" :: ", 1)[0] if pointers else ""
    fonts = {
        str(font.get("family") or "").lower(): key
        for key, font in ((kit.get("assets") or {}).get("fonts") or {}).items()
        if isinstance(font, dict) and font.get("family")
    }
    minter = _Minter(kit)
    recipes = [_mint_style(minter, style, fonts, page) for style in styles if style.surface in COMPONENT_ROOTS]
    used: set[str] = set()
    animations = [
        name for animation in sorted(motion.animations, key=lambda a: a.name)
        if (name := _mint_animation(minter, animation, used, page))
    ]
    reveal_order = sorted(motion.reveals, key=lambda r: (r.from_opacity is None, r.from_opacity or 0.0, r.from_transform or "", r.duration_ms, r.easing))
    reveals = sorted(name for reveal in reveal_order if (name := _mint_reveal(minter, reveal, page)))
    diagnostics: list[dict] = []
    if minter.dropped:
        diagnostics.append({
            "code": "LUMI0607", "severity": "warning",
            "message": (
                f"{len(minter.dropped)} measured value(s) were not minted as tokens (the kit's cap of "
                f"{MAX_MINTED_TOKENS} tokens, {MAX_MINTED_COLORS} colours): " + ", ".join(minter.dropped[:8])
            ),
        })
    section = {
        "schema_version": 1, "source": f"website:{page}", "styles": recipes,
        "motion": {
            "animations": animations, "reveals": reveals,
            "scripted": [{"kind": note.kind, "where": note.where} for note in motion.scripted],
        },
    }
    return MintResult(section, list(minter.minted), diagnostics)
