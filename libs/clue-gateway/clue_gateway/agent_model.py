"""Governed OpenRouter Responses model construction and attribution for C6."""

from __future__ import annotations

import asyncio
import os
import re
import time
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol, cast, runtime_checkable

import httpx
from langchain_core.callbacks import (
    AsyncCallbackManagerForLLMRun,
    CallbackManagerForLLMRun,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.utils.function_calling import convert_to_openai_tool
from openai import APIConnectionError
from pydantic import ConfigDict, SecretStr, model_validator

from clue_config.gateway import GatewayConfig
from clue_core.gateway import TokenUsage
from clue_core.openrouter_cost import openrouter_charged_usd
from clue_gateway.metadata import (
    ANSWERING_MODEL_KEY,
    COST_CENTS_KEY,
    COST_SOURCE_KEY,
    REQUESTED_MODEL_KEY,
    ROLE_KEY,
    CostSource,
)
from clue_gateway.openrouter_chat import OpenRouterChatModel
from clue_gateway.openrouter_responses import OpenRouterResponsesModel, ResponseUsage
from clue_gateway.tracing import record_model_call
from clue_obs import get_logger
from clue_obs.otel import ATTR_AGENT_ROLE, ATTR_MODEL, SPAN_LLM_GATEWAY_CALL, traced_step

__all__ = [
    "ANSWERING_MODEL_KEY",
    "COST_CENTS_KEY",
    "COST_SOURCE_KEY",
    "CostSource",
    "GenerationCostLookup",
    "GovernedAgentChatModel",
    "OpenRouterAgentModelProvider",
    "OpenRouterGenerationCost",
    "provider_compatible_tool_schema",
    "transient_upstream_failure",
    "unsupported_schema_pattern",
]

log = get_logger("clue_gateway.agent_model")

# The OpenAI/OpenRouter Responses JSON-schema subset rejects lookaround and backreferences; a
# single offending tool schema fails the whole request (all tools are sent together) with
# "regex lookaround is not supported". Pydantic emits one for every ``Decimal`` field.
_UNSUPPORTED_REGEX_CONSTRUCTS = ("(?=", "(?!", "(?<=", "(?<!")
_BACKREFERENCE = re.compile(r"\\[1-9]")


def unsupported_schema_pattern(pattern: str) -> bool:
    """Report whether a JSON-schema ``pattern`` uses regex the provider subset rejects."""

    if any(construct in pattern for construct in _UNSUPPORTED_REGEX_CONSTRUCTS):
        return True
    return _BACKREFERENCE.search(pattern) is not None


def provider_compatible_tool_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Drop the ``pattern`` constraints the provider rejects, preserving everything else.

    The provider schema is model *guidance*: every tool argument is re-validated locally against
    the owning pydantic model before anything durable happens, so dropping a pattern here loosens
    no platform guarantee. Rejecting the whole request does.
    """

    transformed = _without_unsupported_patterns(schema)
    return cast(dict[str, Any], transformed)


def _without_unsupported_patterns(node: Any) -> Any:
    if isinstance(node, dict):
        return {
            key: _without_unsupported_patterns(value)
            for key, value in node.items()
            if not (
                key == "pattern" and isinstance(value, str) and unsupported_schema_pattern(value)
            )
        }
    if isinstance(node, list):
        return [_without_unsupported_patterns(item) for item in node]
    return node


# The response-metadata keys this module stamps are PUBLIC and live in the dependency-free
# ``clue_gateway.metadata`` leaf: a caller that only wants to read what a model call cost must be
# able to import them without reaching the vendor SDK this package exists to contain (Rule 4b).
# The leading-underscore aliases keep this module's own body — and the tests that reach into it —
# spelled the way they always were.
_REQUESTED_MODEL_KEY = REQUESTED_MODEL_KEY
_ROLE_KEY = ROLE_KEY
_ANSWERING_MODEL_KEY = ANSWERING_MODEL_KEY
_COST_CENTS_KEY = COST_CENTS_KEY
_COST_SOURCE_KEY = COST_SOURCE_KEY


def _catalog_input_modalities(model_entry: dict[str, Any]) -> list[str] | None:
    """A catalog entry's input modalities, handling BOTH observed OpenRouter shapes:
    ``architecture.input_modalities`` (a list) and ``architecture.modality`` (a
    string like ``text+image->text``). None = the entry names neither (unknown)."""
    architecture = model_entry.get("architecture") or {}
    modalities = architecture.get("input_modalities")
    if isinstance(modalities, list):
        return [str(m).lower() for m in modalities]
    modality = architecture.get("modality")
    if isinstance(modality, str) and modality:
        input_side = modality.split("->", 1)[0]
        return [part.strip().lower() for part in input_side.split("+") if part.strip()]
    return None


# --- bounded transient-failure retry ---------------------------------------------------------
#
# A live entity-research job was suspended because OpenRouter answered HTTP 200 with an in-body
# ``{"error": {"code": "server_error"}}``.  ``langchain_openai`` turns that into a bare
# ``ValueError(ResponseError(...))`` while *parsing* an otherwise successful response
# (``chat_models/base.py::_construct_lc_result_from_responses_api``), so the OpenAI SDK's own
# ``max_retries`` — which only sees transport/status failures — never applies.  The error escaped
# this wrapper, killed the agent graph, and the supervisor contained the job.  A momentary upstream
# blip is not a job-integrity failure, so it is retried here, at the single provider boundary every
# agent lane already builds its model through.
#
# An attempt is one pass over the whole candidate sequence (primary, then the configured fallback),
# so the existing contract — a failing primary reaches the fallback immediately — is unchanged; only
# a round in which the LAST candidate also failed transiently is retried.
#
# The bound is a MODULE CONSTANT, not a ``Settings`` knob, on purpose: it is a provider-boundary
# safety floor rather than per-deployment policy, and the effective spend ceiling is already bounded
# by ``GatewayConfig.max_retries`` (SDK transport retries) times this bound times the candidate
# count.  Promote it to config only if a deployment ever needs to tune it.
_MAX_TRANSIENT_ATTEMPTS = 3
# Seconds to wait before attempt 2 and attempt 3.  Deliberately short: the agent turn is holding a
# fleet lease whose heartbeat must keep landing.
_TRANSIENT_BACKOFF_S = (0.5, 1.5)

# Responses-API in-body error codes that describe a momentary upstream condition.  Everything else
# the enum carries (``invalid_prompt``, the image/policy codes) is a deterministic rejection that
# retrying can only repeat, so it keeps today's loud behaviour.
_TRANSIENT_RESPONSE_ERROR_CODES = frozenset(
    {"server_error", "rate_limit_exceeded", "vector_store_timeout"}
)
# 429 = rate limited, 408/409 = request timeout / conflict, ≥500 = upstream fault.
_TRANSIENT_STATUS_CODES = frozenset({408, 409, 429})


def transient_upstream_failure(error: BaseException) -> bool:
    """Report whether ``error`` is a momentary upstream failure worth one more attempt.

    Three shapes, all observed from OpenRouter: a transport fault or timeout, a retryable HTTP
    status, and — the shape that suspended a live job — a successful HTTP response carrying an
    in-body Responses ``error`` object that ``langchain_openai`` re-raises as a plain
    ``ValueError``.  The error is classified as raised; no ``__cause__`` chain is walked, since
    this runs directly around the provider call, where nothing has wrapped it yet.
    """

    if isinstance(error, APIConnectionError | httpx.TransportError):
        return True
    code = next(
        (found for found in map(_response_error_code, error.args) if found is not None),
        None,
    )
    if code is not None:
        # An in-body Responses error is the authoritative verdict, and must be read BEFORE any
        # status: ``langchain_openai`` re-raises it with the raw HTTP response attached, and that
        # response is the 200 the failing body arrived in.
        #
        # Two vocabularies arrive in that ``code`` field. The Responses enum is a string
        # (``server_error``). OpenRouter's proxy layer instead relays the UPSTREAM HTTP status
        # as the code — seen live twice on 2026-09-04 as ``{"message": "Auth context expired",
        # "code": 502}`` on a 136 s and a 236 s grok generation, each of which discarded a whole
        # web turn. A numeric code is therefore read as the status it is.
        numeric = _numeric_code(code)
        if numeric is not None:
            return _transient_status(numeric)
        return code in _TRANSIENT_RESPONSE_ERROR_CODES
    status = getattr(error, "status_code", None)
    if status is None:
        status = getattr(getattr(error, "response", None), "status_code", None)
    return isinstance(status, int) and _transient_status(status)


def _transient_status(status: int) -> bool:
    """429 = rate limited, 408/409 = request timeout / conflict, >=500 = upstream fault."""

    return status >= 500 or status in _TRANSIENT_STATUS_CODES


def _response_error_code(argument: object) -> str | None:
    """The in-body ``error.code`` an exception argument carries, if it is one.

    A string enum member is returned as is; an integer (OpenRouter relaying the upstream HTTP
    status) is returned as its decimal text so the caller reads both through one path.
    """

    if isinstance(argument, Mapping):
        code = argument.get("code")
    else:
        code = getattr(argument, "code", None)
    if isinstance(code, bool):
        return None
    if isinstance(code, int):
        return str(code)
    return code if isinstance(code, str) else None


def _numeric_code(code: str) -> int | None:
    """The HTTP status a ``code`` field spells, or ``None`` when it is an enum word."""

    return int(code) if code.isdigit() else None


def _transient_retry_backoff_s(error: Exception, attempt: int) -> float | None:
    """Backoff before the next attempt, or ``None`` when this failure must surface as-is."""

    if attempt >= _MAX_TRANSIENT_ATTEMPTS or not transient_upstream_failure(error):
        return None
    return _TRANSIENT_BACKOFF_S[attempt - 1]


# --- OpenRouter's own meter for a completed generation ----------------------------------------
#
# Founder ruling, 2026-09-08: a governed model call's cost is OpenRouter's number and nobody
# else's. ``usage.include`` puts it on the response, but only the chat-completions path carries
# the provider's extra ``cost`` key back through ``langchain_openai`` — the streaming and Responses
# paths keep a fixed key set and drop it. Rather than fall back to rates we would have to keep
# current, those paths ask OpenRouter what the generation cost.
#
# The lookup is deliberately small and deliberately unimportant: it is bounded, it retries once on
# an upstream fault, and it NEVER raises or delays a completed call for long. A failure is an
# honest ``unpriced`` plus a log line naming the generation, which is enough for a later
# reconciliation pass to fetch the number the meter still holds.

#: Where OpenRouter publishes a finished generation's true cost.
_GENERATION_PATH = "/generation"
#: The ceiling on one lookup. Small on purpose: the call it prices has already been paid for, and
#: the caller is holding a fleet lease.
_COST_LOOKUP_TIMEOUT_S = 5.0
#: Exactly one retry, for the two failures that are plausibly momentary: an upstream fault, and a
#: 404. A 404 is the *expected* live shape for a job's last round — the lookup runs the instant the
#: completion returns and OpenRouter's meter can lag the response — so it is re-asked once rather
#: than written off. Everything else (a malformed body, an auth failure) will answer the same way
#: twice and is not worth a second call.
_COST_LOOKUP_ATTEMPTS = 2
#: How long to wait before re-asking about a generation the meter had not recorded yet. Long
#: enough for the lag, short enough that the worst case (timeout + lag + timeout) stays well
#: inside the fleet lease the caller is holding.
_METER_LAG_BACKOFF_S = 1.0
#: Ids LangChain mints for its own runs. They are not generation ids and must never be looked up.
_LANGCHAIN_ID_PREFIXES = ("lc_run", "run-")


@runtime_checkable
class GenerationCostLookup(Protocol):
    """Asks the provider what one finished generation cost, in cents. ``None`` = it would not say.

    A protocol rather than a concrete type so a caller can inject a recorded double (and so the
    governed model stays testable without a network), and so a provider that meters differently
    can be substituted without touching the model wrapper.
    """

    def cost_cents(self, generation_id: str) -> Decimal | None: ...

    async def acost_cents(self, generation_id: str) -> Decimal | None: ...


@dataclass(frozen=True)
class _Retry:
    """Ask again, after ``after_s`` seconds. Distinguishes "attempt again" from a real ``None``."""

    after_s: float


class OpenRouterGenerationCost:
    """``GET {base_url}/generation?id=…`` → ``data.total_cost`` (USD) as cents.

    Bounded and silent by construction: one short request, one retry (immediately on an upstream
    fault, after a second on a 404 — the meter can lag the response it prices), every failure
    swallowed into ``None`` after a ``gateway.cost_lookup_failed`` log that names the generation.
    Pricing a call must never be able to fail the call.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: SecretStr,
        timeout_s: float = _COST_LOOKUP_TIMEOUT_S,
        # Overridable only so a test can assert the retry without really waiting a second for it.
        # Production never passes it; the ceiling above is what bounds this in anger.
        meter_lag_backoff_s: float = _METER_LAG_BACKOFF_S,
        http_client: Any | None = None,
        http_async_client: Any | None = None,
    ) -> None:
        self._url = f"{base_url.rstrip('/')}{_GENERATION_PATH}"
        self._api_key = api_key
        self._timeout_s = min(timeout_s, _COST_LOOKUP_TIMEOUT_S)
        self._meter_lag_backoff_s = meter_lag_backoff_s
        self._http_client = http_client
        self._http_async_client = http_async_client

    def cost_cents(self, generation_id: str) -> Decimal | None:
        for attempt in range(1, _COST_LOOKUP_ATTEMPTS + 1):
            try:
                if self._http_client is not None:
                    response = self._http_client.get(
                        self._url, params={"id": generation_id}, headers=self._headers()
                    )
                else:
                    response = httpx.get(
                        self._url,
                        params={"id": generation_id},
                        headers=self._headers(),
                        timeout=self._timeout_s,
                    )
            except Exception as error:  # noqa: BLE001 - pricing never fails the call it prices
                return self._gave_up(generation_id, reason=repr(error))
            verdict = self._retry_or_result(response, generation_id, attempt=attempt)
            if not isinstance(verdict, _Retry):
                return verdict
            if verdict.after_s:
                time.sleep(verdict.after_s)
        return None  # pragma: no cover - the loop returns on its last attempt

    async def acost_cents(self, generation_id: str) -> Decimal | None:
        for attempt in range(1, _COST_LOOKUP_ATTEMPTS + 1):
            try:
                if self._http_async_client is not None:
                    response = await self._http_async_client.get(
                        self._url, params={"id": generation_id}, headers=self._headers()
                    )
                else:
                    async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                        response = await client.get(
                            self._url, params={"id": generation_id}, headers=self._headers()
                        )
            except Exception as error:  # noqa: BLE001 - pricing never fails the call it prices
                return self._gave_up(generation_id, reason=repr(error))
            verdict = self._retry_or_result(response, generation_id, attempt=attempt)
            if not isinstance(verdict, _Retry):
                return verdict
            if verdict.after_s:
                # Awaited, not slept: this runs on the loop the agent graph is driving.
                await asyncio.sleep(verdict.after_s)
        return None  # pragma: no cover - the loop returns on its last attempt

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key.get_secret_value()}"}

    def _retry_or_result(
        self, response: Any, generation_id: str, *, attempt: int
    ) -> Decimal | None | _Retry:
        """One attempt's verdict: a cost, an honest ``None``, or "ask again after N seconds"."""
        status = int(getattr(response, "status_code", 0))
        if attempt < _COST_LOOKUP_ATTEMPTS:
            if status >= 500:
                # An upstream fault: nothing to wait for, the next replica may just answer.
                return _Retry(0.0)
            if status == 404:
                # The meter has not recorded this generation yet. Give it a moment — this is the
                # ordinary shape for the last round of a job, where the lookup runs immediately
                # after the completion returns.
                return _Retry(self._meter_lag_backoff_s)
        if status != 200:
            return self._gave_up(generation_id, reason=f"http_{status}")
        try:
            payload = response.json()
        except Exception as error:  # noqa: BLE001 - a malformed body is a failed lookup
            return self._gave_up(generation_id, reason=repr(error))
        data = (payload or {}).get("data") or {}
        # The record spells the usage block flat; the charged amount follows the same rule.
        charged = openrouter_charged_usd(
            {
                "cost": data.get("total_cost"),
                "cost_details": {"upstream_inference_cost": data.get("upstream_inference_cost")},
            }
        )
        if charged is None:
            return self._gave_up(generation_id, reason="no_total_cost")
        return charged * 100

    @staticmethod
    def _gave_up(generation_id: str, *, reason: str) -> None:
        # The generation id is logged on purpose: OpenRouter keeps the number, so a later
        # reconciliation can fetch what this call could not.
        log.warning("gateway.cost_lookup_failed", generation_id=generation_id, reason=reason)
        return None


