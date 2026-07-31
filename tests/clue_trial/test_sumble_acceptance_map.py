"""Contract guards for the Sumble-only Clue Trial acceptance map."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_MAP = (
    Path(__file__).parents[1] / "fixtures" / "clue_trial" / "sumble_acceptance_map.json"
)
_COVERAGE = {"full", "partial", "none"}
_FIRST_WAVE_SOURCES = {
    "sumble_organizations",
    "sumble_jobs",
    "sumble_tech_stack",
}


def _load() -> dict[str, Any]:
    return json.loads(_MAP.read_text(encoding="utf-8"))


def test_acceptance_case_ids_are_unique_and_classified() -> None:
    payload = _load()
    cases = payload["cases"]
    ids = [case["id"] for case in cases]

    assert ids
    assert len(ids) == len(set(ids))
    assert all(case["cli_coverage"] in _COVERAGE for case in cases)
    assert all(
        case["companion_surface"]
        if case["cli_coverage"] in {"partial", "none"}
        else case["companion_surface"] is None
        for case in cases
    )


def test_first_wave_is_exactly_sumble_organizations_jobs_and_tech() -> None:
    payload = _load()
    enabled = {
        surface["source_key"]
        for surface in payload["provider_surfaces"]
        if surface["enabled_in_first_wave"]
    }
    policy = payload["source_policy"]

    assert enabled == _FIRST_WAVE_SOURCES
    assert set(policy["allowed_external_factual_sources"]) == _FIRST_WAVE_SOURCES
    assert _FIRST_WAVE_SOURCES.isdisjoint(policy["forbidden_first_wave_sources"])
    assert policy["model_runtime_is_factual_source"] is False


def test_every_enabled_surface_maps_at_least_one_field() -> None:
    payload = _load()
    for surface in payload["provider_surfaces"]:
        if surface["enabled_in_first_wave"]:
            assert surface["field_keys"], surface["source_key"]


def test_first_wave_covers_provider_research_view_and_durability() -> None:
    payload = _load()
    categories = {case["category"] for case in payload["cases"] if case["first_wave"]}

    assert {
        "provider",
        "provider_failure",
        "stage0",
        "icp",
        "account",
        "research",
        "research_view",
        "durability",
        "security",
    } <= categories
