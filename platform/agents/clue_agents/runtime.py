"""Real deepagents turn loop with governed tools and mandatory honest finalization."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Sequence
from typing import Any, cast

from deepagents import create_deep_agent
from langchain_core.callbacks import BaseCallbackHandler
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

__all__ = ["DeepAgentTurnRuntime"]


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
        )
        async with self._execution.checkpointer(
            execution_id=constitution.execution_id
        ) as checkpointer:
            graph = create_deep_agent(
                model=model,
                tools=list(governed_tools),
                system_prompt=resolved_profile.prompt_body,
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
