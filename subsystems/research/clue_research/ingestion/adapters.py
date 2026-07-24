"""Media-type registration for C3 document adapters."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from clue_config.ingestion import IngestionPolicy
from clue_core import EntityScope, Modality, SourceManifest
from clue_research.adapters.documents import (
    DocumentAdapter,
    PdfDocumentAdapter,
    TextDocumentAdapter,
)
from clue_research.adapters.docx import DocxDocumentAdapter
from clue_research.adapters.ocr import ImageOcrDocumentAdapter
from clue_research.adapters.pptx import PptxDocumentAdapter


@dataclass(frozen=True, slots=True)
class RegisteredDocumentAdapter:
    adapter: DocumentAdapter
    paid: bool = False
    gate_manifest: SourceManifest | None = None


class DocumentAdapterRegistry:
    """Open-by-registration media type dispatch with loud collision handling."""

    def __init__(self) -> None:
        self._by_media_type: dict[str, RegisteredDocumentAdapter] = {}

    def register(
        self,
        media_types: tuple[str, ...],
        adapter: DocumentAdapter,
        *,
        paid: bool = False,
        gate_manifest: SourceManifest | None = None,
    ) -> None:
        if paid and gate_manifest is None:
            raise ValueError("a paid document adapter requires a gate_manifest")
        for media_type in media_types:
            if media_type in self._by_media_type:
                raise ValueError(f"document adapter already registered for {media_type!r}")
            self._by_media_type[media_type] = RegisteredDocumentAdapter(
                adapter=adapter, paid=paid, gate_manifest=gate_manifest
            )

    def get(self, media_type: str) -> RegisteredDocumentAdapter | None:
        return self._by_media_type.get(media_type)


def default_document_adapters(policy: IngestionPolicy) -> DocumentAdapterRegistry:
    registry = DocumentAdapterRegistry()
    registry.register(("text/plain", "text/markdown"), TextDocumentAdapter())
    registry.register(("application/pdf",), PdfDocumentAdapter())
    registry.register(
        ("application/vnd.openxmlformats-officedocument.wordprocessingml.document",),
        DocxDocumentAdapter(),
    )
    registry.register(
        ("application/vnd.openxmlformats-officedocument.presentationml.presentation",),
        PptxDocumentAdapter(),
    )
    if policy.ocr_enabled:
        registry.register(
            ("image/png", "image/jpeg", "image/webp", "image/tiff"),
            ImageOcrDocumentAdapter(),
            # Local Tesseract is zero-spend. Hosted OCR implementations register as paid and
            # provide their policy-owned SourceManifest.
        )
    return registry


def paid_ocr_manifest(*, source_key: str, cost_cents: Decimal = Decimal(0)) -> SourceManifest:
    """Fixture/composition helper for a hosted OCR adapter using the shared SourceGate."""
    return SourceManifest(
        source_key=source_key,
        modality=Modality.TEXT,
        entity_scope=EntityScope.BOTH,
        yields=("account", "contact"),
        tier=3,
        cost_cents=cost_cents,
    )
