"""Preserve OpenRouter extensions at the existing, pinned ChatOpenAI boundary.

ChatOpenAI deliberately discards third-party reasoning. These conversion hooks retain
only provider metadata; transport, tools, retries and resource cleanup remain upstream.
Do not use this adapter for the Responses route.
"""

from typing import Any

from langchain_core.language_models import LanguageModelInput
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_openai import ChatOpenAI
from openai import BaseModel


def _retain_reasoning(message: BaseMessage, wire: dict[str, Any]) -> None:
    if not isinstance(message, AIMessage | AIMessageChunk):
        return
    # The two scalar names are aliases, not separate pieces of a trace.
    for name in ("reasoning_content", "reasoning"):
        value = wire.get(name)
        if isinstance(value, str) and value:
            message.additional_kwargs["reasoning_content"] = value
            break
    details = wire.get("reasoning_details")
    if isinstance(details, list):
        # Includes encrypted continuation data. The display extractor allowlists text.
        message.additional_kwargs["reasoning_details"] = details


class OpenRouterChatModel(ChatOpenAI):
    def _convert_chunk_to_generation_chunk(
        self,
        chunk: dict[str, Any],
        default_chunk_class: type,
        base_generation_info: dict[str, Any] | None,
    ) -> ChatGenerationChunk | None:
        result = super()._convert_chunk_to_generation_chunk(
            chunk, default_chunk_class, base_generation_info
        )
        if result is None:
            return None
        choices = chunk.get("choices") or []
        if choices and isinstance(choices[0].get("delta"), dict):
            _retain_reasoning(result.message, choices[0]["delta"])
        metadata = result.message.response_metadata
        metadata["model_provider"] = "openrouter"
        if chunk.get("id"):
            metadata["id"] = chunk["id"]
        if chunk.get("usage"):
            metadata["token_usage"] = chunk["usage"]
        return result

    def _create_chat_result(
        self,
        response: dict[str, Any] | BaseModel,
        generation_info: dict[str, Any] | None = None,
    ) -> ChatResult:
        result = super()._create_chat_result(response, generation_info)
        wire = response if isinstance(response, dict) else response.model_dump()
        for generation, choice in zip(result.generations, wire["choices"], strict=True):
            _retain_reasoning(generation.message, choice["message"])
        return result

    def _get_request_payload(
        self,
        input_: LanguageModelInput,
        *,
        stop: list[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)
        for message, wire in zip(
            self._convert_input(input_).to_messages(), payload["messages"], strict=True
        ):
            if isinstance(message, AIMessage):
                details = message.additional_kwargs.get("reasoning_details")
                if isinstance(details, list):
                    wire["reasoning_details"] = details
                elif isinstance(message.additional_kwargs.get("reasoning_content"), str):
                    wire["reasoning"] = message.additional_kwargs["reasoning_content"]
        return payload
