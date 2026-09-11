"""``GET /frontend/v1/accounts/{account_id}/logo`` — the account's mark, streamed by the platform.

Founder ruling 2026-09-11 (supersedes D0 ruling S2): the accounts list, the account detail and
the contact profile show a mark-type logo. The screens receive a ``/``-rooted path to this route
(``v1_shared.account_logo_path``), never the third-party URL, for three reasons: the frontend's
schema demands a rooted path; the browser fetches it through the session-authenticated BFF like
every other read, so no logo leaks which companies a workspace holds; and the third-party host
(LinkedIn's media CDN, Brandfetch's CDN) is never a dependency of the page itself.

The route reads the account's ``core.logo_url`` under the workspace scope, fetches the image
once with a bounded timeout and size, and answers with the bytes and the upstream content type.
Anything that is not a small raster image is a 404 — the frontend then shows its placeholder.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

import httpx
from fastapi import APIRouter, HTTPException, Response

from clue_api.arv2.logo_resolution import is_linkedin_mark
from clue_api.frontend_read.app import WorkspaceDep
from clue_core import EntityId
from clue_db import ConnFactory
from clue_research.claimstore import WorkspaceScope, current_values

__all__ = ["FetchedImage", "fetch_image", "register_account_logo_route"]

#: (bytes, content type) of a fetched image.
FetchedImage = tuple[bytes, str]
ImageFetcher = Callable[[str], Awaitable[FetchedImage | None]]

_MAX_IMAGE_BYTES = 2_000_000
_FETCH_TIMEOUT_S = 10.0
_ALLOWED_TYPES = ("image/png", "image/jpeg", "image/webp")
_CACHE_CONTROL = "private, max-age=86400"


async def fetch_image(url: str) -> FetchedImage | None:
    """Fetch one raster image over HTTPS, or ``None`` for anything that is not one."""
    if not url.startswith("https://"):
        return None
    try:
        async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT_S, follow_redirects=True) as client:
            response = await client.get(url, headers={"accept": "image/*"})
    except httpx.HTTPError:
        return None
    if response.status_code != 200:
        return None
    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type not in _ALLOWED_TYPES:
        return None
    body = response.content
    if not body or len(body) > _MAX_IMAGE_BYTES:
        return None
    return body, content_type


def register_account_logo_route(
    router: APIRouter, *, conn_factory: ConnFactory, fetcher: ImageFetcher | None = None
) -> None:
    """Register the logo route on the workspace-scoped ``/frontend/v1`` router.

    ``fetcher`` is the one seam to the outside. When none is given the route looks up this
    module's :func:`fetch_image` **at call time**, so a test can script it with a monkeypatch and
    the production app needs no wiring change.
    """

    @router.get("/accounts/{account_id}/logo", response_model=None)
    async def get_account_logo(account_id: str, workspace_id: WorkspaceDep) -> Response:
        try:
            entity_id = EntityId(uuid.UUID(account_id))
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="account not found") from exc
        async with conn_factory() as conn:
            values = await current_values(
                conn,
                [entity_id],
                ("core.logo_url",),
                scope=WorkspaceScope.for_workspace(workspace_id),
            )
        current = values.get((entity_id, "core.logo_url"))
        url = None if current is None else current.value_json
        # Only a stored LinkedIn mark is streamed. Brandfetch's Logo API is embed-only (its CDN
        # refuses programmatic fetches as ``automated_traffic``), so the reads hand the browser
        # that URL directly and this route never proxies it.
        if not isinstance(url, str) or not is_linkedin_mark(url):
            raise HTTPException(status_code=404, detail="no logo")
        fetched = await (fetcher or fetch_image)(url)
        if fetched is None:
            raise HTTPException(status_code=404, detail="logo unavailable")
        body, content_type = fetched
        return Response(
            content=body,
            media_type=content_type,
            headers={"cache-control": _CACHE_CONTROL, "x-content-type-options": "nosniff"},
        )
