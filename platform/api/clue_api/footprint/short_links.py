"""Open the short links in post text (X's ``t.co``, LinkedIn's ``lnkd.in``) to their address.

Both are free and need no sign-in, so they are not provider calls: no spend row, no raw record, no
evidence entry and no trace per link (the r44a trial had 1,053 "gap" evidence entries from them).
Checked live 2026-11-11: asked with a browser user agent, ``t.co`` answers with a page whose
refresh tag holds the address; ``lnkd.in`` answers with a "you are leaving LinkedIn" page whose
outbound link is the address, or, for a LinkedIn address, with a 301 whose ``location`` is it.

The address is read, never fetched (review I8): the transport is the public one that refuses
private and internal addresses and caps the body, with redirects off. A link that cannot be opened
for any reason is left as written (the post keeps only its short link, nothing is guessed) and
counted, so the reader can say how many could not be opened.
"""

from __future__ import annotations

import html
import re
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

from clue_spend.transport import BROWSER_USER_AGENT, HttpRequest, Transport

SHORT_LINK = re.compile(r"https?://(?:t\.co|lnkd\.in)/[A-Za-z0-9_-]+")
#: Links opened at once; each is a small page, about 0.4 s.
WORKERS = 8
TIMEOUT_S = 10
_TCO = re.compile(r'(?i)<meta[^>]+http-equiv="refresh"[^>]+content="\d+;\s*URL=([^"]+)"')
_TITLE = re.compile(r"(?is)<title>\s*(https?://[^<\s]+)\s*</title>")
_LNKD_ANCHOR = re.compile(r"(?is)<a\b[^>]*external_url_click[^>]*>")
_HREF = re.compile(r'(?i)\bhref="([^"]+)"')


def default_transport() -> Transport:
    from clue_api.footprint.media_resolution import PublicMediaTransport

    return PublicMediaTransport(follow_redirects=False)


#: Builds the transport links are opened with; tests replace it.
TRANSPORT: Callable[[], Transport] = default_transport


@dataclass(frozen=True)
class Expanded:
    #: Each short link that opened, mapped to the address it leads to.
    addresses: dict[str, str] = field(default_factory=dict)
    #: Links that could not be opened (left as written).
    failed: int = 0


def short_links(text: str | None) -> list[str]:
    return SHORT_LINK.findall(text or "")


def _web(address: str | None) -> str | None:
    if not address:
        return None
    address = html.unescape(address).strip()
    return address if address.startswith(("http://", "https://")) else None


def _address(host: str, page: str) -> str | None:
    if host == "t.co":
        found = _TCO.search(page) or _TITLE.search(page)
    else:
        anchor = _LNKD_ANCHOR.search(page)
        found = _HREF.search(anchor.group(0)) if anchor else None
    return _web(found.group(1)) if found else None


def _open(transport: Transport, link: str) -> str | None:
    host = urlsplit(link).hostname or ""
    request = HttpRequest(
        "GET", link, headers={"User-Agent": BROWSER_USER_AGENT}, timeout_s=TIMEOUT_S
    )
    try:
        response = transport.send(request)
        if response.status in {301, 302, 303, 307, 308}:
            return _web(urljoin(link, response.headers.get("location", "")))
        if response.status != 200:
            return None
        return _address(host, response.body.decode("utf-8", errors="replace"))
    except Exception:  # noqa: BLE001 - any reason a free link cannot be opened leaves it as written
        return None


def expand(
    links: Iterable[str], *, transport: Transport | None = None, workers: int | None = None
) -> Expanded:
    unique = sorted(set(links))
    if not unique:
        return Expanded()
    sender = transport or TRANSPORT()
    pool_size = max(1, min(workers or WORKERS, len(unique)))
    with ThreadPoolExecutor(max_workers=pool_size) as pool:
        opened = list(pool.map(lambda link: (link, _open(sender, link)), unique))
    addresses = {link: address for link, address in opened if address}
    return Expanded(addresses=addresses, failed=len(unique) - len(addresses))
