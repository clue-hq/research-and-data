"""DB-backed tests for the ``artifact`` table + ``claim.artifact_key`` (PB-B2.2).

The migration battery: content-addressed dedup (UNIQUE storage_key; the upsert resurrects an
erased row), the claim FK + the structural-tenancy CHECKs, the DSAR refcount read (unlocked view
+ the locked ``erase_if_unreferenced`` decision), the two-phase purge, the orphan-blob sweep,
``erased_at`` idempotency/redaction, and the append-only guard covering the provenance column.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from clue_db import db_lifespan
from clue_storage import (
    ArtifactIntegrityError,
    FsStorage,
    artifact_key,
    content_address,
    erase_if_unreferenced,
    get_artifact,
    live_claim_count,
    mark_erased,
    purge_erased_artifacts,
    record_artifact,
    record_uploaded_artifact,
    retain_artifact,
    sweep_orphan_blobs,
)
from tests.storage.conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_storage_db")


def test_concurrent_readers_retain_shared_evidence_without_lock_upgrade() -> None:
    async def case():
        async with db_lifespan() as engine:
            ws = f"ws_{uuid.uuid4().hex}"
            async with engine.begin() as conn:
                record = await _record(conn, uuid.uuid4().bytes, ws)
            key = record.storage_key
            readers = asyncio.Barrier(3)

            async def retain(index):
                async with engine.begin() as conn:
                    await conn.execute(text("SET LOCAL statement_timeout='5s'"))
                    await conn.execute(
                        text("SELECT storage_key FROM artifact WHERE storage_key=:key FOR SHARE"),
                        {"key": key},
                    )
                    await readers.wait()
                    await retain_artifact(
                        conn,
                        workspace_id=ws,
                        storage_key=key,
                        reference_kind="test_retention",
                        reference_id=str(index),
                    )

            try:
                await asyncio.gather(*(retain(i) for i in range(3)))
                async with engine.begin() as conn:
                    assert not await erase_if_unreferenced(conn, key)
                    assert (
                        await conn.execute(
                            text("SELECT count(*) FROM artifact_reference WHERE storage_key=:key"),
                            {"key": key},
                        )
                    ).scalar_one() == 3
            finally:
                async with engine.begin() as conn:
                    await conn.execute(
                        text("DELETE FROM artifact_reference WHERE storage_key=:key"), {"key": key}
                    )
                    await conn.execute(
                        text("DELETE FROM artifact WHERE storage_key=:key"), {"key": key}
                    )

    run_async(case())


def test_research_snapshots_can_rerecord_each_others_source_without_deadlock() -> None:
    """r13: source SHARE locks must not conflict with re-recording unchanged live bytes.

    Each writer holds the other snapshot as source evidence before persisting its own
    existing content-addressed output. An unconditional upsert upgrades to an exclusive
    row lock and creates a cycle, even with sorted source reads.
    """

    async def case():
        async with db_lifespan() as engine:
            ws = f"ws_{uuid.uuid4().hex}"
            bodies = [uuid.uuid4().bytes, uuid.uuid4().bytes]
            async with engine.begin() as conn:
                records = [await _record(conn, body, ws) for body in bodies]
            readers = asyncio.Barrier(2)

            async def persist(index):
                async with engine.begin() as conn:
                    await conn.execute(text("SET LOCAL statement_timeout='5s'"))
                    await conn.execute(
                        text("SELECT storage_key FROM artifact WHERE storage_key=:key FOR SHARE"),
                        {"key": records[1 - index].storage_key},
                    )
                    await asyncio.wait_for(readers.wait(), timeout=5)
                    repeated = await _record(conn, bodies[index], ws)
                    assert repeated == records[index]

            try:
                outcomes = await asyncio.gather(persist(0), persist(1), return_exceptions=True)
                for outcome in outcomes:
                    if isinstance(outcome, BaseException):
                        raise outcome
            finally:
                async with engine.begin() as conn:
                    await conn.execute(
                        text("DELETE FROM artifact WHERE workspace_id=:ws"), {"ws": ws}
                    )

    run_async(case())


def test_rerecording_live_bytes_still_locks_against_erasure() -> None:
    async def case():
        async with db_lifespan() as engine:
            ws = f"ws_{uuid.uuid4().hex}"
            data = uuid.uuid4().bytes
            async with engine.begin() as conn:
                original = await _record(conn, data, ws)
            key = original.storage_key
            try:
                async with engine.begin() as reader:
                    assert await _record(reader, data, ws) == original
                    # An eraser cannot acquire its exclusive lock while live bytes are reused.
                    with pytest.raises(DBAPIError) as blocked:
                        async with engine.begin() as eraser:
                            await eraser.execute(
                                text(
                                    "SELECT storage_key FROM artifact "
                                    "WHERE storage_key=:key FOR UPDATE NOWAIT"
                                ),
                                {"key": key},
                            )
                    assert blocked.value.orig.sqlstate == "55P03"
                async with engine.begin() as eraser:
                    assert await erase_if_unreferenced(eraser, key)
            finally:
                async with engine.begin() as conn:
                    await conn.execute(
                        text("DELETE FROM artifact WHERE storage_key=:key"), {"key": key}
                    )

    run_async(case())


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


async def _insert_claim(
    conn: AsyncConnection, art_key: str | None, *, workspace_id: str | None = None
) -> str:
    result = await conn.execute(
        text(
            "INSERT INTO claim (entity_id, entity_type, field_key, value_json, source_tier, "
            "extraction_method, evidence_span, confidence, run_id, research_mode, artifact_key, "
            "workspace_id, reuse_scope) "
            "VALUES (:entity_id, 'account', 'account.recent_funding', "
            "CAST(:value_json AS jsonb), 2, CAST('scrape' AS extraction_method), 'a span', 0.9, "
            ":run_id, 'account_profiling', :artifact_key, :workspace_id, "
            "CAST(:reuse_scope AS reuse_scope)) RETURNING id"
        ),
        {
            "entity_id": str(uuid.uuid4()),
            "value_json": '{"amount": 1}',
            "run_id": str(uuid.uuid4()),
            "artifact_key": art_key,
            "workspace_id": workspace_id,
            # The 0008 CHECK pairs the scope with the tenancy: tenant-bound ⟺ tenant_private.
            "reuse_scope": "tenant_private" if workspace_id is not None else "public_footprint",
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


def test_concurrent_writers_of_identical_bytes_all_record_one_row() -> None:
    """The live crash: two provider operations returning byte-identical responses.

    ``ON CONFLICT (storage_key)`` arbitrates one index; the composite
    ``artifact_execution_anchor (storage_key, workspace_id)`` is a second unique index that
    speculative insertion does **not** arbitrate, so a writer racing a concurrently-committing
    twin used to die with ``duplicate key value violates unique constraint
    "artifact_execution_anchor"``. Live, two parallel ``enrich_account`` calls in one model wave
    both resolved the same account's Sumble organization document, recorded the identical bytes on
    their own connections, and the loser suspended its whole job.

    Every writer must land on the one content-addressed row. Each round is a real commit race, so
    this test is green-by-construction under the fix and red under the old single-arbiter write.
    """

    writers = 12
    rounds = 4

    async def race(engine: AsyncEngine) -> None:
        data = uuid.uuid4().bytes
        workspace_id = f"ws_{uuid.uuid4().hex}"
        sha = content_address(data)
        key = artifact_key(workspace_id, sha)
        start = asyncio.Barrier(writers)

        async def writer() -> str:
            async with engine.connect() as conn:
                await conn.begin()
                await start.wait()
                record = await record_artifact(
                    conn,
                    storage_key=key,
                    workspace_id=workspace_id,
                    content_sha256=sha,
                    media_type="application/json",
                    size_bytes=len(data),
                    source_key="sumble_organizations",
                    source_url="https://api.sumble.com/v9/organizations",
                )
                await conn.commit()
                return record.artifact_id

        recorded = await asyncio.gather(*(writer() for _ in range(writers)))
        assert len(set(recorded)) == 1  # one row, whoever won the race
        async with engine.begin() as conn:
            row = await get_artifact(conn, key)
            assert row is not None and row.artifact_id == recorded[0]
            await conn.execute(text("DELETE FROM artifact WHERE storage_key = :k"), {"k": key})

    async def scenario() -> None:
        async with db_lifespan() as engine:
            for _ in range(rounds):
                await race(engine)

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


# --- structural tenancy (audit finding 2) --------------------------------------


def test_artifact_row_cannot_lie_about_its_scope() -> None:
    """The storage key encodes the workspace; a row claiming a different scope is rejected."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            sha = content_address(b"scoped bytes")
            with pytest.raises(IntegrityError, match="artifact_key_encodes_scope"):
                await record_artifact(
                    conn,
                    storage_key=artifact_key("ws_a", sha),
                    workspace_id="ws_b",  # contradicts the key's scope segment
                    content_sha256=sha,
                    media_type="text/plain",
                    size_bytes=len(b"scoped bytes"),
                )

    run_async(scenario())


