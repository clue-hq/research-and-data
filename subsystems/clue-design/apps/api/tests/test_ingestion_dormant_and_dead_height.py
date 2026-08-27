"""Hidden sections and dead scroll height, at mint time (clone-fidelity F3.0).

Two founder rulings, both of which change what one captured page turns INTO:

* **D-F8.** A section the source site hides used to be dropped with a loud diagnostic, which was
  honest and useless: the marketer who wants their pricing band back had nothing to point at. It
  is now PRESERVED — segmented into its own collection, minted ``dormant``, carrying the evidence
  that says it was hidden. What stays dropped is the section that is genuinely unreachable: no
  subtree in the snapshot means nothing to mint, and inventing one would be fabrication.
* **D-F6.** A section whose captured band is vastly taller than anything visible inside it is a
  scroll-jacked shell — the Ploy case, and the thing that makes a cloned page feel broken. It is
  minted (it is evidence) and born ``degraded`` with a machine-readable reason, which is the
  repair ladder's trigger.

Pure: html, band geometry and a synthetic screenshot in; records, diagnostics and mint calls out.
The durable half lives in ``test_ingestion_fragment_pipeline.py`` and
``test_web_fragment_lifecycle.py``.
"""

from __future__ import annotations

import hashlib
from io import BytesIO

from lumen_ingestion.sections.bands import (
    SNAPSHOT_META_BANDS_KEY,
    SNAPSHOT_META_SKIPPED_KEY,
    measured_bands,
    skipped_children,
)
from lumen_ingestion.sections.deadheight import (
    DEAD_HEIGHT_MAX_CONTENT_FRACTION,
    DEAD_HEIGHT_MIN_SECTION_PX,
    DEAD_HEIGHT_REASON,
    detect_dead_height,
)
from lumen_ingestion.sections.mint import (
    MINT_DEGRADED_CODE,
    MINT_DORMANT_CODE,
    SECTION_MINT_CAP,
    mint_sections,
)
from lumen_ingestion.sections.segment import HIDDEN_SECTION_CODE, SKIPPED_CONTENT_CODE, segment_page

PAGE_URL = "https://insight.example/"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _shot(height: int, *, content: tuple[int, int] | None, width: int = 1200) -> bytes:
    """A full-page screenshot whose rows in ``content`` carry horizontal variation.

    That is exactly what the detector reads: a row a visitor sees SOMETHING on (text, an image,
    a control) varies across its width, and a row of flat colour or of a vertical gradient does
    not. Everything outside ``content`` here is one flat colour, which is what dead scroll height
    looks like in a screenshot.
    """
    from PIL import Image

    image = Image.new("RGB", (width, height), (245, 245, 247))
    if content is not None:
        top, bottom = content
        pixels = image.load()
        for y in range(max(0, top), min(height, bottom)):
            for x in range(0, width, 2):
                pixels[x, y] = (20, 20, 20)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class _Recorder:
    """The F1 creation seam and the design byte store, injected."""

    def __init__(self) -> None:
        self.created: list[dict] = []

    def register_bytes(self, data: bytes, media_type: str) -> str:
        return hashlib.sha256(data).hexdigest()

    def create_fragment(self, **kwargs):
        from lumen_api.fragments import build_fragment_artifact

        preview = kwargs.get("preview")
        preview_digest = (
            None if preview is None else hashlib.sha256(preview).hexdigest()
        )
        artifact = build_fragment_artifact(
            html=kwargs["html"],
            css=kwargs["css"],
            rehosted=kwargs["rehosted"],
            slots=kwargs["slots"],
            preview_digest=preview_digest,
            prelude_reference=kwargs["prelude_reference"],
        )
        row = {
            "fragment_id": artifact.fragment_id,
            "status": kwargs.get("status") or "draft",
            "label": kwargs.get("label"),
            "provenance": dict(kwargs.get("provenance") or {}),
            "preview_digest": preview_digest,
            "payload_digest": artifact.payload_digest,
            "degraded": bool(kwargs.get("degraded")),
            "degraded_reason": kwargs.get("degraded_reason"),
            "derived_from": kwargs.get("derived_from"),
            "derived_reason": kwargs.get("derived_reason"),
        }
        self.created.append({**kwargs, "row": row})
        return row, artifact


