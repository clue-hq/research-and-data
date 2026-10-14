"""A research dispatch that Postgres aborts as a deadlock or serialization victim runs once more.

Production, 2026-10-13: a ``40P01`` on the evidence tool's authority+reserve transaction surfaced as
a ``DBAPIError`` the agent runtime treats as fatal, and the job ended in needs_review. The lock
modes now avoid that cycle (``test_quality_lock_order_db``); this is the safety net for any other
transient conflict. Each transaction retried here is idempotent on a stable key, and the first
attempt rolled back, so the retry cannot double-count.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.exc import DBAPIError

from clue_api.arv2 import quality_execution, quality_provider_tools, quality_tools
from clue_api.arv2.quality_execution import SharedResearchAllowance, retry_lock_conflict
from tests.claimstore.conftest import run_async


class _Orig(Exception):
    def __init__(self, sqlstate: str):
        super().__init__(sqlstate)
        self.sqlstate = sqlstate


def _db_error(sqlstate: str) -> DBAPIError:
    return DBAPIError("SELECT 1", {}, _Orig(sqlstate))


class _Connections:
    """A connection factory that counts how many transactions were opened."""

    def __init__(self) -> None:
        self.opened = 0

    @asynccontextmanager
    async def __call__(self):
        self.opened += 1
        yield SimpleNamespace(attempt=self.opened)


def _flaky(failures: list[BaseException]):
    calls: list[object] = []

    async def work(conn):
        calls.append(conn)
        if failures:
            raise failures.pop(0)
        return "done"

    return work, calls


@pytest.mark.parametrize("sqlstate", ["40P01", "40001"])
def test_a_deadlock_or_serialization_failure_runs_once_more_in_a_fresh_transaction(sqlstate):
    async def case():
        connections = _Connections()
        work, calls = _flaky([_db_error(sqlstate)])
        assert await retry_lock_conflict(connections, work) == "done"
        assert connections.opened == 2
        assert [c.attempt for c in calls] == [1, 2]

    run_async(case())


def test_any_other_database_error_is_not_retried():
    async def case():
        connections = _Connections()
        work, _ = _flaky([_db_error("23505")])
        with pytest.raises(DBAPIError):
            await retry_lock_conflict(connections, work)
        assert connections.opened == 1

    run_async(case())


def test_a_second_conflict_propagates():
    async def case():
        connections = _Connections()
        work, _ = _flaky([_db_error("40P01"), _db_error("40P01")])
        with pytest.raises(DBAPIError):
            await retry_lock_conflict(connections, work)
        assert connections.opened == 2

    run_async(case())


def _flaky_reserve(monkeypatch, module, failures: int = 1):
    seen: list[object] = []

    async def reserve(conn, scope, *, execution_id, kind, activity_id):
        seen.append(activity_id)
        if len(seen) <= failures:
            raise _db_error("40P01")

    monkeypatch.setattr(module, "reserve", reserve)
    return seen


def test_middleware_model_reserve_retries_with_the_same_activity_id(monkeypatch):
    async def case():
        seen = _flaky_reserve(monkeypatch, quality_execution)
        connections = _Connections()
        middleware = SharedResearchAllowance(connections, SimpleNamespace(), uuid4())
        handled: list[object] = []

        async def handler(request):
            handled.append(request)
            return "response"

        assert await middleware.awrap_model_call("request", handler) == "response"
        assert connections.opened == 2
        assert len(seen) == 2 and seen[0] == seen[1]
        assert handled == ["request"]

    run_async(case())


def test_middleware_tool_reserve_retries(monkeypatch):
    async def case():
        seen = _flaky_reserve(monkeypatch, quality_execution)
        connections = _Connections()
        middleware = SharedResearchAllowance(connections, SimpleNamespace(), uuid4())
        request = SimpleNamespace(tool_call={"name": "write_file", "id": "call-1"})

        async def handler(request):
            return "ok"

        assert await middleware.awrap_tool_call(request, handler) == "ok"
        assert connections.opened == 2
        assert len(seen) == 2 and seen[0] == seen[1]

    run_async(case())


def _authority(role: str = "account_research"):
    return SimpleNamespace(
        role=role, execution_id=uuid4(), grant=SimpleNamespace(scope=SimpleNamespace())
    )


def test_research_write_tool_authority_retries(monkeypatch):
    async def case():
        seen = _flaky_reserve(monkeypatch, quality_tools)
        resolved: list[object] = []

        async def resolve_authority(conn, scope, execution_id):
            resolved.append(conn)
            return _authority()

        monkeypatch.setattr(quality_tools, "resolve_authority", resolve_authority)
        tool = quality_tools.SubmitResearchClaimTool(
            SimpleNamespace(workspace_id="ws_1"), storage=None, purge_unevidenced=False
        )
        connections = _Connections()
        ctx = SimpleNamespace(
            workspace_id="ws_1",
            execution_id=uuid4(),
            conn_factory=connections,
            operation_id=uuid4(),
        )
        authority = await tool.authority(ctx)
        assert authority.role == "account_research"
        assert connections.opened == 2 and len(resolved) == 2 and len(seen) == 2

    run_async(case())


def test_evidence_acquisition_dispatch_retries(monkeypatch):
    async def case():
        seen = _flaky_reserve(monkeypatch, quality_provider_tools)

        async def resolve_authority(conn, scope, execution_id):
            return _authority()

        begun: list[object] = []

        async def begin(conn, scope, key, arguments):
            begun.append(key)
            return SimpleNamespace(operation_id=uuid4()), True

        monkeypatch.setattr(quality_provider_tools, "resolve_authority", resolve_authority)
        monkeypatch.setattr(quality_provider_tools.operations, "begin", begin)
        tool = quality_provider_tools.AcquireResearchTool(None)
        tool.runtime = SimpleNamespace(
            scope=SimpleNamespace(workspace_id="ws_1"), operation_scope=SimpleNamespace()
        )
        connections = _Connections()
        ctx = SimpleNamespace(
            workspace_id="ws_1",
            execution_id=uuid4(),
            conn_factory=connections,
            operation_id=uuid4(),
        )
        operation, won = await tool.begin_dispatch(ctx, "search_web", {"query": "x"})
        assert won is True
        assert connections.opened == 2 and len(seen) == 2
        # The rolled-back first attempt never reached the ledger; the retry began it once.
        assert begun == ["quality_tool:search_web"]

    run_async(case())
