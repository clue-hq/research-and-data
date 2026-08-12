"""Slice 3: both production roots compose the *real* Stage-0 claim extractor.

Slice 2 wired an explicitly empty ``CallableClaimExtractor`` at both composition roots, so live
recon fetched pages, stored snapshots, and drafted nothing. Task 4 built the real
:class:`~clue_api.claim_extraction.LlmClaimExtractor`; this pins that the roots actually reach for
it — and, just as importantly, that a deployment with **no** model credential degrades to the old
empty extractor (recon still captures evidence) instead of refusing to start.

The gateway builder the roots use is the *optional* one:
:func:`~clue_api.run_composition.build_optional_platform_gateway`. ``build_platform_gateway``
raises without an ``OPENROUTER_API_KEY`` (correct for the fleet worker, which cannot do its job
without a model); a missing key must not take the whole HTTP process down over one tool's
extractor, so the optional builder warns loudly and returns ``None``.

Hermetic by construction: ``Settings(_env_file=None)`` plus the api-suite autouse flag scrub cover
the settings channel, and ``Secrets`` (which keeps its own ``.env`` loading on purpose — the DB
skip-gate depends on it) is monkeypatched at the ``run_composition`` call site so a developer's real
OpenRouter key cannot make the no-gateway cases pass or fail by accident.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from clue_api import fleet_main, projections_main, run_composition
from clue_api.claim_extraction import LlmClaimExtractor
from clue_api.phase_c_wiring import Stage0ScrapeBinder
from clue_config import Secrets, Settings
from clue_core import ClaimDraft, Entity, EntityType, FieldDef, NormalizedText, PassKind
from clue_obs import capture_events
from clue_research.adapters import CallableClaimExtractor


class _NoKeySecrets:
    """Stands in for ``Secrets`` with no OpenRouter key configured (the pattern
    ``tests/api/test_run_composition.py`` already uses for the gateway gate)."""

    openrouter_api_key = None


class _FakeGateway:
    """An :class:`~clue_core.gateway.LLMGateway` that is never called: these tests compose, they
    do not extract."""

    def complete(self, *, model: str, messages: list[Any], **opts: object) -> Any:
        raise AssertionError("composition tests must not call the model")

    def embed(self, *, model: str, inputs: list[str]) -> Any:
        raise AssertionError("composition tests must not call the model")


def _settings(tmp_path: Path, **overrides: Any) -> Settings:
    return Settings(
        _env_file=None,
        storage_fs_root=str(tmp_path / "artifacts"),
        **overrides,
    )


def _captured_extractor(monkeypatch: pytest.MonkeyPatch, module: Any) -> dict[str, Any]:
    """Capture the ``extractor`` a root hands ``build_stage0_scrape_binder``.

    The binder keeps its extractor private and neither root returns it, so the composed value is
    observed at the seam where it is passed. The real binder is still built (the capture delegates),
    so the root's own wiring is exercised, not replaced.
    """
    seen: dict[str, Any] = {}
    real = module.build_stage0_scrape_binder

    def capturing(**kwargs: Any) -> Stage0ScrapeBinder:
        seen.update(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(module, "build_stage0_scrape_binder", capturing)
    return seen


# --- the optional gateway builder ----------------------------------------------------------------


def test_optional_gateway_is_none_and_warns_without_a_key_or_stub_optin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No key and no stub opt-in: ``None`` plus a loud, greppable warning — never the RuntimeError
    ``build_platform_gateway`` raises (which would take the HTTP root down at import)."""
    monkeypatch.setattr(run_composition, "Secrets", _NoKeySecrets)
    settings = Settings(_env_file=None, gateway_allow_stub=False)
    with capture_events(mode="info") as cap:
        gateway = run_composition.build_optional_platform_gateway(settings)
    assert gateway is None
    assert cap.has("stage0.claim_extraction_disabled_no_gateway")