class _ReplyUsageFirst:
    """Price a generation from its own reply's usage block, else ask ``/generation``.

    The Responses route's reply carries OpenRouter's cost, which LangChain drops; the
    ``/generation`` record appears only about twelve seconds later, so asking it first left every
    Responses call ``unpriced`` (Sol smoke test, 2026-10-09).
    """

    def __init__(self, usage: ResponseUsage, lookup: GenerationCostLookup) -> None:
        self._usage = usage
        self._lookup = lookup

    def cost_cents(self, generation_id: str) -> Decimal | None:
        charged = self._usage.charged_cents(generation_id)
        return charged if charged is not None else self._lookup.cost_cents(generation_id)

    async def acost_cents(self, generation_id: str) -> Decimal | None:
        charged = self._usage.charged_cents(generation_id)
        return charged if charged is not None else await self._lookup.acost_cents(generation_id)


def _generation_id(message: BaseMessage | None, payload: Mapping[str, Any] | None) -> str | None:
    """The provider's id for this generation (``chatcmpl-…`` / ``gen-…``), or ``None``.

    Read from the same two places the served model is read from — the result's ``llm_output`` and
    the message's ``response_metadata`` — and, failing both, from the message id, which
    ``langchain_openai`` sets from the response on some paths. An id LangChain minted for its own
    run is explicitly refused: looking one of those up would be asking OpenRouter about a call it
    has never heard of.
    """
    candidates = [
        (payload or {}).get("id"),
        (message.response_metadata if message is not None else {}).get("id"),
        getattr(message, "id", None),
    ]
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        cleaned = candidate.strip()
        if cleaned and not cleaned.startswith(_LANGCHAIN_ID_PREFIXES):
            return cleaned
    return None


