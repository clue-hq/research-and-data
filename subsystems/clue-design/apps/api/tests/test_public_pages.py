"""Custom-domain publishing S1 Task 10: publish URLs come from the hostname registry,
never from the request."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from lumen_api.design_store import HybridRepository
from lumen_api.public_pages import public_publish_url, system_public_origin

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
        public_origin="https://acme.pages.test",
        workspace_id=repo.workspace_id,
        node_bin=client.app.state.web_export_node_bin,
        default_description="From workspace settings",
    )
    assert 'name="description" content="From workspace settings"' in package.html
    assert 'property="og:description" content="From workspace settings"' in package.html
