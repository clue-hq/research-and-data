"""Shared doubles for the toolbelt unit tests + the DB skip-gate re-export.

The pure-toolbelt tests need no DB; the ``DbIdempotencyStore`` round-trip test does — so we
re-export the session-migrate + skip-gate fixtures (same pattern as ``tests/api/conftest``) so a
DB test in this scope can request ``require_profiling_db`` and skip gracefully without a database.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from clue_toolbelt import (
    IdempotencyStore,
    PreconditionFailure,
    StoredInvocation,
    Tool,
    ToolContext,
    ToolInput,
    ToolResult,
)
from tests.db.conftest import run_async as run_async
from tests.profiling.conftest import migrated_db as migrated_db
from tests.profiling.conftest import require_profiling_db as require_profiling_db


class EchoInput(ToolInput):
    value: int


class EchoTool(Tool):
    """A trivial tool: echoes its input, records each invoke, and can be told to fail preconditions
    so the runner's precondition/log paths can be exercised without a real capability."""

    name = "echo"
    version = "1"
    input_model = EchoInput

    def __init__(self, *, fail: Sequence[PreconditionFailure] = ()) -> None:
        self._fail = tuple(fail)
        self.invocations: list[int] = []

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        return self._fail

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, EchoInput)
        self.invocations.append(inputs.value)
        return ToolResult(tool=self.name, version=self.version, references={"echoed": inputs.value})


class InMemoryStore:
    """An in-memory :class:`IdempotencyStore` mirroring the Db impl's read-time TTL semantics — for
    the runner-logic tests (replay / conflict / expiry) without a database."""

    def __init__(self) -> None:
        self.rows: dict[str, StoredInvocation] = {}

    async def lookup(
        self, idempotency_key: str, *, ttl_s: float, now: datetime | None = None
    ) -> StoredInvocation | None:
        entry = self.rows.get(idempotency_key)
        if entry is None:
            return None
        moment = now if now is not None else datetime.now(UTC)
        if moment - entry.created_at > timedelta(seconds=ttl_s):
            return None
        return entry

    async def record(self, entry: StoredInvocation) -> None:
        self.rows[entry.idempotency_key] = entry


_STORE_IS_A_STORE: type[IdempotencyStore] = InMemoryStore


def human_ctx() -> ToolContext:
    from clue_db import transaction

    return ToolContext(workspace_id="ws_test", actor="human", conn_factory=transaction)
