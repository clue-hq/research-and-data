"""Website-mode static export + publish (P4).

Drives the real core helper (set LUMEN_CORE_HELPER to the release binary) and the
real node Tailwind toolchain (scripts/web_static_css.mjs) end-to-end: an export
is a full zip, a publish is a self-contained served page. Temp DBs + asset store
via the shared `client` fixture.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clue_design.storage import SOURCE_KEY_ASSET

from conftest import make_blob_store, make_client
from PIL import Image

from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app
from lumen_api.web_export import _CompiledTheme, _build_input_css


REPO_ROOT = Path(__file__).resolve().parents[3]
ACME_KIT_PATH = REPO_ROOT / "crates/lumen-core/fixtures/brand_kits/acme_full.json"

SAMPLE_HTML = """
<header id="site_header" class="bg-light border-b border-border">
  <div class="mx-auto max-w-[1200px] px-6 py-4 flex items-center justify-between">
    <p data-variant="overline" class="text-primary">Acme</p>
    <a data-button="primary" href="https://acme.test/demo">Get started</a>
  </div>
</header>
<section id="hero" class="bg-light">
  <div class="mx-auto max-w-[1200px] px-6 py-24 flex flex-col items-center gap-6 text-center">
    <p data-variant="overline" class="text-primary">Developer tools</p>
    <h1 data-variant="display" class="max-w-[820px]">Ship faster with Acme</h1>
    <p class="text-muted max-w-[640px]">Acme helps teams build and launch quickly.</p>
    <a data-button="primary" href="https://acme.test/demo">Get started</a>
  </div>
</section>
<footer id="site_footer" class="bg-dark">
  <div class="mx-auto max-w-[1200px] px-6 py-12 flex items-center justify-between">
    <p data-variant="small" class="text-inverse">Acme</p>
    <a data-button="link" href="https://acme.test/privacy">Privacy</a>
  </div>
