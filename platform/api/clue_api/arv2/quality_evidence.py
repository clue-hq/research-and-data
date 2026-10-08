"""Durable originals, scoped grants and bounded selective reads for research specialists.

A source descriptor is provenance, not an entity verdict. Only trusted acquisition code creates
sources. Agent briefs and catalog descriptions never pass through this writer as web evidence.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.evidence_paths import INDEX_PATH, SOURCE_PATH, source_path
from clue_api.arv2.research_operations import OperationScope, job_available
from clue_obs import critical_section, get_logger
from clue_storage import (
    ArtifactIntegrityError,
    StorageBackend,
    artifact_key,
    content_address,
    read_verified_artifact,
    record_artifact,
    record_uploaded_artifact,
    retain_artifact,
    verify_artifact_bytes,
)

log = get_logger(__name__)
SourceKind = Literal[
    "web_snapshot",
    "provider_record",
    "research_report",
    "transcript",
    "seller_document",
    "acquisition_gap",
]
Disposition = Literal["written", "reused", "conflict", "excluded", "gap", "unprocessed"]


class EvidenceUnavailable(ValueError):
    """Recoverable refusal; list the current granted manifest rather than inventing another ID."""


class SourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_id: UUID
    workspace_id: str
    run_id: UUID
    account_id: UUID
    job_id: UUID
    subject_id: UUID
    revision: int
    kind: SourceKind
    artifact_key: str
    artifact_sha256: str
    byte_size: int
    media_type: str
    original_key: str | None
    source_url: str | None
    observed_at: datetime
    ledger_id: UUID | None
    operation_id: UUID | None
    origin_locator: str
    normalizer_version: str
    metadata: dict[str, JsonValue]


@dataclass(frozen=True)
class EvidenceGrant:
    scope: OperationScope
    consumer_id: UUID
    grant_id: UUID


def _params(scope: OperationScope) -> dict[str, object]:
    return {
        "ws": scope.workspace_id,
        "run": scope.run_id,
        "account": scope.account_id,
        "job": scope.job_id,
    }


async def _subject(conn: AsyncConnection, scope: OperationScope) -> UUID:
    if not await job_available(conn, scope):
        raise EvidenceUnavailable("research authority unavailable")
    row = (
        (
            await conn.execute(
                text("""
      SELECT COALESCE(subject_entity_id,account_entity_id) AS subject_id,input_refs
      FROM arv2_research_job WHERE job_id=:job AND workspace_id=:ws
        AND run_id=:run AND account_entity_id=:account FOR SHARE
    """),
                _params(scope),
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None or (row["input_refs"] or {}).get("privacy_stopped"):
        raise EvidenceUnavailable("research authority unavailable")
    return UUID(str(row["subject_id"]))


@dataclass(frozen=True)
class PreparedSource:
    """A source whose bytes are stored and retained but not yet published (no revision yet).

    ``existing`` is set when the deterministic source id was already recorded; otherwise
    ``pending`` holds every ``SourceRef`` field except ``revision``.
    """

    existing: SourceRef | None
    pending: Mapping[str, Any] | None


async def _existing_source(conn: AsyncConnection, sid: UUID) -> SourceRef | None:
    row = (
        (
            await conn.execute(
                text("SELECT * FROM arv2_evidence_source WHERE source_id=:id"), {"id": sid}
            )
        )
        .mappings()
        .one_or_none()
    )
    return None if row is None else SourceRef.model_validate(dict(row))


#: Source files of one acquisition uploaded at once (W2-16). Each is a storage round trip that
#: used to run one after another inside the open transaction.
UPLOAD_CONCURRENCY = 16


@dataclass(frozen=True)
class SourceSpec:
    """One source to prepare: the arguments of :func:`prepare_source`."""

    kind: SourceKind
    body: str | Mapping[str, Any] | list[Any]
    original_key: str | None
    origin_locator: str
    observed_at: datetime
    source_url: str | None = None
    ledger_id: UUID | None = None
    operation_id: UUID | None = None
    metadata: Mapping[str, JsonValue] | None = None
    normalizer_version: str = "v1"


def source_file(scope: OperationScope, spec: SourceSpec) -> tuple[str, bytes, str]:
    """The storage key, bytes and media type a source's file is stored under."""
    body = spec.body
    raw = (
        body if isinstance(body, str) else json.dumps(body, sort_keys=True, separators=(",", ":"))
    ).encode()
    media = "text/plain" if isinstance(body, str) else "application/json"
    return artifact_key(scope.workspace_id, content_address(raw)), raw, media


