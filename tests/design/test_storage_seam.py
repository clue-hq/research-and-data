"""D4 acceptance tests: the design storage seam (PD contract §5; rulings R-D4-2 / R-D4-3).

Six properties, all against the session-migrated DB in rolled-back transactions:

1. **Key shape** — ``{workspace}/design/{sha256}``, and a key is *data*: a malformed digest or
   an empty/slashed workspace is refused rather than minted.
2. **Row before blob** — after one register the ``artifact`` row is visible with its
   ``source_key``/``media_type``/``size_bytes``, and the blob round-trips byte-for-byte.
3. **Idempotent re-register** — the same bytes twice give the same key, ONE row, and clear a
   prior erasure (the row is the writer's statement that a live blob exists again).
4. **Workspace disjointness** — identical bytes in two workspaces are two keys and two rows;
   neither tenant's blob is the other's.
5. **Fail-closed reads** — an absent digest and a foreign-workspace digest raise the SAME
   :class:`DesignNotFoundError`, so existence never leaks across tenants.
6. **Erasure is honoured** — a DSAR-erased row makes the bytes unreadable even while they are
   still physically present (the intent is durable before the purge runs).

Round B adds four more: digest resolution across every historical ``opaque_ref`` shape, the
deliberately workspace-UNSCOPED public read (R-D4-7) and its namespace boundary, and destruction.
"""

from __future__ import annotations

import hashlib
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_db import db_lifespan
from clue_design.errors import DesignNotFoundError
from clue_design.storage import (
    SOURCE_KEY_ASSET,
    SOURCE_KEY_CUSTOM_COMPONENT,
    SOURCE_KEY_PUBLISH_ASSET,
    delete_design_bytes,
    design_bytes_exist,
    design_storage_key,
    location_digest,
    read_design_blob,
    read_design_bytes,
    read_public_design_blob,
    register_design_bytes,
)
from clue_storage import FsStorage, get_artifact, mark_erased
from clue_storage.artifacts import record_artifact
from clue_storage.protocol import artifact_key
from tests.design.conftest import run_async


def _ws(tag: str) -> str:
    return f"ws_test_d4_{tag}_{uuid4().hex[:12]}"


async def _seed_ws(conn: AsyncConnection, workspace_id: str) -> None:
    await conn.execute(
        text("INSERT INTO workspace (workspace_id, name) VALUES (:w, :w)"),
        {"w": workspace_id},
    )


async def _row_count(conn: AsyncConnection, storage_key: str) -> int:
    result = await conn.execute(
        text("SELECT count(*) FROM artifact WHERE storage_key = :k"), {"k": storage_key}
    )
    return int(result.scalar_one())


# --- 1. the key is derived and validated, never trusted ---------------------------------------


def test_design_storage_key_is_namespaced_and_validated() -> None:
    digest = hashlib.sha256(b"hello").hexdigest()
    assert design_storage_key("ws_a", digest) == f"ws_a/design/{digest}"
    # Disjoint from the claim-evidence namespace `{ws}/{sha}` — the whole point of R-D4-2.
    assert design_storage_key("ws_a", digest) != f"ws_a/{digest}"

    for bad_digest in ("", "nope", digest.upper(), digest[:63], digest + "0", "../etc"):
        with pytest.raises(ValueError):
            design_storage_key("ws_a", bad_digest)
    for bad_workspace in ("", "ws/../other"):
        with pytest.raises(ValueError):
            design_storage_key(bad_workspace, digest)


# --- 2/3. row before blob, and idempotent re-registration --------------------------------------


def test_register_writes_the_row_then_the_blob_and_is_idempotent(
    require_design_db: None, tmp_path
) -> None:
    workspace_id = _ws("register")
    storage = FsStorage(tmp_path / "store")
    data = b"export default function Component() {}"
    digest = hashlib.sha256(data).hexdigest()

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn:
            transaction = await conn.begin()
            try:
                await _seed_ws(conn, workspace_id)
                key = await register_design_bytes(
                    conn,
                    storage,
                    workspace_id=workspace_id,
                    data=data,
                    media_type="application/octet-stream",
                    source_key=SOURCE_KEY_CUSTOM_COMPONENT,
                )
                assert key == f"{workspace_id}/design/{digest}"

                record = await get_artifact(conn, key)
                assert record is not None
                assert record.workspace_id == workspace_id
                assert record.content_sha256 == digest
                assert record.media_type == "application/octet-stream"
                assert record.size_bytes == len(data)
                assert record.source_key == SOURCE_KEY_CUSTOM_COMPONENT

                assert await storage.exists(key)
                assert (
                    await read_design_bytes(conn, storage, workspace_id=workspace_id, sha256=digest)
                    == data
                )
                assert await design_bytes_exist(conn, workspace_id=workspace_id, sha256=digest)

                # Re-registering identical bytes: same key, still ONE row, erasure cleared.
                await mark_erased(conn, key)
                assert not await design_bytes_exist(conn, workspace_id=workspace_id, sha256=digest)
                again = await register_design_bytes(
                    conn,
                    storage,
                    workspace_id=workspace_id,
                    data=data,
                    media_type="application/octet-stream",
                    source_key=SOURCE_KEY_PUBLISH_ASSET,
                )
                assert again == key
                assert await _row_count(conn, key) == 1
                resurrected = await get_artifact(conn, key)
                assert resurrected is not None
                assert resurrected.erased_at is None and resurrected.purged_at is None
                # The first writer's provenance wins (the upsert preserves it) — recording is a
                # statement about the BYTES, not a re-attribution of them.
                assert resurrected.source_key == SOURCE_KEY_CUSTOM_COMPONENT
            finally:
                await transaction.rollback()

    run_async(scenario())


