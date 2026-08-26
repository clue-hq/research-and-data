"""Total asset slurp (clone-fidelity F0.2).

The clone harvest (Phase F2) rewrites a captured fragment's asset URLs onto OUR store, so
an asset the capture silently skipped becomes a broken image on a published page. This file
pins the three properties that make the asset side total and honest:

1. **Everything referenced is fetched.** One shared collector
   (:mod:`lumen_ingestion.capture.candidates`) enumerates every fetchable reference — ``<img>``
   src, every ``srcset`` rung, ``<picture><source>`` (dark ones tagged), CSS ``url()`` from
   inline styles and EVERY fetched stylesheet, inline-SVG ``<use>``/``<image>`` external refs,
   every ``@font-face`` src, and every rung the logo ladder scores — and that ONE list feeds
   both the fetch batch and the scorers.
2. **Budget, not caps.** The old hard caps (image candidates 50, CSS backgrounds 40) dropped
   assets in silence. They are replaced by one asset budget, and ANY drop is a loud
   ``LUMI0514`` naming the dropped URLs and the budget that tripped.
3. **No silent failures.** A referenced asset that arrives byteless, an ingest that refuses,
   and a ``@font-face`` file that failed to fetch each cost a diagnostic naming the URL and
   the reason — the ingestion still completes (honest-partial, never silent-partial).

Plus D-F2: a workspace-brand font family is stamped embeddable at emit, with the basis stated
honestly, and the publish gate accepts the stamp.
"""

from __future__ import annotations

import asyncio
import base64
import tempfile

import httpx
import pytest
from selectolax.parser import HTMLParser

from lumen_ingestion.capture import CaptureOutcome, build_evidence, capture_website
from lumen_ingestion.capture.budget import MAX_ASSET_BYTES, MAX_ASSET_COUNT
from lumen_ingestion.capture.candidates import AssetCandidate, collect_asset_candidates
from lumen_ingestion.capture.parse import parse_site
from lumen_ingestion.capture.snapshot import Stylesheet

BASE = "https://example.com/"

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
WOFF2 = b"wOF2" + b"\x00" * 60


def _noop(stage: str, progress: float) -> None:
    return None


# --------------------------------------------------------------------------- #
# The fixture page: one of every reference kind the brief enumerates.
# --------------------------------------------------------------------------- #

JSONLD = (
    '<script type="application/ld+json">'
    '{"@context":"https://schema.org","@type":"Organization","name":"Acme",'
    '"logo":"https://example.com/brand/jsonld-logo.svg"}'
    "</script>"
)

PAGE = (
    "<html><head><title>Acme</title>"
    '<link rel="stylesheet" href="/css/site.css">'
    + JSONLD
    + "</head><body>"
    '<header><img src="/brand/nav-logo.svg" alt="Acme logo" width="120" height="32"></header>'
    '<img src="/i/hero.png" srcset="/i/hero-400.png 400w, /i/hero-800.png 800w, '
    '/i/hero-1600.png 1600w" width="800" height="600">'
    "<picture>"
    '<source media="(prefers-color-scheme: dark)" srcset="/i/chart-dark.png 1200w">'
    '<source srcset="/i/chart-light.png 1200w">'
    '<img src="/i/chart.png" width="600" height="400">'
    "</picture>"
    '<svg viewBox="0 0 10 10">'
    '<use href="/brand/sprite.svg#mark"></use>'
    '<image href="/i/inline-bitmap.png"></image>'
    "</svg>"
    '<div style="background-image:url(/i/inline-bg.png)">'
    "<p>Acme builds honest infrastructure for teams that ship every single day.</p>"
    "</div>"
    "</body></html>"
)

CSS = (
    '@font-face{font-family:"Acme Sans";src:url(/fonts/acme-regular.woff2) '
    'format("woff2");font-weight:400;font-style:normal}'
    '@font-face{font-family:"Acme Sans";src:url(/fonts/acme-bold.woff2) '
    'format("woff2");font-weight:700;font-style:normal}'
    'body{background-image:url(/i/bg-gradient.png);color:#123456;'
    'font-family:"Acme Sans",sans-serif;font-size:16px}'
    ".masked{-webkit-mask-image:url(/i/mask.svg)}"
    'h1{font-family:"Acme Sans";font-size:48px;color:#123456}'
)

