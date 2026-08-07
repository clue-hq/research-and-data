"""Print W1: the export-parity harness (R1 enforcement engine).

One fixture per feature family, authored in the real DSL through the real
helper, exported through the real export pipeline. The Skia PNG raster is
the truth; the PDF (vector Skia-PDF default, raster-flattened D5 baseline)
must match it within tolerance after rasterizing back through pymupdf.

What the tolerance means: pymupdf (MuPDF) and Skia rasterize glyphs and
gradients with different antialiasing, so a small neighborhood-tolerant
residual is expected and allowed. Feature DROPS (missing effects, fallback
fonts, absent gradients, lost spans) shift whole regions and blow far past
the thresholds — that is the regression this harness exists to catch, the
way gradients and effects silently vanished from the old vector stub.

The SVG axis (deferred at W1) is now covered by the headless-Chromium lane
at the bottom of this file: the exported SVG — with the painter's font
faces embedded as @font-face subsets — is rasterized in Chromium at the
PNG truth's pixel size and ink-diffed against it.
"""

from __future__ import annotations

import io
from typing import Callable, Optional

import fitz
import pytest

from lumen_api.core import CoreClient


TEXT_MARKER = "Parity harness"

# name, dsl, include_bleed, expected text in vector PDF, max mismatch ratio
FIXTURES = [
    (
        "typography",
        f"""
page page_parity
  headline text "{TEXT_MARKER} headline weight seven hundred" p(60,60) s(600,120) font("Inter",44,700,left) fill(#111827)
  body text "Body copy wraps across multiple lines to exercise the shared line breaker at a comfortable measure for the fixture page." p(60,200) s(480,220) font("Inter",22,400,left) fill(#374151)
  aligned text "right aligned run" p(60,440) s(600,60) font("Inter",24,500,right) fill(#0f172a)
""",
        False,
        TEXT_MARKER,
        0.02,
    ),
    (
        "spans_italic",
        """
page page_parity
  spanned text "Accent [[colored run]] and [[bold italic run]] inside one block" p(60,80) s(720,160) font("Inter",32,400,left) fill(#111827) span(fill(#dc2626)) span(weight(700), italic(true))
  italic_block text "Whole block italic rendering" p(60,300) s(720,80) font("Inter",28,500,left) italic(true) fill(#1f2937)
""",
        False,
        "Accent",
        0.02,
    ),
    (
        "effects",
        """
page page_parity
  plate rect p(140,140) s(400,240) fill(#ffffff) rd(24) shadow(0,12,48,#0f172a)
  glowbox rect p(620,140) s(240,240) fill(#f59e0b) glow(#f59e0b, o(0.6), blur(40))
  soft rect p(140,480) s(300,200) fill(#3b82f6) blur(6)
""",
        False,
        None,
        0.03,
    ),
    (
        "gradient_opacity",
        # Page background authored the way the agent does it: a #page:
        # modify line (the page HEADER accepts only preset/size — anything
        # else is a loud LUMD0204).
        """
page page_parity
  band rect p(0,340) s(1080,220) fill(linear(90, stop(#f59e0b,0), stop(#dc2626,1)))
  ghost rect p(120,120) s(360,160) fill(#ffffff) o(0.5)
#page:page_parity bg(linear(135, stop(#0f172a,0), stop(#334155,1)))
""",
        False,
        None,
        0.02,
    ),
    (
        "valign",
        """
page page_parity
  vtop text "top anchored" p(60,60) s(300,200) font("Inter",24,500,left) valign(top) fill(#111827)
  vcenter text "center anchored" p(390,60) s(300,200) font("Inter",24,500,center) valign(center) fill(#111827)
  vbottom text "bottom anchored" p(720,60) s(300,200) font("Inter",24,500,right) valign(bottom) fill(#111827)
""",
        False,
        "anchored",
        0.02,
    ),
]

MULTIPAGE_DSL = """
page page_one
  first text "Page one marker" p(60,60) s(400,80) font("Inter",30,700,left) fill(#111827)
page page_two
  second text "Page two marker" p(60,60) s(400,80) font("Inter",30,700,left) fill(#7c2d12)
"""

