"""Shared doubles for the toolbelt unit tests + the DB skip-gate re-export.

The pure-toolbelt tests need no DB; the ``DbIdempotencyStore`` round-trip test does — so we
re-export the session-migrate + skip-gate fixtures (same pattern as ``tests/api/conftest``) so a
DB test in this scope can request ``require_profiling_db`` and skip gracefully without a database.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from clue_core import new_operation_id
from clue_toolbelt import (
    IdempotencyStore,
    PreconditionFailure,
    StoredInvocation,
    Tool,
    ToolContext,
    ToolInput,
    ToolOutput,
    ToolResult,
)
from tests.db.conftest import run_async as run_async
from tests.profiling.conftest import migrated_db as migrated_db
from tests.profiling.conftest import require_profiling_db as require_profiling_db


class EchoInput(ToolInput):
    value: int
    # An optional field so the S10 hash tests can prove null-vs-omitted stability.
    note: str | None = None


class EchoOutput(ToolOutput):
    echoed: int


class EchoTool(Tool):
    """A trivial tool: echoes its input, records each invoke, and can be told to fail preconditions
    or raise mid-invoke so the runner's precondition/log/release paths can be exercised without a
    real capability."""

    name = "echo"
    version = "1"
    input_model = EchoInput
    output_model = EchoOutput

    def __init__(
        self, *, fail: Sequence[PreconditionFailure] = (), raise_on_invoke: bool = False
    ) -> None:
        self._fail = tuple(fail)
        self._raise = raise_on_invoke
        self.invocations: list[int] = []

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        return self._fail

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, EchoInput)
        if self._raise:
            raise RuntimeError("echo invoke failure (test double)")
        self.invocations.append(inputs.value)
        return ToolResult(tool=self.name, version=self.version, references={"echoed": inputs.value})


class OtherTool(EchoTool):
    """A second tool under a different name — for the same-key-different-tool conflict test."""

    name = "other"
    input_model = EchoInput


class InMemoryStore:
    """An in-memory :class:`IdempotencyStore` mirroring the Db impl's semantics — the
    ``(workspace, key)`` scope, the read-time TTL, and the S4 pending-reservation lifecycle — for
    the runner-logic tests (replay / conflict / expiry / reservation) without a database."""

    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], StoredInvocation] = {}

    async def lookup(
        self, workspace_id: str, idempotency_key: str, *, ttl_s: float, now: datetime | None = None
    ) -> StoredInvocation | None:
        entry = self.rows.get((workspace_id, idempotency_key))
        if entry is None:
            return None
        moment = now if now is not None else datetime.now(UTC)
        if moment - entry.created_at > timedelta(seconds=ttl_s):
            return None
        return entry

    async def reserve(
        self,
        workspace_id: str,
        idempotency_key: str,
        *,
        tool_name: str,
        body_sha256: str,
        ttl_s: float,
        now: datetime | None = None,
    ) -> bool:
        moment = now if now is not None else datetime.now(UTC)
        existing = self.rows.get((workspace_id, idempotency_key))
        if existing is not None and moment - existing.created_at <= timedelta(seconds=ttl_s):
            return False  # a live row holds the slot
        self.rows[(workspace_id, idempotency_key)] = StoredInvocation(
            workspace_id=workspace_id,
            idempotency_key=idempotency_key,
            body_sha256=body_sha256,
            tool_name=tool_name,
            status="pending",
            response_json=None,
            created_at=moment,
        )
        return True

    async def complete(
        self,
        workspace_id: str,
        idempotency_key: str,
        *,
        response_json: dict[str, Any],
        now: datetime | None = None,
    ) -> None:
        entry = self.rows[(workspace_id, idempotency_key)]
        self.rows[(workspace_id, idempotency_key)] = StoredInvocation(
            workspace_id=entry.workspace_id,
            idempotency_key=entry.idempotency_key,
            body_sha256=entry.body_sha256,
            tool_name=entry.tool_name,
            status="completed",
            response_json=response_json,
            created_at=entry.created_at,
        )

    async def release(self, workspace_id: str, idempotency_key: str) -> None:
        entry = self.rows.get((workspace_id, idempotency_key))
        if entry is not None and entry.status == "pending":
            del self.rows[(workspace_id, idempotency_key)]


_STORE_IS_A_STORE: type[IdempotencyStore] = InMemoryStore


def human_ctx(workspace_id: str = "ws_test") -> ToolContext:
    from clue_db import transaction

    return ToolContext(
        workspace_id=workspace_id,
        actor="human",
        conn_factory=transaction,
        operation_id=new_operation_id(),
    )
