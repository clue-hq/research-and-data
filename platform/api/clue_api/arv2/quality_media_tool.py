"""Versioned media claims share the ordinary proposal writer and correction path."""

from dataclasses import asdict
from typing import ClassVar

from clue_api.arv2.quality_claims import TranscriptProposal, submit_proposal
from clue_api.arv2.quality_tools import ResearchClaimReceipt, _ResearchWriteTool
from clue_toolbelt import ToolContext, ToolInput, ToolOutput, ToolResult


class SubmitTranscriptClaimInput(ToolInput):
    proposal: TranscriptProposal


class TranscriptClaimReceipt(ResearchClaimReceipt):
    recovery: str | None = None


class SubmitTranscriptClaimTool(_ResearchWriteTool):
    name = "submit_transcript_claim"
    input_model = SubmitTranscriptClaimInput
    output_model: ClassVar[type[ToolOutput]] = TranscriptClaimReceipt
    model_description = (
        "Submit an attributed statement from one exact transcript version and contiguous range. "
        "Read the source and its /research/transcripts/<version>/0.json segment view first. "
        "A personal voice needs a same-recording self-introduction and consistent speaker label; "
        "episode titles and model labels alone remain qualified. Repairs require rechecking "
        "current "
        "versions. Recover refused references through /evidence/index.json without a paid call."
    )

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        args = SubmitTranscriptClaimInput.model_validate(inputs)
        authority = await self.authority(ctx)
        if authority.role == "research_narrative":
            raise ValueError("narrative specialist requests claim work through the parent")
        async with ctx.conn_factory() as conn:
            receipt = await submit_proposal(
                conn,
                self.storage,
                self.scope,
                authority.grant,
                args.proposal,
                context_id=authority.context_id,
                actor_ref=authority.actor_ref,
                purge_unevidenced=self.purge_unevidenced,
            )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references=TranscriptClaimReceipt(
                **asdict(receipt),
                recovery=(
                    "Read /evidence/index.json, then the transcript segment view; correct the "
                    "reference using a new proposal key. Do not repeat acquisition."
                    if receipt.status == "refused"
                    else None
                ),
            ).model_dump(mode="json"),
        )
