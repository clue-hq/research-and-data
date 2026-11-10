"""Open the short links in post text (X's ``t.co``, LinkedIn's ``lnkd.in``) to their address.

Both are free and need no sign-in. Asked with a browser user agent, ``t.co`` answers with a page
whose refresh tag holds the address, and ``lnkd.in`` with a "you are leaving LinkedIn" page whose
outbound link is the address (checked 2026-11-10). A link that cannot be opened is left out of the
result, so the post keeps only its short link and nothing is guessed.
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

from clue_spend.calls import CallSpec, ProviderCaller
from clue_spend.errors import SpendError
from clue_spend.transport import BROWSER_USER_AGENT, HttpRequest

SHORT_LINK = re.compile(r"https?://(?:t\.co|lnkd\.in)/[A-Za-z0-9_-]+")
#: Links opened at once; each is a small page, about 0.4 s.
WORKERS = 8
_TCO = re.compile(r'(?i)<meta[^>]+http-equiv="refresh"[^>]+content="\d+;\s*URL=([^"]+)"')
_TITLE = re.compile(r"(?is)<title>\s*(https?://[^<\s]+)\s*</title>")
_LNKD_ANCHOR = re.compile(r"(?is)<a\b[^>]*external_url_click[^>]*>")
_HREF = re.compile(r'(?i)\bhref="([^"]+)"')


def short_links(text: str | None) -> list[str]:
    return SHORT_LINK.findall(text or "")


def _address(host: str, page: str) -> str | None:
    if host == "t.co":
        found = _TCO.search(page) or _TITLE.search(page)
    else:
        anchor = _LNKD_ANCHOR.search(page)
        found = _HREF.search(anchor.group(0)) if anchor else None
    if found is None:
        return None
    address = html.unescape(found.group(1)).strip()
    return address if address.startswith(("http://", "https://")) else None


def _open(caller: ProviderCaller, link: str) -> str | None:
    host = urlsplit(link).hostname or ""
    spec = CallSpec(
        provider="short_link",
        operation=host,
        label=f"short_link.{host}",
        request=HttpRequest("GET", link, headers={"User-Agent": BROWSER_USER_AGENT}, timeout_s=20),
        max_attempts=2,
    )
    try:
        result = caller.call(spec)
    except SpendError:
        return None
    if result.response.status != 200:
        return None
    return _address(host, result.text())


def expand(
    caller: ProviderCaller, links: Iterable[str], *, workers: int | None = None
) -> dict[str, str]:
    """Each short link that opened, mapped to the address it leads to."""
    unique = sorted(set(links))
    if not unique:
        return {}
    pool_size = max(1, min(workers or WORKERS, len(unique)))
    with ThreadPoolExecutor(max_workers=pool_size) as pool:
        opened = list(pool.map(lambda link: (link, _open(caller, link)), unique))
    return {link: address for link, address in opened if address}
