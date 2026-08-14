"""Deterministic URL classification and discovery planning for official-site crawling (C2)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from html.parser import HTMLParser
from types import MappingProxyType
from urllib.parse import urlsplit
from uuid import UUID

from clue_research.official_site.contracts import (
    CrawlEligibility,
    DiscoveredVia,
    LinkObservation,
    LinkRelation,
    PolicyOutcome,
    UrlObservation,
)
from clue_research.official_site.safety import (
    DEFAULT_CRAWL_SAFETY_POLICY,
    CrawlSafetyPolicy,
    bound_outgoing_links,
)
from clue_research.official_site.sitemap import SitemapEntry
from clue_research.official_site.url_policy import ConservativeUrlPolicy, FetchKeyDecision

DISCOVERY_POLICY_VERSION = "official-site-discovery-v1"


class PageCategory(StrEnum):
    HOMEPAGE = "homepage"
    PRODUCT = "product"
    PRICING = "pricing"
    CUSTOMER_PROOF = "customer_proof"
    COMPANY = "company"
    PARTNER = "partner"
    TRUST = "trust"
    BLOG = "blog"
    REMAINING = "remaining"


FAST_CATEGORY_QUOTAS: Mapping[str, int] = MappingProxyType(
    {
        PageCategory.HOMEPAGE.value: 1,
        PageCategory.PRODUCT.value: 3,
        PageCategory.PRICING.value: 1,
        PageCategory.CUSTOMER_PROOF.value: 2,
        PageCategory.COMPANY.value: 1,
        PageCategory.PARTNER.value: 1,
        PageCategory.TRUST.value: 1,
        PageCategory.BLOG.value: 1,
    }
)
FAST_CATEGORY_ORDER = tuple(FAST_CATEGORY_QUOTAS)


_CATEGORY_PATTERNS: tuple[tuple[PageCategory, tuple[str, ...]], ...] = (
    (PageCategory.PRICING, ("pricing", "plans", "quote")),
    (
        PageCategory.CUSTOMER_PROOF,
        ("customer", "case-study", "case-studies", "testimonial", "stories", "success"),
    ),
    (
        PageCategory.COMPANY,
        ("about", "company", "mission", "founder", "leadership", "team", "who-we-are"),
    ),
    (PageCategory.PARTNER, ("partner", "integration", "ecosystem")),
    (PageCategory.TRUST, ("trust", "security", "compliance", "privacy")),
    (
        PageCategory.PRODUCT,
        ("product", "solution", "use-case", "usecase", "platform", "feature", "service"),
    ),
    (PageCategory.BLOG, ("blog", "news", "insight", "resource")),
)

_CATEGORY_PRIORITY = {
    PageCategory.HOMEPAGE: 0,
    PageCategory.PRODUCT: 10,
    PageCategory.PRICING: 20,
    PageCategory.CUSTOMER_PROOF: 30,
    PageCategory.COMPANY: 40,
    PageCategory.PARTNER: 50,
    PageCategory.TRUST: 60,
    PageCategory.BLOG: 70,
    PageCategory.REMAINING: 100,
}


@dataclass(frozen=True, slots=True)
class ExtractedPageLinks:
    links: tuple[LinkObservation, ...]
    canonical_hints: tuple[LinkObservation, ...]
    dropped_links: int


def classify_page(url: str, *, link_text: str | None = None) -> PageCategory:
    parts = urlsplit(url)
    if (parts.path or "/") == "/" and not parts.query and not parts.fragment:
        return PageCategory.HOMEPAGE
    path = parts.path.casefold().replace("_", "-")
    for category, patterns in _CATEGORY_PATTERNS:
        if any(pattern in path for pattern in patterns):
            return category
    # Provider link extraction may return an entire article-card description as anchor text. Use
    # that bounded text only when the URL path itself is opaque; otherwise a blog sentence that
    # happens to mention "plans" can incorrectly outrank its explicit /blog/ path as pricing.
    text = (link_text or "").casefold().replace("_", "-")
    for category, patterns in _CATEGORY_PATTERNS:
        if any(pattern in text for pattern in patterns):
            return category
    return PageCategory.REMAINING


def _eligibility(category: PageCategory) -> CrawlEligibility:
    if category is PageCategory.REMAINING:
        return CrawlEligibility.BACKGROUND
    return CrawlEligibility.BOTH


def _admission_order(observation: UrlObservation) -> tuple[int, int, str, str, str, str]:
    """Make capacity admission independent of provider/DOM link ordering.

    The repository intentionally preserves the order of a discovery batch because every parser
    occurrence is provenance.  It also applies the crawl-wide page ceiling while consuming that
    batch.  Sort here, at the deterministic policy seam, so a provider returning footer links
    before product/pricing/company links cannot spend the ceiling on lower-priority pages.

    This does not deduplicate observations or change URL identity.  The remaining fields provide
    a stable order within a priority band while retaining every occurrence downstream.
    """

    return (
        0 if observation.policy_outcome is PolicyOutcome.ADMITTED else 1,
        observation.priority,
        observation.fetch_key or observation.discovered_url,
        observation.discovered_via.value,
        observation.link_text or "",
        observation.policy_reason or "",
    )


def _observation_category(observation: UrlObservation) -> str | None:
    reasons = frozenset(observation.priority_reason)
    return next(
        (category for category in FAST_CATEGORY_ORDER if f"category:{category}" in reasons),
        None,
    )


def _refused(
    *,
    discovered_url: str,
    discovered_via: DiscoveredVia,
    reason: str,
    source_page_id: UUID | None,
    link_text: str | None,
    decision: FetchKeyDecision | None = None,
    sitemap_url: str | None = None,
) -> UrlObservation:
    return UrlObservation(
        discovered_url=discovered_url,
        discovered_via=discovered_via,
        sitemap_url=sitemap_url,
        fetch_key=decision.fetch_key if decision is not None else None,
        fetch_key_hash=decision.fetch_key_hash if decision is not None else None,
        source_page_id=source_page_id,
        graph_depth=None,
        link_text=link_text,
        eligibility=CrawlEligibility.REFUSED,
        policy_outcome=PolicyOutcome.REFUSED,
        policy_reason=reason,
    )


class OfficialSiteDiscoveryPolicy:
    def __init__(
        self,
        *,
        url_policy: ConservativeUrlPolicy,
        safety: CrawlSafetyPolicy = DEFAULT_CRAWL_SAFETY_POLICY,
        version: str = DISCOVERY_POLICY_VERSION,
    ) -> None:
        if version != DISCOVERY_POLICY_VERSION:
            raise ValueError(f"unsupported discovery policy version: {version}")
        self.url_policy = url_policy
        self.safety = safety
        self.version = version

    def root(self, url: str) -> UrlObservation:
        decision = self.url_policy.decide(url)
        if not decision.admitted:
            return _refused(
                discovered_url=url,
                discovered_via=DiscoveredVia.ROOT,
                reason=decision.reason,
                source_page_id=None,
                link_text=None,
            )
        return self._admitted(
            decision=decision,
            via=DiscoveredVia.ROOT,
            source_page_id=None,
            graph_depth=0,
            link_text=None,
            category=PageCategory.HOMEPAGE,
        )

    def link(
        self,
        link: LinkObservation,
        *,
        source_page_id: UUID,
        source_url: str,
        source_graph_depth: int | None,
    ) -> UrlObservation:
        link_text = (
            link.link_text[: self.safety.max_link_text_chars]
            if link.link_text is not None
            else None
        )
        via = {
            LinkRelation.REDIRECT: DiscoveredVia.REDIRECT,
            LinkRelation.CANONICAL_HINT: DiscoveredVia.CANONICAL,
        }.get(link.relation, DiscoveredVia.LINK)
        decision = self.url_policy.decide(link.discovered_url, base_url=source_url)
        if via in {DiscoveredVia.REDIRECT, DiscoveredVia.CANONICAL}:
            return self._alias(
                decision=decision,
                discovered_url=link.discovered_url,
                via=via,
                source_page_id=source_page_id,
                link_text=link_text,
            )
        if not decision.admitted:
            return _refused(
                discovered_url=link.discovered_url,
                discovered_via=via,
                reason=decision.reason,
                source_page_id=source_page_id,
                link_text=link_text,
            )
        if source_graph_depth is not None and source_graph_depth >= 2:
            return _refused(
                discovered_url=link.discovered_url,
                discovered_via=via,
                reason="graph_depth_ceiling_exceeded",
                source_page_id=source_page_id,
                link_text=link_text,
                decision=decision,
            )
        depth = source_graph_depth + 1 if source_graph_depth is not None else None
        category = classify_page(decision.fetch_key or link.discovered_url, link_text=link_text)
        return self._admitted(
            decision=decision,
            via=via,
            source_page_id=source_page_id,
            graph_depth=depth,
            link_text=link_text,
            category=category,
        )

    def sitemap(self, entry: SitemapEntry) -> UrlObservation:
        decision = self.url_policy.decide(entry.discovered_url)
        if not decision.admitted:
            return _refused(
                discovered_url=entry.discovered_url,
                discovered_via=DiscoveredVia.SITEMAP,
                reason=decision.reason,
                source_page_id=None,
                link_text=None,
                sitemap_url=entry.sitemap_url,
            )
        category = classify_page(decision.fetch_key or entry.discovered_url)
        return self._admitted(
            decision=decision,
            via=DiscoveredVia.SITEMAP,
            source_page_id=None,
            graph_depth=None,
            link_text=None,
            category=category,
            extra_reason=f"sitemap:{entry.sitemap_url}",
            sitemap_url=entry.sitemap_url,
        )

    def plan_links(
        self,
        links: tuple[LinkObservation, ...],
        *,
        source_page_id: UUID,
        source_url: str,
        source_graph_depth: int | None,
    ) -> tuple[tuple[UrlObservation, ...], int]:
        bounded = bound_outgoing_links(links, safety=self.safety)
        planned = tuple(
            self.link(
                link,
                source_page_id=source_page_id,
                source_url=source_url,
                source_graph_depth=source_graph_depth,
            )
            for link in bounded.links
        )
        return self.order_for_admission(planned), bounded.dropped_count

    def order_for_admission(
        self, observations: tuple[UrlObservation, ...]
    ) -> tuple[UrlObservation, ...]:
        """Put unique category-quota candidates before the capacity-sensitive tail.

        Fast claiming and initial frontier admission intentionally share one quota vocabulary.
        The prefix reserves no phantom pages: it includes only categories actually observed.  All
        duplicates, excess same-category URLs, remaining pages, and refusals stay in the returned
        batch, so neither provenance nor background coverage is discarded.
        """

        admitted = sorted(
            (
                observation
                for observation in observations
                if observation.policy_outcome is PolicyOutcome.ADMITTED
            ),
            key=_admission_order,
        )
        refused = sorted(
            (
                observation
                for observation in observations
                if observation.policy_outcome is PolicyOutcome.REFUSED
            ),
            key=_admission_order,
        )
        prefix: list[UrlObservation] = []
        selected_indices: set[int] = set()
        selected_fetch_keys: set[str] = set()
        for category in FAST_CATEGORY_ORDER:
            selected_for_category = 0
            for index, observation in enumerate(admitted):
                if selected_for_category >= FAST_CATEGORY_QUOTAS[category]:
                    break
                if index in selected_indices or _observation_category(observation) != category:
                    continue
                assert observation.fetch_key is not None
                if observation.fetch_key in selected_fetch_keys:
                    continue
                prefix.append(observation)
                selected_indices.add(index)
                selected_fetch_keys.add(observation.fetch_key)
                selected_for_category += 1
        tail = [
            observation
            for index, observation in enumerate(admitted)
            if index not in selected_indices
        ]
        return (*prefix, *tail, *refused)

    def _alias(
        self,
        *,
        decision: FetchKeyDecision,
        discovered_url: str,
        via: DiscoveredVia,
        source_page_id: UUID,
        link_text: str | None,
    ) -> UrlObservation:
        if not decision.admitted:
            return _refused(
                discovered_url=discovered_url,
                discovered_via=via,
                reason=f"{via.value}_{decision.reason}_refused",
                source_page_id=source_page_id,
                link_text=link_text,
            )
        return _refused(
            discovered_url=discovered_url,
            discovered_via=via,
            reason=f"{via.value}_hint_observed_no_identity_merge",
            source_page_id=source_page_id,
            link_text=link_text,
            decision=decision,
        )

    def _admitted(
        self,
        *,
        decision: FetchKeyDecision,
        via: DiscoveredVia,
        source_page_id: UUID | None,
        graph_depth: int | None,
        link_text: str | None,
        category: PageCategory,
        extra_reason: str | None = None,
        sitemap_url: str | None = None,
    ) -> UrlObservation:
        assert decision.fetch_key is not None and decision.fetch_key_hash is not None
        reasons = [f"category:{category.value}", f"via:{via.value}"]
        if decision.removed_tracking_parameters:
            reasons.append("tracking_removed")
        if decision.routing_fragment:
            reasons.append("routing_fragment")
        if extra_reason:
            reasons.append(extra_reason)
        return UrlObservation(
            discovered_url=decision.discovered_url,
            discovered_via=via,
            sitemap_url=sitemap_url,
            fetch_key=decision.fetch_key,
            fetch_key_hash=decision.fetch_key_hash,
            source_page_id=source_page_id,
            graph_depth=graph_depth,
            link_text=link_text,
            priority=_CATEGORY_PRIORITY[category],
            priority_reason=tuple(reasons),
            eligibility=_eligibility(category),
            policy_outcome=PolicyOutcome.ADMITTED,
            policy_reason=decision.reason,
        )


class _HtmlLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[LinkObservation] = []
        self.canonical_hints: list[LinkObservation] = []
        self._anchor_href: str | None = None
        self._anchor_text: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        if self._ignored_depth:
            if tag in {"script", "style", "template"}:
                self._ignored_depth += 1
            return
        attributes = {key.casefold(): value for key, value in attrs}
        if tag in {"script", "style", "template"}:
            self._ignored_depth = 1
            return
        if tag == "a" and attributes.get("href"):
            self._anchor_href = attributes["href"]
            self._anchor_text = []
        if tag == "link" and attributes.get("href"):
            relations = (attributes.get("rel") or "").casefold().split()
            if "canonical" in relations:
                self.canonical_hints.append(
                    LinkObservation(
                        discovered_url=attributes["href"] or "",
                        relation=LinkRelation.CANONICAL_HINT,
                    )
                )

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if self._ignored_depth:
            if tag in {"script", "style", "template"}:
                self._ignored_depth -= 1
            return
        if tag == "a" and self._anchor_href is not None:
            text = " ".join("".join(self._anchor_text).split()) or None
            self.links.append(LinkObservation(discovered_url=self._anchor_href, link_text=text))
            self._anchor_href = None
            self._anchor_text = []
        if tag in {"script", "style", "template"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._anchor_href is not None and self._ignored_depth == 0:
            self._anchor_text.append(data)


def extract_html_links(
    content: bytes,
    *,
    safety: CrawlSafetyPolicy = DEFAULT_CRAWL_SAFETY_POLICY,
) -> ExtractedPageLinks:
    parser = _HtmlLinkParser()
    parser.feed(content.decode("utf-8", errors="replace"))
    bounded = bound_outgoing_links((*parser.links, *parser.canonical_hints), safety=safety)
    links = tuple(link for link in bounded.links if link.relation is LinkRelation.ANCHOR)
    canonical_hints = tuple(
        link for link in bounded.links if link.relation is LinkRelation.CANONICAL_HINT
    )
    return ExtractedPageLinks(
        links=links,
        canonical_hints=canonical_hints,
        dropped_links=bounded.dropped_count,
    )


__all__ = [
    "DISCOVERY_POLICY_VERSION",
    "ExtractedPageLinks",
    "OfficialSiteDiscoveryPolicy",
    "PageCategory",
    "classify_page",
    "extract_html_links",
]
