"""The account-research agent loop: one ``create_agent`` graph under four honest caps.

The founder's stop policy (2026-09-08) is "no pre-emptive caps": a hundred model rounds, fifty tool
calls in one round, thirty minutes, and **no** total-call or zero-yield ceiling. What matters here
is not the numbers (they are settings) but the *shape* of every ending:

* **Every cap ends the graph; none of them raises.** ``ModelCallLimitMiddleware`` is built with
  ``exit_behavior="end"`` so the round ceiling ends the run gracefully instead of throwing
  ``ModelCallLimitExceededError`` into the driver — the M8D lane's ``"error"`` behaviour is exactly
  what made a capped job *fail* rather than finish honestly.
* **A finalization stops the loop before the next model call**, so the one decision this job is
  allowed to make cannot be re-made or talked past.
* **The per-round ceiling refuses the excess calls, never the round.** The calls within the
  ceiling run; each call beyond it comes back as its own ``too_many_parallel_calls`` envelope, so
  every tool call in the wave is answered (a wave with an unanswered call is a malformed
  conversation to every provider) and the model reads the manual's reaction for that code.
* **A runtime cap waits for in-flight provider hops to drain** before it reports, because a hop
  that already happened has already been paid for, and money truth must reach the ledger.

The loop returns an :class:`AgentOutcome`; it never raises. Deciding what an outcome *means* for
the job row belongs to the driver, not here.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal
from uuid import uuid4

from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    InputAgentState,
    ModelCallLimitMiddleware,
    hook_config,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import StructuredTool

from clue_api.arv2.account_research_refusals import refusal_json
from clue_api.arv2.account_research_tools import ToolRuntime
from clue_api.arv2.sinks import LedgerRow
from clue_api.langfuse_callbacks import build_langfuse_callbacks
from clue_core.provider_failures import ProviderFailure, classify_exception
from clue_gateway.metadata import ANSWERING_MODEL_KEY, COST_SOURCE_KEY, cost_cents_from_metadata
from clue_obs import get_logger
from clue_obs.langfuse import (
    LangfuseRunRegistry,
    event,
    guardrail,
    observation,
    propagate_trace,
    tag_entities,
)

log = get_logger("clue_api.arv2.account_research_agent")

__all__ = ["AgentOutcome", "AgentStopReason", "ModelSpend", "run_account_agent"]

#: How long the loop waits for provider hops that were still in flight when a cap fired. They are
#: shielded from cancellation precisely so their ledger rows land, so this is the bound on
#: *waiting*, never on the hop.
_INFLIGHT_DRAIN_S = 60.0

#: How much of an unexpected exception is recorded on the outcome. Enough to name the failure in
#: the job row without turning a stack trace into a database column.
_ERROR_CHARS = 500

AgentStopReason = Literal["finalized", "round_cap", "runtime_cap", "model_error"]


@dataclass(frozen=True)
class ModelSpend:
    """What the loop's own model calls cost, summed from the rows it wrote to the ledger.

    ``cost_source`` is the honesty label carried up from the gateway: ``metered`` when OpenRouter
    reported the credits it charged, ``estimate`` when our price sheet answered, ``unpriced`` when
    neither could, and ``mixed`` when one job's rounds were not all answered the same way.
    """

    calls: int = 0
    usd: Decimal = Decimal(0)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_prompt_tokens: int = 0
    cost_source: str = "unpriced"

    def as_receipt(self) -> dict[str, Any]:
        return {
            "usd": str(self.usd),
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cached_prompt_tokens": self.cached_prompt_tokens,
            "cost_source": self.cost_source,
        }


@dataclass(frozen=True)
class AgentOutcome:
    """How one account job's loop ended, and what it spent getting there.

    ``reason`` is the whole vocabulary: the agent finalized, it ran out of rounds, it ran out of
    time, or the graph raised. There is no fifth ending, and none of them is an exception.

    ``provider_failure`` is set only when the ending was a *provider's* doing — it refused to
    serve, or it faulted — so the driver can record why on the job row instead of the bare
    ``model_error``. A fault nobody can classify leaves it ``None``.
    """

    reason: AgentStopReason
    model_rounds: int
    tool_calls: int
    error: str | None
    model_spend: ModelSpend = field(default_factory=ModelSpend)
    provider_failure: ProviderFailure | None = None


class _ModelUsageRecorder(AgentMiddleware[Any, Any, Any]):
    """Counts the model calls that happened, and writes each one onto the job's cost ledger.

    The tools' provider hops have been money-truth since R1; the loop's own rounds were not, so a
    job that spent twenty-nine Grok completions settled with ``cost_usd = 0``. A round is a
    provider call like any other: it becomes one ``result`` row under ``operation`` =
    ``agent_completion``, and ``job_spend`` — which already sums every ``result`` row — picks it
    up with no change.

    An unpriced round records ``cost_usd = NULL`` rather than ``0``: the ledger says "nobody
    measured this", never "this was free". A round that raises records a ``transport_error`` row
    and re-raises, so the loop's existing ``model_error`` ending is unchanged.

    ``attempt`` is the job row's own attempt counter (``begin_job`` increments it on every claim).
    It is part of the row id so a suspended job that is re-driven — whose round numbering starts
    at one again — adds its second attempt's rounds to the ledger instead of colliding with the
    first attempt's and being dropped by the drain's ``ON CONFLICT DO NOTHING``.
    """

    def __init__(
        self,
        runtime: ToolRuntime,
        *,
        attempt: int,
        langfuse_ids: LangfuseRunRegistry | None = None,
    ) -> None:
        super().__init__()
        self._runtime = runtime
        self._attempt = attempt
        self._langfuse_ids = langfuse_ids
        self.count = 0
        self._spend = ModelSpend()
        #: The last round's classified provider verdict, so the loop's ``model_error`` ending can
        #: name what the provider did rather than only which exception class reached it.
        self.last_provider_failure: ProviderFailure | None = None

    async def awrap_model_call(self, request: Any, handler: Any) -> Any:
        self.count += 1
        round_number = self.count
        started = time.perf_counter()
        try:
            response = await handler(request)
        except Exception as error:
            failure = classify_exception("openrouter", error)
            self.last_provider_failure = failure
            self._record(
                round_number,
                started=started,
                message=None,
                error_code=type(error).__name__,
                provider_failure=failure,
            )
            raise
        self._record(round_number, started=started, message=_answer(response), error_code=None)
        return response

    @property
    def spend(self) -> ModelSpend:
        """Every round this recorder wrote, summed — whether or not the rows have been drained."""
        return self._spend

    def _record(
        self,
        round_number: int,
        *,
        started: float,
        message: AIMessage | None,
        error_code: str | None,
        provider_failure: ProviderFailure | None = None,
    ) -> None:
        metadata: Mapping[str, Any] = message.response_metadata if message is not None else {}
        usage: Mapping[str, Any] = (message.usage_metadata or {}) if message is not None else {}
        cents = _cost_cents(metadata) if message is not None else None
        details: Mapping[str, Any] = usage.get("input_token_details") or {}
        prompt_tokens = int(usage.get("input_tokens") or 0)
        completion_tokens = int(usage.get("output_tokens") or 0)
        cached_tokens = int(details.get("cache_read") or 0)
        source = str(metadata.get(COST_SOURCE_KEY) or "unpriced")
        extras: dict[str, object] = (
            {}
            if message is None
            else {
                "model": str(metadata.get(ANSWERING_MODEL_KEY) or metadata.get("model_name") or ""),
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "cached_prompt_tokens": cached_tokens,
                "cost_source": source,
            }
        )
        # The drain reads this stamp to open one durable incident per (provider, reason): a round
        # that a provider refused says so on its own row, not only in an exception class name.
        if provider_failure is not None:
            extras["provider_failure"] = {
                "kind": provider_failure.kind,
                "reason": provider_failure.reason,
                "message": provider_failure.message,
            }
        # The graph runs one model round at a time, so the registry's most recent entry is this
        # round's generation: the durable row and the Langfuse observation name each other.
        if message is not None and self._langfuse_ids is not None:
            ids = self._langfuse_ids.latest()
            if ids is not None:
                extras["langfuse_trace_id"] = ids.trace_id
                if ids.observation_id is not None:
                    extras["langfuse_observation_id"] = ids.observation_id
        row = LedgerRow(
            # Deterministic in the job, the attempt and the round, so the drain — which runs
            # inside the driver's settlement transaction and may be retried after a rollback —
            # lands one row per round however many times it runs (``ledger_id_for`` + ``ON
            # CONFLICT DO NOTHING``), while a re-driven job's rounds still add to the ledger
            # rather than collapsing into its first attempt's.
            row_id=f"model:{self._runtime.scope.job_id}:{self._attempt}:{round_number}",
            call_id=str(uuid4()),
            phase="result",
            provider="openrouter",
            operation="agent_completion",
            label=f"round-{round_number}",
            recorded_at=self._runtime.now(),
            http_status=None if error_code is not None else 200,
            latency_ms=int((time.perf_counter() - started) * 1000),
            attempts=1,
            cost_usd=None if cents is None else cents / 100,
            outcome="transport_error" if error_code is not None else "ok",
            error_code=error_code,
            extras=extras,
        )
        self._runtime.model_ledger.record(row)
        # A job whose rounds were not all priced the same way says ``mixed`` rather than picking
        # one of the two labels and quietly misdescribing the other rounds.
        previous = self._spend
        self._spend = ModelSpend(
            calls=previous.calls + 1,
            usd=previous.usd + (row.cost_usd or Decimal(0)),
            prompt_tokens=previous.prompt_tokens + prompt_tokens,
            completion_tokens=previous.completion_tokens + completion_tokens,
            cached_prompt_tokens=previous.cached_prompt_tokens + cached_tokens,
            cost_source=(
                source if previous.calls == 0 or previous.cost_source == source else "mixed"
            ),
        )


def _answer(response: Any) -> AIMessage | None:
    """The assistant turn inside whatever the middleware handler returned.

    ``awrap_model_call``'s handler answers with a ``ModelResponse`` whose ``result`` is the
    model's messages, but the contract also admits a bare ``AIMessage`` and an extended response,
    so all three shapes are read rather than assumed.
    """
    if isinstance(response, AIMessage):
        return response
    inner = getattr(response, "model_response", response)
    for message in getattr(inner, "result", ()) or ():
        if isinstance(message, AIMessage):
            return message
    return None


def _cost_cents(metadata: Any) -> Decimal | None:
    """The gateway's stamped cost for one answer, or ``None`` when it could not price the model.

    Delegates to the shared reader so this ledger and the conversation-turn receipt parse the
    stamp identically (an ``unpriced`` answer is a blank, never a measured zero).
    """
    cents, _source = cost_cents_from_metadata(metadata)
    return cents


class _RoundShapeMiddleware(AgentMiddleware[Any, Any, Any]):
    """Cap the parallel wave: the first ``limit`` calls of a round run, the rest are refused.

    The cap is applied at the *tool* boundary rather than by truncating the model's message,
    because a truncated ``AIMessage`` leaves tool calls that never receive a result, and a
    provider replaying that history rejects the whole conversation. Refusing each excess call
    keeps the wave complete: N calls, N results, of which the last few say
    ``too_many_parallel_calls`` and name the ceiling.
    """

    def __init__(self, *, limit: int, runtime: ToolRuntime) -> None:
        super().__init__()
        self._limit = limit
        self._runtime = runtime

    async def awrap_tool_call(self, request: Any, handler: Any) -> Any:
        call = dict(request.tool_call)
        position = self._position(request.state, str(call.get("id") or ""))
        if position is not None and position >= self._limit:
            detail = (
                f"this call is number {position + 1} of the round; the first {self._limit} ran and "
                "the rest are refused"
            )
            log.info(
                "arv2.account_round_shape_refused",
                tool=str(call.get("name") or ""),
                position=position,
                limit=self._limit,
            )
            guardrail(
                "arv2.too_many_parallel_calls",
                reason=detail,
                metadata={
                    "tool": str(call.get("name") or ""),
                    "position": position,
                    "limit": self._limit,
                },
            )
            return ToolMessage(
                content=refusal_json("too_many_parallel_calls", detail),
                tool_call_id=str(call.get("id") or ""),
                name=str(call.get("name") or ""),
                status="error",
            )
        return await handler(request)

    @staticmethod
    def _position(state: Any, call_id: str) -> int | None:
        """Where this call sits in the wave its own model turn proposed."""
        messages = state.get("messages", ()) if isinstance(state, dict) else ()
        for message in reversed(tuple(messages)):
            if isinstance(message, AIMessage) and message.tool_calls:
                ids = [str(item.get("id") or "") for item in message.tool_calls]
                return ids.index(call_id) if call_id in ids else None
        return None


class _FinalizeEndsMiddleware(AgentMiddleware[Any, Any, Any]):
    """End the graph as soon as the job has a finalization, before another model call."""

    def __init__(self, runtime: ToolRuntime) -> None:
        super().__init__()
        self._runtime = runtime

    @hook_config(can_jump_to=["end"])
    async def abefore_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        del state, runtime
        return {"jump_to": "end"} if self._runtime.finalization is not None else None


async def _graph_failed(
    runtime: ToolRuntime, rounds: _ModelUsageRecorder, error: BaseException
) -> AgentOutcome:
    """The graph raised: drain the paid-for hops, then report the failure as an outcome."""
    await runtime.wait_for_inflight(timeout_s=_INFLIGHT_DRAIN_S)
    log.exception("arv2.account_agent_failed", model_rounds=rounds.count)
    detail = f"{type(error).__name__}: {error}"[:_ERROR_CHARS]
    return AgentOutcome(
        "model_error",
        rounds.count,
        runtime.tool_calls,
        detail,
        rounds.spend,
        provider_failure=rounds.last_provider_failure,
    )


async def run_account_agent(
    *,
    model: BaseChatModel,
    system_prompt: str,
    tools: Sequence[StructuredTool],
    runtime: ToolRuntime,
    max_model_rounds: int,
    max_tool_calls_per_round: int,
    max_runtime_s: float,
    task_instruction: str,
    attempt: int,
) -> AgentOutcome:
    """Run one account job's agent to one of its four endings. Never raises.

    A graph that ends with no finalization is reported as ``round_cap`` whether the ceiling fired
    or the model simply stopped calling tools: both are "the job ended without the one decision it
    was asked for", which is what the receipt and the reviewer need to know.

    ``attempt`` is the job row's attempt counter; it only ever reaches the ledger row ids the
    loop's model rounds write, so a re-driven job's spend adds up instead of colliding.
    """

    langfuse = build_langfuse_callbacks()
    rounds = _ModelUsageRecorder(
        runtime, attempt=attempt, langfuse_ids=langfuse.registry if langfuse is not None else None
    )
    agent = create_agent(
        model=model,
        tools=list(tools),
        system_prompt=system_prompt,
        middleware=[
            rounds,
            _RoundShapeMiddleware(limit=max_tool_calls_per_round, runtime=runtime),
            _FinalizeEndsMiddleware(runtime),
            ModelCallLimitMiddleware(run_limit=max_model_rounds, exit_behavior="end"),
        ],
        name="clue-arv2-account",
    )
    opening = InputAgentState(messages=[HumanMessage(content=task_instruction)])
    # The graph takes one step per node, so the ceiling has to cover every round's model call, its
    # tool wave and the middleware hops around them, plus the entry and exit nodes. Below this the
    # graph would raise GraphRecursionError long before the round cap it is supposed to defer to.
    config = RunnableConfig(
        recursion_limit=max_model_rounds * (max_tool_calls_per_round + 2) + 4,
        callbacks=[langfuse.handler] if langfuse is not None else [],
    )
    scope = runtime.scope
    # One job is one named trace: every span the graph opens inside — the agent tree the handler
    # reports, the tools' provider observations — carries the job's session, user and metadata.
    with (
        propagate_trace(
            trace_name="arv2.account_research",
            session_id=str(scope.run_id),
            user_id=scope.workspace_id,
            metadata={
                "project_id": scope.project_id,
                "project_run_id": scope.project_run_id,
                "job_id": scope.job_id,
                "account_id": scope.account_id,
                "contact_id": scope.contact_id,
                "subject_kind": scope.subject_kind,
                "attempt": attempt,
            },
            tags=("arv2", scope.subject_kind),
        ),
        observation(
            "arv2.account_research",
            as_type="agent",
            input={
                "account_id": str(scope.account_id),
                "subject_kind": scope.subject_kind,
                "attempt": attempt,
            },
            metadata={"job_id": str(scope.job_id), "run_id": str(scope.run_id)},
        ) as current,
    ):
        # The subject first, before any work: a job that dies mid-round still names who it was
        # about on its trace.
        tag_entities([scope.account_id, scope.contact_id])
        outcome = await _drive_graph(
            agent,
            opening,
            config,
            runtime=runtime,
            rounds=rounds,
            max_runtime_s=max_runtime_s,
        )
        # Inside the observation: the graph the handler reported, the tools' provider hops and
        # this ending all sit beneath the one agent observation, under one trace id.
        _report_ending(outcome)
        # Everything the job wrote a claim about, re-emitted whole onto the job's trace.
        tag_entities(runtime.entities_touched)
        current.update(
            output={
                "reason": outcome.reason,
                "model_rounds": outcome.model_rounds,
                "tool_calls": outcome.tool_calls,
                "model_spend_usd": str(outcome.model_spend.usd),
            },
            level="ERROR" if outcome.reason == "model_error" else "DEFAULT",
            status_message=outcome.error if outcome.reason == "model_error" else None,
        )
    return outcome


async def _drive_graph(
    agent: Any,
    opening: InputAgentState,
    config: RunnableConfig,
    *,
    runtime: ToolRuntime,
    rounds: _ModelUsageRecorder,
    max_runtime_s: float,
) -> AgentOutcome:
    """Run the graph to one of its four endings. Never raises."""
    # The invoke runs as its own task so the two ``TimeoutError``s can be told apart. Our runtime
    # cap and a provider timeout raised *inside* the graph are the same exception type reaching the
    # same handler, and they are opposite endings: one is us stopping a job that was still working,
    # the other is the provider failing to answer. ``wait_for``'s expiry cancels this task, so a
    # task that finished with an exception of its own is the graph's failure, never the cap.
    invoke: asyncio.Task[Any] = asyncio.create_task(agent.ainvoke(opening, config=config))
    try:
        await asyncio.wait_for(invoke, timeout=max_runtime_s or None)
    except TimeoutError:
        failed = invoke.exception() if invoke.done() and not invoke.cancelled() else None
        if failed is not None:
            return await _graph_failed(runtime, rounds, failed)
        await runtime.wait_for_inflight(timeout_s=_INFLIGHT_DRAIN_S)
        log.info(
            "arv2.account_agent_runtime_cap",
            model_rounds=rounds.count,
            tool_calls=runtime.tool_calls,
        )
        return AgentOutcome("runtime_cap", rounds.count, runtime.tool_calls, None, rounds.spend)
    except Exception as error:  # noqa: BLE001 — the graph's failures are outcomes, never raises
        return await _graph_failed(runtime, rounds, error)
    if runtime.finalization is not None:
        return AgentOutcome("finalized", rounds.count, runtime.tool_calls, None, rounds.spend)
    return AgentOutcome("round_cap", rounds.count, runtime.tool_calls, None, rounds.spend)


def _report_ending(outcome: AgentOutcome) -> None:
    """The job's ending as one event (and a guardrail when a cap, not the agent, ended it)."""
    event(
        "arv2.agent.ending",
        output={
            "reason": outcome.reason,
            "model_rounds": outcome.model_rounds,
            "tool_calls": outcome.tool_calls,
            "error": outcome.error,
            "model_spend_usd": str(outcome.model_spend.usd),
        },
        level="ERROR" if outcome.reason == "model_error" else "DEFAULT",
        status_message=outcome.error if outcome.reason == "model_error" else None,
    )
    if outcome.reason in ("round_cap", "runtime_cap"):
        guardrail(
            f"arv2.{outcome.reason}",
            reason=(
                f"the job ended on its {outcome.reason.replace('_', ' ')} after "
                f"{outcome.model_rounds} rounds"
            ),
            metadata={"model_rounds": outcome.model_rounds, "tool_calls": outcome.tool_calls},
        )
