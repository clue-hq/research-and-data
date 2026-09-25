"""The ``artifact`` table DAL (PB-B2.2) — snapshot rows + the durable erasure lifecycle.

Plain async functions over ``AsyncConnection`` in the repo's raw-SQL style (the ``clue_spine``
pattern: one implementation will ever exist, so no repository/service layer). The
        table's UNIQUE
``storage_key`` makes :func:`record_artifact` the dedup — identical bytes in one workspace land
on one row, however many times a fetch (or a re-flush of the same sink) records them.

**The lifecycle** (the audit's findings 1/3/4 — upload, erasure, concurrency, rollback, and
resurrection handled by one design):

* The **artifact row is the serialization point**. Writers upsert the row *before* putting the
  blob (:func:`record_artifact` — ``ON CONFLICT DO UPDATE`` takes the row lock and *resurrects*
  an erased row), and erasure decisions read the refcount **under ``SELECT … FOR UPDATE``**
  (:func:`erase_if_unreferenced`), so two concurrent erasures of the last two citers serialize
  — the second recounts after the first commits and sees zero. A concurrent claim insert citing
  the key blocks on the same lock via its FK (``FOR KEY SHARE`` conflicts with ``FOR UPDATE``).
* **Erasure is two-phase.** Phase 1, inside the erasing transaction: ``erased_at`` is stamped
  (the durable intent) and ``source_url`` is nulled (the one potentially-personal metadata
  column — the retained row is then genuinely metadata-only). Phase 2, **after commit**:
  :func:`purge_erased_artifacts` deletes the physical blob and stamps ``purged_at`` — external
  storage is never mutated inside a database transaction, so a rollback can never un-commit a
  claim whose evidence was already destroyed. A crash between the phases leaves
  ``erased_at IS NOT NULL AND purged_at IS NULL``, which the next purge/sweep converges on.
* **Resurrection is explicit, not accidental.** Re-capturing bytes whose row was erased clears
  ``erased_at``/``purged_at`` in :func:`record_artifact` (the row again owns a live blob, put
  *after* the row write); conversely the purge re-checks the refcount under its lock and
  *un-erases* instead of deleting when a claim re-cited the snapshot in the window.
* **Rollback orphans converge.** A transaction that put a blob and then rolled back leaves a
  blob with no row; a retry re-records/re-puts the same content-addressed key, and
  :func:`sweep_orphan_blobs` collects abandoned ones (blobs older than a grace window with no
  ``artifact`` row).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import UtcDatetime
from clue_storage.protocol import StorageBackend, StorageError, artifact_key, content_address


class ArtifactIntegrityError(StorageError):
    """Artifact metadata and physical content do not prove one live content-addressed object."""


class ArtifactRecord(BaseModel):
    """An ``artifact`` row — the DB identity of one stored evidence snapshot (REQ-07)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_id: str
    storage_key: str
    workspace_id: str | None = None
    content_sha256: str
    media_type: str
    size_bytes: int
    source_key: str | None = None
    source_url: str | None = None
    created_at: UtcDatetime
    erased_at: UtcDatetime | None = None
    purged_at: UtcDatetime | None = None
    privacy_erased: bool = False
    expires_at: datetime | None = None


