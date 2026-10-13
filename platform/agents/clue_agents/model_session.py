"""Name each agent conversation on its model calls, so the provider keeps it on one cache.

Run 3 (2026-10-09): ten Grok calls re-sent a byte-identical prompt and still paid full price,
because consecutive calls of one conversation landed on servers that did not hold its cache.
OpenRouter routes every request carrying the same ``x-session-id`` to the provider that served
the conversation before (falling back to the next provider if that one is down), for every model.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware

__all__ = ["SESSION_HEADER", "ModelSessionAffinity"]

SESSION_HEADER = "x-session-id"


class ModelSessionAffinity(AgentMiddleware[Any, Any, Any]):
    """Send ``session_id`` as OpenRouter's ``x-session-id`` header on every model call."""

    def __init__(self, session_id: str) -> None:
        super().__init__()
        self.session_id = session_id

    async def awrap_model_call(self, request: Any, handler: Callable[[Any], Awaitable[Any]]) -> Any:
        settings = dict(request.model_settings)
        settings["extra_headers"] = {
            **(settings.get("extra_headers") or {}),
            SESSION_HEADER: self.session_id,
        }
        return await handler(request.override(model_settings=settings))
