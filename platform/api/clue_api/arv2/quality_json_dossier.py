"""Researcher-authored JSON sections and mechanical import on the governed tool seam.

Artifact references retain each complete draft and frozen import receipt. A job-scoped advisory lock
serializes section replacement across parallel tool calls. No model is called here.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, ClassVar
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import Field, JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.account_research_claims import JobScope
from clue_api.arv2.dossier_import import import_research_dossier
from clue_api.arv2.dossier_json import (
    Entry,
    dossier_coverage,
    parse_json_dossier,
    replace_section,
    update_findings,
)
from clue_api.arv2.dossier_revision import claim_versions, import_revision, revision_plan
from clue_api.arv2.quality_authority import resolve_authority
from clue_api.arv2.quality_evidence import list_sources
from clue_api.arv2.quality_person_release import mark_account_import_ready
from clue_api.arv2.quality_tools import _ResearchWriteTool
from clue_api.quality_research_artifacts import ResearchArtifacts
from clue_obs import get_logger
from clue_storage import StorageBackend, read_verified_artifact, retain_artifact
from clue_toolbelt import ToolContext, ToolInput, ToolOutput, ToolResult

log = get_logger("arv2.dossier_authoring")
VIEW = "/research/dossier/latest.json"
_KIND = "research_json_dossier"


def uses_json_dossier(scope: JobScope) -> bool:
    return (
        scope.catalog_version == "v4"
        and int((scope.input_refs or {}).get("quality_recipe_version", 5)) >= 16
    )


def encode(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True).encode()


async def read_json_dossier(
    conn: AsyncConnection,
    storage: StorageBackend,
    scope: JobScope,
    context_id: UUID,
) -> dict[str, Any]:
    key = (
        await conn.execute(
            text("""SELECT storage_key FROM artifact_reference
      WHERE workspace_id=:ws AND reference_kind=:kind AND reference_id LIKE :prefix
      ORDER BY reference_id DESC LIMIT 1"""),
            {"ws": scope.workspace_id, "kind": _KIND, "prefix": f"{scope.job_id}:%"},
        )
    ).scalar_one_or_none()
    if key is None:
        return {"state": "draft", "version": 0, "document": {"sections": []}, "path": VIEW}
    _, raw = await read_verified_artifact(
        conn, storage, workspace_id=scope.workspace_id, storage_key=key
    )
    saved = json.loads(raw)
    expected = {
        "job_id": str(scope.job_id),
        "context_id": str(context_id),
        "subject_id": str(scope.person_subject_id or scope.account_id),
    }
    if any(saved.get(k) != v for k, v in expected.items()):
        raise ValueError("JSON dossier belongs to another task or subject")
    return {**saved, "artifact_key": key, "path": VIEW}


async def _persist(
    conn: AsyncConnection,
    storage: StorageBackend,
    scope: JobScope,
    context_id: UUID,
    saved: dict[str, Any],
) -> dict[str, Any]:
    @asynccontextmanager
    async def connections() -> AsyncIterator[AsyncConnection]:
        yield conn

    sink = ResearchArtifacts(storage=storage, conn_factory=connections)
    sink.scope, sink.context_id = scope, context_id
    saved = {
        **saved,
        "job_id": str(scope.job_id),
        "context_id": str(context_id),
        "subject_id": str(scope.person_subject_id or scope.account_id),
    }
    saved.pop("artifact_key", None)
    saved.pop("path", None)
    document_ref = await sink.persist_body(
        workspace_id=scope.workspace_id,
        data=encode(saved["document"]),
        media_type="application/json",
    )
    saved["document_artifact_key"] = document_ref.artifact_key
    await retain_artifact(
        conn,
        workspace_id=scope.workspace_id,
        storage_key=document_ref.artifact_key,
        reference_kind="research_json_dossier_document",
        reference_id=f"{scope.job_id}:{saved['version']:010d}",
    )
    ref = await sink.persist_body(
        workspace_id=scope.workspace_id,
        data=encode(saved),
        media_type="application/vnd.clue.research-json-dossier+json",
    )
    await retain_artifact(
        conn,
        workspace_id=scope.workspace_id,
        storage_key=ref.artifact_key,
        reference_kind=_KIND,
        reference_id=f"{scope.job_id}:{saved['version']:010d}",
    )
    # A lightweight index over the same committed snapshot; no job-row lock upgrade.
    from clue_api.arv2.quality_progress import DOSSIER_PROGRESS_KIND

    await retain_artifact(
        conn,
        workspace_id=scope.workspace_id,
        storage_key=ref.artifact_key,
        reference_kind=DOSSIER_PROGRESS_KIND,
        reference_id=f"{scope.job_id}:{saved['version']:010d}:{saved['state']}",
    )
    log.info(
        "arv2.dossier.snapshot_saved",
        job_id=str(scope.job_id),
        subject_kind=scope.subject_kind,
        version=saved["version"],
        state=saved["state"],
        artifact_key=ref.artifact_key,
    )
    return {**saved, "artifact_key": ref.artifact_key, "path": VIEW}


async def _lock(conn: AsyncConnection, scope: JobScope) -> None:
    # Do not upgrade the evidence authority's shared job lock to FOR UPDATE:
    # readers acquire execution -> job, so job -> execution would create a cycle.
    # Only dossier writers take this separate lock, before resolving authority.
    await conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"research-dossier:{scope.workspace_id}:{scope.job_id}"},
    )


async def validate_dossier_handoff(
    conn: AsyncConnection,
    storage: StorageBackend,
    scope: JobScope,
    context_id: UUID,
    claim_ids: tuple[UUID, ...],
) -> None:
    """Completion checks storage receipts, not factual quality or research coverage."""
    if not uses_json_dossier(scope):
        return
    saved = await read_json_dossier(conn, storage, scope, context_id)
    if saved["state"] != "complete":
        raise ValueError("Finish the JSON dossier import before completion")
    imported = {UUID(e["claim_id"]) for e in saved["receipt"]["entries"]}
    if not imported.issubset(set(claim_ids)):
        raise ValueError("Final report must reference every imported finding")


class SaveSectionInput(ToolInput):
    section: str = Field(min_length=1)
    findings: list[Entry]


class DossierInput(ToolInput):
    pass


class DossierReceipt(ToolOutput):
    result: dict[str, JsonValue]


class _DossierTool(_ResearchWriteTool):
    output_model: ClassVar[type[ToolOutput]] = DossierReceipt

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        authority = await self.authority(ctx)
        if not uses_json_dossier(self.scope) or authority.role != "account_research":
            raise ValueError("JSON dossier authoring belongs to this job's researcher")
        async with ctx.conn_factory() as conn:
            await _lock(conn, self.scope)
            authority = await resolve_authority(conn, self.scope, authority.execution_id)
            saved = await read_json_dossier(conn, self.storage, self.scope, authority.context_id)
            inventory = await list_sources(conn, authority.grant, limit=0)
            aliases = {
                r["path"]: UUID(r["source_id"])
                for r in inventory["sources"]
                if r.get("available") and r.get("path")
            }
            result = await self.apply(conn, authority, saved, aliases, inputs)
        return ToolResult(tool=self.name, version=self.version, references={"result": result})

    async def apply(
        self,
        conn: AsyncConnection,
        authority: Any,
        saved: dict[str, Any],
        aliases: dict[str, UUID],
        inputs: ToolInput,
    ) -> dict[str, Any]:
        raise NotImplementedError


class SaveDossierSectionTool(_DossierTool):
    name = "save_dossier_section"
    input_model = SaveSectionInput
    change_document = staticmethod(replace_section)
    model_description = (
        "Save one complete JSON dossier section, replacing that named section and preserving "
        "others. Read /research/dossier/latest.json before revisions. Each finding has a stable "
        "F-ID and original source_paths. The backend stores the draft durably; no claims yet. "
        "Forward conflict/duplicate references are allowed while drafting. A frozen dossier "
        "cannot be edited; retry finish_dossier to recover its import."
    )

    async def apply(
        self,
        conn: AsyncConnection,
        authority: Any,
        saved: dict[str, Any],
        aliases: dict[str, UUID],
        inputs: ToolInput,
    ) -> dict[str, Any]:
        args = SaveSectionInput.model_validate(inputs)
        if saved["state"] != "draft":
            return {
                "saved": False,
                "error": "Dossier frozen; reuse or retry its import",
                "path": VIEW,
            }
        try:
            document = self.change_document(
                saved["document"],
                args.section,
                [f.model_dump(mode="json") for f in args.findings],
                set(aliases),
            )
        except ValueError as exc:
            return {"saved": False, "error": str(exc), "path": VIEW}
        if saved["document"] != document:
            saved = await _persist(
                conn,
                self.storage,
                self.scope,
                authority.context_id,
                {**saved, "version": saved["version"] + 1, "document": document},
            )
        return {
            "saved": True,
            "path": VIEW,
            "version": saved["version"],
            "section": args.section,
            "entries": len(args.findings),
        }


class UpdateDossierFindingsTool(SaveDossierSectionTool):
    name = "update_dossier_findings"
    change_document = staticmethod(update_findings)
    model_description = (
        "Save only new or corrected findings within a named draft section. Send each affected "
        "finding's complete Entry with its stable F-ID; omitted findings and other sections "
        "remain unchanged. New IDs append; existing IDs replace in place. No field fragments "
        "or deletion by omission. Use for small corrections and incremental batches instead "
        "of rewriting whole sections. Imported dossiers require begin_dossier_revision first."
    )


class BeginRevisionInput(ToolInput):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=1)
    withdrawals: dict[str, str] = Field(default_factory=dict)


class BeginDossierRevisionTool(_DossierTool):
    name = "begin_dossier_revision"
    input_model = BeginRevisionInput
    model_description = (
        "Start a new draft from this job's completed imported dossier. Read latest.json first, "
        "supply its expected_version and a correction/extension reason. Preserve F-IDs for revised "
        "findings. Explicit withdrawals map removed F-IDs to reasons; do not omit other findings. "
        "Old claims remain current until finish_dossier applies the whole revision atomically."
    )

    async def apply(
        self,
        conn: AsyncConnection,
        authority: Any,
        saved: dict[str, Any],
        aliases: dict[str, UUID],
        inputs: ToolInput,
    ) -> dict[str, Any]:
        args = BeginRevisionInput.model_validate(inputs)
        if int((self.scope.input_refs or {}).get("quality_recipe_version", 0)) < 17:
            raise ValueError("Dossier revisions require recipe 17 or newer")
        if saved["state"] != "complete" or saved["version"] != args.expected_version:
            return {
                "started": False,
                "error": "Read latest.json; expected a completed version",
                "path": VIEW,
            }
        ids = {e["id"] for e in saved["receipt"]["entries"]}
        if (
            args.withdrawals.keys() - ids
            or not args.reason.strip()
            or any(not reason.strip() for reason in args.withdrawals.values())
        ):
            return {
                "started": False,
                "error": "Use existing finding IDs and nonempty reasons",
                "path": VIEW,
            }
        revisions = await claim_versions(
            conn, self.scope, authority.context_id, saved["receipt"]["entries"]
        )
        document = {
            "sections": [
                {
                    **section,
                    "findings": [f for f in section["findings"] if f["id"] not in args.withdrawals],
                }
                for section in saved["document"]["sections"]
            ]
        }
        draft = await _persist(
            conn,
            self.storage,
            self.scope,
            authority.context_id,
            {
                "state": "draft",
                "version": saved["version"] + 1,
                "document": document,
                "revision": {
                    "base_version": saved["version"],
                    "base_artifact_key": saved["artifact_key"],
                    "base_document": saved["document"],
                    "base_receipt": saved["receipt"],
                    "claim_revisions": revisions,
                    "reason": args.reason,
                    "withdrawals": args.withdrawals,
                },
            },
        )
        return {
            "started": True,
            "path": VIEW,
            "version": draft["version"],
            "base_version": saved["version"],
        }


class DiscardRevisionInput(ToolInput):
    expected_version: int = Field(ge=1)


class DiscardDossierRevisionTool(_DossierTool):
    name = "discard_dossier_revision"
    input_model = DiscardRevisionInput
    model_description = (
        "Discard an unapplied dossier revision, restoring the last imported document and receipt. "
        "Requires its current expected_version. No claim is removed or changed. "
        "Draft history remains."
    )

    async def apply(
        self,
        conn: AsyncConnection,
        authority: Any,
        saved: dict[str, Any],
        aliases: dict[str, UUID],
        inputs: ToolInput,
    ) -> dict[str, Any]:
        args = DiscardRevisionInput.model_validate(inputs)
        if (
            saved["state"] != "draft"
            or not saved.get("revision")
            or saved["version"] != args.expected_version
        ):
            return {
                "discarded": False,
                "error": "Expected the current unapplied revision",
                "path": VIEW,
            }
        revision = saved["revision"]
        restored = await _persist(
            conn,
            self.storage,
            self.scope,
            authority.context_id,
            {
                "state": "complete",
                "version": saved["version"] + 1,
                "document": revision["base_document"],
                "receipt": revision["base_receipt"],
                "discarded_revision_artifact_key": saved["artifact_key"],
                "previous_import_artifact_key": revision["base_artifact_key"],
            },
        )
        return {"discarded": True, "version": restored["version"], "path": VIEW}


def validation(saved: dict[str, Any], aliases: dict[str, UUID]) -> dict[str, Any]:
    parsed = parse_json_dossier(encode(saved["document"]))
    errors = list(parsed.errors)
    for record in parsed.records:
        unknown = set(record.entry.source_paths) - aliases.keys()
        if unknown:
            errors.append(
                {"id": record.entry.id, "error": f"Unavailable source paths: {sorted(unknown)}"}
            )
    if saved.get("revision"):
        try:
            revision_plan(saved)
        except ValueError as exc:
            errors.append({"error": str(exc)})
    if not parsed.finding_count and not saved.get("revision"):
        errors.append(
            {"error": "No findings; report incomplete research rather than an empty import"}
        )
    return {
        "valid": not errors,
        "entries": parsed.finding_count,
        "errors": errors,
        "path": VIEW,
        "state": saved["state"],
        "coverage": dossier_coverage(saved["document"], set(aliases)),
        "note": "Shape and references only; counts are informational, not a completion gate.",
    }


class ValidateDossierTool(_DossierTool):
    name = "validate_dossier"
    input_model = DossierInput
    model_description = (
        "Check saved JSON syntax, finding IDs, source paths and related IDs. Does not judge facts."
    )

    async def apply(
        self,
        conn: AsyncConnection,
        authority: Any,
        saved: dict[str, Any],
        aliases: dict[str, UUID],
        inputs: ToolInput,
    ) -> dict[str, Any]:
        return validation(saved, aliases)


class FinishDossierTool(_DossierTool):
    name = "finish_dossier"
    input_model = DossierInput
    model_description = (
        "After critically reviewing and correcting the JSON against the formation skill, freeze "
        "it and import each finding programmatically into this subject's claim store. Returns "
        "claim IDs and per-finding outcomes, not a semantic quality judgment. Repeating resumes "
        "the same import without duplicate claims. Continue to narrative/final report afterward."
    )

    async def apply(
        self,
        conn: AsyncConnection,
        authority: Any,
        saved: dict[str, Any],
        aliases: dict[str, UUID],
        inputs: ToolInput,
    ) -> dict[str, Any]:
        check = validation(saved, aliases)
        if not check["valid"]:
            return {"finished": False, **check}
        body = encode(saved["document"])
        digest = hashlib.sha256(body).hexdigest()
        if saved["state"] == "complete":
            await mark_account_import_ready(conn, self.scope, saved)
            return {
                "finished": True,
                "path": VIEW,
                "artifact_key": saved["artifact_key"],
                "document_artifact_key": saved["document_artifact_key"],
                "claim_ids": [e["claim_id"] for e in saved["receipt"]["entries"]],
                **saved["receipt"],
                "entries": [{**e, "replayed": True} for e in saved["receipt"]["entries"]],
            }
        generation = saved.get("revision", {}).get("base_version")
        identity = f"research-json-dossier:{self.scope.job_id}:{digest}"
        if generation is not None:
            identity += f":revision-after:{generation}"
        import_id = uuid5(NAMESPACE_URL, identity)
        if saved.get("revision"):
            receipt = await import_revision(
                conn, self.storage, self.scope, authority, saved, aliases, body, digest, import_id
            )
        else:
            receipt = await import_research_dossier(
                conn,
                self.storage,
                self.scope,
                authority.grant,
                context_id=authority.context_id,
                actor_ref=authority.actor_ref,
                import_id=import_id,
                body=body,
                expected_sha256=digest,
                source_aliases=aliases,
            )
        receipt = json.loads(json.dumps(receipt, default=str))
        saved = await _persist(
            conn,
            self.storage,
            self.scope,
            authority.context_id,
            {
                **saved,
                "version": saved["version"] + 1,
                "state": (
                    "complete"
                    if receipt["complete"]
                    else "draft"
                    if saved.get("revision")
                    else "import_pending"
                ),
                "dossier_sha256": digest,
                "import_id": str(import_id),
                "receipt": receipt,
            },
        )
        await mark_account_import_ready(conn, self.scope, saved)
        return {
            "finished": receipt["complete"],
            "path": VIEW,
            "artifact_key": saved["artifact_key"],
            "document_artifact_key": saved["document_artifact_key"],
            "claim_ids": [e["claim_id"] for e in receipt["entries"] if e.get("claim_id")],
            "stored": receipt["stored"],
            "errors": receipt["errors"],
            "entries": receipt["entries"],
            "changes": receipt.get("changes", []),
            "reused": receipt.get("reused", 0),
        }
