"""Real deepagents turn loop with governed tools and mandatory honest finalization."""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Callable, Collection, Mapping, Sequence
from typing import Any, Literal, cast

from deepagents import create_deep_agent
from langchain.agents.middleware.types import AgentMiddleware, ModelResponse
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool
from langgraph.types import Command
from pydantic import BaseModel

from clue_agents.compaction import (
    CompactionSettings,
    build_compaction_middleware,
    register_governed_harness_profile,
)
from clue_agents.contracts import AgentConstitution, AgentTurnRequest
from clue_agents.execution import (
    MAX_RUNTIME_MODEL_ROUNDS,
    AgentExecutionStatus,
    AgentTurnOutcome,
    GovernedOperationReceipt,
)
from clue_agents.model_session import ModelSessionAffinity
from clue_agents.ports import (
    AgentExecutionAdapter,
    AgentModelProvider,
    AssembledAgentContext,
)
from clue_agents.registry import ResolvedAgentProfile
from clue_agents.state import ClueDeepAgentState
from clue_agents.tool_recovery import ToolRepairRoundsMiddleware
from clue_core.provider_failures import classify_exception, failure_code
from clue_obs import get_logger
from clue_obs.langfuse import flag_trace
from clue_obs.sentry import warn as sentry_warn

__all__ = [
    "ORDINARY_FINALIZE_REPAIRS",
    "DeepAgentTurnRuntime",
    "ExactAgentToolSurfaceMiddleware",
    "TurnBudgetMiddleware",
]

log = get_logger("clue_agents.runtime")

register_governed_harness_profile()


def _fallback_compaction(model_id: str) -> CompactionSettings:
    """A runtime given no thresholds still compacts, at the fixed fallback (ruling 2026-09-29)."""
    del model_id
    return CompactionSettings.fallback()


_FRAMEWORK_TOOL_NAMES = frozenset(
    {
        "write_todos",
        "ls",
        "read_file",
        "write_file",
        "edit_file",
        "glob",
        "grep",
        # deepagents' manual compaction (founder ruling 2026-09-29): every agent may compact.
        "compact_conversation",
    }
)

_FINALIZE_TOOL_NAME = "finalize_turn"

# One corrective round trip per independent rejector. A finalization is refused by two unrelated
# authorities — the shape contract (``ModelFinalizeRequest``) and the surface's ``CompletionGuard``
# — and a turn can legitimately trip both once each while converging: the model fixes the shape,
# then learns from the guard that it must route the human's input first. With a single shared
# repair the second, honest attempt never happened and the turn died ``missing_finalize`` mid-
# repair. A model that repeatedly proposes an invalid terminal shape may still be receiving
# incomplete feedback. Bound retries to prevent a loop;
# exhausting this allowance is not evidence of model intent or of failed research.
_MAX_FINALIZE_REPAIRS = 2
#: The allowance an ordinary (non-research) turn gets, continued or not.
ORDINARY_FINALIZE_REPAIRS = _MAX_FINALIZE_REPAIRS


#: LangGraph supersteps one model round costs today: the turn-budget and tool-repair
#: ``before_model`` hooks, the model call, deepagents' to-do ``after_model`` hook, and the tool
#: node. ``test_turn_budget.py`` proves an agent really reaches its configured rounds, so a new hook
#: that costs another step fails that test instead of silently shrinking the budget.
_SUPERSTEPS_PER_ROUND = 5


def superstep_ceiling(max_rounds: int) -> int:
    """LangGraph's ``recursion_limit`` for a round budget: a runaway-loop fuse, never the limit.

    The round limit itself is :class:`TurnBudgetMiddleware`, which winds the turn up and ends it
    through ``finalize_turn``. This fuse sits above it with one spare step a round (for a future
    hook) plus headroom for the graph's entry/exit nodes and the finalize repairs, so a working
    agent never reaches it; only a loop inside the graph itself would.
    """

    return max_rounds * (_SUPERSTEPS_PER_ROUND + 1) + 10


# The status contract itself is stated once, on the finalize tool's own description, which the
# model is holding when it reads this. Restating it here would be a second copy free to drift.
_FINALIZE_CONTRACT_HELP = (
    "Execution finalization was not accepted; previously saved tool outputs remain stored. "
    "Correct the specific file, field, or unfinished stage named above, using other tools "
    "if needed, then retry finalize_turn. Changing user_message cannot repair a saved file. "
    "Do not repeat already successful research or writes."
)

