"""Publishing a new brand-level version of a Brand-context document.

One writer for every server-side author of brand knowledge: product management (pages and the
catalog) and the Head of ABM's ``write_brand_document@1``. A version is published ``ready``; older
``ready``/``proposed`` versions of the same path are superseded; a ``confirmed`` version is a
project's approved pin and is never touched (the ``save_knowledge_document`` rule).

Every function writes through the ``conn`` it is given and never commits. Callers that may race
another writer on the same brand lock the brand row first (:func:`lock_brand`).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.onboarding_documents import KnowledgeDocument, render_markdown
from clue_storage import StorageBackend, artifact_key, content_address, record_artifact

__all__ = [
    "RETIRABLE_STATUSES",
    "SERVABLE_STATUSES",
    "lock_brand",
    "next_brand_version",
    "render_brand_document",
    "retire_older_versions",
    "store_document_bytes",
    "write_brand_document_version",
]

SERVABLE_STATUSES = ("ready", "proposed", "confirmed")
#: Versions a write may retire.
RETIRABLE_STATUSES = ("ready", "proposed")


async def lock_brand(conn: AsyncConnection, *, workspace_id: str, brand_id: str) -> bool:
    """Lock the brand row so brand writes run one after another; ``False`` if there is none."""
    found = (
        await conn.execute(
            text(
                "SELECT brand_id FROM brand WHERE workspace_id = :ws AND brand_id = :brand "
                "FOR UPDATE"
            ),
            {"ws": workspace_id, "brand": brand_id},
        )
    ).scalar_one_or_none()
    return found is not None


async def next_brand_version(
    conn: AsyncConnection, *, workspace_id: str, brand_id: str, path: str
) -> int:
    return int(
        (
            await conn.execute(
                text(
                    "SELECT COALESCE(MAX(version), 0) + 1 FROM brand_knowledge_document "
                    "WHERE workspace_id = :ws AND brand_id = :brand AND path = :path "
                    "AND project_id IS NULL"
                ),
                {"ws": workspace_id, "brand": brand_id, "path": path},
            )
        ).scalar_one()
    )


def render_brand_document(*, path: str, kind: str, front: dict[str, Any], body: str) -> bytes:
    """The exact bytes a version of ``path`` is stored as. The folder is the path's first segment
    (the ``path_in_folder`` CHECK)."""
    folder = path.split("/", 1)[0]
    return render_markdown(
        KnowledgeDocument(
            kind=kind, folder=folder, path=path, front_matter=front, body=body, cost=None
        )
    ).encode("utf-8")


async def store_document_bytes(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    workspace_id: str,
    data: bytes,
    source_key: str,
) -> tuple[str, str]:
    """Store Markdown bytes content-addressed; returns ``(artifact_key, sha256)``."""
    sha = content_address(data)
    key = artifact_key(workspace_id, sha)
    await record_artifact(
        conn,
        storage_key=key,
        workspace_id=workspace_id,
        content_sha256=sha,
        media_type="text/markdown",
        size_bytes=len(data),
        source_key=source_key,
    )
    await storage.put(key, data, media_type="text/markdown")
    return key, sha


async def retire_older_versions(
    conn: AsyncConnection, *, workspace_id: str, brand_id: str, path: str, below: int | None = None
) -> list[UUID]:
    """Supersede every retirable brand-level version of ``path`` (below ``below`` when given)."""
    rows = await conn.execute(
        text(
            "UPDATE brand_knowledge_document SET status = 'superseded', updated_at = now() "
            "WHERE workspace_id = :ws AND brand_id = :brand AND path = :path "
            "AND project_id IS NULL AND status IN :retirable "
            "AND (CAST(:below AS integer) IS NULL OR version < CAST(:below AS integer)) "
            "RETURNING document_id"
        ).bindparams(bindparam("retirable", expanding=True)),
        {
            "ws": workspace_id,
            "brand": brand_id,
            "path": path,
            "retirable": list(RETIRABLE_STATUSES),
            "below": below,
        },
    )
    return list(rows.scalars().all())


async def write_brand_document_version(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    workspace_id: str,
    brand_id: str,
    path: str,
    kind: str,
    front: dict[str, Any],
    body: str,
    source_key: str,
) -> UUID:
    """Publish ``ready`` bytes as the next brand-level version of ``path``; retire older ones."""
    folder = path.split("/", 1)[0]
    data = render_brand_document(path=path, kind=kind, front=front, body=body)
    key, sha = await store_document_bytes(
        conn, storage, workspace_id=workspace_id, data=data, source_key=source_key
    )
    version = await next_brand_version(
        conn, workspace_id=workspace_id, brand_id=brand_id, path=path
    )
    previous = (
        await conn.execute(
            text(
                "SELECT document_id FROM brand_knowledge_document WHERE workspace_id = :ws "
                "AND brand_id = :brand AND path = :path AND project_id IS NULL "
                "AND status IN :servable ORDER BY version DESC LIMIT 1"
            ).bindparams(bindparam("servable", expanding=True)),
            {
                "ws": workspace_id,
                "brand": brand_id,
                "path": path,
                "servable": list(SERVABLE_STATUSES),
            },
        )
    ).scalar_one_or_none()
    document_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO brand_knowledge_document (document_id, workspace_id, brand_id, folder, "
            " path, kind, version, status, artifact_key, artifact_sha256, supersedes_document_id) "
            "VALUES (:id, :ws, :brand, :folder, :path, :kind, :version, 'ready', :key, :sha, "
            " :previous)"
        ),
        {
            "id": document_id,
            "ws": workspace_id,
            "brand": brand_id,
            "folder": folder,
            "path": path,
            "kind": kind,
            "version": version,
            "key": key,
            "sha": sha,
            "previous": previous,
        },
    )
    await retire_older_versions(
        conn, workspace_id=workspace_id, brand_id=brand_id, path=path, below=version
    )
    return document_id
