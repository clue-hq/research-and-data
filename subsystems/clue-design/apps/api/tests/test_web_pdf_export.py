"""Website PDF export: the whole site, every page, one PDF.

Drives the real route end to end — real repository, real core helper, real node
Tailwind compile, real Chromium — because the only thing worth asserting is that a
two-page site comes back as a PDF with at least two pages in it. The capture is
skipped honestly (never failed) when no browser is installed, the way the
thumbnail suite skips: the probe LAUNCHES a browser, so it lives in the test body
rather than in a collection-time `skipif`.
"""

from __future__ import annotations

import functools

import pymupdf
import pytest
from fastapi.testclient import TestClient

from conftest import make_client

from lumen_api.main import create_app

# `test_web_export` is this file's nearest peer (it owns the ZIP export these pages
# also feed), and it already carries the F5 helpers — so the site fixture is built
# from ITS copies rather than planting a third one here.
from test_web_export import (
    _empty_page,
    create_scene_document,
    create_web_document,
    seed_content,
)

# Every sheet is A4 — 210mm expressed in PDF points. The layout inside it is the
# 768px `md:` tablet layout, which fits A4's 794px unscaled; the sheet SIZE is the
# thing asserted here, and the layout is asserted by the grid test below.
PAGE_WIDTH_PT = 210 / 25.4 * 72

PAGE_HTML = """
<section id="hero" class="bg-light">
  <div class="mx-auto max-w-[1200px] px-6 py-24 flex flex-col items-center gap-6">
    <h1 data-variant="display">{heading}</h1>
    <p class="text-muted">A page of the site the PDF has to contain.</p>
  </div>
</section>
"""

# Three columns from `md:` up, stacked below it. At the 768px viewport this export
# prints at, the three headings sit side by side on ONE row; in the mobile layout a
# margin-shrunk (<768px) box would fall back to, they stack down the page.
GRID_HTML = """
<section id="cards" class="bg-light">
  <div class="mx-auto max-w-[1200px] px-6 py-24 grid grid-cols-1 md:grid-cols-3 gap-6">
    <div class="p-6"><h3>Alpha</h3></div>
    <div class="p-6"><h3>Bravo</h3></div>
    <div class="p-6"><h3>Charlie</h3></div>
  </div>
</section>
"""


@functools.lru_cache(maxsize=None)
def _chromium_available() -> bool:
    # Cached: the probe LAUNCHES a browser, so a session that asks twice pays once.
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            pw.chromium.launch(headless=True).close()
        return True
    except Exception:
        return False


@pytest.fixture()
def client(tmp_path, design_storage) -> TestClient:
    return make_client(create_app(tmp_path / "engine-cache", storage=design_storage))


def _two_page_site(client: TestClient) -> dict:
    """A stored web document with a home page and a pricing page, both with content."""
    document = create_web_document(client)
    response = client.post(
        f"/documents/{document['id']}/web/operations",
        json={
            "operations": [
                {"kind": "add_page", "page": _empty_page("pricing", "/pricing")}
            ],
            "base_version": document["current_version"],
            "intent": "add pricing page",
        },
    )
    assert response.status_code == 200, response.text

    core = client.app.state.core
    web_doc = client.get(f"/documents/{document['id']}").json()["scene"]
    for page_id, heading in (("home", "Home"), ("pricing", "Pricing")):
        ingested = core.web_ingest_html(
            web_doc, page_id, PAGE_HTML.format(heading=heading), None, None
        )
        errors = [
            d
            for d in ingested.get("diagnostics", [])
            if d.get("severity") == "error"
        ]
        assert not errors, ingested.get("diagnostics")
        web_doc = ingested["web_doc"]
    seed_content(client, document["id"], web_doc)
    return document


def test_web_pdf_export_returns_every_page_of_the_site(client: TestClient) -> None:
    if not _chromium_available():
        pytest.skip("playwright chromium not installed")

    document = _two_page_site(client)
    response = client.get(f"/documents/{document['id']}/web/export.pdf")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == (
        f'attachment; filename="my-site-{document["id"][:8]}.pdf"'
    )

    # Two site pages, each printing at least one sheet — a homepage-only PDF is the
    # bug this asserts against, so the floor is the page COUNT, not "a valid PDF".
    with pymupdf.open(stream=response.content, filetype="pdf") as pdf:
        assert pdf.page_count >= 2
        widths = [page.rect.width for page in pdf]
        text = "\n".join(page.get_text() for page in pdf)
    # ...and every sheet is A4, the paper this export paginates onto.
    assert all(abs(width - PAGE_WIDTH_PT) <= 1 for width in widths), widths
    # ...and it is THIS site: both headings are in the printed text, so a PDF of two
    # copies of the homepage would fail here even though its page count passed.
    assert "Home" in text and "Pricing" in text


def test_web_pdf_export_prints_the_tablet_layout_not_the_mobile_one(
    client: TestClient,
) -> None:
    if not _chromium_available():
        pytest.skip("playwright chromium not installed")

    document = create_web_document(client)
    core = client.app.state.core
    web_doc = client.get(f"/documents/{document['id']}").json()["scene"]
    ingested = core.web_ingest_html(web_doc, "home", GRID_HTML, None, None)
    errors = [
        d for d in ingested.get("diagnostics", []) if d.get("severity") == "error"
    ]
    assert not errors, ingested.get("diagnostics")
    seed_content(client, document["id"], ingested["web_doc"])

    response = client.get(f"/documents/{document['id']}/web/export.pdf")
    assert response.status_code == 200, response.text

    with pymupdf.open(stream=response.content, filetype="pdf") as pdf:
        words = pdf[0].get_text("words")
    # (x0, y0, x1, y1, word, ...) — the top of each heading's box is what matters.
    tops = {
        word[4]: word[1] for word in words if word[4] in {"Alpha", "Bravo", "Charlie"}
    }
    assert set(tops) == {"Alpha", "Bravo", "Charlie"}, tops
    # One row: the `md:` three-column grid applied. Stacked mobile columns would sit
    # a whole card apart vertically, which is orders of magnitude past this slack.
    assert max(tops.values()) - min(tops.values()) <= 2, tops


def test_web_pdf_export_refuses_a_scene_document(client: TestClient) -> None:
    # No browser needed: the kind check happens before anything is rendered.
    document = create_scene_document(client)
    response = client.get(f"/documents/{document['id']}/web/export.pdf")
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "document.kind_unsupported"


def test_web_pdf_export_persists_nothing(client: TestClient) -> None:
    if not _chromium_available():
        pytest.skip("playwright chromium not installed")

    document = _two_page_site(client)
    before = client.get(f"/documents/{document['id']}").json()["current_version"]
    assert client.get(f"/documents/{document['id']}/web/export.pdf").status_code == 200
    after = client.get(f"/documents/{document['id']}").json()
    assert after["current_version"] == before
    # ...and no publish was put on the air by the package build.
    state = client.get(f"/documents/{document['id']}/web/publish")
    assert state.status_code == 200, state.text
    assert not state.json().get("published")
