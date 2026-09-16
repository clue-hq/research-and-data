from __future__ import annotations

import contextlib
import sys
from pathlib import Path
from typing import Iterator, List


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
from py_lumen_config import settings

from lumen_api.design_store import DesignBlobStore


# --- D9: no test in this suite may reach the Brandfetch vendor --------------------------------
# The repo-root `.env` can carry a REAL Brandfetch key, and the command that runs this suite
# sources it, so an un-patched `fetch_vendor_family` would spend live quota against a live API.
# It reads `settings.brandfetch_api_key` at CALL time (lumen_ingestion/logo_vendor.py), so
# blanking the field here makes it raise `VendorCredentialsMissing` for every test that has not
# deliberately supplied a key. The vendor suite passes `api_key=` explicitly (or asserts on the
# blank-key refusal), so it is untouched by this.
@pytest.fixture(autouse=True)
def _brandfetch_vendor_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "brandfetch_api_key", "")
    monkeypatch.setattr(settings, "logo_dev_secret_key", "")


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


#: How long an ingestion-job poller waits for the embedded fleet worker to reach a terminal row.
#: Generous because a real ingestion pass does engine work; a job that is genuinely stuck fails
#: the assertion that follows rather than hanging the suite.
INGESTION_JOB_TIMEOUT_S = 60.0


def wait_for_ingestion_job(
    client: TestClient, job_id: str, timeout_s: float = INGESTION_JOB_TIMEOUT_S
) -> dict:
    """Block until an ingestion job reaches a terminal status, then return it.

    D5 Round C moved ingestion off ``BackgroundTasks`` onto the ``design_job`` fleet queue. Under
    ``BackgroundTasks`` the TestClient ran the work synchronously before unblocking the POST, so
    a test could assert on a finished job the instant the response came back. Now the API OFFERS
    the job and the embedded fleet worker — a real task on the app's own event loop — claims and
    executes it, so the POST returns while the job is still ``queued``. That is the production
    behaviour, so the suites wait for it rather than pretending it did not change.

    Returns the terminal job dto; on timeout it returns the LAST-seen one so the caller's own
    assertion reports the real status (``running``/``queued``) instead of a bare TimeoutError.
    """
    import time

    deadline = time.monotonic() + timeout_s
    job: dict = {}
    while True:
        response = client.get(f"/brand-kits/ingest/{job_id}")
        if response.status_code == 200:
            job = response.json()["job"]
            if job.get("status") in ("succeeded", "failed"):
                return job
        if time.monotonic() >= deadline:
            return job
        time.sleep(0.05)


def unique_run_id(label: str) -> str:
    """A collision-free agent-run id (D2.5A).

    Per-test workspaces make client-supplied *document* ids safe, because document ids are
    workspace-local. ``design_agent_run.run_id`` is a GLOBAL primary key in the D1 temporary
    shape, so a hard-coded run id in a test collides with the SAME test's row from the previous
    suite run against a persistent database. Production never hits this (run ids are uuid4);
    fixtures must mint one too. (D5's reshape is the place to revisit run-id scoping.)
    """
    return f"run_{label}_{uuid.uuid4().hex[:12]}"


#: Clients whose lifespan this module entered, closed by the autouse fixture below. Module-level
#: rather than fixture-owned because `make_client` is a plain helper called mid-test (often more
#: than once), so it has no fixture scope of its own to hang teardown on.
_LIFESPAN_CLIENTS: List[TestClient] = []


@pytest.fixture(autouse=True)
def _shutdown_lifespan_clients() -> Iterator[None]:
    """Run every `make_client` app's shutdown at test end — stopping its embedded fleet worker.

    Paired with `make_client` entering the lifespan (see there). Exceptions on the way out are
    suppressed deliberately: a test that already failed must not be re-reported as a teardown
    error, and the worker task is cancelled by the lifespan itself in any case.
    """
    yield
    while _LIFESPAN_CLIENTS:
        client = _LIFESPAN_CLIENTS.pop()
        with contextlib.suppress(Exception):
            client.__exit__(None, None, None)


def make_client(app: FastAPI) -> TestClient:
    """A TestClient that sends X-Workspace-Id on every request (D2.5A), with its LIFESPAN RUNNING.

    The O4 seam is strict now — an absent header is a 401, not a silent fall-back to the dev
    workspace — so every suite client must carry one. It reads the SAME env var the autouse
    isolation fixture sets, so a client keeps talking to its own test's workspace, and direct
    store constructions in the same test agree with it.

    D5 Round B: the client is ENTERED here (`__enter__`), because Starlette runs an app's
    lifespan only inside the context manager and the lifespan is what starts the embedded design
    fleet worker. Agent/web turns are leased fleet work now — a turn offered with nobody draining
    the queue would sit `queued` for the whole test. Adapting this one helper keeps every async-
    turn test unchanged; the autouse fixture above owns the matching exit.
    """
    client = TestClient(app, headers={"X-Workspace-Id": os.environ["LUMEN_DEV_WORKSPACE_ID"]})
    client.__enter__()
    _LIFESPAN_CLIENTS.append(client)
    return client


@pytest.fixture()
def workspace_id(_isolated_design_workspace: str) -> str:
    """This test's workspace — needed by the O6b public publish routes, whose tenant comes from
    the PATH (``/w/{workspace_id}/p/{slug}``) because a public visitor sends no header."""
    return _isolated_design_workspace
