"""Bounded source-library discovery from observed links, never invented routes.

Automatic discovery stays on the captured site's origin. Explicit URLs remain
operator-selected and pass through the usual network guard at capture time.
Coverage describes acquisition, not approval or visual fidelity.
"""

from __future__ import annotations

import re
from collections import Counter
from urllib.parse import urldefrag, urljoin, urlsplit

import tinycss2
from selectolax.lexbor import LexborHTMLParser, LexborNode

MAX_CAPTURE_PAGES = 20
ROLE_LIMITS = {"product": 2, "customers": 1, "case-study": 2}
_PRODUCT_LABELS = frozenset({"product", "products", "platform", "features", "services"})
_LIST_SELECTOR = 'ul, ol, [role="list"], [role="menu"]'
# Only constrain the semantic fallback: existing explicit product/proof URL roles
# keep their contract (e.g. /product/security is still a product page).
_CONTEXT_UTILITY_NAMES = frozenset(
    {
        "pricing",
        "security",
        "changelog",
        "docs",
        "documentation",
        "developers",
        "download",
        "downloads",
        "signup",
        "sign up",
        "register",
        "contact",
        "contact sales",
        "contact us",
        "support",
        "help",
        "help center",
        "status",
    }
)
_EXCLUDED_SEGMENTS = frozenset(
    {
        "privacy",
        "terms",
        "legal",
        "login",
        "signin",
        "sign-in",
        "logout",
        "cart",
        "checkout",
        "blog",
        "news",
        "press",
        "careers",
        "jobs",
    }
)
_PROOF_SEGMENTS = frozenset(
    {
        "customers",
        "customer",
        "case-studies",
        "case-study",
        "customer-stories",
        "success-stories",
        "testimonials",
        "reviews",
    }
)

_STRONG_PROOF_SEGMENTS = frozenset(
    {"case-studies", "case-study", "customer-stories", "success-stories"}
)
_PROOF_COLLECTION_CTA = re.compile(
    r"(?:view|see|browse|explore|read) (?:all|more) "
    r"(?:stories|customer stories|success stories|case studies|customers|testimonials|reviews)"
)


def page_role(url: str, label: str = "") -> str:
    segments = [part.lower() for part in urlsplit(url).path.split("/") if part]
    if set(segments) & _EXCLUDED_SEGMENTS:
        return "reference"
    product_namespace = False
    for index, segment in enumerate(segments):
        product_namespace |= segment in _PRODUCT_LABELS
        if segment in _PROOF_SEGMENTS:
            # A product's customer/review feature is not evidence of customers.
            # Explicit story namespaces still carry proof inside a product tree.
            if product_namespace and segment not in _STRONG_PROOF_SEGMENTS:
                continue
            # Depth alone cannot distinguish a nested collection from a story.
            # Use a complete, observed collection CTA only within a proof path;
            # arbitrary prose containing these words is not a role override.
            if _PROOF_COLLECTION_CTA.fullmatch(_label(label)):
                return "customers"
            return "case-study" if segments[index + 1 :] else "customers"
    if set(segments) & _PRODUCT_LABELS:
        return "product"
    if "case study" in label.lower() or "customer story" in label.lower():
        return "case-study"
    return "reference"


def canonical_page_url(url: str, base: str) -> str:
    # Exact query strings remain part of source identity; only anchors are not pages.
    return urldefrag(urljoin(base, url.strip()))[0]


def _label(text: str) -> str:
    return " ".join(text.split()).casefold()


def _closest(
    node: LexborNode | None, tags: tuple[str, ...], roles: tuple[str, ...]
) -> LexborNode | None:
    while node is not None:
        if node.tag in tags or node.attributes.get("role") in roles:
            return node
        node = node.parent
    return None


def _navigation(node: LexborNode) -> LexborNode | None:
    return _closest(node, ("nav", "footer"), ("navigation", "contentinfo"))


def _aria_label(
    node: LexborNode, landmark: LexborNode, ids: dict[str, list[LexborNode]]
) -> str | None:
    # None means absent. An invalid/ambiguous explicit label returns an empty
    # string so a nearby heading cannot silently override it.
    attrs = node.attributes
    if "aria-labelledby" in attrs:
        parts = []
        for ref in (attrs["aria-labelledby"] or "").split():
            matches = ids.get(ref, [])
            if len(matches) != 1 or _navigation(matches[0]) != landmark:
                return ""
            parts.append(matches[0].text(separator=" ", strip=True))
        return _label(" ".join(parts))
    if "aria-label" in attrs:
        return _label(attrs["aria-label"] or "")
    return None