async def prepare_source(
    conn: AsyncConnection,
    storage: StorageBackend,
    scope: OperationScope,
    *,
    kind: SourceKind,
    body: str | Mapping[str, Any] | list[Any],
    original_key: str | None,
    origin_locator: str,
    observed_at: datetime,
    source_url: str | None = None,
    ledger_id: UUID | None = None,
    operation_id: UUID | None = None,
    metadata: Mapping[str, JsonValue] | None = None,
    normalizer_version: str = "v1",
) -> PreparedSource:
    """Store, verify and retain one source's bytes WITHOUT the account-wide manifest lock.

    One source of :func:`prepare_sources`.
    """
    (prepared,) = await prepare_sources(
        conn,
        storage,
        scope,
        [
            SourceSpec(
                kind=kind,
                body=body,
                original_key=original_key,
                origin_locator=origin_locator,
                observed_at=observed_at,
                source_url=source_url,
                ledger_id=ledger_id,
                operation_id=operation_id,
                metadata=metadata,
                normalizer_version=normalizer_version,
            )
        ],
    )
    return prepared


async def prepare_sources(
    conn: AsyncConnection,
    storage: StorageBackend,
    scope: OperationScope,
    specs: Sequence[SourceSpec],
    *,
    originals: Mapping[str, bytes] | None = None,
    uploaded: Collection[str] = frozenset(),
) -> tuple[PreparedSource, ...]:
    """Store, verify and retain sources' bytes WITHOUT the account-wide manifest lock, in order.

    Every artifact row is still recorded before its upload (the storage rule); only publication —
    the revision and the ``arv2_evidence_source`` row — needs the account lock
    (:func:`publish_sources`). Research slowness fix 2026-10-03: acquisition saves many sources in
    one transaction, and taking the lock per source held it across every later upload.

    W2-16: the uploads run together (``UPLOAD_CONCURRENCY`` at a time) instead of one after
    another, and each original is verified once per batch — from ``originals`` (bytes the caller
    has just stored, checked against their row without a download) when present. Retention still
    holds every artifact lock before an original is checked and linked, so erasure cannot slip
    between check and link.

    ``uploaded`` names source files the caller already put before this transaction (W2-15
    option B, :func:`~clue_api.arv2.quality_acquisition.upload_sources_early`). Their rows are
    recorded with :func:`record_uploaded_artifact` and they are not uploaded again — unless the
    recording brought an erased or purged row back, when a purge may have deleted the file after
    the early upload, so it is put again here under the row lock. A file whose row turns out to
    be privacy-erased is deleted before the refusal propagates.
    """
    if not specs:
        return ()
    subject = await _subject(conn, scope)
    planned: list[PreparedSource | dict[str, Any]] = []
    uploads: dict[str, tuple[bytes, str]] = {}
    for spec in specs:
        key, raw, media = source_file(scope, spec)
        sha = key.rsplit("/", 1)[1]
        identity = json.dumps(
            [
                str(scope.job_id),
                str(spec.ledger_id),
                str(spec.operation_id),
                spec.original_key,
                spec.origin_locator,
                spec.kind,
                spec.source_url,
                sha,
                spec.normalizer_version,
            ],
            separators=(",", ":"),
        )
        sid = uuid5(NAMESPACE_URL, "research-source:" + identity)
        existing = await _existing_source(conn, sid)
        if existing is not None:
            await _body(conn, storage, existing)
            planned.append(PreparedSource(existing=existing, pending=None))
            continue
        if key in uploaded:
            try:
                _, restored = await record_uploaded_artifact(
                    conn,
                    storage_key=key,
                    workspace_id=scope.workspace_id,
                    content_sha256=sha,
                    media_type=media,
                    size_bytes=len(raw),
                )
            except ArtifactIntegrityError:
                await storage.delete(key)
                raise
            if restored:
                uploads.setdefault(key, (raw, media))
        else:
            await record_artifact(
                conn,
                storage_key=key,
                workspace_id=scope.workspace_id,
                content_sha256=sha,
                media_type=media,
                size_bytes=len(raw),
            )
            uploads.setdefault(key, (raw, media))
        planned.append(
            {
                "source_id": sid,
                "workspace_id": scope.workspace_id,
                "run_id": scope.run_id,
                "account_id": scope.account_id,
                "job_id": scope.job_id,
                "subject_id": subject,
                "kind": spec.kind,
                "artifact_key": key,
                "artifact_sha256": sha,
                "byte_size": len(raw),
                "media_type": media,
                "original_key": spec.original_key,
                "source_url": spec.source_url,
                "observed_at": spec.observed_at,
                "ledger_id": spec.ledger_id,
                "operation_id": spec.operation_id,
                "origin_locator": spec.origin_locator,
                "normalizer_version": spec.normalizer_version,
                "metadata": dict(spec.metadata or {}),
            }
        )
    gate = asyncio.Semaphore(UPLOAD_CONCURRENCY)

    async def upload(key: str, raw: bytes, media: str) -> None:
        async with gate:
            await storage.put(key, raw, media_type=media)

    outcomes = await asyncio.gather(
        *(upload(key, raw, media) for key, (raw, media) in uploads.items()),
        return_exceptions=True,
    )
    if failure := next((o for o in outcomes if isinstance(o, BaseException)), None):
        raise failure
    pending = [p for p in planned if isinstance(p, dict)]
    for item in pending:
        original = item["original_key"]
        for retained in sorted({item["artifact_key"], *([original] if original else [])}):
            await retain_artifact(
                conn,
                workspace_id=scope.workspace_id,
                storage_key=retained,
                reference_kind="research_source",
                reference_id=str(item["source_id"]),
            )
    verified: set[str] = set()
    for item in pending:
        original, key = item["original_key"], item["artifact_key"]
        if not original or original == key:
            continue
        if original not in verified:
            # Retention above holds both artifact locks; erasure cannot slip between check and link.
            held = (originals or {}).get(original)
            if held is not None:
                await verify_artifact_bytes(
                    conn, storage_key=original, workspace_id=scope.workspace_id, data=held
                )
            else:
                await read_verified_artifact(
                    conn, storage, workspace_id=scope.workspace_id, storage_key=original
                )
            verified.add(original)
        await conn.execute(
            text(
                "INSERT INTO artifact_derivation(workspace_id,parent_key,child_key) "
                "VALUES(:ws,:parent,:child) ON CONFLICT DO NOTHING"
            ),
            {"ws": scope.workspace_id, "parent": original, "child": key},
        )
    return tuple(
        p if isinstance(p, PreparedSource) else PreparedSource(existing=None, pending=p)
        for p in planned
    )


