"""Section segmentation over a persisted site snapshot (clone-fidelity F2.1).

The harvest's first stage: given the HTML F0 kept and the band sequence F0 measured, say where
this page's top-level sections BEGIN and END and what each one IS. Nothing here mints, writes or
fetches — it is a mechanical read, so every test below builds its page in-memory and the suite
needs neither the network nor a database.

Three fixture shapes, because three shapes fail differently:

* a Webflow-class page (semantic ``<header>``/``<main>``/``<footer>`` plus Client-First
  ``section_home-hero`` naming) — landmarks carry it;
* a landmark-poor div soup — the measured bands and the content carry it;
* a page whose only signals are CONTENT (a logo wall, a blockquote) — neither landmark nor
  class name says anything.
"""

from __future__ import annotations

import pytest
from selectolax.parser import HTMLParser

from lumen_ingestion.sections.bands import (
    SNAPSHOT_META_BANDS_KEY,
    MeasuredBand,
    bands_for_meta,
    measured_bands,
)
from lumen_ingestion.sections.segment import (
    BAND_ALIGNMENT_REFUSED_CODE,
    COMPOUND_BAND_SPLIT_CODE,
    CONTENT_WEIGHT,
    CONTEST_MARGIN,
    CORROBORATION_BONUS,
    HEADLINE_WEIGHT,
    POSITION_WEIGHT,
    STRONG_HINT_WEIGHT,
    WEAK_HINT_WEIGHT,
    _within_contest_margin,
    ESTIMATED_GEOMETRY_CODE,
    NO_BAND_EVIDENCE_CODE,
    NO_SECTIONS_CODE,
    SKIPPED_CONTENT_CODE,
    UNMEASURED_SECTION_CODE,
    resolve_section,
    segment_page,
    segment_snapshot,
)

# --- fixtures -------------------------------------------------------------------------------

WEBFLOW_HTML = """
<html><head><title>Insight</title></head><body>
  <header class="nav_component">
    <nav class="nav_menu">
      <a class="nav_logo" href="/">Insight</a>
      <a href="/product">Product</a><a href="/pricing">Pricing</a><a href="/demo">Demo</a>
    </nav>
  </header>
  <main>
    <section class="section_home-hero">
      <div class="padding-global">
        <h1>Care that keeps up</h1>
        <p>Neurology practices run on Insight.</p>
        <a class="button" href="/demo">Book a demo</a>
      </div>
    </section>
    <section class="section_home-logos">
      <div class="logo-wall">
        <img src="/a.svg" alt="Acme"><img src="/b.svg" alt="Beta">
        <img src="/c.svg" alt="Gamma"><img src="/d.svg" alt="Delta">
      </div>
    </section>
    <section class="section_home-testimonial">
      <blockquote>It changed how our practice runs.</blockquote>
      <div class="testimonial_cite">Dr. Medress</div>
    </section>
    <section class="home-security_badge">
      <h2>Safe, Secure &amp; Compliant</h2>
      <p>HIPAA compliant and SOC 2 Type II certified.</p>
    </section>
    <section class="section_home-cta">
      <h2>Ready when you are</h2>
      <a href="/demo">Talk to us</a>
    </section>
  </main>
  <footer class="footer_component">
    <div class="footer_links"><a href="/">Home</a><a href="/legal">Legal</a></div>
    <p>© 2026 Insight Health</p>
  </footer>
</body></html>
"""

#: The five bands the rendered-tier probe measures under ``<main>`` — nav and footer sit OUTSIDE
#: the probe's root, which is exactly the asymmetry the segmenter has to survive.
WEBFLOW_BANDS = [
    {"index": 0, "tag": "section", "classes": "section_home-hero", "top": 96.0, "height": 720.0,
     "bg": "#ffffff"},
    {"index": 1, "tag": "section", "classes": "section_home-logos", "top": 816.0, "height": 220.0,
     "bg": "#f5f7fa"},
    {"index": 2, "tag": "section", "classes": "section_home-testimonial", "top": 1036.0,
     "height": 460.0, "bg": "#ffffff"},
    {"index": 3, "tag": "section", "classes": "home-security_badge", "top": 1496.0,
     "height": 520.0, "bg": "#0b1020"},
    {"index": 4, "tag": "section", "classes": "section_home-cta", "top": 2016.0, "height": 380.0,
     "bg": "#ffffff"},
]

DIV_SOUP_HTML = """
<html><body><div id="page">
  <div class="c1">
    <a href="/">Insight</a><a href="/a">Product</a><a href="/b">Pricing</a><a href="/c">Docs</a>
  </div>
  <div class="c2"><h1>Care that keeps up</h1><p>Neurology practices run on Insight.</p>
    <a href="/demo">Book a demo</a></div>
  <div class="c3"><h2>What we do</h2><p>Scheduling, intake, follow-up.</p></div>
  <div class="c4"><h2>How it works</h2><p>Three steps, no training.</p></div>
  <div class="c5"><a href="/privacy">Privacy</a><a href="/terms">Terms</a>
    <a href="/legal">Legal</a><a href="/contact">Contact</a>
    <p>© 2026 Insight Health. All rights reserved.</p></div>
</div></body></html>
"""

DIV_SOUP_BANDS = [
    {"index": 0, "tag": "div", "classes": "c1", "top": 0.0, "height": 96.0},
    {"index": 1, "tag": "div", "classes": "c2", "top": 96.0, "height": 760.0},
    {"index": 2, "tag": "div", "classes": "c3", "top": 856.0, "height": 480.0},
    {"index": 3, "tag": "div", "classes": "c4", "top": 1336.0, "height": 520.0},
    {"index": 4, "tag": "div", "classes": "c5", "top": 1856.0, "height": 300.0},
]

CONTENT_ONLY_HTML = """
<html><body>
  <section class="band-a">
    <p>Trusted by teams at</p>
    <img src="/1.svg" alt="One"><img src="/2.svg" alt="Two"><img src="/3.svg" alt="Three">
  </section>
  <section class="band-b">
    <blockquote>Best thing we bought all year.</blockquote>
    <p>Dana, COO</p>
  </section>
</body></html>
"""


class _Snapshot:
    """The read seam's shape, as much of it as the segmenter touches."""

    def __init__(self, html: str, *, meta: dict | None = None, viewport_width: int | None = 1440):
        self.snapshot_id = "snap_deadbeefdeadbeef"
        self.page_url = "https://insighthealth.example/"
        self.html = html
        self.meta = meta or {}
        self.viewport_width = viewport_width


def _roles(segmentation) -> list[str]:
    return [section.role for section in segmentation.sections]


# --- the Webflow-class page -----------------------------------------------------------------


def test_a_webflow_page_segments_into_its_named_roles_in_document_order():
    result = segment_page(
        WEBFLOW_HTML,
        page_url="https://insighthealth.example/",
        bands=measured_bands({SNAPSHOT_META_BANDS_KEY: WEBFLOW_BANDS}),
        viewport_width=1440,
    )
    assert _roles(result) == [
        "nav",
        "hero",
        "proof",
        "testimonial",
        "security",
        "other",
        "footer",
    ]
    assert [s.index for s in result.sections] == list(range(7))
    # A section that fits no named role is still a section, and says so honestly.
    assert result.sections[5].confidence < result.sections[1].confidence


def test_every_role_call_carries_the_evidence_behind_it():
    result = segment_page(WEBFLOW_HTML, page_url="https://x.example/")
    hero = next(s for s in result.sections if s.role == "hero")
    signals = {ev.signal for ev in hero.evidence}
    assert "class-hint" in signals
    assert any("hero" in ev.detail for ev in hero.evidence)
    nav = next(s for s in result.sections if s.role == "nav")
    assert any(ev.signal == "landmark" for ev in nav.evidence)
    security = next(s for s in result.sections if s.role == "security")
    assert any(ev.signal == "content" for ev in security.evidence)


def test_a_dom_path_re_finds_the_same_element_after_a_re_parse():
    result = segment_page(WEBFLOW_HTML, page_url="https://x.example/")
    fresh = HTMLParser(WEBFLOW_HTML)
    for section in result.sections:
        node = resolve_section(fresh, section)
        assert node is not None
        assert node.tag == section.tag
        assert tuple((node.attributes.get("class") or "").split()) == section.class_names
    hero = next(s for s in result.sections if s.role == "hero")
    assert "Care that keeps up" in resolve_section(fresh, hero).html


def test_the_same_snapshot_segments_identically_twice():
    once = segment_page(WEBFLOW_HTML, page_url="https://x.example/", bands=measured_bands(
        {SNAPSHOT_META_BANDS_KEY: WEBFLOW_BANDS}
    ))
    twice = segment_page(WEBFLOW_HTML, page_url="https://x.example/", bands=measured_bands(
        {SNAPSHOT_META_BANDS_KEY: WEBFLOW_BANDS}
    ))
    assert once.sections == twice.sections
    assert once.diagnostics == twice.diagnostics


