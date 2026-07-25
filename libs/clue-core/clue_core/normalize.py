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

from urllib.parse import urlsplit

__all__ = ["normalize_host"]


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
