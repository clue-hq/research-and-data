"""M8D R3 shared runtime for bounded account, contact, and facet research agents.

This is intentionally a different runtime from :class:`DeepAgentTurnRuntime`.  The user-facing
Head-of-ABM remains a Deep Agent; every entity research mind constructed here goes through the
smaller :func:`langchain.agents.create_agent` API with an exact semantic tool surface.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping, Sequence
from contextlib import AbstractAsyncContextManager, suppress
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Protocol, cast, runtime_checkable
from uuid import uuid4

from langchain.agents import create_agent
from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ToolCallLimitMiddleware,
    hook_config,
)
from langchain.agents.middleware.types import AgentMiddleware, ModelResponse
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    ToolMessage,
    message_to_dict,
)
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from pydantic import BaseModel, JsonValue, ValidationError

from clue_agents.entity_research_contracts import (
    EntityAgentJournalEventKind,
    EntityAgentRole,
    EntityResearchAgentDefinition,
    EntityResearchAgentResult,
    EntityResearchAgentSuspension,
    EntityResearchJournalEvent,
    EntityResearchRuntimeContext,
    EntityResearchToolCall,
    canonical_sha256,
)
from clue_agents.ports import AgentModelProvider
from clue_core.entity_research import ResearchFinalizationProposal, ResearchFinalizationReceipt


class EntityResearchRuntimeError(RuntimeError):
    """Base error for a fail-closed entity-agent execution."""


class EntityResearchAgentAborted(EntityResearchRuntimeError):
    pass


class EntityResearchGovernedToolRefusal(EntityResearchRuntimeError):
    """A guard/engine refusal of one tool call the model can repair — never a dead job.

    The R3 execution guard enforces model-facing rules (call sequencing against pending work,
    first-call bundling, scope shape). Violating one is model timing or arguments, not job
    integrity: the middleware returns this refusal to the model as an error tool message so the
    next turn can wait, re-read state, or fix the call. Role-specific authority errors subclass
    this marker; anything that must genuinely suspend keeps raising an ordinary exception.
    """

    def __init__(self, detail: str, *, code: str = "tool_authorization_refused") -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail

    def render(self) -> str:
        return json.dumps(
            {
                "error": "governed_research_rejection",
                "code": self.code,
                "detail": self.detail[:1_000],
                "recoverable": True,
                "guidance": (
                    "This tool call was refused without spending or suspending the job. Wait "
                    "for pending work to settle, re-read state, correct the request, or "
                    "finalize honestly with the remaining gap."
                ),
            },
            sort_keys=True,
            separators=(",", ":"),
        )


class _EntityResearchToolRejected(EntityResearchRuntimeError):
    """A model-authored tool request was rejected before producing governed work.

    LangGraph deliberately returns schema/structured-tool failures to the model as an error
    ``ToolMessage`` so the agent can correct its own arguments.  That message is not a successful
    research result and must never enter the R9 result join ledger.
    """


class EntityResearchExternalWait(EntityResearchRuntimeError):
    """Governed tool signal that external work is durable but not ready yet."""

    def __init__(self, *, wait_ref: str, current_state_sha256: str) -> None:
        if not wait_ref:
            raise ValueError("external wait reference must be non-empty")
        self.wait_ref = wait_ref
        self.current_state_sha256 = current_state_sha256
        super().__init__(f"entity research waits on {wait_ref}")


@dataclass(frozen=True)
class EntityResearchToolReplay:
    found: bool
    result: object | None = None


class EntityResearchFinalizationRejected(EntityResearchRuntimeError):
    pass


@dataclass(frozen=True)
class ActiveEntityResearchToolExecution:
    """Trusted task-local authority visible only while one governed handler executes.

    LangChain tool argument schemas deliberately exclude tenancy, job, target, budget, and
    causation identifiers.  R4 obtains those values from this engine-owned context after the R3
    journal and execution guard have admitted the call.  ``ContextVar`` preserves isolation when
    the agent runs independent tools concurrently in the same model round.
    """

    context: EntityResearchRuntimeContext
    call: EntityResearchToolCall
    journal_event_ref: str


_ACTIVE_TOOL_EXECUTION: ContextVar[ActiveEntityResearchToolExecution | None] = ContextVar(
    "active_entity_research_tool_execution",
    default=None,
)


def current_entity_research_tool_execution() -> ActiveEntityResearchToolExecution:
    """Return the exact admitted tool execution or fail outside a governed R3 invocation."""

    active = _ACTIVE_TOOL_EXECUTION.get()
    if active is None:
        raise EntityResearchRuntimeError(
            "entity research semantic tool was invoked outside the governed create_agent runtime"
        )
    return active


@runtime_checkable
class EntityResearchAgentJournal(Protocol):
    """Append-only durable construction/history journal implemented at composition root."""

    async def start(
        self,
        *,
        definition: EntityResearchAgentDefinition,
        context_sha256: str,
        resource_manifest_sha256: str,
        tool_manifest_sha256: str,
        system_prompt_sha256: str,
    ) -> None: ...

    async def append(self, event: EntityResearchJournalEvent) -> str: ...


@runtime_checkable
class EntityResearchExecutionGuard(Protocol):
    """Engine-owned budget/policy/yield authority consulted before tool handlers run.

    R3 owns the mandatory seam.  R4 supplies the concrete gate together with governed tools.  The
    ordering is deliberate: the middleware journals the call first, then consults this authority,
    and only then invokes a handler that may reserve or dispatch provider work.
    """

    async def authorize_parallel(
        self,
        *,
        context: EntityResearchRuntimeContext,
        calls: Sequence[EntityResearchToolCall],
    ) -> None: ...

    async def authorize_tool(
        self,
        *,
        context: EntityResearchRuntimeContext,
        call: EntityResearchToolCall,
        journal_event_ref: str,
    ) -> None: ...

    async def observe_tool_result(
        self,
        *,
        context: EntityResearchRuntimeContext,
        call: EntityResearchToolCall,
        result: object,
    ) -> None: ...


@runtime_checkable
class EntityResearchToolBatchCoordinator(Protocol):
    """Durable R9 admission and partial-result joining around one model tool batch."""

    async def admit(
        self,
        *,
        context: EntityResearchRuntimeContext,
        calls: Sequence[EntityResearchToolCall],
    ) -> None: ...

    async def replay(
        self,
        *,
        context: EntityResearchRuntimeContext,
        call: EntityResearchToolCall,
    ) -> EntityResearchToolReplay: ...

    async def completed(
        self,
        *,
        context: EntityResearchRuntimeContext,
        call: EntityResearchToolCall,
        result: object,
    ) -> None: ...

    async def waiting(
        self,
        *,
        context: EntityResearchRuntimeContext,
        call: EntityResearchToolCall,
        wait: EntityResearchExternalWait,
    ) -> EntityResearchExternalWait: ...

    async def failed(
        self,
        *,
        context: EntityResearchRuntimeContext,
        call: EntityResearchToolCall,
        error: BaseException,
    ) -> None: ...


class PassthroughEntityResearchToolBatchCoordinator(EntityResearchToolBatchCoordinator):
    """R3 fixture compatibility; production R6/R8 composition installs the durable R9 ledger."""

    async def admit(
        self,
        *,
        context: EntityResearchRuntimeContext,
        calls: Sequence[EntityResearchToolCall],
    ) -> None:
        del context, calls

    async def replay(
        self,
        *,
        context: EntityResearchRuntimeContext,
        call: EntityResearchToolCall,
    ) -> EntityResearchToolReplay:
        del context, call
        return EntityResearchToolReplay(found=False)

    async def completed(
        self,
        *,
        context: EntityResearchRuntimeContext,
        call: EntityResearchToolCall,
        result: object,
    ) -> None:
        del context, call, result

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
        del context, call, error


@runtime_checkable
class EntityResearchFinalizationEngine(Protocol):
    """Independently verify a typed proposal and return immutable terminal authority."""

    async def accept(
        self,
        *,
        context: EntityResearchRuntimeContext,
        proposal: ResearchFinalizationProposal,
    ) -> ResearchFinalizationReceipt: ...


@runtime_checkable
class EntityResearchCheckpointerFactory(Protocol):
    def open(
        self, thread_id: str
    ) -> AbstractAsyncContextManager[BaseCheckpointSaver[str], None]: ...


def _json_value(value: object) -> JsonValue:
    """Produce durable JSON without retaining process-only object representations."""

    if isinstance(value, BaseMessage):
        value = message_to_dict(value)
    elif isinstance(value, BaseModel):
        value = value.model_dump(mode="json", exclude_none=False)
    elif isinstance(value, tuple):
        value = list(value)
    encoded = json.dumps(
        value,
        default=lambda item: (
            message_to_dict(item)
            if isinstance(item, BaseMessage)
            else item.model_dump(mode="json", exclude_none=False)
            if isinstance(item, BaseModel)
            else str(item)
        ),
        ensure_ascii=False,
        allow_nan=False,
    )
    return cast(JsonValue, json.loads(encoded))


def _error_payload(error: BaseException) -> dict[str, JsonValue]:
    return {
        "error_type": type(error).__name__,
        "message": str(error)[:2000],
    }


def _resolved_system_prompt(definition: EntityResearchAgentDefinition) -> str:
    resources = definition.context.resources
    profile_section = (
        f"<profile ref={json.dumps(resources.profile.ref)} "
        f"version={json.dumps(resources.profile.version)} "
        f"sha256={json.dumps(resources.profile.sha256)}>\n"
        f"{resources.profile.body}\n</profile>"
    )
    skill_sections = "\n\n".join(
        f"<skill ref={json.dumps(skill.ref)} version={json.dumps(skill.version)} "
        f"sha256={json.dumps(skill.sha256)}>\n{skill.body}\n</skill>"
        for skill in resources.skills
    )
    exact_context = json.dumps(
        definition.exact_model_context(),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    sections = [
        profile_section,
        resources.prompt.body.rstrip(),
        (
            "The following runtime context is immutable engine authority. Never widen an entity, "
            "field, source, channel, policy, budget, or facet beyond it.\n"
            f"<entity_research_context>{exact_context}</entity_research_context>"
        ),
    ]
    if skill_sections:
        sections.insert(2, skill_sections)
    return "\n\n".join(sections)


_FINALIZE_TOOL_NAMES = ("finalize_account_research", "finalize_contact_research")

#: How many times one execution refuses an empty model turn back to the model before it stops
#: paying for repairs. Deliberately small: the stop policy's model-round and runtime budgets are
#: the real ceiling, and a model that cannot produce a tool call or a proposal in three tries is
#: not going to on the fourth.
_MAX_EMPTY_TURN_REPAIRS = 3

#: State-reading engine tools that buy nothing and change nothing. Mirrors the api layer's
#: read-only set (``clue_api.account_entity_research._READ_ONLY_TOOL_NAMES``); duplicated here
#: because the runtime may not import the api package (dependency direction).
_STATE_READ_TOOL_NAMES = frozenset(
    {
        "read_account_research_state",
        "inspect_account_evidence",
        "read_research_result",
        "read_evidence",
        "read_contact_research_state",
        "inspect_contact_evidence",
    }
)

#: Consecutive identical read-only calls tolerated before the runtime refuses the next one back
#: to the model. Reading the same unchanged state cannot make progress; observed live (job
#: 5d9dfe7b): a model called ``read_account_research_state`` back-to-back until the graph
#: recursion cap suspended the job. The refusal is recoverable — any *different* call resets it.
_MAX_IDENTICAL_READS = 3


def _read_loop_refusal(tool_name: str, repeats: int) -> EntityResearchGovernedToolRefusal:
    return EntityResearchGovernedToolRefusal(
        f"{tool_name} was already answered identically {repeats} times in a row and the state "
        "has not changed; do not read it again — research an outstanding field/source pair, "
        "assess coverage, or finalize honestly with the remaining gap",
        code="identical_read_loop",
    )


def _empty_turn_refusal() -> EntityResearchGovernedToolRefusal:
    """The one refusal text an empty model turn gets, in-turn and across a process resume."""

    return EntityResearchGovernedToolRefusal(
        "the turn produced neither a governed tool call nor the typed finalization proposal; "
        "call a tool, or finalize honestly with the remaining gap",
        code="empty_model_turn",
    )


def _tool_message_text(result: Any) -> str:
    content = getattr(result, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, Sequence):
        return "".join(
            str(block.get("text", ""))
            for block in content
            if isinstance(block, Mapping) and block.get("type") == "text"
        )
    return ""


def _engine_finalization_proposal(result: Any) -> ResearchFinalizationProposal | None:
    """Recover the engine's typed proposal from the finalize tool's rendered result.

    The finalize tools render the durably stored proposal verbatim, so a successful parse is
    the engine's own contract object — not model output. Returns None on any mismatch so the
    caller can fall back to the model-echo path instead of failing a run at its success moment.
    """

    if not isinstance(result, ToolMessage) or result.status == "error":
        return None
    try:
        return ResearchFinalizationProposal.model_validate(json.loads(_tool_message_text(result)))
    except Exception:  # noqa: BLE001 - defensive fallback to the model-echo path
        return None


class _EntityResearchRuntimeMiddleware(AgentMiddleware[Any, Any, Any]):
    """Exact tool-surface, history, causation-order, parallel, and guard enforcement."""

    def __init__(
        self,
        *,
        definition: EntityResearchAgentDefinition,
        journal: EntityResearchAgentJournal,
        guard: EntityResearchExecutionGuard,
        batches: EntityResearchToolBatchCoordinator | None = None,
    ) -> None:
        self._definition = definition
        self._context = definition.context
        self._journal = journal
        self._guard = guard
        self._batches = batches or PassthroughEntityResearchToolBatchCoordinator()
        self._bindings = {binding.name: binding for binding in definition.tools}
        self._versions = {name: binding.version for name, binding in self._bindings.items()}
        self._allowed = frozenset(self._versions)
        self._structured_tool_name = ResearchFinalizationProposal.__name__
        self._admission_lock = asyncio.Lock()
        self._admitted_batches: set[str] = set()
        # Set once the engine's finalize tool has returned its admissible proposal. From that
        # point the only legitimate model output is the typed structured response; every further
        # governed tool call is refused deterministically (prompt guidance alone did not stop
        # live finalization looping). Process-local by design: a cold resume re-runs the finalize
        # tool idempotently, and the zero-yield stop policy remains the outer backstop.
        self._finalization_proposed = False
        # The engine proposal captured from the finalize tool result. When present, abefore_model
        # ends the graph deterministically with it instead of waiting for the model to echo it —
        # a live contact run looped on post-finalization refusals until the recursion limit.
        self._engine_proposal: ResearchFinalizationProposal | None = None
        # How many empty model turns this execution has already refused (see `aafter_model`).
        # Process-local like `_finalization_proposed`: a cold resume re-reads the persisted
        # messages and simply gets its own repair budget.
        self._empty_turn_repairs = 0
        self._last_read_signature: tuple[str, str] | None = None
        self._identical_reads = 0

    def _call(self, raw: Mapping[str, Any]) -> EntityResearchToolCall:
        name = str(raw.get("name", ""))
        if name not in self._versions:
            raise EntityResearchRuntimeError(
                f"tool {name!r} is outside the exact {self._context.role.value} allowlist"
            )
        raw_arguments = raw.get("args", {})
        if not isinstance(raw_arguments, dict):
            raise EntityResearchRuntimeError("entity research tool arguments must be an object")
        arguments = cast(dict[str, JsonValue], _json_value(raw_arguments))
        return EntityResearchToolCall(
            tool_call_id=str(raw.get("id", "")),
            tool_name=name,
            tool_version=self._versions[name],
            tool_input_sha256=canonical_sha256(arguments),
            arguments=arguments,
            provider_family=self._bindings[name].provider_family,
            budget_reservation_cents=self._bindings[name].budget_reservation_cents,
            provider_rate_limit_ref=self._bindings[name].provider_rate_limit_ref,
            provider_concurrency_limit=self._bindings[name].provider_concurrency_limit,
        )

    def _event(
        self,
        kind: EntityAgentJournalEventKind,
        *,
        payload: dict[str, JsonValue],
        call: EntityResearchToolCall | None = None,
    ) -> EntityResearchJournalEvent:
        return EntityResearchJournalEvent(
            event_id=uuid4(),
            agent_execution_id=self._context.agent_execution_id,
            agent_turn_id=self._context.agent_turn_id,
            kind=kind,
            payload=payload,
            tool_call_id=call.tool_call_id if call is not None else None,
            tool_name=call.tool_name if call is not None else None,
            tool_version=call.tool_version if call is not None else None,
            tool_input_sha256=call.tool_input_sha256 if call is not None else None,
        )

    async def _admit_batch(self, calls: Sequence[EntityResearchToolCall]) -> None:
        """Admit one exact model wave once per runtime, including tool-node cold resumes.

        A LangGraph checkpoint taken while a tool waits resumes directly at the tool node. The
        replacement middleware therefore does not observe the original model callback. Rebuild
        that persisted model wave from tool-node state and run the same guard/admission path before
        any handler dispatch. The lock prevents concurrently resumed siblings from independently
        widening or partially admitting the wave.
        """

        batch_sha = canonical_sha256(
            [call.model_dump(mode="json", exclude_none=False) for call in calls]
        )
        async with self._admission_lock:
            if batch_sha in self._admitted_batches:
                return
            if len(calls) > 1:
                await self._guard.authorize_parallel(
                    context=self._context,
                    calls=tuple(calls),
                )
            await self._batches.admit(context=self._context, calls=tuple(calls))
            self._admitted_batches.add(batch_sha)

    def _persisted_tool_wave(
        self,
        request: Any,
        current: EntityResearchToolCall,
    ) -> tuple[EntityResearchToolCall, ...]:
        for message in reversed(tuple(self._state_messages(request.state))):
            if not isinstance(message, AIMessage):
                continue
            calls = tuple(
                self._call(raw)
                for raw in message.tool_calls
                if str(raw.get("name", "")) in self._allowed
            )
            if any(call.tool_call_id == current.tool_call_id for call in calls):
                return calls
        return (current,)

    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        names = {str(getattr(tool, "name", "")) for tool in request.tools}
        missing = self._allowed - names
        unexpected = names - self._allowed - {self._structured_tool_name}
        if missing or unexpected:
            raise EntityResearchRuntimeError(
                "constructed model tool surface differs from exact allowlist: "
                f"missing={sorted(missing)} unexpected={sorted(unexpected)}"
            )
        zero_yield = self._consecutive_zero_yield(request.messages)
        if zero_yield >= self._context.stop_policy.max_consecutive_zero_yield:
            raise EntityResearchRuntimeError(
                "entity research stopped after the configured consecutive zero-yield limit"
            )
        await self._journal.append(
            self._event(
                EntityAgentJournalEventKind.MODEL_STARTED,
                payload={
                    "messages": _json_value(tuple(request.messages)),
                    "tool_names": _json_value(sorted(names)),
                },
            )
        )
        response = await handler(request)
        result_messages = (
            tuple(response.result) if isinstance(response, ModelResponse) else (response,)
        )
        await self._journal.append(
            self._event(
                EntityAgentJournalEventKind.MODEL_COMPLETED,
                payload={"messages": _json_value(result_messages)},
            )
        )
        calls: list[EntityResearchToolCall] = []
        for message in result_messages:
            if not isinstance(message, AIMessage):
                continue
            for raw_call in message.tool_calls:
                if str(raw_call.get("name", "")) in self._allowed:
                    calls.append(self._call(raw_call))
        if len(calls) > self._context.stop_policy.max_parallel_tools:
            raise EntityResearchRuntimeError("model proposed more parallel tools than admitted")
        if calls:
            # A refused *round shape* (duplicated work in one wave, a dependent tool travelling
            # with siblings, overlapping fields) is model output, not job integrity: nothing was
            # admitted, reserved or dispatched. Raising here killed the graph and suspended the
            # job. Let the response through instead — admission is deterministic over the wave, so
            # each call re-runs it in ``awrap_tool_call`` and comes back to the model as its own
            # error tool message, which is the repair path the refusal species promises.
            with suppress(EntityResearchGovernedToolRefusal):
                await self._admit_batch(calls)
        return response

    @staticmethod
    def _consecutive_zero_yield(messages: Sequence[BaseMessage]) -> int:
        """Count persisted governed results, so the limit survives checkpoint/resume."""

        count = 0
        for message in reversed(messages):
            # Every tool-result round is preceded by the model's AI tool-call message.  Skip that
            # transport envelope so the counter spans durable rounds and process resumes instead
            # of resetting after every single call.
            if isinstance(message, AIMessage) and message.tool_calls:
                continue
            if not isinstance(message, ToolMessage):
                if count:
                    break
                continue
            content = message.content
            try:
                payload = json.loads(content) if isinstance(content, str) else content
            except json.JSONDecodeError:
                if count:
                    break
                continue
            if not isinstance(payload, Mapping) or not {
                "tool_request_ref",
                "results",
                "current_state_sha256",
                "yield_count",
            }.issubset(payload):
                if count:
                    break
                continue
            yield_count = payload.get("yield_count")
            if not isinstance(yield_count, int) or yield_count > 0:
                break
            count += 1
        return count

    def _note_finalization_result(self, call: EntityResearchToolCall, result: Any) -> None:
        """Arm deterministic termination once the engine has returned its finalize proposal.

        Covers both the fresh dispatch path and the cold-resume settled-result replay path,
        so a resumed post-finalization checkpoint terminates instead of re-looping.
        """

        if call.tool_name not in _FINALIZE_TOOL_NAMES:
            return
        if isinstance(result, ToolMessage) and result.status == "error":
            return
        self._finalization_proposed = True
        proposal = _engine_finalization_proposal(result)
        if proposal is not None:
            self._engine_proposal = proposal

    @hook_config(can_jump_to=["end"])
    async def abefore_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        """End the graph deterministically once the engine's finalize proposal exists.

        After finalize succeeds, the model's only remaining job is to echo the engine proposal
        through the typed response format — a formality a live contact run failed to perform,
        looping on post-finalization refusals until GraphRecursionError. The runtime performs
        the echo itself from the engine's own stored proposal; the outer run() still verifies
        subject/entity bounds and the independent finalization-engine receipt, so no authority
        moves to this shortcut. When proposal capture failed, fall through to the model-echo
        path (the post-finalization refusals below remain the guard).
        """

        if not self._finalization_proposed or self._engine_proposal is None:
            return None
        return {"jump_to": "end", "structured_response": self._engine_proposal}

    @hook_config(can_jump_to=["model"])
    async def aafter_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        """Refuse an empty model turn back to the model instead of ending with no proposal.

        A turn that calls no governed tool and emits no typed proposal ends the graph with no
        ``structured_response`` at all. Live, a run whose model spent its whole 16k output budget
        on reasoning ended exactly that way, and the run then failed the job validating ``None``
        as the finalization proposal. An empty turn is model output, not job integrity, so it is
        refused in the ordinary governed species — the model gets a bounded number of attempts to
        call a tool or finalize honestly. The refusal is durable without a new journal kind: it is
        an ordinary message, so the next ``model_started`` event records it with the rest of the
        history.
        """

        if self._finalization_proposed or self._structured_response(state) is not None:
            return None
        last = next(
            (
                message
                for message in reversed(tuple(self._state_messages(state)))
                if isinstance(message, AIMessage)
            ),
            None,
        )
        if last is None or last.tool_calls:
            return None
        if self._empty_turn_repairs >= _MAX_EMPTY_TURN_REPAIRS:
            return None
        self._empty_turn_repairs += 1
        return {
            "messages": [HumanMessage(content=_empty_turn_refusal().render())],
            "jump_to": "model",
        }

    @staticmethod
    def _state_messages(state: Any) -> Sequence[BaseMessage]:
        if isinstance(state, Mapping):
            return cast(Sequence[BaseMessage], state.get("messages", ()))
        return cast(Sequence[BaseMessage], getattr(state, "messages", ()))

    @staticmethod
    def _structured_response(state: Any) -> object | None:
        if isinstance(state, Mapping):
            return state.get("structured_response")
        return getattr(state, "structured_response", None)

    async def awrap_tool_call(self, request: Any, handler: Any) -> Any:
        call = self._call(cast(dict[str, Any], request.tool_call))
        if call.tool_name in _STATE_READ_TOOL_NAMES:
            signature = (
                call.tool_name,
                hashlib.sha256(json.dumps(call.arguments, sort_keys=True).encode()).hexdigest(),
            )
            if signature == self._last_read_signature:
                self._identical_reads += 1
            else:
                self._last_read_signature = signature
                self._identical_reads = 1
            if self._identical_reads > _MAX_IDENTICAL_READS:
                read_refusal = _read_loop_refusal(call.tool_name, self._identical_reads - 1)
                await self._journal.append(
                    self._event(
                        EntityAgentJournalEventKind.TOOL_FAILED,
                        call=call,
                        payload={
                            **_error_payload(read_refusal),
                            "disposition": "identical_read_loop_refused",
                        },
                    )
                )
                return ToolMessage(
                    content=read_refusal.render(),
                    status="error",
                    tool_call_id=call.tool_call_id,
                    name=call.tool_name,
                )
        else:
            self._last_read_signature = None
            self._identical_reads = 0
        if self._finalization_proposed:
            refusal = ToolMessage(
                content=(
                    '{"error":"finalization_already_proposed","detail":"the engine already '
                    "returned the only admissible finalization proposal; emit it unchanged "
                    'through the typed response format and stop"}'
                ),
                status="error",
                tool_call_id=call.tool_call_id,
                name=call.tool_name,
            )
            await self._journal.append(
                self._event(
                    EntityAgentJournalEventKind.TOOL_FAILED,
                    call=call,
                    payload={
                        "error_type": "EntityResearchToolRejected",
                        "error": "tool call refused after accepted finalization proposal",
                        "disposition": "post_finalization_rejected",
                    },
                )
            )
            return refusal
        event_ref = await self._journal.append(
            self._event(
                EntityAgentJournalEventKind.TOOL_STARTED,
                call=call,
                payload={"arguments": call.arguments},
            )
        )
        try:
            try:
                await self._admit_batch(self._persisted_tool_wave(request, call))
            except EntityResearchGovernedToolRefusal as refusal:
                # The wave was refused on its shape, so no batch member exists to settle and no
                # provider work was reserved or dispatched. Journal the refusal and hand it to the
                # model as this call's result; ``self._batches.failed`` is deliberately not called
                # (it would look for the member this refusal is the reason there is none of).
                await self._journal.append(
                    self._event(
                        EntityAgentJournalEventKind.TOOL_FAILED,
                        call=call,
                        payload={
                            **_error_payload(refusal),
                            "disposition": "round_admission_refused",
                        },
                    )
                )
                return ToolMessage(
                    content=refusal.render(),
                    status="error",
                    tool_call_id=call.tool_call_id,
                    name=call.tool_name,
                )
            try:
                await self._guard.authorize_tool(
                    context=self._context,
                    call=call,
                    journal_event_ref=event_ref,
                )
            except EntityResearchGovernedToolRefusal as refusal:
                await self._batches.failed(context=self._context, call=call, error=refusal)
                await self._journal.append(
                    self._event(
                        EntityAgentJournalEventKind.TOOL_FAILED,
                        call=call,
                        payload={
                            **_error_payload(refusal),
                            "disposition": "authorization_refused",
                        },
                    )
                )
                return ToolMessage(
                    content=refusal.render(),
                    status="error",
                    tool_call_id=call.tool_call_id,
                    name=call.tool_name,
                )
            replay = await self._batches.replay(context=self._context, call=call)
            if replay.found:
                result = replay.result
                await self._guard.observe_tool_result(
                    context=self._context,
                    call=call,
                    result=result,
                )
                self._note_finalization_result(call, result)
                await self._journal.append(
                    self._event(
                        EntityAgentJournalEventKind.TOOL_COMPLETED,
                        call=call,
                        payload={
                            "disposition": "joined_settled_result",
                            "result": _json_value(result),
                        },
                    )
                )
                return result
            token = _ACTIVE_TOOL_EXECUTION.set(
                ActiveEntityResearchToolExecution(
                    context=self._context,
                    call=call,
                    journal_event_ref=event_ref,
                )
            )
            try:
                result = await handler(request)
            finally:
                _ACTIVE_TOOL_EXECUTION.reset(token)
            if isinstance(result, ToolMessage) and result.status == "error":
                rejection = _EntityResearchToolRejected(str(result.content)[:2000])
                await self._batches.failed(
                    context=self._context,
                    call=call,
                    error=rejection,
                )
                await self._journal.append(
                    self._event(
                        EntityAgentJournalEventKind.TOOL_FAILED,
                        call=call,
                        payload={
                            **_error_payload(rejection),
                            "disposition": "model_request_rejected",
                        },
                    )
                )
                return result
            await self._batches.completed(context=self._context, call=call, result=result)
            await self._guard.observe_tool_result(
                context=self._context,
                call=call,
                result=result,
            )
            self._note_finalization_result(call, result)
        except EntityResearchExternalWait as wait:
            batch_wait = await self._batches.waiting(
                context=self._context,
                call=call,
                wait=wait,
            )
            await self._journal.append(
                self._event(
                    EntityAgentJournalEventKind.TOOL_COMPLETED,
                    call=call,
                    payload={
                        "disposition": "waiting_external",
                        "wait_ref": batch_wait.wait_ref,
                        "member_wait_ref": wait.wait_ref,
                        "current_state_sha256": batch_wait.current_state_sha256,
                    },
                )
            )
            raise batch_wait from wait
        except BaseException as error:
            # Journal the real cause *first*. Settling the batch can itself fail (a wave that never
            # reached admission has no member to settle), and when it did, its own error replaced
            # the original and skipped this record entirely — a live job's true failure was
            # unknowable afterwards. Settlement failure is recorded, never substituted.
            await self._journal.append(
                self._event(
                    EntityAgentJournalEventKind.TOOL_FAILED,
                    call=call,
                    payload=_error_payload(error),
                )
            )
            try:
                await self._batches.failed(context=self._context, call=call, error=error)
            except Exception as settlement_error:
                await self._journal.append(
                    self._event(
                        EntityAgentJournalEventKind.TOOL_FAILED,
                        call=call,
                        payload={
                            **_error_payload(settlement_error),
                            "disposition": "batch_settlement_failed",
                        },
                    )
                )
            raise
        await self._journal.append(
            self._event(
                EntityAgentJournalEventKind.TOOL_COMPLETED,
                call=call,
                payload={"result": _json_value(result)},
            )
        )
        return result


class EntityResearchAgentFactory:
    """Construct every account/contact/facet unit through exactly one LangChain factory."""

    def __init__(
        self,
        *,
        models: AgentModelProvider,
        journal: EntityResearchAgentJournal,
        guard: EntityResearchExecutionGuard,
        batches: EntityResearchToolBatchCoordinator | None = None,
    ) -> None:
        self._models = models
        self._journal = journal
        self._guard = guard
        self._batches = batches or PassthroughEntityResearchToolBatchCoordinator()

    def create(
        self,
        *,
        definition: EntityResearchAgentDefinition,
        checkpointer: BaseCheckpointSaver[str],
    ) -> Any:
        policy = definition.model_policy
        model = self._models.build(
            model_id=policy.model_id,
            timeout_s=policy.timeout_s,
            max_retries=policy.max_retries,
            max_output_tokens=policy.max_output_tokens,
            temperature=policy.temperature,
        )
        stop = definition.context.stop_policy
        middleware: tuple[AgentMiddleware[Any, Any, Any], ...] = (
            _EntityResearchRuntimeMiddleware(
                definition=definition,
                journal=self._journal,
                guard=self._guard,
                batches=self._batches,
            ),
            ModelCallLimitMiddleware(run_limit=stop.max_model_rounds, exit_behavior="error"),
            ToolCallLimitMiddleware(run_limit=stop.max_tool_calls, exit_behavior="error"),
        )
        return create_agent(
            model=model,
            tools=[binding.tool for binding in definition.tools],
            system_prompt=_resolved_system_prompt(definition),
            middleware=middleware,
            response_format=ResearchFinalizationProposal,
            checkpointer=checkpointer,
            name=f"clue-entity-{definition.context.role.value}",
        )


class EntityResearchAgentRuntime:
    """Run/resume one exact unit and accept only independently verified finalization."""

    def __init__(
        self,
        *,
        factory: EntityResearchAgentFactory,
        checkpointers: EntityResearchCheckpointerFactory,
        journal: EntityResearchAgentJournal,
        finalizer: EntityResearchFinalizationEngine,
    ) -> None:
        self._factory = factory
        self._checkpointers = checkpointers
        self._journal = journal
        self._finalizer = finalizer

    def _event(
        self,
        context: EntityResearchRuntimeContext,
        kind: EntityAgentJournalEventKind,
        payload: dict[str, JsonValue],
    ) -> EntityResearchJournalEvent:
        return EntityResearchJournalEvent(
            event_id=uuid4(),
            agent_execution_id=context.agent_execution_id,
            agent_turn_id=context.agent_turn_id,
            kind=kind,
            payload=payload,
        )

    async def _invoke(
        self,
        graph: Any,
        *,
        definition: EntityResearchAgentDefinition,
        config: RunnableConfig,
        stop_requested: asyncio.Event | None,
        lease_lost: asyncio.Event | None,
    ) -> dict[str, Any]:
        snapshot = await graph.aget_state(config)
        resumed = bool(snapshot.values)
        if resumed and not snapshot.next and snapshot.values.get("structured_response") is not None:
            return cast(dict[str, Any], snapshot.values)
        graph_input: dict[str, Any] | None
        if not resumed:
            graph_input = {"messages": [HumanMessage(content=definition.task_instruction)]}
        elif not snapshot.next:
            # The persisted graph is already at END with no proposal: the crashed drive's last
            # model turn spent its whole output budget on reasoning and returned neither a tool
            # call nor the typed response. Resuming such a thread with no input replays that dead
            # end in microseconds — no node runs, so the middleware's empty-turn repair can never
            # fire and every resume fails identically (live: two account jobs re-suspended on
            # exactly this). Re-enter with the same governed refusal the in-turn repair uses, so a
            # fresh process gives the model its bounded chance to call a tool or finalize honestly.
            graph_input = {"messages": [HumanMessage(content=_empty_turn_refusal().render())]}
        else:
            graph_input = None
        invocation = asyncio.create_task(graph.ainvoke(graph_input, config=config))
        stop_task = (
            asyncio.create_task(stop_requested.wait()) if stop_requested is not None else None
        )
        lease_task = asyncio.create_task(lease_lost.wait()) if lease_lost is not None else None
        sentinels = {task for task in (stop_task, lease_task) if task is not None}
        try:
            done, _ = await asyncio.wait(
                {invocation, *sentinels},
                timeout=definition.context.stop_policy.max_runtime_s,
                return_when=asyncio.FIRST_COMPLETED,
            )
            # A simultaneous graph result and stop/lease signal is not terminal authority. The
            # R2 fence will reject a late write too, but the runtime should never offer one after
            # it already knows its execution authority was revoked.
            if done.intersection(sentinels):
                invocation.cancel()
                await asyncio.gather(invocation, return_exceptions=True)
                raise EntityResearchAgentAborted("entity research agent lost stop/lease authority")
            if invocation in done:
                return cast(dict[str, Any], await invocation)
            invocation.cancel()
            await asyncio.gather(invocation, return_exceptions=True)
            if not done:
                raise TimeoutError("entity research agent exceeded its runtime limit")
            raise EntityResearchRuntimeError("entity research invocation stopped unexpectedly")
        finally:
            for task in sentinels:
                task.cancel()
            if sentinels:
                await asyncio.gather(*sentinels, return_exceptions=True)

    async def run(
        self,
        *,
        definition: EntityResearchAgentDefinition,
        stop_requested: asyncio.Event | None = None,
        lease_lost: asyncio.Event | None = None,
    ) -> EntityResearchAgentResult | EntityResearchAgentSuspension:
        context = definition.context
        context_payload = definition.exact_model_context()
        resource_manifest = context.resources.manifest()
        tool_manifest = definition.tool_manifest()
        system_prompt = _resolved_system_prompt(definition)
        context_sha256 = canonical_sha256(context_payload)
        resource_manifest_sha256 = canonical_sha256(resource_manifest)
        tool_manifest_sha256 = canonical_sha256(tool_manifest)
        system_prompt_sha256 = hashlib.sha256(system_prompt.encode()).hexdigest()
        await self._journal.start(
            definition=definition,
            context_sha256=context_sha256,
            resource_manifest_sha256=resource_manifest_sha256,
            tool_manifest_sha256=tool_manifest_sha256,
            system_prompt_sha256=system_prompt_sha256,
        )
        await self._journal.append(
            self._event(
                context,
                EntityAgentJournalEventKind.EXECUTION_STARTED,
                {
                    "context_sha256": context_sha256,
                    "resource_manifest_sha256": resource_manifest_sha256,
                    "tool_manifest_sha256": tool_manifest_sha256,
                    "system_prompt_sha256": system_prompt_sha256,
                },
            )
        )
        config = cast(
            RunnableConfig,
            {
                "configurable": {
                    "thread_id": context.effective_checkpoint_thread_id,
                },
                "recursion_limit": (
                    context.stop_policy.max_model_rounds * 2
                    + context.stop_policy.max_tool_calls
                    + 4
                ),
            },
        )
        try:
            suspension: EntityResearchAgentSuspension | None = None
            async with self._checkpointers.open(
                context.effective_checkpoint_thread_id
            ) as checkpointer:
                graph = self._factory.create(
                    definition=definition,
                    checkpointer=checkpointer,
                )
                try:
                    result = await self._invoke(
                        graph,
                        definition=definition,
                        config=config,
                        stop_requested=stop_requested,
                        lease_lost=lease_lost,
                    )
                except EntityResearchExternalWait as wait:
                    snapshot = await graph.aget_state(config)
                    configurable = dict(snapshot.config.get("configurable", {}))
                    checkpoint_id = str(configurable.get("checkpoint_id", ""))
                    if not checkpoint_id:
                        raise EntityResearchRuntimeError(
                            "external wait produced no durable checkpoint identity"
                        ) from wait
                    checkpoint_payload = {
                        "configurable": _json_value(configurable),
                        "next": _json_value(snapshot.next),
                        "values": _json_value(snapshot.values),
                    }
                    suspension = EntityResearchAgentSuspension(
                        role=context.role,
                        wait_ref=wait.wait_ref,
                        checkpoint_ref=(
                            f"langgraph:{context.effective_checkpoint_thread_id}:"
                            f"{configurable.get('checkpoint_ns', '')}:{checkpoint_id}"
                        ),
                        checkpoint_sha256=canonical_sha256(checkpoint_payload),
                        current_state_sha256=wait.current_state_sha256,
                    )
            if suspension is not None:
                await self._journal.append(
                    self._event(
                        context,
                        EntityAgentJournalEventKind.EXECUTION_SUSPENDED,
                        {
                            "wait_ref": suspension.wait_ref,
                            "checkpoint_ref": suspension.checkpoint_ref,
                            "checkpoint_sha256": suspension.checkpoint_sha256,
                            "current_state_sha256": suspension.current_state_sha256,
                        },
                    )
                )
                return suspension
            raw_proposal = result.get("structured_response")
            if isinstance(raw_proposal, ResearchFinalizationProposal):
                proposal = raw_proposal
            else:
                try:
                    proposal = ResearchFinalizationProposal.model_validate(raw_proposal)
                except ValidationError as invalid:
                    # The graph ended without an admissible typed proposal — the middleware's
                    # bounded empty-turn repairs are the recovery path, and reaching here means
                    # they were exhausted. Fail in the runtime's own species with the shape that
                    # was actually returned, not as a raw pydantic ValidationError.
                    raise EntityResearchFinalizationRejected(
                        "entity research ended without an admissible typed finalization proposal "
                        f"(received {type(raw_proposal).__name__})"
                    ) from invalid
            if (
                proposal.subject_type is not context.authorization.subject_type
                or proposal.target_entity_id != context.authorization.subject_entity_id
            ):
                raise EntityResearchFinalizationRejected(
                    "typed finalization widens the authorized target"
                )
            await self._journal.append(
                self._event(
                    context,
                    EntityAgentJournalEventKind.FINALIZATION_PROPOSED,
                    {"proposal": _json_value(proposal)},
                )
            )
            if context.role is EntityAgentRole.FACET:
                await self._journal.append(
                    self._event(
                        context,
                        EntityAgentJournalEventKind.FACET_COMPLETED,
                        {"proposal_id": str(proposal.proposal_id)},
                    )
                )
                return EntityResearchAgentResult(role=context.role, proposal=proposal)
            receipt = await self._finalizer.accept(context=context, proposal=proposal)
            if receipt.proposal != proposal:
                raise EntityResearchFinalizationRejected(
                    "engine finalization receipt differs from the typed proposal"
                )
            await self._journal.append(
                self._event(
                    context,
                    EntityAgentJournalEventKind.FINALIZATION_ACCEPTED,
                    {"receipt": _json_value(receipt)},
                )
            )
            return EntityResearchAgentResult(
                role=context.role,
                proposal=proposal,
                finalization_receipt=receipt,
            )
        except (asyncio.CancelledError, EntityResearchAgentAborted):
            await self._journal.append(
                self._event(context, EntityAgentJournalEventKind.EXECUTION_CANCELLED, {})
            )
            raise
        except BaseException as error:
            await self._journal.append(
                self._event(
                    context,
                    EntityAgentJournalEventKind.EXECUTION_FAILED,
                    _error_payload(error),
                )
            )
            raise


__all__ = [
    "EntityResearchAgentAborted",
    "EntityResearchAgentFactory",
    "EntityResearchAgentJournal",
    "EntityResearchAgentRuntime",
    "EntityResearchCheckpointerFactory",
    "EntityResearchExecutionGuard",
    "EntityResearchExternalWait",
    "EntityResearchFinalizationEngine",
    "EntityResearchFinalizationRejected",
    "EntityResearchRuntimeError",
    "EntityResearchToolBatchCoordinator",
    "EntityResearchToolReplay",
    "PassthroughEntityResearchToolBatchCoordinator",
]
