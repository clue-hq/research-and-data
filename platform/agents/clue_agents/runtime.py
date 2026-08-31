"""Real deepagents turn loop with governed tools and mandatory honest finalization."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Collection, Sequence
from typing import Any, cast

from deepagents import create_deep_agent
from langchain.agents.middleware.types import AgentMiddleware, ModelResponse
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool

from clue_agents.contracts import AgentTurnRequest
from clue_agents.execution import (
    AgentExecutionStatus,
    AgentTurnOutcome,
    GovernedOperationReceipt,
)
from clue_agents.ports import (
    AgentExecutionAdapter,
    AgentModelProvider,
    AssembledAgentContext,
)
from clue_agents.registry import ResolvedAgentProfile
from clue_agents.state import ClueDeepAgentState
from clue_obs import get_logger

__all__ = ["DeepAgentTurnRuntime", "ExactAgentToolSurfaceMiddleware"]

log = get_logger("clue_agents.runtime")

_FRAMEWORK_TOOL_NAMES = frozenset(
    {
        "write_todos",
        "ls",
        "read_file",
        "write_file",
        "edit_file",
        "glob",
        "grep",
    }
)

_FINALIZE_TOOL_NAME = "finalize_turn"

# One corrective round trip per independent rejector. A finalization is refused by two unrelated
# authorities — the shape contract (``ModelFinalizeRequest``) and the surface's ``CompletionGuard``
# — and a turn can legitimately trip both once each while converging: the model fixes the shape,
# then learns from the guard that it must route the human's input first. With a single shared
# repair the second, honest attempt never happened and the turn died ``missing_finalize`` mid-
# repair. A model that proposes a dishonest terminal shape a *third* time has not misread the
# schema; it is refusing the contract, and the turn must die rather than loop.
_MAX_FINALIZE_REPAIRS = 2

# The status contract itself is stated once, on the finalize tool's own description, which the
# model is holding when it reads this. Restating it here would be a second copy free to drift.
_FINALIZE_CONTRACT_HELP = (
    "Nothing was committed and this turn is not finished. Call finalize_turn again with a "
    "terminal shape that satisfies the status contract in its description. Keep the content "
    "you already wrote; change only what the error above names."
)

_FINALIZE_REPAIRS_EXHAUSTED = (
    "Nothing was committed and no further finalize attempt will be accepted for this turn."
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
    ) -> None:
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
        """Give a refused finalization back to the model once, then fail the turn closed.

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
        exhausted = self._finalize_rejections > _MAX_FINALIZE_REPAIRS
        if not exhausted and isinstance(tool, BaseTool):
            tool.return_direct = False
        guidance = _FINALIZE_REPAIRS_EXHAUSTED if exhausted else _FINALIZE_CONTRACT_HELP
        return ToolMessage(
            content=f"{result.content}\n\n{guidance}",
            name=_FINALIZE_TOOL_NAME,
            tool_call_id=tool_call_id,
            status="error",
        )


def _error_code(exc: BaseException) -> str:
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
        max_runtime_s: float = 300.0,
        max_rounds: int = 24,
    ) -> None:
        if max_runtime_s <= 0:
            raise ValueError("agent runtime timeout must be positive")
        if not 1 <= max_rounds <= 128:
            raise ValueError("agent round ceiling must be between 1 and 128")
        self._models = models
        self._execution = execution
        self._max_runtime_s = max_runtime_s
        self._recursion_limit = max_rounds * 2 + 4

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
        constitution = request.constitution
        profile = resolved_profile.profile
        if constitution.profile_ref != resolved_profile.profile_ref:
            raise ValueError("turn constitution differs from the resolved exact profile")
        if context.manifest.execution_id != constitution.execution_id:
            raise ValueError("context bundle belongs to another execution")

        model = self._models.build(
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
        async with self._execution.checkpointer(
            execution_id=constitution.execution_id
        ) as checkpointer:
            graph = create_deep_agent(
                model=model,
                tools=list(governed_tools),
                system_prompt=resolved_profile.prompt_body,
                middleware=(
                    ExactAgentToolSurfaceMiddleware(
                        profile=resolved_profile,
                        # Some reviewed profile capabilities are constitution-dependent.  For
                        # example, selected-product readers are intentionally omitted unless the
                        # turn carries an exact Product-KB pin.  The factory has already applied
                        # that trusted narrowing; the runtime must enforce the resulting surface,
                        # not incorrectly require every capability listed by the reusable role
                        # profile.
                        effective_governed_tool_names={_tool_name(tool) for tool in governed_tools},
                    ),
                ),
                backend=backend,  # type: ignore[arg-type]
                checkpointer=checkpointer,
                state_schema=ClueDeepAgentState,
                name=f"clue-{profile.role.value}",
            )
            state: ClueDeepAgentState = {
                "messages": cast(Any, list(context.messages)),
                "constitution": constitution,
                "context_manifest": context.manifest,
                "turn_id": request.turn_id,
            }
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