#: Every URL the fixture page references, absolutized. The acceptance criterion
#: "100% of referenced assets have bytes-or-loud-error" in miniature.
REFERENCED = {
    "https://example.com/brand/jsonld-logo.svg",
    "https://example.com/brand/nav-logo.svg",
    "https://example.com/i/hero.png",
    "https://example.com/i/hero-400.png",
    "https://example.com/i/hero-800.png",
    "https://example.com/i/hero-1600.png",
    "https://example.com/i/chart.png",
    "https://example.com/i/chart-dark.png",
    "https://example.com/i/chart-light.png",
    "https://example.com/brand/sprite.svg",
    "https://example.com/i/inline-bitmap.png",
    "https://example.com/i/inline-bg.png",
    "https://example.com/i/bg-gradient.png",
    "https://example.com/i/mask.svg",
    "https://example.com/fonts/acme-regular.woff2",
    "https://example.com/fonts/acme-bold.woff2",
}


def _handler_for(page_html: str, css: str, missing: set[str]):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        query = request.url.query.decode() if request.url.query else ""
        target = f"{path}?{query}" if query else path
        if target in missing or path in missing:
            return httpx.Response(404)
        if path in ("/", "/index.html"):
            return httpx.Response(200, html=page_html)
        if path.endswith(".css"):
            return httpx.Response(200, text=css)
        if path.endswith((".woff2", ".woff", ".ttf", ".otf")):
            return httpx.Response(
                200,
                content=WOFF2 + path.encode(),
                headers={"content-type": "font/woff2"},
            )
        if path.endswith(".svg"):
            return httpx.Response(
                200,
                text=f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 16">'
                f"<title>{path}</title><rect width='64' height='16'/></svg>",
                headers={"content-type": "image/svg+xml"},
            )
        # Every asset gets DISTINCT bytes: ingest is content-addressed, so a fixture that
        # served one shared 1x1 PNG would collapse the whole page into a single asset and
        # quietly hide whether each reference was really rehosted.
        return httpx.Response(
            200, content=PNG + path.encode(), headers={"content-type": "image/png"}
        )

    return handler


def _capture(
    *, page_html: str = PAGE, css: str = CSS, missing: set[str] | None = None
) -> CaptureOutcome:
    transport = httpx.MockTransport(_handler_for(page_html, css, missing or set()))

    async def run() -> CaptureOutcome:
        async with httpx.AsyncClient(transport=transport) as client:
            return await capture_website(
                BASE, reporter=_noop, render_available=False, http_client=client
            )

    return asyncio.run(asyncio.wait_for(run(), timeout=30.0))


class _StubCore:
    """``CoreClient.ingest_asset``-shaped stub.

    ``failing`` filenames get a not-ok RESPONSE (what ``raise_on_error=False`` produces);
    ``raising`` filenames RAISE (a dead helper, an unreachable store — which
    ``raise_on_error=False`` does not suppress).
    """

    def __init__(
        self, failing: set[str] | None = None, raising: set[str] | None = None
    ) -> None:
        self.calls: list[dict] = []
        self._failing = failing or set()
        self._raising = raising or set()

    def ingest_asset(self, **kwargs):
        self.calls.append(kwargs)
        name = kwargs.get("filename") or ""
        if any(token in name for token in self._raising):
            raise RuntimeError("helper.process died")
        if any(token in name for token in self._failing):
            return {"ok": False, "error": {"code": "asset.refused", "message": "boom"}}
        return {"ok": True, "asset": {"record": {"id": kwargs["asset_id"]}}}


def _evidence(outcome: CaptureOutcome, core: _StubCore | None = None):
    core = core or _StubCore()
    with tempfile.TemporaryDirectory() as store:
        evidence = build_evidence(
            outcome, core=core, store_root=store, reporter=_noop
        )
    return evidence, core


def _codes(outcome: CaptureOutcome) -> list[str]:
    return [d.get("code") for d in outcome.diagnostics]


# --------------------------------------------------------------------------- #
# 1 — everything scored is fetched
# --------------------------------------------------------------------------- #


def test_every_referenced_asset_is_fetched_or_loudly_reported() -> None:
    outcome = _capture()
    downloaded = {d.url for d in outcome.snapshot.downloads}
    loud = " ".join(str(d.get("message", "")) for d in outcome.diagnostics)

    for url in sorted(REFERENCED):
        assert url in downloaded or url in loud, f"{url} was neither fetched nor reported"


