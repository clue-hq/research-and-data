from __future__ import annotations

import io
import random

import pytest

from lumen_ingestion.capture.uploads import (
    UploadFileInput,
    analyze_uploads,
    sniff_mime,
)


def _noop(stage: str, progress: float) -> None:
    return None


class _StubCore:
    """Records ingest_asset calls; returns a trivial success record."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def ingest_asset(self, **kwargs) -> dict:
        self.calls.append(kwargs)
        return {"asset_id": kwargs["asset_id"], "ok": True}


# --------------------------------------------------------------------------- #
# In-test image generators (Pillow) — no binary fixtures.
# --------------------------------------------------------------------------- #


def _png_bytes(img) -> bytes:
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def _teal_logo_png() -> bytes:
    from PIL import Image

    img = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    for x in range(40, 160):
        for y in range(40, 160):
            img.putpixel((x, y), (0, 128, 128, 255))
    return _png_bytes(img)


def _reversed_mark_png() -> bytes:
    """White-on-transparent mark (96×96) → reversed variant + mark usage."""
    from PIL import Image

    img = Image.new("RGBA", (96, 96), (0, 0, 0, 0))
    for x in range(20, 76):
        for y in range(20, 76):
            img.putpixel((x, y), (245, 245, 245, 255))
    return _png_bytes(img)


def _photo_jpeg() -> bytes:
    from PIL import Image

    rng = random.Random(7)
    img = Image.new("RGB", (1200, 900))
    px = img.load()
    for x in range(1200):
        for y in range(0, 900, 3):  # coarse rows; keep the loop cheap
            r = (x * 255) // 1200
            g = (y * 255) // 900
            b = rng.randint(0, 255)
            for yy in range(y, min(y + 3, 900)):
                px[x, yy] = (r, g, b)
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=80)
    return buffer.getvalue()


_SVG_SRC = (
    '<?xml version="1.0"?>\n'
    '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="200" '
    'viewBox="0 0 300 200">\n'
    '  <rect width="300" height="200" fill="#FF6600"/>\n'
    '  <circle cx="150" cy="100" r="60" style="fill:#0044CC;stroke:#FFFFFF"/>\n'
    "</svg>\n"
)


def _svg_bytes() -> bytes:
    return _SVG_SRC.encode("utf-8")


# --------------------------------------------------------------------------- #
# Magic-byte sniffing
# --------------------------------------------------------------------------- #


def test_sniff_accepts_supported_types() -> None:
    assert sniff_mime(_teal_logo_png()) == "image/png"
    assert sniff_mime(_photo_jpeg()) == "image/jpeg"
    assert sniff_mime(_svg_bytes()) == "image/svg+xml"


def test_sniff_rejects_unknown() -> None:
    assert sniff_mime(b"not an image at all, just plain text bytes") is None
    assert sniff_mime(b"%PDF-1.4 fake pdf") is None


# --------------------------------------------------------------------------- #
# Classification + variant hints
# --------------------------------------------------------------------------- #


def test_transparent_teal_classified_logo() -> None:
    core = _StubCore()
    files = [UploadFileInput("mark-teal.png", "image/png", _teal_logo_png())]
    evidence, diags = analyze_uploads(
        files, core=core, store_root="/tmp/store", reporter=_noop
    )
    assert len(evidence.logos) == 1
    logo = evidence.logos[0]
    assert logo.color_mode_hint in ("full_color", "one_color")
    assert not diags


def test_reversed_mark_hints() -> None:
    core = _StubCore()
    files = [UploadFileInput("emblem.png", "image/png", _reversed_mark_png())]
    evidence, _ = analyze_uploads(
        files, core=core, store_root="/tmp/store", reporter=_noop
    )
    assert len(evidence.logos) == 1
    logo = evidence.logos[0]
    assert logo.color_mode_hint == "reversed"
    assert logo.background_hint == "#121212"
    assert logo.usage_hint == "mark"


def test_filename_logo_wins() -> None:
    core = _StubCore()
    # A JPEG photo named "...logo..." classifies as logo by rule 1.
    files = [UploadFileInput("company-logo.jpg", "image/jpeg", _photo_jpeg())]
    evidence, _ = analyze_uploads(
        files, core=core, store_root="/tmp/store", reporter=_noop
    )
    assert len(evidence.logos) == 1
    assert not evidence.images


def test_photo_classified_and_palette_excluded() -> None:
    core = _StubCore()
    files = [UploadFileInput("hero.jpg", "image/jpeg", _photo_jpeg())]
    evidence, _ = analyze_uploads(
        files, core=core, store_root="/tmp/store", reporter=_noop
    )
    assert not evidence.logos
    assert len(evidence.images) == 1
    assert evidence.images[0].kind_hint == "photo"
    # Photo palettes are scene noise → excluded from color evidence.
    assert evidence.colors == []


def test_logo_palette_becomes_color_evidence() -> None:
    core = _StubCore()
    files = [UploadFileInput("mark-teal.png", "image/png", _teal_logo_png())]
    evidence, _ = analyze_uploads(
        files, core=core, store_root="/tmp/store", reporter=_noop
    )
    assert evidence.colors, "logo dominant colors should seed color evidence"
    assert all(c.weight == 2.0 and c.role_hints == ["accent"] for c in evidence.colors)
    assert all(c.pointer.source == "upload" for c in evidence.colors)


# --------------------------------------------------------------------------- #
# SVG handling: color parse, dims, no Pillow pass
# --------------------------------------------------------------------------- #


def test_svg_color_parse_and_dims() -> None:
    core = _StubCore()
    files = [UploadFileInput("brand.svg", "image/svg+xml", _svg_bytes())]
    evidence, _ = analyze_uploads(
        files, core=core, store_root="/tmp/store", reporter=_noop
    )
    # SVG with squarish viewBox → logo.
    assert len(evidence.logos) == 1
    # Colors parsed from fill/stroke/style attrs (no rasterization).
    values = {c.value for c in evidence.colors}
    assert "#FF6600" in values
    assert "#0044CC" in values
    # Ingested as the original SVG bytes with the svg mime.
    assert core.calls[0]["declared_mime_type"] == "image/svg+xml"


def test_svg_transparency_none() -> None:
    core = _StubCore()
    files = [UploadFileInput("brand.svg", "image/svg+xml", _svg_bytes())]
    evidence, _ = analyze_uploads(
        files, core=core, store_root="/tmp/store", reporter=_noop
    )
    # No Pillow pass for SVGs: transparency stays unknown on any image entry.
    for image in evidence.images:
        assert image.transparency is None


# --------------------------------------------------------------------------- #
# Content-addressed ids + ingest calls
# --------------------------------------------------------------------------- #


def test_content_addressed_ids_and_tags() -> None:
    core = _StubCore()
    data = _teal_logo_png()
    files = [UploadFileInput("mark.png", "image/png", data)]
    evidence, _ = analyze_uploads(
        files, core=core, store_root="/tmp/store", reporter=_noop
    )
    assert len(core.calls) == 1
    call = core.calls[0]
    assert call["asset_id"].startswith("asset_ing_")
    assert evidence.logos[0].asset_id == call["asset_id"]
    assert call["tags"] == ["brand-ingestion", "upload", "logo"]
    # Deterministic content-address: same bytes → same id.
    core2 = _StubCore()
    analyze_uploads(
        [UploadFileInput("other.png", "image/png", data)],
        core=core2,
        store_root="/tmp/store",
        reporter=_noop,
    )
    assert core2.calls[0]["asset_id"] == call["asset_id"]


# --------------------------------------------------------------------------- #
# Source shape
# --------------------------------------------------------------------------- #


def test_source_logo_file_when_all_logos() -> None:
    core = _StubCore()
    files = [UploadFileInput("mark-teal.png", "image/png", _teal_logo_png())]
    evidence, _ = analyze_uploads(
        files, core=core, store_root="/tmp/store", reporter=_noop
    )
    assert evidence.source["kind"] == "logo_file"
    assert evidence.source["confidence"] == 0.8


def test_source_style_guide_image_when_mixed() -> None:
    core = _StubCore()
    files = [
        UploadFileInput("mark-teal.png", "image/png", _teal_logo_png()),
        UploadFileInput("hero.jpg", "image/jpeg", _photo_jpeg()),
    ]
    evidence, _ = analyze_uploads(
        files, core=core, store_root="/tmp/store", reporter=_noop
    )
    assert evidence.source["kind"] == "style_guide_image"
    assert evidence.source["confidence"] == 0.7
    assert evidence.narrative.brand_name is None


# --------------------------------------------------------------------------- #
# Caps + rejection
# --------------------------------------------------------------------------- #


def test_unsupported_files_skipped_with_diagnostic() -> None:
    core = _StubCore()
    files = [
        UploadFileInput("mark.png", "image/png", _teal_logo_png()),
        UploadFileInput("notes.txt", "text/plain", b"just some text, not an image"),
    ]
    evidence, diags = analyze_uploads(
        files, core=core, store_root="/tmp/store", reporter=_noop
    )
    assert len(evidence.logos) == 1
    codes = {d["code"] for d in diags}
    assert "LUMI0701" in codes


def test_all_unsupported_raises() -> None:
    core = _StubCore()
    files = [UploadFileInput("a.txt", "text/plain", b"nope not an image here")]
    with pytest.raises(ValueError):
        analyze_uploads(files, core=core, store_root="/tmp/store", reporter=_noop)


def test_file_cap_diagnostic() -> None:
    core = _StubCore()
    # 21 tiny distinct logos → cap at 20 with LUMI0702.
    files = []
    for i in range(21):
        from PIL import Image

        img = Image.new("RGBA", (32 + i, 32), (0, 0, 0, 0))
        img.putpixel((1, 1), (i * 10 % 255, 100, 100, 255))
        files.append(UploadFileInput(f"logo-{i}.png", "image/png", _png_bytes(img)))
    evidence, diags = analyze_uploads(
        files, core=core, store_root="/tmp/store", reporter=_noop
    )
    assert len(core.calls) == 20
    codes = {d["code"] for d in diags}
    assert "LUMI0702" in codes
