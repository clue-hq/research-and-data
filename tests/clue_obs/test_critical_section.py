"""clue_obs.critical_section: a slow lock-holding section names itself in the log."""

from __future__ import annotations

import importlib

import pytest

from clue_obs import critical_section
from clue_obs.testing import capture_events

# The package attribute ``clue_obs.critical_section`` is the exported function, so the module is
# fetched by name.
critical_section_module = importlib.import_module("clue_obs.critical_section")


def _clock(monkeypatch: pytest.MonkeyPatch, *readings: float) -> None:
    values = iter(readings)
    monkeypatch.setattr(critical_section_module.time, "monotonic", lambda: next(values))


def test_a_section_over_the_threshold_logs_its_name_duration_and_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLUE_DB_CRITICAL_SECTION_LOG_MS", "100")
    _clock(monkeypatch, 10.0, 10.25)
    with capture_events(mode="info") as cap, critical_section("artifact.persist", job_id="j1"):
        pass
    event = cap.first("db.critical_section")
    assert event is not None
    assert event["name"] == "artifact.persist"
    assert event["held_ms"] == 250.0
    assert event["job_id"] == "j1"


def test_a_fast_section_stays_quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLUE_DB_CRITICAL_SECTION_LOG_MS", "100")
    _clock(monkeypatch, 10.0, 10.05)
    with capture_events(mode="info") as cap, critical_section("artifact.persist"):
        pass
    assert not cap.has("db.critical_section")


def test_default_threshold_is_500_ms_and_a_bad_value_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CLUE_DB_CRITICAL_SECTION_LOG_MS", "not-a-number")
    _clock(monkeypatch, 0.0, 0.499)
    with capture_events(mode="info") as cap, critical_section("x"):
        pass
    assert not cap.has("db.critical_section")


def test_the_section_is_logged_even_when_its_body_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLUE_DB_CRITICAL_SECTION_LOG_MS", "0")
    _clock(monkeypatch, 0.0, 1.0)
    with capture_events(mode="info") as cap, pytest.raises(RuntimeError), critical_section("x"):
        raise RuntimeError("boom")
    assert cap.has("db.critical_section")
