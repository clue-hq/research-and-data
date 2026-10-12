"""Gallery thumbnails for Puck sites (Wave 2 Lane A, Task 18).

The first three tests pin the route's contract. The scenarios after them drive the real composed
app (``create_app`` over the Postgres test database, the test's own blob storage, the real site-kit
bundles and real hardened Chromium) through whole flows: a card per version, an agent section in
the card, failures never cached, nothing fetched from the network, missing bytes, a real picture.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from clue_design.storage import SOURCE_KEY_ASSET
from conftest import make_blob_store, make_client
from lumen_api import site_publish, site_render
from lumen_api.core import CoreError
from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app
from site_kit_support import (
    QUOTE_JS,
    QUOTE_SCHEMA,
    chromium_available,
    ensure_site_kit_dist,
    garner_brand,
    garner_site,
    hold_site_images,
    install_site_inputs,
    png,
    section_module,
    site_with_section,
    store_site,
)


@pytest.fixture()
def client(tmp_path: Path, design_storage) -> TestClient:
    ensure_site_kit_dist()
    return make_client(create_app(tmp_path / "engine-cache", storage=design_storage))


def stored(client: TestClient, document_id: str) -> tuple[dict, dict]:
    site, brand = hold_site_images(garner_site(document_id), garner_brand(), make_blob_store(client.app))
    store_site(site)
    install_site_inputs(client.app, brand)
    return site, brand


def test_a_site_thumbnail_is_captured_once_then_served_from_cache(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    if not chromium_available():
        pytest.skip("playwright chromium not installed")
    stored(client, "site_thumb")
    first = client.get("/documents/site_thumb/thumbnail?v=0")
    assert first.status_code == 200, first.text
    assert first.headers["cache-control"] == "private, max-age=31536000, immutable"
    assert Image.open(io.BytesIO(first.content)).size == (724, 543)

    def must_not_run(*_args: object, **_kwargs: object) -> bytes:
        raise AssertionError("a cached thumbnail must not be captured again")

    monkeypatch.setattr(site_publish, "site_thumbnail_png", must_not_run)
    assert client.get("/documents/site_thumb/thumbnail?v=0").content == first.content


def test_a_site_thumbnail_without_its_brand_is_a_typed_502(client: TestClient) -> None:
    from lumen_api.site_doc_inputs import brand_loader_not_composed

    stored(client, "site_thumb_nobrand")
    client.app.state.site_brand_loader = brand_loader_not_composed
    response = client.get("/documents/site_thumb_nobrand/thumbnail")
    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "thumbnail.render_failed"


def test_a_failed_site_render_is_labelled_render_failed(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from lumen_api.site_render import RENDER_TIMEOUT, SiteRenderError

    stored(client, "site_thumb_slow")

    def slow(*_args: object, **_kwargs: object) -> bytes:
        raise SiteRenderError(RENDER_TIMEOUT, "the site did not render within 20s")

    monkeypatch.setattr(site_publish, "site_thumbnail_png", slow)
    response = client.get("/documents/site_thumb_slow/thumbnail")
    assert response.status_code == 502
    assert response.json()["detail"] == {"code": "thumbnail.render_failed", "message": "the site did not render within 20s"}


# --- Scenarios ------------------------------------------------------------------------------------

_ASSET_REF = re.compile(r"/asset-store/([0-9a-f]{64})")
QUOTE_TEXT = "Fewer surprises for SCSD."


def needs_chromium() -> None:
    if not chromium_available():
        pytest.skip("playwright chromium not installed")


def thumbnail(client: TestClient, document_id: str, version: int | None = None):
    query = "" if version is None else f"?v={version}"
    return client.get(f"/documents/{document_id}/thumbnail{query}")


def card(response) -> Image.Image:
    """The 200 PNG of a thumbnail response, as an image (asserting its size)."""
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/png"
    image = Image.open(io.BytesIO(response.content))
    assert image.format == "PNG" and image.size == (724, 543)
    return image


def cached_row(document_id: str, version: int) -> dict | None:
    return HybridRepository().get_document_thumbnail(document_id, version)


def expect_render_failed(response) -> str:
    assert response.status_code == 502, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "thumbnail.render_failed", detail
    return detail["message"]


def quote_module(css: str = ""):
    return section_module("QuoteBand", QUOTE_JS, QUOTE_SCHEMA, css=css)


def quote_site(document_id: str, module) -> dict:
    return site_with_section(document_id, "QuoteBand", module.digest, {"id": "quote", "surface": "page", "quote": QUOTE_TEXT})


def hold_every_image(site: dict, brand: dict, blobs: Any) -> tuple[dict, dict]:
    """``hold_site_images`` widened to EVERY /asset-store digest the site and its brand name (the
    kit's logo, its fonts and the clones' images too), each swapped for distinct bytes this
    workspace holds, so nothing the rendered page names is missing from the store."""
    mapping: dict[str, str] = {}
    for index, old in enumerate(dict.fromkeys(_ASSET_REF.findall(json.dumps([site, brand])))):
        data = png((index % 256, 60 + index // 256, 90))
        blobs.register(data, media_type="image/png", source_key=SOURCE_KEY_ASSET)
        mapping[old] = hashlib.sha256(data).hexdigest()

    def swap(value: dict) -> dict:
        return json.loads(_ASSET_REF.sub(lambda m: "/asset-store/" + mapping[m.group(1)], json.dumps(value)))

    return swap(site), swap(brand)


class Recorder:
    """Call-through wrappers on site_publish's own names: how often a card was built, the HTML
    handed to inlining, and the HTML handed to the capture."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.builds = 0
        self.inlined_from: list[str] = []
        self.captured: list[str] = []
        real_build = site_publish.site_thumbnail_png
        real_inline = site_publish.inline_asset_store_refs
        real_capture = site_render.capture_site_screenshot

        def build(*args: Any, **kwargs: Any) -> bytes:
            self.builds += 1
            return real_build(*args, **kwargs)

        def inline(html: str, *args: Any, **kwargs: Any):
            self.inlined_from.append(html)
            return real_inline(html, *args, **kwargs)

        def capture(page: Any, css: str, **kwargs: Any) -> bytes:
            self.captured.append(page.html + css)
            return real_capture(page, css, **kwargs)

        monkeypatch.setattr(site_publish, "site_thumbnail_png", build)
        monkeypatch.setattr(site_publish, "inline_asset_store_refs", inline)
        monkeypatch.setattr(site_publish, "capture_site_screenshot", capture)


