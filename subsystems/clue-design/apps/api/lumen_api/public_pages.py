"""Public page URLs for a workspace — from the hostname registry, never from ``request.base_url``.

Custom-domain publishing §6.1/§6.3. The system hostname is allocated with the workspace
(``clue_spine.hostnames``) and is always live; a custom hostname appears here only once the S2
control plane has walked it to ``active``. Scheme and port come from ``CLUE_PAGES_PUBLIC_SCHEME`` /
``CLUE_PAGES_PUBLIC_PORT`` (dev: http + 8040).
"""

from __future__ import annotations

from clue_config import Settings
from clue_spine.hostnames import public_origin

from .design_store import HybridRepository
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