def test_sections_are_ordered_and_never_overlap():
    result = segment_page(
        DIV_SOUP_HTML,
        page_url="https://x.example/",
        bands=measured_bands({SNAPSHOT_META_BANDS_KEY: DIV_SOUP_BANDS}),
    )
    extents = [(s.geometry.top_px, s.geometry.bottom_px) for s in result.sections]
    assert extents == sorted(extents)
    for (_, previous_bottom), (next_top, _) in zip(extents, extents[1:]):
        assert next_top >= previous_bottom


# --- the measured bands ---------------------------------------------------------------------


def test_measured_bands_give_a_section_its_y_extent_and_name_their_source():
    result = segment_page(
        WEBFLOW_HTML,
        page_url="https://x.example/",
        bands=measured_bands({SNAPSHOT_META_BANDS_KEY: WEBFLOW_BANDS}),
        viewport_width=1440,
    )
    hero = next(s for s in result.sections if s.role == "hero")
    assert hero.band_index == 0
    assert hero.geometry.top_px == 96.0
    assert hero.geometry.bottom_px == 816.0
    assert hero.geometry.basis == "measured"
    assert hero.geometry.viewport_width == 1440


def test_a_section_outside_the_measured_root_carries_no_geometry_and_says_so():
    # The probe roots at `<main>`, so a semantic page's nav and footer are never measured.
    result = segment_page(
        WEBFLOW_HTML,
        page_url="https://x.example/",
        bands=measured_bands({SNAPSHOT_META_BANDS_KEY: WEBFLOW_BANDS}),
    )
    nav = next(s for s in result.sections if s.role == "nav")
    footer = next(s for s in result.sections if s.role == "footer")
    assert nav.geometry is None and nav.band_index is None
    assert footer.geometry is None
    codes = [d["code"] for d in result.diagnostics]
    assert UNMEASURED_SECTION_CODE in codes


def test_geometry_is_estimated_when_the_probe_recorded_no_absolute_tops():
    bands = [{k: v for k, v in band.items() if k != "top"} for band in WEBFLOW_BANDS]
    result = segment_page(
        WEBFLOW_HTML,
        page_url="https://x.example/",
        bands=measured_bands({SNAPSHOT_META_BANDS_KEY: bands}),
    )
    hero = next(s for s in result.sections if s.role == "hero")
    assert hero.geometry.basis == "estimated"
    assert hero.geometry.top_px == 0.0
    assert hero.geometry.bottom_px == 720.0
    assert ESTIMATED_GEOMETRY_CODE in [d["code"] for d in result.diagnostics]


def test_a_page_with_no_band_evidence_still_segments_and_says_it_is_blind():
    result = segment_page(WEBFLOW_HTML, page_url="https://x.example/")
    assert _roles(result)[:2] == ["nav", "hero"]
    assert all(section.geometry is None for section in result.sections)
    assert NO_BAND_EVIDENCE_CODE in [d["code"] for d in result.diagnostics]


def test_bands_that_do_not_line_up_with_the_dom_are_refused_loudly():
    strange = [
        {"index": 0, "tag": "article", "classes": "nothing-like-it", "top": 0.0, "height": 500.0},
        {"index": 1, "tag": "aside", "classes": "still-not", "top": 500.0, "height": 500.0},
    ]
    result = segment_page(
        WEBFLOW_HTML,
        page_url="https://x.example/",
        bands=measured_bands({SNAPSHOT_META_BANDS_KEY: strange}),
    )
    assert all(section.geometry is None for section in result.sections)
    assert all(section.band_index is None for section in result.sections)
    assert BAND_ALIGNMENT_REFUSED_CODE in [d["code"] for d in result.diagnostics]
    # Refusing the geometry does not cost the role calls.
    assert _roles(result)[:2] == ["nav", "hero"]


# --- the landmark-poor page -----------------------------------------------------------------


def test_a_div_soup_page_leans_on_the_bands_and_the_content():
    result = segment_page(
        DIV_SOUP_HTML,
        page_url="https://x.example/",
        bands=measured_bands({SNAPSHOT_META_BANDS_KEY: DIV_SOUP_BANDS}),
        viewport_width=1440,
    )
    assert _roles(result) == ["nav", "hero", "other", "other", "footer"]
    nav = result.sections[0]
    assert any(ev.signal in {"band", "position"} for ev in nav.evidence)
    assert nav.confidence < result.sections[1].confidence or nav.confidence <= 0.75


def test_content_alone_can_call_proof_and_testimonial():
    result = segment_page(CONTENT_ONLY_HTML, page_url="https://x.example/")
    assert _roles(result) == ["proof", "testimonial"]
    proof = result.sections[0]
    assert any("logo" in ev.detail or "trusted by" in ev.detail.lower() for ev in proof.evidence)


# --- refusals -------------------------------------------------------------------------------


def test_two_named_roles_in_one_class_name_fall_back_to_other():
    html = """
    <html><body>
      <section class="hero-testimonial"><h2>Voices</h2><p>Some copy here.</p></section>
      <section class="closing"><p>More copy.</p></section>
    </body></html>
    """
    result = segment_page(html, page_url="https://x.example/")
    assert result.sections[0].role == "other"
    detail = " ".join(ev.detail for ev in result.sections[0].evidence)
    assert "hero" in detail and "testimonial" in detail


def test_a_second_hero_is_demoted_rather_than_named_twice():
    html = """
    <html><body>
      <section class="section_home-hero"><h1>First</h1><p>Copy.</p></section>
      <section class="section_home-hero"><h2>Second</h2><p>Copy.</p></section>
    </body></html>
    """
    result = segment_page(html, page_url="https://x.example/")
    assert _roles(result) == ["hero", "other"]
    assert any("already" in ev.detail for ev in result.sections[1].evidence)


def test_sibling_bands_that_share_a_class_bind_once_the_hidden_one_is_named():
    # Three sections named alike; the browser measured two, because the middle one is hidden by
    # a class. Greedy in-order matching would bind the testimonial's band to the hidden promo —
    # a plausible, wrong crop — and the F2 wave's predecessor answered that by refusing the whole
    # page. There IS evidence here, though: the markup says which section is not on the page. So
    # the hidden one is subtracted, the residue lines up one-for-one, and both bands bind.
    html = """
    <html><body><main>
      <section class="section"><h1>Care that keeps up</h1><p>Copy.</p></section>
      <section class="section w-condition-invisible"><h2>Promo</h2><p>Limited time.</p></section>
      <section class="section"><blockquote>It changed our practice.</blockquote></section>
    </main></body></html>
    """
    bands = [
        {"index": 0, "tag": "section", "classes": "section", "top": 0.0, "height": 720.0},
        {"index": 1, "tag": "section", "classes": "section", "top": 700.0, "height": 400.0},
    ]
    result = segment_page(
        html,
        page_url="https://x.example/",
        bands=measured_bands({SNAPSHOT_META_BANDS_KEY: bands}),
    )
    # The hidden promo is not a section at all any more, and the two real ones carry geometry.
    assert _roles(result) == ["hero", "testimonial"]
    assert [s.band_index for s in result.sections] == [0, 1]
    assert all(s.geometry is not None and s.geometry.basis == "measured" for s in result.sections)
    assert not [d for d in result.diagnostics if d["code"] == BAND_ALIGNMENT_REFUSED_CODE]


def test_repeated_section_names_still_bind_when_the_alignment_is_the_only_one():
    # The same-name case that must NOT be refused: two identically-named feature bands, both
    # measured, in the same order. There is exactly one way to line them up.
    html = """
    <html><body><main>
      <section class="section_home-feature"><h2>One</h2><p>Copy.</p></section>
      <section class="section_home-feature"><h2>Two</h2><p>Copy.</p></section>
    </main></body></html>
    """
    bands = [
        {"index": 0, "tag": "section", "classes": "section_home-feature", "top": 0.0,
         "height": 400.0},
        {"index": 1, "tag": "section", "classes": "section_home-feature", "top": 400.0,
         "height": 400.0},
    ]
    result = segment_page(
        html,
        page_url="https://x.example/",
        bands=measured_bands({SNAPSHOT_META_BANDS_KEY: bands}),
    )
    assert [s.band_index for s in result.sections] == [0, 1]
    assert result.sections[1].geometry.top_px == 400.0


