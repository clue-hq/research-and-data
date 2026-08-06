"""M8D R8 executable contact-agent and exact-set shared-fleet acceptance."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from pydantic import ConfigDict, PrivateAttr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

import clue_agents.entity_research_runtime as runtime_module
from clue_agents.contracts import ModelPolicy
from clue_agents.entity_research_runtime import (
    EntityResearchAgentFactory,
    EntityResearchAgentRuntime,
)
from clue_api.contact_channel_enrichment import (
    ContactChannelEnrichmentOutcome,
    ExaContactChannelCoordinator,
)
from clue_api.contact_entity_research import (
    ContactChannelActions,
    ContactResearchExecutionGuard,
    ContactResearchFinalizationEngine,
    ContactResearchStateStore,
)
from clue_api.contact_entity_research_channels import GovernedContactChannelActions
from clue_api.contact_entity_research_composition import (
    ContactResearchDefinitionResolver,
    StaticContactResearchChannelActions,
    StaticContactResearchProviderActions,
)
from clue_api.contact_research_fleet import (
    ContactResearchFleetService,
    ContactResearchFleetState,
    ContactResearchFleetWorkHandler,
)
from clue_api.contact_research_fleet_launch import (
    ContactResearchFleetLauncher,
    ContactResearchFleetLaunchRequest,
)
from clue_api.entity_research_runtime_wiring import (
    CreateAgentEntityResearchDriver,
    DbEntityResearchAgentJournal,
)
from clue_api.entity_research_tools import (
    EntityResearchProviderCausationStore,
    EntityResearchResultStore,
    EntityResearchToolRequestStore,
    ExternalResearchResultLineageReader,
    GovernedEntityResearchToolFactory,
    ProviderActionBinding,
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
from clue_core import (
    ContactChannel,
    ContactChannelOperationId,
    ContactResearchIntent,
    ContactResearchSelection,
    EntityId,
    ProjectRunId,
    new_contact_research_selection_id,
    new_run_id,
)
from clue_core.entity_research import FieldSourceAuthority
from clue_fleet import (
    DbEntityResearchJobStore,
    EntityResearchJobWorkHandler,
    FleetTaskKind,
    LeaseGeneration,
    WorkId,
    acquire_work_lease,
    claim_next_task,
    release_work_lease,
)
from clue_fleet.work_worker import WorkContext, WorkResult
from clue_research.durable.contact_research_selection import (
    ContactResearchSelectionApprovalAuthority,
    ContactResearchSelectionApprovalKind,
    store_contact_research_selection,
)
from clue_research.identity import get_account, get_contact
from clue_storage import FsStorage
from tests.agents.test_entity_research_runtime_r3 import Checkpointers
from tests.api.test_contact_research_fleet_launch_r7_db import (
    _approved_mixed_selection,
    _non_committee_identity_claim,
)
from tests.contact_research.test_c4_exa_contact_acquisition_materialization import (
    _payload as exa_contact_payload,
)
from tests.contact_research.test_c5_contact_channel_enrichment import (
    _channel_intent,
    _PassGate,
    _TransactionalTrackedConnFactory,
    _UseGate,
    _Validator,
)
from tests.contact_research.test_c5_contact_channel_enrichment import (
    _Transport as ChannelTransport,
)
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    rollback_conn,
)
from tests.profiling.conftest import (
    require_profiling_db as require_profiling_db,
)

pytestmark = pytest.mark.usefixtures("require_profiling_db")
_TTL = timedelta(seconds=60)


class _NestedConnFactory:
    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn
        self.active = 0

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[AsyncConnection]:
        self.active += 1
        try:
            async with self._conn.begin_nested():
                yield self._conn
        finally:
            self.active -= 1


class _DecisionModel(BaseChatModel):
    """One deterministic test mind for either a parent contact or its fresh facet child."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    question: str
    _bound_tools: tuple[str, ...] = PrivateAttr(default=())
    _contact_id: str | None = PrivateAttr(default=None)
    _field_key: str | None = PrivateAttr(default=None)
    _result_refs: list[str] = PrivateAttr(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "m8d-r8-observing-contact-agent"

    @property
    def role(self) -> str:
        return "contact" if "read_contact_research_state" in self._bound_tools else "facet"

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Any],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Runnable[Any, AIMessage]:
        del tool_choice, kwargs
        self._bound_tools = tuple(
            str(item.get("name") or item.get("function", {}).get("name"))
            if isinstance(item, dict)
            else str(getattr(item, "name", getattr(item, "__name__", "")))
            for item in tools
        )
        return self

    @staticmethod
    def _payload(message: ToolMessage) -> dict[str, Any]:
        if isinstance(message.content, str):
            return cast(dict[str, Any], json.loads(message.content))
        if isinstance(message.content, dict):
            return cast(dict[str, Any], message.content)
        raise AssertionError(f"unexpected R8 tool payload: {type(message.content)!r}")

    @staticmethod
    def _refs(payload: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
        results = cast(list[dict[str, Any]], payload["results"])
        result_refs = [str(value["result_ref"]) for value in results]
        fields = [field for result in results for field in result["fields"]]
        claim_refs = [str(ref) for field in fields for ref in field["claim_refs"]]
        evidence_refs = [
            str(evidence["evidence_ref"]) for field in fields for evidence in field["evidence"]
        ]
        return result_refs, claim_refs, evidence_refs

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        tools = [message for message in messages if isinstance(message, ToolMessage)]
        if not tools:
            call = (
                {"name": "read_contact_research_state", "args": {}, "id": "r8-read"}
                if self.role == "contact"
                else {
                    "name": "research_contact_deep",
                    "args": {
                        "field_keys": [self.question.split("|", 1)[0]],
                        "source_keys": ["exa_deep"],
                        "questions": [self.question.split("|", 1)[1]],
                    },
                    "id": "r8-facet-deep",
                }
            )
            response = AIMessage(content="", tool_calls=[call])
        else:
            last = tools[-1]
            payload = self._payload(last)
            if last.name == "read_contact_research_state":
                self._contact_id = str(payload["contact_entity_id"])
                self._field_key = str(payload["admitted_field_keys"][0])
                assert payload["identity"]["contact_entity_id"] == self._contact_id
                assert payload["identity"]["parent_account_id"] == payload["parent_account_id"]
                assert payload["identity"]["full_name"]
                assert payload["identity"]["account_name"]
                assert payload["identity_lock_ref"].startswith("contact-identity-lock:")
                response = AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "research_contact_deep",
                            "args": {
                                "field_keys": [self._field_key],
                                "source_keys": ["exa_deep"],
                                "questions": [self.question.split("|", 1)[1]],
                            },
                            "id": "r8-parent-deep",
                        }
                    ],
                )
            elif last.name == "research_contact_deep" and self.role == "facet":
                result_refs, claim_refs, evidence_refs = self._refs(payload)
                response = AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "ResearchFinalizationProposal",
                            "args": {
                                "proposal_id": str(uuid4()),
                                "subject_type": "contact",
                                "target_entity_id": payload["results"][0]["target_entity_id"],
                                "outcome": "completed",
                                "current_state_sha256": payload["current_state_sha256"],
                                "coverage_ledger_ref": "facet-coverage:r8",
                                "claim_delta_ledger_ref": "facet-claim-delta:r8",
                                "spend_reconciliation_ref": "facet-spend:r8",
                                "identity_use_verification_ref": "facet-identity:r8",
                                "completed_field_keys": [self.question.split("|", 1)[0]],
                                "claim_refs": claim_refs,
                                "evidence_refs": evidence_refs,
                                "result_refs": result_refs,
                            },
                            "id": "r8-facet-typed-final",
                        }
                    ],
                )
            elif last.name == "research_contact_deep":
                result_refs, _claims, _evidence = self._refs(payload)
                self._result_refs.extend(result_refs)
                response = AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "delegate_contact_facet",
                            "args": {
                                "facet_key": self._field_key,
                                "question": self.question.split("|", 1)[1],
                            },
                            "id": "r8-delegate-facet",
                        }
                    ],
                )
            elif last.name == "delegate_contact_facet":
                self._result_refs.extend(
                    ref for ref in payload["result_refs"] if ref not in self._result_refs
                )
                response = AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "assess_contact_coverage",
                            "args": {
                                "result_refs": self._result_refs,
                                "assessment_note": (
                                    "The selected public facet is grounded for this exact contact."
                                ),
                            },
                            "id": "r8-coverage",
                        }
                    ],
                )
            elif last.name == "assess_contact_coverage":
                assert payload["unresolved_field_keys"] == []
                response = AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "finalize_contact_research",
                            "args": {
                                "coverage_ledger_ref": payload["coverage_ledger_ref"],
                                "requested_outcome": "completed",
                            },
                            "id": "r8-finalize-tool",
                        }
                    ],
                )
            elif last.name == "finalize_contact_research":
                response = AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "ResearchFinalizationProposal",
                            "args": payload,
                            "id": "r8-contact-typed-final",
                        }
                    ],
                )
            else:  # pragma: no cover - new tool flow must be explicitly accepted
                raise AssertionError(f"unexpected R8 tool result: {last.name}")
        return ChatResult(generations=[ChatGeneration(message=response)])


