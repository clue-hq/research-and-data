"""The ARV2 research lane (master plan §9 Track R).

Two rules govern every module in this package, and both are machine-checked by
``tests/arv2/test_import_guard.py``:

1. **It imports nothing quarantined.** Allowed internal prefixes are ``clue_api.arv2`` itself,
   the shared base (``clue_core``, ``clue_config``, ``clue_obs``, ``clue_db``, ``clue_storage``,
   ``clue_gateway``, ``clue_locks``, ``clue_spine``), the capability planes (``clue_toolbelt``,
   ``clue_agents``, ``clue_execution``, ``clue_fleet``, ``clue_auth``, ``clue_projections``) and
   ``clue_research.claimstore``. Everything else under ``clue_research``, all of ``clue_memory``,
   and any ``clue_api`` module outside ``arv2`` are forbidden — as is every provider SDK.
2. **Every provider call goes through :class:`~clue_api.arv2.calls.ProviderCaller`.** No module
   here opens a socket of its own. That is what makes Appendix A laws 1 and 2 — raw before parse,
   estimate before the wire — properties of the lane rather than habits of its authors.
"""

from __future__ import annotations

from clue_api.arv2.ai_ark_client import AiArkClient
from clue_api.arv2.ats_client import AtsBoard, BoardNotFound, fetch_postings, find_board
from clue_api.arv2.calls import (
    DEFAULT_RETRY_STATUSES,
    CallResult,
    CallSpec,
    Ceilings,
    CostReader,
    CostReading,
    HaltRule,
    ProviderCaller,
    RawScrubber,
    SpendEstimate,
)
from clue_api.arv2.errors import (
    Arv2Error,
    ProviderHalted,
    ProviderTransportError,
    RawParseError,
)
from clue_api.arv2.exa_client import ExaClient
from clue_api.arv2.gemini_media_client import GeminiMediaClient, MediaBudget, MediaCeilingExceeded
from clue_api.arv2.media_feeds_client import (
    UnsupportedMediaHost,
    download_enclosure,
    fetch_feed,
    find_episode,
    youtube_metadata,
    youtube_words,
)
from clue_api.arv2.openrouter import (
    openrouter_chat_request,
    openrouter_cost_reader,
    openrouter_embeddings_request,
    openrouter_halt_rule,
    openrouter_message_text,
)
from clue_api.arv2.sinks import (
    FileRawSink,
    JsonlLedger,
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
)
from clue_api.arv2.text import normalize_for_match, substring_verdict
from clue_api.arv2.transport import (
    BROWSER_USER_AGENT,
    HttpRequest,
    HttpResponse,
    HttpxTransport,
    ScriptedTransport,
    Transport,
    TransportFailure,
    json_request,
)

__all__ = [
    "AiArkClient",
    "AtsBoard",
    "BoardNotFound",
    "ExaClient",
    "GeminiMediaClient",
    "MediaBudget",
    "MediaCeilingExceeded",
    "UnsupportedMediaHost",
    "download_enclosure",
    "fetch_feed",
    "fetch_postings",
    "find_board",
    "find_episode",
    "youtube_metadata",
    "youtube_words",
    "BROWSER_USER_AGENT",
    "DEFAULT_RETRY_STATUSES",
    "Arv2Error",
    "CallResult",
    "CallSpec",
    "Ceilings",
    "CostReader",
    "CostReading",
    "FileRawSink",
    "HaltRule",
    "HttpRequest",
    "HttpResponse",
    "HttpxTransport",
    "JsonlLedger",
    "LedgerRow",
    "LedgerSink",
    "MemoryLedger",
    "MemoryRawSink",
    "ProviderCaller",
    "ProviderHalted",
    "ProviderTransportError",
    "RawParseError",
    "RawRecord",
    "RawRequest",
    "RawResponse",
    "RawScrubber",
    "RawSink",
    "ScriptedTransport",
    "SpendEstimate",
    "SpendTotals",
    "Transport",
    "TransportFailure",
    "json_request",
    "normalize_for_match",
    "openrouter_chat_request",
    "openrouter_cost_reader",
    "openrouter_embeddings_request",
    "openrouter_halt_rule",
    "openrouter_message_text",
    "redact_headers",
    "redact_url",
    "substring_verdict",
]
