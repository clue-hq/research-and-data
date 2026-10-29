"""The document-thumbnail cache index DAL — three properties, against the session-migrated DB.

1. **Round-trip** — a miss is ``None`` (never an error: a gallery card with no cached PNG yet is
   the normal first read), and after one record the digest and its media type come back.
2. **Idempotent upsert** — recording again for the same ``(document, version)`` REPLACES the
   digest AND its media type instead of raising. Two workers may render the same card
   concurrently, and a re-render after an evicted blob must be able to re-claim the slot.
3. **Workspace scoping** — the key is ``(workspace, document, version)``, so one tenant's cached
   thumbnail is invisible to another even for an identical document id.

The rows are written for workspaces and documents that were never seeded, which is the FK-free
property the table is built on: a thumbnail is a pure cache and must never be the thing that
blocks a document (or a workspace) from being deleted.

Writes run inside transactions that are rolled back explicitly, so they leave no rows behind.
"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_db import db_lifespan
from clue_design import thumbnails
from tests.design.conftest import run_async

_PNG_DIGEST = "a" * 64
_OTHER_DIGEST = "b" * 64


def _ws(tag: str) -> str:
    return f"ws_test_thumb_{tag}_{uuid4().hex[:12]}"


async def _row_count(conn: AsyncConnection, workspace_id: str) -> int:
    result = await conn.execute(
        text("SELECT count(*) FROM design_document_thumbnail WHERE workspace_id = :w"),
        {"w": workspace_id},
    )
    return int(result.scalar_one())


def test_record_then_get_roundtrip(require_design_db: None) -> None:
    workspace_id = _ws("roundtrip")

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn:
            transaction = await conn.begin()
            try:
                assert (
                    await thumbnails.get_document_thumbnail(
                        conn, workspace_id=workspace_id, document_id="doc_1", version=3
                    )
                    is None
                )

                row = await thumbnails.record_document_thumbnail(
                    conn,
                    workspace_id=workspace_id,
                    document_id="doc_1",
                    version=3,
                    sha256=_PNG_DIGEST,
                    media_type="image/png",
                )
                assert row == {"sha256": _PNG_DIGEST, "media_type": "image/png"}

                assert await thumbnails.get_document_thumbnail(
                    conn, workspace_id=workspace_id, document_id="doc_1", version=3
                ) == {"sha256": _PNG_DIGEST, "media_type": "image/png"}

                # The version is part of the key: the next version has its own (empty) slot.
                assert (
                    await thumbnails.get_document_thumbnail(
                        conn, workspace_id=workspace_id, document_id="doc_1", version=4
                    )
                    is None
                )
            finally:
                await transaction.rollback()

    run_async(scenario())


def test_record_is_an_idempotent_upsert(require_design_db: None) -> None:
    workspace_id = _ws("upsert")

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn:
            transaction = await conn.begin()
            try:
                await thumbnails.record_document_thumbnail(
                    conn,
                    workspace_id=workspace_id,
                    document_id="doc_1",
                    version=3,
                    sha256=_PNG_DIGEST,
                    media_type="image/png",
                )
                # A different media type on the re-record, so the upsert's
                # `media_type = excluded.media_type` is exercised too: without it the
                # slot would keep naming the FIRST render's type for the second
                # render's bytes.
                replaced = await thumbnails.record_document_thumbnail(
                    conn,
                    workspace_id=workspace_id,
                    document_id="doc_1",
                    version=3,
                    sha256=_OTHER_DIGEST,
                    media_type="image/webp",
                )
                assert replaced == {"sha256": _OTHER_DIGEST, "media_type": "image/webp"}

                # One slot, not two — and the latest render is what it names.
                assert await _row_count(conn, workspace_id) == 1
                assert await thumbnails.get_document_thumbnail(
                    conn, workspace_id=workspace_id, document_id="doc_1", version=3
                ) == {"sha256": _OTHER_DIGEST, "media_type": "image/webp"}
            finally:
                await transaction.rollback()

    run_async(scenario())


def test_a_cached_thumbnail_is_invisible_to_another_workspace(require_design_db: None) -> None:
    owner, stranger = _ws("owner"), _ws("stranger")

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn:
            transaction = await conn.begin()
            try:
                await thumbnails.record_document_thumbnail(
                    conn,
                    workspace_id=owner,
                    document_id="doc_1",
                    version=1,
                    sha256=_PNG_DIGEST,
                    media_type="image/png",
                )
                assert (
                    await thumbnails.get_document_thumbnail(
                        conn, workspace_id=stranger, document_id="doc_1", version=1
                    )
                    is None
                )

                # And a stranger's own record for the same document id is its own row.
                await thumbnails.record_document_thumbnail(
                    conn,
                    workspace_id=stranger,
                    document_id="doc_1",
                    version=1,
                    sha256=_OTHER_DIGEST,
                    media_type="image/png",
                )
                assert await thumbnails.get_document_thumbnail(
                    conn, workspace_id=owner, document_id="doc_1", version=1
                ) == {"sha256": _PNG_DIGEST, "media_type": "image/png"}
            finally:
                await transaction.rollback()

    run_async(scenario())


def test_latest_thumbnail_is_the_highest_cached_version(require_design_db: None) -> None:
    """The stand-in a card shows while its current version renders in the background
    (production 2026-10-28): the newest version that has a cached PNG, in this workspace only."""
    owner, stranger = _ws("latest"), _ws("latest_stranger")

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn:
            transaction = await conn.begin()
            try:
                assert (
                    await thumbnails.get_latest_document_thumbnail(
                        conn, workspace_id=owner, document_id="doc_1"
                    )
                    is None
                )
                for version, digest in ((2, _PNG_DIGEST), (7, _OTHER_DIGEST), (5, _PNG_DIGEST)):
                    await thumbnails.record_document_thumbnail(
                        conn,
                        workspace_id=owner,
                        document_id="doc_1",
                        version=version,
                        sha256=digest,
                        media_type="image/png",
                    )
                assert await thumbnails.get_latest_document_thumbnail(
                    conn, workspace_id=owner, document_id="doc_1"
                ) == {"sha256": _OTHER_DIGEST, "media_type": "image/png", "version": 7}
                assert (
                    await thumbnails.get_latest_document_thumbnail(
                        conn, workspace_id=stranger, document_id="doc_1"
                    )
                    is None
                )
            finally:
                await transaction.rollback()

    run_async(scenario())
