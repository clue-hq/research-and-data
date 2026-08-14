"""Coordinator-owned network and response safety policy for official-site crawling (C2)."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

from clue_research.official_site.contracts import (
    CrawlEligibility,
    LinkObservation,
    PolicyOutcome,
    RedirectHop,
    UrlObservation,
)
from clue_research.official_site.url_policy import ConservativeUrlPolicy

SAFETY_POLICY_VERSION = "official-site-safety-v1"
DEFAULT_ACCEPTED_MIME_TYPES = frozenset({"application/xhtml+xml", "text/html", "text/plain"})


@dataclass(frozen=True, slots=True)
class CrawlSafetyPolicy:
    version: str = SAFETY_POLICY_VERSION
    dns_timeout_seconds: float = 2.0
    max_dns_answers: int = 16
    max_redirects: int = 5
    max_response_bytes: int = 5_000_000
    max_outgoing_links: int = 200
    max_link_text_chars: int = 500
    accepted_mime_types: frozenset[str] = DEFAULT_ACCEPTED_MIME_TYPES
    allow_pdf: bool = False

    def __post_init__(self) -> None:
        if self.version != SAFETY_POLICY_VERSION:
            raise ValueError(f"unsupported safety policy version: {self.version}")
        if self.dns_timeout_seconds <= 0:
            raise ValueError("dns_timeout_seconds must be positive")
        if (
            min(
                self.max_dns_answers,
                self.max_response_bytes,
                self.max_outgoing_links,
                self.max_link_text_chars,
            )
            < 1
        ):
            raise ValueError("safety ceilings must be positive")
        if self.max_redirects < 0:
            raise ValueError("max_redirects cannot be negative")
        if self.max_link_text_chars > 500:
            raise ValueError("max_link_text_chars cannot exceed the frozen observation bound")

    @property
    def effective_mime_types(self) -> frozenset[str]:
        if self.allow_pdf:
            return self.accepted_mime_types | {"application/pdf"}
        return self.accepted_mime_types


DEFAULT_CRAWL_SAFETY_POLICY = CrawlSafetyPolicy()


@dataclass(frozen=True, slots=True)
class SafetyDecision:
    allowed: bool
    reason: str
    checked_addresses: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BoundedLinks:
    links: tuple[LinkObservation, ...]
    dropped_count: int


class AddressResolver(Protocol):
    async def resolve(
        self, host: str, *, max_answers: int, timeout_seconds: float
    ) -> tuple[str, ...]: ...


class SystemAddressResolver:
    """Bounded system DNS lookup used only for coordinator preflight.

    A local provider transport must additionally pin/connect to one of these validated addresses;
    preflight alone is not treated as DNS-rebinding protection.
    """

    async def resolve(
        self, host: str, *, max_answers: int, timeout_seconds: float
    ) -> tuple[str, ...]:
        loop = asyncio.get_running_loop()

        rows = await asyncio.wait_for(
            loop.getaddrinfo(
                host,
                None,
                family=socket.AF_UNSPEC,
                type=socket.SOCK_STREAM,
            ),
            timeout=timeout_seconds,
        )
        addresses: list[str] = []
        for row in rows:
            address = str(row[4][0])
            if address not in addresses:
                addresses.append(address)
            if len(addresses) > max_answers:
                raise ValueError("dns_answer_ceiling_exceeded")
        if not addresses:
            raise ValueError("dns_no_answers")
        return tuple(addresses)


class StaticAddressResolver:
    """Deterministic resolver for policy tests and provider conformance fixtures."""

    def __init__(self, answers: dict[str, tuple[str, ...] | Exception]) -> None:
        self._answers = {host.lower(): value for host, value in answers.items()}

    async def resolve(
        self, host: str, *, max_answers: int, timeout_seconds: float
    ) -> tuple[str, ...]:
        del timeout_seconds
        answer = self._answers.get(host.lower(), ValueError("dns_no_answers"))
        if isinstance(answer, Exception):
            raise answer
        if len(answer) > max_answers:
            raise ValueError("dns_answer_ceiling_exceeded")
        return answer


def _address_is_public(address: str) -> bool:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(parsed, ipaddress.IPv6Address) and parsed.ipv4_mapped is not None:
        parsed = parsed.ipv4_mapped
    # Python's ``is_global`` includes multicast on some versions, so every prohibited class is
    # stated explicitly as well.  This also rejects documentation, carrier-grade NAT, and the
    # IPv4 cloud-metadata range.
    return bool(
        parsed.is_global
        and not parsed.is_private
        and not parsed.is_loopback
        and not parsed.is_link_local
        and not parsed.is_multicast
        and not parsed.is_reserved
        and not parsed.is_unspecified
    )


async def preflight_target(
    url: str,
    *,
    url_policy: ConservativeUrlPolicy,
    resolver: AddressResolver,
    safety: CrawlSafetyPolicy,
    base_url: str | None = None,
) -> SafetyDecision:
    decision = url_policy.decide(url, base_url=base_url)
    if not decision.admitted or decision.fetch_key is None or decision.normalized_host is None:
        return SafetyDecision(False, decision.reason)
    host = decision.normalized_host
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    addresses: tuple[str, ...]
    if literal is not None:
        addresses = (str(literal),)
    else:
        try:
            addresses = await resolver.resolve(
                host,
                max_answers=safety.max_dns_answers,
                timeout_seconds=safety.dns_timeout_seconds,
            )
        except (TimeoutError, OSError, ValueError) as exc:
            return SafetyDecision(False, str(exc) or "dns_resolution_failed")
    if not addresses:
        return SafetyDecision(False, "dns_no_answers")
    for address in addresses:
        if not _address_is_public(address):
            return SafetyDecision(False, "non_public_network_target", addresses)
    return SafetyDecision(True, "public_network_target", addresses)


async def validate_redirects(
    *,
    requested_url: str,
    final_url: str,
    redirect_chain: tuple[RedirectHop, ...],
    url_policy: ConservativeUrlPolicy,
    resolver: AddressResolver,
    safety: CrawlSafetyPolicy,
) -> SafetyDecision:
    if len(redirect_chain) > safety.max_redirects:
        return SafetyDecision(False, "redirect_ceiling_exceeded")
    current = requested_url
    seen: set[str] = set()
    all_addresses: list[str] = []
    for hop in redirect_chain:
        if hop.from_url != current:
            return SafetyDecision(False, "redirect_chain_discontinuous")
        if hop.from_url in seen or hop.to_url in seen:
            return SafetyDecision(False, "redirect_loop")
        seen.add(hop.from_url)
        decision = await preflight_target(
            hop.to_url,
            url_policy=url_policy,
            resolver=resolver,
            safety=safety,
        )
        if not decision.allowed:
            return SafetyDecision(False, f"redirect_{decision.reason}", decision.checked_addresses)
        all_addresses.extend(decision.checked_addresses)
        current = hop.to_url
    if current != final_url:
        if redirect_chain:
            return SafetyDecision(False, "redirect_final_url_mismatch")
        # Providers may normalize the terminal spelling even when they report no intermediate hop.
        requested = url_policy.decide(requested_url)
        final = url_policy.decide(final_url)
        if not requested.admitted or not final.admitted or requested.fetch_key != final.fetch_key:
            return SafetyDecision(False, "unreported_redirect_or_external_final")
    final_decision = await preflight_target(
        final_url,
        url_policy=url_policy,
        resolver=resolver,
        safety=safety,
    )
    if not final_decision.allowed:
        return SafetyDecision(
            False,
            f"final_{final_decision.reason}",
            final_decision.checked_addresses,
        )
    all_addresses.extend(final_decision.checked_addresses)
    return SafetyDecision(True, "redirects_valid", tuple(dict.fromkeys(all_addresses)))


def validate_response_content(
    *, media_type: str | None, content: bytes | None, safety: CrawlSafetyPolicy
) -> SafetyDecision:
    if media_type is None:
        return SafetyDecision(False, "missing_media_type")
    normalized = media_type.split(";", 1)[0].strip().lower()
    if normalized not in safety.effective_mime_types:
        return SafetyDecision(False, "unsupported_media_type")
    if content is None:
        return SafetyDecision(False, "missing_response_body")
    if len(content) > safety.max_response_bytes:
        return SafetyDecision(False, "decompressed_response_too_large")
    return SafetyDecision(True, "content_valid")


def apply_safety_decision(observation: UrlObservation, decision: SafetyDecision) -> UrlObservation:
    """Turn a preflight refusal into a durable URL observation without losing provenance."""

    if decision.allowed:
        return observation
    return observation.model_copy(
        update={
            "fetch_key": None,
            "fetch_key_hash": None,
            "eligibility": CrawlEligibility.REFUSED,
            "policy_outcome": PolicyOutcome.REFUSED,
            "policy_reason": decision.reason,
        }
    )


def bound_outgoing_links(
    links: Iterable[LinkObservation], *, safety: CrawlSafetyPolicy
) -> BoundedLinks:
    retained: list[LinkObservation] = []
    dropped = 0
    for link in links:
        if len(retained) >= safety.max_outgoing_links:
            dropped += 1
            continue
        text = link.link_text
        if text is not None:
            text = text[: safety.max_link_text_chars]
        retained.append(
            LinkObservation(
                discovered_url=link.discovered_url,
                relation=link.relation,
                link_text=text,
            )
        )
    return BoundedLinks(tuple(retained), dropped)


def make_pinned_resolver(
    resolver: AddressResolver,
    connector: Callable[[str, tuple[str, ...]], Awaitable[object]],
    *,
    safety: CrawlSafetyPolicy,
) -> Callable[[str], Awaitable[object]]:
    """Build the local-fetcher rebinding seam: connect only to prevalidated DNS answers.

    C3's Scrapling transport supplies ``connector``.  Keeping it injected here makes the security
    requirement executable without coupling C2 to any HTTP or provider package.
    """

    async def connect(url: str) -> object:
        host = urlsplit(url).hostname
        if host is None:
            raise ValueError("missing_host")
        addresses = await resolver.resolve(
            host,
            max_answers=safety.max_dns_answers,
            timeout_seconds=safety.dns_timeout_seconds,
        )
        if not addresses or any(not _address_is_public(address) for address in addresses):
            raise ValueError("non_public_network_target")
        return await connector(url, addresses)

    return connect


__all__ = [
    "AddressResolver",
    "BoundedLinks",
    "CrawlSafetyPolicy",
    "DEFAULT_CRAWL_SAFETY_POLICY",
    "DEFAULT_ACCEPTED_MIME_TYPES",
    "SAFETY_POLICY_VERSION",
    "SafetyDecision",
    "StaticAddressResolver",
    "SystemAddressResolver",
    "apply_safety_decision",
    "bound_outgoing_links",
    "make_pinned_resolver",
    "preflight_target",
    "validate_redirects",
    "validate_response_content",
]
