"""Index trusted acquired evidence during the existing provider drain, without another call."""

from __future__ import annotations

import hashlib
import json
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
from clue_api.arv2.quality_evidence import SourceRef, persist_source
from clue_api.arv2.research_operations import OperationScope
from clue_storage import StorageBackend, read_verified_artifact


async def index_acquisition(
    conn: AsyncConnection,
    storage: StorageBackend,
    scope: OperationScope,
    report: DrainReport,
    *,
    operation_id: UUID | None = None,
) -> tuple[SourceRef, ...]:
    return await _index_receipts(
        conn,
        storage,
        scope,
        tuple(
            AcquisitionReceipt(
                ledger_id_for(row.row_id),
                row.provider,
                row.operation,
                row.recorded_at,
                row.http_status,
                row.error_code,
                report.raw_artifact_keys.get(row.raw_ref or ""),
                operation_id,
            )
            for row in report.result_rows
            if row.provider not in ("openrouter", "model")
        ),
    )


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


async def recover_acquisitions(
    conn: AsyncConnection, storage: StorageBackend, scope: OperationScope
) -> tuple[SourceRef, ...]:
    """Rebuild missing descriptors from settled ledger artifacts, never from another purchase."""
    sources: list[SourceRef] = []
    while True:
        rows = (
            (
                await conn.execute(
                    text("""
          SELECT l.ledger_id,l.provider,l.operation,l.recorded_at,l.http_status,l.error_code,
                 l.response_artifact_key AS key,o.operation_id
          FROM provider_call_ledger l LEFT JOIN arv2_research_operation o
            ON o.ledger_id=l.ledger_id AND o.workspace_id=l.workspace_id AND o.job_id=:job
          WHERE l.workspace_id=:ws AND l.entity_research_job_id=:job AND l.phase='result'
            AND l.provider NOT IN ('openrouter','model')
            AND NOT EXISTS(SELECT 1 FROM arv2_evidence_source s
                           WHERE s.workspace_id=l.workspace_id AND s.ledger_id=l.ledger_id)
          ORDER BY l.recorded_at,l.ledger_id LIMIT 100
        """),
                    {"ws": scope.workspace_id, "job": scope.job_id},
                )
            )
            .mappings()
            .all()
        )
        if not rows:
            return tuple(sources)
        sources.extend(
            await _index_receipts(
                conn, storage, scope, tuple(AcquisitionReceipt(**dict(r)) for r in rows)
            )
        )


async def _index_receipts(
    conn: AsyncConnection,
    storage: StorageBackend,
    scope: OperationScope,
    rows: tuple[AcquisitionReceipt, ...],
) -> tuple[SourceRef, ...]:
    sources = []
    for row in rows:
        key, operation_id = row.key, row.operation_id
        if key is None:
            sources.append(
                await persist_source(
                    conn,
                    storage,
                    scope,
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
            continue
        _, raw = await read_verified_artifact(
            conn, storage, workspace_id=scope.workspace_id, storage_key=key
        )
        envelope = json.loads(raw)
        try:
            body = json.loads(envelope["body_utf8"])
        except (KeyError, TypeError, ValueError):
            body = None
        ledger = row.ledger_id

        save = partial(
            persist_source,
            conn,
            storage,
            scope,
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
                await save(
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
            continue
        sources.append(
            await save(
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
            continue
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
                await save(
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
                await save(
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
                    await save(
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
    return tuple(sources)


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
