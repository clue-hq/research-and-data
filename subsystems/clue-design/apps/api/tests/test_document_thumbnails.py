"""Unit cover for the gallery thumbnail generator (`lumen_api.document_thumbnails`).

The pure halves — runtime resolution, the Tailwind inline splice, the engine-PNG
decode, the downscale, the scene page pick — run everywhere. The one capture test
launches a real Chromium (nothing else proves a Tailwind arbitrary-value class
actually compiled) and skips honestly when the browser or the runtime is absent.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from lumen_api import document_thumbnails as thumbs


def _png(width: int, height: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (12, 34, 56)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_inline_tailwind_lands_before_head_close():
    html = "<html><head><title>t</title></head><body><p>hi</p></body></html>"
    out = thumbs.inline_tailwind(html, b"RUNTIME_JS")
    # The splice is web_substrate's, newline and all (web_substrate.py:8880).
    assert "<script>RUNTIME_JS</script>\n</head>" in out


def test_inline_tailwind_without_head_prepends():
    html = "<html><body><p>hi</p></body></html>"
    out = thumbs.inline_tailwind(html, b"RUNTIME_JS")
    # Never dropped: with no `</head>` the runtime goes in front of the document,
    # so it still loads before the theme block it has to compile.
    assert out.startswith("<script>RUNTIME_JS</script>")
    assert html in out


def test_downscale_caps_the_long_edge_and_keeps_aspect():
    data = thumbs.downscale_png(_png(2000, 1000), max_edge=724)
    image = Image.open(io.BytesIO(data))
    assert image.size == (724, 362)


def test_downscale_never_upscales():
    data = thumbs.downscale_png(_png(400, 300), max_edge=724)
    image = Image.open(io.BytesIO(data))
    assert image.size == (400, 300)


def test_png_from_export_result_decodes_engine_bytes():
    png = _png(10, 10)
    result = {
        "ok": True,
        "export": {"artifacts": [{"bytes": list(png), "mime_type": "image/png"}]},
    }
    assert thumbs.png_from_export_result(result) == png


def test_png_from_export_result_refuses_a_failed_export():
    with pytest.raises(thumbs.ThumbnailUnavailable) as raised:
        thumbs.png_from_export_result({"ok": False, "export": {}})
    assert raised.value.code == "thumbnail.export_failed"


def test_png_from_export_result_refuses_an_empty_artifact():
    result = {"ok": True, "export": {"artifacts": [{"bytes": [], "mime_type": "image/png"}]}}
    with pytest.raises(thumbs.ThumbnailUnavailable) as raised:
        thumbs.png_from_export_result(result)
    assert raised.value.code == "thumbnail.export_failed"


def test_first_page_ids_takes_the_first_page_only():
    # A scene's pages are a MAP keyed by page id (engine `BTreeMap<PageId, Page>`),
    # not a list — confirmed against a stored `doc_kind='scene'` document.
    scene = {"pages": {"page_a4": {"id": "page_a4"}, "page_b": {"id": "page_b"}}}
    assert thumbs.first_page_ids(scene) == ["page_a4"]


def test_first_page_ids_none_when_shape_unknown():
    assert thumbs.first_page_ids({}) is None
    # A web document's pages ARE a list; this function only speaks scene, and a
    # guessed answer would export the wrong page.
    assert thumbs.first_page_ids({"pages": [{"id": "p1"}]}) is None


def test_resolve_tailwind_runtime_refuses_a_named_but_missing_override(monkeypatch, tmp_path):
    monkeypatch.setenv(thumbs._TAILWIND_RUNTIME_ENV, str(tmp_path / "nope.js"))
    assert thumbs.resolve_tailwind_runtime() is None


def test_resolve_tailwind_runtime_reads_the_override(monkeypatch, tmp_path):
    runtime = tmp_path / "tailwind.js"
    runtime.write_text("RUNTIME_JS", encoding="utf-8")
    monkeypatch.setenv(thumbs._TAILWIND_RUNTIME_ENV, str(runtime))
    assert thumbs.resolve_tailwind_runtime() == b"RUNTIME_JS"


def test_web_thumbnail_png_refuses_without_a_runtime(monkeypatch, tmp_path):
    monkeypatch.setenv(thumbs._TAILWIND_RUNTIME_ENV, str(tmp_path / "nope.js"))
    with pytest.raises(thumbs.ThumbnailUnavailable) as raised:
        thumbs.web_thumbnail_png("<html><body></body></html>")
    assert raised.value.code == "thumbnail.tailwind_runtime_missing"


def _chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            pw.chromium.launch(headless=True).close()
        return True
    except Exception:
        return False


@pytest.mark.skipif(
    not (_chromium_available() and thumbs.resolve_tailwind_runtime() is not None),
    reason="playwright chromium or the Tailwind browser runtime is not installed",
)
def test_web_thumbnail_png_captures_styled_html(monkeypatch):
    # A page that is red only if arbitrary-value Tailwind classes compiled.
    monkeypatch.delenv(thumbs._TAILWIND_RUNTIME_ENV, raising=False)
    html = (
        "<html><head></head><body>"
        '<div class="min-h-screen bg-[rgb(255,0,0)]"></div>'
        "</body></html>"
    )
    data = thumbs.web_thumbnail_png(html)
    image = Image.open(io.BytesIO(data))
    assert image.size == (724, 543)
    assert image.convert("RGB").getpixel((362, 271)) == (255, 0, 0)