def test_a_section_the_browser_skipped_is_reported_for_what_it_is():
    # A middle section the browser never measured, with names distinctive enough that the
    # alignment is unambiguous. The unmeasured-section diagnostic must not claim the section
    # "lies outside the measured root" — it is inside it; the browser simply skipped it.
    html = """
    <html><body><main>
      <section class="section_a"><h1>Care that keeps up</h1></section>
      <section class="section_b"><h2>A band the browser skipped for being short</h2></section>
      <section class="section_c"><blockquote>Quote.</blockquote></section>
    </main></body></html>
    """
    bands = [
        {"index": 0, "tag": "section", "classes": "section_a", "top": 0.0, "height": 720.0},
        {"index": 1, "tag": "section", "classes": "section_c", "top": 720.0, "height": 400.0},
    ]
    result = segment_page(
        html,
        page_url="https://x.example/",
        bands=measured_bands({SNAPSHOT_META_BANDS_KEY: bands}),
    )
    assert [s.band_index for s in result.sections] == [0, None, 1]
    unmeasured = next(d for d in result.diagnostics if d["code"] == UNMEASURED_SECTION_CODE)
    assert unmeasured["inside_measured_root"] == 1
    assert unmeasured["outside_measured_root"] == 0
    assert "outside" not in unmeasured["message"]


def test_a_page_without_main_still_knows_its_header_is_the_nav():
    # No <main>, so every body-flow child sits in the measured root — which used to disqualify
    # the <header> landmark and let `masthead` name the header a hero, demoting the real one.
    html = """
    <html><body><div class="page-wrapper">
      <header class="masthead"><a href="/">Insight</a></header>
      <section class="section_home-hero"><h1>Care that keeps up</h1><p>Copy.</p></section>
      <footer class="footer_component"><p>© 2026 Insight Health</p></footer>
    </div></body></html>
    """
    result = segment_page(html, page_url="https://x.example/")
    assert _roles(result) == ["nav", "hero", "footer"]
    assert any(
        ev.signal == "landmark" and ev.role == "nav" for ev in result.sections[0].evidence
    )
    assert any(
        ev.signal == "landmark" and ev.role == "footer" for ev in result.sections[2].evidence
    )


def test_a_header_inside_the_main_content_is_not_the_page_banner():
    html = """
    <html><body><main>
      <header class="page-intro"><h2>Introducing</h2><p>Copy.</p></header>
      <section class="section_home-hero"><h1>Care that keeps up</h1><p>Copy.</p></section>
    </main></body></html>
    """
    result = segment_page(html, page_url="https://x.example/")
    assert result.sections[0].role != "nav"
    assert not any(ev.signal == "landmark" for ev in result.sections[0].evidence)
    assert result.sections[1].role == "hero"


def test_a_flat_page_keeps_its_containers_and_names_the_loose_content_it_dropped():
    # The shape of this repo's own rendered snapshot fixture: a body whose children are a
    # header and then bare <h1>/<p>/<button>/<img> elements. A lone heading is not a section —
    # nothing about it can be reused as a fragment — but silently losing the page's copy would
    # be a lie about coverage, so the drop is named.
    html = """
    <html><body>
      <header class="site-header"><a href="/">Home</a><a href="/a">A</a><a href="/b">B</a></header>
      <h1>Clinical intelligence for modern care</h1>
      <p>Insight Health turns raw clinical data into confident decisions.</p>
      <button class="btn">Book a demo</button>
    </body></html>
    """
    result = segment_page(html, page_url="https://x.example/")
    assert _roles(result) == ["nav"]
    skipped = next(d for d in result.diagnostics if d["code"] == SKIPPED_CONTENT_CODE)
    assert {entry["tag"] for entry in skipped["skipped"]} == {"h1", "p", "button"}
    assert any("Clinical intelligence" in entry["text"] for entry in skipped["skipped"])


def test_a_measured_band_makes_even_a_leaf_element_a_section():
    html = """
    <html><body>
      <h1>Clinical intelligence for modern care</h1>
      <p>Insight Health turns raw clinical data into confident decisions.</p>
    </body></html>
    """
    bands = [
        {"index": 0, "tag": "h1", "top": 0.0, "height": 420.0},
        {"index": 1, "tag": "p", "top": 420.0, "height": 300.0},
    ]
    result = segment_page(
        html,
        page_url="https://x.example/",
        bands=measured_bands({SNAPSHOT_META_BANDS_KEY: bands}),
    )
    assert [s.tag for s in result.sections] == ["h1", "p"]
    assert result.sections[0].geometry.bottom_px == 420.0


def test_a_page_with_nothing_in_it_yields_no_sections_and_says_so():
    result = segment_page("<html><body></body></html>", page_url="https://x.example/")
    assert result.sections == ()
    assert NO_SECTIONS_CODE in [d["code"] for d in result.diagnostics]


# --- the persisted-snapshot seam ------------------------------------------------------------


def test_segment_snapshot_reads_the_bands_off_the_persisted_meta():
    snapshot = _Snapshot(WEBFLOW_HTML, meta={SNAPSHOT_META_BANDS_KEY: WEBFLOW_BANDS})
    result = segment_snapshot(snapshot)
    assert result.snapshot_id == snapshot.snapshot_id
    assert result.page_url == snapshot.page_url
    assert result.viewport_width == 1440
    hero = next(s for s in result.sections if s.role == "hero")
    assert hero.geometry.top_px == 96.0


def test_bands_for_meta_keeps_the_probe_records_and_bounds_them():
    harvest = {"viewport": 1440, "sections": WEBFLOW_BANDS, "surfaces": [{"cls": "button"}]}
    kept = bands_for_meta(harvest)
    assert kept == WEBFLOW_BANDS
    assert bands_for_meta(None) == []
    assert bands_for_meta({"sections": "nonsense"}) == []
    flood = [{"index": i, "tag": "section", "height": 10.0} for i in range(120)]
    assert len(bands_for_meta({"sections": flood})) == 40


def test_bands_for_meta_refuses_to_carry_an_unbounded_background_image():
    # `bgImage` is a raw CSS value: a data: URI or a multi-layer gradient, up to 40 of them on
    # one row. Nothing downstream reads more than "is there one", so only that is kept.
    import json

    harvest = {
        "sections": [
            {
                "index": 0,
                "tag": "section",
                "classes": "hero " + "utility-class " * 200,
                "bgImage": "url(data:image/png;base64," + "A" * 60_000 + ")",
                "gradient": False,
                "top": 0.0,
                "height": 720.0,
                "bg": "#ffffff",
                "padding": [10, 20, 10, 20],
                "somethingElse": "x" * 5_000,
            }
        ]
    }
    kept = bands_for_meta(harvest)
    assert kept[0]["bgImage"] is True
    assert "padding" not in kept[0] and "somethingElse" not in kept[0]
    assert len(kept[0]["classes"]) <= 512
    assert kept[0]["classes"].split()[0] == "hero"
    assert len(json.dumps(kept)) < 2_000
    # …and what survives still reads back as a band.
    band = measured_bands({SNAPSHOT_META_BANDS_KEY: kept})[0]
    assert band.has_image is True
    assert band.class_names[0] == "hero"
    assert band.top_px == 0.0


def test_measured_bands_tolerate_a_pre_f21_probe_record():
    older = [{"index": 0, "tag": "section", "bg": "#fff", "height": 400.0, "gradient": False}]
    bands = measured_bands({SNAPSHOT_META_BANDS_KEY: older})
    assert bands == (
        MeasuredBand(
            index=0,
            tag="section",
            element_id=None,
            class_names=(),
            top_px=None,
            height_px=400.0,
            background="#fff",
            gradient=False,
            has_image=False,
        ),
    )
    assert measured_bands({}) == ()
    assert measured_bands(None) == ()


def test_a_band_whose_class_list_drifted_since_the_html_was_captured_still_matches():
    # The capture serializes the html BEFORE it runs the geometry probe, so a page's own JS can
    # add or drop a class in between (a sticky nav's `is-scrolled` is the everyday case). A band
    # that still shares a class with the element is the same band.
    drifted = [dict(band) for band in WEBFLOW_BANDS]
    drifted[0]["classes"] = "section_home-hero is-scrolled"
    drifted[1]["classes"] = "section_home-logos w-condition-invisible"
    result = segment_page(
        WEBFLOW_HTML,
        page_url="https://x.example/",
        bands=measured_bands({SNAPSHOT_META_BANDS_KEY: drifted}),
    )
    hero = next(s for s in result.sections if s.role == "hero")
    assert hero.band_index == 0
    assert hero.geometry.top_px == 96.0
    assert BAND_ALIGNMENT_REFUSED_CODE not in [d["code"] for d in result.diagnostics]


def test_bands_that_identify_nothing_must_line_up_one_for_one():
    # A pre-F2.1 harvest recorded tags and heights only. Tag-order matching alone would happily
    # bind the hero's band to a nav <div> the browser skipped, so an anonymous sequence has to
    # account for every parsed section or it is refused outright.
    anonymous = [
        {"index": index, "tag": "section", "height": 200.0}
        for index in range(len(WEBFLOW_BANDS) - 1)
    ]
    refused = segment_page(
        WEBFLOW_HTML,
        page_url="https://x.example/",
        bands=measured_bands({SNAPSHOT_META_BANDS_KEY: anonymous}),
    )
    assert BAND_ALIGNMENT_REFUSED_CODE in [d["code"] for d in refused.diagnostics]
    assert all(section.geometry is None for section in refused.sections)

    complete = [
        {"index": index, "tag": "section", "height": 200.0}
        for index in range(len(WEBFLOW_BANDS))
    ]
    bound = segment_page(
        WEBFLOW_HTML,
        page_url="https://x.example/",
        bands=measured_bands({SNAPSHOT_META_BANDS_KEY: complete}),
    )
    assert next(s for s in bound.sections if s.role == "hero").band_index == 0


