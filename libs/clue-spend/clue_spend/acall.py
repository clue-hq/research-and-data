"""One async provider call through the spend layer, drained by itself (design 2026-10-31).

Most paid calls run inside a unit of work that already owns a :class:`ProviderCaller` and drains it
when the unit ends. A handful of async call sites have no such unit — a CRM gateway request, a
Cloudflare hostname check, a Clerk invite, an Exa Websets poll — but do hold a connection factory.
:func:`acall` gives each of them the whole path in one await: the call is made by a caller of its
own (in a worker thread, because the caller is synchronous), its rows are drained right after —
which also records a provider incident when the provider refused — and the response comes back.

The drain never changes the call's outcome: a drain that fails is logged and dropped, and the
caller's own response or error is what the call site sees.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_obs import get_logger

from .calls import CallSpec, ProviderCaller
from .ledger import BufferedLedger, BufferedRawSink, LedgerStamp, drain_provider_calls
from .transport import HttpResponse, HttpxTransport, Transport

__all__ = ["ConnFactory", "acall"]

log = get_logger("clue_spend.acall")

ConnFactory = Callable[[], AbstractAsyncContextManager[AsyncConnection]]


async def acall(
    spec: CallSpec,
    *,
    conn_factory: ConnFactory,
    stamp: LedgerStamp,
    transport: Transport | None = None,
) -> HttpResponse:
    """Make one call, ledger it, record any provider incident it shows, and return the response.

    A non-2xx answer is returned, not raised (the caller's own rule); a transport failure or a
    halt raises the caller's error after the rows are drained.
    """
    raw, ledger = BufferedRawSink(), BufferedLedger()
    caller = ProviderCaller(
        transport=transport or HttpxTransport(),
        raw_sink=raw,
        ledger=ledger,
        now=lambda: datetime.now(UTC),
    )
    try:
        result = await asyncio.to_thread(caller.call, spec)
        return result.response
    finally:
        try:
            async with conn_factory() as conn:
                await drain_provider_calls(
                    conn, raw=raw, ledger=ledger, artifacts=None, stamp=stamp
                )
        except Exception:
            log.exception(
                "provider_incident.recorder_failed",
                provider=spec.provider,
                reason="acall_drain",
            )