def test_the_collector_enumerates_every_reference_kind_with_its_origin() -> None:
    tree = HTMLParser(PAGE)
    harvest = collect_asset_candidates(
        tree, BASE, [Stylesheet(url="https://example.com/css/site.css", text=CSS)]
    )
    by_url = {c.url: c for c in harvest.candidates}

    assert isinstance(harvest.candidates[0], AssetCandidate)
    # a JSON-LD-declared logo the fetcher would never have seen from the DOM
    assert by_url["https://example.com/brand/jsonld-logo.svg"].origin == "logo-rung"
    # every srcset rung, not just the widest
    for rung in ("hero-400", "hero-800", "hero-1600"):
        assert by_url[f"https://example.com/i/{rung}.png"].origin == "srcset"
    # the <img>'s own src still rides
    assert by_url["https://example.com/i/hero.png"].origin in ("img", "srcset")
    # CSS url() from an EXTERNAL stylesheet, and a mask
    assert by_url["https://example.com/i/bg-gradient.png"].origin == "css-url"
    assert by_url["https://example.com/i/mask.svg"].origin == "css-url"
    # inline-SVG external references, fragment stripped
    assert by_url["https://example.com/brand/sprite.svg"].origin == "svg-ref"
    assert by_url["https://example.com/i/inline-bitmap.png"].origin == "svg-ref"
    # both @font-face files
    assert by_url["https://example.com/fonts/acme-regular.woff2"].origin == "font"
    assert by_url["https://example.com/fonts/acme-bold.woff2"].kind == "font"


def test_the_collector_is_the_one_list_the_fetcher_walks() -> None:
    """Structural pin: the scorer must never rank a URL the fetcher never saw."""
    from lumen_ingestion.capture import candidates, static

    assert static.collect_asset_candidates is candidates.collect_asset_candidates


# --------------------------------------------------------------------------- #
# 2 — budget, not caps
# --------------------------------------------------------------------------- #


def test_an_ordinary_marketing_page_drops_nothing() -> None:
    outcome = _capture()
    assert "LUMI0514" not in _codes(outcome)


def test_the_count_budget_names_the_dropped_urls_and_the_budget_that_tripped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lumen_ingestion.capture import candidates as candidates_module

    monkeypatch.setattr(candidates_module, "MAX_ASSET_COUNT", 4)
    tree = HTMLParser(PAGE)
    harvest = collect_asset_candidates(
        tree, BASE, [Stylesheet(url="https://example.com/css/site.css", text=CSS)]
    )

    assert len(harvest.candidates) == 4
    drops = [d for d in harvest.diagnostics if d["code"] == "LUMI0514"]
    assert len(drops) == 1
    message = drops[0]["message"]
    assert "asset count" in message and "4" in message
    assert drops[0]["dropped"], "the diagnostic must name what it dropped"
    assert drops[0]["dropped"][0].startswith("https://example.com/")


def test_the_budget_defaults_are_generous_enough_that_a_real_page_never_trips_them() -> None:
    assert MAX_ASSET_COUNT >= 400
    assert MAX_ASSET_BYTES >= 100 * 1024 * 1024


# --------------------------------------------------------------------------- #
# 3 — no silent failures
# --------------------------------------------------------------------------- #


def test_an_image_that_arrived_byteless_is_a_diagnostic_not_a_silent_drop() -> None:
    """RED CASE: the old ``queue()`` returned ``None`` and the caller said ``continue``."""
    page = PAGE.replace(
        "<p>Acme builds",
        '<img src="/i/orphan.png" width="600" height="400"><p>Acme builds',
    )
    outcome = _capture(page_html=page, missing={"/i/orphan.png"})
    _evidence(outcome)

    drops = [d for d in outcome.diagnostics if d["code"] == "LUMI0515"]
    assert drops, _codes(outcome)
    assert any("orphan.png" in d["message"] for d in drops)
    assert all(d["severity"] == "warning" for d in drops)


def test_an_ingest_failure_is_loud_and_the_evidence_is_still_produced() -> None:
    outcome = _capture()
    evidence, core = _evidence(outcome, _StubCore(failing={"nav-logo"}))

    assert evidence.colors, "the ingestion still completes — honest-partial"
    refused = [
        d
        for d in outcome.diagnostics
        if d["code"] == "LUMI0515" and "nav-logo" in d["message"]
    ]
    assert refused, _codes(outcome)
    assert "boom" in refused[0]["message"]


def test_an_ingest_that_raises_costs_one_asset_not_the_whole_kit() -> None:
    """``raise_on_error=False`` suppresses a refusal, not a dead helper.

    With every captured asset now rehosted, one raising ingest used to escape the gather and
    take the human's entire brand kit with it.
    """
    outcome = _capture()
    evidence, _ = _evidence(outcome, _StubCore(raising={"hero-1600"}))

    assert evidence.colors and evidence.fonts
    failed = [
        d
        for d in outcome.diagnostics
        if d["code"] == "LUMI0515" and "hero-1600" in d["message"]
    ]
    assert failed, _codes(outcome)
    assert "helper.process died" in failed[0]["reason"]


