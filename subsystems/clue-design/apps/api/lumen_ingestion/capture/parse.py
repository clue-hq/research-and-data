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


def parse_color_value(raw: str, custom_props: dict[str, str]) -> str | None:
    """Parse a CSS color token to #RRGGBB(AA). One var() hop resolved. Returns
    None for keywords we skip (transparent/inherit/currentColor/unset)."""
    text = raw.strip()
    lowered = text.lower()
    if lowered in _SKIP_COLOR_KEYWORDS:
        return None

    var_match = re.match(r"var\(\s*(--[\w-]+)\s*(?:,\s*([^)]+))?\)", text, re.IGNORECASE)
    if var_match:
        name = var_match.group(1)
        resolved = custom_props.get(name)
        if resolved is None:
            fallback = var_match.group(2)
            if fallback is None:
                return None
            return parse_color_value(fallback, custom_props)
        return parse_color_value(resolved, custom_props)

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

    rgb = re.match(r"rgba?\(([^)]+)\)", text, re.IGNORECASE)
    if rgb:
        parts = re.split(r"[,\s/]+", rgb.group(1).strip())
        parts = [p for p in parts if p]
        if len(parts) >= 3:
            try:
                comps = [_parse_channel(parts[i]) for i in range(3)]
            except ValueError:
                return None
            hex6 = "#%02X%02X%02X" % (comps[0], comps[1], comps[2])
            if len(parts) >= 4:
                alpha = _parse_alpha(parts[3])
                if alpha < 255:
                    return hex6 + "%02X" % alpha
            return hex6
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
                return None
            hex6 = _hsl_to_hex(h, s, lightness)
            if len(parts) >= 4:
                alpha = _parse_alpha(parts[3])
                if alpha < 255:
                    return hex6 + "%02X" % alpha
            return hex6
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
    chosen = None
    if src_urls:
        chosen = sorted(src_urls, key=lambda u: _FORMAT_RANK.get(_font_format(u), 3))[0]
    face = ParsedFontFace(
        weight=weight if weight is not None else 400,
        style=style,
        source_url=chosen,
        format=_font_format(chosen) if chosen else None,
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
        hex_value = parse_color_value(value, custom_props)
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

    for sheet in snapshot.stylesheets:
        rules = tinycss2.parse_stylesheet(
            sheet.text, skip_comments=True, skip_whitespace=True
        )
        # @font-face at top level (and inside media, though rare).
        for rule in rules:
            if rule.type == "at-rule" and rule.lower_at_keyword == "font-face":
                decls = tinycss2.parse_declaration_list(
                    rule.content or [], skip_comments=True, skip_whitespace=True
                )
                face = _parse_font_face(decls, base_url)
                if face is not None:
                    _accumulate_font(parsed, face, sheet.url)

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
                hex_value = parse_color_value(value, custom_props)
                if hex_value:
                    parsed.colors.append(
                        ParsedColor(hex_value, weight, theme, list(fg_hints), None, locator)
                    )
            elif name in ("background", "background-color"):
                hex_value = parse_color_value(value.split()[0] if value else value, custom_props)
                if hex_value:
                    parsed.colors.append(
                        ParsedColor(hex_value, weight, theme, list(bg_hints), None, locator)
                    )
            elif name in ("border-color", "border"):
                hex_value = _extract_first_color(value, custom_props)
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


def _extract_first_color(value: str, custom_props: dict[str, str]) -> str | None:
    for token in re.split(r"\s+", value.strip()):
        hex_value = parse_color_value(token, custom_props)
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
            hex_value = parse_color_value(str(bg), parsed.custom_props)
            if hex_value:
                parsed.colors.append(
                    ParsedColor(hex_value, weight, "light", list(bg_hints), None, locator)
                )
        if color:
            hex_value = parse_color_value(str(color), parsed.custom_props)
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


def _parse_dom(snapshot: SiteSnapshot, parsed: ParsedSite, base_url: str) -> None:
    tree = HTMLParser(snapshot.html)
    seen_logo_urls: set[str] = set()

    # The site's OWN logo lives in header/nav/home-link chrome. A bare
    # [class*=logo] selector would also sweep up client/press logo walls
    # ("Trusted by" sections — live insighthealth.ai yields 50 of them), so
    # candidates are position-restricted and capped: first 2 imgs + first
    # inline svg in document order.
    primary_img_candidates: list[ParsedAsset] = []
    for node in tree.css("header img, nav img, a[href='/'] img"):
        src = node.attributes.get("src")
        if not src:
            continue
        url = _absolutize(base_url, src)
        if url in seen_logo_urls:
            continue
        seen_logo_urls.add(url)
        primary_img_candidates.append(
            ParsedAsset(
                sha256=_download_by_url(snapshot, url),
                source_url=url,
                kind="logo",
                usage_hint="primary",
                width=_int_attr(node, "width"),
                height=_int_attr(node, "height"),
                locator="dom :: header img",
            )
        )
    parsed.logos.extend(primary_img_candidates[:2])

    for node in tree.css("header svg, nav svg, a[href='/'] svg"):
        markup = node.html or ""
        if not markup:
            continue
        parsed.logos.append(
            ParsedAsset(
                sha256=None,
                source_url=None,
                kind="logo",
                usage_hint="primary",
                locator="dom :: inline svg",
            )
        )
        parsed._inline_svgs = getattr(parsed, "_inline_svgs", [])  # type: ignore[attr-defined]
        parsed._inline_svgs.append(markup)  # type: ignore[attr-defined]
        break

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

    # meta og:logo → logo
    og_logo = _meta_content(tree, "og:logo")
    if og_logo:
        url = _absolutize(base_url, og_logo)
        parsed.logos.append(
            ParsedAsset(
                sha256=_download_by_url(snapshot, url),
                source_url=url,
                kind="logo",
                usage_hint="primary",
                locator="dom :: og:logo",
            )
        )

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
    for node in tree.css("img"):
        src = node.attributes.get("src")
        if not src:
            continue
        if src.startswith("data:"):
            # Skip large data URIs; parse.py never inlines them.
            if len(src) > 50 * 1024:
                continue
        url = _absolutize(base_url, src)
        if url in logo_urls:
            continue
        width = _int_attr(node, "width")
        height = _int_attr(node, "height")
        if width is not None and height is not None and width <= 4 and height <= 4:
            continue  # tracking pixel
        sha = _download_by_url(snapshot, url)
        file_size = 0
        if sha:
            data = snapshot.download_bytes(sha)
            file_size = len(data) if data else 0
        # keep when it has size hints OR a fetched file ≥ 10 KB
        if not (width or height) and file_size < 10 * 1024 and sha is None:
            continue
        area = float((width or 0) * (height or 0))
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
                    locator="dom :: img",
                ),
            )
        )

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    cap = 12
    kept = candidates[:cap]
    skipped = len(candidates) - len(kept)
    for _, _, asset in kept:
        parsed.images.append(asset)
    if skipped > 0:
        parsed.diagnostics.append(
            {
                "code": "LUMI0504",
                "severity": "info",
                "message": f"image candidate cap reached; skipped {skipped} image(s)",
            }
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