# --- 4. identical bytes never dedup across tenants ---------------------------------------------


def test_the_same_bytes_in_two_workspaces_are_two_keys_and_two_rows(
    require_design_db: None, tmp_path
) -> None:
    left, right = _ws("left"), _ws("right")
    storage = FsStorage(tmp_path / "store")
    data = b"shared delivery bundle"
    digest = hashlib.sha256(data).hexdigest()

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn:
            transaction = await conn.begin()
            try:
                await _seed_ws(conn, left)
                await _seed_ws(conn, right)
                keys = [
                    await register_design_bytes(
                        conn,
                        storage,
                        workspace_id=workspace_id,
                        data=data,
                        media_type="text/javascript; charset=utf-8",
                        source_key=SOURCE_KEY_PUBLISH_ASSET,
                    )
                    for workspace_id in (left, right)
                ]
                assert keys == [f"{left}/design/{digest}", f"{right}/design/{digest}"]
                for key in keys:
                    assert await _row_count(conn, key) == 1
            finally:
                await transaction.rollback()

    run_async(scenario())


# --- 5/6. fail-closed reads --------------------------------------------------------------------


def test_reads_are_fail_closed_for_absent_foreign_and_erased_blobs(
    require_design_db: None, tmp_path
) -> None:
    owner, stranger = _ws("owner"), _ws("stranger")
    storage = FsStorage(tmp_path / "store")
    data = b"first frame html"
    digest = hashlib.sha256(data).hexdigest()
    absent = hashlib.sha256(b"never stored").hexdigest()

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn:
            transaction = await conn.begin()
            try:
                await _seed_ws(conn, owner)
                await _seed_ws(conn, stranger)
                key = await register_design_bytes(
                    conn,
                    storage,
                    workspace_id=owner,
                    data=data,
                    media_type="text/html; charset=utf-8",
                    source_key=SOURCE_KEY_PUBLISH_ASSET,
                )
                media_type, read_back = await read_design_blob(
                    conn, storage, workspace_id=owner, sha256=digest
                )
                assert (media_type, read_back) == ("text/html; charset=utf-8", data)

                # An absent digest and a foreign-workspace digest are the SAME refusal.
                with pytest.raises(DesignNotFoundError):
                    await read_design_bytes(conn, storage, workspace_id=owner, sha256=absent)
                with pytest.raises(DesignNotFoundError):
                    await read_design_bytes(conn, storage, workspace_id=stranger, sha256=digest)
                assert not await design_bytes_exist(conn, workspace_id=stranger, sha256=digest)

                # Erased row: the bytes are still on disk (the purge is phase 2), but the seam
                # refuses them — the durable intent is what a reader honours.
                await mark_erased(conn, key)
                assert await storage.exists(key)
                with pytest.raises(DesignNotFoundError):
                    await read_design_bytes(conn, storage, workspace_id=owner, sha256=digest)
            finally:
                await transaction.rollback()

    run_async(scenario())


# --- Round B: location resolution, the unscoped public read, and destruction -------------------


def test_location_digest_resolves_every_ref_shape_and_refuses_the_rest() -> None:
    """D4 Round B: readers resolve BY DIGEST, so all three historical ref shapes work and no
    stored ref is ever interpreted as a path."""
    digest = hashlib.sha256(b"pixels").hexdigest()
    for provider in ("clue-storage", "local-store", "opaque_asset_store"):
        for ref in (digest, f"sha256/{digest[:2]}/{digest}", f"ws_a/design/{digest}"):
            assert location_digest({"provider": provider, "opaque_ref": ref}) == digest

    # A location that names some other system's object resolves to nothing — which is what
    # `register_scene_assets` uses to decide a record is not servable.
    assert location_digest({"provider": "opaque_asset_store", "opaque_ref": "acme/hero"}) is None
    assert location_digest({"provider": "s3", "opaque_ref": digest}) is None
    assert location_digest({"provider": "local-store", "opaque_ref": ""}) is None
    assert location_digest(None) is None
    assert location_digest({"provider": "local-store"}) is None


