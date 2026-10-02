"""Researcher-authored pages: scoped dossier references -> existing display blocks.

No model, classification or prose rewriting occurs here. C5 journals the full typed draft;
the receipt contains only persisted block IDs. Older specialist tools remain pinned unchanged.
"""

from __future__ import annotations

from typing import Any, ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from clue_api.arv2.account_research_claims import JobScope
from clue_api.arv2.display.recipes import OPTIONAL_SECTION_KEYS, read_recipes
from clue_api.arv2.quality_authority import resolve_authority
from clue_api.arv2.quality_json_dossier import _lock, read_json_dossier
from clue_api.arv2.quality_page_inputs import page_inputs
from clue_api.arv2.quality_page_tools import PublishPageOutput
from clue_api.arv2.quality_pages import (
    CitedItem,
    CitedSentence,
    PageDraft,
    PageSectionDraft,
    publish_page,
)
from clue_api.arv2.quality_person_release import read_parent_dossier
from clue_api.arv2.quality_tools import _ResearchWriteTool
from clue_toolbelt import ToolContext, ToolInput, ToolOutput, ToolResult


def owns_narrative(scope: JobScope) -> bool:
    return (
        scope.catalog_version == "v4"
        and int((scope.input_refs or {}).get("quality_recipe_version", 0)) >= 20
    )


class NarrativeSentence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=4000)
    finding_ids: tuple[str, ...] = ()
    account_finding_ids: tuple[str, ...] = ()
    claim_ids: tuple[UUID, ...] = ()
    kind: Literal["fact", "inference", "quote", "qualified", "gap"] = "fact"
    qualifications: tuple[str, ...] = ()


class NarrativeItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    h2: str
    body: tuple[NarrativeSentence, ...]
    contact_ids: tuple[UUID, ...] = ()
    send_line: NarrativeSentence | None = None


class NarrativeSection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    intro: tuple[NarrativeSentence, ...] = ()
    items: tuple[NarrativeItem, ...] = ()
    gaps: tuple[str, ...] = ()


class NarrativePage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page: Literal["overview", "insights", "contact"]
    sections: tuple[NarrativeSection, ...]


class WriteNarrativeInput(ToolInput):
    dossier_version: int = Field(ge=1)
    # The pinned v1 schema serves both subjects. Person-only requiredness is checked
    # against the authorized job scope below, not inferred from caller-supplied pages.
    account_dossier_version: int | None = None
    pages: tuple[NarrativePage, ...]


class NarrativeVersionError(ValueError):
    """Actionable version refusal, distinct from citation or page-shape errors."""

    def __init__(self, code: str, recovery: str):
        super().__init__(recovery)
        self.code = code


def finding_map(saved: dict[str, Any]) -> dict[str, UUID]:
    if not saved.get("receipt", {}).get("complete"):
        raise ValueError("Complete finish_dossier before writing the narrative")
    return {e["id"]: UUID(e["claim_id"]) for e in saved["receipt"]["entries"]}


def resolve_sentence(
    sentence: NarrativeSentence,
    own: dict[str, UUID],
    account: dict[str, UUID],
    allowed: set[UUID],
) -> CitedSentence:
    ids = list(sentence.claim_ids)
    for refs, mapping, label in (
        (sentence.finding_ids, own, "finding_ids"),
        (sentence.account_finding_ids, account, "account_finding_ids"),
    ):
        unknown = set(refs) - mapping.keys()
        if unknown:
            raise ValueError(
                f"Unknown {label}: {', '.join(sorted(unknown))}; read the saved dossier"
            )
        ids.extend(mapping[ref] for ref in refs)
    if bad := set(ids) - allowed:
        raise ValueError(
            f"Unavailable or out-of-scope claim IDs: {', '.join(map(str, sorted(bad)))}"
        )
    return CitedSentence(
        text=sentence.text,
        claim_ids=tuple(dict.fromkeys(ids)),
        kind=sentence.kind,
        qualifications=sentence.qualifications,
    )


def resolve_section(
    section: NarrativeSection, own: dict[str, UUID], account: dict[str, UUID], allowed: set[UUID]
) -> PageSectionDraft:
    def resolve(s: NarrativeSentence) -> CitedSentence:
        return resolve_sentence(s, own, account, allowed)

    return PageSectionDraft(
        key=section.key,
        intro=tuple(resolve(s) for s in section.intro),
        items=tuple(
            CitedItem(
                h2=i.h2,
                body=tuple(resolve(s) for s in i.body),
                contact_ids=i.contact_ids,
                send_line=resolve(i.send_line) if i.send_line else None,
            )
            for i in section.items
        ),
        gaps=section.gaps,
    )


