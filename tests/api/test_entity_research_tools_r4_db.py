"""M8D R4 live-Postgres Exa fixture proof from governed tool call through lossless reads."""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.contracts import ModelPolicy
from clue_agents.entity_research_contracts import (
    EntityAgentJournalEventKind,
    EntityAgentRole,
    EntityResearchAgentDefinition,
    EntityResearchAgentSuspension,
    EntityResearchJournalEvent,
    EntityResearchResource,
    EntityResearchResourceBundle,
    EntityResearchRuntimeContext,
    EntityResearchToolBinding,
    EntityResearchToolCall,
    canonical_sha256,
)
from clue_agents.entity_research_runtime import (
    _ACTIVE_TOOL_EXECUTION,
    ActiveEntityResearchToolExecution,
    EntityResearchAgentFactory,
    EntityResearchAgentRuntime,
)
from clue_agents.entity_research_tools import (
    EntityResearchSemanticToolInput,
    ReadResearchEvidenceInput,
)
from clue_agents.model import ScriptedAgentChatModel
from clue_api.contact_entity_research import ContactResearchStateStore
from clue_api.entity_research_runtime_wiring import (
    DbEntityResearchAgentJournal,
    PostgresEntityResearchCheckpointers,
)
from clue_api.entity_research_tools import (
    EntityResearchGovernedRejection,
    EntityResearchProviderCausationStore,
    EntityResearchProviderWait,
    EntityResearchResultStore,
    EntityResearchToolRequestStore,
    GovernedEntityResearchToolFactory,
    ProviderActionBinding,
    ProviderObservationDisposition,
    ProviderOperationReservation,
)
from clue_api.exa_contact_acquisition import ExaDeepContactAcquisitionService
from clue_api.exa_contact_materialization import (
    ExaDeepContactSnapshotMaterializer,
    ExaDeepContactSnapshotResolverProvider,
)
from clue_api.exa_deep_acquisition import ExaDeepAcquisitionCoordinator
from clue_api.exa_entity_research_tools import (
    ExaContactSemanticResearchAction,
    ExaEntityResearchProjectionBuilder,
)
from clue_core import EntityId, new_run_id
from clue_core.entity_research import (
    EntityAgentToolSurface,
    EntityResearchJobAuthorization,
    EntityResearchSelection,
    FieldSourceAuthority,
    GovernedResearchToolRequest,
    ResearchFollowUpReason,
    ResearchOperationKind,
    ResearchRunKind,
    ResearchRunLifecycleContract,
    ResearchSelectionBasis,
    ResearchSubjectType,
    SelectedContactResearchAuthority,
    SelectedResearchSubject,
)
from clue_db import db_lifespan
from clue_db import transaction as db_transaction
from clue_fleet import (
    DbEntityResearchJobStore,
    EntityResearchJobEnvelope,
    EntityResearchRunEnvelope,
)
from clue_research.compliance import DataSubjectRightsImpl
from clue_storage import FsStorage, get_artifact
from tests.agents.test_entity_research_runtime_r3 import (
    Checkpointers,
    Finalizer,
    Guard,
    Models,
    _context,
    _proposal,
    _tool,
)
from tests.agents.test_entity_research_tools_r4 import _Action
from tests.contact_research.test_c4_exa_contact_acquisition_materialization import (
    _FIELD,
    _payload,
    _seed,
    _TrackedConnFactory,
    _Transport,
)
from tests.profiling.conftest import migrated_db as migrated_db
from tests.profiling.conftest import require_profiling_db as require_profiling_db
from tests.profiling.conftest import rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_QUESTION = "Which attributable publications discuss referral operations?"
_SECOND_FIELD = "contact.facet.professional_interests"
_FOLLOW_UP_QUESTION = (
    "Which independent public source verifies the operational role described in that result?"
)


class _TransactionalTrackedConnFactory(_TrackedConnFactory):
    """Mirror a real ConnFactory transaction while retaining the no-I/O-under-DB assertion."""

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[AsyncConnection]:
        self.active += 1
        try:
            async with self.conn.begin_nested():
                yield self.conn
        finally:
            self.active -= 1


def _fleet_envelope(seed: Any, *, profile_sha256: str) -> EntityResearchRunEnvelope:
    intent = seed.intent
    legacy_target = intent.selection.body.targets[0]
    strong_refs = tuple(f"claim:{value}" for value in legacy_target.strong_identity_claim_ids)
    committee_refs = tuple(f"claim:{value}" for value in legacy_target.committee_claim_ids)
    policy_refs = (
        intent.selection.body.jurisdiction_policy_ref,
        intent.selection.body.use_policy_ref,
        intent.selection.body.retention_policy_ref,
    )
    approval_refs = (f"contact-selection:{intent.selection_id}",)
    field_authority = (FieldSourceAuthority(field_key=_FIELD, source_keys=("exa_deep",)),)
    target_authority = SelectedContactResearchAuthority(
        contact_selection_ref=f"contact-selection:{intent.selection_id}",
        contact_selection_sha256=intent.selection_sha256,
        contact_intent_ref=f"contact-intent:{intent.sha256()}",
        contact_intent_sha256=intent.sha256(),
        field_plan_ref=f"contact-field-plan:{intent.selection_id}",
        source_plan_ref=intent.source_profile_ref,
        admitted_field_keys=(_FIELD,),
        admitted_source_keys=("exa_deep",),
        field_source_authority=field_authority,
        research_questions=(_QUESTION,),
        facet_keys=("publications",),
        policy_refs=policy_refs,
        budget_envelope_ref=intent.budget_reservation_ref,
        budget_cap_cents=intent.budget_cap_cents,
        approval_refs=approval_refs,
    )
    selection = EntityResearchSelection(
        selection_id=uuid4(),
        workspace_id=intent.workspace_id,
        project_id=intent.project_id,
        product_id="prd_fixture_aura_ai",
        project_run_id=UUID(str(intent.project_run_id)),
        subject_type=ResearchSubjectType.CONTACT,
        account_entity_id=UUID(str(intent.account_entity_id)),
        subjects=(
            SelectedResearchSubject(
                subject_entity_id=UUID(str(intent.contact_entity_id)),
                basis=ResearchSelectionBasis.COMMITTEE_MEMBER,
                strong_identity_claim_refs=strong_refs,
                association_evidence_refs=strong_refs,
                committee_claim_refs=committee_refs,
                contact_authority=target_authority,
            ),
        ),
        directive_ref=f"account-research-directive:{intent.research_directive.directive_id}",
        directive_sha256=intent.research_directive.canonical_json_sha256,
        field_plan_ref=f"contact-field-plan:{intent.selection_id}",
        source_plan_ref=intent.source_profile_ref,
        admitted_field_keys=(_FIELD,),
        admitted_source_keys=("exa_deep",),
        field_source_authority=field_authority,
        research_questions=(_QUESTION,),
        facet_keys=("publications",),
        policy_refs=policy_refs,
        budget_envelope_ref=intent.budget_reservation_ref,
        approval_refs=approval_refs,
        confirmed_by=intent.selection.body.approved_by,
        confirmed_at=intent.selection.body.approved_at,
    )
    research_run_id = uuid4()
    lifecycle = ResearchRunLifecycleContract(
        run_id=research_run_id,
        run_kind=ResearchRunKind.CONTACT_RESEARCH,
        selection=selection,
        user_confirmed_launch=True,
        operations=(ResearchOperationKind.CONTACT_RESEARCH,),
    )
    authorization = EntityResearchJobAuthorization(
        job_id=uuid4(),
        research_run_id=research_run_id,
        subject_type=ResearchSubjectType.CONTACT,
        subject_entity_id=selection.subjects[0].subject_entity_id,
        parent_account_id=selection.account_entity_id,
        workspace_id=selection.workspace_id,
        project_id=selection.project_id,
        product_id=selection.product_id,
        project_run_id=selection.project_run_id,
        selection=selection,
        agent_profile_ref="agent-profile:contact-research:v1",
        agent_profile_sha256=profile_sha256,
        checkpoint_thread_id=f"checkpoint:{research_run_id}:{intent.contact_entity_id}",
        attempt_id=uuid4(),
        lease_id=uuid4(),
    )
    return EntityResearchRunEnvelope(
        lifecycle=lifecycle,
        jobs=(
            EntityResearchJobEnvelope(
                authorization=authorization,
                priority=0,
                budget_envelope_ref=selection.budget_envelope_ref,
                budget_cap_cents=Decimal("20"),
            ),
        ),
        budget_cap_cents=Decimal("20"),
        concurrency_limit=1,
    )


