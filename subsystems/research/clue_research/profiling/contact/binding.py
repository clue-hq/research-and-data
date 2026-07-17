"""Extraction-time identity-binding classification — the M8.4 make-or-break (mode M4).

Getting a personal fact *wrong* in 1:1 outreach is worse than omitting it (staged-flow §6), so
every ``contact.facet.*`` claim is tagged ``identity_binding ∈ {strong, weak}`` — **strong** = the
evidence is on the person's *verified* handle, or co-occurs with multiple strong identifiers (name
+ employer / geo); **weak** = a name-only match (the same-name trap). A ``WEAK`` claim is still
written (with the tag) but never promoted (``core.can_be_promoted``); M9's gate decides promotion.

The binding is **required at claim construction and immutable thereafter** (the facet field-class
validator + the 0004 trigger), and M9.4's ``classify_binding`` runs *post-hoc* on a stored claim and
is unimportable here (worker independence). So M8.4 needs its own tagger that produces the binding
*before* the claim exists. This module ships a thin :class:`DefaultBindingClassifier` behind a
:class:`BindingClassifier` protocol; the authoritative ``verification.classify_binding`` is injected
at the ``api`` composition root (the deferred-to-integration pattern, CLAUDE.md M9.4×M8.4). The two
must agree on the same-name / verified-handle fixtures.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict

from clue_core import ContactEntity, IdentityBinding


class BindingInput(BaseModel):
    """Everything the binding classifier needs *before* the claim is constructed (no ``Claim`` yet —
    the facet claim cannot exist without its binding)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contact: ContactEntity  # the resolved target person
    evidence_span: str | None = None  # the text the value was extracted from
    source_url: str | None = None  # where the evidence was found
    source_key: str = ""  # the producing source (for the prior)
    manifest_prior: IdentityBinding | None = (
        None  # the source-level binding prior (e.g. crm=STRONG)
    )
    account_name: str | None = None  # the contact's employer (a co-occurring strong identifier)
    account_aliases: tuple[str, ...] = ()


@runtime_checkable
class BindingClassifier(Protocol):
    """The extraction-time binding seam (M8.4 implements a default; the ``api`` root may inject the
    authoritative ``verification.classify_binding`` behind it)."""

    def classify(self, inp: BindingInput) -> IdentityBinding: ...


def _normalize_url(url: str | None) -> str:
    """Fold a URL for prefix comparison: lowercased, scheme-stripped, trailing-slash-stripped.

    (A small local fold — the shared ``normalize_host`` consolidation across M9.2/M9.4/firecrawl
    is a tracked DRY follow-up; this one compares the full handle URL *path*, not just the host,
    because a bare host like ``linkedin.com`` is shared by every profile.)"""
    if not url:
        return ""
    parts = urlsplit(url if "//" in url else f"//{url}")
    host = (parts.netloc or "").lower().removeprefix("www.")
    path = parts.path.rstrip("/").lower()
    return f"{host}{path}"


def _on_verified_handle(contact: ContactEntity, source_url: str | None) -> bool:
    """Whether the evidence sits on the contact's own verified profile/handle (a per-person URL).

    Compared on the full path — ``linkedin.com/in/jane`` is unique to Jane, whereas the bare
    ``linkedin.com`` host (or a shared company email domain) is not a per-person signal."""
    if not source_url or not contact.linkedin_url:
        return False
    handle = _normalize_url(contact.linkedin_url)
    return bool(handle) and _normalize_url(source_url).startswith(handle)


def _identifier_tokens(
    contact: ContactEntity, account_name: str | None, aliases: tuple[str, ...]
) -> list[str]:
    """The strong corroborating identifiers (besides the bare name) that bind evidence to *this*
    person: employer name(s) and a geo token."""
    tokens: list[str] = []
    if account_name and account_name.strip():
        tokens.append(account_name.strip().lower())
    tokens.extend(a.strip().lower() for a in aliases if a.strip())
    geo = contact.geo or {}
    for key in ("city", "region", "country", "country_code"):
        value = geo.get(key)
        if isinstance(value, str) and value.strip():
            tokens.append(value.strip().lower())
    return [t for t in tokens if t]


def _co_occurs_strong(inp: BindingInput) -> bool:
    """Whether the evidence span carries the contact's name AND ≥1 other strong identifier
    (employer / geo) — multiple identifiers co-occurring bind the fact to this person, not a
    same-name stranger."""
    span = (inp.evidence_span or "").lower()
    name = (inp.contact.full_name or "").strip().lower()
    if not span or not name or name not in span:
        return False
    return any(
        token in span
        for token in _identifier_tokens(inp.contact, inp.account_name, inp.account_aliases)
    )


class DefaultBindingClassifier:
    """The thin, spec-mandated default binding classifier (M8.4).

    ``STRONG`` iff the source prior is already strong, OR the evidence is on the verified handle, OR
    the name co-occurs with ≥1 other strong identifier; otherwise ``WEAK`` (name-only / unverified —
    the same-name trap). Deliberately minimal so it is easy to keep in agreement with the injected
    authoritative classifier on the golden fixtures."""

    def classify(self, inp: BindingInput) -> IdentityBinding:
        if inp.manifest_prior is IdentityBinding.STRONG:
            return IdentityBinding.STRONG
        if _on_verified_handle(inp.contact, inp.source_url):
            return IdentityBinding.STRONG
        if _co_occurs_strong(inp):
            return IdentityBinding.STRONG
        return IdentityBinding.WEAK


DEFAULT_BINDING_CLASSIFIER = DefaultBindingClassifier()
