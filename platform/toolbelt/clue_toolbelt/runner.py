"""The invocation wrapper — the sanctioned path to run a tool (D5: runner-mediated ⇒ logged).

:func:`invoke_tool` is the pure typed runner used internally by C5's required production
``ToolInvoker`` and directly by focused unit tests. Production roots do not call it bare: the
journaled invoker snapshots parameters and establishes the durable execution node first. This
runner provides the inner invocation guarantees:

1. **Resolve** the tool from the registry (``UnknownTool`` if absent).
2. **Validate** the request body against the tool's pydantic ``input_model`` (a bad body is a loud
   ``ValidationError``, never a silent coercion). The idempotency body hash is taken over the
   *validated* model dump (canonical, so null-vs-omitted and key order do not change the key).
3. **Estimate** the pre-spend cost (:meth:`Tool.estimate`) — stamped on the span and the
   ``ToolResult.meta`` so the UI/journal can show the prior before the spend lands.
4. **Idempotency (D6 / S4, when a key + a store are supplied):** consult by ``(workspace, key)`` —
   a live ``completed`` record with the same tool + body replays; a *different* tool or body, or an
   in-flight ``pending`` reservation, is an ``IdempotencyConflict``. Otherwise the runner reserves
   the slot up-front (so a concurrent same-key double-submit refuses rather than double-executing).
5. **Preconditions (pre-mortem #2):** run the tool's ``preconditions``; any failure raises
   ``PreconditionFailed`` with the machine-readable reason codes — the write never runs, and (since
   preconditions run before the reservation) a precondition failure is never cached.
6. **Execute** the tool inside a :func:`clue_obs.log_span` named ``toolbelt.<tool>`` stamping
   ``actor`` (human|agent, REQ-20), ``workspace_id``, ``quality_mode`` (A8/D9), and the tool version
   — so every runner-mediated invocation (success *or* failure) emits a matched span. A raising
   invoke releases its reservation (a failure is never cached).
7. **Record** the response to the idempotency store (when a key + store were supplied).

The whole flow after tool resolution runs *inside* the span, so a ``PreconditionFailed`` /
``ValidationError`` / ``IdempotencyConflict`` also emits a ``toolbelt.<tool>_failed`` — a blocked
invocation is as observable as a successful one."""

from __future__ import annotations

from pydantic import TypeAdapter, ValidationError
from pydantic_core import PydanticSerializationError

from clue_obs import get_logger, log_span
from clue_toolbelt.envelope import Tool, ToolContext, ToolOutput, ToolResult
from clue_toolbelt.errors import (
    IdempotencyConflict,
    PreconditionFailed,
    ToolAwaitingInput,
    ToolContractViolation,
)
from clue_toolbelt.idempotency import IdempotencyStore, StoredInvocation, body_sha256
from clue_toolbelt.registry import ToolRegistry

__all__ = ["invoke_tool", "validate_tool_output_references", "validate_tool_result"]

log = get_logger("clue_toolbelt.runner")
_JSON_OBJECT = TypeAdapter(dict[str, object])


def validate_tool_output_references(
    output_model: type[ToolOutput], references: dict[str, object]
) -> dict[str, object]:
    """Validate a tool result at its durable JSON boundary.

    Tool outputs are domain models, but ``ToolResult.references`` is a JSON document: it is
    journaled, artifact-backed, and replayed after serialization.  Strict Pydantic models must
    therefore be validated in JSON mode.  This matters for every JSON-semantic type whose Python
    representation differs on the wire (for example tuple/array, UUID/string, date/string, and
    Decimal/number), and keeps that transport rule in one place instead of forcing every tool
    author to weaken its domain contract.

    The returned mapping is the canonical JSON-native form stored by all durable callers.
    """

    encoded = _JSON_OBJECT.dump_json(references)
    return output_model.model_validate_json(encoded).model_dump(mode="json")


def _replay_or_conflict(
    existing: StoredInvocation, *, tool: Tool, request_sha: str, key: str
) -> ToolResult:
    """Interpret a live record against the current request: replay a matching ``completed`` row,
    else raise the appropriate :class:`IdempotencyConflict`. A different tool or body is a client
    bug; a still-``pending`` row is a concurrent in-flight double-submit."""
    descriptor = tool.descriptor
    if existing.tool_name != descriptor.address:
        raise IdempotencyConflict(key, reason="tool")
    if existing.body_sha256 != request_sha:
        raise IdempotencyConflict(key, reason="body")
    if existing.status == "pending":
        raise IdempotencyConflict(key, reason="pending")
    # A completed row with the matching tool + body → replay (no re-execution).
    replayed = ToolResult.model_validate(existing.response_json or {})
    return validate_tool_result(tool, replayed).model_copy(update={"replayed": True})


