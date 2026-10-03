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

from lumen_api.core import CoreClient
from lumen_ingestion.capture import CaptureOutcome, build_evidence, capture_website
from lumen_ingestion.capture.budget import MAX_ASSET_BYTES, MAX_ASSET_COUNT
from lumen_ingestion.capture.candidates import AssetCandidate, collect_asset_candidates
from lumen_ingestion.capture.parse import parse_site
from lumen_ingestion.capture.snapshot import Stylesheet
from lumen_ingestion.normalizer.emit import PLATFORM_TERMS_BASIS

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
    # The :root token is what keeps `evidence.colors` non-empty as the tests'
    # "pipeline still completed" sentinel: since the Phase-1 brand-color
    # overhaul (2026-08-30), rule-text colors like `color:#123456` are no
    # longer palette evidence — token declarations are the naming layer that
    # survives.
    ":root{--brand:#123456}"
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


def test_a_data_uri_image_is_not_a_missing_asset() -> None:
    """RED CASE (fix round 1, I1): the inline bytes ARE the asset.

    A ``data:`` URI is not fetchable and needs no rehosting — the bytes already ride in the
    HTML the snapshot carries. Reporting it as "not stored" was a false positive, and because
    the diagnostic quoted the URL, a Webflow/Next LQIP placeholder dragged ~2 KB of base64 per
    image into the published kit's diagnostics.
    """
    placeholder = (
        "data:image/svg+xml;base64,"
        + base64.b64encode(b"<svg xmlns='http://www.w3.org/2000/svg'/>" * 40).decode()
    )
    page = PAGE.replace(
        "<p>Acme builds",
        f'<img src="{placeholder}" width="600" height="400"><p>Acme builds',
    )
    outcome = _capture(page_html=page)
    _evidence(outcome)

    drops = [d for d in outcome.diagnostics if d["code"] == "LUMI0515"]
    assert not any("data:" in d["message"] for d in drops), drops
    assert all(len(d["message"]) < 600 for d in outcome.diagnostics), [
        (d["code"], len(d["message"])) for d in outcome.diagnostics
    ]


def test_a_very_long_url_is_truncated_in_the_diagnostic_it_appears_in() -> None:
    """No diagnostic may carry an unbounded URL into the kit (fix round 1, I1)."""
    long_path = "/i/" + ("x" * 400) + ".png"
    page = PAGE.replace(
        "<p>Acme builds",
        f'<img src="{long_path}" width="600" height="400"><p>Acme builds',
    )
    outcome = _capture(page_html=page, missing={long_path})
    _evidence(outcome)

    drops = [d for d in outcome.diagnostics if d["code"] == "LUMI0515"]
    named = [d for d in drops if "xxxx" in d["message"]]
    assert named, drops
    assert "…" in named[0]["message"]
    assert len(named[0]["message"]) < 400
    # the structured key keeps the WHOLE url — truncation is for the human line only
    assert named[0]["url"].endswith(".png") and len(named[0]["url"]) > 400


def test_missing_asset_diagnostics_are_capped_and_then_summarized() -> None:
    """RED CASE (fix round 1, I3): one diagnostic per drop was unbounded.

    A page that trips the budget re-emitted its whole dropped tail as N diagnostics on top of
    the LUMI0514 that already named them.
    """
    from lumen_ingestion.capture.budget import MAX_NAMED_DROPS

    count = MAX_NAMED_DROPS + 7
    extra = "".join(
        f'<img src="/i/gone{i}.png" width="600" height="400">' for i in range(count)
    )
    page = PAGE.replace("<p>Acme builds", extra + "<p>Acme builds")
    outcome = _capture(
        page_html=page, missing={f"/i/gone{i}.png" for i in range(count)}
    )
    _evidence(outcome)

    drops = [d for d in outcome.diagnostics if d["code"] == "LUMI0515"]
    named = [d for d in drops if d.get("url")]
    summary = [d for d in drops if not d.get("url")]
    assert len(named) == MAX_NAMED_DROPS, len(named)
    assert len(summary) == 1
    assert f"{7} more" in summary[0]["message"]
    # the full list is NOT persisted into the kit's diagnostics
    assert all("dropped" not in d for d in drops)


