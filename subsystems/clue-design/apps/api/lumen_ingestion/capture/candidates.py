"""The ONE enumeration of everything a captured page references (clone-fidelity F0.2).

Why this module exists
----------------------
The historical defect this closes has a shape: **one component scored a URL a different
component never downloaded.** The logo scorer ranked JSON-LD / ``og:logo``-declared URLs the
fetcher had never heard of, so the top candidate arrived byteless and
``evidence_builder.queue()`` dropped it without a word — the recurring ``bytes_missing``. The
D8 logo-ladder wave closed that for the LOGO rungs specifically (``static._collect_assets``
began calling ``logo_ladder.candidate_asset_urls``), but the rest of the page's references
were still enumerated ad hoc, inline, in the collector — and three whole classes were not
enumerated at all: inline-SVG external refs, CSS ``url()`` outside ``background``, and the
``srcset`` rungs the image ladder does not pick.

So there is now exactly one list. :func:`collect_asset_candidates` walks the DOM and every
fetched stylesheet once and returns every fetchable reference, each tagged with where it came
from. ``static._collect_assets`` fetches precisely that list; nothing else may build its own.

Coverage, and the origin tag each reference carries:
  ``logo-rung``    every URL the logo ladder can score (nav/header/footer marks, JSON-LD
                   ``Organization.logo``, ``og:logo``, ``og:image``, apple-touch-icon,
                   favicon, chrome CSS backgrounds)
  ``font``         every ``@font-face`` ``src`` URL, found by the same walk ``parse`` uses
  ``img``          an ``<img>``'s own ``src``
  ``srcset``       every ``srcset`` rung — the ``<img>``'s and every ``<picture><source>``'s —
                   plus any CDN width-upgraded rendition the shared ladder derived
  ``picture-dark`` a ``<picture><source media="(prefers-color-scheme: dark)">`` rung; the tag
                   rides on ``dark_scheme`` too, and survives into the snapshot and evidence
  ``css-url``      every ``url()`` in an asset-bearing declaration (background, mask,
                   border-image, list-style-image, content, cursor) from inline ``style``
                   attributes and EVERY fetched stylesheet. ``@font-face`` ``src`` is
                   deliberately excluded — the font path owns it and double-counting it would
                   make one file two candidates
  ``svg-ref``      an inline ``<svg>``'s external references (``<use href>``, ``<image href>``,
                   and their ``xlink:`` forms); the fragment is stripped, because the fragment
                   selects INSIDE the file and is not part of what we fetch

Ordering is identity-first — logos, then fonts, then imagery, then CSS references, then SVG
references — because the count budget drops the TAIL. If a page is ever big enough to trip the
budget, the thing we keep is the brand's identity.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urldefrag, urljoin

from .. import logo_ladder
from .budget import MAX_ASSET_COUNT, budget_diagnostic
from .imgsrc import image_source_ladder, parse_srcset
from .parse import font_face_sources

#: Origin tags, in the order the collector emits them. Task 3 and the F2 clone harvest read
#: these off the candidate, so they are part of this module's contract, not decoration.
ORIGINS = ("logo-rung", "font", "img", "srcset", "picture-dark", "css-url", "svg-ref")

#: ``net.ResourceKind`` for each origin — what byte cap the fetcher applies.
_KIND_BY_ORIGIN = {
    "logo-rung": "logo",
    "font": "font",
    "img": "image",
    "srcset": "image",
    "picture-dark": "image",
    "css-url": "image",
    "svg-ref": "image",
}

#: CSS declarations that can carry a fetchable ``url()``. ``src`` is NOT here on purpose
#: (``@font-face`` owns it). Longest names first so ``mask-image`` wins over ``mask``.
_CSS_ASSET_DECL_RE = re.compile(
    r"(-webkit-mask-image|-webkit-mask|border-image-source|border-image|list-style-image"
    r"|background-image|background|mask-image|mask|content|cursor)\s*:\s*([^;{}]*)",
    re.IGNORECASE,
)
_CSS_URL_RE = re.compile(r"url\(\s*(?:'([^']*)'|\"([^\"]*)\"|([^)'\"\s]+))\s*\)")

_DARK_MEDIA_RE = re.compile(r"prefers-color-scheme\s*:\s*dark", re.IGNORECASE)


@dataclass(frozen=True)
class AssetCandidate:
    """One fetchable reference, with the story of where the page referenced it.

    ``origin`` is one of :data:`ORIGINS`; ``kind`` is the ``net.ResourceKind`` the fetcher
    applies caps by; ``dark_scheme`` is true only when EVERY reference to this URL came from a
    ``prefers-color-scheme: dark`` source (a URL used on both schemes is not a dark asset).
    ``detail`` is free-text provenance for a human reading a diagnostic.
    """

    url: str
    origin: str
    kind: str
    dark_scheme: bool = False
    detail: str = ""


@dataclass
class CandidateHarvest:
    """The collector's output: the deduped candidate list plus any budget diagnostics."""

    candidates: list[AssetCandidate] = field(default_factory=list)
    diagnostics: list[dict] = field(default_factory=list)

    @property
    def urls(self) -> list[str]:
        return [candidate.url for candidate in self.candidates]