class PurgeResult(BaseModel):
    """The outcome of one :func:`purge_erased_artifacts` pass."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    purged_keys: tuple[str, ...] = ()
    resurrected_keys: tuple[str, ...] = ()


_COLUMNS = (
    "artifact_id, storage_key, workspace_id, content_sha256, media_type, size_bytes, "
    "source_key, source_url, created_at, erased_at, purged_at, privacy_erased, expires_at"
)


async def record_artifact(
    conn: AsyncConnection,
    *,
    storage_key: str,
    workspace_id: str | None,
    content_sha256: str,
    media_type: str,
    size_bytes: int,
    source_key: str | None = None,
    source_url: str | None = None,
) -> ArtifactRecord:
    """Upsert one snapshot row and return the canonical record. **Call before the blob put** —
    the row is the lock that serializes writers against a concurrent erasure.

    An identical live record is reused under ``FOR SHARE``: its metadata needs no mutation,
    and the shared lock still excludes concurrent erasure. Research transactions already hold
    shared locks on their source artifacts; upgrading an unchanged output to an exclusive lock
    can deadlock when two outputs also appear in each other's source sets (r13).

    New records and changed/erased records take the upsert path. On conflict the existing
    metadata wins, but ordinary erasure state is cleared: recording says a live blob (re-)exists
    under this key. Privacy-erased records are never resurrected. Both paths hold a row lock
    until the caller's transaction ends, serializing against erasure and purge.

    **Concurrent duplicate bytes.** ``ON CONFLICT (storage_key)`` names one arbiter index, and
    Postgres' speculative insertion resolves a conflict only on *that* index. The table also
    carries the composite ``artifact_execution_anchor (storage_key, workspace_id)`` unique
    constraint (the FK target every ``(artifact_key, workspace_id)`` evidence citation points at),
    so a writer whose arbiter probe found nothing, but whose composite index insert then collides
    with a *concurrently committed* row, raises a unique violation instead of taking the update
    path. Two real provider calls legitimately return byte-identical responses (the same
    zero-result organization document for two accounts), which crashed two live fleet jobs here.
    The statement therefore runs inside a savepoint and is retried once: by the time the violation
    surfaces the winner's row is committed, so the retry resolves through the arbiter and keeps the
    resurrect/row-lock guarantees above intact.
    """
    live = (
        (
            await conn.execute(
                text(
                    f"SELECT {_COLUMNS} FROM artifact WHERE storage_key=:key "
                    "AND workspace_id IS NOT DISTINCT FROM :ws AND content_sha256=:sha "
                    "AND media_type=:media AND size_bytes=:size "
                    "AND erased_at IS NULL AND purged_at IS NULL AND NOT privacy_erased FOR SHARE"
                ),
                {
                    "key": storage_key,
                    "ws": workspace_id,
                    "sha": content_sha256,
                    "media": media_type,
                    "size": size_bytes,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    if live is not None:
        data = dict(live)
        data["artifact_id"] = str(data["artifact_id"])
        return ArtifactRecord.model_validate(data)

    statement = text(
        "INSERT INTO artifact (storage_key, workspace_id, content_sha256, media_type, "
        "size_bytes, source_key, source_url) "
        "VALUES (:storage_key, :workspace_id, :content_sha256, :media_type, :size_bytes, "
        ":source_key, :source_url) "
        "ON CONFLICT (storage_key) DO UPDATE SET erased_at = NULL, purged_at = NULL "
        "WHERE NOT artifact.privacy_erased"
    )
    parameters = {
        "storage_key": storage_key,
        "workspace_id": workspace_id,
        "content_sha256": content_sha256,
        "media_type": media_type,
        "size_bytes": size_bytes,
        "source_key": source_key,
        "source_url": source_url,
    }
    try:
        async with conn.begin_nested():
            await conn.execute(statement, parameters)
    except IntegrityError:
        await conn.execute(statement, parameters)
    record = await get_artifact(conn, storage_key)
    if record is None:  # pragma: no cover - unreachable inside one transaction
        raise RuntimeError(f"artifact {storage_key!r} vanished during record")
    if record.privacy_erased:
        raise ArtifactIntegrityError("privacy-erased artifact cannot be restored")
    return record


async def get_artifact(conn: AsyncConnection, storage_key: str) -> ArtifactRecord | None:
    result = await conn.execute(
        text(f"SELECT {_COLUMNS} FROM artifact WHERE storage_key = :storage_key"),
        {"storage_key": storage_key},
    )
    row = result.mappings().first()
    if row is None:
        return None
    data = dict(row)
    data["artifact_id"] = str(data["artifact_id"])
    return ArtifactRecord(**data)


async def read_verified_artifact(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    storage_key: str,
    workspace_id: str,
) -> tuple[ArtifactRecord, bytes]:
    """Read a live workspace artifact and verify its row, key, size, and content digest."""

    record = await get_artifact(conn, storage_key)
    if record is None:
        raise ArtifactIntegrityError(f"artifact row is missing for {storage_key!r}")
    if record.workspace_id != workspace_id:
        raise ArtifactIntegrityError("artifact belongs to another workspace")
    if (
        record.erased_at is not None
        or record.purged_at is not None
        or (record.expires_at is not None and record.expires_at <= datetime.now(UTC))
    ):
        raise ArtifactIntegrityError("artifact was erased, expired or purged")
    try:
        data = await storage.get(storage_key)
    except StorageError as exc:
        raise ArtifactIntegrityError("artifact blob is missing") from exc
    digest = content_address(data)
    expected_key = artifact_key(workspace_id, digest)
    if (
        record.content_sha256 != digest
        or record.size_bytes != len(data)
        or record.storage_key != expected_key
        or storage_key != expected_key
    ):
        raise ArtifactIntegrityError(
            "artifact bytes do not match durable content-addressed metadata"
        )
    return record, data


async def live_claim_count(conn: AsyncConnection, storage_key: str) -> int:
    """How many live (non-superseded) claims still cite this snapshot — the DSAR refcount.

    Deliberately counts *all* non-superseded claims regardless of verification status (the
    fail-safe direction: an unverified-but-live claim keeps its evidence). Erasure tombstones
    supersede the claim row, so an erased person's claims drop out of this count.

    **Race warning:** an unlocked count is only advisory. An erasure decision must go through
    :func:`erase_if_unreferenced`, which recounts under the artifact row lock.
    """
    result = await conn.execute(
        text(
            "SELECT count(*) FROM claim WHERE artifact_key = :storage_key AND superseded_by IS NULL"
        ),
        {"storage_key": storage_key},
    )
    return int(result.scalar_one())


async def mark_erased(conn: AsyncConnection, storage_key: str) -> None:
    """Stamp ``erased_at`` (idempotent — the first erasure's timestamp is the audit fact) and
    null ``source_url``, the one metadata column that can itself identify a person (a profile
    URL, a sensitive path/query) — the retained row is then genuinely metadata-only, as the
    migration comment promises. Key/hash/size survive as the audit trail.

    This is phase-1 bookkeeping only; callers wanting the race-free refcount decision use
    :func:`erase_if_unreferenced`, and the physical blob delete is phase 2
    (:func:`purge_erased_artifacts`, after commit)."""
    await conn.execute(
        text(
            "UPDATE artifact SET erased_at = now(), source_url = NULL "
            "WHERE storage_key = :storage_key AND erased_at IS NULL"
        ),
        {"storage_key": storage_key},
    )


async def retain_artifact(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    storage_key: str,
    reference_kind: str,
    reference_id: str,
) -> None:
    """Hold immutable bytes for a durable owner. Explicit privacy erasure always wins.

    A shared lock excludes erasure while allowing concurrent evidence readers to retain the
    same original. Upgrading their existing shared locks to exclusive locks would deadlock.
    Owners release these references when their durable records/grants are retired.
    """
    row = (
        await conn.execute(
            text(
                "SELECT storage_key FROM artifact WHERE storage_key=:key AND workspace_id=:ws "
                "AND erased_at IS NULL AND NOT privacy_erased "
                "AND (expires_at IS NULL OR expires_at>now()) FOR SHARE"
            ),
            {"key": storage_key, "ws": workspace_id},
        )
    ).first()
    if row is None:
        raise ArtifactIntegrityError("artifact is unavailable for retention")
    await conn.execute(
        text(
            "INSERT INTO artifact_reference(workspace_id,reference_kind,reference_id,storage_key) "
            "VALUES (:ws,:kind,:id,:key) ON CONFLICT DO NOTHING"
        ),
        {"ws": workspace_id, "kind": reference_kind, "id": reference_id, "key": storage_key},
    )


async def release_artifacts(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    reference_kind: str,
    reference_id: str,
) -> None:
    """Release one durable owner's retention, without deleting bytes or other owners' grants."""
    await conn.execute(
        text(
            "DELETE FROM artifact_reference WHERE workspace_id=:ws "
            "AND reference_kind=:kind AND reference_id=:id"
        ),
        {"ws": workspace_id, "kind": reference_kind, "id": reference_id},
    )


async def live_reference_count(conn: AsyncConnection, storage_key: str) -> int:
    result = await conn.execute(
        text("SELECT count(*) FROM artifact_reference WHERE storage_key=:key"), {"key": storage_key}
    )
    return await live_claim_count(conn, storage_key) + int(result.scalar_one())


async def erase_if_unreferenced(conn: AsyncConnection, storage_key: str) -> bool:
    """Phase 1 of erasure: under the artifact **row lock**, recount live citers and stamp
    ``erased_at`` iff the count is zero. Returns whether the row was marked (the caller then
    schedules the post-commit :func:`purge_erased_artifacts` for the key).

    The ``FOR UPDATE`` lock is what makes the refcount decision race-free (audit finding 3):
    two concurrent erasures of the final two citers serialize here — the loser blocks, then
    recounts *after* the winner's supersede committed and sees zero; and a concurrent claim
    insert citing this key blocks on the same lock (its FK takes ``FOR KEY SHARE``, which
    conflicts with ``FOR UPDATE``), so the count can never go stale mid-decision. A key with no
    ``artifact`` row (pre-B2 claim, or a never-flushed ref) is a no-op ``False``."""
    locked = await conn.execute(
        text("SELECT erased_at FROM artifact WHERE storage_key = :storage_key FOR UPDATE"),
        {"storage_key": storage_key},
    )
    row = locked.first()
    if row is None:
        return False
    if await live_reference_count(conn, storage_key) != 0:
        return False
    await mark_erased(conn, storage_key)
    return True


async def purge_erased_artifacts(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    keys: tuple[str, ...] | None = None,
) -> PurgeResult:
    """Phase 2 of erasure: physically delete the blobs of erased-but-unpurged rows and stamp
    ``purged_at``. Run in a **fresh transaction after** the transaction that stamped
    ``erased_at`` committed — never inside it (a rollback must not be able to restore a claim
    whose evidence is already destroyed, audit finding 1).

    ``keys=None`` scans every erased-unpurged row (the crash-recovery sweep); a caller that just
    erased passes its own keys. Each row is re-checked under ``FOR UPDATE``:

    * a claim re-cited the snapshot in the window (e.g. a cache-hit writer that stamps
      ``artifact_key`` without re-capturing) → the row is **un-erased** instead of deleted —
      live evidence beats a stale intent;
    * still unreferenced → the blob is deleted while the row lock is held (a concurrent
      :func:`record_artifact` upsert blocks until this commits, then resurrects and re-puts),
      and ``purged_at`` is stamped. ``delete`` is idempotent, so a crash after delete but
      before commit converges on the next pass.
    """
    # Expiry was committed with the source. Reads already refuse it, even if a purge rolls back.
    await conn.execute(
        text(
            "UPDATE artifact SET privacy_erased=true, "
            "erasure_reason=COALESCE(erasure_reason,'retention'), "
            "erased_at=COALESCE(erased_at,now()), source_url=NULL WHERE "
            "expires_at<=now() AND purged_at IS NULL"
        )
    )
    where = "erased_at IS NOT NULL AND purged_at IS NULL"
    params: dict[str, object] = {}
    if keys is not None:
        if not keys:
            return PurgeResult()
        where += " AND storage_key = ANY(:keys)"
        params["keys"] = list(keys)
    result = await conn.execute(
        # Ordered so two concurrent purges lock rows in the same order (no deadlock).
        text(
            f"SELECT storage_key,privacy_erased FROM artifact WHERE {where} "
            "ORDER BY storage_key FOR UPDATE"
        ),
        params,
    )
    purged: list[str] = []
    resurrected: list[str] = []
    for storage_key, privacy_erased in result.all():
        if not privacy_erased and await live_reference_count(conn, storage_key) != 0:
            await conn.execute(
                text(
                    "UPDATE artifact SET erased_at = NULL, purged_at = NULL "
                    "WHERE storage_key = :storage_key"
                ),
                {"storage_key": storage_key},
            )
            resurrected.append(storage_key)
            continue
        await storage.delete(storage_key)
        await conn.execute(
            text("UPDATE artifact SET purged_at = now() WHERE storage_key = :storage_key"),
            {"storage_key": storage_key},
        )
        purged.append(storage_key)
    return PurgeResult(purged_keys=tuple(purged), resurrected_keys=tuple(resurrected))


async def sweep_orphan_blobs(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    grace: timedelta = timedelta(hours=24),
    now: datetime | None = None,
) -> tuple[str, ...]:
    """Delete blobs that have **no** ``artifact`` row and are older than ``grace`` — the
    reconciliation backstop for a rolled-back-and-abandoned upload (the blob was put inside a
    transaction whose row insert rolled back; audit finding 1's residual state). Returns the
    deleted keys.

    Writers record the row *before* putting the blob, so a legitimately in-flight blob's row is
    already inserted (just not yet committed/visible) — the grace window (default 24h, far
    beyond any transaction lifetime) is what keeps this sweep from racing an open transaction.
    Purged rows keep their row forever, so an erased blob's key never reads as an orphan."""
    cutoff = (now or datetime.now(UTC)) - grace
    deleted: list[str] = []
    async for key, last_modified in storage.list_blobs():
        if last_modified >= cutoff:
            continue
        if await get_artifact(conn, key) is not None:
            continue
        await storage.delete(key)
        deleted.append(key)
    return tuple(deleted)
