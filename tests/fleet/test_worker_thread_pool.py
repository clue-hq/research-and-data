"""The fleet worker's thread pool is sized for its blocking provider calls (2026-10-05).

Every provider call runs in ``asyncio.to_thread``, and so does the event loop's own DNS lookup
for a fresh database connection — the lease heartbeat's included. On the default pool,
``min(32, cpu + 4)`` threads, a handful of research jobs (each allowed four calls per provider,
some held for minutes) fill it, and the heartbeat waits behind them for a thread. The worker
installs a pool sized by ``CLUE_FLEET_THREAD_POOL_SIZE`` instead.
"""

from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path

import pytest

from clue_config import Settings
from clue_fleet.runner import install_thread_pool

REPO = Path(__file__).resolve().parents[2]

#: More blocking calls than any default pool holds (it caps at 32 threads).
_IN_FLIGHT = 40


def test_a_lookup_is_not_starved_by_blocking_calls_in_flight() -> None:
    async def scenario() -> float:
        loop = asyncio.get_running_loop()
        install_thread_pool(loop, max_workers=64)
        calls = [asyncio.create_task(asyncio.to_thread(time.sleep, 1.5)) for _ in range(_IN_FLIGHT)]
        await asyncio.sleep(0.1)  # let them take their threads
        started = time.monotonic()
        await loop.getaddrinfo("localhost", 5432)
        took = time.monotonic() - started
        await asyncio.gather(*calls)
        return took

    assert asyncio.run(scenario()) < 0.5


def test_the_pool_size_is_an_operator_setting_documented_with_its_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CLUE_FLEET_THREAD_POOL_SIZE", raising=False)
    assert Settings(_env_file=None).fleet_thread_pool_size == 128
    monkeypatch.setenv("CLUE_FLEET_THREAD_POOL_SIZE", "256")
    assert Settings(_env_file=None).fleet_thread_pool_size == 256
    documented = re.search(
        r"^CLUE_FLEET_THREAD_POOL_SIZE=(.*)$",
        (REPO / ".env.example").read_text(),
        re.MULTILINE,
    )
    assert documented is not None and documented.group(1) == "128"
