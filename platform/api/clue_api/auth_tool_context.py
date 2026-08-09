"""Provider-neutral conversion from authenticated principals to ambient tool authority.

Lane D supplies the durable ``action_ref``; this module only binds it to the already-resolved
internal principal. Provider tokens, subjects, and client-authored actor fields never enter the
tool context.
"""

from __future__ import annotations

from datetime import UTC, datetime

from clue_auth import RequestPrincipal, ServicePrincipal
from clue_core import ExecutionId, ExecutionNodeId, OperationId
from clue_db import ConnFactory
from clue_toolbelt import PreconditionFailure, ToolContext


def tool_context_for_principal(
    principal: RequestPrincipal,
    *,
    conn_factory: ConnFactory,
    operation_id: OperationId,
    action_ref: str | None = None,
    quality_mode: str | None = None,
    execution_id: ExecutionId | None = None,
    execution_node_id: ExecutionNodeId | None = None,
    execution_node_key: str | None = None,
    parent_execution_id: ExecutionId | None = None,
    execution_worker_id: str | None = None,
    lease_generation: int | None = None,
) -> ToolContext:
    """Bind a Clue human principal to a human invocation; never accept provider identity."""

    return ToolContext(
        workspace_id=principal.workspace_id,
        actor="human",
        conn_factory=conn_factory,
        operation_id=operation_id,
        principal_kind="human",
        actor_id=principal.user_id,
        membership_id=principal.membership_id,
        action_ref=action_ref,
        quality_mode=quality_mode,
        execution_id=execution_id,
        execution_node_id=execution_node_id,
        execution_node_key=execution_node_key,
        parent_execution_id=parent_execution_id,
        execution_worker_id=execution_worker_id,
        lease_generation=lease_generation,
    )


def tool_context_for_service(
    principal: ServicePrincipal,
    *,
    conn_factory: ConnFactory,
    operation_id: OperationId,
    action_ref: str | None = None,
    quality_mode: str | None = None,
    execution_id: ExecutionId | None = None,
    execution_node_id: ExecutionNodeId | None = None,
    execution_node_key: str | None = None,
    parent_execution_id: ExecutionId | None = None,
    execution_worker_id: str | None = None,
    lease_generation: int | None = None,
) -> ToolContext:
    """Bind a separately authenticated service; an action ref is evidence, not impersonation."""

    return ToolContext(
        workspace_id=principal.workspace_id,
        actor="agent",
        conn_factory=conn_factory,
        operation_id=operation_id,
        principal_kind="service",
        actor_id=principal.service_id,
        membership_id=None,
        action_ref=action_ref,
        quality_mode=quality_mode,
        execution_id=execution_id,
        execution_node_id=execution_node_id,
        execution_node_key=execution_node_key,
        parent_execution_id=parent_execution_id,
        execution_worker_id=execution_worker_id,
        lease_generation=lease_generation,
    )


def tool_context_for_internal_service(
    *,
    service_id: str,
    workspace_id: str,
    conn_factory: ConnFactory,
    operation_id: OperationId,
    action_ref: str | None = None,
    quality_mode: str | None = None,
    execution_id: ExecutionId | None = None,
    execution_node_id: ExecutionNodeId | None = None,
    execution_node_key: str | None = None,
    parent_execution_id: ExecutionId | None = None,
    execution_worker_id: str | None = None,
    lease_generation: int | None = None,
) -> ToolContext:
    """Bind a composition-root-owned process identity without inventing human membership.

    Credential validation remains the future service-auth adapter's job. This helper closes the
    current in-process composition sites so detached work is durably a service principal instead
    of an anonymous legacy ``actor="agent"`` context.
    """

    return tool_context_for_service(
        ServicePrincipal(
            service_id=service_id,
            workspace_id=workspace_id,
            permissions=frozenset(),
            authenticated_at=datetime.now(UTC),
        ),
        conn_factory=conn_factory,
        operation_id=operation_id,
        action_ref=action_ref,
        quality_mode=quality_mode,
        execution_id=execution_id,
        execution_node_id=execution_node_id,
        execution_node_key=execution_node_key,
        parent_execution_id=parent_execution_id,
        execution_worker_id=execution_worker_id,
        lease_generation=lease_generation,
    )


def require_human_authority(
    ctx: ToolContext,
    *,
    action_ref_required: bool = False,
    reason_code: str = "trusted_human_receipt_required",
    message: str = "this operation requires authenticated human authority",
) -> tuple[PreconditionFailure, ...]:
    """Require a closed authenticated human principal at every human-only tool boundary."""

    if ctx.principal_kind is None:
        if (
            ctx.actor == "human"
            and ctx.execution_id is not None
            and ctx.execution_node_id is not None
            and not action_ref_required
        ):
            # Pre-D1 compatibility is restricted to a node already declared in C5's durable
            # journal. Lane D replaces this with the persisted turn principal before D5; receipt-
            # bearing gates remain closed because they require the Lane-D action reference.
            return ()
        return (
            PreconditionFailure(
                reason_code=(
                    "human_authority_required" if ctx.actor == "human" else "human_required"
                ),
                message=message,
            ),
        )
    if (
        ctx.principal_kind != "human"
        or ctx.actor != "human"
        or ctx.actor_id is None
        or ctx.membership_id is None
        or (action_ref_required and ctx.action_ref is None)
    ):
        return (PreconditionFailure(reason_code=reason_code, message=message),)
    return ()


__all__ = [
    "require_human_authority",
    "tool_context_for_internal_service",
    "tool_context_for_principal",
    "tool_context_for_service",
]
