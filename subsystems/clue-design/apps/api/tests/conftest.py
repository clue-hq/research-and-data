from __future__ import annotations

import sys
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
for _path in (API_ROOT, REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))



# --- D2.2 (design-integration Part II): per-test workspace isolation --------------------------
# The document domain lives on Postgres (clue_design) behind the request's workspace. Each test
# keeps its fresh per-test SQLite file, but Postgres is shared — so every test gets its OWN
# workspace id, making client-supplied fixture document ids collision-free across tests (doc
# ids are workspace-local since migration 7a9881f9717a). Rows accumulate in the dev/throwaway
# database; run this suite against a disposable CLUE_DATABASE_URL.
import os
import uuid

import pytest


@pytest.fixture(autouse=True)
def _isolated_design_workspace(monkeypatch: pytest.MonkeyPatch) -> str:
    workspace_id = f"ws_test_{uuid.uuid4().hex[:16]}"
    monkeypatch.setenv("LUMEN_DEV_WORKSPACE_ID", workspace_id)
    return workspace_id


@pytest.fixture()
def workspace_id(_isolated_design_workspace: str) -> str:
    """This test's workspace — needed by the O6b public publish routes, whose tenant comes from
    the PATH (``/w/{workspace_id}/p/{slug}``) because a public visitor sends no header."""
    return _isolated_design_workspace