def _runtime_context(
    *,
    authorization: EntityResearchJobAuthorization,
    state_sha256: str,
    profile_body: str,
    agent_turn_id: UUID,
) -> EntityResearchRuntimeContext:
    base = _context(ResearchSubjectType.CONTACT, EntityAgentRole.CONTACT)
    profile = EntityResearchResource(
        kind="profile",
        ref=authorization.agent_profile_ref,
        version="v1",
        sha256=authorization.agent_profile_sha256,
        body=profile_body,
    )
    return EntityResearchRuntimeContext(
        agent_execution_id=authorization.attempt_id,
        agent_turn_id=agent_turn_id,
        role=EntityAgentRole.CONTACT,
        authorization=authorization,
        resources=EntityResearchResourceBundle(
            profile=profile,
            prompt=base.resources.prompt,
            skills=base.resources.skills,
        ),
        tool_surface=EntityAgentToolSurface(
            subject_type=ResearchSubjectType.CONTACT,
            tool_names=base.tool_surface.tool_names,
        ),
        stop_policy=base.stop_policy,
        facet_contract=base.facet_contract,
        current_state_sha256=state_sha256,
        job_budget_cap_cents=Decimal("20"),
        job_spent_cents=Decimal("0"),
        run_budget_remaining_cents=Decimal("20"),
    )