class FirstChunkTimeout(TimeoutError):
    """A streamed candidate sent no chunk at all within the first-chunk deadline."""


async def _first_chunk_within(
    stream: AsyncIterator[ChatGenerationChunk], timeout_s: float | None
) -> AsyncIterator[ChatGenerationChunk]:
    """Re-yield ``stream``, raising :class:`FirstChunkTimeout` when its FIRST chunk takes longer
    than ``timeout_s``. Later chunks are not timed here (mid-answer pauses stay governed by the
    provider client's own chunk timeout). The underlying stream is always closed, so an abandoned
    candidate releases its HTTP request before the next one starts."""

    try:
        if timeout_s is None:
            async for chunk in stream:
                yield chunk
            return
        iterator = stream.__aiter__()
        try:
            first = await asyncio.wait_for(iterator.__anext__(), timeout=timeout_s)
        except StopAsyncIteration:
            return
        except TimeoutError as exc:
            raise FirstChunkTimeout(f"no response chunk within {timeout_s:g}s") from exc
        yield first
        async for chunk in iterator:
            yield chunk
    finally:
        aclose = getattr(stream, "aclose", None)
        if aclose is not None:
            await aclose()


class GovernedAgentChatModel(BaseChatModel):
    """Provider model(s) wrapped with fallback, bounded transient retry, usage/cost metadata,
    tracing, and tool binding.

    Retries live *inside* one call: a caller (and every journal that brackets that call, such as the
    entity-research runtime's ``model_started``/``model_completed`` pair) observes exactly one model
    call regardless of how many attempts it took.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    models: tuple[BaseChatModel, ...]
    model_ids: tuple[str, ...]
    requested_model: str
    gateway_config: GatewayConfig
    # P3.2: the agent-role label this instance answers for (one instance per role is the
    # attribution mechanism — LangChain callbacks and usage records are per-instance).
    # None = an unlabelled platform model; nothing changes for existing call sites.
    attribution_role: str | None = None
    # Seconds a streamed call may wait for its FIRST chunk from one candidate before the next
    # candidate is tried (2026-10-04: grok-4.6 accepted requests and sent nothing for 300 s).
    # ``None`` = no first-chunk deadline. Once a chunk has arrived, pauses are not cut here.
    first_token_timeout_s: float | None = None
    # Hard wall-clock deadline for one candidate's NON-streamed call, opt-in per builder (the
    # design-leg exit judge): a stalled provider can keep the connection alive, so the per-read
    # HTTP timeout never fires (a judge call hung 13 minutes on 2026-10-04). ``None`` = none.
    call_deadline_s: float | None = None
    # OpenRouter's meter for a generation whose response did not carry its own cost (the streaming
    # and Responses paths). ``None`` = do not ask — every such call reports ``unpriced`` unless the
    # deployment happens to list the model in ``GatewayConfig.prices``. The provider injects the
    # real one; a hand-built model (tests, doubles) gets the honest silence.
    cost_lookup: GenerationCostLookup | None = None

    @model_validator(mode="after")
    def _validate_candidates(self) -> GovernedAgentChatModel:
        if not self.models:
            raise ValueError("governed agent model requires at least one provider model")
        if len(self.models) != len(self.model_ids):
            raise ValueError("provider models and model ids must have equal length")
        if any(not model_id.strip() for model_id in self.model_ids):
            raise ValueError("provider model ids must be non-empty")
        return self

    @property
    def _llm_type(self) -> str:
        return "clue-openrouter-agent"

    def _get_ls_params(self, stop: list[str] | None = None, **kwargs: Any) -> Any:
        # deepagents resolves a harness profile by this provider name; the default derives it from
        # the class name (a best-effort fallback, not a contract), so it is pinned here. It must
        # equal ``clue_agents.compaction.GOVERNED_PROVIDER_KEY`` (tests/agents/test_compaction.py).
        params = super()._get_ls_params(stop=stop, **kwargs)
        params["ls_provider"] = "clue-openrouter-agent"
        return params

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {
            "requested_model": self.requested_model,
            "fallback_model": self.gateway_config.fallback_model,
        }

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Any],
        *,
        tool_choice: dict[str, Any] | str | bool | None = None,
        **kwargs: Any,
    ) -> Runnable[Any, AIMessage]:
        """Bind standard tool schemas while keeping calls inside this governed wrapper."""

        formatted = [
            provider_compatible_tool_schema(convert_to_openai_tool(tool)) for tool in tools
        ]
        normalized_choice = _normalize_tool_choice(tool_choice, tools=formatted)
        if normalized_choice is not None:
            kwargs["tool_choice"] = normalized_choice
        return self.bind(tools=formatted, **kwargs)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        with traced_step(
            SPAN_LLM_GATEWAY_CALL,
            **{ATTR_MODEL: self.requested_model},
            **({ATTR_AGENT_ROLE: self.attribution_role} if self.attribution_role else {}),
        ) as span:
            started = time.perf_counter()
            result, served_model = self._generate_with_fallback(
                messages,
                stop=stop,
                run_manager=run_manager,
                **kwargs,
            )
            message = result.generations[0].message
            usage, served, cost, source = self._annotate(
                message, served_model=served_model, usage_payload=result.llm_output
            )
            cost, _source = self._priced(
                message, served=served, cost=cost, source=source, usage_payload=result.llm_output
            )
            record_model_call(
                span=span,
                call_kind="agent_completion",
                requested_model=self.requested_model,
                served_model=served,
                usage=usage,
                cost_cents=cost,
                duration_ms=(time.perf_counter() - started) * 1000.0,
                role=self.attribution_role,
            )
            return result

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        with traced_step(
            SPAN_LLM_GATEWAY_CALL,
            **{ATTR_MODEL: self.requested_model},
            **({ATTR_AGENT_ROLE: self.attribution_role} if self.attribution_role else {}),
        ) as span:
            started = time.perf_counter()
            result, served_model = await self._agenerate_with_fallback(
                messages,
                stop=stop,
                run_manager=run_manager,
                **kwargs,
            )
            message = result.generations[0].message
            usage, served, cost, source = self._annotate(
                message, served_model=served_model, usage_payload=result.llm_output
            )
            cost, _source = await self._apriced(
                message, served=served, cost=cost, source=source, usage_payload=result.llm_output
            )
            record_model_call(
                span=span,
                call_kind="agent_completion",
                requested_model=self.requested_model,
                served_model=served,
                usage=usage,
                cost_cents=cost,
                duration_ms=(time.perf_counter() - started) * 1000.0,
                role=self.attribution_role,
            )
            return result

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        with traced_step(
            SPAN_LLM_GATEWAY_CALL,
            **{ATTR_MODEL: self.requested_model},
            **({ATTR_AGENT_ROLE: self.attribution_role} if self.attribution_role else {}),
        ) as span:
            started = time.perf_counter()
            last_message: AIMessageChunk | None = None
            usage_message: AIMessageChunk | None = None
            for chunk in self._stream_with_fallback(
                messages,
                stop=stop,
                run_manager=run_manager,
                **kwargs,
            ):
                if isinstance(chunk.message, AIMessageChunk):
                    last_message = chunk.message
                    if chunk.message.usage_metadata is not None:
                        usage_message = chunk.message
                        self._annotate(chunk.message)
                yield chunk
            final = usage_message or last_message
            usage, served, cost, source = self._usage_and_cost(final)
            cost, _source = self._priced(final, served=served, cost=cost, source=source)
            record_model_call(
                span=span,
                call_kind="agent_stream",
                requested_model=self.requested_model,
                served_model=served,
                usage=usage,
                cost_cents=cost,
                duration_ms=(time.perf_counter() - started) * 1000.0,
                role=self.attribution_role,
            )

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        with traced_step(
            SPAN_LLM_GATEWAY_CALL,
            **{ATTR_MODEL: self.requested_model},
            **({ATTR_AGENT_ROLE: self.attribution_role} if self.attribution_role else {}),
        ) as span:
            started = time.perf_counter()
            last_message: AIMessageChunk | None = None
            usage_message: AIMessageChunk | None = None
            async for chunk in self._astream_with_fallback(
                messages,
                stop=stop,
                run_manager=run_manager,
                **kwargs,
            ):
                if isinstance(chunk.message, AIMessageChunk):
                    last_message = chunk.message
                    if chunk.message.usage_metadata is not None:
                        usage_message = chunk.message
                        self._annotate(chunk.message)
                yield chunk
            final = usage_message or last_message
            usage, served, cost, source = self._usage_and_cost(final)
            cost, _source = await self._apriced(final, served=served, cost=cost, source=source)
            record_model_call(
                span=span,
                call_kind="agent_stream",
                requested_model=self.requested_model,
                served_model=served,
                usage=usage,
                cost_cents=cost,
                duration_ms=(time.perf_counter() - started) * 1000.0,
                role=self.attribution_role,
            )

    def _generate_with_fallback(
        self,
        messages: list[BaseMessage],
        *,
        stop: list[str] | None,
        run_manager: CallbackManagerForLLMRun | None,
        **kwargs: Any,
    ) -> tuple[ChatResult, str]:
        first_error: Exception | None = None
        for attempt in range(1, _MAX_TRANSIENT_ATTEMPTS + 1):
            for index, (model, model_id) in enumerate(
                zip(self.models, self.model_ids, strict=True)
            ):
                try:
                    result = model._generate(
                        messages,
                        stop=stop,
                        run_manager=run_manager,
                        **kwargs,
                    )
                    return result, _served_model_from_result(result, fallback=model_id)
                except Exception as exc:
                    first_error = first_error or exc
                    if index != len(self.models) - 1:
                        continue
                    backoff = _transient_retry_backoff_s(exc, attempt)
                    if backoff is not None:
                        time.sleep(backoff)
                        break
                    if first_error is not exc:
                        raise exc from first_error
                    raise
        raise AssertionError("governed agent model requires at least one provider model")

    async def _agenerate_with_fallback(
        self,
        messages: list[BaseMessage],
        *,
        stop: list[str] | None,
        run_manager: AsyncCallbackManagerForLLMRun | None,
        **kwargs: Any,
    ) -> tuple[ChatResult, str]:
        first_error: Exception | None = None
        for attempt in range(1, _MAX_TRANSIENT_ATTEMPTS + 1):
            for index, (model, model_id) in enumerate(
                zip(self.models, self.model_ids, strict=True)
            ):
                try:
                    call = model._agenerate(
                        messages,
                        stop=stop,
                        run_manager=run_manager,
                        **kwargs,
                    )
                    result = (
                        await asyncio.wait_for(call, timeout=self.call_deadline_s)
                        if self.call_deadline_s is not None
                        else await call
                    )
                    return result, _served_model_from_result(result, fallback=model_id)
                except Exception as exc:
                    first_error = first_error or exc
                    if index != len(self.models) - 1:
                        continue
                    backoff = _transient_retry_backoff_s(exc, attempt)
                    if backoff is not None:
                        await asyncio.sleep(backoff)
                        break
                    if first_error is not exc:
                        raise exc from first_error
                    raise
        raise AssertionError("governed agent model requires at least one provider model")

    def _stream_with_fallback(
        self,
        messages: list[BaseMessage],
        *,
        stop: list[str] | None,
        run_manager: CallbackManagerForLLMRun | None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        first_error: Exception | None = None
        for attempt in range(1, _MAX_TRANSIENT_ATTEMPTS + 1):
            for index, (model, model_id) in enumerate(
                zip(self.models, self.model_ids, strict=True)
            ):
                yielded = False
                pending: ChatGenerationChunk | None = None
                try:
                    for chunk in model._stream(
                        messages,
                        stop=stop,
                        run_manager=run_manager,
                        **kwargs,
                    ):
                        if pending is not None:
                            _strip_model_keys(pending.message)
                            yielded = True
                            yield pending
                        pending = chunk
                    if pending is not None:
                        _stamp_answering_model(pending.message, fallback=model_id)
                        yielded = True
                        yield pending
                    return
                except Exception as exc:
                    # A partially consumed stream cannot be replayed: the consumer already holds
                    # chunks, so another attempt would duplicate them.  Surface it, as today.
                    if yielded:
                        raise
                    first_error = first_error or exc
                    if index != len(self.models) - 1:
                        continue
                    backoff = _transient_retry_backoff_s(exc, attempt)
                    if backoff is not None:
                        time.sleep(backoff)
                        break
                    if first_error is not exc:
                        raise exc from first_error
                    raise

    async def _astream_with_fallback(
        self,
        messages: list[BaseMessage],
        *,
        stop: list[str] | None,
        run_manager: AsyncCallbackManagerForLLMRun | None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        first_error: Exception | None = None
        for attempt in range(1, _MAX_TRANSIENT_ATTEMPTS + 1):
            for index, (model, model_id) in enumerate(
                zip(self.models, self.model_ids, strict=True)
            ):
                yielded = False
                pending: ChatGenerationChunk | None = None
                try:
                    async for chunk in _first_chunk_within(
                        model._astream(
                            messages,
                            stop=stop,
                            run_manager=run_manager,
                            **kwargs,
                        ),
                        self.first_token_timeout_s,
                    ):
                        if pending is not None:
                            _strip_model_keys(pending.message)
                            yielded = True
                            yield pending
                        pending = chunk
                    if pending is not None:
                        _stamp_answering_model(pending.message, fallback=model_id)
                        yielded = True
                        yield pending
                    return
                except Exception as exc:
                    # A partially consumed stream cannot be replayed: the consumer already holds
                    # chunks, so another attempt would duplicate them.  Surface it, as today.
                    if yielded:
                        raise
                    first_error = first_error or exc
                    if index != len(self.models) - 1:
                        continue
                    backoff = _transient_retry_backoff_s(exc, attempt)
                    if backoff is not None:
                        await asyncio.sleep(backoff)
                        break
                    if first_error is not exc:
                        raise exc from first_error
                    raise

    def _annotate(
        self,
        message: AIMessage | AIMessageChunk | BaseMessage,
        *,
        served_model: str | None = None,
        usage_payload: Mapping[str, Any] | None = None,
    ) -> tuple[TokenUsage, str, Decimal, CostSource]:
        usage, served, cost, source = self._usage_and_cost(
            message, served_model=served_model, usage_payload=usage_payload
        )
        self._stamp(message, served=served, cost=cost, source=source)
        return usage, served, cost, source

    def _stamp(
        self,
        message: AIMessage | AIMessageChunk | BaseMessage,
        *,
        served: str,
        cost: Decimal,
        source: CostSource,
    ) -> None:
        """Write this call's attribution onto the message. Idempotent — re-stamping after the
        generation lookup replaces the cost and its label, and nothing else."""
        message.response_metadata = {
            **message.response_metadata,
            _REQUESTED_MODEL_KEY: self.requested_model,
            _ANSWERING_MODEL_KEY: served,
            _COST_CENTS_KEY: str(cost),
            _COST_SOURCE_KEY: source,
            **({_ROLE_KEY: self.attribution_role} if self.attribution_role else {}),
        }

    def _needs_lookup(
        self, source: CostSource, message: BaseMessage | None, payload: Mapping[str, Any] | None
    ) -> str | None:
        """The generation id to ask about, or ``None`` when nothing should be asked.

        Lazy by construction: a response that already carried its own cost is never looked up, and
        neither is one for which there is no lookup or no provider id to ask about.
        """
        if source == "metered" or self.cost_lookup is None or message is None:
            return None
        return _generation_id(message, payload)

    def _priced(
        self,
        message: AIMessage | AIMessageChunk | BaseMessage | None,
        *,
        served: str,
        cost: Decimal,
        source: CostSource,
        usage_payload: Mapping[str, Any] | None = None,
    ) -> tuple[Decimal, CostSource]:
        """``cost``/``source`` after asking OpenRouter, when the response did not say (sync)."""
        generation_id = self._needs_lookup(source, message, usage_payload)
        if generation_id is None or self.cost_lookup is None:
            return cost, source
        looked_up = self.cost_lookup.cost_cents(generation_id)
        if looked_up is None:
            # The meter would not answer: keep whatever the price table said (``estimate``) or the
            # honest ``unpriced`` zero. Never a number we made up to fill the hole.
            return cost, source
        if message is not None:
            self._stamp(message, served=served, cost=looked_up, source="metered")
        return looked_up, "metered"

    async def _apriced(
        self,
        message: AIMessage | AIMessageChunk | BaseMessage | None,
        *,
        served: str,
        cost: Decimal,
        source: CostSource,
        usage_payload: Mapping[str, Any] | None = None,
    ) -> tuple[Decimal, CostSource]:
        """The async twin of :meth:`_priced` — the lookup is a network hop, so it is awaited
        rather than blocking the loop the agent graph is running on."""
        generation_id = self._needs_lookup(source, message, usage_payload)
        if generation_id is None or self.cost_lookup is None:
            return cost, source
        looked_up = await self.cost_lookup.acost_cents(generation_id)
        if looked_up is None:
            return cost, source
        if message is not None:
            self._stamp(message, served=served, cost=looked_up, source="metered")
        return looked_up, "metered"

    def _usage_and_cost(
        self,
        message: AIMessage | AIMessageChunk | BaseMessage | None,
        *,
        served_model: str | None = None,
        usage_payload: Mapping[str, Any] | None = None,
    ) -> tuple[TokenUsage, str, Decimal, CostSource]:
        """This call's tokens, the model that served it, what it cost, and who says so.

        ``usage_payload`` is the provider's own usage block as ``langchain_openai`` hands it back
        (``ChatResult.llm_output``). With ``usage.include`` asked for, OpenRouter puts the credits
        the call actually spent in ``token_usage["cost"]`` there, and a metered number always beats
        one we derive from a price sheet.
        """
        metadata = message.response_metadata if message is not None else {}
        served = str(
            served_model
            or metadata.get(_ANSWERING_MODEL_KEY)
            or metadata.get("model_name")
            or metadata.get("model")
            or self.requested_model
        )
        input_tokens = 0
        output_tokens = 0
        cached_tokens = 0
        if isinstance(message, AIMessage | AIMessageChunk):
            raw_usage = message.usage_metadata
            if raw_usage is not None:
                input_tokens = raw_usage["input_tokens"]
                output_tokens = raw_usage["output_tokens"]
                details = raw_usage.get("input_token_details") or {}
                cached_tokens = int(details.get("cache_read") or 0)
        usage = TokenUsage(
            prompt_tokens=input_tokens,
            completion_tokens=output_tokens,
            cached_prompt_tokens=cached_tokens,
        )
        reported = _reported_cost_cents(usage_payload, metadata)
        if reported is not None:
            return usage, served, reported, "metered"
        if served in self.gateway_config.prices:
            return usage, served, self.gateway_config.cost_cents(served, usage), "estimate"
        # No meter and no listed rate: zero, said out loud as a blank rather than as a measurement.
        return usage, served, Decimal(0), "unpriced"


#: The model requests whose refusals are logged (not the catalog or the cost meter).
_MODEL_REQUEST_PATHS = ("/chat/completions", "/responses")


def _refusal_fields(response: httpx.Response) -> dict[str, Any]:
    text = response.text if response.content else ""
    return {
        "status": response.status_code,
        "path": response.request.url.path,
        "should_retry": response.headers.get("x-should-retry"),
        "error": " ".join(text.split())[:1500],
    }


def _is_refused_model_request(response: httpx.Response) -> bool:
    return response.status_code >= 400 and response.request.url.path.endswith(_MODEL_REQUEST_PATHS)


def _log_provider_refusal(response: httpx.Response) -> None:
    if _is_refused_model_request(response):
        response.read()
        log.warning("gateway.provider_refused", **_refusal_fields(response))


async def _alog_provider_refusal(response: httpx.Response) -> None:
    if _is_refused_model_request(response):
        await response.aread()
        log.warning("gateway.provider_refused", **_refusal_fields(response))


def _with_refusal_log(client: Any | None, *, asynchronous: bool) -> Any:
    """The client a provider's models use, with the refusal log hooked in. An injected client keeps
    its own transport and settings. With none, the sync side gets the OpenAI SDK's own default
    client (thread-safe; the design agents call through it); the async side stays the SDK's own,
    unhooked, because one async client shared across event loops breaks."""
    hook = _alog_provider_refusal if asynchronous else _log_provider_refusal
    if client is None:
        if asynchronous:
            return None
        from openai import DefaultHttpxClient

        return DefaultHttpxClient(event_hooks={"response": [hook]})
    hooks = client.event_hooks
    if hook not in hooks.get("response", []):
        hooks["response"] = [*hooks.get("response", []), hook]
        client.event_hooks = hooks
    return client


class OpenRouterAgentModelProvider:
    """Build governed LangChain tool-calling models through the OpenRouter policy boundary."""

    def __init__(
        self,
        config: GatewayConfig,
        api_key: SecretStr,
        *,
        http_client: Any | None = None,
        http_async_client: Any | None = None,
    ) -> None:
        self._config = config
        self._api_key = api_key
        # Every model request goes through clients that log a refusal in the provider's own words
        # (_log_provider_refusal): the OpenAI client retries a refusal the provider marks retryable
        # and never surfaces it, so without this a slow turn's 400s had no reason anywhere.
        self._http_client = _with_refusal_log(http_client, asynchronous=False)
        self._http_async_client = _with_refusal_log(http_async_client, asynchronous=True)
        self._model_capabilities: dict[str, bool] | None = None
        # One store per provider: its Responses models keep each reply's usage block in it, and
        # the cost lookup of every model it builds reads from it first.
        self._reply_usage = ResponseUsage()

    def build(
        self,
        *,
        model_id: str,
        timeout_s: float,
        max_retries: int,
        max_output_tokens: int,
        temperature: float,
        role: str | None = None,
        call_deadline_s: float | None = None,
    ) -> BaseChatModel:
        """Build a bounded primary/fallback model with truthful answering-model attribution.

        ``role`` (P3.2) labels every usage record/span this instance produces — the design
        runtime builds one instance per trio role, so per-role attribution is structural.
        """

        if not model_id.strip():
            raise ValueError("model_id must be non-empty")
        if timeout_s <= 0 or timeout_s > self._config.timeout_s:
            raise ValueError(
                "agent model timeout must be positive and no greater than gateway policy"
            )
        if max_retries < 0 or max_retries > self._config.max_retries:
            raise ValueError("agent model retries must not exceed gateway policy")
        if max_output_tokens < 1:
            raise ValueError("max_output_tokens must be positive")
        if not 0 <= temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")

        # Primary, then the single fallback, then the chain (2026-10-04) — each model once.
        candidates = [model_id]
        for candidate in (self._config.fallback_model, *self._config.fallback_models):
            if candidate and candidate not in candidates:
                candidates.append(candidate)
        models = tuple(
            self._build_openrouter_model(
                model_id=candidate,
                timeout_s=timeout_s,
                max_retries=max_retries,
                max_output_tokens=max_output_tokens,
                temperature=temperature,
                role=role,
            )
            for candidate in candidates
        )
        return GovernedAgentChatModel(
            models=models,
            model_ids=tuple(candidates),
            requested_model=model_id,
            gateway_config=self._config,
            attribution_role=role,
            first_token_timeout_s=self._config.first_token_timeout_s,
            call_deadline_s=call_deadline_s,
            # The meter for the paths that do not carry a cost back. Built here because this is
            # where the key and the HTTP clients live; the model itself holds no credential.
            cost_lookup=_ReplyUsageFirst(
                self._reply_usage,
                OpenRouterGenerationCost(
                    base_url=self._config.base_url,
                    api_key=self._api_key,
                    http_client=self._http_client,
                    http_async_client=self._http_async_client,
                ),
            ),
        )

    def supports_image_input(self, model_id: str) -> bool | None:
        """Pre-spend vision capability from the provider's model catalog (P3.2).

        Replaces the design runtime's raw-key ``GET /models`` probe with a provider-owned
        seam. ``True``/``False`` from the catalog's ``architecture.input_modalities``;
        ``None`` when the model is not listed or the catalog is unreachable — the CALLER
        chooses how hard to fail (the design harness fails closed before any spend).
        The catalog is fetched once per provider instance.
        """
        if self._model_capabilities is None:
            import httpx

            try:
                client = self._http_client
                url = f"{self._config.base_url.rstrip('/')}/models"
                headers = {"Authorization": f"Bearer {self._api_key.get_secret_value()}"}
                if client is not None:
                    response = client.get(url, headers=headers)
                else:
                    response = httpx.get(url, headers=headers, timeout=self._config.timeout_s)
                response.raise_for_status()
                payload = response.json()
            except Exception:  # noqa: BLE001 - unreachable catalog = honest "unknown"
                return None
            capabilities: dict[str, bool] = {}
            for entry in payload.get("data", []):
                modalities = _catalog_input_modalities(entry)
                if modalities is None:
                    # Entry present but carries no modality metadata: honestly
                    # unknown — absent from the dict, NOT recorded as text-only.
                    continue
                capabilities[str(entry.get("id"))] = "image" in modalities
            self._model_capabilities = capabilities
        return self._model_capabilities.get(model_id)

    def _build_openrouter_model(
        self,
        *,
        model_id: str,
        timeout_s: float,
        max_retries: int,
        max_output_tokens: int,
        temperature: float,
        role: str | None = None,
    ) -> BaseChatModel:
        # OpenRouter's Responses API is stateless. Clue/DeepAgents therefore continues to replay
        # the complete durable message history and never uses ``previous_response_id``.
        reasoning = _reasoning_request(self._config, model_id=model_id, role=role)
        # P3.2: the OpenRouter economics knobs ride the request body (config, not code).
        extra_body: dict[str, Any] = {}
        if self._config.openrouter_provider_sort is not None:
            extra_body["provider"] = {"sort": self._config.openrouter_provider_sort}
        if self._config.openrouter_usage_include:
            extra_body["usage"] = {"include": True}
        if model_id.startswith("anthropic/"):
            # Anthropic caches only when asked; OpenRouter places this top-level breakpoint at the
            # end of the prompt on every call. xAI, OpenAI and Gemini cache on their own.
            extra_body["cache_control"] = {"type": "ephemeral"}
        if self._config.openrouter_chat_completions_fallback and not model_id.startswith("openai/"):
            # OpenRouter's ``/responses`` translation for non-OpenAI providers rejects the
            # platform conversation's array-shaped message content (grok-4.6 400s
            # ``invalid_union: expected string, received array`` on the tool-result follow-up —
            # live, 2026-08-27; the design deepagent's plain-string turns pass, which is why
            # this is config-scoped, not unconditional). On chat-completions the reasoning
            # request rides ``extra_body`` — Responses-only keys (``summary``) stripped.
            if reasoning is not None:
                chat_reasoning = {
                    k: v for k, v in reasoning.items() if k in ("effort", "max_tokens")
                }
                if chat_reasoning:
                    extra_body["reasoning"] = chat_reasoning
            return OpenRouterChatModel(  # type: ignore[call-arg]
                model=model_id,
                api_key=self._api_key,
                base_url=self._config.base_url,
                timeout=timeout_s,
                max_retries=max_retries,
                max_tokens=max_output_tokens,
                temperature=temperature,
                stream_usage=True,
                use_responses_api=False,
                http_client=self._http_client,
                http_async_client=self._http_async_client,
                extra_body=extra_body or None,
            )
        # Runtime aliases are intentionally friendlier than ChatOpenAI's generated static type.
        return OpenRouterResponsesModel(  # type: ignore[call-arg]
            model=model_id,
            api_key=self._api_key,
            base_url=self._config.base_url,
            timeout=timeout_s,
            max_retries=max_retries,
            max_tokens=max_output_tokens,
            temperature=temperature,
            stream_usage=True,
            use_responses_api=True,
            output_version="responses/v1",
            http_client=self._http_client,
            http_async_client=self._http_async_client,
            reasoning=reasoning,
            extra_body=extra_body or None,
            usage=self._reply_usage,
        )


def _reasoning_request(
    config: GatewayConfig, *, model_id: str, role: str | None = None
) -> dict[str, Any] | None:
    """The provider ``reasoning`` block for one governed agent model — config first, baseline else.

    **The per-role environment override (founder ruling 2026-08-31).** When the call is built
    for a named role and ``<ROLE>_AGENT_MODEL_EFFORT`` is set non-blank (e.g.
    ``HEAD_OF_ABM_AGENT_MODEL_EFFORT=high``), that effort replaces whatever effort the config
    or baseline chose — the deployment names the effort the way ``<ROLE>_AGENT_MODEL`` names
    the model, with no new profile version. Blank/unset changes nothing below.

    **The baseline (no config).** The production Head-of-ABM model
    ``openai/gpt-5.6-terra`` uses reasoning ``high``. Other GPT-5.6 routes retain reasoning
    ``none`` and every non-GPT-5.6 model asks for nothing. The explicit Responses shape keeps the
    policy inspectable and overrideable without returning to Chat params.

    **The override (``GatewayConfig.agent_reasoning``).** Set only by ``default_gateway_config``
    under the dev-only ``CLUE_CHAT_REASONING_TRACE_MODE=raw`` lens, which a production process is
    refused at startup. It replaces the baseline wholesale — including GPT-5.6's ``effort: none``,
    which is the point: a model told to spend no reasoning effort has no reasoning to expose.

    **What actually comes back is provider-dependent, and this is the honest account.** The request
    is uniform; the response is not.

    * **OpenAI o-series / GPT-5.x reasoning models.** The Responses API never returns the private
      chain-of-thought. With ``summary`` requested it returns a model-written *summary* of it, as
      ``response.reasoning_summary_text.delta`` chunks that
      ``langchain_openai`` surfaces as ``reasoning`` content blocks. That summary is what the dev
      lens streams. Without ``summary`` the request still reasons and emits nothing observable.
    * **Anthropic models (via OpenRouter).** Extended thinking returns thinking blocks, and
      OpenRouter maps them onto the same reasoning items — so the lens shows the thinking text
      rather than a summary. ``max_tokens`` is the thinking budget these models actually read.
    * **Plain (non-reasoning) models.** Nothing. The block is accepted and ignored, or ignored and
      dropped, depending on the route; either way no reasoning content exists to stream and the
      ``reasoning`` part stays exactly the safe status card it is in ``summary`` mode.

    Nothing downstream may assume a trace arrived. An empty reasoning card is the correct output for
    a model with no reasoning to show, in the same way an empty claim is the correct output for a
    field no source can answer.
    """

    configured = config.agent_reasoning
    if configured is not None:
        payload = configured.as_provider_payload()
        reasoning = dict(payload) if payload else None
    elif model_id == "openai/gpt-5.6-terra":
        reasoning = {"effort": "high"}
    else:
        reasoning = {"effort": "none"} if model_id.startswith("openai/gpt-5.6") else None
    if role:
        effort = os.environ.get(f"{role.upper()}_AGENT_MODEL_EFFORT", "").strip()
        if effort:
            reasoning = dict(reasoning or {})
            reasoning["effort"] = effort
    return reasoning


def _served_model_from_result(result: ChatResult, *, fallback: str) -> str:
    output = result.llm_output or {}
    return str(output.get("model_name") or output.get("model") or fallback)


def _reported_cost_cents(*sources: Mapping[str, Any] | None) -> Decimal | None:
    """The provider's own cost for this call, in cents, or ``None`` when it did not report one.

    OpenRouter answers ``usage.include`` with ``usage.cost`` in USD credits. ``langchain_openai``
    carries that block through verbatim on the chat-completions path as
    ``llm_output["token_usage"]``; the streaming path drops the extra keys, which is why the price
    sheet remains the fallback rather than being retired. The value is read through ``str`` so it
    stays exact ``Decimal`` arithmetic even when the JSON parser handed us a float.
    """
    for source in sources:
        if not source:
            continue
        token_usage = source.get("token_usage")
        if not isinstance(token_usage, Mapping):
            continue
        charged = openrouter_charged_usd(token_usage)
        if charged is not None:
            return charged * 100
    return None


def _normalize_tool_choice(
    tool_choice: dict[str, Any] | str | bool | None,
    *,
    tools: Sequence[dict[str, Any]],
) -> dict[str, Any] | str | None:
    """Normalize LangChain's provider-neutral choices to the OpenAI Responses contract.

    ``create_agent`` deliberately binds ``ToolStrategy`` schemas with ``"any"``.  OpenAI and
    OpenRouter spell the same requirement ``"required"``.  ``ChatOpenAI.bind_tools`` normally
    performs this conversion, along with converting an exact tool name to the function-choice
    object, but this governed fallback wrapper binds the already-formatted tools to itself so that
    retries remain under one authority.  The translation therefore belongs here, at that same
    provider boundary; forwarding ``"any"`` makes a live Responses request invalid before the
    model or any governed tool can run.
    """

    if tool_choice is None or tool_choice is False:
        return None
    if tool_choice is True:
        return "required"
    if isinstance(tool_choice, dict):
        return tool_choice
    if tool_choice == "any":
        return "required"
    if tool_choice in {"auto", "none", "required"}:
        return tool_choice

    tool_names = {
        str(function["name"])
        for tool in tools
        if isinstance((function := tool.get("function")), dict)
        and isinstance(function.get("name"), str)
    }
    if tool_choice in tool_names:
        return {"type": "function", "function": {"name": tool_choice}}
    raise ValueError(f"tool_choice names no bound function: {tool_choice!r}")


_MODEL_KEYS: tuple[str, ...] = ("model_name", "model", _ANSWERING_MODEL_KEY)


def _strip_model_keys(message: BaseMessage) -> None:
    """LangChain's chunk merge concatenates equal string metadata, so only ONE chunk of a stream
    may carry the model keys (the last, which is the provider's truthful one)."""
    metadata = message.response_metadata
    if any(key in metadata for key in _MODEL_KEYS):
        message.response_metadata = {k: v for k, v in metadata.items() if k not in _MODEL_KEYS}


def _stamp_answering_model(message: BaseMessage, *, fallback: str) -> None:
    metadata = message.response_metadata
    served = str(
        metadata.get(_ANSWERING_MODEL_KEY)
        or metadata.get("model_name")
        or metadata.get("model")
        or fallback
    )
    message.response_metadata = {**metadata, _ANSWERING_MODEL_KEY: served}
