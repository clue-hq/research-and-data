"""CSS/DOM analysis: ``SiteSnapshot`` → pre-asset-ingest evidence pieces.

Pure: works on any snapshot (static or rendered) with no network. Produces a
``ParsedSite`` whose lists mirror ``BrandEvidence`` fields but reference download
sha256s instead of asset ids (the evidence builder ingests those into assets).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import tinycss2
from clue_core.normalize import canonical_workspace_name
from selectolax.parser import HTMLParser

from ..css_color4 import COLOR4_FUNCTIONS, color4_to_hex
from .budget import (
    MAX_ASSET_COUNT,
    MAX_STATE_STYLE_COUNT,
    STATE_BUDGET_DIAGNOSTIC_CODE,
    budget_diagnostic,
)
from .cssurl import iter_css_urls
from .declared_roles import DeclaredRole, declared_roles
from .imgsrc import background_image_urls, image_source_ladder
from .snapshot import SiteSnapshot
from .svg_looks import bake_svg_looks, look_hides

# --- parsed pieces (internal, pre-asset-ingest) ---------------------------------


@dataclass
class ParsedColor:
    value: str
    weight: float
    theme: str
    role_hints: list[str]
    name: str | None
    locator: str


@dataclass
class ParsedType:
    label: str
    family: str | None
    weight: int | None
    size_px: float | None
    line_height: float | None
    letter_spacing: float | None
    locator: str
    color: str | None = None
    background: str | None = None
    area: float | None = None
    #: Which computed sample it came from, so the same element can be read at other widths.
    sample_index: int | None = None


@dataclass
class ParsedFontFace:
    weight: int | None
    style: str
    source_url: str | None
    format: str | None
    # EVERY ``src`` rung this face declares, best-format first (clone-fidelity F0.2 fix
    # round 1). ``source_url`` stays the ONE rung the kit binds — the browser would pick the
    # best format it supports and so do we — but F2 rewrites a captured ``@font-face`` block
    # verbatim, so every rung a browser might pick has to resolve on our store. Defaulted so
    # a hand-built face (fixtures, the PDF path) stays valid.
    source_urls: list[str] = field(default_factory=list)


@dataclass
class ParsedFont:
    family: str
    role_hint: str
    faces: list[ParsedFontFace]
    fallback_stack: list[str]
    license_hint: str | None
    locator: str


@dataclass
class ParsedAsset:
    """A logo or image referencing a download by sha256 (or an inline SVG)."""

    sha256: str | None
    source_url: str | None
    kind: str  # "logo" | "image" | "og_image"
    usage_hint: str | None = None
    background_hint: str | None = None
    width: int | None = None
    height: int | None = None
    kind_hint: str | None = None
    locator: str = ""
    alt: str | None = None
    surrounding_text: str | None = None
    placement: str | None = None


@dataclass
class ParsedNarrative:
    brand_name: str | None = None
    url: str | None = None
    tagline: str | None = None
    summary_facts: list[str] = field(default_factory=list)
    text_excerpt: str | None = None


@dataclass
class ParsedStateStyle:
    """One ``:hover``/``:focus``/``:active``/``:disabled`` rule on an interactive selector.

    Mirrors ``evidence.StateStyle``; only properties the rule actually declares are set.
    """

    selector: str
    state: str
    scheme: str = "light"
    background: str | None = None
    color: str | None = None
    border_color: str | None = None
    box_shadow: str | None = None
    opacity: float | None = None
    text_decoration: str | None = None
    locator: str = ""

    def declares_anything(self) -> bool:
        return any(
            value is not None
            for value in (
                self.background,
                self.color,
                self.border_color,
                self.box_shadow,
                self.opacity,
                self.text_decoration,
            )
        )


@dataclass
class ParsedSite:
    colors: list[ParsedColor] = field(default_factory=list)
    type_samples: list[ParsedType] = field(default_factory=list)
    fonts: list[ParsedFont] = field(default_factory=list)
    logos: list[ParsedAsset] = field(default_factory=list)
    images: list[ParsedAsset] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)  # download sha256s
    narrative: ParsedNarrative = field(default_factory=ParsedNarrative)
    custom_props: dict[str, str] = field(default_factory=dict)
    # Source-truth styling (clone-fidelity F0.3).
    #: `--…: value` overrides declared inside `@media (prefers-color-scheme: dark)`.
    dark_custom_props: dict[str, str] = field(default_factory=dict)
    #: At most one per anchor role — see `declared_roles.declared_roles`.
    declared_roles: list[DeclaredRole] = field(default_factory=list)
    state_styles: list[ParsedStateStyle] = field(default_factory=list)
    diagnostics: list[dict] = field(default_factory=list)
    #: Responsive brand type: the capture's own width and the type samples at each narrower width.
    type_capture_width: int | None = None
    type_widths: list[tuple[int, list[ParsedType]]] = field(default_factory=list)


# --- color parsing --------------------------------------------------------------

_GENERIC_FAMILIES = {
    "serif",
    "sans-serif",
    "monospace",
    "cursive",
    "fantasy",
    "system-ui",
    "ui-sans-serif",
    "ui-serif",
    "ui-monospace",
    "-apple-system",
    "blinkmacsystemfont",
    "inherit",
    "initial",
    "unset",
}

_SKIP_COLOR_KEYWORDS = {"transparent", "inherit", "currentcolor", "unset", "none", "initial"}

_NAMED_COLORS = {
    "white": "#FFFFFF",
    "black": "#000000",
    "red": "#FF0000",
    "green": "#008000",
    "blue": "#0000FF",
    "gray": "#808080",
    "grey": "#808080",
    "silver": "#C0C0C0",
}


# A custom-property chain deeper than this is a cycle, not a real color.
_MAX_VAR_HOPS = 24
# Diagnostics are a report, not a log: cap how many skipped colors we name.
_MAX_COLOR_SKIPS_REPORTED = 8


def _clamp8(value: float) -> int:
    return max(0, min(255, round(value)))


def _hsl_to_hex(h: float, s: float, lightness: float) -> str:
    s /= 100.0
    lightness /= 100.0
    c = (1 - abs(2 * lightness - 1)) * s
    hp = (h % 360) / 60.0
    x = c * (1 - abs(hp % 2 - 1))
    if hp < 1:
        r, g, b = c, x, 0.0
    elif hp < 2:
        r, g, b = x, c, 0.0
    elif hp < 3:
        r, g, b = 0.0, c, x
    elif hp < 4:
        r, g, b = 0.0, x, c
    elif hp < 5:
        r, g, b = x, 0.0, c
    else:
        r, g, b = c, 0.0, x
    m = lightness - c / 2
    return "#%02X%02X%02X" % (
        _clamp8((r + m) * 255),
        _clamp8((g + m) * 255),
        _clamp8((b + m) * 255),
    )


_VAR_RE = re.compile(r"var\(\s*(--[\w-]+)\s*(?:,\s*([^)]+))?\)", re.IGNORECASE)


def parse_color_value(
    raw: str,
    custom_props: dict[str, str],
    *,
    diagnostics: list[dict] | None = None,
    _depth: int = 0,
    _seen: tuple[str, ...] = (),
) -> str | None:
    """Parse a CSS color token to #RRGGBB(AA). var() hops resolved (bounded).

    **This function never raises.** A color we cannot read is one swatch
    skipped, never a failed ingestion job: every unreadable value returns
    ``None`` and, when a ``diagnostics`` sink is supplied, records why. That
    matters because a single modern-syntax color used to sink whole sites —
    apollo.io served ``rgb(15 23 42 / var(--tw-text-opacity))`` and the bare
    ``float()`` under the alpha channel failed the job 4/4 URLs (``LUMI0401``).

    ``None`` is also the answer for keywords we deliberately skip
    (transparent/inherit/currentColor/unset); those are not diagnosed.
    """
    text = raw.strip()
    lowered = text.lower()
    if lowered in _SKIP_COLOR_KEYWORDS:
        return None

    var_match = _VAR_RE.match(text)
    if var_match:
        # A custom property may point at another one. Real sites ship cyclic chains
        # (cursor.com/about does), so the walk carries the chain it has already walked:
        # revisiting a name IS the cycle, caught at the hop that closes it rather than 24
        # frames later, and named in full so a human can go delete it. `_MAX_VAR_HOPS`
        # stays as the backstop for a chain that is merely absurd rather than cyclic —
        # unbounded recursion here is a RecursionError, i.e. another whole-job failure.
        name = var_match.group(1)
        if name in _seen or _depth >= _MAX_VAR_HOPS:
            chain = " → ".join((*_seen, name))
            _record_color_skip(
                diagnostics,
                f"custom-property chain did not resolve (cycle?): {chain}",
            )
            return None
        resolved = custom_props.get(name)
        if resolved is None:
            fallback = var_match.group(2)
            if fallback is None:
                return None
            return parse_color_value(
                fallback,
                custom_props,
                diagnostics=diagnostics,
                _depth=_depth + 1,
                _seen=(*_seen, name),
            )
        return parse_color_value(
            resolved,
            custom_props,
            diagnostics=diagnostics,
            _depth=_depth + 1,
            _seen=(*_seen, name),
        )

    if lowered in _NAMED_COLORS:
        return _NAMED_COLORS[lowered]

    if text.startswith("#"):
        body = text[1:]
        if len(body) in (3, 4):
            body = "".join(ch * 2 for ch in body)
        if len(body) in (6, 8):
            try:
                int(body, 16)
                return "#" + body.upper()
            except ValueError:
                return None
        return None

    # Both the legacy comma form `rgb(15, 23, 42)` and the modern
    # space-separated/slash form `rgb(15 23 42 / 60%)` split the same way.
    rgb_body = _function_body(text, ("rgba", "rgb"))
    if rgb_body is not None:
        parts, alpha_slot = _split_color_args(rgb_body)
        if len(parts) >= 3:
            try:
                comps = [_parse_channel(parts[i]) for i in range(3)]
            except ValueError:
                _record_color_skip(diagnostics, f"unreadable rgb() channels: {text}")
                return None
            hex6 = "#%02X%02X%02X" % (comps[0], comps[1], comps[2])
            if alpha_slot is None and len(parts) >= 4:
                alpha_slot = parts[3]
            if alpha_slot is not None:
                alpha = _alpha_or_opaque(alpha_slot, text, custom_props, diagnostics)
                if alpha < 255:
                    return hex6 + "%02X" % alpha
            return hex6
        _record_color_skip(diagnostics, f"unreadable rgb() value: {text}")
        return None

    hsl_body = _function_body(text, ("hsla", "hsl"))
    if hsl_body is not None:
        parts, alpha_slot = _split_color_args(hsl_body)
        if len(parts) >= 3:
            try:
                h = float(parts[0].rstrip("deg"))
                s = float(parts[1].rstrip("%"))
                lightness = float(parts[2].rstrip("%"))
            except ValueError:
                _record_color_skip(diagnostics, f"unreadable hsl() channels: {text}")
                return None
            hex6 = _hsl_to_hex(h, s, lightness)
            if alpha_slot is None and len(parts) >= 4:
                alpha_slot = parts[3]
            if alpha_slot is not None:
                alpha = _alpha_or_opaque(alpha_slot, text, custom_props, diagnostics)
                if alpha < 255:
                    return hex6 + "%02X" % alpha
            return hex6
        _record_color_skip(diagnostics, f"unreadable hsl() value: {text}")
        return None

    for name in COLOR4_FUNCTIONS:
        body = _function_body(text, (name,))
        if body is None:
            continue
        parts, alpha_slot = _split_color_args(body)
        # These functions have no legacy comma syntax (Chromium refuses `oklch(0.5, 0.1, 180)`).
        # Only the channel half is checked: the alpha slot may hold `var(--o, 0.5)`.
        hex6 = None if "," in body.partition("/")[0] else color4_to_hex(name, parts)
        if hex6 is None:
            _record_color_skip(diagnostics, f"unreadable {name}() value: {text}")
            return None
        if alpha_slot is not None:
            alpha = _alpha_or_opaque(alpha_slot, text, custom_props, diagnostics)
            if alpha < 255:
                return hex6 + "%02X" % alpha
        return hex6

    return None


def _function_body(text: str, names: tuple[str, ...]) -> str | None:
    """The argument text of the leading ``<name>( … )`` call in ``text``, else ``None``.

    Paren-BALANCED rather than the old ``[^)]+``, because the alpha slot routinely holds a
    nested call — Tailwind's ``rgb(15 23 42 / var(--tw-text-opacity))`` — and stopping at the
    first ``)`` cut that var in half. Balanced-but-leading (rather than anchored to the end
    of the string) so a value carrying trailing junk still yields its first color, exactly as
    the old permissive regex did.
    """
    lowered = text.lower()
    for name in names:
        if not lowered.startswith(name + "("):
            continue
        start = len(name) + 1
        depth = 1
        for index in range(start, len(text)):
            char = text[index]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    return text[start:index]
        return None  # unclosed call — unreadable, never a guess
    return None


def _split_color_args(body: str) -> tuple[list[str], str | None]:
    """Split an ``rgb()``/``hsl()`` argument list into channels and the alpha SLOT.

    The modern slash form's alpha is taken verbatim rather than tokenized, because the thing
    living in that slot is routinely a whole function call: Tailwind serves
    ``rgb(15 23 42 / var(--tw-text-opacity))``, and splitting on commas as well would tear
    ``var(--o, 0.5)`` in half and lose the fallback that makes it readable. Returns
    ``(channel tokens, alpha slot or None)``; a legacy fourth comma-separated channel stays
    an ordinary token and is handled by the caller.
    """
    head, slash, tail = body.strip().partition("/")
    tokens = [token for token in re.split(r"[,\s]+", head.strip()) if token]
    return tokens, tail.strip() if slash else None


def _parse_channel(token: str) -> int:
    token = token.strip()
    if token.endswith("%"):
        return _clamp8(float(token[:-1]) / 100.0 * 255)
    return _clamp8(float(token))


def _parse_alpha(token: str) -> int:
    token = token.strip()
    if token.endswith("%"):
        return _clamp8(float(token[:-1]) / 100.0 * 255)
    return _clamp8(float(token) * 255)


def _resolve_var_scalar(
    token: str, custom_props: dict[str, str], _seen: tuple[str, ...] = ()
) -> str | None:
    """Follow a ``var()`` chain to the non-``var`` text it points at, or ``None``.

    The color path resolves vars on its way to a hex; the ALPHA slot needs the same walk but
    ends at a plain number, so it cannot reuse `parse_color_value`. Same cycle discipline:
    the chain walked so far rides along, and revisiting a name ends the walk.
    """
    text = token.strip()
    for _ in range(_MAX_VAR_HOPS):
        match = _VAR_RE.match(text)
        if match is None:
            return text or None
        name = match.group(1)
        if name in _seen:
            return None
        _seen = (*_seen, name)
        resolved = custom_props.get(name)
        if resolved is None:
            fallback = match.group(2)
            if fallback is None:
                return None
            text = fallback.strip()
        else:
            text = resolved.strip()
    return None


def _alpha_or_opaque(
    token: str,
    source: str,
    custom_props: dict[str, str],
    diagnostics: list[dict] | None,
) -> int:
    """Read an alpha channel, falling back to fully opaque when it is unreadable.

    Tailwind serves `rgb(15 23 42 / var(--tw-text-opacity))`. When that custom
    property is one this page actually declares we now follow it and honour the
    real transparency (clone-fidelity F0.3 — reading a 50%-opaque overlay as
    solid is a visible clone defect).

    When it is not resolvable the three channels still carry the site's real
    color and only the alpha is unknown. Dropping the whole swatch there would
    throw away good brand evidence, so we keep the color and read it as opaque —
    which is also what the browser shows when the opacity var is unset.
    """
    try:
        return _parse_alpha(token)
    except (ValueError, TypeError):
        pass
    resolved = _resolve_var_scalar(token, custom_props)
    if resolved is not None and resolved != token.strip():
        try:
            return _parse_alpha(resolved)
        except (ValueError, TypeError):
            pass
    _record_color_skip(
        diagnostics, f"alpha channel unreadable, color read as opaque: {source}"
    )
    return 255


def _record_color_skip(diagnostics: list[dict] | None, message: str) -> None:
    """Record one unreadable color into an ingestion diagnostics sink.

    Bounded and deduped on purpose: a Tailwind site serves thousands of these
    and the diagnostics list is a report a human reads, not a log.
    """
    if diagnostics is None:
        return
    entry = {"code": "LUMI0511", "severity": "warning", "message": message[:240]}
    for existing in diagnostics:
        if existing.get("message") == entry["message"]:
            return
    if sum(1 for d in diagnostics if d.get("code") == "LUMI0511") >= _MAX_COLOR_SKIPS_REPORTED:
        return
    diagnostics.append(entry)


# --- selector role hints --------------------------------------------------------
#
# `_selector_role` — the selector-vocabulary weight table (body 5.0, headings
# 4.0, buttons 4.0, …) that let rule-text mentions elect palette colors — was
# DELETED 2026-08-30 (Phase-1 brand-color overhaul). It elected apollo.io's
# phone-widget focus ring as the brand. Election now belongs to the rendered
# census (`lumen_ingestion.census`); see `_parse_rule` for the retirement note.


# --- interaction states ---------------------------------------------------------
#
# A clone that paints a site's buttons the right color and then does nothing when the pointer
# lands on them is visibly not the site. The states are DECLARED in the stylesheet we already
# parse rule by rule, so F0.3 records them verbatim instead of leaving F2 to invent a hover.

#: Recognized states, in the order a selector carrying several is read. `hover` leads because
#: it is the state a clone most needs; `focus-visible` precedes `focus` so the modern form is
#: not swallowed by the older one.
_STATE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("hover", re.compile(r":hover(?![-\w])", re.IGNORECASE)),
    ("focus-visible", re.compile(r":focus-visible(?![-\w])", re.IGNORECASE)),
    ("focus", re.compile(r":focus(?![-\w])", re.IGNORECASE)),
    ("active", re.compile(r":active(?![-\w])", re.IGNORECASE)),
    ("disabled", re.compile(r":disabled(?![-\w])", re.IGNORECASE)),
)

#: Elements a user can actually interact with. Same vocabulary the retired
#: `_selector_role` table used, plus the form controls it never needed to name.
_INTERACTIVE_TAGS = frozenset(
    {"a", "button", "input", "select", "textarea", "summary", "option"}
)

#: Class fragments that mean "this is a control". Substring matches, mirroring the
#: `[class*="btn"]` selectors these sites are built from.
_INTERACTIVE_CLASS_FRAGMENTS = ("btn", "button", "cta")

#: Class WORDS that mean the same but are too short to substring-match safely (`.blink` is
#: not a link), so they are matched against the class's own hyphen/underscore-separated words.
_INTERACTIVE_CLASS_WORDS = frozenset({"link", "nav", "menu", "tab", "chip", "toggle"})


def _state_of(selector: str) -> str | None:
    for state, pattern in _STATE_PATTERNS:
        if pattern.search(selector):
            return state
    return None


def _is_interactive_selector(selector: str) -> bool:
    """Does this selector's SUBJECT name something a user interacts with?

    Only the rightmost compound is consulted: in ``.card a:hover`` the thing that hovers is
    the link, and in ``.card:hover .icon`` the thing being styled is an icon inside a hovered
    card — which is a card state, not a control state, and is deliberately not recorded.
    """
    compounds = [part for part in re.split(r"[\s>+~]+", selector.strip()) if part]
    if not compounds:
        return False
    subject = compounds[-1].lower()
    if _state_of(subject) is None:
        return False  # the state lives on an ancestor, not on the styled element
    tag = re.match(r"^[a-z][a-z0-9]*", subject)
    if tag and tag.group(0) in _INTERACTIVE_TAGS:
        return True
    if any(fragment in subject for fragment in _INTERACTIVE_CLASS_FRAGMENTS):
        return True
    words = {word for word in re.split(r"[^a-z0-9]+", subject) if word}
    return bool(words & _INTERACTIVE_CLASS_WORDS)


def _parse_opacity(value: str) -> float | None:
    text = value.strip().rstrip("%")
    try:
        number = float(text)
    except ValueError:
        return None
    if value.strip().endswith("%"):
        number /= 100.0
    return max(0.0, min(1.0, number))


def _collect_state_styles(
    parsed: ParsedSite,
    selectors: list[str],
    decls,
    theme: str,
    custom_props: dict[str, str],
    stylesheet_url: str,
) -> None:
    """Record every interaction state this rule declares, one record per selector."""
    for selector in selectors:
        state = _state_of(selector)
        if state is None or not _is_interactive_selector(selector):
            continue
        record = ParsedStateStyle(
            selector=selector,
            state=state,
            scheme="dark" if theme == "dark" else "light",
            locator=f"{stylesheet_url} :: {selector}",
        )
        for decl in decls:
            if getattr(decl, "type", None) != "declaration":
                continue
            name = decl.name.lower()
            value = _decl_value_text(decl)
            if name in ("background", "background-color"):
                record.background = parse_color_value(
                    value.split()[0] if value else value,
                    custom_props,
                    diagnostics=parsed.diagnostics,
                )
            elif name in ("color", "fill"):
                record.color = parse_color_value(
                    value, custom_props, diagnostics=parsed.diagnostics
                )
            elif name in ("border-color", "border"):
                record.border_color = _extract_first_color(
                    value, custom_props, diagnostics=parsed.diagnostics
                )
            elif name == "box-shadow":
                # Composite value kept as declared text: the kit models shadows with its own
                # shape, and re-serializing here would lose more than it gained.
                record.box_shadow = value if value.lower() != "none" else None
            elif name == "opacity":
                record.opacity = _parse_opacity(value)
            elif name in ("text-decoration", "text-decoration-line"):
                record.text_decoration = value or None
        if record.declares_anything():
            parsed.state_styles.append(record)


def _cap_state_styles(parsed: ParsedSite) -> None:
    """Trim the state evidence to its budget, LOUDLY (clone-fidelity F0.2's pattern)."""
    if len(parsed.state_styles) <= MAX_STATE_STYLE_COUNT:
        return
    dropped = [record.selector for record in parsed.state_styles[MAX_STATE_STYLE_COUNT:]]
    del parsed.state_styles[MAX_STATE_STYLE_COUNT:]
    parsed.diagnostics.append(
        budget_diagnostic(
            budget="interaction state",
            limit=MAX_STATE_STYLE_COUNT,
            dropped=dropped,
            code=STATE_BUDGET_DIAGNOSTIC_CODE,
            noun="interaction state rule(s) were not recorded",
        )
    )


# --- CSS iteration --------------------------------------------------------------


def _decl_value_text(decl) -> str:
    return tinycss2.serialize(decl.value).strip()


def _collect_custom_props(stylesheets, existing: dict[str, str]) -> dict[str, str]:
    props = dict(existing)
    for sheet in stylesheets:
        rules = tinycss2.parse_stylesheet(
            sheet.text, skip_comments=True, skip_whitespace=True
        )
        # Through the shared iterator (W2), so a `:root` block inside `@layer base` — how a
        # Tailwind-era site ships its palette — is not invisible here while being visible to
        # the dark walker three functions down.
        for selectors, decls, theme in _iter_qualified_rules(rules, "light"):
            if theme == "dark":
                continue  # `_collect_dark_custom_props` owns those; the two tables never merge
            if not any(_is_root_selector(selector) for selector in selectors):
                continue
            for decl in decls:
                if getattr(decl, "type", None) == "declaration" and decl.name.startswith("--"):
                    props[decl.name] = _decl_value_text(decl)
    return props


def _is_root_selector(selector: str) -> bool:
    """Does this one selector target the document root a custom property is declared on?"""
    return selector.strip().lower() in ("html", ":root")


def _collect_dark_custom_props(stylesheets) -> dict[str, str]:
    """The custom-property OVERRIDES a site declares for dark mode (clone-fidelity F0.3).

    ``_collect_custom_props`` walks top-level rules only, so a
    ``@media (prefers-color-scheme: dark) { :root { --bg: #0b0f14 } }`` block — how every
    modern site ships its dark palette — was invisible: the overrides reached neither the
    light table (correctly, they are not light values) nor anything else (incorrectly), and
    the kit's dark colorway was synthesized from the light palette even for sites that had
    written theirs down. Kept in its own table rather than merged, so the light table stays
    byte-identical and the two colorways can never shadow each other.
    """
    props: dict[str, str] = {}
    for sheet in stylesheets:
        rules = tinycss2.parse_stylesheet(
            sheet.text, skip_comments=True, skip_whitespace=True
        )
        for selectors, decls, theme in _iter_qualified_rules(rules, "light"):
            if theme != "dark":
                continue
            if not any(_is_root_selector(selector) for selector in selectors):
                continue
            for decl in decls:
                if getattr(decl, "type", None) == "declaration" and decl.name.startswith("--"):
                    props[decl.name] = _decl_value_text(decl)
    return props


#: At-rules whose block holds NESTED RULES rather than declarations. Every structure-aware CSS
#: walker in this module descends into them (clone-fidelity F2 wave W2). The bug this closes had
#: already been found and fixed once, narrowly, for dark custom properties
#: (:func:`_collect_dark_custom_props`) and never generalized — so ``iter_font_faces`` stayed the
#: one non-recursive walker here, and a single ``@media``-wrapped ``@font-face`` on stripe.com
#: meant its brand font was never fetched and every section of the site refused to mint.
CONDITIONAL_GROUP_AT_RULES = frozenset({"media", "supports", "layer", "container", "scope"})

#: How deep the descent goes. Real stylesheets nest two or three of these (`@layer` inside
#: `@supports` inside `@media` is a shipped Tailwind/Next shape); the cap is a guard against a
#: pathological or hostile sheet, not a judgement about how sites are written.
MAX_AT_RULE_DEPTH = 8


def _nested_rules(rule, depth: int):
    """The rule list inside one conditional group at-rule, or ``None`` if it is not one."""
    if rule.type != "at-rule" or rule.content is None:
        return None
    if rule.lower_at_keyword not in CONDITIONAL_GROUP_AT_RULES:
        return None
    if depth >= MAX_AT_RULE_DEPTH:
        return None
    return tinycss2.parse_rule_list(rule.content, skip_comments=True, skip_whitespace=True)


def _iter_qualified_rules(rules, theme: str, depth: int = 0):
    """Yield (selector_list, declarations, theme) flattening every conditional group at-rule."""
    for rule in rules:
        if rule.type == "qualified-rule":
            selectors = [
                s.strip()
                for s in tinycss2.serialize(rule.prelude).strip().split(",")
                if s.strip()
            ]
            decls = tinycss2.parse_declaration_list(
                rule.content, skip_comments=True, skip_whitespace=True
            )
            yield selectors, decls, theme
            continue
        inner = _nested_rules(rule, depth)
        if inner is None:
            continue
        inner_theme = theme
        if rule.lower_at_keyword == "media":
            prelude = tinycss2.serialize(rule.prelude).lower()
            if "prefers-color-scheme" in prelude and "dark" in prelude:
                inner_theme = "dark"
        yield from _iter_qualified_rules(inner, inner_theme, depth + 1)


def _px_from_length(value: str) -> float | None:
    value = value.strip().lower()
    m = re.match(r"^([\d.]+)(px|rem|em)$", value)
    if not m:
        return None
    number = float(m.group(1))
    unit = m.group(2)
    if unit == "px":
        return number
    return number * 16.0  # rem/em × 16


def _first_family(value: str) -> str | None:
    for part in value.split(","):
        family = part.strip().strip("'\"")
        if not family:
            continue
        if family.lower() in _GENERIC_FAMILIES:
            continue
        return family
    return None


def _fallback_stack(value: str) -> list[str]:
    return [part.strip().strip("'\"") for part in value.split(",") if part.strip()]


_ROOT_FONT_SIZE_PX = 16.0


def _line_height(value: str, font_size_px: float | None) -> float | None:
    """CSS ``line-height`` as a ratio of the ELEMENT's font size.

    unitless / ``em`` / ``%`` are ratios already; ``px`` divides by the element size; ``rem``
    is root-relative (× 16) and then divides by the element size. A length with no element
    size is unconvertible → ``None`` (an honest blank). It must never fall back to ``px / 16``:
    that was the 2026-09-04 Apollo bug — a 72px headline leading stored as 4.5.
    """
    value = value.strip().lower()
    if not value or value in ("normal", "inherit", "initial", "unset"):
        return None
    try:
        return float(value)
    except ValueError:
        pass
    m = re.match(r"^(-?[\d.]+)(px|rem|em|%)$", value)
    if not m:
        return None
    number, unit = float(m.group(1)), m.group(2)
    if unit == "em":
        return number
    if unit == "%":
        return number / 100.0
    px = number if unit == "px" else number * _ROOT_FONT_SIZE_PX
    if not font_size_px or font_size_px <= 0:
        return None
    return px / font_size_px


def _letter_spacing(value: str, font_size_px: float | None) -> float | None:
    """CSS ``letter-spacing`` in em of the ELEMENT's font size (same rules as ``_line_height``)."""
    value = value.strip().lower()
    if not value or value in ("normal", "inherit", "initial", "unset"):
        return None
    m = re.match(r"^(-?[\d.]+)(px|rem|em)$", value)
    if not m:
        return None
    number, unit = float(m.group(1)), m.group(2)
    if unit == "em":
        return number
    px = number if unit == "px" else number * _ROOT_FONT_SIZE_PX
    if not font_size_px or font_size_px <= 0:
        return None
    return px / font_size_px


def _weight_int(value: str) -> int | None:
    value = value.strip().lower()
    mapping = {"normal": 400, "bold": 700, "lighter": 300, "bolder": 700}
    if value in mapping:
        return mapping[value]
    try:
        return int(float(value))
    except ValueError:
        return None


def _type_label(selectors: list[str]) -> str | None:
    for selector in selectors:
        sel = selector.lower()
        tokens = re.split(r"[\s>+~]+", sel)
        for token in tokens:
            for label in ("h1", "h2", "h3", "h4", "h5", "h6"):
                if token == label or token.startswith(label + ".") or token.startswith(label + ":"):
                    return label
        if any(t == "body" or t == "html" for t in tokens):
            return "body"
        if any(t in ("p", "li") for t in tokens):
            return "body"
        if any(t in ("button", ".btn", ".button") for t in tokens) or "cta" in sel:
            return "button"
        if any(t in ("nav", "header") for t in tokens):
            return "nav"
    return None


def _absolutize(base: str, url: str) -> str:
    return urljoin(base, url)


def _font_format(url: str) -> str:
    lowered = url.lower()
    for ext in ("woff2", "woff", "ttf", "otf"):
        if lowered.endswith("." + ext) or f".{ext}?" in lowered:
            return ext
    return "woff2"


_FORMAT_RANK = {"woff2": 0, "woff": 1, "ttf": 2, "otf": 2}


def _parse_font_face(decls, base_url: str) -> ParsedFontFace | None:
    family = None
    weight = None
    style = "normal"
    src_urls: list[str] = []
    for decl in decls:
        if getattr(decl, "type", None) != "declaration":
            continue
        name = decl.name.lower()
        value = _decl_value_text(decl)
        if name == "font-family":
            family = value.strip().strip("'\"")
        elif name == "font-weight":
            weight = _weight_int(value)
        elif name == "font-style":
            style = value.strip().lower() or "normal"
        elif name == "src":
            # `value` is tinycss2's re-serialization, which RE-ESCAPES a url token: a face
            # declared `url(…/A%20\(1\).woff2)` serializes back with those `\(`/`\)` intact.
            # So this reads it with the same escape-aware reader the collector uses — which
            # is also what keeps capture and parse agreeing on the URL to the character, the
            # invariant `iter_font_faces`'s docstring exists to protect.
            for raw in iter_css_urls(value):
                src_urls.append(_absolutize(base_url, raw))
    if family is None:
        return None
    src_urls = list(dict.fromkeys(src_urls))
    chosen = None
    if src_urls:
        chosen = sorted(src_urls, key=lambda u: _FORMAT_RANK.get(_font_format(u), 3))[0]
    # Bound rung first, then the rest in declaration order: the asset budget drops the tail,
    # so under pressure the file the kit actually binds is the one that survives.
    rungs = ([chosen] if chosen else []) + [u for u in src_urls if u != chosen]
    face = ParsedFontFace(
        weight=weight if weight is not None else 400,
        style=style,
        source_url=chosen,
        format=_font_format(chosen) if chosen else None,
        source_urls=rungs,
    )
    face._family = family  # type: ignore[attr-defined]
    return face


def _license_hint(face: ParsedFontFace) -> str | None:
    if not face.source_url:
        return None
    filename = urlparse(face.source_url).path.rsplit("/", 1)[-1]
    if re.search(r"trial", filename, re.IGNORECASE):
        return "trial-filename"
    host = urlparse(face.source_url).hostname or ""
    if host == "fonts.gstatic.com":
        return "google-fonts"
    return None


def _sheet_base(sheet_url: str, page_url: str) -> str:
    """The base a relative URL inside this stylesheet resolves against.

    Per the CSS spec that is the stylesheet's own URL, not the page's. The
    rendered tier reads same-origin sheets straight out of the CSSOM and stores
    them as ``inline:N``, which have no URL of their own — those resolve against
    the page, exactly like a ``<style>`` block.
    """
    if not sheet_url or sheet_url.startswith("inline:"):
        return page_url
    return sheet_url


def iter_font_faces(stylesheets, page_url: str):
    """Yield ``(sheet_url, ParsedFontFace)`` for every ``@font-face`` rule.

    **This is the one and only ``@font-face`` discovery path.** Capture calls it
    to decide which font files to download and :func:`parse_site` calls it to
    record the faces, so the two cannot disagree about a URL. They used to:
    capture found font files with its own regex resolved against the stylesheet
    while parse resolved against the page, and the evidence builder then looked
    the bytes up by exact URL string. Every mismatch produced a face with
    ``asset_id: null`` — bytes fetched under one key, looked for under another —
    which is why ingested brand fonts never painted and every render fell back
    to Inter with ``LUMS0100``.
    """
    for sheet in stylesheets:
        base = _sheet_base(sheet.url, page_url)
        rules = tinycss2.parse_stylesheet(
            sheet.text, skip_comments=True, skip_whitespace=True
        )
        for face in _font_faces_in(rules, base, 0):
            yield sheet.url, face


def _font_faces_in(rules, base: str, depth: int):
    """Every ``@font-face`` at any conditional-group depth, resolved against ITS OWN sheet.

    A media-wrapped face is the ordinary modern shape — a responsive or `@layer`-scoped font
    stack — and it declares a real file the page really loads. The base URL stays the sheet's,
    which is the capture↔parse exact-URL invariant this function exists to keep.
    """
    for rule in rules:
        if rule.type == "at-rule" and rule.lower_at_keyword == "font-face":
            decls = tinycss2.parse_declaration_list(
                rule.content or [], skip_comments=True, skip_whitespace=True
            )
            face = _parse_font_face(decls, base)
            if face is not None:
                yield face
            continue
        inner = _nested_rules(rule, depth)
        if inner is not None:
            yield from _font_faces_in(inner, base, depth + 1)


def font_face_source_rungs(stylesheets, page_url: str) -> list[str]:
    """EVERY ``src`` URL every ``@font-face`` declares — EVERY face's BOUND rung first.

    What capture downloads (clone-fidelity F0.2). A face routinely lists ``woff2, woff,
    ttf``; the kit binds the best format the same way a browser would, but F2 rewrites the
    captured ``@font-face`` block verbatim onto our store, so a rung we never fetched is a
    font that fails to load for whichever browser picks it.

    **Why bound rungs come first GLOBALLY, not per face.** The asset budget keeps a PREFIX of
    this list and drops the tail. Emitting face by face meant a budget that cut mid-list kept
    face 1's ``ttf`` alternate while dropping face 9's bound ``woff2`` — the exact opposite
    of "the file the kit binds survives budget pressure". Two passes make that promise true
    across the whole page: every bound rung, then every alternate.

    (This replaced ``font_face_sources``, which returned only the bound URLs and became the
    binding set nobody called once the fetch list grew — the binding choice itself lives in
    ``_parse_font_face``'s ``chosen`` and rides on ``ParsedFontFace.source_url``.)
    """
    faces = [face for _sheet_url, face in iter_font_faces(stylesheets, page_url)]

    def rungs_of(face) -> list[str]:
        return face.source_urls or ([face.source_url] if face.source_url else [])

    urls: list[str] = []
    for face in faces:
        if face.source_url and face.source_url not in urls:
            urls.append(face.source_url)
    for face in faces:
        for url in rungs_of(face):
            if url and url not in urls:
                urls.append(url)
    return urls


# --- main parse -----------------------------------------------------------------


def parse_site(snapshot: SiteSnapshot) -> ParsedSite:
    parsed = ParsedSite()
    base_url = snapshot.final_url or snapshot.requested_url

    custom_props = dict(snapshot.custom_props or {})
    custom_props = _collect_custom_props(snapshot.stylesheets, custom_props)
    parsed.custom_props = custom_props
    parsed.dark_custom_props = _collect_dark_custom_props(snapshot.stylesheets)

    _parse_css(snapshot, parsed, custom_props, base_url)
    if snapshot.computed_samples:
        _parse_computed_samples(snapshot, parsed)
        parsed.type_widths = parse_type_widths(snapshot, custom_props)
        if parsed.type_widths and snapshot.type_widths:
            parsed.type_capture_width = int(snapshot.type_widths["capture_width"])
    _parse_dom(snapshot, parsed, base_url)
    _parse_narrative(snapshot, parsed, base_url)
    return parsed


def _parse_css(
    snapshot: SiteSnapshot,
    parsed: ParsedSite,
    custom_props: dict[str, str],
    base_url: str,
) -> None:
    # Custom props → hinted color evidence (weight 3.0).
    for name, value in custom_props.items():
        hex_value = parse_color_value(value, custom_props, diagnostics=parsed.diagnostics)
        if hex_value:
            parsed.colors.append(
                ParsedColor(
                    value=hex_value,
                    weight=3.0,
                    theme="light",
                    role_hints=[f"custom-prop:{name}"],
                    name=None,
                    locator=f"css :: {name}",
                )
            )

    # The same properties read a SECOND way (clone-fidelity F0.3): a name that states a role
    # — `--base-color-brand--green` — is the site telling us what the color is FOR, and the
    # normalizer applies it as a direct role assignment above the clustering heuristic. The
    # weighted-evidence emission above is deliberately untouched: a name we cannot read a
    # role off of keeps exactly today's behaviour, and one we can still contributes its
    # swatch to the clusters everything else is derived from.
    parsed.declared_roles = declared_roles(
        custom_props,
        lambda value: parse_color_value(
            value, custom_props, diagnostics=parsed.diagnostics
        ),
    )

    # Dark-mode custom-property overrides → dark color evidence, which is what turns the
    # kit's dark colorway from `synthesized` into `captured`. Resolved against the dark table
    # FIRST so an override pointing at another override reads the dark value, falling back to
    # the light table for the (common) chain that only re-points its top link.
    dark_scope = {**custom_props, **parsed.dark_custom_props}
    if parsed.dark_custom_props:
        for name, value in parsed.dark_custom_props.items():
            hex_value = parse_color_value(
                value, dark_scope, diagnostics=parsed.diagnostics
            )
            if hex_value:
                parsed.colors.append(
                    ParsedColor(
                        value=hex_value,
                        weight=3.0,
                        theme="dark",
                        role_hints=[f"custom-prop:{name}"],
                        name=None,
                        locator=f"css :: {name} :: prefers-color-scheme: dark",
                    )
                )

    # @font-face — the shared walk capture also downloads from, so a face's
    # source_url is always the key its bytes were fetched under.
    for sheet_url, face in iter_font_faces(snapshot.stylesheets, base_url):
        _accumulate_font(parsed, face, sheet_url)

    for sheet in snapshot.stylesheets:
        rules = tinycss2.parse_stylesheet(
            sheet.text, skip_comments=True, skip_whitespace=True
        )
        for selectors, decls, theme in _iter_qualified_rules(rules, "light"):
            # A rule inside the dark block resolves its vars against the dark overrides —
            # otherwise `@media dark { body { background: var(--bg) } }` reads the LIGHT
            # `--bg` and the captured dark page comes out white. Identical to the light
            # table for any site that declares no dark overrides.
            scope = dark_scope if theme == "dark" else custom_props
            _parse_rule(parsed, selectors, decls, theme, scope, sheet.url)
            _collect_state_styles(parsed, selectors, decls, theme, scope, sheet.url)
    _cap_state_styles(parsed)


def _parse_rule(
    parsed: ParsedSite,
    selectors: list[str],
    decls,
    theme: str,
    custom_props: dict[str, str],
    stylesheet_url: str,
) -> None:
    # RETIRED 2026-08-30 (Phase-1 brand-color overhaul): this walk no longer
    # emits LIGHT palette candidates. Weighting rule-text color mentions by
    # selector vocabulary elected a phone-widget FOCUS ring as apollo.io's
    # brand color — code mentioning a color is not the page showing it, and on
    # hashed-class frontends the vocabulary misses the real CTA entirely while
    # a `button:focus` rule inherits its credential. Light election authority
    # now lives in the rendered census (`lumen_ingestion.census` +
    # `RenderTruth`); stylesheets keep their naming jobs — custom-prop/token
    # evidence, declared roles, fonts, and the interaction-state records.
    #
    # DARK-block rule colors are the one deliberate survivor: the capture takes
    # no dark-scheme screenshot yet (deferred scope), so `build_dark_colorway`
    # has no census to read and dark rules remain its only whole-page evidence.
    # They are emitted FLAT — weight 1.0, no hints, no vocabulary table — and,
    # being theme="dark", they can never vote in the light election.
    for selector in selectors:
        locator = f"{stylesheet_url} :: {selector}"
        family = None
        size_px = None
        font_weight = None
        line_height_raw: str | None = None
        letter_spacing_raw: str | None = None
        for decl in decls:
            if getattr(decl, "type", None) != "declaration":
                continue
            name = decl.name.lower()
            value = _decl_value_text(decl)
            if theme == "dark" and name in ("color", "fill", "background", "background-color"):
                candidate = value.split()[0] if name == "background" and value else value
                hex_value = parse_color_value(
                    candidate, custom_props, diagnostics=parsed.diagnostics
                )
                if hex_value:
                    parsed.colors.append(
                        ParsedColor(hex_value, 1.0, "dark", [], None, locator)
                    )
            if name == "font-family":
                family = _first_family(value)
            elif name == "font-size":
                size_px = _px_from_length(value)
            elif name == "font-weight":
                font_weight = _weight_int(value)
            elif name == "line-height":
                line_height_raw = value
            elif name == "letter-spacing":
                letter_spacing_raw = value

        # Resolved AFTER the loop: a rule may declare line-height before font-size, and both
        # lengths are relative to this rule's own element size.
        line_height = _line_height(line_height_raw, size_px) if line_height_raw is not None else None
        letter_spacing = (
            _letter_spacing(letter_spacing_raw, size_px) if letter_spacing_raw is not None else None
        )

        label = _type_label([selector])
        if label and (family or size_px or font_weight):
            parsed.type_samples.append(
                ParsedType(
                    label=label,
                    family=family,
                    weight=font_weight,
                    size_px=size_px,
                    line_height=line_height,
                    letter_spacing=letter_spacing,
                    locator=locator,
                )
            )


def _extract_first_color(
    value: str, custom_props: dict[str, str], *, diagnostics: list[dict] | None = None
) -> str | None:
    for token in re.split(r"\s+", value.strip()):
        hex_value = parse_color_value(token, custom_props, diagnostics=diagnostics)
        if hex_value:
            return hex_value
    return None


def _accumulate_font(parsed: ParsedSite, face: ParsedFontFace, stylesheet_url: str) -> None:
    family = getattr(face, "_family", None)
    if not family:
        return
    for font in parsed.fonts:
        if font.family.lower() == family.lower():
            font.faces.append(face)
            if font.license_hint is None:
                font.license_hint = _license_hint(face)
            return
    parsed.fonts.append(
        ParsedFont(
            family=family,
            role_hint="unknown",
            faces=[face],
            fallback_stack=[],
            license_hint=_license_hint(face),
            locator=f"{stylesheet_url} :: @font-face {family}",
        )
    )


# --- computed samples (rendered tier) -------------------------------------------

_SAMPLE_HINTS: dict[str, tuple[list[str], list[str]]] = {
    "body": (["page-bg"], ["body-text"]),
    "html": (["page-bg"], ["body-text"]),
    "h1": ([], ["heading-text"]),
    "h2": ([], ["heading-text"]),
    "h3": ([], ["heading-text"]),
    "p": ([], ["body-text"]),
    "a": ([], ["link"]),
    "button": (["button-bg"], ["button-text"]),
}


def _parse_computed_samples(snapshot: SiteSnapshot, parsed: ParsedSite) -> None:
    _parse_samples(enumerate(snapshot.computed_samples or []), parsed)


def parse_type_widths(snapshot: SiteSnapshot, custom_props: dict[str, str]) -> list[tuple[int, list[ParsedType]]]:
    """Responsive brand type: the type samples at each width the capture narrowed to, parsed exactly
    as desktop's (the desktop sample with that width's size, line height and letter spacing). A
    sample with no reading at a width (gone, hidden) is left out there; each keeps its index."""
    measured = snapshot.type_widths or {}
    samples = snapshot.computed_samples or []
    out: list[tuple[int, list[ParsedType]]] = []
    for entry in measured.get("widths") or []:
        reads = entry.get("samples") or []
        indexed = [
            (index, {**sample, **{key: read[key] for key in ("fontSize", "lineHeight", "letterSpacing") if key in read}})
            for index, (sample, read) in enumerate(zip(samples, reads))
            if isinstance(read, dict)
        ]
        scratch = ParsedSite(custom_props=dict(custom_props))
        _parse_samples(indexed, scratch)
        out.append((int(entry["width"]), scratch.type_samples))
    return out


def _parse_samples(indexed, parsed: ParsedSite) -> None:
    for index, sample in indexed:
        tag = str(sample.get("tag") or sample.get("selectorish") or "").lower()
        area = float(sample.get("area") or 0.0)
        weight = max(0.5, math.log2(1 + area) / 4.0)
        bg_hints, fg_hints = _SAMPLE_HINTS.get(tag, ([], []))
        locator = f"rendered :: {sample.get('selectorish') or tag}"
        bg = sample.get("bg")
        color = sample.get("color")
        if bg:
            hex_value = parse_color_value(
                str(bg), parsed.custom_props, diagnostics=parsed.diagnostics
            )
            if hex_value:
                parsed.colors.append(
                    ParsedColor(hex_value, weight, "light", list(bg_hints), None, locator)
                )
        if color:
            hex_value = parse_color_value(
                str(color), parsed.custom_props, diagnostics=parsed.diagnostics
            )
            if hex_value:
                parsed.colors.append(
                    ParsedColor(hex_value, weight, "light", list(fg_hints), None, locator)
                )
        label = tag if tag in ("h1", "h2", "h3", "h4", "h5", "h6", "body", "button", "nav") else None
        family = sample.get("fontFamily")
        if label and family:
            size_px = _px_from_length(str(sample.get("fontSize") or ""))
            # A heading keeps its own ink, what sits behind it and its whole box: the heading ink
            # is read from these (normalizer.typography.heading_ink).
            ink = backdrop = box = None
            if label in ("h1", "h2", "h3"):
                if color:
                    ink = parse_color_value(str(color), parsed.custom_props)
                if sample.get("behind"):
                    backdrop = parse_color_value(str(sample["behind"]), parsed.custom_props)
                box = float(sample.get("boxArea") or sample.get("area") or 0.0)
            parsed.type_samples.append(
                ParsedType(
                    label="body" if label == "html" else label,
                    family=_first_family(str(family)),
                    weight=_weight_int(str(sample.get("fontWeight") or "")),
                    size_px=size_px,
                    line_height=_line_height(str(sample.get("lineHeight") or ""), size_px),
                    letter_spacing=_letter_spacing(str(sample.get("letterSpacing") or ""), size_px),
                    locator=locator,
                    color=ink,
                    background=backdrop,
                    area=box,
                    sample_index=index,
                )
            )


# --- DOM: logos + images --------------------------------------------------------


def _download_by_url(snapshot: SiteSnapshot, url: str) -> str | None:
    for entry in snapshot.downloads:
        if entry.url == url:
            return entry.sha256
    return None


def _is_dark_scheme(snapshot: SiteSnapshot, url: str) -> bool:
    """Did every reference to this URL come from a ``prefers-color-scheme: dark`` source?

    The collector decides this (``candidates._dedupe``) and stamps it on the download; parse
    only reads it, so the two can never disagree about which rendition is the dark one.
    """
    for entry in snapshot.downloads:
        if entry.url == url:
            return bool(entry.dark_scheme)
    return False


# --- primary-logo identification: multi-signal scoring ---------------------------
#
# No single heuristic survives the open web (live counterexample: the first two
# header <img>s on insighthealth.ai were an App Store badge and a promo tile,
# while the real lockup sat in a `class="nav_logo"` img the old first-2 cap
# never reached). Every candidate is scored across independent signals and the
# slot is filled from the top scorers ABOVE A THRESHOLD — a page with no
# convincing candidate produces an EMPTY primary slot for the human to fill,
# never a confident wrong guess. The score and matched signals ride the
# locator into kit provenance for auditability.
#
# Signals not yet available from the static snapshot (viewport bounding box,
# cross-page header consistency) need a rendered-capture extension — riders,
# not part of this scorer.

_LOGO_CONTAINER_RE = re.compile(r"logo|brand|masthead|navbar-brand|site-logo", re.I)
_LOGO_FILENAME_RE = re.compile(r"logo|brand.?mark|word.?mark|lock.?up", re.I)
_JUNK_FILENAME_RE = re.compile(
    r"app.?store|google.?play|play.?store|chrome|extension|badge|download"
    r"|sponsor|award|partner|certified|appstore",
    re.I,
)

#: Candidates scoring below this are not logos we believe in.
_LOGO_SCORE_THRESHOLD = 2.5
#: The primary slot carries at most this many scraped variants.
_LOGO_MAX_VARIANTS = 2


def _node_class_id(node) -> str:
    attributes = node.attributes or {}
    return f"{attributes.get('class') or ''} {attributes.get('id') or ''}"


def _ancestor_container_match(node, depth: int = 5) -> bool:
    current = node
    for _ in range(depth):
        if current is None:
            return False
        if _LOGO_CONTAINER_RE.search(_node_class_id(current)):
            return True
        current = current.parent
    return False


def _ancestor_home_link(node, base_url: str, depth: int = 5) -> bool:
    root = base_url.rstrip("/")
    current = node
    for _ in range(depth):
        if current is None:
            return False
        if current.tag == "a":
            href = (current.attributes or {}).get("href") or ""
            if href in ("/", root, f"{root}/"):
                return True
        current = current.parent
    return False


def _in_header_or_nav(node, depth: int = 8) -> bool:
    current = node
    for _ in range(depth):
        if current is None:
            return False
        if current.tag in ("header", "nav"):
            return True
        current = current.parent
    return False


def _jsonld_organization_logos(tree, base_url: str) -> list[str]:
    """Logo URLs DECLARED by the site via schema.org Organization JSON-LD —
    an explicit statement, not an inference, hence the strongest signal."""
    import json as _json

    urls: list[str] = []

    def visit(obj) -> None:
        if isinstance(obj, list):
            for item in obj:
                visit(item)
            return
        if not isinstance(obj, dict):
            return
        types = obj.get("@type")
        type_list = types if isinstance(types, list) else [types]
        if any(isinstance(t, str) and "organization" in t.lower() for t in type_list):
            logo = obj.get("logo")
            if isinstance(logo, dict):
                logo = logo.get("url")
            if isinstance(logo, str) and logo:
                urls.append(_absolutize(base_url, logo))
        for value in obj.values():
            if isinstance(value, (dict, list)):
                visit(value)

    for node in tree.css("script[type='application/ld+json']"):
        try:
            visit(_json.loads(node.text() or ""))
        except Exception:
            continue
    return urls


@dataclass
class _LogoCandidate:
    url: str | None  # None for inline SVG
    node: object | None
    inline_svg: str | None
    order: int
    score: float = 0.0
    signals: list[str] = field(default_factory=list)
    width: int | None = None
    height: int | None = None

    def add(self, points: float, signal: str) -> None:
        self.score += points
        self.signals.append(signal)


def _score_candidate(candidate: _LogoCandidate, base_url: str, declared: set[str]) -> None:
    node = candidate.node
    url = candidate.url or ""
    name = urlparse(url).path.rsplit("/", 1)[-1] if url else ""

    if url and url in declared:
        candidate.add(5.0, "jsonld-or-og-declared")
    if node is not None:
        if _ancestor_container_match(node):
            candidate.add(2.0, "logo-class")
        if _in_header_or_nav(node):
            candidate.add(1.5, "header-nav")
        if _ancestor_home_link(node, base_url):
            candidate.add(1.5, "home-link")
    if candidate.inline_svg is not None or url.lower().endswith(".svg"):
        candidate.add(1.5, "svg")
    if name and _LOGO_FILENAME_RE.search(name):
        candidate.add(1.0, "filename")
    if name and _JUNK_FILENAME_RE.search(name):
        candidate.add(-2.5, "junk-filename")
    width, height = candidate.width, candidate.height
    if width and height and height > 0:
        ratio = width / height
        if height <= 120 and 1.2 <= ratio <= 8.0:
            candidate.add(0.75, "lockup-aspect")
        if width >= 800 or height >= 400:
            candidate.add(-1.5, "hero-sized")


def _parse_primary_logo_candidates(
    snapshot: SiteSnapshot, tree, parsed: ParsedSite, base_url: str
) -> None:
    declared = set(_jsonld_organization_logos(tree, base_url))
    og_logo = _meta_content(tree, "og:logo")
    if og_logo:
        declared.add(_absolutize(base_url, og_logo))

    candidates: dict[str, _LogoCandidate] = {}
    order = 0

    def consider(url: str | None, node, inline_svg: str | None = None) -> None:
        nonlocal order
        key = url or f"inline-svg-{order}"
        if url and url in candidates:
            # Keep the best-placed occurrence of a repeated asset.
            existing = candidates[url]
            challenger = _LogoCandidate(
                url=url, node=node, inline_svg=None, order=existing.order,
                width=existing.width, height=existing.height,
            )
            _score_candidate(challenger, base_url, declared)
            if challenger.score > existing.score:
                candidates[url] = challenger
            return
        candidate = _LogoCandidate(
            url=url,
            node=node,
            inline_svg=inline_svg,
            order=order,
            width=_int_attr(node, "width") if node is not None else None,
            height=_int_attr(node, "height") if node is not None else None,
        )
        _score_candidate(candidate, base_url, declared)
        candidates[key] = candidate
        order += 1

    # Pool: chrome-scoped imgs, logo-classed imgs anywhere in the document
    # (catches `div.nav_logo` outside <header>), inline chrome SVGs, and the
    # declared URLs themselves (which may not appear in any <img>).
    for node in tree.css("header img, nav img, a[href='/'] img"):
        src = node.attributes.get("src")
        if src:
            consider(_absolutize(base_url, src), node)
    for node in tree.css("img"):
        src = node.attributes.get("src")
        if src and _ancestor_container_match(node):
            consider(_absolutize(base_url, src), node)
    for node in tree.css("header svg, nav svg, a[href='/'] svg"):
        if look_hides(node.attributes):
            continue  # hidden where the page was captured (capture keeps it for clones)
        # A logo file has no page CSS: what the page painted it with is baked back in.
        markup = bake_svg_looks(node.html or "")
        if markup:
            consider(None, node, inline_svg=markup)
            break
    for url in declared:
        if url not in candidates:
            consider(url, None)

    ranked = sorted(
        (c for c in candidates.values() if c.score >= _LOGO_SCORE_THRESHOLD),
        key=lambda c: (-c.score, c.order),
    )
    for candidate in ranked[:_LOGO_MAX_VARIANTS]:
        signals = "+".join(candidate.signals)
        locator = f"dom :: logo-score {candidate.score:.1f} [{signals}]"
        if candidate.inline_svg is not None:
            parsed.logos.append(
                ParsedAsset(
                    sha256=None,
                    source_url=None,
                    kind="logo",
                    usage_hint="primary",
                    locator=locator,
                )
            )
            parsed._inline_svgs = getattr(parsed, "_inline_svgs", [])  # type: ignore[attr-defined]
            parsed._inline_svgs.append(candidate.inline_svg)  # type: ignore[attr-defined]
        else:
            parsed.logos.append(
                ParsedAsset(
                    sha256=_download_by_url(snapshot, candidate.url or ""),
                    source_url=candidate.url,
                    kind="logo",
                    usage_hint="primary",
                    width=candidate.width,
                    height=candidate.height,
                    locator=locator,
                )
            )


def _parse_dom(snapshot: SiteSnapshot, parsed: ParsedSite, base_url: str) -> None:
    tree = HTMLParser(snapshot.html)

    _parse_primary_logo_candidates(snapshot, tree, parsed, base_url)

    # apple-touch-icon → mark
    for node in tree.css("link[rel='apple-touch-icon']"):
        href = node.attributes.get("href")
        if href:
            url = _absolutize(base_url, href)
            parsed.logos.append(
                ParsedAsset(
                    sha256=_download_by_url(snapshot, url),
                    source_url=url,
                    kind="logo",
                    usage_hint="mark",
                    locator="dom :: apple-touch-icon",
                )
            )

    # favicon → a FALLBACK mark. Recorded into `meta` since the first ingestion slice but
    # never fetched, so a site with no apple-touch-icon had an empty mark slot even though
    # it declared one. Appended AFTER apple-touch-icon deliberately: `normalizer.emit`
    # fills `logo.mark` from the first mark, and a 180px touch icon beats a 32px favicon.
    for node in tree.css("link[rel='icon'], link[rel='shortcut icon']"):
        href = node.attributes.get("href")
        if not href:
            continue
        url = _absolutize(base_url, href)
        sha = _download_by_url(snapshot, url)
        if sha is None:
            continue  # not fetched (or the fetch failed) — an absent mark, never a fake one
        parsed.logos.append(
            ParsedAsset(
                sha256=sha,
                source_url=url,
                kind="logo",
                usage_hint="mark",
                locator="dom :: favicon",
            )
        )
        break

    # og:image is an IMAGE (kind og_image), not a logo.
    og_image = _meta_content(tree, "og:image")
    if og_image:
        url = _absolutize(base_url, og_image)
        parsed.images.append(
            ParsedAsset(
                sha256=_download_by_url(snapshot, url),
                source_url=url,
                kind="image",
                kind_hint="og_image",
                locator="dom :: og:image",
            )
        )

    _parse_images(snapshot, tree, parsed, base_url)


def _parse_images(snapshot: SiteSnapshot, tree, parsed: ParsedSite, base_url: str) -> None:
    candidates: list[tuple[float, int, ParsedAsset]] = []
    logo_urls = {logo.source_url for logo in parsed.logos}

    def measure(sha: str | None) -> int:
        if not sha:
            return 0
        data = snapshot.download_bytes(sha)
        return len(data) if data else 0

    for image_index, node in enumerate(tree.css("img")):
        # THE SHARED LADDER. `static._collect_assets` enqueued exactly these URLs, so the
        # first rung with bytes is the best rendition that actually arrived; if the widened
        # request was refused we simply walk down to the bare `src` and are no worse off
        # than the pre-2026-08-20 behaviour. Resolving anything else here would orphan every
        # download and produce a kit with zero images — see `imgsrc`.
        ladder = image_source_ladder(node, base_url)
        if not ladder:
            continue
        if any(url in logo_urls for url in ladder):
            continue
        if ladder[-1].startswith("data:") and len(ladder[-1]) > 50 * 1024:
            continue  # large data URI; parse.py never inlines them
        width = _int_attr(node, "width")
        height = _int_attr(node, "height")
        if width is not None and height is not None and width <= 4 and height <= 4:
            continue  # tracking pixel
        url, sha = ladder[-1], None
        for candidate in ladder:
            candidate_sha = _download_by_url(snapshot, candidate)
            if candidate_sha:
                url, sha = candidate, candidate_sha
                break
        file_size = measure(sha)
        # keep when it has size hints OR a fetched file ≥ 10 KB
        if not (width or height) and file_size < 10 * 1024 and sha is None:
            continue
        area = float((width or 0) * (height or 0))
        # Provenance stays honest about WHICH rendition we hold: a chosen URL that is not
        # the element's own `src` says so in the locator, and a rendition that exists only
        # for dark mode says THAT — the signal is worthless if it dies in the snapshot.
        locator = "dom :: img" if url == ladder[-1] else "dom :: img :: hi-res rendition"
        if _is_dark_scheme(snapshot, url):
            locator += " :: prefers-color-scheme: dark"
        surrounding = None
        parent = node.parent
        for _ in range(4):
            if parent is None:
                break
            heading = parent.css_first("h1,h2,h3,h4,figcaption")
            if heading is not None:
                surrounding = parent.text(separator=" ", strip=True)[:2000]
                break
            parent = parent.parent
        locator += f" :: img-index {image_index}"
        candidates.append(
            (
                area,
                file_size,
                ParsedAsset(
                    sha256=sha,
                    source_url=url,
                    kind="image",
                    kind_hint="photo",
                    width=width,
                    height=height,
                    locator=locator,
                    alt=node.attributes.get("alt"),
                    surrounding_text=surrounding,
                    placement="img element",
                ),
            )
        )

    # CSS background-image art (gradients, hero panels) — same shared chooser the collector
    # used, so the bytes are already in the snapshot. No DOM size hints exist for these, so
    # they rank by file size alone.
    # A URL used in an <img> and as a CSS background has two source occurrences.
    # Custody/analysis deduplicate the asset later; do not erase placement evidence here.
    seen = set()
    for url in background_image_urls(tree, snapshot.stylesheets, base_url):
        if url in seen:
            continue
        seen.add(url)
        sha = _download_by_url(snapshot, url)
        if sha is None:
            continue  # never fetched — an absent image, never a fabricated one
        candidates.append(
            (
                0.0,
                measure(sha),
                ParsedAsset(
                    sha256=sha,
                    source_url=url,
                    kind="image",
                    kind_hint="illustration",
                    locator="dom :: css background-image",
                    placement="CSS background-image",
                ),
            )
        )

    # The old hard cap of 50 lived here and whispered a LUMI0504 at `info`. It is now the
    # shared asset budget, and overflow is LOUD and NAMED (clone-fidelity F0.2): an image the
    # kit does not carry is an image the F2 clone cannot rehost, so a human has to be told
    # which ones. Sorted best-first (largest rendered area, then file size), so if the budget
    # ever does trip, what it costs is the smallest imagery on the page.
    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    kept = candidates[:MAX_ASSET_COUNT]
    dropped = [asset.source_url for _, _, asset in candidates[MAX_ASSET_COUNT:]]
    for _, _, asset in kept:
        parsed.images.append(asset)
    if dropped:
        parsed.diagnostics.append(
            budget_diagnostic(
                budget="image candidate", limit=MAX_ASSET_COUNT, dropped=dropped
            )
        )


def _int_attr(node, name: str) -> int | None:
    value = node.attributes.get(name)
    if not value:
        return None
    m = re.match(r"^(\d+)", str(value))
    return int(m.group(1)) if m else None


def _meta_content(tree, prop: str) -> str | None:
    for node in tree.css(f"meta[property='{prop}']"):
        content = node.attributes.get("content")
        if content:
            return content
    for node in tree.css(f"meta[name='{prop}']"):
        content = node.attributes.get("content")
        if content:
            return content
    return None


def _parse_narrative(snapshot: SiteSnapshot, parsed: ParsedSite, base_url: str) -> None:
    tree = HTMLParser(snapshot.html)
    title_node = tree.css_first("title")
    title = title_node.text().strip() if title_node else None

    description = None
    for node in tree.css("meta[name='description']"):
        description = node.attributes.get("content")
        break

    og_site = _meta_content(tree, "og:site_name")
    og_title = _meta_content(tree, "og:title")
    og_description = _meta_content(tree, "og:description")

    body = tree.body
    text_excerpt = None
    if body is not None:
        text = re.sub(r"\s+", " ", body.text(separator=" ")).strip()
        text_excerpt = text[:3000] if text else None

    brand_name = og_site
    if not brand_name and title:
        brand_name = re.split(r"[|—–]", title)[0].strip()
    # A long name means we grabbed an SEO headline, not a brand name
    # ("AI Document Processing For Referrals, Pre-Auth & Fax") — the hostname
    # is the better fallback.
    if not brand_name or len(brand_name) > 40:
        brand_name = _host_brand_name(base_url) or brand_name

    facts = []
    if description:
        facts.append(description)
    if og_description and og_description != description:
        facts.append(og_description)

    parsed.narrative = ParsedNarrative(
        brand_name=brand_name,
        url=base_url,
        tagline=og_title if og_title and og_title != title else None,
        summary_facts=facts,
        text_excerpt=text_excerpt,
    )


def _host_brand_name(base_url: str) -> str | None:
    """The one canonical name-from-a-domain rule; it lives in ``clue_core.normalize``."""
    return canonical_workspace_name(base_url)
