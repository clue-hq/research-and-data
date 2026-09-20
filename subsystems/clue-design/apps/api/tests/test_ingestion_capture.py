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
    # Keep the selected worktree's shared-package roots. Discarding these can
    # silently mix this API with editable packages from another checkout.
    roots = [str(api_root), str(repo_root), *os.environ.get("PYTHONPATH", "").split(os.pathsep)]
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(root for root in roots if root)}
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
    roots = [str(api_root), str(repo_root), *os.environ.get("PYTHONPATH", "").split(os.pathsep)]
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(root for root in roots if root)}
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
# W1.3 — modern CSS color syntax must not sink the ingestion job
#
# apollo.io failed LUMI0401 on 4/4 URLs with
# `ValueError: could not convert string to float: 'var(--tw-text-opacity'`.
# Tailwind serves `rgb(15 23 42 / var(--tw-text-opacity))`; the tokenizer split
# on `)`, so the fragment reached a bare float() and killed the whole job.
# --------------------------------------------------------------------------- #


def test_tailwind_slash_alpha_keeps_the_color_instead_of_crashing() -> None:
    """RED before the fix: this exact apollo.io string raised ValueError."""
    diagnostics: list[dict] = []
    # The three channels are numeric and carry apollo.io's real text color;
    # only the alpha is an unresolved custom property. Keep the color.
    assert (
        parse_color_value(
            "rgb(15 23 42 / var(--tw-text-opacity))", {}, diagnostics=diagnostics
        )
        == "#0F172A"
    )
    # ...and say out loud that the alpha was read as opaque.
    assert [d for d in diagnostics if d["code"] == "LUMI0511"]
    assert "alpha channel unreadable" in diagnostics[0]["message"]
    # The same shape in hsl(), and in the rgba() spelling Tailwind also emits.
    assert parse_color_value("rgba(24 24 27 / var(--tw-bg-opacity))", {}) == "#18181B"
    assert parse_color_value("hsl(0 100% 50% / var(--tw-x))", {}) == "#FF0000"


def test_modern_space_separated_rgb_parses_with_numeric_alpha() -> None:
    """The modern syntax is not just survivable — it is read correctly."""
    assert parse_color_value("rgb(15 23 42)", {}) == "#0F172A"
    assert parse_color_value("rgb(15 23 42 / 0.5)", {}) == "#0F172A80"
    assert parse_color_value("rgb(15 23 42 / 50%)", {}) == "#0F172A80"
    assert parse_color_value("hsl(0 100% 50%)", {}) == "#FF0000"


def test_a_genuinely_unreadable_color_is_skipped_not_raised() -> None:
    """Fail soft: an unreadable value is one swatch dropped, with a reason."""
    diagnostics: list[dict] = []
    # Relative-color syntax — real modern CSS this parser does not implement.
    assert parse_color_value("rgb(from var(--accent) r g b)", {}, diagnostics=diagnostics) is None
    assert parse_color_value("rgb(a b c)", {}, diagnostics=diagnostics) is None
    assert parse_color_value("hsl(nope, bad, worse)", {}, diagnostics=diagnostics) is None
    assert len(diagnostics) == 3
    assert all(d["severity"] == "warning" for d in diagnostics)


def test_a_cyclic_custom_property_chain_is_skipped_not_a_recursion_error() -> None:
    """RED before the fix: cursor.com/about's cyclic var() blew the stack."""
    props = {"--a": "var(--b)", "--b": "var(--a)"}
    diagnostics: list[dict] = []
    assert parse_color_value("var(--a)", props, diagnostics=diagnostics) is None
    assert "did not resolve" in diagnostics[0]["message"]
    # A long-but-finite chain still resolves.
    chain = {f"--n{i}": f"var(--n{i + 1})" for i in range(10)}
    chain["--n10"] = "#12EAB1"
    assert parse_color_value("var(--n0)", chain) == "#12EAB1"