async def publish_sources(
    conn: AsyncConnection, scope: OperationScope, prepared: Sequence[PreparedSource]
) -> tuple[SourceRef, ...]:
    """Publish prepared sources: one account-lock acquisition, revisions in the given order."""
    if all(item.existing is not None for item in prepared):
        return tuple(item.existing for item in prepared if item.existing is not None)
    params = _params(scope)
    refs: list[SourceRef] = []
    with critical_section("arv2.evidence.publish", job_id=str(scope.job_id), sources=len(prepared)):
        await conn.execute(
            text(
                "INSERT INTO arv2_evidence_manifest(workspace_id,run_id,account_id) "
                "VALUES(:ws,:run,:account) ON CONFLICT DO NOTHING"
            ),
            params,
        )
        # One account's sequence lock gives manifest revision a real publication order.
        await conn.execute(
            text(
                "SELECT revision FROM arv2_evidence_manifest WHERE workspace_id=:ws "
                "AND run_id=:run AND account_id=:account FOR UPDATE"
            ),
            params,
        )
        for item in prepared:
            if item.existing is not None:
                refs.append(item.existing)
                continue
            assert item.pending is not None
            already = await _existing_source(conn, item.pending["source_id"])
            if already is not None:  # published by a concurrent save while this one prepared
                refs.append(already)
                continue
            revision = (
                await conn.execute(
                    text(
                        "UPDATE arv2_evidence_manifest SET revision=revision+1 "
                        "WHERE workspace_id=:ws AND run_id=:run AND account_id=:account "
                        "RETURNING revision"
                    ),
                    params,
                )
            ).scalar_one()
            ref = SourceRef(revision=revision, **item.pending)
            values = ref.model_dump()
            values["metadata"] = json.dumps(values["metadata"])
            columns = ",".join(values)
            binds = ",".join(
                "CAST(:metadata AS jsonb)" if k == "metadata" else ":" + k for k in values
            )
            await conn.execute(
                text(f"INSERT INTO arv2_evidence_source({columns}) VALUES({binds})"), values
            )
            log.info(
                "arv2.evidence_recorded",
                source_id=str(ref.source_id),
                job_id=str(scope.job_id),
                revision=revision,
                ledger_id=str(ref.ledger_id) if ref.ledger_id else None,
                kind=ref.kind,
            )
            refs.append(ref)
    return tuple(refs)