def test_a_role_declared_only_in_aria_is_still_a_landmark():
    html = """
    <html><body>
      <div role="navigation"><a href="/">Home</a><a href="/a">A</a><a href="/b">B</a></div>
      <div><h1>Hello</h1><p>Copy.</p></div>
      <div role="contentinfo"><p>© 2026 Someone</p></div>
    </body></html>
    """
    result = segment_page(html, page_url="https://x.example/")
    assert _roles(result) == ["nav", "hero", "footer"]
    assert all(
        any(ev.signal == "landmark" for ev in section.evidence)
        for section in result.sections
        if section.role in {"nav", "footer"}
    )


def test_resolving_a_section_against_different_html_refuses_rather_than_guesses():
    result = segment_page(WEBFLOW_HTML, page_url="https://x.example/")
    footer = next(s for s in result.sections if s.role == "footer")
    assert resolve_section("<html><body><p>different page</p></body></html>", footer) is None
    assert result.by_role("footer") == (footer,)


def test_resolving_a_section_after_the_page_shifted_refuses_rather_than_returning_a_neighbour():
    # A path is a position, and positions move. Minting extracts `resolve_section(...).html`, so
    # a silently shifted path mints the WRONG subtree — the one failure mode a durable handle
    # exists to prevent.
    result = segment_page(WEBFLOW_HTML, page_url="https://x.example/")
    hero = next(s for s in result.sections if s.role == "hero")
    shifted = WEBFLOW_HTML.replace(
        "<main>",
        '<main><section class="section_home-banner"><p>New announcement.</p></section>',
        1,
    )
    assert resolve_section(shifted, hero) is None
    # The same html still resolves, so the check discriminates rather than just refusing.
    assert resolve_section(WEBFLOW_HTML, hero) is not None


def test_a_persisted_snapshot_carries_the_bands_the_probe_measured():
    # `_meta` is the row's meta_json builder; testing it directly keeps this a pure round-trip
    # (the persistence path around it is DB-backed and lives in test_ingestion_site_snapshot).
    from lumen_ingestion.capture.snapshot import SiteSnapshot
    from lumen_ingestion.site_snapshot import _meta

    snapshot = SiteSnapshot(
        requested_url="https://insighthealth.example/",
        final_url="https://insighthealth.example/",
        fetched_at="2026-08-27T00:00:00Z",
        tier="rendered",
        html=WEBFLOW_HTML,
        geometry={"viewport": 1440, "sections": WEBFLOW_BANDS, "surfaces": []},
    )
    meta = _meta(snapshot)
    assert meta[SNAPSHOT_META_BANDS_KEY] == WEBFLOW_BANDS
    assert measured_bands(meta)[0].top_px == 96.0
    # A static-tier capture measured nothing and says so with an empty list, not a missing key.
    snapshot_without = snapshot.model_copy(update={"tier": "static", "geometry": None})
    assert _meta(snapshot_without)[SNAPSHOT_META_BANDS_KEY] == []


def test_the_capture_probe_records_what_a_band_record_needs():
    # The probe only runs inside a browser, so this pins its SOURCE: `measured_bands` reads a
    # band's absolute top, id and class list, and a probe that stopped recording them would
    # silently downgrade every future snapshot to estimated geometry.
    from lumen_ingestion.capture.geometry import GEOMETRY_JS

    band_record = GEOMETRY_JS.split("sections.push({", 1)[1].split("});", 1)[0]
    for key in ("index:", "tag:", "id:", "classes:", "top:", "height:", "bg:"):
        assert key in band_record


@pytest.mark.parametrize("role", ["nav", "hero", "proof", "testimonial", "security", "footer"])
def test_every_named_role_is_reachable_from_the_vocabulary(role):
    from lumen_ingestion.sections.segment import SECTION_ROLES

    assert role in SECTION_ROLES
    assert "other" in SECTION_ROLES


# --------------------------------------------------------------------------- #
# F2 fix wave — W1 (the floor guarantee), W3 (rendered text), W4 (hidden class)
# --------------------------------------------------------------------------- #

from lumen_ingestion.sections.bands import (  # noqa: E402
    SNAPSHOT_META_SKIPPED_KEY,
    bands_were_truncated,
    skipped_children,
    skipped_for_meta,
)
from lumen_ingestion.sections.segment import rendered_text  # noqa: E402

_AMBIGUOUS_PAGE = """
<html><body><main>
  <section class="section_home-hero"><h1>Ship faster</h1></section>
  <section class="section"><h2>Featured in</h2></section>
  <section class="section_products"><h2>Products</h2></section>
  <section class="section"><h2>Safe and compliant</h2></section>
  <section class="section"><h2>Dr Medress</h2></section>
  <section class="section pricing-not-shown"><h2>Pricing</h2></section>
  <section class="overflow-hidden"><h2>Testimonials</h2></section>
</main></body></html>
"""

#: Six bands for seven same-shaped sections: the walk's real shape, with the site's own private
#: hidden-class spelling (which nothing here is allowed to know about).
_AMBIGUOUS_BANDS = [
    {"index": 0, "tag": "section", "classes": "section_home-hero", "top": 0.0, "height": 600.0},
    {"index": 1, "tag": "section", "classes": "section", "top": 600.0, "height": 200.0},
    {"index": 2, "tag": "section", "classes": "section_products", "top": 800.0, "height": 400.0},
    {"index": 3, "tag": "section", "classes": "section", "top": 1200.0, "height": 200.0},
    {"index": 4, "tag": "section", "classes": "section", "top": 1400.0, "height": 200.0},
    {"index": 5, "tag": "section", "classes": "overflow-hidden", "top": 1600.0, "height": 300.0},
]


def _ambiguous(**kwargs):
    return segment_page(
        _AMBIGUOUS_PAGE,
        page_url="https://x.example/",
        bands=measured_bands({SNAPSHOT_META_BANDS_KEY: _AMBIGUOUS_BANDS}),
        **kwargs,
    )


def test_the_bands_that_are_forced_bind_even_when_others_are_contested():
    """THE FLOOR GUARANTEE (W1b). Whole-list agreement cost the F2 acceptance walk every preview
    on its primary site: two contested bands out of six refused all thirteen sections' geometry.
    A band whose earliest and latest feasible candidate are the same candidate is FORCED — no
    valid alignment can place it anywhere else — so it binds, and only the genuinely contested
    span goes without."""
    result = _ambiguous()
    bound = [s for s in result.sections if s.geometry is not None]
    assert len(bound) >= 4
    refusal = next(d for d in result.diagnostics if d["code"] == BAND_ALIGNMENT_REFUSED_CODE)
    assert refusal["reason"] == "partial"
    assert refusal["bound_bands"] and refusal["contested_bands"]
    assert len(refusal["bound_bands"]) + len(refusal["contested_bands"]) == 6
    # Every bound band's geometry is the browser's own measurement, never a reconstruction.
    assert all(s.geometry.basis == "measured" for s in bound)


def test_a_contested_page_with_no_measured_tops_still_refuses_whole():
    """Partial binding is restricted to measured tops: the running-sum fallback reconstructs a
    section's top by accumulating the heights before it, which is only true when the bound set is
    contiguous. With holes it would place every later section at the wrong offset — confidently."""
    topless = [{k: v for k, v in band.items() if k != "top"} for band in _AMBIGUOUS_BANDS]
    result = segment_page(
        _AMBIGUOUS_PAGE,
        page_url="https://x.example/",
        bands=measured_bands({SNAPSHOT_META_BANDS_KEY: topless}),
    )
    assert all(s.geometry is None for s in result.sections)
    refusal = next(d for d in result.diagnostics if d["code"] == BAND_ALIGNMENT_REFUSED_CODE)
    assert refusal["reason"] == "ambiguous"


def test_the_probes_own_skip_records_resolve_the_page_completely():
    """W1a. The browser is the only thing that can answer "is this hidden?". When it says so, the
    residue lines up one-for-one and every band binds with certainty — no feasibility argument
    needed."""
    skips = skipped_children(
        {
            SNAPSHOT_META_SKIPPED_KEY: [
                {"tag": "section", "id": None, "classes": "section pricing-not-shown",
                 "reason": "hidden"}
            ]
        }
    )
    result = _ambiguous(skips=skips)
    assert not [d for d in result.diagnostics if d["code"] == BAND_ALIGNMENT_REFUSED_CODE]
    assert len([s for s in result.sections if s.geometry is not None]) == 6