def test_the_byte_budget_drops_and_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    """The other half of the budget: what the snapshot may CARRY (fix round 1 test gap)."""
    from lumen_ingestion.capture import static as static_module

    monkeypatch.setattr(static_module, "MAX_ASSET_BYTES", 400)
    outcome = _capture()

    over = [d for d in outcome.diagnostics if d["code"] == "LUMI0514"]
    assert len(over) == 1, _codes(outcome)
    assert over[0]["budget"] == "asset bytes"
    assert over[0]["limit"] == 400
    assert over[0]["dropped"]
    # what DID fit is still under the budget
    kept = sum(len(base64.b64decode(d.bytes_b64)) for d in outcome.snapshot.downloads)
    assert kept <= 400


def test_a_budget_message_names_a_bounded_number_of_urls() -> None:
    from lumen_ingestion.capture.budget import _NAMED_IN_MESSAGE, budget_diagnostic

    dropped = [f"https://example.com/i/{i}.png" for i in range(_NAMED_IN_MESSAGE + 5)]
    diagnostic = budget_diagnostic(budget="asset count", limit=3, dropped=dropped)

    assert diagnostic["message"].count("https://") == _NAMED_IN_MESSAGE
    assert "and 5 more" in diagnostic["message"]
    assert len(diagnostic["dropped"]) == len(dropped)


# --------------------------------------------------------------------------- #
# @font-face: EVERY src rung is fetched and rehosted (fix round 1, I2)
# --------------------------------------------------------------------------- #

MULTI_RUNG_CSS = (
    '@font-face{font-family:"Acme Sans";'
    'src:url(/fonts/acme-regular.woff2) format("woff2"),'
    'url(/fonts/acme-regular.woff) format("woff"),'
    'url(/fonts/acme-regular.ttf) format("truetype");'
    "font-weight:400;font-style:normal}"
    'body{color:#123456;font-family:"Acme Sans",sans-serif;font-size:16px}'
    'h1{font-family:"Acme Sans";font-size:48px;color:#123456}'
)


def test_every_font_face_src_rung_is_fetched_not_just_the_best_format() -> None:
    """F2 rewrites a captured ``@font-face`` block verbatim, so every rung a browser might
    pick has to resolve on our store — the same defect class as the srcset rungs."""
    outcome = _capture(css=MULTI_RUNG_CSS)
    downloaded = {d.url for d in outcome.snapshot.downloads}

    for extension in ("woff2", "woff", "ttf"):
        assert f"https://example.com/fonts/acme-regular.{extension}" in downloaded, (
            extension,
            sorted(downloaded),
        )

    evidence, core = _evidence(outcome)
    # the kit still BINDS the best format
    face = next(f for f in evidence.fonts if f.family == "Acme Sans").faces[0]
    assert face.source_url.endswith(".woff2")
    # …and every rung is rehosted
    names = [call["filename"] for call in core.calls]
    for extension in ("woff2", "woff", "ttf"):
        assert any(name.endswith(f"-acme-regular.{extension}") for name in names), (
            extension,
            names,
        )


def test_a_failed_font_rung_is_reported_even_when_the_bound_rung_is_fine() -> None:
    outcome = _capture(css=MULTI_RUNG_CSS, missing={"/fonts/acme-regular.woff"})
    evidence, _ = _evidence(outcome)

    per_rung = [d for d in outcome.diagnostics if d["code"] == "LUMI0516"]
    assert len(per_rung) == 1, _codes(outcome)
    assert "acme-regular.woff" in per_rung[0]["message"]
    assert per_rung[0]["reason"]
    # `bound` is declared contract surface for Task 3 / F2: it tells "the kit's font is dead"
    # apart from "one alternative format is missing". This failure is the latter.
    assert per_rung[0]["bound"] is False

    face = next(f for f in evidence.fonts if f.family == "Acme Sans").faces[0]
    assert face.asset_id is not None, "the bound rung is fine and must still paint"