class _Models:
    def __init__(self, *, facet_key: str, question: str) -> None:
        self._encoded = f"{facet_key}|{question}"
        self.instances: list[_DecisionModel] = []

    def build(self, **_kwargs: object) -> BaseChatModel:
        model = _DecisionModel(question=self._encoded)
        self.instances.append(model)
        return model


class _ChannelDecisionModel(_DecisionModel):
    @property
    def role(self) -> str:
        return "contact"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        tools = [message for message in messages if isinstance(message, ToolMessage)]
        if not tools:
            response = AIMessage(
                content="",
                tool_calls=[{"name": "read_contact_research_state", "args": {}, "id": "r8-c-read"}],
            )
        else:
            last = tools[-1]
            payload = self._payload(last)
            if last.name == "read_contact_research_state":
                assert payload["identity"]["contact_entity_id"] == payload["contact_entity_id"]
                response = AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "reveal_contact_channel",
                            "args": {"channel": "email"},
                            "id": "r8-c-reveal",
                        }
                    ],
                )
            elif last.name == "reveal_contact_channel":
                assert payload["stage"] == "acquisition"
                response = AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "validate_contact_channel",
                            "args": {"channel": "email"},
                            "id": "r8-c-validate",
                        }
                    ],
                )
            elif last.name == "validate_contact_channel":
                assert payload["stage"] == "validation" and payload["delivery_eligible"]
                response = AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "assess_contact_coverage",
                            "args": {
                                "result_refs": [],
                                "assessment_note": "The selected email is independently validated.",
                            },
                            "id": "r8-c-coverage",
                        }
                    ],
                )
            elif last.name == "assess_contact_coverage":
                assert payload["unresolved_field_keys"] == ["contact.facet.publications"]
                assert payload["review_flags"] == ["contact_fields_unresolved"]
                response = AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "finalize_contact_research",
                            "args": {
                                "coverage_ledger_ref": payload["coverage_ledger_ref"],
                                "requested_outcome": "needs_review",
                            },
                            "id": "r8-c-finalize",
                        }
                    ],
                )
            elif last.name == "finalize_contact_research":
                response = AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "ResearchFinalizationProposal",
                            "args": payload,
                            "id": "r8-c-typed-final",
                        }
                    ],
                )
            else:  # pragma: no cover
                raise AssertionError(f"unexpected R8 channel tool result: {last.name}")
        return ChatResult(generations=[ChatGeneration(message=response)])


