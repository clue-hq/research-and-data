"""Shared URL-host normalization (M9.4 DRY consolidation).

The one host fold every seam that compares URLs by origin shares. Three copies previously
re-implemented it — the M9.4 identity-binding ``normalize_url`` (verification), the M9.2
corroboration independence ``_host`` (verification), and the M4.5/M11 resolver target-lock
``_registrable_host``/``registrable_host`` (firecrawl / grounded) — with subtly divergent
scheme-less fallbacks (the resolvers' single ``'//' in url`` heuristic mis-parsed
``acme.com/a//b`` as path-only and dropped the host). Consolidated here so the fold cannot
drift again; dependency-free (stdlib only), per the ``core`` seam contract.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

__all__ = ["canonical_workspace_name", "normalize_host"]


def normalize_host(url: str) -> str:
    """Fold a URL or bare domain to its comparison host: lower-cased, leading ``www.`` stripped.

    Uses :meth:`urllib.parse.SplitResult.hostname`, which correctly strips userinfo, the port,
    and IPv6 brackets (a manual ``rsplit(':')`` would corrupt a bracketed IPv6 authority). A
    scheme-less but real authority (``"acme.com/x"`` — the input is an unvalidated string) is
    handled by a two-pass parse (``urlsplit(url).hostname``, else ``urlsplit('//' + url)
    .hostname``) — the single ``'//' in url`` heuristic would mis-parse ``acme.com/a//b`` (it
    contains ``//`` yet has no scheme) as path-only and drop the host. Returns ``""`` when the
    input carries no host (callers needing ``None`` write ``normalize_host(url) or None``).
    """
    raw = url.strip()
    if not raw:
        return ""
    host = urlsplit(raw).hostname or urlsplit("//" + raw).hostname or ""
    return host.lower().removeprefix("www.")


_MULTI_LABEL_SUFFIXES: frozenset[str] = frozenset(
    {
        "co.uk",
        "org.uk",
        "ac.uk",
        "gov.uk",
        "com.au",
        "net.au",
        "org.au",
        "co.nz",
        "co.jp",
        "co.in",
        "com.br",
        "com.mx",
        "co.za",
        "myshopify.com",
        "webflow.io",
        "github.io",
    }
)


def canonical_workspace_name(website: str | None) -> str | None:
    """The display name a workspace takes from its website when no company name was typed.

    Host only (a scheme is optional; userinfo, port and path are dropped — the shared
    :func:`normalize_host` fold), lower-cased, minus a leading ``www.``; the registrable label —
    the one before the public suffix, with the common multi-label suffixes treated as suffixes —
    split on ``-``/``_`` and capitalised. An IP literal, a dotless host or blank input names
    nothing (``None``): a name is never invented.
    """

    if not website or not website.strip():
        return None
    host = normalize_host(website)
    if not host or "." not in host:
        return None
    labels = host.split(".")
    if all(label.isdigit() for label in labels):
        return None
    suffix_len = 2 if ".".join(labels[-2:]) in _MULTI_LABEL_SUFFIXES and len(labels) > 2 else 1
    if len(labels) <= suffix_len:
        return None
    stem = labels[-(suffix_len + 1)]
    parts = [part for part in re.split(r"[-_]", stem) if part]
    return " ".join(part.capitalize() for part in parts) or None
