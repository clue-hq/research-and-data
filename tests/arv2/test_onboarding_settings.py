"""Track O flags: typed, defaulted, documented in .env.example, loadable from their env string."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from clue_config import Settings
from tests._model_ids import assert_well_formed_model_id

REPO = Path(__file__).resolve().parents[2]
ENV_EXAMPLE = REPO / ".env.example"

#: Which model a step uses is an env setting, never a test expectation: this entry is checked
#: for a well-formed id, not for a particular model (``tests/_model_ids.py``).
MODEL_ID = object()

#: ARV2-ONBOARDING-PLAN.md §10 — every onboarding knob and the default the lane ships with.
ONBOARDING_SETTING_DEFAULTS: dict[str, object] = {
    # On by default since 2026-09-12 (spec 2026-09-12-onboarding-v2-default).
    "onboarding_v2_enabled": True,
    "onboarding_overview_effort": "high",
    "onboarding_reviews_effort": "medium",
    "onboarding_product_effort": "medium",
    "onboarding_customers_effort": "xhigh",
    "onboarding_reviews_phase": "fast",
    "onboarding_max_parallel_runs": 6,
    "onboarding_persona_evidence_enabled": True,
    "onboarding_catalog_reconcile_enabled": True,
    "onboarding_reconcile_model": MODEL_ID,
}

#: Documented in the agent-model block today; read by the registry once the role exists (O4).
AGENT_MODEL_KEYS = ("ONBOARDING_SYNTHESIS_AGENT_MODEL", "ONBOARDING_SYNTHESIS_AGENT_MODEL_EFFORT")


def _env_name(field_name: str) -> str:
    return f"CLUE_{field_name.upper()}"


@pytest.fixture
def unset_onboarding_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for field_name in ONBOARDING_SETTING_DEFAULTS:
        monkeypatch.delenv(_env_name(field_name), raising=False)


def test_every_onboarding_setting_has_its_shipped_default(unset_onboarding_env: None) -> None:
    settings = Settings(_env_file=None)
    for field_name, expected in ONBOARDING_SETTING_DEFAULTS.items():
        if expected is MODEL_ID:
            assert_well_formed_model_id(getattr(settings, field_name))
            continue
        assert getattr(settings, field_name) == expected, field_name


def test_the_lane_flag_ships_on() -> None:
    """Flipped on 2026-09-12 after O7 acceptance (plan §10); the Welcome flow runs this lane."""
    assert Settings.model_fields["onboarding_v2_enabled"].default is True


def test_reviews_phase_loads_from_its_env_string(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Literal that rejects its own documented env form is a bug (CLAUDE.md parity rule)."""
    monkeypatch.setenv("CLUE_ONBOARDING_REVIEWS_PHASE", "background")
    assert Settings(_env_file=None).onboarding_reviews_phase == "background"
    monkeypatch.setenv("CLUE_ONBOARDING_REVIEWS_PHASE", "sideways")
    with pytest.raises(ValueError):
        Settings(_env_file=None)


def test_max_parallel_runs_must_be_positive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLUE_ONBOARDING_MAX_PARALLEL_RUNS", "0")
    with pytest.raises(ValueError):
        Settings(_env_file=None)


def test_every_onboarding_env_name_is_documented_with_its_default() -> None:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    for field_name, default in ONBOARDING_SETTING_DEFAULTS.items():
        documented = re.search(rf"^{_env_name(field_name)}=(.*)$", text, re.MULTILINE)
        assert documented is not None, f"absent from .env.example: {_env_name(field_name)}"
        # dotenv semantics: one pair of matching surrounding quotes is not part of the value.
        value = documented.group(1).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if default is MODEL_ID:
            # The example documents whatever the code default is today; neither pins a model.
            assert_well_formed_model_id(value)
            assert value == Settings.model_fields[field_name].default, field_name
            continue
        shipped = str(default).lower() if isinstance(default, bool) else str(default)
        assert value == shipped, field_name


def test_the_synthesis_agent_model_lines_are_documented() -> None:
    """The role's model and effort lines exist in the example; the model named is the operator's."""
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    for key in AGENT_MODEL_KEYS:
        documented = re.search(rf"^{key}=(.*)$", text, re.MULTILINE)
        assert documented is not None, key
    model_line = re.search(r"^ONBOARDING_SYNTHESIS_AGENT_MODEL=(.*)$", text, re.MULTILINE)
    assert model_line is not None
    assert_well_formed_model_id(model_line.group(1).strip())
