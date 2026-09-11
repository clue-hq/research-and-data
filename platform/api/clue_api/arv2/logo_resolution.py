"""An account's **mark-type** logo: which URL to keep, and where to ask when Websets has none.

Founder rulings 2026-09-11, after a measured proof of concept over the first Insight Health
discovery run (34 companies): show a logo on the accounts list, the account detail and the
contact profile; **the mark only** — a square symbol, never a wordmark, never a social banner;
Exa Websets' ``logoUrl`` first, Brandfetch's Brand API second. This supersedes D0 ruling S2
("no logo pipeline; ``logo_path`` is always null").

What the proof of concept measured, and what each rule below encodes:

* Websets returned a ``logoUrl`` for all 34. 22 were LinkedIn's **company mark**
  (``media.licdn.com/dms/image/…/company-logo_…``, 200×200, non-expiring — ``e=2147483647``);
  every one inspected was the real mark. The rest were images from the company's own site, and
  about half of those were NOT logos: an Open Graph banner, a social-share photo, a team photo, a
  page hero. One was LinkedIn's *default* placeholder (``static.licdn.com``), one 403'd.
  → :func:`websets_mark_url` keeps a LinkedIn company mark and nothing else.
* Brandfetch's Brand API (``GET /v2/brands/{domain}``, bearer key) answered 7 of 7 misses with a
  logo set; 5 carried a ``type == "icon"`` (the mark — Inova's symbol, Southern Ortho's tree),
  2 only a wordmark ``logo``. Its logo-link CDN rejected the client id we hold, so the Brand
  API is the fallback. → :class:`BrandfetchClient.icon_url` returns the icon or ``None``; a
  wordmark is never substituted for a mark.

Everything here is a URL decision. The image itself is streamed to the browser by the platform's
own logo route (``frontend_read.account_logo``), never linked raw.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any
from urllib.parse import quote, urlsplit

from pydantic import SecretStr

from clue_api.arv2.calls import CallSpec, CostReading, ProviderCaller, SpendEstimate
from clue_api.arv2.transport import HttpRequest, HttpResponse

__all__ = [
    "BRANDFETCH_ESTIMATE_USD",
    "PROVIDER",
    "BrandfetchClient",
    "brandfetch_halt_rule",
    "icon_from_brand",
    "websets_mark_url",
]

PROVIDER = "brandfetch"

#: Brandfetch meters the Brand API per request on its paid plans; it returns no cost on the wire,
#: so the ledger carries this flat estimate and says so (the cost reader below reads nothing).
BRANDFETCH_ESTIMATE_USD = Decimal("0.01")

#: The image formats the platform's logo route will stream. SVG is deliberately out: an SVG from a
#: third party is a script container, and the route serves bytes to a browser.
_RASTER_FORMATS = frozenset({"png", "jpeg", "jpg", "webp"})

#: The largest mark worth keeping; the screens render 12 px and 36 px, a 400 px source is plenty.
_MAX_ICON_SIDE = 512

_LINKEDIN_MARK_HOST = "media.licdn.com"
_LINKEDIN_MARK_MARKER = "company-logo"


def websets_mark_url(logo_url: str | None) -> str | None:
    """The Websets ``logoUrl`` when it is a LinkedIn company mark, else ``None``.

    The rule is deliberately narrow: the proof of concept found LinkedIn marks correct in every
    inspected case and site-hosted images wrong about half the time, and there is no cheap way to
    tell a site's logo from its social banner by URL. A company whose Websets image is not a
    LinkedIn mark goes to Brandfetch instead — better no logo than a team photo.
    """
    if not logo_url:
        return None
    parts = urlsplit(logo_url.strip())
    if parts.scheme != "https" or parts.hostname != _LINKEDIN_MARK_HOST:
        return None
    if _LINKEDIN_MARK_MARKER not in parts.path:
        return None
    return logo_url.strip()


def icon_from_brand(brand: Mapping[str, Any]) -> str | None:
    """The mark's URL out of a Brand API payload — the ``icon`` logo's best raster format.

    Prefers the largest raster no wider than :data:`_MAX_ICON_SIDE`; falls back to the smallest
    raster above it (a 704 px icon is still a mark). Wordmarks (``type == "logo"``) and symbols
    Brandfetch flags as ``symbol`` are not used: the founder asked for the mark, and Brandfetch's
    ``icon`` is the square, background-carrying form the screens expect.
    """
    logos = brand.get("logos")
    if not isinstance(logos, Sequence):
        return None
    candidates: list[tuple[int, str]] = []
    for logo in logos:
        if not isinstance(logo, Mapping) or logo.get("type") != "icon":
            continue
        formats = logo.get("formats")
        if not isinstance(formats, Sequence):
            continue
        for fmt in formats:
            if not isinstance(fmt, Mapping):
                continue
            if str(fmt.get("format") or "").lower() not in _RASTER_FORMATS:
                continue
            src = fmt.get("src")
            if not isinstance(src, str) or not src.startswith("https://"):
                continue
            width = fmt.get("width")
            side = width if isinstance(width, int) and not isinstance(width, bool) else 0
            candidates.append((side, src))
    if not candidates:
        return None
    fitting = [c for c in candidates if c[0] <= _MAX_ICON_SIDE]
    if fitting:
        return max(fitting, key=lambda c: c[0])[1]
    return min(candidates, key=lambda c: c[0])[1]


def brandfetch_halt_rule(response: HttpResponse) -> str | None:
    """Stop the run's Brandfetch calls on a credential or quota refusal; a 404 is just no brand."""
    if response.status in (401, 403):
        return "brandfetch_unauthorized"
    if response.status == 402 or response.status == 429:
        return "brandfetch_quota"
    return None


def _no_cost_reader(response: HttpResponse) -> CostReading:
    del response
    return CostReading()


class BrandfetchClient:
    """One Brand API hop through the run's :class:`ProviderCaller`, for the mark only."""

    def __init__(
        self,
        caller: ProviderCaller,
        *,
        api_key: SecretStr,
        base_url: str = "https://api.brandfetch.io",
        timeout_s: float = 20.0,
    ) -> None:
        self._caller = caller
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s

    def icon_url(self, domain: str, *, label: str) -> str | None:
        """The mark's URL for ``domain``, or ``None`` when Brandfetch has no brand or no icon.

        A 404 is the normal "unknown brand" answer and is not an error; any other non-2xx is left
        to the caller's retry/halt discipline and reads as ``None`` here.
        """
        request = HttpRequest(
            method="GET",
            url=f"{self._base_url}/v2/brands/{quote(domain, safe='')}",
            headers={
                "authorization": f"Bearer {self._api_key.get_secret_value()}",
                "accept": "application/json",
            },
            timeout_s=self._timeout_s,
        )
        result = self._caller.call(
            CallSpec(
                provider=PROVIDER,
                operation="brand",
                label=label,
                request=request,
                estimate=SpendEstimate(usd=BRANDFETCH_ESTIMATE_USD),
                cost_reader=_no_cost_reader,
                halt_rule=brandfetch_halt_rule,
            )
        )
        if result.response.status != 200:
            return None
        body = result.json()
        return icon_from_brand(body) if isinstance(body, Mapping) else None
