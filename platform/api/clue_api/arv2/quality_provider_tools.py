"""Govern existing research acquisitions without giving specialists provider or legacy writes.

The wrapper journals intent before dispatch and retains the complete tool result by reference.
An interrupted dispatch is not purchased again. Saved source evidence remains independently
readable even if no result receipt could be committed. Provider charges keep their existing owner.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar, Literal, cast, get_args
from uuid import UUID

from pydantic import BaseModel, Field, JsonValue, ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.execution import SPILL_THRESHOLD_BYTES
from clue_api.arv2 import research_operations as operations
from clue_api.arv2.account_exa_brief import uses_account_discovery
from clue_api.arv2.account_research_tools import (
    ToolRuntime,
    build_account_tools,
    build_person_tools,
)
from clue_api.arv2.person_exa_brief import uses_person_exa_brief
from clue_api.arv2.quality_authority import resolve_authority
from clue_api.arv2.quality_execution import reserve, retry_lock_conflict
from clue_api.arv2.quality_source_navigation import operation_source_navigation
from clue_storage import (
    artifact_key,
    content_address,
    record_artifact,
    retain_artifact,
)
from clue_toolbelt import (
    ReplayPolicy,
    ReplaySafety,
    Tool,
    ToolContext,
    ToolEffectClass,
    ToolInput,
    ToolOutput,
    ToolResult,
)

AcquisitionName = Literal[
    "fetch_page",
    "search_web",
    "read_ats_board",
    "lookup_company",
    "research_deep",
    "discover_people",
    "read_people_result",
    "lookup_person",
    "enrich_contact",
    "discover_media",
    "read_media",
    "search_transcripts",
    "open_transcript",
]
ACQUISITIONS = frozenset(get_args(AcquisitionName))

#: Version 3 (recipe 43, founder 2026-11-10): the footprint jobs join; ``discover_media`` leaves
#: (its Exa search lives on only as find_videos' fallback). Versions 1 and 2 are unchanged.
AcquisitionNameV3 = Literal[
    "fetch_page",
    "search_web",
    "read_ats_board",
    "lookup_company",
    "research_deep",
    "discover_people",
    "read_people_result",
    "lookup_person",
    "enrich_contact",
    "read_media",
    "search_transcripts",
    "open_transcript",
    "find_podcasts",
    "find_videos",
    "find_handles",
    "linkedin_activity",
    "x_posts",
    "instagram_posts",
    "facebook_posts",
    "company_linkedin_posts",
]
ACQUISITIONS_V3 = frozenset(get_args(AcquisitionNameV3))


class AcquireResearchInput(ToolInput):
    operation: AcquisitionName
    arguments: dict[str, JsonValue]


class AcquireResearchInputV3(ToolInput):
    operation: AcquisitionNameV3
    arguments: dict[str, JsonValue]


class AcquireResearchReceipt(ToolOutput):
    operation_id: UUID
    status: Literal["completed", "refused", "outcome_unknown"]
    result_path: str | None = None
    error_code: str | None = None
    recovery: str | None = None
    replayed: bool = False


#: Outcomes that are a failure on our side, not an answer: repeating the identical call runs it
#: again instead of replaying the failure (a social history that could not be read, or stopped
#: part-way). An uncertain dispatch is never among them, so nothing paid for is bought twice blind.
RETRY_ON_REPEAT = frozenset({"history_partial", "history_unavailable"})


def settle_outcome(value: Any) -> tuple[bool, bool, str | None]:
    """``(unknown, refused, code)`` for a job's result. A job may name its own outcome in
    ``outcome_code`` (the social histories do); a ``partial`` result is not refused, since what it
    read is kept, but its code still tells the agent it is incomplete."""
    domain_state = value.get("state") if isinstance(value, dict) else None
    unknown = domain_state in {"unknown", "dispatched", "reserved"}
    refused = isinstance(value, dict) and (
        bool(value.get("error"))
        or domain_state
        in {
            "unavailable",
            "empty",
            "ambiguous",
            "not_found",
            "refused",
            "failed",
        }
    )
    named = value.get("outcome_code") if isinstance(value, dict) else None
    code = (
        "dispatch_outcome_unknown"
        if unknown
        else str(named or value.get("code") or value.get("gap") or "provider_refusal")
        if refused
        else str(named)
        if named
        else None
    )
    return unknown, refused, code


class AcquireResearchTool(Tool):
    name = "acquire_research_evidence"
    input_model: ClassVar[type[ToolInput]] = AcquireResearchInput
    output_model: ClassVar[type[ToolOutput]] = AcquireResearchReceipt
    effect_class = ToolEffectClass.WRITE
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="research job + operation + canonical arguments; uncertain dispatch stops",
        operation_id_required=True,
    )
    model_description = (
        "Acquire originals using company, people, web, ATS and media providers. "
        "AI Ark supplies basic typed enrichment; Exa and company pages inform substantive research "
        "and company descriptions. AI Ark descriptive prose is excluded from research inputs; "
        "its typed facts are mapped directly to enrichment fields. "
        "Both web and AI Ark SMART can discover people. "
        "Read /research/capabilities/0.json for operation names and argument schemas. "
        "Read result bodies through the returned path; originals through /evidence/. "
        "Refusals and uncertain dispatches are gaps, not successful research. Never repeat an "
        "uncertain purchase with cosmetically changed arguments."
    )

    def __init__(self, runtime: ToolRuntime | None):
        self.runtime = runtime
        available = (
            []
            if runtime is None
            else (
                build_person_tools(runtime)
                if runtime.scope.person_subject_id
                else build_account_tools(runtime)
            )
        )
        self.operations = {t.name: t for t in available if t.name in ACQUISITIONS}

    def capabilities(self) -> list[dict[str, object]]:
        return [
            {
                "operation": name,
                "description": tool.description,
                "arguments_schema": cast(
                    type[BaseModel], tool.get_input_schema()
                ).model_json_schema(),
            }
            for name, tool in sorted(self.operations.items())
        ]

    async def begin_dispatch(
        self, ctx: ToolContext, operation: str, arguments: dict[str, Any]
    ) -> tuple[Any, bool]:
        """Authorize, reserve the shared allowance and begin the ledger entry in one transaction,
        retried once if Postgres aborts it as a lock-conflict victim (no provider call happens
        inside it, and each step is idempotent on the tool call's operation id)."""
        runtime = self.runtime
        assert runtime is not None and ctx.execution_id is not None
        execution_id = ctx.execution_id

        async def begin(conn: AsyncConnection) -> tuple[Any, bool]:
            authority = await resolve_authority(conn, runtime.scope, execution_id)
            if authority.role != "account_research":
                raise ValueError("specialists request acquisition through their parent")
            await reserve(
                conn,
                authority.grant.scope,
                execution_id=execution_id,
                kind="tool",
                activity_id=UUID(str(ctx.operation_id)),
            )
            return await operations.begin(
                conn, runtime.operation_scope, "quality_tool:" + operation, arguments
            )

        return await retry_lock_conflict(ctx.conn_factory, begin)

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        args = cast(AcquireResearchInput, self.input_model.model_validate(inputs))
        runtime = self.runtime
        if runtime is None:
            raise ValueError("acquisition is not bound in this research execution")
        if ctx.workspace_id != runtime.scope.workspace_id or ctx.execution_id is None:
            raise ValueError("acquisition needs its bound research execution")
        tool = self.operations.get(args.operation)
        validation_error: str | None = None
        if tool is None:
            validation_error = "operation_unavailable_for_subject"
        else:
            try:
                cast(type[BaseModel], tool.get_input_schema()).model_validate(args.arguments)
            except ValidationError:
                validation_error = "invalid_acquisition_arguments"
        operation, won = await self.begin_dispatch(ctx, args.operation, args.arguments)
        if not won:
            # The provider ledger committed before indexing. Recover an interrupted index using
            # saved originals, even when the tool's own final receipt was never committed.
            from clue_api.arv2.quality_acquisition import recover_acquisitions

            assert runtime.storage is not None
            async with ctx.conn_factory() as conn:
                await recover_acquisitions(conn, runtime.storage, runtime.operation_scope)
                from clue_api.arv2.quality_media import index_transcripts

                await index_transcripts(conn, runtime.storage, runtime.operation_scope)
            if operation.artifact_key and operation.state in {"succeeded", "failed", "unknown"}:
                return self.receipt(
                    AcquireResearchReceipt(
                        operation_id=operation.operation_id,
                        status="outcome_unknown"
                        if operation.state == "unknown"
                        else "completed"
                        if operation.state == "succeeded"
                        else "refused",
                        result_path=f"/research/operations/{operation.operation_id}/0.json",
                        error_code=operation.error_code,
                        replayed=True,
                    )
                )
            return self.receipt(
                AcquireResearchReceipt(
                    operation_id=operation.operation_id,
                    status="outcome_unknown",
                    replayed=True,
                    error_code="dispatch_outcome_unknown",
                    recovery="Inspect /evidence/index.json; record the gap without repurchasing.",
                )
            )
        # The existing tool normalizes provider refusals. Exceptions after dispatch remain unknown;
        # a retry will return the above refusal instead of calling the provider again.
        value: Any
        if validation_error:
            # A correctable planning mistake is a durable, non-spending refusal, not a runtime
            # failure. Authority checks above remain hard failures, including specialist misuse.
            value = {
                "state": "refused",
                "code": validation_error,
                "recovery": "Read /research/capabilities/0.json and retry with a supported "
                "operation and its exact arguments schema.",
            }
        else:
            assert tool is not None
            raw = await tool.ainvoke(args.arguments)
            value = json.loads(raw) if isinstance(raw, str) else raw
        unknown, refused, code = settle_outcome(value)
        assert runtime.storage is not None
        async with ctx.conn_factory() as conn:
            from clue_api.arv2.quality_media import index_transcripts

            if args.operation in {"read_media", "search_transcripts", "open_transcript"}:
                await index_transcripts(conn, runtime.storage, runtime.operation_scope)
            # Privacy may have been withdrawn during the hop. Keep settlement, refuse new exposure.
            authority = await resolve_authority(conn, runtime.scope, ctx.execution_id)
            if (
                (
                    (
                        args.operation == "research_deep"
                        and runtime.scope.subject_kind == "account"
                        and int((runtime.scope.input_refs or {}).get("quality_recipe_version", 5))
                        >= 8
                    )
                    or (
                        (
                            uses_person_exa_brief(runtime.scope)
                            or uses_account_discovery(runtime.scope)
                        )
                        and args.operation in {"search_web", "fetch_page", "research_deep"}
                    )
                )
                and isinstance(value, dict)
                and value.get("result_ref")
            ):
                value["source_navigation"] = await operation_source_navigation(
                    conn, authority.grant, UUID(str(value["result_ref"]))
                )
                if uses_person_exa_brief(runtime.scope) or uses_account_discovery(runtime.scope):
                    value["source_review_path"] = (
                        f"/research/source-review/{value['result_ref']}/0.json"
                    )
            body = json.dumps(value, ensure_ascii=False, sort_keys=True).encode()
            sha = content_address(body)
            key = artifact_key(runtime.scope.workspace_id, sha)
            await record_artifact(
                conn,
                storage_key=key,
                workspace_id=runtime.scope.workspace_id,
                content_sha256=sha,
                media_type="application/json",
                size_bytes=len(body),
            )
            await runtime.storage.put(key, body, media_type="application/json")
            await conn.execute(
                text("""
              INSERT INTO agent_artifact_subject
                (workspace_id,artifact_key,subject_entity_id,binding_kind)
              VALUES (:ws,:key,:subject,'context') ON CONFLICT DO NOTHING
            """),
                {
                    "ws": runtime.scope.workspace_id,
                    "key": key,
                    "subject": runtime.scope.person_subject_id or runtime.scope.account_id,
                },
            )
            await retain_artifact(
                conn,
                workspace_id=runtime.scope.workspace_id,
                storage_key=key,
                reference_kind="research_tool_output",
                reference_id=str(operation.operation_id),
            )
            # A tool result may summarize any originals acquired by this job. Conservatively
            # invalidate the receipt on erasure of any such original, without copying source text.
            await conn.execute(
                text("""
              INSERT INTO artifact_derivation(workspace_id,parent_key,child_key)
              SELECT workspace_id,artifact_key,:key FROM arv2_evidence_source
              WHERE workspace_id=:ws AND job_id=:job AND artifact_key<>:key
              ON CONFLICT DO NOTHING
            """),
                {"ws": runtime.scope.workspace_id, "job": runtime.scope.job_id, "key": key},
            )
            await conn.execute(
                text("""
              UPDATE arv2_research_operation SET state=:state,artifact_key=:key,
                error_code=:code,finished_at=now()
              WHERE operation_id=:id AND workspace_id=:ws AND owner_token=:owner
            """),
                {
                    "id": operation.operation_id,
                    "ws": runtime.scope.workspace_id,
                    "owner": operation.owner_token,
                    "state": "unknown" if unknown else "failed" if refused else "succeeded",
                    "key": key,
                    "code": code,
                },
            )
        return self.settled_receipt(
            operation.operation_id, value, unknown=unknown, refused=refused, code=code
        )

    def settled_receipt(
        self, operation_id: UUID, value: Any, *, unknown: bool, refused: bool, code: str | None
    ) -> ToolResult:
        """The receipt for a freshly settled operation (v2 adds a preview of what came back)."""
        return self.receipt(
            AcquireResearchReceipt(
                operation_id=operation_id,
                status="outcome_unknown" if unknown else "refused" if refused else "completed",
                result_path=f"/research/operations/{operation_id}/0.json",
                error_code=code,
                recovery=value.get("recovery") if isinstance(value, dict) else None,
            )
        )

    def receipt(self, value: AcquireResearchReceipt) -> ToolResult:
        return ToolResult(
            tool=self.name, version=self.version, references=value.model_dump(mode="json")
        )


PREVIEW_SNIPPET = 300
#: Every entry is previewed (founder ruling 2026-10-10). The preview stays this far under the spill
#: line, leaving room for the rest of the receipt, so a long result list is never replaced by a file
#: pointer; when it would not fit, the snippets shorten in these steps and no entry is dropped.
PREVIEW_MAX_BYTES = SPILL_THRESHOLD_BYTES - 2 * 1024
#: (snippet, title) lengths, tried in order: snippets go first, titles only after them.
_SHORTENING_STEPS = (
    (PREVIEW_SNIPPET, 300),
    (200, 300),
    (120, 300),
    (60, 300),
    (0, 300),
    (0, 120),
    (0, 60),
)


class ReceiptHit(BaseModel):
    title: str | None = None
    url: str | None = None
    published: str | None = None
    path: str | None = None
    snippet: str | None = None


class AcquireResearchReceiptV2(AcquireResearchReceipt):
    status: Literal["completed", "empty", "refused", "outcome_unknown"]  # type: ignore[assignment]
    result_count: int | None = None
    preview: list[ReceiptHit] = Field(default_factory=list)


def _snippet(*parts: Any, limit: int = PREVIEW_SNIPPET) -> str | None:
    if limit <= 0:
        return None
    for part in parts:
        if isinstance(part, list):
            part = " ".join(str(p) for p in part if p)
        if isinstance(part, str) and part.strip():
            text = " ".join(part.split())
            return text[: limit - 1] + "…" if len(text) > limit else text
    return None


def receipt_preview(value: Any) -> tuple[list[dict[str, str | None]], int | None, bool]:
    """``(hits, result_count, empty)`` for a settled acquisition body.

    One entry per result, in the provider's order, so the agent sees everything that came back
    without spending a model round opening the result file. Every entry is kept; only the snippets
    shorten, and only as far as the spill line needs (2026-10-10: run 3's preview, capped at eight
    saved files, showed four of ten results and hid the account's ABM case study).
    """
    if not isinstance(value, dict):
        return [], None, False
    sources = [
        s
        for s in (value.get("source_navigation") or {}).get("sources") or []
        if isinstance(s, dict) and s.get("url")
    ]
    # A result is saved as its provider record and then its page snapshot: the last file for a
    # link is the page text, the one worth opening.
    by_url = {str(s.get("url")): s for s in sources}
    rows = value.get("results") or value.get("hits") or []
    entries: list[tuple[dict[str, str | None], tuple[Any, ...]]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        url = row.get("url")
        source = by_url.get(str(url), {})
        entries.append(
            (
                {
                    "title": _snippet(row.get("title"), source.get("title")),
                    "url": url,
                    "published": row.get("published")
                    or row.get("publishedDate")
                    or source.get("published_at"),
                    "path": source.get("path"),
                },
                (row.get("highlights"), row.get("summary"), row.get("text"), row.get("text_head")),
            )
        )
    if not entries:
        entries = [
            (
                {
                    "title": _snippet(s.get("title")),
                    "url": url,
                    "published": s.get("published_at"),
                    "path": s.get("path"),
                },
                (),
            )
            for url, s in by_url.items()
        ]
    report = value.get("report")
    if isinstance(report, str) and report.strip():
        entries.insert(
            0, ({"title": "Report", "url": None, "published": None, "path": None}, (report,))
        )
    count = value.get("n_results")
    if not isinstance(count, int):
        count = len(rows) if isinstance(rows, list) and rows else len(by_url) or None
    # Only a body that lists results (a search, page read or report) can come back empty; an
    # enrichment profile, a queued job or a media item always came back with something.
    listed = any(key in value for key in ("results", "hits", "n_results", "report"))
    empty = listed and (
        (count == 0) or (not entries and not (isinstance(report, str) and report.strip()))
    )
    hits: list[dict[str, str | None]] = []
    for snippet_limit, title_limit in _SHORTENING_STEPS:
        hits = [
            ReceiptHit(
                **{**fields, "title": _snippet(fields["title"], limit=title_limit)},
                snippet=_snippet(*parts, limit=snippet_limit),
            ).model_dump()
            for fields, parts in entries
        ]
        if len(json.dumps(hits, default=str)) <= PREVIEW_MAX_BYTES:
            break
    return hits, count, empty


class AcquireResearchToolV2(AcquireResearchTool):
    """Recipe 26: the receipt previews what came back and says ``empty`` when nothing did."""

    version = "2"
    output_model: ClassVar[type[ToolOutput]] = AcquireResearchReceiptV2
    model_description = (
        AcquireResearchTool.model_description
        + " Each receipt previews what came back (titles, links, evidence paths, snippets); "
        "read result_path only when you need the full text. status empty means nothing came back."
    )

    def settled_receipt(
        self, operation_id: UUID, value: Any, *, unknown: bool, refused: bool, code: str | None
    ) -> ToolResult:
        hits, count, empty = receipt_preview(value)
        status: Literal["completed", "empty", "refused", "outcome_unknown"]
        if unknown:
            status = "outcome_unknown"
        elif refused:
            status = "refused"
        elif empty:
            status = "empty"
        else:
            status = "completed"
        return self.receipt(
            AcquireResearchReceiptV2(
                operation_id=operation_id,
                status=status,
                result_path=f"/research/operations/{operation_id}/0.json",
                error_code=code,
                recovery=value.get("recovery") if isinstance(value, dict) else None,
                result_count=count,
                preview=[ReceiptHit.model_validate(h) for h in hits],
            )
        )


class AcquireResearchToolV3(AcquireResearchToolV2):
    """Recipe 43: the footprint jobs (podcasts, videos, handles, LinkedIn, X, Instagram, Facebook,
    company pages) run through the same wrapper; ``discover_media`` is no longer offered."""

    version = "3"
    input_model = AcquireResearchInputV3

    def __init__(self, runtime: ToolRuntime | None):
        super().__init__(runtime)
        if runtime is None:
            return
        from clue_api.arv2.footprint_operations import footprint_tools

        kept = {n: t for n, t in self.operations.items() if n in ACQUISITIONS_V3}
        self.operations = {**kept, **{t.name: t for t in footprint_tools(runtime)}}

    async def begin_dispatch(
        self, ctx: ToolContext, operation: str, arguments: dict[str, Any]
    ) -> tuple[Any, bool]:
        """As in version 2, except that an identical call after a failure on our side
        (:data:`RETRY_ON_REPEAT`) runs again as a new attempt instead of replaying the failure.
        Attempt ``n`` is keyed on ``{"arguments": ..., "attempt": n}``, so each attempt is still
        recorded once and the first attempt keeps the plain arguments' key."""
        attempt = 0
        while True:
            request = arguments if attempt == 0 else {"arguments": arguments, "attempt": attempt}
            operation_row, won = await super().begin_dispatch(ctx, operation, request)
            if (
                won
                or operation_row.state not in {"succeeded", "failed"}
                or operation_row.error_code not in RETRY_ON_REPEAT
            ):
                return operation_row, won
            attempt += 1