def test_the_public_read_is_unscoped_but_design_only_and_skips_unreadable_candidates(
    require_design_db: None, tmp_path
) -> None:
    """R-D4-7: ``GET /asset-store/{digest}`` must keep serving the published page and the
    origin-"null" preview iframe, neither of which can name a tenant.

    So this read resolves ACROSS workspaces — but only inside the ``design`` namespace (a
    claim-evidence snapshot sharing the same bytes must stay unreachable), only for LIVE rows,
    and skipping any candidate whose bytes the backend cannot produce.
    """
    owner, stranger = _ws("pub_owner"), _ws("pub_stranger")
    storage = FsStorage(tmp_path / "store")
    data = b"public font bytes"
    digest = hashlib.sha256(data).hexdigest()

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn:
            transaction = await conn.begin()
            try:
                await _seed_ws(conn, owner)
                await _seed_ws(conn, stranger)
                key = await register_design_bytes(
                    conn,
                    storage,
                    workspace_id=owner,
                    data=data,
                    media_type="font/woff2",
                    source_key=SOURCE_KEY_ASSET,
                )
                # A *stranger* resolves it — deliberately, and with the row's media type.
                assert await read_public_design_blob(conn, storage, sha256=digest) == (
                    "font/woff2",
                    data,
                )

                # A candidate whose blob the backend cannot produce is skipped, not fatal: the
                # stranger's row is younger, so it is only reached because the owner's is dead.
                await register_design_bytes(
                    conn,
                    storage,
                    workspace_id=stranger,
                    data=data,
                    media_type="application/octet-stream",
                    source_key=SOURCE_KEY_ASSET,
                )
                await storage.delete(key)
                assert await read_public_design_blob(conn, storage, sha256=digest) == (
                    "application/octet-stream",
                    data,
                )

                # Nothing live left → the same refusal as every other read.
                await mark_erased(conn, design_storage_key(stranger, digest))
                with pytest.raises(DesignNotFoundError):
                    await read_public_design_blob(conn, storage, sha256=digest)
                with pytest.raises(DesignNotFoundError):
                    await read_public_design_blob(conn, storage, sha256="not a digest")
            finally:
                await transaction.rollback()

    run_async(scenario())


def test_the_public_read_cannot_reach_the_claim_evidence_namespace(
    require_design_db: None, tmp_path
) -> None:
    """The `design` segment is the structural boundary (R-D4-2): an evidence snapshot keyed
    ``{workspace}/{sha}`` is invisible to this route even for identical bytes."""
    workspace_id = _ws("evidence")
    storage = FsStorage(tmp_path / "store")
    data = b"a scraped page snapshot"
    digest = hashlib.sha256(data).hexdigest()

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn:
            transaction = await conn.begin()
            try:
                await _seed_ws(conn, workspace_id)
                evidence_key = artifact_key(workspace_id, digest)
                await record_artifact(
                    conn,
                    storage_key=evidence_key,
                    workspace_id=workspace_id,
                    content_sha256=digest,
                    media_type="text/html",
                    size_bytes=len(data),
                    source_key="firecrawl",
                )
                await storage.put(evidence_key, data, media_type="text/html")

                with pytest.raises(DesignNotFoundError):
                    await read_public_design_blob(conn, storage, sha256=digest)
            finally:
                await transaction.rollback()

    run_async(scenario())


def test_delete_destroys_the_blob_and_tombstones_the_row(require_design_db: None, tmp_path) -> None:
    """The asset hard-delete GC's byte half. No claim ever cites a design key, so the refcount
    guard `erase_if_unreferenced` exists to arbitrate is vacuous here — the caller owns the
    reference decision and this owns row + blob."""
    workspace_id = _ws("delete")
    storage = FsStorage(tmp_path / "store")
    data = b"bytes nobody references any more"
    digest = hashlib.sha256(data).hexdigest()

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn:
            transaction = await conn.begin()
            try:
                await _seed_ws(conn, workspace_id)
                key = await register_design_bytes(
                    conn,
                    storage,
                    workspace_id=workspace_id,
                    data=data,
                    media_type="image/png",
                    source_key=SOURCE_KEY_ASSET,
                )

                assert await delete_design_bytes(
                    conn, storage, workspace_id=workspace_id, sha256=digest
                )
                assert not await storage.exists(key)
                record = await get_artifact(conn, key)
                assert record is not None, "the row survives as the audit trail"
                assert record.erased_at is not None and record.purged_at is not None
                assert not await design_bytes_exist(conn, workspace_id=workspace_id, sha256=digest)

                # Idempotent, and never destructive across tenants.
                assert not await delete_design_bytes(
                    conn, storage, workspace_id=workspace_id, sha256=digest
                )
                assert not await delete_design_bytes(
                    conn, storage, workspace_id=_ws("other"), sha256=digest
                )
            finally:
                await transaction.rollback()

    run_async(scenario())
