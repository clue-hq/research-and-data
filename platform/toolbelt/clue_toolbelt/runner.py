"""The invocation wrapper — the *only* way to run a tool (D5: an unlogged write is impossible).

:func:`invoke_tool` is the single entry point every caller (the slice-3 HTTP route, the agent plane,
a test) goes through. It is the choke point that makes the toolbelt's guarantees structural rather
than by-convention:

1. **Resolve** the tool from the registry (``UnknownTool`` if absent).
2. **Validate** the request body against the tool's pydantic ``input_model`` (a bad body is a loud
   ``ValidationError``, never a silent coercion).
3. **Idempotency (D6, when a key is supplied):** consult the store — a live same-body record
   replays its stored response; a live *different*-body record is an ``IdempotencyConflict``.
4. **Preconditions (pre-mortem #2):** run the tool's ``preconditions``; any failure raises
   ``PreconditionFailed`` with the machine-readable reason codes — the write never runs.
5. **Execute** the tool inside a :func:`clue_obs.log_span` named ``toolbelt.<tool>`` stamping
   ``actor`` (human|agent, REQ-20), ``workspace_id``, ``quality_mode`` (A8/D9), and the tool version
   — so every invocation (success *or* failure) emits a matched span. There is no code path that
   reaches ``Tool.invoke`` outside this span.
6. **Record** the response to the idempotency store (when a key was supplied).

The whole flow after tool resolution runs *inside* the span, so a ``PreconditionFailed`` /
``ValidationError`` / ``IdempotencyConflict`` also emits a ``toolbelt.<tool>_failed`` — a blocked
invocation is as observable as a successful one."""

from __future__ import annotations

from datetime import UTC, datetime

from clue_obs import get_logger, log_span
from clue_toolbelt.envelope import Tool, ToolContext, ToolResult
from clue_toolbelt.errors import IdempotencyConflict, PreconditionFailed
from clue_toolbelt.idempotency import (
    IdempotencyStore,
    StoredInvocation,
    body_sha256,
)
from clue_toolbelt.registry import ToolRegistry

__all__ = ["invoke_tool"]

log = get_logger("clue_toolbelt.runner")


async def invoke_tool(
    registry: ToolRegistry,
    name: str,
    body: dict[str, object],
    ctx: ToolContext,
    *,
    idempotency_key: str | None = None,
    store: IdempotencyStore | None = None,
    idempotency_ttl_s: float,
) -> ToolResult:
    """Run the tool ``name`` over ``body`` in ``ctx`` and return its :class:`ToolResult`.

    ``idempotency_key`` + ``store`` enable D6 replay/conflict (both must be supplied to engage it;
    without a store, a key is ignored — the caller is responsible for wiring one at the HTTP root).
    ``idempotency_ttl_s`` is the read-time freshness window (``CLUE_TOOLBELT_IDEMPOTENCY_TTL_S``).

    Raises: :class:`~clue_toolbelt.errors.UnknownTool`, ``pydantic.ValidationError`` (bad body),
    :class:`~clue_toolbelt.errors.IdempotencyConflict`, and
    :class:`~clue_toolbelt.errors.PreconditionFailed` — each *before* any write; the tool body only
    runs when all four gates pass."""
    tool: Tool = registry.get(name)
    with log_span(
        f"toolbelt.{name}",
        logger=log,
        actor=ctx.actor,
        workspace_id=ctx.workspace_id,
        quality_mode=ctx.quality_mode,
        tool_version=tool.version,
        idempotency_key=idempotency_key,
    ):
        inputs = tool.input_model.model_validate(body)
        engage_idempotency = idempotency_key is not None and store is not None
        request_sha = body_sha256(body)

        if engage_idempotency:
            assert idempotency_key is not None and store is not None  # narrowed by engage flag
            existing = await store.lookup(idempotency_key, ttl_s=idempotency_ttl_s)
            if existing is not None:
                if existing.body_sha256 != request_sha:
                    raise IdempotencyConflict(idempotency_key)
                # Same key + same body within TTL → replay the stored response (no re-execution).
                replayed = ToolResult.model_validate(existing.response_json)
                return replayed.model_copy(update={"replayed": True})

        failures = await tool.preconditions(inputs, ctx)
        if failures:
            raise PreconditionFailed(failures)

        result = await tool.invoke(inputs, ctx)

        if engage_idempotency:
            assert idempotency_key is not None and store is not None
            await store.record(
                StoredInvocation(
                    idempotency_key=idempotency_key,
                    body_sha256=request_sha,
                    tool_name=name,
                    response_json=result.model_dump(mode="json"),
                    created_at=datetime.now(UTC),
                )
            )
        return result
