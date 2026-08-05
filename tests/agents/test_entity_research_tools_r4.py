"""M8D R4 pure contracts: hidden authority, task-local causation, and exact composition."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

import pytest
from langchain_core.messages import AIMessage

from clue_agents.entity_research_contracts import EntityAgentRole, EntityResearchToolBinding
from clue_agents.entity_research_runtime import (
    EntityResearchAgentFactory,
    EntityResearchAgentRuntime,
    EntityResearchRuntimeError,
    current_entity_research_tool_execution,
)
from clue_agents.entity_research_tools import EntityResearchSemanticToolInput
from clue_agents.model import ScriptedAgentChatModel
from clue_api.entity_research_tools import (
    EntityResearchProviderCausationStore,
    EntityResearchResultStore,
    EntityResearchToolAuthorityError,
    EntityResearchToolRequestStore,
    GovernedEntityResearchToolFactory,
    ProviderActionBinding,
)
from clue_core.entity_research import (
    GovernedResearchToolRequest,
    ResearchSubjectType,
)
from clue_storage import FsStorage
from tests.agents.test_entity_research_runtime_r3 import (
    Checkpointers,
    Finalizer,
    Guard,
    Journal,
    Models,
    _context,
    _definition,
    _proposal,
    _tool,
)


@asynccontextmanager
async def _unused_conn() -> AsyncIterator[Any]:
    raise AssertionError("pure R4 composition test must not open Postgres")
    yield  # pragma: no cover


class _Action:
    async def execute(
        self,
        request: GovernedResearchToolRequest,
        *,
        before_dispatch: Any,
    ) -> Sequence[Any]:
        del request, before_dispatch
        raise AssertionError("pure composition test must not dispatch a provider")


def test_model_facing_research_schema_contains_intent_and_no_engine_authority() -> None:
    properties = EntityResearchSemanticToolInput.model_json_schema()["properties"]
    assert set(properties) == {
        "field_keys",
        "source_keys",
        "questions",
        "parent_operation_ref",
        "parent_observation_ref",
        "follow_up_reason",
    }
    forbidden = {
        "workspace_id",
        "project_id",
        "product_id",
        "project_run_id",
        "research_run_id",
        "job_id",
        "target_entity_id",
        "agent_turn_id",
        "agent_execution_id",
        "tool_call_id",
        "budget_reservation_key",
        "idempotency_key",
    }
    assert forbidden.isdisjoint(properties)


def test_exact_account_and_contact_surfaces_compose_without_provider_sdks(
    tmp_path: Any,
) -> None:
    for subject in (ResearchSubjectType.ACCOUNT, ResearchSubjectType.CONTACT):
        context = _context(
            subject,
            (
                EntityAgentRole.ACCOUNT
                if subject is ResearchSubjectType.ACCOUNT
                else EntityAgentRole.CONTACT
            ),
        )
        semantic_name = (
            "research_account_deep"
            if subject is ResearchSubjectType.ACCOUNT
            else "research_contact_deep"
        )
        provider_names = set(context.tool_surface.tool_names).intersection(
            {
                "research_account_deep",
                "enrich_account",
                "discover_buying_committee",
                "research_contact_deep",
                "enrich_contact",
                "reveal_contact_channel",
                "validate_contact_channel",
            }
        )
        assert semantic_name in provider_names
        engine_names = (
            set(context.tool_surface.tool_names)
            - provider_names
            - {
                "read_research_result",
                "read_evidence",
            }
        )
        factory = GovernedEntityResearchToolFactory(
            requests=EntityResearchToolRequestStore(conn_factory=_unused_conn),
            causation=EntityResearchProviderCausationStore(conn_factory=_unused_conn),
            results=EntityResearchResultStore(
                storage=FsStorage(tmp_path / subject.value),
                conn_factory=_unused_conn,
            ),
        )
        bindings = factory.compose(
            surface=context.tool_surface,
            provider_actions={
                name: ProviderActionBinding(action=_Action(), version=1) for name in provider_names
            },
            engine_tools={
                name: EntityResearchToolBinding(tool=_tool(name), version=1)
                for name in engine_names
            },
        )
        assert tuple(binding.name for binding in bindings) == context.tool_surface.tool_names
        assert all("provider" not in binding.tool.get_input_jsonschema() for binding in bindings)

        with pytest.raises(EntityResearchToolAuthorityError, match="differs from exact surface"):
            factory.compose(
                surface=context.tool_surface,
                provider_actions={
                    name: ProviderActionBinding(action=_Action(), version=1)
                    for name in provider_names
                },
                engine_tools={
                    name: EntityResearchToolBinding(tool=_tool(name), version=1)
                    for name in engine_names
                    if name != next(iter(engine_names))
                },
            )

        misplaced = next(iter(provider_names))
        with pytest.raises(
            EntityResearchToolAuthorityError,
            match="provider-capable semantic tools require governed provider actions",
        ):
            factory.compose(
                surface=context.tool_surface,
                provider_actions={
                    name: ProviderActionBinding(action=_Action(), version=1)
                    for name in provider_names
                    if name != misplaced
                },
                engine_tools={
                    **{
                        name: EntityResearchToolBinding(tool=_tool(name), version=1)
                        for name in engine_names
                    },
                    misplaced: EntityResearchToolBinding(tool=_tool(misplaced), version=1),
                },
            )


def test_parallel_handlers_receive_isolated_active_tool_authority() -> None:
    async def scenario() -> None:
        context = _context(ResearchSubjectType.ACCOUNT, EntityAgentRole.ACCOUNT)
        observed: dict[str, tuple[str, str]] = {}

        async def capture(name: str) -> None:
            active = current_entity_research_tool_execution()
            observed[name] = (active.call.tool_call_id, active.journal_event_ref)

        first, second = context.tool_surface.tool_names[:2]
        proposal = _proposal(context)
        model = ScriptedAgentChatModel(
            responses=(
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": first, "args": {"value": "one"}, "id": "r4-call-one"},
                        {"name": second, "args": {"value": "two"}, "id": "r4-call-two"},
                    ],
                ),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "ResearchFinalizationProposal",
                            "args": proposal.model_dump(mode="json"),
                            "id": "r4-final",
                        }
                    ],
                ),
            )
        )
        journal = Journal()
        guard = Guard()
        runtime = EntityResearchAgentRuntime(
            factory=EntityResearchAgentFactory(models=Models(model), journal=journal, guard=guard),
            checkpointers=Checkpointers(),
            journal=journal,
            finalizer=Finalizer(),
        )
        await runtime.run(
            definition=_definition(
                context,
                callbacks={first: capture, second: capture},
            )
        )
        assert observed[first][0] == "r4-call-one"
        assert observed[second][0] == "r4-call-two"
        assert observed[first][1] != observed[second][1]
        assert all(
            reference.startswith("entity-agent-event:") for _, reference in observed.values()
        )
        with pytest.raises(EntityResearchRuntimeError, match="outside the governed"):
            current_entity_research_tool_execution()

    from tests.db.conftest import run_async

    run_async(scenario())
