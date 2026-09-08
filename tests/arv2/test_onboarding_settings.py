"""Track O flags: typed, defaulted, documented in .env.example, loadable from their env string."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from clue_config import Settings

REPO = Path(__file__).resolve().parents[2]
ENV_EXAMPLE = REPO / ".env.example"

#: ARV2-ONBOARDING-PLAN.md §10 — every onboarding knob and the default the lane ships with.
ONBOARDING_SETTING_DEFAULTS: dict[str, object] = {
    "onboarding_v2_enabled": False,
    "onboarding_overview_effort": "high",
    "onboarding_reviews_effort": "medium",
    "onboarding_product_effort": "medium",
    "onboarding_reviews_phase": "fast",
    "onboarding_max_parallel_runs": 6,
    "onboarding_persona_evidence_enabled": True,
}

#: Documented in the agent-model block today; read by the registry once the role exists (O4).
AGENT_MODEL_LINES = (
    "ONBOARDING_SYNTHESIS_AGENT_MODEL=x-ai/grok-4.6",
    "ONBOARDING_SYNTHESIS_AGENT_MODEL_EFFORT=",
)


def _env_name(field_name: str) -> str:
    return f"CLUE_{field_name.upper()}"


@pytest.fixture
def unset_onboarding_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for field_name in ONBOARDING_SETTING_DEFAULTS:
        monkeypatch.delenv(_env_name(field_name), raising=False)


def test_every_onboarding_setting_has_its_shipped_default(unset_onboarding_env: None) -> None:
    settings = Settings(_env_file=None)
    for field_name, expected in ONBOARDING_SETTING_DEFAULTS.items():
        assert getattr(settings, field_name) == expected, field_name


def test_the_lane_flag_ships_off() -> None:
    """Flips only after O7 acceptance (plan §10)."""
    assert Settings.model_fields["onboarding_v2_enabled"].default is False


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
        shipped = str(default).lower() if isinstance(default, bool) else str(default)
        # dotenv semantics: one pair of matching surrounding quotes is not part of the value.
        value = documented.group(1).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        assert value == shipped, field_name


def test_the_synthesis_agent_model_lines_are_documented() -> None:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    for line in AGENT_MODEL_LINES:
        assert re.search(rf"^{re.escape(line)}$", text, re.MULTILINE), line
