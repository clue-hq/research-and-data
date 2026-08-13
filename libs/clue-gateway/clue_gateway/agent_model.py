"""Governed OpenRouter Responses model construction and attribution for C6."""

from __future__ import annotations

import re
import time
from collections.abc import AsyncIterator, Iterator, Sequence
from decimal import Decimal
from typing import Any, cast

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
from pydantic import ConfigDict, SecretStr, model_validator

from clue_config.gateway import GatewayConfig
from clue_core.gateway import TokenUsage
from clue_gateway.tracing import record_model_call
from clue_obs.otel import ATTR_AGENT_ROLE, ATTR_MODEL, SPAN_LLM_GATEWAY_CALL, traced_step

__all__ = [
    "GovernedAgentChatModel",
    "OpenRouterAgentModelProvider",
    "provider_compatible_tool_schema",
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


_REQUESTED_MODEL_KEY = "clue_requested_model"
_ANSWERING_MODEL_KEY = "clue_answering_model"
_COST_CENTS_KEY = "clue_cost_cents"
_ROLE_KEY = "clue_role"


class GovernedAgentChatModel(BaseChatModel):
    """Provider model(s) wrapped with fallback, usage/cost metadata, tracing, and tool binding."""

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
            usage, served, cost = self._annotate(message, served_model=served_model)
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
            usage, served, cost = self._annotate(message, served_model=served_model)
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
            usage, served, cost = self._usage_and_cost(usage_message or last_message)
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
            usage, served, cost = self._usage_and_cost(usage_message or last_message)
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
        for index, (model, model_id) in enumerate(zip(self.models, self.model_ids, strict=True)):
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
                if index == len(self.models) - 1:
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
        for index, (model, model_id) in enumerate(zip(self.models, self.model_ids, strict=True)):
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
                if index == len(self.models) - 1:
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
        for index, (model, model_id) in enumerate(zip(self.models, self.model_ids, strict=True)):
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
                if yielded:
                    raise
                first_error = first_error or exc
                if index == len(self.models) - 1:
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
        for index, (model, model_id) in enumerate(zip(self.models, self.model_ids, strict=True)):
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
                if yielded:
                    raise
                first_error = first_error or exc
                if index == len(self.models) - 1:
                    if first_error is not exc:
                        raise exc from first_error
                    raise

    def _annotate(
        self,
        message: AIMessage | AIMessageChunk | BaseMessage,
        *,
        served_model: str | None = None,
    ) -> tuple[TokenUsage, str, Decimal]:
        usage, served, cost = self._usage_and_cost(message, served_model=served_model)
        message.response_metadata = {
            **message.response_metadata,
            _REQUESTED_MODEL_KEY: self.requested_model,
            _ANSWERING_MODEL_KEY: served,
            _COST_CENTS_KEY: str(cost),
            **({_ROLE_KEY: self.attribution_role} if self.attribution_role else {}),
        }
        return usage, served, cost

    def _usage_and_cost(
        self,
        message: AIMessage | AIMessageChunk | BaseMessage | None,
        *,
        served_model: str | None = None,
    ) -> tuple[TokenUsage, str, Decimal]:
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
        return usage, served, self.gateway_config.cost_cents(served, usage)


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
                    response = httpx.get(url, headers=headers, timeout=30.0)
                response.raise_for_status()
                payload = response.json()
            except Exception:  # noqa: BLE001 - unreachable catalog = honest "unknown"
                return None
            capabilities: dict[str, bool] = {}
            for entry in payload.get("data", []):
                modalities = (entry.get("architecture") or {}).get("input_modalities") or []
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
    ) -> BaseChatModel:
        # OpenRouter's Responses API is stateless. Clue/DeepAgents therefore continues to replay
        # the complete durable message history and never uses ``previous_response_id``.
        reasoning = _reasoning_request(self._config, model_id=model_id)
        # P3.2: the OpenRouter economics knobs ride the request body (config, not code).
        extra_body: dict[str, Any] = {}
        if self._config.openrouter_provider_sort is not None:
            extra_body["provider"] = {"sort": self._config.openrouter_provider_sort}
        if self._config.openrouter_usage_include:
            extra_body["usage"] = {"include": True}
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


def _reasoning_request(config: GatewayConfig, *, model_id: str) -> dict[str, Any] | None:
    """The provider ``reasoning`` block for one governed agent model — config first, baseline else.

    **The baseline (no config).** GPT-5.6's current governed default is reasoning ``none``,
    expressed in the native Responses shape so it can be tuned by eval-backed policy without
    returning to Chat params. Every other model asks for nothing.

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
        return dict(payload) if payload else None
    return {"effort": "none"} if model_id.startswith("openai/gpt-5.6") else None


def _served_model_from_result(result: ChatResult, *, fallback: str) -> str:
    output = result.llm_output or {}
    return str(output.get("model_name") or output.get("model") or fallback)


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
