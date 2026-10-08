"""Index trusted acquired evidence during the existing provider drain, without another call."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from functools import partial
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.ai_ark_research import enrichment_only
from clue_api.arv2.exa_client import _read_output, _read_report, read_deep_report
from clue_api.arv2.provider_ledger import DrainReport, ledger_id_for
from clue_api.arv2.quality_evidence import (
    UPLOAD_CONCURRENCY,
    PreparedSource,
    SourceRef,
    SourceSpec,
    prepare_sources,
    publish_sources,
    source_file,
)
from clue_api.arv2.research_operations import OperationScope
from clue_db import ConnFactory
from clue_obs import get_logger
from clue_spend.sinks import LedgerRow
from clue_storage import StorageBackend, read_verified_artifact, verify_artifact_bytes

log = get_logger("clue_api.arv2.quality_acquisition")


async def index_acquisition(
    conn: AsyncConnection,
    storage: StorageBackend,
    scope: OperationScope,
    report: DrainReport,
    *,
    operation_id: UUID | None = None,
    uploaded: Collection[str] = frozenset(),
) -> tuple[SourceRef, ...]:
    prepared = await _index_receipts(
        conn,
        storage,
        scope,
        acquisition_receipts(report.result_rows, report.raw_artifact_keys, operation_id),
        report.raw_bodies,
        uploaded,
    )
    return await publish_sources(conn, scope, prepared)


def acquisition_receipts(
    result_rows: Sequence[LedgerRow],
    raw_artifact_keys: Mapping[str, str],
    operation_id: UUID | None = None,
) -> tuple[AcquisitionReceipt, ...]:
    """One receipt per paid provider result of a drain (model calls are not evidence)."""
    return tuple(
        AcquisitionReceipt(
            ledger_id_for(row.row_id),
            row.provider,
            row.operation,
            row.recorded_at,
            row.http_status,
            row.error_code,
            raw_artifact_keys.get(row.raw_ref or ""),
            operation_id,
        )
        for row in result_rows
        if row.provider not in ("openrouter", "model")
    )


def planned_source_files(
    scope: OperationScope,
    result_rows: Sequence[LedgerRow],
    raw_artifact_keys: Mapping[str, str],
    raw_bodies: Mapping[str, bytes],
) -> dict[str, tuple[bytes, str]]:
    """The source files indexing will store for a drain whose responses are held in memory:
    storage key -> (bytes, media type). A result whose response is not held is left out; indexing
    reads and stores it under the lock as before."""
    files: dict[str, tuple[bytes, str]] = {}
    for row in acquisition_receipts(result_rows, raw_artifact_keys):
        if row.key is not None and row.key not in raw_bodies:
            continue
        raw = None if row.key is None else raw_bodies[row.key]
        for spec in _receipt_specs(row, raw):
            key, data, media = source_file(scope, spec)
            files.setdefault(key, (data, media))
    return files


async def upload_sources_early(
    connections: ConnFactory,
    storage: StorageBackend,
    scope: OperationScope,
    result_rows: Sequence[LedgerRow],
    raw_artifact_keys: Mapping[str, str],
    raw_bodies: Mapping[str, bytes],
) -> frozenset[str]:
    """W2-15 option B: put a drained call's source files BEFORE the worker's database lock, so
    the lock is held only for database work. Returns the keys that were put; pass them to
    :func:`index_acquisition` as ``uploaded``. It never raises: it runs after the drain has taken
    its ledger rows and before it writes them, so on any error it uploads nothing and indexing
    stores every file under the lock, as before.

    A file whose artifact row is privacy-erased is never put — erased personal data must not be
    written back, and no sweep would find it again (the orphan sweep skips keys that have a
    row). Indexing still refuses that row under the lock, as before. A failed upload is simply
    left out; indexing then stores that file under the lock as before. A file put here whose
    indexing never happens has no row, so the orphan sweep removes it after its grace window.
    """
    try:
        files = planned_source_files(scope, result_rows, raw_artifact_keys, raw_bodies)
        if not files:
            return frozenset()
        async with connections() as conn:
            blocked = set(
                (
                    await conn.execute(
                        text(
                            "SELECT storage_key FROM artifact WHERE storage_key = ANY(:keys) "
                            "AND privacy_erased"
                        ),
                        {"keys": list(files)},
                    )
                ).scalars()
            )
    except Exception as error:  # noqa: BLE001 - the drain's rows are not written yet; never fail it
        log.warning("arv2.early_upload_skipped", job_id=str(scope.job_id), error=repr(error))
        return frozenset()
    gate = asyncio.Semaphore(UPLOAD_CONCURRENCY)

    async def put(key: str, data: bytes, media: str) -> str:
        async with gate:
            await storage.put(key, data, media_type=media)
        return key

    outcomes = await asyncio.gather(
        *(put(key, data, media) for key, (data, media) in files.items() if key not in blocked),
        return_exceptions=True,
    )
    return frozenset(o for o in outcomes if isinstance(o, str))


_RECOVERY_BATCH = 100


@dataclass(frozen=True)
class AcquisitionReceipt:
    ledger_id: UUID
    provider: str
    operation: str
    recorded_at: datetime
    http_status: int | None
    error_code: str | None
    key: str | None
    operation_id: UUID | None


#: Settled ledger results of one job that have no evidence source yet. It runs after every evidence
#: call, so it must stay an index lookup: ``provider_call_ledger_job`` finds the job's results and
#: ``arv2_evidence_source_ledger`` answers the NOT EXISTS (migration 702784fe02b7). Without them it
#: reads both tables whole, and its cost grows with every run ever stored.
RECOVERY_QUERY = text("""
  SELECT l.ledger_id,l.provider,l.operation,l.recorded_at,l.http_status,l.error_code,
         l.response_artifact_key AS key,o.operation_id
  FROM provider_call_ledger l LEFT JOIN arv2_research_operation o
    ON o.ledger_id=l.ledger_id AND o.workspace_id=l.workspace_id AND o.job_id=:job
  WHERE l.workspace_id=:ws AND l.entity_research_job_id=:job AND l.phase='result'
    AND l.provider NOT IN ('openrouter','model')
    AND NOT EXISTS(SELECT 1 FROM arv2_evidence_source s
                   WHERE s.workspace_id=l.workspace_id AND s.ledger_id=l.ledger_id)
    AND NOT (l.ledger_id = ANY(CAST(:seen AS uuid[])))
  ORDER BY l.recorded_at,l.ledger_id LIMIT :batch