_TAILWIND_CSS = """
:root { --color-brand: rgb(254 255 0 / var(--tw-bg-opacity)); }
body { background-color: rgb(255 255 255 / var(--tw-bg-opacity)); color: rgb(15 23 42 / var(--tw-text-opacity)); }
h1 { color: rgb(15 23 42 / var(--tw-text-opacity)); font-family: 'Source Serif 4'; font-size: 48px; font-weight: 700; }
p { color: rgb(71 85 105 / var(--tw-text-opacity)); font-family: 'DM Sans'; font-size: 16px; }
.btn { background-color: rgb(254 255 0 / var(--tw-bg-opacity)); color: rgb(15 23 42 / var(--tw-text-opacity)); }
"""


def _tailwind_snapshot():
    """The apollo.io shape: a real snapshot whose CSS is modern Tailwind color
    syntax with unresolved opacity custom properties."""
    from lumen_ingestion.capture.snapshot import SiteSnapshot, Stylesheet

    base = load("insight_static")
    return SiteSnapshot(
        **{
            **base.model_dump(),
            "requested_url": "https://apollo.io",
            "final_url": "https://apollo.io",
            "stylesheets": [
                Stylesheet(url="https://apollo.io/assets/app.css", text=_TAILWIND_CSS).model_dump()
            ],
            "custom_props": {"--color-brand": "rgb(254 255 0 / var(--tw-bg-opacity))"},
        }
    )


def test_an_ingestion_job_survives_unparseable_colors_end_to_end(tmp_path) -> None:
    """RED before the fix: apollo.io failed `LUMI0401` on 4/4 URLs here.

    This is the whole offline job — parse → evidence → normalize — driven
    through `run_ingestion_job`, the wrapper that turns any escaped exception
    into the `LUMI0401` failure the pilot hit. It must reach `succeeded`.
    """
    from lumen_api.design_store import HybridRepository
    from lumen_ingestion.jobs import IngestionJobStore, run_ingestion_job

    kit_id = "kit_tailwind_survival"
    HybridRepository().create_brand_kit(
        {"id": kit_id, "version": 1, "name": kit_id, "approval_status": "draft"},
        {"product_ready": False},
        [],
        "website",
    )
    store = IngestionJobStore()
    job_id = store.create("website", {"url": "https://apollo.io"})["job_id"]

    outcome = CaptureOutcome(
        snapshot=_tailwind_snapshot(),
        tier="static",
        escalated=False,
        escalation_reason=None,
        diagnostics=[],
    )
    stub = _StubCore()

    def work(report):
        report("Taking a closer look…", 0.55)  # the stage apollo.io died at
        with tempfile.TemporaryDirectory() as asset_store:
            evidence = build_evidence(
                outcome, core=stub, store_root=asset_store, reporter=_noop
            )
        result = normalize_evidence(
            evidence, brand_kit_id=kit_id, name="Apollo", created_at="2026-08-26"
        )
        assert result.brand_kit["assets"] is not None
        return (kit_id, 1, None)

    run_ingestion_job(store, job_id, work)

    job = store.require(job_id)
    assert job["error"] is None, job["error"]
    assert job["status"] == "succeeded"

    # The colors were not merely survived — the real channels were read.
    # (Phase-1 overhaul: rule-text colors like the near-black `#0F172A` are no
    # longer palette evidence; the TOKEN yellow — the modern-syntax survival
    # this test guards — must still parse through the alpha-var fallback.)
    hexes = {c.value for c in parse_site(_tailwind_snapshot()).colors}
    assert "#FEFF00" in hexes  # apollo's brand yellow, from --color-brand

    # ...and the skipped alpha is reported to the human, on the outcome the
    # pipeline publishes, not swallowed.
    assert [d for d in outcome.diagnostics if d["code"] == "LUMI0511"]


def test_diagnostics_are_deduped_and_bounded() -> None:
    """A Tailwind site serves thousands of these; the report stays readable."""
    diagnostics: list[dict] = []
    for i in range(200):
        parse_color_value(f"rgb(a{i} b c)", {}, diagnostics=diagnostics)
    assert 0 < len(diagnostics) <= 8
    # Repeating one value does not repeat its diagnostic.
    repeated: list[dict] = []
    for _ in range(50):
        parse_color_value("rgb(a b c)", {}, diagnostics=repeated)
    assert len(repeated) == 1