# L2 fixture: 12pt symmetric bleed, background and an edge-touching band
# that extend past trim to the bleed line — authored end-to-end in the
# real DSL (page geometry via the #page: modify line, the agent's route).
EDGE_BLEED_DSL = """
page page_parity size(1080,1080,px)
  band rect p(-12,880) s(1104,140) fill(#f59e0b) bleed(true)
  label text "Edge to bleed" p(80,120) s(500,80) font("Inter",36,700,left) fill(#ffffff)
#page:page_parity bg(#12355b) bleed(-12,-12,1104,1104) safe_area(60,60,960,960)
"""


@pytest.fixture(scope="module")
def core() -> CoreClient:
    return CoreClient()


def build_scene(core: CoreClient, dsl: str) -> dict:
    fresh = core.new_scene("doc_export_parity", "Export parity fixture")
    compiled = core.compile_dsl_into_scene(fresh, dsl)
    # DSL compile diagnostics live under dsl.compile_output, NOT the
    # top-level diagnostics key (a halted compile is otherwise easy to
    # misread as a silent drop).
    compile_output = (compiled.get("dsl") or {}).get("compile_output") or {}
    errors = [
        entry
        for entry in compile_output.get("diagnostics") or []
        if entry.get("diagnostic", {}).get("severity") == "error"
    ]
    assert not errors, f"fixture DSL must compile clean: {errors}"
    scene = compiled["scene"]
    assert scene["pages"], "fixture compiled to zero pages"
    return scene


def export_bytes(
    core: CoreClient,
    scene: dict,
    export_format: str,
    include_bleed: bool,
    dpi: Optional[int] = None,
) -> tuple[bytes, list[dict]]:
    response = core.export_preview(
        scene,
        export_format=export_format,
        profile={
            "name": f"parity_{export_format}",
            "format": export_format,
            "pdf_intent": "print" if export_format == "pdf" else None,
            "raster": {"scale": 1.0, "dpi": dpi} if dpi else None,
            "include_bleed": include_bleed,
            "embed_fonts": True,
        },
    )
    artifacts = response["export"]["artifacts"]
    assert artifacts, f"no artifacts: {response.get('diagnostics') or []}"
    payload = bytes(int(value) & 0xFF for value in artifacts[0]["bytes"])
    # The helper omits empty diagnostic lists from the serialized response.
    diagnostics = list(response.get("diagnostics") or [])
    diagnostics.extend(response["export"].get("diagnostics") or [])
    return payload, diagnostics


def rgb_pixmap(pixmap: fitz.Pixmap) -> fitz.Pixmap:
    if pixmap.alpha or pixmap.colorspace.n != 3:
        return fitz.Pixmap(fitz.csRGB, pixmap)
    return pixmap


def sampled_mismatch(
    png_pixmap: fitz.Pixmap,
    other_pixmap: fitz.Pixmap,
    map_point: Callable[[float, float], tuple[float, float]],
    steps: int,
    channel_tolerance: int,
    window: int,
    ink_threshold: Optional[int] = None,
) -> tuple[float, int]:
    """Neighborhood-tolerant sampled diff — the ONE diff core both lanes
    share: a PNG sample passes if ANY pixel of the other raster within a
    small window matches, absorbing antialiasing differences between
    rasterizers while whole-region drift still fails loudly. With
    `ink_threshold` set, only samples where either raster has ink are
    counted (text pixels are the signal on a mostly-white page). Returns
    (mismatch ratio over counted samples, counted sample count)."""
    total = 0
    mismatched = 0
    for iy in range(1, steps):
        for ix in range(1, steps):
            u, v = ix / steps, iy / steps
            png_px = png_pixmap.pixel(
                int(u * (png_pixmap.width - 1)), int(v * (png_pixmap.height - 1))
            )
            tx, ty = map_point(u, v)
            px = int(tx * (other_pixmap.width - 1))
            py = int(ty * (other_pixmap.height - 1))
            if ink_threshold is not None:
                other_px = other_pixmap.pixel(px, py)
                if (
                    min(png_px[:3]) >= ink_threshold
                    and min(other_px[:3]) >= ink_threshold
                ):
                    continue
            best = 255
            for dy in range(-window, window + 1):
                for dx in range(-window, window + 1):
                    qx = min(max(px + dx, 0), other_pixmap.width - 1)
                    qy = min(max(py + dy, 0), other_pixmap.height - 1)
                    other = other_pixmap.pixel(qx, qy)
                    delta = max(
                        abs(a - b) for a, b in zip(png_px[:3], other[:3])
                    )
                    best = min(best, delta)
                    if best <= channel_tolerance:
                        break
                if best <= channel_tolerance:
                    break
            total += 1
            if best > channel_tolerance:
                mismatched += 1
    return (mismatched / total if total else 0.0, total)


