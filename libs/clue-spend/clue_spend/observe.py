"""Record a provider call that a client of its own made (design 2026-10-31 ruling 8).

Most paid calls go through :class:`~clue_spend.calls.ProviderCaller`, which sends them. A few
clients keep their own HTTP stack because their error taxonomy is load-bearing — the Exa Websets
client must tell "never sent" from "sent, outcome unknown" for a paid create; Composio, Cloudflare
and Clerk map transport faults to their own typed errors that callers act on. Rather than change
how they send, each one reports what came back: :func:`record_observed_call` writes one ``result``
row to ``provider_call_ledger`` with the same failure classification the caller stamps, and drains
it, which opens (or closes) a provider incident.

Recording never changes the call: every failure here is logged and dropped.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_obs import get_logger

from .calls import _failure_extras
from .ledger import BufferedLedger, BufferedRawSink, LedgerStamp, drain_provider_calls
from .sinks import LedgerRow

__all__ = ["ConnFactory", "Observe", "record_observed_call"]

log = get_logger("clue_spend.observe")

ConnFactory = Callable[[], AbstractAsyncContextManager[AsyncConnection]]


class Observe(Protocol):
    """What a client calls after each answer: the operation, its status and body, and how long."""

    def __call__(
        self, *, operation: str, label: str, status: int, body: bytes | str, latency_ms: int
    ) -> Awaitable[None]: ...


async def record_observed_call(
    *,
    provider: str,
    conn_factory: ConnFactory,
    workspace_id: str | None,
    operation: str,
    label: str,
    status: int,
    body: bytes | str,
    latency_ms: int,
) -> None:
    """Ledger one answered call and record any provider incident it shows.

    ``workspace_id`` is ``None`` for a call made on the platform's own behalf (a CRM tool search,
    a Clerk lookup with no workspace yet); the row then carries no workspace.
    """
    try:
        now = datetime.now(UTC)
        ledger = BufferedLedger()
        ledger.record(
            LedgerRow(
                row_id=str(uuid.uuid4()),
                call_id=str(uuid.uuid4()),
                phase="result",
                provider=provider,
                operation=operation,
                label=label,
                recorded_at=now,
                http_status=status,
                latency_ms=latency_ms,
                attempts=1,
                outcome="ok" if 200 <= status < 300 else "client_error",
                extras={"cost_source": "free", **_failure_extras(provider, status, body)},
            )
        )
        async with conn_factory() as conn:
            await drain_provider_calls(
                conn,
                raw=BufferedRawSink(),
                ledger=ledger,
                artifacts=None,
                stamp=LedgerStamp(workspace_id=workspace_id),  # type: ignore[arg-type]
            )
    except Exception:
        log.exception("provider_incident.recorder_failed", provider=provider, reason="observe")
