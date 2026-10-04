"""The invocation runner: validation, preconditions, idempotency (D6/S4), and the mandatory span."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from clue_obs import capture_events
from clue_toolbelt import (
    IdempotencyConflict,
    PreconditionFailed,
    PreconditionFailure,
    StoredInvocation,
    Tool,
    ToolContext,
    ToolContractViolation,
    ToolInput,
    ToolOutput,
    ToolRegistry,
    ToolResult,
    UnknownTool,
    invoke_tool,
)
from tests.toolbelt.conftest import EchoTool, InMemoryStore, OtherTool, human_ctx

TTL = 86400.0


def _registry(*tools: EchoTool) -> ToolRegistry:
    reg = ToolRegistry()
    for tool in tools:
        reg.register(tool, make_default=True)
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
    # N2: the pre-spend estimate rides on the result meta (EchoTool has the free default).
    assert result.meta["estimated_cost_cents"] == "0"
    completed = cap.first("toolbelt.echo_completed")
    assert completed is not None
    assert completed["actor"] == "human"
    assert completed["workspace_id"] == "ws_test"
    assert completed["tool_version"] == "1"
    # started is emitted too (matched pair) — every runner-mediated invocation is logged.
    assert cap.has("toolbelt.echo_started")
    # N2: the estimate is also a structured event inside the span.
    estimate = cap.first("toolbelt.echo_estimate")
    assert estimate is not None
    assert estimate["estimated_cost_cents"] == "0"


def test_preconditions_block_and_emit_a_failed_span() -> None:
    tool = EchoTool(fail=[PreconditionFailure(reason_code="no_active_icp", message="nope")])
    reg = _registry(tool)
    with capture_events(mode="info") as cap, pytest.raises(PreconditionFailed) as ei:
        asyncio.run(invoke_tool(reg, "echo", {"value": 1}, human_ctx(), idempotency_ttl_s=TTL))
    assert ei.value.reason_codes == ("no_active_icp",)
    assert tool.invocations == []  # the write never ran
    assert cap.has("toolbelt.echo_failed")  # a blocked invocation is still observable
    # ...as a warning: the agent repairs a refusal itself, so it must not page Sentry (R6).
    (failed,) = cap.events("toolbelt.echo_failed")
    assert failed["level"] == "warning" and failed["error_type"] == "PreconditionFailed"


def test_unknown_tool_is_typed() -> None:
    with pytest.raises(UnknownTool):
        asyncio.run(invoke_tool(ToolRegistry(), "ghost", {}, human_ctx(), idempotency_ttl_s=TTL))


def test_exact_version_resolution_does_not_float() -> None:
    class _EchoV2(EchoTool):
        version = "2"

    v1 = EchoTool()
    v2 = _EchoV2()
    reg = ToolRegistry()
    reg.register(v1, make_default=False)
    reg.register(v2, make_default=True)

    result = asyncio.run(
        invoke_tool(
            reg,
            "echo",
            {"value": 6},
            human_ctx(),
            version="1",
            idempotency_ttl_s=TTL,
        )
    )
    assert result.version == "1"
    assert v1.invocations == [6]
    assert v2.invocations == []


def test_idempotency_key_cannot_replay_across_versions() -> None:
    class _EchoV2(EchoTool):
        version = "2"

    reg = ToolRegistry()
    reg.register(EchoTool(), make_default=False)
    reg.register(_EchoV2(), make_default=True)
    store = InMemoryStore()

    async def scenario() -> None:
        await invoke_tool(
            reg,
            "echo",
            {"value": 6},
            human_ctx(),
            version="1",
            idempotency_key="versioned",
            store=store,
            idempotency_ttl_s=TTL,
        )
        with pytest.raises(IdempotencyConflict) as exc:
            await invoke_tool(
                reg,
                "echo",
                {"value": 6},
                human_ctx(),
                version="2",
                idempotency_key="versioned",
                store=store,
                idempotency_ttl_s=TTL,
            )
        assert exc.value.reason == "tool"

    asyncio.run(scenario())


def test_output_contract_violation_fails_before_cache_completion() -> None:
    class _BadEcho(EchoTool):
        async def invoke(self, inputs, ctx):  # type: ignore[no-untyped-def]
            return ToolResult(
                tool=self.name,
                version=self.version,
                references={"echoed": "not-an-int"},
            )

    store = InMemoryStore()
    reg = _registry(_BadEcho())

    async def scenario() -> None:
        with pytest.raises(ToolContractViolation):
            await invoke_tool(
                reg,
                "echo",
                {"value": 6},
                human_ctx(),
                idempotency_key="bad-output",
                store=store,
                idempotency_ttl_s=TTL,
            )
        assert await store.lookup("ws_test", "bad-output", ttl_s=TTL) is None

    asyncio.run(scenario())


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


def test_strict_domain_output_uses_json_semantics_for_initial_result_and_replay() -> None:
    """The toolbelt owns the durable JSON boundary; individual tools keep precise domain types."""

    class _TupleInput(ToolInput):
        pass

    class _TupleOutput(ToolOutput):
        values: tuple[str, ...]

    class _TupleTool(Tool):
        name = "tuple-output"
        input_model = _TupleInput
        output_model = _TupleOutput

        def __init__(self) -> None:
            self.invocations = 0

        async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
            del inputs, ctx
            self.invocations += 1
            return ToolResult(
                tool=self.name,
                version=self.version,
                references={"values": ("one", "two")},
            )

    tool = _TupleTool()
    reg = ToolRegistry()
    reg.register(tool, make_default=True)

    store = InMemoryStore()

    async def scenario() -> None:
        first = await invoke_tool(
            reg,
            tool.name,
            {},
            human_ctx(),
            idempotency_key="json-domain-output",
            store=store,
            idempotency_ttl_s=TTL,
        )
        assert first.references == {"values": ["one", "two"]}

        second = await invoke_tool(
            reg,
            tool.name,
            {},
            human_ctx(),
            idempotency_key="json-domain-output",
            store=store,
            idempotency_ttl_s=TTL,
        )
        assert second.replayed is True
        assert second.references == {"values": ["one", "two"]}

    asyncio.run(scenario())
    assert tool.invocations == 1


def test_strict_typed_json_output_validates_and_replays_without_reexecution() -> None:
    class _StrictOutput(ToolOutput):
        object_id: UUID
        related_ids: tuple[UUID, ...]

    class _StrictEcho(EchoTool):
        name = "strict_echo"
        output_model = _StrictOutput

        async def invoke(self, inputs, ctx):  # type: ignore[no-untyped-def]
            del ctx
            self.invocations.append(inputs.value)
            output = _StrictOutput(
                object_id=UUID("11111111-1111-4111-8111-111111111111"),
                related_ids=(UUID("22222222-2222-4222-8222-222222222222"),),
            )
            return ToolResult(
                tool=self.name,
                version=self.version,
                references=output.model_dump(mode="json"),
            )

    tool = _StrictEcho()
    reg = _registry(tool)
    store = InMemoryStore()

    async def scenario() -> None:
        first = await invoke_tool(
            reg,
            tool.name,
            {"value": 9},
            human_ctx(),
            idempotency_key="strict-json",
            store=store,
            idempotency_ttl_s=TTL,
        )
        second = await invoke_tool(
            reg,
            tool.name,
            {"value": 9},
            human_ctx(),
            idempotency_key="strict-json",
            store=store,
            idempotency_ttl_s=TTL,
        )
        assert first.references == {
            "object_id": "11111111-1111-4111-8111-111111111111",
            "related_ids": ["22222222-2222-4222-8222-222222222222"],
        }
        assert second.references == first.references
        assert second.replayed is True

    asyncio.run(scenario())
    assert tool.invocations == [9]


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
        with pytest.raises(IdempotencyConflict) as ei:
            await invoke_tool(
                reg,
                "echo",
                {"value": 2},
                human_ctx(),
                idempotency_key="k2",
                store=store,
                idempotency_ttl_s=TTL,
            )
        assert ei.value.reason == "body"

    asyncio.run(scenario())
    assert tool.invocations == [1]  # the conflicting second body never executed


def test_same_key_different_tool_conflicts() -> None:
    """B3 (the proven pause/resume trap): the same key reused against a *different* tool — even
    with an identical body — is a conflict, never a cross-tool replay."""
    echo = EchoTool()
    other = OtherTool()
    reg = _registry(echo, other)
    store = InMemoryStore()

    async def scenario() -> None:
        await invoke_tool(
            reg,
            "echo",
            {"value": 1},
            human_ctx(),
            idempotency_key="k-tool",
            store=store,
            idempotency_ttl_s=TTL,
        )
        with pytest.raises(IdempotencyConflict) as ei:
            await invoke_tool(
                reg,
                "other",
                {"value": 1},  # SAME body — only the tool differs
                human_ctx(),
                idempotency_key="k-tool",
                store=store,
                idempotency_ttl_s=TTL,
            )
        assert ei.value.reason == "tool"

    asyncio.run(scenario())
    assert echo.invocations == [1]
    assert other.invocations == []  # the different tool never executed under the reused key


def test_cross_workspace_same_key_is_a_clean_miss() -> None:
    """B3: ws_B reusing ws_A's key executes fresh — no cross-tenant replay leak, no conflict."""
    tool = EchoTool()
    reg = _registry(tool)
    store = InMemoryStore()

    async def scenario() -> None:
        a = await invoke_tool(
            reg,
            "echo",
            {"value": 7},
            human_ctx("ws_A"),
            idempotency_key="shared-key",
            store=store,
            idempotency_ttl_s=TTL,
        )
        assert a.replayed is False
        b = await invoke_tool(
            reg,
            "echo",
            {"value": 8},  # different body under the SAME key — fine across workspaces
            human_ctx("ws_B"),
            idempotency_key="shared-key",
            store=store,
            idempotency_ttl_s=TTL,
        )
        assert b.replayed is False
        assert b.references == {"echoed": 8}

    asyncio.run(scenario())
    assert tool.invocations == [7, 8]  # both executed; neither replayed the other


