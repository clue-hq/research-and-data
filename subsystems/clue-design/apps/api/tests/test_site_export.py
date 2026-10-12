"""Exporting a Puck site as a ZIP and as a PDF (Wave 2 Lane A, Task 22)."""

from __future__ import annotations

import hashlib
import io
import json
import re
import threading
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pymupdf
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import text

from conftest import make_blob_store, make_client
from lumen_api import web_export, web_pdf
from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app
from lumen_api.site_doc_inputs import brand_loader_not_composed
from lumen_api.site_publish import site_delivery_csp
from site_kit_support import (
    QUOTE_JS,
    QUOTE_SCHEMA,
    chromium_available,
    ensure_site_kit_dist,
    garner_brand,
    garner_site_without_clones,
    hold_site_images,
    install_site_inputs,
    section_module,
    store_site,
)
from test_agent_run_write_lock import create_document as create_scene_document
from test_site_publish_package import HOSTILE_JS, INTER_TTF, seed_font_face
from test_site_thumbnails import _CountingServer, hold_every_image
from test_web_export import create_web_document, ingest_content, seed_content


@pytest.fixture()
def client(tmp_path: Path, design_storage) -> TestClient:
    if not chromium_available():
        pytest.skip("playwright chromium not installed")
    ensure_site_kit_dist()
    return make_client(create_app(tmp_path / "engine-cache", storage=design_storage))


@pytest.fixture()
def site(client: TestClient) -> dict:
    site, brand = hold_site_images(garner_site_without_clones("site_export"), garner_brand(), make_blob_store(client.app))
    store_site(site)
    install_site_inputs(client.app, brand)
    return site


def test_the_zip_holds_every_page_its_bytes_and_folder_links(client: TestClient, site: dict) -> None:
    response = client.get("/documents/site_export/site/export")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    names = set(archive.namelist())
    assert {"index.html", "analysis/index.html", "manifest.json"} <= names
    held = site["pages"]["/analysis"]["content"][0]["props"]["image"].removeprefix("/asset-store/")
    assert f"assets/{held}.png" in names
    analysis = archive.read("analysis/index.html").decode()
    assert f"../assets/{held}.png" in analysis and f"/asset-store/{held}" not in analysis
    home = archive.read("index.html").decode()
    assert 'href="/analysis/"' in home and "<script" not in home.lower()
    assert "img-src 'self' data: file:" in home
    manifest = json.loads(archive.read("manifest.json"))
    assert manifest["delivery"] == "site" and [page["route"] for page in manifest["pages"]] == ["/", "/analysis"]


def test_the_pdf_prints_every_page(client: TestClient, site: dict) -> None:
    response = client.get("/documents/site_export/site/export.pdf")
    assert response.status_code == 200, response.text
    assert response.content.startswith(b"%PDF")
    with pymupdf.open(stream=response.content, filetype="pdf") as document:
        assert document.page_count >= 2


def test_a_web_document_is_not_exported_as_a_site(client: TestClient, site: dict) -> None:
    web = client.post("/documents", json={"doc_kind": "web", "title": "W"}).json()["document"]
    assert client.get(f"/documents/{web['id']}/site/export").json()["detail"]["code"] == "document.kind_unsupported"


# --- Scenarios ------------------------------------------------------------------------------------
# Whole exports over the real pieces: the composed app over the Postgres test database, this test's
# blob store, the real site-kit render bundles, the real cleaner and real (hardened) Chromium. Each
# one downloads the ZIP or the PDF over HTTP and reads it the way the person holding the file does:
# unzipped and opened from disk, or opened in a PDF reader.

_ASSET_REF = re.compile(r"/asset-store/([0-9a-f]{64})")
_FONT_FACE = re.compile(r"@font-face\s*\{([^}]*)\}")
HOME_TEXT = "lower medical spend in year one"
ANALYSIS_TEXT = "What the free analysis shows SCSD"
QUOTE_TEXT = "Fewer surprises for SCSD, every renewal."
STATIC_CSP_META = f'<meta http-equiv="Content-Security-Policy" content="{web_export._escape_attr(site_delivery_csp(meta=True, static_bundle=True))}">'