# --------------------------------------------------------------------------- #
# Parse: role hints, dark scope, var() resolution, rem→px, fonts, logos, images
# --------------------------------------------------------------------------- #


def test_parse_rule_text_emits_no_light_candidates_but_tokens_and_dark_survive() -> None:
    """Phase-1 brand-color overhaul (2026-08-30): light rule-text colors are
    NOT palette evidence any more — the selector-vocabulary weights elected
    apollo.io's focus ring as its brand. What must survive the retirement:
    custom-prop token evidence (naming layer) and dark-block rule colors (the
    dark colorway's only whole-page evidence until dark capture lands)."""
    parsed = parse_site(load("insight_static"))

    # No LIGHT color evidence from rule text — the fixture's `body`/`.btn-primary`
    # rules used to emit weighted, hinted candidates here.
    light_rule_colors = [
        c
        for c in parsed.colors
        if c.theme == "light" and not any(h.startswith("custom-prop:") for h in c.role_hints)
    ]
    assert light_rule_colors == []

    # Dark prefers-color-scheme block colors still carry theme="dark", flat and
    # hintless — evidence for `build_dark_colorway`, never light election.
    dark = [c for c in parsed.colors if c.theme == "dark"]
    assert any(c.value == "#0B0B0C" for c in dark)
    assert all(c.weight == 1.0 and c.role_hints == [] for c in dark)

    # var() still resolved against custom props: the naming layer survives.
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


def test_image_budget_logic() -> None:
    """The budget holds and announces itself.

    Was a hard cap (12 → 50 by founder order 2026-08-20); replaced by the shared asset budget
    at clone-fidelity F0.2, whose ``LUMI0514`` names every dropped URL. The exact boundary
    behaviour is pinned in ``test_ingestion_image_sources.py``.
    """
    from lumen_ingestion.capture.budget import MAX_ASSET_COUNT
    from lumen_ingestion.capture.snapshot import SiteSnapshot

    snapshot = load("insight_static")
    extra_imgs = "".join(
        f'<img src="/img/x{i}.png" width="{100 + i}" height="{100 + i}">'
        for i in range(MAX_ASSET_COUNT + 5)
    )
    html = snapshot.html.replace("</main>", extra_imgs + "</main>")
    mutated = SiteSnapshot(**{**snapshot.model_dump(), "html": html})
    parsed = parse_site(mutated)
    assert len(parsed.images) <= MAX_ASSET_COUNT + 1  # +1 tolerance for og_image
    assert any(d["code"] == "LUMI0514" for d in parsed.diagnostics)


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
# F0.4 — the multi-page provision
# --------------------------------------------------------------------------- #


_MULTIPAGE_HTML = {
    "/": "<html><head><title>Home</title></head><body><p>home page words</p></body></html>",
    "/about": "<html><head><title>About</title></head><body><p>about page words</p></body></html>",
}


def _multipage_transport(broken: set[str] | None = None) -> httpx.MockTransport:
    broken = broken or set()

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in broken:
            raise httpx.ConnectError("connection refused", request=request)
        if path in _MULTIPAGE_HTML:
            return httpx.Response(200, html=_MULTIPAGE_HTML[path])
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _capture(url: str, transport: httpx.MockTransport, **kwargs) -> CaptureOutcome:
    async def run() -> CaptureOutcome:
        async with httpx.AsyncClient(transport=transport) as client:
            return await capture_website(
                url, reporter=_noop, render_available=False, http_client=client, **kwargs
            )

    return asyncio.run(asyncio.wait_for(run(), timeout=10.0))


def test_capture_website_yields_one_snapshot_for_the_entry_page_by_default() -> None:
    outcome = _capture("https://example.com/", _multipage_transport())
    assert [s.requested_url for s in outcome.snapshots] == ["https://example.com/"]
    # `.snapshot` stays the entry page — every pre-F0.4 caller reads it and must not move.
    assert outcome.snapshots[0] is outcome.snapshot


