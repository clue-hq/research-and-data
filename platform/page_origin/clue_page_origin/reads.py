"""What the origin reads, behind one protocol so route tests run on fakes (spec §10)."""

from __future__ import annotations

import hashlib
import json
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from clue_db import ConnFactory, transaction
from clue_design.brand import approved_brand_mark_sha256
from clue_design.errors import DesignNotFoundError
from clue_design.publishes import get_web_publish, get_web_publish_page
from clue_design.storage import read_design_blob, read_public_design_blob
from clue_spine.hostnames import resolve_active_hostname
from clue_spine.pages_settings import get_pages_settings
from clue_storage import StorageBackend


class ServedPublish(BaseModel):
    """The slice of an active publish the origin serves."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    html: str
    html_digest: str
    manifest_json: str
    manifest_digest: str
    noindex: bool


class ServedPage(BaseModel):
    """One route of an active publish (F5 multipage), as the origin serves it."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    html: str
    html_digest: str
    noindex: bool


class PageReads(Protocol):
    async def workspace_for_hostname(self, hostname: str) -> str | None: ...
    async def active_publish(self, workspace_id: str, slug: str) -> ServedPublish | None: ...
    async def active_page(self, workspace_id: str, slug: str, route: str) -> ServedPage | None: ...
    async def fallback_url(self, workspace_id: str) -> str | None: ...
    async def favicon(self, workspace_id: str) -> tuple[str, bytes] | None: ...
    async def publish_asset(self, workspace_id: str, sha256: str) -> tuple[str, bytes] | None: ...
    async def public_blob(self, sha256: str) -> tuple[str, bytes] | None: ...


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class DbPageReads:
    """The production reads over the registry, the publish DAL and the blob store."""

    def __init__(self, storage: StorageBackend, *, conn_factory: ConnFactory = transaction) -> None:
        self._storage = storage
        self._conn_factory = conn_factory

    async def workspace_for_hostname(self, hostname: str) -> str | None:
        async with self._conn_factory() as conn:
            return await resolve_active_hostname(conn, hostname)

    async def active_publish(self, workspace_id: str, slug: str) -> ServedPublish | None:
        async with self._conn_factory() as conn:
            publish = await get_web_publish(conn, workspace_id=workspace_id, slug=slug)
        if publish is None or publish.get("status") != "active":
            return None
        manifest = publish.get("manifest")
        if not isinstance(manifest, dict):
            return None
        html = str(publish["html"])
        manifest_json = json.dumps(
            manifest, ensure_ascii=True, separators=(",", ":"), sort_keys=True
        )
        return ServedPublish(
            html=html,
            html_digest=str(publish.get("html_digest") or _sha(html)),
            manifest_json=manifest_json,
            manifest_digest=str(publish.get("manifest_digest") or _sha(manifest_json)),
            noindex=manifest.get("robots") == "noindex",
        )

    async def active_page(self, workspace_id: str, slug: str, route: str) -> ServedPage | None:
        """One route of a live publish: its F5 page row, else — for ``/`` only — the publish's
        own html (a publish made before F5 has no page rows), else ``None``."""
        async with self._conn_factory() as conn:
            publish = await get_web_publish(conn, workspace_id=workspace_id, slug=slug)
            if publish is None or publish.get("status") != "active":
                return None
            row = await get_web_publish_page(
                conn, workspace_id=workspace_id, slug=slug, route=route
            )
        manifest = publish.get("manifest")
        noindex = isinstance(manifest, dict) and manifest.get("robots") == "noindex"
        if row is not None:
            html = str(row["html"])
            return ServedPage(
                html=html, html_digest=str(row.get("html_digest") or _sha(html)), noindex=noindex
            )
        if route == "/":
            html = str(publish["html"])
            return ServedPage(
                html=html,
                html_digest=str(publish.get("html_digest") or _sha(html)),
                noindex=noindex,
            )
        return None

    async def fallback_url(self, workspace_id: str) -> str | None:
        async with self._conn_factory() as conn:
            return (await get_pages_settings(conn, workspace_id)).fallback_url

    async def favicon(self, workspace_id: str) -> tuple[str, bytes] | None:
        """The admin's uploaded favicon, else the brand mark website ingestion took from the
        client's own site (one-brand workspaces only), else None."""
        async with self._conn_factory() as conn:
            sha256 = (await get_pages_settings(conn, workspace_id)).favicon_sha256
            if sha256 is None:
                sha256 = await approved_brand_mark_sha256(conn, workspace_id=workspace_id)
            if sha256 is None:
                return None
            try:
                return await read_design_blob(
                    conn, self._storage, workspace_id=workspace_id, sha256=sha256
                )
            except DesignNotFoundError:
                return None

    async def publish_asset(self, workspace_id: str, sha256: str) -> tuple[str, bytes] | None:
        async with self._conn_factory() as conn:
            try:
                return await read_design_blob(
                    conn, self._storage, workspace_id=workspace_id, sha256=sha256
                )
            except DesignNotFoundError:
                return None

    async def public_blob(self, sha256: str) -> tuple[str, bytes] | None:
        async with self._conn_factory() as conn:
            try:
                return await read_public_design_blob(conn, self._storage, sha256=sha256)
            except DesignNotFoundError:
                return None
