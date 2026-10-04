"""The O5 bridge reuses one event loop and one pooled engine per process (brand-context fix).

Production 2026-10-03: every design-api store call built a private engine (a new Postgres
connection) and a private event loop (so a new R2 client), and the brand-context page's image and
asset reads queued behind that setup — 300 requests in flight, 30 s median for one image. Each
call is still exactly ONE coroutine in ONE transaction (the binding O5 rule); only the engine and
the loop now live as long as the process.
"""

from __future__ import annotations

import asyncio
import os
import threading

import pytest
from sqlalchemy import text

from lumen_api import design_store
from lumen_api.design_store import DesignStoreBridge

pytestmark = pytest.mark.skipif(
    not os.environ.get("CLUE_DATABASE_URL"), reason="needs a throwaway CLUE_DATABASE_URL"
)


@pytest.fixture
def fresh_bridge(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """A fresh process-wide bridge loop, and a record of every engine the bridge creates."""
    made: list[str] = []
    real = design_store.create_engine

    def counting(url: str | None = None, **kwargs: object):
        made.append(url or "")
        return real(url, **kwargs)

    monkeypatch.setattr(design_store, "create_engine", counting)
    loop_class = getattr(design_store, "_BridgeLoop", None)
    if loop_class is not None:
        monkeypatch.setattr(design_store, "_BRIDGE_LOOP", loop_class())
    return made


async def _probe(conn) -> tuple[asyncio.AbstractEventLoop, int]:
    # The loop object itself (not its id, which a freed loop's successor can reuse).
    await conn.execute(text("SELECT 1"))
    return asyncio.get_running_loop(), threading.get_ident()


def test_calls_share_one_loop_and_one_engine(fresh_bridge: list[str]) -> None:
    first = DesignStoreBridge("ws_bridge_pool", ensure_workspace=False)._run(_probe)
    second = DesignStoreBridge("ws_bridge_pool", ensure_workspace=False)._run(_probe)
    assert first == second
    assert len(fresh_bridge) == 1


def test_calls_from_many_threads_share_the_engine(fresh_bridge: list[str]) -> None:
    results: list[tuple[asyncio.AbstractEventLoop, int]] = []

    def call() -> None:
        results.append(DesignStoreBridge("ws_bridge_pool", ensure_workspace=False)._run(_probe))

    threads = [threading.Thread(target=call) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert len(results) == 8 and len(set(results)) == 1
    assert len(fresh_bridge) == 1


def test_a_different_database_url_gets_its_own_engine(
    fresh_bridge: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    url = os.environ["CLUE_DATABASE_URL"]
    other = url.replace("localhost", "127.0.0.1") if "localhost" in url else url.replace(
        "127.0.0.1", "localhost"
    )
    assert other != url
    DesignStoreBridge("ws_bridge_pool", ensure_workspace=False)._run(_probe)
    monkeypatch.setenv("CLUE_DATABASE_URL", other)
    DesignStoreBridge("ws_bridge_pool", ensure_workspace=False)._run(_probe)
    DesignStoreBridge("ws_bridge_pool", ensure_workspace=False)._run(_probe)
    assert fresh_bridge == [url, other]


def test_a_forked_process_builds_its_own_loop(
    fresh_bridge: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = DesignStoreBridge("ws_bridge_pool", ensure_workspace=False)._run(_probe)
    real_pid = os.getpid()
    monkeypatch.setattr(design_store.os, "getpid", lambda: real_pid + 1)
    child = DesignStoreBridge("ws_bridge_pool", ensure_workspace=False)._run(_probe)
    assert child != parent
    assert len(fresh_bridge) == 2


def test_a_call_made_from_inside_a_call_does_not_deadlock(fresh_bridge: list[str]) -> None:
    async def outer(conn):
        await conn.execute(text("SELECT 1"))
        # A synchronous store call from code already running on the bridge loop.
        return DesignStoreBridge("ws_bridge_pool", ensure_workspace=False)._run(_probe)

    done: list[object] = []
    worker = threading.Thread(
        target=lambda: done.append(
            DesignStoreBridge("ws_bridge_pool", ensure_workspace=False)._run(outer)
        ),
        daemon=True,
    )
    worker.start()
    worker.join(timeout=20)
    assert done, "a nested bridge call deadlocked the bridge loop"