_FINALIZE_REPAIRS_EXHAUSTED = (
    "Execution finalization was not accepted and its repair allowance is exhausted. "
    "Previously saved tool outputs remain stored for recovery."
)


def _tool_name(tool: BaseTool | dict[str, Any]) -> str:
    if isinstance(tool, BaseTool):
        return tool.name
    name = tool.get("name")
    if not isinstance(name, str):
        function = tool.get("function")
        name = function.get("name") if isinstance(function, dict) else None
    if not isinstance(name, str):
        raise TypeError("agent model tool has no stable name")
    return name


class ExactAgentToolSurfaceMiddleware(AgentMiddleware[Any, Any, Any]):
    """Make framework and platform absence a runtime enforcement mechanism.

    Deep Agents 0.6 installs a general-purpose ``task`` subagent by default. The platform never
    exposes that bypass: C6.6 delegation uses ``delegate_specialist``, whose implementation
    compiles a durable C5 delegation operation before any child wakes. This middleware also fails
    construction-on-first-call if a backend unexpectedly contributes execution or another
    undeclared tool.
    """

    def __init__(
        self,
        *,
        profile: ResolvedAgentProfile,
        effective_governed_tool_names: Collection[str] | None = None,
        max_finalize_repairs: int = _MAX_FINALIZE_REPAIRS,
    ) -> None:
        self._max_finalize_repairs = max_finalize_repairs
        self._profile = profile
        declared = frozenset(
            {
                *(pin.name for pin in profile.profile.tools),
                _FINALIZE_TOOL_NAME,
                *(("delegate_specialist",) if profile.profile.delegation_roles else ()),
            }
        )
        effective = (
            declared
            if effective_governed_tool_names is None
            else frozenset(effective_governed_tool_names)
        )
        undeclared = sorted(effective - declared)
        if undeclared:
            raise ValueError(f"effective governed tools are absent from the profile: {undeclared}")
        if _FINALIZE_TOOL_NAME not in effective:
            raise ValueError("the effective governed surface must include finalize_turn")
        self._allowed = effective | _FRAMEWORK_TOOL_NAMES
        # Per-turn state: one middleware instance is constructed per ``DeepAgentTurnRuntime.run``.
        self._finalize_rejections = 0

    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        by_name = {_tool_name(tool): tool for tool in request.tools}
        missing = sorted(self._allowed - set(by_name))
        if missing:
            raise RuntimeError(f"resolved agent tools are missing at model call: {missing}")
        unexpected = sorted(set(by_name) - self._allowed - {"task"})
        if unexpected:
            raise RuntimeError(f"undeclared runtime tools were installed: {unexpected}")
        if "execute" in by_name:
            raise RuntimeError("agent workspace unexpectedly exposes code execution")
        base_prompt = request.system_message.text if request.system_message is not None else ""
        suffix = self._profile.generated_resource_map
        if base_prompt.rstrip().endswith(suffix):
            final_prompt = base_prompt
        else:
            final_prompt = f"{base_prompt.rstrip()}\n\n{suffix}"
        filtered = [by_name[name] for name in sorted(self._allowed)]
        governed_request = request.override(
            tools=filtered,
            # Every platform turn has a mandatory ``finalize_turn`` authority. Requiring a tool
            # call asks compatible providers to keep acting until they invoke a governed tool.
            tool_choice="required",
            system_message=SystemMessage(content=final_prompt),
        )
        response = await handler(governed_request)
        if not isinstance(response, ModelResponse) or len(response.result) != 1:
            return response
        message = response.result[0]
        if not isinstance(message, AIMessage) or message.tool_calls or not message.text.strip():
            return response

        # Some OpenAI-compatible gateways/models may still return a plain-text stop despite
        # ``tool_choice=required``. Give that exact proposed response one bounded finalize-only
        # recovery call. Authority is not bypassed: the model must still invoke the real governed
        # finalizer, and a second non-tool stop remains ``missing_finalize`` downstream.
        return await handler(
            governed_request.override(
                messages=[
                    *governed_request.messages,
                    message,
                    HumanMessage(
                        content=(
                            "Your previous response is not committed because it did not call "
                            "finalize_turn. Call finalize_turn now and no other tool. Preserve "
                            "the previous response exactly as user_message. Use awaiting_input "
                            "when it asks the human for information or confirmation and include "
                            "one next_actions item describing that requested response; otherwise "
                            "use completed. Do not add new content."
                        )
                    ),
                ],
                tools=[by_name["finalize_turn"]],
                tool_choice="finalize_turn",
            )
        )

    async def awrap_tool_call(self, request: Any, handler: Any) -> Any:
        name = str(request.tool_call.get("name", ""))
        if name not in self._allowed:
            return ToolMessage(
                content=(f"Tool {name!r} is structurally unavailable to this exact agent profile."),
                tool_call_id=str(request.tool_call.get("id", "unavailable-tool")),
                status="error",
            )
        if name != _FINALIZE_TOOL_NAME:
            return await handler(request)
        return await self._bounded_finalize(request, handler)

    async def _bounded_finalize(self, request: Any, handler: Any) -> Any:
        """Return refused finalizations for bounded correction, then fail the turn closed.

        ``finalize_turn`` is ``return_direct``: the agent graph ends as soon as the tool node
        produces its message, which is exactly right for a *committed* finalization and exactly
        wrong for a *refused* one — the model never saw the rejection, so the turn died as
        ``missing_finalize`` with no feedback (the live Stage-0 defect). A refusal therefore
        clears ``return_direct`` for that one call so the corrected proposal can come back, and
        restores it before every attempt so a commit still ends the turn immediately.

        Bounding is by omission, not by a new terminal path: once the repair budget is spent the
        tool stays ``return_direct``, so the final refusal ends the graph the way it always did
        and the runtime reports the same stable ``missing_finalize``. Nothing was committed, so
        that remains the honest code.
        """

        tool = request.tool
        if isinstance(tool, BaseTool):
            tool.return_direct = True
        tool_call_id = str(request.tool_call.get("id", _FINALIZE_TOOL_NAME))
        try:
            latest = next(
                (
                    m
                    for m in reversed(request.state.get("messages", ()))
                    if isinstance(m, AIMessage)
                ),
                None,
            )
            if latest is not None and len(latest.tool_calls) > 1:
                raise ValueError(
                    "Call finalize_turn alone after reading the completed tool batch results. "
                    "Other calls in this batch are still allowed to finish."
                )
            result = await handler(request)
        except ValueError as error:
            # Argument-schema violations are already turned into an error ``ToolMessage`` by the
            # tool node; a refusal raised *inside* the finalize tool (envelope construction, the
            # required-output check, the completion guard) would otherwise crash the graph unseen.
            # Both are the same thing to the model: its proposed terminal shape was not accepted.
            #
            # The catch is deliberately the whole ``ValueError`` family, not just pydantic's
            # ``ValidationError``: the platform's own finalize guards raise plain ``ValueError``
            # and their messages are precisely what the model needs in order to produce an honest
            # terminal shape. The cost is that a guard violation now reaches the operator as
            # ``missing_finalize`` rather than as its own exception, so every swallowed error is
            # logged here with the exception type and message that would otherwise have surfaced.
            log.warning(
                "agent.finalize_refused",
                tool_call_id=tool_call_id,
                error_type=type(error).__name__,
                error=str(error),
                rejection=self._finalize_rejections + 1,
            )
            result = ToolMessage(
                content=str(error),
                name=_FINALIZE_TOOL_NAME,
                tool_call_id=tool_call_id,
                status="error",
            )
        if not (isinstance(result, ToolMessage) and result.status == "error"):
            return result

        self._finalize_rejections += 1
        exhausted = self._finalize_rejections > self._max_finalize_repairs
        if not exhausted and isinstance(tool, BaseTool):
            tool.return_direct = False
        guidance = _FINALIZE_REPAIRS_EXHAUSTED if exhausted else _FINALIZE_CONTRACT_HELP
        return ToolMessage(
            content=f"{result.content}\n\n{guidance}",
            name=_FINALIZE_TOOL_NAME,
            tool_call_id=tool_call_id,
            status="error",
        )


