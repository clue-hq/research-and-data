"""Production scoped-memory factories shared by every conversational surface."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_config import MemoryCaps, Settings
from clue_core import (
    AssemblyRequest,
    ContextAssembly,
    LLMGateway,
    MemoryBundle,
    MemorySelectionPin,
    MemorySelectionStale,
    MemorySelectionUnavailable,
    MemoryWriteSeam,
)
from clue_db import ConnFactory
from clue_memory import Assembly, LLMReconcileJudge, WriteSeam


class TransactionalMemoryAssembly(ContextAssembly):
    """Resolve the current advisory bundle inside one database transaction."""

    def __init__(self, *, settings: Settings, conn_factory: ConnFactory) -> None:
        self._settings = settings
        self._caps = MemoryCaps()
        self._conn_factory = conn_factory

    async def assemble(self, request: AssemblyRequest) -> MemoryBundle | None:
        async with self._conn_factory() as conn:
            return await Assembly(
                conn,
                settings=self._settings,
                caps=self._caps,
            ).assemble(request)

    async def select(
        self, request: AssemblyRequest
    ) -> MemorySelectionPin | MemorySelectionUnavailable:
        async with self._conn_factory() as conn:
            return await Assembly(conn, settings=self._settings, caps=self._caps).select(request)

    async def resolve(
        self, request: AssemblyRequest, pin: MemorySelectionPin
    ) -> MemoryBundle | MemorySelectionStale | MemorySelectionUnavailable:
        async with self._conn_factory() as conn:
            return await Assembly(conn, settings=self._settings, caps=self._caps).resolve(
                request, pin
            )


def memory_assembly_factory(
    settings: Settings,
    conn_factory: ConnFactory,
) -> ContextAssembly:
    return TransactionalMemoryAssembly(settings=settings, conn_factory=conn_factory)


def memory_write_factory_builder(
    settings: Settings,
    gateway: LLMGateway,
) -> Callable[[AsyncConnection], MemoryWriteSeam]:
    caps = MemoryCaps()
    judge = LLMReconcileJudge(gateway, model=settings.memory_reconcile_model)

    def factory(conn: AsyncConnection) -> MemoryWriteSeam:
        return WriteSeam(conn, judge, settings=settings, caps=caps)

    return factory


__all__ = [
    "TransactionalMemoryAssembly",
    "memory_assembly_factory",
    "memory_write_factory_builder",
]