async def persist_source(
    conn: AsyncConnection,
    storage: StorageBackend,
    scope: OperationScope,
    *,
    kind: SourceKind,
    body: str | Mapping[str, Any] | list[Any],
    original_key: str | None,
    origin_locator: str,
    observed_at: datetime,
    source_url: str | None = None,
    ledger_id: UUID | None = None,
    operation_id: UUID | None = None,
    metadata: Mapping[str, JsonValue] | None = None,
    normalizer_version: str = "v1",
) -> SourceRef:
    """Trusted acquisition only. Commit before returning this handle to an agent.

    A provider report and its individual pages are separate descriptors; repeat observations have
    distinct ledger IDs even when bytes match. Re-draining one observation reuses its source ID.
    One source: :func:`prepare_source`, then :func:`publish_sources`.
    """
    prepared = await prepare_source(
        conn,
        storage,
        scope,
        kind=kind,
        body=body,
        original_key=original_key,
        origin_locator=origin_locator,
        observed_at=observed_at,
        source_url=source_url,
        ledger_id=ledger_id,
        operation_id=operation_id,
        metadata=metadata,
        normalizer_version=normalizer_version,
    )
    (ref,) = await publish_sources(conn, scope, (prepared,))
    return ref


async def grant_manifest(
    conn: AsyncConnection,
    scope: OperationScope,
    *,
    consumer_id: UUID,
) -> EvidenceGrant:
    await _subject(conn, scope)
    revision = (
        await conn.execute(
            text(
                "SELECT revision FROM arv2_evidence_manifest "
                "WHERE workspace_id=:ws AND run_id=:run AND account_id=:account"
            ),
            _params(scope),
        )
    ).scalar_one_or_none() or 0
    gid = uuid5(NAMESPACE_URL, f"research-grant:{scope.job_id}:{consumer_id}:{revision}")
    await conn.execute(
        text(
            "INSERT INTO arv2_evidence_grant(grant_id,workspace_id,run_id,account_id,"
            "job_id,consumer_id,revision) VALUES(:id,:ws,:run,:account,:job,:consumer,:revision) "
            "ON CONFLICT DO NOTHING"
        ),
        dict(_params(scope), id=gid, consumer=consumer_id, revision=revision),
    )
    return EvidenceGrant(scope, consumer_id, gid)


async def revoke_grant(conn: AsyncConnection, grant: EvidenceGrant) -> None:
    await conn.execute(
        text(
            "UPDATE arv2_evidence_grant SET revoked_at=COALESCE(revoked_at,now()) "
            "WHERE grant_id=:id AND workspace_id=:ws AND job_id=:job AND consumer_id=:consumer"
        ),
        dict(_params(grant.scope), id=grant.grant_id, consumer=grant.consumer_id),
    )
    log.info("arv2.evidence_grant_revoked", grant_id=str(grant.grant_id))


async def _grant(conn: AsyncConnection, grant: EvidenceGrant) -> tuple[int, UUID]:
    subject = await _subject(conn, grant.scope)
    revision = (
        await conn.execute(
            text(
                "SELECT revision FROM arv2_evidence_grant "
                "WHERE grant_id=:id AND workspace_id=:ws AND run_id=:run AND account_id=:account "
                "AND job_id=:job AND consumer_id=:consumer AND revoked_at IS NULL FOR SHARE"
            ),
            dict(_params(grant.scope), id=grant.grant_id, consumer=grant.consumer_id),
        )
    ).scalar_one_or_none()
    if revision is None:
        raise EvidenceUnavailable("grant unavailable; ask the parent for a current evidence grant")
    return int(revision), subject


