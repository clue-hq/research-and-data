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
from selectolax.parser import HTMLParser

from .budget import MAX_ASSET_COUNT, budget_diagnostic
from .imgsrc import background_image_urls, image_source_ladder
from .snapshot import SiteSnapshot

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


@dataclass
class ParsedNarrative:
    brand_name: str | None = None
    url: str | None = None
    tagline: str | None = None
    summary_facts: list[str] = field(default_factory=list)
    text_excerpt: str | None = None


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
    diagnostics: list[dict] = field(default_factory=list)


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


def parse_color_value(
    raw: str,
    custom_props: dict[str, str],
    *,
    diagnostics: list[dict] | None = None,
    _depth: int = 0,
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

    var_match = re.match(r"var\(\s*(--[\w-]+)\s*(?:,\s*([^)]+))?\)", text, re.IGNORECASE)
    if var_match:
        # A custom property may point at another one. Real sites ship cyclic
        # chains (cursor.com/about does), so the walk is bounded: unbounded
        # recursion here is a RecursionError, i.e. another whole-job failure.
        if _depth >= _MAX_VAR_HOPS:
            _record_color_skip(
                diagnostics, f"custom-property chain did not resolve (cycle?): {text}"
            )
            return None
        name = var_match.group(1)
        resolved = custom_props.get(name)
        if resolved is None:
            fallback = var_match.group(2)
            if fallback is None:
                return None
            return parse_color_value(
                fallback, custom_props, diagnostics=diagnostics, _depth=_depth + 1
            )
        return parse_color_value(
            resolved, custom_props, diagnostics=diagnostics, _depth=_depth + 1
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
    rgb = re.match(r"rgba?\(([^)]+)\)", text, re.IGNORECASE)
    if rgb:
        parts = re.split(r"[,\s/]+", rgb.group(1).strip())
        parts = [p for p in parts if p]
        if len(parts) >= 3:
            try:
                comps = [_parse_channel(parts[i]) for i in range(3)]
            except ValueError:
                _record_color_skip(diagnostics, f"unreadable rgb() channels: {text}")
                return None
            hex6 = "#%02X%02X%02X" % (comps[0], comps[1], comps[2])
            if len(parts) >= 4:
                alpha = _alpha_or_opaque(parts[3], text, diagnostics)
                if alpha < 255:
                    return hex6 + "%02X" % alpha
            return hex6
        _record_color_skip(diagnostics, f"unreadable rgb() value: {text}")
        return None

    hsl = re.match(r"hsla?\(([^)]+)\)", text, re.IGNORECASE)
    if hsl:
        parts = re.split(r"[,\s/]+", hsl.group(1).strip())
        parts = [p for p in parts if p]
        if len(parts) >= 3:
            try:
                h = float(parts[0].rstrip("deg"))
                s = float(parts[1].rstrip("%"))
                lightness = float(parts[2].rstrip("%"))
            except ValueError:
                _record_color_skip(diagnostics, f"unreadable hsl() channels: {text}")
                return None
            hex6 = _hsl_to_hex(h, s, lightness)
            if len(parts) >= 4:
                alpha = _alpha_or_opaque(parts[3], text, diagnostics)
                if alpha < 255:
                    return hex6 + "%02X" % alpha
            return hex6
        _record_color_skip(diagnostics, f"unreadable hsl() value: {text}")
        return None

    return None


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


def _alpha_or_opaque(token: str, source: str, diagnostics: list[dict] | None) -> int:
    """Read an alpha channel, falling back to fully opaque when it is unreadable.

    Tailwind serves `rgb(15 23 42 / var(--tw-text-opacity))`: the three channels
    carry the site's real color and only the alpha is an unresolved custom
    property. Dropping the whole swatch there would throw away good brand
    evidence, so we keep the color and read it as opaque — which is also what
    the browser shows when the opacity var is unset.
    """
    try:
        return _parse_alpha(token)
    except (ValueError, TypeError):
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


def _selector_role(selector: str) -> tuple[list[str], list[str], float]:
    """Return (bg_hints, fg_hints, weight) for a selector's role mapping."""
    sel = selector.lower()
    tokens = re.split(r"[\s>+~]+", sel)

    def has(*names: str) -> bool:
        for token in tokens:
            compound = token.strip()
            for name in names:
                if name.startswith(".") or name.startswith("["):
                    if name in compound:
                        return True
                elif re.search(r"(^|[.#:\[])" + re.escape(name) + r"($|[.#:\[])", compound) or compound == name or compound.startswith(name + "."):
                    return True
                if compound == name:
                    return True
        return False

    # body/html
    if has("body", "html"):
        return (["page-bg"], ["body-text"], 5.0)
    # headings
    if has("h1", "h2", "h3"):
        return ([], ["heading-text"], 4.0)
    # paragraph/list body text
    if has("p", "li"):
        return ([], ["body-text"], 3.0)
    # buttons / cta
    if has("button", ".btn", ".button") or "[class*=cta]" in sel or "cta" in sel:
        return (["button-bg"], ["button-text"], 4.0)
    # links
    if has("a"):
        return ([], ["link"], 3.0)
    # nav/header/footer
    if has("nav", "header", "footer"):
        return ([], [], 2.0)
    return ([], [], 0.5)


# --- CSS iteration --------------------------------------------------------------


def _decl_value_text(decl) -> str:
    return tinycss2.serialize(decl.value).strip()


def _collect_custom_props(stylesheets, existing: dict[str, str]) -> dict[str, str]:
    props = dict(existing)
    for sheet in stylesheets:
        rules = tinycss2.parse_stylesheet(
            sheet.text, skip_comments=True, skip_whitespace=True
        )
        for rule in rules:
            if rule.type != "qualified-rule":
                continue
            selector = tinycss2.serialize(rule.prelude).strip().lower()
            if not any(part.strip() in ("html", ":root") for part in selector.split(",")):
                continue
            for decl in tinycss2.parse_declaration_list(
                rule.content, skip_comments=True, skip_whitespace=True
            ):
                if getattr(decl, "type", None) == "declaration" and decl.name.startswith("--"):
                    props[decl.name] = _decl_value_text(decl)
    return props


def _iter_qualified_rules(rules, theme: str):
    """Yield (selector_list, declarations, theme) flattening dark-scheme media."""
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
        elif rule.type == "at-rule" and (rule.lower_at_keyword == "media"):
            prelude = tinycss2.serialize(rule.prelude).lower()
            inner_theme = theme
            if "prefers-color-scheme" in prelude and "dark" in prelude:
                inner_theme = "dark"
            if rule.content is None:
                continue
            inner = tinycss2.parse_rule_list(
                rule.content, skip_comments=True, skip_whitespace=True
            )
            yield from _iter_qualified_rules(inner, inner_theme)


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


def _line_height(value: str) -> float | None:
    value = value.strip().lower()
    try:
        return float(value)
    except ValueError:
        px = _px_from_length(value)
        return px / 16.0 if px is not None else None


def _letter_spacing(value: str) -> float | None:
    value = value.strip().lower()
    if value in ("normal", "inherit"):
        return None
    m = re.match(r"^(-?[\d.]+)(px|rem|em)$", value)
    if not m:
        return None
    number = float(m.group(1))
    unit = m.group(2)
    if unit == "em":
        return number
    if unit == "rem":
        return number
    return number / 16.0  # px → em approximation


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
            for m in re.finditer(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)", value):
                src_urls.append(_absolutize(base_url, m.group(1)))
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
        for rule in rules:
            if rule.type == "at-rule" and rule.lower_at_keyword == "font-face":
                decls = tinycss2.parse_declaration_list(
                    rule.content or [], skip_comments=True, skip_whitespace=True
                )
                face = _parse_font_face(decls, base)
                if face is not None:
                    yield sheet.url, face


def font_face_sources(stylesheets, page_url: str) -> list[str]:
    """Absolute URLs of the font files ``@font-face`` actually SELECTS — one per face.

    This is the binding set: every face the evidence builder later looks up has bytes waiting
    under the same key. It is no longer the whole fetch list — see
    :func:`font_face_source_rungs`.
    """
    urls: list[str] = []
    for _sheet_url, face in iter_font_faces(stylesheets, page_url):
        if face.source_url and face.source_url not in urls:
            urls.append(face.source_url)
    return urls


def font_face_source_rungs(stylesheets, page_url: str) -> list[str]:
    """EVERY ``src`` URL every ``@font-face`` declares, bound rung first within each face.

    What capture downloads (clone-fidelity F0.2 fix round 1). A face routinely lists
    ``woff2, woff, ttf``; we bind the best format the same way a browser would, but F2
    rewrites the captured ``@font-face`` block verbatim onto our store, so a rung we never
    fetched is a font that fails to load for whichever browser picks it.
    """
    urls: list[str] = []
    for _sheet_url, face in iter_font_faces(stylesheets, page_url):
        for url in face.source_urls or ([face.source_url] if face.source_url else []):
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

    _parse_css(snapshot, parsed, custom_props, base_url)
    if snapshot.computed_samples:
        _parse_computed_samples(snapshot, parsed)
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

    # @font-face — the shared walk capture also downloads from, so a face's
    # source_url is always the key its bytes were fetched under.
    for sheet_url, face in iter_font_faces(snapshot.stylesheets, base_url):
        _accumulate_font(parsed, face, sheet_url)

    for sheet in snapshot.stylesheets:
        rules = tinycss2.parse_stylesheet(
            sheet.text, skip_comments=True, skip_whitespace=True
        )
        for selectors, decls, theme in _iter_qualified_rules(rules, "light"):
            _parse_rule(parsed, selectors, decls, theme, custom_props, sheet.url)


def _parse_rule(
    parsed: ParsedSite,
    selectors: list[str],
    decls,
    theme: str,
    custom_props: dict[str, str],
    stylesheet_url: str,
) -> None:
    for selector in selectors:
        bg_hints, fg_hints, weight = _selector_role(selector)
        locator = f"{stylesheet_url} :: {selector}"
        family = None
        size_px = None
        font_weight = None
        line_height = None
        letter_spacing = None
        for decl in decls:
            if getattr(decl, "type", None) != "declaration":
                continue
            name = decl.name.lower()
            value = _decl_value_text(decl)
            if name in ("color", "fill"):
                hex_value = parse_color_value(
                    value, custom_props, diagnostics=parsed.diagnostics
                )
                if hex_value:
                    parsed.colors.append(
                        ParsedColor(hex_value, weight, theme, list(fg_hints), None, locator)
                    )
            elif name in ("background", "background-color"):
                hex_value = parse_color_value(
                    value.split()[0] if value else value,
                    custom_props,
                    diagnostics=parsed.diagnostics,
                )
                if hex_value:
                    parsed.colors.append(
                        ParsedColor(hex_value, weight, theme, list(bg_hints), None, locator)
                    )
            elif name in ("border-color", "border"):
                hex_value = _extract_first_color(
                    value, custom_props, diagnostics=parsed.diagnostics
                )
                if hex_value:
                    parsed.colors.append(
                        ParsedColor(hex_value, weight, theme, ["border"] if weight >= 2.0 else [], None, locator)
                    )
            elif name == "font-family":
                family = _first_family(value)
            elif name == "font-size":
                size_px = _px_from_length(value)
            elif name == "font-weight":
                font_weight = _weight_int(value)
            elif name == "line-height":
                line_height = _line_height(value)
            elif name == "letter-spacing":
                letter_spacing = _letter_spacing(value)

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
    for sample in snapshot.computed_samples or []:
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
            parsed.type_samples.append(
                ParsedType(
                    label="body" if label == "html" else label,
                    family=_first_family(str(family)),
                    weight=_weight_int(str(sample.get("fontWeight") or "")),
                    size_px=_px_from_length(str(sample.get("fontSize") or "")),
                    line_height=_line_height(str(sample.get("lineHeight") or "")),
                    letter_spacing=_letter_spacing(str(sample.get("letterSpacing") or "")),
                    locator=locator,
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
        markup = node.html or ""
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

    for node in tree.css("img"):
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
                ),
            )
        )

    # CSS background-image art (gradients, hero panels) — same shared chooser the collector
    # used, so the bytes are already in the snapshot. No DOM size hints exist for these, so
    # they rank by file size alone.
    seen = {asset.source_url for _, _, asset in candidates} | logo_urls
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
    from urllib.parse import urlparse

    host = urlparse(base_url).hostname or ""
    host = host.removeprefix("www.")
    stem = host.split(".")[0] if host else ""
    if not stem:
        return None
    return " ".join(part.capitalize() for part in re.split(r"[-_]", stem) if part)
