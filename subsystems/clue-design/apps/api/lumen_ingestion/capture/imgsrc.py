"""The ONE image-source chooser both the downloader and the parser walk.

Why this module exists as a seam rather than two local helpers
-------------------------------------------------------------
``static._collect_assets`` decides which URLs are DOWNLOADED into the snapshot;
``parse._parse_images`` then looks bytes up **by URL** (``_download_by_url``), and an asset
with no bytes is dropped outright (``evidence_builder.queue`` returns ``None`` without a
sha). So the collector and the parser must agree, per ``<img>`` element, on which URL
represents it. If one of them ever picked the widest ``srcset`` candidate while the other
still resolved the bare ``src``, EVERY image would lose its bytes and the kit would come out
with zero images. Implementing the choice twice is precisely the failure mode; hence one
function, imported by both, pinned by
``test_ingestion_image_sources.py::test_the_collector_and_the_parser_call_the_same_chooser``.

What changed (founder order, 2026-08-20)
----------------------------------------
Ingestion used to enqueue exactly ``node.attributes["src"]`` and cap the harvest at 12. A
brand on an image CDN therefore handed us its *thumbnail*: the live Stripe kit stored
thirteen 296px-wide renditions because every ``src`` carried ``?w=296&q=90`` — including a
``_2x.png`` retina asset — while the single URL with no width param came back 2048x1024. The
pipeline stored whatever it asked for; it simply asked for the small one. These assets are
reused directly in generated microsites and later as reference images for the
image-generation tool, so the thumbnail is a real quality loss, not a cosmetic one.

The ladder, best first:
  1. the widest ``srcset`` candidate (``w`` descriptors by pixel width; failing that ``x``
     descriptors by density), including ``<picture><source srcset=…>`` entries, which
     precede the ``<img>`` fallback in document order;
  2. a CDN width-param upgrade of the best URL so far — recognized width params raised to
     :data:`TARGET_IMAGE_WIDTH`, every other param preserved and an explicit height scaled
     with it so the aspect ratio survives;
  3. the bare ``src`` — today's behaviour, ALWAYS the last rung, so the new machinery can
     never do worse than the old.

The parser walks the same ladder and takes the first rung that actually produced bytes, so a
CDN that refuses a widened request costs us nothing. Cost note: the ladder is bounded at
:data:`MAX_CANDIDATES_PER_IMAGE` rungs, so with the 50-image cap the image fetch count can
roughly double (~150 requests worst case). That is accepted — the fan-out is async under
``net.DEFAULT_CONCURRENCY`` (8) and every ``net.py`` byte cap/timeout is unchanged.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

#: The rendition width a CDN width-param upgrade asks for. 2048 is the widest rendition the
#: live evidence proved a real CDN serves un-asked (``Stripe.jpg?q=80`` → 2048x1024), and
#: comfortably above any 2x hero on a 1440-wide viewport. Every sane image CDN clamps to the
#: original when the source is smaller, so asking high is free.
TARGET_IMAGE_WIDTH = 2048

#: Query params image CDNs use for the requested width (Contentful/imgix/Shopify/Cloudinary
#: family). Matched case-insensitively.
_WIDTH_PARAMS = ("w", "width", "sw")
#: Their height counterparts — scaled by the same factor so the upgrade never distorts.
_HEIGHT_PARAMS = ("h", "height", "sh")

#: Rungs per ``<img>``. The bound is the cost dial: rung 1 is the best candidate, rung 2 its
#: fallback, and the bare ``src`` is always last. Three keeps the worst case at 3x today's
#: image fetch count.
MAX_CANDIDATES_PER_IMAGE = 3

#: The parsed-image ceiling, raised 12 → 50 by founder order 2026-08-20 (extraction must be
#: exhaustive: these assets are reused in generated microsites and as image-generation
#: references). Lives here rather than in ``parse.py`` so the cap and the ladder that feeds
#: it are read together.
IMAGE_CANDIDATE_CAP = 50

#: Ceiling on CSS ``background-image`` URLs harvested from one site. A large design system's
#: stylesheets can reference hundreds of sprites; the cap keeps the fan-out bounded while
#: still reaching the hero art and gradients a brand actually keeps in CSS.
MAX_BACKGROUND_IMAGES = 40

#: ``background``/``background-image`` declarations only — a ``@font-face`` ``src: url(…)``
#: is the font path's business and must not be double-counted here.
_BACKGROUND_DECL_RE = re.compile(
    r"background(?:-image)?\s*:\s*([^;{}]*)", re.IGNORECASE
)
_CSS_URL_RE = re.compile(r"url\(\s*(?:'([^']*)'|\"([^\"]*)\"|([^)'\"\s]+))\s*\)")

_SRCSET_DESCRIPTOR_RE = re.compile(r"^([0-9]*\.?[0-9]+)([wx])$", re.IGNORECASE)


# --------------------------------------------------------------------------- #
# srcset
# --------------------------------------------------------------------------- #


def parse_srcset(value: str | None) -> list[tuple[str, float, str]]:
    """``srcset`` → ``[(url, descriptor_value, "w" | "x"), …]`` in document order.

    An entry with no descriptor is ``1x`` per the HTML spec. Malformed entries are dropped
    rather than guessed at.
    """
    if not value:
        return []
    entries: list[tuple[str, float, str]] = []
    for chunk in value.split(","):
        parts = chunk.split()
        if not parts:
            continue
        url = parts[0].strip()
        if not url:
            continue
        descriptor, kind = 1.0, "x"
        if len(parts) > 1:
            match = _SRCSET_DESCRIPTOR_RE.match(parts[1].strip())
            if match is None:
                continue
            descriptor = float(match.group(1))
            kind = match.group(2).lower()
        entries.append((url, descriptor, kind))
    return entries


# --------------------------------------------------------------------------- #
# CDN width-param upgrade
# --------------------------------------------------------------------------- #


def upgrade_width_params(url: str, target: int = TARGET_IMAGE_WIDTH) -> str | None:
    """Raise a CDN width param to ``target``, or ``None`` when there is nothing to raise.

    Returns ``None`` (never a rewritten URL) when the URL carries no recognized width param
    or already asks for ``target`` or more — we upgrade, we never downgrade, and we never
    invent a param a CDN did not already prove it honours.
    """
    if not url or url.startswith("data:"):
        return None
    split = urlsplit(url)
    if not split.query:
        return None
    pairs = parse_qsl(split.query, keep_blank_values=True)

    factor: float | None = None
    upgraded: list[tuple[str, str]] = []
    for name, value in pairs:
        if name.lower() in _WIDTH_PARAMS and value.isdigit():
            current = int(value)
            if 0 < current < target:
                factor = target / current
                upgraded.append((name, str(target)))
                continue
        upgraded.append((name, value))
    if factor is None:
        return None

    # Scale an explicit height by the same factor: raising w alone on a `?w=&h=` CDN request
    # would silently change the crop.
    scaled: list[tuple[str, str]] = []
    for name, value in upgraded:
        if name.lower() in _HEIGHT_PARAMS and value.isdigit():
            scaled.append((name, str(max(1, round(int(value) * factor)))))
        else:
            scaled.append((name, value))

    return urlunsplit(
        (split.scheme, split.netloc, split.path, urlencode(scaled), split.fragment)
    )


# --------------------------------------------------------------------------- #
# the ladder
# --------------------------------------------------------------------------- #


def image_source_ladder(node, base_url: str) -> list[str]:
    """Ordered, absolutized candidate URLs for one ``<img>`` — best rendition first.

    The bare ``src`` is always the final rung (when the element has one), so a caller that
    walks the ladder until it finds bytes can never end up worse off than the old
    ``src``-only behaviour.
    """
    raw_src = (node.attributes.get("src") or "").strip()

    # A data: URI is inert: nothing to download, nothing to upgrade. It rides through
    # verbatim so the parser's existing 50 KB guard still sees exactly what it used to.
    if raw_src.startswith("data:"):
        return [raw_src]

    ranked = _ranked_srcset_urls(node, base_url)
    src = urljoin(base_url, raw_src) if raw_src else None

    preferred: list[str] = []
    best = ranked[0] if ranked else src
    if best:
        upgraded_best = upgrade_width_params(best)
        if upgraded_best:
            preferred.append(upgraded_best)
    preferred.extend(ranked)
    if src:
        upgraded_src = upgrade_width_params(src)
        if upgraded_src:
            preferred.append(upgraded_src)

    ladder = _dedup(preferred)
    if src:
        # Reserve the last rung for the bare src, then trim the rest to the cost bound.
        ladder = [url for url in ladder if url != src][: MAX_CANDIDATES_PER_IMAGE - 1]
        ladder.append(src)
    else:
        ladder = ladder[:MAX_CANDIDATES_PER_IMAGE]
    return ladder


def _ranked_srcset_urls(node, base_url: str) -> list[str]:
    """Every ``srcset`` candidate for this ``<img>``, widest first.

    ``<picture><source>`` entries are read in document order ahead of the ``<img>``'s own
    ``srcset``, which is how the browser considers them. Descriptor families are not mixed:
    if any candidate carries a ``w`` descriptor we rank by pixel width and the ``x`` entries
    become fallbacks; otherwise we rank by density.
    """
    collected: list[tuple[str, float, str, int]] = []
    order = 0
    parent = getattr(node, "parent", None)
    if parent is not None and (parent.tag or "").lower() == "picture":
        for source in parent.css("source"):
            for url, descriptor, kind in parse_srcset(source.attributes.get("srcset")):
                collected.append((url, descriptor, kind, order))
                order += 1
    for url, descriptor, kind in parse_srcset(node.attributes.get("srcset")):
        collected.append((url, descriptor, kind, order))
        order += 1

    if not collected:
        return []

    widths = [c for c in collected if c[2] == "w"]
    densities = [c for c in collected if c[2] != "w"]
    primary, secondary = (widths, densities) if widths else (densities, widths)

    def key(entry: tuple[str, float, str, int]):
        return (-entry[1], entry[3])

    ordered = sorted(primary, key=key) + sorted(secondary, key=key)
    return _dedup(
        urljoin(base_url, url)
        for url, _descriptor, _kind, _order in ordered
        if url and not url.startswith("data:")
    )


# --------------------------------------------------------------------------- #
# CSS background-image
# --------------------------------------------------------------------------- #


def background_image_urls(tree, stylesheets, base_url: str) -> list[str]:
    """Absolutized ``background-image`` URLs from inline ``style`` attrs and fetched CSS.

    This is where a brand like Stripe keeps its gradients and hero art, and none of it was
    ever downloaded. Shared by the collector and the parser for the same reason the ``<img>``
    ladder is: the parser resolves bytes by URL, so both sides must derive the same list.

    ``@font-face`` ``src: url(…)`` is deliberately not matched (the font path owns it) and
    data: URIs are skipped — there is nothing to fetch and the inline bytes are already in
    the HTML the snapshot carries.
    """
    urls: list[str] = []

    for node in tree.css("[style]"):
        style = node.attributes.get("style") or ""
        urls.extend(_background_urls_in_css(style, base_url))

    for sheet in stylesheets:
        sheet_url = getattr(sheet, "url", "") or ""
        base = base_url if sheet_url.startswith("inline:") or not sheet_url else sheet_url
        urls.extend(_background_urls_in_css(getattr(sheet, "text", "") or "", base))

    return _dedup(urls)[:MAX_BACKGROUND_IMAGES]


def _background_urls_in_css(css_text: str, base: str) -> list[str]:
    if "background" not in css_text.lower():
        return []
    found: list[str] = []
    for declaration in _BACKGROUND_DECL_RE.finditer(css_text):
        for match in _CSS_URL_RE.finditer(declaration.group(1)):
            raw = (match.group(1) or match.group(2) or match.group(3) or "").strip()
            if not raw or raw.startswith("data:") or raw.startswith("#"):
                continue
            found.append(urljoin(base, raw))
    return found


# --------------------------------------------------------------------------- #


def _dedup(urls) -> list[str]:
    return list(dict.fromkeys(url for url in urls if url))