def test_a_font_face_that_failed_to_fetch_gets_its_own_diagnostic() -> None:
    outcome = _capture(missing={"/fonts/acme-bold.woff2"})
    evidence, core = _evidence(outcome)

    per_face = [d for d in outcome.diagnostics if d["code"] == "LUMI0516"]
    assert len(per_face) == 1, _codes(outcome)
    assert "acme-bold.woff2" in per_face[0]["message"]
    assert per_face[0]["reason"], "the diagnostic must name why"

    # the healthy face still ingested
    families = {f.family: f for f in evidence.fonts}
    faces = families["Acme Sans"].faces
    assert any(face.asset_id for face in faces)
    assert any(face.asset_id is None for face in faces)


# --------------------------------------------------------------------------- #
# 4 — provenance-preserving stored names
# --------------------------------------------------------------------------- #


def test_stored_filenames_carry_the_slurp_provenance_shape() -> None:
    outcome = _capture()
    _evidence(outcome, core := _StubCore())

    names = [call["filename"] for call in core.calls]
    assert names, "nothing was ingested"
    for name in names:
        assert name.startswith("slurp-"), name
        prefix, sha12, basename = name.split("-", 2)
        assert len(sha12) == 12 and all(c in "0123456789abcdef" for c in sha12), name
        assert basename, name

    assert any(name.endswith("-acme-regular.woff2") for name in names), names
    assert any(name.endswith("-nav-logo.svg") for name in names), names
    # the asset id is untouched — content-addressed, 16 hex chars
    for call in core.calls:
        assert call["asset_id"].startswith("asset_ing_")
        assert len(call["asset_id"]) == len("asset_ing_") + 16


# --------------------------------------------------------------------------- #
# 5 — the dark-scheme tag survives into evidence
# --------------------------------------------------------------------------- #


def test_a_prefers_color_scheme_dark_source_is_tagged_all_the_way_to_evidence() -> None:
    outcome = _capture()

    dark = [d for d in outcome.snapshot.downloads if d.url.endswith("/chart-dark.png")]
    assert dark and dark[0].dark_scheme is True
    light = [d for d in outcome.snapshot.downloads if d.url.endswith("/chart-light.png")]
    assert light and light[0].dark_scheme is False

    parsed = parse_site(outcome.snapshot)
    dark_assets = [a for a in parsed.images if a.source_url.endswith("chart-dark.png")]
    assert dark_assets, [a.source_url for a in parsed.images]
    assert "prefers-color-scheme: dark" in dark_assets[0].locator

    # …and all the way onto the evidence a human (and F2) reads.
    evidence, _ = _evidence(outcome)
    dark_pointers = [
        image.pointer.locator
        for image in evidence.images
        if "prefers-color-scheme: dark" in (image.pointer.locator or "")
    ]
    assert dark_pointers, [image.pointer.locator for image in evidence.images]


# --------------------------------------------------------------------------- #
# 6 — D-F2 font stamping at emit
# --------------------------------------------------------------------------- #


def _kit_font_license(license_hint: str | None = "Acme Sans (site webfont)") -> dict:
    from lumen_ingestion import normalize_evidence

    outcome = _capture()
    evidence, _ = _evidence(outcome)
    assert evidence.fonts
    evidence.fonts[0].license_hint = license_hint
    result = normalize_evidence(
        evidence,
        brand_kit_id="brand_kit_test",
        name="Acme",
        created_at="2026-08-27",
        version=1,
    )
    fonts = result.brand_kit["assets"]["fonts"]
    entry = next(
        font for font in fonts.values() if font["family"] == evidence.fonts[0].family
    )
    return entry["license"]


def test_a_workspace_brand_font_is_stamped_embeddable_with_an_honest_basis() -> None:
    license_obj = _kit_font_license()

    assert license_obj["embeddable"] is True
    assert license_obj["subsettable"] is False
    # the NAME stays honest — never a fabricated "OFL"
    assert license_obj["name"] == "Acme Sans (site webfont)"
    assert "OFL" not in license_obj["name"]
    restrictions = " ".join(license_obj["restrictions"])
    assert "platform-terms" in restrictions
    assert "confirm" in restrictions.lower()


def test_an_unknown_license_hint_still_reads_unknown() -> None:
    assert _kit_font_license(None)["name"] == "unknown"


def test_the_publish_gate_accepts_the_stamp_and_still_refuses_an_unstamped_family() -> None:
    from lumen_api.web_export import _family_embeddable

    assert _family_embeddable(_kit_font_license()) is True
    assert (
        _family_embeddable(
            {
                "name": "Locked Display",
                "embeddable": False,
                "subsettable": False,
                "restrictions": [],
            }
        )
        is False
    )