def test_a_base64_inlined_font_face_is_not_a_missing_file() -> None:
    """RED CASE (fix round 2, R2-1): the same data-URI blind spot, on the font path.

    A brand that inlines its webfont as base64 in the CSS holds the bytes in the CSS. The
    rung loop treated it as a rung that never arrived — a false-positive LUMI0516 whose
    structured ``url`` carried the whole multi-KB URI onto the published kit — and, because
    the inlined rung is also the BOUND one, a LUMI0231 whose message interpolated it verbatim.
    """
    inline_font = "data:font/woff2;base64," + base64.b64encode(b"wOF2" * 900).decode()
    css = (
        '@font-face{font-family:"Inline Sans";'
        f'src:url({inline_font}) format("woff2");'
        "font-weight:400;font-style:normal}"
        'body{color:#123456;font-family:"Inline Sans",sans-serif;font-size:16px}'
        'h1{font-family:"Inline Sans";font-size:48px;color:#123456}'
    )
    outcome = _capture(css=css)
    _evidence(outcome)

    assert not [d for d in outcome.diagnostics if d["code"] == "LUMI0516"], [
        d for d in outcome.diagnostics if d["code"] == "LUMI0516"
    ]
    for diagnostic in outcome.diagnostics:
        # Nothing may carry the URI's payload onto the kit — not a message, not a key.
        assert len(diagnostic["message"]) < 800, (
            diagnostic["code"],
            len(diagnostic["message"]),
        )
        assert "base64," not in str(diagnostic.get("url") or "")

    # LUMI0231 DOES still fire, and should: the engine loads a face by asset id, and an
    # inlined face has none, so it genuinely cannot paint. That is an honest finding, not a
    # false positive — it just has to say so in a bounded line.
    uncustodied = [d for d in outcome.diagnostics if d["code"] == "LUMI0231"]
    assert len(uncustodied) == 1
    assert "Inline Sans" in uncustodied[0]["message"]
    assert "chars)" in uncustodied[0]["message"], "the URI must be visibly truncated"


def test_font_rung_failures_are_capped_and_then_summarized() -> None:
    """RED CASE (fix round 2, R2-2): per-rung LUMI0516 multiplied volume by 3.

    A down font host used to mean one persisted warning per rung per face, unbounded.
    """
    from lumen_ingestion.capture.budget import MAX_NAMED_DROPS

    faces = 9  # 9 faces x 3 rungs = 27 dead rungs, comfortably over the cap
    css = "".join(
        '@font-face{font-family:"Dead Sans";'
        f"src:url(/fonts/dead-{i}.woff2) format(\"woff2\"),"
        f'url(/fonts/dead-{i}.woff) format("woff"),'
        f'url(/fonts/dead-{i}.ttf) format("truetype");'
        f"font-weight:{100 * (i + 1)};font-style:normal}}"
        for i in range(faces)
    ) + (
        'body{color:#123456;font-family:"Dead Sans",sans-serif;font-size:16px}'
        'h1{font-family:"Dead Sans";font-size:48px;color:#123456}'
    )
    missing = {
        f"/fonts/dead-{i}.{ext}"
        for i in range(faces)
        for ext in ("woff2", "woff", "ttf")
    }
    outcome = _capture(css=css, missing=missing)
    _evidence(outcome)

    per_rung = [d for d in outcome.diagnostics if d["code"] == "LUMI0516"]
    named = [d for d in per_rung if d.get("url")]
    summary = [d for d in per_rung if not d.get("url")]
    assert len(named) == MAX_NAMED_DROPS, len(named)
    assert len(summary) == 1
    assert f"{faces * 3 - MAX_NAMED_DROPS} more" in summary[0]["message"]


