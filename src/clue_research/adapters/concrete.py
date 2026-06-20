"""Concrete modality adapters + their default provider backends (M4.3 / ENG-116).

Enough to prove the framework end-to-end and unblock M4.5 (Firecrawl scrape) and M8 (the long tail):

* :class:`PassthroughAdapter` — ``text`` / ``structured`` sources that need no transcription/OCR
  (the default so simple sources stay simple).
* :class:`PdfAdapter` — journals/filings: bytes → text via the :class:`PdfTextExtractor` seam
  (default ``pypdf``, behind the adapter — import-linter Rule 4).
* :class:`TranscriptionAdapter` — audio/video: media → transcript via the swappable
  :class:`Transcriber` seam (the costly, gated stage).
* :class:`FirecrawlHtmlAdapter` — the tier-2 official-site scrape normalization M4.5 consumes:
  page → markdown via the :class:`ScrapeBackend` seam (default Firecrawl-backed).

Each adapter composes its modality-specific *transport* (``fetch``) + *normalization* (``adapt``)
with an injected *extraction* (``extract``) seam — three independently-swappable seams behind one
:class:`~clue_research.core.ModalityAdapter`. The live provider clients are **lazy-imported** so the
double-driven CI path (locked decision #3) never needs the SDK/key; the Firecrawl client is wired in
M4.5. Adapters import only ``core`` + these seams — never a resolver or another adapter.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from clue_research.adapters.seams import (
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
    Entity,
    FieldDef,
    Modality,
    NormalizedText,
    RawArtifact,
)

# --- default transport backends ---------------------------------------------


class InlineBytesFetcher:
    """Treat ``ref`` as the inline text content itself — the simplest transport (no network).

    The default for passthrough/text sources and the doubles-driven tests: the caller hands the text
    in as the ``ref`` and it round-trips through the pipeline unchanged.
    """

    def fetch(self, ref: str, ctx: AdaptContext) -> RawArtifact:
        return RawArtifact(ref=ref, media_type="text/plain", content=ref.encode("utf-8"))


class FileBytesFetcher:
    """Read bytes from a local path or ``file://`` ref (hermetic; no network).

    HTTP / authenticated fetching is a resolver concern (M4.5 binds a Firecrawl/HTTP transport),
    kept out of M4.3 so the framework stays offline-testable.
    """

    def fetch(self, ref: str, ctx: AdaptContext) -> RawArtifact:
        path = ref[len("file://") :] if ref.startswith("file://") else ref
        try:
            data = Path(path).read_bytes()
        except OSError as exc:
            raise FetchError(f"could not read artifact at {ref!r}: {exc}") from exc
        return RawArtifact(ref=ref, media_type="application/octet-stream", content=data)


# --- default normalization backends -----------------------------------------


class PypdfTextExtractor:
    """Default PDF→text via ``pypdf`` (lazy import — installed in production; tests inject a
    double).

    Lazy so importing the module never requires the library and CI's double-driven path stays
    hermetic; the import lives here (``adapters/``), the only place import-linter Rule 4 permits it.
    """

    def to_text(self, artifact: RawArtifact) -> NormalizedText:
        try:
            import pypdf
        except ImportError as exc:  # pragma: no cover - production has the dep; CI injects a double
            raise AdaptError("pypdf is required for PDF text extraction; install it") from exc
        try:
            reader = pypdf.PdfReader(io.BytesIO(artifact.content))
            pages = [page.extract_text() or "" for page in reader.pages]
        except Exception as exc:  # pragma: no cover - malformed PDF surfaced as a typed AdaptError
            raise AdaptError(f"could not extract text from PDF {artifact.ref!r}: {exc}") from exc
        return NormalizedText(
            text="\n".join(pages), media_type="text/plain", metadata={"pages": len(pages)}
        )


class FirecrawlScrapeBackend:
    """Default HTML→markdown scrape, Firecrawl-backed (the tier-2 normalization M4.5 consumes).

    The scrape *logic* (call the client, map its markdown result → a :class:`RawArtifact`) is
    duck-typed against an injectable ``client`` so it is unit-testable with a fake; the live client
    is lazy-built from the firecrawl SDK + the ``auth_ref`` credential (wired in M4.5). The SDK
    is imported only here (import-linter Rule 4); CI never builds the live client.
    """

    def __init__(self, *, client: Any | None = None) -> None:
        self._client = client

    def scrape(self, ref: str, ctx: AdaptContext) -> RawArtifact:
        client = self._client or self._build_client(ctx)
        try:
            result = client.scrape_url(ref, formats=["markdown"])
        except (
            Exception
        ) as exc:  # pragma: no cover - live path; tests inject a ScrapeBackend double
            raise FetchError(f"firecrawl scrape of {ref!r} failed: {exc}") from exc
        markdown = _firecrawl_markdown(result)
        if markdown is None:
            raise FetchError(f"firecrawl returned no markdown for {ref!r}")
        return RawArtifact(
            ref=ref,
            media_type="text/markdown",
            content=markdown.encode("utf-8"),
            metadata={"backend": "firecrawl"},
        )

    @staticmethod
    def _build_client(ctx: AdaptContext) -> Any:  # pragma: no cover - live path (M4.5 wires this)
        # Lazy import keeps the SDK out of CI and behind the adapter seam (Rule 4). M4.5 owns the
        # config-selected backend + credential resolution; this interim reads the key from Secrets
        # via the manifest's ``auth_ref`` reference (never the secret in code).
        from firecrawl import FirecrawlApp

        from clue_research.config import Secrets

        secret = getattr(Secrets(), (ctx.auth_ref or "").lower().removeprefix("clue_"), None)
        if secret is None:
            raise FetchError(
                f"no Firecrawl credential resolved for auth_ref {ctx.auth_ref!r}; "
                "wire the live backend in M4.5 or inject a ScrapeBackend double"
            )
        return FirecrawlApp(api_key=secret.get_secret_value())


def _firecrawl_markdown(result: Any) -> str | None:
    """Pull the markdown out of a Firecrawl scrape result (dict-shaped or attribute-shaped)."""
    if isinstance(result, dict):
        value = result.get("markdown")
        return value if isinstance(value, str) else None
    value = getattr(result, "markdown", None)
    return value if isinstance(value, str) else None


# --- the adapters ------------------------------------------------------------


class PassthroughAdapter:
    """``text`` / ``structured`` source needing no transcription/OCR — the default (substrate §7b).

    ``fetch`` gets the bytes (inline by default), ``adapt`` decodes them unchanged, ``extract``
    delegates to the injected :class:`ClaimExtractor`. No transcription/OCR is ever invoked — the
    M4.3 "passthrough still types claims correctly" acceptance criterion.
    """

    def __init__(
        self,
        extractor: ClaimExtractor,
        *,
        fetcher: BytesFetcher | None = None,
        modality: Modality = Modality.TEXT,
    ) -> None:
        self.modality = modality
        self._extractor = extractor
        self._fetcher = fetcher or InlineBytesFetcher()

    def fetch(self, ref: str, ctx: AdaptContext) -> RawArtifact:
        return self._fetcher.fetch(ref, ctx)

    def adapt(self, artifact: RawArtifact, ctx: AdaptContext) -> NormalizedText:
        return NormalizedText(text=artifact.text(), media_type=artifact.media_type)

    def extract(
        self, normalized: NormalizedText, entity: Entity, field: FieldDef
    ) -> list[ClaimDraft]:
        return self._extractor.extract(normalized, entity, field)


class PdfAdapter:
    """PDF source (journals/filings): bytes → text → claims. ``modality = pdf``."""

    modality = Modality.PDF

    def __init__(
        self,
        extractor: ClaimExtractor,
        *,
        pdf_text: PdfTextExtractor | None = None,
        fetcher: BytesFetcher | None = None,
    ) -> None:
        self._extractor = extractor
        self._pdf_text = pdf_text or PypdfTextExtractor()
        self._fetcher = fetcher or FileBytesFetcher()

    def fetch(self, ref: str, ctx: AdaptContext) -> RawArtifact:
        return self._fetcher.fetch(ref, ctx)

    def adapt(self, artifact: RawArtifact, ctx: AdaptContext) -> NormalizedText:
        return self._pdf_text.to_text(artifact)

    def extract(
        self, normalized: NormalizedText, entity: Entity, field: FieldDef
    ) -> list[ClaimDraft]:
        return self._extractor.extract(normalized, entity, field)


class TranscriptionAdapter:
    """Audio/video source: media → transcript → claims. The ``adapt`` stage is the costly,
    *gated* transcription (its own cost span). The :class:`Transcriber` is injected — swapping it
    (a config change) keeps the claim contract, an M4.3 acceptance criterion."""

    def __init__(
        self,
        extractor: ClaimExtractor,
        transcriber: Transcriber,
        *,
        fetcher: BytesFetcher | None = None,
        modality: Modality = Modality.AUDIO,
    ) -> None:
        self.modality = modality
        self._extractor = extractor
        self._transcriber = transcriber
        self._fetcher = fetcher or FileBytesFetcher()

    def fetch(self, ref: str, ctx: AdaptContext) -> RawArtifact:
        return self._fetcher.fetch(ref, ctx)

    def adapt(self, artifact: RawArtifact, ctx: AdaptContext) -> NormalizedText:
        return self._transcriber.transcribe(artifact)

    def extract(
        self, normalized: NormalizedText, entity: Entity, field: FieldDef
    ) -> list[ClaimDraft]:
        return self._extractor.extract(normalized, entity, field)


class FirecrawlHtmlAdapter:
    """The tier-2 HTML→markdown adapter M4.5's Firecrawl resolver consumes (it does not
    hand-roll fetch/parse). ``fetch`` scrapes via the :class:`ScrapeBackend` seam (Firecrawl returns
    markdown); ``adapt`` carries it through as the normalized surface; ``extract`` is injected.
    ``modality = text`` (matches the ``firecrawl_site`` manifest)."""

    modality = Modality.TEXT

    def __init__(self, extractor: ClaimExtractor, *, scraper: ScrapeBackend | None = None) -> None:
        self._extractor = extractor
        self._scraper = scraper or FirecrawlScrapeBackend()

    def fetch(self, ref: str, ctx: AdaptContext) -> RawArtifact:
        return self._scraper.scrape(ref, ctx)

    def adapt(self, artifact: RawArtifact, ctx: AdaptContext) -> NormalizedText:
        return NormalizedText(
            text=artifact.text(), media_type="text/markdown", metadata=artifact.metadata
        )

    def extract(
        self, normalized: NormalizedText, entity: Entity, field: FieldDef
    ) -> list[ClaimDraft]:
        return self._extractor.extract(normalized, entity, field)
