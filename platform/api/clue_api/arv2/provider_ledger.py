"""ARV2's drain — now simply the shared provider-call drain.

The drain itself — buffered sinks, the artifact write, the ``provider_call_ledger`` insert — moved
to :mod:`clue_spend.ledger` in lane 3 slice 5, and since 2026-10-31 the library drain records
provider incidents itself (design ``2026-10-31-provider-credit-and-key-alerts``), so this module
only keeps the old import address: ``from clue_api.arv2.provider_ledger import BufferedLedger,
drain_provider_calls`` is unchanged.
"""

from __future__ import annotations

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
    HeldDrain,
    LedgerStamp,
    _ledger_params,
    _stamped_failure,
    _surface_for,
    artifact_payload,
    drain_provider_calls,
    hold_drain,
    ledger_id_for,
)

__all__ = [
    "ArtifactRefLike",
    "ArtifactSink",
    "BufferedLedger",
    "BufferedRawSink",
    "DrainReport",
    "FailureHook",
    "HeldDrain",
    "LedgerStamp",
    "artifact_payload",
    "drain_provider_calls",
    "hold_drain",
    "ledger_id_for",
]
