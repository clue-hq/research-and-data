"""Shared process-local per-entity lock factory for the scheduler test suites (fleet + durable).

The testable analogue of the production Redis entity lock (``clue_locks.entity_lock`` /
``clue_research.durable.account_entity_lock_factory``): an ``asyncio.Lock`` per entity that
single-flights same-entity ``run_one`` calls, so two campaign runs never deep-research one entity
at once (Doc C §4). One implementation, shared by ``tests/fleet`` (its conftest fakes and the
exit-gate harness subprocess) and ``tests/durable`` — previously three near-identical copies.

Kept **dependency-light** (stdlib + ``clue_core`` only, no pytest) on purpose: the exit-gate
harness runs as a detached subprocess and imports this module, so it must not drag the pytest
runtime.

Keyed on the ``EntityId`` OBJECT, not its string form — mirroring the production lock, which keys
on the resolved ``entity_id``. Keying on the value (an ``EntityId`` is a distinct ``UUID``, so
hashable and value-equal) serializes exactly the identity the real lock serializes, with no
assumption baked in about a canonical string spelling of the id.
"""

from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

from clue_core import EntityId


class ProcessLocalLockFactory:
    """Callable as ``factory(entity_id) -> async context manager``.

    A per-entity ``asyncio.Lock`` (via ``defaultdict``, keyed on the ``EntityId`` object)
    single-flights same-entity runs; the ``acquired`` :class:`~collections.Counter` records one
    tick per successful acquisition, so a test can assert the lock was actually taken (e.g. that a
    replayed done job still acquires it)."""

    def __init__(self) -> None:
        self._locks: dict[EntityId, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.acquired: Counter[EntityId] = Counter()

    def __call__(self, entity_id: EntityId) -> AbstractAsyncContextManager[Any]:
        return self._guarded(entity_id)

    @asynccontextmanager
    async def _guarded(self, entity_id: EntityId) -> AsyncIterator[None]:
        async with self._locks[entity_id]:
            self.acquired[entity_id] += 1
            yield
