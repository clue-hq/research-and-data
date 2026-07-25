"""Run-scoped source-call observation seam used by the C5.5 supervisor."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from clue_core import CostCents, EntityId, RunId


class SourceCallOutcome(StrEnum):
    CLAIMS_PRODUCED = "claims_produced"
    EMPTY = "empty"
    FAILED = "failed"


class SourceCallEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    account_entity_id: EntityId
    account_run_id: RunId
    field_key: str = Field(min_length=1)
    source_key: str = Field(min_length=1)
    outcome: SourceCallOutcome
    error_code: str | None = None
    claims_count: int = Field(default=0, ge=0)
    cost_cents: CostCents = Decimal(0)
    latency_ms: float = Field(default=0, ge=0)


class SourceCallObserver(Protocol):
    async def observe(self, event: SourceCallEvent) -> None: ...


_CURRENT_OBSERVER: ContextVar[SourceCallObserver | None] = ContextVar(
    "clue_source_call_observer", default=None
)


def current_source_call_observer() -> SourceCallObserver | None:
    return _CURRENT_OBSERVER.get()


@contextmanager
def bind_source_call_observer(observer: SourceCallObserver | None) -> Iterator[None]:
    token = _CURRENT_OBSERVER.set(observer)
    try:
        yield
    finally:
        _CURRENT_OBSERVER.reset(token)


__all__ = [
    "SourceCallEvent",
    "SourceCallObserver",
    "SourceCallOutcome",
    "bind_source_call_observer",
    "current_source_call_observer",
]
