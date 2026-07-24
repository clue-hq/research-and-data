"""DOCX normalizer with stable paragraph and table-cell paths."""

from __future__ import annotations

import io
import zipfile
from xml.etree import ElementTree

from clue_core import RawArtifact
from clue_research.adapters.documents import DocumentSegment, ExtractedDocument
from clue_research.adapters.seams import AdaptError

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_MAX_XML_BYTES = 10 * 1024 * 1024


def _text(node: ElementTree.Element) -> str:
    return "".join(part.text or "" for part in node.iter(f"{{{_W}}}t")).strip()


class DocxDocumentAdapter:
    """Read OOXML directly so the adapter remains provider-free and deterministic."""

    adapter_key = "docx"

    def __init__(self, *, max_xml_bytes: int = _MAX_XML_BYTES) -> None:
        self._max_xml_bytes = max_xml_bytes

    def extract(self, artifact: RawArtifact) -> ExtractedDocument:
        try:
            with zipfile.ZipFile(io.BytesIO(artifact.content)) as archive:
                info = archive.getinfo("word/document.xml")
                if info.file_size > self._max_xml_bytes:
                    raise AdaptError("DOCX document XML exceeds the configured limit")
                root = ElementTree.fromstring(archive.read("word/document.xml"))
        except AdaptError:
            raise
        except (KeyError, OSError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
            raise AdaptError("corrupt or unsupported DOCX upload") from exc

        body = root.find(f"{{{_W}}}body")
        if body is None:
            raise AdaptError("DOCX upload has no document body")
        segments: list[DocumentSegment] = []
        paragraph = 0
        table = 0
        for child in body:
            if child.tag == f"{{{_W}}}p":
                value = _text(child)
                if value:
                    segments.append(
                        DocumentSegment(
                            text=value,
                            locator={"kind": "docx_paragraph", "paragraph": paragraph},
                        )
                    )
                paragraph += 1
            elif child.tag == f"{{{_W}}}tbl":
                for row_index, row in enumerate(child.findall(f"{{{_W}}}tr")):
                    for cell_index, cell in enumerate(row.findall(f"{{{_W}}}tc")):
                        value = _text(cell)
                        if value:
                            segments.append(
                                DocumentSegment(
                                    text=value,
                                    locator={
                                        "kind": "docx_table_cell",
                                        "table": table,
                                        "row": row_index,
                                        "cell": cell_index,
                                    },
                                )
                            )
                table += 1
        return ExtractedDocument(segments=tuple(segments))
