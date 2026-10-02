"""Cover for the gallery thumbnail generator and the route that serves it.

The pure halves — runtime resolution, the Tailwind inline splice, the engine-PNG
decode, the downscale, the scene page pick — run everywhere. The one capture test
launches a real Chromium (nothing else proves a Tailwind arbitrary-value class
actually compiled) and skips honestly when the browser or the runtime is absent.

The second half exercises `GET /documents/{id}/thumbnail` against the real app:
real repository, real blob store, real engine. Only the *generator seams* are
faked (the web capture, so the suite does not launch Chromium per request), never
HTTP — the caching, the version keying and the typed refusal are the route's, and
a fake response would prove none of them.
"""

from __future__ import annotations

import functools
import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from conftest import make_blob_store, make_client

from lumen_api import document_thumbnails as thumbs
from lumen_api.core import CoreError
from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[3]
MINIMAL_SCENE_PATH = REPO_ROOT / "crates/lumen-core/fixtures/minimal_scene.json"


def _png(width: int, height: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (12, 34, 56)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_inline_tailwind_lands_before_head_close():
    html = "<html><head><title>t</title></head><body><p>hi</p></body></html>"
    out = thumbs.inline_tailwind(html, b"RUNTIME_JS")
    # The splice is web_substrate's, newline and all (web_substrate.py:8880).
    assert "<script>RUNTIME_JS</script>\n</head>" in out


def test_inline_tailwind_without_head_prepends():
    html = "<html><body><p>hi</p></body></html>"
    out = thumbs.inline_tailwind(html, b"RUNTIME_JS")
    # Never dropped: with no `</head>` the runtime goes in front of the document,
    # so it still loads before the theme block it has to compile.
    assert out.startswith("<script>RUNTIME_JS</script>")
    assert html in out


def test_inline_tailwind_without_head_stays_behind_the_doctype():
    html = "<!DOCTYPE html>\n<html><body><p>hi</p></body></html>"
    out = thumbs.inline_tailwind(html, b"RUNTIME_JS")
    # A script in FRONT of the doctype puts Chromium in quirks mode, and the
    # thumbnail would then picture a layout nobody ships.
    assert out.startswith("<!DOCTYPE html>")
    assert out.startswith("<!DOCTYPE html><script>RUNTIME_JS</script>")
    assert out.endswith("\n<html><body><p>hi</p></body></html>")


def test_downscale_caps_the_long_edge_and_keeps_aspect():
    data = thumbs.downscale_png(_png(2000, 1000), max_edge=724)
    image = Image.open(io.BytesIO(data))
    assert image.size == (724, 362)


def test_downscale_never_upscales():
    data = thumbs.downscale_png(_png(400, 300), max_edge=724)
    image = Image.open(io.BytesIO(data))
    assert image.size == (400, 300)


def test_png_from_export_result_decodes_engine_bytes():
    png = _png(10, 10)
    result = {
        "ok": True,
        "export": {"artifacts": [{"bytes": list(png), "mime_type": "image/png"}]},
    }
    assert thumbs.png_from_export_result(result) == png


def test_png_from_export_result_refuses_a_failed_export():
    with pytest.raises(thumbs.ThumbnailUnavailable) as raised:
        thumbs.png_from_export_result({"ok": False, "export": {}})
    assert raised.value.code == "thumbnail.export_failed"


def test_png_from_export_result_refuses_an_empty_artifact():
    result = {"ok": True, "export": {"artifacts": [{"bytes": [], "mime_type": "image/png"}]}}
    with pytest.raises(thumbs.ThumbnailUnavailable) as raised:
        thumbs.png_from_export_result(result)
    assert raised.value.code == "thumbnail.export_failed"


def test_png_from_export_result_wraps_malformed_bytes():
    # The route's only refusal channel is ThumbnailUnavailable — a `bytes` list the
    # engine never produces must arrive as a typed 502, not an untyped 500.
    result = {"ok": True, "export": {"artifacts": [{"bytes": ["nonsense"]}]}}
    with pytest.raises(thumbs.ThumbnailUnavailable) as raised:
        thumbs.png_from_export_result(result)
    assert raised.value.code == "thumbnail.export_failed"


def test_downscale_png_wraps_undecodable_bytes():
    # PIL raises UnidentifiedImageError on garbage; the boundary owns that too.
    with pytest.raises(thumbs.ThumbnailUnavailable) as raised:
        thumbs.downscale_png(b"not a png")
    assert raised.value.code == "thumbnail.export_failed"


def test_first_page_ids_takes_the_first_page_as_serialized():
    # A scene's pages are a MAP keyed by page id (engine `BTreeMap<PageId, Page>`),
    # not a list — confirmed against a stored `doc_kind='scene'` document.
    #
    # The keys here are seeded in NON-sorted order on purpose. The contract is
    # "first key AS SERIALIZED", not "client-side re-sort": the engine serializes
    # its BTreeMap in key order, and both `next(iter(...))` here and the editor's
    # `Object.keys(...)` read the document's own order. A re-sorting reader would
    # answer "page_a" and thumbnail a page the editor does not open on.
    scene = {"pages": {"page_z": {"id": "page_z"}, "page_a": {"id": "page_a"}}}
    assert thumbs.first_page_ids(scene) == ["page_z"]


def test_first_page_ids_none_when_shape_unknown():
    assert thumbs.first_page_ids({}) is None
    # A web document's pages ARE a list; this function only speaks scene, and a
    # guessed answer would export the wrong page.
    assert thumbs.first_page_ids({"pages": [{"id": "p1"}]}) is None


def test_resolve_tailwind_runtime_refuses_a_named_but_missing_override(monkeypatch, tmp_path):
    monkeypatch.setenv(thumbs._TAILWIND_RUNTIME_ENV, str(tmp_path / "nope.js"))
    assert thumbs.resolve_tailwind_runtime() is None


def test_resolve_tailwind_runtime_reads_the_override(monkeypatch, tmp_path):
    runtime = tmp_path / "tailwind.js"
    runtime.write_text("RUNTIME_JS", encoding="utf-8")
    monkeypatch.setenv(thumbs._TAILWIND_RUNTIME_ENV, str(runtime))
    assert thumbs.resolve_tailwind_runtime() == b"RUNTIME_JS"


def test_web_thumbnail_png_refuses_without_a_runtime(monkeypatch, tmp_path):
    monkeypatch.setenv(thumbs._TAILWIND_RUNTIME_ENV, str(tmp_path / "nope.js"))
    with pytest.raises(thumbs.ThumbnailUnavailable) as raised:
        thumbs.web_thumbnail_png("<html><body></body></html>")
    assert raised.value.code == "thumbnail.tailwind_runtime_missing"


def test_web_thumbnail_png_wraps_a_playwright_failure(monkeypatch):
    # A browser that will not start (no chromium downloaded, a sandbox refusal) is a
    # thumbnail refusal, not a server fault — and the route only understands
    # ThumbnailUnavailable. The runtime is made resolvable first, or the refusal
    # above would fire and prove nothing about the capture.
    import playwright.sync_api

    monkeypatch.setattr(thumbs, "resolve_tailwind_runtime", lambda: b"x")

    def explode():
        raise playwright.sync_api.Error("Executable doesn't exist")

    # Patched on `playwright.sync_api` itself: the generator imports the name at
    # call time, so this is the real `except PlaywrightError` clause being taken.
    monkeypatch.setattr(playwright.sync_api, "sync_playwright", explode)
    with pytest.raises(thumbs.ThumbnailUnavailable) as raised:
        thumbs.web_thumbnail_png("<html><body></body></html>")
    assert raised.value.code == "thumbnail.capture_failed"
    assert "Executable doesn't exist" in str(raised.value)


@functools.lru_cache(maxsize=None)
def _chromium_available() -> bool:
    # Cached: the probe LAUNCHES a browser, so a session that asks twice must pay once.
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            pw.chromium.launch(headless=True).close()
        return True
    except Exception:
        return False


def test_web_thumbnail_png_captures_styled_html(monkeypatch):
    # The skips are IN THE BODY, not a `skipif` condition: a marker expression is
    # evaluated at COLLECTION time, so this probe used to launch a real Chromium
    # (and read the filesystem) merely to list the tests in this file.
    if not _chromium_available():
        pytest.skip("playwright chromium not installed")
    if thumbs.resolve_tailwind_runtime() is None:
        pytest.skip("no tailwind runtime on this machine")
    # A page that is red only if arbitrary-value Tailwind classes compiled.
    monkeypatch.delenv(thumbs._TAILWIND_RUNTIME_ENV, raising=False)
    html = (
        "<html><head></head><body>"
        '<div class="min-h-screen bg-[rgb(255,0,0)]"></div>'
        "</body></html>"
    )
    data = thumbs.web_thumbnail_png(html)
    image = Image.open(io.BytesIO(data))
    assert image.size == (724, 543)
    assert image.convert("RGB").getpixel((362, 271)) == (255, 0, 0)


# --- the route: GET /documents/{document_id}/thumbnail ----------------------------------------


@pytest.fixture()
def client(tmp_path: Path, design_storage) -> TestClient:
    return make_client(create_app(tmp_path / "engine-cache", storage=design_storage))


@pytest.fixture()
def seeded_web_document(client: TestClient) -> str:
    """A stored `doc_kind='web'` document, built the way the web suites build one."""
    core = client.app.state.core
    web_doc = core.web_new_doc("doc_thumb_web", "Thumbnail fixture", None)["web_doc"]
    ingested = core.web_ingest_html(
        web_doc,
        "home",
        "<section id='hero'><h1>Thumbnail</h1></section>",
        None,
        None,
    )
    assert ingested.get("web_doc"), ingested
    HybridRepository().create_document(ingested["web_doc"], doc_kind="web")
    return "doc_thumb_web"


@pytest.fixture()
def seeded_scene_document(client: TestClient) -> str:
    scene = json.loads(MINIMAL_SCENE_PATH.read_text())
    response = client.post("/documents", json={"title": "Thumbnail scene", "scene": scene})
    assert response.status_code == 200, response.text
    return response.json()["document"]["id"]


def test_web_thumbnail_generates_once_then_serves_from_cache(
    client: TestClient, seeded_web_document: str, monkeypatch
) -> None:
    calls = []

    def fake_capture(html, **kwargs):
        calls.append(html)
        return _png(724, 543)

    monkeypatch.setattr("lumen_api.document_thumbnails.web_thumbnail_png", fake_capture)
    first = client.get(f"/documents/{seeded_web_document}/thumbnail")
    assert first.status_code == 200, first.text
    assert first.headers["content-type"] == "image/png"
    second = client.get(f"/documents/{seeded_web_document}/thumbnail")
    assert second.status_code == 200, second.text
    assert len(calls) == 1  # the second hit came from the blob cache
    assert second.content == first.content
    # The capture ran against the document's own composed render, not a stub.
    assert "Thumbnail" in calls[0]


def test_matching_version_gets_immutable_caching(
    client: TestClient, seeded_web_document: str, monkeypatch
) -> None:
    monkeypatch.setattr(
        "lumen_api.document_thumbnails.web_thumbnail_png", lambda html, **kw: _png(7, 5)
    )
    version = client.get(f"/documents/{seeded_web_document}").json()["current_version"]
    fresh = client.get(f"/documents/{seeded_web_document}/thumbnail?v={version}")
    assert fresh.status_code == 200, fresh.text
    assert fresh.headers["cache-control"] == "private, max-age=31536000, immutable"
    stale = client.get(f"/documents/{seeded_web_document}/thumbnail?v=999999")
    assert stale.status_code == 200  # still serves the CURRENT bytes
    assert stale.headers["cache-control"] == "no-store"  # never cached under a stale key
    assert stale.content == fresh.content
    # No `v` at all is the same "do not cache this under a key I did not name" case.
    unversioned = client.get(f"/documents/{seeded_web_document}/thumbnail")
    assert unversioned.headers["cache-control"] == "no-store"


def test_thumbnail_regenerates_when_the_index_row_dangles(
    client: TestClient, seeded_web_document: str, monkeypatch
) -> None:
    # An index row whose blob is gone (erased bytes, a restored database) must not
    # 500 and must not serve nothing — it regenerates and re-claims the slot.
    repository = HybridRepository()
    version = client.get(f"/documents/{seeded_web_document}").json()["current_version"]
    repository.record_document_thumbnail(
        seeded_web_document, version, sha256="0" * 64, media_type="image/png"
    )
    calls = []

    def fake_capture(html, **kwargs):
        calls.append(html)
        return _png(64, 48)

    monkeypatch.setattr("lumen_api.document_thumbnails.web_thumbnail_png", fake_capture)
    response = client.get(f"/documents/{seeded_web_document}/thumbnail")
    assert response.status_code == 200, response.text
    assert len(calls) == 1
    assert response.content == _png(64, 48)
    # The dangling digest was replaced, so the next read is a cache hit again.
    recorded = repository.get_document_thumbnail(seeded_web_document, version)
    assert recorded is not None and recorded["sha256"] != "0" * 64


def test_scene_thumbnail_goes_through_the_engine_export(
    client: TestClient, seeded_scene_document: str, monkeypatch
) -> None:
    # The scene path is the engine's own PNG, downscaled — never the web capture.
    def refuse(*args, **kwargs):  # pragma: no cover - the assertion is that it is unused
        raise AssertionError("a scene document must not take the web capture path")

    monkeypatch.setattr("lumen_api.document_thumbnails.web_thumbnail_png", refuse)
    response = client.get(f"/documents/{seeded_scene_document}/thumbnail")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/png"
    image = Image.open(io.BytesIO(response.content))
    assert max(image.size) <= 724
    # And the bytes are cached under this document's version like the web ones.
    version = client.get(f"/documents/{seeded_scene_document}").json()["current_version"]
    assert HybridRepository().get_document_thumbnail(seeded_scene_document, version)


def test_scene_thumbnail_generates_once_then_serves_from_cache(
    client: TestClient, seeded_scene_document: str, monkeypatch
) -> None:
    # The web path's cache-hit proof, for the other generator: the engine export is
    # the expensive half of a scene thumbnail, so a second read must not pay it.
    real_export = client.app.state.core.export_preview
    calls = []

    def counting_export(*args, **kwargs):
        calls.append(args)
        return real_export(*args, **kwargs)

    monkeypatch.setattr(client.app.state.core, "export_preview", counting_export)
    first = client.get(f"/documents/{seeded_scene_document}/thumbnail")
    assert first.status_code == 200, first.text
    second = client.get(f"/documents/{seeded_scene_document}/thumbnail")
    assert second.status_code == 200, second.text
    assert len(calls) == 1  # the second hit came from the blob cache
    assert second.content == first.content


def test_generated_thumbnail_bytes_land_in_the_blob_store(
    client: TestClient, seeded_web_document: str, monkeypatch
) -> None:
    monkeypatch.setattr(
        "lumen_api.document_thumbnails.web_thumbnail_png", lambda html, **kw: _png(80, 60)
    )
    response = client.get(f"/documents/{seeded_web_document}/thumbnail")
    assert response.status_code == 200, response.text
    version = client.get(f"/documents/{seeded_web_document}").json()["current_version"]
    recorded = HybridRepository().get_document_thumbnail(seeded_web_document, version)
    assert recorded is not None
    media_type, data = make_blob_store(client.app).read_blob(recorded["sha256"])
    assert media_type == "image/png"
    assert data == response.content


def test_generation_failure_is_a_typed_502(
    client: TestClient, seeded_web_document: str, monkeypatch
) -> None:
    def refuse(html, **kwargs):
        raise thumbs.ThumbnailUnavailable("thumbnail.capture_failed", "boom")

    monkeypatch.setattr("lumen_api.document_thumbnails.web_thumbnail_png", refuse)
    response = client.get(f"/documents/{seeded_web_document}/thumbnail")
    assert response.status_code == 502, response.text
    assert response.json()["detail"]["code"] == "thumbnail.capture_failed"
    # A refusal must not leave a cache row claiming a thumbnail exists.
    version = client.get(f"/documents/{seeded_web_document}").json()["current_version"]
    assert HybridRepository().get_document_thumbnail(seeded_web_document, version) is None


def test_engine_helper_failure_is_a_typed_502(
    client: TestClient, seeded_scene_document: str, monkeypatch
) -> None:
    # `raise_on_error=False` does NOT cover a helper that never answered: `_run`
    # raises CoreError before that flag is read. Un-normalized it would leave the
    # route as a raw 500.
    def refuse(*args, **kwargs):
        raise CoreError("helper.process", "the helper process died")

    monkeypatch.setattr(client.app.state.core, "export_preview", refuse)
    response = client.get(f"/documents/{seeded_scene_document}/thumbnail")
    assert response.status_code == 502, response.text
    assert response.json()["detail"]["code"] == "thumbnail.export_failed"


def test_render_failure_is_a_typed_502_not_the_render_route_s_422(
    client: TestClient, seeded_web_document: str, monkeypatch
) -> None:
    # The real escape path: `render_web_document` converts its own CoreError with
    # `core_http_error` into a 422 `web_render.*`, which would propagate straight
    # out of this route. Patch the CORE so that whole conversion really runs.
    def refuse(*args, **kwargs):
        raise CoreError("web_render.failed", "the web renderer died")

    monkeypatch.setattr(client.app.state.core, "web_render", refuse)
    response = client.get(f"/documents/{seeded_web_document}/thumbnail")
    assert response.status_code == 502, response.text
    assert response.json()["detail"]["code"] == "thumbnail.render_failed"
    # And nothing was cached behind the refusal.
    version = client.get(f"/documents/{seeded_web_document}").json()["current_version"]
    assert HybridRepository().get_document_thumbnail(seeded_web_document, version) is None


def test_unknown_document_is_404(client: TestClient) -> None:
    response = client.get("/documents/doc_nope/thumbnail")
    assert response.status_code == 404
    # The route's own refusal, not the router's "no such path" — asserted so this
    # test cannot pass while the route is missing.
    assert response.json()["detail"]["code"] == "document.not_found"


# --- the scene branch preflights like the export route (2026-09-06) ---------------------------


def _brand_seed(version: int = 2) -> dict:
    """The seed `test_api` generates its brand kit from — it defines `surface.brand`."""
    return {
        "id": "brand_kit_thumbnail_tokens",
        "version": version,
        "name": "Thumbnail Tokens",
        "primary_color": "#075E68",
        "description": "Healthcare automation brand kit generated from seed inputs.",
        "secondary_color": "#0F766E",
        "accent_color": "#22C55E",
        "neutral_color": "#111827",
        "preferred_fonts": ["Source Sans 3", "Arial"],
        "logo_refs": [],
        "tone_words": ["clinical", "calm", "expert"],
        "website_url": "https://example.test",
        "style_guide_asset_ids": [],
        "sources": [],
        "default_mode": {
            "values": {
                "theme": "light",
                "density": "comfortable",
                "accessibility": "standard",
                "medium": "digital",
            }
        },
    }


def _token_scene(document_id: str) -> dict:
    """An agent-authored ad in miniature: a brand TOKEN fill, a HUG-sized text node,
    and no stored geometry anywhere (`computed: null`)."""
    scene = json.loads(MINIMAL_SCENE_PATH.read_text())
    scene["meta"]["id"] = document_id
    # The slot's length caps are what `test_api.preflightable_scene` relaxes so a
    # preflight can run at all; without it the fixture would prove the route's
    # diagnostics, not its rendering.
    slot = scene["slots"]["slot_contact_name"]
    slot["formatting"]["max_length"] = None
    slot["validation"]["samples"] = []
    slot["validation"]["max_length"] = None
    text = scene["nodes"]["node_contact_name"]
    text["size"] = {"width": {"kind": "hug"}, "height": {"kind": "hug"}}
    text["computed"] = None
    scene["nodes"]["node_brand_panel"] = {
        "id": "node_brand_panel",
        "name": "Brand panel",
        "kind": {"kind": "rect"},
        "transform": {
            "x": 20.0,
            "y": 60.0,
            "rotation": 0.0,
            "skew_x": 0.0,
            "skew_y": 0.0,
            "flip_x": False,
            "flip_y": False,
        },
        # FILL, not fixed: a fixed box carries enough geometry for the raw export to
        # place it (it just paints the magenta unresolved-paint sentinel over it), so
        # only a size the LAYOUT has to solve reproduces the blank card.
        "size": {
            "width": {"kind": "fill", "value": {"weight": 1.0}},
            "height": {"kind": "fill", "value": {"weight": 1.0}},
        },
        "children": [],
        "fills": [
            {
                "id": "paint_brand_panel",
                "paint": {"kind": "token", "token": "surface.brand"},
            }
        ],
        "strokes": [],
        "corner": {
            "top_left": 0.0,
            "top_right": 0.0,
            "bottom_right": 0.0,
            "bottom_left": 0.0,
        },
        "opacity": 1.0,
        "clip": False,
        "layout": None,
        "computed": None,
        "locked": False,
    }
    # In FRONT of the text, so the panel cannot paint over the copy it frames.
    scene["pages"]["page_a4"]["children"].insert(0, "node_brand_panel")
    return scene


@pytest.fixture()
def seeded_token_scene_document(client: TestClient) -> str:
    """A scene document shaped like every agent-authored ad: token fills, hug sizes,
    `computed: null`, and a brand kit attached that DEFINES the token."""
    generated = client.post("/brand-kits/generate", json={"seed": _brand_seed()})
    assert generated.status_code == 200, generated.text
    brand_kit_id = generated.json()["brand_kit"]["id"]

    created = client.post(
        "/documents",
        json={"title": "Token thumbnail", "scene": _token_scene("doc_thumb_tokens")},
    )
    assert created.status_code == 200, created.text
    document_id = created.json()["document"]["id"]

    attached = client.post(
        f"/documents/{document_id}/brand-kit",
        json={
            "brand_kit_id": brand_kit_id,
            "version": 2,
            "mode": {
                "values": {
                    "theme": "light",
                    "density": "comfortable",
                    "accessibility": "standard",
                    "medium": "digital",
                }
            },
            "snapshot_reason": "attach kit for thumbnail fixture",
        },
    )
    assert attached.status_code == 200, attached.text
    return document_id


def test_scene_thumbnail_resolves_tokens_and_geometry(
    client: TestClient, seeded_token_scene_document: str
) -> None:
    """A token-filled, unsolved scene (every agent-authored ad) used to export raw and come back
    as a blank white PNG (LUME0209 / LUME0205, raise_on_error=False). The route now preflights
    like the export route, so the card shows the design."""
    before = client.get(f"/documents/{seeded_token_scene_document}")
    assert before.status_code == 200, before.text

    response = client.get(f"/documents/{seeded_token_scene_document}/thumbnail")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/png"
    image = Image.open(io.BytesIO(response.content)).convert("RGB")
    colours = image.getcolors(maxcolors=1 << 20) or []
    non_white = [count for count, rgb in colours if rgb != (255, 255, 255)]
    assert non_white, "the thumbnail is blank: nothing but white pixels"
    assert (
        sum(non_white) > image.width * image.height * 0.05
    ), "barely any ink — tokens or geometry still unresolved"
    # The other half of the same bug, and the one the ink count cannot see: an
    # UNRESOLVED paint rasters as the engine's opaque magenta sentinel (LUME0213,
    # lumen-skia/src/render.rs), which is ink too. A card painted in it would pass
    # the assertion above while showing nobody's brand.
    assert (255, 0, 255) not in [
        rgb for _count, rgb in colours
    ], "the unresolved-paint sentinel is on the card: brand tokens did not resolve"

    # Read-only: preflighting for the card must not persist a thing.
    after = client.get(f"/documents/{seeded_token_scene_document}")
    assert after.status_code == 200, after.text
    assert after.json()["current_version"] == before.json()["current_version"]
    assert after.json()["scene"] == before.json()["scene"]