def export_zip(client: TestClient, document_id: str) -> zipfile.ZipFile:
    response = client.get(f"/documents/{document_id}/site/export")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    return zipfile.ZipFile(io.BytesIO(response.content))


def export_pdf(client: TestClient, document_id: str) -> bytes:
    response = client.get(f"/documents/{document_id}/site/export.pdf")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    return response.content


def pdf_page_texts(content: bytes) -> list[str]:
    """Each PDF page's text with its whitespace collapsed (a heading may wrap)."""
    with pymupdf.open(stream=content, filetype="pdf") as document:
        return [" ".join(page.get_text().split()) for page in document]


def first_page_with(texts: list[str], needle: str) -> int:
    hits = [index for index, page in enumerate(texts) if needle in page]
    assert hits, f"{needle!r} is on no PDF page"
    return hits[0]


def html_files(archive: zipfile.ZipFile) -> dict[str, str]:
    return {name: archive.read(name).decode("utf-8") for name in archive.namelist() if name.endswith(".html")}


def stored_every_image(client: TestClient, document_id: str, site: dict | None = None, sections: list | None = None) -> tuple[dict, dict]:
    """The site (Garner's own sections, a nav link to /analysis) and its brand with every
    /asset-store digest either names held by this workspace, stored and installed."""
    site, brand = hold_every_image(site or garner_site_without_clones(document_id), garner_brand(), make_blob_store(client.app))
    store_site(site)
    install_site_inputs(client.app, brand, sections or [])
    return site, brand


def colour_of(data: bytes) -> tuple[int, int, int]:
    return Image.open(io.BytesIO(data)).convert("RGB").getpixel((0, 0))


# a. The ZIP works offline --------------------------------------------------------------------------


@contextmanager
def offline_browser() -> Iterator[tuple[Any, list[str]]]:
    """A plain Chromium page for reading the unzipped folder from disk, with every http(s) request
    refused AND counted (the routed ones and any the page attempts outside the route)."""
    from playwright.sync_api import sync_playwright

    attempted: list[str] = []

    def refuse_the_network(route: Any) -> None:
        if route.request.url.startswith(("http://", "https://")):
            attempted.append(route.request.url)
            route.abort()
        else:
            route.continue_()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            # Tall enough that every image on either page is in view (a lazy image loads anyway).
            context = browser.new_context(viewport={"width": 1280, "height": 6000})
            context.route("**/*", refuse_the_network)
            page = context.new_page()
            page.on("request", lambda request: attempted.append(request.url) if request.url.startswith(("http://", "https://")) else None)
            yield page, attempted
        finally:
            browser.close()


def unzipped(client: TestClient, document_id: str, root: Path) -> Path:
    export_zip(client, document_id).extractall(root)
    assert (root / "index.html").is_file() and (root / "analysis" / "index.html").is_file()
    return root


def images_of(page: Any) -> list[dict]:
    return page.evaluate("Array.from(document.images).map(i => ({src: i.currentSrc || i.src, complete: i.complete, width: i.naturalWidth}))")


def test_the_zip_opened_from_disk_shows_every_image_and_reaches_nothing(client: TestClient, tmp_path: Path) -> None:
    stored_every_image(client, "site_offline")
    root = unzipped(client, "site_offline", tmp_path / "unzipped")
    with offline_browser() as (page, attempted):
        for path, text_on_page in ((root / "index.html", HOME_TEXT), (root / "analysis" / "index.html", ANALYSIS_TEXT)):
            page.goto(path.as_uri(), wait_until="load")
            assert text_on_page in " ".join(page.inner_text("body").split()), path
            images = images_of(page)
            assert images, f"{path} shows no image (the kit's logo at least)"
            assert all(image["complete"] and image["width"] > 0 for image in images), (path, images)
            assert all(image["src"].startswith("file://") for image in images), (path, images)
    assert attempted == [], attempted


