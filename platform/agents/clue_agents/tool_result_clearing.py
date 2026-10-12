"""Clear processed tool results in batches, and strip the read gutter, for research agents.

Production 2026-10-06: a research conversation grew from ~16k to ~200k tokens and every model
call re-sent all of it; re-sending was 82% of the model cost, and the configured compaction
(90% of a 500k window) never fired. Clearing old tool results keeps the conversation small.

The cut is *stateless and quantised*: once the conversation passes ``trigger`` tokens, the
oldest eligible results up to ``min(size - target, start of the newest two rounds) // step *
step`` tokens of history are replaced by a short placeholder (``step = trigger - target``).
The history is append-only, so the cut moves only in whole steps; between moves the prompt
prefix is byte-identical and stays in the provider's cache. LangChain's ``ClearToolUsesEdit``
instead clears "all but the newest N" on every call, which moves the boundary each round and
bills everything after it uncached.

Sizes are the model's real tokens (:mod:`clue_agents.context_tokens`), calibrated by the
provider's count of the conversation's first counted request (a rate fixed for the conversation,
so the cut never moves back), and include the system prompt and tool schemas, which every request
carries.

Only the model request is edited; the checkpointed history keeps every result, so a resumed or
continued turn reproduces the same request.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage

from clue_agents.context_tokens import estimate_tokens, real_token_ratio

__all__ = [
    "BatchedToolResultClearing",
    "plan_clearing",
    "strip_read_gutter",
]

#: Reads never cleared: the agent's own instructions would otherwise be re-read.
KEEP_PATHS: tuple[str, ...] = ("/.deepagent/skills/",)
#: Reads whose deepagents line-number gutter is stripped.
GUTTER_PATHS: tuple[str, ...] = ("/research/", "/evidence/", "/.deepagent/skills/")
#: The newest rounds are never cleared: the model is still working with them.
PROTECTED_ROUNDS = 2

_GUTTER = re.compile(r"(?m)^[ \t]*\d+(?:\.\d+)?\t")


def placeholder(path: str | None) -> str:
    if path:
        return (
            "[Earlier result removed to keep the conversation small. "
            f"Re-read {path} if you need it.]"
        )
    return (
        "[Earlier result removed to keep the conversation small. Re-run the tool if you need it.]"
    )


def strip_read_gutter(content: str) -> str:
    """Remove deepagents' ``cat -n`` line-number column (and ``N.M`` continuation markers)."""
    return _GUTTER.sub("", content)


def _calls(messages: Sequence[BaseMessage]) -> dict[str, dict[str, Any]]:
    calls: dict[str, dict[str, Any]] = {}
    for message in messages:
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                calls[str(call.get("id"))] = dict(call)
    return calls


def _path(call: dict[str, Any] | None) -> str | None:
    args = (call or {}).get("args") or {}
    value = args.get("file_path") or args.get("path") or args.get("source_path")
    return str(value) if value else None


def plan_clearing(
    messages: Sequence[BaseMessage],
    *,
    trigger: int,
    target: int,
    keep_paths: tuple[str, ...] = KEEP_PATHS,
    system_message: SystemMessage | None = None,
    tools: Sequence[Any] | None = None,
) -> list[str]:
    """The ``tool_call_id``s whose results the model should see as a placeholder, oldest first."""
    if trigger <= target:
        raise ValueError("trigger must exceed target")
    # The oldest counted reply's rate, fixed for the conversation: the newest one drifts as tool
    # output fills the context (run 6: 1.08 -> 0.93), and re-scaling every size by it moved the
    # result at the cut back and forth. Each flip changed a message far behind GPT-5.6's cache
    # lookup points and re-wrote the whole context (run 6: 11 misses, ~$3.70). With fixed sizes
    # and an append-only history the cut only moves forward.
    ratio = real_token_ratio(messages, newest=False) or 1.0
    sizes = [estimate_tokens([m]) * ratio for m in messages]
    fixed = (
        estimate_tokens([system_message] if system_message is not None else [], tools) * ratio
        if system_message is not None or tools
        else 0.0
    )
    total = fixed + sum(sizes)
    if total <= trigger:
        return []
    step = trigger - target
    # The newest PROTECTED_ROUNDS model turns, and everything after them, stay whole. The
    # protection is folded into the cut *before* quantising, so the cut still only moves in
    # steps when the protected rounds slide forward over uneven history.
    ai_positions = [i for i, m in enumerate(messages) if isinstance(m, AIMessage)]
    protected_from = ai_positions[-PROTECTED_ROUNDS] if len(ai_positions) >= PROTECTED_ROUNDS else 0
    cut = min(total - target, sum(sizes[:protected_from])) // step * step
    calls = _calls(messages)
    cleared: list[str] = []
    end = 0
    for message, size in zip(messages, sizes, strict=True):
        end += size
        if end > cut:
            break
        if not isinstance(message, ToolMessage) or message.status == "error":
            continue
        path = _path(calls.get(message.tool_call_id))
        if path and any(path.startswith(prefix) for prefix in keep_paths):
            continue
        cleared.append(message.tool_call_id)
    return cleared


class BatchedToolResultClearing(AgentMiddleware[Any, Any, Any]):
    """Recipe-26 research middleware: batched result clearing plus the read-gutter strip."""

    def __init__(self, *, trigger_tokens: int, target_tokens: int) -> None:
        super().__init__()
        if trigger_tokens <= target_tokens:
            raise ValueError("trigger_tokens must exceed target_tokens")
        self.trigger_tokens = trigger_tokens
        self.target_tokens = target_tokens

    async def awrap_model_call(self, request: Any, handler: Callable[[Any], Awaitable[Any]]) -> Any:
        messages = list(request.messages)
        cleared = set(
            plan_clearing(
                messages,
                trigger=self.trigger_tokens,
                target=self.target_tokens,
                system_message=getattr(request, "system_message", None),
                tools=getattr(request, "tools", None),
            )
        )
        if not cleared:
            return await handler(request)
        calls = _calls(messages)
        edited = [
            m.model_copy(
                update={"content": placeholder(_path(calls.get(m.tool_call_id))), "artifact": None}
            )
            if isinstance(m, ToolMessage) and m.tool_call_id in cleared
            else m
            for m in messages
        ]
        return await handler(request.override(messages=edited))

    async def awrap_tool_call(self, request: Any, handler: Callable[[Any], Awaitable[Any]]) -> Any:
        result = await handler(request)
        call = getattr(request, "tool_call", None) or {}
        if call.get("name") != "read_file" or not isinstance(result, ToolMessage):
            return result
        path = _path(call)
        if not path or not any(path.startswith(prefix) for prefix in GUTTER_PATHS):
            return result
        if not isinstance(result.content, str):
            return result
        return result.model_copy(update={"content": strip_read_gutter(result.content)})