def test_governed_exa_tool_persists_complete_result_causation_reads_and_replay(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn() as conn:
            seed = await _seed(conn, storage, suffix="m8d-r4")
            connection = _TransactionalTrackedConnFactory(conn)
            profile_body = "role: contact-research\nframework: langchain-create-agent\n"
            profile_sha = hashlib.sha256(profile_body.encode()).hexdigest()
            envelope = _fleet_envelope(seed, profile_sha256=profile_sha)
            store = DbEntityResearchJobStore(conn_factory=connection)
            await store.launch(envelope)
            authorization = envelope.jobs[0].authorization
            job = await store.get_job(authorization.job_id)
            assert job is not None

            provider_payload = _payload("supported.json")
            provider_payload["results"][0]["text"] += " Clínica operations 🩺."
            transport = _Transport(provider_payload, connection)
            coordinator = ExaDeepAcquisitionCoordinator(
                transport=transport,
                storage=storage,
                conn_factory=connection,
            )
            acquisition = ExaDeepContactAcquisitionService(
                coordinator=coordinator,
                conn_factory=connection,
            )
            materializer = ExaDeepContactSnapshotMaterializer(
                provider=ExaDeepContactSnapshotResolverProvider(
                    storage=storage,
                    conn_factory=connection,
                ),
                conn_factory=connection,
            )
            projector = ExaEntityResearchProjectionBuilder(
                storage=storage,
                conn_factory=connection,
            )
            action = ExaContactSemanticResearchAction(
                intent=seed.intent,
                effective_policy=seed.policy,
                acquisition=acquisition,
                materializer=materializer,
                projector=projector,
                run_id=new_run_id(),
                observation_window="m8d-r4-governed-contact",
            )
            request_store = EntityResearchToolRequestStore(
                conn_factory=connection,
                storage=storage,
            )
            causation = EntityResearchProviderCausationStore(conn_factory=connection)
            result_store = EntityResearchResultStore(
                storage=storage,
                conn_factory=connection,
                inline_max_bytes=1,
            )
            tool_factory = GovernedEntityResearchToolFactory(
                requests=request_store,
                causation=causation,
                results=result_store,
            )

            async def run_turn(
                turn_id: UUID,
                call_id: str,
                *,
                parent_operation_ref: str | None = None,
                parent_observation_ref: str | None = None,
                follow_up_reason: ResearchFollowUpReason | None = None,
                questions: tuple[str, ...] = (_QUESTION,),
            ) -> EntityResearchRuntimeContext:
                current_job = await store.get_job(authorization.job_id)
                assert current_job is not None
                context = _runtime_context(
                    authorization=authorization,
                    state_sha256=current_job.current_state_sha256,
                    profile_body=profile_body,
                    agent_turn_id=turn_id,
                )
                provider_names = {
                    "research_contact_deep",
                    "enrich_contact",
                    "reveal_contact_channel",
                    "validate_contact_channel",
                }
                engine_names = (
                    set(context.tool_surface.tool_names)
                    - provider_names
                    - {
                        "read_research_result",
                        "read_evidence",
                    }
                )
                bindings = tool_factory.compose(
                    surface=context.tool_surface,
                    provider_actions={
                        name: ProviderActionBinding(
                            action=action,
                            version=1,
                        )
                        for name in provider_names
                    },
                    engine_tools={
                        name: EntityResearchToolBinding(tool=_tool(name), version=1)
                        for name in engine_names
                    },
                )
                proposal = _proposal(context)
                tool_args: dict[str, object] = {
                    "field_keys": [_FIELD],
                    "source_keys": ["exa_deep"],
                    "questions": list(questions),
                }
                if parent_operation_ref is not None:
                    tool_args.update(
                        {
                            "parent_operation_ref": parent_operation_ref,
                            "parent_observation_ref": parent_observation_ref,
                            "follow_up_reason": follow_up_reason,
                        }
                    )
                model = ScriptedAgentChatModel(
                    responses=(
                        AIMessage(
                            content="",
                            tool_calls=[
                                {
                                    "name": "research_contact_deep",
                                    "args": tool_args,
                                    "id": call_id,
                                }
                            ],
                        ),
                        AIMessage(
                            content="",
                            tool_calls=[
                                {
                                    "name": "ResearchFinalizationProposal",
                                    "args": proposal.model_dump(mode="json"),
                                    "id": f"final-{call_id}",
                                }
                            ],
                        ),
                    )
                )
                journal = DbEntityResearchAgentJournal(conn_factory=connection)
                guard = Guard()
                runtime = EntityResearchAgentRuntime(
                    factory=EntityResearchAgentFactory(
                        models=Models(model),
                        journal=journal,
                        guard=guard,
                    ),
                    checkpointers=Checkpointers(),
                    journal=journal,
                    finalizer=Finalizer(),
                )
                definition = EntityResearchAgentDefinition(
                    context=context,
                    model_policy=ModelPolicy(
                        model_id="test-model",
                        timeout_s=5,
                        max_retries=0,
                        max_output_tokens=4096,
                        temperature=0,
                    ),
                    tools=bindings,
                    task_instruction="Research the exact contact with governed persisted tools.",
                )
                await runtime.run(definition=definition)
                return context

            first_context = await run_turn(uuid4(), "r4-exa-first")
            assert transport.calls == 1
            retry_arguments = {
                "field_keys": [_FIELD],
                "source_keys": ["exa_deep"],
                "questions": [_QUESTION],
            }
            retry_call = EntityResearchToolCall(
                tool_call_id="r4-exa-first",
                tool_name="research_contact_deep",
                tool_version=1,
                tool_input_sha256=canonical_sha256(retry_arguments),
                arguments=retry_arguments,
            )
            retry_event = EntityResearchJournalEvent(
                event_id=uuid4(),
                agent_execution_id=first_context.agent_execution_id,
                agent_turn_id=first_context.agent_turn_id,
                kind=EntityAgentJournalEventKind.TOOL_STARTED,
                payload={"arguments": retry_arguments},
                tool_call_id=retry_call.tool_call_id,
                tool_name=retry_call.tool_name,
                tool_version=retry_call.tool_version,
                tool_input_sha256=retry_call.tool_input_sha256,
            )
            retry_ref = await DbEntityResearchAgentJournal(conn_factory=connection).append(
                retry_event
            )
            replayed_request = await request_store.record(
                active=ActiveEntityResearchToolExecution(
                    context=first_context,
                    call=retry_call,
                    journal_event_ref=retry_ref,
                ),
                semantic=EntityResearchSemanticToolInput.model_validate(retry_arguments),
            )
            original_event_id = (
                await conn.execute(
                    text(
                        "SELECT tool_event_id FROM entity_research_tool_request "
                        "WHERE tool_request_id=:request_id"
                    ),
                    {"request_id": replayed_request.tool_call_id},
                )
            ).scalar_one()
            assert original_event_id != retry_event.event_id
            tool_event = (
                await conn.execute(
                    text(
                        """
                            SELECT payload_json FROM entity_research_agent_event
                            WHERE agent_turn_id=:turn_id AND event_kind='tool_completed'
                            ORDER BY event_seq DESC LIMIT 1
                            """
                    ),
                    {"turn_id": first_context.agent_turn_id},
                )
            ).scalar_one()
            tool_message = tool_event["result"]
            assert tool_message["type"] == "tool"
            assert tool_message["data"]["status"] == "success"
            batch = json.loads(tool_message["data"]["content"])
            assert "results" in batch, batch
            result = batch["results"][0]
            assert result["delivery"] == "indexed_complete"
            assert result["fields"][0]["outcome"] == "found"
            assert result["fields"][0]["claim_delta"] == "accepted"
            assert result["fields"][0]["value"] is None
            assert result["fields"][0]["value_ref"]
            assert result["fields"][0]["evidence"]
            assert Decimal(result["cost_cents"]) == Decimal("8")
            assert batch["current_state_sha256"] != first_context.current_state_sha256
            refreshed_job = await store.get_job(authorization.job_id)
            assert refreshed_job is not None
            assert refreshed_job.current_state_sha256 == batch["current_state_sha256"]
            result_ref = result["result_ref"]
            evidence_ref = result["fields"][0]["evidence"][0]["evidence_ref"]
            result_id = UUID(result_ref.removeprefix("research-result:"))
            result_store_result_sha256 = (
                await conn.execute(
                    text(
                        "SELECT result_sha256 FROM entity_research_result "
                        "WHERE result_id=:result_id"
                    ),
                    {"result_id": result_id},
                )
            ).scalar_one()

            operation_ref = result["operation_ref"]
            cause = await causation.causation_for(operation_ref)
            assert cause is not None
            assert cause.agent_turn_id == first_context.agent_turn_id
            assert cause.tool_name == "research_contact_deep"
            assert cause.agent_turn_started_at <= cause.tool_call_recorded_at
            assert cause.tool_call_recorded_at <= cause.provider_operation_reserved_at
            assert cause.provider_operation_reserved_at <= cause.provider_dispatched_at

            active = ActiveEntityResearchToolExecution(
                context=first_context,
                call=EntityResearchToolCall(
                    tool_call_id="read-r4-result",
                    tool_name="read_research_result",
                    tool_version=1,
                    tool_input_sha256=canonical_sha256({"result_ref": result_ref}),
                    arguments={"result_ref": result_ref},
                ),
                journal_event_ref=f"entity-agent-event:{uuid4()}",
            )
            complete = await result_store.read_result(
                active=active,
                result_ref=result_ref,
            )
            assert complete.delivery.value == "inline_complete"
            assert complete.fields[0].value is not None
            page = await result_store.read_evidence(
                active=active,
                request=ReadResearchEvidenceInput(
                    evidence_ref=evidence_ref,
                    max_bytes=128,
                ),
            )
            assert page.content
            assert len(page.content_sha256) == 64
            evidence_bytes = await storage.get(page.artifact_ref.removeprefix("artifact:"))
            assert "Clínica operations 🩺" in evidence_bytes.decode("utf-8")
            pieces: list[str] = []
            offset = 0
            while True:
                unicode_page = await result_store.read_evidence(
                    active=active,
                    request=ReadResearchEvidenceInput(
                        evidence_ref=evidence_ref,
                        offset=offset,
                        max_bytes=7,
                    ),
                )
                pieces.append(unicode_page.content)
                assert unicode_page.next_offset >= offset
                if unicode_page.complete:
                    break
                assert unicode_page.next_offset > offset
                offset = unicode_page.next_offset
            assert "".join(pieces).encode("utf-8") == evidence_bytes
            emoji_offset = evidence_bytes.index("🩺".encode())
            # A paging argument the model got wrong (a mid-code-point offset, an offset past the
            # end, a window too small for the next code point) is its own repairable mistake — the
            # suspending integrity species is for retained bytes that are not what they claim.
            with pytest.raises(EntityResearchGovernedRejection, match="code-point boundary"):
                await result_store.read_evidence(
                    active=active,
                    request=ReadResearchEvidenceInput(
                        evidence_ref=evidence_ref,
                        offset=emoji_offset + 1,
                        max_bytes=16,
                    ),
                )
            with pytest.raises(EntityResearchGovernedRejection, match="exceeds retained content"):
                await result_store.read_evidence(
                    active=active,
                    request=ReadResearchEvidenceInput(
                        evidence_ref=evidence_ref,
                        offset=len(evidence_bytes) + 1,
                        max_bytes=16,
                    ),
                )
            with pytest.raises(EntityResearchGovernedRejection, match="page size is too small"):
                await result_store.read_evidence(
                    active=active,
                    request=ReadResearchEvidenceInput(
                        evidence_ref=evidence_ref,
                        offset=emoji_offset,
                        max_bytes=1,
                    ),
                )

            foreign = _context(ResearchSubjectType.CONTACT, EntityAgentRole.CONTACT)
            # Still refused — the read authority is unchanged — but in the repairable species, so
            # a model-typed foreign ref corrects the agent instead of failing its execution.
            with pytest.raises(EntityResearchGovernedRejection, match="outside the exact job"):
                await result_store.read_result(
                    active=active.__class__(
                        context=foreign,
                        call=active.call,
                        journal_event_ref=active.journal_event_ref,
                    ),
                    result_ref=result_ref,
                )

            second_context = await run_turn(uuid4(), "r4-exa-replay")
            assert transport.calls == 1
            observations = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT disposition FROM entity_research_provider_observation
                            WHERE provider_operation_ref=:operation_ref
                            ORDER BY created_at, observation_id
                            """
                        ),
                        {"operation_ref": operation_ref},
                    )
                )
                .scalars()
                .all()
            )
            assert sorted(observations) == ["caused", "replay_observation"]
            assert second_context.agent_turn_id != first_context.agent_turn_id
            replay_request_row = (
                (
                    await conn.execute(
                        text(
                            """
                        SELECT research_run_id, job_id, subject_type, target_entity_id,
                               parent_account_id, agent_turn_id, agent_execution_id,
                               tool_request_id AS tool_call_id, tool_name, tool_version,
                               tool_input_sha256,
                               field_plan_ref, source_plan_ref, field_keys, source_keys,
                               field_source_authority, questions, budget_reservation_key,
                               idempotency_key, parent_operation_ref, parent_observation_ref,
                               follow_up_reason, prior_result_sha256, prior_research_context
                        FROM entity_research_tool_request
                        WHERE agent_turn_id=:agent_turn_id
                        """
                        ),
                        {"agent_turn_id": second_context.agent_turn_id},
                    )
                )
                .mappings()
                .one()
            )
            replay_request = GovernedResearchToolRequest.model_validate(
                {
                    **dict(replay_request_row),
                    "field_keys": tuple(replay_request_row["field_keys"]),
                    "source_keys": tuple(replay_request_row["source_keys"]),
                    "questions": tuple(replay_request_row["questions"]),
                }
            )
            retained_cause = await causation.causation_for(operation_ref)
            assert retained_cause is not None
            assert retained_cause.tool_call_id != replay_request.tool_call_id
            cause_count = int(
                (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM entity_research_provider_observation "
                            "WHERE provider_operation_ref=:operation_ref "
                            "AND disposition='caused'"
                        ),
                        {"operation_ref": operation_ref},
                    )
                ).scalar_one()
            )
            assert cause_count == 1

            follow_up_context = await run_turn(
                uuid4(),
                "r4-exa-follow-up",
                parent_operation_ref=result["operation_ref"],
                parent_observation_ref=result_ref,
                follow_up_reason=ResearchFollowUpReason.EVIDENCE_VERIFICATION,
                questions=(_FOLLOW_UP_QUESTION,),
            )
            assert transport.calls == 2
            follow_up_operation = (
                await conn.execute(
                    text(
                        """
                        SELECT observation.provider_operation_ref
                        FROM entity_research_provider_observation observation
                        JOIN entity_research_tool_request request_row
                          ON request_row.tool_request_id=observation.tool_request_id
                        WHERE request_row.agent_turn_id=:agent_turn_id
                          AND observation.disposition='caused'
                        """
                    ),
                    {"agent_turn_id": follow_up_context.agent_turn_id},
                )
            ).scalar_one()
            assert follow_up_operation != operation_ref
            follow_up_cause = await causation.causation_for(follow_up_operation)
            assert follow_up_cause is not None
            assert follow_up_cause.parent_operation_ref == result["operation_ref"]
            assert follow_up_cause.parent_observation_ref == result_ref
            assert follow_up_cause.follow_up_reason is ResearchFollowUpReason.EVIDENCE_VERIFICATION
            follow_up_request = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT questions, prior_result_sha256, prior_research_context
                            FROM entity_research_tool_request
                            WHERE agent_turn_id=:agent_turn_id
                            """
                        ),
                        {"agent_turn_id": follow_up_context.agent_turn_id},
                    )
                )
                .mappings()
                .one()
            )
            assert tuple(follow_up_request["questions"]) == (_FOLLOW_UP_QUESTION,)
            assert follow_up_request["prior_result_sha256"] == result_store_result_sha256
            assert result_ref in str(follow_up_request["prior_research_context"])
            follow_up_request_artifact = (
                await conn.execute(
                    text(
                        "SELECT request_artifact_key FROM external_research_operation "
                        "WHERE id=:operation_id"
                    ),
                    {
                        "operation_id": UUID(
                            follow_up_operation.removeprefix("external-research-operation:")
                        )
                    },
                )
            ).scalar_one()
            follow_up_wire = (await storage.get(str(follow_up_request_artifact))).decode("utf-8")
            assert _FOLLOW_UP_QUESTION in follow_up_wire
            assert result_ref in follow_up_wire
            follow_up_event = (
                await conn.execute(
                    text(
                        """
                        SELECT payload_json FROM entity_research_agent_event
                        WHERE agent_turn_id=:turn_id AND event_kind='tool_completed'
                        ORDER BY event_seq DESC LIMIT 1
                        """
                    ),
                    {"turn_id": follow_up_context.agent_turn_id},
                )
            ).scalar_one()
            follow_up_result = json.loads(follow_up_event["result"]["data"]["content"])["results"][
                0
            ]
            assert follow_up_result["operation_ref"] == (follow_up_operation)
            # A second Exa observation is additive lineage, not independent-source
            # corroboration; its claim delta therefore remains an accepted candidate.
            assert follow_up_result["fields"][0]["claim_delta"] == "accepted"
            counts = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT
                              (SELECT count(*) FROM entity_research_tool_request
                               WHERE job_id=:job_id) AS requests,
                              (SELECT count(*) FROM entity_research_result result
                               JOIN entity_research_tool_request request_row
                                 ON request_row.tool_request_id=result.tool_request_id
                               WHERE request_row.job_id=:job_id) AS results,
                              (SELECT count(*) FROM external_research_operation
                               WHERE contact_id=:contact_id) AS operations,
                              (SELECT count(*) FROM external_research_receipt receipt
                               JOIN external_research_operation operation
                                 ON operation.id=receipt.operation_id
                               WHERE operation.contact_id=:contact_id) AS receipts
                            """
                        ),
                        {
                            "job_id": authorization.job_id,
                            "contact_id": seed.intent.contact_entity_id,
                        },
                    )
                )
                .mappings()
                .one()
            )
            assert dict(counts) == {
                "requests": 3,
                "results": 3,
                "operations": 2,
                "receipts": 2,
            }
            folded_spend = (
                (
                    await conn.execute(
                        text(
                            "SELECT job.spent_cents AS job_spent, "
                            "run_row.spent_cents AS run_spent, "
                            "(SELECT count(*) FROM "
                            "entity_research_provider_settlement_fold fold "
                            "WHERE fold.job_id=job.job_id) AS folds "
                            "FROM entity_research_job job "
                            "JOIN entity_research_run run_row "
                            "ON run_row.research_run_id=job.research_run_id "
                            "WHERE job.job_id=:job_id"
                        ),
                        {"job_id": authorization.job_id},
                    )
                )
                .mappings()
                .one()
            )
            assert Decimal(folded_spend["job_spent"]) == Decimal("16")
            assert Decimal(folded_spend["run_spent"]) == Decimal("16")
            assert folded_spend["folds"] == 2

            with pytest.raises(DBAPIError, match="append-only"):
                async with conn.begin_nested():
                    await conn.execute(
                        text(
                            "UPDATE entity_research_result SET delivery='inline_complete' "
                            "WHERE result_id=:result_id"
                        ),
                        {"result_id": result_id},
                    )

            result_artifact_keys = tuple(
                (
                    await conn.execute(
                        text(
                            """
                            SELECT DISTINCT artifact_key
                            FROM discovery_artifact_subject
                            WHERE workspace_id=:workspace_id
                              AND subject_kind='contact'
                              AND subject_entity_id=:contact_id
                              AND reference_kind IN
                                  ('entity_research_result', 'entity_research_value')
                              AND tombstoned_at IS NULL
                            ORDER BY artifact_key
                            """
                        ),
                        {
                            "workspace_id": seed.intent.workspace_id,
                            "contact_id": seed.intent.contact_entity_id,
                        },
                    )
                )
                .scalars()
                .all()
            )
            assert result_artifact_keys
            await DataSubjectRightsImpl(
                seed.intent.workspace_id,
                conn_factory=connection,
                storage=storage,
            ).erase(EntityId(seed.intent.contact_entity_id))
            for artifact_key in result_artifact_keys:
                assert not await storage.exists(str(artifact_key))
                record = await get_artifact(conn, str(artifact_key))
                assert record is not None and record.erased_at is not None
            redacted_turns = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT context_json, erased_at
                            FROM entity_research_agent_turn
                            WHERE workspace_id=:workspace_id
                              AND subject_type='contact'
                              AND target_entity_id=:contact_id
                            """
                        ),
                        {
                            "workspace_id": seed.intent.workspace_id,
                            "contact_id": seed.intent.contact_entity_id,
                        },
                    )
                )
                .mappings()
                .all()
            )
            assert redacted_turns
            assert all(
                row["context_json"] == {"erased": True} and row["erased_at"] is not None
                for row in redacted_turns
            )
            redacted_events = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT event_row.payload_json, event_row.payload_erased_at
                            FROM entity_research_agent_event event_row
                            JOIN entity_research_agent_turn turn_row
                              ON turn_row.agent_turn_id=event_row.agent_turn_id
                            WHERE turn_row.workspace_id=:workspace_id
                              AND turn_row.subject_type='contact'
                              AND turn_row.target_entity_id=:contact_id
                            """
                        ),
                        {
                            "workspace_id": seed.intent.workspace_id,
                            "contact_id": seed.intent.contact_entity_id,
                        },
                    )
                )
                .mappings()
                .all()
            )
            assert redacted_events
            assert all(
                row["payload_json"] == {"erased": True} and row["payload_erased_at"] is not None
                for row in redacted_events
            )

    from tests.db.conftest import run_async

    run_async(scenario())


def test_causation_failure_leaves_operation_planned_and_makes_zero_provider_calls(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn() as conn:
            seed = await _seed(conn, storage, suffix="m8d-r4-cause-failure")
            connection = _TransactionalTrackedConnFactory(conn)
            transport = _Transport(_payload("supported.json"), connection)
            acquisition = ExaDeepContactAcquisitionService(
                coordinator=ExaDeepAcquisitionCoordinator(
                    transport=transport,
                    storage=storage,
                    conn_factory=connection,
                ),
                conn_factory=connection,
            )

            async def reject_cause(operation: object) -> None:
                del operation
                raise RuntimeError("causation journal unavailable")

            with pytest.raises(RuntimeError, match="causation journal unavailable"):
                await acquisition.acquire_intent(
                    intent=seed.intent,
                    effective_policy=seed.policy,
                    observation_window="m8d-r4-cause-failure",
                    before_dispatch=reject_cause,
                    field_keys=(_FIELD,),
                    directional_questions=(_QUESTION,),
                )

            assert transport.calls == 0
            operation = (
                (
                    await conn.execute(
                        text(
                            """
                        SELECT id, state::text FROM external_research_operation
                        WHERE contact_id=:contact_id
                          AND observation_window LIKE 'm8d-r4-cause-failure:%'
                        """
                        ),
                        {"contact_id": seed.intent.contact_entity_id},
                    )
                )
                .mappings()
                .one()
            )
            assert operation["state"] == "planned"
            attempt_count = int(
                (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM external_research_attempt "
                            "WHERE operation_id=:operation_id"
                        ),
                        {"operation_id": operation["id"]},
                    )
                ).scalar_one()
            )
            assert attempt_count == 0

    from tests.db.conftest import run_async

    run_async(scenario())


def test_provider_neutral_join_records_wait_and_advances_durable_state(tmp_path: Path) -> None:
    class _JoinedSumbleAction:
        async def execute(
            self,
            request: GovernedResearchToolRequest,
            *,
            before_dispatch: object,
            settle_terminal: object,
        ) -> tuple[()]:
            del before_dispatch, settle_terminal
            now = datetime.now(UTC)
            raise EntityResearchProviderWait(
                ProviderOperationReservation(
                    provider_kind="sumble_people",
                    operation_ref=f"sumble-people-operation:{uuid4()}",
                    workspace_id=str(request_workspace_id),
                    project_id=str(request_project_id),
                    project_run_id=request_project_run_id,
                    subject_type=request.subject_type,
                    target_entity_id=request.target_entity_id,
                    parent_account_id=request.parent_account_id,
                    source_key="sumble_people",
                    field_keys=(_FIELD,),
                    request_artifact_ref="artifact:sumble-people-inflight-request",
                    reserved_at=now,
                    dispatched_at=now,
                    observation_disposition=ProviderObservationDisposition.JOINED,
                )
            )

    async def scenario() -> None:
        nonlocal request_workspace_id, request_project_id, request_project_run_id
        storage = FsStorage(tmp_path / "artifacts")
        checkpoint_thread_id: str | None = None
        async with rollback_conn() as conn:
            seed = await _seed(conn, storage, suffix="m8d-r4-provider-join")
            connection = _TransactionalTrackedConnFactory(conn)
            profile_body = "role: contact-research\nframework: langchain-create-agent\n"
            profile_sha = hashlib.sha256(profile_body.encode()).hexdigest()
            envelope = _fleet_envelope(seed, profile_sha256=profile_sha)
            original_selection = envelope.lifecycle.selection
            field_authority = (
                FieldSourceAuthority(
                    field_key=_FIELD,
                    source_keys=("sumble_people",),
                ),
                FieldSourceAuthority(
                    field_key=_SECOND_FIELD,
                    source_keys=("exa_deep",),
                ),
            )
            original_subject = original_selection.subjects[0]
            assert original_subject.contact_authority is not None
            target_authority = original_subject.contact_authority.model_copy(
                update={
                    "admitted_field_keys": (_FIELD, _SECOND_FIELD),
                    "admitted_source_keys": ("sumble_people", "exa_deep"),
                    "field_source_authority": field_authority,
                }
            )
            selection = original_selection.model_copy(
                update={
                    "subjects": (
                        original_subject.model_copy(update={"contact_authority": target_authority}),
                    ),
                    "admitted_field_keys": (_FIELD, _SECOND_FIELD),
                    "admitted_source_keys": ("sumble_people", "exa_deep"),
                    "field_source_authority": field_authority,
                }
            )
            original_job = envelope.jobs[0]
            authorization = original_job.authorization.model_copy(update={"selection": selection})
            envelope = envelope.model_copy(
                update={
                    "lifecycle": envelope.lifecycle.model_copy(update={"selection": selection}),
                    "jobs": (original_job.model_copy(update={"authorization": authorization}),),
                }
            )
            request_workspace_id = authorization.workspace_id
            request_project_id = authorization.project_id
            request_project_run_id = authorization.project_run_id
            job_store = DbEntityResearchJobStore(conn_factory=connection)
            await job_store.launch(envelope)
            job = await job_store.get_job(authorization.job_id)
            assert job is not None
            context = _runtime_context(
                authorization=authorization,
                state_sha256=job.current_state_sha256,
                profile_body=profile_body,
                agent_turn_id=uuid4(),
            )
            checkpoint_thread_id = context.effective_checkpoint_thread_id
            provider_names = {
                "research_contact_deep",
                "enrich_contact",
                "reveal_contact_channel",
                "validate_contact_channel",
            }
            engine_names = (
                set(context.tool_surface.tool_names)
                - provider_names
                - {"read_research_result", "read_evidence"}
            )
            causation = EntityResearchProviderCausationStore(conn_factory=connection)
            results = EntityResearchResultStore(storage=storage, conn_factory=connection)
            factory = GovernedEntityResearchToolFactory(
                requests=EntityResearchToolRequestStore(
                    conn_factory=connection,
                    storage=storage,
                ),
                causation=causation,
                results=results,
            )
            bindings = factory.compose(
                surface=context.tool_surface,
                provider_actions={
                    name: ProviderActionBinding(action=_JoinedSumbleAction(), version=1)
                    for name in provider_names
                },
                engine_tools={
                    name: EntityResearchToolBinding(tool=_tool(name), version=1)
                    for name in engine_names
                },
            )
            model = ScriptedAgentChatModel(
                responses=(
                    AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "research_contact_deep",
                                "args": {
                                    "field_keys": [_FIELD, _SECOND_FIELD],
                                    "source_keys": ["sumble_people", "exa_deep"],
                                    "questions": [_QUESTION],
                                },
                                "id": "r4-sumble-joined",
                            }
                        ],
                    ),
                )
            )
            journal = DbEntityResearchAgentJournal(conn_factory=connection)
            runtime = EntityResearchAgentRuntime(
                factory=EntityResearchAgentFactory(
                    models=Models(model),
                    journal=journal,
                    guard=Guard(),
                ),
                checkpointers=PostgresEntityResearchCheckpointers(),
                journal=journal,
                finalizer=Finalizer(),
            )
            outcome = await runtime.run(
                definition=EntityResearchAgentDefinition(
                    context=context,
                    model_policy=ModelPolicy(
                        model_id="test-model",
                        timeout_s=5,
                        max_retries=0,
                        max_output_tokens=4096,
                        temperature=0,
                    ),
                    tools=bindings,
                    task_instruction="Join exact durable provider work and suspend honestly.",
                )
            )
            assert isinstance(outcome, EntityResearchAgentSuspension)
            assert outcome.wait_ref.startswith("sumble-people-operation:")
            observations = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT operation.provider_kind, observation.disposition
                            FROM entity_research_provider_observation observation
                            JOIN entity_research_provider_operation operation
                              ON operation.operation_ref=observation.provider_operation_ref
                            WHERE observation.provider_operation_ref=:operation_ref
                            """
                        ),
                        {"operation_ref": outcome.wait_ref},
                    )
                )
                .mappings()
                .one()
            )
            assert dict(observations) == {
                "provider_kind": "sumble_people",
                "disposition": "joined_observation",
            }
            assert (
                int(
                    (
                        await conn.execute(
                            text(
                                "SELECT count(*) FROM entity_research_result "
                                "WHERE provider_operation_ref=:operation_ref"
                            ),
                            {"operation_ref": outcome.wait_ref},
                        )
                    ).scalar_one()
                )
                == 0
            )
            refreshed = await job_store.get_job(authorization.job_id)
            assert refreshed is not None
            assert refreshed.current_state_sha256 == outcome.current_state_sha256
            assert refreshed.current_state_sha256 != job.current_state_sha256

            # Both sources are admitted to this request, but Exa is not admitted for _FIELD.
            # The database must reject this manufactured cross-product before dispatch, even if
            # an application caller attempts to bypass the in-memory authority check.
            invalid_operation_ref = f"manufactured-provider-operation:{uuid4()}"
            request_id = (
                await conn.execute(
                    text(
                        "SELECT tool_request_id FROM entity_research_tool_request "
                        "WHERE agent_turn_id=:turn_id"
                    ),
                    {"turn_id": context.agent_turn_id},
                )
            ).scalar_one()
            await conn.execute(
                text(
                    """
                    INSERT INTO entity_research_provider_operation
                        (operation_ref, provider_kind, workspace_id, project_id, project_run_id,
                         subject_type, target_entity_id, parent_account_id, source_key,
                         field_keys, request_artifact_ref, reserved_at)
                    VALUES
                        (:operation_ref, 'manufactured', :workspace_id, :project_id,
                         :project_run_id, 'contact', :target_entity_id, :parent_account_id,
                         'exa_deep', :field_keys, 'artifact:manufactured-request', now())
                    """
                ),
                {
                    "operation_ref": invalid_operation_ref,
                    "workspace_id": authorization.workspace_id,
                    "project_id": authorization.project_id,
                    "project_run_id": authorization.project_run_id,
                    "target_entity_id": authorization.subject_entity_id,
                    "parent_account_id": authorization.parent_account_id,
                    "field_keys": [_FIELD],
                },
            )
            with pytest.raises(DBAPIError, match="crosses governed tool request authority"):
                async with conn.begin_nested():
                    await conn.execute(
                        text(
                            """
                            INSERT INTO entity_research_provider_observation
                                (observation_id, tool_request_id, operation_id,
                                 external_workspace_id, disposition, provider_operation_ref)
                            VALUES
                                (:observation_id, :tool_request_id, NULL, NULL, 'caused',
                                 :operation_ref)
                            """
                        ),
                        {
                            "observation_id": uuid4(),
                            "tool_request_id": request_id,
                            "operation_ref": invalid_operation_ref,
                        },
                    )

            checkpoint_count = int(
                (
                    await conn.execute(
                        text("SELECT count(*) FROM checkpoints WHERE thread_id=:thread_id"),
                        {"thread_id": checkpoint_thread_id},
                    )
                ).scalar_one()
            )
            assert checkpoint_count >= 1

            await DataSubjectRightsImpl(
                seed.intent.workspace_id,
                conn_factory=connection,
                storage=storage,
            ).erase(EntityId(seed.intent.contact_entity_id))
            assert (
                int(
                    (
                        await conn.execute(
                            text("SELECT count(*) FROM checkpoints WHERE thread_id=:thread_id"),
                            {"thread_id": checkpoint_thread_id},
                        )
                    ).scalar_one()
                )
                == 0
            )
            erased_turn = (
                (
                    await conn.execute(
                        text(
                            "SELECT context_json, erased_at FROM entity_research_agent_turn "
                            "WHERE agent_turn_id=:turn_id"
                        ),
                        {"turn_id": context.agent_turn_id},
                    )
                )
                .mappings()
                .one()
            )
            assert erased_turn["context_json"] == {"erased": True}
            assert erased_turn["erased_at"] is not None

        # The rollback fixture restores its SQL deletion, while LangGraph's saver committed on a
        # separate connection. Remove only this test's globally-scoped thread so reruns leave no
        # replay state behind.
        assert checkpoint_thread_id is not None
        async with db_lifespan(), db_transaction() as cleanup:
            for table_name in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
                await cleanup.execute(
                    text(f"DELETE FROM {table_name} WHERE thread_id=:thread_id"),  # noqa: S608
                    {"thread_id": checkpoint_thread_id},
                )

    request_workspace_id = ""
    request_project_id = ""
    request_project_run_id = uuid4()
    from tests.db.conftest import run_async

    run_async(scenario())


