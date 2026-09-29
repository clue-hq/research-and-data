"""Where a published site lives on the public internet — the one address type.

F5 introduced ``PublicSiteAddress`` as the single answer to "where is this site?". Since the
2026-09-28 reconciliation (custom-domain publishing × F5 multipage) the answer comes from the
hostname registry, never from environment variables and never from the request: the builders are
``lumen_api.public_pages.site_address`` (the workspace's always-live system hostname) and
``custom_site_address`` (its active custom domain, when it has one). A site sits at ``/{slug}`` on
that origin and every route of it at ``/{slug}{route}``; the page origin serves them.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

__all__ = ["PublicSiteAddress"]


@dataclass(frozen=True)
class PublicSiteAddress:
    """One published site's public address: an origin plus the path the site sits at.

    The URL the API reports and the editor shows, the per-route share links and the rebased
    internal links are all built from this one value, so there is exactly one answer to "where
    is this site?".
    """

    #: Scheme + host (+ dev port) with no trailing slash: ``https://acme.pages.cluehq.ai``.
    origin: str
    #: The site's root path BELOW ``origin``: ``/abm-openai``. Never has a trailing slash.
    site_path: str
    #: Where ``/p-assets`` and ``/asset-store`` resolve — the same origin as the pages, so a
    #: site's bytes are same-origin with its pages.
    asset_origin: str

    def page_url(self, route: str) -> str:
        """The absolute URL of one route of this site. ``/`` is the site root itself."""

        return f"{self.origin}{self.site_path}" + ("" if route == "/" else route)

    def asset_base(self) -> str:
        """The origin ``/p-assets/{digest}.{ext}`` hangs off: always ``asset_origin``."""

        return self.asset_origin

    @property
    def link_path(self) -> str:
        """The site root as a path from the VISITOR's origin — what an internal link becomes.

        Identical to ``site_path`` unless the origin carries a mount path, in which case that
        mount is part of the path a browser has to request.
        """

        return f"{urlsplit(self.origin).path.rstrip('/')}{self.site_path}"
