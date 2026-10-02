"""Governed narrative page inputs/publication with the same owner for initial and later refresh."""

from typing import Any, ClassVar, cast
from uuid import UUID

from sqlalchemy import text

from clue_api.arv2.display.recipes import Page
from clue_api.arv2.quality_page_inputs import page_inputs
from clue_api.arv2.quality_pages import PageDraft, publish_page
from clue_api.arv2.quality_tools import _ResearchWriteTool
from clue_toolbelt import ToolContext, ToolInput, ToolOutput, ToolResult


class ReadPageInputsInput(ToolInput):
    page: Page


class ReadPageInputsOutput(ToolOutput):
    generation_id: UUID
    dependency_sha256: str
    section_keys: tuple[str, ...]
    context_path: str = "/research/context.json"
    claims_path: str = "/research/claims/0.json"
    committee_path: str = "/research/committee.json"


class ReadPageInputsTool(_ResearchWriteTool):
    name = "read_research_page_inputs"
    input_model = ReadPageInputsInput
    output_model: ClassVar[type[ToolOutput]] = ReadPageInputsOutput
    model_description = (
        "Pin the current dependencies before composing a whole contextual page. Returns section "
        "keys and original context/claim paths. Reread after writing value narratives, correcting "
        "claims or receiving new people. Publish using this exact dependency digest."
    )

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        args = ReadPageInputsInput.model_validate(inputs)
        authority = await self.authority(ctx)
        async with ctx.conn_factory() as conn:
            value = await page_inputs(
                conn, self.scope, context_id=authority.context_id, page=args.page
            )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references=ReadPageInputsOutput(
                generation_id=value.generation.generation_id,
                dependency_sha256=value.sha256,
                section_keys=tuple(
                    r["section_key"] for r in cast(list[dict[str, Any]], value.manifest["recipes"])
                ),
            ).model_dump(mode="json"),
        )


class PublishPageInput(ToolInput):
    draft: PageDraft


class PublishPageOutput(ToolOutput):
    status: str
    block_ids: tuple[UUID, ...] = ()
    error_code: str | None = None
    recovery: str | None = None


class PublishResearchPageTool(_ResearchWriteTool):
    name = "publish_research_page"
    input_model: ClassVar[type[ToolInput]] = PublishPageInput
    output_model: ClassVar[type[ToolOutput]] = PublishPageOutput
    model_description = (
        "Publish a complete contextual page using the digest from read_research_page_inputs. "
        "Every fact/inference needs applicable claim IDs; quote means exact original wording. "
        "Cite value-narrative claims for seller-specific arguments. Include gaps in every empty "
        "section. Publication refuses obsolete inputs, invalid claims and unsupported outreach."
    )

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        args = cast(
            PublishPageInput | PublishResearchInput, self.input_model.model_validate(inputs)
        )
        authority = await self.authority(ctx)
        if authority.role != "research_narrative":
            raise ValueError("page publication belongs to the narrative specialist")
        try:
            async with ctx.conn_factory() as conn:
                # The model identity comes from the governed turn journal, never model arguments.
                model = (
                    await conn.execute(
                        text(
                            "SELECT answering_model FROM agent_model_call "
                            "WHERE workspace_id=:ws AND execution_id=:execution "
                            "ORDER BY started_at DESC LIMIT 1"
                        ),
                        {"ws": self.scope.workspace_id, "execution": authority.execution_id},
                    )
                ).scalar_one_or_none()
                ids = await publish_page(
                    conn,
                    self.storage,
                    self.scope,
                    context_id=authority.context_id,
                    execution_id=authority.execution_id,
                    model=model or "governed-research-narrative",
                    draft=args.draft,
                )
            result = PublishPageOutput(status="published", block_ids=ids)
        except ValueError as exc:
            result = PublishPageOutput(
                status="refused", error_code="page_validation_refused", recovery=str(exc)[:400]
            )
        return ToolResult(
            tool=self.name, version=self.version, references=result.model_dump(mode="json")
        )


class ResearchPageDraft(PageDraft):
    expected_dependency_sha256: str = ""


class PublishResearchInput(ToolInput):
    draft: ResearchPageDraft


class PublishAdvisoryResearchPageTool(PublishResearchPageTool):
    version = "2"
    input_model = PublishResearchInput
    model_description = (
        "Publish the research page, including uncertain, conflicting and source-reported findings. "
        "Use claim citations where available and plain-language qualifications where helpful. "
        "No employment verification, quality threshold or outreach eligibility is required. "
        "Seller-specific reasoning belongs directly in the narrative. All recorded findings are "
        "also displayed below the synthesis. Dependency digests are optional."
    )
