"""M8D R3 executable acceptance for the shared ``create_agent`` runtime."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel

import clue_agents.entity_research_runtime as runtime_module
from clue_agents.contracts import ModelPolicy
from clue_agents.entity_research_contracts import (
    EntityAgentJournalEventKind,
    EntityAgentRole,
    EntityFacetScope,
    EntityResearchAgentDefinition,
    EntityResearchAgentResult,
    EntityResearchAgentSuspension,
    EntityResearchJournalEvent,
    EntityResearchResource,
    EntityResearchResourceBundle,
    EntityResearchRuntimeContext,
    EntityResearchStopPolicy,
    EntityResearchToolBinding,
    EntityResearchToolCall,
    canonical_sha256,
)
from clue_agents.entity_research_runtime import (
    EntityResearchAgentAborted,
    EntityResearchAgentFactory,
    EntityResearchAgentRuntime,
    EntityResearchExecutionGuard,
    EntityResearchExternalWait,
    EntityResearchFinalizationEngine,
    EntityResearchFinalizationRejected,
    EntityResearchRuntimeError,
)
from clue_agents.model import ScriptedAgentChatModel
from clue_core.entity_research import (
    EntityAgentToolSurface,
    FacetDelegationContract,
    FinalizationVerification,
    ResearchFinalizationOutcome,
    ResearchFinalizationProposal,
    ResearchFinalizationReceipt,
    ResearchRunKind,
    ResearchSubjectType,
)
from tests.db.conftest import run_async
from tests.fleet.entity_research_r2_helpers import run_envelope

ACCOUNT_TOOLS = (
    "read_account_research_state",
    "research_account_deep",
    "enrich_account",
    "inspect_account_evidence",
    "discover_buying_committee",
    "record_committee_role_inferences",
    "assess_account_coverage",
    "read_research_result",
    "read_evidence",
    "finalize_account_research",
    "delegate_account_facet",
)
CONTACT_TOOLS = (
    "read_contact_research_state",
    "research_contact_deep",
    "enrich_contact",
    "inspect_contact_evidence",
    "assess_contact_coverage",
    "read_research_result",
    "read_evidence",
    "finalize_contact_research",
    "delegate_contact_facet",
    "reveal_contact_channel",
    "validate_contact_channel",
)


class ToolInput(BaseModel):
    value: str = "ok"


class Models:
    def __init__(self, model: ScriptedAgentChatModel) -> None:
        self.model = model

    def build(self, **_kwargs: object) -> ScriptedAgentChatModel:
        return self.model


class Journal:
    def __init__(self) -> None:
        self.started: list[dict[str, object]] = []
        self.events: list[EntityResearchJournalEvent] = []

    async def start(self, **values: object) -> None:
        self.started.append(values)

    async def append(self, event: EntityResearchJournalEvent) -> str:
        self.events.append(event)
        return f"entity-agent-event:{event.event_id}"


class Guard(EntityResearchExecutionGuard):
    def __init__(self) -> None:
        self.parallel: list[tuple[EntityResearchToolCall, ...]] = []
        self.authorized: list[tuple[EntityResearchToolCall, str]] = []
        self.results: list[EntityResearchToolCall] = []

    async def authorize_parallel(
        self,
        *,
        context: EntityResearchRuntimeContext,
        calls: Sequence[EntityResearchToolCall],
    ) -> None:
        del context
        self.parallel.append(tuple(calls))

    async def authorize_tool(
        self,
        *,
        context: EntityResearchRuntimeContext,
        call: EntityResearchToolCall,
        journal_event_ref: str,
    ) -> None:
        del context
        self.authorized.append((call, journal_event_ref))

    async def observe_tool_result(
        self,
        *,
        context: EntityResearchRuntimeContext,
        call: EntityResearchToolCall,
        result: object,
    ) -> None:
        del context, result
        self.results.append(call)


class BatchRecorder:
    def __init__(self) -> None:
        self.admitted: list[tuple[EntityResearchToolCall, ...]] = []
        self.completed_calls: list[EntityResearchToolCall] = []
        self.failed_calls: list[tuple[EntityResearchToolCall, BaseException]] = []

    async def admit(
        self,
        *,
        context: EntityResearchRuntimeContext,
        calls: Sequence[EntityResearchToolCall],
    ) -> None:
        del context
        self.admitted.append(tuple(calls))

    async def replay(
        self,
        *,
        context: EntityResearchRuntimeContext,
        call: EntityResearchToolCall,
    ) -> runtime_module.EntityResearchToolReplay:
        del context, call
        return runtime_module.EntityResearchToolReplay(found=False)

    async def completed(
        self,
        *,
        context: EntityResearchRuntimeContext,
        call: EntityResearchToolCall,
        result: object,
    ) -> None:
        del context, result
        self.completed_calls.append(call)

    async def waiting(
        self,
        *,
        context: EntityResearchRuntimeContext,
        call: EntityResearchToolCall,
        wait: EntityResearchExternalWait,
    ) -> EntityResearchExternalWait:
        del context, call
        return wait

    async def failed(
        self,
        *,
        context: EntityResearchRuntimeContext,
        call: EntityResearchToolCall,
        error: BaseException,
    ) -> None:
        del context
        self.failed_calls.append((call, error))


class Finalizer(EntityResearchFinalizationEngine):
    def __init__(self) -> None:
        self.proposals: list[ResearchFinalizationProposal] = []

    async def accept(
        self,
        *,
        context: EntityResearchRuntimeContext,
        proposal: ResearchFinalizationProposal,
    ) -> ResearchFinalizationReceipt:
        del context
        self.proposals.append(proposal)
        return ResearchFinalizationReceipt(
            receipt_id=uuid4(),
            proposal=proposal,
            proposal_ref=f"finalization-proposal:{proposal.proposal_id}",
            engine_actor="engine:r3-test",
            accepted_at=datetime.now(UTC),
            accepted_state_sha256=proposal.current_state_sha256,
            verification=FinalizationVerification(
                no_pending_operations=True,
                evidence_complete=True,
                coverage_matches=True,
                spend_reconciled=True,
                identity_use_verification_complete=True,
                policy_scope_respected=True,
                current_state_matches=True,
            ),
        )


class Checkpointers:
    def __init__(self) -> None:
        self.by_thread: dict[str, InMemorySaver] = {}

    def open(self, thread_id: str) -> Any:
        return self._open(thread_id)

    @asynccontextmanager
    async def _open(self, thread_id: str) -> AsyncIterator[BaseCheckpointSaver[str]]:
        yield self.by_thread.setdefault(thread_id, InMemorySaver())


def _resource(kind: str, ref: str, version: str, body: str) -> EntityResearchResource:
    return EntityResearchResource(
        kind=kind,  # type: ignore[arg-type]
        ref=ref,
        version=version,
        sha256=hashlib.sha256(body.encode()).hexdigest(),
        body=body,
    )


def _proposal(context: EntityResearchRuntimeContext) -> ResearchFinalizationProposal:
    return ResearchFinalizationProposal(
        proposal_id=uuid4(),
        subject_type=context.authorization.subject_type,
        target_entity_id=context.authorization.subject_entity_id,
        outcome=ResearchFinalizationOutcome.COMPLETED,
        current_state_sha256=context.current_state_sha256,
        coverage_ledger_ref=f"coverage:{context.authorization.job_id}",
        claim_delta_ledger_ref=f"claims:{context.authorization.job_id}",
        spend_reconciliation_ref=f"spend:{context.authorization.job_id}",
        identity_use_verification_ref=f"identity-use:{context.authorization.job_id}",
    )


def _context(
    subject_type: ResearchSubjectType,
    role: EntityAgentRole,
) -> EntityResearchRuntimeContext:
    kind = (
        ResearchRunKind.ACCOUNT_RESEARCH
        if subject_type is ResearchSubjectType.ACCOUNT
        else ResearchRunKind.CONTACT_RESEARCH
    )
    authorization = run_envelope(kind).jobs[0].authorization
    profile_body = f"role: {subject_type.value}-research\nframework: langchain-create-agent\n"
    profile = _resource("profile", authorization.agent_profile_ref, "v1", profile_body)
    authorization = authorization.model_copy(
        update={"agent_profile_sha256": profile.sha256},
    )
    prompt = _resource(
        "prompt",
        f"prompt:{subject_type.value}-research",
        "v1",
        (
            "Research only the exact authorized subject. Prefer evidence; "
            "leave unsupported fields blank."
        ),
    )
    skill = _resource(
        "skill",
        f"skill:{subject_type.value}-research",
        "v1",
        "Inspect complete persisted tool results before choosing an additive follow-up.",
    )
    surface = EntityAgentToolSurface(
        subject_type=subject_type,
        tool_names=(
            ACCOUNT_TOOLS if subject_type is ResearchSubjectType.ACCOUNT else CONTACT_TOOLS
        ),
    )
    facet_scope = None
    if role is EntityAgentRole.FACET:
        facet_scope = EntityFacetScope(
            parent_agent_execution_id=uuid4(),
            parent_agent_turn_id=uuid4(),
            facet_key=authorization.effective_facet_keys[0],
            depth=1,
            child_ordinal=1,
            parent_budget_envelope_ref=authorization.effective_budget_envelope_ref,
        )
    return EntityResearchRuntimeContext(
        agent_execution_id=authorization.attempt_id,
        agent_turn_id=uuid4(),
        role=role,
        authorization=authorization,
        resources=EntityResearchResourceBundle(profile=profile, prompt=prompt, skills=(skill,)),
        tool_surface=surface,
        stop_policy=EntityResearchStopPolicy(
            max_model_rounds=8,
            max_tool_calls=32,
            max_runtime_s=10,
            max_parallel_tools=2,
            max_consecutive_zero_yield=2,
        ),
        facet_contract=FacetDelegationContract(
            enabled=True,
            max_depth=1,
            max_children=2,
        ),
        current_state_sha256="e" * 64,
        job_budget_cap_cents=Decimal("4"),
        job_spent_cents=Decimal("0"),
        run_budget_remaining_cents=Decimal("10"),
        facet_scope=facet_scope,
    )


def _tool(name: str, callback: Any | None = None) -> StructuredTool:
    async def invoke(value: str = "ok") -> dict[str, str]:
        if callback is not None:
            await callback(name)
        return {"tool": name, "value": value}

    return StructuredTool.from_function(
        coroutine=invoke,
        name=name,
        description=f"Governed test double for {name}",
        args_schema=ToolInput,
    )


def _definition(
    context: EntityResearchRuntimeContext,
    *,
    callbacks: dict[str, Any] | None = None,
) -> EntityResearchAgentDefinition:
    names = (
        (context.tool_surface.tool_names[0],)
        if context.role is EntityAgentRole.FACET
        else context.tool_surface.tool_names
    )
    return EntityResearchAgentDefinition(
        context=context,
        model_policy=ModelPolicy(
            model_id="test-model",
            timeout_s=5,
            max_retries=0,
            max_output_tokens=4096,
            temperature=0,
        ),
        tools=tuple(
            EntityResearchToolBinding(
                tool=_tool(name, (callbacks or {}).get(name)),
                version=1,
            )
            for name in names
        ),
        task_instruction="Research the exact selected subject and propose an honest typed result.",
    )


def test_record_only_budget_context_does_not_turn_overspend_into_agent_refusal() -> None:
    context = _context(ResearchSubjectType.ACCOUNT, EntityAgentRole.ACCOUNT)
    payload = context.model_dump(mode="python")
    payload.update(
        {
            "budget_controls_enabled": False,
            "job_budget_cap_cents": Decimal("0"),
            "job_spent_cents": Decimal("5"),
            "run_budget_remaining_cents": Decimal("0"),
        }
    )

    record_only = EntityResearchRuntimeContext.model_validate(payload)

    assert record_only.model_context()["budget_controls_enabled"] is False
    payload["budget_controls_enabled"] = True
    with pytest.raises(ValueError, match="spend exceeds the exact job cap"):
        EntityResearchRuntimeContext.model_validate(payload)


@pytest.mark.parametrize(
    ("subject_type", "role"),
    (
        (ResearchSubjectType.ACCOUNT, EntityAgentRole.ACCOUNT),
        (ResearchSubjectType.CONTACT, EntityAgentRole.CONTACT),
        (ResearchSubjectType.CONTACT, EntityAgentRole.FACET),
    ),
)
def test_account_contact_and_facet_execute_through_langchain_create_agent(
    monkeypatch: pytest.MonkeyPatch,
    subject_type: ResearchSubjectType,
    role: EntityAgentRole,
) -> None:
    async def run() -> None:
        context = _context(subject_type, role)
        proposal = _proposal(context)
        model = ScriptedAgentChatModel(
            responses=(
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "ResearchFinalizationProposal",
                            "args": proposal.model_dump(mode="json"),
                            "id": f"typed-final-{role.value}",
                        }
                    ],
                ),
            )
        )
        journal = Journal()
        guard = Guard()
        finalizer = Finalizer()
        calls: list[str] = []
        real_create_agent: Any = runtime_module.create_agent  # type: ignore[attr-defined]

        def spy_create_agent(*args: object, **kwargs: object) -> Any:
            calls.append(str(kwargs.get("name")))
            return real_create_agent(*args, **kwargs)

        monkeypatch.setattr(runtime_module, "create_agent", spy_create_agent)
        factory = EntityResearchAgentFactory(
            models=Models(model),
            journal=journal,
            guard=guard,
        )
        runtime = EntityResearchAgentRuntime(
            factory=factory,
            checkpointers=Checkpointers(),
            journal=journal,
            finalizer=finalizer,
        )
        outcome = await runtime.run(definition=_definition(context))

        assert isinstance(outcome, EntityResearchAgentResult)
        assert calls == [f"clue-entity-{role.value}"]
        assert outcome.role is role
        assert outcome.proposal == proposal
        if role is EntityAgentRole.FACET:
            assert outcome.finalization_receipt is None
            assert not finalizer.proposals
        else:
            assert outcome.finalization_receipt is not None
            assert finalizer.proposals == [proposal]
        kinds = [event.kind for event in journal.events]
        assert kinds[0] is EntityAgentJournalEventKind.EXECUTION_STARTED
        assert EntityAgentJournalEventKind.MODEL_STARTED in kinds
        assert EntityAgentJournalEventKind.MODEL_COMPLETED in kinds
        assert EntityAgentJournalEventKind.FINALIZATION_PROPOSED in kinds

    run_async(run())


def test_independent_tool_calls_run_concurrently_after_journal_and_guard() -> None:
    async def run() -> None:
        context = _context(ResearchSubjectType.ACCOUNT, EntityAgentRole.ACCOUNT)
        proposal = _proposal(context)
        journal = Journal()
        guard = Guard()
        finalizer = Finalizer()
        both_started = asyncio.Event()
        starts: list[str] = []

        async def barrier(name: str) -> None:
            starts.append(name)
            if len(starts) == 2:
                both_started.set()
            await asyncio.wait_for(both_started.wait(), timeout=2)
            assert any(
                event.kind is EntityAgentJournalEventKind.TOOL_STARTED and event.tool_name == name
                for event in journal.events
            )

        first, second = "research_account_deep", "enrich_account"
        model = ScriptedAgentChatModel(
            responses=(
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": first, "args": {"value": "qualitative"}, "id": "call-1"},
                        {"name": second, "args": {"value": "structured"}, "id": "call-2"},
                    ],
                ),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "ResearchFinalizationProposal",
                            "args": proposal.model_dump(mode="json"),
                            "id": "typed-final",
                        }
                    ],
                ),
            )
        )
        definition = _definition(context, callbacks={first: barrier, second: barrier})
        factory = EntityResearchAgentFactory(
            models=Models(model),
            journal=journal,
            guard=guard,
        )
        runtime = EntityResearchAgentRuntime(
            factory=factory,
            checkpointers=Checkpointers(),
            journal=journal,
            finalizer=finalizer,
        )
        outcome = await runtime.run(definition=definition)

        assert isinstance(outcome, EntityResearchAgentResult)
        assert outcome.finalization_receipt is not None
        assert set(starts) == {first, second}
        assert len(guard.parallel) == 1
        assert {call.tool_name for call in guard.parallel[0]} == {first, second}
        assert {call.tool_name for call, _ in guard.authorized} == {first, second}
        for call, event_ref in guard.authorized:
            start = next(
                event
                for event in journal.events
                if event.kind is EntityAgentJournalEventKind.TOOL_STARTED
                and event.tool_call_id == call.tool_call_id
            )
            assert event_ref == f"entity-agent-event:{start.event_id}"

    run_async(run())


def test_runtime_module_never_imports_or_calls_create_deep_agent() -> None:
    source = Path(runtime_module.__file__).read_text()
    assert "from langchain.agents import create_agent" in source
    assert "create_deep_agent" not in source


def test_exact_construction_uses_profile_prompt_skills_model_and_task_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _context(ResearchSubjectType.ACCOUNT, EntityAgentRole.ACCOUNT)
    definition = _definition(context)
    observed: dict[str, Any] = {}

    def capture_create_agent(*args: object, **kwargs: object) -> object:
        del args
        observed.update(kwargs)
        return object()

    monkeypatch.setattr(runtime_module, "create_agent", capture_create_agent)
    EntityResearchAgentFactory(
        models=Models(ScriptedAgentChatModel(responses=())),
        journal=Journal(),
        guard=Guard(),
    ).create(definition=definition, checkpointer=InMemorySaver())

    system_prompt = str(observed["system_prompt"])
    assert context.resources.profile.body in system_prompt
    assert context.resources.prompt.body in system_prompt
    assert context.resources.skills[0].body in system_prompt
    exact_context = definition.exact_model_context()
    assert exact_context["model_policy"] == definition.model_policy.model_dump(mode="json")
    assert exact_context["task_instruction_sha256"] == canonical_sha256(definition.task_instruction)

    changed_task = definition.model_copy(update={"task_instruction": "A different task."})
    changed_model = definition.model_copy(
        update={
            "model_policy": definition.model_policy.model_copy(update={"model_id": "another-model"})
        }
    )
    assert canonical_sha256(changed_task.exact_model_context()) != canonical_sha256(exact_context)
    assert canonical_sha256(changed_model.exact_model_context()) != canonical_sha256(exact_context)


def test_checkpoint_threads_are_globally_scoped_even_when_raw_ids_collide() -> None:
    first = _context(ResearchSubjectType.ACCOUNT, EntityAgentRole.ACCOUNT)
    second = _context(ResearchSubjectType.ACCOUNT, EntityAgentRole.ACCOUNT)
    second = second.model_copy(
        update={
            "authorization": second.authorization.model_copy(
                update={
                    "checkpoint_thread_id": first.authorization.checkpoint_thread_id,
                }
            )
        }
    )

    assert first.authorization.checkpoint_thread_id == second.authorization.checkpoint_thread_id
    assert first.authorization.research_run_id != second.authorization.research_run_id
    assert first.effective_checkpoint_thread_id != second.effective_checkpoint_thread_id
    assert first.effective_checkpoint_thread_id.startswith("entity-research:")
    assert len(first.effective_checkpoint_thread_id.removeprefix("entity-research:")) == 64


def test_consecutive_zero_yield_limit_spans_interleaved_model_rounds() -> None:
    async def run() -> None:
        context = _context(ResearchSubjectType.ACCOUNT, EntityAgentRole.ACCOUNT)
        definition = _definition(context)
        journal = Journal()
        middleware = runtime_module._EntityResearchRuntimeMiddleware(
            definition=definition,
            journal=journal,
            guard=Guard(),
        )
        batch = json.dumps(
            {
                "tool_request_ref": "entity-research-tool-request:test",
                "results": [{"result_ref": "research-result:test"}],
                "current_state_sha256": "a" * 64,
                "yield_count": 0,
            }
        )
        messages = (
            AIMessage(
                content="",
                tool_calls=[{"name": "research_account_deep", "args": {}, "id": "zero-call-1"}],
            ),
            ToolMessage(content=batch, tool_call_id="zero-call-1"),
            AIMessage(
                content="",
                tool_calls=[{"name": "research_account_deep", "args": {}, "id": "zero-call-2"}],
            ),
            ToolMessage(content=batch, tool_call_id="zero-call-2"),
        )
        handler_called = False

        async def handler(_request: object) -> object:
            nonlocal handler_called
            handler_called = True
            return AIMessage(content="should not run")

        with pytest.raises(EntityResearchRuntimeError, match="consecutive zero-yield limit"):
            await middleware.awrap_model_call(
                SimpleNamespace(
                    tools=[binding.tool for binding in definition.tools],
                    messages=messages,
                ),
                handler,
            )
        assert not handler_called
        assert not journal.events

    run_async(run())


def test_structured_tool_rejection_is_returned_for_agent_repair_not_joined_as_result() -> None:
    async def run() -> None:
        context = _context(ResearchSubjectType.ACCOUNT, EntityAgentRole.ACCOUNT)
        definition = _definition(context)
        journal = Journal()
        guard = Guard()
        batches = BatchRecorder()
        middleware = runtime_module._EntityResearchRuntimeMiddleware(
            definition=definition,
            journal=journal,
            guard=guard,
            batches=batches,
        )
        raw_call = {
            "name": "discover_buying_committee",
            "args": {"value": "malformed"},
            "id": "repairable-committee-call",
        }
        rejected = ToolMessage(
            content="committee discovery enumerates people and must not request fields",
            tool_call_id="repairable-committee-call",
            name="discover_buying_committee",
            status="error",
        )

        async def handler(_request: object) -> ToolMessage:
            return rejected

        returned = await middleware.awrap_tool_call(
            SimpleNamespace(
                tool_call=raw_call,
                state={"messages": (AIMessage(content="", tool_calls=[raw_call]),)},
            ),
            handler,
        )

        assert returned is rejected
        assert len(batches.admitted) == 1
        assert not batches.completed_calls
        assert len(batches.failed_calls) == 1
        assert not guard.results
        assert [event.kind for event in journal.events] == [
            EntityAgentJournalEventKind.TOOL_STARTED,
            EntityAgentJournalEventKind.TOOL_FAILED,
        ]
        assert journal.events[-1].payload["disposition"] == "model_request_rejected"

    run_async(run())


def test_external_wait_returns_exact_durable_checkpoint_for_r2_driver() -> None:
    async def run() -> None:
        context = _context(ResearchSubjectType.ACCOUNT, EntityAgentRole.ACCOUNT)
        journal = Journal()

        async def wait_for_provider(_name: str) -> None:
            raise EntityResearchExternalWait(
                wait_ref="external-operation:pending-1",
                current_state_sha256=context.current_state_sha256,
            )

        model = ScriptedAgentChatModel(
            responses=(
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "research_account_deep",
                            "args": {"value": "bounded-request"},
                            "id": "wait-call-1",
                        }
                    ],
                ),
            )
        )
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
        outcome = await runtime.run(
            definition=_definition(
                context,
                callbacks={"research_account_deep": wait_for_provider},
            )
        )

        assert isinstance(outcome, EntityResearchAgentSuspension)
        assert outcome.wait_ref == "external-operation:pending-1"
        assert outcome.checkpoint_ref.startswith(
            f"langgraph:{context.effective_checkpoint_thread_id}:"
        )
        assert len(outcome.checkpoint_sha256) == 64
        assert outcome.current_state_sha256 == context.current_state_sha256
        assert journal.events[-1].kind is EntityAgentJournalEventKind.EXECUTION_SUSPENDED

    run_async(run())


def test_preexisting_stop_authority_wins_over_simultaneous_model_completion() -> None:
    async def run() -> None:
        context = _context(ResearchSubjectType.ACCOUNT, EntityAgentRole.ACCOUNT)
        proposal = _proposal(context)
        model = ScriptedAgentChatModel(
            responses=(
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "ResearchFinalizationProposal",
                            "args": proposal.model_dump(mode="json"),
                            "id": "typed-final-after-stop",
                        }
                    ],
                ),
            )
        )
        journal = Journal()
        finalizer = Finalizer()
        runtime = EntityResearchAgentRuntime(
            factory=EntityResearchAgentFactory(
                models=Models(model),
                journal=journal,
                guard=Guard(),
            ),
            checkpointers=Checkpointers(),
            journal=journal,
            finalizer=finalizer,
        )
        stop_requested = asyncio.Event()
        stop_requested.set()
        with pytest.raises(EntityResearchAgentAborted):
            await runtime.run(
                definition=_definition(context),
                stop_requested=stop_requested,
            )
        assert not finalizer.proposals
        assert journal.events[-1].kind is EntityAgentJournalEventKind.EXECUTION_CANCELLED

    run_async(run())


def test_facet_cannot_receive_delegation_finalization_or_separate_budget() -> None:
    context = _context(ResearchSubjectType.CONTACT, EntityAgentRole.FACET)
    with pytest.raises(ValueError, match="non-recursive subset"):
        EntityResearchAgentDefinition(
            context=context,
            model_policy=_definition(context).model_policy,
            tools=(EntityResearchToolBinding(tool=_tool("delegate_contact_facet"), version=1),),
            task_instruction="Attempt an impermissible recursive facet.",
        )

    assert context.facet_scope is not None
    with pytest.raises(ValueError, match="share the selected parent budget"):
        EntityResearchRuntimeContext.model_validate(
            {
                **context.model_dump(),
                "facet_scope": {
                    **context.facet_scope.model_dump(),
                    "parent_budget_envelope_ref": "budget:separate-child",
                },
            }
        )


def test_after_accepted_finalize_tool_every_further_tool_call_is_refused() -> None:
    """Prompt guidance alone did not stop live finalization looping (R10 defect #10).

    Once ``finalize_account_research`` returns the only admissible proposal, the middleware
    refuses every subsequent governed tool call deterministically, so the model's sole remaining
    move is emitting the typed structured response.
    """

    async def run() -> None:
        context = _context(ResearchSubjectType.ACCOUNT, EntityAgentRole.ACCOUNT)
        definition = _definition(context)
        journal = Journal()
        guard = Guard()
        batches = BatchRecorder()
        middleware = runtime_module._EntityResearchRuntimeMiddleware(
            definition=definition,
            journal=journal,
            guard=guard,
            batches=batches,
        )
        assert "finalize_account_research" in {b.name for b in definition.tools}

        finalize_call = {
            "name": "finalize_account_research",
            "args": {},
            "id": "finalize-once",
        }
        proposal = ToolMessage(
            content='{"proposal":"the-only-admissible-one"}',
            tool_call_id="finalize-once",
            name="finalize_account_research",
        )

        async def finalize_handler(_request: object) -> ToolMessage:
            return proposal

        returned = await middleware.awrap_tool_call(
            SimpleNamespace(
                tool_call=finalize_call,
                state={"messages": (AIMessage(content="", tool_calls=[finalize_call]),)},
            ),
            finalize_handler,
        )
        assert returned is proposal

        late_call = {
            "name": "read_account_research_state",
            "args": {},
            "id": "post-finalize-read",
        }

        async def must_not_run(_request: object) -> ToolMessage:
            raise AssertionError("post-finalization tool call must never execute")

        refused = await middleware.awrap_tool_call(
            SimpleNamespace(
                tool_call=late_call,
                state={"messages": (AIMessage(content="", tool_calls=[late_call]),)},
            ),
            must_not_run,
        )
        assert isinstance(refused, ToolMessage)
        assert refused.status == "error"
        assert "finalization_already_proposed" in str(refused.content)
        assert journal.events[-1].payload["disposition"] == "post_finalization_rejected"

    run_async(run())


def test_engine_finalize_result_terminates_the_graph_without_a_model_echo() -> None:
    """A live contact run looped on post-finalization refusals until GraphRecursionError.

    Once the finalize tool returns the engine's rendered proposal, ``abefore_model`` must end
    the graph deterministically with that proposal as the structured response instead of
    waiting for the model to volunteer the echo.
    """

    async def run() -> None:
        context = _context(ResearchSubjectType.CONTACT, EntityAgentRole.CONTACT)
        definition = _definition(context)
        middleware = runtime_module._EntityResearchRuntimeMiddleware(
            definition=definition,
            journal=Journal(),
            guard=Guard(),
            batches=BatchRecorder(),
        )
        assert "finalize_contact_research" in {b.name for b in definition.tools}
        # Before finalization the hook must never interfere with the model loop.
        assert await middleware.abefore_model({}, None) is None

        proposal = _proposal(context)
        finalize_call = {"name": "finalize_contact_research", "args": {}, "id": "finalize-live"}
        rendered = ToolMessage(
            content=proposal.model_dump_json(),
            tool_call_id="finalize-live",
            name="finalize_contact_research",
        )

        async def finalize_handler(_request: object) -> ToolMessage:
            return rendered

        returned = await middleware.awrap_tool_call(
            SimpleNamespace(
                tool_call=finalize_call,
                state={"messages": (AIMessage(content="", tool_calls=[finalize_call]),)},
            ),
            finalize_handler,
        )
        assert returned is rendered

        update = await middleware.abefore_model({}, None)
        assert update == {"jump_to": "end", "structured_response": proposal}

    run_async(run())


def test_full_graph_terminates_when_the_model_never_stops_calling_tools_after_finalize() -> None:
    """End-to-end regression for the live GraphRecursionError loop (R10 live defect #10).

    The scripted model finalizes and then requests ``read_contact_research_state`` forever —
    the exact live misbehavior. The runtime must end the graph itself with the engine's
    proposal: exactly one model round, zero post-finalization refusals, accepted receipt.
    """

    async def run() -> None:
        context = _context(ResearchSubjectType.CONTACT, EntityAgentRole.CONTACT)
        proposal = _proposal(context)

        async def finalize(value: str = "ok") -> str:
            del value
            return proposal.model_dump_json()

        base = _definition(context)
        definition = EntityResearchAgentDefinition(
            context=context,
            model_policy=base.model_policy,
            tools=tuple(
                binding
                if binding.name != "finalize_contact_research"
                else EntityResearchToolBinding(
                    tool=StructuredTool.from_function(
                        coroutine=finalize,
                        name="finalize_contact_research",
                        description="Governed test double rendering the engine proposal",
                        args_schema=ToolInput,
                    ),
                    version=1,
                )
                for binding in base.tools
            ),
            task_instruction=base.task_instruction,
        )
        model = ScriptedAgentChatModel(
            responses=(
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "finalize_contact_research", "args": {}, "id": "final-live"}
                    ],
                ),
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "read_contact_research_state", "args": {}, "id": "loop-live"}
                    ],
                ),
            ),
            repeat_last=True,
        )
        journal = Journal()
        finalizer = Finalizer()
        factory = EntityResearchAgentFactory(models=Models(model), journal=journal, guard=Guard())
        runtime = EntityResearchAgentRuntime(
            factory=factory,
            checkpointers=Checkpointers(),
            journal=journal,
            finalizer=finalizer,
        )
        outcome = await runtime.run(definition=definition)

        assert isinstance(outcome, EntityResearchAgentResult)
        assert outcome.proposal == proposal
        assert finalizer.proposals == [proposal]
        model_rounds = sum(
            1 for event in journal.events if event.kind is EntityAgentJournalEventKind.MODEL_STARTED
        )
        assert model_rounds == 1
        assert not any(
            event.payload.get("disposition") == "post_finalization_rejected"
            for event in journal.events
        )

    run_async(run())


def test_unparseable_finalize_render_falls_back_to_the_model_echo_path() -> None:
    """Proposal capture must fail open: refusals continue, the hook stays out of the way."""

    async def run() -> None:
        context = _context(ResearchSubjectType.ACCOUNT, EntityAgentRole.ACCOUNT)
        middleware = runtime_module._EntityResearchRuntimeMiddleware(
            definition=_definition(context),
            journal=Journal(),
            guard=Guard(),
            batches=BatchRecorder(),
        )
        finalize_call = {"name": "finalize_account_research", "args": {}, "id": "finalize-odd"}

        async def finalize_handler(_request: object) -> ToolMessage:
            return ToolMessage(
                content="not the rendered proposal",
                tool_call_id="finalize-odd",
                name="finalize_account_research",
            )

        await middleware.awrap_tool_call(
            SimpleNamespace(
                tool_call=finalize_call,
                state={"messages": (AIMessage(content="", tool_calls=[finalize_call]),)},
            ),
            finalize_handler,
        )
        assert middleware._finalization_proposed is True
        assert await middleware.abefore_model({}, None) is None

    run_async(run())


def test_an_empty_model_turn_is_refused_back_to_the_model_instead_of_failing_the_job() -> None:
    """Live regression: a maxed-out reasoning turn produced no tool call and no typed proposal.

    The graph ended with no ``structured_response`` and the run then failed the whole job
    validating ``None`` as a ``ResearchFinalizationProposal``. An empty turn is model output, not
    job integrity, so it comes back as the ordinary governed refusal and the model finalizes on
    its next turn.
    """

    async def run() -> None:
        context = _context(ResearchSubjectType.ACCOUNT, EntityAgentRole.ACCOUNT)
        proposal = _proposal(context)
        model = ScriptedAgentChatModel(
            responses=(
                AIMessage(content="(reasoning only; output budget exhausted)"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "ResearchFinalizationProposal",
                            "args": proposal.model_dump(mode="json"),
                            "id": "typed-final-after-repair",
                        }
                    ],
                ),
            )
        )
        journal = Journal()
        runtime = EntityResearchAgentRuntime(
            factory=EntityResearchAgentFactory(
                models=Models(model), journal=journal, guard=Guard()
            ),
            checkpointers=Checkpointers(),
            journal=journal,
            finalizer=Finalizer(),
        )

        outcome = await runtime.run(definition=_definition(context))

        assert isinstance(outcome, EntityResearchAgentResult)
        assert outcome.proposal == proposal
        assert outcome.finalization_receipt is not None
        assert not any(
            event.kind is EntityAgentJournalEventKind.EXECUTION_FAILED for event in journal.events
        )
        # The refusal is durable without a new journal kind: it rides the message history the next
        # model round records.
        rounds = [
            event
            for event in journal.events
            if event.kind is EntityAgentJournalEventKind.MODEL_STARTED
        ]
        assert len(rounds) == 2
        replayed = json.dumps(rounds[-1].payload)
        assert "governed_research_rejection" in replayed
        assert "empty_model_turn" in replayed

    run_async(run())


def test_a_run_that_never_proposes_fails_in_the_runtime_species_not_pydantic() -> None:
    """Repairs are bounded; exhausting them is a typed runtime refusal, never a ValidationError."""

    async def run() -> None:
        context = _context(ResearchSubjectType.ACCOUNT, EntityAgentRole.ACCOUNT)
        model = ScriptedAgentChatModel(
            responses=(AIMessage(content="(reasoning only, forever)"),), repeat_last=True
        )
        journal = Journal()
        runtime = EntityResearchAgentRuntime(
            factory=EntityResearchAgentFactory(
                models=Models(model), journal=journal, guard=Guard()
            ),
            checkpointers=Checkpointers(),
            journal=journal,
            finalizer=Finalizer(),
        )

        with pytest.raises(
            EntityResearchFinalizationRejected,
            match="without an admissible typed finalization proposal",
        ):
            await runtime.run(definition=_definition(context))

        failures = [
            event
            for event in journal.events
            if event.kind is EntityAgentJournalEventKind.EXECUTION_FAILED
        ]
        assert len(failures) == 1
        assert failures[0].payload["error_type"] == "EntityResearchFinalizationRejected"
        rounds = [
            event
            for event in journal.events
            if event.kind is EntityAgentJournalEventKind.MODEL_STARTED
        ]
        assert len(rounds) == runtime_module._MAX_EMPTY_TURN_REPAIRS + 1

    run_async(run())


def test_a_resumed_terminal_checkpoint_without_a_proposal_re_enters_the_model() -> None:
    """Live regression: two account jobs re-suspended forever on a proposal-less checkpoint.

    The crashed drive's last model turn spent its whole output budget on reasoning, so the graph
    ended at ``END`` with no ``structured_response``. Resuming that thread with no input replays the
    dead end without running a single node — no model round, so the in-turn empty-turn repair can
    never fire — and the drive fails identically on every resume. The resumed drive must re-enter
    the model with the same governed refusal, which is the only reachable repair across processes.
    """

    async def run() -> None:
        context = _context(ResearchSubjectType.ACCOUNT, EntityAgentRole.ACCOUNT)
        proposal = _proposal(context)
        checkpointers = Checkpointers()
        definition = _definition(context)

        crashed_journal = Journal()
        crashed = EntityResearchAgentRuntime(
            factory=EntityResearchAgentFactory(
                models=Models(
                    ScriptedAgentChatModel(
                        responses=(AIMessage(content="(reasoning only)"),), repeat_last=True
                    )
                ),
                journal=crashed_journal,
                guard=Guard(),
            ),
            checkpointers=checkpointers,
            journal=crashed_journal,
            finalizer=Finalizer(),
        )
        with pytest.raises(EntityResearchFinalizationRejected):
            await crashed.run(definition=definition)

        resumed_journal = Journal()
        resumed = EntityResearchAgentRuntime(
            factory=EntityResearchAgentFactory(
                models=Models(
                    ScriptedAgentChatModel(
                        responses=(
                            AIMessage(
                                content="",
                                tool_calls=[
                                    {
                                        "name": "ResearchFinalizationProposal",
                                        "args": proposal.model_dump(mode="json"),
                                        "id": "typed-final-after-resume",
                                    }
                                ],
                            ),
                        )
                    )
                ),
                journal=resumed_journal,
                guard=Guard(),
            ),
            checkpointers=checkpointers,
            journal=resumed_journal,
            finalizer=Finalizer(),
        )

        outcome = await resumed.run(definition=definition)

        assert isinstance(outcome, EntityResearchAgentResult)
        assert outcome.proposal == proposal
        assert not any(
            event.kind is EntityAgentJournalEventKind.EXECUTION_FAILED
            for event in resumed_journal.events
        )
        rounds = [
            event
            for event in resumed_journal.events
            if event.kind is EntityAgentJournalEventKind.MODEL_STARTED
        ]
        assert len(rounds) == 1
        replayed = json.dumps(rounds[0].payload)
        assert "empty_model_turn" in replayed

    run_async(run())


def test_a_refused_round_shape_returns_to_the_model_instead_of_killing_the_graph() -> None:
    """Live regression: a governed refusal of the model's *wave* suspended the whole job.

    ``authorize_parallel`` refusals are the ordinary repairable species — nothing is admitted,
    reserved or dispatched — but they were raised out of the model callback, where nothing caught
    them. Each call in the refused wave must come back to the model as its own error tool message.
    """

    class RefusingGuard(Guard):
        async def authorize_parallel(
            self,
            *,
            context: EntityResearchRuntimeContext,
            calls: Sequence[EntityResearchToolCall],
        ) -> None:
            await super().authorize_parallel(context=context, calls=calls)
            raise runtime_module.EntityResearchGovernedToolRefusal(
                "one model round cannot duplicate account provider work"
            )

    async def run() -> None:
        context = _context(ResearchSubjectType.ACCOUNT, EntityAgentRole.ACCOUNT)
        proposal = _proposal(context)
        model = ScriptedAgentChatModel(
            responses=(
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "read_research_result", "args": {"value": "a"}, "id": "read-a"},
                        {"name": "read_research_result", "args": {"value": "b"}, "id": "read-b"},
                    ],
                ),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "ResearchFinalizationProposal",
                            "args": proposal.model_dump(mode="json"),
                            "id": "typed-final-after-round-repair",
                        }
                    ],
                ),
            )
        )
        journal = Journal()
        runtime = EntityResearchAgentRuntime(
            factory=EntityResearchAgentFactory(
                models=Models(model), journal=journal, guard=RefusingGuard()
            ),
            checkpointers=Checkpointers(),
            journal=journal,
            finalizer=Finalizer(),
        )

        outcome = await runtime.run(definition=_definition(context))

        assert isinstance(outcome, EntityResearchAgentResult)
        assert outcome.proposal == proposal
        assert not any(
            event.kind is EntityAgentJournalEventKind.EXECUTION_FAILED for event in journal.events
        )
        refusals = [
            event
            for event in journal.events
            if event.kind is EntityAgentJournalEventKind.TOOL_FAILED
            and event.payload.get("disposition") == "round_admission_refused"
        ]
        assert len(refusals) == 2

    run_async(run())


def test_a_fourth_identical_read_is_refused_back_to_the_model() -> None:
    """Live regression (job 5d9dfe7b): a model read the same unchanged state until the graph
    recursion cap suspended the job. Identical consecutive read-only calls are answered normally
    three times, refused recoverably from the fourth, and any different call resets the streak.
    """

    async def run() -> None:
        context = _context(ResearchSubjectType.ACCOUNT, EntityAgentRole.ACCOUNT)
        definition = _definition(context)
        journal = Journal()
        middleware = runtime_module._EntityResearchRuntimeMiddleware(
            definition=definition,
            journal=journal,
            guard=Guard(),
            batches=BatchRecorder(),
        )

        answer = ToolMessage(content='{"state":"unchanged"}', tool_call_id="r", name="read")

        def read_request(call_id: str) -> SimpleNamespace:
            call = {"name": "read_account_research_state", "args": {}, "id": call_id}
            return SimpleNamespace(
                tool_call=call,
                state={"messages": (AIMessage(content="", tool_calls=[call]),)},
            )

        async def read_handler(_request: object) -> ToolMessage:
            return answer

        for attempt in range(3):
            returned = await middleware.awrap_tool_call(
                read_request(f"read-{attempt}"), read_handler
            )
            assert returned is answer, f"read {attempt} should be answered"

        refused = await middleware.awrap_tool_call(read_request("read-3"), read_handler)
        assert isinstance(refused, ToolMessage)
        assert refused.status == "error"
        assert "identical_read_loop" in str(refused.content)
        assert journal.events[-1].payload["disposition"] == "identical_read_loop_refused"

        # A different call resets the streak: the same read is answered again afterwards.
        different_call = {
            "name": "read_research_result",
            "args": {"result_ref": "research-result:x"},
            "id": "different-read",
        }

        async def different_handler(_request: object) -> ToolMessage:
            return ToolMessage(content="{}", tool_call_id="different-read", name="read")

        await middleware.awrap_tool_call(
            SimpleNamespace(
                tool_call=different_call,
                state={"messages": (AIMessage(content="", tool_calls=[different_call]),)},
            ),
            different_handler,
        )
        again = await middleware.awrap_tool_call(read_request("read-after-reset"), read_handler)
        assert again is answer

    run_async(run())
