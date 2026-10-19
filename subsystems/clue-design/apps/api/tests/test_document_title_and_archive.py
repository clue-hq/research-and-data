"""PUT /documents/{id}/title and /archived — the artifacts library's two governed writes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from py_lumen_config import settings

from conftest import make_client

from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app
from site_kit_support import born_site, store_site
from test_agent_run_write_lock import assert_locked, finish_run, start_leg_run


REPO_ROOT = Path(__file__).resolve().parents[3]
MINIMAL_SCENE_PATH = REPO_ROOT / "crates/lumen-core/fixtures/minimal_scene.json"


@pytest.fixture(autouse=True)
def _no_embedded_fleet_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    # The K1-5 scenario seeds a running run row directly; nothing here offers fleet work, so no
    # embedded worker drains the shared queue beside it (test_agent_run_write_lock's reason).
    monkeypatch.setattr(settings, "lumen_embedded_fleet_worker", False, raising=False)


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    return make_client(create_app(tmp_path / "engine-cache"))


def _scene(doc_id: str, title: str = "Before") -> dict:
    """The engine's own minimal scene, renamed onto this document.

    The route's no-scene branch mints a scene with no export profile, which ``finalize`` refuses
    (``op.finalize_missing_export_profile``) — and the finalized half of the refusal test needs a
    document that CAN be finalized.
    """
    scene = json.loads(MINIMAL_SCENE_PATH.read_text())
    scene["meta"]["id"] = doc_id
    scene["meta"]["title"] = title
    return scene


def _create(client: TestClient, doc_id: str) -> str:
    created = client.post("/documents", json={"document_id": doc_id, "scene": _scene(doc_id)})
    assert created.status_code in (200, 201), created.text
    return doc_id


def test_rename_writes_row_and_scene_and_bumps_version(
    client: TestClient, workspace_id: str
) -> None:
    doc_id = _create(client, "doc_rename_route")
    repo = HybridRepository(workspace_id=workspace_id)
    before = repo.require_document(doc_id)["current_version"]
    renamed = client.put(f"/documents/{doc_id}/title", json={"title": " After "})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json() == {"schema_version": 1, "document_id": doc_id, "title": "After"}
    document = repo.require_document(doc_id)
    assert document["title"] == "After"
    assert document["scene"]["meta"]["title"] == "After"
    assert document["current_version"] == before + 1


def test_rename_refuses_blank_and_finalized(client: TestClient, workspace_id: str) -> None:
    doc_id = _create(client, "doc_rename_refused")
    assert client.put(f"/documents/{doc_id}/title", json={"title": "   "}).status_code == 422
    finalized = client.post(f"/documents/{doc_id}/finalize", json={})
    assert finalized.status_code == 200, finalized.text
    refused = client.put(f"/documents/{doc_id}/title", json={"title": "Nope"})
    assert refused.status_code == 409, refused.text


def test_archive_toggles_and_converges_without_a_version_bump(
    client: TestClient, workspace_id: str
) -> None:
    doc_id = _create(client, "doc_archive_route")
    repo = HybridRepository(workspace_id=workspace_id)
    version = repo.require_document(doc_id)["current_version"]
    assert client.put(f"/documents/{doc_id}/archived", json={}).status_code == 422
    archived = client.put(f"/documents/{doc_id}/archived", json={"archived": True})
    assert archived.status_code == 200, archived.text
    stamp = archived.json()["archived_at"]
    assert stamp
    again = client.put(f"/documents/{doc_id}/archived", json={"archived": True})
    assert again.json()["archived_at"] == stamp
    assert repo.require_document(doc_id)["current_version"] == version
    restored = client.put(f"/documents/{doc_id}/archived", json={"archived": False})
    assert restored.json()["archived_at"] is None


# --- K1-5 (founder ruling 2026-10-16): no rename while a design run drives the document ----------
#
# A rename moves the document version, and a site turn saves once, at the end, only if the version
# has not moved since it started — so a rename mid-run threw away the agent's whole request. The
# route now gives the same 409 every other manual write gives while a run holds the document.


def _scene_document(client: TestClient) -> str:
    return _create(client, "doc_rename_lock_scene")


def _web_document(client: TestClient) -> str:
    created = client.post("/documents", json={"doc_kind": "web", "title": "Before"})
    assert created.status_code == 200, created.text
    return created.json()["document"]["id"]


def _site_document(client: TestClient) -> str:
    return store_site(born_site("doc_rename_lock_site", title="Before"))["id"]


SEEDERS = {"scene": _scene_document, "web": _web_document, "site": _site_document}


@pytest.mark.parametrize("kind", sorted(SEEDERS))
def test_k1_5_a_rename_waits_while_a_design_run_drives_the_document(
    client: TestClient, workspace_id: str, kind: str
) -> None:
    doc_id = SEEDERS[kind](client)
    repo = HybridRepository(workspace_id=workspace_id)
    before = repo.require_document(doc_id)
    assert before["doc_kind"] == kind

    run_id = start_leg_run(repo, doc_id)
    try:
        assert_locked(client.put(f"/documents/{doc_id}/title", json={"title": "Mid-run"}), run_id)
        during = repo.require_document(doc_id)
        assert during["title"] == before["title"]
        assert during["current_version"] == before["current_version"]
    finally:
        finish_run(repo, run_id)

    # The run is over: the same rename goes through, exactly as before the ruling.
    renamed = client.put(f"/documents/{doc_id}/title", json={"title": "After the run"})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["title"] == "After the run"
    after = repo.require_document(doc_id)
    assert after["title"] == "After the run"
    assert after["current_version"] == before["current_version"] + 1


def test_k1_5_a_run_on_another_document_does_not_hold_this_ones_rename(
    client: TestClient, workspace_id: str
) -> None:
    busy = _create(client, "doc_rename_lock_busy")
    free = _create(client, "doc_rename_lock_free")
    repo = HybridRepository(workspace_id=workspace_id)
    run_id = start_leg_run(repo, busy)
    try:
        assert client.put(f"/documents/{free}/title", json={"title": "Free"}).status_code == 200
        assert_locked(client.put(f"/documents/{busy}/title", json={"title": "Busy"}), run_id)
    finally:
        finish_run(repo, run_id)
