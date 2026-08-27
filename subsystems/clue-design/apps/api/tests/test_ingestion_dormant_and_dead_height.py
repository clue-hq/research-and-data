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
    DEAD_HEIGHT_MIN_CROP_COVERAGE,
    DEAD_HEIGHT_MIN_SECTION_PX,
    DEAD_HEIGHT_REASON,
    assess_dead_height,
    detect_dead_height,
)
from lumen_ingestion.sections.mint import (
    MINT_CAPPED_CODE,
    MINT_DEGRADED_CODE,
    MINT_DEGRADED_RECONCILED_CODE,
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
    """The F1 creation seam, the design byte store and the F3.0 marker writer, injected.

    ``held`` stands in for the rows a previous ingestion already wrote: a fragment id present
    there makes ``create_fragment`` behave the way ``insert_web_fragment``'s ``ON CONFLICT DO
    NOTHING`` really behaves — the offered birth facts are discarded and the existing row comes
    back — which is the only way to exercise the reconciliation path.
    """

    def __init__(self, held: dict[str, dict] | None = None) -> None:
        self.created: list[dict] = []
        self.marked: list[dict] = []
        self.held: dict[str, dict] = dict(held or {})

    def register_bytes(self, data: bytes, media_type: str) -> str:
        return hashlib.sha256(data).hexdigest()

    def mark_degraded(self, fragment_id: str, *, degraded: bool, reason: str | None) -> dict:
        self.marked.append(
            {"fragment_id": fragment_id, "degraded": degraded, "reason": reason}
        )
        row = dict(self.held.get(fragment_id) or {})
        row.update(
            {"fragment_id": fragment_id, "degraded": degraded, "degraded_reason": reason}
        )
        self.held[fragment_id] = row
        return row

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
        held = self.held.get(artifact.fragment_id)
        if held is not None:
            # ON CONFLICT DO NOTHING: the offered birth facts are discarded.
            self.created.append({**kwargs, "row": held})
            return held, artifact
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
        self.held[artifact.fragment_id] = row
        self.created.append({**kwargs, "row": row})
        return row, artifact


def _mint(
    html: str,
    *,
    bands=(),
    skips=(),
    screenshot=None,
    viewport_width=1200,
    recorder=None,
    limit=SECTION_MINT_CAP,
    dormant_limit=SECTION_MINT_CAP,
):
    recorder = recorder or _Recorder()
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
        mark_degraded=recorder.mark_degraded,
        limit=limit,
        dormant_limit=dormant_limit,
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
    finding = detect_dead_height(preview, section_height_px=tall, basis="measured", viewport_width=1200)
    assert finding is not None
    assert finding.reason == DEAD_HEIGHT_REASON
    assert finding.content_fraction < DEAD_HEIGHT_MAX_CONTENT_FRACTION


def test_a_band_whose_content_fills_it_is_not_dead_height() -> None:
    tall = DEAD_HEIGHT_MIN_SECTION_PX + 400.0
    preview = _shot(int(tall), content=(100, int(tall) - 100))
    assert detect_dead_height(preview, section_height_px=tall, basis="measured", viewport_width=1200) is None


def test_a_band_just_under_the_content_threshold_trips_and_just_over_does_not() -> None:
    """The threshold is a named constant and it is exercised from both sides, one row apart."""
    tall = DEAD_HEIGHT_MIN_SECTION_PX + 400.0
    rows = int(tall)
    just_under = int(rows * DEAD_HEIGHT_MAX_CONTENT_FRACTION) - 10
    just_over = int(rows * DEAD_HEIGHT_MAX_CONTENT_FRACTION) + 10

    assert detect_dead_height(
        _shot(rows, content=(0, just_under)), section_height_px=tall, basis="measured", viewport_width=1200
    ) is not None
    assert detect_dead_height(
        _shot(rows, content=(0, just_over)), section_height_px=tall, basis="measured", viewport_width=1200
    ) is None


def test_an_ordinary_short_section_is_never_dead_height_however_empty_it_looks() -> None:
    """A thin divider or a flat-background strip is not artificial scroll height. The floor is
    what keeps the detector about SCROLL COST rather than about emptiness."""
    short = DEAD_HEIGHT_MIN_SECTION_PX - 100.0
    assert detect_dead_height(
        _shot(int(short), content=None), section_height_px=short, basis="measured", viewport_width=1200
    ) is None


def test_a_crop_we_only_inferred_is_never_judged() -> None:
    """A nav/footer extent is inferred from its neighbours, so the pixels may not be the
    section's. Judging a section on somebody else's picture is worse than not judging it."""
    tall = DEAD_HEIGHT_MIN_SECTION_PX + 400.0
    preview = _shot(int(tall), content=(0, 100))
    assert (
        detect_dead_height(
            preview,
            section_height_px=tall,
            basis="inferred-above-first-band",
            viewport_width=1200,
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


# --------------------------------------------------------------------------- #
# I4: the two halves of the measurement must be talking about the same stretch
# --------------------------------------------------------------------------- #


def test_a_crop_the_screenshot_cut_short_is_not_judged() -> None:
    """The floor is the BAND's height in CSS px; the fraction is counted over the CROP's rows.
    A 4000px band whose screenshot ends 900px in yields a slice of the section's top padding —
    a tiny fraction of a slice, and a durable `degraded` marker that sends the repair ladder
    after a section that was never broken."""
    tall = 4000.0
    clipped = _shot(900, content=(0, 60))  # only the very top of the band was captured
    assessment = assess_dead_height(
        clipped, section_height_px=tall, basis="measured", viewport_width=1200
    )
    assert assessment.finding is None
    assert assessment.judged is False
    assert assessment.abstained_because == "crop_clipped"


def test_a_crop_that_covers_its_band_is_judged_normally() -> None:
    """The guard must discriminate, not blanket-refuse: a whole-band crop still gets judged."""
    tall = 4000.0
    whole = _shot(int(tall * DEAD_HEIGHT_MIN_CROP_COVERAGE) + 20, content=(0, 200))
    assessment = assess_dead_height(
        whole, section_height_px=tall, basis="measured", viewport_width=1200
    )
    assert assessment.judged is True
    assert assessment.finding is not None


def test_an_unknown_viewport_is_an_abstention_not_a_verdict() -> None:
    """Without the viewport there is no conversion between preview rows and CSS pixels, so the
    coverage guard cannot run — and the module does not guess at the conversion."""
    tall = DEAD_HEIGHT_MIN_SECTION_PX + 400.0
    assessment = assess_dead_height(
        _shot(int(tall), content=(0, 100)),
        section_height_px=tall,
        basis="measured",
        viewport_width=None,
    )
    assert assessment.judged is False
    assert assessment.abstained_because == "viewport_unknown"


def test_a_short_band_is_JUDGED_not_dead_rather_than_left_unjudged() -> None:
    """The distinction R-I1 rides on. "Looked at, and it is fine" is a clean bill; "could not
    look" is not, and only the first may clear a marker somebody else set."""
    short = DEAD_HEIGHT_MIN_SECTION_PX - 100.0
    assessment = assess_dead_height(
        _shot(int(short), content=None),
        section_height_px=short,
        basis="measured",
        viewport_width=1200,
    )
    assert assessment.judged is True
    assert assessment.finding is None


# --------------------------------------------------------------------------- #
# I1: a re-mint that converges reconciles the marker — on evidence, both ways
# --------------------------------------------------------------------------- #


SCROLL_HEIGHT = DEAD_HEIGHT_MIN_SECTION_PX + 400.0
DEAD_SHOT = _shot(int(600 + SCROLL_HEIGHT), content=(0, 800))
LIVE_SHOT = _shot(int(600 + SCROLL_HEIGHT), content=(0, int(600 + SCROLL_HEIGHT)))


def _held_after(screenshot: bytes | None) -> tuple[_Recorder, str]:
    """Mint the scroll-jacked page once so its rows exist; hand back the recorder and that id.

    The recorder's ``held`` map is the stand-in for rows a previous ingestion wrote, and it makes
    ``create_fragment`` behave as ``ON CONFLICT DO NOTHING`` really behaves. A test then flips the
    held row's marker to the reading the OTHER capture would have produced and re-mints the same
    inputs — which is the convergence this reconciliation exists for, stated directly instead of
    smuggled in through a second capture story.
    """
    _segmentation, outcome, recorder = _mint(
        DEAD_PAGE, bands=_dead_page_bands(SCROLL_HEIGHT), screenshot=screenshot
    )
    jacked = next(
        minted for minted in outcome.minted if minted.role not in ("hero", "nav")
    )
    recorder.created.clear()
    recorder.marked.clear()
    return recorder, jacked.fragment_id


def _remint(recorder: _Recorder, screenshot: bytes | None):
    _segmentation, outcome, _recorder = _mint(
        DEAD_PAGE,
        bands=_dead_page_bands(SCROLL_HEIGHT),
        screenshot=screenshot,
        recorder=recorder,
    )
    return outcome


def test_a_capture_that_finds_dead_height_marks_the_row_it_converged_onto() -> None:
    """The failure this closes: the job evidence says the section "was minted DEGRADED" and the
    row it converged onto still says otherwise, because ``ON CONFLICT DO NOTHING`` discards a
    converging row's birth facts. The ladder reads the column, so it never sees it."""
    recorder, jacked = _held_after(DEAD_SHOT)
    recorder.held[jacked].update({"degraded": False, "degraded_reason": None})

    outcome = _remint(recorder, DEAD_SHOT)
    assert [mark["degraded"] for mark in recorder.marked] == [True]
    assert recorder.marked[0]["reason"] == DEAD_HEIGHT_REASON
    assert recorder.held[jacked]["degraded"] is True
    reconciled = next(
        d for d in outcome.diagnostics if d["code"] == MINT_DEGRADED_RECONCILED_CODE
    )
    assert reconciled["applied"] is True
    assert (reconciled["was_degraded"], reconciled["degraded"]) == (False, True)


def test_a_capture_that_measures_a_clean_band_clears_the_marker() -> None:
    """The same rule in reverse — the newer LOOK wins, not the older one.

    (The preview digest is part of the fragment id, so the two passes have to share a screenshot
    for the mint to converge at all; the held row carries the OTHER reading, which is the state
    this reconciliation exists to resolve.)"""
    recorder, jacked = _held_after(LIVE_SHOT)
    recorder.held[jacked].update({"degraded": True, "degraded_reason": DEAD_HEIGHT_REASON})

    _remint(recorder, LIVE_SHOT)
    assert [mark["degraded"] for mark in recorder.marked] == [False]
    assert recorder.marked[0]["reason"] is None
    assert recorder.held[jacked]["degraded"] is False


def test_a_pass_that_could_not_look_never_clears_an_existing_marker() -> None:
    """Honest absence is not a clean bill of health. A static-tier re-ingest of a page whose
    scroll-jacked section was already marked must leave the ladder's work alone."""
    recorder, jacked = _held_after(DEAD_SHOT)
    assert recorder.held[jacked]["degraded"] is True

    outcome = _remint(recorder, None)
    assert recorder.marked == []
    assert recorder.held[jacked]["degraded"] is True
    assert not [d for d in outcome.diagnostics if d["code"] == MINT_DEGRADED_RECONCILED_CODE]


def test_a_marker_somebody_else_set_for_another_reason_is_left_alone() -> None:
    """``degraded`` is one column with several future authors. F3.3's behavioural gate will mark
    a clone broken for a blank mobile viewport or a dead control — reasons this detector cannot
    re-measure — so "the band is full of content" must never overrule them."""
    recorder, jacked = _held_after(DEAD_SHOT)
    recorder.held[jacked].update({"degraded": True, "degraded_reason": "blank_on_mobile"})

    outcome = _remint(recorder, LIVE_SHOT)
    assert recorder.marked == []
    assert recorder.held[jacked]["degraded_reason"] == "blank_on_mobile"
    assert not [d for d in outcome.diagnostics if d["code"] == MINT_DEGRADED_RECONCILED_CODE]


def test_a_first_mint_never_pays_for_a_reconciliation_it_does_not_need() -> None:
    """A brand-new row is born with the marker already right, so nothing is written twice."""
    _segmentation, outcome, recorder = _mint(
        DEAD_PAGE, bands=_dead_page_bands(SCROLL_HEIGHT), screenshot=DEAD_SHOT
    )
    assert recorder.marked == []
    assert any(minted.degraded for minted in outcome.minted)
    assert not [d for d in outcome.diagnostics if d["code"] == MINT_DEGRADED_RECONCILED_CODE]


def test_a_divergence_nobody_can_write_is_still_said_out_loud() -> None:
    """A mint path with no marker writer (the pure-driver case) must not swallow the disagreement
    — a job and a row that quietly contradict each other is the defect, not the write."""
    recorder, jacked = _held_after(DEAD_SHOT)
    recorder.held[jacked].update({"degraded": False, "degraded_reason": None})
    recorder.mark_degraded = None  # type: ignore[assignment]

    outcome = _remint(recorder, DEAD_SHOT)
    reconciled = next(
        d for d in outcome.diagnostics if d["code"] == MINT_DEGRADED_RECONCILED_CODE
    )
    assert reconciled["applied"] is False
    assert reconciled["severity"] == "warning"


# --------------------------------------------------------------------------- #
# I2: a hidden section may never starve a visible one
# --------------------------------------------------------------------------- #


def test_hidden_sections_draw_on_their_own_budget_and_cannot_starve_the_page() -> None:
    """The shared cap is ingestion-wide and spent across pages, so a CMS homepage full of
    `w-condition-invisible` variants could exhaust it and leave later pages' VISIBLE sections
    uncloned. Separate pools make that structurally impossible."""
    _segmentation, outcome, _recorder = _mint(
        HIDDEN_PAGE,
        bands=measured_bands({SNAPSHOT_META_BANDS_KEY: HIDDEN_PAGE_BANDS}),
        dormant_limit=0,
    )
    roles = [minted.role for minted in outcome.minted]
    assert "hero" in roles and "proof" in roles
    assert not any(minted.hidden_on_source for minted in outcome.minted)
    capped = [d for d in outcome.diagnostics if d["code"] == MINT_CAPPED_CODE]
    assert [d["scope"] for d in capped] == ["dormant"]
    assert capped[0]["remaining"] == 1


def test_the_visible_cap_is_reported_in_its_own_right() -> None:
    _segmentation, outcome, _recorder = _mint(
        HIDDEN_PAGE, bands=measured_bands({SNAPSHOT_META_BANDS_KEY: HIDDEN_PAGE_BANDS}), limit=1
    )
    assert len([m for m in outcome.minted if not m.hidden_on_source]) == 1
    # The hidden one still mints: it was never competing for that pool.
    assert len([m for m in outcome.minted if m.hidden_on_source]) == 1
    capped = [d for d in outcome.diagnostics if d["code"] == MINT_CAPPED_CODE]
    assert [d["scope"] for d in capped] == ["visible"]


# --------------------------------------------------------------------------- #
# M2: preserving is only ever right for something there is a subtree to preserve
# --------------------------------------------------------------------------- #


def test_loose_content_the_page_hides_is_dropped_not_preserved_as_a_fragment() -> None:
    """A bare `<p class="hide">` is loose content whether or not the page shows it. Testing
    hidden-ness before section-shape promoted it out of the honest LUMI0525 drop into a fragment
    row, a picker entry and a slice of the mint budget — for a paragraph."""
    html = (
        "<html><body>"
        '<section class="section_hero"><h1>Ship</h1></section>'
        '<p class="hide">Cookie note</p>'
        "</body></html>"
    )
    result = segment_page(
        html,
        page_url=PAGE_URL,
        skips=skipped_children(
            {
                SNAPSHOT_META_SKIPPED_KEY: [
                    {"tag": "p", "id": None, "classes": "hide", "reason": "hidden"}
                ]
            }
        ),
    )
    assert result.hidden_sections == ()
    dropped = next(d for d in result.diagnostics if d["code"] == SKIPPED_CONTENT_CODE)
    assert {entry["tag"] for entry in dropped["skipped"]} == {"p"}


# --------------------------------------------------------------------------- #
# I3: the probe's own word is enough by itself
# --------------------------------------------------------------------------- #


def test_an_inline_style_hidden_section_the_probe_skipped_is_dormant_not_draft() -> None:
    """`style="display:none"` carries neither a recognised class token nor an aria attribute, so
    the F2 markup-AND-measurement conjunction missed the commonest spelling of all: the section
    fell through to the visible page, was minted draft, and the next kit approval released a
    clone of a section the site does not show."""
    html = (
        "<html><body><main>"
        '<section class="section_hero"><h1>Ship</h1></section>'
        '<section class="section_pricing" style="display:none"><h2>Pricing</h2></section>'
        '<section class="section_proof"><p>Trusted by teams</p></section>'
        "</main></body></html>"
    )
    result = segment_page(
        html,
        page_url=PAGE_URL,
        skips=skipped_children(
            {
                SNAPSHOT_META_SKIPPED_KEY: [
                    {"tag": "section", "id": None, "classes": "section_pricing", "reason": "hidden"}
                ]
            }
        ),
    )
    assert [section.heading for section in result.hidden_sections] == ["Pricing"]
    assert [section.role for section in result.sections] == ["hero", "proof"]
    assert any("probe" in note for note in result.hidden_sections[0].hidden_evidence)


def test_an_inline_style_hidden_section_is_dormant_even_with_no_probe_record_at_all() -> None:
    """``style="display:none"`` is the element's own literal statement, not a guess about a
    stylesheet, so it needs nothing beside it. F2 already treated it as certain — it threw such a
    child away before it could become a candidate; F3.0 keeps the certainty and preserves it
    instead, which is strictly more conservative than the drop it replaces."""
    html = (
        "<html><body><main>"
        '<section class="section_hero"><h1>Ship</h1></section>'
        '<section class="section_pricing" style="display:none"><h2>Pricing</h2></section>'
        '<section class="section_proof"><p>Trusted by teams</p></section>'
        "</main></body></html>"
    )
    result = segment_page(html, page_url=PAGE_URL)
    assert [section.heading for section in result.hidden_sections] == ["Pricing"]
    assert [section.role for section in result.sections] == ["hero", "proof"]
    assert any("inline style" in note for note in result.hidden_sections[0].hidden_evidence)


def test_a_markup_token_alone_still_never_removes_a_section_from_the_page() -> None:
    """Unchanged in the other direction (ruling R-I3): a class token with no measurement behind
    it is a guess about a stylesheet nobody evaluated. `hidden md:block` is the standard Tailwind
    DESKTOP-visible variant, and captures are taken at desktop width."""
    html = (
        "<html><body><main>"
        '<section class="hidden md:block"><h1>Desktop hero</h1></section>'
        '<section class="tail"><p>Tail.</p></section>'
        "</main></body></html>"
    )
    result = segment_page(html, page_url=PAGE_URL)
    assert result.hidden_sections == ()
    assert len(result.sections) == 2


# --------------------------------------------------------------------------- #
# M4: the live capture's evidence projection, and the branch it turns on
# --------------------------------------------------------------------------- #


class _LiveCapture:
    """The `SiteSnapshot` shape `_SnapshotView` reads — html plus a raw geometry harvest."""

    def __init__(self, html: str, geometry: dict) -> None:
        self.html = html
        self.requested_url = PAGE_URL
        self.geometry = geometry


_LIVE_GEOMETRY = {
    "viewport": 1200,
    "truncated": True,
    "sections": [
        {"index": 0, "tag": "section", "classes": "section", "top": 0.0, "height": 500.0},
        {"index": 1, "tag": "section", "classes": "section", "top": 500.0, "height": 300.0},
    ],
    "skipped": [
        {"tag": "section", "id": None, "classes": "section promo", "reason": "hidden"}
    ],
}


def test_the_live_capture_view_projects_the_same_three_keys_the_stored_row_does() -> None:
    """The live path was reading the persisted row's shape MINUS the probe's skip records, so a
    real ingestion made its hidden and band-binding judgements from markup alone while the
    snapshot beside it held the browser's own answer."""
    from lumen_ingestion.pipeline import _SnapshotView
    from lumen_ingestion.sections.bands import (
        SNAPSHOT_META_TRUNCATED_KEY,
        bands_for_meta,
        skipped_for_meta,
    )

    view = _SnapshotView(_LiveCapture("<html></html>", _LIVE_GEOMETRY), snapshot_id="snap_1")
    assert set(view.meta) == {
        SNAPSHOT_META_BANDS_KEY,
        SNAPSHOT_META_SKIPPED_KEY,
        SNAPSHOT_META_TRUNCATED_KEY,
    }
    assert view.meta[SNAPSHOT_META_BANDS_KEY] == bands_for_meta(_LIVE_GEOMETRY)
    assert view.meta[SNAPSHOT_META_SKIPPED_KEY] == skipped_for_meta(_LIVE_GEOMETRY)
    assert view.meta[SNAPSHOT_META_TRUNCATED_KEY] is True


def test_a_live_capture_now_binds_by_the_probes_own_skip_record() -> None:
    """The projection is not inert: `_bind_bands` subtracts what the probe says it skipped, and
    only THAT evidence resolves three same-class siblings with a hidden middle one. Without the
    skip records this page's middle band binds to the wrong section or refuses outright."""
    from lumen_ingestion.pipeline import _SnapshotView
    from lumen_ingestion.sections.segment import segment_snapshot

    html = (
        "<html><body><main>"
        '<section class="section"><h1>Hero</h1></section>'
        '<section class="section promo"><h2>Promo</h2></section>'
        '<section class="section"><h2>Third</h2></section>'
        "</main></body></html>"
    )
    result = segment_snapshot(_SnapshotView(_LiveCapture(html, _LIVE_GEOMETRY), snapshot_id=None))
    assert [section.heading for section in result.hidden_sections] == ["Promo"]
    # Both bands bound, and the second one landed on `Third` rather than on the hidden promo.
    bound = {section.heading: section.geometry for section in result.sections}
    assert bound["Hero"] is not None and bound["Hero"].top_px == 0.0
    assert bound["Third"] is not None and bound["Third"].top_px == 500.0
