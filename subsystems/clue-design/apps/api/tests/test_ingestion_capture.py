from __future__ import annotations

import asyncio
import base64
import os
import tempfile
from pathlib import Path

import httpx
import pytest

from lumen_ingestion import normalize_evidence
from lumen_ingestion.capture import (
    CaptureError,
    CaptureOutcome,
    build_evidence,
    capture_website,
)
from lumen_ingestion.capture.net import BoundedFetcher, FetchRequest, guard_url
from lumen_ingestion.capture.parse import parse_color_value, parse_site
from lumen_ingestion.capture.quality_gate import evaluate
from lumen_ingestion.capture.snapshot import load_snapshot
from lumen_api.core import CoreClient

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ingestion" / "snapshots"


def _noop(stage: str, progress: float) -> None:
    return None


def load(name: str):
    return load_snapshot(FIXTURES / f"{name}.json")


# --------------------------------------------------------------------------- #
# Import hygiene
# --------------------------------------------------------------------------- #


def test_import_pulls_no_heavy_deps() -> None:
    # Must run in a fresh interpreter: the shared test-session sys.modules is
    # polluted by other tests (Pillow etc.), so a clean subprocess is the only
    # honest hygiene check.
    import subprocess
    import sys

    script = (
        "import sys, lumen_ingestion.capture as _; "
        "bad = [m for m in ('playwright','fitz','pymupdf','PIL') if m in sys.modules]; "
        "assert not bad, bad; print('clean')"
    )
    api_root = Path(__file__).resolve().parents[1]
    repo_root = Path(__file__).resolve().parents[3]
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(api_root), str(repo_root)])}
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(api_root),
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "clean" in result.stdout


def test_the_rendered_tier_imports_cleanly_in_a_worker_shaped_process() -> None:
    """The forced-render import chain must resolve in the process shape a FLEET WORKER has.

    The missing case (found live 2026-08-19): `lumen_ingestion.capture.rendered` and its
    `geometry` probe are imported LAZILY, deep inside `capture_website`, so nothing — not this
    suite, not process start-up — touched them until a rendered ingestion was already running.
    A design API whose `lumen_ingestion.evidence` was loaded before the geometry module existed
    therefore drained a forced-render job off the shared `design_job` queue and died 0.2s in
    with `ImportError: cannot import name 'GeometryEvidence' from 'lumen_ingestion.evidence'`,
    while the identical call succeeded in every fresh process. The root cause was a stale
    sibling process, not a code defect — but NOTHING in the suite executed that import edge, so
    a genuine circular import or a renamed symbol there would have shipped exactly as far.

    A fresh interpreter is the only honest context: the shared test session has already
    imported everything, so an in-process import proves nothing. The order mirrors the worker's
    (`lumen_api.main` first — that is what `fleet_handler._execute` imports — then the capture
    chain the job reaches later), and the identity assertions are what a half-old module graph
    fails: `capture.geometry`'s `GeometryEvidence` MUST be the very object
    `lumen_ingestion.evidence` defines.
    """
    import subprocess
    import sys

    script = (
        "import sys;"
        "import lumen_api.main;"  # the worker's entry module, imported first
        "from lumen_ingestion.pipeline import _default_capture;"
        "import lumen_ingestion.capture.rendered as rendered;"
        "import lumen_ingestion.capture.geometry as geometry;"
        "import lumen_ingestion.evidence as evidence;"
        "assert geometry.GeometryEvidence is evidence.GeometryEvidence;"
        "assert rendered.fetch_rendered is not None;"
        "assert callable(_default_capture);"
        # Rendering is now unconditional, so importing the rendered tier must stay as cheap as
        # importing the static one: playwright is still resolved inside `fetch_rendered`.
        "assert 'playwright' not in sys.modules;"
        "print('worker-import-ok')"
    )
    api_root = Path(__file__).resolve().parents[1]
    repo_root = Path(__file__).resolve().parents[3]
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(api_root), str(repo_root)])}
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(api_root),
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "worker-import-ok" in result.stdout


# --------------------------------------------------------------------------- #
# SSRF guard
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/",
        "http://127.0.0.1/",
        "http://10.0.0.5/",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/",
        "file:///etc/passwd",
        "ftp://example.com/x",
        "http://user:pass@example.com/",
        "http://example.com:22/",
    ],
)
def test_guard_url_rejects(url: str) -> None:
    with pytest.raises(CaptureError) as excinfo:
        asyncio.run(guard_url(url))
    assert excinfo.value.code == "LUMI0501"