def test_the_home_pages_nav_link_reaches_the_analysis_page_from_disk(client: TestClient, tmp_path: Path) -> None:
    stored_every_image(client, "site_offline_nav")
    root = unzipped(client, "site_offline_nav", tmp_path / "unzipped")
    with offline_browser() as (page, attempted):
        page.goto((root / "index.html").as_uri(), wait_until="load")
        # Following the header's nav link, as a reader of the unzipped folder does.
        nav = 'header a:has-text("The analysis")'
        href = page.get_attribute(nav, "href")
        page.click(nav)
        page.wait_for_load_state("load")
        assert page.url == (root / "analysis" / "index.html").as_uri(), (
            f"the nav link href={href!r} took the reader to {page.url}, not to the unzipped analysis page"
        )
        assert ANALYSIS_TEXT in " ".join(page.inner_text("body").split())
        assert all(image["complete"] and image["width"] > 0 for image in images_of(page))
    assert attempted == [], attempted


# b. Every page, its policy and its assets ---------------------------------------------------------


def test_every_exported_page_is_script_free_with_one_charset_the_static_policy_and_its_own_bytes(client: TestClient) -> None:
    stored_every_image(client, "site_policy")
    archive = export_zip(client, "site_policy")
    pages = html_files(archive)
    assert set(pages) == {"index.html", "analysis/index.html"}
    for name, html in pages.items():
        lowered = html.lower()
        assert "<script" not in lowered, name
        assert lowered.count("<meta charset") == 1, name
        assert html.count(STATIC_CSP_META) == 1 and html.count("Content-Security-Policy") == 1, name
        assert STATIC_CSP_META in html[: html.index("</head>")], name
        assert "/asset-store/" not in html, (name, _ASSET_REF.findall(html))
    # The static policy is the delivery policy with `file:` where the page loads its own files.
    policy = site_delivery_csp(meta=True, static_bundle=True)
    for directive in ("style-src", "img-src", "font-src", "media-src"):
        assert re.search(rf"(^|; ){directive} [^;]* file:(;|$)", policy), directive
    assert "script-src 'none'" in policy and "connect-src 'none'" in policy

    manifest = json.loads(archive.read("manifest.json"))
    in_zip = sorted(name for name in archive.namelist() if name.startswith("assets/"))
    assert in_zip and manifest["assets"] == in_zip
    # Every asset is named by some page, and every page reaches it by its own relative path.
    blobs = make_blob_store(client.app)
    for path in in_zip:
        digest = path.removeprefix("assets/").split(".")[0]
        assert archive.read(path) == blobs.read_blob(digest)[1], path
        assert path in pages["index.html"] or f"../{path}" in pages["analysis/index.html"], path
    assert "../assets/" not in pages["index.html"]


def test_a_digest_without_bytes_keeps_its_reference_and_the_manifest_names_it(client: TestClient) -> None:
    # Every other digest is held; this one names bytes the workspace never stored. Stored straight
    # to the table, so no save validation stands in the way (a legacy row, a restore without bytes).
    site, brand = hold_every_image(garner_site_without_clones("site_missing_bytes"), garner_brand(), make_blob_store(client.app))
    missing = hashlib.sha256(b"bytes this workspace never stored").hexdigest()
    site["pages"]["/analysis"]["content"][0]["props"]["image"] = f"/asset-store/{missing}"
    store_site(site)
    install_site_inputs(client.app, brand)

    archive = export_zip(client, "site_missing_bytes")
    analysis = archive.read("analysis/index.html").decode()
    assert f"/asset-store/{missing}" in analysis
    manifest = json.loads(archive.read("manifest.json"))
    assert not any(missing in name for name in archive.namelist())
    assert all(missing not in path for path in manifest["assets"])
    assert any(missing[:12] in warning and "missing from the asset store" in warning for warning in manifest["warnings"]), manifest["warnings"]
    # The held bytes still travel.
    assert manifest["assets"] and all(path in archive.namelist() for path in manifest["assets"])


# c. The font gate in the ZIP -----------------------------------------------------------------------


