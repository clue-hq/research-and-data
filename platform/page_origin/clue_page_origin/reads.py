"""What the origin reads, behind one protocol so route tests run on fakes (spec §10)."""

from __future__ import annotations

import hashlib
import json
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from clue_db import ConnFactory, transaction
from clue_design.errors import DesignNotFoundError
from clue_design.publishes import get_web_publish
from clue_design.storage import read_design_blob, read_public_design_blob
from clue_spine.hostnames import resolve_active_hostname
from clue_storage import StorageBackend


class ServedPublish(BaseModel):
    """The slice of an active publish the origin serves."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    html: str
    html_digest: str
    manifest_json: str
    manifest_digest: str
    noindex: bool


class PageReads(Protocol):
    async def workspace_for_hostname(self, hostname: str) -> str | None: ...
    async def active_publish(self, workspace_id: str, slug: str) -> ServedPublish | None: ...
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

    async def fallback_url(self, workspace_id: str) -> str | None:
        # S2 reads workspace_pages_settings.fallback_url here; S1 has no writer, so no fallback.
        return None

    async def favicon(self, workspace_id: str) -> tuple[str, bytes] | None:
        # S2 reads workspace_pages_settings.favicon_sha256 → read_design_blob here.
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