def mismatch_ratio(
    png_pixmap: fitz.Pixmap,
    pdf_pixmap: fitz.Pixmap,
    map_point: Callable[[float, float], tuple[float, float]],
    steps: int = 120,
    channel_tolerance: int = 16,
    window: int = 3,
) -> float:
    ratio, _ = sampled_mismatch(
        png_pixmap, pdf_pixmap, map_point, steps, channel_tolerance, window
    )
    return ratio


def assert_pdf_matches_png(
    pdf_bytes: bytes,
    png_bytes: bytes,
    max_ratio: float,
    fixture: str,
    renderer: str,
    page_index: int = 0,
) -> None:
    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = document[page_index]
    png_pixmap = rgb_pixmap(fitz.Pixmap(png_bytes))
    zoom = png_pixmap.width / page.rect.width
    pdf_pixmap = rgb_pixmap(
        page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    )
    ratio = mismatch_ratio(png_pixmap, pdf_pixmap, lambda u, v: (u, v))
    assert ratio <= max_ratio, (
        f"[{fixture}/{renderer}] PDF diverges from PNG: {ratio:.2%} of samples "
        f"mismatch (allowed {max_ratio:.2%}) — a feature likely dropped"
    )


@pytest.mark.parametrize("renderer", ["vector", "flattened"])
@pytest.mark.parametrize(
    "fixture", [f[0] for f in FIXTURES], ids=[f[0] for f in FIXTURES]
)
def test_pdf_matches_png_truth(
    core: CoreClient,
    monkeypatch: pytest.MonkeyPatch,
    renderer: str,
    fixture: str,
) -> None:
    name, dsl, include_bleed, expected_text, max_ratio = next(
        f for f in FIXTURES if f[0] == fixture
    )
    monkeypatch.setenv("LUMEN_PDF_RENDERER", renderer)
    scene = build_scene(core, dsl)

    png_bytes, _ = export_bytes(core, scene, "png", include_bleed=False)
    pdf_bytes, pdf_diagnostics = export_bytes(
        core, scene, "pdf", include_bleed=include_bleed, dpi=300
    )

    codes = {diagnostic["code"] for diagnostic in pdf_diagnostics}
    expected_mode = "LUME0427" if renderer == "vector" else "LUME0426"
    assert expected_mode in codes, f"[{name}/{renderer}] mode advisory missing: {codes}"

    assert_pdf_matches_png(pdf_bytes, png_bytes, max_ratio, name, renderer)

    if renderer == "vector" and expected_text:
        document = fitz.open(stream=pdf_bytes, filetype="pdf")
        extracted = document[0].get_text()
        assert expected_text in extracted, (
            f"[{name}] vector PDF must carry live extractable text; got: "
            f"{extracted[:200]!r}"
        )


@pytest.mark.parametrize("renderer", ["vector", "flattened"])
def test_multipage_parity(
    core: CoreClient, monkeypatch: pytest.MonkeyPatch, renderer: str
) -> None:
    monkeypatch.setenv("LUMEN_PDF_RENDERER", renderer)
    scene = build_scene(core, MULTIPAGE_DSL)

    pdf_bytes, _ = export_bytes(core, scene, "pdf", include_bleed=False, dpi=300)
    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    assert document.page_count == 2

    for index, page_id in enumerate(["page_one", "page_two"]):
        response = core.export_preview(
            scene,
            export_format="png",
            page_ids=[page_id],
            profile={
                "name": "parity_png",
                "format": "png",
                "pdf_intent": None,
                "raster": {"scale": 1.0, "dpi": None},
                "include_bleed": False,
                "embed_fonts": True,
            },
        )
        png_bytes = bytes(
            int(value) & 0xFF
            for value in response["export"]["artifacts"][0]["bytes"]
        )
        assert_pdf_matches_png(
            pdf_bytes, png_bytes, 0.02, "multipage", renderer, page_index=index
        )


