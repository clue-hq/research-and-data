"""Keep OpenRouter's usage block of each Responses reply, so the call is priced from it.

On the Responses route ``langchain_openai`` keeps a fixed set of response keys and drops the rest,
including OpenRouter's ``usage.cost`` / ``usage.cost_details``. The ``/generation`` record that
would answer instead appears only about twelve seconds after the reply (measured 2026-10-09), long
after the call has been priced. So the model's OpenAI client is wrapped: each reply's usage block
is kept under its generation id until the governed model prices that generation.

Only ``responses.create`` is wrapped; every other client attribute is the original.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from langchain_openai import ChatOpenAI
from pydantic import Field, model_validator

from clue_core.openrouter_cost import openrouter_charged_usd

__all__ = ["OpenRouterResponsesModel", "ResponseUsage"]

#: Replies whose generation was never priced (a failed call, a dropped stream) are forgotten
#: oldest-first past this many, so the store cannot grow without bound.
_MAX_KEPT = 1024


class ResponseUsage:
    """Usage blocks by generation id, shared by one provider's models and its cost lookup."""

    def __init__(self) -> None:
        self._kept: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._lock = threading.Lock()

    def keep(self, response: Any) -> None:
        generation_id = getattr(response, "id", None)
        usage = getattr(response, "usage", None)
        if not isinstance(generation_id, str) or usage is None:
            return
        block = usage.model_dump() if hasattr(usage, "model_dump") else usage
        if not isinstance(block, Mapping):
            return
        with self._lock:
            self._kept[generation_id] = dict(block)
            while len(self._kept) > _MAX_KEPT:
                self._kept.popitem(last=False)

    def charged_cents(self, generation_id: str) -> Decimal | None:
        """What the kept reply says it cost, in cents (forgotten once read), or ``None``."""
        with self._lock:
            block = self._kept.pop(generation_id, None)
        charged = openrouter_charged_usd(block)
        return None if charged is None else charged * 100


class _Raw:
    """A raw response whose ``parse()`` keeps the parsed reply's usage block."""

    def __init__(self, inner: Any, usage: ResponseUsage) -> None:
        self._inner = inner
        self._usage = usage

    def parse(self, *args: Any, **kwargs: Any) -> Any:
        parsed = self._inner.parse(*args, **kwargs)
        self._usage.keep(parsed)
        return parsed

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _Responses:
    """``responses`` whose ``create`` (plain or ``with_raw_response``) keeps each reply's usage.

    ``langchain_openai`` reaches the Responses API through ``with_raw_response.create`` on its
    async path (the research agents') and through plain ``create`` on its sync path.
    """

    def __init__(
        self, inner: Any, usage: ResponseUsage, *, is_async: bool, raw: bool = False
    ) -> None:
        self._inner = inner
        self._usage = usage
        self._is_async = is_async
        self._raw = raw

    @property
    def with_raw_response(self) -> _Responses:
        return _Responses(
            self._inner.with_raw_response, self._usage, is_async=self._is_async, raw=True
        )

    def create(self, **kwargs: Any) -> Any:
        if self._is_async:
            return self._acreate(**kwargs)
        return self._kept(self._inner.create(**kwargs), stream=bool(kwargs.get("stream")))

    async def _acreate(self, **kwargs: Any) -> Any:
        return self._kept(await self._inner.create(**kwargs), stream=bool(kwargs.get("stream")))

    def _kept(self, result: Any, *, stream: bool) -> Any:
        if stream:
            # A stream's final chunk carries no generation id, so its call is never priced from
            # here; it keeps the ``/generation`` lookup it always had.
            return result
        if self._raw:
            return _Raw(result, self._usage)
        self._usage.keep(result)
        return result

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _Client:
    def __init__(self, inner: Any, usage: ResponseUsage, *, is_async: bool) -> None:
        self._inner = inner
        self.responses = _Responses(inner.responses, usage, is_async=is_async)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class OpenRouterResponsesModel(ChatOpenAI):
    """``ChatOpenAI`` on the Responses route, keeping each reply's usage block in ``usage``."""

    usage: Any = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def _keep_usage(self) -> OpenRouterResponsesModel:
        if isinstance(self.usage, ResponseUsage):
            if self.root_client is not None and not isinstance(self.root_client, _Client):
                self.root_client = _Client(self.root_client, self.usage, is_async=False)
            if self.root_async_client is not None and not isinstance(
                self.root_async_client, _Client
            ):
                self.root_async_client = _Client(self.root_async_client, self.usage, is_async=True)
        return self