def _product_group_links(dom: LexborHTMLParser) -> set[int]:
    """Node identities under an explicitly labelled, local navigation list.

    Never borrow the text of an entire footer/page. A heading must be a direct
    sibling of the only list in its group; ARIA references must resolve uniquely
    within the same navigation/footer landmark. Nested lists own their labels.
    """
    ids: dict[str, list[LexborNode]] = {}
    for node in dom.css("[id]"):
        ids.setdefault(node.attributes["id"], []).append(node)
    links: set[int] = set()
    for listing in dom.css(_LIST_SELECTOR):
        landmark = _navigation(listing)
        if landmark is None:
            continue
        label = _aria_label(listing, landmark, ids)
        if label is None:
            group = listing.parent
            if (
                group is None
                or _navigation(group) != landmark
                or len(group.css(_LIST_SELECTOR)) != 1
            ):
                continue
            label = _aria_label(group, landmark, ids)
            if label is None:
                headings = [node for node in group.css("h1,h2,h3,h4,h5,h6") if node.parent == group]
                if len(headings) != 1:
                    continue
                label = _label(headings[0].text(separator=" ", strip=True))
        if label not in _PRODUCT_LABELS:
            continue
        links.update(
            node.mem_id
            for node in listing.css("a[href]")
            if _closest(node, ("ul", "ol"), ("list", "menu")) == listing
        )
    return links


def _context_product_allowed(url: str, label: str) -> bool:
    segments = {part.lower() for part in urlsplit(url).path.split("/") if part}
    return not (
        segments & (_EXCLUDED_SEGMENTS | _CONTEXT_UTILITY_NAMES)
        or _label(label) in _CONTEXT_UTILITY_NAMES
    )


def discover_reference_pages(html: str, base_url: str, *, existing: list[dict]) -> list[dict]:
    counts = Counter(row["role"] for row in existing)
    seen = {canonical_page_url(row["url"], base_url) for row in existing}
    seen.add(canonical_page_url(base_url, base_url))
    origin = urlsplit(base_url)
    candidates: dict[str, list[dict]] = {role: [] for role in ROLE_LIMITS}
    dom = LexborHTMLParser(html)
    product_links = _product_group_links(dom)
    for node in dom.css("a[href]"):
        href = node.attributes.get("href", "").strip()
        if not href or href.startswith("#"):
            continue
        try:
            url = canonical_page_url(href, base_url)
            parsed = urlsplit(url)
        except ValueError:
            # Untrusted source markup can contain malformed URLs; one bad link
            # must not discard all otherwise valid, bounded page candidates.
            continue
        if (parsed.scheme, parsed.netloc) != (origin.scheme, origin.netloc):
            continue
        if parsed.username or parsed.password or url in seen:
            continue
        label = node.text(separator=" ", strip=True)
        role = page_role(url, label)
        if (
            role == "reference"
            and node.mem_id in product_links
            and _context_product_allowed(url, label)
        ):
            role = "product"
        if role not in candidates:
            continue
        seen.add(url)
        candidates[role].append({"url": url, "role": role, "discovered_from": base_url})
    result = []
    for role, limit in ROLE_LIMITS.items():
        for row in candidates[role][: max(0, limit - counts[role])]:
            if len(existing) + len(result) >= MAX_CAPTURE_PAGES:
                return result
            result.append(row)
    return result


def motion_inventory(snapshot) -> dict:
    dom = LexborHTMLParser(snapshot.html)
    keyframes: set[str] = set()

    def collect(rules) -> None:
        for rule in rules:
            if getattr(rule, "type", "") != "at-rule":
                continue
            if rule.lower_at_keyword in {"keyframes", "-webkit-keyframes", "-moz-keyframes"}:
                name = tinycss2.serialize(rule.prelude).strip().strip("\"'")
                if name:
                    keyframes.add(name)
            elif rule.content and rule.lower_at_keyword in {
                "media",
                "supports",
                "layer",
                "container",
            }:
                collect(tinycss2.parse_rule_list(rule.content))

    for sheet in snapshot.stylesheets:
        collect(tinycss2.parse_stylesheet(sheet.text, skip_comments=True, skip_whitespace=True))
    base = snapshot.final_url or snapshot.requested_url
    videos = sorted(
        {urljoin(base, node.attributes["src"]) for node in dom.css("video[src], video source[src]")}
    )
    posters = sorted(
        {urljoin(base, node.attributes["poster"]) for node in dom.css("video[poster]")}
    )
    downloaded = {asset.url for asset in snapshot.downloads}
    return {
        "css_keyframes": sorted(keyframes),
        "videos": videos,
        "video_posters": posters,
        "missing_video_assets": sorted(set(videos + posters) - downloaded),
        "canvas_count": len(dom.css("canvas")),
        "canvas_runtime_recovered": False,
        "script_count": len(dom.css("script")),
        "source_scripts_replayable": False,
    }


def page_coverage(snapshot, *, role: str, diagnostics: list[dict]) -> dict:
    return {
        "url": snapshot.requested_url,
        "final_url": snapshot.final_url,
        "role": role,
        "status": "partial"
        if any(d.get("severity") in {"warning", "error"} for d in diagnostics)
        else "captured",
        "tier": snapshot.tier,
        "captured_at": snapshot.fetched_at,
        "asset_count": len(snapshot.downloads),
        "diagnostics": diagnostics,
        "motion": motion_inventory(snapshot),
        "fidelity_verified": False,
    }
