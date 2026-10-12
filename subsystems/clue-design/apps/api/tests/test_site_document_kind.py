"""The site document kind in the design API's reads and gates (Wave 2 Lane A, Task 8)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from conftest import make_client
from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app, require_site_document
from lumen_api.toolbelt.documents import document_failures
from site_kit_support import garner_site, store_site


@pytest.fixture()
def client(tmp_path: Path, design_storage) -> TestClient:
    return make_client(create_app(tmp_path / "engine-cache", storage=design_storage))


def test_get_document_treats_a_site_like_a_web_document(client: TestClient) -> None:
    store_site(garner_site("site_kind_get"))
    body = client.get("/documents/site_kind_get").json()
    assert body["doc_kind"] == "site"
    assert "render_context" not in body  # no scene render context, no platform-default brand call
    assert "account_id" in body and body["account_id"] is None  # exposed, as for web
    assert "fragment_meta" not in body


def test_the_site_gate_refuses_every_other_kind() -> None:
    require_site_document({"id": "doc_s", "doc_kind": "site"})
    for kind in ("web", "scene"):
        with pytest.raises(HTTPException) as refused:
            require_site_document({"id": "doc_x", "doc_kind": kind})
        assert refused.value.status_code == 409
        assert refused.value.detail["code"] == "document.kind_unsupported"


def test_the_tool_gate_names_a_document_that_is_not_a_site(client: TestClient) -> None:
    store_site(garner_site("site_kind_gate"))
    repo = HybridRepository()
    assert document_failures(repo, "site_kind_gate", kind="site", draft=True) == ()
    web = client.post("/documents", json={"doc_kind": "web", "title": "A web page"}).json()["document"]
    (failure,) = document_failures(repo, web["id"], kind="site")
    assert failure.reason_code == "design_document_not_site"
    (scene_gate,) = document_failures(repo, "site_kind_gate", kind="web")
    assert scene_gate.reason_code == "design_document_not_web"