class _ChannelModels:
    def build(self, **_kwargs: object) -> BaseChatModel:
        return _ChannelDecisionModel(question="contact.channel|validate selected email")


class _NeverProviderAction:
    async def execute(self, *_args: object, **_kwargs: object) -> Any:
        raise AssertionError("channel-only contact agent must not invoke a research provider")


class _ExactContactTransport:
    """Deterministic wire fixture behind the real Exa acquisition/materialization adapter."""

    def __init__(
        self,
        *,
        payload: Mapping[str, Any],
        tracker: _NestedConnFactory,
        contact_id: UUID,
        observed_targets: list[UUID],
    ) -> None:
        self._payload = payload
        self._tracker = tracker
        self._contact_id = contact_id
        self._observed_targets = observed_targets
        self.calls = 0

    def search(self, request: object) -> Mapping[str, Any]:
        del request
        assert self._tracker.active == 0, "Exa traffic occurred under a database transaction"
        self.calls += 1
        self._observed_targets.append(self._contact_id)
        return self._payload


def _exact_contact_payload(*, full_name: str, employer_name: str) -> dict[str, Any]:
    encoded = json.dumps(exa_contact_payload("supported.json"))
    encoded = encoded.replace("Alex Rivera", full_name)
    encoded = encoded.replace("Cascade Gastroenterology Associates", employer_name)
    payload = cast(dict[str, Any], json.loads(encoded))
    payload["requestId"] = f"exa-r8-{full_name.casefold().replace(' ', '-')}"
    payload["costDollars"] = {"total": 0.01}
    return payload


class _NoChannelActions(ContactChannelActions):
    async def reveal(self, **_values: object) -> Any:
        raise AssertionError("channel reveal was not selected")

    async def validate(self, **_values: object) -> Any:
        raise AssertionError("channel validation was not selected")