def test_pending_reservation_conflicts() -> None:
    """S4: a live pending reservation (a concurrent same-key invocation in flight) refuses rather
    than double-executing."""
    tool = EchoTool()
    reg = _registry(tool)
    store = InMemoryStore()

    async def scenario() -> None:
        # Simulate a concurrent in-flight caller holding a pending row for the SAME body the
        # second caller will send — so the refusal is unambiguously the `pending` reason.
        from clue_toolbelt import body_sha256

        sha = body_sha256({"value": 3, "note": None})
        won = await store.reserve(
            "ws_test", "k-pending", tool_name="echo@1", body_sha256=sha, ttl_s=TTL
        )
        assert won
        with pytest.raises(IdempotencyConflict) as ei:
            await invoke_tool(
                reg,
                "echo",
                {"value": 3},
                human_ctx(),
                idempotency_key="k-pending",
                store=store,
                idempotency_ttl_s=TTL,
            )
        assert ei.value.reason == "pending"

    asyncio.run(scenario())
    assert tool.invocations == []


def test_failed_invoke_releases_reservation_and_is_never_cached() -> None:
    """S4: a raising invoke deletes its pending reservation, so a retry re-executes cleanly."""
    failing = EchoTool(raise_on_invoke=True)
    reg = _registry(failing)
    store = InMemoryStore()

    async def scenario() -> None:
        with pytest.raises(RuntimeError):
            await invoke_tool(
                reg,
                "echo",
                {"value": 5},
                human_ctx(),
                idempotency_key="k-fail",
                store=store,
                idempotency_ttl_s=TTL,
            )
        # The reservation is gone — nothing cached for the failed attempt.
        assert await store.lookup("ws_test", "k-fail", ttl_s=TTL) is None

        # A retry with a now-working tool executes fresh under the same key.
        working = EchoTool()
        retry_reg = _registry(working)
        result = await invoke_tool(
            retry_reg,
            "echo",
            {"value": 5},
            human_ctx(),
            idempotency_key="k-fail",
            store=store,
            idempotency_ttl_s=TTL,
        )
        assert result.replayed is False
        assert working.invocations == [5]

    asyncio.run(scenario())


