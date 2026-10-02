"""The document-scoped agent-busy read (scene live-streaming rung A follow-up, 2026-09-03).

The standalone artifact route has no turn stream, so it asks the design API directly whether a
run is driving the document — the SAME predicate the manual-write routes' 409 uses, so the
page's lock and the server's refusal can never disagree about which state they are in.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from py_lumen_config import settings

from conftest import make_client
from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app
from test_agent_run_write_lock import create_document, finish_run, start_leg_run


@pytest.fixture(autouse=True)
def _no_embedded_fleet_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    # Same fixture, same reason, as test_agent_run_write_lock: this module seeds run rows
    # directly and never offers work; an embedded worker would drain the shared queue.
    monkeypatch.setattr(settings, "lumen_embedded_fleet_worker", False, raising=False)


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    return make_client(create_app(tmp_path / "engine-cache"))


def read_agent_run(client: TestClient, document_id: str) -> dict:
    response = client.get(f"/documents/{document_id}/agent-run")
    assert response.status_code == 200, response.text
    return response.json()


def test_an_idle_document_reports_no_run_and_its_current_version(client: TestClient) -> None:
    document = create_document(client, "Idle")
    body = read_agent_run(client, document["id"])
    assert body["schema_version"] == 1
    assert body["document_id"] == document["id"]
    assert body["active"] is False
    assert body["run_id"] is None
    assert body["current_version"] == document["current_version"]


def test_a_running_run_is_reported_and_clears_when_it_finishes(client: TestClient) -> None:
    document = create_document(client, "Driven")
    store = HybridRepository()
    run_id = start_leg_run(store, document["id"])

    busy = read_agent_run(client, document["id"])
    assert busy["active"] is True
    assert busy["run_id"] == run_id

    finish_run(store, run_id)
    idle = read_agent_run(client, document["id"])
    assert idle["active"] is False
    assert idle["run_id"] is None


def test_a_run_on_another_document_does_not_lock_this_one(client: TestClient) -> None:
    driven = create_document(client, "Driven")
    bystander = create_document(client, "Bystander")
    store = HybridRepository()
    run_id = start_leg_run(store, driven["id"])
    try:
        assert read_agent_run(client, bystander["id"])["active"] is False
        assert read_agent_run(client, driven["id"])["run_id"] == run_id
    finally:
        finish_run(store, run_id)


def test_an_unknown_document_is_a_404(client: TestClient) -> None:
    response = client.get("/documents/doc_does_not_exist/agent-run")
    assert response.status_code == 404, response.text
