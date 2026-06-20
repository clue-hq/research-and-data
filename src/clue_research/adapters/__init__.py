"""`clue_research.adapters` — the modality-adapter framework (M4.3 / ENG-116).

``fetch → adapt → extract`` made *open by registration, not enumeration* (staged-flow §7b): a
source isn't always "fetch a URL and read text" — video/podcasts go through transcription, PDFs
through text extraction, web pages through HTML→markdown, before claim extraction. Adding "anything
on the internet" is registering a manifest (M4.2) + (if non-trivial) an adapter here — not a fork.

Public seam (what callers depend on; the providers stay hidden):

* the :class:`~clue_research.core.ModalityAdapter` protocol (defined in ``core`` alongside
  ``Resolver``) + its value types (:class:`~clue_research.core.RawArtifact`,
  :class:`~clue_research.core.NormalizedText`, :class:`~clue_research.core.ClaimDraft`);
* :func:`register_adapter` / :func:`run_pipeline` / :func:`cost_estimate` — register a modality,
  run a source's chain into written claims, and read a source's pre-spend cost estimate;
* the three **independent provider seams** — :class:`Transcriber`, :class:`PdfTextExtractor`,
  :class:`ScrapeBackend` (+ the :class:`BytesFetcher` transport and :class:`ClaimExtractor`
  extraction seam) — each swappable by config/registration behind ``run_pipeline``;
* the content-addressed :class:`ArtifactCache` (costly fetch/transcription done once per ref).

The concrete adapters (passthrough, PDF, transcription, Firecrawl HTML→markdown) prove the framework
end-to-end and unblock M4.5 (Firecrawl) and M8 (the long tail). This package imports a provider SDK
only behind its seam (import-linter Rule 4) and **never** imports a resolver or another adapter
(Rule 3 / conventions §2).
"""

from __future__ import annotations

from clue_research.adapters.cache import (
    ArtifactCache,
    CachedArtifact,
    InMemoryArtifactCache,
    content_key,
    freshness_ttl,
    is_fresh,
    utc_now,
)
from clue_research.adapters.concrete import (
    FileBytesFetcher,
    FirecrawlHtmlAdapter,
    FirecrawlScrapeBackend,
    InlineBytesFetcher,
    PassthroughAdapter,
    PdfAdapter,
    PypdfTextExtractor,
    TranscriptionAdapter,
)
from clue_research.adapters.extractors import CallableClaimExtractor, ExtractFn, span_for
from clue_research.adapters.pipeline import (
    GateDecision,
    UnknownSourceError,
    cost_estimate,
    run_pipeline,
)
from clue_research.adapters.registry import (
    AdapterNotRegisteredError,
    clear_adapters,
    get_adapter,
    is_adapter_registered,
    register_adapter,
    registered_adapter_keys,
    unregister_adapter,
)
from clue_research.adapters.seams import (
    AdapterError,
    AdaptError,
    BytesFetcher,
    ClaimExtractor,
    FetchError,
    PdfTextExtractor,
    ScrapeBackend,
    Transcriber,
)
from clue_research.core import (
    AdaptContext,
    ClaimDraft,
    ModalityAdapter,
    NormalizedText,
    RawArtifact,
)

__all__ = [
    # core contract (re-exported for ergonomics; defined in clue_research.core)
    "ModalityAdapter",
    "RawArtifact",
    "NormalizedText",
    "ClaimDraft",
    "AdaptContext",
    # dispatch
    "run_pipeline",
    "cost_estimate",
    "GateDecision",
    "UnknownSourceError",
    # adapter registry
    "register_adapter",
    "get_adapter",
    "unregister_adapter",
    "clear_adapters",
    "is_adapter_registered",
    "registered_adapter_keys",
    "AdapterNotRegisteredError",
    # provider seams
    "BytesFetcher",
    "PdfTextExtractor",
    "Transcriber",
    "ScrapeBackend",
    "ClaimExtractor",
    "AdapterError",
    "FetchError",
    "AdaptError",
    # concrete adapters + default backends
    "PassthroughAdapter",
    "PdfAdapter",
    "TranscriptionAdapter",
    "FirecrawlHtmlAdapter",
    "InlineBytesFetcher",
    "FileBytesFetcher",
    "PypdfTextExtractor",
    "FirecrawlScrapeBackend",
    # extraction helpers
    "CallableClaimExtractor",
    "ExtractFn",
    "span_for",
    # artifact cache
    "ArtifactCache",
    "InMemoryArtifactCache",
    "CachedArtifact",
    "content_key",
    "freshness_ttl",
    "is_fresh",
    "utc_now",
]
