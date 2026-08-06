"""M8D R4 pure contracts: hidden authority, task-local causation, and exact composition."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage

from clue_agents.entity_research_contracts import (
    EntityAgentRole,
    EntityResearchToolBinding,
    EntityResearchToolCall,
    canonical_sha256,
)
from clue_agents.entity_research_runtime import (
    ActiveEntityResearchToolExecution,
    EntityResearchAgentFactory,
    EntityResearchAgentRuntime,
    EntityResearchRuntimeError,
    current_entity_research_tool_execution,
)
from clue_agents.entity_research_tools import EntityResearchSemanticToolInput
from clue_agents.model import ScriptedAgentChatModel
from clue_api.entity_research_tools import (
    EntityResearchProviderCausationStore,
    EntityResearchResultIntegrityError,
    EntityResearchResultStore,
    EntityResearchToolAuthorityError,
    EntityResearchToolRequestStore,
    GovernedEntityResearchToolFactory,
    ProviderActionBinding,
    ProviderObservationDisposition,
    ProviderOperationReservation,
)
from clue_core.entity_research import (
    FieldSourceAuthority,
    GovernedResearchToolRequest,
    PersistedResearchToolResult,
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


def test_semantic_request_cannot_apply_one_fields_source_to_another_field() -> None:
    async def scenario() -> None:
        context = _context(ResearchSubjectType.CONTACT, EntityAgentRole.CONTACT)
        selection = context.authorization.selection
        subject = context.authorization.selected_subject
        assert subject.contact_authority is not None
        original_field = subject.contact_authority.admitted_field_keys[0]
        second_field = "contact.facet.professional_interests"
        widened_authority = subject.contact_authority.model_copy(
            update={
                "admitted_field_keys": (original_field, second_field),
                "admitted_source_keys": ("exa_deep", "sumble_people"),
                "field_source_authority": (
                    FieldSourceAuthority(
                        field_key=original_field,
                        source_keys=("exa_deep",),
                    ),
                    FieldSourceAuthority(
                        field_key=second_field,
                        source_keys=("sumble_people",),
                    ),
                ),
            }
        )
        widened_subject = subject.model_copy(update={"contact_authority": widened_authority})
        widened_selection = selection.model_copy(
            update={
                "subjects": tuple(
                    widened_subject if item.subject_entity_id == subject.subject_entity_id else item
                    for item in selection.subjects
                ),
                "admitted_field_keys": (original_field, second_field),
                "admitted_source_keys": ("exa_deep", "sumble_people"),
                "field_source_authority": (
                    FieldSourceAuthority(field_key=original_field, source_keys=("exa_deep",)),
                    FieldSourceAuthority(field_key=second_field, source_keys=("sumble_people",)),
                ),
            }
        )
        context = context.model_copy(
            update={
                "authorization": context.authorization.model_copy(
                    update={"selection": widened_selection}
                )
            }
        )
        arguments = {
            "field_keys": [original_field],
            "source_keys": ["sumble_people"],
            "questions": [context.authorization.effective_research_questions[0]],
        }
        active = ActiveEntityResearchToolExecution(
            context=context,
            call=EntityResearchToolCall(
                tool_call_id="cross-product-attempt",
                tool_name="research_contact_deep",
                tool_version=1,
                tool_input_sha256=canonical_sha256(arguments),
                arguments=arguments,
            ),
            journal_event_ref=f"entity-agent-event:{uuid4()}",
        )
        with pytest.raises(EntityResearchToolAuthorityError, match="no authorized requested"):
            await EntityResearchToolRequestStore(conn_factory=_unused_conn).record(
                active=active,
                semantic=EntityResearchSemanticToolInput.model_validate(arguments),
            )

    from tests.db.conftest import run_async

    run_async(scenario())


def test_provider_operation_contract_is_not_tied_to_external_research_ids() -> None:
    operation = ProviderOperationReservation(
        provider_kind="sumble_people",
        operation_ref="sumble-committee-operation:opaque-provider-id",
        workspace_id="workspace-a",
        project_id="project-a",
        project_run_id=uuid4(),
        subject_type=ResearchSubjectType.ACCOUNT,
        target_entity_id=uuid4(),
        source_key="sumble_people",
        field_keys=(),
        request_artifact_ref="artifact:sumble-request",
        reserved_at=datetime.now(UTC),
        observation_disposition=ProviderObservationDisposition.CAUSED,
    )
    assert operation.provider_kind == "sumble_people"
    assert operation.operation_ref == "sumble-committee-operation:opaque-provider-id"


def test_result_message_bound_cannot_be_below_inline_threshold(tmp_path: Any) -> None:
    with pytest.raises(ValueError, match="cannot be below"):
        EntityResearchResultStore(
            storage=FsStorage(tmp_path / "bounded"),
            conn_factory=_unused_conn,
            inline_max_bytes=1024,
            message_max_bytes=1023,
        )


def test_final_index_is_remeasured_against_agent_message_bound(tmp_path: Any) -> None:
    fixture = json.loads(
        (
            Path(__file__).parents[1] / "fixtures" / "entity_research" / "r0_contract_fixture.json"
        ).read_text()
    )
    result = PersistedResearchToolResult.model_validate(fixture["tool_result"])
    store = EntityResearchResultStore(
        storage=FsStorage(tmp_path / "remeasure"),
        conn_factory=_unused_conn,
        inline_max_bytes=1,
        message_max_bytes=256,
    )
    with pytest.raises(EntityResearchResultIntegrityError, match="agent-message bound"):
        store._agent_message_bytes(result)


def test_bounded_follow_up_context_retains_discovered_subject_identity_and_fields() -> None:
    store = EntityResearchToolRequestStore(
        conn_factory=_unused_conn,
        prior_context_max_bytes=1024,
    )
    parent = {
        "result_ref": "research-result:parent",
        "operation_ref": "sumble-committee-operation:parent",
        "subject_type": "account",
        "target_entity_id": str(uuid4()),
        "padding": "x" * 2_000,
        "fields": [],
        "discovered_subjects": [
            {
                "subject_type": "contact",
                "target_entity_id": str(uuid4()),
                "parent_account_id": str(uuid4()),
                "identity_claim_refs": ["claim:identity"],
                "association_evidence_refs": ["claim:association"],
                "fields": [
                    {
                        "field_key": "contact.role.current_title",
                        "outcome": "found",
                        "value": "Chief Operating Officer",
                        "claim_refs": ["claim:title"],
                        "verification_status": "supported",
                    }
                ],
            }
        ],
    }
    compact = json.loads(store._bounded_prior_context(json.dumps(parent).encode("utf-8")))
    assert "padding" not in compact
    subject = compact["discovered_subjects"][0]
    assert subject["identity_claim_refs"] == ["claim:identity"]
    assert subject["association_evidence_refs"] == ["claim:association"]
    assert subject["fields"][0]["value"] == "Chief Operating Officer"


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
