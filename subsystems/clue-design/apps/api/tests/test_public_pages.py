"""Custom-domain publishing S1 Task 10: publish URLs come from the hostname registry,
never from the request. Reconciliation 2026-09-28: F5's ``PublicSiteAddress`` is built from the
same registry (``site_address`` / ``custom_site_address``), every route of a multi-page site sits
at ``/{slug}{route}`` on those origins, and the first publish locks the workspace's label."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from lumen_api.design_store import HybridRepository
from lumen_api.public_address import PublicSiteAddress
from lumen_api.public_pages import (
    custom_site_address,
    public_publish_url,
    site_address,
    system_public_origin,
)

from conftest import make_client
from test_web_export import seed_document  # the existing seeding helper


@pytest.fixture
def client(tmp_path, design_storage):
    from lumen_api.main import create_app

    return make_client(create_app(tmp_path / "engine-cache", storage=design_storage))


def test_every_dev_workspace_gets_a_system_hostname(
    client: TestClient, workspace_id: str, monkeypatch
) -> None:
    monkeypatch.setenv("CLUE_PAGES_SYSTEM_SUFFIX", "pages.test")
    monkeypatch.setenv("CLUE_PAGES_PUBLIC_SCHEME", "http")
    monkeypatch.setenv("CLUE_PAGES_PUBLIC_PORT", "8040")
    seed_document(client)  # any request scaffolds the workspace through _ensure_workspace
    repo = HybridRepository()
    hostname = repo.system_hostname()
    assert hostname == f"{workspace_id.replace('_', '-')}.pages.test"
    assert system_public_origin(repo) == f"http://{hostname}:8040"
    assert public_publish_url(repo, "annual-report") == f"http://{hostname}:8040/annual-report"
    assert repo.active_custom_hostname() is None


def test_publish_responses_carry_absolute_urls_and_origins(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setenv("CLUE_PAGES_SYSTEM_SUFFIX", "pages.test")
    monkeypatch.setenv("CLUE_PAGES_PUBLIC_SCHEME", "https")
    monkeypatch.delenv("CLUE_PAGES_PUBLIC_PORT", raising=False)
    document = seed_document(client)
    state = client.get(f"/documents/{document['id']}/web/publish").json()
    assert state["published"] is False
    assert state["public_origin"].endswith(".pages.test") and state["public_origin"].startswith(
        "https://"
    )
    assert state["custom_origin"] is None
    published = client.post(
        f"/documents/{document['id']}/web/publish", json={"slug": "hello"}
    ).json()
    assert published["url"] == f"{state['public_origin']}/hello"
    assert published["custom_url"] is None
    assert published["public_origin"] == state["public_origin"]
    again = client.get(f"/documents/{document['id']}/web/publish").json()
    assert again["url"] == published["url"] and again["custom_url"] is None


# --- S2 Task 9: publish-time defaults from the workspace settings row --------


def test_publish_falls_back_to_workspace_description_and_social_preview(
    client: TestClient, monkeypatch
) -> None:
    """The workspace social preview becomes ``og:image`` when the page has no image node.

    Custom-domain publishing §4.2. The page's OWN derived description still wins here — the
    sample landing page has body copy — so this asserts the picture fallback and that the page
    keeps a description of its own; the empty-description path is the next test.
    """
    from clue_spine.pages_settings import update_pages_settings
    from clue_storage import content_address

    from conftest import make_blob_store, published_html

    monkeypatch.setenv("CLUE_PAGES_SYSTEM_SUFFIX", "pages.test")
    monkeypatch.setenv("CLUE_PAGES_PUBLIC_SCHEME", "https")
    monkeypatch.delenv("CLUE_PAGES_PUBLIC_PORT", raising=False)
    document = seed_document(client)  # SAMPLE_HTML has no image node; its description is body copy
    repo = HybridRepository()
    preview = b"\x89PNG-social-preview"
    make_blob_store(client.app).register(preview, media_type="image/png", source_key="test")
    repo._bridge._run(
        lambda conn: update_pages_settings(
            conn,
            workspace_id=repo.workspace_id,
            page_description="From workspace settings",
            social_preview_sha256=content_address(preview),
        )
    )
    response = client.post(f"/documents/{document['id']}/web/publish", json={"slug": "defaults"})
    assert response.status_code == 200, response.text
    html = published_html(repo.workspace_id, "defaults")
    assert (
        f'property="og:image" content="https://{repo.system_hostname()}'
        f'/asset-store/{content_address(preview)}"' in html
    )
    # the page's own derived description wins when non-empty
    assert 'name="description"' in html
    assert 'name="description" content="From workspace settings"' not in html


def test_publish_falls_back_to_workspace_description_when_the_page_derives_none(
    client: TestClient,
) -> None:
    """The workspace ``page_description`` fills in ONLY when the page derives an empty one.

    Proven directly against ``build_publish_package`` (the brief's cheap path): a document with
    no body copy AND no title is the only shape ``_seo_description`` answers with "".
    """
    from lumen_api.web_export import build_publish_package

    from conftest import make_blob_store
    from test_web_export import create_web_document, get_document

    blank = get_document(client, create_web_document(client, title="")["id"])
    repo = HybridRepository()
    package = build_publish_package(
        client.app.state.core,
        repo,
        {**blank, "title": ""},
        blobs=make_blob_store(client.app),
        slug="blank",
        site_address=PublicSiteAddress(
            origin="https://acme.pages.test",
            site_path="/blank",
            asset_origin="https://acme.pages.test",
        ),
        workspace_id=repo.workspace_id,
        node_bin=client.app.state.web_export_node_bin,
        default_description="From workspace settings",
    )
    assert 'name="description" content="From workspace settings"' in package.html
    assert 'property="og:description" content="From workspace settings"' in package.html


# --- Reconciliation 2026-09-28: F5 addresses from the registry; lock at first publish ------


def _activate_custom_hostname(repo: HybridRepository) -> str:
    """Give the workspace an ACTIVE custom hostname, as the S2 control plane would leave it."""
    from uuid import uuid4

    from clue_spine.hostnames import insert_custom_hostname, set_custom_hostname_status

    hostname = f"go-{uuid4().hex[:10]}.example.com"

    async def _write(conn) -> None:
        await insert_custom_hostname(
            conn, workspace_id=repo.workspace_id, hostname=hostname, cname_target="edge.test"
        )
        await set_custom_hostname_status(conn, hostname=hostname, status="active")

    repo._bridge._run(_write)
    return hostname


def test_site_address_puts_every_route_under_the_slug_on_the_registry_origins(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setenv("CLUE_PAGES_SYSTEM_SUFFIX", "pages.test")
    monkeypatch.setenv("CLUE_PAGES_PUBLIC_SCHEME", "http")
    monkeypatch.setenv("CLUE_PAGES_PUBLIC_PORT", "8040")
    seed_document(client)  # scaffolds the workspace (and its system hostname)
    repo = HybridRepository()
    origin = system_public_origin(repo)
    address = site_address(repo, "multi")
    assert address == PublicSiteAddress(
        origin=origin, site_path="/multi", asset_origin=origin
    )
    assert address.page_url("/") == f"{origin}/multi"
    assert address.page_url("/pricing") == f"{origin}/multi/pricing"
    assert address.link_path == "/multi"
    assert address.asset_base() == origin
    assert custom_site_address(repo, "multi") is None

    custom = _activate_custom_hostname(repo)
    on_custom = custom_site_address(repo, "multi")
    assert on_custom is not None
    assert on_custom.origin == f"https://{custom}"
    assert on_custom.page_url("/pricing") == f"https://{custom}/multi/pricing"


def test_publish_responses_carry_one_route_map_per_origin(client: TestClient) -> None:
    document = seed_document(client)
    repo = HybridRepository()
    custom = _activate_custom_hostname(repo)
    published = client.post(
        f"/documents/{document['id']}/web/publish", json={"slug": "both-origins"}
    ).json()
    origin = system_public_origin(repo)
    assert published["public_origin"] == origin
    assert published["custom_origin"] == f"https://{custom}"
    assert published["url"] == f"{origin}/both-origins"
    assert published["custom_url"] == f"https://{custom}/both-origins"
    assert published["page_urls"] == {"/": f"{origin}/both-origins"}
    assert published["custom_page_urls"] == {"/": f"https://{custom}/both-origins"}
    state = client.get(f"/documents/{document['id']}/web/publish").json()
    assert state["custom_page_urls"] == published["custom_page_urls"]
    assert state["page_urls"] == published["page_urls"]


def test_the_first_publish_locks_the_system_label(client: TestClient) -> None:
    """F5 R-F5-5, adopted 2026-09-28: something on the air at an address freezes its label."""
    from sqlalchemy import text

    document = seed_document(client)
    repo = HybridRepository()

    async def _locked_at(conn):
        result = await conn.execute(
            text(
                "SELECT locked_at FROM workspace_hostname "
                "WHERE workspace_id = :w AND kind = 'system'"
            ),
            {"w": repo.workspace_id},
        )
        return result.scalar()

    assert repo._bridge._run(_locked_at) is None
    response = client.post(f"/documents/{document['id']}/web/publish", json={"slug": "locks"})
    assert response.status_code == 200, response.text
    first = repo._bridge._run(_locked_at)
    assert first is not None
    again = client.post(f"/documents/{document['id']}/web/publish", json={"slug": "locks"})
    assert again.status_code == 200, again.text
    assert repo._bridge._run(_locked_at) == first  # idempotent: never moves forward


def test_a_refused_publish_leaves_the_label_unlocked(client: TestClient) -> None:
    """The lock follows a real revision, so a publish refused before anything is built leaves
    the marketer free to keep choosing the label."""
    from sqlalchemy import text

    document = seed_document(client)
    repo = HybridRepository()
    refused = client.post(f"/documents/{document['id']}/web/publish", json={"slug": "ab"})
    assert refused.status_code == 422, refused.text

    async def _locked_at(conn):
        result = await conn.execute(
            text(
                "SELECT locked_at FROM workspace_hostname "
                "WHERE workspace_id = :w AND kind = 'system'"
            ),
            {"w": repo.workspace_id},
        )
        return result.scalar()

    assert repo._bridge._run(_locked_at) is None


def test_republishing_under_a_new_slug_moves_the_site(client: TestClient) -> None:
    """A document lives at ONE address (found live 2026-09-30: a renamed page kept serving at
    its old slug). Republishing under a new slug unpublishes the old one — the page origin serves
    only `active` rows, so it 404s — and leaves every other document's slug alone."""
    document = seed_document(client)
    other = seed_document(client)
    repo = HybridRepository()

    for doc, slug in ((document, "first-name"), (other, "someone-else")):
        response = client.post(f"/documents/{doc['id']}/web/publish", json={"slug": slug})
        assert response.status_code == 200, response.text
    moved = client.post(f"/documents/{document['id']}/web/publish", json={"slug": "second-name"})
    assert moved.status_code == 200, moved.text

    assert repo.get_web_publish("first-name")["status"] == "unpublished"
    assert repo.get_web_publish("second-name")["status"] == "active"
    assert repo.get_web_publish("someone-else")["status"] == "active"

    # Republishing in place keeps the one live address live.
    again = client.post(f"/documents/{document['id']}/web/publish", json={"slug": "second-name"})
    assert again.status_code == 200, again.text
    assert repo.get_web_publish("second-name")["status"] == "active"
    assert repo.get_web_publish("first-name")["status"] == "unpublished"
