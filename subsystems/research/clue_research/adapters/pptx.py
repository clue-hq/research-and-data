"""PPTX normalizer with stable slide and shape paths."""

from __future__ import annotations

import io
import re
import zipfile
from xml.etree import ElementTree

from clue_core import RawArtifact
from clue_research.adapters.documents import DocumentSegment, ExtractedDocument
from clue_research.adapters.seams import AdaptError

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_SLIDE_RE = re.compile(r"ppt/slides/slide(\d+)\.xml$")
_MAX_SLIDE_XML_BYTES = 10 * 1024 * 1024


def _shape_name(shape: ElementTree.Element, fallback: int) -> str:
    node = shape.find(f".//{{{_P}}}cNvPr")
    name = node.get("name") if node is not None else None
    return name or f"shape-{fallback}"


class PptxDocumentAdapter:
    """Read OOXML slide text directly; animations and speaker notes are out of C3 scope."""

    adapter_key = "pptx"

    def __init__(self, *, max_xml_bytes: int = _MAX_SLIDE_XML_BYTES) -> None:
        self._max_xml_bytes = max_xml_bytes

    def extract(self, artifact: RawArtifact) -> ExtractedDocument:
        try:
            with zipfile.ZipFile(io.BytesIO(artifact.content)) as archive:
                slide_names = sorted(
                    (
                        (int(match.group(1)), name)
                        for name in archive.namelist()
                        if (match := _SLIDE_RE.fullmatch(name))
                    ),
                    key=lambda item: item[0],
                )
                xml_sizes = tuple(archive.getinfo(name).file_size for _, name in slide_names)
                if (
                    any(size > self._max_xml_bytes for size in xml_sizes)
                    or sum(xml_sizes) > self._max_xml_bytes
                ):
                    raise AdaptError("PPTX slide XML exceeds the configured limit")
                roots = [
                    (number, ElementTree.fromstring(archive.read(name)))
                    for number, name in slide_names
                ]
        except AdaptError:
            raise
        except (OSError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
            raise AdaptError("corrupt or unsupported PPTX upload") from exc

        segments: list[DocumentSegment] = []
        for slide_number, root in roots:
            shapes = root.findall(f".//{{{_P}}}sp")
            for shape_index, shape in enumerate(shapes):
                value = "\n".join(
                    text for text in (node.text or "" for node in shape.iter(f"{{{_A}}}t")) if text
                ).strip()
                if value:
                    segments.append(
                        DocumentSegment(
                            text=value,
                            locator={
                                "kind": "pptx_shape",
                                "slide": slide_number,
                                "shape": _shape_name(shape, shape_index),
                            },
                        )
                    )
        return ExtractedDocument(segments=tuple(segments))