def test_every_faces_bound_rung_outranks_every_alternate_in_the_fetch_order() -> None:
    """Fix round 2, R2-3: the budget drops a suffix, so bound rungs must ALL come first.

    Face-by-face emission meant a budget prefix could keep face 1's ``ttf`` alternate and
    drop face 9's bound ``woff2`` — the opposite of "the kit-bound file survives pressure".
    """
    from lumen_ingestion.capture.parse import font_face_source_rungs
    from lumen_ingestion.capture.snapshot import Stylesheet

    css = "".join(
        '@font-face{font-family:"Multi";'
        f"src:url(/f/{i}.woff2) format(\"woff2\"),url(/f/{i}.ttf) format(\"truetype\");"
        f"font-weight:{100 * (i + 1)}}}"
        for i in range(4)
    )
    rungs = font_face_source_rungs(
        [Stylesheet(url="https://example.com/a.css", text=css)], BASE
    )
    bound = [u for u in rungs if u.endswith(".woff2")]
    alternates = [u for u in rungs if u.endswith(".ttf")]
    assert len(bound) == 4 and len(alternates) == 4
    assert rungs[:4] == bound, rungs
    assert rungs[4:] == alternates, rungs


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
    # F1.5: the basis is its OWN field now (the Rust struct grew one), not a line smuggled
    # through `restrictions` because serde used to drop the unknown key.
    assert license_obj["basis"] == PLATFORM_TERMS_BASIS
    assert not any("basis:" in line for line in license_obj["restrictions"])
    # …and the human-readable caveat stays where a human reads it.
    restrictions = " ".join(license_obj["restrictions"])
    assert "confirm" in restrictions.lower()


def test_the_basis_survives_the_real_rust_brand_kit_round_trip() -> None:
    """The F0 ledger's deferred item, closed: pinned through the REAL engine.

    F0 could not put the basis in its own key because ``validate_brand_kit`` deserializes into
    the typed ``FontLicense`` and RE-SERIALIZES it — an unknown key never came back, and the
    pipeline persists what comes back. This drives the real helper over a real emitted kit, so
    the encoding is pinned where it actually broke rather than at the Python boundary.
    """
    from lumen_ingestion import normalize_evidence

    outcome = _capture()
    evidence, _ = _evidence(outcome)
    assert evidence.fonts
    evidence.fonts[0].license_hint = "Acme Sans (site webfont)"
    result = normalize_evidence(
        evidence,
        brand_kit_id="brand_kit_roundtrip",
        name="Acme",
        created_at="2026-08-27",
        version=1,
    )
    family = evidence.fonts[0].family

    validation = CoreClient().validate_brand_kit(
        result.brand_kit, product_ready=False, raise_on_error=False
    )
    returned = validation.get("brand_kit") or {}
    entry = next(
        font
        for font in returned["assets"]["fonts"].values()
        if font["family"] == family
    )
    assert entry["license"]["basis"] == PLATFORM_TERMS_BASIS
    assert entry["license"]["embeddable"] is True
    assert entry["license"]["name"] == "Acme Sans (site webfont)"


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


def test_the_publish_gate_reads_the_basis_field_and_refuses_nothing_new() -> None:
    """F1.5 obligation 2: the gate HONORS the basis, and its old refusals are untouched."""
    from lumen_api.web_export import _family_embeddable, font_license_basis

    stamped = {
        "name": "unknown",
        "embeddable": True,
        "subsettable": False,
        "basis": PLATFORM_TERMS_BASIS,
        "restrictions": [],
    }
    assert _family_embeddable(stamped) is True
    assert font_license_basis(stamped) == PLATFORM_TERMS_BASIS

    # An old kit with no basis at all still passes on `embeddable` alone…
    assert _family_embeddable({"name": "OFL-1.1", "embeddable": False}) is True
    assert font_license_basis({"name": "OFL-1.1", "embeddable": False}) is None
    # …and a basis can never talk a NON-embeddable family onto a published page.
    assert (
        _family_embeddable(
            {"name": "Locked Display", "embeddable": False, "basis": PLATFORM_TERMS_BASIS}
        )
        is False
    )


