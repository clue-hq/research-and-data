from __future__ import annotations

import io
import zipfile

import pytest

from clue_core import RawArtifact
from clue_research.adapters.documents import PdfDocumentAdapter, TextDocumentAdapter
from clue_research.adapters.docx import DocxDocumentAdapter
from clue_research.adapters.ocr import ImageOcrDocumentAdapter, OcrBlock
from clue_research.adapters.pptx import PptxDocumentAdapter
from clue_research.adapters.seams import AdaptError


def _zip(files: dict[str, str]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as archive:
        for name, body in files.items():
            archive.writestr(name, body)
    return out.getvalue()


def _pdf(text: str) -> bytes:
    objects = (
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            "/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
        ),
        (
            f"<< /Length {len(text) + 34} >>\nstream\n"
            f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET\nendstream"
        ),
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    )
    body = b"%PDF-1.4\n"
    offsets = [0]
    for number, value in enumerate(objects, 1):
        offsets.append(len(body))
        body += f"{number} 0 obj\n{value}\nendobj\n".encode()
    xref = len(body)
    body += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets[1:]:
        body += f"{offset:010d} 00000 n \n".encode()
    body += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    ).encode()
    return body


def test_text_segments_are_stable_and_addressable() -> None:
    artifact = RawArtifact(ref="upload", media_type="text/markdown", content=b"alpha\nbeta\ngamma")
    adapter = TextDocumentAdapter(max_chars=8)
    first = adapter.extract(artifact)
    second = adapter.extract(artifact)
    assert first == second
    assert "".join(segment.text for segment in first.segments) == "alpha\nbeta\ngamma"
    assert first.segments[0].locator == {"kind": "character_range", "start": 0, "end": 6}


def test_pdf_page_path_is_stable() -> None:
    artifact = RawArtifact(ref="upload", media_type="application/pdf", content=_pdf("Acme proof"))
    first = PdfDocumentAdapter().extract(artifact)
    second = PdfDocumentAdapter().extract(artifact)
    assert first == second
    assert first.segments[0].text == "Acme proof"
    assert first.segments[0].locator == {"kind": "pdf_page", "page": 1}


def test_invalid_utf8_fails_loud() -> None:
    with pytest.raises(AdaptError, match="UTF-8"):
        TextDocumentAdapter().extract(
            RawArtifact(ref="upload", media_type="text/plain", content=b"\xff")
        )


def test_docx_paragraph_and_table_cell_paths_are_stable() -> None:
    xml = """\
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>
        <w:p><w:r><w:t>Overview</w:t></w:r></w:p>
        <w:tbl><w:tr><w:tc><w:p><w:r><w:t>Proof point</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
      </w:body>
    </w:document>
    """
    artifact = RawArtifact(
        ref="upload",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        content=_zip({"word/document.xml": xml}),
    )
    result = DocxDocumentAdapter().extract(artifact)
    assert tuple(segment.text for segment in result.segments) == ("Overview", "Proof point")
    assert result.segments[1].locator == {
        "kind": "docx_table_cell",
        "table": 0,
        "row": 0,
        "cell": 0,
    }


def test_pptx_slide_and_shape_paths_are_stable() -> None:
    xml = """\
    <p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
           xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
      <p:cSld><p:spTree><p:sp>
        <p:nvSpPr><p:cNvPr id="2" name="Title 1"/></p:nvSpPr>
        <p:txBody><a:p><a:r><a:t>Acme proof</a:t></a:r></a:p></p:txBody>
      </p:sp></p:spTree></p:cSld>
    </p:sld>
    """
    artifact = RawArtifact(
        ref="upload",
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        content=_zip({"ppt/slides/slide1.xml": xml}),
    )
    result = PptxDocumentAdapter().extract(artifact)
    assert len(result.segments) == 1
    assert result.segments[0].text == "Acme proof"
    assert result.segments[0].locator == {
        "kind": "pptx_shape",
        "slide": 1,
        "shape": "Title 1",
    }


class _Ocr:
    def recognize(self, content: bytes) -> tuple[OcrBlock, ...]:
        assert content == b"image"
        return (OcrBlock(text="Acme", left=1, top=2, width=30, height=10),)


def test_ocr_preserves_bounding_box() -> None:
    result = ImageOcrDocumentAdapter(_Ocr()).extract(
        RawArtifact(ref="upload", media_type="image/png", content=b"image")
    )
    assert result.segments[0].locator == {
        "kind": "image_bbox",
        "left": 1,
        "top": 2,
        "width": 30,
        "height": 10,
    }


@pytest.mark.parametrize(
    ("adapter", "media_type"),
    [
        (
            DocxDocumentAdapter(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        (
            PptxDocumentAdapter(),
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ),
    ],
)
def test_corrupt_office_documents_fail_without_embedding_content(adapter, media_type: str) -> None:
    with pytest.raises(AdaptError, match="corrupt or unsupported"):
        adapter.extract(RawArtifact(ref="upload", media_type=media_type, content=b"secret bytes"))


def test_office_xml_expansion_limit_fails_before_parse() -> None:
    artifact = RawArtifact(
        ref="upload",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        content=_zip({"word/document.xml": "<document>oversized</document>"}),
    )
    with pytest.raises(AdaptError, match="configured limit"):
        DocxDocumentAdapter(max_xml_bytes=8).extract(artifact)
