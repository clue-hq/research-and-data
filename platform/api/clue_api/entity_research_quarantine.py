"""M8D R1 active-path quarantine for superseded entity-research orchestration.

R1 deliberately preserves the provider, snapshot, claim, receipt, and historical execution
substrates while removing the old orchestration from *new* work.  This module is the single loud
boundary used by both production phase composition and the historical tool addresses:

* a project run that reaches ``DEEP`` cannot schedule the old account orchestrator; and
* a completed journal/idempotency record may replay under its exact historical tool descriptor,
  but a cache miss is refused before the wrapped tool's preconditions or body can run.

The wrapper retains the exact descriptor so durable historical results remain schema-valid.  It
never delegates to the wrapped implementation.  Production invokers resolve completed journal
records before invoking the tool, and the pure runner resolves completed idempotency records before
calling preconditions, which makes "replay-only" a mechanically enforced state rather than prose.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from clue_core import PhaseContext, PhaseResult, ProjectPhase
from clue_toolbelt import (
    PreconditionFailed,
    PreconditionFailure,
    Tool,
    ToolContext,
    ToolDescriptor,
    ToolEstimate,
    ToolInput,
    ToolResult,
)

__all__ = [
    "ENTITY_RESEARCH_AGENT_NOT_COMPOSED",
    "QUARANTINED_ENTITY_RESEARCH_TOOL_ADDRESSES",
    "EntityResearchAgentNotComposed",
    "EntityResearchQuarantineComposition",
    "EntityResearchQuarantinePhaseHandler",
    "ReplayOnlyEntityResearchTool",
    "quarantine_entity_research_tool",
]


ENTITY_RESEARCH_AGENT_NOT_COMPOSED = "entity_research_agent_not_composed"

# Exact historical addresses whose implementations embody one or more R1-forbidden flows.  Keeping
# this list exact prevents a future replacement version from being quarantined accidentally.
QUARANTINED_ENTITY_RESEARCH_TOOL_ADDRESSES = frozenset(
    {
        "enrich_account_gaps@1",
        "enrich_selected_accounts@1",
        "launch_account_deep@1",
        "profile_contact@1",
        "profile_contact@2",
        "research_account_gaps@1",
        "research_account_gaps@2",
        "resolve_committee@1",
        "run_deep_account@1",
    }
)


def _failure() -> PreconditionFailure:
    return PreconditionFailure(
        reason_code=ENTITY_RESEARCH_AGENT_NOT_COMPOSED,
        message=(
            "the M8D entity-research agent replacement is not composed; this historical "
            "orchestration is available only through an already-completed exact replay"
        ),
    )


class EntityResearchAgentNotComposed(RuntimeError):
    """A new entity-research run reached the intentionally empty R1 composition slot."""

    reason_code = ENTITY_RESEARCH_AGENT_NOT_COMPOSED

    def __init__(self, *, project_run_id: object | None = None) -> None:
        suffix = "" if project_run_id is None else f" for project run {project_run_id}"
        super().__init__(f"{self.reason_code}{suffix}")


class EntityResearchQuarantinePhaseHandler:
    """Fail before the former DEEP scheduler/orchestrator can be constructed or invoked."""

    phase = ProjectPhase.DEEP

    async def run(self, ctx: PhaseContext) -> PhaseResult:
        raise EntityResearchAgentNotComposed(project_run_id=ctx.project_run_id)


@dataclass(frozen=True, slots=True)
class EntityResearchQuarantineComposition:
    """The deliberately minimal replacement for the former ``DeepPhaseComposition`` bundle."""

    handler: EntityResearchQuarantinePhaseHandler
    reason_code: str = ENTITY_RESEARCH_AGENT_NOT_COMPOSED


class ReplayOnlyEntityResearchTool(Tool):
    """Retain one exact tool contract for completed replay while refusing every cache miss."""

    def __init__(self, inner: Tool) -> None:
        self._inner = inner

    @property
    def descriptor(self) -> ToolDescriptor:
        return self._inner.descriptor

    @property
    def input_model(self) -> type[ToolInput]:  # type: ignore[override]
        return self._inner.input_model

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        del inputs
        return ToolEstimate(
            detail={
                "availability": "exact_replay_only",
                "reason_code": ENTITY_RESEARCH_AGENT_NOT_COMPOSED,
            }
        )

    async def preconditions(
        self,
        inputs: ToolInput,
        ctx: ToolContext,
    ) -> Sequence[PreconditionFailure]:
        del inputs, ctx
        return (_failure(),)

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        # Defence in depth for callers that violate the sanctioned runner boundary.
        del inputs, ctx
        raise PreconditionFailed((_failure(),))


def quarantine_entity_research_tool(tool: Tool) -> Tool:
    """Return an exact-descriptor replay-only view when ``tool`` is an R1 historical address."""

    if tool.descriptor.address not in QUARANTINED_ENTITY_RESEARCH_TOOL_ADDRESSES:
        return tool
    return ReplayOnlyEntityResearchTool(tool)
