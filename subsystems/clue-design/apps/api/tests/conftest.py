from __future__ import annotations

import sys
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
for _path in (API_ROOT, REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))



# --- D2.2 (design-integration Part II): per-test workspace isolation --------------------------
# Every domain lives on Postgres (clue_design) behind the request's workspace — D2.5B deleted
# SQLite outright, so the per-test `create_app(tmp_path / "api.sqlite3")` path now only anchors
# the per-test asset store and no file is created. Postgres is shared, so every test gets its
# OWN workspace id, making client-supplied fixture document ids collision-free across tests (doc
# ids are workspace-local since migration 7a9881f9717a). Rows accumulate in the dev/throwaway
# database; run this suite against a disposable CLUE_DATABASE_URL.
import os
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _isolated_design_workspace(monkeypatch: pytest.MonkeyPatch) -> str:
    workspace_id = f"ws_test_{uuid.uuid4().hex[:16]}"
    monkeypatch.setenv("LUMEN_DEV_WORKSPACE_ID", workspace_id)
    return workspace_id


def unique_run_id(label: str) -> str:
    """A collision-free agent-run id (D2.5A).

    Per-test workspaces make client-supplied *document* ids safe, because document ids are
    workspace-local. ``design_agent_run.run_id`` is a GLOBAL primary key in the D1 temporary
    shape, so a hard-coded run id in a test collides with the SAME test's row from the previous
    suite run against a persistent database. Production never hits this (run ids are uuid4);
    fixtures must mint one too. (D5's reshape is the place to revisit run-id scoping.)
    """
    return f"run_{label}_{uuid.uuid4().hex[:12]}"


def make_client(app: FastAPI) -> TestClient:
    """A TestClient that sends X-Workspace-Id on every request (D2.5A).

    The O4 seam is strict now — an absent header is a 401, not a silent fall-back to the dev
    workspace — so every suite client must carry one. It reads the SAME env var the autouse
    isolation fixture sets, so a client keeps talking to its own test's workspace, and direct
    store constructions in the same test agree with it.
    """
    return TestClient(app, headers={"X-Workspace-Id": os.environ["LUMEN_DEV_WORKSPACE_ID"]})


@pytest.fixture()
def workspace_id(_isolated_design_workspace: str) -> str:
    """This test's workspace — needed by the O6b public publish routes, whose tenant comes from
    the PATH (``/w/{workspace_id}/p/{slug}``) because a public visitor sends no header."""
    return _isolated_design_workspace