async def _journal_governed_request(
    conn: AsyncConnection,
    *,
    authorization: EntityResearchJobAuthorization,
    operation_ref: str,
    disposition: str,
) -> UUID:
    """Journal one governed contact tool request and its observation of ``operation_ref``.

    Written as SQL rather than driven through the agent because the shape under test is durable,
    not behavioural: two jobs over the same contact, one provider operation, one settlement. Every
    row still passes the production triggers (turn ⇄ event ⇄ request authority, and the observation
    ⇄ operation authority), so nothing here is admitted that the runtime could not have written.
    """

    selection = authorization.selection
    turn_id, execution_id, event_id, request_id = uuid4(), uuid4(), uuid4(), uuid4()
    call_id = f"governed-call:{authorization.job_id}"
    params = {
        "turn_id": turn_id,
        "execution_id": execution_id,
        "event_id": event_id,
        "request_id": request_id,
        "observation_id": uuid4(),
        "call_id": call_id,
        "job_id": authorization.job_id,
        "research_run_id": authorization.research_run_id,
        "contact_id": authorization.subject_entity_id,
        "account_id": authorization.parent_account_id,
        "workspace_id": authorization.workspace_id,
        "project_id": authorization.project_id,
        "product_id": authorization.product_id,
        "project_run_id": authorization.project_run_id,
        "checkpoint_thread_id": authorization.checkpoint_thread_id,
        "field_keys": list(selection.admitted_field_keys),
        "source_keys": list(selection.admitted_source_keys),
        "questions": list(selection.research_questions),
        "operation_ref": operation_ref,
        "disposition": disposition,
        "sha": "a" * 64,
        "authority": json.dumps(
            [
                {"field_key": item.field_key, "source_keys": list(item.source_keys)}
                for item in selection.field_source_authority
            ]
        ),
    }
    params["context"] = json.dumps(
        {
            "agent_execution_id": str(execution_id),
            "agent_turn_id": str(turn_id),
            "role": "contact",
            "subject_type": "contact",
            "subject_entity_id": str(authorization.subject_entity_id),
            "job_id": str(authorization.job_id),
            "research_run_id": str(authorization.research_run_id),
            "workspace_id": authorization.workspace_id,
            "project_id": authorization.project_id,
            "product_id": authorization.product_id,
            "project_run_id": str(authorization.project_run_id),
            "checkpoint_thread_id": authorization.checkpoint_thread_id,
            "tool_names": ["research_contact_deep"],
            "admitted_field_keys": list(selection.admitted_field_keys),
            "admitted_source_keys": list(selection.admitted_source_keys),
            "field_source_authority": json.loads(str(params["authority"])),
            "research_questions": list(selection.research_questions),
        }
    )
    await conn.execute(
        text(
            """
            INSERT INTO entity_research_agent_turn
                (agent_turn_id, agent_execution_id, job_id, research_run_id, role, subject_type,
                 target_entity_id, parent_account_id, workspace_id, project_id, product_id,
                 project_run_id, checkpoint_thread_id, context_json, context_sha256,
                 resource_manifest_json, resource_manifest_sha256, tool_manifest_json,
                 tool_manifest_sha256, system_prompt_sha256)
            VALUES
                (:turn_id, :execution_id, :job_id, :research_run_id, 'contact', 'contact',
                 :contact_id, :account_id, :workspace_id, :project_id, :product_id,
                 :project_run_id, :checkpoint_thread_id, CAST(:context AS jsonb), :sha,
                 '{}'::jsonb, :sha, '[]'::jsonb, :sha, :sha)
            """
        ),
        params,
    )
    await conn.execute(
        text(
            """
            INSERT INTO entity_research_agent_event
                (event_id, agent_turn_id, agent_execution_id, event_kind, tool_call_id, tool_name,
                 tool_version, tool_input_sha256, payload_json)
            VALUES (:event_id, :turn_id, :execution_id, 'tool_started', :call_id,
                    'research_contact_deep', 1, :sha, '{}'::jsonb)
            """
        ),
        params,
    )
    await conn.execute(
        text(
            """
            INSERT INTO entity_research_tool_request
                (tool_request_id, agent_turn_id, agent_execution_id, tool_event_id,
                 raw_tool_call_id, research_run_id, job_id, subject_type, target_entity_id,
                 parent_account_id, workspace_id, project_id, product_id, project_run_id,
                 tool_name, tool_version, tool_input_sha256, field_plan_ref, source_plan_ref,
                 field_keys, source_keys, questions, budget_reservation_key, idempotency_key,
                 field_source_authority)
            VALUES
                (:request_id, :turn_id, :execution_id, :event_id, :call_id, :research_run_id,
                 :job_id, 'contact', :contact_id, :account_id, :workspace_id, :project_id,
                 :product_id, :project_run_id, 'research_contact_deep', 1, :sha,
                 'contact-field-plan:1', 'contact-source-plan:1', :field_keys, :source_keys,
                 :questions, :call_id, :call_id, CAST(:authority AS jsonb))
            """
        ),
        params,
    )
    await conn.execute(
        text(
            """
            INSERT INTO entity_research_provider_observation
                (observation_id, tool_request_id, external_workspace_id, disposition,
                 provider_operation_ref)
            VALUES (:observation_id, :request_id, :workspace_id, :disposition, :operation_ref)
            """
        ),
        params,
    )
    return request_id


