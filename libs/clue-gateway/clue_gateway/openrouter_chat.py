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
        # Meta's Muse Spark 1.3 endpoint currently rejects forced tool choices.
        # Keep the offered surface restrictive for named/disabled choices; the
        # governed runtime still requires and validates finalize_turn before success.
        # For `required`, auto cannot force a call: the runtime's bounded plain-text
        # recovery remains responsible for handling a model that stops without one.
        if payload.get("model") == "meta/muse-spark-1.3":
            choice = payload.get("tool_choice")
            if choice == "none":
                payload.pop("tools", None)
                payload.pop("tool_choice", None)
            elif isinstance(choice, dict):
                name = choice.get("function", {}).get("name")
                selected = [
                    tool
                    for tool in payload.get("tools", [])
                    if tool.get("function", {}).get("name") == name and name
                ]
                if len(selected) != 1:
                    raise ValueError("Muse named tool choice must match exactly one bound function")
                payload["tools"] = selected
                payload["tool_choice"] = "auto"
            elif choice in ("required", "any"):
                payload["tool_choice"] = "auto"
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