@pytest.mark.parametrize("renderer", ["vector", "flattened"])
def test_edge_bleed_chain_l2_l3(
    core: CoreClient, monkeypatch: pytest.MonkeyPatch, renderer: str
) -> None:
    """The no-color-cutoff chain, mechanically: content authored to the
    bleed line must survive into the PDF past the trim (L2), and the box
    set must declare trim inside bleed exactly (L3)."""
    monkeypatch.setenv("LUMEN_PDF_RENDERER", renderer)
    scene = build_scene(core, EDGE_BLEED_DSL)

    pdf_bytes, _ = export_bytes(core, scene, "pdf", include_bleed=True, dpi=300)
    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = document[0]

    # L3: boxes. Page is 1080px = 1080pt trim with 12pt bleed per side.
    assert page.mediabox.width == pytest.approx(1104, abs=0.01)
    trim = page.trimbox
    assert trim.width == pytest.approx(1080, abs=0.01)
    assert page.bleedbox.width == pytest.approx(1104, abs=0.01)

    # L2: the bleed margin carries ink, not blank paper. Sample the strip
    # between trim and bleed on all four edges at the vertical midline /
    # horizontal band of the edge-touching art.
    pixmap = rgb_pixmap(page.get_pixmap(dpi=72, alpha=False))

    def sample(x_pt: float, y_pt: float) -> tuple[int, ...]:
        scale_x = pixmap.width / page.rect.width
        scale_y = pixmap.height / page.rect.height
        return pixmap.pixel(int(x_pt * scale_x), int(y_pt * scale_y))

    white = (255, 255, 255)
    # Left bleed strip, mid-height (page background must extend).
    assert sample(6, 550)[:3] != white, f"[{renderer}] left bleed strip is blank"
    # Right bleed strip.
    assert sample(1098, 550)[:3] != white, f"[{renderer}] right bleed strip is blank"
    # Bottom bleed strip where the edge-touching band extends. PDF y-up:
    # bottom of the layout = top of pymupdf's rendered image? pymupdf
    # renders in display order (y down from top-left), so the layout-bottom
    # band sits near the image bottom.
    assert sample(550, 1098)[:3] != white, f"[{renderer}] bottom bleed strip is blank"


