"""Shared identifiers for durable recipe execution.

Only cross-package identity lives in ``clue_core``. Recipe lifecycle, persistence, and scheduling
remain owned by the platform execution package.
"""

from __future__ import annotations

from typing import NewType
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

ExecutionId = NewType("ExecutionId", UUID)
ExecutionNodeId = NewType("ExecutionNodeId", UUID)
ExecutionAttemptId = NewType("ExecutionAttemptId", UUID)
RecipeId = NewType("RecipeId", UUID)
RecipeRevisionId = NewType("RecipeRevisionId", UUID)
OperationId = NewType("OperationId", UUID)


def new_execution_id() -> ExecutionId:
    return ExecutionId(uuid4())


def new_execution_node_id() -> ExecutionNodeId:
    return ExecutionNodeId(uuid4())


def new_execution_attempt_id() -> ExecutionAttemptId:
    return ExecutionAttemptId(uuid4())


def new_recipe_id() -> RecipeId:
    return RecipeId(uuid4())


def new_recipe_revision_id() -> RecipeRevisionId:
    return RecipeRevisionId(uuid4())


def new_operation_id() -> OperationId:
    """Mint an operation identity for a one-off invocation."""
    return OperationId(uuid4())


def operation_id_from_key(scope: str, key: str) -> OperationId:
    """Derive a stable operation identity from an already-scoped idempotency key."""
    if not scope:
        raise ValueError("operation-id scope must be non-empty")
    if not key:
        raise ValueError("operation-id key must be non-empty")
    return OperationId(uuid5(NAMESPACE_URL, f"clue-operation:{scope}:{key}"))


__all__ = [
    "ExecutionAttemptId",
    "ExecutionId",
    "ExecutionNodeId",
    "OperationId",
    "RecipeId",
    "RecipeRevisionId",
    "new_execution_attempt_id",
    "new_execution_id",
    "new_execution_node_id",
    "new_operation_id",
    "new_recipe_id",
    "new_recipe_revision_id",
    "operation_id_from_key",
]
