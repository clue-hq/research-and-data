"""The provider-caller seam: estimate before the wire, raw before parse, one ledger of record.

Every paid call any subsystem makes goes through :class:`~clue_spend.calls.ProviderCaller`, which
writes an estimate row *before* the wire, saves the raw response *before* anything parses it, and
settles one result row after. That is what makes "what did this cost?" and "what did the provider
actually say?" queries rather than folklore — and it only holds if there is one implementation, so
this package is the one home. It was ARV2's (``clue_api.arv2``) until lane 3 slice 5; ARV2 now
re-exports from here, and the design subsystem imports it directly.

The package may depend on the shared base (``clue_core``, ``clue_obs``) and SQLAlchemy. It imports
no platform or subsystem internals — no ``clue_api``, no ``clue_research``, no ``lumen_*`` — which
is what lets a subsystem import it without importing the platform. ``tests/spend`` enforces that.
"""

from __future__ import annotations

from .calls import (
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_RETRY_STATUSES,
    MAX_INLINE_REQUEST_CHARS,
    CallCost,
    CallResult,
    CallSpec,
    Ceilings,
    CostReader,
    CostReading,
    CostSource,
    HaltRule,
    ProviderCaller,
    RawScrubber,
    SpendEstimate,
)
from .errors import (
    Arv2Error,
    ProviderHalted,
    ProviderTransportError,
    RawParseError,
    RawScrubFailed,
    SpendError,
)
from .ledger import (
    ArtifactRefLike,
    ArtifactSink,
    BufferedLedger,
    BufferedRawSink,
    DrainReport,
    HeldDrain,
    LedgerStamp,
    artifact_payload,
    drain_provider_calls,
    hold_drain,
    ledger_id_for,
    record_drain,
)
from .observe import ConnFactory, Observe, record_observed_call
from .openrouter import openrouter_cost_reader, openrouter_halt_rule
from .sinks import (
    SECRET_HEADERS,
    SECRET_QUERY_PARAMS,
    CallOutcome,
    FileRawSink,
    JsonlLedger,
    LedgerPhase,
    LedgerRow,
    LedgerSink,
    MemoryLedger,
    MemoryRawSink,
    RawRecord,
    RawRequest,
    RawResponse,
    RawSink,
    SpendTotals,
    redact_headers,
    redact_url,
    sha256_hex,
)
from .transport import (
    BROWSER_USER_AGENT,
    HttpRequest,
    HttpResponse,
    HttpxTransport,
    ScriptedTransport,
    Transport,
    TransportFailure,
    json_request,
    lower_headers,
)

__all__ = [
    "ConnFactory",
    "Observe",
    "record_observed_call",
    "BROWSER_USER_AGENT",
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_RETRY_STATUSES",
    "MAX_INLINE_REQUEST_CHARS",
    "SECRET_HEADERS",
    "SECRET_QUERY_PARAMS",
    "ArtifactRefLike",
    "ArtifactSink",
    "Arv2Error",
    "BufferedLedger",
    "BufferedRawSink",
    "CallCost",
    "CallOutcome",
    "CallResult",
    "CallSpec",
    "Ceilings",
    "CostReader",
    "CostReading",
    "CostSource",
    "DrainReport",
    "FileRawSink",
    "HaltRule",
    "HttpRequest",
    "HttpResponse",
    "HttpxTransport",
    "JsonlLedger",
    "LedgerPhase",
    "LedgerRow",
    "LedgerSink",
    "LedgerStamp",
    "MemoryLedger",
    "MemoryRawSink",
    "ProviderCaller",
    "ProviderHalted",
    "ProviderTransportError",
    "RawParseError",
    "RawRecord",
    "RawRequest",
    "RawResponse",
    "RawScrubFailed",
    "RawScrubber",
    "RawSink",
    "ScriptedTransport",
    "SpendEstimate",
    "SpendError",
    "SpendTotals",
    "Transport",
    "TransportFailure",
    "artifact_payload",
    "drain_provider_calls",
    "HeldDrain",
    "hold_drain",
    "record_drain",
    "json_request",
    "ledger_id_for",
    "lower_headers",
    "openrouter_cost_reader",
    "openrouter_halt_rule",
    "redact_headers",
    "redact_url",
    "sha256_hex",
]