</footer>
"""


@pytest.fixture()
def client(tmp_path: Path, design_storage) -> TestClient:
    app = create_app(tmp_path / "engine-cache", storage=design_storage)
    return make_client(app)


def create_web_document(client: TestClient, **extra) -> dict:
    response = client.post(
        "/documents", json={"doc_kind": "web", "title": "My site", **extra}
    )
    assert response.status_code == 200, response.text
    return response.json()["document"]


def create_scene_document(client: TestClient) -> dict:
    scene = json.loads(
        (REPO_ROOT / "crates/lumen-core/fixtures/minimal_scene.json").read_text()
    )
    response = client.post("/documents", json={"title": "A scene", "scene": scene})
    assert response.status_code == 200, response.text
    return response.json()["document"]


def ingest_content(client: TestClient, document_id: str) -> dict:
    web_doc = client.get(f"/documents/{document_id}").json()["scene"]
    response = client.app.state.core.web_ingest_html(
        web_doc, "home", SAMPLE_HTML, None, None
    )
    errors = [d for d in response.get("diagnostics", []) if d.get("severity") == "error"]
    assert not errors, response.get("diagnostics")
    return response["web_doc"]


def seed_content(client: TestClient, document_id: str, web_doc: dict) -> None:
    store = HybridRepository()
    store.update_web_document(
        document_id,
        web_doc,
        intent="seed",
        checkpoint_label="seed",
        operations=[{"kind": "replace_web_doc"}],
        inverse_operations=None,
        push_undo=False,
    )


def get_document(client: TestClient, document_id: str) -> dict:
    return client.get(f"/documents/{document_id}").json()


def seed_document(client: TestClient, web_doc: dict | None = None, **extra) -> dict:
    """Create a web doc + install the sample landing page (or a provided doc)."""
    document = create_web_document(client, **extra)
    content = web_doc if web_doc is not None else ingest_content(client, document["id"])
    seed_content(client, document["id"], content)
    return document


def export_zip(client: TestClient, document_id: str) -> tuple[dict[str, bytes], str, dict]:
    response = client.get(f"/documents/{document_id}/web/export")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    files = {name: archive.read(name) for name in archive.namelist()}
    html = files["index.html"].decode("utf-8")
    manifest = json.loads(files["manifest.json"].decode("utf-8"))
    return files, html, manifest


def find_node(web_doc: dict, kind: str) -> str:
    nodes = web_doc["pages"][0]["nodes"]
    return next(nid for nid, node in nodes.items() if node.get("kind") == kind)


# --- (a0) the input CSS the static compile is fed ---------------------------


def test_build_input_css_carries_colors_geometry_and_utility_rules() -> None:
    """The published page's `@theme` block must carry the SAME three channels
    the editor's `theme_block` does, or brand geometry silently no-ops on every
    published page while it works on the canvas."""
    theme = _CompiledTheme(
        tokens={"primary": "#4FD3C8"},
        geometry={
            "radius-button": "4px",
            "shadow-brand": "0 15.93px 31.86px -8px #32325D1F",
            "border-width-card": "1px",
            "spacing-section": "96px",
        },
        utility_css="@utility border-w-card { border-width: var(--border-width-card); }\n",
    )
    css = _build_input_css(theme)

    assert "  --color-primary: #4FD3C8;" in css
    assert "  --radius-button: 4px;" in css
    assert "  --shadow-brand: 0 15.93px 31.86px -8px #32325D1F;" in css
    assert "  --border-width-card: 1px;" in css
    assert "  --spacing-section: 96px;" in css
    # Every var lands INSIDE the block; `@utility` is top-level, so after it.
    block = css.index("@theme {")
    close = css.index("\n}", block)
    assert css.index("--radius-button") < close
    assert css.index("@utility border-w-card") > close
    assert css.endswith("\n")


def test_build_input_css_without_geometry_is_unchanged() -> None:
    """An engine too old to answer `geometry`/`utility_css` still compiles —
    the export never hard-fails on a thin theme payload."""
    css = _build_input_css(_CompiledTheme(tokens={"primary": "#000000"}, geometry={}, utility_css=""))
    assert css == '@import "tailwindcss";\n@theme {\n  --color-primary: #000000;\n}\n'


# --- (a) export zip of a seeded doc -----------------------------------------


def test_export_zip_has_core_files(client: TestClient) -> None:
    document = seed_document(client)
    files, html, manifest = export_zip(client, document["id"])

    assert "index.html" in files
    assert "site.css" in files
    assert "manifest.json" in files

    # Delivery html is un-instrumented, at most the one platform runtime script,
    # and links the compiled stylesheet.
    assert "data-node-id" not in html
    assert html.count("<script") <= 1
    assert '<link rel="stylesheet" href="site.css">' in html

    css = files["site.css"].decode("utf-8")
    assert css.strip(), "site.css is non-empty"
    # A token var the page actually uses (text-primary -> var(--color-primary)).
    assert "--color-primary" in css
    assert ".bg-light" in css

    assert manifest["schema_version"] == 2
    assert manifest["document_id"] == document["id"]
    assert manifest["doc_version"] == get_document(client, document["id"])["current_version"]
    assert "index.html" in manifest["files"]
    assert "manifest.json" in manifest["files"]


GEOMETRY_HTML = """
<section id="hero" class="bg-light py-section">
  <div class="mx-auto max-w-[1200px] px-6 flex flex-col gap-stack">
    <div class="bg-card p-card rounded-card shadow-brand border border-border border-w-card">
      <h1 data-variant="h2">Brand geometry</h1>
      <p class="text-muted">Corners, elevation, hairlines and rhythm, by name.</p>
      <a data-button="primary" class="rounded-button shadow-card" href="https://acme.test/demo">Get started</a>
    </div>
    <div class="border-t border-border border-w-divider"></div>
    <div class="rounded-badge bg-primary px-3"><p data-variant="small" class="text-inverse">New</p></div>
  </div>