async def _handle_claimed_job(
    conn: AsyncConnection,
    *,
    job_id: UUID,
    handler: ContactResearchFleetWorkHandler,
) -> WorkResult:
    worker_id = f"r8-worker:{job_id}"
    task = await claim_next_task(
        conn,
        kind=FleetTaskKind.ENTITY_RESEARCH_JOB,
        worker_id=worker_id,
        project_run_id=ProjectRunId(job_id),
    )
    assert task is not None
    lease = await acquire_work_lease(
        conn,
        work_id=WorkId(job_id),
        worker_id=worker_id,
        ttl=_TTL,
    )
    assert lease is not None
    try:
        result = await handler.handle(
            WorkContext(
                task_id=task.task_id,
                work_id=WorkId(job_id),
                worker_id=worker_id,
                lease_generation=LeaseGeneration(lease.generation),
                payload={"job_id": str(job_id)},
                stop_requested=asyncio.Event(),
                lease_lost=asyncio.Event(),
            )
        )
        assert result.task_finalized
        return result
    finally:
        await release_work_lease(
            conn,
            work_id=WorkId(job_id),
            worker_id=worker_id,
            generation=LeaseGeneration(lease.generation),
        )


def test_r8_contact_agents_profile_only_the_exact_selected_set_on_shared_fleet(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "r8-artifacts")
        async with rollback_conn() as conn:
            (
                seed,
                _initial,
                selection,
                _approval,
                _approval_operation_id,
                approved_at,
                non_committee_id,
            ) = await _approved_mixed_selection(conn, tmp_path, suffix="r8-exact-fleet")
            unselected_id, _ = await _non_committee_identity_claim(
                conn,
                account_id=UUID(str(seed.account_id)),
                account_run_id=UUID(str(seed.account_run_id)),
                suffix="r8-never-selected",
            )
            launched = await ContactResearchFleetLauncher(
                conn_factory=conn_session_factory(conn)
            ).launch(
                ContactResearchFleetLaunchRequest(
                    workspace_id=selection.body.workspace_id,
                    selection_id=UUID(str(selection.selection_id)),
                    selection_sha256=selection.selection_sha256,
                    approved_budget_cap_cents=selection.body.execution_budget_cap_cents,
                    expected_estimated_cost_cents=selection.body.execution_budget_cap_cents,
                    concurrency_limit=2,
                ),
                actor="human:r8-owner",
                source_action_ref="turn:r8-launch:exact-set",
                source_operation_id=uuid4(),
                confirmed_at=approved_at + timedelta(seconds=1),
            )
            selected_ids = {UUID(str(seed.contact_id)), non_committee_id}
            assert {job.contact_entity_id for job in launched.jobs} == selected_ids
            connection = _NestedConnFactory(conn)
            result_store = EntityResearchResultStore(
                storage=storage,
                conn_factory=connection,
                lineage_readers={
                    ExternalResearchResultLineageReader.provider_kind: (
                        ExternalResearchResultLineageReader(conn_factory=connection)
                    )
                },
            )
            tools = GovernedEntityResearchToolFactory(
                requests=EntityResearchToolRequestStore(
                    conn_factory=connection,
                    storage=storage,
                ),
                causation=EntityResearchProviderCausationStore(conn_factory=connection),
                results=result_store,
            )
            state = ContactResearchStateStore(conn_factory=connection)
            question = selection.body.targets[0].directional_question_ids[0]
            effective_question = launched.jobs[0].research_questions[0]
            facet_key = str(selection.body.targets[0].facet_keys[0])
            assert question and effective_question and facet_key
            models = _Models(facet_key=facet_key, question=effective_question)
            journal = DbEntityResearchAgentJournal(conn_factory=connection)
            guard = ContactResearchExecutionGuard(conn_factory=connection)
            runtime = EntityResearchAgentRuntime(
                factory=EntityResearchAgentFactory(models=models, journal=journal, guard=guard),
                checkpointers=Checkpointers(),
                journal=journal,
                finalizer=ContactResearchFinalizationEngine(conn_factory=connection),
            )
            provider_targets: list[UUID] = []
            actions: dict[UUID, dict[str, ProviderActionBinding]] = {}
            for job in launched.jobs:
                authority_row = (
                    (
                        await conn.execute(
                            text(
                                "SELECT contact_intent_json FROM "
                                "entity_research_contact_job_authority WHERE job_id=:job_id"
                            ),
                            {"job_id": job.job_id},
                        )
                    )
                    .mappings()
                    .one()
                )
                intent = ContactResearchIntent.model_validate(authority_row["contact_intent_json"])
                contact = await get_contact(conn, EntityId(intent.contact_entity_id))
                account = await get_account(conn, EntityId(intent.account_entity_id))
                assert contact is not None and contact.full_name
                assert account is not None and account.canonical_name
                transport = _ExactContactTransport(
                    payload=_exact_contact_payload(
                        full_name=contact.full_name,
                        employer_name=account.canonical_name,
                    ),
                    tracker=connection,
                    contact_id=UUID(str(intent.contact_entity_id)),
                    observed_targets=provider_targets,
                )
                coordinator = ExaDeepAcquisitionCoordinator(
                    transport=transport,
                    storage=storage,
                    conn_factory=connection,
                )
                action = ExaContactSemanticResearchAction(
                    intent=intent,
                    effective_policy=intent.selection.body.policy,
                    acquisition=ExaDeepContactAcquisitionService(
                        coordinator=coordinator,
                        conn_factory=connection,
                    ),
                    materializer=ExaDeepContactSnapshotMaterializer(
                        provider=ExaDeepContactSnapshotResolverProvider(
                            storage=storage,
                            conn_factory=connection,
                        ),
                        conn_factory=connection,
                    ),
                    projector=ExaEntityResearchProjectionBuilder(
                        storage=storage,
                        conn_factory=connection,
                    ),
                    run_id=new_run_id(),
                    observation_window=f"m8d-r8:{job.job_id}",
                )
                binding = ProviderActionBinding(action=action, version=1)
                actions[job.job_id] = {
                    "research_contact_deep": binding,
                    "enrich_contact": binding,
                }
            channels = {job.job_id: _NoChannelActions() for job in launched.jobs}
            definitions = ContactResearchDefinitionResolver(
                tools=tools,
                state=state,
                provider_actions=StaticContactResearchProviderActions(actions),
                channel_actions=StaticContactResearchChannelActions(channels),
                facet_runtime=runtime,
                model_policy=ModelPolicy(
                    model_id="r8-test-model",
                    timeout_s=10,
                    max_retries=0,
                    max_output_tokens=4096,
                    temperature=0,
                ),
                conn_factory=connection,
            )
            fleets = ContactResearchFleetService(conn_factory=connection)
            handler = ContactResearchFleetWorkHandler(
                inner=EntityResearchJobWorkHandler(
                    store=DbEntityResearchJobStore(conn_factory=connection),
                    driver=CreateAgentEntityResearchDriver(
                        runtime=runtime,
                        definitions=definitions,
                    ),
                ),
                fleets=fleets,
            )
            create_agent_calls: list[str] = []
            real_create_agent: Any = runtime_module.create_agent

            def spy_create_agent(*args: object, **kwargs: object) -> Any:
                create_agent_calls.append(str(kwargs.get("name")))
                return real_create_agent(*args, **kwargs)

            monkeypatch.setattr(runtime_module, "create_agent", spy_create_agent)
            outcomes = [
                await _handle_claimed_job(conn, job_id=job.job_id, handler=handler)
                for job in launched.jobs
            ]
            assert [item.outcome for item in outcomes] == ["completed", "completed"]
            terminal = await fleets.read(
                launched.research_run_id,
                workspace_id=selection.body.workspace_id,
            )
            assert terminal is not None
            assert terminal.fleet_state is ContactResearchFleetState.TERMINAL
            assert set(terminal.selected_contact_ids) == selected_ids
            assert terminal.completed_count == terminal.terminal_count == 2
            assert terminal.needs_review_count == terminal.waiting_count == 0
            # Each parent contact causes one provider operation; its facet child observes the
            # ready snapshot through a separate governed tool call without duplicate dispatch.
            assert terminal.provider_operation_count == 2
            assert terminal.account_tool_request_count == 0
            assert terminal.unselected_contact_request_count == 0
            assert all(job.coverage_ref and job.finalization_receipt_ref for job in terminal.jobs)
            returned = await fleets.latest_return(
                launched.research_run_id,
                workspace_id=selection.body.workspace_id,
            )
            assert returned is not None and returned.return_kind == "terminal"
            assert returned.projection == terminal
            assert (
                await fleets.read(launched.research_run_id, workspace_id="foreign-workspace")
                is None
            )
            assert (
                await fleets.latest_return(
                    launched.research_run_id,
                    workspace_id="foreign-workspace",
                )
                is None
            )
            assert create_agent_calls.count("clue-entity-contact") == 2
            assert create_agent_calls.count("clue-entity-facet") == 2
            assert {model.role for model in models.instances} == {"contact", "facet"}
            assert set(provider_targets) == selected_ids
            assert len(provider_targets) == len(selected_ids)
            assert unselected_id not in provider_targets

            counts = (
                (
                    await conn.execute(
                        text(
                            "SELECT "
                            "(SELECT count(*) FROM entity_research_contact_identity_lock WHERE "
                            " research_run_id=:run_id) AS identity_locks, "
                            "(SELECT count(*) FROM entity_research_contact_facet_event WHERE "
                            " research_run_id=:run_id AND state='completed') AS completed_facets, "
                            "(SELECT count(*) FROM entity_research_contact_coverage WHERE "
                            " research_run_id=:run_id) AS coverage_rows, "
                            "(SELECT count(*) FROM entity_research_contact_finalization_intent "
                            " WHERE research_run_id=:run_id) AS finalization_intents, "
                            "(SELECT count(*) FROM entity_research_tool_request WHERE "
                            " research_run_id=:run_id AND tool_name='research_contact_deep') "
                            "AS deep_requests, "
                            "(SELECT count(*) FROM entity_research_provider_observation obs JOIN "
                            " entity_research_tool_request req USING (tool_request_id) WHERE "
                            " req.research_run_id=:run_id AND obs.disposition='caused') "
                            "AS caused_operations, "
                            "(SELECT count(*) FROM entity_research_provider_observation obs JOIN "
                            " entity_research_tool_request req USING (tool_request_id) WHERE "
                            " req.research_run_id=:run_id AND "
                            "obs.disposition='replay_observation') AS replay_observations, "
                            "(SELECT count(*) FROM entity_research_tool_request WHERE "
                            " research_run_id=:run_id AND target_entity_id=:unselected) "
                            "AS unselected_requests, "
                            "(SELECT count(*) FROM entity_research_tool_request WHERE "
                            " research_run_id=:run_id AND subject_type='account') "
                            "AS account_requests"
                        ),
                        {"run_id": launched.research_run_id, "unselected": unselected_id},
                    )
                )
                .mappings()
                .one()
            )
            assert counts == {
                "identity_locks": 2,
                "completed_facets": 2,
                "coverage_rows": 2,
                "finalization_intents": 2,
                "deep_requests": 4,
                "caused_operations": 2,
                "replay_observations": 2,
                "unselected_requests": 0,
                "account_requests": 0,
            }

    run_async(scenario())


