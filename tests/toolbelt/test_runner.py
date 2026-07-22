"""The invocation runner: validation, preconditions, idempotency (D6), and the mandatory span."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from clue_obs import capture_events
from clue_toolbelt import (
    IdempotencyConflict,
    PreconditionFailed,
    PreconditionFailure,
    StoredInvocation,
    ToolRegistry,
    UnknownTool,
    invoke_tool,
)
from tests.toolbelt.conftest import EchoTool, InMemoryStore, human_ctx

TTL = 86400.0


def _registry(tool: EchoTool) -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(tool)
    return reg


def test_success_returns_references_and_emits_span_with_actor() -> None:
    tool = EchoTool()
    reg = _registry(tool)
    with capture_events(mode="info") as cap:
        result = asyncio.run(
            invoke_tool(reg, "echo", {"value": 5}, human_ctx(), idempotency_ttl_s=TTL)
        )
    assert result.references == {"echoed": 5}
    assert tool.invocations == [5]
    completed = cap.first("toolbelt.echo_completed")
    assert completed is not None
    assert completed["actor"] == "human"
    assert completed["workspace_id"] == "ws_test"
    assert completed["tool_version"] == "1"
    # started is emitted too (matched pair) — an unlogged invocation is structurally impossible.
    assert cap.has("toolbelt.echo_started")


def test_preconditions_block_and_emit_a_failed_span() -> None:
    tool = EchoTool(fail=[PreconditionFailure(reason_code="no_active_icp", message="nope")])
    reg = _registry(tool)
    with capture_events(mode="info") as cap, pytest.raises(PreconditionFailed) as ei:
        asyncio.run(invoke_tool(reg, "echo", {"value": 1}, human_ctx(), idempotency_ttl_s=TTL))
    assert ei.value.reason_codes == ("no_active_icp",)
    assert tool.invocations == []  # the write never ran
    assert cap.has("toolbelt.echo_failed")  # a blocked invocation is still observable


def test_unknown_tool_is_typed() -> None:
    with pytest.raises(UnknownTool):
        asyncio.run(invoke_tool(ToolRegistry(), "ghost", {}, human_ctx(), idempotency_ttl_s=TTL))


def test_idempotent_replay_does_not_re_execute() -> None:
    tool = EchoTool()
    reg = _registry(tool)
    store = InMemoryStore()

    async def scenario() -> None:
        first = await invoke_tool(
            reg,
            "echo",
            {"value": 9},
            human_ctx(),
            idempotency_key="k1",
            store=store,
            idempotency_ttl_s=TTL,
        )
        assert first.replayed is False
        second = await invoke_tool(
            reg,
            "echo",
            {"value": 9},
            human_ctx(),
            idempotency_key="k1",
            store=store,
            idempotency_ttl_s=TTL,
        )
        assert second.replayed is True
        assert second.references == {"echoed": 9}

    asyncio.run(scenario())
    assert tool.invocations == [9]  # executed exactly once


def test_same_key_different_body_conflicts_409() -> None:
    tool = EchoTool()
    reg = _registry(tool)
    store = InMemoryStore()

    async def scenario() -> None:
        await invoke_tool(
            reg,
            "echo",
            {"value": 1},
            human_ctx(),
            idempotency_key="k2",
            store=store,
            idempotency_ttl_s=TTL,
        )
        with pytest.raises(IdempotencyConflict):
            await invoke_tool(
                reg,
                "echo",
                {"value": 2},
                human_ctx(),
                idempotency_key="k2",
                store=store,
                idempotency_ttl_s=TTL,
            )

    asyncio.run(scenario())
    assert tool.invocations == [1]  # the conflicting second body never executed


def test_expired_record_re_executes() -> None:
    tool = EchoTool()
    reg = _registry(tool)
    store = InMemoryStore()
    # Plant a stale record (older than the TTL) — the runner must treat it as absent and re-execute.
    store.rows["k3"] = StoredInvocation(
        idempotency_key="k3",
        body_sha256="stale",
        tool_name="echo",
        response_json={"tool": "echo", "version": "1", "references": {"echoed": 0}},
        created_at=datetime.now(UTC) - timedelta(seconds=TTL + 60),
    )
    result = asyncio.run(
        invoke_tool(
            reg,
            "echo",
            {"value": 4},
            human_ctx(),
            idempotency_key="k3",
            store=store,
            idempotency_ttl_s=TTL,
        )
    )
    assert result.replayed is False
    assert tool.invocations == [4]  # re-executed past the expiry


def test_key_without_store_is_ignored() -> None:
    """A key with no store wired does not engage idempotency (the HTTP root wires the store)."""
    tool = EchoTool()
    reg = _registry(tool)
    result = asyncio.run(
        invoke_tool(
            reg, "echo", {"value": 1}, human_ctx(), idempotency_key="k", idempotency_ttl_s=TTL
        )
    )
    assert result.replayed is False