""")


async def recover_acquisitions(
    conn: AsyncConnection, storage: StorageBackend, scope: OperationScope
) -> tuple[SourceRef, ...]:
    """Rebuild missing descriptors from settled ledger artifacts, never from another purchase.

    Every batch is prepared (stored, verified, retained) first and everything is published once
    at the end, so the account lock is never held across an upload (research slowness fix
    2026-10-03). Rows already prepared in this call are excluded by id: they are not published
    yet, so "no evidence source for this ledger row" alone would page over them forever.
    """
    prepared: list[PreparedSource] = []
    seen: list[UUID] = []
    while True:
        rows = (
            (
                await conn.execute(
                    RECOVERY_QUERY,
                    {
                        "ws": scope.workspace_id,
                        "job": scope.job_id,
                        "seen": seen,
                        "batch": _RECOVERY_BATCH,
                    },
                )
            )
            .mappings()
            .all()
        )
        if not rows:
            return await publish_sources(conn, scope, prepared)
        seen.extend(row["ledger_id"] for row in rows)
        prepared.extend(
            await _index_receipts(
                conn, storage, scope, tuple(AcquisitionReceipt(**dict(r)) for r in rows)
            )
        )


async def _index_receipts(
    conn: AsyncConnection,
    storage: StorageBackend,
    scope: OperationScope,
    rows: tuple[AcquisitionReceipt, ...],
    bodies: Mapping[str, bytes] | None = None,
    uploaded: Collection[str] = frozenset(),
) -> tuple[PreparedSource, ...]:
    """Every receipt's sources, prepared together (W2-16: one batch of parallel uploads).

    ``bodies`` are raw responses this drain has just stored (artifact key -> bytes): they are
    checked against their rows instead of downloaded again. Recovery passes none and reads them.
    ``uploaded`` names source files already put before the worker lock (W2-15 option B).
    """
    sources: list[SourceSpec] = []
    for row in rows:
        raw: bytes | None = None
        if row.key is not None:
            held = (bodies or {}).get(row.key)
            if held is not None:
                await verify_artifact_bytes(
                    conn, storage_key=row.key, workspace_id=scope.workspace_id, data=held
                )
                raw = held
            else:
                _, raw = await read_verified_artifact(
                    conn, storage, workspace_id=scope.workspace_id, storage_key=row.key
                )
        sources.extend(_receipt_specs(row, raw))
    return await prepare_sources(conn, storage, scope, sources, originals=bodies, uploaded=uploaded)


def _receipt_specs(row: AcquisitionReceipt, raw: bytes | None) -> list[SourceSpec]:
    """The sources one settled provider result yields, from its raw response (``None`` when the
    ledger row cites no response). Pure — no database or storage — so it also plans the files an
    evidence call will store before the worker lock is taken (W2-15 option B)."""
    key, operation_id = row.key, row.operation_id
    sources: list[SourceSpec] = []
    if key is None or raw is None:
        sources.append(
            SourceSpec(
                kind="acquisition_gap",
                original_key=None,
                body={
                    "provider": row.provider,
                    "operation": row.operation,
                    "status": row.http_status,
                    "error_code": row.error_code,
                },
                origin_locator="response-unavailable",
                observed_at=row.recorded_at,
                ledger_id=row.ledger_id,
                operation_id=operation_id,
            )
        )
        return sources
    envelope = json.loads(raw)
    try:
        body = json.loads(envelope["body_utf8"])
    except (KeyError, TypeError, ValueError):
        body = None
    ledger = row.ledger_id

    save = partial(
        SourceSpec,
        original_key=key,
        observed_at=row.recorded_at,
        ledger_id=ledger,
        operation_id=operation_id,
        normalizer_version=f"{row.provider}:enrichment-v2"
        if row.provider == "ai_ark"
        else f"{row.provider}:v1",
    )

    if (
        row.http_status is None
        or not 200 <= row.http_status < 300
        or not isinstance(body, (dict, list))
    ):
        sources.append(
            save(
                kind="acquisition_gap",
                body={
                    "provider": row.provider,
                    "operation": row.operation,
                    "status": row.http_status,
                    "error_code": row.error_code,
                },
                origin_locator="response-status",
            )
        )
        return sources
    sources.append(
        save(
            kind="provider_record",
            body=enrichment_only(body) if row.provider == "ai_ark" else body,
            origin_locator="response-body",
            metadata={
                "content_kind": "ai_ark_enrichment",
                "excluded_content": "descriptive_prose",
            }
            if row.provider == "ai_ark"
            else None,
        )
    )
    if row.provider != "exa" or not isinstance(body, dict):
        return sources
    report_text = read_deep_report(body, text_output=row.operation == "deep-reasoning")
    if report_text:
        _, parsed, _ = _read_output(body)
        # Keep historical structured-report source IDs stable on recovery.
        locator = (
            "output.report"
            if _read_report(parsed) is not None
            else ("output.content" if isinstance(body.get("output"), dict) else "output")
        )
        sources.append(
            save(
                kind="research_report",
                body=report_text,
                origin_locator=locator,
                metadata={"attribution": "provider_synthesis", "primary_quote": False},
            )
        )
    results = body.get("results")
    for i, result in enumerate(results if isinstance(results, list) else []):
        if not isinstance(result, dict):
            continue
        # A whole result retains links, structured fields and fresh highlights that can be
        # absent from both its text field and Exa's dossier. Existing excerpt IDs stay stable.
        sources.append(
            save(
                kind="provider_record",
                body=result,
                origin_locator=f"results/{i}",
                source_url=result.get("url"),
                metadata={
                    "title": result.get("title"),
                    "published_at": result.get("publishedDate"),
                    "content_kind": "exa_result",
                    "field_hashes": {
                        k: hashlib.sha256(json.dumps(v, sort_keys=True).encode()).hexdigest()
                        for k, v in result.items()
                    },
                },
            )
        )
        for locator, content in exa_source_texts(result):
            sources.append(
                save(
                    kind="web_snapshot",
                    body=content,
                    origin_locator=f"results/{i}/{locator}",
                    source_url=result.get("url"),
                    metadata={
                        "published_at": result.get("publishedDate"),
                        "title": result.get("title"),
                        "content_kind": "highlight"
                        if locator.startswith("highlights/")
                        else "text",
                    },
                )
            )
    return sources


async def discard_early_uploads(
    connections: ConnFactory, storage: StorageBackend, keys: Collection[str]
) -> tuple[str, ...]:
    """Delete files :func:`upload_sources_early` put that indexing never recorded — the job was
    withdrawn before indexing (a privacy stop, a suspension) or indexing failed. Nothing else
    could find them: purge and erasure work from artifact rows, and the orphan sweep waits a day.

    A key with a live artifact row is kept: other evidence cites those same bytes. Accepted race
    (founder, 2026-10-08): another job uploading byte-identical content at this very moment can
    lose its file and then hold a live row whose read fails — fail-closed, never a leak. Never
    raises; returns the keys it deleted.
    """
    if not keys:
        return ()
    try:
        async with connections() as conn:
            live = set(
                (
                    await conn.execute(
                        text(
                            "SELECT storage_key FROM artifact WHERE storage_key = ANY(:keys) "
                            "AND erased_at IS NULL AND purged_at IS NULL AND NOT privacy_erased"
                        ),
                        {"keys": list(keys)},
                    )
                ).scalars()
            )
        doomed = sorted(key for key in keys if key not in live)
        await asyncio.gather(*(storage.delete(key) for key in doomed))
        return tuple(doomed)
    except Exception as error:  # noqa: BLE001 - cleanup must not mask the call's own outcome
        log.warning("arv2.early_upload_discard_failed", keys=len(keys), error=repr(error))
        return ()


def exa_source_texts(result: dict[str, Any]) -> list[tuple[str, str]]:
    """Keep each returned excerpt addressable; a highlights-only response is not a full page."""
    texts = []
    if isinstance(result.get("text"), str) and result["text"].strip():
        texts.append(("text", result["text"]))
    highlights = result.get("highlights")
    if isinstance(highlights, list):
        texts.extend(
            (f"highlights/{index}", value)
            for index, value in enumerate(highlights)
            if isinstance(value, str) and value.strip()
        )
    return texts