def test_marks_mode_pdf_strokes_trim_and_bleed_ticks(core: CoreClient) -> None:
    """The marks coverage gap: tick GEOMETRY is unit-pinned in Rust, but
    until now nothing rendered a marks-mode export and asserted INK — a
    regression that computes perfect coordinates yet never strokes them
    (paint order, clip, alpha) passed every suite. Fixture geometry:
    1080pt trim, 12pt bleed, 14pt mark margin → MediaBox 1132, trim line
    26pt in, bleed line 14pt in. Every corner carries BOTH tick sets
    (trim + bleed = 16 segments), floating in the ink-free margin."""
    scene = build_scene(core, EDGE_BLEED_DSL)
    response = core.export_preview(
        scene,
        export_format="pdf",
        profile={
            "name": "parity_pdf_marks",
            "format": "pdf",
            "pdf_intent": "print",
            "raster": None,
            "include_bleed": True,
            "include_marks": True,
            "embed_fonts": True,
        },
    )
    artifacts = response["export"]["artifacts"]
    assert artifacts, f"no artifacts: {response.get('diagnostics') or []}"
    pdf_bytes = bytes(int(value) & 0xFF for value in artifacts[0]["bytes"])

    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = document[0]
    assert page.mediabox.width == pytest.approx(1132, abs=0.01)
    assert page.trimbox.width == pytest.approx(1080, abs=0.01)

    # 4 px/pt so the 0.5pt hairline ticks land solidly.
    pixmap = rgb_pixmap(page.get_pixmap(dpi=288, alpha=False))
    scale = pixmap.width / page.rect.width

    def darkest(x0: float, y0: float, x1: float, y1: float) -> int:
        values = []
        for py in range(int(y0 * scale), int(y1 * scale) + 1):
            for px in range(int(x0 * scale), int(x1 * scale) + 1):
                r, g, b = pixmap.pixel(px, py)[:3]
                values.append((r + g + b) // 3)
        return min(values)

    size = 1132.0
    trim_line, bleed_line = 26.0, 14.0
    # Ticks run outward through the margin band 2..11pt from the MediaBox
    # edge (3pt gap after the bleed line, ~11pt long).
    near = (2.0, 10.0)
    far = (size - 10.0, size - 2.0)
    for line, label in ((trim_line, "trim"), (bleed_line, "bleed")):
        for position in (line, size - line):
            for band in (near, far):
                assert (
                    darkest(position - 1.5, band[0], position + 1.5, band[1]) < 160
                ), f"missing vertical {label} tick at x={position}, y≈{band}"
                assert (
                    darkest(band[0], position - 1.5, band[1], position + 1.5) < 160
                ), f"missing horizontal {label} tick at y={position}, x≈{band}"

    # The margin between corners stays ink-free — ticks, not a frame.
    assert darkest(500.0, 2.0, 632.0, 10.0) > 235, "stray ink in the mark margin"


BOOKLET_DSL = """
page page_1 size(400,300,pt)
  label1 text "One" p(40,40) s(150,50) font("Inter",28,700,left) fill(#ffffff)
page page_2 size(400,300,pt)
  label2 text "Two" p(40,40) s(150,50) font("Inter",28,700,left) fill(#ffffff)
page page_3 size(400,300,pt)
  label3 text "Three" p(40,40) s(150,50) font("Inter",28,700,left) fill(#ffffff)
page page_4 size(400,300,pt)
  label4 text "Four" p(40,40) s(150,50) font("Inter",28,700,left) fill(#111827)
#page:page_1 bg(#dc2626)
#page:page_2 bg(#16a34a)
#page:page_3 bg(#2563eb)
#page:page_4 bg(#f59e0b)
"""


@pytest.mark.parametrize("renderer", ["vector", "flattened"])
def test_booklet_sheet_halves_match_reader_pages(
    core: CoreClient, monkeypatch: pytest.MonkeyPatch, renderer: str
) -> None:
    """Print W4: the imposed booklet is a pure rearrangement — every sheet
    half must pixel-match its reader page. 4 pages → 1 duplex sheet:
    front [4|1], back [2|3]."""
    monkeypatch.setenv("LUMEN_PDF_RENDERER", renderer)
    scene = build_scene(core, BOOKLET_DSL)

    response = core.export_preview(
        scene,
        export_format="pdf",
        profile={
            "name": "booklet_pdf",
            "format": "pdf",
            "pdf_intent": "print",
            "raster": {"scale": 1.0, "dpi": 150},
            "include_bleed": False,
            "embed_fonts": True,
            "imposition": "booklet",
        },
    )
    artifacts = response["export"]["artifacts"]
    pdf_bytes = bytes(int(value) & 0xFF for value in artifacts[0]["bytes"])
    codes = {
        diagnostic["code"]
        for diagnostic in (response.get("diagnostics") or [])
        + (response["export"].get("diagnostics") or [])
    }
    assert "LUME0428" in codes, f"imposition advice missing: {sorted(codes)}"

    document = fitz.open(stream=pdf_bytes, filetype="pdf")
    assert document.page_count == 2
    for page in document:
        assert page.rect.width == pytest.approx(800.0, abs=0.01)
        assert page.rect.height == pytest.approx(300.0, abs=0.01)

    # side index -> (left reader page, right reader page), 1-based.
    arrangement = {0: (4, 1), 1: (2, 3)}
    for side_index, (left_page, right_page) in arrangement.items():
        sheet = document[side_index]
        zoom = 2.0
        sheet_pixmap = rgb_pixmap(
            sheet.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        )
        for slot, reader_number in [(0, left_page), (1, right_page)]:
            reader = core.export_preview(
                scene,
                export_format="png",
                page_ids=[f"page_{reader_number}"],
                profile={
                    "name": "parity_png",
                    "format": "png",
                    "pdf_intent": None,
                    "raster": {"scale": 1.0, "dpi": None},
                    "include_bleed": False,
                    "embed_fonts": True,
                },
            )
            png_bytes = bytes(
                int(value) & 0xFF
                for value in reader["export"]["artifacts"][0]["bytes"]
            )
            png_pixmap = rgb_pixmap(fitz.Pixmap(png_bytes))
            ratio = mismatch_ratio(
                png_pixmap,
                sheet_pixmap,
                lambda u, v, slot=slot: ((slot + u) / 2.0, v),
                steps=80,
            )
            assert ratio <= 0.02, (
                f"[{renderer}] side {side_index} slot {slot} should carry reader "
                f"page {reader_number}: {ratio:.2%} mismatch"
            )


def test_verapdf_structural_validation_of_print_pdf(
    core: CoreClient, tmp_path
) -> None:
    """PDF/X-4 structural regression via veraPDF (skips when not installed).

    veraPDF validates PDF/A, not PDF/X, so this is NOT a conformance pass —
    full ISO 15930-7 validation needs a commercial tool (callas pdfToolbox;
    ruled out for now by D4). What this pins: the file parses completely
    (jobEndStatus normal) and the only PDF/A-4 rule failures are the five
    known NOT-APPLICABLE-to-X classes (PDF-2.0 header, A-4's no-Info rules,
    the PDF/A ID schema, DeviceRGB-vs-PDF/A-intent). Any NEW failure class
    is a structural regression. The one A-failure that WAS also an X
    failure (missing trailer /ID, 6.1.3#1) is fixed and must stay fixed.
    """
    import shutil
    import subprocess

    verapdf = shutil.which("verapdf")
    if not verapdf:
        pytest.skip("veraPDF not installed")

    scene = build_scene(core, EDGE_BLEED_DSL)
    response = core.export_preview(
        scene,
        export_format="pdf",
        profile={
            "name": "print_pdf",
            "format": "pdf",
            "pdf_intent": "print",
            "raster": {"scale": 1.0, "dpi": 300},
            "include_bleed": True,
            "embed_fonts": True,
        },
    )
    pdf_bytes = bytes(
        int(value) & 0xFF
        for value in response["export"]["artifacts"][0]["bytes"]
    )
    pdf_path = tmp_path / "print.pdf"
    pdf_path.write_bytes(pdf_bytes)

    result = subprocess.run(
        [verapdf, "-f", "4", str(pdf_path)], capture_output=True, text=True
    )
    report = result.stdout
    assert 'jobEndStatus="normal"' in report, "veraPDF could not parse the PDF"

    import re

    failed = {
        (match.group(1), match.group(2))
        for match in re.finditer(
            r'clause="([^"]+)" testNumber="(\d+)" status="failed"', report
        )
    }
    not_applicable_to_x = {
        ("6.1.2", "1"),      # A-4 wants a PDF-2.0 header; X-4 wants <= 1.6
        ("6.1.3", "4"),      # A-4 forbids the Info dict; X-4 requires it
        ("6.1.3", "5"),      # ditto (Info contents)
        ("6.7.3", "1"),      # PDF/A Identification schema; we claim pdfxid
        ("6.2.4.3", "2"),    # DeviceRGB vs PDF/A OutputIntent; ours is GTS_PDFX
    }
    unexpected = failed - not_applicable_to_x
    assert not unexpected, (
        f"new structural failure classes (regression): {sorted(unexpected)}"
    )
    # Trailer /ID (6.1.3#1) is required by PDF/X and must stay fixed.
    assert ("6.1.3", "1") not in failed, "trailer /ID regressed — required by PDF/X"



# ---------------------------------------------------------------------------
# SVG axis (deferred at W1, closed by the font-embedding work): the exported
# SVG — with the painter's font faces embedded as @font-face subsets — is
# rasterized in headless Chromium at the PNG truth's pixel size and diffed
# over INK samples only (text pixels are the signal; the mostly-white page
# would otherwise dilute a wrong-font regression below any threshold).
# Chromium and Skia both shape with HarfBuzz over the same embedded bytes,
# so genuine drift is sub-pixel; a missing/substituted font multiplies the
# ink mismatch (probed live: 3.7%/7.7% embedded vs ~25% with @font-face
# stripped — the threshold sits in the middle of that gap).

SVG_FIXTURES = ["typography", "spans_italic"]
SVG_MAX_INK_RATIO = 0.15
SVG_MIN_INK_SAMPLES = 200


def rasterize_svg_chromium(svg_bytes: bytes, width: int, height: int) -> bytes:
    """Screenshot the SVG in headless Chromium at exactly width x height CSS
    pixels. The root element's width/height are set through the DOM after
    load (a pt-sized page otherwise renders at 96/72 px per pt) — purely a
    raster-resolution choice, like passing dpi to a rasterizer; the viewBox
    and all geometry stay untouched, and nothing depends on the exporter's
    byte-level attribute layout. Skips (never fails) when Playwright or its
    Chromium build is absent."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("playwright not installed")

    import base64

    url = "data:image/svg+xml;base64," + base64.b64encode(svg_bytes).decode("ascii")
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Exception as error:  # missing browser build — environment, not product
            pytest.skip(f"chromium unavailable: {error}")
        try:
            page = browser.new_page(
                viewport={"width": width, "height": height},
                device_scale_factor=1,
            )
            page.goto(url)
            page.evaluate(
                "([w, h]) => {"
                " const svg = document.documentElement;"
                " svg.setAttribute('width', w + 'px');"
                " svg.setAttribute('height', h + 'px'); }",
                [width, height],
            )
            # @font-face data URIs decode asynchronously; text paints with
            # them only after the font faces resolve.
            page.evaluate("() => document.fonts ? document.fonts.ready : 0")
            return page.screenshot(
                clip={"x": 0, "y": 0, "width": width, "height": height}
            )
        finally:
            browser.close()


def ink_mismatch_ratio(
    png_pixmap: fitz.Pixmap,
    svg_pixmap: fitz.Pixmap,
) -> tuple[float, int]:
    """The SVG lane's diff: the shared sampled core, ink-restricted.
    Constants deliberately differ from the PDF lane — calibrated live
    against embedded (~4-8%) vs @font-face-stripped (~25%) renders."""
    return sampled_mismatch(
        png_pixmap,
        svg_pixmap,
        lambda u, v: (u, v),
        steps=240,
        channel_tolerance=32,
        window=2,
        ink_threshold=240,
    )


@pytest.mark.parametrize("fixture", SVG_FIXTURES)
def test_svg_matches_png_truth(core: CoreClient, fixture: str) -> None:
    name, dsl, _include_bleed, _expected_text, _max_ratio = next(
        f for f in FIXTURES if f[0] == fixture
    )
    scene = build_scene(core, dsl)

    png_bytes, _ = export_bytes(core, scene, "png", include_bleed=False)
    svg_bytes, svg_diagnostics = export_bytes(core, scene, "svg", include_bleed=False)

    # The embedding contract: fonts are IN the file and the viewer-font
    # dependency warning is gone.
    svg_text = svg_bytes.decode("utf-8")
    assert "@font-face" in svg_text, f"[{name}] SVG must embed fonts"
    codes = {diagnostic["code"] for diagnostic in svg_diagnostics}
    assert "LUME0216" not in codes, f"[{name}] embedded SVG still warns: {codes}"

    png_pixmap = rgb_pixmap(fitz.Pixmap(png_bytes))
    shot = rasterize_svg_chromium(svg_bytes, png_pixmap.width, png_pixmap.height)
    svg_pixmap = rgb_pixmap(fitz.Pixmap(shot))

    ratio, ink_samples = ink_mismatch_ratio(png_pixmap, svg_pixmap)
    assert ink_samples >= SVG_MIN_INK_SAMPLES, (
        f"[{name}/svg] too little ink to compare ({ink_samples} samples) — "
        "a blank render would pass vacuously"
    )
    assert ratio <= SVG_MAX_INK_RATIO, (
        f"[{name}/svg] browser-rendered SVG diverges from PNG truth over ink: "
        f"{ratio:.2%} of {ink_samples} ink samples mismatch "
        f"(allowed {SVG_MAX_INK_RATIO:.2%})"
    )


def test_svg_without_embedding_warns_viewer_font_dependency(core: CoreClient) -> None:
    """embed_fonts=false is the declared name-only state: the export must
    carry the LUME0216 viewer-font dependency warning naming the families."""
    name, dsl, _include_bleed, _expected_text, _max_ratio = next(
        f for f in FIXTURES if f[0] == "typography"
    )
    scene = build_scene(core, dsl)
    response = core.export_preview(
        scene,
        export_format="svg",
        profile={
            "name": "parity_svg_no_embed",
            "format": "svg",
            "pdf_intent": None,
            "raster": None,
            "include_bleed": False,
            "embed_fonts": False,
        },
    )
    svg = bytes(
        int(value) & 0xFF for value in response["export"]["artifacts"][0]["bytes"]
    ).decode("utf-8")
    assert "@font-face" not in svg
    diagnostics = list(response.get("diagnostics") or [])
    diagnostics.extend(response["export"].get("diagnostics") or [])
    warning = next(
        (d for d in diagnostics if d["code"] == "LUME0216"), None
    )
    assert warning is not None, f"LUME0216 missing: {sorted(d['code'] for d in diagnostics)}"
    assert "Inter" in warning["message"]