def test_a_skip_record_that_identifies_nothing_costs_only_the_shortcut():
    result = _ambiguous(
        skips=skipped_children(
            {SNAPSHOT_META_SKIPPED_KEY: [
                {"tag": "aside", "id": None, "classes": "nope", "reason": "hidden"}
            ]}
        )
    )
    assert len([s for s in result.sections if s.geometry is not None]) >= 4


def test_a_backward_walk_that_matches_nothing_is_not_reported_as_ambiguous():
    """The zip backward-None conflation: a `None` backward walk fell into the ambiguity branch,
    where `zip(forward, backward or [])` compared nothing and the diagnostic named the first band
    as contested — a confident answer to a question nobody asked."""
    html = """
    <html><body><main>
      <section class="only"><h1>One</h1></section>
      <section class="other"><p>Two</p></section>
    </main></body></html>
    """
    bands = [
        {"index": 0, "tag": "section", "classes": "only", "top": 0.0, "height": 300.0},
        {"index": 1, "tag": "section", "classes": "nowhere", "top": 300.0, "height": 300.0},
    ]
    result = segment_page(
        html, page_url="https://x.example/",
        bands=measured_bands({SNAPSHOT_META_BANDS_KEY: bands}),
    )
    refusal = next(d for d in result.diagnostics if d["code"] == BAND_ALIGNMENT_REFUSED_CODE)
    assert refusal["reason"] == "unmatched"
    assert refusal["direction"] in ("forward", "backward")


def test_the_skip_whitelist_projects_and_bounds_what_the_probe_wrote():
    raw = {"skipped": [
        {"tag": "SECTION", "id": "x", "classes": "a " + "b" * 900, "reason": "hidden",
         "outerHTML": "<section>…</section>"},
        {"tag": "div", "reason": "made-up"},
    ]}
    kept = skipped_for_meta(raw)
    assert len(kept) == 1
    assert set(kept[0]) <= {"tag", "id", "classes", "reason"}
    assert len(kept[0]["classes"]) <= 512


def test_a_truncated_probe_says_so_on_the_snapshot():
    assert bands_were_truncated({"bands_truncated": True}) is True
    assert bands_were_truncated({}) is False


# --- W3: rendered text -------------------------------------------------------------------- #


def test_rendered_text_never_reads_script_or_style_source():
    """The F2 walk labelled the nav — the most valuable clone on the page —
    `Nav — document.querySelectorAll('.w-dropdown')…`, scored an empty style embed `security`
    off a CSS comment, and admitted a script shell as a section. One defect, three symptoms:
    the segmenter judged sections by text that will never exist in the artifact."""
    html = (
        '<html><body><main><section class="nav_component">'
        "<script>document.querySelectorAll('.w-dropdown').forEach(d => d.addEventListener())</script>"
        "<style>/* Ensure all elements inherit the color */</style>"
        '<a href="/">Brand Assets</a></section>'
        '<section class="tail"><p>Tail copy.</p></section></main></body></html>'
    )
    node = HTMLParser(html).css_first("section")
    assert rendered_text(node) == "Brand Assets"

    result = segment_page(html, page_url="https://x.example/")
    label = result.sections[0].heading or result.sections[0].text_preview
    assert "querySelectorAll" not in label
    assert "Ensure all elements" not in label
    assert "Brand Assets" in label


def test_a_shell_whose_only_content_is_source_is_not_a_section():
    html = (
        '<html><body><main><div class="w-embed w-script">'
        "<script>(function(w,d){ if(w.__router)return; })()</script></div>"
        '<section class="real"><h1>Real</h1></section>'
        '<section class="tail"><p>Tail.</p></section></main></body></html>'
    )
    result = segment_page(html, page_url="https://x.example/")
    assert [s.role for s in result.sections] == ["hero", "other"]


# --- W4: hidden by class ------------------------------------------------------------------ #


@pytest.mark.parametrize("token", ["hide", "hidden", "d-none", "sr-only", "w-condition-invisible"])
def test_a_section_the_page_hides_by_class_is_not_one_of_the_pages_sections(token: str):
    """The vocabulary, exercised on an EVIDENCED page. The class token alone never removes a
    section (N2) — here the browser measured the page and did not measure this child, which is
    the corroboration removing it from the page requires.

    Still literally accurate under its old name (a dormant clone is never offered), and renamed
    with its two neighbours so the file says one thing about this population rather than three."""
    html = (
        f'<html><body><main><section class="banner {token}"><h2>Announcing</h2></section>'
        '<section class="real"><h1>Real</h1></section>'
        '<section class="tail"><p>Tail.</p></section></main></body></html>'
    )
    bands = [
        {"index": 0, "tag": "section", "classes": "real", "top": 0.0, "height": 500.0},
        {"index": 1, "tag": "section", "classes": "tail", "top": 500.0, "height": 200.0},
    ]
    result = segment_page(
        html,
        page_url="https://x.example/",
        bands=measured_bands({SNAPSHOT_META_BANDS_KEY: bands}),
    )
    assert [s.role for s in result.sections] == ["hero", "other"]


def test_an_overflow_utility_is_not_a_visibility_one():
    """`overflow-hidden` is a Tailwind OVERFLOW utility. A suffix rule (`*-hidden`) read it as a
    visibility one and dropped a real testimonials band on the very page the list was written
    from — which is why the vocabulary is a closed set of whole tokens."""
    html = (
        '<html><body><main><section class="overflow-hidden">'
        "<blockquote>It changed our practice.</blockquote></section>"
        '<section class="tail"><p>Tail.</p></section></main></body></html>'
    )
    result = segment_page(html, page_url="https://x.example/")
    assert result.sections[0].role == "testimonial"


def test_the_browser_overrules_the_class_name():
    """A class named `hide` that the stylesheet never acts on is a guess; a measured band is a
    fact. Where the probe measured the section, it stays."""
    html = (
        '<html><body><main><section class="section hide"><h1>Actually shown</h1></section>'
        '<section class="tail"><p>Tail.</p></section></main></body></html>'
    )
    bands = [
        {"index": 0, "tag": "section", "classes": "section hide", "top": 0.0, "height": 500.0},
        {"index": 1, "tag": "section", "classes": "tail", "top": 500.0, "height": 200.0},
    ]
    result = segment_page(
        html, page_url="https://x.example/",
        bands=measured_bands({SNAPSHOT_META_BANDS_KEY: bands}),
    )
    assert len(result.sections) == 2
    assert result.sections[0].geometry is not None


# --------------------------------------------------------------------------- #
# F2 wave completion — N1 and N2, both defects the wave diff itself introduced
# --------------------------------------------------------------------------- #


def test_the_hidden_class_proposal_never_binds_a_band_to_a_worse_match():
    """N1 (Critical class). The proposal path removes a class-named candidate and then checks the
    residue lines up — but ``_band_matches`` compares classes by INTERSECTION, so the token that
    distinguishes the removed section is exactly the token the line-up ignores.

    Here the `hide`-named section is REALLY ON THE PAGE (the browser measured it and recorded its
    full class attribute). Removing it leaves two same-class siblings that "line up" on the shared
    token alone, and band 0 — which names `section hide` verbatim — binds to a plain `section`
    two positions away. A confident wrong crop, with no feasibility behind it. The old code
    refused this page; the wave made it worse than the thing it was fixing."""
    html = """
    <html><body><main>
      <section class="section hide"><h1>Actually shown</h1></section>
      <section class="section"><h2>Second</h2></section>
      <section class="section"><h2>Third</h2></section>
    </main></body></html>
    """
    bands = [
        {"index": 0, "tag": "section", "classes": "section hide", "top": 0.0, "height": 500.0},
        {"index": 1, "tag": "section", "classes": "section", "top": 500.0, "height": 300.0},
    ]
    result = segment_page(
        html,
        page_url="https://x.example/",
        bands=measured_bands({SNAPSHOT_META_BANDS_KEY: bands}),
    )
    # The band that names `section hide` may never land on a section that is not it.
    for section in result.sections:
        if section.geometry is not None:
            assert "hide" in section.class_names, (
                f"band bound to {section.class_names!r}, which the band's own classes do not name"
            )


def test_the_proposal_still_binds_when_the_removed_section_is_not_a_better_match():
    """The guard must discriminate, not blanket-refuse: the walk's real shape — a hidden section
    whose band nobody recorded — still binds completely."""
    html = """
    <html><body><main>
      <section class="section_hero"><h1>Hero</h1></section>
      <section class="section hide"><h2>Hidden promo</h2></section>
      <section class="section_proof"><h2>Proof</h2></section>
    </main></body></html>
    """
    bands = [
        {"index": 0, "tag": "section", "classes": "section_hero", "top": 0.0, "height": 500.0},
        {"index": 1, "tag": "section", "classes": "section_proof", "top": 500.0, "height": 300.0},
    ]
    result = segment_page(
        html,
        page_url="https://x.example/",
        bands=measured_bands({SNAPSHOT_META_BANDS_KEY: bands}),
    )
    assert [s.role for s in result.sections] == ["hero", "proof"]
    assert all(s.geometry is not None for s in result.sections)


