"""Test doubles + helpers for M6.1 discovery (ENG-128).

Discovery is pure of persistence (channels are providers, dedup uses the M2 normalizers, the ICP
spec is built in-memory), so these tests need no database — they drive the async ``discover`` from a
sync body via ``run_async`` (the shared ``asyncio.run`` wrapper). The doubles model the two seams a
real run depends on: a grounded :class:`DiscoveryChannel` and the :class:`LLMGateway`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from pydantic import JsonValue

from clue_research.core import (
    Completion,
    EmbeddingResult,
    ICPCreatedFrom,
    ICPSpec,
    Message,
)
from clue_research.discovery_scoring.discovery import CandidateRecord, DiscoveryQuery

# Reuse the shared sync coroutine runner (DRY; no pytest-asyncio).
from tests.db.conftest import run_async as run_async

Responder = Callable[[DiscoveryQuery], Sequence[CandidateRecord]]


def icp_spec(discovery_strategy: dict[str, JsonValue] | None = None) -> ICPSpec:
    """Build an in-memory ICP spec carrying a discovery-strategy slot (the only field M6.1 uses)."""
    return ICPSpec(
        client_id="acme",
        icp_key="default",
        created_from=ICPCreatedFrom.SYNTHESIS,
        discovery_strategy=discovery_strategy or {},
    )


def record(
    ref: str,
    *,
    domain: str | None = None,
    name: str | None = None,
    url: str | None = None,
    signal: str = "icp-match",
    confidence: float = 0.8,
    cost_cents: Decimal = Decimal(0),
) -> CandidateRecord:
    """Build one grounded candidate record (the shape a real channel returns)."""
    return CandidateRecord(
        source_record_ref=ref,
        source_url=url,
        candidate_domain=domain,
        raw_name=name,
        matched_signal=signal,
        confidence=confidence,
        cost_cents=cost_cents,
    )


@dataclass
class FakeChannel:
    """A :class:`DiscoveryChannel` double: returns whatever ``responder`` computes for a query and
    records every call (so tests can assert fan-out + provider-swap behaviour)."""

    source_key: str
    responder: Responder
    calls: list[DiscoveryQuery] = field(default_factory=list)

    async def discover(self, query: DiscoveryQuery) -> list[CandidateRecord]:
        self.calls.append(query)
        return list(self.responder(query))


def const_channel(source_key: str, records: Sequence[CandidateRecord]) -> FakeChannel:
    """A channel that returns the same records on every call."""
    return FakeChannel(source_key=source_key, responder=lambda _query: records)


def empty_channel(source_key: str) -> FakeChannel:
    """A channel that always returns nothing (a real channel's miss) — never fabricates."""
    return FakeChannel(source_key=source_key, responder=lambda _query: ())


@dataclass
class FakeGateway:
    """An :class:`LLMGateway` double: ``complete`` returns canned query lines (never entities);
    ``embed`` is unused by discovery. ``complete_calls`` lets a test assert planning ran."""

    reply: str = "widen query one\nwiden query two"
    complete_calls: int = 0

    def complete(self, *, model: str, messages: list[Message], **opts: object) -> Completion:
        self.complete_calls += 1
        return Completion(model=model, text=self.reply)

    def embed(self, *, model: str, inputs: list[str]) -> EmbeddingResult:
        return EmbeddingResult(model=model, vectors=())
