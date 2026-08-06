from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from clue_api.locks import scoped_account_lock_factory
from clue_core import EntityId
from tests.db.conftest import run_async
from tests.lock_factory import ProcessLocalLockFactory


def test_separately_composed_factories_reuse_active_account_scope() -> None:
    run_async(_separately_composed_factories_reuse_active_account_scope())


async def _separately_composed_factories_reuse_active_account_scope() -> None:
    account_id = EntityId(uuid4())
    scheduler_physical = ProcessLocalLockFactory()
    tool_physical = ProcessLocalLockFactory()
    scheduler_lock = scoped_account_lock_factory(scheduler_physical)
    tool_lock = scoped_account_lock_factory(tool_physical)

    async with scheduler_lock(account_id), tool_lock(account_id):
        pass

    assert scheduler_physical.acquired[account_id] == 1
    assert tool_physical.acquired[account_id] == 0


def test_independent_task_still_contends_on_physical_account_lock() -> None:
    run_async(_independent_task_still_contends_on_physical_account_lock())


async def _independent_task_still_contends_on_physical_account_lock() -> None:
    account_id = EntityId(uuid4())
    physical = ProcessLocalLockFactory()
    scheduler_lock = scoped_account_lock_factory(physical)
    other_run_lock = scoped_account_lock_factory(physical)
    start = asyncio.Event()
    entered = asyncio.Event()

    async def other_run() -> None:
        await start.wait()
        async with other_run_lock(account_id):
            entered.set()

    # Creating the task before entering the scheduler scope models another run with independent
    # logical ownership; it must not inherit the scheduler's active lease.
    task = asyncio.create_task(other_run())
    async with scheduler_lock(account_id):
        start.set()
        await asyncio.sleep(0)
        assert not entered.is_set()
    await task

    assert entered.is_set()
    assert physical.acquired[account_id] == 2


def test_child_outliving_parent_cannot_reuse_released_scope() -> None:
    run_async(_child_outliving_parent_cannot_reuse_released_scope())


async def _child_outliving_parent_cannot_reuse_released_scope() -> None:
    account_id = EntityId(uuid4())
    physical = ProcessLocalLockFactory()
    lock = scoped_account_lock_factory(physical)
    parent_released = asyncio.Event()

    async def escaped_child() -> None:
        await parent_released.wait()
        async with lock(account_id):
            pass

    async with lock(account_id):
        # This task inherits the scope object, so its post-release behavior exercises the mutable
        # ``active`` guard rather than merely a fresh ContextVar value.
        task = asyncio.create_task(escaped_child())
    parent_released.set()
    await task

    assert physical.acquired[account_id] == 2


def test_nested_different_account_acquires_its_own_physical_lock() -> None:
    run_async(_nested_different_account_acquires_its_own_physical_lock())


async def _nested_different_account_acquires_its_own_physical_lock() -> None:
    first = EntityId(uuid4())
    second = EntityId(uuid4())
    acquired: list[EntityId] = []

    @asynccontextmanager
    async def physical(entity_id: EntityId) -> AsyncIterator[None]:
        acquired.append(entity_id)
        yield

    lock = scoped_account_lock_factory(physical)
    async with lock(first), lock(second):
        pass

    assert acquired == [first, second]