def test_claim_cannot_cite_another_workspaces_artifact() -> None:
    """The audit's reproduced leak: a private claim in workspace B referencing workspace A's
    snapshot must be unrepresentable, not caller-discipline."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            record = await _record(conn, b"tenant A evidence", workspace_id="ws_a")
            with pytest.raises(IntegrityError, match="claim_artifact_scope_compatible"):
                await _insert_claim(conn, record.storage_key, workspace_id="ws_b")

    run_async(scenario())


def test_claim_scope_compatible_citations_are_allowed() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            own = await _record(conn, b"own-tenant evidence", workspace_id="ws_a")
            shared = await _record(conn, b"public evidence", workspace_id=None)
            # Own-workspace and public snapshots are citable by a ws_a claim…
            await _insert_claim(conn, own.storage_key, workspace_id="ws_a")
            await _insert_claim(conn, shared.storage_key, workspace_id="ws_a")
            # …and a public-footprint claim may cite its capture-context workspace's snapshot
            # (one fetch backs both public and private claims; serving is the presign gate's job).
            await _insert_claim(conn, own.storage_key, workspace_id=None)

    run_async(scenario())


# --- the erasure lifecycle (audit findings 1/3/4) -------------------------------


def test_record_resurrects_an_erased_row() -> None:
    """Finding 4: re-capturing identical bytes must clear the erased/purged state — never a
    physically-present blob whose row still says erased."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            record = await _record(conn, b"recaptured bytes")
            await mark_erased(conn, record.storage_key)
            await conn.execute(
                text("UPDATE artifact SET purged_at = now() WHERE storage_key = :k"),
                {"k": record.storage_key},
            )
            revived = await _record(conn, b"recaptured bytes")
            assert revived.artifact_id == record.artifact_id  # same row, resurrected
            assert revived.erased_at is None
            assert revived.purged_at is None

    run_async(scenario())


