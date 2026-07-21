"""DB-backed tests for the ``artifact`` table + ``claim.artifact_key`` (PB-B2.2).

The migration battery: content-addressed dedup (UNIQUE storage_key + ON CONFLICT DO NOTHING),
the claim FK, the DSAR refcount read, ``erased_at`` idempotency, and the append-only guard
covering the new provenance column.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_storage import (
    artifact_key,
    content_address,
    get_artifact,
    live_claim_count,
    mark_erased,
    record_artifact,
)
from tests.storage.conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_storage_db")


async def _record(conn: AsyncConnection, data: bytes, workspace_id: str | None = "ws_t"):
    sha = content_address(data)
    key = artifact_key(workspace_id, sha)
    return await record_artifact(
        conn,
        storage_key=key,
        workspace_id=workspace_id,
        content_sha256=sha,
        media_type="text/markdown",
        size_bytes=len(data),
        source_key="firecrawl_site",
        source_url="https://example.com",
    )


async def _insert_claim(conn: AsyncConnection, art_key: str | None) -> str:
    result = await conn.execute(
        text(
            "INSERT INTO claim (entity_id, entity_type, field_key, value_json, source_tier, "
            "extraction_method, evidence_span, confidence, run_id, research_mode, artifact_key) "
            "VALUES (:entity_id, 'account', 'account.recent_funding', "
            "CAST(:value_json AS jsonb), 2, CAST('scrape' AS extraction_method), 'a span', 0.9, "
            ":run_id, 'account_profiling', :artifact_key) RETURNING id"
        ),
        {
            "entity_id": str(uuid.uuid4()),
            "value_json": '{"amount": 1}',
            "run_id": str(uuid.uuid4()),
            "artifact_key": art_key,
        },
    )
    return str(result.scalar_one())


def test_record_round_trip_and_dedup() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            first = await _record(conn, b"the page bytes")
            again = await _record(conn, b"the page bytes")  # identical bytes → same row
            assert again.artifact_id == first.artifact_id
            assert again.created_at == first.created_at
            fetched = await get_artifact(conn, first.storage_key)
            assert fetched is not None and fetched.size_bytes == len(b"the page bytes")
            assert fetched.erased_at is None

    run_async(scenario())


def test_same_bytes_two_workspaces_two_rows() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            a = await _record(conn, b"shared bytes", workspace_id="ws_a")
            b = await _record(conn, b"shared bytes", workspace_id="ws_b")
            assert a.artifact_id != b.artifact_id  # never cross-tenant dedup (ruling 2)

    run_async(scenario())


def test_claim_fk_rejects_unknown_artifact_key() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            with pytest.raises(IntegrityError):
                await _insert_claim(conn, "ws_x/" + "0" * 64)

    run_async(scenario())


def test_live_claim_count_follows_supersession() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            record = await _record(conn, b"evidence page")
            assert await live_claim_count(conn, record.storage_key) == 0
            first = await _insert_claim(conn, record.storage_key)
            second = await _insert_claim(conn, record.storage_key)
            assert await live_claim_count(conn, record.storage_key) == 2
            # Supersede one (a tombstone does exactly this) — it drops out of the refcount.
            await conn.execute(
                text("UPDATE claim SET superseded_by = :new WHERE id = :old"),
                {"new": second, "old": first},
            )
            assert await live_claim_count(conn, record.storage_key) == 1

    run_async(scenario())


def test_mark_erased_is_idempotent() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            record = await _record(conn, b"to erase")
            await mark_erased(conn, record.storage_key)
            stamped = await get_artifact(conn, record.storage_key)
            assert stamped is not None and stamped.erased_at is not None
            await mark_erased(conn, record.storage_key)  # second call keeps the first timestamp
            again = await get_artifact(conn, record.storage_key)
            assert again is not None and again.erased_at == stamped.erased_at

    run_async(scenario())


def test_artifact_key_is_immutable_provenance() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            record = await _record(conn, b"immutable evidence")
            claim_id = await _insert_claim(conn, record.storage_key)
            other = await _record(conn, b"other evidence")
            with pytest.raises(DBAPIError, match="append-only"):
                await conn.execute(
                    text("UPDATE claim SET artifact_key = :key WHERE id = :id"),
                    {"key": other.storage_key, "id": claim_id},
                )

    run_async(scenario())


def test_sha256_shape_check() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            with pytest.raises(IntegrityError, match="artifact_sha256_shape"):
                await record_artifact(
                    conn,
                    storage_key="ws_x/not-a-hash",
                    workspace_id="ws_x",
                    content_sha256="not-a-hash",
                    media_type="text/plain",
                    size_bytes=1,
                )

    run_async(scenario())