def test_capture_website_captures_every_requested_page_in_order() -> None:
    outcome = _capture(
        "https://example.com/",
        _multipage_transport(),
        page_urls=["https://example.com/about"],
    )
    assert [s.requested_url for s in outcome.snapshots] == [
        "https://example.com/",
        "https://example.com/about",
    ]
    assert outcome.snapshot is outcome.snapshots[0]
    assert "about page words" in outcome.snapshots[1].html


def test_the_entry_page_is_captured_once_even_when_the_page_list_repeats_it() -> None:
    outcome = _capture(
        "https://example.com/",
        _multipage_transport(),
        page_urls=["https://example.com/", "https://example.com/about", "https://example.com/"],
    )
    assert [s.requested_url for s in outcome.snapshots] == [
        "https://example.com/",
        "https://example.com/about",
    ]


def test_a_non_entry_page_failure_is_a_loud_diagnostic_and_the_capture_continues() -> None:
    outcome = _capture(
        "https://example.com/",
        _multipage_transport(broken={"/about"}),
        page_urls=["https://example.com/about"],
    )
    assert [s.requested_url for s in outcome.snapshots] == ["https://example.com/"]
    failures = [d for d in outcome.diagnostics if d["code"] == "LUMI0513"]
    assert len(failures) == 1
    assert "https://example.com/about" in failures[0]["message"]
    assert failures[0]["severity"] == "warning"


def test_an_entry_page_failure_still_fails_the_whole_capture() -> None:
    with pytest.raises(httpx.ConnectError):
        _capture(
            "https://example.com/",
            _multipage_transport(broken={"/"}),
            page_urls=["https://example.com/about"],
        )


# --------------------------------------------------------------------------- #
# Diagnostics are recorded once (F0 fix wave, FIX 2)
# --------------------------------------------------------------------------- #
#
# A failed fetch is reported twice by construction: `net.BoundedFetcher` puts the diagnostic
# on the per-item `FetchResult` — which `static._collect_assets` folds into the SNAPSHOT —
# and on its own accumulating list, which `_capture_page` reads as a delta. The acceptance
# walk against insighthealth.ai turned three distinct failures into six LUMI0503s. These land
# on the published kit UNCAPPED (`budget.MAX_NAMED_DROPS` bounds the evidence builder's
# LUMI0515/LUMI0516 lists, not this one), so the doubling is both twice the noise a human
# reads and a wrong answer to "how much did this capture lose".


_DEAD_ASSET_PAGE = (
    "<html><head><title>Doubled</title>"
    '<link rel="stylesheet" href="/css/site.css">'
    "</head><body>"
    '<img src="/i/one.png"><img src="/i/two.png">'
    "<p>enough words on the page that the quality gate has something to read</p>"
    "</body></html>"
)
_DEAD_ASSET_CSS = "body{background-image:url(/i/three.png);color:#123456}"
_DEAD_ASSETS = ("/i/one.png", "/i/two.png", "/i/three.png")
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def _dead_asset_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in _DEAD_ASSETS:
            return httpx.Response(403)
        if path == "/css/site.css":
            return httpx.Response(200, text=_DEAD_ASSET_CSS, headers={"content-type": "text/css"})
        if path == "/":
            return httpx.Response(200, html=_DEAD_ASSET_PAGE)
        if path == "/favicon.ico":
            # The logo ladder probes this on every page; serving it keeps the three dead
            # assets the only failures, so the count below means what it says.
            return httpx.Response(200, content=_PNG, headers={"content-type": "image/png"})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_each_failed_fetch_is_reported_exactly_once_on_the_outcome() -> None:
    outcome = _capture("https://example.com/", _dead_asset_transport())
    failures = [d for d in outcome.diagnostics if d["code"] == "LUMI0503"]

    assert sorted(d["url"] for d in failures) == [
        f"https://example.com{path}" for path in sorted(_DEAD_ASSETS)
    ], [d["url"] for d in failures]
    assert len(failures) == len(_DEAD_ASSETS), failures