def test_r8_static_bindings_are_rejected_by_production_composition(tmp_path: Path) -> None:
    from clue_api.contact_research_fleet_composition import build_contact_research_fleet_composition

    with pytest.raises(TypeError, match="cannot use static action bindings"):
        build_contact_research_fleet_composition(
            storage=FsStorage(tmp_path / "r8-production-guard"),
            models=cast(Any, object()),
            provider_actions=StaticContactResearchProviderActions({}),
            channel_actions=StaticContactResearchChannelActions({}),
            model_policy=ModelPolicy(
                model_id="never-built",
                timeout_s=1,
                max_retries=0,
                max_output_tokens=1,
                temperature=0,
            ),
        )


def test_r8_channel_acquisition_and_validation_are_separate_dispatch_decisions(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "r8-channel-artifacts")
        async with rollback_conn() as conn:
            intent, policy, corroborating_claim_id = await _channel_intent(
                conn,
                storage,
                suffix="r8-split-dispatch",
            )
            contact = await get_contact(conn, intent.contact_entity_id)
            assert contact is not None and contact.linkedin_url is not None
            connection = _TransactionalTrackedConnFactory(conn)
            transport = ChannelTransport(contact.linkedin_url)
            validator = _Validator(corroborating_claim_id)
            coordinator = ExaContactChannelCoordinator(
                transport=transport,
                validator=validator,
                use_gate=_UseGate(),
                pre_spend_gate=_PassGate(),
                storage=storage,
                conn_factory=connection,
                poll_after_seconds=1,
            )
            acquisition_dispatches: list[UUID] = []
            validation_dispatches: list[UUID] = []

            async def before_acquisition(operation: Any) -> None:
                assert connection.active == 0
                acquisition_dispatches.append(UUID(str(operation.operation_id)))

            async def before_validation(operation: Any) -> None:
                assert connection.active == 0
                validation_dispatches.append(UUID(str(operation.operation_id)))

            started = await coordinator.start(
                intent=intent,
                effective_policy=policy.pin(),
                channel=ContactChannel.EMAIL,
                observation_window="m8d-r8-split-dispatch",
                defer_validation=True,
                before_acquisition_dispatch=before_acquisition,
            )
            assert started.outcome is ContactChannelEnrichmentOutcome.CREATED
            assert len(acquisition_dispatches) == 1
            assert validation_dispatches == [] and validator.calls == 0

            ready = await coordinator.drive_once(
                workspace_id=intent.workspace_id,
                operation_id=started.operation.operation_id,
                effective_policy=policy.pin(),
                defer_validation=True,
            )
            assert ready.outcome is ContactChannelEnrichmentOutcome.READY_TO_VALIDATE
            assert ready.operation.validation is None
            assert validation_dispatches == [] and validator.calls == 0

            validated = await coordinator.validate_ready(
                workspace_id=intent.workspace_id,
                operation_id=ready.operation.operation_id,
                effective_policy=policy.pin(),
                before_validation_dispatch=before_validation,
            )
            assert validated.outcome is ContactChannelEnrichmentOutcome.SUCCEEDED
            assert validation_dispatches == acquisition_dispatches
            assert validator.calls == 1

    run_async(scenario())


