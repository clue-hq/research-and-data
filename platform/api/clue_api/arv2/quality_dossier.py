"""Account-authored research deliverables, separate from externally acquired evidence.

Normal filesystem writes publish immutable artifacts immediately. The existing artifact
reference index owns versions; neither a new tool nor a second storage system is needed.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import ToolMessage
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.account_research_claims import JobScope
from clue_api.arv2.evidence_paths import source_path
from clue_api.arv2.quality_authority import resolve_authority
from clue_api.arv2.quality_evidence import EvidenceGrant, list_sources
from clue_api.quality_research_artifacts import ResearchArtifacts
from clue_db import ConnFactory
from clue_obs import get_logger
from clue_storage import StorageBackend, read_verified_artifact, retain_artifact

log = get_logger("arv2.quality.dossier")
DOSSIER_FILE = "outputs/account-dossier.md"
DOSSIER_VIEW = "/research/account-dossier/latest.json"
_KIND = "account_research_dossier"
_URL = re.compile(r"https?://[^\s<>\]\)\"']+")


def uses_account_dossier(scope: JobScope) -> bool:
    return (
        scope.catalog_version == "v4"
        and scope.subject_kind == "account"
        and int((scope.input_refs or {}).get("quality_recipe_version", 5)) >= 13
    )


def source_inventory(markdown: str, sources: list[dict[str, Any]]) -> dict[str, Any]:
    """Citation matching records references, never claims a source was read or verified."""
    urls = sorted({url.rstrip(".,;") for url in _URL.findall(markdown)})
    entries = []
    for source in sources:
        sid = source["source_id"]
        path = source_path(source) if source.get("available") else None
        entries.append(
            {
                **{
                    key: source.get(key)
                    for key in (
                        "source_id",
                        "revision",
                        "kind",
                        "source_url",
                        "artifact_key",
                        "original_key",
                        "subject_id",
                        "job_id",
                        "operation_id",
                        "available",
                    )
                },
                "path": path,
                "citation_match": (
                    "path"
                    if path and path in markdown
                    else "source_id"
                    if sid in markdown
                    else "url"
                    if source.get("source_url") in urls
                    else None
                ),
            }
        )
    return {
        "sources": entries,
        "cited_urls": urls,
        "unmatched_cited_urls": [
            url for url in urls if not any(s.get("source_url") == url for s in sources)
        ],
        "interpretation": "Citation matches indicate references in the report. Other entries "
        "are retrieved material, not proof of reading. Unmatched URLs may occur inside retained "
        "provider records; they are not evidence of a separate page fetch.",
    }


async def read_dossier(
    conn: AsyncConnection,
    storage: StorageBackend,
    scope: JobScope,
    *,
    context_id: UUID,
    version: int | None = None,
    grant: EvidenceGrant | None = None,
) -> dict[str, Any]:
    if scope.person_subject_id is not None:
        raise ValueError("account dossier is not a person-scoped evidence view")
    prefix = f"{scope.job_id}:"
    key = (
        await conn.execute(
            text("""SELECT storage_key FROM artifact_reference
        WHERE workspace_id=:ws AND reference_kind=:kind
          AND reference_id LIKE :prefix
          AND (CAST(:ref AS text) IS NULL OR reference_id=:ref)
        ORDER BY reference_id DESC LIMIT 1"""),
            {
                "ws": scope.workspace_id,
                "kind": _KIND,
                "prefix": prefix + "%",
                "ref": f"{prefix}{version:010d}" if version is not None else None,
            },
        )
    ).scalar_one_or_none()
    if key is None:
        if version is not None:
            raise ValueError("dossier version is unavailable")
        return {"state": "not_written", "write_path": "/" + DOSSIER_FILE}
    _, raw = await read_verified_artifact(
        conn, storage, workspace_id=scope.workspace_id, storage_key=key
    )
    manifest = json.loads(raw)
    expected = {
        "workspace_id": scope.workspace_id,
        "project_id": scope.project_id,
        "context_id": str(context_id),
        "run_id": str(scope.run_id),
        "account_id": str(scope.account_id),
        "job_id": str(scope.job_id),
    }
    if any(manifest.get(k) != v for k, v in expected.items()):
        raise ValueError("dossier is outside the current research task")
    ref, body = await read_verified_artifact(
        conn,
        storage,
        workspace_id=scope.workspace_id,
        storage_key=manifest["report"]["artifact_key"],
    )
    if ref.content_sha256 != manifest["report"]["sha256"]:
        raise ValueError("dossier content differs from its saved version")
    if grant is not None:
        # Navigation is a current scoped view, including for retained dev dossiers.
        # The saved report and manifest bytes remain unchanged.
        available = await list_sources(conn, grant, limit=0)
        paths = {s["source_id"]: s for s in available["sources"] if s.get("available")}
        for entry in manifest.get("source_inventory", {}).get("sources", []):
            current = paths.get(entry["source_id"])
            entry["path"] = current["path"] if current else None
            entry["available"] = current is not None
    return {**manifest, "manifest_key": key, "markdown": body.decode("utf-8")}


async def save_dossier(
    conn: AsyncConnection,
    storage: StorageBackend,
    scope: JobScope,
    *,
    execution_id: UUID,
    markdown: str,
) -> dict[str, Any]:
    authority = await resolve_authority(conn, scope, execution_id)
    if not uses_account_dossier(scope) or authority.role != "account_research":
        raise ValueError("only the account researcher authors this dossier")
    # Continuations reuse the initial account job. Serialize version allocation across
    # executions and retries without modifying that job's terminal result or input pins.
    await conn.execute(
        text(
            "SELECT job_id FROM arv2_research_job WHERE job_id=:job AND workspace_id=:ws FOR UPDATE"
        ),
        {"job": scope.job_id, "ws": scope.workspace_id},
    )
    original = await list_sources(conn, authority.grant, limit=0)
    inventory = source_inventory(markdown, original["sources"])
    digest = hashlib.sha256(
        json.dumps(
            {"markdown": markdown, "inventory": inventory},
            sort_keys=True,
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    previous = await read_dossier(conn, storage, scope, context_id=authority.context_id)
    if previous.get("content_digest") == digest:
        return {k: v for k, v in previous.items() if k != "markdown"}

    @asynccontextmanager
    async def connections() -> AsyncIterator[AsyncConnection]:
        yield conn

    sink = ResearchArtifacts(storage=storage, conn_factory=connections)
    sink.scope, sink.context_id = scope, authority.context_id
    report = await sink.persist_body(
        workspace_id=scope.workspace_id, data=markdown.encode("utf-8"), media_type="text/markdown"
    )
    version = previous.get("version", 0) + 1
    manifest = {
        "kind": "account_agent_dossier_not_external_evidence",
        "version": version,
        "workspace_id": scope.workspace_id,
        "project_id": scope.project_id,
        "context_id": str(authority.context_id),
        "run_id": str(scope.run_id),
        "account_id": str(scope.account_id),
        "job_id": str(scope.job_id),
        "execution_id": str(execution_id),
        "content_digest": digest,
        "report": {"artifact_key": report.artifact_key, "sha256": report.sha256},
        "source_inventory": inventory,
        "evidence_revision": original["revision"],
        "previous_version_path": previous.get("path"),
        "path": f"/research/account-dossier/{version}.json",
    }
    ref = await sink.persist_body(
        workspace_id=scope.workspace_id,
        data=json.dumps(manifest, sort_keys=True, ensure_ascii=False).encode(),
        media_type="application/vnd.clue.account-research-dossier+json",
    )
    await conn.execute(
        text("""INSERT INTO artifact_derivation(workspace_id,parent_key,child_key)
        VALUES(:ws,:parent,:child) ON CONFLICT DO NOTHING"""),
        {"ws": scope.workspace_id, "parent": report.artifact_key, "child": ref.artifact_key},
    )
    await retain_artifact(
        conn,
        workspace_id=scope.workspace_id,
        storage_key=ref.artifact_key,
        reference_kind=_KIND,
        reference_id=f"{scope.job_id}:{version:010d}",
    )
    log.info(
        "arv2.quality.dossier_saved",
        job_id=str(scope.job_id),
        execution_id=str(execution_id),
        version=version,
        artifact_key=report.artifact_key,
        source_count=len(inventory["sources"]),
    )
    return {**manifest, "manifest_key": ref.artifact_key}


class AccountDossierPersistence(AgentMiddleware[Any, Any, Any]):
    """Persist completed file writes before the next model turn or specialist dispatch."""

    def __init__(
        self,
        connections: ConnFactory,
        storage: StorageBackend,
        scope: JobScope,
        execution_id: UUID,
        backend: Any,
    ):
        self.connections, self.storage, self.scope = connections, storage, scope
        self.execution_id, self.backend = execution_id, backend

    async def awrap_tool_call(self, request: Any, handler: Any) -> Any:
        call = request.tool_call
        if (
            call.get("name") == "delegate_specialist"
            and call.get("args", {}).get("role") == "research_claims"
        ):
            async with self.connections() as conn:
                authority = await resolve_authority(conn, self.scope, self.execution_id)
                saved = await read_dossier(
                    conn, self.storage, self.scope, context_id=authority.context_id
                )
            if saved.get("path"):
                args = dict(call["args"])
                args["instructions"] = args.get("instructions", "") + (
                    f"\n\nRead the account research dossier at {saved['path']} and its source "
                    "inventory. It preserves the researcher's findings, interpretations and gaps. "
                    "Use the referenced original evidence for extraction and quotations, including "
                    "useful source-only findings. The dossier is agent synthesis, not an external "
                    "verbatim quotation."
                )
                request = request.override(tool_call={**call, "args": args})
        result = await handler(request)
        args = call.get("args", {})
        if (
            call.get("name") in {"write_file", "edit_file"}
            and args.get("file_path", "").lstrip("/") == DOSSIER_FILE
            and isinstance(result, ToolMessage)
            and result.status != "error"
        ):
            # Read unformatted bytes from the anchored workspace, never numbered tool output.
            markdown = await self.backend.read_text(DOSSIER_FILE)
            async with self.connections() as conn:
                saved = await save_dossier(
                    conn,
                    self.storage,
                    self.scope,
                    execution_id=self.execution_id,
                    markdown=markdown,
                )
            notice = f"\nDossier durably saved: {saved['path']} (version {saved['version']})."
            content = result.content
            result = result.model_copy(
                update={
                    "content": content + notice
                    if isinstance(content, str)
                    else [*content, {"type": "text", "text": notice}]
                }
            )
        return result