def _mint(html: str, *, bands=(), skips=(), screenshot=None, viewport_width=1200):
    recorder = _Recorder()
    segmentation = segment_page(
        html,
        page_url=PAGE_URL,
        bands=bands,
        skips=skips,
        viewport_width=viewport_width,
    )
    outcome = mint_sections(
        segmentation,
        html=html,
        stylesheets=[],
        captured={},
        screenshot=screenshot,
        source_kit_id="brand_kit_x",
        source_kit_version=1,
        register_bytes=recorder.register_bytes,
        create_fragment=recorder.create_fragment,
        limit=SECTION_MINT_CAP,
    )
    return segmentation, outcome, recorder


# --------------------------------------------------------------------------- #
# D-F8: hidden on the source site, preserved rather than dropped
# --------------------------------------------------------------------------- #


HIDDEN_PAGE = (
    "<html><body><main>"
    '<section class="section_hero"><h1>Ship faster</h1></section>'
    '<section class="section_pricing hide"><h2>Pricing</h2><p>From $99.</p></section>'
    '<section class="section_proof"><p>Trusted by teams</p></section>'
    "</main></body></html>"
)

HIDDEN_PAGE_BANDS = [
    {"index": 0, "tag": "section", "classes": "section_hero", "top": 0.0, "height": 600.0},
    {"index": 1, "tag": "section", "classes": "section_proof", "top": 600.0, "height": 300.0},
]


def test_a_section_the_site_hides_is_kept_out_of_the_page_but_not_thrown_away() -> None:
    result = segment_page(
        HIDDEN_PAGE,
        page_url=PAGE_URL,
        bands=measured_bands({SNAPSHOT_META_BANDS_KEY: HIDDEN_PAGE_BANDS}),
    )
    # The visible page is exactly what F2 said it was — a hidden section is still not a section
    # OF THE PAGE, and every role, index and diagnostic about the page is unchanged.
    assert [section.role for section in result.sections] == ["hero", "proof"]
    # ...and it is no longer gone.
    assert [section.heading for section in result.hidden_sections] == ["Pricing"]
    hidden = result.hidden_sections[0]
    assert hidden.hidden_on_source is True
    assert hidden.hidden_evidence  # says WHY we believe the site hides it
    assert hidden.geometry is None  # the browser never measured it, and we do not pretend


def test_a_hidden_section_keeps_the_position_it_held_on_the_page() -> None:
    result = segment_page(
        HIDDEN_PAGE,
        page_url=PAGE_URL,
        bands=measured_bands({SNAPSHOT_META_BANDS_KEY: HIDDEN_PAGE_BANDS}),
    )
    assert [section.index for section in result.sections] == [0, 2]
    assert [section.index for section in result.hidden_sections] == [1]


def test_the_probe_saying_it_skipped_a_child_is_evidence_too() -> None:
    """The browser is the only thing that can answer "is this hidden?" — when it does, no band
    binding is needed to believe it."""
    html = (
        "<html><body><main>"
        '<section class="banner hide"><h2>Announcing</h2></section>'
        '<section class="tail"><p>Tail.</p></section>'
        "</main></body></html>"
    )
    result = segment_page(
        html,
        page_url=PAGE_URL,
        skips=skipped_children(
            {
                SNAPSHOT_META_SKIPPED_KEY: [
                    {"tag": "section", "id": None, "classes": "banner hide", "reason": "hidden"}
                ]
            }
        ),
    )
    assert len(result.sections) == 1
    assert [section.heading for section in result.hidden_sections] == ["Announcing"]
    assert any("probe" in note for note in result.hidden_sections[0].hidden_evidence)


def test_preserving_a_hidden_section_is_reported_and_is_not_the_loose_content_drop() -> None:
    result = segment_page(
        HIDDEN_PAGE,
        page_url=PAGE_URL,
        bands=measured_bands({SNAPSHOT_META_BANDS_KEY: HIDDEN_PAGE_BANDS}),
    )
    preserved = [d for d in result.diagnostics if d["code"] == HIDDEN_SECTION_CODE]
    assert len(preserved) == 1
    assert preserved[0]["count"] == 1
    assert not [d for d in result.diagnostics if d["code"] == SKIPPED_CONTENT_CODE]


