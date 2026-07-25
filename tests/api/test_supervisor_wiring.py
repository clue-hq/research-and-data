"""C5.5 API-root enforcement boundaries."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from clue_api.supervisor_wiring import RunControlledPreSpendGate
from clue_core import (
    EntityType,
    ExecutionId,
    PreSpendDecision,
    PreSpendRequest,
    PreSpendVerdict,
    new_entity_id,
    new_execution_id,
    new_run_id,
)
from tests.db.conftest import run_async


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


class _Connection:
    def __init__(self, owner: ExecutionId | None) -> None:
        self._owner = owner

    async def execute(self, statement: object, params: object) -> _ScalarResult:
        del statement, params
        return _ScalarResult(self._owner)


def _conn_factory(owner: ExecutionId | None):
    @asynccontextmanager
    async def factory() -> AsyncIterator[_Connection]:
        yield _Connection(owner)

    return factory


class _Controls:
    def __init__(self, blocked: set[str]) -> None:
        self.blocked = blocked
        self.checks: list[tuple[ExecutionId, str]] = []

    async def source_allowed(self, execution_id: ExecutionId, source_key: str) -> bool:
        self.checks.append((execution_id, source_key))
        return source_key not in self.blocked


class _InnerGate:
    def __init__(self) -> None:
        self.calls = 0

    async def check(self, request: PreSpendRequest) -> PreSpendDecision:
        del request
        self.calls += 1
        return PreSpendDecision(verdict=PreSpendVerdict.PASS)


def _request(source_key: str) -> PreSpendRequest:
    return PreSpendRequest(
        entity_id=new_entity_id(),
        entity_type=EntityType.ACCOUNT,
        field_key="core.employee_count",
        source_tier=1,
        source_key=source_key,
        run_id=new_run_id(),
    )


def test_source_breaker_rejects_exact_source_before_the_existing_gate() -> None:
    async def scenario() -> None:
        owner = new_execution_id()
        controls = _Controls({"provider-a"})
        inner = _InnerGate()
        gate = RunControlledPreSpendGate(
            inner=inner,
            controls=controls,  # type: ignore[arg-type]
            conn_factory=_conn_factory(owner),  # type: ignore[arg-type]
        )
        rejected = await gate.check(_request("provider-a"))
        assert rejected.verdict is PreSpendVerdict.REJECT
        assert rejected.reasons == ("source_breaker_active",)
        assert inner.calls == 0

        admitted = await gate.check(_request("provider-b"))
        assert admitted.verdict is PreSpendVerdict.PASS
        assert inner.calls == 1
        assert controls.checks == [(owner, "provider-a"), (owner, "provider-b")]

    run_async(scenario())


def test_legacy_unowned_run_preserves_existing_gate_behavior() -> None:
    async def scenario() -> None:
        controls = _Controls({"provider-a"})
        inner = _InnerGate()
        gate = RunControlledPreSpendGate(
            inner=inner,
            controls=controls,  # type: ignore[arg-type]
            conn_factory=_conn_factory(None),  # type: ignore[arg-type]
        )
        decision = await gate.check(_request("provider-a"))
        assert decision.verdict is PreSpendVerdict.PASS
        assert inner.calls == 1
        assert controls.checks == []

    run_async(scenario())
