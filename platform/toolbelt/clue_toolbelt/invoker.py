"""The production journaled tool invoker.

The pure :func:`clue_toolbelt.invoke_tool` remains the small unit-test runner. Production roots use
this composed invoker so parameter snapshotting and execution journaling are mandatory.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol

from clue_core import ExecutionAttemptId, ExecutionId, ExecutionNodeId
from clue_toolbelt.envelope import (
    PreconditionFailure,
    ToolContext,
    ToolDescriptor,
    ToolEffectClass,
    ToolInput,
    ToolResult,
)
from clue_toolbelt.errors import PreconditionFailed
from clue_toolbelt.idempotency import IdempotencyStore
from clue_toolbelt.registry import ToolRegistry
from clue_toolbelt.runner import invoke_tool, validate_tool_result


@dataclass(frozen=True, slots=True)
class ParameterSnapshot:
    artifact_key: str
    content_sha256: str
    display_params: dict[str, object]


class ParameterSnapshotter(Protocol):
    async def snapshot(
        self,
        *,
        descriptor: ToolDescriptor,
        inputs: ToolInput,
        context: ToolContext,
    ) -> ParameterSnapshot: ...


class JournalDisposition(StrEnum):
    STARTED = "started"
    COMPLETED = "completed"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class JournalStart:
    execution_id: ExecutionId
    node_id: ExecutionNodeId
    attempt_id: ExecutionAttemptId | None
    disposition: JournalDisposition
    owns_execution: bool = False
    result: ToolResult | None = None
    blocked_reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.disposition is JournalDisposition.STARTED and self.attempt_id is None:
            raise ValueError("a started journal invocation requires an attempt id")
        if self.disposition is JournalDisposition.COMPLETED and self.result is None:
            raise ValueError("a completed journal invocation requires a result")
        if self.disposition is JournalDisposition.BLOCKED and not self.blocked_reason_codes:
            raise ValueError("a blocked journal invocation requires reason codes")


class InvocationJournal(Protocol):
    async def begin(
        self,
        *,
        descriptor: ToolDescriptor,
        context: ToolContext,
        snapshot: ParameterSnapshot,
    ) -> JournalStart: ...

    async def steering_snapshot(
        self,
        *,
        start: JournalStart,
        context: ToolContext,
        phase: str,
        state: dict[str, object],
    ) -> None: ...

    async def blocked(
        self,
        *,
        start: JournalStart,
        context: ToolContext,
        reason_codes: tuple[str, ...],
    ) -> None: ...

    async def failed(
        self,
        *,
        start: JournalStart,
        context: ToolContext,
        error_code: str,
    ) -> None: ...

    async def completed(
        self,
        *,
        start: JournalStart,
        context: ToolContext,
        result: ToolResult,
    ) -> ToolResult: ...


def _error_code(exc: BaseException) -> str:
    name = re.sub(r"(?<!^)(?=[A-Z])", "_", type(exc).__name__).lower()
    return name or "tool_invocation_failed"


class ToolInvoker:
    """Mandatory production path: snapshot → begin journal → tool → terminal journal event."""

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        snapshotter: ParameterSnapshotter,
        journal: InvocationJournal,
        idempotency_store: IdempotencyStore,
        idempotency_ttl_s: float,
    ) -> None:
        self._registry = registry
        self._snapshotter = snapshotter
        self._journal = journal
        self._idempotency_store = idempotency_store
        self._idempotency_ttl_s = idempotency_ttl_s

    async def invoke(
        self,
        name: str,
        body: dict[str, object],
        context: ToolContext,
        *,
        version: str | None = None,
        idempotency_key: str | None = None,
    ) -> ToolResult:
        tool = self._registry.get(name, version)
        descriptor = tool.descriptor
        inputs = tool.input_model.model_validate(body)
        snapshot = await self._snapshotter.snapshot(
            descriptor=descriptor,
            inputs=inputs,
            context=context,
        )
        start = await self._journal.begin(
            descriptor=descriptor,
            context=context,
            snapshot=snapshot,
        )
        if start.disposition is JournalDisposition.COMPLETED:
            assert start.result is not None
            return validate_tool_result(tool, start.result).model_copy(update={"replayed": True})
        if start.disposition is JournalDisposition.BLOCKED:
            raise PreconditionFailed(
                tuple(
                    PreconditionFailure(
                        reason_code=code,
                        message="this logical operation is durably blocked; invoke a new operation "
                        "after satisfying its prerequisite",
                    )
                    for code in start.blocked_reason_codes
                )
            )

        assert start.attempt_id is not None
        effective_context = replace(
            context,
            execution_id=start.execution_id,
            execution_node_id=start.node_id,
        )
        # The A9 key is always derived from the durable journal identity. A caller-supplied HTTP
        # key may derive ``operation_id`` at the edge, but cannot create a second cache identity for
        # the same logical operation (which would permit concurrent duplicate effects).
        stable_cache_key = f"execution:{start.execution_id}:operation:{context.operation_id}"
        try:
            if descriptor.effect_class is ToolEffectClass.STEERING:
                before = await tool.audit_snapshot(inputs, effective_context)
                await self._journal.steering_snapshot(
                    start=start,
                    context=effective_context,
                    phase="before",
                    state=dict(before),
                )
            result = await invoke_tool(
                self._registry,
                name,
                body,
                effective_context,
                version=descriptor.version,
                idempotency_key=stable_cache_key,
                store=self._idempotency_store,
                idempotency_ttl_s=self._idempotency_ttl_s,
            )
            if descriptor.effect_class is ToolEffectClass.STEERING:
                after = await tool.audit_snapshot(inputs, effective_context)
                await self._journal.steering_snapshot(
                    start=start,
                    context=effective_context,
                    phase="after",
                    state=dict(after),
                )
        except PreconditionFailed as exc:
            await self._journal.blocked(
                start=start,
                context=effective_context,
                reason_codes=exc.reason_codes,
            )
            raise
        except BaseException as exc:
            await self._journal.failed(
                start=start,
                context=effective_context,
                error_code=_error_code(exc),
            )
            raise
        return await self._journal.completed(
            start=start,
            context=effective_context,
            result=result,
        )


__all__ = [
    "InvocationJournal",
    "JournalDisposition",
    "JournalStart",
    "ParameterSnapshot",
    "ParameterSnapshotter",
    "ToolInvoker",
]