def collect_asset_candidates(tree, base_url: str, stylesheets) -> CandidateHarvest:
    """Every fetchable reference on one captured page, deduped, in identity-first order.

    ``stylesheets`` are the sheets already fetched for this page (anything with ``.url`` and
    ``.text``), so a CSS ``url()`` resolves against ITS OWN sheet rather than the page — an
    ``/img/x.png`` in a sheet served from a CDN is a CDN URL, not a page-relative one.
    """
    raw: list[AssetCandidate] = []

    def add(url: str | None, origin: str, *, dark: bool = False, detail: str = "") -> None:
        if not url:
            return
        url = url.strip()
        if not url or url.startswith(("data:", "about:", "blob:", "javascript:")):
            return
        raw.append(
            AssetCandidate(
                url=url,
                origin=origin,
                kind=_KIND_BY_ORIGIN[origin],
                dark_scheme=dark,
                detail=detail,
            )
        )

    sheet_pairs = [
        (getattr(sheet, "url", "") or "", getattr(sheet, "text", "") or "")
        for sheet in stylesheets
    ]

    # 1 — everything the logo machinery can score. Whatever the ladder ranks, we hold bytes
    #     for; that IS the invariant this module exists to keep.
    for url in logo_ladder.candidate_asset_urls(tree, base_url, sheet_pairs):
        add(url, "logo-rung", detail="logo ladder rung")

    # 2 — every @font-face file, resolved by the same walk `parse` uses. Capture and parse
    #     must agree on the URL to the character: the evidence builder matches a face to its
    #     bytes by exact URL string.
    for url in font_face_sources(stylesheets, base_url):
        add(url, "font", detail="@font-face src")

    # 3 — imagery: the shared ladder's picks first (best rendition), then EVERY remaining
    #     srcset rung, so nothing a page offered is left unfetched.
    for node in tree.css("img"):
        _add_image_references(node, base_url, add)

    # 4 — CSS url() from inline style attributes and every fetched sheet.
    for node in tree.css("[style]"):
        for url, prop in _css_urls(node.attributes.get("style") or "", base_url):
            add(url, "css-url", detail=f"inline style {prop}")
    for sheet_url, text in sheet_pairs:
        base = base_url if (not sheet_url or sheet_url.startswith("inline:")) else sheet_url
        for url, prop in _css_urls(text, base):
            add(url, "css-url", detail=f"{prop} in {sheet_url or 'inline'}")

    # 5 — inline-SVG external references.
    for url, detail in _svg_reference_urls(tree, base_url):
        add(url, "svg-ref", detail=detail)

    return _budgeted(_dedupe(raw))


# --------------------------------------------------------------------------- #
# imagery
# --------------------------------------------------------------------------- #


def _add_image_references(node, base_url: str, add) -> None:
    """One ``<img>``'s full reference set — the ladder's picks, then every other rung.

    The ladder (``imgsrc.image_source_ladder``) is the SHARED chooser ``parse._parse_images``
    walks, so its rungs must be fetched or every image loses its bytes. Everything it did not
    pick is fetched too: an F2 clone rewrites a fragment's ``srcset`` wholesale, so a rung we
    skipped is a broken rendition on a published page.
    """
    raw_src = (node.attributes.get("src") or "").strip()
    src = urljoin(base_url, raw_src) if raw_src and not raw_src.startswith("data:") else None

    # Which URLs came from a dark <picture><source>, and which from any srcset at all.
    dark: set[str] = set()
    from_srcset: set[str] = set()
    ordered_rungs: list[tuple[str, bool]] = []
    parent = getattr(node, "parent", None)
    if parent is not None and (parent.tag or "").lower() == "picture":
        for source in parent.css("source"):
            is_dark = bool(_DARK_MEDIA_RE.search(source.attributes.get("media") or ""))
            for url, _descriptor, _kind in parse_srcset(source.attributes.get("srcset")):
                if not url or url.startswith("data:"):
                    continue
                absolute = urljoin(base_url, url)
                from_srcset.add(absolute)
                if is_dark:
                    dark.add(absolute)
                ordered_rungs.append((absolute, is_dark))
            source_src = (source.attributes.get("src") or "").strip()
            if source_src and not source_src.startswith("data:"):
                absolute = urljoin(base_url, source_src)
                from_srcset.add(absolute)
                if is_dark:
                    dark.add(absolute)
                ordered_rungs.append((absolute, is_dark))
    for url, _descriptor, _kind in parse_srcset(node.attributes.get("srcset")):
        if not url or url.startswith("data:"):
            continue
        absolute = urljoin(base_url, url)
        from_srcset.add(absolute)
        ordered_rungs.append((absolute, False))

    def origin_for(url: str) -> tuple[str, bool]:
        if url in dark:
            return "picture-dark", True
        if url == src:
            return "img", False
        if url in from_srcset:
            return "srcset", False
        return "srcset", False  # a CDN width-upgraded rendition the ladder derived

    for url in image_source_ladder(node, base_url):
        if url.startswith("data:"):
            continue
        origin, is_dark = origin_for(url)
        detail = "img src" if origin == "img" else "srcset rung"
        if url not in from_srcset and url != src:
            detail = "cdn width-upgraded rendition"
        add(url, origin, dark=is_dark, detail=detail)

    for url, is_dark in ordered_rungs:
        origin, resolved_dark = origin_for(url)
        add(url, origin, dark=resolved_dark, detail="srcset rung")

    if src:
        add(src, "img", detail="img src")


