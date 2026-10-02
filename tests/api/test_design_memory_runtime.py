"""Loop lifecycle and timeout handling without providers or a database."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

import pytest

from clue_api.design_memory_runtime import (
    DesignMemoryRuntimeError,
    build_design_preference_resolver_factory,
)
from clue_design.envelopes import DesignTurnEnvelope
from tests.db.conftest import run_async


def _envelope(**updates: Any) -> DesignTurnEnvelope:
    return DesignTurnEnvelope(
        kind="agent_turn",
        workspace_id="test",
        work_id=uuid4(),
        run_id="run",
        checkpoint_thread_id="run",
        config={"design_memory": {}},
    ).model_copy(update=updates)


def test_unavailable_loop_and_legacy_shapes_do_not_attempt_database_reads() -> None:
    loop = asyncio.new_event_loop()
    loop.close()
    factory = build_design_preference_resolver_factory(memory=object(), loop=loop)
    with pytest.raises(DesignMemoryRuntimeError, match="loop_unavailable"):
        factory(_envelope())
    assert factory(_envelope(config={})) is None
    assert factory(_envelope(kind="web_turn")) is None


def test_timeout_cancels_platform_operation_without_exposing_input_or_waiting_forever() -> None:
    async def scenario() -> None:
        cancelled = asyncio.Event()

        @asynccontextmanager
        async def hanging_connection() -> AsyncIterator[Any]:
            try:
                await asyncio.Event().wait()
                yield None
            finally:
                cancelled.set()

        factory = build_design_preference_resolver_factory(
            memory=object(), conn_factory=hanging_connection, timeout_s=0.05
        )
        with pytest.raises(DesignMemoryRuntimeError, match="^design_memory_timeout$"):
            await asyncio.to_thread(factory, _envelope())
        await asyncio.wait_for(cancelled.wait(), timeout=1)

    run_async(scenario())
