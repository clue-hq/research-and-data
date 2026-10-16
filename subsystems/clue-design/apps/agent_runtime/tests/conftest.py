from __future__ import annotations

import sys
from pathlib import Path

import pytest
from py_lumen_config import settings


RUNTIME_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
for _path in (RUNTIME_ROOT, REPO_ROOT / "apps" / "api", REPO_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))


# --- D9: no test in this suite may reach the Brandfetch vendor -------------------------------
# The repo-root `.env` can carry a REAL Brandfetch key, and the command that runs this suite
# sources it, so an un-patched `fetch_logo_family` would spend live quota against a live API.
# `fetch_vendor_family` reads `settings.brandfetch_api_key` at CALL time
# (apps/api/lumen_ingestion/logo_vendor.py), so blanking the field here makes the vendor rung
# raise `VendorCredentialsMissing` for every test that has not deliberately replaced it — the
# dispatch then degrades to the ladder, which is already faked. Tests that DO want the vendor
# path patch `logo_fetch._vendor_rung` (or pass an explicit `api_key=`) themselves, and are
# untouched by this.
@pytest.fixture(autouse=True)
def _brandfetch_vendor_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "brandfetch_api_key", "")


# Compaction is sized from the model's context window, which `clue_gateway.model_windows` reads
# from OpenRouter's public catalogue once per process. An empty cache answers "window unknown"
# without the network, so a harness built in a test compacts at the fixed fallback.
@pytest.fixture(autouse=True)
def _model_windows_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    import clue_gateway.model_windows as model_windows

    monkeypatch.setattr(model_windows, "_cache", {})
