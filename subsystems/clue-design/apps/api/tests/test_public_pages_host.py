"""F5 Task 15: the ORIGIN behaviour — a published site answering on its own hostname.

Task 12 taught the API to *report* ``https://{handle}.{suffix}/{slug}`` once
``LUMEN_PUBLIC_PAGES_HOST_SUFFIX`` is configured; Task 14 gave every workspace the handle that
goes in front of it. Neither made that hostname actually serve anything — the bytes still only
came out of the interim ``/w/{ws}/p/{slug}`` path. This suite is the missing half: a Starlette
``Host`` route in front of the app's own routes, resolving the handle to a workspace and
answering with the SAME serving bodies the interim routes use.

Two properties beyond "it 200s":

* **A stranger's host is a 404, not somebody else's site.** The handle is the tenant selector,
  so an unknown one must resolve to nothing at all — and must not mint a workspace row on the
  way past (``ensure_workspace=False``).
* **Blank suffix changes nothing.** The mount is conditional; with no suffix configured the app
  has no host route and every existing path route behaves exactly as it did before.

The suffix is read ONCE, at app-build time, because a ``Host`` pattern is compiled into the
route table — so each test here builds its own app with the env already set, rather than
monkeypatching the shared one. That is also the production contract: changing the suffix needs
a restart, like every other env in this API.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from clue_design.storage import SOURCE_KEY_ASSET
from conftest import make_blob_store, make_client
from fastapi.testclient import TestClient
from starlette.routing import Host

from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app

SUFFIX = "pages.test"

SAMPLE_HTML = """
<section id="hero" class="bg-light">
  <div class="mx-auto max-w-[1200px] px-6 py-24 flex flex-col items-center gap-6 text-center">
    <h1 data-variant="display" class="max-w-[820px]">Ship faster with Acme</h1>
    <p class="text-muted max-w-[640px]">Acme helps teams build and launch quickly.</p>
  </div>
</section>
"""


@pytest.fixture()
def client(tmp_path: Path, design_storage, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """The AUTHORING client, on an app built with the public host suffix already configured.

    Set before ``create_app`` on purpose: the ``Host`` route is compiled into the route table at
    build time, so an env set afterwards would report host-mode URLs from an app that cannot
    serve them.
    """
    monkeypatch.setenv("LUMEN_PUBLIC_PAGES_HOST_SUFFIX", SUFFIX)
    monkeypatch.setenv("LUMEN_PUBLIC_PAGES_SCHEME", "https")
    return make_client(create_app(tmp_path / "engine-cache", storage=design_storage))


def publish_site(client: TestClient, slug: str) -> dict:
    """Seed a real web document and publish it — the whole pipeline, like ``test_web_export``."""
    created = client.post("/documents", json={"doc_kind": "web", "title": "My site"})
    assert created.status_code == 200, created.text
    document = created.json()["document"]
    web_doc = client.get(f"/documents/{document['id']}").json()["scene"]
    response = client.app.state.core.web_ingest_html(web_doc, "home", SAMPLE_HTML, None, None)
    errors = [d for d in response.get("diagnostics", []) if d.get("severity") == "error"]
    assert not errors, response.get("diagnostics")
    HybridRepository().update_web_document(
        document["id"],
        response["web_doc"],
        intent="seed",
        checkpoint_label="seed",
        operations=[{"kind": "replace_web_doc"}],
        inverse_operations=None,
        push_undo=False,
    )
    published = client.post(f"/documents/{document['id']}/web/publish", json={"slug": slug})
    assert published.status_code == 200, published.text
    return published.json()


def public_client(client: TestClient, handle: str) -> TestClient:
    """A visitor arriving at ``https://{handle}.pages.test`` — same app, different Host header."""
    return TestClient(client.app, base_url=f"https://{handle}.{SUFFIX}")


