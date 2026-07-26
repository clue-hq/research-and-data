"""Provider-neutral deterministic agent-model test adapter."""

from __future__ import annotations

import threading
from collections.abc import Sequence
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from pydantic import ConfigDict, PrivateAttr

__all__ = ["ScriptedAgentChatModel"]


class ScriptedAgentChatModel(BaseChatModel):
    """Return an exact sequence of AI messages without network access or hidden behavior."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    responses: tuple[AIMessage, ...]
    repeat_last: bool = False
    _cursor: int = PrivateAttr(default=0)
    _lock: threading.Lock = PrivateAttr(default_factory=threading.Lock)

    @property
    def _llm_type(self) -> str:
        return "clue-scripted-agent"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {
            "response_count": len(self.responses),
            "repeat_last": self.repeat_last,
        }

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Any],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Runnable[Any, AIMessage]:
        # The scripted response already contains the exact desired tool call. Binding is retained
        # in runnable kwargs so framework construction follows the production model shape.
        return self.bind(
            scripted_bound_tool_count=len(tools),
            scripted_tool_choice=tool_choice,
            **kwargs,
        )

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        del messages, stop, run_manager, kwargs
        with self._lock:
            if not self.responses:
                raise RuntimeError("scripted agent model has no responses")
            if self._cursor >= len(self.responses):
                if not self.repeat_last:
                    raise RuntimeError("scripted agent model response sequence is exhausted")
                response = self.responses[-1]
            else:
                response = self.responses[self._cursor]
                self._cursor += 1
        return ChatResult(generations=[ChatGeneration(message=response)])