def test_each_version_gets_its_own_card_and_an_undo_gets_one_too(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    needs_chromium()
    doc = "site_thumb_versions"
    site, _brand = stored(client, doc)
    seen = Recorder(monkeypatch)

    v0 = thumbnail(client, doc, 0)
    card(v0)
    old_headline = site["pages"]["/"]["content"][0]["props"]["slots"]["headline"]
    assert old_headline in seen.captured[-1]

    # A manual save changes the home page's hero heading: version 1.
    edited = copy.deepcopy(site)
    new_headline = "Fewer surprises for SCSD, on the plan you already run."
    edited["pages"]["/"]["content"][0]["props"]["slots"]["headline"] = new_headline
    saved = client.put(f"/documents/{doc}/site", json={"site": edited, "base_version": 0})
    assert saved.status_code == 200, saved.text
    assert saved.json()["document"]["current_version"] == 1

    v1 = thumbnail(client, doc, 1)
    card(v1)
    assert seen.builds == 2, "the new version's card must be captured anew, not served from v0's row"
    assert new_headline in seen.captured[-1] and old_headline not in seen.captured[-1]
    assert v1.content != v0.content

    row0, row1 = cached_row(doc, 0), cached_row(doc, 1)
    assert row0 is not None and row1 is not None
    assert row0["sha256"] == hashlib.sha256(v0.content).hexdigest()
    assert row1["sha256"] == hashlib.sha256(v1.content).hexdigest()
    assert row0["sha256"] != row1["sha256"]

    # Undo moves to version 2 (v0's site again): it gets its own card, captured and cached.
    undone = client.post(f"/documents/{doc}/site/undo", json={"base_version": 1})
    assert undone.status_code == 200, undone.text
    assert undone.json()["document"]["current_version"] == 2
    v2 = thumbnail(client, doc, 2)
    card(v2)
    assert seen.builds == 3
    assert old_headline in seen.captured[-1] and new_headline not in seen.captured[-1]
    row2 = cached_row(doc, 2)
    assert row2 is not None and row2["sha256"] == hashlib.sha256(v2.content).hexdigest()
    # A caller still naming v1 gets the CURRENT card (v2's cached row, no rebuild) and no
    # permission to keep it under v1's key; naming v2 may keep it forever.
    stale = thumbnail(client, doc, 1)
    assert stale.content == v2.content and stale.headers["cache-control"] == "no-store"
    assert thumbnail(client, doc, 2).headers["cache-control"] == "private, max-age=31536000, immutable"
    assert seen.builds == 3


def test_an_agent_section_is_in_the_card_and_every_image_is_inlined(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    needs_chromium()
    doc = "site_thumb_agent_section"
    module = quote_module()
    site, brand = hold_every_image(quote_site(doc, module), garner_brand(), make_blob_store(client.app))
    store_site(site)
    install_site_inputs(client.app, brand, [module])
    seen = Recorder(monkeypatch)

    card(thumbnail(client, doc))

    (before,) = seen.inlined_from
    (captured,) = seen.captured
    assert QUOTE_TEXT in captured
    named = set(_ASSET_REF.findall(before))
    assert named, "the rendered page names the brand's images and fonts by /asset-store digest"
    blobs = make_blob_store(client.app)
    for digest in named:
        media_type, data = blobs.read_blob(digest)
        assert f"data:{media_type};base64,{base64.b64encode(data).decode('ascii')}" in captured, digest
    assert "/asset-store/" not in captured


def test_a_missing_section_module_is_never_cached_and_answers_once_it_is_stored(client: TestClient) -> None:
    needs_chromium()
    doc = "site_thumb_missing_module"
    module = quote_module()
    site, brand = hold_site_images(quote_site(doc, module), garner_brand(), make_blob_store(client.app))
    store_site(site)
    install_site_inputs(client.app, brand, [])  # the section store does not hold the module

    message = expect_render_failed(thumbnail(client, doc, 0))
    assert "QuoteBand" in message
    assert cached_row(doc, 0) is None
    # Asking again still fails (nothing poisoned the slot), then the module is stored: 200.
    expect_render_failed(thumbnail(client, doc, 0))
    assert cached_row(doc, 0) is None

    install_site_inputs(client.app, brand, [module])
    response = thumbnail(client, doc, 0)
    card(response)
    row = cached_row(doc, 0)
    assert row is not None and row["sha256"] == hashlib.sha256(response.content).hexdigest()


def test_a_missing_brand_is_never_cached_and_answers_once_it_is_composed(client: TestClient) -> None:
    needs_chromium()
    from lumen_api.site_doc_inputs import brand_loader_not_composed

    doc = "site_thumb_missing_brand"
    _site, brand = stored(client, doc)
    client.app.state.site_brand_loader = brand_loader_not_composed

    message = expect_render_failed(thumbnail(client, doc, 0))
    assert "site_brand_loader" in message
    assert cached_row(doc, 0) is None

    install_site_inputs(client.app, brand)
    response = thumbnail(client, doc, 0)
    card(response)
    row = cached_row(doc, 0)
    assert row is not None and row["sha256"] == hashlib.sha256(response.content).hexdigest()


class _CountingServer(ThreadingHTTPServer):
    """A local server that counts every connection it accepts and every request it is sent."""

    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _CountingHandler)
        self.connections = 0
        self.requests: list[str] = []

    def verify_request(self, request: Any, client_address: Any) -> bool:
        self.connections += 1
        return True


class _CountingHandler(BaseHTTPRequestHandler):
    def _answer(self) -> None:
        self.server.requests.append(f"{self.command} {self.path}")  # type: ignore[attr-defined]
        body = png((255, 0, 0))
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    do_GET = do_HEAD = do_POST = do_OPTIONS = _answer

    def log_message(self, *args: object) -> None:
        return None


def test_the_capture_loads_nothing_from_the_network(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    needs_chromium()
    server = _CountingServer()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        origin = f"http://127.0.0.1:{server.server_address[1]}"
        doc = "site_thumb_hostile_row"
        module = quote_module(css=f"body{{background:url({origin}/css.png)}}")
        # A hostile or legacy row, stored straight to the table (no save validation): its images
        # point at the network and its agent section's CSS reaches for it too.
        site = garner_site(doc)
        split = copy.deepcopy(site["pages"]["/analysis"]["content"][0])
        split["props"]["image"] = f"{origin}/beacon.png"
        site["pages"] = {
            "/": {
                "root": {"props": {"title": "Hostile row"}},
                "content": [split, {"type": "QuoteBand", "props": {"id": "quote", "surface": "page", "quote": QUOTE_TEXT}}],
            }
        }
        site["shell"]["header"]["accountLogo"] = f"{origin}/beacon.png"
        site["agent_sections"] = {"QuoteBand": module.digest}
        store_site(site)
        install_site_inputs(client.app, garner_brand(), [module])
        seen = Recorder(monkeypatch)

        card(thumbnail(client, doc))

        (captured,) = seen.captured
        assert f"{origin}/beacon.png" in captured and f"{origin}/css.png" in captured, (
            "the capture must have been handed the network references (else this proves nothing)"
        )
        assert server.requests == [] and server.connections == 0, server.requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_missing_image_bytes_still_make_a_card(client: TestClient) -> None:
    needs_chromium()
    doc = "site_thumb_missing_bytes"
    # Garner's site and brand as written: not one of their /asset-store digests has bytes here.
    store_site(garner_site(doc))
    install_site_inputs(client.app, garner_brand())
    card(thumbnail(client, doc))


def test_the_card_is_a_real_picture(client: TestClient) -> None:
    needs_chromium()
    stored(client, "site_thumb_picture")
    image = card(thumbnail(client, "site_thumb_picture")).convert("RGB")
    colours = image.getcolors(maxcolors=724 * 543)
    assert colours is not None and len(colours) > 64, len(colours or [])
    top = image.crop((0, 0, 724, 543 // 5))
    assert top.getextrema() != ((255, 255), (255, 255), (255, 255)), "the top fifth is uniformly white"


def test_a_core_error_from_the_site_arm_is_labelled_render_failed(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    stored(client, "site_thumb_core_error")

    def core_failure(*_args: object, **_kwargs: object) -> bytes:
        raise CoreError("helper.process", "the helper process died")

    monkeypatch.setattr(site_publish, "site_thumbnail_png", core_failure)
    response = thumbnail(client, "site_thumb_core_error")
    assert response.status_code == 502, response.text
    assert response.json()["detail"] == {"code": "thumbnail.render_failed", "message": "the helper process died"}
    assert cached_row("site_thumb_core_error", 0) is None