</section>
"""


def test_export_css_carries_brand_geometry(client: TestClient) -> None:
    """A published page uses the SAME geometry mechanism the canvas does — the
    static compile rebuilds `@theme` from the engine's geometry map, and the
    `border-w-*` names ride the engine-built `@utility` rules.

    Tailwind v4 tree-shakes unused theme vars, so this asserts only over
    geometry the page actually authors (same posture as the `--color-primary`
    assertion above)."""
    document = create_web_document(client)
    web_doc = client.get(f"/documents/{document['id']}").json()["scene"]
    response = client.app.state.core.web_ingest_html(
        web_doc, "home", GEOMETRY_HTML, None, None
    )
    errors = [d for d in response.get("diagnostics", []) if d.get("severity") == "error"]
    assert not errors, response.get("diagnostics")
    seed_content(client, document["id"], response["web_doc"])

    files, _html, _manifest = export_zip(client, document["id"])
    css = files["site.css"].decode("utf-8")

    # The theme vars reached the compile.
    assert "--radius-button" in css
    assert "--radius-card" in css
    assert "--radius-badge" in css
    assert "--spacing-section" in css
    assert "--spacing-stack" in css
    assert "--spacing-card" in css
    assert "--border-width-card" in css
    assert "--border-width-divider" in css
    # The utilities compiled against them.
    assert "border-radius: var(--radius-button)" in css
    assert "padding: var(--spacing-card)" in css
    assert "padding-block: var(--spacing-section)" in css
    assert "gap: var(--spacing-stack)" in css
    # `border-w-*` has no Tailwind namespace — it exists only because the
    # engine's `@utility` rules travelled with the theme.
    assert "border-width: var(--border-width-card)" in css
    assert "border-width: var(--border-width-divider)" in css
    # Shadows compile through Tailwind's own `--tw-shadow` plumbing.
    assert ".shadow-brand" in css
    assert ".shadow-card" in css
    assert "box-shadow" in css


def test_publish_html_carries_brand_geometry(
    client: TestClient, workspace_id: str
) -> None:
    """The publish path shares the pipeline, so it inherits geometry too — but
    it inlines the CSS rather than linking it, so prove it separately."""
    document = create_web_document(client)
    web_doc = client.get(f"/documents/{document['id']}").json()["scene"]
    response = client.app.state.core.web_ingest_html(
        web_doc, "home", GEOMETRY_HTML, None, None
    )
    seed_content(client, document["id"], response["web_doc"])

    published = client.post(
        f"/documents/{document['id']}/web/publish", json={"slug": "geometry-page"}
    )
    assert published.status_code == 200, published.text
    served = client.get(f"/w/{workspace_id}/p/geometry-page")
    assert served.status_code == 200, served.text
    html = served.text
    assert "--radius-button" in html
    assert "border-width: var(--border-width-card)" in html


def test_export_preserves_semantic_structured_body_without_editor_state(
    client: TestClient,
) -> None:
    document = create_web_document(client)
    web_doc = ingest_content(client, document["id"])
    body_id = next(
        node_id
        for node_id, node in web_doc["pages"][0]["nodes"].items()
        if node.get("kind") == "text" and node.get("variant") == "body"
    )
    web_doc["pages"][0]["nodes"][body_id]["content"] = {
        "schema_version": 1,
        "blocks": [
            {
                "type": "paragraph",
                "children": [{"type": "text", "text": "Intro"}],
            },
            {
                "type": "list",
                "list_type": "unordered",
                "items": [
                    {"children": [{"type": "text", "text": "First"}]},
                    {
                        "children": [{"type": "text", "text": "Second"}],
                        "nested": [
                            {
                                "type": "list",
                                "list_type": "ordered",
                                "items": [
                                    {
                                        "children": [
                                            {"type": "text", "text": "Nested"}
                                        ]
                                    }
                                ],
                            }
                        ],
                    },
                ],
            },
        ],
    }
    seed_content(client, document["id"], web_doc)
    _files, html, _manifest = export_zip(client, document["id"])
    assert (
        "<p>Intro</p><ul><li>First</li>"
        "<li>Second<ol><li>Nested</li></ol></li></ul>"
    ) in html
    assert "data-lexical" not in html
    assert "contenteditable" not in html
    assert "lumen-rich-editor-root" not in html


# --- (b) asset round-trip ---------------------------------------------------


def test_export_copies_and_rewrites_image_assets(client: TestClient) -> None:
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), (120, 80, 200)).save(buffer, "PNG")
    upload = client.post(
        "/assets", files={"file": ("hero.png", buffer.getvalue(), "image/png")}
    )
    assert upload.status_code == 200, upload.text
    record = upload.json()["asset"]
    asset_id = record["id"]
    digest = record["media"]["digest"]["value"]

    document = create_web_document(client)
    web_doc = ingest_content(client, document["id"])
    container = find_node(web_doc, "container")
    image_id = "export_img"
    web_doc["pages"][0]["nodes"][image_id] = {
        "id": image_id,
        "kind": "image",
        "asset_id": asset_id,
        "alt": "Export hero",
        "classes": "",
    }
    web_doc["pages"][0]["nodes"][container].setdefault("children", []).append(image_id)
    web_doc.setdefault("assets", {})[asset_id] = record

    seed_content(client, document["id"], web_doc)
    files, html, _manifest = export_zip(client, document["id"])

    assert f"assets/{digest}.png" in files
    assert f"assets/{digest}.png" in html
    # The bare (extension-less) reference is fully rewritten.
    assert f'"assets/{digest}"' not in html


# --- (c) font license gate --------------------------------------------------


def seed_font_asset(client: TestClient, asset_id: str, data: bytes) -> str:
    # D4: the export reads face bytes from DURABLE storage, so seed them through the seam.
    digest = make_blob_store(client.app).register(
        data, media_type="font/woff2", source_key=SOURCE_KEY_ASSET
    ) and hashlib.sha256(data).hexdigest()
    record = {
        "id": asset_id,
        "label": asset_id,
        "kind": "font",
        "status": "ready",
        "source": {"kind": "uploaded"},
        "media": {
            "mime_type": "font/woff2",
            "digest": {"algorithm": "sha256", "value": digest},
            "filename": f"{asset_id}.woff2",
            "byte_length": len(data),
            "location": None,
        },
    }
    store = HybridRepository()
    store.create_asset_record(record)
    return digest


def create_font_kit(client: TestClient, ofl_asset: str, locked_asset: str) -> None:
    kit = json.loads(ACME_KIT_PATH.read_text())
    kit["id"] = "kit_export_fonts"
    kit["version"] = 1
    template = next(iter(kit["assets"]["fonts"].values()))
    included = json.loads(json.dumps(template))
    included["family"] = "Export Sans"
    # OFL license name → included even though embeddable is false.
    included["license"] = {
        "name": "OFL 1.1",
        "embeddable": False,
        "subsettable": True,
        "source_url": None,
        "restrictions": [],
    }
    included["faces"] = [
        {"weight": 400, "style": "normal", "asset_id": ofl_asset, "source_url": None}
    ]
    excluded = json.loads(json.dumps(template))
    excluded["family"] = "Locked Display"
    excluded["license"] = {
        "name": "Commercial",
        "embeddable": False,
        "subsettable": False,
        "source_url": None,
        "restrictions": [],
    }
    excluded["faces"] = [
        {"weight": 400, "style": "normal", "asset_id": locked_asset, "source_url": None}
    ]
    kit["assets"]["fonts"] = {"brand": included, "locked": excluded}
    store = HybridRepository()
    store.create_brand_kit(kit, {}, [], "manual")


def test_export_font_license_gate(client: TestClient) -> None:
    ofl_digest = seed_font_asset(client, "asset_font_ofl", b"wOF2" + b"\x00" * 96)
    seed_font_asset(client, "asset_font_locked", b"wOF2" + b"\x11" * 96)
    create_font_kit(client, "asset_font_ofl", "asset_font_locked")

    document = create_web_document(
        client, brand_kit_ref={"id": "kit_export_fonts", "version": 1}
    )
    seed_content(client, document["id"], ingest_content(client, document["id"]))
    files, _html, manifest = export_zip(client, document["id"])

    # OFL family embedded under fonts/.
    assert f"fonts/{ofl_digest[:12]}.woff2" in files
    assert "Export Sans" in manifest["font_families_included"]

    # Non-embeddable family excluded — no file, manifest entry + warning.
    assert not any(name.startswith("fonts/") and "Locked" in name for name in files)
    assert {"family": "Locked Display", "reason": "license not embeddable"} in manifest[
        "font_families_excluded"
    ]
    assert any(
        "Locked Display" in warning and "license not embeddable" in warning
        for warning in manifest["warnings"]
    )


def test_the_publish_manifest_stops_discarding_the_font_exclusions(
    client: TestClient, workspace_id: str
) -> None:
    """D-F2 obligation 3: what the gate excludes must be VISIBLE, never dropped.

    The publish path gathered fonts through the same license gate as export and then threw the
    exclusion list away (`_excluded`), so a family the gate refused left no trace on the one
    artifact a publish keeps. A page that silently ships in a fallback font is exactly the
    failure a manifest exists to explain.
    """
    ofl_digest = seed_font_asset(client, "asset_font_pub_ofl", b"wOF2" + b"\x00" * 96)
    seed_font_asset(client, "asset_font_pub_locked", b"wOF2" + b"\x11" * 96)
    create_font_kit(client, "asset_font_pub_ofl", "asset_font_pub_locked")

    document = create_web_document(
        client, brand_kit_ref={"id": "kit_export_fonts", "version": 1}
    )
    seed_content(client, document["id"], ingest_content(client, document["id"]))
    published = client.post(
        f"/documents/{document['id']}/web/publish", json={"slug": "font-exclusions"}
    )
    assert published.status_code == 200, published.text

    manifest = client.get(f"/w/{workspace_id}/p/font-exclusions/manifest.json")
    assert manifest.status_code == 200, manifest.text
    body = manifest.json()

    assert {"family": "Locked Display", "reason": "license not embeddable"} in body[
        "font_families_excluded"
    ]
    assert "Export Sans" in body["font_families_included"]
    # The included family's faces really are on the page (the gate let them through), and its
    # @font-face points at the digest route.
    served = client.get(f"/w/{workspace_id}/p/font-exclusions")
    assert f"/asset-store/{ofl_digest}" in served.text


def test_the_publish_manifest_names_the_basis_a_family_embeds_under(
    client: TestClient, workspace_id: str
) -> None:
    """D-F2 obligation 2, made visible: a workspace-brand font ships under `platform-terms`,
    and the manifest says so — the gate reads the basis, so a legal reviewer can see WHY a font
    with no verifiable license name was embedded."""
    digest = seed_font_asset(client, "asset_font_basis", b"wOF2" + b"\x22" * 96)
    kit = json.loads(ACME_KIT_PATH.read_text())
    kit["id"] = "kit_basis_fonts"
    kit["version"] = 1
    family = json.loads(json.dumps(next(iter(kit["assets"]["fonts"].values()))))
    family["family"] = "Workspace Brand Sans"
    family["license"] = {
        "name": "unknown",
        "embeddable": True,
        "subsettable": False,
        "source_url": None,
        "basis": "platform-terms",
        "restrictions": ["Off-platform reuse still requires license confirmation."],
    }
    family["faces"] = [
        {"weight": 400, "style": "normal", "asset_id": "asset_font_basis", "source_url": None}
    ]
    kit["assets"]["fonts"] = {"brand": family}
    HybridRepository().create_brand_kit(kit, {}, [], "manual")

    document = create_web_document(
        client, brand_kit_ref={"id": "kit_basis_fonts", "version": 1}
    )
    seed_content(client, document["id"], ingest_content(client, document["id"]))
    published = client.post(
        f"/documents/{document['id']}/web/publish", json={"slug": "font-basis"}
    )
    assert published.status_code == 200, published.text
    body = client.get(f"/w/{workspace_id}/p/font-basis/manifest.json").json()

    assert "Workspace Brand Sans" in body["font_families_included"]
    assert {
        "family": "Workspace Brand Sans",
        "basis": "platform-terms",
    } in body["font_embed_bases"]

    # The same basis rides the export manifest, so the two artifacts agree.
    _files, _html, manifest = export_zip(client, document["id"])
    assert {
        "family": "Workspace Brand Sans",
        "basis": "platform-terms",
    } in manifest["font_embed_bases"]
    assert f"fonts/{digest[:12]}.woff2" in _files


# --- (d) SEO ----------------------------------------------------------------


def test_export_seo_description(client: TestClient) -> None:
    document = seed_document(client)
    _files, html, _manifest = export_zip(client, document["id"])
    assert '<meta name="description"' in html
    marker = 'content="'
    start = html.index('<meta name="description"')
    content_start = html.index(marker, start) + len(marker)
    content_end = html.index('"', content_start)
    description = html[content_start:content_end]
    assert description, "description is non-empty"
    assert len(description) <= 155


# --- (e) node compile failure fails honestly --------------------------------


def test_export_node_failure_is_502(client: TestClient) -> None:
    document = seed_document(client)
    client.app.state.web_export_node_bin = "false"  # the unix binary: exits 1
    response = client.get(f"/documents/{document['id']}/web/export")
    assert response.status_code == 502, response.text
    assert response.json()["detail"]["code"] == "web_export.compile_failed"


# --- (f) publish / serve / rollback -----------------------------------------


def test_publish_serve_republish_rollback(client: TestClient, workspace_id: str) -> None:
    document = seed_document(client)

    published = client.post(f"/documents/{document['id']}/web/publish", json={})
    assert published.status_code == 200, published.text
    body = published.json()
    slug = body["slug"]
    # F5/R-F5-1: the reported URL is ABSOLUTE and config-sourced. With no host suffix set
    # (the default, and what the test env has) it is the interim path on the request origin.
    assert body["url"] == f"http://testserver/w/{workspace_id}/p/{slug}"
    assert body["doc_version"] == 1
    assert body["previous_available"] is False

    # Served page: inlined style + canonical, no external stylesheet link.
    served = client.get(f"/w/{workspace_id}/p/{slug}")
    assert served.status_code == 200, served.text
    assert 'id="lumen-static-css"' in served.text
    assert '<link rel="canonical"' in served.text
    assert '<link rel="stylesheet" href="site.css">' not in served.text

    # Edit a text marker, republish → doc_version bumps + previous available.
    text_id = find_node(get_document(client, document["id"])["scene"], "text")
    edit = client.post(
        f"/documents/{document['id']}/web/operations",
        json={
            "operations": [
                {
                    "kind": "set_text",
                    "page_id": "home",
                    "id": text_id,
                    "content": "MARKER_TWO",
                }
            ],
            "base_version": 1,
        },
    )
    assert edit.status_code == 200, edit.text

    republished = client.post(f"/documents/{document['id']}/web/publish", json={})
    assert republished.status_code == 200, republished.text
    assert republished.json()["doc_version"] == 2
    assert republished.json()["previous_available"] is True
    assert "MARKER_TWO" in client.get(f"/w/{workspace_id}/p/{slug}").text

    # Rollback → serves the previous publish, doc_version back to 1.
    rolled = client.post(f"/web/publishes/{slug}/rollback")
    assert rolled.status_code == 200, rolled.text
    assert rolled.json()["doc_version"] == 1
    assert rolled.json()["status"] == "active"
    assert "MARKER_TWO" not in client.get(f"/w/{workspace_id}/p/{slug}").text

    # GET publish state reflects the document.
    state = client.get(f"/documents/{document['id']}/web/publish").json()
    assert state["published"] is True
    assert state["slug"] == slug

    # Unpublish → /p 404.
    unpub = client.delete(f"/web/publishes/{slug}")
    assert unpub.status_code == 200, unpub.text
    assert unpub.json()["status"] == "unpublished"
    assert client.get(f"/w/{workspace_id}/p/{slug}").status_code == 404


def test_publish_slug_validation(client: TestClient) -> None:
    document = seed_document(client)
    response = client.post(
        f"/documents/{document['id']}/web/publish", json={"slug": "ab"}
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "web_publish.bad_slug"


def test_publish_slug_collision_across_documents(client: TestClient) -> None:
    first = seed_document(client)
    second = seed_document(client)
    published = client.post(
        f"/documents/{first['id']}/web/publish", json={"slug": "shared-slug"}
    )
    assert published.status_code == 200, published.text
    collision = client.post(
        f"/documents/{second['id']}/web/publish", json={"slug": "shared-slug"}
    )
    assert collision.status_code == 409, collision.text
    assert collision.json()["detail"]["code"] == "web_publish.slug_taken"


def test_rollback_without_previous_is_409(client: TestClient) -> None:
    document = seed_document(client)
    client.post(f"/documents/{document['id']}/web/publish", json={"slug": "solo-page"})
    response = client.post("/web/publishes/solo-page/rollback")
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "web_publish.no_previous"


def test_unpublish_unknown_slug_is_404(client: TestClient) -> None:
    response = client.delete("/web/publishes/nope-nope")
    assert response.status_code == 404, response.text
    assert response.json()["detail"]["code"] == "web_publish.not_found"


def test_get_publish_state_unpublished(client: TestClient) -> None:
    document = seed_document(client)
    state = client.get(f"/documents/{document['id']}/web/publish").json()
    assert state == {"schema_version": 1, "published": False}


# --- (g) scene documents are rejected on the new endpoints -------------------


@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("get", "/web/export", None),
        ("post", "/web/publish", {}),
        ("get", "/web/publish", None),
    ],
)
def test_web_export_endpoints_reject_scene_documents(
    client: TestClient, method: str, path: str, payload
) -> None:
    scene = create_scene_document(client)
    url = f"/documents/{scene['id']}{path}"
    response = (
        client.post(url, json=payload) if method == "post" else client.get(url)
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "document.kind_unsupported"


# --------------------------------------------------------------------------- #
# F5 — multi-page publishing, per-route serving, one export folder per page    #
# --------------------------------------------------------------------------- #


def _empty_page(page_id: str, route: str, name: str = "Pricing") -> dict:
    """The smallest legal WebPage: its root Container alone, no children.

    Copied from ``test_web_documents.py`` rather than imported: these modules are peers, and a
    test helper shared across them by import makes one file's refactor break the other's.
    """
    root = f"root_{page_id}"
    return {
        "id": page_id,
        "name": name,
        "route": route,
        "root": root,
        "nodes": {root: {"id": root, "kind": "container", "classes": "", "children": []}},
    }


def test_rewrite_site_links_touches_only_document_routes() -> None:
    from lumen_api.web_export import rewrite_site_links

    html = (
        '<a href="/pricing">a</a><a href="/careers">b</a>'
        '<img src="/asset-store/abc"><a href="/">home</a>'
    )
    out = rewrite_site_links(html, ["/", "/pricing"], "/w/ws1/p/site")
    assert 'href="/w/ws1/p/site/pricing"' in out
    assert 'href="/w/ws1/p/site"' in out
    # A path that merely LOOKS like a route, and a non-href attribute, are untouched.
    assert 'href="/careers"' in out
    assert 'src="/asset-store/abc"' in out


def test_publish_serves_every_page_at_its_route(
    client: TestClient, workspace_id: str
) -> None:
    document = create_web_document(client)
    added = client.post(
        f"/documents/{document['id']}/web/operations",
        json={"operations": [{"kind": "add_page", "page": _empty_page("pricing", "/pricing")}]},
    )
    assert added.status_code == 200, added.text

    web_doc = client.get(f"/documents/{document['id']}").json()["scene"]
    home_html = (
        '<section id="hero"><h1>Home</h1>'
        '<p><a href="/pricing">See pricing</a></p></section>'
    )
    seeded = client.app.state.core.web_ingest_html(web_doc, "home", home_html, None, None)[
        "web_doc"
    ]
    seeded = client.app.state.core.web_ingest_html(
        seeded, "pricing", '<section id="plans"><h1>Plans</h1></section>', None, None
    )["web_doc"]
    seed_content(client, document["id"], seeded)

    published = client.post(
        f"/documents/{document['id']}/web/publish", json={"slug": "multi"}
    )
    assert published.status_code == 200, published.text
    assert published.json()["routes"] == ["/", "/pricing"]

    home = client.get(f"/w/{workspace_id}/p/multi")
    pricing = client.get(f"/w/{workspace_id}/p/multi/pricing")
    assert home.status_code == 200, home.text
    assert "Home" in home.text
    assert pricing.status_code == 200, pricing.text
    assert "Plans" in pricing.text
    # The site link is rewritten to the served address of the pricing page.
    assert f'href="/w/{workspace_id}/p/multi/pricing"' in home.text
    # ...and each page carries its OWN canonical.
    assert '<link rel="canonical" href="' in pricing.text
    assert f"/w/{workspace_id}/p/multi/pricing" in pricing.text
    assert client.get(f"/w/{workspace_id}/p/multi/nope").status_code == 404

    state = client.get(f"/documents/{document['id']}/web/publish").json()
    assert [page["route"] for page in state["pages"]] == ["/", "/pricing"]


def test_export_zip_writes_one_folder_per_page(client: TestClient) -> None:
    document = create_web_document(client)
    added = client.post(
        f"/documents/{document['id']}/web/operations",
        json={"operations": [{"kind": "add_page", "page": _empty_page("pricing", "/pricing")}]},
    )
    assert added.status_code == 200, added.text
    web_doc = client.get(f"/documents/{document['id']}").json()["scene"]
    seeded = client.app.state.core.web_ingest_html(
        web_doc,
        "home",
        '<section id="hero"><h1>Home</h1><p><a href="/pricing">Pricing</a></p></section>',
        None,
        None,
    )["web_doc"]
    seeded = client.app.state.core.web_ingest_html(
        seeded, "pricing", '<section id="plans"><h1>Plans</h1></section>', None, None
    )["web_doc"]
    seed_content(client, document["id"], seeded)

    files, _html, manifest = export_zip(client, document["id"])
    assert "index.html" in files
    assert "pricing/index.html" in files
    assert "pricing/index.html" in manifest["files"]
    assert [page["route"] for page in manifest["pages"]] == ["/", "/pricing"]
    assert b"Plans" in files["pricing/index.html"]
    # A static host serves a folder page from its directory index.
    assert 'href="/pricing/"' in files["index.html"].decode("utf-8")