def test_a_desktop_only_section_is_not_dropped_on_a_bandless_capture():
    """N2. `hidden md:block` is the standard Tailwind DESKTOP-visible variant, and captures are
    taken at desktop width — so the element is on the page the clone is being made from. Dropping
    it on a bare class token removed a real section from every static-tier capture and every page
    whose binding was refused, where nothing measured anything and there is no evidence at all."""
    html = """
    <html><body><main>
      <section class="hidden md:block"><h1>Desktop hero</h1></section>
      <section class="tail"><p>Tail.</p></section>
    </main></body></html>
    """
    result = segment_page(html, page_url="https://x.example/")
    assert len(result.sections) == 2
    assert result.sections[0].heading == "Desktop hero"


def test_a_hidden_named_section_the_browser_skipped_is_off_the_page_and_kept_dormant():
    """The evidence-backed half, unchanged: the probe measured this page and did not measure this
    child, so `hidden` in its class list is corroborated rather than guessed.

    Named for what F3.0 made it do (D-F8). The behaviour asserted here has never changed — the
    section is not one of the page's — but "dropped" stopped being true when the section started
    being preserved in ``hidden_sections`` for a human to activate."""
    html = """
    <html><body><main>
      <section class="section_hero"><h1>Hero</h1></section>
      <section class="banner hide"><h2>Announcing</h2></section>
      <section class="section_proof"><h2>Proof</h2></section>
    </main></body></html>
    """
    bands = [
        {"index": 0, "tag": "section", "classes": "section_hero", "top": 0.0, "height": 500.0},
        {"index": 1, "tag": "section", "classes": "section_proof", "top": 500.0, "height": 300.0},
    ]
    result = segment_page(
        html,
        page_url="https://x.example/",
        bands=measured_bands({SNAPSHOT_META_BANDS_KEY: bands}),
    )
    assert [s.role for s in result.sections] == ["hero", "proof"]


def test_a_probe_skip_record_takes_a_section_off_the_page_with_no_bands_at_all():
    """The other evidence path: the browser said so directly, so no binding is needed to believe
    it. Renamed for the same reason as its neighbour above: off the page, not gone."""
    html = """
    <html><body><main>
      <section class="banner hide"><h2>Announcing</h2></section>
      <section class="tail"><p>Tail.</p></section>
    </main></body></html>
    """
    result = segment_page(
        html,
        page_url="https://x.example/",
        skips=skipped_children(
            {SNAPSHOT_META_SKIPPED_KEY: [
                {"tag": "section", "id": None, "classes": "banner hide", "reason": "hidden"}
            ]}
        ),
    )
    assert [s.heading for s in result.sections] == [None]
    assert len(result.sections) == 1


def test_an_id_only_band_still_triggers_the_proposal_guard():
    """N1 follow-up. `_identifies` asked only about CLASSES, and an empty band class list is
    trivially a subset of anything — so a band identified by its `id` alone was "identified" by
    every candidate, and the guard that exists to catch exactly this could never fire.

    The probe: a visible `<section id="promo" aria-hidden="true">` and two identity-less
    siblings. The aria hint removes `promo`, the residue lines up (nothing distinguishes the
    siblings), and `promo`'s own band binds to `Second` — the same wrong-crop class the guard was
    written for, arriving through the one identifier it did not read.
    """
    html = """
    <html><body><main>
      <section id="promo" aria-hidden="true"><h1>Promo</h1></section>
      <section><h2>Second</h2></section>
      <section><h2>Third</h2></section>
    </main></body></html>
    """
    bands = [
        {"index": 0, "tag": "section", "id": "promo", "top": 0.0, "height": 500.0},
        {"index": 1, "tag": "section", "top": 500.0, "height": 300.0},
    ]
    result = segment_page(
        html,
        page_url="https://x.example/",
        bands=measured_bands({SNAPSHOT_META_BANDS_KEY: bands}),
    )
    # The band the browser recorded against `#promo` may not land on a section that is not it.
    for section in result.sections:
        if section.geometry is not None and section.geometry.top_px == 0.0:
            assert section.element_id == "promo", (
                f"promo's band bound to {section.element_id!r} / {section.heading!r}"
            )


# --------------------------------------------------------------------------- #
# F3.4 — compound bands split into the sections their author declared
# --------------------------------------------------------------------------- #


def test_a_wrapper_holding_only_authored_sections_is_split_into_them():
    """The F2 walk minted insighthealth's Testimonials + Blog + Get-Started as ONE fragment.

    The page wraps three `<section>`s in a `<div class="overflow-hidden">`, and that div is what
    the browser measured as a band — so a library of reusable sections held "those three, in that
    order", and none of them could be inserted without the other two.
    """
    html = """
    <html><body><main>
      <section class="hero"><h1>Care, on your terms</h1></section>
      <div class="overflow-hidden">
        <section class="section"><h2>Testimonials</h2><p>Real results.</p></section>
        <section class="section"><h2>From Our Blog</h2><p>Latest writing.</p></section>
        <section class="section_cta"><h2>Get Started</h2><p>Book a demo.</p></section>
      </div>
    </main></body></html>
    """
    bands = [
        {"index": 0, "tag": "section", "classes": "hero", "top": 0.0, "height": 900.0},
        {
            "index": 1,
            "tag": "div",
            "classes": "overflow-hidden",
            "top": 900.0,
            "height": 2286.78,
        },
    ]
    result = segment_page(
        html,
        page_url="https://x.example/",
        bands=measured_bands({SNAPSHOT_META_BANDS_KEY: bands}),
    )

    assert [section.heading for section in result.sections] == [
        "Care, on your terms",
        "Testimonials",
        "From Our Blog",
        "Get Started",
    ]
    # The hero keeps its own measured geometry: the split changes what is minted out of the flow,
    # never the alignment, which ran against the flow the browser actually saw.
    assert result.sections[0].geometry is not None
    assert result.sections[0].geometry.top_px == 0.0
    # The parts carry none, because the browser measured their WRAPPER and their own heights
    # inside it are not derivable from its total. Honest absence, said out loud.
    assert [section.geometry for section in result.sections[1:]] == [None, None, None]
    split = [d for d in result.diagnostics if d["code"] == COMPOUND_BAND_SPLIT_CODE]
    assert len(split) == 1
    assert split[0]["parts"] == 3
    assert split[0]["band_index"] == 1
    assert split[0]["band_height_px"] == 2286.78
    assert "isolation render" in split[0]["message"]
    # …and the OTHER cost the split has, which the first version of this sentence left out (F-9):
    # a part is minted from its own subtree, so a rule written against the wrapper element itself
    # stops applying to it. Rules reaching THROUGH the wrapper survive, and the sentence says so.
    assert 'against <div class="overflow-hidden"> itself' in split[0]["message"]
    assert "rules reaching THROUGH it still do" in split[0]["message"]
    # …and the unmeasured-section diagnostic keeps the three facts apart rather than telling the
    # reader the browser looked at these three and skipped them.
    unmeasured = [d for d in result.diagnostics if d["code"] == UNMEASURED_SECTION_CODE][0]
    assert unmeasured["from_compound_band"] == 3
    assert "measured their wrapper rather than them" in unmeasured["message"]
    # THE LOAD-BEARING PROPERTY: minting extracts `resolve_section(...).html`, so a part whose
    # dom_path did not re-find its own subtree would mint the wrong markup with every appearance
    # of success. Each part re-finds itself, and each finds something different.
    resolved = [resolve_section(html, section) for section in result.sections]
    assert all(node is not None for node in resolved)
    assert [node.css_first("h2").text() for node in resolved[1:]] == [
        "Testimonials",
        "From Our Blog",
        "Get Started",
    ]


def test_a_section_that_declares_itself_one_is_never_split_into_its_subsections():
    """The other compound band the F2 walk named — stripe's 4,598px `business-sizes-section`.

    It carries its own `<h2>` and three `<section>`s that are its SUBSECTIONS, two `<div>`s deep,
    interleaved with dividers that are not sections at all. The author declared one section, so
    it stays one: the same evidence that justifies the split forbids this one.
    """
    html = """
    <html><body><main>
      <section class="business-sizes-section">
        <div class="section-container">
          <div class="section-title"><h2>Powering businesses of all sizes.</h2></div>
          <span class="section-header-divider"></span>
          <div class="section-row">
            <section class="row"><h3>Enterprise</h3><p>Agile finance.</p></section>
            <div class="divider-wrapper"></div>
            <section class="row"><h3>Startups</h3><p>A foundation.</p></section>
          </div>
        </div>
      </section>
      <section class="tail"><h2>Tail</h2><p>Tail.</p></section>
    </main></body></html>
    """
    result = segment_page(html, page_url="https://x.example/")
    assert [section.heading for section in result.sections] == [
        "Powering businesses of all sizes.",
        "Tail",
    ]
    assert [d for d in result.diagnostics if d["code"] == COMPOUND_BAND_SPLIT_CODE] == []


