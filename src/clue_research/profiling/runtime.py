"""Shared runtime wiring for the deep-profiling workers (M8).

The M7 worker/phase protocols (``core.execution``) hand a worker only a context object — never a DB
connection — so a worker obtains its own connection from an injected :data:`SessionFactory` (the M6
pattern: ``db.transaction`` in production, a rollback-scoped connection in tests). Keeping the type
in one place lets the committee (M8.3) and contact (M8.4) workers share it without re-declaring it.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from sqlalchemy.ext.asyncio import AsyncConnection

# A session is an async context manager yielding a connection (committed in prod via
# ``db.transaction``; rolled back per-test). Injected so a worker is testable without committing.
SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncConnection]]