# --------------------------------------------------------------------------- #
# CSS
# --------------------------------------------------------------------------- #


def _css_urls(css_text: str, base: str) -> list[tuple[str, str]]:
    """``(absolutized url, property name)`` for every asset-bearing ``url()`` in some CSS."""
    if "url(" not in css_text.lower():
        return []
    found: list[tuple[str, str]] = []
    for declaration in _CSS_ASSET_DECL_RE.finditer(css_text):
        prop = declaration.group(1).lower()
        for match in _CSS_URL_RE.finditer(declaration.group(2)):
            raw = (match.group(1) or match.group(2) or match.group(3) or "").strip()
            if not raw or raw.startswith("data:") or raw.startswith("#"):
                continue
            found.append((urljoin(base, raw), prop))
    return found


# --------------------------------------------------------------------------- #
# inline SVG
# --------------------------------------------------------------------------- #


def _svg_reference_urls(tree, base_url: str) -> list[tuple[str, str]]:
    """External refs out of inline ``<svg>``: ``<use>`` sprites and ``<image>`` bitmaps.

    A fragment-only ref (``#gradient-a``) points inside the same document and is not
    fetchable; a ref WITH a fragment (``/sprite.svg#mark``) is fetched without it, because the
    fragment selects a symbol inside the file we are downloading.
    """
    out: list[tuple[str, str]] = []
    for svg in tree.css("svg"):
        for node in svg.css("use, image"):
            for attribute in ("href", "xlink:href"):
                raw = (node.attributes.get(attribute) or "").strip()
                if not raw or raw.startswith("#") or raw.startswith("data:"):
                    continue
                url, _fragment = urldefrag(urljoin(base_url, raw))
                if url:
                    out.append((url, f"inline svg <{node.tag}> {attribute}"))
                break
    return out


# --------------------------------------------------------------------------- #
# dedupe + budget
# --------------------------------------------------------------------------- #


def _dedupe(raw: list[AssetCandidate]) -> list[AssetCandidate]:
    """First reference wins the origin; ``dark_scheme`` survives only if EVERY one was dark."""
    order: list[str] = []
    first: dict[str, AssetCandidate] = {}
    all_dark: dict[str, bool] = {}
    for candidate in raw:
        if candidate.url not in first:
            first[candidate.url] = candidate
            all_dark[candidate.url] = candidate.dark_scheme
            order.append(candidate.url)
        else:
            all_dark[candidate.url] = all_dark[candidate.url] and candidate.dark_scheme
    return [
        AssetCandidate(
            url=url,
            origin=first[url].origin,
            kind=first[url].kind,
            dark_scheme=all_dark[url],
            detail=first[url].detail,
        )
        for url in order
    ]


def _budgeted(candidates: list[AssetCandidate]) -> CandidateHarvest:
    if len(candidates) <= MAX_ASSET_COUNT:
        return CandidateHarvest(candidates=candidates, diagnostics=[])
    kept = candidates[:MAX_ASSET_COUNT]
    dropped = [candidate.url for candidate in candidates[MAX_ASSET_COUNT:]]
    return CandidateHarvest(
        candidates=kept,
        diagnostics=[
            budget_diagnostic(budget="asset count", limit=MAX_ASSET_COUNT, dropped=dropped)
        ],
    )
