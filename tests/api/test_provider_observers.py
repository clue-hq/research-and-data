"""The platform's provider observer never makes the observed call wait on the database."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from clue_api import provider_observers
from clue_api.provider_observers import cost_source_for, provider_observer


def test_the_observer_returns_before_the_recording_finishes() -> None:
    async def scenario() -> tuple[bool, bool]:
        release = asyncio.Event()
        recorded = asyncio.Event()

        @asynccontextmanager
        async def slow():
            await release.wait()  # a database that has not answered yet
            yield object()

        async def fake_record(**_kwargs: object) -> None:
            async with slow():
                recorded.set()

        provider_observers._record = fake_record  # type: ignore[assignment]
        observe = provider_observer("composio")
        await asyncio.wait_for(
            observe(operation="o", label="l", status=200, body=b"{}", latency_ms=1), timeout=1
        )
        returned_first = not recorded.is_set()
        release.set()
        await provider_observers.drain_pending()
        return returned_first, recorded.is_set()

    original = provider_observers._record
    try:
        assert asyncio.run(scenario()) == (True, True)
    finally:
        provider_observers._record = original  # type: ignore[assignment]


def test_cost_source_names_the_billed_provider() -> None:
    assert cost_source_for("exa_websets") == "estimate" and cost_source_for("cloudflare") == "free"
