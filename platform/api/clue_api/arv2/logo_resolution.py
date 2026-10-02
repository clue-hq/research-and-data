"""An account's **mark-type** logo: which Websets URL to keep, and the Brandfetch Logo API URL.

Founder rulings 2026-09-11, after a measured proof of concept over the first Insight Health
discovery run (34 companies): show a logo on the accounts list, the account detail and the
contact profile; **the mark only** — a square icon, never a wordmark, never a social banner;
Exa Websets' ``logoUrl`` first, Brandfetch's **Logo API** second — and only the Logo API: the
Brand API is not used (founder: overkill). This supersedes D0 ruling S2 ("no logo pipeline").

What the proof of concept measured, and what each rule encodes:

* Websets returned a ``logoUrl`` for all 34. 22 were LinkedIn's **company mark**
  (``media.licdn.com/dms/image/…/company-logo_…``, 200×200, non-expiring — ``e=2147483647``);
  every one inspected was the real mark. The rest were images from the company's own site, and
  about half of those were NOT logos: an Open Graph banner, a social-share photo, a team photo, a
  page hero. → :func:`websets_mark_url` keeps a LinkedIn company mark and nothing else, and the
  platform's logo route streams it.
* Brandfetch's Logo API (https://docs.brandfetch.com/logo-api/overview) is a free, embed-only
  CDN keyed by a public client id: ``type/icon`` is the mark, ``fallback/lettermark`` a square
  first-letter tile when the brand has no icon. **Programmatic fetches are refused** — a script's
  request is answered ``302 x-bf-error: automated_traffic`` even with a valid client id (that is
  exactly how our first probe was bounced), and the docs require the URL to be embedded in the
  page with the browser's own ``Referer``. So Brandfetch is never fetched by the platform: the
  reads hand the browser :func:`brandfetch_logo_url` for a domain with no LinkedIn mark, and
  nothing is stored for it — the URL is a pure function of the domain.
"""

from __future__ import annotations

from urllib.parse import quote, urlsplit

__all__ = [
    "BRANDFETCH_CDN_HOST",
    "LINKEDIN_MARK_HOST",
    "brandfetch_logo_url",
    "is_linkedin_mark",
    "websets_mark_url",
]

LINKEDIN_MARK_HOST = "media.licdn.com"
BRANDFETCH_CDN_HOST = "cdn.brandfetch.io"

_LINKEDIN_MARK_MARKER = "company-logo"

#: Retina-sized for the screens' largest rendering (36 px); the ratio is always respected.
_BRANDFETCH_SIDE = 128


def is_linkedin_mark(url: str | None) -> bool:
    """Is this a LinkedIn company mark — the one Websets image class the PoC found reliable?"""
    if not url:
        return False
    parts = urlsplit(url.strip())
    return (
        parts.scheme == "https"
        and parts.hostname == LINKEDIN_MARK_HOST
        and _LINKEDIN_MARK_MARKER in parts.path
    )


def websets_mark_url(logo_url: str | None) -> str | None:
    """The Websets ``logoUrl`` when it is a LinkedIn company mark, else ``None``.

    Deliberately narrow: LinkedIn marks were correct in every inspected case and site-hosted
    images wrong about half the time, and there is no cheap way to tell a site's logo from its
    social banner by URL. A company whose Websets image is not a LinkedIn mark gets Brandfetch's
    Logo API at display time instead — better a lettermark than a team photo.
    """
    return logo_url.strip() if logo_url and is_linkedin_mark(logo_url) else None


def brandfetch_logo_url(domain: str, *, client_id: str) -> str | None:
    """The Logo API URL the browser embeds for ``domain``'s mark, or ``None`` without a client id.

    ``type/icon`` is the mark; ``fallback/lettermark`` yields a square first-letter tile when
    Brandfetch has no icon for the brand (the founder's placeholder of choice over a broken
    image); ``w``/``h`` 128 is retina for the 36 px detail header. The client id is public by
    the Logo API's design (it rides in every ``<img src>``), so it is a setting, not a secret.
    """
    domain = domain.strip().lower()
    client_id = client_id.strip()
    if not domain or not client_id:
        return None
    return (
        f"https://{BRANDFETCH_CDN_HOST}/domain/{quote(domain, safe='')}"
        f"/w/{_BRANDFETCH_SIDE}/h/{_BRANDFETCH_SIDE}/fallback/lettermark/type/icon"
        f"?c={quote(client_id, safe='')}"
    )