class ReadNarrativeInput(ToolInput):
    pass


class ReadNarrativeOutput(ToolOutput):
    dossier_version: int
    account_dossier_version: int | None = None
    dossier_path: str = "/research/dossier/latest.json"
    account_dossier_path: str | None = None
    context_path: str = "/research/context.json"
    claims_path: str = "/research/claims/0.json"
    committee_path: str = "/research/committee.json"
    sections: dict[str, list[dict[str, Any]]]


class ReadNarrativeInputsTool(_ResearchWriteTool):
    name = "read_narrative_inputs"
    input_model = ReadNarrativeInput
    output_model: ClassVar[type[ToolOutput]] = ReadNarrativeOutput
    model_description = (
        "After finish_dossier, get current dossier versions, canonical paths and exact owned "
        "page sections. Existing claims include provider enrichment. Write your own narrative; "
        "reuse your investigation and seller context, rather than repeating all source reads. "
        "Pass dossier_version to write_research_narrative; person/contact writers must also "
        "pass the separate account_dossier_version returned here."
    )

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        authority = await self.authority(ctx)
        if authority.role != "account_research" or not owns_narrative(self.scope):
            raise ValueError("Narrative authoring belongs to the current subject researcher")
        async with ctx.conn_factory() as conn:
            saved = await read_json_dossier(conn, self.storage, self.scope, authority.context_id)
            finding_map(saved)
            parent = (
                await read_parent_dossier(conn, self.storage, self.scope, authority.context_id)
                if self.scope.person_subject_id
                else None
            )
            sections = {}
            for page in ("contact",) if self.scope.person_subject_id else ("overview", "insights"):
                sections[page] = [
                    {"key": r.section_key, "title": r.h1, "intro": r.narrative}
                    for r in await read_recipes(conn, page, workspace_id=self.scope.workspace_id)
                    if r.shared_from is None
                ]
        result = ReadNarrativeOutput(
            dossier_version=saved["version"],
            account_dossier_version=parent["version"] if parent else None,
            account_dossier_path=parent["path"] if parent else None,
            sections=sections,
        )
        return ToolResult(
            tool=self.name, version=self.version, references=result.model_dump(mode="json")
        )


