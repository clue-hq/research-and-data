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
        middleware = runtime_module._EntityResearchRuntimeMiddleware(  # type: ignore[attr-defined]
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
