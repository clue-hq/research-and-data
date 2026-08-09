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
# SQLite outright, and D4 replaced the vestigial `database_path` anchor with the ENGINE
# MATERIALIZATION CACHE root, which is what `create_app(tmp_path / "engine-cache")` now names
# (a transient per-workspace mirror, not a store — durable bytes live in platform storage).
# Postgres is shared, so every test gets its
# OWN workspace id, making client-supplied fixture document ids collision-free across tests (doc
# ids are workspace-local since migration 7a9881f9717a). Rows accumulate in the dev/throwaway
# database; run this suite against a disposable CLUE_DATABASE_URL.
import os
import uuid

import pytest
from clue_storage import FsStorage
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lumen_api.design_store import DesignBlobStore


@pytest.fixture(autouse=True)
def _isolated_design_workspace(monkeypatch: pytest.MonkeyPatch) -> str:
    workspace_id = f"ws_test_{uuid.uuid4().hex[:16]}"
    monkeypatch.setenv("LUMEN_DEV_WORKSPACE_ID", workspace_id)
    return workspace_id


# --- D4 (design-integration Part II): per-test design BYTE store ------------------------------
# Design bytes live in platform storage (clue_storage) since D4. The default backend is the
# process-wide `storage_from_settings()` one, so every suite that writes blobs injects a
# throwaway `FsStorage(tmp_path)` into `create_app` instead — the blobs then die with the test's
# tmp_path, exactly as the old per-test `asset-store/custom-components` tree did. Artifact ROWS
# still land in the shared Postgres under this test's own workspace id, which is what keeps
# content-addressed keys collision-free across tests.


@pytest.fixture(autouse=True)
def _isolated_design_storage_root(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the DEFAULT fs backend at this test's tmp_path.

    A suite that does not inject a backend still gets `storage_from_settings()`, whose fs root
    defaults to `.artifacts` in the process cwd — test blobs would accumulate in the repo. This
    keeps every non-injecting `create_app` disposable too, without each suite having to know that
    design bytes moved.
    """
    monkeypatch.setenv("CLUE_STORAGE_FS_ROOT", str(tmp_path / "default-storage"))


@pytest.fixture()
def design_storage(tmp_path) -> FsStorage:
    """This test's disposable design blob backend."""
    return FsStorage(tmp_path / "design-storage")


def make_blob_store(app: FastAPI) -> DesignBlobStore:
    """A blob-store handle on the app's backend, scoped to this test's workspace.

    The direct-store analogue of `HybridRepository()`: it reads the SAME env var the isolation
    fixture sets, so a test that persists bytes out-of-band and then reads them back through the
    app is talking to one tenant and one backend.
    """
    return DesignBlobStore(app.state.storage, os.environ["LUMEN_DEV_WORKSPACE_ID"])


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