def test_guard_url_accepts_public_https() -> None:
    # Uses real DNS; a stable public host that resolves to a routable address.
    assert asyncio.run(guard_url("https://example.com/")) == "https://example.com/"


# --------------------------------------------------------------------------- #
# Color parsing
# --------------------------------------------------------------------------- #


def test_parse_color_value_forms() -> None:
    props = {"--brand": "#12EAB1"}
    assert parse_color_value("#12eab1", props) == "#12EAB1"
    assert parse_color_value("#abc", props) == "#AABBCC"
    assert parse_color_value("rgb(0, 227, 225)", props) == "#00E3E1"
    assert parse_color_value("rgba(0,0,0,0.5)", props) == "#00000080"
    assert parse_color_value("var(--brand)", props) == "#12EAB1"
    assert parse_color_value("transparent", props) is None
    assert parse_color_value("currentColor", props) is None
    # hsl(0,100%,50%) == red
    assert parse_color_value("hsl(0, 100%, 50%)", props) == "#FF0000"


# --------------------------------------------------------------------------- #
# Parse: role hints, dark scope, var() resolution, rem→px, fonts, logos, images
# --------------------------------------------------------------------------- #


def test_parse_role_hints_and_dark_scope() -> None:
    parsed = parse_site(load("insight_static"))

    def find(value: str, hint: str, theme: str = "light"):
        return [
            c
            for c in parsed.colors
            if c.value == value and hint in c.role_hints and c.theme == theme
        ]

    page = find("#F5F5F5", "page-bg")
    assert page and any(c.weight == 5.0 for c in page)

    button = find("#12EAB1", "button-bg")
    assert button and any(c.weight == 4.0 for c in button)

    # dark prefers-color-scheme block colors carry theme="dark"
    dark = [c for c in parsed.colors if c.theme == "dark"]
    assert dark
    assert any(c.value == "#0B0B0C" and "page-bg" in c.role_hints for c in dark)

    # var() resolved against custom props
    assert any(
        c.value == "#12EAB1" and c.role_hints == ["custom-prop:--brand"]
        for c in parsed.colors
    )


def test_parse_type_samples_rem_to_px() -> None:
    parsed = parse_site(load("insight_static"))
    h1 = [t for t in parsed.type_samples if t.label == "h1"]
    body = [t for t in parsed.type_samples if t.label == "body"]
    assert h1 and h1[0].size_px == 48.0  # 3rem × 16
    assert h1[0].family == "Aeonik"
    assert body and body[0].size_px == 16.0  # 1rem × 16
    assert body[0].family == "Inter"


def test_parse_font_face_preference_and_license() -> None:
    parsed = parse_site(load("insight_static"))
    aeonik = [f for f in parsed.fonts if f.family == "Aeonik"]
    assert aeonik
    font = aeonik[0]
    assert font.license_hint == "trial-filename"
    # woff2 preferred over woff
    assert font.faces[0].format == "woff2"
    assert font.faces[0].source_url.endswith(".woff2")


def test_parse_logo_vs_og_image_split() -> None:
    parsed = parse_site(load("insight_static"))
    # header logo → primary; apple-touch-icon → mark; og:logo → primary
    usages = sorted(l.usage_hint for l in parsed.logos)
    assert "primary" in usages and "mark" in usages
    # og:image is an image with kind_hint og_image, never a logo
    assert any(i.kind_hint == "og_image" for i in parsed.images)
    assert not any(
        l.source_url and l.source_url.endswith("og-cover.png") for l in parsed.logos
    )


def test_parse_computed_samples_rendered() -> None:
    parsed = parse_site(load("insight_rendered"))
    # rendered computed samples produce area-weighted colors with the same hints
    body_bg = [
        c
        for c in parsed.colors
        if c.value == "#F5F5F5" and "page-bg" in c.role_hints and c.weight > 5.0
    ]
    assert body_bg  # area-weighted body bg exceeds the flat CSS-rule weight


def test_image_cap_logic() -> None:
    """The cap holds and announces itself. Raised 12 → 50 by founder order 2026-08-20;
    the exact boundary behaviour is pinned in ``test_ingestion_image_sources.py``."""
    from lumen_ingestion.capture.imgsrc import IMAGE_CANDIDATE_CAP
    from lumen_ingestion.capture.snapshot import SiteSnapshot

    snapshot = load("insight_static")
    extra_imgs = "".join(
        f'<img src="/img/x{i}.png" width="{100 + i}" height="{100 + i}">'
        for i in range(IMAGE_CANDIDATE_CAP + 5)
    )
    html = snapshot.html.replace("</main>", extra_imgs + "</main>")
    mutated = SiteSnapshot(**{**snapshot.model_dump(), "html": html})
    parsed = parse_site(mutated)
    assert len(parsed.images) <= IMAGE_CANDIDATE_CAP + 1  # +1 tolerance for og_image
    assert any(d["code"] == "LUMI0504" for d in parsed.diagnostics)