# --------------------------------------------------------------------------- #
# CSS url() escapes (F0 fix wave, FIX 1)
# --------------------------------------------------------------------------- #
#
# RED CASE, taken verbatim off the insighthealth.ai acceptance walk. Webflow escapes the
# parentheses a Designer-uploaded filename carries, so the hero's two background layers are
# declared as `…_Ellipse%202%20\(1\).png`. The unquoted branch of the url() regex used to be
# `[^)'"\s]+`, which stops dead at the backslash before the escaped `)` and never unescapes
# the `\(` either — every consumer then enumerated `…_Ellipse%202%20\(1\`, the CDN answered
# 403, and two real hero assets were lost behind a loud-but-wrong LUMI0503. There are three
# copies of this reading (candidates / imgsrc / the @font-face src in parse), so each is
# pinned here against the same declaration.

ESCAPED_PAREN_CSS = (
    ".aura-bg{background-image:"
    r"url(https://cdn.prod.website-files.com/68a/68b_Ellipse%202%20\(1\).png), "
    r"url(https://cdn.prod.website-files.com/68a/68b_Ellipse%202%20\(2\).png)"
    "}"
)
ESCAPED_PAREN_URLS = [
    "https://cdn.prod.website-files.com/68a/68b_Ellipse%202%20(1).png",
    "https://cdn.prod.website-files.com/68a/68b_Ellipse%202%20(2).png",
]

#: The quoted branch already handled parens — it is pinned so a fix to the unquoted branch
#: cannot regress it, and so the `\"` escape (which the old `[^"]*` DID stop at) is covered.
QUOTED_PAREN_CSS = (
    '.q{background-image:url("https://cdn.example.com/Ellipse (3).png")}'
    ".s{background-image:url('https://cdn.example.com/Ellipse (4).png')}"
    r'.e{background-image:url("https://cdn.example.com/say-\"hi\"-(5).png")}'
)
QUOTED_PAREN_URLS = [
    "https://cdn.example.com/Ellipse (3).png",
    "https://cdn.example.com/Ellipse (4).png",
    'https://cdn.example.com/say-"hi"-(5).png',
]


def _candidate_urls(css: str) -> list[str]:
    harvest = collect_asset_candidates(
        HTMLParser("<html><body></body></html>"),
        BASE,
        [Stylesheet(url="https://cdn.example.com/css/site.css", text=css)],
    )
    # The logo ladder contributes a default favicon rung for any page; these fixtures are
    # about the stylesheet, so only the CDN-hosted references are the subject.
    return [c.url for c in harvest.candidates if c.url.startswith("https://cdn.")]


def test_an_escaped_paren_in_an_unquoted_css_url_survives_the_collector() -> None:
    urls = _candidate_urls(ESCAPED_PAREN_CSS)
    assert urls == ESCAPED_PAREN_URLS, urls
    assert not any("\\" in url for url in urls), urls


def test_a_quoted_css_url_carrying_parens_and_escapes_survives_the_collector() -> None:
    assert _candidate_urls(QUOTED_PAREN_CSS) == QUOTED_PAREN_URLS


def test_an_escaped_paren_survives_the_background_image_reader() -> None:
    from lumen_ingestion.capture.imgsrc import background_image_urls

    assert (
        background_image_urls(
            HTMLParser("<html><body></body></html>"),
            [Stylesheet(url="https://cdn.example.com/css/site.css", text=ESCAPED_PAREN_CSS)],
            BASE,
        )
        == ESCAPED_PAREN_URLS
    )


def test_a_quoted_paren_url_survives_the_background_image_reader() -> None:
    from lumen_ingestion.capture.imgsrc import background_image_urls

    assert (
        background_image_urls(
            HTMLParser("<html><body></body></html>"),
            [Stylesheet(url="https://cdn.example.com/css/site.css", text=QUOTED_PAREN_CSS)],
            BASE,
        )
        == QUOTED_PAREN_URLS
    )


