"""Deterministic document-normalization types plus text/PDF adapters for C3."""

from __future__ import annotations

import io
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, JsonValue

from clue_core import RawArtifact
from clue_research.adapters.seams import AdaptError


class DocumentSegment(BaseModel):
    """One stable, adapter-addressable piece of normalized text."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    locator: dict[str, JsonValue]


class ExtractedDocument(BaseModel):
    """The modality-erased output consumed by the C3 ingestion engine."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    segments: tuple[DocumentSegment, ...]


@runtime_checkable
class DocumentAdapter(Protocol):
    """Raw artifact bytes to stable text segments."""

    adapter_key: str

    def extract(self, artifact: RawArtifact) -> ExtractedDocument: ...


class TextDocumentAdapter:
    """UTF-8 text/markdown split into bounded, stable character ranges."""

    adapter_key = "text"

    def __init__(self, *, max_chars: int = 8_000) -> None:
        if max_chars < 1:
            raise ValueError("max_chars must be positive")
        self._max_chars = max_chars

    def extract(self, artifact: RawArtifact) -> ExtractedDocument:
        try:
            text = artifact.content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise AdaptError("text upload is not valid UTF-8") from exc
        segments: list[DocumentSegment] = []
        start = 0
        while start < len(text):
            stop = min(start + self._max_chars, len(text))
            if stop < len(text):
                boundary = text.rfind("\n", start, stop)
                if boundary > start:
                    stop = boundary + 1
            body = text[start:stop]
            if body:
                segments.append(
                    DocumentSegment(
                        text=body,
                        locator={"kind": "character_range", "start": start, "end": stop},
                    )
                )
            start = stop
        return ExtractedDocument(segments=tuple(segments))


class PdfDocumentAdapter:
    """PDF pages to one stable segment per page via the existing pypdf boundary."""

    adapter_key = "pdf"

    def extract(self, artifact: RawArtifact) -> ExtractedDocument:
        try:
            import pypdf
        except ImportError as exc:  # pragma: no cover - declared production dependency
            raise AdaptError("pypdf is required for PDF extraction") from exc
        try:
            reader = pypdf.PdfReader(io.BytesIO(artifact.content))
            segments = tuple(
                DocumentSegment(
                    text=page.extract_text() or "",
                    locator={"kind": "pdf_page", "page": index + 1},
                )
                for index, page in enumerate(reader.pages)
            )
        except Exception as exc:
            raise AdaptError("could not extract text from PDF upload") from exc
        return ExtractedDocument(segments=tuple(s for s in segments if s.text))