# --------------------------------------------------------------------------- #
# Quality gate
# --------------------------------------------------------------------------- #


def test_gate_static_no_escalation() -> None:
    snapshot = load("insight_static")
    result = evaluate(snapshot, parse_site(snapshot))
    assert result.escalate is False
    assert result.reasons == []


def test_gate_spa_shell_escalates() -> None:
    snapshot = load("spa_shell")
    result = evaluate(snapshot, parse_site(snapshot))
    assert result.escalate is True
    assert any("client-rendered shell" in r for r in result.reasons)
    assert any("fewer than 4 distinct colors" in r for r in result.reasons)
    assert any("no type sample" in r for r in result.reasons)
    assert any("zero stylesheets" in r for r in result.reasons)


def test_escalation_unavailable_emits_LUMI0506(monkeypatch) -> None:
    # A capture that would escalate but has no renderer → LUMI0506 + static outcome.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            html="<html><head><title>App</title></head><body><div id=root></div></body></html>",
        )

    transport = httpx.MockTransport(handler)

    async def run() -> CaptureOutcome:
        async with httpx.AsyncClient(transport=transport) as client:
            return await capture_website(
                "https://example.com/",
                reporter=_noop,
                render_available=False,
                http_client=client,
            )

    # guard_url does real DNS; example.com resolves to a routable public address.
    outcome = asyncio.run(run())
    assert outcome.tier == "static"
    assert outcome.escalated is False
    assert outcome.escalation_reason is not None
    assert any(d["code"] == "LUMI0506" for d in outcome.diagnostics)


# --------------------------------------------------------------------------- #
# capture_website plumbing: concurrency + redirect re-guard
# --------------------------------------------------------------------------- #