def test_a_replaying_contact_job_sees_the_settlement_another_job_folded(tmp_path: Path) -> None:
    """The contact half of the live Millennium wedge: the fold belongs to the operation.

    ``entity_research_provider_settlement_fold`` is keyed on the provider operation and inserted ON
    CONFLICT DO NOTHING, so it is written once and stamped with the job that settled it first.
    Provider operations are content-keyed and deliberately reused across jobs (that is the
    anti-double-spend rule), so a later job re-derives the same ref and records a
    ``replay_observation``. While ``_pending_refs`` demanded a fold carrying its *own* job id, that
    operation stayed pending forever and the contact finalization guard refused every attempt —
    the account-side shape that wedged two live jobs on 2026-08-19. Spend stays job-scoped: the
    replaying job dispatched nothing and owes nothing.
    """

    async def scenario() -> None:
        storage = FsStorage(tmp_path / "cross-job-fold-artifacts")
        async with rollback_conn() as conn:
            seed = await _seed(conn, storage, suffix="cross-job-fold")
            connection = _TransactionalTrackedConnFactory(conn)
            profile_body = "role: contact-research\nframework: langchain-create-agent\n"
            profile_sha = hashlib.sha256(profile_body.encode()).hexdigest()
            store = DbEntityResearchJobStore(conn_factory=connection)
            # Two runs over the same contact — a relaunch, which is exactly how the live wedge
            # arose. Each envelope mints its own selection, run and job.
            envelopes = tuple(_fleet_envelope(seed, profile_sha256=profile_sha) for _ in range(2))
            for envelope in envelopes:
                await store.launch(envelope)
            settling, replaying = (envelope.jobs[0].authorization for envelope in envelopes)

            operation_ref = f"exa-contact-operation:{uuid4()}"
            await conn.execute(
                text(
                    """
                    INSERT INTO entity_research_provider_operation
                        (operation_ref, provider_kind, workspace_id, project_id, project_run_id,
                         subject_type, target_entity_id, parent_account_id, source_key,
                         field_keys, request_artifact_ref, reserved_at)
                    VALUES
                        (:operation_ref, 'exa_deep', :workspace_id, :project_id, :project_run_id,
                         'contact', :contact_id, :account_id, 'exa_deep', :field_keys,
                         'artifact:cross-job-fold-request', now())
                    """
                ),
                {
                    "operation_ref": operation_ref,
                    "workspace_id": settling.workspace_id,
                    "project_id": settling.project_id,
                    "project_run_id": settling.project_run_id,
                    "contact_id": settling.subject_entity_id,
                    "account_id": settling.parent_account_id,
                    "field_keys": list(settling.selection.admitted_field_keys),
                },
            )
            await _journal_governed_request(
                conn,
                authorization=settling,
                operation_ref=operation_ref,
                disposition="caused",
            )
            # Causation is journalled before dispatch (the trigger enforces that order), so the
            # dispatch stamp lands after it, exactly as the provider path stamps it.
            await conn.execute(
                text(
                    "UPDATE entity_research_provider_operation SET dispatched_at=now() "
                    "WHERE operation_ref=:operation_ref"
                ),
                {"operation_ref": operation_ref},
            )
            pending = ContactResearchStateStore._pending_refs
            assert await pending(conn, settling.job_id) == (operation_ref,)

            # The provider terminally settles the operation under the job that dispatched it.
            await conn.execute(
                text(
                    """
                    INSERT INTO entity_research_provider_settlement_fold
                        (provider_operation_ref, research_run_id, job_id, settled_cost_cents)
                    VALUES (:operation_ref, :run_id, :job_id, 3.25)
                    """
                ),
                {
                    "operation_ref": operation_ref,
                    "run_id": settling.research_run_id,
                    "job_id": settling.job_id,
                },
            )
            await _journal_governed_request(
                conn,
                authorization=replaying,
                operation_ref=operation_ref,
                disposition="replay_observation",
            )

            assert await pending(conn, settling.job_id) == ()
            assert await pending(conn, replaying.job_id) == ()

            # Spend attribution is untouched and stays job-scoped.
            spend = (
                (
                    await conn.execute(
                        text(
                            "SELECT job.job_id, (SELECT COALESCE(sum(fold.settled_cost_cents), 0) "
                            "FROM entity_research_provider_settlement_fold fold "
                            "WHERE fold.job_id=job.job_id) AS folded_spend "
                            "FROM entity_research_job job WHERE job.job_id=ANY(:job_ids)"
                        ),
                        {"job_ids": [str(settling.job_id), str(replaying.job_id)]},
                    )
                )
                .mappings()
                .all()
            )
            assert {UUID(str(row["job_id"])): row["folded_spend"] for row in spend} == {
                settling.job_id: Decimal("3.25"),
                replaying.job_id: Decimal("0"),
            }

    from tests.db.conftest import run_async

    run_async(scenario())


