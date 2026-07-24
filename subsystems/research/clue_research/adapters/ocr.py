"""Raster-image OCR adapter behind an injectable backend."""

from __future__ import annotations

import io
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from clue_core import RawArtifact
from clue_research.adapters.documents import DocumentSegment, ExtractedDocument
from clue_research.adapters.seams import AdaptError


class OcrBlock(BaseModel):
    """One OCR text block and its pixel bounding box."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    left: int = Field(ge=0)
    top: int = Field(ge=0)
    width: int = Field(ge=0)
    height: int = Field(ge=0)


@runtime_checkable
class OcrBackend(Protocol):
    def recognize(self, content: bytes) -> tuple[OcrBlock, ...]: ...


class PytesseractBackend:
    """Default local OCR backend. Tests inject a deterministic backend."""

    def recognize(self, content: bytes) -> tuple[OcrBlock, ...]:
        try:
            import pytesseract  # type: ignore[import-untyped]
            from PIL import Image
        except ImportError as exc:  # pragma: no cover - production dependencies are declared
            raise AdaptError("Pillow and pytesseract are required for image OCR") from exc
        try:
            data = pytesseract.image_to_data(
                Image.open(io.BytesIO(content)),
                output_type=pytesseract.Output.DICT,
            )
            blocks = []
            for index, raw in enumerate(data["text"]):
                value = str(raw).strip()
                if not value:
                    continue
                blocks.append(
                    OcrBlock(
                        text=value,
                        left=int(data["left"][index]),
                        top=int(data["top"][index]),
                        width=int(data["width"][index]),
                        height=int(data["height"][index]),
                    )
                )
            return tuple(blocks)
        except Exception as exc:
            raise AdaptError("image OCR failed") from exc


class ImageOcrDocumentAdapter:
    adapter_key = "ocr"

    def __init__(self, backend: OcrBackend | None = None) -> None:
        self._backend = backend or PytesseractBackend()

    def extract(self, artifact: RawArtifact) -> ExtractedDocument:
        return ExtractedDocument(
            segments=tuple(
                DocumentSegment(
                    text=block.text,
                    locator={
                        "kind": "image_bbox",
                        "left": block.left,
                        "top": block.top,
                        "width": block.width,
                        "height": block.height,
                    },
                )
                for block in self._backend.recognize(artifact.content)
            )
        )
