"""M8D R1: old entity-research orchestration is exact-replay-only and cannot spend."""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path

import pytest

from clue_api.entity_research_quarantine import (
    ENTITY_RESEARCH_AGENT_NOT_COMPOSED,
    QUARANTINED_ENTITY_RESEARCH_TOOL_ADDRESSES,
    ReplayOnlyEntityResearchTool,
    quarantine_entity_research_tool,
)
from clue_api.toolbelt_wiring import build_toolbelt
from clue_toolbelt import (
    PreconditionFailed,
    StoredInvocation,
    Tool,
    ToolContext,
    ToolInput,
    ToolOutput,
    ToolRegistry,
    ToolResult,
    body_sha256,
    invoke_tool,
)
from tests.toolbelt.conftest import InMemoryStore, human_ctx


class _Input(ToolInput):
    value: int


class _Output(ToolOutput):
    value: int


class _FormerDeepTool(Tool):
    name = "run_deep_account"
    version = "1"
    input_model = _Input
    output_model = _Output

    def __init__(self) -> None:
        self.provider_dispatches = 0

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        del ctx
        assert isinstance(inputs, _Input)
        self.provider_dispatches += 1
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={"value": inputs.value},
        )


def _registry(tool: Tool) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(tool, make_default=True)
    return registry


def test_every_forbidden_historical_address_is_replay_only_in_live_toolbelt() -> None:
    registry = build_toolbelt(storage=None, gateway=None)
    wrapped = {
        descriptor.address
        for descriptor in registry.all_descriptors()
        if isinstance(
            registry.get(descriptor.name, descriptor.version),
            ReplayOnlyEntityResearchTool,
        )
    }
    assert wrapped == QUARANTINED_ENTITY_RESEARCH_TOOL_ADDRESSES


def test_production_composition_does_not_reference_quarantined_collaborators() -> None:
    """Freeze the cut at the two production roots instead of trusting constructor defaults."""

    root = Path(__file__).resolve().parents[2]
    forbidden = {
        "AccountResearchAgentRuntime",
        "GovernedAccountProfiler",
        "ProductionContactResearchPreparer",
        "build_deep_phase_handler",
        "build_production_exa_deep_resolver_provider",
        "build_production_sumble_committee_preparer",
    }
    for relative in (
        "platform/api/clue_api/fleet_main.py",
        "platform/api/clue_api/run_composition.py",
    ):
        tree = ast.parse((root / relative).read_text())
        referenced = {
            node.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Name)
        } | {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
        }
        assert forbidden.isdisjoint(referenced), relative


def test_new_invocation_refuses_before_former_provider_body() -> None:
    inner = _FormerDeepTool()
    quarantined = quarantine_entity_research_tool(inner)

    async def scenario() -> None:
        with pytest.raises(PreconditionFailed) as excinfo:
            await invoke_tool(
                _registry(quarantined),
                quarantined.descriptor.name,
                {"value": 7},
                human_ctx(),
                version=quarantined.descriptor.version,
                idempotency_ttl_s=86_400,
            )
        assert excinfo.value.reason_codes == (ENTITY_RESEARCH_AGENT_NOT_COMPOSED,)
        assert inner.provider_dispatches == 0

    import asyncio

    asyncio.run(scenario())


def test_completed_exact_idempotency_record_replays_without_former_provider_body() -> None:
    inner = _FormerDeepTool()
    quarantined = quarantine_entity_research_tool(inner)
    store = InMemoryStore()
    body: dict[str, object] = {"value": 11}
    key = "historical-exact-replay"
    store.rows[("ws_test", key)] = StoredInvocation(
        workspace_id="ws_test",
        idempotency_key=key,
        body_sha256=body_sha256(body),
        tool_name=quarantined.descriptor.address,
        status="completed",
        response_json=ToolResult(
            tool=quarantined.descriptor.name,
            version=quarantined.descriptor.version,
            references={"value": 11},
        ).model_dump(mode="json"),
        created_at=datetime.now(UTC),
    )

    async def scenario() -> None:
        result = await invoke_tool(
            _registry(quarantined),
            quarantined.descriptor.name,
            body,
            human_ctx(),
            version=quarantined.descriptor.version,
            idempotency_key=key,
            store=store,
            idempotency_ttl_s=86_400,
        )
        assert result.replayed
        assert result.references == {"value": 11}
        assert inner.provider_dispatches == 0

    import asyncio

    asyncio.run(scenario())