def test_precondition_failure_is_never_cached() -> None:
    """The reservation happens *after* preconditions, so a PreconditionFailed leaves no record —
    the verified pre-fix property, preserved."""
    tool = EchoTool(fail=[PreconditionFailure(reason_code="no_active_icp", message="nope")])
    reg = _registry(tool)
    store = InMemoryStore()

    async def scenario() -> None:
        with pytest.raises(PreconditionFailed):
            await invoke_tool(
                reg,
                "echo",
                {"value": 1},
                human_ctx(),
                idempotency_key="k-pre",
                store=store,
                idempotency_ttl_s=TTL,
            )
        assert await store.lookup("ws_test", "k-pre", ttl_s=TTL) is None
        assert store.rows == {}

    asyncio.run(scenario())


def test_body_hash_is_over_the_validated_model() -> None:
    """S10: an explicit-null optional and an omitted optional hash identically (same validated
    model), so the second call replays instead of conflicting."""
    tool = EchoTool()
    reg = _registry(tool)
    store = InMemoryStore()

    async def scenario() -> None:
        first = await invoke_tool(
            reg,
            "echo",
            {"value": 4},  # `note` omitted
            human_ctx(),
            idempotency_key="k-canon",
            store=store,
            idempotency_ttl_s=TTL,
        )
        assert first.replayed is False
        second = await invoke_tool(
            reg,
            "echo",
            {"value": 4, "note": None},  # `note` explicit-null — same validated model
            human_ctx(),
            idempotency_key="k-canon",
            store=store,
            idempotency_ttl_s=TTL,
        )
        assert second.replayed is True

        # A REAL change still conflicts.
        with pytest.raises(IdempotencyConflict):
            await invoke_tool(
                reg,
                "echo",
                {"value": 4, "note": "changed"},
                human_ctx(),
                idempotency_key="k-canon",
                store=store,
                idempotency_ttl_s=TTL,
            )

    asyncio.run(scenario())
    assert tool.invocations == [4]  # executed exactly once


def test_expired_record_re_executes() -> None:
    tool = EchoTool()
    reg = _registry(tool)
    store = InMemoryStore()
    # Plant a stale record (older than the TTL) — the runner must treat it as absent and re-execute.
    store.rows[("ws_test", "k3")] = StoredInvocation(
        workspace_id="ws_test",
        idempotency_key="k3",
        body_sha256="stale",
        tool_name="echo@1",
        status="completed",
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
