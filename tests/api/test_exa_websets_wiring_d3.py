"""D3 production composition remains default-off and fails closed when enabled incorrectly."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from clue_api.exa_targeted_enrichment import (
    ExaTargetedEnrichmentStarter,
    build_production_exa_targeted_starter,
)
from clue_api.exa_websets_acquisition import ExaWebsetsDiscoveryStarter
from clue_api.fleet_main import (
    _build_exa_discovery_starter,
    _start_exa_discovery,
    _start_exa_targeted_enrichment,
)
from clue_api.projections_main import build_application
from clue_api.sumble_account_gaps import (
    SumbleAccountGapStarter,
    build_production_sumble_account_gap_starter,
)
from clue_api.sumble_discovery_gaps import (
    SumbleDiscoveryGapResolver,
    build_production_sumble_discovery_gap_resolver,
)
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


def test_paid_acquisition_is_default_off_and_enabled_without_api_key_fails_closed(
    tmp_path: Path,
) -> None:
    storage = FsStorage(tmp_path / "artifacts")
    assert (
        _build_exa_discovery_starter(
            Settings(_env_file=None),
            secrets=Secrets(_env_file=None, exa_api_key=None),
            storage=storage,
        )
        is None
    )
    with pytest.raises(RuntimeError, match="CLUE_EXA_API_KEY"):
        _build_exa_discovery_starter(
            Settings(
                _env_file=None,
                exa_websets_lifecycle_enabled=True,
                exa_websets_acquisition_enabled=True,
            ),
            secrets=Secrets(_env_file=None, exa_api_key=None),
            storage=storage,
        )
    with pytest.raises(RuntimeError, match="lifecycle worker is disabled"):
        _build_exa_discovery_starter(
            Settings(_env_file=None, exa_websets_acquisition_enabled=True),
            secrets=Secrets(_env_file=None, exa_api_key=SecretStr("fixture-exa-key")),
            storage=storage,
        )
    starter = _build_exa_discovery_starter(
        Settings(
            _env_file=None,
            exa_websets_lifecycle_enabled=True,
            exa_websets_acquisition_enabled=True,
        ),
        secrets=Secrets(_env_file=None, exa_api_key=SecretStr("fixture-exa-key")),
        storage=storage,
    )
    assert isinstance(starter, ExaWebsetsDiscoveryStarter)


def test_targeted_enrichment_is_independently_default_off_and_fails_closed(
    tmp_path: Path,
) -> None:
    storage = FsStorage(tmp_path / "artifacts")
    off = Settings(_env_file=None)
    no_secrets = Secrets(_env_file=None, exa_api_key=None)
    assert build_production_exa_targeted_starter(off, secrets=no_secrets, storage=storage) is None
    assert _start_exa_targeted_enrichment(off, secrets=no_secrets, storage=storage) is None

    with pytest.raises(RuntimeError, match="lifecycle worker is disabled"):
        build_production_exa_targeted_starter(
            Settings(_env_file=None, exa_targeted_enrichment_enabled=True),
            secrets=Secrets(_env_file=None, exa_api_key=SecretStr("fixture-exa-key")),
            storage=storage,
        )
    with pytest.raises(RuntimeError, match="CLUE_EXA_API_KEY"):
        build_production_exa_targeted_starter(
            Settings(
                _env_file=None,
                exa_websets_lifecycle_enabled=True,
                exa_targeted_enrichment_enabled=True,
            ),
            secrets=no_secrets,
            storage=storage,
        )
    with pytest.raises(RuntimeError, match="CLUE_EXA_API_KEY"):
        _start_exa_targeted_enrichment(
            Settings(_env_file=None, exa_websets_lifecycle_enabled=True),
            secrets=no_secrets,
            storage=storage,
        )
    starter = build_production_exa_targeted_starter(
        Settings(
            _env_file=None,
            exa_websets_lifecycle_enabled=True,
            exa_targeted_enrichment_enabled=True,
        ),
        secrets=Secrets(_env_file=None, exa_api_key=SecretStr("fixture-exa-key")),
        storage=storage,
    )
    assert isinstance(starter, ExaTargetedEnrichmentStarter)


def test_sumble_account_gaps_are_independently_default_off_and_fail_closed(
    tmp_path: Path,
) -> None:
    storage = FsStorage(tmp_path / "artifacts")
    no_secrets = Secrets(_env_file=None, sumble_api_key=None)
    assert (
        build_production_sumble_account_gap_starter(
            Settings(_env_file=None), secrets=no_secrets, storage=storage
        )
        is None
    )
    with pytest.raises(RuntimeError, match="CLUE_SUMBLE_API_KEY"):
        build_production_sumble_account_gap_starter(
            Settings(_env_file=None, sumble_account_gap_enrichment_enabled=True),
            secrets=no_secrets,
            storage=storage,
        )
    starter = build_production_sumble_account_gap_starter(
        Settings(
            _env_file=None,
            sumble_account_gap_enrichment_enabled=True,
            sumble_cents_per_credit="0.5",
        ),
        secrets=Secrets(_env_file=None, sumble_api_key=SecretStr("fixture-sumble-key")),
        storage=storage,
    )
    assert isinstance(starter, SumbleAccountGapStarter)


def test_preseal_sumble_waterfall_has_independent_authorization(tmp_path: Path) -> None:
    storage = FsStorage(tmp_path / "discovery-gap-artifacts")
    no_secrets = Secrets(_env_file=None, sumble_api_key=None)
    disabled = build_production_sumble_discovery_gap_resolver(
        Settings(_env_file=None), secrets=no_secrets, storage=storage
    )
    assert isinstance(disabled, SumbleDiscoveryGapResolver)

    with pytest.raises(RuntimeError, match="CLUE_SUMBLE_API_KEY"):
        build_production_sumble_discovery_gap_resolver(
            Settings(_env_file=None, sumble_discovery_gap_enrichment_enabled=True),
            secrets=no_secrets,
            storage=storage,
        )
    enabled = build_production_sumble_discovery_gap_resolver(
        Settings(
            _env_file=None,
            sumble_discovery_gap_enrichment_enabled=True,
            sumble_account_gap_enrichment_enabled=False,
            sumble_cents_per_credit="0.5",
        ),
        secrets=Secrets(_env_file=None, sumble_api_key=SecretStr("fixture-sumble-key")),
        storage=storage,
    )
    assert isinstance(enabled, SumbleDiscoveryGapResolver)


def test_the_websets_observer_marks_its_rows_as_estimated_spend() -> None:
    """Exa Websets is billed per result: its observed rows say ``estimate``, never ``free``."""
    from clue_api.provider_observers import cost_source_for

    assert cost_source_for("exa_websets") == "estimate"
    assert cost_source_for("clerk") == "free"
