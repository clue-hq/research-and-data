"""Provider-neutral deterministic agent-model test adapter.

Holds :class:`ScriptedAgentChatModel` — a fake ``BaseChatModel`` that replays canned
``AIMessage`` responses so agent runtime tests never need a live LLM.
"""

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
    """Deterministic fake chat model for agent/runtime tests (not used in production).

    Stands in for a live provider (e.g. OpenRouter) so the deepagent loop can be exercised
    without network calls or model nondeterminism. Callers pass the exact ``AIMessage``
    sequence they want the "LLM" to emit — including any ``tool_calls`` — and each
    ``invoke`` / ``ainvoke`` returns the next message in order.

    ``bind_tools`` is a no-op for tool *selection*: production code still calls it when
    building the agent, so this stub accepts the call to keep the construction path
    identical, but the scripted messages already carry the tool calls to execute.
    """

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
        """Accept tool binding so agent construction matches production; ignore schemas.

        Real models use the bound schemas to decide tool calls. Here the next scripted
        ``AIMessage`` already contains the desired ``tool_calls``, so we only record that
        binding happened (for identifying params / runnable config).
        """
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