def test_optional_gateway_builds_the_gateway_when_the_stub_is_opted_into(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the explicit CI/test opt-in (or a real key) the optional builder returns the same
    gateway ``build_platform_gateway`` would."""
    monkeypatch.setattr(run_composition, "Secrets", _NoKeySecrets)
    settings = Settings(_env_file=None, gateway_allow_stub=True)
    assert run_composition.build_optional_platform_gateway(settings) is not None


def test_optional_gateway_returns_the_real_gateway_when_a_key_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured key needs no stub opt-in — the optional builder must not add a second gate."""

    class _KeyedSecrets:
        openrouter_api_key = "test-key"

    monkeypatch.setattr(run_composition, "Secrets", _KeyedSecrets)
    settings = Settings(_env_file=None, gateway_allow_stub=False)
    assert run_composition.build_optional_platform_gateway(settings) is not None


# --- the extractor selector ----------------------------------------------------------------------


def test_stage0_extractor_is_the_llm_extractor_when_a_gateway_exists() -> None:
    assert isinstance(
        run_composition.build_stage0_claim_extractor(_FakeGateway()), LlmClaimExtractor
    )


def test_stage0_extractor_falls_back_to_a_drafting_nothing_extractor_without_a_gateway() -> None:
    """The slice-2 posture, kept for a keyless deployment: recon still resolves, scrapes and
    snapshots — it just drafts no values."""
    extractor = run_composition.build_stage0_claim_extractor(None)
    assert isinstance(extractor, CallableClaimExtractor)
    drafts: list[ClaimDraft] = extractor.extract(
        NormalizedText(text="Acme sells widgets."),
        Entity(entity_id=uuid4(), entity_type=EntityType.ACCOUNT),
        FieldDef(field_key="client.value_prop", value_type="str", pass_kind=PassKind.DEEP),
    )
    assert drafts == []


# --- the HTTP root -------------------------------------------------------------------------------


def test_projections_root_composes_the_llm_extractor_when_a_gateway_is_available(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(run_composition, "Secrets", _NoKeySecrets)
    seen = _captured_extractor(monkeypatch, projections_main)
    projections_main.build_application(
        _settings(tmp_path, self_serve_provisioning_enabled=True, gateway_allow_stub=True),
        secrets=Secrets(_env_file=None),
    )
    assert isinstance(seen["extractor"], LlmClaimExtractor)


def test_projections_root_falls_back_to_the_empty_extractor_without_a_gateway(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(run_composition, "Secrets", _NoKeySecrets)
    seen = _captured_extractor(monkeypatch, projections_main)
    projections_main.build_application(
        _settings(tmp_path, self_serve_provisioning_enabled=True, gateway_allow_stub=False),
        secrets=Secrets(_env_file=None),
    )
    assert isinstance(seen["extractor"], CallableClaimExtractor)


def test_projections_root_builds_no_gateway_when_the_scrape_surface_is_off(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Flag off: no binder, and no gateway warmed for one that will not exist."""
    calls: list[Settings] = []

    def counting(settings: Settings) -> None:
        calls.append(settings)
        return None

    monkeypatch.setattr(projections_main, "build_optional_platform_gateway", counting)
    seen = _captured_extractor(monkeypatch, projections_main)
    projections_main.build_application(
        _settings(tmp_path, self_serve_provisioning_enabled=False),
        secrets=Secrets(_env_file=None),
    )
    assert calls == []
    assert seen == {}


# --- the fleet root ------------------------------------------------------------------------------


def test_fleet_root_composes_the_llm_extractor_from_its_existing_gateway(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen = _captured_extractor(monkeypatch, fleet_main)
    binder = fleet_main._build_stage0_scrape_binder(
        _settings(tmp_path, self_serve_provisioning_enabled=True), gateway=_FakeGateway()
    )
    assert isinstance(binder, Stage0ScrapeBinder)
    assert isinstance(seen["extractor"], LlmClaimExtractor)


def test_fleet_root_has_no_binder_when_the_scrape_surface_is_off(tmp_path: Path) -> None:
    assert (
        fleet_main._build_stage0_scrape_binder(
            _settings(tmp_path, self_serve_provisioning_enabled=False), gateway=_FakeGateway()
        )
        is None
    )


def test_the_fleet_worker_builds_exactly_one_gateway() -> None:
    """The worker's extractor must reuse the gateway ``_serve`` already built — a second
    ``build_platform_gateway`` would mean a second client (and a second stub-mode warning) for the
    same credential."""
    source = inspect.getsource(fleet_main)
    calls = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"build_platform_gateway", "build_optional_platform_gateway"}
    ]
    assert len(calls) == 1