async def _record_uploaded(conn: AsyncConnection, data: bytes, workspace_id: str = "ws_t"):
    sha = content_address(data)
    return await record_uploaded_artifact(
        conn,
        storage_key=artifact_key(workspace_id, sha),
        workspace_id=workspace_id,
        content_sha256=sha,
        media_type="text/markdown",
        size_bytes=len(data),
    )


def test_recording_a_blob_put_beforehand_says_when_it_brought_an_erased_row_back() -> None:
    """W2-15 option B: a writer that uploaded BEFORE recording must upload again, under the row
    lock, whenever its recording resurrected an erased or purged row — a purge may have deleted
    the blob between the upload and the recording."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            fresh, restored = await _record_uploaded(conn, b"new bytes")
            assert restored is False and fresh.erased_at is None

            live, restored = await _record_uploaded(conn, b"new bytes")
            assert restored is False and live.artifact_id == fresh.artifact_id

            await mark_erased(conn, fresh.storage_key)
            revived, restored = await _record_uploaded(conn, b"new bytes")
            assert restored is True and revived.erased_at is None

            await mark_erased(conn, fresh.storage_key)
            await conn.execute(
                text("UPDATE artifact SET purged_at = now() WHERE storage_key = :k"),
                {"k": fresh.storage_key},
            )
            revived, restored = await _record_uploaded(conn, b"new bytes")
            assert restored is True and revived.purged_at is None

    run_async(scenario())


def test_recording_a_blob_put_beforehand_refuses_a_privacy_erased_row() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            record, _ = await _record_uploaded(conn, b"private bytes")
            await conn.execute(
                text(
                    "UPDATE artifact SET privacy_erased=true, erasure_reason='privacy', "
                    "erased_at=now() WHERE storage_key=:k"
                ),
                {"k": record.storage_key},
            )
            with pytest.raises(ArtifactIntegrityError):
                await _record_uploaded(conn, b"private bytes")

    run_async(scenario())


def test_the_purge_sweep_removes_a_file_written_back_after_a_privacy_purge(
    tmp_path: object,
) -> None:
    """Review M-4: a writer that uploads before recording (W2-15 option B) can, in a crash
    window, put bytes back just after their row was privacy-purged. Nothing records them again,
    and the orphan sweep skips keys that have a row, so the purge sweep re-deletes the files of
    recently privacy-purged rows (deleting a missing file is a no-op)."""

    async def scenario() -> None:
        storage = FsStorage(tmp_path)  # type: ignore[arg-type]
        async with rollback_conn() as conn:
            record = await _record(conn, b"withdrawn person")
            await conn.execute(
                text(
                    "UPDATE artifact SET privacy_erased=true, erasure_reason='privacy', "
                    "erased_at=now(), purged_at=now() WHERE storage_key=:k"
                ),
                {"k": record.storage_key},
            )
            await storage.put(record.storage_key, b"withdrawn person", media_type="text/markdown")
            await purge_erased_artifacts(conn, storage)
            assert not await storage.exists(record.storage_key)

    run_async(scenario())


def test_mark_erased_nulls_source_url() -> None:
    """Finding 7: the retained audit row must be genuinely metadata-only — ``source_url`` can
    identify a person (profile URL, sensitive path/query) and must not survive erasure."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            record = await _record(conn, b"personal page")
            assert record.source_url is not None
            await mark_erased(conn, record.storage_key)
            erased = await get_artifact(conn, record.storage_key)
            assert erased is not None and erased.erased_at is not None
            assert erased.source_url is None

    run_async(scenario())