def test_a_fetcher_diagnostic_with_no_snapshot_twin_still_reaches_the_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fetcher delta is still READ, not dropped — the dedupe removes twins, not sources.

    The page fetch itself records onto the fetcher, and a future caller can hand the fetcher
    work whose result never becomes part of a snapshot; an entry with no twin must survive.
    """
    from lumen_ingestion import capture as capture_pkg
    from lumen_ingestion.capture.snapshot import SiteSnapshot

    twinned = {
        "code": "LUMI0503",
        "severity": "warning",
        "message": "fetch failed for https://example.com/i/twinned.png: HTTP 403",
        "url": "https://example.com/i/twinned.png",
        "reason": "HTTP 403",
    }
    fetcher_only = {
        "code": "LUMI0502",
        "severity": "warning",
        "message": "resource exceeded its cap and was skipped: https://example.com/",
        "url": "https://example.com/",
        "reason": "exceeded the cap for its resource class",
    }

    async def _fake_static(url, fetcher, reporter, *, fetched_at):
        fetcher.diagnostics.append(fetcher_only)
        fetcher.diagnostics.append(twinned)
        return SiteSnapshot(
            requested_url=url,
            final_url=url,
            fetched_at=fetched_at,
            tier="static",
            html="<html><body><p>" + ("word " * 80) + "</p></body></html>",
            diagnostics=[twinned],
        )

    monkeypatch.setattr(capture_pkg, "fetch_static", _fake_static)

    async def run() -> CaptureOutcome:
        return await capture_website(
            "https://example.com/", reporter=_noop, render_available=False
        )

    outcome = asyncio.run(asyncio.wait_for(run(), timeout=10.0))

    assert outcome.diagnostics.count(twinned) == 1, outcome.diagnostics
    assert fetcher_only in outcome.diagnostics, outcome.diagnostics


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
# W1.2 — font byte custody
#
# Both pilots recorded brand faces by URL with `asset_id: null` (CursorGothic:
# 4 woff2 URLs, nothing stored), so the renderer had no bytes, emitted
# LUMS0100, and painted Inter in literally every run. Capture and parse were
# discovering @font-face URLs two different ways; the evidence builder matches
# a face to its bytes by exact URL string, so any disagreement meant the bytes
# were fetched under one key and looked for under another.
# --------------------------------------------------------------------------- #


_WOFF2 = base64.b64decode("d09GMgABAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")


def _font_site(css: str, sheet_path: str = "/assets/app.css"):
    """A site whose only interesting content is one self-hosted @font-face."""
    page_html = (
        "<html><head><title>Brand</title>"
        f'<link rel="stylesheet" href="{sheet_path}">'
        "</head><body><h1>Brand</h1><p>hello world</p></body></html>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/":
            return httpx.Response(200, html=page_html)
        if path == sheet_path:
            return httpx.Response(200, text=css, headers={"content-type": "text/css"})
        if path.endswith(".woff2"):
            return httpx.Response(
                200, content=_WOFF2, headers={"content-type": "font/woff2"}
            )
        return httpx.Response(404)

    async def run() -> CaptureOutcome:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await capture_website(
                "https://example.com/",
                reporter=_noop,
                render_available=False,
                http_client=client,
            )

    return asyncio.run(asyncio.wait_for(run(), timeout=10.0))


@pytest.mark.parametrize(
    "src,label",
    [
        ("url('/media/BrandSans-Regular.woff2')", "root-relative"),
        # RED: resolved against the stylesheet by capture and against the page
        # by parse — two different absolute URLs for one file.
        ("url('../media/BrandSans-Regular.woff2')", "stylesheet-relative"),
        # RED: capture's old regex required the extension to be the last thing
        # before the paren, so a cache-busted URL was never fetched at all.
        ("url('/media/BrandSans-Regular.woff2?v=3')", "cache-busted"),
        (
            "url('/media/BrandSans-Regular.woff2') format('woff2')",
            "with-format-hint",
        ),
    ],
)
def test_a_declared_font_face_ends_up_with_retrievable_bytes(src, label) -> None:
    """The W1.2 contract: a face the site declares carries an asset_id, and
    that asset was handed real bytes through the normal custody path."""
    css = (
        "@font-face{font-family:'BrandSans';font-weight:400;font-style:normal;"
        f"src:{src};}}"
        "h1{font-family:'BrandSans';font-size:48px;font-weight:700}"
    )
    outcome = _font_site(css)

    # The bytes were actually downloaded during capture.
    font_downloads = [d for d in outcome.snapshot.downloads if d.kind == "font"]
    assert font_downloads, f"{label}: no font bytes were fetched at all"

    stub = _StubCore()
    with tempfile.TemporaryDirectory() as store:
        evidence = build_evidence(outcome, core=stub, store_root=store, reporter=_noop)

    assert evidence.fonts, f"{label}: no font evidence"
    face = evidence.fonts[0].faces[0]
    assert face.asset_id is not None, f"{label}: face has no asset_id — LUMS0100"
    assert face.asset_id.startswith("asset_ing_")

    # ...and that asset id was ingested with the real bytes, as a font.
    ingested = {c["asset_id"]: c for c in stub.calls}
    assert face.asset_id in ingested, f"{label}: asset_id was never custodied"
    call = ingested[face.asset_id]
    assert call["kind"] == "font"
    assert base64.b64decode(call["bytes_base64"]) == _WOFF2
    # Nothing was reported as missing.
    assert not [d for d in outcome.diagnostics if d["code"] == "LUMI0231"]


def test_capture_and_parse_agree_on_every_font_url() -> None:
    """The invariant behind the fix: every URL a face points at is a URL whose
    bytes capture actually downloaded. This is what `asset_id: null` meant."""
    css = (
        "@font-face{font-family:'BrandSans';font-weight:400;"
        "src:url('../media/BrandSans-Regular.woff2');}"
        "@font-face{font-family:'BrandSans';font-weight:700;"
        "src:url('/media/BrandSans-Bold.woff2?v=9');}"
    )
    outcome = _font_site(css, sheet_path="/nested/css/app.css")
    downloaded = {d.url for d in outcome.snapshot.downloads if d.kind == "font"}
    declared = {
        face.source_url
        for font in parse_site(outcome.snapshot).fonts
        for face in font.faces
        if face.source_url
    }
    assert declared, "no faces parsed"
    assert declared <= downloaded, f"faces with no bytes: {declared - downloaded}"
    # The stylesheet-relative URL resolved against the stylesheet, not the page.
    assert "https://example.com/nested/media/BrandSans-Regular.woff2" in declared


def test_a_font_whose_bytes_cannot_be_fetched_is_reported_not_silent() -> None:
    """Honest failure: when the site's font 404s we cannot custody it, and that
    must be said out loud rather than surfacing later as a mystery Inter run."""
    css = (
        "@font-face{font-family:'BrandSans';font-weight:400;"
        "src:url('/media/missing.woff2');}"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/":
            return httpx.Response(
                200,
                html='<html><head><title>B</title><link rel="stylesheet" href="/a.css">'
                "</head><body><p>hello world</p></body></html>",
            )
        if path == "/a.css":
            return httpx.Response(200, text=css, headers={"content-type": "text/css"})
        return httpx.Response(404)  # the font is gone

    async def run() -> CaptureOutcome:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await capture_website(
                "https://example.com/",
                reporter=_noop,
                render_available=False,
                http_client=client,
            )

    outcome = asyncio.run(asyncio.wait_for(run(), timeout=10.0))
    stub = _StubCore()
    with tempfile.TemporaryDirectory() as store:
        evidence = build_evidence(outcome, core=stub, store_root=store, reporter=_noop)

    assert evidence.fonts[0].faces[0].asset_id is None  # honestly empty
    reported = [d for d in outcome.diagnostics if d["code"] == "LUMI0231"]
    assert reported, "a byte-less font face was recorded in total silence"
    assert "BrandSans" in reported[0]["message"]


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
