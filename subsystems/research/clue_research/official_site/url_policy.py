"""Versioned, conservative URL identity for official-site crawling (C2).

The policy deliberately folds only equivalences that are safe before fetching.  It preserves the
exact discovered value alongside the derived fetch key, never treats canonical hints as identity,
and performs no network I/O.  DNS/response validation lives in :mod:`safety`.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from urllib.parse import SplitResult, urljoin, urlsplit, urlunsplit

from clue_research.official_site.contracts import PolicyOutcome

URL_POLICY_VERSION = "official-site-url-v1"

# This allowlist is part of URL_POLICY_VERSION.  Do not broaden it without a version bump and
# fixture review: an unfamiliar query parameter may select different content.
TRACKING_PARAMETER_NAMES = frozenset(
    {
        "dclid",
        "fbclid",
        "gclid",
        "gbraid",
        "mc_cid",
        "mc_eid",
        "msclkid",
        "twclid",
        "wbraid",
    }
)
TRACKING_PARAMETER_PREFIXES = ("utm_",)

_HEX = frozenset("0123456789abcdefABCDEF")
_UNRESERVED = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
_CONTROL_OR_SPACE = re.compile(r"[\x00-\x20\x7f]")
_DEFAULT_DENIED_HOST_PREFIXES = ("account.", "accounts.", "auth.", "login.", "signin.")
_DEFAULT_DENIED_PATH_PREFIXES = (
    "/account",
    "/admin",
    "/auth",
    "/login",
    "/logout",
    "/signin",
    "/sign-in",
)


@dataclass(frozen=True, slots=True)
class UrlPolicyConfig:
    """Inputs pinned by the crawl run plus V1's conservative fixed policy."""

    root_url: str
    allowed_registrable_domain: str
    allow_subdomains: bool = False
    max_url_chars: int = 4_096
    denied_host_prefixes: tuple[str, ...] = _DEFAULT_DENIED_HOST_PREFIXES
    denied_path_prefixes: tuple[str, ...] = _DEFAULT_DENIED_PATH_PREFIXES
    version: str = URL_POLICY_VERSION


@dataclass(frozen=True, slots=True)
class FetchKeyDecision:
    discovered_url: str
    resolved_url: str | None
    fetch_key: str | None
    fetch_key_hash: str | None
    normalized_host: str | None
    outcome: PolicyOutcome
    reason: str
    removed_tracking_parameters: tuple[str, ...] = ()
    stripped_fragment: str | None = None
    routing_fragment: str | None = None

    @property
    def admitted(self) -> bool:
        return self.outcome is PolicyOutcome.ADMITTED


def _refuse(
    discovered_url: str, reason: str, *, resolved_url: str | None = None
) -> FetchKeyDecision:
    return FetchKeyDecision(
        discovered_url=discovered_url,
        resolved_url=resolved_url,
        fetch_key=None,
        fetch_key_hash=None,
        normalized_host=None,
        outcome=PolicyOutcome.REFUSED,
        reason=reason,
    )


def _normalize_percent_encoding(value: str) -> str:
    """Decode only unreserved octets and canonicalize all retained escape hex to uppercase."""

    output: list[str] = []
    index = 0
    while index < len(value):
        character = value[index]
        if character != "%":
            output.append(character)
            index += 1
            continue
        if index + 2 >= len(value) or value[index + 1] not in _HEX or value[index + 2] not in _HEX:
            raise ValueError("malformed_percent_encoding")
        encoded = value[index + 1 : index + 3].upper()
        decoded = chr(int(encoded, 16))
        output.append(decoded if decoded in _UNRESERVED else f"%{encoded}")
        index += 3
    return "".join(output)


def _normalize_host(host: str) -> str:
    candidate = host.rstrip(".").lower()
    if not candidate:
        raise ValueError("missing_host")
    try:
        return candidate.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError("invalid_idna_host") from exc


def _netloc(parts: SplitResult, host: str) -> str:
    try:
        port = parts.port
    except ValueError as exc:
        raise ValueError("invalid_port") from exc
    if port is not None and not 1 <= port <= 65_535:
        raise ValueError("invalid_port")
    rendered_host = f"[{host}]" if ":" in host else host
    if port is None or (parts.scheme.lower(), port) in {("http", 80), ("https", 443)}:
        return rendered_host
    return f"{rendered_host}:{port}"


def _tracking_name(query_component: str) -> str:
    raw_name = query_component.split("=", 1)[0]
    try:
        return _normalize_percent_encoding(raw_name).lower()
    except ValueError:
        # The complete query is rejected later.  This keeps classification side-effect free.
        return raw_name.lower()


def _normalize_query(query: str) -> tuple[str, tuple[str, ...]]:
    if not query:
        return "", ()
    retained: list[str] = []
    removed: list[str] = []
    for component in query.split("&"):
        name = _tracking_name(component)
        if name in TRACKING_PARAMETER_NAMES or name.startswith(TRACKING_PARAMETER_PREFIXES):
            removed.append(name)
            continue
        retained.append(_normalize_percent_encoding(component))
    return "&".join(retained), tuple(removed)


