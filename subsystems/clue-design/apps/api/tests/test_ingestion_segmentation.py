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
