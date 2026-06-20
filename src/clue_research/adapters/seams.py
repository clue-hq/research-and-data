"""The swappable provider seams behind the modality adapters (M4.3 / ENG-116).

Three independent seams (staged-flow §7b): *transport* (fetch bytes), *normalization* (transcribe /
extract-text / scrape→markdown), and *extraction* (text → typed claim drafts). Each is a Protocol,
so the provider is a config/registration choice — swap the transcription provider, the PDF
extractor, or the HTML→markdown backend without touching ``run_pipeline`` or any caller. Concrete
defaults live in :mod:`clue_research.adapters.concrete`; CI exercises the framework with
deterministic doubles (locked decision #3 — hermetic, no live provider call). Adapters import only
these shared shapes; they never import a resolver or another adapter (``_conventions.md`` §2;
import-linter Rule 3).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from clue_research.core import (
    AdaptContext,
    ClaimDraft,
    Entity,
    FieldDef,
    NormalizedText,
    RawArtifact,
)


class AdapterError(RuntimeError):
    """Base error for the modality-adapter framework (a typed failure callers can catch)."""


class FetchError(AdapterError):
    """A source's *transport* (``fetch``) failed (unreachable ref, unreadable artifact)."""


class AdaptError(AdapterError):
    """A source's *normalization* (``adapt``) or extraction failed (bad PDF, missing provider,
    an evidence span not grounded in the normalized text)."""


@runtime_checkable
class BytesFetcher(Protocol):
    """Transport seam: turn a ``ref`` into raw bytes. The default reads a local file / inline text;
    an HTTP/authenticated fetcher (M4.5 Firecrawl, M8 long-tail) swaps in here."""

    def fetch(self, ref: str, ctx: AdaptContext) -> RawArtifact: ...


@runtime_checkable
class PdfTextExtractor(Protocol):
    """Normalization seam for PDFs: bytes → text. The default wraps ``pypdf`` (behind the adapter,
    import-linter Rule 4); a swap (OCR, a hosted parser) changes only this binding."""

    def to_text(self, artifact: RawArtifact) -> NormalizedText: ...


@runtime_checkable
class Transcriber(Protocol):
    """Normalization seam for audio/video: media → transcript. The provider (Whisper / Deepgram /
    AssemblyAI …) is an open M8 choice — swapping it keeps the claim contract (an M4.3 acceptance
    criterion). M4.3 ships the seam; callers/tests inject the implementation (a double in CI)."""

    def transcribe(self, artifact: RawArtifact) -> NormalizedText: ...


@runtime_checkable
class ScrapeBackend(Protocol):
    """Normalization seam for the web: fetch a page and return it as markdown (Firecrawl-shaped).
    Config-selected (M4.5 wires the live Firecrawl client + key); tests inject a double."""

    def scrape(self, ref: str, ctx: AdaptContext) -> RawArtifact: ...


@runtime_checkable
class ClaimExtractor(Protocol):
    """Extraction seam: normalized text + (entity, field) → :class:`ClaimDraft`s, each carrying the
    exact ``evidence_span``. Field-specific — an LLM extractor (M8/M11) or a structured parser
    (M4.5) plugs in here. ``run_pipeline`` stamps tier/extraction_method, so the extractor never
    decides trust (adaptation never upgrades trust)."""

    def extract(
        self, normalized: NormalizedText, entity: Entity, field: FieldDef
    ) -> list[ClaimDraft]: ...