def test_a_grid_of_article_cards_is_one_band_not_three_sections():
    """Ruling R20-2, reproduced live by the reviewer. `<article>` is the standard's SELF-CONTAINED
    composition — a blog card, a news teaser, a product card — so a `<div class="posts">` holding
    three of them is one reusable band. Splitting it minted three preview-less, geometry-less
    "sections", each spending a fragment row and a slot of the mint cap, on the ordinary markup of
    every blog index there is."""
    cards = "".join(
        f'<article class="card"><h2>Post {name}</h2><p>Words.</p></article>'
        for name in ("one", "two", "three")
    )
    html = f"""
    <html><body><main>
      <section class="hero"><h1>Blog</h1></section>
      <div class="posts">{cards}</div>
    </main></body></html>
    """
    result = segment_page(html, page_url="https://x.example/")

    assert [section.tag for section in result.sections] == ["section", "div"]
    assert [d for d in result.diagnostics if d["code"] == COMPOUND_BAND_SPLIT_CODE] == []


def test_a_wrapper_holding_a_header_and_a_footer_is_one_band_with_a_top_and_a_bottom():
    """The other two tags ruling R20-2 excludes. `<header>`/`<footer>` are not sectioning content
    in the standard at all — they are the banner/contentinfo landmarks, and inside anything else
    they are that thing's own header. Two of them in a wrapper is one band, not two sections."""
    html = """
    <html><body><main>
      <section class="hero"><h1>Home</h1></section>
      <div class="panel">
        <header class="panel-top"><h2>Plans</h2></header>
        <footer class="panel-foot"><p>Terms apply.</p></footer>
      </div>
    </main></body></html>
    """
    result = segment_page(html, page_url="https://x.example/")

    assert [section.tag for section in result.sections] == ["section", "div"]
    assert [d for d in result.diagnostics if d["code"] == COMPOUND_BAND_SPLIT_CODE] == []


def test_a_wrapper_with_copy_of_its_own_is_not_split_out_from_under_it():
    """A heading or a line between the sections belongs to the WRAPPER, and the parts would leave
    it behind — which is content loss, not finer segmentation."""
    html = """
    <html><body><main>
      <div class="group">
        What our customers say
        <section class="a"><h2>Testimonials</h2><p>One.</p></section>
        <section class="b"><h2>Reviews</h2><p>Two.</p></section>
      </div>
      <section class="tail"><h2>Tail</h2><p>Tail.</p></section>
    </main></body></html>
    """
    result = segment_page(html, page_url="https://x.example/")
    assert [section.tag for section in result.sections] == ["div", "section"]
    assert [d for d in result.diagnostics if d["code"] == COMPOUND_BAND_SPLIT_CODE] == []


def test_a_wrapper_holding_one_stray_div_beside_its_sections_is_not_split():
    """One `<div>` among them means the wrapper holds something besides sections, and splitting
    would orphan it."""
    html = """
    <html><body><main>
      <div class="group">
        <section class="a"><h2>Testimonials</h2><p>One.</p></section>
        <div class="promo"><p>A banner nobody declared a section.</p></div>
        <section class="b"><h2>Reviews</h2><p>Two.</p></section>
      </div>
      <section class="tail"><h2>Tail</h2><p>Tail.</p></section>
    </main></body></html>
    """
    result = segment_page(html, page_url="https://x.example/")
    assert [section.tag for section in result.sections] == ["div", "section"]
    assert [d for d in result.diagnostics if d["code"] == COMPOUND_BAND_SPLIT_CODE] == []


def test_a_wrapper_around_a_single_section_is_a_wrapper_not_a_group():
    html = """
    <html><body><main>
      <div class="group"><section class="a"><h2>Testimonials</h2><p>One.</p></section></div>
      <section class="tail"><h2>Tail</h2><p>Tail.</p></section>
    </main></body></html>
    """
    result = segment_page(html, page_url="https://x.example/")
    assert [section.tag for section in result.sections] == ["div", "section"]
    assert [d for d in result.diagnostics if d["code"] == COMPOUND_BAND_SPLIT_CODE] == []


def test_a_compound_band_is_not_split_when_the_extents_are_a_running_sum():
    """`_assign_geometry` reconstructs tops by accumulating the bound heights when the capture
    recorded none, which is only true while the bound set is the whole measured sequence.
    Dropping a bound wrapper out of it would move every section below it up by 2,286px and report
    the result as geometry. Refuse the split and say why."""
    html = """
    <html><body><main>
      <div class="overflow-hidden">
        <section class="a"><h2>Testimonials</h2><p>One.</p></section>
        <section class="b"><h2>Reviews</h2><p>Two.</p></section>
      </div>
      <section class="tail"><h2>Tail</h2><p>Tail.</p></section>
    </main></body></html>
    """
    bands = [
        {"index": 0, "tag": "div", "classes": "overflow-hidden", "height": 2286.78},
        {"index": 1, "tag": "section", "classes": "tail", "height": 400.0},
    ]
    result = segment_page(
        html,
        page_url="https://x.example/",
        bands=measured_bands({SNAPSHOT_META_BANDS_KEY: bands}),
    )
    assert [section.tag for section in result.sections] == ["div", "section"]
    withheld = [d for d in result.diagnostics if d["code"] == COMPOUND_BAND_SPLIT_CODE]
    assert len(withheld) == 1
    assert withheld[0]["reason"] == "estimated_geometry"
    assert withheld[0]["parts"] == 0
    # The tail is still where the running sum puts it, which is the whole point of refusing.
    assert result.sections[1].geometry.top_px == 2286.78


def test_a_part_of_a_compound_band_is_never_called_hidden_for_having_no_band():
    """A part was never a CHILD of the measured root, so the browser was never offered it. Its
    silence is not the "the browser looked and saw nothing" evidence that makes a section dormant
    — and a part that carries a stray hidden-ish class would otherwise be parked dormant on it."""
    html = """
    <html><body><main>
      <section class="hero"><h1>Care</h1></section>
      <div class="overflow-hidden">
        <section class="section hide"><h2>Testimonials</h2><p>One.</p></section>
        <section class="section"><h2>Reviews</h2><p>Two.</p></section>
      </div>
    </main></body></html>
    """
    bands = [
        {"index": 0, "tag": "section", "classes": "hero", "top": 0.0, "height": 900.0},
        {"index": 1, "tag": "div", "classes": "overflow-hidden", "top": 900.0, "height": 800.0},
    ]
    result = segment_page(
        html,
        page_url="https://x.example/",
        bands=measured_bands({SNAPSHOT_META_BANDS_KEY: bands}),
    )
    assert [section.heading for section in result.sections] == [
        "Care",
        "Testimonials",
        "Reviews",
    ]
    assert result.hidden_sections == ()


# --------------------------------------------------------------------------- #
# F3.4 — the section's own heading, read as the label the author put on it
# --------------------------------------------------------------------------- #


def test_a_section_headed_testimonials_is_called_one():
    """Measured on the F2 re-walk's insighthealth capture: `<section class="section">` with
    `<h2>Testimonials</h2>` came out `other` at 0.30. The class list said nothing and the role
    caller never read the word the page puts at the top of the section."""
    html = (
        '<html><body><main><section class="hero"><h1>Care</h1></section>'
        '<section class="section"><h2>Testimonials</h2>'
        "<p>Real results from real clinicians.</p></section></main></body></html>"
    )
    result = segment_page(html, page_url="https://x.example/")
    assert result.sections[1].role == "testimonial"
    assert result.sections[1].confidence >= 0.70
    assert any(
        evidence.signal == "heading" and evidence.role == "testimonial"
        for evidence in result.sections[1].evidence
    )


def test_a_hint_word_inside_a_sentence_headline_is_not_a_label():
    """`Trusted by the world's best teams` is a hero's MESSAGE. Reading `trusted` out of it would
    hand the page's hero to `proof` — which is why the rule reads only a heading short enough to
    be a label."""
    html = (
        '<html><body><main><section class="hero">'
        "<h1>Trusted by the world's best engineering teams</h1>"
        "<p>Start building today.</p></section>"
        '<section class="tail"><h2>Tail</h2><p>Tail.</p></section></main></body></html>'
    )
    result = segment_page(html, page_url="https://x.example/")
    assert result.sections[0].role == "hero"
    assert not any(evidence.signal == "heading" for evidence in result.sections[0].evidence)


def test_a_heading_never_outranks_the_class_name_the_author_wrote():
    """A class token is machinery written for a machine; a heading is prose and may be a pun. So
    the same word is worth one step less in a heading, and the declaration wins the argument."""
    html = (
        '<html><body><main><section class="hero"><h1>Care</h1></section>'
        '<section class="testimonials"><h2>Security</h2>'
        "<p>What our customers say about us.</p></section></main></body></html>"
    )
    result = segment_page(html, page_url="https://x.example/")
    assert result.sections[1].role == "testimonial"


