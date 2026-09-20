"""Bounded source-library discovery from observed links, never invented routes.

Automatic discovery stays on the captured site's origin. Explicit URLs remain
operator-selected and pass through the usual network guard at capture time.
Coverage describes acquisition, not approval or visual fidelity.
"""

from __future__ import annotations

from collections import Counter
from urllib.parse import urldefrag, urljoin, urlsplit

import tinycss2
from selectolax.lexbor import LexborHTMLParser

MAX_CAPTURE_PAGES = 20
ROLE_LIMITS = {"product": 2, "customers": 1, "case-study": 2}
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


def page_role(url: str, label: str = "") -> str:
    segments = [part.lower() for part in urlsplit(url).path.split("/") if part]
    if set(segments) & _EXCLUDED_SEGMENTS:
        return "reference"
    for index, segment in enumerate(segments):
        if segment in _PROOF_SEGMENTS:
            return "case-study" if segments[index + 1 :] else "customers"
    if set(segments) & {"product", "products", "platform", "features", "services"}:
        return "product"
    if "case study" in label.lower() or "customer story" in label.lower():
        return "case-study"
    return "reference"


def canonical_page_url(url: str, base: str) -> str:
    # Exact query strings remain part of source identity; only anchors are not pages.
    return urldefrag(urljoin(base, url.strip()))[0]


def discover_reference_pages(html: str, base_url: str, *, existing: list[dict]) -> list[dict]:
    counts = Counter(row["role"] for row in existing)
    seen = {canonical_page_url(row["url"], base_url) for row in existing}
    seen.add(canonical_page_url(base_url, base_url))
    origin = urlsplit(base_url)
    candidates: dict[str, list[dict]] = {role: [] for role in ROLE_LIMITS}
    for node in LexborHTMLParser(html).css("a[href]"):
        href = node.attributes.get("href", "").strip()
        if not href or href.startswith("#"):
            continue
        url = canonical_page_url(href, base_url)
        parsed = urlsplit(url)
        if (parsed.scheme, parsed.netloc) != (origin.scheme, origin.netloc):
            continue
        if parsed.username or parsed.password or url in seen:
            continue
        label = node.text(separator=" ", strip=True)
        role = page_role(url, label)
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
