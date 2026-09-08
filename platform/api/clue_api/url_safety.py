"""The one URL-safety predicate every read surface shares.

It lived in :mod:`clue_api.research_view_governance` while C7 was its only caller. The ARV2 read
surface needs the same test (a LinkedIn chip, an account social, an evidence link), and importing
the C7 research-view module for one pure string check would tie the ARV2 path to a surface it does
not read. So the function moved *down* to a module with no dependencies at all, and C7 imports it
from here — one definition, no cycle, and neither surface owns the other.
"""

from __future__ import annotations

from urllib.parse import urlsplit

__all__ = ["safe_public_url"]


def safe_public_url(value: str | None) -> bool:
    """Whether ``value`` is a plain, public ``http(s)`` URL a browser may be pointed at.

    Credentials in the authority make a URL unsafe to render or follow, and a non-``http(s)``
    scheme (``javascript:``, ``file:``, ``data:``) is never a source link — both are refused rather
    than sanitised, because a rewritten URL is no longer the one the claim cited.
    """

    if value is None:
        return False
    parsed = urlsplit(value)
    return (
        parsed.scheme.lower() in {"http", "https"}
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
    )
