"""Live research context, catalog and claim views behind the governed virtual filesystem.

The filesystem is a view, not a source of truth or a cache. Every read authorizes the execution
again. Originals and current assessments can be revoked between two reads of the same path.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from deepagents.backends.protocol import BackendProtocol, FileInfo, LsResult, ReadResult
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.account_research_claims import JobScope
from clue_api.arv2.quality_authority import ResearchAuthority, resolve_authority
from clue_api.arv2.quality_context import read_context, read_document
from clue_api.arv2.quality_relationships import read_committee
from clue_api.arv2.quality_workspace import EvidenceWorkspace
from clue_db import ConnFactory
from clue_research.claimstore.quality import eligible_sql
from clue_storage import StorageBackend, StorageError, read_verified_artifact

_DOCUMENT = re.compile(r"/documents/([0-9a-f-]{36})/(0|[1-9][0-9]*)\.json\Z")
_CLAIM = re.compile(r"/claim/([0-9a-f-]{36})/(0|[1-9][0-9]*)\.json\Z")
_PAGE = re.compile(r"/(claims|catalog)/(0|[1-9][0-9]*)\.json\Z")
_OPERATION = re.compile(r"/operations/([0-9a-f-]{36})/(0|[1-9][0-9]*)\.json\Z")
_CAPABILITIES = re.compile(r"/capabilities/(0|[1-9][0-9]*)\.json\Z")


def _render(value: object, limit: int) -> ReadResult:
    rendered = json.dumps(value, ensure_ascii=False, indent=2, default=str)
    if len(rendered.splitlines()) > limit:
        return ReadResult(error="Read this bounded view with limit=2000; no data was returned.")
    return ReadResult(file_data={"content": rendered, "encoding": "utf-8"})


def _passage(body: str, start: int, path: str) -> dict[str, object]:
    if start > len(body):
        raise ValueError("offset exceeds the document; start at 0")
    end = min(start + 8000, len(body))
    return {
        "start": start,
        "end": end,
        "total_chars": len(body),
        "text_segments": [
            {"start": i, "text": body[i : min(i + 256, end)]} for i in range(start, end, 256)
        ],
        "next_path": f"/research/{path}/{end}.json" if end < len(body) else None,
    }


class ResearchViewMount(EvidenceWorkspace):
    """Read-only backend mounted at /research/ or /evidence/ by CompositeBackend.

    The composite strips the route prefix. Reattach only our trusted fixed prefix, never a host
    path. Inherited synchronous, write, upload and download methods all refuse access.
    """

    def __init__(
        self,
        connections: ConnFactory,
        storage: StorageBackend,
        scope: JobScope,
        execution_id: UUID,
        *,
        evidence: bool = False,
        capabilities: Sequence[dict[str, object]] = (),
    ):
        self._connections = connections
        self._storage = storage
        self._scope = scope
        self._execution_id = execution_id
        self._evidence = evidence
        self._capabilities = capabilities

    async def aread(self, file_path: str, offset: int = 0, limit: int = 2000) -> ReadResult:
        if offset != 0 or limit < 1:
            return ReadResult(error="Use the explicit continuation path, offset=0 and limit=2000.")
        try:
            async with self._connections() as conn:
                authority = await resolve_authority(conn, self._scope, self._execution_id)
                if not self._evidence:
                    value = await self._view(conn, authority, file_path)
                    return _render(value, limit)
            # EvidenceWorkspace opens its own short transaction and rechecks the same grant.
            return await EvidenceWorkspace(self._connections, self._storage, authority.grant).aread(
                "/evidence" + file_path, offset=offset, limit=limit
            )
        except (ValueError, StorageError):
            return ReadResult(
                error="Research view unavailable; inspect scope or request a new authorized task."
            )

    async def _view(
        self, conn: AsyncConnection, authority: ResearchAuthority, path: str
    ) -> dict[str, Any]:
        scope = authority.scope
        if path == "/committee.json":
            members = await read_committee(
                conn,
                workspace_id=scope.workspace_id,
                account_id=scope.account_id,
                context_id=authority.context_id,
            )
            return {
                "members": [m.model_dump(mode="json") for m in members],
                "supported_count": sum(m.state == "supported" for m in members),
            }
        if path == "/generation.json":
            row = (
                (
                    await conn.execute(
                        text("""SELECT g.generation_id,g.state,g.input_revision,
                    g.reconciled_revision
                FROM arv2_account_research_generation g WHERE g.workspace_id=:ws AND g.run_id=:run
                  AND g.account_id=:account AND g.context_id=:context"""),
                        {
                            "ws": scope.workspace_id,
                            "run": scope.run_id,
                            "account": scope.account_id,
                            "context": authority.context_id,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
            if row is None:
                return {"state": "independent_person_research"}
            children = (
                (
                    await conn.execute(
                        text("""SELECT c.job_id,c.contact_id,j.status,c.receipt_key
                FROM arv2_generation_child c JOIN arv2_research_job j ON j.job_id=c.job_id
                WHERE c.workspace_id=:ws AND c.generation_id=:id ORDER BY c.job_id LIMIT 100"""),
                        {"ws": scope.workspace_id, "id": row["generation_id"]},
                    )
                )
                .mappings()
                .all()
            )
            return {**dict(row), "person_jobs": [dict(r) for r in children]}
        match = _CAPABILITIES.fullmatch(path)
        if match and authority.role == "account_research":
            return _passage(
                json.dumps(self._capabilities, ensure_ascii=False), int(match[1]), "capabilities"
            )
        match = _OPERATION.fullmatch(path)
        if match and authority.role == "account_research":
            key = (
                await conn.execute(
                    text("""
              SELECT artifact_key FROM arv2_research_operation
              WHERE operation_id=:id AND workspace_id=:ws AND job_id=:job
                AND run_id=:run AND account_id=:account AND kind LIKE 'quality_tool:%'
            """),
                    {
                        "id": match[1],
                        "ws": scope.workspace_id,
                        "job": scope.job_id,
                        "run": scope.run_id,
                        "account": scope.account_id,
                    },
                )
            ).scalar_one_or_none()
            if key is None:
                raise ValueError("operation result unavailable in this research job")
            _, raw = await read_verified_artifact(
                conn, self._storage, workspace_id=scope.workspace_id, storage_key=key
            )
            return _passage(raw.decode(), int(match[2]), f"operations/{match[1]}")
        if path == "/context.json" or _DOCUMENT.fullmatch(path):
            context = await read_context(
                conn,
                self._storage,
                workspace_id=scope.workspace_id,
                project_id=scope.project_id,
                context_id=authority.context_id,
            )
            match = _DOCUMENT.fullmatch(path)
            if match:
                document = next(
                    (d for d in context.documents() if str(d.document_id) == match[1]), None
                )
                if document is None:
                    raise ValueError("document outside context pin")
                body = await read_document(
                    conn, self._storage, workspace_id=scope.workspace_id, pin=document
                )
                return _passage(body, int(match[2]), f"documents/{match[1]}")
            result = context.model_dump(mode="json", exclude={"field_catalog"})
            result["context_id"] = str(authority.context_id)
            result["document_paths"] = {
                str(d.document_id): f"/research/documents/{d.document_id}/0.json"
                for d in context.documents()
            }
            result["catalog_path"] = "/research/catalog/0.json"
            result["claims_path"] = "/research/claims/0.json"
            result["committee_path"] = "/research/committee.json"
            result["generation_path"] = "/research/generation.json"
            result["evidence_path"] = "/evidence/index/0.json"
            if authority.role == "account_research":
                result["capabilities_path"] = "/research/capabilities/0.json"
            return result
        match = _PAGE.fullmatch(path)
        claim_match = _CLAIM.fullmatch(path)
        if not match and not claim_match:
            raise ValueError("unknown research path")
        kind, start = (match[1], int(match[2])) if match else ("claims", 0)
        if kind == "catalog":
            context = await read_context(
                conn,
                self._storage,
                workspace_id=scope.workspace_id,
                project_id=scope.project_id,
                context_id=authority.context_id,
            )
            entity = "contacts" if scope.person_subject_id else "accounts"
            catalog_rows = [r for r in context.field_catalog if r.entity == entity]
            values = [r.model_dump(mode="json") for r in catalog_rows[start : start + 20]]
            return {
                "kind": "field_definitions_not_evidence",
                "fields": values,
                "next_path": f"/research/catalog/{start + 20}.json"
                if start + 20 < len(catalog_rows)
                else None,
            }
        rows = (
            (
                await conn.execute(
                    text(f"""
          SELECT c.id,c.entity_id,c.entity_type,c.field_key,c.value_json,
                 c.source_url,c.evidence_span,c.write_markers,
                 c.superseded_by,c.outreach_safe,c.use_class,c.identity_binding,
                 q.conclusion,q.revision,q.assessment_id,q.rationale_key,
                 {eligible_sql("c")} AS applicable
          FROM claim c LEFT JOIN claim_quality_current q ON q.claim_id=c.id
          LEFT JOIN artifact a ON a.storage_key=c.artifact_key AND a.workspace_id=c.workspace_id
          WHERE c.workspace_id=:ws AND (c.entity_id=:subject OR c.entity_id=:account OR (
              :is_account AND EXISTS (SELECT 1 FROM arv2_generation_child child
              JOIN arv2_account_research_generation g ON g.generation_id=child.generation_id
              WHERE child.workspace_id=:ws AND child.contact_id=c.entity_id
                AND g.initial_job_id=:job AND g.context_id=CAST(:context AS uuid))
            ))
            AND (CAST(:claim_id AS uuid) IS NULL OR c.id=CAST(:claim_id AS uuid))
            AND (c.write_markers->>'context_id' IS NULL
                 OR c.write_markers->>'context_id'=CAST(:context AS text))
            AND (c.artifact_key IS NULL OR (a.erased_at IS NULL AND NOT a.privacy_erased
                 AND (a.expires_at IS NULL OR a.expires_at>now())))
            AND NOT EXISTS(SELECT 1 FROM claim_quality_support s JOIN artifact sa
                ON sa.storage_key=s.artifact_key WHERE s.assessment_id=q.assessment_id
                AND (sa.erased_at IS NOT NULL OR sa.privacy_erased OR sa.expires_at<=now()))
          ORDER BY c.collected_at,c.id OFFSET :offset LIMIT 11
        """),
                    {
                        "ws": scope.workspace_id,
                        "subject": scope.person_subject_id or scope.account_id,
                        "account": scope.account_id,
                        "job": scope.job_id,
                        "is_account": scope.person_subject_id is None,
                        "context": str(authority.context_id),
                        "offset": start,
                        "claim_id": claim_match[1] if claim_match else None,
                    },
                )
            )
            .mappings()
            .all()
        )
        items = []
        for row in rows[:10]:
            value = dict(row)
            value["status"] = value.pop("conclusion") or "legacy_unassessed"
            value["revision"] = value["revision"] or 0
            if authority.role == "research_narrative" and (
                not value["applicable"] or value["superseded_by"] or value["status"] != "supported"
            ):
                # The narrative gets the gap/status, not prose it could accidentally assert.
                for k in ("value_json", "evidence_span", "write_markers"):
                    value.pop(k, None)
            if claim_match:
                return _passage(
                    json.dumps(value, ensure_ascii=False, default=str, indent=2),
                    int(claim_match[2]),
                    f"claim/{claim_match[1]}",
                )
            items.append(
                {
                    "claim_id": str(value["id"]),
                    "field_key": value["field_key"],
                    "status": value["status"],
                    "revision": value["revision"],
                    "applicable": value["applicable"] and value["superseded_by"] is None,
                    "path": f"/research/claim/{value['id']}/0.json",
                }
            )
        if claim_match:
            raise ValueError("claim is unavailable in this research context")
        return {
            "claims": items,
            "next_path": f"/research/claims/{start + 10}.json" if len(rows) > 10 else None,
        }

    async def als(self, path: str) -> LsResult:
        if path not in ("/", ""):
            return LsResult(error="Open /research/context.json or /evidence/index/0.json.")
        try:
            async with self._connections() as conn:
                await resolve_authority(conn, self._scope, self._execution_id)
        except (ValueError, StorageError):
            return LsResult(error="Research authority unavailable.")
        return LsResult(
            entries=[
                FileInfo(path=p, is_dir=False)
                for p in (
                    ("/index/0.json",)
                    if self._evidence
                    else ("/context.json", "/catalog/0.json", "/claims/0.json")
                )
            ]
        )


def research_backend(
    default: BackendProtocol,
    connections: ConnFactory,
    storage: StorageBackend,
    scope: JobScope,
    execution_id: UUID,
    *,
    capabilities: Sequence[dict[str, object]] = (),
) -> BackendProtocol:
    from deepagents.backends.composite import CompositeBackend

    return CompositeBackend(
        default=default,
        routes={
            "/research/": ResearchViewMount(
                connections, storage, scope, execution_id, capabilities=capabilities
            ),
            "/evidence/": ResearchViewMount(
                connections, storage, scope, execution_id, evidence=True
            ),
        },
    )
