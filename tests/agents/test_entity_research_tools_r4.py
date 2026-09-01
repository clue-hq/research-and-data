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
from pydantic import ValidationError

from clue_agents.account_entity_research import (
    CommitteeRoleInference,
    DiscoverBuyingCommitteeInput,
    RecordCommitteeRoleInferencesInput,
)
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
    EntityResearchGovernedRejection,
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
        settle_terminal: Any,
    ) -> Sequence[Any]:
        del request, before_dispatch, settle_terminal
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


def test_committee_role_inference_schema_is_closed_and_contains_no_engine_authority() -> None:
    inference = CommitteeRoleInference.model_json_schema()["properties"]
    assert set(inference) == {
        "contact_entity_id",
        "role",
        "confidence",
        "reasoning",
        "evidence_claim_ids",
    }
    assert set(RecordCommitteeRoleInferencesInput.model_json_schema()["properties"]) == {
        "inferences"
    }
    assert inference["role"]["$ref"].endswith("/$defs/Persona")
    assert inference["confidence"]["minimum"] == 0.0
    assert inference["confidence"]["maximum"] == 1.0
    assert inference["reasoning"]["minLength"] == 1
    assert inference["reasoning"]["maxLength"] == 2_000
    assert inference["evidence_claim_ids"]["minItems"] == 1
    assert inference["evidence_claim_ids"]["maxItems"] == 16


def test_governed_provider_tool_returns_actionable_bounded_schema_feedback(
    tmp_path: Path,
) -> None:
    context = _context(ResearchSubjectType.ACCOUNT, EntityAgentRole.ACCOUNT)
    provider_names = {
        "research_account_deep",
        "enrich_account",
        "discover_buying_committee",
    }
    engine_names = (
        set(context.tool_surface.tool_names)
        - provider_names
        - {"read_research_result", "read_evidence"}
    )
    factory = GovernedEntityResearchToolFactory(
        requests=EntityResearchToolRequestStore(conn_factory=_unused_conn),
        causation=EntityResearchProviderCausationStore(conn_factory=_unused_conn),
        results=EntityResearchResultStore(
            storage=FsStorage(tmp_path / "schema-feedback"),
            conn_factory=_unused_conn,
        ),
    )
    bindings = factory.compose(
        surface=context.tool_surface,
        provider_actions={
            name: ProviderActionBinding(
                action=_Action(),
                version=1,
                args_schema=(
                    DiscoverBuyingCommitteeInput
                    if name == "discover_buying_committee"
                    else EntityResearchSemanticToolInput
                ),
            )
            for name in provider_names
        },
        engine_tools={
            name: EntityResearchToolBinding(tool=_tool(name), version=1) for name in engine_names
        },
    )
    committee = next(
        binding.tool for binding in bindings if binding.name == "discover_buying_committee"
    )
    assert callable(committee.handle_validation_error)
    with pytest.raises(ValidationError) as error:
        DiscoverBuyingCommitteeInput.model_validate(
            {
                "field_keys": ["account.operational_pain"],
                "source_keys": ["sumble_people"],
                "questions": ["Which exact people form the committee?"],
                "buying_unit_scope": {
                    "scope_id": str(uuid4()),
                    "account_entity_id": str(uuid4()),
                    "office_label": "Boston office",
                    "locality": "Boston",
                    "target_functions": ["Operations"],
                    "evidence_refs": [f"research-evidence:{uuid4()}"],
                },
            }
        )
    rendered = committee.handle_validation_error(error.value)
    payload = json.loads(rendered)
    assert payload["error"] == "semantic_tool_input_validation_failed"
    assert payload["details"] == [
        {
            # The committee schema registers a per-field correction, so the refusal names the
            # exact repair as well as the fault. Naming only the fault is what let the live agent
            # retry the same malformed shape until its runtime budget ran out (run ``dc86340f``).
            "correction": (
                "'field_keys' must be omitted or []: committee discovery enumerates people, "
                "never account fields. Research fields with research_account_deep or "
                "enrich_account instead."
            ),
            "location": ["field_keys"],
            "message": "Tuple should have at most 0 items after validation, not 1",
            "type": "too_long",
        }
    ]
    assert "account.operational_pain" not in rendered


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
        # R10 species 1: applying one field's source to another is a model mistake the agent can
        # repair by dropping the pairing, so it refuses as a governed rejection, never a
        # suspension. A comprehensive field may also legitimately carry an empty authority.
        with pytest.raises(EntityResearchGovernedRejection) as refusal:
            await EntityResearchToolRequestStore(conn_factory=_unused_conn).record(
                active=active,
                semantic=EntityResearchSemanticToolInput.model_validate(arguments),
            )
        assert refusal.value.code == "field_source_authority_mismatch"
        assert "no authorized requested" in refusal.value.detail

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


def test_governed_rejection_renders_bounded_recoverable_feedback() -> None:
    """R10 partial-failure policy: a governed refusal is agent-repairable, never a suspension.

    The rendered payload is the exact error tool-message content the model sees; it must be
    bounded, typed, and must tell the model the job is still alive.
    """

    from clue_api.entity_research_tools import EntityResearchGovernedRejection

    rejection = EntityResearchGovernedRejection("provider_rejected", "detail " * 1_000)
    payload = json.loads(rejection.render())
    assert payload["error"] == "governed_research_rejection"
    assert payload["code"] == "provider_rejected"
    assert payload["recoverable"] is True
    assert len(payload["detail"]) <= 1_000
    assert "finalize honestly" in payload["guidance"]


