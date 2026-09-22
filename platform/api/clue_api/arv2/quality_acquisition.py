"""Index trusted acquired evidence during the existing provider drain, without another call."""

from __future__ import annotations

import json
from functools import partial
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.exa_client import _read_output, _read_report
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
    sources = []
    for row in report.result_rows:
        # Model reasoning and structuring replies are never original source evidence.
        if row.provider in ("openrouter", "model"):
            continue
        key = report.raw_artifact_keys.get(row.raw_ref or "")
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
                    ledger_id=ledger_id_for(row.row_id),
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
        ledger = ledger_id_for(row.row_id)

        save = partial(
            persist_source,
            conn,
            storage,
            scope,
            original_key=key,
            observed_at=row.recorded_at,
            ledger_id=ledger,
            operation_id=operation_id,
            normalizer_version=f"{row.provider}:v1",
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
            await save(kind="provider_record", body=body, origin_locator="response-body")
        )
        if row.provider != "exa" or not isinstance(body, dict):
            continue
        _, parsed, _ = _read_output(body)
        report_text = _read_report(parsed)
        if report_text:
            sources.append(
                await save(
                    kind="research_report",
                    body=report_text,
                    origin_locator="output.report",
                    metadata={"attribution": "provider_synthesis", "primary_quote": False},
                )
            )
        results = body.get("results")
        for i, result in enumerate(results if isinstance(results, list) else []):
            if not isinstance(result, dict) or not isinstance(result.get("text"), str):
                continue
            sources.append(
                await save(
                    kind="web_snapshot",
                    body=result["text"],
                    origin_locator=f"results/{i}/text",
                    source_url=result.get("url"),
                    metadata={
                        "published_at": result.get("publishedDate"),
                        "title": result.get("title"),
                    },
                )
            )
    return tuple(sources)
