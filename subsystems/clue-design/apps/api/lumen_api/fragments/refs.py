"""What a fragment is allowed to point AT (clone-fidelity F1.2, ruling D-F4).

Every byte a cloned section displays must already be in our custody. F0 rehosts a captured
site's images and fonts into the design blob namespace; this module is the gate that says so —
one predicate, shared by the HTML sanitizer and the CSS scoper, so the two cannot disagree
about what "resolved" means.

**Fail-closed, and loud.** A reference this module cannot resolve REFUSES the whole fragment
(:class:`FragmentRefused`, naming the reference) instead of being silently dropped. A silently
dropped reference produces an artifact that looks complete and renders a hole, which is the
failure mode a clone can least afford: nobody ever finds out why the hero has no background.
Refusing at creation is recoverable — the producer rehosts the asset and mints the fragment
again — and creation is the only moment at which anything about a fragment is checkable, because
the artifact is immutable from then on.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from .reference_identity import ReferenceConflict, lookup_reference_key

#: The engine's fragment-id grammar (``lumen_web::doc::fragment_id_is_valid``): the registry
#: mints these and the document node refuses anything else.
FRAGMENT_ID_RE = re.compile(r"frag_[0-9a-f]{16}")

SHA256_RE = re.compile(r"[0-9a-f]{64}")

#: Where a rehosted design blob is served from. The digest route (``GET /asset-store/{digest}``)
#: is the ONE public byte surface, and it is what web export/publish already emit for images and
#: font faces — so a fragment that names its assets this way needs no special serving path.
ASSET_URL_PREFIX = "/asset-store/"

#: URL schemes a link may carry. Everything else — ``javascript:``, ``data:``, ``vbscript:``,
#: ``file:`` — loses the attribute. A scheme-less value (``/pricing``, ``#features``,
#: ``//cdn.example/x``) is a relative or protocol-relative link and is left alone.
ALLOWED_LINK_SCHEMES = frozenset({"http", "https", "mailto", "tel", "sms"})

_SCHEME_RE = re.compile(r"\A([a-zA-Z][a-zA-Z0-9+.\-]*):")

#: Characters browsers ignore inside a URL scheme, and which an attacker therefore uses to
#: smuggle one past a naive prefix test (``java\tscript:``). Stripped before the scheme is read.
_SCHEME_NOISE = "\t\n\r\f\v\x00 "


class FragmentRefused(ValueError):
    """Fragment creation was refused. There is no partial artifact.

    ``code`` is a stable machine label (``fragment.*``); ``reference`` names the offending
    URL/selector/key when the refusal is about one, so a producer's diagnostic can say WHICH
    thing to fix rather than that something, somewhere, was wrong.
    """

    def __init__(self, code: str, message: str, *, reference: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.reference = reference


def fragment_wrapper_class(fragment_id: str) -> str:
    """The ONE class name a fragment's markup and CSS agree on: ``lumen-frag-<16 hex>``.

    The plan writes it ``.lumen-frag-<id>``; the ``<id>`` is the digest half of the fragment id,
    not the whole ``frag_``-prefixed string, because ``.lumen-frag-frag_…`` says "frag" twice and
    the prefix carries no information a class name needs. Exported as a function rather than a
    format string so the F1.3 render arm and this scoper cannot drift into two spellings — there
    is exactly one place that decides.
    """
    if not FRAGMENT_ID_RE.fullmatch(fragment_id):
        raise FragmentRefused(
            "fragment.id_invalid",
            f"fragment id must be frag_<16 lowercase hex>: {fragment_id!r}",
            reference=fragment_id,
        )
    return f"lumen-frag-{fragment_id[len('frag_'):]}"


def asset_url(digest: str) -> str:
    """The in-artifact reference for one rehosted blob."""
    return f"{ASSET_URL_PREFIX}{digest}"


def asset_reference_url(raw: str, digest: str) -> str:
    """Rewrite the fetched resource while retaining its authored in-resource selector/time."""
    _resource, marker, suffix = raw.strip().partition("#")
    return asset_url(digest) + (marker + suffix if marker else "")


def asset_url_digest(value: str) -> str | None:
    """The digest an ``/asset-store/{sha}`` reference names, or ``None`` if it is not one.

    Recognising an already-rewritten reference is what makes the sanitizer idempotent: a producer
    that hands over markup it already rewrote (or re-sanitizes a stored artifact) does not need a
    rehost map to say the same thing twice.
    """
    text = value.strip()
    if not text.startswith(ASSET_URL_PREFIX):
        return None
    tail = text[len(ASSET_URL_PREFIX) :].split("#", 1)[0].split("?", 1)[0]
    return tail if SHA256_RE.fullmatch(tail) else None


def link_scheme_allowed(value: str) -> bool:
    """Whether a link target may keep its attribute.

    The value is stripped of the whitespace and NUL bytes browsers ignore inside a scheme first,
    so ``java\\tscript:alert(1)`` is read as the ``javascript:`` it will execute as rather than as
    the scheme-less relative URL it superficially resembles.
    """
    cleaned = value.translate({ord(char): None for char in _SCHEME_NOISE})
    match = _SCHEME_RE.match(cleaned)
    if match is None:
        return True
    return match.group(1).lower() in ALLOWED_LINK_SCHEMES


def resolve_asset_reference(raw: str, rehosted: Mapping[str, str]) -> str | None:
    """The digest a byte-loading reference resolves to, or ``None`` when it loads no bytes.

    ``None`` means "leave this alone": an empty value, or a same-document ``#fragment`` (an SVG
    ``<use href="#icon">` points inside the fragment's own markup and fetches nothing).

    Anything else must be in our custody — already written as ``/asset-store/{digest}``, or
    present in ``rehosted`` under the source spelling or an unambiguous fragment-only alias.
    Query strings and other spelling differences remain exact. Aliases naming different bytes
    refuse, including when one alias exactly matches. Non-web schemes require an exact entry.
    """
    text = raw.strip()
    if not text or text.startswith("#"):
        return None
    already = asset_url_digest(text)
    if already is not None:
        return already
    try:
        key = lookup_reference_key(text, rehosted)
        if key is None and text != raw:
            key = lookup_reference_key(raw, rehosted)
    except ReferenceConflict as conflict:
        raise FragmentRefused(
            "fragment.rehost_reference_conflict",
            f"fragment reference has conflicting rehosted content: {text}",
            reference=text,
        ) from conflict
    digest = rehosted[key] if key is not None else None
    if digest is None:
        raise FragmentRefused(
            "fragment.unrehosted_reference",
            f"fragment references bytes that were never rehosted: {text}",
            reference=text,
        )
    if not SHA256_RE.fullmatch(digest):
        raise FragmentRefused(
            "fragment.rehost_digest_invalid",
            f"rehosted digest for {text} is not a sha256: {digest!r}",
            reference=text,
        )
    return digest