def validate_tool_result(tool: Tool, result: ToolResult) -> ToolResult:
    """Validate identity and typed references against the exact registered descriptor.

    ``ToolResult.references`` is a durable JSON envelope, including on idempotent replay. Validate
    it in Pydantic's JSON mode so strict UUID/datetime/Decimal and tuple contracts accept their
    canonical JSON representations without weakening the declared output model. Python-strict
    validation here made a fresh rich result pass only until ``model_dump(mode='json')`` and made
    every replay of that same valid result fail.
    """
    descriptor = tool.descriptor
    if result.tool != descriptor.name or result.version != descriptor.version:
        raise ToolContractViolation(
            descriptor.address,
            f"returned identity {result.tool}@{result.version}",
        )
    try:
        references = validate_tool_output_references(
            descriptor.output_model,
            result.references,
        )
    except (PydanticSerializationError, TypeError, ValueError, ValidationError) as exc:
        raise ToolContractViolation(descriptor.address, str(exc)) from exc
    return result.model_copy(update={"references": references})


async def invoke_tool(
    registry: ToolRegistry,
    name: str,
    body: dict[str, object],
    ctx: ToolContext,
    *,
    version: str | None = None,
    idempotency_key: str | None = None,
    store: IdempotencyStore | None = None,
    idempotency_ttl_s: float,
) -> ToolResult:
    """Run the tool ``name`` over ``body`` in ``ctx`` and return its :class:`ToolResult`.

    ``idempotency_key`` + ``store`` enable D6/S4 replay/conflict/reservation, scoped
    ``(ctx.workspace_id, idempotency_key)`` (both must be supplied to engage it; without a store, a
    key is ignored — the caller is responsible for wiring one at the HTTP root).
    ``idempotency_ttl_s`` is the read-time freshness window (``CLUE_TOOLBELT_IDEMPOTENCY_TTL_S``).

    Raises: :class:`~clue_toolbelt.errors.UnknownTool`, ``pydantic.ValidationError`` (bad body),
    :class:`~clue_toolbelt.errors.IdempotencyConflict`, and
    :class:`~clue_toolbelt.errors.PreconditionFailed` — each *before* any write; the tool body only
    runs when all gates pass."""
    tool: Tool = registry.get(name, version)
    descriptor = tool.descriptor
    with log_span(
        f"toolbelt.{name}",
        logger=log,
        # A refused precondition is the agent's to repair and an awaited input is a wait, not a
        # fault: warnings, so they never become Sentry issues (2026-10-03 spec, R6).
        expected=(PreconditionFailed, ToolAwaitingInput),
        actor=ctx.actor,
        workspace_id=ctx.workspace_id,
        quality_mode=ctx.quality_mode,
        tool_version=descriptor.version,
        operation_id=str(ctx.operation_id),
        idempotency_key=idempotency_key,
    ) as span_log:
        inputs = tool.input_model.model_validate(body)
        # S10: the idempotency body key is the canonical hash of the *validated* model, so
        # serialisation variants (null-vs-omitted, key order) do not change the key, while a real
        # field change does.
        request_sha = body_sha256(inputs.model_dump(mode="json"))
        # N2: the pre-spend estimate — stamped on the span (a structured event within the span) and
        # returned in ToolResult.meta.
        estimate = tool.estimate(inputs)
        span_log.info(
            f"toolbelt.{name}_estimate",
            estimated_cost_cents=str(estimate.cost_cents),
            estimate_detail=dict(estimate.detail),
        )

        engage_idempotency = idempotency_key is not None and store is not None
        ws = ctx.workspace_id

        if engage_idempotency:
            assert idempotency_key is not None and store is not None  # narrowed by engage flag
            existing = await store.lookup(ws, idempotency_key, ttl_s=idempotency_ttl_s)
            if existing is not None:
                return _replay_or_conflict(
                    existing, tool=tool, request_sha=request_sha, key=idempotency_key
                )

        failures = await tool.preconditions(inputs, ctx)
        if failures:
            raise PreconditionFailed(failures)

        if engage_idempotency:
            assert idempotency_key is not None and store is not None
            won = await store.reserve(
                ws,
                idempotency_key,
                tool_name=descriptor.address,
                body_sha256=request_sha,
                ttl_s=idempotency_ttl_s,
            )
            if not won:
                # Lost the reservation to a concurrent same-key caller between lookup and reserve —
                # re-look-up and replay/conflict per the rules (a still-pending peer → pending
                # conflict; the at-least-once caveat is documented on IdempotencyConflict).
                existing = await store.lookup(ws, idempotency_key, ttl_s=idempotency_ttl_s)
                if existing is not None:
                    return _replay_or_conflict(
                        existing, tool=tool, request_sha=request_sha, key=idempotency_key
                    )
                raise IdempotencyConflict(idempotency_key, reason="pending")

        try:
            result = validate_tool_result(tool, await tool.invoke(inputs, ctx))
        except BaseException:
            # A failed invoke must never be cached — release the reservation so a retry re-executes.
            if engage_idempotency:
                assert idempotency_key is not None and store is not None
                await store.release(ws, idempotency_key)
            raise

        result = result.model_copy(
            update={"meta": {**result.meta, "estimated_cost_cents": str(estimate.cost_cents)}}
        )

        if engage_idempotency:
            assert idempotency_key is not None and store is not None
            await store.complete(ws, idempotency_key, response_json=result.model_dump(mode="json"))
        return result