def test_public_host_serves_the_site_by_handle(client: TestClient) -> None:
    handle = client.get("/workspace/handle").json()["handle"]
    publish_site(client, "site")

    public = public_client(client, handle)
    page = public.get("/site")
    assert page.status_code == 200, page.text
    assert "Ship faster with Acme" in page.text
    assert public.get("/site/manifest.json").status_code == 200
    assert public.get("/nope").status_code == 404


def test_a_stranger_handle_serves_nothing(client: TestClient) -> None:
    publish_site(client, "site")
    stranger = TestClient(client.app, base_url=f"https://nobody-at-all.{SUFFIX}")
    refused = stranger.get("/site")
    assert refused.status_code == 404
    # And the lookup must not have minted a workspace row for the host somebody typed.
    assert (
        HybridRepository(workspace_id="ws_public_host_router", ensure_workspace=False)
        .get_workspace_by_handle("nobody-at-all")
        is None
    )


def test_the_page_is_canonical_at_its_own_host(client: TestClient) -> None:
    """Task 12's addressing and Task 15's serving are the same answer: the page a visitor gets
    from ``{handle}.pages.test`` declares THAT as its canonical URL, not the interim path."""

    handle = client.get("/workspace/handle").json()["handle"]
    published = publish_site(client, "site")
    assert published["url"] == f"https://{handle}.{SUFFIX}/site"

    page = public_client(client, handle).get("/site")
    assert f'<link rel="canonical" href="https://{handle}.{SUFFIX}/site">' in page.text
    # The serving CSP names the site's OWN origin, so its stylesheet and fonts are allowed.
    assert f"https://{handle}.{SUFFIX}" in page.headers["Content-Security-Policy"]


def test_the_sites_own_assets_resolve_on_its_host(client: TestClient) -> None:
    """A published page loads its images, fonts and component runtimes ROOT-RELATIVELY —
    ``/asset-store/{digest}`` and (in host mode, bare) ``/p-assets/{digest}.{ext}``. Both have
    to answer on the public host, or a site that has any of them loads broken."""

    handle = client.get("/workspace/handle").json()["handle"]
    publish_site(client, "site")
    public = public_client(client, handle)

    payload = b"body{color:red}"
    digest = hashlib.sha256(payload).hexdigest()
    blobs = make_blob_store(client.app)
    blobs.register(payload, media_type="text/css; charset=utf-8", source_key=SOURCE_KEY_ASSET)
    # The publish-asset route is workspace-scoped, and the workspace comes from the HANDLE.
    served = public.get(f"/p-assets/{digest}.css")
    assert served.status_code == 200, served.text
    assert served.content == payload
    # A stranger's host cannot read this tenant's bytes even holding the digest.
    stranger = TestClient(client.app, base_url=f"https://nobody-at-all.{SUFFIX}")
    assert stranger.get(f"/p-assets/{digest}.css").status_code == 404

    image = b"host-mode image bytes"
    blobs.register(image, media_type="application/octet-stream", source_key=SOURCE_KEY_ASSET)
    stored = public.get(f"/asset-store/{hashlib.sha256(image).hexdigest()}")
    assert stored.status_code == 200, stored.text
    assert stored.content == image


def test_no_suffix_mounts_no_host_route(
    tmp_path: Path, design_storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Blank is the default and blank is a real posture: nothing is mounted, and the interim
    path serving is untouched."""

    monkeypatch.delenv("LUMEN_PUBLIC_PAGES_HOST_SUFFIX", raising=False)
    app = create_app(tmp_path / "engine-cache-plain", storage=design_storage)
    assert not any(isinstance(route, Host) for route in app.router.routes)

    plain = make_client(app)
    workspace_id = plain.get("/workspace/handle").json()
    handle = workspace_id["handle"]
    assert workspace_id["public_host"] is None
    publish_site(plain, "site")
    # The interim path still serves...
    interim = plain.get(f"/w/{plain.headers['X-Workspace-Id']}/p/site")
    assert interim.status_code == 200, interim.text
    # ...and the hostname answers nothing, because no host route exists.
    assert TestClient(app, base_url=f"https://{handle}.{SUFFIX}").get("/site").status_code == 404
