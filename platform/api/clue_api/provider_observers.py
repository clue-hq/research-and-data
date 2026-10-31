"""The spend layer's observer, bound for platform clients that keep their own HTTP stack.

Exa Websets, Composio, Cloudflare and Clerk report every answer through this observer, so their
calls land on ``provider_call_ledger`` and a refusal (a 402, a quota used up) opens a provider
incident — the founders are told (design ``2026-10-31-provider-credit-and-key-alerts`` §6.4).

The observed call never waits on the database: the recording runs as a background task, held in
:data:`_PENDING` until it finishes so it is never collected half-way.
"""

from __future__ import annotations

import asyncio
from typing import Any

from clue_db import ConnFactory, transaction
from clue_spend import Observe, record_observed_call

#: Providers that bill per call or per result. Their observed rows say ``estimate``; every other
#: observed provider charges nothing per call and says ``free``.
_BILLED = frozenset({"exa_websets"})

#: Recordings still running. A task with no strong reference can be collected mid-flight.
_PENDING: set[asyncio.Task[None]] = set()

#: The recorder, a module attribute so a test can stand in a slow one.
_record = record_observed_call


def cost_source_for(provider: str) -> str:
    return "estimate" if provider in _BILLED else "free"


def provider_observer(
    provider: str, *, workspace_id: str | None = None, conn_factory: ConnFactory = transaction
) -> Observe:
    """The observer one client of ``provider`` reports to; ``workspace_id`` when the call is one
    workspace's, ``None`` when the client serves several (a fleet loop) or none yet."""

    async def observe(**call: Any) -> None:
        task = asyncio.get_running_loop().create_task(
            _record(
                provider=provider,
                conn_factory=conn_factory,
                workspace_id=workspace_id,
                cost_source=cost_source_for(provider),
                **call,
            )
        )
        _PENDING.add(task)
        task.add_done_callback(_PENDING.discard)

    return observe


async def drain_pending() -> None:
    """Wait for every recording in flight (a test, or a process shutting down cleanly)."""
    if _PENDING:
        await asyncio.gather(*list(_PENDING), return_exceptions=True)