def test_r8_channel_agent_waits_resumes_folds_spend_and_finalizes_on_shared_fleet(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "r8-channel-fleet-artifacts")
        async with rollback_conn() as conn:
            intent, policy, corroborating_claim_id = await _channel_intent(
                conn,
                storage,
                suffix="r8-channel-fleet",
            )
            approved_at = intent.selection.body.approved_at + timedelta(seconds=1)
            facet_key = "contact.facet.publications"
            target = intent.selection.body.targets[0].model_copy(
                update={
                    "field_keys": (facet_key, "core.work_email"),
                    "field_source_authority": (
                        FieldSourceAuthority(
                            field_key=facet_key,
                            source_keys=("exa_deep",),
                        ),
                    ),
                    "directional_question_ids": ("publication-direction-c5-r8-channel-fleet",),
                    "facet_keys": (facet_key,),
                    "research_budget_envelope_ref": "budget:r8-channel-research",
                    "research_budget_cap_cents": Decimal("2.00"),
                }
            )
            body = intent.selection.body.model_copy(
                update={
                    "targets": (target,),
                    "budget_reservation_ref": "budget:r8-channel-agent",
                    "budget_cap_cents": Decimal("2.00"),
                    "approved_by": "human:r8-channel-owner",
                    "approved_at": approved_at,
                }
            )
            selection = ContactResearchSelection.from_body(
                body,
                effective_policy=body.policy,
                selection_id=new_contact_research_selection_id(),
            )
            account_run_id = (
                await conn.execute(
                    text(
                        "SELECT account_run_id FROM contact_research_selection WHERE "
                        "workspace_id=:workspace_id AND id=:selection_id"
                    ),
                    {
                        "workspace_id": intent.workspace_id,
                        "selection_id": intent.selection_id,
                    },
                )
            ).scalar_one()
            selection = await store_contact_research_selection(
                conn,
                selection,
                account_run_id=account_run_id,
                predecessor_id=intent.selection_id,
                approval=ContactResearchSelectionApprovalAuthority(
                    kind=ContactResearchSelectionApprovalKind.HUMAN_SUCCESSOR,
                    operation_id=uuid4(),
                    approved_by=body.approved_by,
                    action_ref="human-action:r8-channel-selection",
                    approved_at=approved_at,
                ),
            )
            intent = ContactResearchIntent.from_selection(
                selection,
                contact_entity_id=intent.contact_entity_id,
            )
            launched = await ContactResearchFleetLauncher(
                conn_factory=conn_session_factory(conn)
            ).launch(
                ContactResearchFleetLaunchRequest(
                    workspace_id=selection.body.workspace_id,
                    selection_id=UUID(str(selection.selection_id)),
                    selection_sha256=selection.selection_sha256,
                    approved_budget_cap_cents=selection.body.execution_budget_cap_cents,
                    expected_estimated_cost_cents=selection.body.execution_budget_cap_cents,
                    concurrency_limit=1,
                ),
                actor="human:r8-channel-owner",
                source_action_ref="turn:r8-channel-launch",
                source_operation_id=uuid4(),
                confirmed_at=selection.body.approved_at + timedelta(seconds=1),
            )
            job = launched.jobs[0]
            connection = _NestedConnFactory(conn)
            contact = await get_contact(conn, intent.contact_entity_id)
            assert contact is not None and contact.linkedin_url is not None
            transport = ChannelTransport(contact.linkedin_url)
            validator = _Validator(corroborating_claim_id)
            coordinator = ExaContactChannelCoordinator(
                transport=transport,
                validator=validator,
                use_gate=_UseGate(),
                pre_spend_gate=_PassGate(),
                storage=storage,
                conn_factory=connection,
                poll_after_seconds=1,
            )
            state = ContactResearchStateStore(conn_factory=connection)
            channel_actions = GovernedContactChannelActions(
                intent=intent,
                effective_policy=policy.pin(),
                coordinator=coordinator,
                state=state,
                observation_window="m8d-r8-channel-agent",
                conn_factory=connection,
            )
            binding = ProviderActionBinding(action=_NeverProviderAction(), version=1)
            actions = StaticContactResearchProviderActions(
                {
                    job.job_id: {
                        "research_contact_deep": binding,
                        "enrich_contact": binding,
                    }
                }
            )
            channels = StaticContactResearchChannelActions({job.job_id: channel_actions})
            result_store = EntityResearchResultStore(
                storage=storage,
                conn_factory=connection,
                lineage_readers={
                    ExternalResearchResultLineageReader.provider_kind: (
                        ExternalResearchResultLineageReader(conn_factory=connection)
                    )
                },
            )
            tools = GovernedEntityResearchToolFactory(
                requests=EntityResearchToolRequestStore(
                    conn_factory=connection,
                    storage=storage,
                ),
                causation=EntityResearchProviderCausationStore(conn_factory=connection),
                results=result_store,
            )
            journal = DbEntityResearchAgentJournal(conn_factory=connection)
            runtime = EntityResearchAgentRuntime(
                factory=EntityResearchAgentFactory(
                    models=_ChannelModels(),
                    journal=journal,
                    guard=ContactResearchExecutionGuard(conn_factory=connection),
                ),
                checkpointers=Checkpointers(),
                journal=journal,
                finalizer=ContactResearchFinalizationEngine(conn_factory=connection),
            )
            definitions = ContactResearchDefinitionResolver(
                tools=tools,
                state=state,
                provider_actions=actions,
                channel_actions=channels,
                facet_runtime=runtime,
                model_policy=ModelPolicy(
                    model_id="r8-channel-test-model",
                    timeout_s=10,
                    max_retries=0,
                    max_output_tokens=4096,
                    temperature=0,
                ),
                conn_factory=connection,
            )
            job_store = DbEntityResearchJobStore(conn_factory=connection)
            fleets = ContactResearchFleetService(conn_factory=connection)
            handler = ContactResearchFleetWorkHandler(
                inner=EntityResearchJobWorkHandler(
                    store=job_store,
                    driver=CreateAgentEntityResearchDriver(
                        runtime=runtime,
                        definitions=definitions,
                    ),
                ),
                fleets=fleets,
            )

            waiting = await _handle_claimed_job(conn, job_id=job.job_id, handler=handler)
            assert waiting.outcome == "waiting_external"
            waiting_job = await job_store.get_job(job.job_id)
            assert waiting_job is not None and waiting_job.current_wait_ref
            operation_id = UUID(waiting_job.current_wait_ref.rsplit(":", 1)[1])
            ready = await coordinator.drive_once(
                workspace_id=intent.workspace_id,
                operation_id=ContactChannelOperationId(operation_id),
                effective_policy=policy.pin(),
                defer_validation=True,
            )
            assert ready.outcome is ContactChannelEnrichmentOutcome.READY_TO_VALIDATE
            await job_store.wake(
                job.job_id,
                wait_ref=waiting_job.current_wait_ref,
                actor="provider:r8-channel-ready",
            )

            completed = await _handle_claimed_job(conn, job_id=job.job_id, handler=handler)
            assert completed.outcome == "needs_review"
            projection = await fleets.read(
                launched.research_run_id,
                workspace_id=selection.body.workspace_id,
            )
            assert projection is not None
            assert projection.fleet_state is ContactResearchFleetState.TERMINAL
            assert projection.needs_review_count == 1
            assert projection.selected_contact_ids == (intent.contact_entity_id,)
            assert projection.account_tool_request_count == 0
            assert projection.unselected_contact_request_count == 0
            assert validator.calls == 1
            spend = (
                (
                    await conn.execute(
                        text(
                            "SELECT job.spent_cents AS job_spent, run.spent_cents AS run_spent, "
                            "(SELECT sum(cost_cents) FROM "
                            "entity_research_contact_channel_cost_fold WHERE job_id=job.job_id) "
                            "AS folded, (SELECT count(*) FROM "
                            "entity_research_contact_channel_causation WHERE job_id=job.job_id) "
                            "AS decisions, (SELECT "
                            "operation.acquisition_cost_cents_charged + "
                            "operation.validation_cost_cents_charged FROM "
                            "contact_channel_operation operation JOIN "
                            "entity_research_contact_channel_causation link ON "
                            "link.channel_operation_id=operation.id WHERE "
                            "link.job_id=job.job_id LIMIT 1) AS provider_settled FROM "
                            "entity_research_job job JOIN entity_research_run "
                            "run USING (research_run_id) WHERE job.job_id=:job_id"
                        ),
                        {"job_id": job.job_id},
                    )
                )
                .mappings()
                .one()
            )
            assert spend["job_spent"] == spend["run_spent"] == spend["folded"]
            assert spend["folded"] == spend["provider_settled"]
            assert Decimal("0") < spend["folded"] <= selection.body.execution_budget_cap_cents
            assert spend["decisions"] == 2

    run_async(scenario())