def test_an_escaped_paren_in_a_font_face_src_survives_the_font_walk() -> None:
    """The third copy: ``parse._parse_font_face``'s own ``src`` regex.

    A font URL is matched to its bytes by EXACT string, so a mangled one costs the face its
    ``asset_id`` and the whole kit falls back to Inter — the same failure the one-and-only
    ``iter_font_faces`` walk exists to prevent.
    """
    from lumen_ingestion.capture.parse import font_face_source_rungs

    css = (
        '@font-face{font-family:"Aura";'
        r"src:url(https://cdn.example.com/Aura%20\(1\).woff2) format(" '"woff2"),'
        '''url("https://cdn.example.com/Aura (2).woff") format("woff"),'''
        r"""url('https://cdn.example.com/Aura \(3\).ttf') format("truetype")}"""
    )
    rungs = font_face_source_rungs(
        [Stylesheet(url="https://cdn.example.com/css/site.css", text=css)], BASE
    )
    assert rungs == [
        "https://cdn.example.com/Aura%20(1).woff2",
        "https://cdn.example.com/Aura (2).woff",
        "https://cdn.example.com/Aura (3).ttf",
    ], rungs


def test_the_three_css_url_readers_are_one_shared_reader() -> None:
    """Structural pin: the regex existed in three copies and drifted. One home, three callers."""
    from lumen_ingestion.capture import candidates, cssurl, imgsrc, parse

    assert candidates.iter_css_urls is cssurl.iter_css_urls
    assert imgsrc.iter_css_urls is cssurl.iter_css_urls
    assert parse.iter_css_urls is cssurl.iter_css_urls


def test_the_shared_url_reader_handles_hex_escapes_and_an_uppercase_declaration() -> None:
    """Two smaller properties of the one reader, pinned directly.

    A CSS hex escape (``\\26`` = ``&``) is how a stylesheet minifier writes a URL that carries
    a character it would rather not emit literally, and ``URL(…)`` is legal CSS that both
    previous copies missed — the cheap ``"url(" in text.lower()`` guard in front of them was
    case-insensitive while the regex was not.
    """
    from lumen_ingestion.capture.cssurl import iter_css_urls, unescape_css

    assert unescape_css(r"a\26 b.png") == "a&b.png"
    assert unescape_css("plain.png") == "plain.png"
    assert list(iter_css_urls("URL(https://cdn.example.com/UP.png)")) == [
        "https://cdn.example.com/UP.png"
    ]


def test_ingest_failure_diagnostics_are_capped_and_then_summarized() -> None:
    """RED CASE (F0 fix wave, rider): the refused-ingest producer bypassed the cap.

    ``_drop_diagnostics`` and the font-rung failures both go through
    :func:`cap_and_summarize`; ``ingest_failures`` — the same ``LUMI0515`` code, the same
    per-item bulk failure mode (a store that is down refuses every asset on the page) — was
    extended onto the outcome raw, so one bad store made the published kit's diagnostics
    unbounded.
    """
    from lumen_ingestion.capture.budget import MAX_NAMED_DROPS

    count = MAX_NAMED_DROPS + 5
    extra = "".join(
        f'<img src="/i/refused{i}.png" width="600" height="400">' for i in range(count)
    )
    page = PAGE.replace("<p>Acme builds", extra + "<p>Acme builds")
    outcome = _capture(page_html=page)
    _evidence(outcome, _StubCore(failing={".png", ".svg", ".woff2"}))

    refused = [d for d in outcome.diagnostics if d["code"] == "LUMI0515"]
    named = [d for d in refused if d.get("url")]
    summary = [d for d in refused if not d.get("url")]
    assert len(named) == MAX_NAMED_DROPS, len(named)
    assert len(summary) == 1, summary
    assert summary[0]["context"] == "summary"
    assert "more" in summary[0]["message"]


def test_captured_video_is_not_sent_to_image_ingestion() -> None:
    import hashlib

    from lumen_ingestion.capture.snapshot import Download

    outcome = _capture()
    media = b"\x1a\x45\xdf\xa3original-background-video"
    outcome.snapshot.downloads.append(
        Download(
            url=BASE + "original-background.webm",
            kind="video",
            content_type="video/webm",
            bytes_b64=base64.b64encode(media).decode(),
            sha256=hashlib.sha256(media).hexdigest(),
            origin="video",
        )
    )
    _, core = _evidence(outcome)
    assert core.calls  # Images/fonts still go through their existing ingest path.
    assert not any("original-background" in call.get("filename", "") for call in core.calls)