async def authorize_grant(conn: AsyncConnection, grant: EvidenceGrant) -> None:
    """Revalidate a capability even when serving an idempotent mutation receipt."""
    await _grant(conn, grant)


async def list_sources(
    conn: AsyncConnection,
    grant: EvidenceGrant,
    *,
    after: int = 0,
    limit: int = 30,
    operation_id: UUID | None = None,
) -> dict[str, Any]:
    revision, subject = await _grant(conn, grant)
    if after < 0:
        raise ValueError("invalid evidence page bounds")
    rows = (
        (
            await conn.execute(
                text(
                    "SELECT * FROM arv2_evidence_source WHERE workspace_id=:ws "
                    "AND run_id=:run AND account_id=:account AND revision>:after AND "
                    "revision<=:revision "
                    "AND (CAST(:operation AS uuid) IS NULL OR operation_id=:operation) "
                    "AND (:subject=account_id OR subject_id IN (:subject,account_id)) "
                    "ORDER BY revision LIMIT :limit"
                ),
                dict(
                    _params(grant.scope),
                    after=after,
                    operation=operation_id,
                    revision=revision,
                    subject=subject,
                    limit=limit + 1 if limit > 0 else None,
                ),
            )
        )
        .mappings()
        .all()
    )
    selected = [SourceRef.model_validate(dict(r)) for r in (rows[:limit] if limit > 0 else rows)]
    keys = {s.artifact_key for s in selected} | {s.original_key for s in selected if s.original_key}
    available = (
        set(
            (
                await conn.execute(
                    text(
                        "SELECT storage_key FROM artifact WHERE workspace_id=:ws "
                        "AND storage_key=ANY(:keys) AND erased_at IS NULL AND NOT privacy_erased "
                        "AND (expires_at IS NULL OR expires_at>now()) "
                        "ORDER BY storage_key FOR SHARE"
                    ),
                    {"ws": grant.scope.workspace_id, "keys": sorted(keys)},
                )
            )
            .scalars()
            .all()
        )
        if keys
        else set()
    )
    return {
        "revision": revision,
        "sources": [
            dict(s.model_dump(mode="json"), path=source_path(s.model_dump()), available=True)
            if s.artifact_key in available
            and (s.original_key is None or s.original_key in available)
            else {"source_id": str(s.source_id), "revision": s.revision, "available": False}
            for s in selected
        ],
        "next_after": selected[-1].revision if limit > 0 and len(rows) > limit else None,
    }