def test_erase_if_unreferenced_decides_under_the_row_lock() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            record = await _record(conn, b"refcounted evidence")
            claim_id = await _insert_claim(conn, record.storage_key)
            assert not await erase_if_unreferenced(conn, record.storage_key)  # live citer
            await conn.execute(
                text("UPDATE claim SET superseded_by = :new WHERE id = :old"),
                {"new": await _insert_claim(conn, None), "old": claim_id},
            )
            assert await erase_if_unreferenced(conn, record.storage_key)  # last citer gone
            stamped = await get_artifact(conn, record.storage_key)
            assert stamped is not None and stamped.erased_at is not None
            # A key with no artifact row (pre-B2 claim ref) is a no-op False.
            assert not await erase_if_unreferenced(conn, "ws_t/" + "0" * 64)

    run_async(scenario())


def test_purge_deletes_blob_and_stamps_purged_at(tmp_path: object) -> None:
    async def scenario() -> None:
        storage = FsStorage(str(tmp_path))
        async with rollback_conn() as conn:
            record = await _record(conn, b"blob to purge")
            await storage.put(record.storage_key, b"blob to purge", media_type="text/markdown")
            await mark_erased(conn, record.storage_key)

            result = await purge_erased_artifacts(conn, storage, keys=(record.storage_key,))
            assert result.purged_keys == (record.storage_key,)
            assert not await storage.exists(record.storage_key)
            purged = await get_artifact(conn, record.storage_key)
            assert purged is not None and purged.purged_at is not None

            # Idempotent: a second pass finds nothing erased-unpurged.
            again = await purge_erased_artifacts(conn, storage, keys=(record.storage_key,))
            assert again.purged_keys == () and again.resurrected_keys == ()

    run_async(scenario())


def test_purge_resurrects_a_recited_row_instead_of_deleting(tmp_path: object) -> None:
    """A claim re-cited the snapshot between the erasure mark and the purge (e.g. a cache-hit
    writer): live evidence beats the stale intent — the purge un-erases rather than deletes."""

    async def scenario() -> None:
        storage = FsStorage(str(tmp_path))
        async with rollback_conn() as conn:
            record = await _record(conn, b"re-cited blob")
            await storage.put(record.storage_key, b"re-cited blob", media_type="text/markdown")
            await mark_erased(conn, record.storage_key)
            await _insert_claim(conn, record.storage_key)  # the re-citation

            result = await purge_erased_artifacts(conn, storage, keys=(record.storage_key,))
            assert result.resurrected_keys == (record.storage_key,)
            assert await storage.exists(record.storage_key)  # blob kept
            revived = await get_artifact(conn, record.storage_key)
            assert revived is not None and revived.erased_at is None

    run_async(scenario())


def test_sweep_orphan_blobs_collects_only_aged_rowless_blobs(tmp_path: object) -> None:
    async def scenario() -> None:
        storage = FsStorage(str(tmp_path))
        async with rollback_conn() as conn:
            recorded = await _record(conn, b"row-backed blob")
            await storage.put(recorded.storage_key, b"row-backed blob", media_type="text/plain")
            orphan_key = artifact_key("ws_t", content_address(b"rolled-back blob"))
            await storage.put(orphan_key, b"rolled-back blob", media_type="text/plain")

            # Younger than the grace window: nothing is touched (could be an open transaction).
            assert await sweep_orphan_blobs(conn, storage) == ()
            # Past the grace window: only the row-less orphan goes.
            future = datetime.now(UTC) + timedelta(hours=48)
            deleted = await sweep_orphan_blobs(conn, storage, now=future)
            assert deleted == (orphan_key,)
            assert await storage.exists(recorded.storage_key)
            assert not await storage.exists(orphan_key)

    run_async(scenario())
