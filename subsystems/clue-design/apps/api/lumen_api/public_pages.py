"""Public page URLs for a workspace — from the hostname registry, never from ``request.base_url``.

Custom-domain publishing §6.1/§6.3. The system hostname is allocated with the workspace
(``clue_spine.hostnames``) and is always live; a custom hostname appears here only once the S2
control plane has walked it to ``active``. Scheme and port come from ``CLUE_PAGES_PUBLIC_SCHEME`` /
``CLUE_PAGES_PUBLIC_PORT`` (dev: http + 8040).

``site_address`` / ``custom_site_address`` wrap the same origins in F5's ``PublicSiteAddress``
(reconciliation 2026-09-28), so a multi-page site's per-route URLs (``/{slug}{route}``) come from
the one builder that knows where sites live.
"""

from __future__ import annotations

from clue_config import Settings
from clue_spine.hostnames import public_origin

from .design_store import HybridRepository
from .public_address import PublicSiteAddress
from .web_export import WebExportError


def system_public_origin(repository: HybridRepository) -> str:
    hostname = repository.system_hostname()
    if hostname is None:
        raise WebExportError(
            f"workspace {repository.workspace_id!r} has no system hostname; "
            "run `make pages-backfill-hostnames`"
        )
    settings = Settings()
    return public_origin(
        hostname, scheme=settings.pages_public_scheme, port=settings.pages_public_port
    )


def custom_public_origin(repository: HybridRepository) -> str | None:
    hostname = repository.active_custom_hostname()
    if hostname is None:
        return None
    # A customer hostname terminates at Cloudflare: always https, never a port.
    return public_origin(hostname, scheme="https", port=None)


def public_publish_url(repository: HybridRepository, slug: str) -> str:
    return f"{system_public_origin(repository)}/{slug}"


def custom_publish_url(repository: HybridRepository, slug: str) -> str | None:
    origin = custom_public_origin(repository)
    return None if origin is None else f"{origin}/{slug}"


def site_address(repository: HybridRepository, slug: str) -> PublicSiteAddress:
    """The site published at ``slug``, on the workspace's always-live system hostname.

    F5's one address type, built from the registry (reconciliation 2026-09-28): the site sits at
    ``/{slug}`` and each of its routes at ``/{slug}{route}``; its bytes are same-origin.
    """
    origin = system_public_origin(repository)
    return PublicSiteAddress(origin=origin, site_path=f"/{slug}", asset_origin=origin)


def custom_site_address(repository: HybridRepository, slug: str) -> PublicSiteAddress | None:
    """The same site on the workspace's active custom domain, or ``None`` without one."""
    origin = custom_public_origin(repository)
    if origin is None:
        return None
    return PublicSiteAddress(origin=origin, site_path=f"/{slug}", asset_origin=origin)