async def resolve_source(
    conn: AsyncConnection,
    grant: EvidenceGrant,
    source_id: UUID | str,
) -> SourceRef:
    revision, subject = await _grant(conn, grant)
    requested_path = str(source_id) if str(source_id).startswith("/evidence/") else None
    path_match = SOURCE_PATH.fullmatch(requested_path) if requested_path else None
    if requested_path and not path_match:
        raise EvidenceUnavailable(f"Invalid evidence path; copy an exact path from {INDEX_PATH}.")
    number = int(path_match[1]) if path_match else None
    if number is not None and number > 2_147_483_647:
        raise EvidenceUnavailable(f"Invalid source number; copy an exact path from {INDEX_PATH}.")
    try:
        identifier = None if path_match else UUID(str(source_id))
    except ValueError as exc:
        raise EvidenceUnavailable(f"Invalid source reference; read {INDEX_PATH}.") from exc
    row = (
        (
            await conn.execute(
                text(
                    "SELECT * FROM arv2_evidence_source WHERE "
                    "((CAST(:id AS uuid) IS NOT NULL AND source_id=CAST(:id AS uuid)) OR "
                    "(CAST(:number AS integer) IS NOT NULL AND revision=CAST(:number AS integer))) "
                    "AND workspace_id=:ws AND run_id=:run AND account_id=:account AND "
                    "revision<=:revision "
                    "AND (:subject=account_id OR subject_id IN (:subject,account_id))"
                ),
                dict(
                    _params(grant.scope),
                    id=identifier,
                    number=number,
                    revision=revision,
                    subject=subject,
                ),
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise EvidenceUnavailable(
            f"Source unavailable in this evidence view; read {INDEX_PATH} "
            "and copy its exact path. Report a listed path that fails."
        )
    ref = SourceRef.model_validate(dict(row))
    if requested_path and requested_path != source_path(ref.model_dump()):
        raise EvidenceUnavailable(
            f"Source name does not match; copy its exact path from {INDEX_PATH}."
        )
    return ref


async def _body(conn: AsyncConnection, storage: StorageBackend, ref: SourceRef) -> bytes:
    segments_key = ref.metadata.get("segments_key") if ref.kind == "transcript" else None
    keys = sorted(
        {
            ref.artifact_key,
            *([ref.original_key] if ref.original_key else []),
            *([segments_key] if isinstance(segments_key, str) else []),
        }
    )
    locked = (
        (
            await conn.execute(
                text(
                    "SELECT storage_key FROM artifact WHERE storage_key=ANY(:keys) "
                    "AND workspace_id=:ws "
                    "AND erased_at IS NULL AND NOT privacy_erased "
                    "AND (expires_at IS NULL OR expires_at>now()) ORDER BY storage_key FOR SHARE"
                ),
                {"keys": keys, "ws": ref.workspace_id},
            )
        )
        .scalars()
        .all()
    )
    if len(locked) != len(keys):
        raise ArtifactIntegrityError("source or its original is unavailable")
    if ref.original_key:
        await read_verified_artifact(
            conn, storage, workspace_id=ref.workspace_id, storage_key=ref.original_key
        )
    record, raw = await read_verified_artifact(
        conn, storage, workspace_id=ref.workspace_id, storage_key=ref.artifact_key
    )
    if record.content_sha256 != ref.artifact_sha256:
        raise ArtifactIntegrityError("source descriptor digest mismatch")
    return raw


async def read_source(
    conn: AsyncConnection,
    storage: StorageBackend,
    grant: EvidenceGrant,
    source_id: UUID,
    *,
    start: int = 0,
    limit: int = 0,
) -> dict[str, Any]:
    if start < 0:
        raise ValueError("invalid source read offset")
    ref = await resolve_source(conn, grant, source_id)
    raw = (await _body(conn, storage, ref)).decode("utf-8")
    if start > len(raw):
        raise EvidenceUnavailable("offset beyond source; restart at offset 0")
    end = min(len(raw), start + limit) if limit > 0 else len(raw)
    return {
        "source_id": str(source_id),
        "path": source_path(ref.model_dump()),
        "text": raw[start:end],
        "start": start,
        "end": end,
        "next_start": end if end < len(raw) else None,
        "total_chars": len(raw),
        "kind": ref.kind,
        "source_url": ref.source_url,
        "metadata": ref.metadata,
    }


async def search_source(
    conn: AsyncConnection,
    storage: StorageBackend,
    grant: EvidenceGrant,
    source_id: UUID,
    *,
    query: str,
    start: int = 0,
    limit: int = 10,
) -> dict[str, Any]:
    if not query or len(query) > 500 or start < 0 or not 1 <= limit <= 20:
        raise ValueError("invalid source search bounds")
    ref = await resolve_source(conn, grant, source_id)
    raw = (await _body(conn, storage, ref)).decode("utf-8")
    positions: list[int] = []
    cursor = start
    while len(positions) < limit + 1:
        pos = raw.find(query, cursor)
        if pos < 0:
            break
        positions.append(pos)
        cursor = pos + len(query)
    return {
        "source_id": str(source_id),
        "matches": [
            {
                "start": p,
                "end": p + len(query),
                "context": raw[max(0, p - 160) : p + len(query) + 160],
            }
            for p in positions[:limit]
        ],
        "next_start": positions[limit] if len(positions) > limit else None,
    }


class TextSupport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["text"] = "text"
    source_id: UUID
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str = Field(min_length=1, max_length=16000)


class JsonSupport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["json"] = "json"
    source_id: UUID
    pointer: str
    expected_value: JsonValue


def json_value(raw: Any, pointer: str) -> Any:
    """RFC6901, including keys containing slash/tilde; no executable path expressions."""
    if pointer == "":
        return raw
    if not pointer.startswith("/"):
        raise EvidenceUnavailable("JSON pointer must start with /")
    value = raw
    for part in pointer[1:].split("/"):
        key = part.replace("~1", "/").replace("~0", "~")
        try:
            if isinstance(value, list):
                if not key.isdigit() or (len(key) > 1 and key[0] == "0"):
                    raise ValueError("invalid array index")
                value = value[int(key)]
            elif isinstance(value, dict):
                value = value[key]
            else:
                raise ValueError("not a container")
        except (IndexError, KeyError, ValueError) as exc:
            raise EvidenceUnavailable(
                "JSON pointer missing; read the provider record first"
            ) from exc
    return value


async def validate_support(
    conn: AsyncConnection,
    storage: StorageBackend,
    grant: EvidenceGrant,
    support: TextSupport | JsonSupport,
) -> SourceRef:
    ref = await resolve_source(conn, grant, support.source_id)
    raw = await _body(conn, storage, ref)
    if isinstance(support, TextSupport):
        if ref.kind in ("provider_record", "acquisition_gap"):
            raise EvidenceUnavailable(
                "this source requires a JSON value, not a purported quotation"
            )
        if (
            support.end <= support.start
            or support.end > len(raw.decode())
            or raw.decode()[support.start : support.end] != support.quote
        ):
            raise EvidenceUnavailable("quote must match the exact contiguous source range")
    else:
        if ref.kind != "provider_record":
            raise EvidenceUnavailable("source is not a provider record")
        actual = json_value(json.loads(raw), support.pointer)
        if json.dumps(actual, sort_keys=True) != json.dumps(support.expected_value, sort_keys=True):
            raise EvidenceUnavailable("provider value differs at this JSON pointer")
    return ref


async def record_disposition(
    conn: AsyncConnection,
    storage: StorageBackend,
    grant: EvidenceGrant,
    *,
    source_id: UUID,
    unit_locator: str,
    decision: Disposition,
    receipt: Mapping[str, JsonValue],
) -> UUID:
    if not 1 <= len(unit_locator) <= 500:
        raise ValueError("unit locator must contain 1-500 characters")
    ref = await resolve_source(conn, grant, source_id)
    await _body(conn, storage, ref)
    raw = json.dumps(dict(receipt), sort_keys=True, separators=(",", ":")).encode()
    sha = content_address(raw)
    key = artifact_key(grant.scope.workspace_id, sha)
    did = uuid5(NAMESPACE_URL, f"{grant.grant_id}:{source_id}:{unit_locator}:{decision}:{sha}")
    await record_artifact(
        conn,
        storage_key=key,
        workspace_id=grant.scope.workspace_id,
        content_sha256=sha,
        media_type="application/json",
        size_bytes=len(raw),
    )
    await storage.put(key, raw, media_type="application/json")
    await retain_artifact(
        conn,
        workspace_id=grant.scope.workspace_id,
        storage_key=key,
        reference_kind="research_disposition",
        reference_id=str(did),
    )
    if key != ref.artifact_key:
        await conn.execute(
            text(
                "INSERT INTO artifact_derivation(workspace_id,parent_key,child_key) "
                "VALUES(:ws,:parent,:child) ON CONFLICT DO NOTHING"
            ),
            {"ws": grant.scope.workspace_id, "parent": ref.artifact_key, "child": key},
        )
    await conn.execute(
        text(
            "INSERT INTO arv2_evidence_disposition(disposition_id,grant_id,"
            "workspace_id,source_id,unit_locator,decision,receipt_key) "
            "VALUES(:id,:grant,:ws,:source,:unit,:decision,:key) ON CONFLICT DO NOTHING"
        ),
        {
            "id": did,
            "grant": grant.grant_id,
            "ws": grant.scope.workspace_id,
            "source": source_id,
            "unit": unit_locator,
            "decision": decision,
            "key": key,
        },
    )
    log.info(
        "arv2.evidence_disposition",
        disposition_id=str(did),
        source_id=str(source_id),
        grant_id=str(grant.grant_id),
        decision=decision,
    )
    return did