def test_a_result_or_evidence_ref_outside_the_exact_job_refuses_recoverably(
    tmp_path: Path,
) -> None:
    """Live 2026-08-20, job ``5b8898e3``: the account agent read three foreign refs and died.

    The model had ``claim:<uuid>`` references in ``read_account_research_state``'s
    ``existing_claims`` block and re-prefixed three of them as ``research-result:<uuid>``. The
    prefix was right, so ``_model_supplied_uuid`` passed; the row lookup then missed and the raw
    :class:`EntityResearchToolAuthorityError` escaped the shared read tool, failing the whole
    execution. A model-supplied reference naming a row outside this job is R10 species 1 —
    exactly the wrong-*type* reference converted in ``2d71e47f``, in its wrong-*job* variant.
    """

    async def scenario() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn() as conn:
            connection = _TransactionalTrackedConnFactory(conn)
            results = EntityResearchResultStore(storage=storage, conn_factory=connection)
            factory = GovernedEntityResearchToolFactory(
                requests=EntityResearchToolRequestStore(
                    conn_factory=connection,
                    storage=storage,
                ),
                causation=EntityResearchProviderCausationStore(conn_factory=connection),
                results=results,
            )
            context = _context(ResearchSubjectType.ACCOUNT, EntityAgentRole.ACCOUNT)
            foreign_result_ref = f"research-result:{uuid4()}"
            foreign_evidence_ref = f"research-evidence:{uuid4()}"
            active = ActiveEntityResearchToolExecution(
                context=context,
                call=EntityResearchToolCall(
                    tool_call_id="read-foreign-result",
                    tool_name="read_research_result",
                    tool_version=1,
                    tool_input_sha256=canonical_sha256({"result_ref": foreign_result_ref}),
                    arguments={"result_ref": foreign_result_ref},
                ),
                journal_event_ref=f"entity-agent-event:{uuid4()}",
            )

            with pytest.raises(EntityResearchGovernedRejection) as rejected_result:
                await results.read_result(active=active, result_ref=foreign_result_ref)
            payload = json.loads(rejected_result.value.render())
            assert payload["error"] == "governed_research_rejection"
            assert payload["recoverable"] is True
            assert "outside the exact job" in payload["detail"]
            # The refusal must name the two legal moves, or the agent repeats the read.
            assert "read_account_research_state" in payload["detail"]

            with pytest.raises(EntityResearchGovernedRejection) as rejected_evidence:
                await results.read_evidence(
                    active=active,
                    request=ReadResearchEvidenceInput(
                        evidence_ref=foreign_evidence_ref,
                        max_bytes=128,
                    ),
                )
            assert "outside the exact job" in rejected_evidence.value.detail

            # The whole live path: the composed read tools render it as an error tool message
            # instead of letting it escape and fail the execution.
            _, read_result_tool, read_evidence_tool = factory.compose_facet(
                subject_type=ResearchSubjectType.ACCOUNT,
                provider_action=ProviderActionBinding(action=_Action(), version=1),
            )
            token = _ACTIVE_TOOL_EXECUTION.set(active)
            try:
                rendered_result = await read_result_tool.tool.ainvoke(
                    {"result_ref": foreign_result_ref}
                )
                rendered_evidence = await read_evidence_tool.tool.ainvoke(
                    {"evidence_ref": foreign_evidence_ref, "offset": 0, "max_bytes": 128}
                )
            finally:
                _ACTIVE_TOOL_EXECUTION.reset(token)
            for rendered in (rendered_result, rendered_evidence):
                rendered_payload = json.loads(str(rendered))
                assert rendered_payload["error"] == "governed_research_rejection"
                assert rendered_payload["recoverable"] is True

    from tests.db.conftest import run_async

    run_async(scenario())