def test_fetch_many_is_concurrent() -> None:
    """Barrier proof: the transport only completes each response once N requests
    are simultaneously in flight. A serial fetcher would deadlock (never reach
    N) and time out; a concurrent one releases the barrier and passes."""
    n_expected = 5
    barrier_reached = asyncio.Event()
    in_flight = {"count": 0, "max": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        in_flight["count"] += 1
        in_flight["max"] = max(in_flight["max"], in_flight["count"])
        if in_flight["count"] >= n_expected:
            barrier_reached.set()
        # Block until every expected request has arrived: serial code never gets
        # here for request #2 because request #1 is still awaiting the barrier.
        await asyncio.wait_for(barrier_reached.wait(), timeout=5.0)
        in_flight["count"] -= 1
        return httpx.Response(200, text="body")

    transport = httpx.MockTransport(handler)

    async def run() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            fetcher = BoundedFetcher(client)
            requests = [
                FetchRequest(url=f"https://example.com/r{i}.css", kind="css")
                for i in range(n_expected)
            ]
            results = await fetcher.fetch_many(requests)
        assert all(r.ok for r in results)

    asyncio.run(asyncio.wait_for(run(), timeout=8.0))
    assert in_flight["max"] >= n_expected  # all N were in flight together


def test_static_capture_fetches_assets_concurrently() -> None:
    """End-to-end static capture over MockTransport: page + 2 CSS + assets all
    arrive concurrently. The barrier releases only once ≥4 asset/CSS requests
    overlap, so a serial implementation times out."""
    page_html = (
        "<html><head><title>T</title>"
        '<link rel="stylesheet" href="/a.css">'
        '<link rel="stylesheet" href="/b.css">'
        "</head><body>"
        '<header><a href="/"><img src="/logo.png" width="10" height="10"></a></header>'
        '<img src="/i1.png" width="200" height="200">'
        '<img src="/i2.png" width="200" height="200">'
        "<p>hello world</p></body></html>"
    )
    barrier = asyncio.Event()
    overlap = {"count": 0, "max": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/":
            return httpx.Response(200, html=page_html)
        if path.endswith(".css"):
            return httpx.Response(200, text="body{color:#123456}")
        # asset requests block on the barrier to prove they overlap
        overlap["count"] += 1
        overlap["max"] = max(overlap["max"], overlap["count"])
        if overlap["count"] >= 3:
            barrier.set()
        await asyncio.wait_for(barrier.wait(), timeout=5.0)
        overlap["count"] -= 1
        # 1x1 PNG
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        )
        return httpx.Response(200, content=png, headers={"content-type": "image/png"})

    transport = httpx.MockTransport(handler)

    async def run() -> CaptureOutcome:
        async with httpx.AsyncClient(transport=transport) as client:
            return await capture_website(
                "https://example.com/",
                reporter=_noop,
                render_available=False,
                http_client=client,
            )

    outcome = asyncio.run(asyncio.wait_for(run(), timeout=10.0))
    assert outcome.tier == "static"
    assert len(outcome.snapshot.stylesheets) == 2
    assert overlap["max"] >= 3  # assets overlapped, not serial


def test_rendered_stylesheets_follow_one_level_of_import_like_static_does() -> None:
    """The static tier's ``@import`` contribution survives the always-render ruling.

    Website ingestion now ALWAYS renders (founder, 2026-08-20), so the static tier no longer
    runs for a well-server-rendered site — and everything it used to contribute has to be
    present on the rendered tier or it is silently lost. Assets, meta and inline CSS already
    were (rendered reuses static's collectors on the post-JS DOM); one thing was not: static
    follows one level of ``@import`` out of a fetched stylesheet, while the rendered tier read
    ``document.styleSheets``, where an imported sheet appears only as the parent's one-line
    ``@import`` rule. A brand whose ``@font-face`` block lives behind an import would have
    stopped being read the day the ruling landed.

    No browser: the harvest ``page.evaluate`` returns is a plain list of dicts, so the
    stylesheet assembly is driven directly.
    """
    from lumen_ingestion.capture.rendered import collect_stylesheets

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/main.css":
            return httpx.Response(
                200, text='@import url("fonts.css");\nbody{color:#123456}'
            )
        if request.url.path == "/fonts.css":
            return httpx.Response(
                200,
                text="@font-face{font-family:Brand;src:url(brand.woff2) format('woff2')}",
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)

    async def run() -> list:
        async with httpx.AsyncClient(transport=transport) as client:
            fetcher = BoundedFetcher(client)
            return await collect_stylesheets(
                [
                    {"href": None, "text": ":root{--brand:#123456}"},
                    {"href": "https://example.com/main.css", "text": None},
                ],
                fetcher,
            )

    sheets, _diagnostics = asyncio.run(asyncio.wait_for(run(), timeout=10.0))
    urls = [sheet.url for sheet in sheets]
    assert urls[0] == "inline:0"
    assert "https://example.com/main.css" in urls
    assert "https://example.com/fonts.css" in urls, urls
    imported = next(s for s in sheets if s.url.endswith("fonts.css"))
    assert "@font-face" in imported.text


def test_capture_redirect_reguard_rejects_private() -> None:
    """A redirect to 127.0.0.1 is re-guarded and rejected mid-capture."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "example.com":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/"})
        return httpx.Response(200, text="ok")

    transport = httpx.MockTransport(handler)

    async def run() -> None:
        async with httpx.AsyncClient(transport=transport) as client:
            await capture_website(
                "https://example.com/",
                reporter=_noop,
                render_available=False,
                http_client=client,
            )

    with pytest.raises(CaptureError) as excinfo:
        asyncio.run(run())
    assert excinfo.value.code == "LUMI0501"


# --------------------------------------------------------------------------- #
# evidence_builder
# --------------------------------------------------------------------------- #


class _StubCore:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def ingest_asset(self, **kwargs):  # matches CoreClient.ingest_asset kwargs
        self.calls.append(kwargs)
        return {"ok": True, "asset": {"record": {"id": kwargs["asset_id"]}}}


def _outcome(name: str) -> CaptureOutcome:
    return CaptureOutcome(
        snapshot=load(name),
        tier=load(name).tier,
        escalated=False,
        escalation_reason=None,
        diagnostics=[],
    )


def test_build_evidence_content_addressed_and_wired() -> None:
    stub = _StubCore()
    with tempfile.TemporaryDirectory() as store:
        evidence = build_evidence(
            _outcome("insight_static"), core=stub, store_root=store, reporter=_noop
        )

    # all asset ids are content-addressed asset_ing_<sha[:16]>
    for call in stub.calls:
        assert call["asset_id"].startswith("asset_ing_")
        assert len(call["asset_id"]) == len("asset_ing_") + 16

    # font face wired to an ingested asset
    assert evidence.fonts
    face = evidence.fonts[0].faces[0]
    assert face.asset_id is not None
    assert face.asset_id.startswith("asset_ing_")

    # logos & images reference ingested assets
    assert all(l.asset_id.startswith("asset_ing_") for l in evidence.logos)
    assert all(i.asset_id.startswith("asset_ing_") for i in evidence.images)

    # source carries website provenance
    assert evidence.source["kind"] == "website"
    assert evidence.source["confidence"] == 0.7


def test_build_evidence_screenshot_listed() -> None:
    stub = _StubCore()
    with tempfile.TemporaryDirectory() as store:
        evidence = build_evidence(
            _outcome("insight_rendered"), core=stub, store_root=store, reporter=_noop
        )
    assert evidence.screenshots
    assert evidence.screenshots[0].startswith("asset_ing_")


# --------------------------------------------------------------------------- #
# End-to-end replay (DoD): snapshot → parse → build_evidence → normalize →
# real-engine validate_brand_kit(product_ready=False)
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(
    not os.environ.get("LUMEN_CORE_HELPER"),
    reason="requires the cargo helper (LUMEN_CORE_HELPER)",
)
def test_replay_static_validates_against_engine() -> None:
    stub = _StubCore()
    with tempfile.TemporaryDirectory() as store:
        evidence = build_evidence(
            _outcome("insight_static"), core=stub, store_root=store, reporter=_noop
        )
    result = normalize_evidence(
        evidence,
        brand_kit_id="brand_kit_ing_replay",
        name="Insight Health",
        created_at="2026-07-05",
    )
    engine = CoreClient()
    validated = engine.validate_brand_kit(result.brand_kit, product_ready=False)
    assert validated.get("ok") is True

    summary = engine.summarize_brand_kit(result.brand_kit)
    assert summary.get("ok") is True

    # dark colorway captured from the prefers-color-scheme block
    assert result.ingestion_report["dark_colorway"] == "captured"


# --------------------------------------------------------------------------- #
# Multi-signal primary-logo scoring
# --------------------------------------------------------------------------- #


def _with_html(snapshot, html: str):
    from lumen_ingestion.capture.snapshot import SiteSnapshot

    return SiteSnapshot(**{**snapshot.model_dump(), "html": html})


def test_logo_scoring_junk_badges_lose_to_classed_logo_outside_header() -> None:
    """The live insighthealth.ai failure shape: header's first imgs are store
    badges, the real lockup sits in a `class="nav_logo"` img the old first-2
    cap never reached. The scorer must pick the classed lockup and drop the
    badges (junk-filename penalty)."""
    snapshot = load("insight_static")
    html = """
    <html><head><title>x</title></head><body>
      <header>
        <img src="/badges/Download_on_the_App_Store_Badge.svg">
        <img src="/promo/download_chrome_extension_large.avif">
      </header>
      <div class="navbar_component">
        <a href="/"><img class="nav_logo" src="/media/company-lockup.webp" width="474" height="71"></a>
      </div>
      <main></main>
    </body></html>
    """
    parsed = parse_site(_with_html(snapshot, html))
    primaries = [l for l in parsed.logos if l.usage_hint == "primary"]
    assert [l.source_url for l in primaries] == ["https://www.insighthealth.ai/media/company-lockup.webp"]
    assert "logo-class" in primaries[0].locator and "home-link" in primaries[0].locator


def test_logo_scoring_jsonld_organization_declaration_wins() -> None:
    """schema.org Organization JSON-LD is an explicit declaration — it must
    outrank every DOM inference."""
    snapshot = load("insight_static")
    html = """
    <html><head>
      <script type="application/ld+json">
        {"@context":"https://schema.org","@graph":[{"@type":"Organization",
         "logo":{"@type":"ImageObject","url":"/brand/declared-logo.png"}}]}
      </script>
    </head><body>
      <header><a href="/"><img src="/img/some-header-logo.svg"></a></header>
      <main></main>
    </body></html>
    """
    parsed = parse_site(_with_html(snapshot, html))
    primaries = [l for l in parsed.logos if l.usage_hint == "primary"]
    assert primaries[0].source_url == "https://www.insighthealth.ai/brand/declared-logo.png"
    assert "jsonld-or-og-declared" in primaries[0].locator


def test_logo_scoring_no_convincing_candidate_leaves_primary_empty() -> None:
    """Below the confidence threshold the slot stays EMPTY for the human to
    fill — an honest gap beats a confident wrong guess."""
    snapshot = load("insight_static")
    html = """
    <html><head></head><body>
      <div><img src="/photos/team-photo-1600.jpg" width="1600" height="900"></div>
      <main></main>
    </body></html>
    """
    parsed = parse_site(_with_html(snapshot, html))
    assert [l for l in parsed.logos if l.usage_hint == "primary"] == []
