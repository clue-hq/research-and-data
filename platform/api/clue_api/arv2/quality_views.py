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

from deepagents.backends.protocol import (
    BackendProtocol,
    FileInfo,
    GlobResult,
    GrepMatch,
    GrepResult,
    LsResult,
    ReadResult,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.account_research_claims import JobScope
from clue_api.arv2.person_research_brief import BRIEF_PATH, read_person_brief
from clue_api.arv2.quality_authority import ResearchAuthority, resolve_authority
from clue_api.arv2.quality_context import read_context, read_document
from clue_api.arv2.quality_person_release import (
    PARENT_DOSSIER_PATH,
    RELEASE_AT_NOMINATION,
    parent_dossier_ready,
    read_parent_dossier,
    releases_after_import,
)
from clue_api.arv2.quality_policy import advisory_research
from clue_api.arv2.quality_recipe import RECIPE_26, at_least, recipe_of
from clue_api.arv2.quality_relationships import read_committee
from clue_api.arv2.quality_workspace import EvidenceWorkspace, render_text, render_view
from clue_db import ConnFactory
from clue_research.claimstore.quality import eligible_sql
from clue_storage import StorageBackend, StorageError, read_verified_artifact

_GREP_MAX_MATCHES = 1000  # deepagents' own agent-facing grep cap
_DOCUMENT = re.compile(r"/documents/([0-9a-f-]{36})/(0|[1-9][0-9]*)\.json\Z")
_CLAIM = re.compile(r"/claim/([0-9a-f-]{36})/(0|[1-9][0-9]*)\.json\Z")
_PAGE = re.compile(r"/(claims|catalog)/(0|[1-9][0-9]*)\.json\Z")
_OPERATION = re.compile(r"/operations/([0-9a-f-]{36})/(0|[1-9][0-9]*)\.json\Z")
_TRANSCRIPT = re.compile(r"/transcripts/([0-9a-f-]{36})/(0|[1-9][0-9]*)\.json\Z")
_CAPABILITIES = re.compile(r"/capabilities/(0|[1-9][0-9]*)\.json\Z")
_PERSON_BRIEF = re.compile(r"/person-brief/(0|[1-9][0-9]*)\.json\Z")
_SOURCE_REVIEW = re.compile(r"/source-review/([0-9a-f-]{36})/(0|[1-9][0-9]*)\.json\Z")


class PlainView(str):
    """A recipe-26 research view: the document text itself, plus one header line."""

    header: str

    def __new__(cls, text: str, header: str) -> PlainView:
        value = super().__new__(cls, text)
        value.header = header
        return value


def passage_view(body: str, start: int, path: str, *, recipe: int) -> dict[str, object] | PlainView:
    """A long text view. Recipe 26+ serves the document as plain text; earlier recipes keep the
    256-character segment envelope they were pinned with."""
    if start > len(body):
        raise ValueError("offset exceeds the document; start at 0")
    if recipe >= RECIPE_26:
        suffix = f", from character {start}" if start else ""
        header = f"# /research/{path}/{start}.json ({len(body)} characters{suffix})"
        return PlainView(body[start:], header)
    end = len(body)
    return {
        "start": start,
        "end": end,
        "total_chars": len(body),
        "text_segments": [
            {"start": i, "text": body[i : min(i + 256, end)]} for i in range(start, end, 256)
        ],
        "next_path": f"/research/{path}/{end}.json" if end < len(body) else None,
    }


def _passage(body: str, start: int, path: str) -> dict[str, object]:
    """The pre-recipe-26 segment envelope (kept for pinned recipes and their tests)."""
    view = passage_view(body, start, path, recipe=0)
    assert isinstance(view, dict)
    return view


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
        if offset < 0:
            return ReadResult(error="Read offset must be nonnegative.")
        try:
            async with self._connections() as conn:
                authority = await resolve_authority(conn, self._scope, self._execution_id)
                if not self._evidence:
                    value = await self._view(conn, authority, file_path)
                    if isinstance(value, PlainView):
                        return render_text(value.header, str(value), offset=offset, limit=limit)
                    return render_view(value, offset=offset, limit=limit)
            # EvidenceWorkspace opens its own short transaction and rechecks the same grant.
            return await EvidenceWorkspace(
                self._connections,
                self._storage,
                authority.grant,
                recipe=recipe_of(authority.scope),
            ).aread("/evidence" + file_path, offset=offset, limit=limit)
        except (ValueError, StorageError):
            return ReadResult(
                error="Research view unavailable; inspect scope or request a new authorized task."
            )

    async def agrep(
        self, pattern: str, path: str | None = None, glob: str | None = None
    ) -> GrepResult:
        """Recipe 26+: a literal search inside one research or evidence file.

        Earlier recipes refuse every grep and point to search_evidence, which cannot open a
        research view; the agent then failed search_evidence and could not finish
        (2026-10-06). The search runs over exactly what ``aread`` serves for that file.
        """
        if not at_least(self._scope, RECIPE_26):
            return await super().agrep(pattern, path, glob)
        if not path or path.endswith("/") or not path.endswith(".json"):
            return GrepResult(
                error="Grep one file: give the exact path of a research view or an evidence "
                "source (for example a path listed in /evidence/index.json)."
            )
        if not pattern:
            return GrepResult(error="Give a literal text to search for.")
        result = await self.aread(path)
        if result.error:
            return GrepResult(error=result.error)
        file_data: dict[str, Any] = dict(result.file_data or {})
        content = str(file_data.get("content", ""))
        matches: list[GrepMatch] = [
            GrepMatch(path=path, line=number, text=line)
            for number, line in enumerate(content.splitlines(), start=1)
            if pattern in line
        ][:_GREP_MAX_MATCHES]
        return GrepResult(matches=matches)

    async def _view(
        self, conn: AsyncConnection, authority: ResearchAuthority, path: str
    ) -> dict[str, Any] | PlainView:
        scope = authority.scope
        recipe = recipe_of(scope)
        if path == "/parent-account-dossier.json":
            return await read_parent_dossier(conn, self._storage, scope, authority.context_id)
        if path == "/dossier/latest.json":
            from clue_api.arv2.quality_json_dossier import read_json_dossier

            return await read_json_dossier(conn, self._storage, scope, authority.context_id)
        dossier = re.fullmatch(r"/account-dossier/(latest|[1-9][0-9]*)\.json", path)
        if dossier:
            from clue_api.arv2.quality_dossier import read_dossier

            return await read_dossier(
                conn,
                self._storage,
                scope,
                context_id=authority.context_id,
                version=None if dossier[1] == "latest" else int(dossier[1]),
                grant=authority.grant,
            )
        review = _SOURCE_REVIEW.fullmatch(path)
        if review:
            from clue_api.arv2.quality_source_review import source_review

            return await source_review(
                conn, self._storage, authority.grant, UUID(review[1]), int(review[2])
            )
        brief_match = _PERSON_BRIEF.fullmatch(path)
        if brief_match:
            brief = await read_person_brief(
                conn, self._storage, scope, context_id=authority.context_id
            )
            if brief is None:
                return {
                    "state": "no_person_specific_brief",
                    "context_path": "/research/context.json",
                }
            return passage_view(
                json.dumps(brief, ensure_ascii=False, indent=1 if recipe >= RECIPE_26 else None),
                int(brief_match[1]),
                "person-brief",
                recipe=recipe,
            )
        transcript = _TRANSCRIPT.fullmatch(path)
        if transcript:
            from clue_api.arv2.quality_media import read_transcript

            return await read_transcript(
                conn, self._storage, authority.grant, UUID(transcript[1]), int(transcript[2])
            )
        if path == "/coverage.json":
            from clue_api.arv2.quality_coverage import coverage

            return await coverage(conn, scope, authority.context_id)
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
                        # One run can hold several generations for the same account (each
                        # independently launched person opens its own), so resolve the one this
                        # job owns, or the one it was released into as a child.
                        text("""SELECT g.generation_id,g.state,g.input_revision,
                    g.reconciled_revision
                FROM arv2_account_research_generation g WHERE g.workspace_id=:ws AND g.run_id=:run
                  AND g.account_id=:account AND g.context_id=:context
                  AND (g.initial_job_id=:job OR EXISTS (
                    SELECT 1 FROM arv2_generation_child c
                    WHERE c.generation_id=g.generation_id AND c.workspace_id=g.workspace_id
                      AND c.job_id=:job))
                ORDER BY (g.initial_job_id=:job) DESC, g.created_at DESC LIMIT 1"""),
                        {
                            "ws": scope.workspace_id,
                            "run": scope.run_id,
                            "account": scope.account_id,
                            "context": authority.context_id,
                            "job": scope.job_id,
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
            return passage_view(
                json.dumps(
                    self._capabilities,
                    ensure_ascii=False,
                    indent=1 if recipe >= RECIPE_26 else None,
                ),
                int(match[1]),
                "capabilities",
                recipe=recipe,
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
            body = raw.decode()
            if recipe >= RECIPE_26:
                # Stored compact; serve the document itself (not an escaped string) one key
                # per line so a literal grep still lands on a short line.
                body = json.dumps(json.loads(body), ensure_ascii=False, indent=1)
            return passage_view(body, int(match[2]), f"operations/{match[1]}", recipe=recipe)
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
                return passage_view(body, int(match[2]), f"documents/{match[1]}", recipe=recipe)
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
            result["evidence_path"] = "/evidence/index.json"
            from clue_api.arv2.quality_json_dossier import uses_json_dossier

            if uses_json_dossier(scope):
                result["dossier_path"] = "/research/dossier/latest.json"
            elif not scope.person_subject_id:
                result["account_dossier_path"] = "/research/account-dossier/latest.json"
            if scope.person_subject_id:
                result["selected_person"] = {
                    "contact_id": str(scope.person_subject_id),
                    "name": scope.person_name,
                    "title": scope.person_title,
                    "linkedin_url": scope.person_linkedin_url,
                    "employment_history": scope.employment_history,
                }
                result["person_research_brief_path"] = BRIEF_PATH
                result["discovery_references"] = {
                    key: value
                    for key, value in (scope.input_refs or {}).items()
                    if key
                    in {
                        "parent_job_id",
                        "candidate_ref",
                        "discovered_via",
                        "discovered_profile_source_id",
                        "committee_assessment_id",
                    }
                }
                result["account_research_references"] = {
                    "findings": "/research/claims/0.json",
                    "original_reports_pages_and_transcripts": "/evidence/index.json",
                }
                if (
                    releases_after_import(scope)
                    and (scope.input_refs or {}).get("parent_job_id")
                    # Recipe 26: listed only once the account has imported it.
                    and (
                        not at_least(scope, RELEASE_AT_NOMINATION)
                        or await parent_dossier_ready(conn, scope)
                    )
                ):
                    result["account_research_references"]["dossier"] = PARENT_DOSSIER_PATH
            if advisory_research(scope):
                result["review_policy"] = {
                    "verification": "deferred",
                    "relationships": "source_reported",
                    "presentation": "all_findings_including_uncertain_and_disputed",
                    "quality_labels": "advisory_not_publication_requirements",
                }
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
            values = [r.model_dump(mode="json") for r in catalog_rows[start:]]
            return {
                "kind": "field_definitions_not_evidence",
                "fields": values,
                "next_path": None,
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
          ORDER BY c.collected_at,c.id OFFSET :offset
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
        for row in rows:
            value = dict(row)
            value["status"] = value.pop("conclusion") or "legacy_unassessed"
            value["revision"] = value["revision"] or 0
            if advisory_research(scope):
                value["presentation_allowed"] = True
                value["review_policy"] = "advisory"
            if (
                not advisory_research(scope)
                and authority.role == "research_narrative"
                and (
                    not value["applicable"]
                    or value["superseded_by"]
                    or value["status"] != "supported"
                )
            ):
                # The narrative gets the gap/status, not prose it could accidentally assert.
                for k in ("value_json", "evidence_span", "write_markers"):
                    value.pop(k, None)
            if claim_match:
                return passage_view(
                    json.dumps(
                        value,
                        ensure_ascii=False,
                        default=str,
                        indent=1 if recipe >= RECIPE_26 else 2,
                    ),
                    int(claim_match[2]),
                    f"claim/{claim_match[1]}",
                    recipe=recipe,
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
            "next_path": None,
        }

    async def als(self, path: str) -> LsResult:
        if self._evidence:
            try:
                async with self._connections() as conn:
                    authority = await resolve_authority(conn, self._scope, self._execution_id)
                listing = await EvidenceWorkspace(
                    self._connections, self._storage, authority.grant
                ).als("/evidence" + path.rstrip("/"))
                if listing.error:
                    return listing
                return LsResult(
                    entries=[
                        {**row, "path": row["path"].removeprefix("/evidence")}
                        for row in listing.entries or []
                    ]
                )
            except (ValueError, StorageError):
                return LsResult(error="Evidence authority unavailable; request an authorized task.")
        if path not in ("/", "", "/dossier", "/dossier/"):
            return LsResult(error="Open /research/context.json or /evidence/index.json.")
        try:
            async with self._connections() as conn:
                await resolve_authority(conn, self._scope, self._execution_id)
                parent_listed = bool(
                    self._scope.person_subject_id
                    and releases_after_import(self._scope)
                    and (self._scope.input_refs or {}).get("parent_job_id")
                ) and (
                    not at_least(self._scope, RELEASE_AT_NOMINATION)
                    or await parent_dossier_ready(conn, self._scope)
                )
        except (ValueError, StorageError):
            return LsResult(error="Research authority unavailable.")
        if path.rstrip("/") == "/dossier":
            return LsResult(entries=[FileInfo(path="/dossier/latest.json", is_dir=False)])
        return LsResult(
            entries=[
                FileInfo(path=p, is_dir=False)
                for p in (
                    ("/index/0.json",)
                    if self._evidence
                    else (
                        "/context.json",
                        "/catalog/0.json",
                        "/claims/0.json",
                        "/dossier/latest.json",
                        *(("/parent-account-dossier.json",) if parent_listed else ()),
                    )
                )
            ]
        )

    async def aglob(self, pattern: str, path: str | None = None) -> GlobResult:
        from pathlib import PurePosixPath

        listing = await self.als(path or "/")
        if listing.error:
            return GlobResult(error=listing.error)
        if not pattern or ".." in PurePosixPath(pattern).parts:
            return GlobResult(error="Use a file-name glob pattern within this research view.")
        return GlobResult(
            matches=[
                row for row in listing.entries or [] if PurePosixPath(row["path"]).match(pattern)
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
        # Deep Agents places compaction archives and large tool results under this root.
        # /work is already private, readable and writable in every research profile.
        artifacts_root="/work",
        routes={
            "/research/": ResearchViewMount(
                connections, storage, scope, execution_id, capabilities=capabilities
            ),
            "/evidence/": ResearchViewMount(
                connections, storage, scope, execution_id, evidence=True
            ),
        },
    )