def test_content_that_is_not_a_section_at_all_still_drops_loudly() -> None:
    """The honest-absence half of the ruling. A bare heading in the body is real content and
    still nothing a clone can reuse — there is no subtree to mint, so it is named and dropped."""
    html = (
        "<html><body>"
        '<header class="site-header"><a href="/">Home</a><a href="/a">A</a><a href="/b">B</a></header>'
        "<h1>Clinical intelligence</h1><p>Insight turns data into decisions.</p>"
        "</body></html>"
    )
    result = segment_page(html, page_url=PAGE_URL)
    assert result.hidden_sections == ()
    dropped = next(d for d in result.diagnostics if d["code"] == SKIPPED_CONTENT_CODE)
    assert {entry["tag"] for entry in dropped["skipped"]} == {"h1", "p"}


def test_a_hidden_section_mints_dormant_carrying_the_evidence_that_it_was_hidden() -> None:
    _segmentation, outcome, recorder = _mint(
        HIDDEN_PAGE, bands=measured_bands({SNAPSHOT_META_BANDS_KEY: HIDDEN_PAGE_BANDS})
    )
    statuses = {minted.role: minted.status for minted in outcome.minted}
    assert statuses["hero"] == "draft"
    assert statuses["proof"] == "draft"

    dormant = [call for call in recorder.created if call.get("status") == "dormant"]
    assert len(dormant) == 1
    provenance = dormant[0]["provenance"]
    assert provenance["hidden_on_source"]["hidden"] is True
    assert provenance["hidden_on_source"]["evidence"]
    assert provenance["section_index"] == 1
    assert any(d["code"] == MINT_DORMANT_CODE for d in outcome.diagnostics)


def test_a_hidden_section_is_never_given_a_preview_cropped_from_somebody_else() -> None:
    """The nav/footer extent fallbacks infer a crop from the neighbouring bands. A hidden section
    was never rendered, so those pixels are another section's — and here that lie would be the
    evidence a human activates the clone on (D-F8 makes a usable preview the condition). Honestly
    previewless beats confidently wrong."""
    from lumen_ingestion.sections.mint import crop_extent

    html = (
        "<html><body>"
        '<header class="nav_component hide"><a href="/">Home</a><a href="/x">X</a></header>'
        '<main><section class="section_home-hero"><h1>Ship</h1></section></main>'
        '<footer class="footer_component hide"><p>&copy; 2026</p></footer>'
        "</body></html>"
    )
    result = segment_page(
        html,
        page_url=PAGE_URL,
        skips=skipped_children(
            {
                SNAPSHOT_META_SKIPPED_KEY: [
                    {"tag": "header", "id": None, "classes": "nav_component hide", "reason": "hidden"},
                    {"tag": "footer", "id": None, "classes": "footer_component hide", "reason": "hidden"},
                ]
            }
        ),
        bands=measured_bands(
            {
                SNAPSHOT_META_BANDS_KEY: [
                    {
                        "index": 0,
                        "tag": "section",
                        "classes": "section_home-hero",
                        "top": 80.0,
                        "height": 600.0,
                    }
                ]
            }
        ),
        viewport_width=1200,
    )
    assert len(result.hidden_sections) == 2
    assert {section.role for section in result.hidden_sections} == {"nav", "footer"}
    assert all(crop_extent(result, section) is None for section in result.hidden_sections)


def test_a_dormant_section_still_carries_its_own_markup_and_slots() -> None:
    """Preserved means preserved: the artifact is a real clone, not a stub. It is the STATUS
    that keeps it off the page."""
    _segmentation, _outcome, recorder = _mint(
        HIDDEN_PAGE, bands=measured_bands({SNAPSHOT_META_BANDS_KEY: HIDDEN_PAGE_BANDS})
    )
    dormant = next(call for call in recorder.created if call.get("status") == "dormant")
    assert "Pricing" in dormant["html"]
    assert "From $99." in dormant["html"]


# --------------------------------------------------------------------------- #
# D-F6: dead scroll height
# --------------------------------------------------------------------------- #


def test_a_band_far_taller_than_anything_visible_in_it_is_dead_height() -> None:
    tall = DEAD_HEIGHT_MIN_SECTION_PX + 400.0
    preview = _shot(int(tall), content=(0, 200))
    finding = detect_dead_height(preview, section_height_px=tall, basis="measured")
    assert finding is not None
    assert finding.reason == DEAD_HEIGHT_REASON
    assert finding.content_fraction < DEAD_HEIGHT_MAX_CONTENT_FRACTION


def test_a_band_whose_content_fills_it_is_not_dead_height() -> None:
    tall = DEAD_HEIGHT_MIN_SECTION_PX + 400.0
    preview = _shot(int(tall), content=(100, int(tall) - 100))
    assert detect_dead_height(preview, section_height_px=tall, basis="measured") is None


