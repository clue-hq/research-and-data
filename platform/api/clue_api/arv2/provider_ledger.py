"""ARV2's drain: the shared provider-call drain with the platform's incident recorder bound.

The drain itself — buffered sinks, the artifact write, the ``provider_call_ledger`` insert — moved
to :mod:`clue_spend.ledger` in lane 3 slice 5, so the design subsystem's spend lands on the same
one ledger. Everything is re-exported here, and existing imports
(``from clue_api.arv2.provider_ledger import BufferedLedger, drain_provider_calls``) are unchanged.

What did *not* move is the one platform-specific thing this module ever did: turning a stamped
provider failure into a **provider incident**. ``clue_spend`` may not import ``clue_api``, so the
shared drain takes a :data:`~clue_spend.ledger.FailureHook` and the binding lives here.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.provider_incidents import record_failure, record_success

# ``_INSERT_LEDGER``, ``_ledger_params`` and ``_surface_for`` are private to the drain, but the
# incident tests build a ledger row through them directly (they assert on what the drain *writes*
# without owning a caller), so the names stay reachable from this module's old address.
from clue_spend.ledger import (  # noqa: F401
    _INSERT_LEDGER,
    ArtifactRefLike,
    ArtifactSink,
    BufferedLedger,
    BufferedRawSink,
    DrainReport,
    FailureHook,
    LedgerStamp,
    _ledger_params,
    _stamped_failure,
    _surface_for,
    artifact_payload,
    ledger_id_for,
)
from clue_spend.ledger import drain_provider_calls as _drain
from clue_spend.sinks import LedgerRow

__all__ = [
    "ArtifactRefLike",
    "ArtifactSink",
    "BufferedLedger",
    "BufferedRawSink",
    "DrainReport",
    "FailureHook",
    "LedgerStamp",
    "artifact_payload",
    "drain_provider_calls",
    "ledger_id_for",
]


async def drain_provider_calls(
    conn: AsyncConnection,
    *,
    raw: BufferedRawSink,
    ledger: BufferedLedger,
    artifacts: ArtifactSink | None,
    stamp: LedgerStamp,
) -> DrainReport:
    """The shared drain, plus the platform's provider-incident bookkeeping.

    ``artifacts=None`` is the design lane (lane 3 slice 5): its bodies are not persisted to the
    platform's artifact store, so its rows land citing nothing there — but its failures still open
    and close provider incidents under the same ARV2 rule, which is the whole point of routing the
    design drain through this shim rather than the bare library one.

    Every stamped failure lands on an incident as the rows are drained, and a provider closes its
    incidents only when its **last word in this batch** was a success.

    A drain is not one call, it is a whole hop's worth — a discovery drain routinely holds two
    hundred good rows and then the 402 that stopped it. Closing on the mere *presence* of an ``ok``
    row would open that incident and shut it again inside the same drain, so the two are folded per
    provider by time: ``last_ok_at`` has to exist and be later than ``last_failure_at`` before
    :func:`record_success` is called at all. Failures are recorded first and one at a time (each
    one counts toward the threshold and names its own surface, through the drain's hook); the close
    is one indexed UPDATE per provider, so thirty good rows still cost one statement.
    """
    last_failure_at: dict[str, datetime] = {}

    async def on_failure(
        conn_: AsyncConnection, row: LedgerRow, stamp_: LedgerStamp, surface: str
    ) -> None:
        failure = _stamped_failure(row)
        if failure is None:
            return
        seen = last_failure_at.get(row.provider, row.recorded_at)
        last_failure_at[row.provider] = max(seen, row.recorded_at)
        await record_failure(
            conn_,
            failure,
            surface=surface,
            workspace_id=stamp_.workspace_id,
            now=row.recorded_at,
        )

    report = await _drain(
        conn, raw=raw, ledger=ledger, artifacts=artifacts, stamp=stamp, on_failure=on_failure
    )

    last_ok_at: dict[str, datetime] = {}
    for row in report.result_rows:
        if row.outcome == "ok" and _stamped_failure(row) is None:
            seen = last_ok_at.get(row.provider, row.recorded_at)
            last_ok_at[row.provider] = max(seen, row.recorded_at)
    for provider, ok_at in last_ok_at.items():
        failed_at = last_failure_at.get(provider)
        if failed_at is None or ok_at > failed_at:
            await record_success(conn, provider, now=ok_at)

    return report