def test_only_the_embeddable_family_is_in_the_zip_as_the_gates_woff2(client: TestClient) -> None:
    blobs = make_blob_store(client.app)
    stored_ttf = seed_font_face(blobs, "asset_export_font_ofl", INTER_TTF.read_bytes(), "font/ttf")
    locked = seed_font_face(blobs, "asset_export_font_locked", b"wOF2" + b"\x33" * 96, "font/woff2")
    brand = garner_brand()
    fonts = brand["kit"]["assets"]["fonts"]
    open_sans, stix = fonts["body"]["family"], fonts["brand"]["family"]
    fonts["body"] = {
        **fonts["body"],
        "license": {"name": "OFL-1.1", "embeddable": False, "subsettable": True, "source_url": None, "restrictions": []},
        "faces": [{"weight": 400, "style": "normal", "asset_id": "asset_export_font_ofl", "source_url": None}],
    }
    fonts["brand"] = {
        **fonts["brand"],
        "license": {"name": "Commercial", "embeddable": False, "subsettable": False, "source_url": None, "restrictions": []},
        "faces": [{"weight": 400, "style": "normal", "asset_id": "asset_export_font_locked", "source_url": None}],
    }
    site, brand = hold_every_image(garner_site_without_clones("site_fonts"), brand, blobs)
    store_site(site)
    install_site_inputs(client.app, brand)

    archive = export_zip(client, "site_fonts")
    names = archive.namelist()
    shipped = [name for name in names if name.endswith(".woff2")]
    assert len(shipped) == 1, names
    (face_path,) = shipped
    digest = face_path.removeprefix("assets/").removesuffix(".woff2")
    data = archive.read(face_path)
    assert data[:4] == b"wOF2" and digest != stored_ttf and hashlib.sha256(data).hexdigest() == digest
    assert not any(locked in name or stored_ttf in name for name in names), names

    for name, prefix in (("index.html", ""), ("analysis/index.html", "../")):
        html = archive.read(name).decode()
        faces = []
        for body in _FONT_FACE.findall(html):
            family = re.search(r'font-family:\s*"?([^";]+)"?', body)
            src = re.search(r'url\(\s*"?([^")]+)"?\s*\)', body)
            faces.append((family.group(1) if family else "", src.group(1) if src else ""))
        assert faces == [(open_sans, f"{prefix}{face_path}")], (name, faces)
        assert stix not in [family for family, _src in faces]

    manifest = json.loads(archive.read("manifest.json"))
    assert face_path in manifest["assets"]
    assert manifest["font_families_included"] == [open_sans]
    assert manifest["font_families_excluded"] == [{"family": stix, "reason": "license not embeddable"}]
    assert any(stix in warning and "license not embeddable" in warning for warning in manifest["warnings"])


# d. An agent section exports -----------------------------------------------------------------------


def test_an_agent_section_is_in_the_zip_and_the_pdf_and_a_hostile_one_exports_clean(client: TestClient) -> None:
    quote = section_module("QuoteBand", QUOTE_JS, QUOTE_SCHEMA)
    site = garner_site_without_clones("site_section")
    site["agent_sections"] = {"QuoteBand": quote.digest}
    site["pages"]["/"]["content"].append({"type": "QuoteBand", "props": {"id": "quote", "surface": "page", "quote": QUOTE_TEXT}})
    stored_every_image(client, "site_section", site, [quote])

    home = export_zip(client, "site_section").read("index.html").decode()
    assert QUOTE_TEXT in home
    texts = pdf_page_texts(export_pdf(client, "site_section"))
    assert first_page_with(texts, QUOTE_TEXT) <= first_page_with(texts, ANALYSIS_TEXT)

    hostile = section_module("Hostile", HOSTILE_JS, QUOTE_SCHEMA)
    site = garner_site_without_clones("site_hostile")
    site["agent_sections"] = {"Hostile": hostile.digest}
    site["pages"]["/"]["content"].append({"type": "Hostile", "props": {"id": "h", "surface": "page", "quote": "Still here."}})
    stored_every_image(client, "site_hostile", site, [hostile])
    archive = export_zip(client, "site_hostile")
    for name, html in html_files(archive).items():
        lowered = html.lower()
        for gone in ("<script", "onerror", "javascript:", "<iframe", "collector.example"):
            assert gone not in lowered, (name, gone)
    assert "Still here." in archive.read("index.html").decode()
    assert not any("collector" in name for name in archive.namelist())
    assert any("Still here." in page for page in pdf_page_texts(export_pdf(client, "site_hostile")))


# e. The PDF prints every page, with its images, and loads nothing ---------------------------------


