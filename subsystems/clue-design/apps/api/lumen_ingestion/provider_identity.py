"""Shared checks of logo providers' brand metadata, never proof of logo pixels."""

from __future__ import annotations

import re
import unicodedata
from typing import Any
from urllib.parse import unquote, urlsplit


class ProviderIdentityError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def normalized_host(value: Any) -> str:
    """Keep subdomains; normalize only URL syntax, DNS case/root dot and www."""
    if not isinstance(value, str) or not value.strip():
        return ""
    text = value.strip()
    try:
        parsed = urlsplit(text if "://" in text or text.startswith("//") else f"//{text}")
        if parsed.username is not None or parsed.password is not None:
            return ""
        host = (parsed.hostname or "").rstrip(".").encode("idna").decode("ascii").lower()
    except (ValueError, UnicodeError):
        return ""
    if host.startswith("www."):
        host = host[4:]
    if (
        not host
        or len(host) > 253
        or any(
            len(part) > 63 or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", part)
            for part in host.split(".")
        )
    ):
        return ""
    return host


_UNSAFE_IDENTITY_TEXT = re.compile(
    r"://|//|\bwww\.|%[0-9a-f]{2}|\b(?:bearer|basic)\s+"
    r"|\b(?:authorization|token|secret|password|api[_ -]?key|access[_ -]?token)\s*[:=]"
    r"|\b(?:sk|pk)[_-][a-z0-9]",
    re.IGNORECASE,
)


def _safe_identity_text(value: Any, *, max_length: int = 256) -> str | None:
    """Retain display metadata, never URLs, credential-shaped text or controls."""
    if not isinstance(value, str) or len(value) > max_length:
        return None
    normalized = unicodedata.normalize("NFKC", value)
    inspected = unquote(normalized)
    if (
        len(normalized) > max_length
        or any(unicodedata.category(char).startswith("C") for char in inspected)
        or _UNSAFE_IDENTITY_TEXT.search(inspected)
    ):
        return None
    return " ".join(normalized.split()) or None


def _safe_provider_id(value: Any) -> str | None:
    # IDs are optional evidence; unsafe/malformed IDs do not invalidate a name
    # and domain that were independently verified.
    text = _safe_identity_text(value, max_length=128)
    return text if text and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", text) else None


_LEGAL_SUFFIXES = {
    "inc",
    "incorporated",
    "llc",
    "ltd",
    "limited",
    "corp",
    "corporation",
    "plc",
    "gmbh",
}


def _name_words(value: Any) -> tuple[str, ...]:
    if not isinstance(value, str):
        return ()
    words = re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", value).casefold())
    while words and words[-1] in _LEGAL_SUFFIXES:
        words.pop()
    # Parenthesized or prefixed initialisms may accompany the full name.
    if len(words) > 2 and words[-1] == "".join(word[0] for word in words[:-1]):
        words.pop()
    if len(words) > 2 and words[0] == "".join(word[0] for word in words[1:]):
        words.pop(0)
    return tuple(words)


def _is_acronym(short: tuple[str, ...], full: tuple[str, ...]) -> bool:
    return (
        len(short) == 1
        and len(short[0]) >= 2
        and len(full) >= 2
        and short[0] == "".join(word[0] for word in full)
    )


def validate_vendor_identity(
    payload: Any,
    *,
    requested_domain: str,
    company_name: str | None = None,
) -> dict[str, Any]:
    """Validate declared identity before logo downloads/candidate eligibility.

    No registrable-domain relaxation: a parent brand is not a requested product.
    Name ambiguities remain typed gaps; no provider metadata certifies the art.
    """
    requested_host = normalized_host(requested_domain)
    returned_host = normalized_host(payload.get("domain")) if isinstance(payload, dict) else ""
    if not requested_host or not returned_host:
        raise ProviderIdentityError(
            "identity_unverified",
            "provider identity requires usable requested and returned domains",
        )
    if requested_host != returned_host:
        raise ProviderIdentityError(
            "identity_mismatch",
            "provider domain does not match the requested exact host; "
            "parent and sub-brand domains are not interchangeable",
        )
    returned_name = _safe_identity_text(payload.get("name"))
    returned_words = _name_words(returned_name)
    if not returned_words:
        raise ProviderIdentityError(
            "identity_unverified", "provider returned no safe, meaningful brand name"
        )
    name_match = "not_requested"
    requested_name = None
    if company_name is not None:
        requested_name = _safe_identity_text(company_name)
        requested_words = _name_words(requested_name)
        if not requested_words:
            raise ProviderIdentityError(
                "identity_unverified", "requested company/product name is not safe and meaningful"
            )
        if "".join(requested_words) == "".join(returned_words):
            name_match = "normalized_exact"
        elif _is_acronym(requested_words, returned_words) or _is_acronym(
            returned_words, requested_words
        ):
            name_match = "acronym"
        elif returned_words[: len(requested_words)] == requested_words:
            raise ProviderIdentityError(
                "identity_unverified",
                "provider name adds an unverified qualifier to the requested name; "
                "exact host alone does not resolve that ambiguity",
            )
        else:
            raise ProviderIdentityError(
                "identity_mismatch",
                "provider name does not match the requested company/product name",
            )
    return {
        "requested_domain": requested_host,
        "requested_company_name": requested_name,
        "provider_domain": returned_host,
        "provider_name": returned_name,
        "provider_id": _safe_provider_id(payload.get("id")),
        "domain_match": "exact_host",
        "name_match": name_match,
    }