class WriteResearchNarrativeTool(_ResearchWriteTool):
    name = "write_research_narrative"
    input_model = WriteNarrativeInput
    output_model: ClassVar[type[ToolOutput]] = PublishPageOutput
    model_description = (
        "Save your complete account (overview + insights) or person (contact) narrative after "
        "claim import. Copy dossier_version and sections from read_narrative_inputs. For a "
        "person/contact narrative, account_dossier_version is REQUIRED, even if no account "
        "findings are cited; copy that separate field from the same receipt. Account writers "
        "omit it or use null. finding_ids "
        "refer to your dossier; account_finding_ids only to a person's parent account dossier. "
        "claim_ids may cite additional scoped stored claims. Code maps references to existing "
        "display blocks without rewriting prose. Shared sections are projected, not authored. "
        "Return is a compact publication receipt; no research, claim extraction or model call."
    )

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        args = WriteNarrativeInput.model_validate(inputs)
        authority = await self.authority(ctx)
        # Recheck authority under the dossier lock, as dossier writers do.
        async with ctx.conn_factory() as conn:
            await _lock(conn, self.scope)
            authority = await resolve_authority(conn, self.scope, authority.execution_id)
            if authority.role != "account_research" or not owns_narrative(self.scope):
                raise ValueError("Narrative authoring belongs to the current subject researcher")
            # Roll back *all* pages if a later page fails; never return a half-published pair.
            try:
                async with conn.begin_nested():
                    ids = await self._write(conn, authority, args)
                result = PublishPageOutput(status="published", block_ids=ids)
            except ValueError as exc:
                result = PublishPageOutput(
                    status="refused",
                    error_code=exc.code
                    if isinstance(exc, NarrativeVersionError)
                    else "narrative_reference_or_shape",
                    recovery=str(exc)[:400],
                )
        return ToolResult(
            tool=self.name, version=self.version, references=result.model_dump(mode="json")
        )

    async def _write(
        self, conn: Any, authority: Any, args: WriteNarrativeInput
    ) -> tuple[UUID, ...]:
        scope = self.scope
        saved = await read_json_dossier(conn, self.storage, scope, authority.context_id)
        if saved.get("state") != "complete":
            raise NarrativeVersionError(
                "narrative_import_incomplete",
                "Your dossier import is incomplete. Complete finish_dossier, then call "
                "read_narrative_inputs before writing the narrative.",
            )
        if saved["version"] != args.dossier_version:
            raise NarrativeVersionError(
                "narrative_dossier_version_stale",
                f"dossier_version={args.dossier_version} does not match current version "
                f"{saved['version']}. Call read_narrative_inputs, review the changed dossier "
                "and refresh affected prose/references before retrying with its version.",
            )
        own = finding_map(saved)
        account = {}
        if scope.person_subject_id:
            if args.account_dossier_version is None:
                raise NarrativeVersionError(
                    "narrative_account_dossier_version_missing",
                    "Missing account_dossier_version: person/contact narratives require it, "
                    "even without account citations. Copy account_dossier_version from your "
                    "read_narrative_inputs receipt (not dossier_version) into the write request. "
                    "If unavailable, call read_narrative_inputs. Preserve your draft; no new "
                    "research or claim import is needed for this missing argument.",
                )
            parent = await read_parent_dossier(conn, self.storage, scope, authority.context_id)
            if parent["version"] != args.account_dossier_version:
                raise NarrativeVersionError(
                    "narrative_account_dossier_version_stale",
                    f"account_dossier_version={args.account_dossier_version} does not match "
                    f"current parent version {parent['version']}. Call read_narrative_inputs, "
                    "review the changed parent dossier and refresh affected prose/references "
                    "before retrying with its account_dossier_version.",
                )
            account = finding_map(parent)
        elif args.account_dossier_version is not None:
            raise NarrativeVersionError(
                "narrative_account_dossier_version_unexpected",
                "Account overview/insights writers have no separate parent account dossier. "
                "Omit account_dossier_version or set it to null; keep dossier_version from "
                "read_narrative_inputs.",
            )
        expected = {"contact"} if scope.person_subject_id else {"overview", "insights"}
        if len(args.pages) != len(expected) or {p.page for p in args.pages} != expected:
            raise ValueError(f"Write exactly these owned pages: {', '.join(sorted(expected))}")
        subjects = list(
            (
                await page_inputs(
                    conn,
                    scope,
                    context_id=authority.context_id,
                    page="contact" if scope.person_subject_id else "overview",
                )
            ).subjects
        )
        allowed = set(
            (
                await conn.execute(
                    text("""SELECT c.id FROM claim c
            JOIN claim_quality_current q ON q.claim_id=c.id
            WHERE c.workspace_id=:ws AND c.entity_id=ANY(:subjects)
              AND (q.context_id IS NULL OR q.context_id=:context)
              AND c.superseded_by IS NULL"""),
                    {
                        "ws": scope.workspace_id,
                        "subjects": subjects,
                        "context": authority.context_id,
                    },
                )
            ).scalars()
        )
        model = (
            await conn.execute(
                text("""SELECT answering_model FROM agent_model_call
            WHERE workspace_id=:ws AND execution_id=:execution ORDER BY started_at DESC LIMIT 1"""),
                {"ws": scope.workspace_id, "execution": authority.execution_id},
            )
        ).scalar_one_or_none()
        drafts = []
        for page in args.pages:
            recipes = await read_recipes(conn, page.page, workspace_id=scope.workspace_id)
            keys = {r.section_key for r in recipes if r.shared_from is None}
            given = [s.key for s in page.sections]
            if (
                len(given) != len(set(given))
                or not set(given) <= keys
                or not keys - OPTIONAL_SECTION_KEYS <= set(given)
            ):
                raise ValueError(
                    f"{page.page}: write each owned section once: {', '.join(sorted(keys))}"
                )
            drafts.append(
                PageDraft(
                    page=page.page,
                    expected_dependency_sha256="0" * 64,
                    sections=tuple(
                        resolve_section(s, own, account, allowed) for s in page.sections
                    ),
                )
            )
        ids: list[UUID] = []
        for draft in drafts:
            ids.extend(
                await publish_page(
                    conn,
                    self.storage,
                    scope,
                    context_id=authority.context_id,
                    execution_id=authority.execution_id,
                    model=model or "governed-researcher",
                    draft=draft,
                )
            )
        return tuple(ids)
