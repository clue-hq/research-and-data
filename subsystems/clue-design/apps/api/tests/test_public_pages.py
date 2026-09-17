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
