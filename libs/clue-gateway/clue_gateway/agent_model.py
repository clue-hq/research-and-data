"""Governed OpenRouter Responses model construction and attribution for C6."""

from __future__ import annotations

import asyncio
import os
import re
import time
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any, cast

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
from langchain_openai import ChatOpenAI
from openai import APIConnectionError
from pydantic import ConfigDict, SecretStr, model_validator

from clue_config.gateway import GatewayConfig
from clue_core.gateway import TokenUsage
from clue_gateway.metadata import (
    ANSWERING_MODEL_KEY,
    COST_CENTS_KEY,
    COST_SOURCE_KEY,
    REQUESTED_MODEL_KEY,
    ROLE_KEY,
    CostSource,
)
from clue_gateway.tracing import record_model_call
from clue_obs.otel import ATTR_AGENT_ROLE, ATTR_MODEL, SPAN_LLM_GATEWAY_CALL, traced_step

__all__ = [
    "ANSWERING_MODEL_KEY",
    "COST_CENTS_KEY",
    "COST_SOURCE_KEY",
    "CostSource",
    "GovernedAgentChatModel",
    "OpenRouterAgentModelProvider",
    "provider_compatible_tool_schema",
    "transient_upstream_failure",
    "unsupported_schema_pattern",
]

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
        return code in _TRANSIENT_RESPONSE_ERROR_CODES
    status = getattr(error, "status_code", None)
    if status is None:
        status = getattr(getattr(error, "response", None), "status_code", None)
    return isinstance(status, int) and (status >= 500 or status in _TRANSIENT_STATUS_CODES)


def _response_error_code(argument: object) -> str | None:
    """The Responses ``error.code`` an exception argument carries, if it is one."""

    if isinstance(argument, Mapping):
        code = argument.get("code")
    else:
        code = getattr(argument, "code", None)
    return code if isinstance(code, str) else None


def _transient_retry_backoff_s(error: Exception, attempt: int) -> float | None:
    """Backoff before the next attempt, or ``None`` when this failure must surface as-is."""

    if attempt >= _MAX_TRANSIENT_ATTEMPTS or not transient_upstream_failure(error):
        return None
    return _TRANSIENT_BACKOFF_S[attempt - 1]


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
            usage, served, cost, _source = self._annotate(
                message, served_model=served_model, usage_payload=result.llm_output
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
            usage, served, cost, _source = self._annotate(
                message, served_model=served_model, usage_payload=result.llm_output
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
            usage, served, cost, _source = self._usage_and_cost(usage_message or last_message)
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
            usage, served, cost, _source = self._usage_and_cost(usage_message or last_message)
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
                    result = await model._agenerate(
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
                try:
                    for chunk in model._stream(
                        messages,
                        stop=stop,
                        run_manager=run_manager,
                        **kwargs,
                    ):
                        yielded = True
                        _stamp_answering_model(chunk.message, fallback=model_id)
                        yield chunk
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
                try:
                    async for chunk in model._astream(
                        messages,
                        stop=stop,
                        run_manager=run_manager,
                        **kwargs,
                    ):
                        yielded = True
                        _stamp_answering_model(chunk.message, fallback=model_id)
                        yield chunk
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
        message.response_metadata = {
            **message.response_metadata,
            _REQUESTED_MODEL_KEY: self.requested_model,
            _ANSWERING_MODEL_KEY: served,
            _COST_CENTS_KEY: str(cost),
            _COST_SOURCE_KEY: source,
            **({_ROLE_KEY: self.attribution_role} if self.attribution_role else {}),
        }
        return usage, served, cost, source

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
        self._http_client = http_client
        self._http_async_client = http_async_client
        self._model_capabilities: dict[str, bool] | None = None

    def build(
        self,
        *,
        model_id: str,
        timeout_s: float,
        max_retries: int,
        max_output_tokens: int,
        temperature: float,
        role: str | None = None,
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

        candidates = [model_id]
        if self._config.fallback_model and self._config.fallback_model != model_id:
            candidates.append(self._config.fallback_model)
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
            return ChatOpenAI(  # type: ignore[call-arg]
                model=model_id,
                api_key=self._api_key,
                base_url=self._config.base_url,
                timeout=timeout_s,
                max_retries=max_retries,
                max_tokens=max_output_tokens,
                temperature=temperature,
                stream_usage=True,
                http_client=self._http_client,
                http_async_client=self._http_async_client,
                extra_body=extra_body or None,
            )
        # Runtime aliases are intentionally friendlier than ChatOpenAI's generated static type.
        return ChatOpenAI(  # type: ignore[call-arg]
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
        cost = token_usage.get("cost")
        if cost is None or isinstance(cost, bool) or not isinstance(cost, int | float | str):
            continue
        try:
            return Decimal(str(cost)) * 100
        except InvalidOperation:
            continue
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


def _stamp_answering_model(message: BaseMessage, *, fallback: str) -> None:
    metadata = message.response_metadata
    served = str(
        metadata.get(_ANSWERING_MODEL_KEY)
        or metadata.get("model_name")
        or metadata.get("model")
        or fallback
    )
    message.response_metadata = {**metadata, _ANSWERING_MODEL_KEY: served}
