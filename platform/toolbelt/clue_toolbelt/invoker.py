"""The production journaled tool invoker.

The pure :func:`clue_toolbelt.invoke_tool` remains the small unit-test runner. Production roots use
this composed invoker so parameter snapshotting and execution journaling are mandatory.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Protocol, cast

from clue_core import ExecutionAttemptId, ExecutionId, ExecutionNodeId
from clue_obs.langfuse import ObservationLike, observation
from clue_toolbelt.envelope import (
    PreconditionFailure,
    Tool,
    ToolContext,
    ToolDescriptor,
    ToolEffectClass,
    ToolInput,
    ToolResult,
)
from clue_toolbelt.errors import PreconditionFailed, ToolAwaitingInput
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

    async def awaiting_input(
        self,
        *,
        start: JournalStart,
        context: ToolContext,
        reason_code: str,
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


class InvocationCrashHook(Protocol):
    async def __call__(
        self,
        point: str,
        *,
        context: ToolContext,
        start: JournalStart,
    ) -> None: ...


async def _no_crash(
    _point: str,
    *,
    context: ToolContext,
    start: JournalStart,
) -> None:
    del context, start


_DEFAULT_CRASH_HOOK = cast(InvocationCrashHook, _no_crash)


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
        crash_hook: InvocationCrashHook = _DEFAULT_CRASH_HOOK,
    ) -> None:
        self._registry = registry
        self._snapshotter = snapshotter
        self._journal = journal
        self._idempotency_store = idempotency_store
        self._idempotency_ttl_s = idempotency_ttl_s
        self._crash_hook = crash_hook

    def descriptor(self, name: str, version: str | None = None) -> ToolDescriptor:
        """Resolve the exact descriptor used by durable graph materialization."""
        return self._registry.descriptor(name, version)

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
        # Lane 3 slice 3: the platform's side of a governed call — what the LangChain handler's
        # own tool observation cannot see: the disposition (completed / replayed / blocked /
        # awaiting input / failed) and the durable references. READ tools are retrievers.
        with observation(
            f"governed.{descriptor.name}@{descriptor.version}",
            as_type="retriever" if descriptor.effect_class is ToolEffectClass.READ else "tool",
            input={
                "operation_id": str(context.operation_id),
                "actor": context.actor,
                "workspace_id": context.workspace_id,
                "inputs": inputs.model_dump(mode="json"),
            },
            metadata={
                "tool": descriptor.name,
                "version": descriptor.version,
                "effect_class": descriptor.effect_class.value,
            },
        ) as current:
            return await self._invoke_observed(
                tool,
                descriptor,
                inputs,
                name,
                body,
                context,
                idempotency_key=idempotency_key,
                current=current,
            )

    async def _invoke_observed(
        self,
        tool: Tool,
        descriptor: ToolDescriptor,
        inputs: ToolInput,
        name: str,
        body: dict[str, object],
        context: ToolContext,
        *,
        idempotency_key: str | None,
        current: ObservationLike,
    ) -> ToolResult:
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
            current.update(
                output={"replayed": True, "references": start.result.references},
                metadata={"disposition": "replayed"},
            )
            return validate_tool_result(tool, start.result).model_copy(update={"replayed": True})
        if start.disposition is JournalDisposition.BLOCKED:
            current.update(
                level="WARNING",
                status_message=", ".join(start.blocked_reason_codes),
                metadata={"disposition": "blocked"},
            )
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
        await self._crash_hook("after_attempt_start", context=context, start=start)
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
            await self._crash_hook("before_tool", context=effective_context, start=start)
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
            await self._crash_hook("after_domain_commit", context=effective_context, start=start)
            if descriptor.effect_class is ToolEffectClass.STEERING:
                after = await tool.audit_snapshot(inputs, effective_context)
                await self._journal.steering_snapshot(
                    start=start,
                    context=effective_context,
                    phase="after",
                    state=dict(after),
                )
        except asyncio.CancelledError:
            # Worker fencing and SIGTERM cancellation are not tool failures. The started attempt
            # remains visibly abandoned and the next lease owner recovers it.
            current.update(metadata={"disposition": "cancelled"})
            raise
        except PreconditionFailed as exc:
            await self._journal.blocked(
                start=start,
                context=effective_context,
                reason_codes=exc.reason_codes,
            )
            current.update(
                level="WARNING",
                status_message=", ".join(exc.reason_codes),
                metadata={"disposition": "blocked"},
            )
            raise
        except ToolAwaitingInput as exc:
            await self._journal.awaiting_input(
                start=start,
                context=effective_context,
                reason_code=exc.reason_code,
            )
            current.update(
                status_message=exc.reason_code,
                metadata={"disposition": "awaiting_input"},
            )
            raise
        except BaseException as exc:
            await self._journal.failed(
                start=start,
                context=effective_context,
                error_code=_error_code(exc),
            )
            current.update(
                level="ERROR",
                status_message=_error_code(exc),
                metadata={"disposition": "failed"},
            )
            raise
        completed = await self._journal.completed(
            start=start,
            context=effective_context,
            result=result,
        )
        current.update(
            output={
                "references": completed.references,
                "meta": completed.meta,
                "replayed": completed.replayed,
            },
            metadata={"disposition": "completed"},
        )
        await self._crash_hook("after_completion_event", context=effective_context, start=start)
        return completed


__all__ = [
    "InvocationJournal",
    "InvocationCrashHook",
    "JournalDisposition",
    "JournalStart",
    "ParameterSnapshot",
    "ParameterSnapshotter",
    "ToolInvoker",
]
