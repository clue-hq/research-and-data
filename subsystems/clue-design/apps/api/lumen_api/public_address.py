"""Where a published site actually lives on the public internet.

Founder ruling R-F5-1: the public origin of a published site is CONFIGURATION. It is not a
constant compiled into the API, and it is not a constant compiled into the editor — a build that
hardcodes ``pages.cluehq.ai`` cannot be run on a second domain, and a developer with no DNS at
all cannot run it either. Two environment variables answer it:

``LUMEN_PUBLIC_PAGES_HOST_SUFFIX``
    The wildcard host every site's own subdomain hangs off (``pages.cluehq.ai``). **Blank is the
    default and blank is a real posture**: the interim path scheme applies and the site is served
    from the request's own origin under ``/w/{workspace}/p/{slug}``, exactly as before this
    module existed. Set it once DNS and TLS exist for the wildcard.

``LUMEN_PUBLIC_PAGES_SCHEME``
    ``https`` unless a deployment says otherwise (a local wildcard host with no certificate).

Host mode needs BOTH halves: the suffix, and a workspace handle to put in front of it. A
workspace with no handle has no subdomain, so it keeps the interim path — a site is never
addressed at ``https://.pages.cluehq.ai``. The handle lookup itself is Task 14; every caller
passes ``handle=None`` today, which is why turning the suffix on right now changes nothing.

Both variables are read at CALL time, not at import time, so a process that reloads its
environment (and a test that monkeypatches it) sees the change without re-importing anything.
There is no settings class in this API; env is read with ``os.environ.get`` throughout (the
``LUMEN_API_ORIGIN`` precedent in ``lumen_agent/config.py``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit

__all__ = ["PublicSiteAddress", "public_site_address"]

#: Blank = the interim ``/w/{workspace}/p/{slug}`` path scheme on the request's own origin.
HOST_SUFFIX_ENV = "LUMEN_PUBLIC_PAGES_HOST_SUFFIX"
SCHEME_ENV = "LUMEN_PUBLIC_PAGES_SCHEME"
DEFAULT_SCHEME = "https"


@dataclass(frozen=True)
class PublicSiteAddress:
    """One published site's public address: an origin plus the path the site sits at.

    Everything a publish mints — the canonical link, ``og:url``, the manifest back-reference,
    the URL the API reports and the editor shows — is built from this one value, so there is
    exactly one answer to "where is this site?" and it moves with configuration.
    """

    #: Scheme + host (+ any mount path) with no trailing slash: ``https://acme.pages.cluehq.ai``
    #: in host mode, the request's own origin (``http://127.0.0.1:8010``) in interim mode.
    origin: str
    #: The site's root path BELOW ``origin``: ``/abm-openai`` in host mode, the tenant-scoped
    #: ``/w/ws_x/p/abm-openai`` in interim mode. Never has a trailing slash.
    site_path: str
    #: Where ``/p-assets`` and ``/asset-store`` resolve. The same origin in both modes — Task 15
    #: mounts both routes on the host app, so a site's bytes are same-origin with its pages.
    asset_origin: str
    #: True only when the suffix is configured AND a handle exists. Kept explicit rather than
    #: re-derived by string-matching the paths: the ``/p-assets`` route is workspace-scoped on
    #: the shared interim origin and bare on a per-site host, and that is the only difference.
    host_mode: bool = False

    def page_url(self, route: str) -> str:
        """The absolute URL of one route of this site. ``/`` is the site root itself."""

        return f"{self.origin}{self.site_path}" + ("" if route == "/" else route)

    def asset_base(self, workspace_id: str) -> str:
        """The prefix ``/p-assets/{digest}.{ext}`` hangs off.

        Interim mode shares one origin across every tenant, so the publish asset route is
        workspace-scoped (``/w/{workspace}/p-assets/…``, the O6 scheme). A site on its own host
        is already unambiguous and serves its assets bare.
        """

        if self.host_mode:
            return self.asset_origin
        return f"{self.asset_origin}/w/{workspace_id}"

    @property
    def link_path(self) -> str:
        """The site root as a path from the VISITOR's origin — what an internal link becomes.

        Identical to ``site_path`` unless the API is mounted under a sub-path, in which case
        that mount is part of the path a browser has to request.
        """

        return f"{urlsplit(self.origin).path.rstrip('/')}{self.site_path}"


def public_site_address(
    *,
    request_base_url: str,
    workspace_id: str,
    slug: str,
    handle: str | None,
) -> PublicSiteAddress:
    """Resolve where the site published at ``slug`` is served from.

    ``request_base_url`` is the interim fallback origin (the request that is publishing or
    reporting); it is ignored entirely once host mode engages.
    """

    suffix = (os.environ.get(HOST_SUFFIX_ENV) or "").strip().strip("/")
    workspace_handle = (handle or "").strip()
    if suffix and workspace_handle:
        scheme = (os.environ.get(SCHEME_ENV) or "").strip() or DEFAULT_SCHEME
        origin = f"{scheme}://{workspace_handle}.{suffix}"
        return PublicSiteAddress(
            origin=origin,
            site_path=f"/{slug}",
            asset_origin=origin,
            host_mode=True,
        )
    origin = request_base_url.rstrip("/")
    return PublicSiteAddress(
        origin=origin,
        site_path=f"/w/{workspace_id}/p/{slug}",
        asset_origin=origin,
        host_mode=False,
    )