def _routing_fragment(fragment: str) -> bool:
    return fragment.startswith("/") or fragment.startswith("!/")


class ConservativeUrlPolicy:
    """Derive one conservative within-run fetch identity from a discovered reference."""

    def __init__(self, config: UrlPolicyConfig) -> None:
        if config.version != URL_POLICY_VERSION:
            raise ValueError(f"unsupported URL policy version: {config.version}")
        if config.max_url_chars < 1:
            raise ValueError("max_url_chars must be positive")
        self.config = config
        root = self._split_absolute(config.root_url)
        self.root_host = _normalize_host(root.hostname or "")
        self.allowed_registrable_domain = _normalize_host(config.allowed_registrable_domain)
        if not self._host_within_registrable_domain(self.root_host):
            raise ValueError("root host is outside allowed registrable domain")

    def _split_absolute(self, value: str) -> SplitResult:
        if _CONTROL_OR_SPACE.search(value):
            raise ValueError("control_or_space_in_url")
        if "\\" in value:
            # WHATWG clients commonly reinterpret backslashes as path/authority separators even
            # though RFC URL parsers do not. Refusing the ambiguous spelling prevents the policy
            # and provider from resolving different network targets.
            raise ValueError("backslash_in_url")
        if any(character.isspace() for character in value):
            raise ValueError("unicode_whitespace_in_url")
        parts = urlsplit(value)
        if parts.scheme.lower() not in {"http", "https"}:
            raise ValueError("unsupported_scheme")
        if parts.username is not None or parts.password is not None:
            raise ValueError("credential_bearing_url")
        if parts.hostname is None:
            raise ValueError("missing_host")
        return parts

    def _host_within_registrable_domain(self, host: str) -> bool:
        return host == self.allowed_registrable_domain or host.endswith(
            f".{self.allowed_registrable_domain}"
        )

    def _host_allowed(self, host: str) -> tuple[bool, str]:
        if not self._host_within_registrable_domain(host):
            return False, "external_domain"
        if host == self.root_host:
            return True, "same_host"
        if not self.config.allow_subdomains:
            return False, "subdomain_not_allowed"
        if any(host.startswith(prefix) for prefix in self.config.denied_host_prefixes):
            return False, "denied_auth_host"
        return True, "allowed_subdomain"

    def decide(self, discovered_url: str, *, base_url: str | None = None) -> FetchKeyDecision:
        if not discovered_url or len(discovered_url) > self.config.max_url_chars:
            return _refuse(discovered_url, "empty_or_oversized_url")
        if _CONTROL_OR_SPACE.search(discovered_url):
            return _refuse(discovered_url, "control_or_space_in_url")
        if "\\" in discovered_url:
            return _refuse(discovered_url, "backslash_in_url")
        if any(character.isspace() for character in discovered_url):
            return _refuse(discovered_url, "unicode_whitespace_in_url")
        try:
            resolved = urljoin(base_url or self.config.root_url, discovered_url)
            if len(resolved) > self.config.max_url_chars:
                return _refuse(discovered_url, "oversized_resolved_url")
            parts = self._split_absolute(resolved)
            scheme = parts.scheme.lower()
            host = _normalize_host(parts.hostname or "")
            netloc = _netloc(parts, host)
            path = _normalize_percent_encoding(parts.path or "/")
            query, removed = _normalize_query(parts.query)
        except ValueError as exc:
            return _refuse(discovered_url, str(exc), resolved_url=locals().get("resolved"))

        allowed, host_reason = self._host_allowed(host)
        if not allowed:
            return _refuse(discovered_url, host_reason, resolved_url=resolved)
        folded_path = path.lower()
        if any(
            folded_path == prefix or folded_path.startswith(f"{prefix}/")
            for prefix in self.config.denied_path_prefixes
        ):
            return _refuse(discovered_url, "denied_auth_path", resolved_url=resolved)

        routing_fragment = parts.fragment if _routing_fragment(parts.fragment) else None
        stripped_fragment = parts.fragment if parts.fragment and routing_fragment is None else None
        fetch_key = urlunsplit((scheme, netloc, path, query, routing_fragment or ""))
        return FetchKeyDecision(
            discovered_url=discovered_url,
            resolved_url=resolved,
            fetch_key=fetch_key,
            fetch_key_hash=hashlib.sha256(fetch_key.encode()).hexdigest(),
            normalized_host=host,
            outcome=PolicyOutcome.ADMITTED,
            reason=(
                "admitted_tracking_removed"
                if removed
                else "admitted_fragment_stripped"
                if stripped_fragment
                else "admitted"
            ),
            removed_tracking_parameters=removed,
            stripped_fragment=stripped_fragment,
            routing_fragment=routing_fragment,
        )


__all__ = [
    "ConservativeUrlPolicy",
    "FetchKeyDecision",
    "TRACKING_PARAMETER_NAMES",
    "TRACKING_PARAMETER_PREFIXES",
    "URL_POLICY_VERSION",
    "UrlPolicyConfig",
]
