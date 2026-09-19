"""The sync→async bridge: a process-local loop a synchronous backend can await on.

These tests run entirely offline — no database, no `.env`, no network.  They exercise the
bridge as its real callers will: from a foreign thread, concurrently, past a timeout, and
(illegally) from inside the bridge's own loop.
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Callable, Coroutine, Iterator
from typing import Any

import pytest

from clue_agents.bridge import (
    AsyncBridge,
    BridgeClosed,
    BridgeTimeout,
    process_bridge,
)


@pytest.fixture
def bridge() -> Iterator[AsyncBridge]:
    made = AsyncBridge(name="test-bridge")
    try:
        yield made
    finally:
        made.close()


def test_run_returns_the_coroutine_value_from_a_foreign_thread(bridge: AsyncBridge) -> None:
    """The headline contract: a sync caller gets the coroutine's return value back."""

    async def answer() -> int:
        await asyncio.sleep(0)
        return 42

    captured: dict[str, int] = {}

    def caller() -> None:
        captured["value"] = bridge.run(answer(), timeout_s=5.0)

    worker = threading.Thread(target=caller, name="foreign")
    worker.start()
    worker.join(timeout=5.0)

    assert not worker.is_alive()
    assert captured["value"] == 42
    # The call really did cross threads: the bridge's loop is not the caller's.
    assert bridge.loop.is_running()


def test_two_concurrent_runs_from_two_threads_both_complete(bridge: AsyncBridge) -> None:
    """Two `run` calls are genuinely concurrent on the one loop, not serialized.

    The waiter blocks until the setter runs.  If the bridge ran submissions one at a time the
    waiter would hold the loop forever and both calls would time out.
    """

    gate = asyncio.Event()
    results: dict[str, str] = {}

    async def waiter() -> str:
        await gate.wait()
        return "waited"

    async def setter() -> str:
        gate.set()
        return "set"

    def call(key: str, coro_factory: Callable[[], Coroutine[Any, Any, str]]) -> None:
        results[key] = bridge.run(coro_factory(), timeout_s=5.0)

    threads = [
        threading.Thread(target=call, args=("waiter", waiter), name="t-waiter"),
        threading.Thread(target=call, args=("setter", setter), name="t-setter"),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5.0)

    assert [t.is_alive() for t in threads] == [False, False]
    assert results == {"waiter": "waited", "setter": "set"}


def test_timeout_raises_bridge_timeout_and_the_loop_stays_usable(bridge: AsyncBridge) -> None:
    """A slow coroutine is cancelled and reported — and the next call still works.

    The abandoned coroutine sleeps well past its own timeout, so the fast follow-up below
    proves a cancelled-but-still-settling task does not wedge the loop.
    """

    async def slow() -> str:
        await asyncio.sleep(5.0)
        return "too late"

    async def fast() -> str:
        return "on time"

    started = time.monotonic()
    with pytest.raises(BridgeTimeout):
        bridge.run(slow(), timeout_s=0.05)
    elapsed = time.monotonic() - started

    assert elapsed < 1.0, "run must return at the timeout, not wait out the coroutine"
    assert bridge.run(fast(), timeout_s=5.0) == "on time"


def test_run_from_the_bridge_thread_raises_bridge_re_entered(bridge: AsyncBridge) -> None:
    """Re-entering from inside the loop would deadlock, so it is refused loudly instead."""

    async def inner() -> str:
        return "unreachable"

    async def outer() -> str:
        try:
            bridge.run(inner(), timeout_s=1.0)
        except RuntimeError as exc:
            return str(exc)
        return "no error"

    assert bridge.run(outer(), timeout_s=5.0) == "bridge re-entered"


def test_run_propagates_the_coroutine_exception(bridge: AsyncBridge) -> None:
    """Failures surface at the sync call site unchanged — the bridge is transparent."""

    async def boom() -> None:
        raise ValueError("writer failed")

    with pytest.raises(ValueError, match="writer failed"):
        bridge.run(boom(), timeout_s=5.0)


def test_a_coroutine_timeouterror_is_not_reported_as_a_bridge_timeout(
    bridge: AsyncBridge,
) -> None:
    """A `TimeoutError` raised *by the work* is not the bridge's own deadline."""

    async def its_own_timeout() -> None:
        raise TimeoutError("the writer's own deadline")

    with pytest.raises(TimeoutError, match="the writer's own deadline") as caught:
        bridge.run(its_own_timeout(), timeout_s=5.0)
    assert not isinstance(caught.value, BridgeTimeout)


def test_run_after_close_raises_bridge_closed() -> None:
    """A closed bridge refuses work rather than blocking on a dead loop."""

    closed = AsyncBridge(name="test-bridge-closed")
    closed.close()

    async def never() -> None:
        return None

    with pytest.raises(BridgeClosed):
        closed.run(never(), timeout_s=1.0)


def test_close_is_idempotent_and_stops_the_thread() -> None:
    """`close()` may be called any number of times — atexit plus an explicit close is normal."""

    made = AsyncBridge(name="test-bridge-idempotent")
    made.close()
    made.close()
    made.close()

    assert not made.loop.is_running()


def test_process_bridge_is_a_lazily_created_singleton() -> None:
    """Every sync backend in the process shares one loop, created on first use."""

    first = process_bridge()
    second = process_bridge()

    assert first is second
    assert isinstance(first, AsyncBridge)

    async def answer() -> int:
        return 7

    assert first.run(answer(), timeout_s=5.0) == 7
