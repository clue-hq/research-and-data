"""D3 production composition remains default-off and fails closed when enabled incorrectly."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from clue_api.fleet_main import _start_exa_discovery
from clue_api.projections_main import build_application
from clue_config import Secrets, Settings
from clue_storage import FsStorage


def _paths(app: FastAPI) -> set[str]:
    paths: set[str] = set()
    for route in app.routes:
        path = getattr(route, "path", None)
        if isinstance(path, str):
            paths.add(path)
        original = getattr(route, "original_router", None)
        if original is not None:
            for child in original.routes:
                child_path = getattr(child, "path", None)
                if isinstance(child_path, str):
                    paths.add(child_path)
    return paths


def test_production_http_app_mounts_webhook_only_when_secret_is_configured(
    tmp_path: Path,
) -> None:
    settings = Settings(_env_file=None, storage_fs_root=str(tmp_path / "artifacts"))
    without = build_application(settings, secrets=Secrets(_env_file=None))
    with_secret = build_application(
        settings,
        secrets=Secrets(
            _env_file=None,
            exa_websets_webhook_secret=SecretStr("fixture-webhook-secret"),
        ),
    )
    path = "/v1/webhooks/exa-websets"
    assert path not in _paths(without)
    assert path in _paths(with_secret)


def test_poll_worker_is_default_off_and_enabled_without_api_key_fails_closed(
    tmp_path: Path,
) -> None:
    storage = FsStorage(tmp_path / "artifacts")
    assert (
        _start_exa_discovery(
            Settings(_env_file=None),
            secrets=Secrets(_env_file=None, exa_api_key=None),
            storage=storage,
        )
        is None
    )
    with pytest.raises(RuntimeError, match="CLUE_EXA_API_KEY"):
        _start_exa_discovery(
            Settings(_env_file=None, exa_websets_lifecycle_enabled=True),
            secrets=Secrets(_env_file=None, exa_api_key=None),
            storage=storage,
        )