def test_a_band_just_under_the_content_threshold_trips_and_just_over_does_not() -> None:
    """The threshold is a named constant and it is exercised from both sides, one row apart."""
    tall = DEAD_HEIGHT_MIN_SECTION_PX + 400.0
    rows = int(tall)
    just_under = int(rows * DEAD_HEIGHT_MAX_CONTENT_FRACTION) - 10
    just_over = int(rows * DEAD_HEIGHT_MAX_CONTENT_FRACTION) + 10

    assert detect_dead_height(
        _shot(rows, content=(0, just_under)), section_height_px=tall, basis="measured"
    ) is not None
    assert detect_dead_height(
        _shot(rows, content=(0, just_over)), section_height_px=tall, basis="measured"
    ) is None


def test_an_ordinary_short_section_is_never_dead_height_however_empty_it_looks() -> None:
    """A thin divider or a flat-background strip is not artificial scroll height. The floor is
    what keeps the detector about SCROLL COST rather than about emptiness."""
    short = DEAD_HEIGHT_MIN_SECTION_PX - 100.0
    assert detect_dead_height(
        _shot(int(short), content=None), section_height_px=short, basis="measured"
    ) is None


def test_a_crop_we_only_inferred_is_never_judged() -> None:
    """A nav/footer extent is inferred from its neighbours, so the pixels may not be the
    section's. Judging a section on somebody else's picture is worse than not judging it."""
    tall = DEAD_HEIGHT_MIN_SECTION_PX + 400.0
    preview = _shot(int(tall), content=(0, 100))
    assert (
        detect_dead_height(
            preview, section_height_px=tall, basis="inferred-above-first-band"
        )
        is None
    )


DEAD_PAGE = (
    "<html><body><main>"
    '<section class="section_hero"><h1>Ship faster</h1></section>'
    '<section class="section_scrolljack"><h2>How it works</h2><p>Step one.</p></section>'
    "</main></body></html>"
)


def _dead_page_bands(scroll_height: float):
    return measured_bands(
        {
            SNAPSHOT_META_BANDS_KEY: [
                {
                    "index": 0,
                    "tag": "section",
                    "classes": "section_hero",
                    "top": 0.0,
                    "height": 600.0,
                },
                {
                    "index": 1,
                    "tag": "section",
                    "classes": "section_scrolljack",
                    "top": 600.0,
                    "height": scroll_height,
                },
            ]
        }
    )


def test_a_scroll_jacked_section_is_minted_and_born_degraded() -> None:
    scroll_height = DEAD_HEIGHT_MIN_SECTION_PX + 400.0
    screenshot = _shot(int(600 + scroll_height), content=(0, 800))
    _segmentation, outcome, recorder = _mint(
        DEAD_PAGE, bands=_dead_page_bands(scroll_height), screenshot=screenshot
    )
    marked = {minted.role: minted.degraded for minted in outcome.minted}
    assert marked["hero"] is False
    jacked = next(
        call for call in recorder.created if call["section_role"] not in ("hero", "nav")
    )
    assert jacked["degraded"] is True
    assert jacked["degraded_reason"] == DEAD_HEIGHT_REASON
    assert jacked["provenance"]["degraded"]["section_height_px"] == scroll_height
    assert any(d["code"] == MINT_DEGRADED_CODE for d in outcome.diagnostics)


def test_a_section_whose_content_fills_its_band_is_minted_clean() -> None:
    scroll_height = DEAD_HEIGHT_MIN_SECTION_PX + 400.0
    screenshot = _shot(int(600 + scroll_height), content=(0, int(600 + scroll_height)))
    _segmentation, outcome, _recorder = _mint(
        DEAD_PAGE, bands=_dead_page_bands(scroll_height), screenshot=screenshot
    )
    assert all(minted.degraded is False for minted in outcome.minted)
    assert not [d for d in outcome.diagnostics if d["code"] == MINT_DEGRADED_CODE]


def test_a_page_with_no_screenshot_judges_nothing_rather_than_guessing() -> None:
    scroll_height = DEAD_HEIGHT_MIN_SECTION_PX + 400.0
    _segmentation, outcome, _recorder = _mint(
        DEAD_PAGE, bands=_dead_page_bands(scroll_height), screenshot=None
    )
    assert all(minted.degraded is False for minted in outcome.minted)
