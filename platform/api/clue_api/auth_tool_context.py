"""Provider-neutral conversion from authenticated principals to ambient tool authority.

Lane D supplies the durable ``action_ref``; this module only binds it to the already-resolved
internal principal. Provider tokens, subjects, and client-authored actor fields never enter the
tool context.
"""

from __future__ import annotations

from clue_auth import RequestPrincipal, ServicePrincipal
from clue_core import ExecutionId, ExecutionNodeId, OperationId
from clue_db import ConnFactory
from clue_toolbelt import ToolContext


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


__all__ = ["tool_context_for_principal", "tool_context_for_service"]