def test_a_committee_call_is_constructible_when_the_confirmed_plan_has_no_question() -> None:
    """Live regression: an unrestricted committee plan made the call impossible to build.

    The confirmed directive allowed committee discovery, authorised ``sumble_people`` and left
    every selector unrestricted — but it confirmed no committee question, while the tool demanded
    at least one *verbatim confirmed* question. The agent correctly refused to synthesize one, so
    the committee obligation could never be attempted, coverage could never close, and the job
    looped to the recursion cap. An empty tuple is the honest value; the engine separately refuses
    any question the confirmed set does not contain, so nothing can be invented here.
    """

    from clue_agents.account_entity_research import AccountCommitteePlanProjection
    from clue_api.account_entity_research_composition import _committee_plan_block

    admitted = DiscoverBuyingCommitteeInput.model_validate(
        {
            "source_keys": ["sumble_people"],
            "buying_unit_scope": {
                "scope_id": str(uuid4()),
                "account_entity_id": str(uuid4()),
                "office_label": "Boston office",
                "locality": "Boston",
                "target_functions": ["Operations"],
                "evidence_refs": [f"research-evidence:{uuid4()}"],
            },
        }
    )
    assert admitted.questions == ()

    block = _committee_plan_block(
        AccountCommitteePlanProjection(
            directive_ref="research-directive:fixture:v1",
            candidate_cap=200,
        )
    )
    assert "leave `questions` empty" in block
    assert "never invent" in block

    with_question = _committee_plan_block(
        AccountCommitteePlanProjection(
            directive_ref="research-directive:fixture:v2",
            candidate_cap=200,
            questions=("Which exact people form the committee?",),
        )
    )
    assert "leave `questions` empty" not in with_question
    assert "Which exact people form the committee?" in with_question


def test_account_model_authored_questions_narrow_to_the_confirmed_set() -> None:
    """Model question text is not authority; the confirmed directive is.

    Live (job 5d9dfe7b): a zero-question comprehensive directive confirms no questions, so a
    model that insisted on adding intent text was refused on every committee/enrichment
    composition, then refused assessment for the unattempted pair, and looped to the recursion
    cap. For ACCOUNT subjects the request store now narrows to the confirmed subset instead of
    refusing (an emptied set is the valid Slice-B zero-question shape); CONTACT stays strict
    because its directives must carry confirmed questions.
    """

    async def scenario() -> None:
        account_context = _context(ResearchSubjectType.ACCOUNT, EntityAgentRole.ACCOUNT)
        authorized_field = account_context.authorization.effective_admitted_field_keys[0]
        authorized_source = account_context.authorization.effective_field_source_authority[
            0
        ].source_keys[0]
        arguments = {
            "field_keys": [authorized_field],
            "source_keys": [authorized_source],
            "questions": ["an invented question the directive never confirmed"],
        }
        active = ActiveEntityResearchToolExecution(
            context=account_context,
            call=EntityResearchToolCall(
                tool_call_id="narrow-not-refuse",
                tool_name="research_account_deep",
                tool_version=1,
                tool_input_sha256=canonical_sha256(arguments),
                arguments=arguments,
            ),
            journal_event_ref=f"entity-agent-event:{uuid4()}",
        )
        # The old widening refusal raised EntityResearchToolAuthorityError before any DB use.
        # Narrowing lets record() proceed to its durable write, which this pure composition
        # harness deliberately cannot perform — reaching the DB boundary IS the proof the
        # authority gate no longer refuses.
        with pytest.raises(AssertionError, match="must not open Postgres"):
            await EntityResearchToolRequestStore(conn_factory=_unused_conn).record(
                active=active,
                semantic=EntityResearchSemanticToolInput.model_validate(arguments),
            )

        contact_context = _context(ResearchSubjectType.CONTACT, EntityAgentRole.CONTACT)
        contact_subject = contact_context.authorization.selected_subject
        assert contact_subject.contact_authority is not None
        contact_field = contact_subject.contact_authority.admitted_field_keys[0]
        contact_arguments = {
            "field_keys": [contact_field],
            "source_keys": ["exa_deep"],
            "questions": ["an invented contact question"],
        }
        contact_active = ActiveEntityResearchToolExecution(
            context=contact_context,
            call=EntityResearchToolCall(
                tool_call_id="contact-still-strict",
                tool_name="research_contact_deep",
                tool_version=1,
                tool_input_sha256=canonical_sha256(contact_arguments),
                arguments=contact_arguments,
            ),
            journal_event_ref=f"entity-agent-event:{uuid4()}",
        )
        with pytest.raises(EntityResearchToolAuthorityError, match="widened confirmed questions"):
            await EntityResearchToolRequestStore(conn_factory=_unused_conn).record(
                active=contact_active,
                semantic=EntityResearchSemanticToolInput.model_validate(contact_arguments),
            )

    from tests.db.conftest import run_async

    run_async(scenario())
