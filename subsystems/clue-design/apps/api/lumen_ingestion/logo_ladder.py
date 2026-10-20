"""The logo ladder: find a company's real logo family from its website.

Ported from the validated `.context/poc-logo-ladder` pilot. Two stages, both
pure over already-fetched content — this module never opens a socket except in
the one clearly-marked `fetch_logo_family` driver at the bottom.

Stage 1 (`harvest`) pulls logo candidates from EVERY rung of the ladder — header
and nav marks, inline SVGs, `<picture>`/srcset colour-scheme sources, footer,
CSS background images in chrome, JSON-LD `Organization.logo`, og:logo/og:image,
manifest/apple-touch/favicon, first-party brand pages. It fetches nothing; the
caller supplies bytes through `attach_bytes`. The hard invariant is that a
candidate is never silently dropped: a failed fetch is recorded in
`fetch_error` and the candidate stays in the ranked list.

Stage 2 (`resolve`) ranks, classifies and picks slots. Two guards make it safe,
and both exist because the pilot was confidently wrong without them:

* **Asset-level identity.** An asset must carry the brand's OWN name evidence
  (alt, filename, JSON-LD org name, page title — boundary-anchored, and never
  the page-derived synthetic URL an inline SVG gets). Without this the pilot
  returned the AWS logo as WorkSpan's, because AWS's logo is served from
  WorkSpan's own CDN and every host-based provenance check passed cleanly.
* **Never synthesize.** A variant is a real published asset, or — for a
  `currentColor` SVG only — that same asset exported in an ink the brand's own
  stylesheet was OBSERVED painting it with. An ink that was never observed is
  never invented. Otherwise the slot is honestly absent.

When identity fails the resolution is fail-closed: zero winners, status
`needs_review`, and the full ranked candidate list preserved so a human can
choose.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit, urlunsplit

from selectolax.parser import HTMLParser

from .capture.cssurl import iter_css_urls

__all__ = [
    "LadderCandidate",
    "LadderResolution",
    "LadderSlot",
    "attach_bytes",
    "candidate_asset_urls",
    "discover_brand_pages",
    "fetch_logo_family",
    "harvest",
    "merge_rendered_observations",
    "registrable_domain",
    "repair_svg_case",
    "resolve",
]


# ---------------------------------------------------------------------------
# hosts
# ---------------------------------------------------------------------------

# A registrable domain needs the public suffix list to be exactly right. The
# pilot used `tldextract`, which drags in `requests` (this subsystem is
# deliberately httpx-only) plus a bundled PSL snapshot, for three uses that are
# all same-organisation COMPARISONS. This table covers the multi-label suffixes
# those comparisons actually meet; anything else folds to the last two labels.
_MULTI_LABEL_SUFFIXES = frozenset(
    {
        "co.uk", "org.uk", "me.uk", "ac.uk", "gov.uk", "net.uk", "sch.uk",
        "com.au", "net.au", "org.au", "edu.au", "gov.au", "id.au",
        "co.nz", "net.nz", "org.nz", "govt.nz",
        "co.za", "org.za", "net.za",
        "co.jp", "or.jp", "ne.jp", "ac.jp", "go.jp",
        "co.kr", "or.kr", "ne.kr",
        "co.in", "net.in", "org.in", "firm.in", "gen.in",
        "com.br", "net.br", "org.br",
        "com.mx", "com.ar", "com.co", "com.pe", "com.tr", "com.tw",
        "com.sg", "com.my", "com.hk", "com.cn", "net.cn", "org.cn",
        "co.il", "org.il", "com.pl", "com.ua", "com.ph", "com.vn",
        # Hosting suffixes where two sites under the same suffix are NOT the
        # same organisation. Getting these wrong makes the first-party check
        # over-permissive, which is the unsafe direction.
        "github.io", "gitlab.io", "netlify.app", "vercel.app", "pages.dev",
        "web.app", "firebaseapp.com", "herokuapp.com", "azurewebsites.net",
        "s3.amazonaws.com", "cloudfront.net", "myshopify.com", "webflow.io",
        "squarespace.com", "wixsite.com", "wordpress.com",
    }
)


def registrable_domain(url_or_host: str) -> str:
    """`https://cdn.acme.co.uk/x` → `acme.co.uk`. Empty string when unparseable."""
    raw = (url_or_host or "").strip()
    if not raw:
        return ""
    host = raw
    if "//" in raw or raw.lower().startswith("http"):
        host = urlsplit(raw).netloc
    host = host.split("@")[-1].split(":")[0].strip("[]").lower().rstrip(".")
    if not host or _is_ip_literal(host):
        return host
    labels = [p for p in host.split(".") if p]
    if len(labels) <= 2:
        return ".".join(labels)
    if ".".join(labels[-2:]) in _MULTI_LABEL_SUFFIXES:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def _is_ip_literal(host: str) -> bool:
    return bool(re.fullmatch(r"[0-9.]+", host)) or ":" in host


def _domain_label(domain: str) -> str:
    """The organisation label: `acme` from `www.acme.co.uk`."""
    reg = registrable_domain(domain)
    return reg.split(".")[0] if reg else ""


def host_of(url: str) -> str:
    return urlsplit(url).netloc.lower()


def norm_url(base: str, raw: str | None) -> str | None:
    if not raw:
        return None
    raw = raw.strip()
    if not raw or raw.startswith("data:") or raw.startswith("javascript:"):
        return None
    if raw.startswith("//"):
        raw = (urlsplit(base).scheme or "https") + ":" + raw
    parts = urlsplit(urljoin(base, raw))
    if parts.scheme not in ("http", "https"):
        return None
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


# ---------------------------------------------------------------------------
# candidates
# ---------------------------------------------------------------------------

RUNGS = (
    "NAV_VISIBLE", "HEADER", "INLINE_SVG", "BRAND_PAGE", "PAGE_LOGO_NAMED",
    "JSONLD_ORG", "FOOTER", "CSS_BG", "MANIFEST_ICON", "APPLE_TOUCH",
    "OG_LOGO", "OG_IMAGE", "FAVICON",
)


@dataclass
class LadderCandidate:
    """One harvested logo candidate, with every scrap of evidence about it."""

    url: str = ""
    source_domain: str = ""
    rung: str = ""
    dom_role: str = ""
    alt_text: str | None = None
    link_destination: str | None = None
    fmt: str | None = None
    width: int | None = None
    height: int | None = None
    occurrences: int = 1
    background_context: str | None = None
    background_source: str | None = None
    theme_signal: str | None = None
    sha256: str | None = None
    byte_len: int | None = None
    fetch_error: str | None = None
    found_on: str = ""
    dom_index: int | None = None
    visibility_state: str | None = None
    scroll_state: str | None = None
    scroll_swap_partner: bool = False
    # The page preloads this exact file under a header/nav logo name (see `harvest`).
    preloaded_header_logo: bool = False
    render_key: str | None = None
    observed_ink: str | None = None
    # The browser's painted box, kept apart from width/height because those get
    # overwritten with the SVG's own declared attributes — and for a padded
    # asset (linear.app: 400x22 declared, 88x22 painted) that is a different
    # number that breaks any lookup keyed on rendered size.
    rendered_w: int | None = None
    rendered_h: int | None = None
    inline_svg_text: str | None = None
    body: bytes | None = None
    content_type: str | None = None
    notes: list[str] = field(default_factory=list)

    # Filled in by `resolve`.
    appearance: dict = field(default_factory=dict)
    lockup: str = "unknown"
    lockup_evidence: dict = field(default_factory=dict)
    score: float = 0.0
    score_signals: list[str] = field(default_factory=list)
    junk_hits: list[str] = field(default_factory=list)
    first_party: bool = False
    first_party_reason: str = ""
    variant: str = "unknown"
    variant_basis: str = ""
    variant_basis_rank: int = 9
    is_mark: bool = False
    mark_reason: str | None = None
    shape_key: str | None = None
    identity_anchored: bool = False
    identity_anchor: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        """A compact, JSON-safe view for tool output and needs_review lists."""
        return {
            "url": self.url,
            "rung": self.rung,
            "fmt": self.fmt,
            "width": self.width,
            "height": self.height,
            "alt_text": self.alt_text,
            "lockup": self.lockup,
            "variant": self.variant,
            "score": round(self.score, 2),
            "sha256": self.sha256,
            "fetch_error": self.fetch_error,
            "junk_hits": self.junk_hits[:4],
        }


@dataclass
class LadderSlot:
    """One resolved slot. `body` is the bytes to ingest — for a materialized
    adaptive asset that is NOT the candidate's own bytes, it is the same
    artwork re-exported in an observed ink."""

    candidate: LadderCandidate
    provenance: str  # "genuine" | "materialized-adaptive"
    body: bytes
    content_type: str
    basis: str
    ink: str | None = None
    surface: str | None = None


@dataclass
class LadderResolution:
    status: str = "needs_review"
    confidence: float = 0.0
    confidence_breakdown: list[str] = field(default_factory=list)
    identity: dict = field(default_factory=dict)
    slots: dict[str, LadderSlot | None] = field(default_factory=dict)
    lockup_completeness: str = "unknown"
    theme_surfaces: dict = field(default_factory=dict)
    adaptive_placements: list[dict] = field(default_factory=list)
    alternate_lockups: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    ranked: list[LadderCandidate] = field(default_factory=list)
    counts: dict = field(default_factory=dict)

    @property
    def variant_provenance(self) -> dict:
        return {
            name: (slot.provenance if slot else None)
            for name, slot in self.slots.items()
        }


# ---------------------------------------------------------------------------
# stage 1 — harvest
# ---------------------------------------------------------------------------

BRAND_PATH_HINTS = (
    "/brand", "/brand-assets", "/brandkit", "/brand-kit", "/press", "/presskit",
    "/press-kit", "/media-kit", "/mediakit", "/newsroom", "/news-room",
    "/about/press", "/company/press", "/logos",
)

# Chrome zones by class/id, for sites that use neither semantic tags nor ARIA.
# mngi.com (Drupal, `region-header`) harvested four candidates and missed its
# own header entirely until this existed — tag-name detection is brittle.
_ZONE_RE = re.compile(
    r"(site-header|masthead|navbar|nav-bar|topbar|top-bar|site-footer|main-header|"
    r"region-header|region-footer|page-header|page-footer|header-wrapper|"
    r"footer-wrapper|global-header|global-footer|^header$|^footer$|^nav$)",
    re.I,
)
_CHROME_SEL_HINT = re.compile(
    r"(header|nav|navbar|masthead|topbar|site-head|footer|logo|brand)", re.I
)
_LOGO_NAMED_RE = re.compile(r"(logo|wordmark|brandmark|brand-mark)", re.I)
# A file name that says where the logo sits: the header or the nav. Read only off a
# preloaded image's own name (`qc-topnav-logo.svg`), never off the page around it.
_HEADER_NAMED_RE = re.compile(
    r"(?:^|[^a-z])(?:top-?nav|nav-?bar|nav|site-?header|header|masthead|top-?bar)(?:[^a-z]|$)",
    re.I,
)
_JSONLD_ORG_TYPES = (
    "Organization", "Corporation", "LocalBusiness", "MedicalOrganization",
    "WebSite", "MedicalClinic", "Physician",
)


def _tree_of(html_or_tree) -> HTMLParser:
    return html_or_tree if isinstance(html_or_tree, HTMLParser) else HTMLParser(html_or_tree)


def _attr(node, name: str) -> str | None:
    value = node.attributes.get(name)
    return value if value else None


def _classes(node) -> list[str]:
    raw = node.attributes.get("class") or ""
    return [c for c in raw.split() if c]


def _int_or_none(value) -> int | None:
    if value is None:
        return None
    match = re.match(r"^\s*(\d+)", str(value))
    return int(match.group(1)) if match else None


def _link_dest(node) -> str | None:
    # Five levels was too shallow: real headers wrap the logo in several divs
    # between the <a> and the <svg>, and the link-home evidence was lost.
    walker = node
    for _ in range(8):
        walker = walker.parent
        if walker is None:
            return None
        if walker.tag == "a":
            return walker.attributes.get("href")
    return None


def _srcset_urls(srcset: str | None) -> list[str]:
    if not srcset:
        return []
    out = []
    for part in srcset.split(","):
        pieces = part.strip().split()
        if pieces:
            out.append(pieces[0])
    return out[:4]


def _iter_jsonld(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _iter_jsonld(value)
    elif isinstance(node, list):
        for value in node:
            yield from _iter_jsonld(value)


def _jsonld_nodes(tree):
    for script in tree.css("script"):
        stype = (script.attributes.get("type") or "").lower()
        if "ld+json" not in stype:
            continue
        try:
            data = json.loads(script.text() or "{}")
        except Exception:  # noqa: BLE001 - a malformed island is not fatal
            continue
        yield from _iter_jsonld(data)


def jsonld_org_names(html_or_tree) -> list[str]:
    tree = _tree_of(html_or_tree)
    names = []
    for node in _jsonld_nodes(tree):
        if isinstance(node, dict) and node.get("name") and node.get("@type") in _JSONLD_ORG_TYPES:
            names.append(str(node["name"]))
    return names


def page_title(html_or_tree) -> str | None:
    node = _tree_of(html_or_tree).css_first("title")
    return node.text().strip() if node else None


def discover_brand_pages(html_or_tree, base_url: str, domain: str) -> list[str]:
    """First-party /brand, /press, /media-kit style pages worth one extra hop."""
    tree = _tree_of(html_or_tree)
    found: list[str] = []
    for anchor in tree.css("a[href]"):
        url = norm_url(base_url, anchor.attributes.get("href"))
        if not url or registrable_domain(url) != registrable_domain(domain):
            continue
        path = urlsplit(url).path.lower().rstrip("/")
        if any(path == hint or path.endswith(hint) for hint in BRAND_PATH_HINTS):
            if url not in found:
                found.append(url)
    for hint in ("/brand", "/press"):
        url = norm_url(base_url, hint)
        if url and url not in found:
            found.append(url)
    return found


#: A ``background`` / ``background-image`` declaration; group 1 is its value, which ends at
#: the ``;`` that closes the declaration. The value is handed WHOLE to the shared
#: escape-aware reader instead of being scanned for ``url(`` here — see ``_parse_css``.
#:
#: This is NOT byte-identical scoping to the regex it replaced. The old pattern hopped over
#: ``[^;}]*`` to reach ``url(`` but then captured with ``[^'\")]+``, a class that does NOT
#: exclude ``;`` — so a literal semicolon INSIDE a url token (``url(/a;b.png)``) survived
#: there and truncates here. That is a deliberate alignment, not a regression: this is now
#: the same declaration scoping ``candidates._CSS_ASSET_DECL_RE`` and
#: ``imgsrc._BACKGROUND_DECL_RE`` already use (both ``[^;{}]*``), so a ``;``-bearing url is a
#: pre-existing package-wide limitation shared by all three scopers rather than a ladder
#: quirk. Before, the ladder could rank a candidate the collector never fetched bytes for.
#: Fixing it properly means teaching all three to skip a ``;`` inside a ``url()`` token —
#: recorded for F2, deliberately not done here.
_BG_DECL_RE = re.compile(r"background(?:-image)?\s*:([^;}]*)", re.I)


def _parse_css(css_text: str, base_url: str):
    """Return (background-image urls by selector, background-color by selector)."""
    images, colors = [], {}
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css_text):
        selector, body = match.group(1).strip(), match.group(2)
        if len(selector) > 300:
            continue
        selectors = [s.strip() for s in selector.split(",")]
        for declaration in _BG_DECL_RE.finditer(body):
            for token in iter_css_urls(declaration.group(1)):
                absolute = norm_url(base_url, token)
                if absolute:
                    images.append((selectors, absolute))
        background = _extract_bg(body)
        if background:
            for one in selectors:
                key = one.split()[-1] if " " in one else one
                key = key.split(":")[0]
                if key and key not in colors:
                    colors[key] = background
    return images, colors


_COLOR_RE = re.compile(r"background(?:-color)?\s*:\s*([^;\"'}]+)", re.I)


def _extract_bg(style: str | None) -> str | None:
    if not style:
        return None
    match = _COLOR_RE.search(style)
    if not match:
        return None
    value = match.group(1).strip()
    if value.startswith("url(") or value in ("none", "transparent", "inherit", "initial"):
        return None
    return value


def color_lightness(color: str | None) -> float | None:
    """Rough 0..1 lightness of a CSS colour string; None if unparseable."""
    if not color:
        return None
    text = str(color).strip().lower()
    named = {
        "white": (255, 255, 255), "black": (0, 0, 0),
        "#fff": (255, 255, 255), "#ffffff": (255, 255, 255),
        "#000": (0, 0, 0), "#000000": (0, 0, 0),
    }
    rgb = named.get(text)
    if rgb is None:
        match = re.match(r"#([0-9a-f]{3,8})$", text)
        if match:
            digits = match.group(1)
            if len(digits) == 3:
                rgb = tuple(int(ch * 2, 16) for ch in digits)
            elif len(digits) in (6, 8):
                rgb = tuple(int(digits[i : i + 2], 16) for i in (0, 2, 4))
        else:
            match = re.match(r"rgba?\(([^)]+)\)", text)
            if match:
                parts = [p.strip() for p in match.group(1).replace("/", ",").split(",")]
                try:
                    rgb = tuple(int(float(p.rstrip("%"))) for p in parts[:3])
                except ValueError:
                    rgb = None
    if not rgb or len(rgb) < 3:
        return None
    red, green, blue = rgb[:3]
    return (0.299 * red + 0.587 * green + 0.114 * blue) / 255.0


def to_hex(color: str | None) -> str | None:
    if not color:
        return None
    text = str(color).strip()
    match = re.match(r"rgba?\(([^)]+)\)", text)
    if not match:
        return text if text.startswith("#") else None
    parts = [p.strip() for p in match.group(1).replace("/", ",").split(",")]
    try:
        red, green, blue = (int(round(float(p.rstrip("%")))) for p in parts[:3])
    except ValueError:
        return None
    return f"#{red:02x}{green:02x}{blue:02x}"


def _bg_for_element(node, css_colors: dict, page_bg: str | None) -> str | None:
    walker = node
    depth = 0
    while walker is not None and depth < 8:
        background = _extract_bg(walker.attributes.get("style"))
        if background:
            return background
        for cls in _classes(walker):
            if css_colors.get("." + cls):
                return css_colors["." + cls]
        node_id = walker.attributes.get("id")
        if node_id and css_colors.get("#" + node_id):
            return css_colors["#" + node_id]
        if walker.tag and css_colors.get(walker.tag):
            return css_colors[walker.tag]
        walker = walker.parent
        depth += 1
    return page_bg


def harvest(
    html_or_tree,
    page_url: str,
    stylesheets: list[tuple[str, str]] | None = None,
    *,
    domain: str | None = None,
    force_rung: str | None = None,
    start_index: int = 0,
) -> list[LadderCandidate]:
    """Pull logo candidates from every rung. Fetches nothing.

    `stylesheets` is a list of (url, text) pairs the caller already fetched;
    inline `<style>` blocks are read straight out of the tree.
    """
    tree = _tree_of(html_or_tree)
    out: list[LadderCandidate] = []

    css_text = "\n".join(text for _, text in (stylesheets or []))
    for style in tree.css("style"):
        css_text += "\n" + (style.text() or "")
    css_bg_images, css_colors = _parse_css(css_text, page_url)

    page_bg = None
    body = tree.css_first("body")
    if body is not None:
        page_bg = _extract_bg(body.attributes.get("style")) or css_colors.get("body")

    def add(
        raw_url,
        rung,
        dom_role,
        node=None,
        alt=None,
        theme=None,
        link_dest=None,
        width=None,
        height=None,
        inline_svg=None,
        dom_index=None,
    ) -> None:
        if inline_svg is None:
            url = norm_url(page_url, raw_url)
            if not url:
                return
        else:
            url = f"{page_url}#inline-svg-{start_index + len(out)}"
        background = None
        if node is not None:
            background = _bg_for_element(node, css_colors, page_bg)
        out.append(
            LadderCandidate(
                url=url,
                source_domain=host_of(url) or host_of(page_url),
                rung=force_rung or rung,
                dom_role=dom_role,
                alt_text=alt,
                link_destination=link_dest,
                background_context=background,
                theme_signal=theme,
                found_on=page_url,
                dom_index=dom_index,
                width=width,
                height=height,
                inline_svg_text=inline_svg,
            )
        )

    # ---- rungs 1 & 2: header/nav and footer visible marks
    chrome_zones: list[tuple[object, str, str]] = []
    for node in tree.css("header, nav"):
        chrome_zones.append((node, "HEADER" if node.tag == "header" else "NAV_VISIBLE", node.tag))
    for node in tree.css("footer"):
        chrome_zones.append((node, "FOOTER", "footer"))
    # ARIA landmarks - reliable and framework-independent.
    for role, rung in (("banner", "HEADER"), ("navigation", "NAV_VISIBLE"), ("contentinfo", "FOOTER")):
        for node in tree.css(f"[role='{role}']"):
            chrome_zones.append((node, rung, f"{node.tag}[role={role}]"))
    for node in tree.css("[class]"):
        if node.tag in ("header", "nav", "footer"):
            continue
        classes = " ".join(_classes(node))
        if _ZONE_RE.search(classes) or any(_ZONE_RE.search(c) for c in _classes(node)):
            rung = "FOOTER" if "footer" in classes.lower() else "HEADER"
            chrome_zones.append((node, rung, f"{node.tag}.{classes[:40]}"))
    for node in tree.css("[id]"):
        if node.tag in ("header", "nav", "footer"):
            continue
        node_id = node.attributes.get("id") or ""
        if _ZONE_RE.search(node_id):
            rung = "FOOTER" if "footer" in node_id.lower() else "HEADER"
            chrome_zones.append((node, rung, f"{node.tag}#{node_id[:40]}"))

    seen_zones: set[int] = set()
    for zone, rung, role in chrome_zones:
        if id(zone) in seen_zones:
            continue
        seen_zones.add(id(zone))
        _extract_marks(zone, rung, role, add)

    # ---- whole-page sweep: any image on the first-party page whose own name or
    # alt says logo/brand/wordmark. Chrome-zone detection is inherently brittle,
    # and an asset literally named `logo.svg` on the company's own homepage is
    # real evidence regardless of which div it sits in.
    for img in tree.css("img"):
        src = _attr(img, "src") or _attr(img, "data-src")
        if not src:
            continue
        if _LOGO_NAMED_RE.search(src) or _LOGO_NAMED_RE.search(img.attributes.get("alt") or ""):
            add(
                src,
                "PAGE_LOGO_NAMED",
                "page-wide sweep: asset named 'logo'",
                node=img,
                alt=_attr(img, "alt"),
                link_dest=_link_dest(img),
                width=_int_or_none(img.attributes.get("width")),
                height=_int_or_none(img.attributes.get("height")),
            )

    # ---- preload hints: `<link rel="preload" as="image">` whose own file name says logo.
    # A header logo painted as a CSS background on an empty element (tencentcloud.com:
    # `<i class="qc-topnav__logo-text">`) leaves no <img> and no inline <svg> in the header.
    # The preload hint names the file directly, and a header/nav word in that name is
    # evidence it is the brand's own header logo. Without that evidence the CSS-background
    # copy ranked below a square share image whose name carried the company name.
    preloaded_header: set[str] = set()
    for link in tree.css("link[rel~='preload']"):
        if (link.attributes.get("as") or "").strip().lower() != "image":
            continue
        hrefs = [link.attributes.get("href"), *_srcset_urls(link.attributes.get("imagesrcset"))]
        for raw in hrefs:
            url = norm_url(page_url, raw)
            if not url:
                continue
            basename = urlsplit(url).path.rsplit("/", 1)[-1]
            if not _LOGO_NAMED_RE.search(basename):
                continue
            add(url, "PAGE_LOGO_NAMED", "preload hint: image named 'logo'")
            if _HEADER_NAMED_RE.search(basename):
                preloaded_header.add(url)

    # ---- CSS background images on chrome selectors
    for selectors, url in css_bg_images:
        if any(_CHROME_SEL_HINT.search(s) for s in selectors):
            add(url, "CSS_BG", f"css bg: {selectors[0][:60]}")

    # ---- JSON-LD
    for node in _jsonld_nodes(tree):
        if not isinstance(node, dict):
            continue
        logo = node.get("logo")
        if isinstance(logo, dict):
            logo = logo.get("url") or logo.get("contentUrl")
        if isinstance(logo, str):
            add(logo, "JSONLD_ORG", f"jsonld {node.get('@type')}.logo")
        image = node.get("image")
        if isinstance(image, dict):
            image = image.get("url")
        if isinstance(image, str) and node.get("@type") in ("Organization", "Corporation"):
            add(image, "JSONLD_ORG", f"jsonld {node.get('@type')}.image")

    # ---- meta
    for meta in tree.css("meta"):
        prop = (meta.attributes.get("property") or meta.attributes.get("name") or "").lower()
        content = meta.attributes.get("content")
        if not content:
            continue
        if prop in ("og:logo", "logo"):
            add(content, "OG_LOGO", f"meta {prop}")
        elif prop in ("og:image", "twitter:image", "og:image:secure_url"):
            add(content, "OG_IMAGE", f"meta {prop}")

    # ---- manifest icons / apple-touch / favicon
    for link in tree.css("link[href]"):
        rels = (link.attributes.get("rel") or "").lower()
        href = link.attributes.get("href")
        sizes = (link.attributes.get("sizes") or "").split("x")
        if "apple-touch-icon" in rels:
            add(href, "APPLE_TOUCH", f"link rel={rels}", width=_int_or_none(sizes[0]))
        elif "icon" in rels or "shortcut" in rels:
            add(href, "FAVICON", f"link rel={rels}", width=_int_or_none(sizes[0]))

    # The well-known favicon is always worth a probe.
    favicon = norm_url(page_url, "/favicon.ico")
    if favicon and not any(c.url == favicon for c in out):
        add("/favicon.ico", "FAVICON", "well-known /favicon.ico")

    for candidate in out:
        if candidate.url in preloaded_header:
            candidate.preloaded_header_logo = True

    return _dedupe(out)


def _dedupe(candidates: list[LadderCandidate]) -> list[LadderCandidate]:
    seen: dict[tuple, LadderCandidate] = {}
    out: list[LadderCandidate] = []
    for candidate in candidates:
        key = (candidate.url, candidate.rung, candidate.theme_signal)
        if key in seen:
            seen[key].occurrences += 1
            continue
        seen[key] = candidate
        out.append(candidate)
    return out


def _extract_marks(zone, rung, role, add) -> None:
    """Pull <img>, <picture>/<source>, srcset and inline <svg> out of a chrome zone.

    Marks are numbered in document order within the zone: the brand mark is
    almost always the first one in a header, and that positional signal is one
    of the few that survives unnamed/hashed asset URLs.
    """
    order = {id(node): i for i, node in enumerate(zone.css("img, svg"))}

    for picture in zone.css("picture"):
        for source in picture.css("source"):
            media = (source.attributes.get("media") or "").lower()
            theme = None
            if "prefers-color-scheme: dark" in media or "prefers-color-scheme:dark" in media:
                theme = "prefers-dark-source"
            elif "prefers-color-scheme: light" in media or "prefers-color-scheme:light" in media:
                theme = "prefers-light-source"
            srcset = source.attributes.get("srcset") or source.attributes.get("src")
            for url in _srcset_urls(srcset):
                add(
                    url,
                    rung,
                    f"{role} <picture><source media='{media[:50]}'>",
                    node=source,
                    theme=theme,
                    link_dest=_link_dest(source),
                )

    for img in zone.css("img"):
        alt = _attr(img, "alt")
        link = _link_dest(img)
        width = _int_or_none(img.attributes.get("width"))
        height = _int_or_none(img.attributes.get("height"))
        src = _attr(img, "src") or _attr(img, "data-src") or _attr(img, "data-lazy-src")
        in_picture = "in-picture" if (img.parent is not None and img.parent.tag == "picture") else ""
        if src:
            add(
                src,
                rung,
                f"{role} <img> {in_picture}".strip(),
                node=img,
                alt=alt,
                link_dest=link,
                width=width,
                height=height,
                dom_index=order.get(id(img)),
            )
        for url in _srcset_urls(
            img.attributes.get("srcset") or img.attributes.get("data-srcset")
        ):
            add(url, rung, f"{role} <img srcset>", node=img, alt=alt, link_dest=link)

    for svg in zone.css("svg"):
        markup = svg.html or ""
        if len(markup) < 60 and svg.css_first("use") is None:
            continue  # empty/sprite-use stub with no drawable content
        title = svg.css_first("title")
        alt = title.text().strip() if title else (
            svg.attributes.get("aria-label") or svg.attributes.get("class")
        )
        add(
            None,
            "INLINE_SVG",
            f"{role} inline <svg>",
            node=svg,
            alt=alt,
            link_dest=_link_dest(svg),
            inline_svg=markup,
            width=_int_or_none(svg.attributes.get("width")),
            height=_int_or_none(svg.attributes.get("height")),
            dom_index=order.get(id(svg)),
        )


def candidate_asset_urls(html_or_tree, page_url: str, stylesheets=None) -> list[str]:
    """Every URL the ladder can consider, for a caller that fetches in bulk.

    This is the fetch-everything invariant expressed as a list: the scorer must
    never rank a candidate whose bytes were never downloaded, because a byteless
    winner is silently dropped downstream.
    """
    seen: list[str] = []
    for candidate in harvest(html_or_tree, page_url, stylesheets):
        if candidate.inline_svg_text is not None:
            continue
        if candidate.url not in seen:
            seen.append(candidate.url)
    return seen


# ---------------------------------------------------------------------------
# bytes
# ---------------------------------------------------------------------------

# SVG is XML and its attribute names are case-sensitive, but a lenient HTML
# parser can lowercase them, turning `viewBox` into `viewbox` — which every
# strict renderer rejects. The file then downloads "successfully" and is
# silently unusable; Anthropic's and Linear's real logomarks were saved this way
# in the pilot. selectolax/lexbor implements the HTML5 SVG attribute-adjustment
# table and does NOT corrupt these (pinned by a round-trip test), but this
# repair also runs on markup that reaches us from elsewhere — a browser's
# outerHTML, a fixture, a hand-written snippet.
_SVG_CAMEL = (
    "viewBox", "preserveAspectRatio", "baseProfile", "clipPath", "clipPathUnits",
    "linearGradient", "radialGradient", "gradientUnits", "gradientTransform",
    "spreadMethod", "patternUnits", "patternContentUnits", "patternTransform",
    "maskUnits", "maskContentUnits", "markerWidth", "markerHeight", "markerUnits",
    "refX", "refY", "startOffset", "textLength", "lengthAdjust", "pathLength",
    "stdDeviation", "filterUnits", "primitiveUnits", "feGaussianBlur", "feOffset",
    "feBlend", "feColorMatrix", "feComposite", "feFlood", "feMerge", "feMergeNode",
    "feDropShadow", "foreignObject", "attributeName", "repeatCount",
    "keyTimes", "keySplines", "calcMode", "systemLanguage", "requiredFeatures",
    "stopColor", "stopOpacity",
)
_SVG_CAMEL_MAP = {name.lower(): name for name in _SVG_CAMEL}


_INVALID_ATTRIBUTE = re.compile(r"""\s+[^\s<>=/]*["'][^\s<>=/]*=(?:"[^"]*"|'[^']*')""")


def _drop_invalid_attributes(markup: str) -> str:
    """Remove attributes whose NAME contains a quote, inside tags only.

    A stray quote in a site's own markup (betterment.com's header <svg>, 2026-10-14) is
    parsed into an attribute literally named `"` and serialized back as `"=""`. Browsers
    forgive it inline; every strict SVG/XML parser rejects the saved file.
    """
    return re.sub(r"<[^<>]*>", lambda tag: _INVALID_ATTRIBUTE.sub("", tag.group(0)), markup)


def repair_svg_case(markup: str) -> str:
    """Restore camelCase SVG names and give the file usable intrinsic size."""
    markup = _drop_invalid_attributes(markup)

    def fix_attr(match):
        name = match.group(1)
        return _SVG_CAMEL_MAP.get(name.lower(), name) + "="

    markup = re.sub(r"\b([a-zA-Z:][\w:.-]*)=", fix_attr, markup)

    def fix_tag(match):
        return match.group(1) + _SVG_CAMEL_MAP.get(match.group(2).lower(), match.group(2))

    markup = re.sub(r"(</?)([a-zA-Z][\w-]*)", fix_tag, markup)

    # Inject width/height INDEPENDENTLY when the viewBox is the only size info.
    # Anthropic's mark carries height but no width, and adding both produced a
    # duplicate-attribute ParseError — a different flavour of the same silently
    # broken file.
    open_tag = markup.split(">", 1)[0]
    viewbox = re.search(r'viewBox\s*=\s*["\']([\d.\-\s]+)["\']', markup)
    if viewbox:
        nums = viewbox.group(1).split()
        if len(nums) == 4:
            inject = ""
            if not re.search(r"\bwidth\s*=", open_tag):
                inject += f' width="{nums[2]}"'
            if not re.search(r"\bheight\s*=", open_tag):
                inject += f' height="{nums[3]}"'
            if inject:
                markup = markup.replace("<svg", "<svg" + inject, 1)
    if "xmlns" not in markup:
        markup = markup.replace("<svg", '<svg xmlns="http://www.w3.org/2000/svg"', 1)
    return markup


def guess_fmt(url: str, content_type: str | None, blob: bytes | None) -> str | None:
    ct = (content_type or "").lower()
    for key, fmt in (
        ("svg", "svg"), ("png", "png"), ("webp", "webp"), ("jpeg", "jpeg"),
        ("jpg", "jpeg"), ("x-icon", "ico"), ("vnd.microsoft.icon", "ico"),
        ("gif", "gif"), ("avif", "avif"),
    ):
        if key in ct:
            return fmt
    if blob:
        if blob[:4] == b"\x89PNG":
            return "png"
        if blob[:3] == b"\xff\xd8\xff":
            return "jpeg"
        if blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
            return "webp"
        if blob[:4] == b"\x00\x00\x01\x00":
            return "ico"
        if blob[:6] in (b"GIF87a", b"GIF89a"):
            return "gif"
        if b"<svg" in blob[:400]:
            return "svg"
    path = urlsplit(url).path.lower()
    for ext, fmt in (
        (".svg", "svg"), (".png", "png"), (".webp", "webp"), (".jpeg", "jpeg"),
        (".jpg", "jpeg"), (".ico", "ico"), (".gif", "gif"), (".avif", "avif"),
    ):
        if path.endswith(ext):
            return fmt
    return None


_MIME_BY_FMT = {
    "svg": "image/svg+xml", "png": "image/png", "jpeg": "image/jpeg",
    "webp": "image/webp", "gif": "image/gif", "ico": "image/x-icon",
    "avif": "image/avif",
}


def attach_bytes(candidates: list[LadderCandidate], fetched: dict) -> list[LadderCandidate]:
    """Bind bytes to candidates and derive fmt/sha/dimensions.

    `fetched` maps url -> bytes, or url -> (bytes, content_type), or
    url -> an object with `.body`/`.content_type`. A url the caller could not
    fetch maps to a string, which is recorded as `fetch_error` — the candidate
    stays in the list. Silence is the failure mode this exists to prevent.
    """
    for candidate in candidates:
        if candidate.inline_svg_text is not None:
            blob = repair_svg_case(candidate.inline_svg_text).encode("utf-8")
            candidate.fmt = "svg"
        else:
            entry = fetched.get(candidate.url)
            body, content_type = _unpack_fetched(entry)
            if body is None:
                candidate.fetch_error = (
                    entry if isinstance(entry, str) else "not fetched"
                )
                continue
            blob = body
            candidate.content_type = content_type
            # A CDN that picks the format from `Accept` (Cloudflare `f=auto`) serves AVIF, which
            # neither our appearance analysis nor the engine can read. Decode it to PNG here, once,
            # so every later step — ink, real dimensions, the asset id, placement — sees PNG.
            # Lazy: `lumen_ingestion.capture` imports this module and must stay PIL-free.
            from lumen_api.image_containers import PNG_MIME, ImageContainerError, convert_to_png

            try:
                decoded = convert_to_png(blob)
            except ImageContainerError as error:
                candidate.fetch_error = f"image could not be decoded: {error}"
                continue
            if decoded is not None:
                candidate.notes.append(
                    f"decoded {decoded.source_container.upper()} to PNG (source sha256:{decoded.source_sha256})"
                )
                blob, content_type = decoded.data, PNG_MIME
                candidate.content_type = content_type
            candidate.fmt = guess_fmt(candidate.url, content_type, blob)
        candidate.body = blob
        candidate.sha256 = hashlib.sha256(blob).hexdigest()
        candidate.byte_len = len(blob)
        candidate.content_type = candidate.content_type or _MIME_BY_FMT.get(candidate.fmt or "")
        _measure(candidate, blob)
    return candidates


def _unpack_fetched(entry):
    if entry is None or isinstance(entry, str):
        return None, None
    if isinstance(entry, (bytes, bytearray)):
        return bytes(entry), None
    if isinstance(entry, tuple):
        body = entry[0] if entry else None
        return (bytes(body) if body else None), (entry[1] if len(entry) > 1 else None)
    body = getattr(entry, "body", None)
    return (bytes(body) if body else None), getattr(entry, "content_type", None)


#: A drawable SVG element — something that can PAINT. `<use>` is deliberately absent: an
#: internal `<use href="#x">` always sits beside the `<defs>` element it references (which this
#: pattern matches), while an EXTERNAL sprite reference has nothing local to draw.
_SVG_DRAWABLE = re.compile(
    r"<\s*(path|rect|circle|ellipse|line|polyline|polygon|text|image)\b", re.I
)
_SVG_INTRINSIC = re.compile(r"<svg[^>]*\s(viewBox|width|height)\s*=", re.I)


def svg_is_renderable(blob: bytes) -> bool:
    """Can this SVG paint anything standalone? Intrinsic geometry AND a drawable element.

    The CP2 walk's live counterexample (F4 wave item 2): a 124-byte sprite-REFERENCE svg —
    `<use>` against an external sheet, no viewBox, no width/height, no artwork — was accepted
    by the ladder, reported ``bound: true``, and rendered 0×0 on every derived page. Shared
    here (beside :func:`_measure`, the ladder's own geometry reader) so the ladder and the
    account-bind door cannot disagree about what "a renderable mark" means.
    """
    text = blob.decode("utf-8", "replace")
    if "<svg" not in text.lower():
        return False
    return bool(_SVG_INTRINSIC.search(text)) and bool(_SVG_DRAWABLE.search(text))


def _measure(candidate: LadderCandidate, blob: bytes) -> None:
    if candidate.fmt in ("png", "jpeg", "webp", "gif", "ico"):
        try:
            import io

            from PIL import Image  # lazy: `lumen_ingestion.capture` must import PIL-free

            image = Image.open(io.BytesIO(blob))
            candidate.width, candidate.height = image.size
        except Exception as error:  # noqa: BLE001
            candidate.notes.append(f"pillow decode failed: {type(error).__name__}")
    elif candidate.fmt == "svg":
        text = blob.decode("utf-8", "replace")
        viewbox = re.search(r'viewBox\s*=\s*["\']([\d.\-\s]+)["\']', text)
        if viewbox:
            nums = [float(x) for x in viewbox.group(1).split() if _is_number(x)]
            if len(nums) == 4:
                candidate.width = candidate.width or int(nums[2])
                candidate.height = candidate.height or int(nums[3])
        width = re.search(r'<svg[^>]*\swidth\s*=\s*["\'](\d+)', text)
        height = re.search(r'<svg[^>]*\sheight\s*=\s*["\'](\d+)', text)
        if width:
            candidate.width = int(width.group(1))
        if height:
            candidate.height = int(height.group(1))


def _is_number(text: str) -> bool:
    try:
        float(text)
        return True
    except ValueError:
        return False


def merge_rendered_observations(
    candidates: list[LadderCandidate], rendered: dict, page_url: str
) -> dict:
    """Fold a rendered computed-style pass into the candidates.

    Optional. Without it, background context is mostly unresolvable and the
    variant ladder falls back to inspecting the asset's own bytes — which cannot
    see CSS. The expected shape is the pilot's:
    `{"surfaces": {footer,header,nav,body}, "zones": {header, header_scrolled,
    footer}, "scroll_swaps": [...], "ink_observations": {...}}`.
    """
    surfaces = rendered.get("surfaces") or {}
    zones = rendered.get("zones") or {}

    asset_bg = {
        mark["src"]: mark["bg"]
        for marks in zones.values()
        for mark in marks
        if mark.get("src") and mark.get("bg")
    }
    # header/nav cross-fallback: workspan.com resolves no <header> surface but a
    # dark navy <nav> one. Without this its header marks inherit the light body
    # colour and the dark-header signal is lost.
    header = surfaces.get("header") or surfaces.get("nav")
    zone_default = {
        "FOOTER": surfaces.get("footer"),
        "HEADER": header,
        "NAV_VISIBLE": surfaces.get("nav") or surfaces.get("header"),
        "INLINE_SVG": header,
    }

    swap_keys = set()
    for swap in rendered.get("scroll_swaps") or []:
        swap_keys.add((swap.get("visible_at_top") or {}).get("key"))
        swap_keys.add((swap.get("visible_after_scroll") or {}).get("key"))

    by_key = {}
    for state, key in (("scroll_top", "header"), ("scrolled", "header_scrolled"),
                       ("footer", "footer")):
        for mark in zones.get(key, []):
            by_key.setdefault(mark.get("key"), (state, mark))

    filled = 0
    for candidate in candidates:
        background = asset_bg.get(candidate.url)
        if background:
            candidate.background_context = background
            candidate.background_source = "rendered:computed-behind-asset"
            filled += 1
        else:
            zone_bg = zone_default.get(candidate.rung) or surfaces.get("body")
            if zone_bg:
                candidate.background_context = zone_bg
                candidate.background_source = f"rendered:computed-{candidate.rung.lower()}-surface"
                filled += 1
        entry = by_key.get(candidate.url)
        if entry:
            state, mark = entry
            candidate.visibility_state = mark.get("visibility_state")
            candidate.scroll_state = state
            candidate.render_key = mark.get("key")
            candidate.observed_ink = mark.get("ink")
            candidate.rendered_w = mark.get("w")
            candidate.rendered_h = mark.get("h")
            candidate.scroll_swap_partner = mark.get("key") in swap_keys

    return {"backgrounds_filled": filled, "surfaces": surfaces}


# ---------------------------------------------------------------------------
# stage 2 — haystacks and tokens
# ---------------------------------------------------------------------------

RUNG_SCORE = {
    "NAV_VISIBLE": 100, "HEADER": 100,
    "INLINE_SVG": 98,        # inline svg is only harvested from chrome zones
    "BRAND_PAGE": 88,
    "PAGE_LOGO_NAMED": 84,   # low base rung; "logo" in its own name earns the lift
    "JSONLD_ORG": 78, "FOOTER": 68, "CSS_BG": 60, "MANIFEST_ICON": 50,
    "APPLE_TOUCH": 48, "OG_LOGO": 46, "OG_IMAGE": 36, "FAVICON": 24,
}
AUTO_ACCEPT_RUNGS = {
    "NAV_VISIBLE", "HEADER", "INLINE_SVG", "FOOTER", "BRAND_PAGE",
    "JSONLD_ORG", "PAGE_LOGO_NAMED",
}
MARK_RUNGS = {"MANIFEST_ICON", "APPLE_TOUCH"}

# Rungs where the SITE ITSELF declares "this is my identity" in machine-readable
# markup: a <link rel=icon>, a web-app manifest, schema.org `Organization.logo`,
# `og:logo`, the brand/press page, a file the page names as its logo. A partner
# or integration glyph embedded in the body copy can never be any of these, so
# arriving through one of these rungs is positive identity evidence on its own.
DECLARED_IDENTITY_RUNGS = {
    "FAVICON", "APPLE_TOUCH", "MANIFEST_ICON", "JSONLD_ORG", "OG_LOGO",
    "BRAND_PAGE", "PAGE_LOGO_NAMED",
}

JUNK_TOKENS = (
    "app-store", "appstore", "app_store", "google-play", "googleplay", "play-store",
    "facebook", "twitter", "x-logo", "linkedin", "instagram", "youtube", "tiktok",
    "pinterest", "github-mark", "social", "badge", "award", "rating", "review",
    "partner", "client-logo", "customer", "sponsor", "press-logo", "as-seen",
    "pixel", "tracking", "spacer", "1x1", "beacon", "avatar", "headshot",
    "hipaa", "bbb", "trustpilot", "g2-", "capterra", "sitejabber",
    "arrow", "chevron", "close", "menu", "hamburger", "search-icon", "caret",
    "search", "burger", "toggle", "dropdown", "expand", "collapse",
    "play-button", "phone-icon", "mail-icon", "email-icon", "location-icon",
    "quote", "star-icon", "check-icon", "plus-icon", "minus-icon", "x-icon",
    "btn", "button", "cta", "banner", "hero", "thumbnail", "thumb", "cover",
    "screenshot", "og-image", "share", "social-card", "twitter-card",
)
STRONG_JUNK = (
    "app-store", "google-play", "facebook", "linkedin", "instagram", "youtube",
    "tiktok", "twitter", "pinterest", "search", "hamburger", "x-icon", "menu",
    "toggle",
)
LOGO_TOKENS = ("logo", "wordmark", "brand", "lockup", "identity")
MARK_TOKENS = ("mark", "symbol", "glyph", "monogram", "isotype", "bug", "logomark")
DARK_NAME_TOKENS = (
    "dark", "white", "inverse", "inverted", "reverse", "reversed", "on-dark",
    "night", "knockout", "light-text",
)
LIGHT_NAME_TOKENS = ("light", "black", "on-light", "day", "dark-text")
SYMBOL_NAME_TOKENS = (
    "mark", "logomark", "icon", "symbol", "glyph", "monogram", "isotype", "bug",
    "favicon", "webclip", "avatar",
)
LOCKUP_NAME_TOKENS = (
    "wordmark", "horizontal", "lockup", "full", "primary", "logotype", "stacked",
)
LOCKUP_RANK = {"full_lockup": 3, "wordmark": 2, "symbol": 1, "unknown": 0}

# Size sanity for the light/dark counterpart slots (D8, apollo.io 2026-08-26).
# A 19x19 OpenAI partner glyph won apollo's `reversed` slot over their real
# 303x303 asterisk, because placement (background luminance) short-circuited
# every other check. These two floors are what "is this even a primary logo?"
# means in pixels, and they are deliberately evaluated BEFORE the placement rule.
#   * MIN_PX mirrors the mark slot's own long-standing `width >= 24` floor
#     ("tiny sprites are UI chrome, not a brand mark") — icon-sized art is not a
#     PRIMARY variant, whatever surface it happens to be painted on.
#   * MAX_SHRINK is directional on purpose. A genuine alternate lockup is
#     usually BIGGER than the primary (workspan.com's footer lockup is 203x32
#     against a 46x26 header symbol), so growth is unbounded; it is dramatic
#     SHRINKAGE that means "sprite / favicon / someone else's glyph".
COUNTERPART_MIN_PX = 24
COUNTERPART_MAX_SHRINK = 3.0
PARTNER_LINK_HINTS = (
    "use-case", "use-cases", "partner", "partners", "partnership", "partnerships",
    "integration", "integrations", "customer", "customers", "case-study",
    "case-studies", "marketplace", "ecosystem", "clients",
)

# An inline <svg> has no file of its own, so it is given a synthetic URL built
# from the PAGE it was found on. That URL contains the company domain, which
# made a close-button icon look "brand-named" and win the mark slot. Synthetic
# URLs therefore contribute ZERO name evidence.
_SYNTHETIC_URL_RE = re.compile(
    r"#(inline-svg|rendered-|scheme-dark-svg|dark-band-svg|rendered-footer-svg|"
    r"rendered-scroll_top|rendered-scrolled)"
)


def _has_token(hay: str, token: str) -> bool:
    """Whole-token match against the hyphen-normalized haystack.

    Boundary-anchored on purpose: plain substring matching makes "search" fire
    on "research" and "mark" fire on "marketing".
    """
    return f"-{token}-" in hay


def _normalize_hay(*parts) -> str:
    raw = " ".join(str(p or "") for p in parts).lower()
    return "-" + re.sub(r"[^a-z0-9]+", "-", raw).strip("-") + "-"


def _hay(candidate: LadderCandidate) -> str:
    """Everything we know, normalized. Used for theme naming, not identity."""
    return _normalize_hay(
        candidate.url, candidate.alt_text, candidate.dom_role,
        candidate.link_destination, candidate.appearance.get("svg_title"),
    )


def _asset_hay(candidate: LadderCandidate) -> str:
    """Haystack of the ASSET's own name only — never the page origin.

    This is guard #1. Only the path basename, alt text and <svg><title> are real
    evidence about the asset itself.
    """
    parts = urlsplit(candidate.url or "")
    basename = parts.path.rsplit("/", 1)[-1] if parts.path else ""
    if _SYNTHETIC_URL_RE.search(candidate.url or ""):
        basename = ""
    return _normalize_hay(basename, candidate.alt_text, candidate.appearance.get("svg_title"))


def company_tokens(domain: str, company_name: str | None = None) -> set[str]:
    label = _domain_label(domain) or domain
    tokens = {label.lower()}
    for piece in re.split(r"[-_.]", label.lower()):
        if len(piece) >= 3:
            tokens.add(piece)
    if company_name:
        for word in re.split(r"[^a-z0-9]+", company_name.lower()):
            if len(word) >= 3 and word not in ("inc", "llc", "ltd", "corp", "the", "company", "co"):
                tokens.add(word)
    return tokens


def _brand_named(candidate: LadderCandidate, tokens: set[str]) -> list[str]:
    """Asset-level name evidence: the company's name inside the asset's own name."""
    squashed = _asset_hay(candidate).replace("-", "")
    return [t for t in tokens if len(t) >= 4 and t in squashed]


def _name_overlap(text: str | None, tokens: set[str]) -> list[str]:
    if not text:
        return []
    low = text.lower()
    hits = [t for t in tokens if len(t) >= 3 and t in low]
    # A two-character name ("Q2", "HP", "3M") is a real company name, but as a substring it
    # would match inside any word, so it counts only as a whole word (q2.com, 2026-10-14:
    # every token under 3 characters was ignored and the company's own site failed identity).
    hits += [
        t
        for t in tokens
        if len(t) == 2 and re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", low)
    ]
    # Compound-domain check: `goodmancampbell` matched by "Goodman Campbell".
    squashed = re.sub(r"[^a-z0-9]", "", low)
    for token in tokens:
        if len(token) >= 6 and token in squashed and token not in hits:
            hits.append(token)
    return hits


def verify_identity(
    candidates: list[LadderCandidate], page_meta: dict, domain: str, company_name: str | None
) -> dict:
    tokens = company_tokens(domain, company_name)
    evidence: list[dict] = []
    passed = False

    title = page_meta.get("page_title")
    hits = _name_overlap(title, tokens)
    if hits:
        passed = True
        evidence.append({"source": "page_title", "value": title, "matched": hits})

    for name in page_meta.get("jsonld_org_names") or []:
        hits = _name_overlap(name, tokens)
        if hits:
            passed = True
            evidence.append({"source": "jsonld_org_name", "value": name, "matched": hits})

    for candidate in candidates:
        hits = _name_overlap(candidate.alt_text, tokens)
        if hits:
            passed = True
            evidence.append({
                "source": "alt_text", "value": candidate.alt_text,
                "url": candidate.url, "matched": hits,
            })
            break

    return {
        "passed": passed,
        "company_tokens": sorted(tokens),
        "evidence": evidence,
        "reason": None if passed
        else "no company-name overlap found in alt text, JSON-LD org name, or page title",
    }


def _links_home(link_destination: str | None, domain: str) -> bool:
    """Does this mark wrap a link to THIS site's own root?

    The naive `urlsplit(href).path in ("", "/")` is true for
    `https://academy.claude.com/` too, which floated every external link-out
    arrow on anthropic.com to the top of the ladder. The host must be ours (or
    absent, i.e. a relative href).
    """
    if link_destination is None:
        return False
    text = str(link_destination).strip()
    if text.startswith("#") or text.lower().startswith(("javascript:", "mailto:", "tel:")):
        return False
    parts = urlsplit(text)
    if parts.path not in ("", "/"):
        return False
    if not parts.netloc:
        return True
    return registrable_domain(parts.netloc) == registrable_domain(domain)


def _first_party(candidate: LadderCandidate, domain: str, page_hosts: set) -> tuple[bool, str]:
    source = candidate.source_domain or ""
    if not source:
        return False, "no source host"
    if registrable_domain(source) == registrable_domain(domain):
        return True, "same registrable domain"
    if source in page_hosts:
        return True, "asset host referenced from the first-party page (CDN)"
    label = _domain_label(domain)
    if label and label in source:
        return True, "asset host contains the company name (CDN)"
    return False, f"third-party host {source}"


def identity_anchor(
    candidate: LadderCandidate, tokens: set, domain: str
) -> list[str]:
    """POSITIVE, asset-level evidence that this mark is THIS BRAND'S identity.

    The apollo.io defect (2026-08-26) was not really "the reversed slot used
    background luminance". It was that a third party's logo was a candidate for
    a brand slot AT ALL. Website ingestion harvests every image in the page's
    chrome — partner badges, integration glyphs, press logos, "powered by" marks
    — and the ladder then classified from that raw pool with no notion of whose
    mark each one is. Luminance is merely where it surfaced: an OpenAI glyph
    happened to sit on a black panel, so it became apollo's reversed logo.

    Scoring already knew this (an inline <svg> with no brand evidence takes -55),
    but a penalty is not a veto: the INLINE_SVG rung is worth 98, so the glyph
    still scored 43 and stayed viable. `slot_eligible` learned this same lesson
    from the AWS/WorkSpan incident and states it outright — "down-scoring it is
    not enough … the rule has to make it INELIGIBLE, not cheap". This function
    is that rule, applied to identity rather than to junk.

    Returns the reasons the asset is ours; empty means no evidence, which makes
    it ineligible for EVERY logo slot. It stays a harvested image, never a mark.
    """
    why: list[str] = []
    named = _brand_named(candidate, tokens)
    if named:
        why.append(f"asset name/alt/title carries the company name {named}")
    if candidate.rung in DECLARED_IDENTITY_RUNGS:
        why.append(f"declared by the site as its own identity ({candidate.rung})")
    if _links_home(candidate.link_destination, domain):
        why.append("wrapped in a link to the site root")
    if candidate.scroll_swap_partner:
        why.append("participates in a collapse-on-scroll logo swap")
    if any(_has_token(_asset_hay(candidate), t) for t in LOGO_TOKENS):
        why.append("asset names itself logo/brand/wordmark")
    return why


def anchor_identity(candidates: list[LadderCandidate], tokens: set, domain: str) -> None:
    """Stamp `identity_anchored` across the pool, then propagate by artwork.

    Two passes, because identity is transitive through the artwork itself: a
    header logo that IS anchored proves that every other copy of the SAME vector
    geometry (the footer recolour, the rendered-DOM duplicate) is also ours,
    even where that copy carries no name and no link of its own.
    """
    for candidate in candidates:
        candidate.identity_anchor = identity_anchor(candidate, tokens, domain)
        candidate.identity_anchored = bool(candidate.identity_anchor)

    anchored_shapes = {
        c.shape_key for c in candidates if c.identity_anchored and c.shape_key
    }
    for candidate in candidates:
        if candidate.identity_anchored or not candidate.shape_key:
            continue
        if candidate.shape_key in anchored_shapes:
            candidate.identity_anchored = True
            candidate.identity_anchor = [
                "same vector artwork as an identity-anchored mark on this site"
            ]


def _partner_context(candidate: LadderCandidate) -> str | None:
    """Is this a PARTNER/customer logo rather than the site's own brand?

    B2B mega-menus are full of other companies' logos served from the site's own
    CDN, so host checks pass cleanly. The tell is the link: a partner logo links
    to `/use-case/aws-partnership`, never to `/`.
    """
    destination = str(candidate.link_destination or "")
    if not destination:
        return None
    path = urlsplit(destination).path.lower()
    for hint in PARTNER_LINK_HINTS:
        if f"/{hint}/" in path or path.endswith(f"/{hint}"):
            return hint
    return None


# ---------------------------------------------------------------------------
# appearance / lockup
# ---------------------------------------------------------------------------


def analyze_appearance(candidate: LadderCandidate) -> dict:
    """Verdict in light_variant / dark_variant / adaptive / unknown."""
    out: dict = {"kind": candidate.fmt, "verdict": "unknown", "detail": None}
    blob = candidate.body
    if not blob:
        return out

    if candidate.fmt == "svg":
        text = blob.decode("utf-8", "replace").lower()
        title = re.search(r"<title[^>]*>(.*?)</title>", text, re.S)
        if title:
            out["svg_title"] = re.sub(r"\s+", " ", title.group(1)).strip()[:80]
        fills = re.findall(r'(?:fill|stroke)\s*[:=]\s*["\']?([#a-z0-9(),.\s%-]+)', text)
        fills = [f.strip().strip("\"'").split(";")[0].strip() for f in fills]
        fills = [f for f in fills if f and f != "none"]
        if not fills:
            out["detail"] = "no explicit fill/stroke (inherits currentColor by default)"
            out["verdict"] = "adaptive"
            return out
        if any("currentcolor" in f for f in fills):
            out["detail"] = f"currentColor present among {len(fills)} fills"
            out["verdict"] = "adaptive"
            return out
        lights = [x for x in (color_lightness(f) for f in fills) if x is not None]
        out["detail"] = {
            "fills": fills[:12], "lightnesses": [round(x, 3) for x in lights[:12]],
        }
        if not lights:
            return out
        mean = sum(lights) / len(lights)
        out["mean_lightness"] = round(mean, 3)
        if mean >= 0.82:
            out["verdict"] = "dark_variant"    # white mark -> made for dark backgrounds
        elif mean <= 0.45:
            out["verdict"] = "light_variant"   # dark mark -> made for light backgrounds
        return out

    if candidate.fmt in ("png", "jpeg", "webp", "gif", "ico"):
        try:
            import io

            from PIL import Image  # lazy: capture must import PIL-free

            image = Image.open(io.BytesIO(blob)).convert("RGBA")
            image.thumbnail((160, 160))
            pixels = list(image.getdata())
            opaque = [p for p in pixels if p[3] > 24]
            if not opaque:
                out["detail"] = "fully transparent"
                return out
            lights = [(0.299 * p[0] + 0.587 * p[1] + 0.114 * p[2]) / 255.0 for p in opaque]
            mean = sum(lights) / len(lights)
            opaque_fraction = len(opaque) / max(1, len(pixels))
            out["mean_lightness"] = round(mean, 3)
            out["opaque_fraction"] = round(opaque_fraction, 3)
            out["detail"] = f"{len(opaque)} opaque px of {len(pixels)}"

            # Real logos are flat artwork with very few distinct colours; award
            # badges, team photos and hero images are not. Quantize hard so
            # antialiasing does not inflate the count.
            quantized = {(p[0] // 32, p[1] // 32, p[2] // 32) for p in opaque}
            out["unique_colors"] = len(quantized)
            out["photographic"] = len(quantized) > 40 and opaque_fraction > 0.9
            if out["photographic"]:
                out["detail"] += " | photographic: not a logo variant"
                return out

            if mean >= 0.80:
                out["verdict"] = "dark_variant"
            elif mean <= 0.45:
                out["verdict"] = "light_variant"
            # A fully-opaque flat image is a logo on a solid plate. The mean then
            # describes the plate, not the ink, so the reading inverts.
            if opaque_fraction > 0.97:
                out["detail"] += " | fully opaque: lightness describes the plate, not the ink"
                out["verdict"] = "light_variant" if mean >= 0.6 else "dark_variant"
            return out
        except Exception as error:  # noqa: BLE001
            out["detail"] = f"decode failed: {type(error).__name__}"
            return out
    return out


def _rasterize(candidate: LadderCandidate, max_w: int = 420):
    """Render any candidate to RGBA pixels so lockup shape is measured the same
    way for SVG and raster. Returns None when it cannot be rendered."""
    blob = candidate.body
    if not blob:
        return None
    try:
        import io

        from PIL import Image  # lazy: capture must import PIL-free

        if candidate.fmt == "svg":
            import pymupdf  # lazy: capture must import fitz/pymupdf-free

            document = pymupdf.open(stream=blob, filetype="svg")
            page = document[0]
            zoom = max_w / max(1.0, page.rect.width)
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=True)
            image = Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("RGBA")
        else:
            image = Image.open(io.BytesIO(blob)).convert("RGBA")
            if image.width > max_w:
                image.thumbnail((max_w, max_w * 4))
        return image if image.width > 4 and image.height > 4 else None
    except Exception:  # noqa: BLE001 - an unrenderable asset degrades, never fails
        return None


def _ink_columns(image) -> list[bool]:
    """Columns containing 'ink'. For transparent art ink is alpha; for a fully
    opaque plate it is any pixel far from the plate colour."""
    pixels = image.load()
    width, height = image.size
    step_y = max(1, height // 40)
    step_x = max(1, width // 40)
    sampled = len(range(0, height, step_y)) * len(range(0, width, step_x))
    alphas = sum(
        1
        for y in range(0, height, step_y)
        for x in range(0, width, step_x)
        if pixels[x, y][3] > 32
    )
    opaque_fraction = alphas / max(1, sampled)

    plate = None
    if opaque_fraction > 0.95:
        corners = [pixels[0, 0], pixels[width - 1, 0], pixels[0, height - 1],
                   pixels[width - 1, height - 1]]
        counts: dict = {}
        for corner in corners:
            counts[corner[:3]] = counts.get(corner[:3], 0) + 1
        plate = max(counts, key=counts.get)

    columns = []
    for x in range(width):
        found = False
        for y in range(height):
            pixel = pixels[x, y]
            if plate is None:
                if pixel[3] > 32:
                    found = True
                    break
            elif pixel[3] > 32 and (
                abs(pixel[0] - plate[0]) + abs(pixel[1] - plate[1]) + abs(pixel[2] - plate[2])
            ) > 90:
                found = True
                break
        columns.append(found)
    return columns


def _row_extent(image, x0: int, x1: int) -> int:
    """Vertical extent of ink within a column band — used to size the symbol."""
    pixels = image.load()
    width, height = image.size
    top = bottom = None
    for y in range(height):
        for x in range(max(0, x0), min(width, x1 + 1)):
            if pixels[x, y][3] > 32:
                if top is None:
                    top = y
                bottom = y
                break
    if top is None:
        return 0
    return bottom - top + 1


def analyze_lockup(candidate: LadderCandidate) -> tuple[str, dict]:
    """symbol | wordmark | full_lockup | unknown, with the evidence behind it.

    The distinguishing feature of a full lockup is not "wide" — a wordmark is
    wide too. It is a SINGLE unusually large horizontal gap early in the artwork
    separating a roughly square symbol from the text that follows. Letter gaps
    inside a wordmark are small and fairly uniform; the symbol-to-text gap is
    several times larger.
    """
    evidence: dict = {"method": None}
    asset_hay = _asset_hay(candidate)
    name_symbol = [t for t in SYMBOL_NAME_TOKENS if _has_token(asset_hay, t)]
    name_lockup = [t for t in LOCKUP_NAME_TOKENS if _has_token(asset_hay, t)]
    evidence["name_symbol_hints"] = name_symbol
    evidence["name_lockup_hints"] = name_lockup

    has_text_element = False
    if candidate.fmt == "svg" and candidate.body:
        text = candidate.body.decode("utf-8", "replace")
        has_text_element = bool(re.search(r"<text[\s>]", text, re.I))
        evidence["svg_path_count"] = len(re.findall(r"<path[\s>]", text, re.I))
    evidence["svg_has_text_element"] = has_text_element

    width, height = candidate.width, candidate.height
    declared_aspect = (width / height) if (width and height) else None
    evidence["declared_aspect"] = round(declared_aspect, 3) if declared_aspect else None

    image = _rasterize(candidate)
    if image is None:
        evidence["method"] = "declared-aspect-only (could not rasterize)"
        evidence["aspect"] = round(declared_aspect, 3) if declared_aspect else None
        if name_symbol and not name_lockup:
            return "symbol", evidence
        if declared_aspect is None:
            return "unknown", evidence
        return ("symbol" if declared_aspect < 1.5 else "wordmark"), evidence

    columns = _ink_columns(image)
    indices = [i for i, on in enumerate(columns) if on]
    if not indices:
        evidence["method"] = "raster ink analysis (no ink found)"
        return "unknown", evidence
    x0, x1 = indices[0], indices[-1]
    ink_w = x1 - x0 + 1
    ink_h = _row_extent(image, x0, x1) or image.height
    aspect = ink_w / max(1, ink_h)

    clusters, run = [], None
    for i in range(x0, x1 + 1):
        if columns[i]:
            run = [i, i] if run is None else [run[0], i]
        elif run is not None:
            clusters.append(run)
            run = None
    if run is not None:
        clusters.append(run)
    gaps = [clusters[i + 1][0] - clusters[i][1] - 1 for i in range(len(clusters) - 1)]

    evidence.update({
        "method": "raster ink analysis",
        "ink_box": [ink_w, ink_h], "ink_aspect": round(aspect, 3),
        "clusters": len(clusters), "gaps": gaps[:12],
    })

    # The BROWSER'S layout box beats the rasterizer when they disagree.
    # Anthropic's 143x16 full wordmark rasterized to an ink aspect of 1.40 (no
    # rasterizer resolves every mask/clip/<use>) and was classified a "symbol",
    # putting the full wordmark in the mark slot.
    effective = aspect
    if declared_aspect and aspect:
        disagreement = max(declared_aspect, aspect) / max(1e-6, min(declared_aspect, aspect))
        if disagreement > 2.0:
            effective = declared_aspect
            evidence["aspect_disagreement"] = round(disagreement, 2)
            evidence["effective_aspect_source"] = "browser/declared box (rasterizer disagreed)"
    evidence["effective_aspect"] = round(effective, 3)

    if effective < 1.5 and not name_lockup:
        evidence["reason"] = f"near-square (effective aspect {effective:.2f})"
        return "symbol", evidence

    verdict = "wordmark"
    evidence["reason"] = f"wide (effective aspect {effective:.2f}) with no dominant early gap"

    if gaps:
        biggest = max(gaps)
        index = gaps.index(biggest)
        others = [g for j, g in enumerate(gaps) if j != index] or [0]
        median_other = sorted(others)[len(others) // 2]
        split_x = clusters[index][1]
        left_w = split_x - x0 + 1
        left_fraction = left_w / ink_w
        left_h = _row_extent(image, x0, split_x)
        left_aspect = left_w / max(1, left_h)
        evidence.update({
            "biggest_gap": biggest, "median_other_gap": median_other,
            "left_fraction": round(left_fraction, 3), "left_aspect": round(left_aspect, 3),
        })
        if (
            biggest >= max(3, 2.5 * max(1, median_other))
            and left_fraction <= 0.5
            and 0.45 <= left_aspect <= 1.9
            and biggest >= 0.03 * ink_w
            and effective >= 1.8
        ):
            verdict = "full_lockup"
            evidence["reason"] = (
                f"one dominant gap ({biggest}px vs median {median_other}px) after a "
                f"near-square left cluster occupying {left_fraction:.0%} of the width — "
                "symbol followed by text"
            )

    if has_text_element and verdict == "symbol":
        verdict = "wordmark"
        evidence["reason"] = "contains an SVG <text> element"

    # Names are a tie-breaker, never an override of clear pixel evidence.
    if name_symbol and not name_lockup and verdict == "wordmark" and effective < 2.2:
        verdict = "symbol"
        evidence["reason"] = f"filename says symbol {name_symbol} and shape is not clearly a wordmark"

    return verdict, evidence


WORDMARK_MAX_ASPECT = 16.0


def _reads_as_lettering(candidate: LadderCandidate) -> bool:
    """Measured ink with at least three glyph clusters and no gap over 3x the median."""
    evidence = candidate.lockup_evidence or {}
    gaps = [g for g in evidence.get("gaps") or [] if isinstance(g, (int, float))]
    if (evidence.get("clusters") or 0) < 3 or len(gaps) < 2:
        return False
    median = sorted(gaps)[len(gaps) // 2]
    return median > 0 and max(gaps) <= 3 * median


def junk_assessment(candidate: LadderCandidate) -> tuple[float, list[str]]:
    # Match on the ASSET's own name/alt, never the DOM-role label. `_hay`
    # includes dom_role, and ARIA landmarks are labelled "div[role=banner]" —
    # which made the "banner" junk token fire on insighthealth.ai's real header
    # logo and disqualify it.
    hay = _asset_hay(candidate)
    hits = [t for t in JUNK_TOKENS if _has_token(hay, t)]
    penalty = sum(60 if hit in STRONG_JUNK else 25 for hit in hits)

    width, height = candidate.width, candidate.height
    if width and height and (width < 16 or height < 16):
        penalty += 70
        hits.append(f"tiny {width}x{height}")
    if candidate.byte_len is not None and candidate.byte_len < 120:
        penalty += 50
        hits.append(f"tiny payload {candidate.byte_len}B")

    if candidate.appearance.get("photographic"):
        penalty += 120
        hits.append(
            f"photographic ({candidate.appearance.get('unique_colors')} unique colors)"
            " - a logo is flat art"
        )

    # Measure the INK, not the box. linear.app's real lockup ships in a 400x22
    # SVG whose artwork is only ~88px wide; the padded box reads as aspect 18 and
    # the true artwork as ~4, so a box measurement disqualified the correct logo.
    ink_aspect = candidate.lockup_evidence.get("ink_aspect")
    aspect = ink_aspect or ((width / height) if (width and height) else None)
    # Widely tracked wordmarks run past 8:1 (proxon.ai's measures 11.66 and lost every slot
    # to its social-share card, 2026-10-14). The wider ceiling is for INK that reads as
    # lettering only — several glyph clusters with even gaps — never a bar, rule or a strip
    # of separate logos, which all keep the 8:1 limit.
    ceiling = WORDMARK_MAX_ASPECT if ink_aspect and _reads_as_lettering(candidate) else 8.0
    if aspect is not None and (aspect < 0.35 or aspect > ceiling):
        penalty += 60
        hits.append(
            f"implausible logo aspect {aspect:.2f}"
            + (" (ink-measured)" if ink_aspect else " (box-measured)")
        )

    if candidate.fetch_error:
        penalty += 1000
        hits.append("fetch_error")
    return penalty, hits


def classify_variant(candidate: LadderCandidate) -> tuple[str, str, int]:
    """-> (variant, basis, basis_rank); variant in light/dark/adaptive/unknown."""
    hay = _hay(candidate)
    appearance = candidate.appearance

    # 1. explicit theme signals from harvest
    if candidate.theme_signal == "prefers-dark-source":
        return "dark", "explicit prefers-color-scheme:dark <source>", 1
    if candidate.theme_signal == "prefers-light-source":
        return "light", "explicit prefers-color-scheme:light <source>", 1

    # 1b. filename/alt naming is an explicit authored signal too
    # A name is ambiguous — "logo-dark" can mean dark ink as easily as dark mode — so it yields
    # when the measured pixels clearly say the opposite (Atrium Hospitality: an asset named "dark"
    # whose ink measures L=0.30, i.e. made for light backgrounds).
    pixel_variant = {"light_variant": "light", "dark_variant": "dark"}.get(
        appearance.get("verdict")
    )
    dark_hits = [t for t in DARK_NAME_TOKENS if _has_token(hay, t)]
    light_hits = [t for t in LIGHT_NAME_TOKENS if _has_token(hay, t)]
    if dark_hits and not light_hits and pixel_variant != "light":
        return "dark", f"filename/alt names a dark/inverse asset: {dark_hits}", 2
    if light_hits and not dark_hits and pixel_variant != "dark":
        return "light", f"filename/alt names a light asset: {light_hits}", 2

    # 1c. Theme-adaptive assets are decided by INSPECTING THE ASSET, and that
    # beats placement. A `currentColor` SVG serves both themes; the fact that
    # linear.app paints it on a near-black page says what that PAGE's theme is,
    # not that the asset is a dark-only variant. Letting placement win here made
    # linear.app report "dark-only" and drop its light slot entirely.
    if appearance.get("verdict") == "adaptive":
        return "adaptive", (
            f"theme-adaptive asset ({appearance.get('detail')}) - serves both themes; "
            "placement describes the page, not the asset"
        ), 2

    # 2. background context — PLACEMENT evidence, i.e. the footer-as-oracle rule:
    # a mark sitting on a light footer is the light-mode asset, one on a dark
    # footer is the dark-mode asset.
    background = candidate.background_context
    source = candidate.background_source or "static"
    lightness = color_lightness(background)
    if lightness is not None:
        where = (candidate.rung or "").lower()
        if lightness <= 0.35:
            return "dark", (
                f"painted on a dark {where} surface ({background}, L={lightness:.2f}) via {source}"
            ), 3
        if lightness >= 0.75:
            return "light", (
                f"painted on a light {where} surface ({background}, L={lightness:.2f}) via {source}"
            ), 3

    # 3. pixel / svg appearance — cannot see CSS, so it goes last
    verdict = appearance.get("verdict")
    if verdict == "light_variant":
        return "light", f"appearance: dark ink (mean L={appearance.get('mean_lightness')})", 4
    if verdict == "dark_variant":
        return "dark", f"appearance: light/white ink (mean L={appearance.get('mean_lightness')})", 4
    return "unknown", "no usable theme evidence", 9


def is_mark(
    candidate: LadderCandidate, primary_aspect: float | None, name_tokens: set
) -> tuple[bool, str | None]:
    """Symbol-only mark detection.

    Squareness alone is NOT enough — that is how a 24x24 hamburger icon in the
    header won this slot on the first run. A mark must be square-ish AND carry
    brand evidence: a mark-ish filename, a dedicated icon rung, or the company
    name in its own path/alt.
    """
    width, height = candidate.width, candidate.height
    aspect = (width / height) if (width and height) else None
    if aspect is None or not (0.75 <= aspect <= 1.33):
        return False, None

    asset_hay = _asset_hay(candidate)
    name_hint = [t for t in MARK_TOKENS if _has_token(asset_hay, t)]
    if name_hint:
        return True, f"square + filename hints a symbol mark: {name_hint}"
    if candidate.rung in MARK_RUNGS:
        return True, f"square + dedicated icon rung {candidate.rung}"
    brand_named = _brand_named(candidate, name_tokens)
    if brand_named and primary_aspect is not None and primary_aspect > 1.6:
        return True, (
            f"square (aspect {aspect:.2f}) + brand-named {brand_named} while the primary "
            f"is wide ({primary_aspect:.2f})"
        )
    return False, "square but carries no brand evidence - not treated as a mark"


def score_candidate(
    candidate: LadderCandidate, domain: str, page_hosts: set
) -> tuple[float, list[str], bool, str]:
    base = RUNG_SCORE.get(candidate.rung, 10)
    signals = [f"rung {candidate.rung} = {base}"]
    score = float(base)

    fmt = candidate.fmt
    if fmt == "svg":
        score += 18
        signals.append("svg +18")
    elif fmt in ("png", "webp"):
        width, height = candidate.width or 0, candidate.height or 0
        bonus = min(14, max(0, (max(width, height) - 32) / 40.0))
        score += bonus
        signals.append(f"raster {width}x{height} +{bonus:.1f}")
    elif fmt == "ico":
        score -= 6
        signals.append("ico -6")
    elif fmt in ("jpeg", "gif"):
        score -= 2
        signals.append(f"{fmt} -2")

    asset_hay = _asset_hay(candidate)
    names_logo = any(_has_token(asset_hay, t) for t in LOGO_TOKENS)
    if names_logo:
        score += 10
        signals.append("asset names itself logo/brand/wordmark +10")

    links_home = _links_home(candidate.link_destination, domain)
    if links_home:
        score += 20
        signals.append("wrapped in a link to THIS site's root +20")

    link_host = urlsplit(str(candidate.link_destination or "")).netloc.lower()
    if link_host:
        for bad in ("apps.apple.com", "itunes.apple.com", "play.google.com",
                    "chromewebstore.google.com", "chrome.google.com", "facebook.com",
                    "twitter.com", "x.com", "linkedin.com", "instagram.com",
                    "youtube.com", "tiktok.com"):
            if link_host.endswith(bad):
                score -= 90
                signals.append(f"links to {bad} - store badge / social icon -90")
                break

    label = _domain_label(domain)
    brand_in_name = bool(label) and label in asset_hay.replace("-", "")
    if candidate.rung == "INLINE_SVG" and not (names_logo or brand_in_name or links_home):
        score -= 55
        signals.append("inline <svg> with no brand evidence (no logo/brand name, no link home) -55")

    # The brand mark is almost always the FIRST thing in the header.
    if candidate.dom_index is not None and candidate.rung in ("NAV_VISIBLE", "HEADER", "INLINE_SVG"):
        if candidate.dom_index == 0:
            score += 14
            signals.append("first mark in its header/nav zone +14")
        elif candidate.dom_index == 1:
            score += 6
            signals.append("second mark in its header/nav zone +6")

    partner = _partner_context(candidate)
    if partner:
        score -= 80
        signals.append(f"links into /{partner}/ - partner/customer logo, not our brand -80")

    width, height = candidate.width, candidate.height
    # A large raster is a hero or a screenshot unless its own name says logo, or it both links to
    # this site's root and carries the brand in its name. That pair is what a header logo served
    # at full resolution looks like (Atrium Hospitality: a 3000x1562 header image, linked home,
    # named `atrium-hospitality-…`, whose size only became visible once its AVIF was decoded).
    brand_logo_evidence = links_home and brand_in_name
    if width and height and width > 800 and height > 800 and not (names_logo or brand_logo_evidence):
        score -= 90
        signals.append(f"{width}x{height} in both dims and not logo-named - hero/screenshot -90")

    if candidate.occurrences > 1:
        bonus = min(6, candidate.occurrences * 2)
        score += bonus
        signals.append(f"appears {candidate.occurrences}x +{bonus}")

    ok, reason = _first_party(candidate, domain, page_hosts)
    if not ok:
        score -= 200
        signals.append(f"NOT first-party ({reason}) -200")
    else:
        signals.append(f"first-party: {reason}")

    penalty, hits = junk_assessment(candidate)
    candidate.junk_hits = hits
    if penalty:
        score -= penalty
        signals.append(f"junk penalty -{penalty} {hits}")

    return score, signals, ok, reason


def _counterpart_plausible(
    candidate: LadderCandidate, primary: LadderCandidate, name_tokens: set
) -> tuple[bool, str]:
    """A genuine dark/light counterpart is the SAME artwork recoloured.

    Aspect ratio and opacity profile are only weak proxies for that. On
    workspan.com the ladder correctly ranked WorkSpan's own symbol first and
    correctly called it the white/dark-mode variant — then adopted the AWS logo
    out of the nav mega-menu as its "light counterpart" purely because the aspect
    ratio was close and the filename said "black". The counterpart search needs
    its own identity constraint; the page-level check cannot help, because it
    only proves the PAGE is WorkSpan's, not the ASSET.

    The checks are ordered by how much they PROVE, strongest first:

      1. identical vector path geometry — the only positive PROOF here, and the
         thing every check below is merely a proxy for;
      2. brand-name mismatch, then partner-link context — whose asset is it;
      3. size sanity — is it even primary-sized;
      4. placement (the footer-as-oracle rule);
      5. aspect ratio and opacity profile, the weakest proxies.

    Size sits ABOVE placement because of apollo.io: background luminance alone
    promoted a 19x19 OpenAI glyph to apollo's reversed primary logo, and it
    shipped in an ad. Placement may override shape, never size.
    """
    # The one POSITIVE identity signal the ladder computes, and the only PROOF
    # in this function: identical vector path geometry with a different fill is
    # precisely what a recoloured counterpart IS. It outranks the filename and
    # aspect proxies below, which exist only to approximate it. Its absence
    # proves nothing (a raster copy, or a reserialized SVG, has no shape key),
    # so this can only ever admit.
    if candidate.shape_key and candidate.shape_key == primary.shape_key:
        return True, "identical vector path geometry to the primary - the same artwork recoloured"

    primary_named = _brand_named(primary, name_tokens)
    candidate_named = _brand_named(candidate, name_tokens)
    if primary_named and not candidate_named:
        return False, (
            f"primary's filename names the company {primary_named} but this one does not - "
            "a different company's asset, not a recolored variant"
        )

    partner = _partner_context(candidate)
    if partner:
        return False, f"links into /{partner}/ - a partner or customer logo, not our brand"

    pw, ph = primary.width, primary.height
    cw, ch = candidate.width, candidate.height
    if not (pw and ph and cw and ch):
        return True, "dimensions unknown on one side - not rejected"

    # SIZE SANITY — deliberately ABOVE the placement rule below (D8, apollo.io).
    # Placement earns the right to ignore lockup SHAPE, never the right to hand
    # a primary slot to art that is not primary-sized: apollo's `reversed` slot
    # went to a 19x19 OpenAI partner glyph that happened to sit on a #000000
    # panel, beating their own 303x303 asterisk, because background luminance
    # was the only evidence anyone checked.
    c_max, p_max = max(cw, ch), max(pw, ph)
    if c_max < COUNTERPART_MIN_PX:
        return False, (
            f"{cw}x{ch} is icon-sized (under {COUNTERPART_MIN_PX}px) - UI chrome or a "
            "third-party glyph, not a primary logo variant"
        )
    if c_max * COUNTERPART_MAX_SHRINK < p_max:
        return False, (
            f"{cw}x{ch} is more than {COUNTERPART_MAX_SHRINK:g}x smaller than the primary "
            f"{pw}x{ph} - too small to be the same mark recoloured"
        )

    # Placement evidence OUTRANKS shape similarity. If we watched this mark get
    # painted on a light footer it is the light asset, whether or not it is the
    # same lockup as the header symbol. Vetoing on aspect here is what made
    # workspan.com report "no light variant" while its own footer displayed the
    # full-colour primary lockup.
    if candidate.variant_basis_rank == 3:
        return True, (
            f"placement-classified ({candidate.variant_basis}) - lockup shape "
            f"'{candidate.lockup}' vs primary '{primary.lockup}' not treated as a veto"
        )

    primary_aspect, candidate_aspect = pw / ph, cw / ch
    ratio = max(primary_aspect, candidate_aspect) / max(
        1e-6, min(primary_aspect, candidate_aspect)
    )
    if ratio > 1.6:
        return False, f"aspect {candidate_aspect:.2f} vs primary {primary_aspect:.2f} - not the same artwork"

    def solid_plate(item: LadderCandidate):
        # SVGs are treated as transparent — vector marks with no plate. This
        # matters because when the primary is an SVG (the common case) a None
        # skipped the check entirely, and linear.app's PWA app icon (a black
        # rounded square) got adopted as the "dark variant".
        if item.fmt == "svg":
            return False
        fraction = item.appearance.get("opaque_fraction")
        return None if fraction is None else fraction > 0.97

    primary_solid, candidate_solid = solid_plate(primary), solid_plate(candidate)
    if primary_solid is not None and candidate_solid is not None and primary_solid != candidate_solid:
        return False, (
            "opacity profile differs - one is a transparent mark, the other a solid plate "
            "(app icon / screenshot), not the same artwork recolored"
        )
    return True, f"aspect {candidate_aspect:.2f} matches primary {primary_aspect:.2f}"


# ---------------------------------------------------------------------------
# adaptive materialization (never synthesis)
# ---------------------------------------------------------------------------


def _svg_shape_key(candidate: LadderCandidate) -> str | None:
    """Identity of an SVG's ARTWORK, independent of serialization.

    The same inline <svg> harvested statically and from a rendered DOM produces
    different bytes and different sha256s, so the static copy carries no rendered
    ink observation. Hashing the sorted path geometry links the two.
    """
    if candidate.fmt != "svg" or not candidate.body:
        return None
    text = candidate.body.decode("utf-8", "replace")
    paths = sorted(re.findall(r'\sd\s*=\s*["\']([^"\']{12,})["\']', text))
    if not paths:
        return None
    return hashlib.sha256("|".join(paths).encode()).hexdigest()[:20]


def _link_render_observations(candidates: list[LadderCandidate]) -> int:
    """Propagate render_key / observed ink between copies of the same artwork."""
    by_shape: dict[str, list[LadderCandidate]] = {}
    for candidate in candidates:
        key = _svg_shape_key(candidate)
        candidate.shape_key = key
        if key:
            by_shape.setdefault(key, []).append(candidate)
    linked = 0
    for group in by_shape.values():
        donor = next((c for c in group if c.render_key), None)
        if donor is None:
            continue
        for candidate in group:
            if not candidate.render_key:
                candidate.render_key = donor.render_key
                candidate.observed_ink = candidate.observed_ink or donor.observed_ink
                candidate.rendered_w = candidate.rendered_w or donor.rendered_w
                candidate.rendered_h = candidate.rendered_h or donor.rendered_h
                linked += 1
    return linked


def _observed_inks(candidate: LadderCandidate, page_meta: dict) -> dict:
    """Inks the brand's own CSS painted this asset with, split by surface theme.

    Matched by the browser element key, falling back to rendered size, because a
    statically harvested copy of the same SVG serializes differently and would
    never match by key.
    """
    observations_map = (page_meta.get("render_styles") or {}).get("ink_observations") or {}
    observations = list(observations_map.get(candidate.render_key) or [])
    if not observations and candidate.rendered_w and candidate.rendered_h:
        observations = list(
            observations_map.get(f"size:{candidate.rendered_w}x{candidate.rendered_h}") or []
        )
    if not observations and candidate.width and candidate.height:
        observations = list(
            observations_map.get(f"size:{candidate.width}x{candidate.height}") or []
        )
    if not observations and candidate.observed_ink:
        observations = [{
            "scheme": "light", "state": "as-harvested", "ink": candidate.observed_ink,
            "bg": candidate.background_context,
            "w": candidate.rendered_w, "h": candidate.rendered_h,
        }]

    light_ink = dark_ink = None
    light_evidence = dark_evidence = None
    for observation in observations:
        background_l = color_lightness(observation.get("bg"))
        ink_l = color_lightness(observation.get("ink"))
        if ink_l is None:
            continue
        on_dark = observation.get("scheme") == "dark" or (
            background_l is not None and background_l <= 0.35
        )
        on_light = background_l is not None and background_l >= 0.75
        if on_dark and ink_l >= 0.6 and dark_ink is None:
            dark_ink, dark_evidence = observation["ink"], observation
        elif on_light and ink_l <= 0.5 and light_ink is None:
            light_ink, light_evidence = observation["ink"], observation
    return {
        "light": light_ink, "dark": dark_ink,
        "light_evidence": light_evidence, "dark_evidence": dark_evidence,
        "observation_count": len(observations),
    }


def materialize_adaptive(candidate: LadderCandidate, page_meta: dict) -> dict | None:
    """Export a `currentColor` SVG in the brand's OWN observed inks.

    This is not synthesis: `currentColor` is a deferred reference and the site's
    own stylesheet supplies the exact value at each placement. The restraint that
    keeps it honest is that an ink which was never OBSERVED is never invented —
    anthropic.com's A-mark is adaptive but was never seen being painted, so its
    dark slot stays absent.
    """
    if candidate.fmt != "svg" or not candidate.body:
        return None
    text = candidate.body.decode("utf-8", "replace")
    if "currentcolor" not in text.lower():
        return None

    inks = _observed_inks(candidate, page_meta)
    out: dict = {
        "materialized": {},
        "evidence": {
            "observed_ink_light": inks["light"],
            "observed_ink_dark": inks["dark"],
            "source": "computed-style",
            "observation_count": inks["observation_count"],
            "light_observation": inks["light_evidence"],
            "dark_observation": inks["dark_evidence"],
        },
    }
    for slot, ink in (("light", inks["light"]), ("dark", inks["dark"])):
        if not ink:
            continue
        hex_value = to_hex(ink) or ink
        baked = re.sub(r"currentColor", hex_value, text, flags=re.I)
        evidence = inks[f"{slot}_evidence"] or {}
        out["materialized"][slot] = {
            "body": baked.encode("utf-8"),
            "ink": hex_value,
            "surface": evidence.get("bg"),
        }
    return out if out["materialized"] else None


# ---------------------------------------------------------------------------
# theme surfaces
# ---------------------------------------------------------------------------


def extract_theme_surfaces(page_meta: dict) -> dict:
    """The brand's own light/dark surface colours, read off the rendered page.

    A brand's dark surface is usually its own navy/charcoal, not black —
    insighthealth.ai's footer is #231e40 — so defaulting a dark theme to #000
    throws away a real brand fact that is sitting right there.
    """
    render = page_meta.get("render_styles") or {}
    surfaces = render.get("surfaces") or {}
    out: dict = {
        "light_surface": None, "dark_surface": None, "source": None,
        "footer_inverse": None, "surfaces_seen": surfaces,
        "available": render.get("status") == "ok",
    }
    if render.get("status") != "ok":
        out["reason"] = f"rendered pass {render.get('status')}: {render.get('error')}"
        return out

    def lightness_of(key):
        return color_lightness(surfaces.get(key))

    # footer first (the variant oracle), then header, then body
    for key in ("footer", "header", "nav", "body"):
        value, lightness = to_hex(surfaces.get(key)), lightness_of(key)
        if value is None or lightness is None:
            continue
        if lightness <= 0.35 and out["dark_surface"] is None:
            out["dark_surface"] = value
            out["source"] = out["source"] or key
            out.setdefault("dark_source", key)
        elif lightness >= 0.75 and out["light_surface"] is None:
            out["light_surface"] = value
            out["source"] = out["source"] or key
            out.setdefault("light_source", key)

    # Page reference = header, else nav, else body. workspan.com resolves no
    # <header> surface but a dark navy <nav> one; comparing against body instead
    # reported footer_inverse=False on the very site whose dark-header /
    # light-footer inversion is the whole point.
    footer_l = lightness_of("footer")
    page_l = lightness_of("header") or lightness_of("nav") or lightness_of("body")
    if footer_l is not None and page_l is not None:
        out["footer_inverse"] = abs(footer_l - page_l) >= 0.35
        out["footer_lightness"] = round(footer_l, 3)
        out["page_lightness"] = round(page_l, 3)
    return out


# ---------------------------------------------------------------------------
# stage 2 — resolve
# ---------------------------------------------------------------------------


def resolve(
    candidates: list[LadderCandidate],
    page_meta: dict,
    domain: str,
    company_name: str | None = None,
) -> LadderResolution:
    """Rank, verify and fill the light / dark / mark / wordmark slots."""
    page_hosts = {c.source_domain for c in candidates if c.source_domain}
    page_hosts.add(urlsplit(page_meta.get("homepage_url", "")).netloc.lower())

    # appearance FIRST: scoring reads it (the photographic penalty) and the
    # haystacks read its extracted <svg><title>.
    for candidate in candidates:
        candidate.appearance = analyze_appearance(candidate)
        candidate.lockup, candidate.lockup_evidence = analyze_lockup(candidate)

    _link_render_observations(candidates)

    for candidate in candidates:
        score, signals, ok, reason = score_candidate(candidate, domain, page_hosts)
        candidate.score = round(score, 2)
        candidate.score_signals = signals
        candidate.first_party = ok
        candidate.first_party_reason = reason

    ranked = sorted(candidates, key=lambda c: -c.score)
    identity = verify_identity(ranked, page_meta, domain, company_name)
    name_tokens = company_tokens(domain, company_name)

    adaptive_placements = []
    for candidate in ranked:
        if candidate.appearance.get("verdict") != "adaptive":
            continue
        lightness = color_lightness(candidate.background_context)
        if lightness is None or candidate.score <= 0:
            continue
        adaptive_placements.append({
            "url": candidate.url, "rung": candidate.rung, "sha256": candidate.sha256,
            "surface": candidate.background_context, "surface_lightness": round(lightness, 3),
            "surface_theme": "dark" if lightness <= 0.35 else ("light" if lightness >= 0.75 else "mid"),
        })

    viable = [c for c in ranked if not c.fetch_error and c.score > 0 and c.first_party]
    anchor_identity(ranked, name_tokens, domain)

    def label_all(primary_aspect):
        for candidate in viable:
            candidate.is_mark, candidate.mark_reason = is_mark(
                candidate, primary_aspect, name_tokens
            )
            (candidate.variant, candidate.variant_basis, candidate.variant_basis_rank) = (
                classify_variant(candidate)
            )

    def slot_eligible(candidate) -> bool:
        """What may fill a slot at all, however well it scores.

        Junk is one half. The other is the partner-link rule: a mark linking
        into /partners/, /customers/, /use-case/ is another company's logo
        sitting on our CDN, and down-scoring it is not enough — on a page whose
        only header mark is a partner's, the tier fallbacks happily hand that
        slot to it. That is the AWS-as-WorkSpan failure with the brand-evidenced
        tier simply empty, so the rule has to make it INELIGIBLE, not cheap.

        The third half (apollo.io, 2026-08-26) is IDENTITY: an asset carrying no
        positive evidence of being THIS brand's mark fills no slot, whatever it
        scores and whatever surface it is painted on. See `identity_anchor`.
        """
        return (
            not candidate.junk_hits
            and _partner_context(candidate) is None
            and candidate.identity_anchored
        )

    def brand_evidence(candidate) -> list[str]:
        """Positive, ASSET-level evidence this is OUR mark.

        Preferring the fullest lockup without this gate is how the Palo Alto
        Networks partner logo (1280x235, filename contains "Logo", first-party
        Webflow CDN, classified full_lockup) took workspan.com's primary slot.
        Being wide and on our CDN is not evidence of being ours.
        """
        why = []
        if _brand_named(candidate, name_tokens):
            why.append("asset name/alt contains the company name")
        if _links_home(candidate.link_destination, domain):
            why.append("wrapped in a link to the site root")
        if candidate.scroll_swap_partner:
            why.append("participates in a collapse-on-scroll logo swap")
        if candidate.preloaded_header_logo:
            why.append("the page preloads it under a header/nav logo name")
        return why

    def pick_primary(pool):
        """Fullest lockup among brand-evidenced candidates; fall back by tiers.

        Score still breaks ties, so a marketing banner cannot leapfrog a real
        logo on shape alone — it has to survive identity, junk and partner
        gating first.
        """
        clean = [c for c in pool if slot_eligible(c)]
        tier1 = [c for c in clean if brand_evidence(c)]
        tier2 = [c for c in clean if c.rung in ("HEADER", "NAV_VISIBLE", "INLINE_SVG")]
        # No unfiltered last resort. If nothing eligible survives, the honest
        # answer is an empty slot and a needs_review — handing the slot to the
        # best of a bad pool is exactly the confident wrong answer these guards
        # exist to prevent.
        for tier, label in (
            (tier1, "brand-evidenced"), (tier2, "visible chrome"),
            (clean, "clean fallback"),
        ):
            if tier:
                return max(tier, key=lambda c: (LOCKUP_RANK.get(c.lockup, 0), c.score)), label
        return None, None

    primary = viable[0] if viable else None
    primary_aspect = (
        primary.width / primary.height
        if primary and primary.width and primary.height
        else None
    )
    label_all(primary_aspect)

    non_marks = [c for c in viable if not c.is_mark]
    pool = non_marks or viable
    primary_tier = None
    if pool:
        primary, primary_tier = pick_primary(pool)
        if primary is not None and primary.width and primary.height:
            label_all(primary.width / primary.height)
            non_marks = [c for c in viable if not c.is_mark]
            pool = non_marks or viable
            if pool:
                primary, primary_tier = pick_primary(pool)

    slots: dict[str, LadderSlot | None] = {
        "light": None, "dark": None, "mark": None, "wordmark": None
    }
    chosen: dict[str, LadderCandidate | None] = {
        "light": None, "dark": None, "mark": None, "wordmark": None
    }
    notes: list[str] = []
    alternate_lockups: list[dict] = []
    lockup_completeness = "unknown"

    if primary is not None:
        if primary.variant == "dark":
            chosen["dark"] = primary
        elif primary.variant == "adaptive":
            chosen["light"] = primary
            seen = ", ".join(
                f"{p['surface_theme']} {p['surface']} ({p['rung']})"
                for p in adaptive_placements
                if p["surface_theme"] in ("light", "dark")
            )[:200]
            notes.append(
                "primary mark is theme-adaptive (currentColor / no baked fill): ONE file "
                "serves both themes, so there is no separate dark asset to return. Observed "
                f"painted on: {seen or 'no confident surface'}. Filed under light."
            )
        else:
            chosen["light"] = primary

        # counterpart variant among the remaining non-mark candidates. A theme-adaptive
        # primary IS both variants (the note above says so), so there is no counterpart to
        # look for: searching anyway put a 32x32 navigation icon in q2.com's dark slot on
        # placement evidence alone (2026-10-14).
        want = None if primary.variant == "adaptive" else (
            "light" if chosen["light"] is None else "dark"
        )
        rejected = []
        for candidate in non_marks if want else ():
            if candidate is primary or candidate.variant != want:
                continue
            if candidate.sha256 == primary.sha256:
                continue
            # The counterpart loop used to run over `non_marks` directly, so it
            # was the ONE slot filler that never asked `slot_eligible` — junk
            # tokens, partner links and (since apollo) identity anchoring were
            # all enforced on every other slot and skipped on this one.
            if not slot_eligible(candidate):
                rejected.append(f"{candidate.url[-60:]} (not slot-eligible)")
                continue
            ok, why = _counterpart_plausible(candidate, primary, name_tokens)
            if not ok:
                rejected.append(f"{candidate.url[-60:]} ({why})")
                # A brand-named asset rejected only on aspect is not junk — it is
                # a DIFFERENT LOCKUP of the same brand (workspan.com's primary is
                # the 46x26 symbol, the rejected asset the 203x32 horizontal
                # wordmark). Surface it rather than silently drop it.
                if (
                    "aspect" in (why or "")
                    and _brand_named(candidate, name_tokens)
                    # One entry per artwork: the same file is harvested from
                    # several rungs, and listing it three times reads as three
                    # rival lockups when it is one.
                    and candidate.sha256 not in {a["sha256"] for a in alternate_lockups}
                ):
                    alternate_lockups.append({
                        "url": candidate.url, "rung": candidate.rung, "fmt": candidate.fmt,
                        "width": candidate.width, "height": candidate.height,
                        "variant": candidate.variant, "sha256": candidate.sha256,
                        "why_not_a_variant": why,
                    })
                continue
            chosen[want] = candidate
            candidate.variant_basis = f"{candidate.variant_basis} | counterpart: {why}"
            break
        if rejected:
            notes.append(f"rejected implausible {want} counterparts: {rejected[:3]}")
        if want and chosen[want] is None:
            notes.append(
                f"no genuine {want}-mode asset found; NOT synthesized - reported as "
                f"{'dark' if want == 'light' else 'light'}-only"
            )

        # ---- mark slot: the SYMBOL. Never the same asset as the primary.
        chosen_shas = {c.sha256 for c in chosen.values() if c}
        symbols = [
            c for c in viable
            if c.lockup == "symbol"
            and slot_eligible(c)
            and c.sha256 not in chosen_shas
            and c is not primary
            # the symbol must ALSO be evidenced as ours, or be a dedicated icon
            # rung. Without this the mark slot picked up mngi.com's
            # `MNGI_Scheduling_BTN_SQUARE.jpg` — a call-to-action button.
            and (
                brand_evidence(c)
                or c.rung in MARK_RUNGS
                or [t for t in MARK_TOKENS if _has_token(_asset_hay(c), t)]
            )
            # tiny sprites are UI chrome, not a brand mark
            and ((c.width or 0) >= 24 or c.rung in MARK_RUNGS)
        ]
        if symbols:
            # a scroll-swap partner of the primary is near-proof this is the
            # brand's own symbol, so prefer it; otherwise fall back to score.
            chosen["mark"] = max(
                symbols,
                key=lambda c: (
                    1 if c.scroll_swap_partner else 0,
                    1 if _brand_named(c, name_tokens) else 0,
                    c.score,
                ),
            )
        else:
            # `slot_eligible` binds here too. Without it the fallback re-opened
            # the door the junk rule closed, and mngi.com's
            # `MNGI_Scheduling_BTN_SQUARE.jpg` walked back in through it.
            marks = [
                c for c in viable
                if c.is_mark and slot_eligible(c) and c.sha256 not in chosen_shas
            ]
            if marks:
                chosen["mark"] = marks[0]

        # ---- wordmark slot: a distinct brand-evidenced wordmark, when one
        # exists that is not already filling another slot.
        chosen_shas = {c.sha256 for c in chosen.values() if c}
        wordmarks = [
            c for c in viable
            if c.lockup == "wordmark"
            and slot_eligible(c)
            and c.sha256 not in chosen_shas
            and brand_evidence(c)
            # A reversed asset is the dark variant of something, never "the
            # wordmark". Live on workspan.com the white 46x26 symbol was
            # rejected for the dark slot on lockup (correctly — different
            # artwork) and then landed here, handing back a white symbol under
            # the wrong name. A slot the asset does not belong in is worse than
            # an empty one.
            and c.variant != "dark"
            # Same gate the primary answers to. Live on insighthealth.ai this
            # slot picked `InsightHealth-dont-6-img.avif` off a CSS background —
            # a brand-guidelines DON'T illustration, brand-named and wide, which
            # is every signal this slot reads. Only rungs that mean "the brand
            # published this as its mark" may fill it.
            and c.rung in AUTO_ACCEPT_RUNGS
        ]
        if wordmarks:
            chosen["wordmark"] = max(wordmarks, key=lambda c: c.score)

        completeness = {
            "full_lockup": "full_lockup", "wordmark": "wordmark_only", "symbol": "symbol_only",
        }.get(primary.lockup, "unknown")
        lockup_completeness = completeness
        if completeness == "symbol_only":
            notes.append(
                "primary is SYMBOL-ONLY: no full lockup (symbol + company name) was found "
                "first-party. Reported honestly, not an error."
            )
        elif completeness == "wordmark_only":
            notes.append(
                "primary is a WORDMARK (company name set as type, no separate symbol cluster)."
            )

    # ---- confidence. It measures how much evidence was found, not whether the
    # answer is right; it is a gate input, never a claim of correctness.
    confidence = 0.0
    breakdown: list[str] = []
    if primary is not None:
        confidence = 0.35 if primary.rung in AUTO_ACCEPT_RUNGS else 0.15
        breakdown.append(f"rung {primary.rung} -> {confidence}")
        if identity["passed"]:
            confidence += 0.30
            breakdown.append("identity check passed +0.30")
        if primary.first_party:
            confidence += 0.15
            breakdown.append("first-party provenance +0.15")
        if primary.fmt == "svg":
            confidence += 0.08
            breakdown.append("vector asset +0.08")
        if any(_has_token(_asset_hay(primary), t) for t in LOGO_TOKENS):
            confidence += 0.07
            breakdown.append("asset names itself a logo +0.07")
        runner = next((c for c in viable if c is not primary), None)
        if runner is not None and (primary.score - runner.score) >= 15:
            confidence += 0.05
            breakdown.append("clear margin over runner-up +0.05")
        confidence = round(min(confidence, 0.99), 2)

    status = "resolved"
    if primary is None:
        status = "needs_review"
        # Distinguish "nothing scored" from "nothing was OURS" — the second is
        # the identity-anchoring outcome, and an operator reading "survived
        # scoring" about candidates that scored fine would be misled.
        if viable and not any(c.identity_anchored for c in viable):
            notes.append(
                f"{len(viable)} first-party candidate(s) scored, but none carried any "
                "evidence of being THIS brand's mark (no company name in the asset "
                "name/alt/title, no favicon or other declared-identity rung, no link "
                "to the site root) - every slot left empty rather than guessing"
            )
        else:
            notes.append("no viable first-party candidate survived scoring")
    elif not identity["passed"]:
        status = "needs_review"
        chosen = {k: None for k in chosen}
        notes.append(
            "IDENTITY CHECK FAILED (fail-closed): zero winners emitted, full ranked "
            "candidate list preserved for review"
        )
    elif primary.rung not in AUTO_ACCEPT_RUNGS:
        status = "needs_review"
        notes.append(
            f"winning rung {primary.rung} is not visible chrome or JSON-LD - "
            "auto-accept gate refuses"
        )
    elif alternate_lockups:
        status = "needs_review"
        notes.append(
            "brand-named assets exist in a different lockup than the chosen primary - which "
            "one is 'the logo' is a human call, not a scoring call"
        )

    # ---- materialize the adaptive primary from OBSERVED ink only
    materialization = None
    if primary is not None and chosen.get("light") is primary and primary.variant == "adaptive":
        materialization = materialize_adaptive(primary, page_meta)

    for name, candidate in chosen.items():
        if candidate is None:
            continue
        slots[name] = LadderSlot(
            candidate=candidate,
            provenance="genuine",
            body=candidate.body or b"",
            content_type=candidate.content_type or _MIME_BY_FMT.get(candidate.fmt or "", "image/png"),
            basis=candidate.variant_basis or candidate.mark_reason or candidate.lockup,
        )
    if materialization:
        for name, info in materialization["materialized"].items():
            if slots.get(name) is not None and slots[name].candidate is not primary:
                continue  # a genuine published asset always beats a materialized one
            slots[name] = LadderSlot(
                candidate=primary,
                provenance="materialized-adaptive",
                body=info["body"],
                content_type="image/svg+xml",
                basis=(
                    "materialized from the adaptive asset in the ink the brand's own CSS "
                    f"paints it with on a {name} surface ({info['ink']}, source: computed-style)"
                ),
                ink=info["ink"],
                surface=info.get("surface"),
            )
        notes.append(
            "adaptive primary MATERIALIZED using observed computed inks "
            f"(light={materialization['evidence']['observed_ink_light']}, "
            f"dark={materialization['evidence']['observed_ink_dark']}); the canonical adaptive "
            "SVG is kept as the light slot"
        )

    return LadderResolution(
        status=status,
        confidence=confidence,
        confidence_breakdown=breakdown,
        identity=identity,
        slots=slots,
        lockup_completeness=lockup_completeness,
        theme_surfaces=extract_theme_surfaces(page_meta),
        adaptive_placements=adaptive_placements,
        alternate_lockups=alternate_lockups,
        notes=notes,
        ranked=ranked,
        counts={
            "harvested": len(ranked),
            "fetched_ok": sum(1 for c in ranked if not c.fetch_error),
            "fetch_errors": sum(1 for c in ranked if c.fetch_error),
            "viable_first_party": len(viable),
            "identity_anchored": sum(1 for c in viable if c.identity_anchored),
            "primary_selection_tier": primary_tier,
        },
    )


# ---------------------------------------------------------------------------
# the one network driver
# ---------------------------------------------------------------------------

# Static tier only, deliberately. This runs inside an agent turn, and a
# Playwright launch costs ~30s of the turn budget. A JS-shell page therefore
# yields no chrome candidates and is reported honestly rather than rendered.
_JS_SHELL_NOTE = (
    "the page served no logo candidates in any visible-chrome rung, which usually means "
    "a JavaScript shell; this static-tier pass does not render pages"
)


async def fetch_logo_family(
    url_or_domain: str,
    *,
    company_name: str | None = None,
    client=None,
    concurrency: int = 4,
    with_brand_pages: bool = True,
) -> LadderResolution:
    """Fetch a site and resolve its logo family. The one impure entry point.

    Every request goes through the shared SSRF/redirect/size guard in
    `capture.net`, which re-guards redirect hops and caps a logo at 15 MB.

    When it owns its client, `LUMEN_LADDER_IMPERSONATE_CHROME` (default on) decides the
    transport: a real Chrome TLS fingerprint that Cloudflare-walled sites answer, or plain
    httpx. A caller-supplied `client` is used as given.
    """
    # Deferred import: `capture.candidates` imports this module, so a module-scope import of
    # `capture.net` would be a cycle — importing `capture.net` runs the `capture` package
    # `__init__`, which imports `.static` → `.candidates` → back here.
    #
    # The `from .capture.cssurl import iter_css_urls` at the top of this module runs that
    # same `__init__` and is nonetheless safe, for two reasons that are worth stating because
    # they are not obvious: `cssurl` is a LEAF (it imports only `re` and `typing`, nothing
    # intra-package), and `candidates` touches `logo_ladder` only at CALL time, so the
    # partially-initialized module it binds during the cycle is fully built long before
    # anything reads an attribute off it. Verified in all three entry orders
    # (logo_ladder-first, capture-first, candidates-first).
    #
    # The fragility: that safety is a property of `cssurl` staying a leaf. If it ever grows
    # an intra-package import, the candidates-first order breaks — `capture.net` is only the
    # more obvious version of the same hazard.
    import httpx

    from .capture.budget import short_url
    from .capture.net import (
        REQUEST_TIMEOUT_SECONDS,
        BoundedFetcher,
        CaptureError,
        FetchRequest,
    )

    page_url = normalize_site_url(url_or_domain)
    domain = host_of(page_url)

    async def run(http_client) -> LadderResolution:
        fetcher = BoundedFetcher(http_client, concurrency=concurrency)
        page = await fetcher.fetch_page(page_url)
        status = page.status or 0
        if status < 200 or status >= 300 or page.body is None:
            raise CaptureError(
                "LUMI0503", f"page fetch failed for {page_url}: HTTP {status or 'unknown'}"
            )
        final_url = page.final_url or page_url
        html = page.body.decode("utf-8", errors="replace")
        tree = HTMLParser(html)

        stylesheets: list[tuple[str, str]] = []
        sheet_urls = []
        for link in tree.css("link[rel~='stylesheet'][href]"):
            sheet_url = norm_url(final_url, link.attributes.get("href"))
            if sheet_url and sheet_url not in sheet_urls:
                sheet_urls.append(sheet_url)
        if sheet_urls:
            for result in await fetcher.fetch_many(
                [FetchRequest(url=u, kind="css") for u in sheet_urls[:12]]
            ):
                if result.ok and result.body:
                    stylesheets.append(
                        (result.url, result.body.decode("utf-8", errors="replace"))
                    )

        candidates = harvest(tree, final_url, stylesheets)
        optional_page_notes: list[str] = []

        if with_brand_pages:
            for brand_url in discover_brand_pages(tree, final_url, host_of(final_url))[:2]:
                try:
                    result = await fetcher.fetch_page(brand_url)
                except (CaptureError, httpx.RequestError) as error:
                    # Optional discovery must not discard the successful page's candidates.
                    # Keep security/size refusals fatal; only ordinary fetch failures degrade.
                    if isinstance(error, CaptureError) and error.code != "LUMI0503":
                        raise
                    code = error.code if isinstance(error, CaptureError) else type(error).__name__
                    optional_page_notes.append(
                        f"optional brand page skipped ({code}): {short_url(brand_url)}"
                    )
                    continue
                if not result.ok or result.body is None:
                    continue
                candidates.extend(
                    harvest(
                        result.body.decode("utf-8", errors="replace"),
                        result.final_url or brand_url,
                        None,
                        force_rung="BRAND_PAGE",
                        start_index=len(candidates),
                    )
                )
            candidates = _dedupe(candidates)

        asset_urls = [c.url for c in candidates if c.inline_svg_text is None]
        fetched: dict = {}
        if asset_urls:
            for result in await fetcher.fetch_many(
                [FetchRequest(url=u, kind="logo") for u in asset_urls]
            ):
                fetched[result.url] = (
                    result if result.ok and result.body else _fetch_error_text(result)
                )
        attach_bytes(candidates, fetched)

        # Which transport actually fetched this page — diagnostic only; `resolve` reads
        # page_meta by key and ignores anything it does not know.
        from .capture.impersonate import ImpersonatingClient

        page_meta = {
            "homepage_url": final_url,
            "page_title": page_title(tree),
            "jsonld_org_names": jsonld_org_names(tree),
            "tier": "static",
            "transport": (
                "chrome-impersonated"
                if isinstance(http_client, ImpersonatingClient)
                else "httpx"
            ),
        }
        resolution = resolve(candidates, page_meta, host_of(final_url), company_name)
        resolution.notes.extend(optional_page_notes)
        if not any(c.rung in ("HEADER", "NAV_VISIBLE", "INLINE_SVG", "FOOTER") for c in candidates):
            resolution.notes.append(_JS_SHELL_NOTE)
        return resolution

    if client is not None:
        return await run(client)
    if _impersonate_chrome():
        from .capture.impersonate import ImpersonatingClient

        async with ImpersonatingClient(timeout=REQUEST_TIMEOUT_SECONDS) as owned:
            return await run(owned)
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as owned:
        return await run(owned)


def _impersonate_chrome() -> bool:
    """Read the transport flag at call time, so a flip is honoured without a restart."""
    from py_lumen_config import settings

    return bool(settings.lumen_ladder_impersonate_chrome)


def _fetch_error_text(result) -> str:
    for diagnostic in result.diagnostics or []:
        message = diagnostic.get("message")
        if message:
            return str(message)
    return f"fetch failed (HTTP {result.status or 'unknown'})"


def normalize_site_url(url_or_domain: str) -> str:
    """`goodmancampbell.com`, `www.x.com/a`, `https://x.com` → a https page URL."""
    raw = (url_or_domain or "").strip()
    if not raw:
        raise ValueError("a domain or URL is required")
    if not re.match(r"^https?://", raw, re.I):
        raw = "https://" + raw.lstrip("/")
    parts = urlsplit(raw)
    if not parts.netloc:
        raise ValueError(f"could not read a host out of {url_or_domain!r}")
    return urlunsplit(("https", parts.netloc, parts.path or "/", "", ""))