def test_a_hidden_section_is_named_from_its_heading_too():
    """`_call_hidden_roles` reads the same declarations and content the visible caller does; a
    dormant section a human is deciding about needs its name as much as a shown one."""
    html = (
        '<html><body><main><section class="a"><h1>Care</h1></section>'
        '<section class="b" style="display:none"><h2>Reviews</h2>'
        "<p>What people said.</p></section></main></body></html>"
    )
    result = segment_page(html, page_url="https://x.example/")
    assert [section.role for section in result.hidden_sections] == ["testimonial"]


# --------------------------------------------------------------------------- #
# F3.4 fix round — R20-1: a heading may promote or re-name, never UNNAME
# --------------------------------------------------------------------------- #


def _second_section(class_names: str, heading: str, copy: str = "Words about it.") -> str:
    return (
        '<html><body><main><section class="hero_wrap"><h1>Ship faster</h1></section>'
        f'<section class="{class_names}"><h2>{heading}</h2><p>{copy}</p></section>'
        "</main></body></html>"
    )


def _role_of_second(html: str):
    section = segment_page(html, page_url="https://x.example/").sections[1]
    return section.role, section.confidence


def test_a_heading_never_turns_a_named_section_into_other() -> None:
    """The reviewer's live repro. A `stats-band` proof strip headed "Customer reviews" resolved
    proof@0.60 → other@0.30: the heading created a contest that did not exist, and a contest
    resolves to `other`. That is the exact failure the heading signal was added to REDUCE,
    running backwards."""
    role, confidence = _role_of_second(_second_section("stats-band", "Customer reviews"))
    assert role != "other"
    assert confidence >= WEAK_HINT_WEIGHT


def test_a_heading_that_contests_a_stronger_declaration_leaves_the_declaration_standing() -> None:
    """The sub-rung case, where the margin genuinely does catch a tie: two heading tokens
    corroborate to 0.75 against a strong class token at 0.80. Without the guard this is `other`;
    with it the class name — the thing the author wrote for a machine — stands, and the evidence
    says the heading argued otherwise."""
    html = _second_section("compliance-band", "Reviews quotes")
    role, confidence = _role_of_second(html)

    assert (role, confidence) == ("security", STRONG_HINT_WEIGHT)
    section = segment_page(html, page_url="https://x.example/").sections[1]
    (note,) = [item for item in section.evidence if item.signal == "resolution"]
    assert "the heading argued for testimonial" in note.detail
    assert "never unnames a section" in note.detail


def test_a_contest_the_declarations_would_have_had_anyway_still_resolves_to_other() -> None:
    """The guard is narrow on purpose: it rescues a contest the HEADING created, not every
    contest. Two class tokens a half-rung apart still refuse to be broken."""
    role, _confidence = _role_of_second(
        _second_section("stats-band story-block", "Ship faster today")
    )
    assert role == "other"


# --- the contest margin itself: both sides, exactly ----------------------------------------- #


def test_one_whole_rung_of_the_weight_ladder_is_decisive_at_both_ends() -> None:
    """The boundary used to be decided by floating-point luck, in opposite directions for the
    same nominal gap: `0.80 - 0.10` is 0.7000000000000001 so a strong class token beat a heading
    outright, while `0.70 - 0.10` is 0.5999999999999999 so a heading was tied by a weak one. Same
    one-rung gap, two answers. It is now one rule, and the rule is that a whole rung decides —
    the ladder exists so that "inference never outranks a declaration" means something, and if
    one rung were a tie it would mean nothing."""
    assert not _within_contest_margin(STRONG_HINT_WEIGHT, HEADLINE_WEIGHT)
    assert not _within_contest_margin(HEADLINE_WEIGHT, WEAK_HINT_WEIGHT)
    assert not _within_contest_margin(WEAK_HINT_WEIGHT, POSITION_WEIGHT)
    # …and anything closer than a rung is still a tie, which is what the margin is for.
    assert _within_contest_margin(STRONG_HINT_WEIGHT, HEADLINE_WEIGHT + CORROBORATION_BONUS)
    assert _within_contest_margin(HEADLINE_WEIGHT, CONTENT_WEIGHT)
    assert _within_contest_margin(HEADLINE_WEIGHT, HEADLINE_WEIGHT)


@pytest.mark.parametrize(
    "leader, runner_up",
    [
        (STRONG_HINT_WEIGHT, HEADLINE_WEIGHT),
        (HEADLINE_WEIGHT, WEAK_HINT_WEIGHT),
        (WEAK_HINT_WEIGHT, POSITION_WEIGHT),
        (0.85, 0.75),
        (0.75, 0.65),
    ],
)
def test_the_margin_answers_the_same_way_whatever_the_operands_are(
    leader: float, runner_up: float
) -> None:
    """The property the float boundary did not have: a gap of exactly one margin gets one answer,
    for every pair of weights that produces it. A retune of any weight can no longer flip a whole
    class of sections to `other` with nothing noticing."""
    assert round(leader - runner_up, 6) == CONTEST_MARGIN
    assert _within_contest_margin(leader, runner_up) is False


def test_a_weaker_newly_named_band_never_steals_a_singular_role_from_a_stronger_claim():
    """The keeper of a singular role is the STRONGEST claim; position only breaks ties.

    (F3.4 fix round 2, finding N-1.) The strict contest margin can newly name an opening band
    — a page ``<h1>`` beside a ``<blockquote>`` resolves ``hero`` where it used to tie into
    ``other`` — and a first-wins-by-position enforcer then stripped the role from the FOLLOWING
    band whose author declared it (``class="hero-section"``, class-hint 0.80 > 0.75). The
    author's declaration is the stronger claim and keeps the name; the earlier band returns to
    ``other``.
    """
    html = """
    <html><body><main>
      <section class="intro-band">
        <h1>Care that keeps up</h1>
        <blockquote>It changed how our practice runs.</blockquote>
      </section>
      <section class="hero-section">
        <p>The platform neurology practices run on.</p>
        <a class="button" href="/demo">Book a demo</a>
      </section>
    </main></body></html>
    """
    result = segment_page(html, page_url="https://x.example/")
    roles = [section.role for section in result.sections]
    assert roles.count("hero") == 1, roles
    intro, declared = result.sections[0], result.sections[1]
    assert declared.role == "hero", roles
    assert intro.role != "hero", roles


def test_between_equal_singular_claims_the_positional_one_still_wins():
    """Ties keep the old rule: a page's first plausible hero is THE hero (F2.1 design)."""
    html = """
    <html><body><main>
      <section class="hero-section"><p>First.</p><a href="/a">Go</a></section>
      <section class="hero-section"><p>Second.</p><a href="/b">Go</a></section>
    </main></body></html>
    """
    result = segment_page(html, page_url="https://x.example/")
    roles = [section.role for section in result.sections]
    assert roles.count("hero") == 1, roles
    assert result.sections[0].role == "hero"
    assert result.sections[1].role != "hero"


def test_a_corroboration_bonus_never_overrides_position_between_equal_kinds_of_claim():
    """The keeper comparison is the strongest single RUNG, not the corroborated total.

    (F3.4 fix round 3, finding D-1.) Between two declarations of the same kind — two nav
    landmarks, two hero class-hints — a 0.05 corroboration bonus on the later one must not
    override "a page's nav and hero are its first". The strongest-claim rule (R20-5) compares
    kinds; corroboration seasons confidence, it does not change what KIND of claim was made.
    """
    hero_html = """
    <html><body><main>
      <section class="hero"><p>First hero.</p><a href="/demo">Go</a></section>
      <section class="hero-section banner"><p>Later, corroborated.</p><a href="/d">Go</a></section>
    </main></body></html>
    """
    result = segment_page(hero_html, page_url="https://x.example/")
    roles = [section.role for section in result.sections]
    assert roles.count("hero") == 1, roles
    # The FIRST class-hint hero keeps the role; the later band's extra vocabulary word is a
    # corroboration bonus, not a stronger kind of claim.
    assert result.sections[0].role == "hero", roles
    assert result.sections[1].role != "hero", roles

    nav_html = """
    <html><body>
      <nav><a href="/">Home</a><a href="/a">Product</a></nav>
      <main>
        <nav class="menu"><a href="/x">One</a><a href="/y">Two</a><a href="/z">Three</a></nav>
        <section class="hero"><p>Hero.</p><a href="/demo">Go</a></section>
      </main>
    </body></html>
    """
    result = segment_page(nav_html, page_url="https://x.example/")
    roles = [section.role for section in result.sections]
    assert roles.count("nav") == 1, roles
    # Both navs are landmark claims; the corroborated later one does not unseat the first.
    assert result.sections[0].role == "nav", roles
