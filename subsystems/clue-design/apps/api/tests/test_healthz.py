"""Liveness for Railway, the uptime monitors and the boot smoke test (first deployment §9.5)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_healthz_answers_without_a_workspace_header(tmp_path, design_storage) -> None:
    from lumen_api.main import create_app

    app = create_app(tmp_path / "engine-cache", storage=design_storage)
    with TestClient(app) as client:  # deliberately NOT make_client: no X-Workspace-Id header
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
