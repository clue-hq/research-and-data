"""Governed OpenRouter tool-calling model construction and attribution for C6."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Iterator, Sequence
from decimal import Decimal
from typing import Any

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
from clue_obs.otel import ATTR_MODEL, SPAN_LLM_GATEWAY_CALL, traced_step

__all__ = ["GovernedAgentChatModel", "OpenRouterAgentModelProvider"]

_REQUESTED_MODEL_KEY = "clue_requested_model"
_ANSWERING_MODEL_KEY = "clue_answering_model"
_COST_CENTS_KEY = "clue_cost_cents"


class GovernedAgentChatModel(BaseChatModel):
    """Provider model(s) wrapped with fallback, usage/cost metadata, tracing, and tool binding."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    models: tuple[BaseChatModel, ...]
    model_ids: tuple[str, ...]
    requested_model: str
    gateway_config: GatewayConfig

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
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Runnable[Any, AIMessage]:
        """Bind standard tool schemas while keeping calls inside this governed wrapper."""

        formatted = [convert_to_openai_tool(tool) for tool in tools]
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice
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
        if isinstance(message, AIMessage | AIMessageChunk):
            raw_usage = message.usage_metadata
            if raw_usage is not None:
                input_tokens = raw_usage["input_tokens"]
                output_tokens = raw_usage["output_tokens"]
        usage = TokenUsage(
            prompt_tokens=input_tokens,
            completion_tokens=output_tokens,
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

    def build(
        self,
        *,
        model_id: str,
        timeout_s: float,
        max_retries: int,
        max_output_tokens: int,
        temperature: float,
    ) -> BaseChatModel:
        """Build a bounded primary/fallback model with truthful answering-model attribution."""

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
        )

    def _build_openrouter_model(
        self,
        *,
        model_id: str,
        timeout_s: float,
        max_retries: int,
        max_output_tokens: int,
        temperature: float,
    ) -> BaseChatModel:
        # Runtime aliases are intentionally friendlier than ChatOpenAI's generated static type.
        return ChatOpenAI(  # type: ignore[call-arg]
            model=model_id,
            api_key=self._api_key,
            base_url=self._config.base_url,
            timeout=timeout_s,
            max_retries=max_retries,
            max_completion_tokens=max_output_tokens,
            temperature=temperature,
            stream_usage=True,
            http_client=self._http_client,
            http_async_client=self._http_async_client,
        )


def _served_model_from_result(result: ChatResult, *, fallback: str) -> str:
    output = result.llm_output or {}
    return str(output.get("model_name") or output.get("model") or fallback)


def _stamp_answering_model(message: BaseMessage, *, fallback: str) -> None:
    metadata = message.response_metadata
    served = str(
        metadata.get(_ANSWERING_MODEL_KEY)
        or metadata.get("model_name")
        or metadata.get("model")
        or fallback
    )
    message.response_metadata = {**metadata, _ANSWERING_MODEL_KEY: served}