#: How many rounds (or, near a time limit, how many model calls) the agent is warned for before
#: only ``finalize_turn`` is offered (founder ruling 2026-09-27).
WRAP_UP_WARNING_ROUNDS = 3
#: Near a time limit the warning starts this many seconds before it — at most a quarter of the
#: turn's whole limit, so a short turn is not wrapping up from its first round.
WRAP_UP_WARNING_S = 180.0
#: Below this much time left (at most a tenth of the limit), a model call is finalize-only
#: whatever the warnings did.
_FINALIZE_ONLY_S = 60.0

WrapUpStatus = Literal["blocked", "awaiting_input"]


class TurnBudgetMiddleware(AgentMiddleware[Any, Any, Any]):
    """End a turn through ``finalize_turn`` before its round or time limit, not by a crash.

    Rounds are counted in graph state (keyed to the turn, as ``ToolRepairRoundsMiddleware`` does)
    so a resumed turn keeps its count. Round ``N`` is the whole budget: the finalize-only round
    comes ``_MAX_FINALIZE_REPAIRS`` rounds before it, so a refused finalization can still be
    repaired inside the budget and nothing outside it (the research allowance, the graph fuse) is
    ever the thing that stops a working agent. The three rounds before that carry a notice.

    With a time limit the same happens by the clock: three warned model calls once about three
    minutes remain, then finalize-only (or at once, with under a minute left). A short turn scales
    both windows down (a quarter and a tenth of its limit).

    Every notice is appended to that model call's messages only; nothing is written to the
    thread's history, so a replay reads exactly what was committed.
    """

    state_schema = ClueDeepAgentState

    def __init__(
        self,
        *,
        max_rounds: int,
        wrap_up_status: WrapUpStatus,
        max_runtime_s: float | None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_rounds = max_rounds
        self._finalize_round = max(1, max_rounds - _MAX_FINALIZE_REPAIRS)
        self._status = wrap_up_status
        self._clock = clock
        self._deadline = None if max_runtime_s is None else clock() + max_runtime_s
        self._warn_s = 0.0 if max_runtime_s is None else min(WRAP_UP_WARNING_S, max_runtime_s / 4)
        self._final_s = 0.0 if max_runtime_s is None else min(_FINALIZE_ONLY_S, max_runtime_s / 10)
        self._time_warnings = 0
        self._announced: set[str] = set()

    async def abefore_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        del runtime
        turn = str(state.get("turn_id"))
        rounds = state.get("turn_budget_rounds", 0) if state.get("turn_budget_turn") == turn else 0
        return {"turn_budget_turn": turn, "turn_budget_rounds": rounds + 1}

    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        round_number = int(request.state.get("turn_budget_rounds", 1))
        remaining_s = None if self._deadline is None else self._deadline - self._clock()
        reason: Literal["round", "time"] | None = None
        finalize_only = False
        notice = ""
        if round_number >= self._finalize_round:
            reason, finalize_only = "round", True
        elif remaining_s is not None and remaining_s <= self._warn_s:
            reason = "time"
            finalize_only = (
                self._time_warnings >= WRAP_UP_WARNING_ROUNDS or remaining_s <= self._final_s
            )
            if not finalize_only:
                self._time_warnings += 1
                minutes = max(1, round(remaining_s / 60))
                notice = f"about {minutes} minute{'s' if minutes != 1 else ''} of its time limit"
        elif round_number >= self._finalize_round - WRAP_UP_WARNING_ROUNDS:
            reason = "round"
            left = self._finalize_round - round_number
            notice = f"{left} model round{'s' if left != 1 else ''}"
        if reason is None:
            return await handler(request)

        self._record(
            reason=reason,
            finalize_only=finalize_only,
            request=request,
            round_number=round_number,
            remaining_s=remaining_s,
        )
        if finalize_only:
            finalize = [tool for tool in request.tools if _tool_name(tool) == _FINALIZE_TOOL_NAME]
            return await handler(
                request.override(
                    messages=[*request.messages, HumanMessage(content=self._reached(reason))],
                    tools=finalize,
                    tool_choice=_FINALIZE_TOOL_NAME,
                )
            )
        return await handler(
            request.override(
                messages=[*request.messages, HumanMessage(content=self._warning(notice))]
            )
        )

    def _unfinished(self) -> str:
        advice = (
            f'If the work is not finished, finalize with status "{self._status}": say in '
            "user_message what you completed, and list the remaining work in next_actions."
        )
        if self._status == "awaiting_input":
            advice += ' Tell the user they can reply "continue" to keep going.'
        return advice

    def _warning(self, notice: str) -> str:
        return (
            f"Platform notice (not from the user): this turn has {notice} left before only "
            "finalize_turn is offered. Use them to save anything you have not saved yet, then "
            f"call finalize_turn. {self._unfinished()}"
        )

    def _reached(self, reason: str) -> str:
        return (
            f"Platform notice (not from the user): this turn has reached its {reason} limit. "
            "Only finalize_turn is available now. Call it once, on its own. "
            f"{self._unfinished()}"
        )

    def _record(
        self,
        *,
        reason: str,
        finalize_only: bool,
        request: Any,
        round_number: int,
        remaining_s: float | None,
    ) -> None:
        """Log and tag each stage once per turn: the first warning, then the limit itself."""
        stage = f"{reason}_budget_reached" if finalize_only else "wrap_up_warned"
        if stage in self._announced:
            return
        self._announced.add(stage)
        constitution = request.state.get("constitution")
        fields: dict[str, object] = {
            "turn_id": str(request.state.get("turn_id")),
            "execution_id": str(getattr(constitution, "execution_id", "")),
            "workspace_id": str(getattr(constitution, "workspace_id", "")),
            "profile_ref": str(getattr(constitution, "profile_ref", "")),
            "reason": reason,
            "round": round_number,
            "max_rounds": self._max_rounds,
            "remaining_s": None if remaining_s is None else round(remaining_s, 1),
            "wrap_up_status": self._status,
        }
        log.warning(f"agent.{stage}", **fields)
        flag_trace(
            f"agent.{stage}",
            tags=(stage,),
            status_message=(
                f"{reason} limit reached; finalize-only, expected status {self._status}"
                if finalize_only
                else f"{reason} limit near; agent warned to wrap up"
            ),
            metadata=fields,
        )


def _error_code(exc: BaseException) -> str:
    # A provider that refused or failed is named for what it did, not for the SDK class that
    # carried the news: the transcript, the turn row and the incident record read the same code.
    failure = classify_exception("openrouter", exc)
    if failure is not None:
        return failure_code(failure)
    value = re.sub(r"(?<!^)(?=[A-Z])", "_", type(exc).__name__).lower()
    return value or "agent_turn_failed"


class DeepAgentTurnRuntime:
    """Construct and run one real deepagent around injected, governed boundaries.

    Normal framework termination has no authority.  The adapter must report a committed
    finalization reference after the graph returns; otherwise this runtime fails the turn.
    """

    def __init__(
        self,
        *,
        models: AgentModelProvider,
        execution: AgentExecutionAdapter,
        max_runtime_s: float | None = 300.0,
        max_rounds: int = 24,
        middleware: Sequence[AgentMiddleware[Any, Any, Any]] = (),
        wrap_up_status: WrapUpStatus = "blocked",
        long_turn_alert_s: float | None = None,
        continuation_config: Mapping[str, Any] | None = None,
        compaction_for: Callable[[str], CompactionSettings] | None = None,
        max_finalize_repairs: int | None = None,
    ) -> None:
        if max_runtime_s is not None and max_runtime_s <= 0:
            raise ValueError("agent runtime timeout must be positive")
        if not 1 <= max_rounds <= MAX_RUNTIME_MODEL_ROUNDS:
            raise ValueError(
                f"agent round ceiling must be between 1 and {MAX_RUNTIME_MODEL_ROUNDS}"
            )
        if long_turn_alert_s is not None and long_turn_alert_s <= 0:
            raise ValueError("a long-turn alert threshold must be positive (None disables it)")
        self._continuation_config = continuation_config
        # A continued research conversation gets a wider finalize-repair allowance; a caller that
        # continues an ordinary conversation (the Head of ABM) passes the ordinary one.
        self._max_finalize_repairs = (
            max_finalize_repairs
            if max_finalize_repairs is not None
            else 10
            if continuation_config
            else _MAX_FINALIZE_REPAIRS
        )
        # Every agent compacts (founder ruling 2026-09-29), sized per run from the model it builds.
        self._compaction_for = compaction_for or _fallback_compaction
        self._models = models
        self._middleware = tuple(middleware)
        self._execution = execution
        self._max_runtime_s = max_runtime_s
        self._max_rounds = max_rounds
        self._wrap_up_status: WrapUpStatus = wrap_up_status
        self._long_turn_alert_s = long_turn_alert_s
        self._recursion_limit = superstep_ceiling(max_rounds)

    async def run(
        self,
        *,
        request: AgentTurnRequest,
        resolved_profile: ResolvedAgentProfile,
        context: AssembledAgentContext,
        backend: object,
        governed_tools: Sequence[BaseTool],
        callbacks: Sequence[BaseCallbackHandler] = (),
    ) -> AgentTurnOutcome:
        watchdog = (
            asyncio.create_task(self._alert_when_long(request, resolved_profile))
            if self._long_turn_alert_s is not None
            else None
        )
        try:
            return await self._run_turn(
                request=request,
                resolved_profile=resolved_profile,
                context=context,
                backend=backend,
                governed_tools=governed_tools,
                callbacks=callbacks,
            )
        finally:
            if watchdog is not None:
                watchdog.cancel()

    async def _alert_when_long(
        self, request: AgentTurnRequest, resolved_profile: ResolvedAgentProfile
    ) -> None:
        """Say so, once, when a turn is still running past the alert threshold; never stop it."""
        assert self._long_turn_alert_s is not None
        await asyncio.sleep(self._long_turn_alert_s)
        constitution = request.constitution
        role = resolved_profile.profile.role.value
        minutes = round(self._long_turn_alert_s / 60)
        fields: dict[str, object] = {
            "role": role,
            "turn_id": str(request.turn_id),
            "execution_id": str(constitution.execution_id),
            "workspace_id": str(constitution.workspace_id),
            "profile_ref": constitution.profile_ref,
            "running_minutes": minutes,
        }
        log.warning("agent.long_turn", **fields)
        flag_trace(
            "agent.long_turn",
            tags=("long_turn",),
            status_message=f"turn still running after {minutes} minutes",
            metadata=fields,
        )
        sentry_warn(
            f"{role} turn still running after {minutes} minutes",
            # One Sentry issue per long turn, so each one raises its own alert.
            fingerprint=("agent-long-turn", str(constitution.execution_id), str(request.turn_id)),
            tags={key: str(value) for key, value in fields.items()},
        )

    def _build_model(self, profile: Any) -> Any:
        return self._models.build(
            model_id=profile.model.model_id,
            timeout_s=profile.model.timeout_s,
            max_retries=profile.model.max_retries,
            max_output_tokens=profile.model.max_output_tokens,
            temperature=profile.model.temperature,
            # Names the role on the governed call so the per-role
            # ``<ROLE>_AGENT_MODEL_EFFORT`` environment override (and span/usage
            # attribution) applies to this turn's model.
            role=profile.role.value,
        )

    async def _compaction(self, profile: Any) -> CompactionSettings:
        """The model's compaction thresholds, read in a thread: ``compaction_for`` may fetch the
        model catalogue over the network, and a blocking read on the event loop stops every other
        task on it — on 2026-10-05 a fleet worker stopped renewing its leases for 105 s."""
        return await asyncio.to_thread(self._compaction_for, profile.model.model_id)

    def _build_graph(
        self,
        *,
        model: Any,
        resolved_profile: ResolvedAgentProfile,
        backend: object,
        governed_tools: Sequence[BaseTool],
        checkpointer: Any,
        compaction: CompactionSettings,
        session_id: str,
    ) -> Any:
        profile = resolved_profile.profile
        summariser, compact_tool = build_compaction_middleware(model, backend, compaction)
        return create_deep_agent(
            model=model,
            tools=list(governed_tools),
            system_prompt=resolved_profile.prompt_body,
            middleware=(
                # One routing key per agent conversation, so its prompt cache stays warm.
                ModelSessionAffinity(session_id),
                ToolRepairRoundsMiddleware(),
                ExactAgentToolSurfaceMiddleware(
                    profile=resolved_profile,
                    # Some reviewed profile capabilities are constitution-dependent.  For
                    # example, selected-product readers are intentionally omitted unless the
                    # turn carries an exact Product-KB pin.  The factory has already applied
                    # that trusted narrowing; the runtime must enforce the resulting surface,
                    # not incorrectly require every capability listed by the reusable role
                    # profile.
                    effective_governed_tool_names={_tool_name(tool) for tool in governed_tools},
                    max_finalize_repairs=self._max_finalize_repairs,
                ),
                # Inside the exact-surface check, which insists every granted tool is present:
                # only after it may the last rounds be narrowed to finalize_turn.
                TurnBudgetMiddleware(
                    max_rounds=self._max_rounds,
                    wrap_up_status=self._wrap_up_status,
                    max_runtime_s=self._max_runtime_s,
                ),
                *self._middleware,
                # Our summariser replaces deepagents' default (removed for governed models by
                # the harness profile registered below), plus ``compact_conversation``.
                summariser,
                compact_tool,
            ),
            backend=backend,  # type: ignore[arg-type]
            checkpointer=checkpointer,
            state_schema=ClueDeepAgentState,
            name=f"clue-{profile.role.value}",
        )

    async def saved_conversation_is_settled(
        self,
        *,
        request: AgentTurnRequest,
        resolved_profile: ResolvedAgentProfile,
        backend: object,
        governed_tools: Sequence[BaseTool],
    ) -> bool:
        """Whether ``continuation_config`` names a saved conversation this runtime can continue.

        Read through the same graph a turn runs, so "settled" means exactly what the run checks:
        the saved state has messages and no pending node. Nothing is written; a caller asks this
        before it assembles a continued turn, because a turn cannot change its opening context
        once assembled (one receipt per turn).
        """
        if self._continuation_config is None:
            raise ValueError("no continuation to check")
        async with self._execution.checkpointer(
            execution_id=request.constitution.execution_id
        ) as checkpointer:
            graph = self._build_graph(
                model=self._build_model(resolved_profile.profile),
                resolved_profile=resolved_profile,
                backend=backend,
                governed_tools=governed_tools,
                checkpointer=checkpointer,
                compaction=await self._compaction(resolved_profile.profile),
                session_id=str(request.constitution.execution_id),
            )
            previous = await graph.aget_state(cast(RunnableConfig, dict(self._continuation_config)))
        return bool(previous.values.get("messages")) and not previous.next

    async def _run_turn(
        self,
        *,
        request: AgentTurnRequest,
        resolved_profile: ResolvedAgentProfile,
        context: AssembledAgentContext,
        backend: object,
        governed_tools: Sequence[BaseTool],
        callbacks: Sequence[BaseCallbackHandler] = (),
    ) -> AgentTurnOutcome:
        constitution = request.constitution
        profile = resolved_profile.profile
        if constitution.profile_ref != resolved_profile.profile_ref:
            raise ValueError("turn constitution differs from the resolved exact profile")
        if context.manifest.execution_id != constitution.execution_id:
            raise ValueError("context bundle belongs to another execution")

        model = self._build_model(profile)
        async with self._execution.checkpointer(
            execution_id=constitution.execution_id
        ) as checkpointer:
            graph = self._build_graph(
                model=model,
                resolved_profile=resolved_profile,
                backend=backend,
                governed_tools=governed_tools,
                checkpointer=checkpointer,
                compaction=await self._compaction(profile),
                session_id=str(constitution.execution_id),
            )
            state: Any = {
                "messages": cast(Any, list(context.messages)),
                "constitution": constitution,
                "context_manifest": context.manifest,
                "turn_id": request.turn_id,
            }
            # A trusted caller may continue a settled research conversation in a new,
            # independently journaled turn. Never copy terminal authority or repair counters.
            # Read through the graph so DeltaChannel and native compaction are reconstructed.
            if self._continuation_config is not None:
                destination = {
                    "configurable": {
                        "thread_id": str(constitution.execution_id),
                        "checkpoint_ns": "",
                    }
                }
                current = await graph.aget_state(cast(RunnableConfig, destination))
                if current.values:
                    # Redelivery continues the existing turn, without reinserting its history.
                    state = None
                else:
                    previous = await graph.aget_state(
                        cast(RunnableConfig, dict(self._continuation_config))
                    )
                    if not previous.values.get("messages") or previous.next:
                        raise ValueError("Continuation requires a settled saved conversation")
                    saved_constitution = previous.values.get("constitution")
                    if isinstance(saved_constitution, BaseModel):
                        saved_constitution = saved_constitution.model_dump(warnings=False)
                    source = AgentConstitution.model_validate_json(
                        json.dumps(saved_constitution, default=str)
                    )
                    if (source.workspace_id, source.project_id, source.profile_ref) != (
                        constitution.workspace_id,
                        constitution.project_id,
                        constitution.profile_ref,
                    ):
                        raise ValueError(
                            "Continuation crosses workspace, project or pinned profile"
                        )
                    assert state is not None
                    state["messages"] = [*previous.values["messages"], *state["messages"]]
                    if "_summarization_event" in previous.values:
                        state["_summarization_event"] = previous.values["_summarization_event"]
                    # Native private compaction state is excluded from graph input. Seed it
                    # with the public state-update API, then resume the new checkpoint.
                    await graph.aupdate_state(
                        cast(RunnableConfig, destination), state, as_node="__start__"
                    )
                    state = Command(
                        update={"_summarization_event": previous.values.get("_summarization_event")}
                    )
            try:
                result = await asyncio.wait_for(
                    graph.ainvoke(
                        cast(Any, state),
                        config=cast(
                            RunnableConfig,
                            {
                                "configurable": {
                                    "thread_id": str(constitution.execution_id),
                                    "checkpoint_ns": f"agent-turn:{request.turn_id}",
                                },
                                "callbacks": list(callbacks),
                                # Nested governed children inherit callbacks, but monetary
                                # receipts belong only to the execution making this dispatch.
                                "metadata": {"agent_execution_id": str(constitution.execution_id)},
                                "recursion_limit": self._recursion_limit,
                            },
                        ),
                    ),
                    timeout=self._max_runtime_s,
                )
            except TimeoutError:
                await self._execution.recover(execution_id=constitution.execution_id)
                return AgentTurnOutcome(
                    turn_id=request.turn_id,
                    execution_id=constitution.execution_id,
                    status=AgentExecutionStatus.FAILED,
                    failure_code="agent_timeout",
                )
            except asyncio.CancelledError:
                await self._execution.recover(execution_id=constitution.execution_id)
                raise
            except BaseException as exc:
                await self._execution.recover(execution_id=constitution.execution_id)
                log.error(
                    "agent.runtime_failed",
                    error_type=type(exc).__name__,
                    error=str(exc),
                    exc_info=True,
                )
                return AgentTurnOutcome(
                    turn_id=request.turn_id,
                    execution_id=constitution.execution_id,
                    status=AgentExecutionStatus.FAILED,
                    failure_code=_error_code(exc),
                )

        recovered = await self._execution.recover(execution_id=constitution.execution_id)
        finalization_ref = recovered.get("finalization_ref")
        status = recovered.get("finalization_status")
        receipts_value = recovered.get("operation_receipts", ())
        receipts = (
            tuple(receipts_value)
            if isinstance(receipts_value, Sequence)
            and all(isinstance(item, GovernedOperationReceipt) for item in receipts_value)
            else ()
        )
        if finalization_ref is None or status not in {
            AgentExecutionStatus.COMPLETED.value,
            AgentExecutionStatus.AWAITING_INPUT.value,
            AgentExecutionStatus.BLOCKED.value,
        }:
            # The model may have emitted a polished answer, but without the trusted finalize tool
            # it is only an uncommitted framework stop.
            del result
            return AgentTurnOutcome(
                turn_id=request.turn_id,
                execution_id=constitution.execution_id,
                status=AgentExecutionStatus.FAILED,
                operation_receipts=receipts,
                failure_code="missing_finalize",
            )
        from clue_agents.contracts import ArtifactRef

        if not isinstance(finalization_ref, ArtifactRef):
            raise TypeError("execution adapter returned a malformed finalization reference")
        return AgentTurnOutcome(
            turn_id=request.turn_id,
            execution_id=constitution.execution_id,
            status=AgentExecutionStatus(status),
            finalization_ref=finalization_ref,
            operation_receipts=receipts,
        )