def test_the_pdf_prints_the_pages_in_order_with_the_held_images(client: TestClient) -> None:
    site, _brand = stored_every_image(client, "site_pdf")
    content = export_pdf(client, "site_pdf")
    texts = pdf_page_texts(content)
    home, analysis = first_page_with(texts, HOME_TEXT), first_page_with(texts, ANALYSIS_TEXT)
    assert home < analysis, texts

    digest = _ASSET_REF.fullmatch(site["pages"]["/analysis"]["content"][0]["props"]["image"]).group(1)
    expected = colour_of(make_blob_store(client.app).read_blob(digest)[1])
    with pymupdf.open(stream=content, filetype="pdf") as document:
        page = document[analysis]
        images = page.get_images(full=True)
        assert images, f"PDF page {analysis} (the analysis page's split band) holds no image"
        colours = []
        for image in images:
            pixmap = pymupdf.Pixmap(document, image[0])
            if pixmap.colorspace is None or pixmap.colorspace.n != 3:
                pixmap = pymupdf.Pixmap(pymupdf.csRGB, pixmap)
            colours.append(tuple(pixmap.pixel(pixmap.width // 2, pixmap.height // 2)[:3]))
    # The split band's own picture, not Chromium's broken-image icon.
    assert any(all(abs(a - b) <= 2 for a, b in zip(colour, expected)) for colour in colours), (expected, colours)


def test_the_pdf_of_a_site_that_names_the_network_reaches_none_of_it(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    printed: list[list[str]] = []
    real_print = web_pdf.render_pages_pdf

    def recording(htmls: list[str], **kwargs: Any) -> bytes:
        printed.append(list(htmls))
        return real_print(htmls, **kwargs)

    monkeypatch.setattr(web_pdf, "render_pages_pdf", recording)
    server = _CountingServer()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        origin = f"http://127.0.0.1:{server.server_address[1]}"
        # A hostile or legacy row, stored straight to the table (no save validation): its images
        # point at a local server that counts every connection.
        site = garner_site_without_clones("site_pdf_network")
        site["pages"]["/analysis"]["content"][0]["props"]["image"] = f"{origin}/beacon.png"
        site["shell"]["header"]["accountLogo"] = f"{origin}/logo.png"
        stored_every_image(client, "site_pdf_network", site)

        texts = pdf_page_texts(export_pdf(client, "site_pdf_network"))
        assert first_page_with(texts, HOME_TEXT) < first_page_with(texts, ANALYSIS_TEXT)
        assert server.requests == [] and server.connections == 0, server.requests
        (htmls,) = printed
        assert len(htmls) == 2
        # The render and the cleaner already dropped every reference to the server (the first layer).
        assert all(origin not in html for html in htmls)

        # The print itself, handed html that DOES name the server (an image, a CSS background, a
        # stylesheet, a font): the hardened print reaches none of it, while the same html printed
        # the web path's way does reach it, so the counter is live and `hardened` is what stops it.
        beacons = (
            f'<!doctype html><html><head><link rel="stylesheet" href="{origin}/sheet.css">'
            f'<style>@font-face{{font-family:B;src:url({origin}/font.woff2)}} body{{font-family:B;background:url({origin}/bg.png)}}</style>'
            f'</head><body><h1>{HOME_TEXT}</h1><img src="{origin}/img.png" alt=""></body></html>'
        )
        assert pdf_page_texts(real_print([beacons], hardened=True)) and server.connections == 0, server.requests
        real_print([beacons])
        assert server.connections > 0 and any("/img.png" in request for request in server.requests), server.requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_the_hardened_print_applies_the_print_sheet_as_the_web_path_does() -> None:
    if not chromium_available():
        pytest.skip("playwright chromium not installed")
    # JavaScript is off in the hardened print, so the sheet rides inside the html instead of
    # add_style_tag. Its `html, body { margin: 0 }` is what lets a band reach the sheet's left edge
    # (Chromium's default body margin is 8px, a white strip at 72 dpi's first pixels).
    band = '<!doctype html><html><head></head><body><section style="background:rgb(10,200,30);height:300px"></section></body></html>'

    def left_edge(content: bytes) -> tuple[int, int, int]:
        with pymupdf.open(stream=content, filetype="pdf") as document:
            pixmap = document[0].get_pixmap(dpi=72)
            return tuple(pixmap.pixel(2, 100)[:3])

    hardened, web = left_edge(web_pdf.render_pages_pdf([band], hardened=True)), left_edge(web_pdf.render_pages_pdf([band]))
    assert hardened == web and all(abs(a - b) <= 2 for a, b in zip(hardened, (10, 200, 30))), (hardened, web)


# f. Refusals and parity, over HTTP, for both routes -----------------------------------------------

ROUTES = ("/site/export", "/site/export.pdf")


def refused(response, status: int, code: str) -> dict:
    assert response.status_code == status, response.text
    detail = response.json()["detail"]
    assert detail["code"] == code, detail
    return detail


def test_both_routes_refuse_what_they_cannot_export(client: TestClient) -> None:
    quote = section_module("QuoteBand", QUOTE_JS, QUOTE_SCHEMA)
    site = garner_site_without_clones("site_no_module")
    site["agent_sections"] = {"QuoteBand": quote.digest}
    site["pages"]["/"]["content"].append({"type": "QuoteBand", "props": {"id": "quote", "surface": "page", "quote": QUOTE_TEXT}})
    stored_every_image(client, "site_no_module", site, [])  # the section store lacks the module
    for route in ROUTES:
        detail = refused(client.get(f"/documents/site_no_module{route}"), 409, "render.section_module_missing")
        assert "QuoteBand" in detail["message"], detail

    store_site(garner_site_without_clones("site_no_brand"))
    client.app.state.site_brand_loader = brand_loader_not_composed  # the default: no brand builder
    for route in ROUTES:
        refused(client.get(f"/documents/site_no_brand{route}"), 503, "site_inputs.unavailable")

    web = create_web_document(client)
    scene = create_scene_document(client)
    for other in (web["id"], scene["id"]):
        for route in ROUTES:
            refused(client.get(f"/documents/{other}{route}"), 409, "document.kind_unsupported")
    for route in ROUTES:
        refused(client.get(f"/documents/doc_nowhere{route}"), 404, "document.not_found")


def test_the_download_is_named_for_the_title_and_the_id(client: TestClient) -> None:
    site = garner_site_without_clones("site_named_download")
    site["title"] = "Garner × SCSD: The Analysis!"
    stored_every_image(client, "site_named_download", site)
    assert HybridRepository().require_document("site_named_download")["title"] == "Garner × SCSD: The Analysis!"
    for route, extension in zip(ROUTES, ("zip", "pdf")):
        response = client.get(f"/documents/site_named_download{route}")
        assert response.status_code == 200, response.text
        assert response.headers["content-disposition"] == f'attachment; filename="garner-scsd-the-analysis-site_nam.{extension}"'


def finalize(document_id: str) -> None:
    """No route finalizes a site or a web document (POST /finalize is the scene-template path), so
    the status column is set the way test_site_lane_a_scenarios does it."""
    repo = HybridRepository()
    repo._bridge._run(
        lambda conn: conn.execute(
            text("UPDATE design_document SET status = 'finalized' WHERE id = :d AND workspace_id = :w"),
            {"d": document_id, "w": repo.workspace_id},
        )
    )
    assert repo.require_document(document_id)["status"] == "finalized"


def test_a_finalized_site_exports_as_a_finalized_web_document_does(client: TestClient) -> None:
    # The web exports read the document and never ask whether it is finalized: a finalized web
    # document still downloads, as a ZIP and as a PDF.
    web = create_web_document(client)
    seed_content(client, web["id"], ingest_content(client, web["id"]))
    finalize(web["id"])
    web_zip = client.get(f"/documents/{web['id']}/web/export")
    web_print = client.get(f"/documents/{web['id']}/web/export.pdf")
    assert (web_zip.status_code, web_print.status_code) == (200, 200), (web_zip.text, web_print.text)

    stored_every_image(client, "site_finalized")
    before = export_zip(client, "site_finalized")
    finalize("site_finalized")
    after = export_zip(client, "site_finalized")
    assert html_files(after) == html_files(before)
    assert export_pdf(client, "site_finalized").startswith(b"%PDF")
