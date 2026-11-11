"""Recipe 43: the footprint jobs and the Jev speaker check (footprint plan, Task 14).

The person and account researchers pin version 3 of acquire_research_evidence (podcast, video,
handle and social-post jobs) and read the founder-approved prompts of 2026-11-11 (person v31-person,
account v42). Everything else is recipe 42's.
"""

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from clue_agents import AgentRole
from clue_api.arv2.quality_catalog import CURRENT_RECIPE_VERSION, load_quality_resources
from clue_api.quality_research_wiring import CATALOG_ROOT, quality_profiles, quality_tools

_ROOT = Path(CATALOG_ROOT)


def _text(path: str) -> str:
    return (_ROOT / path).read_text()


def test_recipe_43_pins_match_files():
    launch = json.loads(_text("launch-v4-r43.json"))
    assert launch["recipe_version"] == 43 and CURRENT_RECIPE_VERSION >= 43
    for path, sha in launch["resources"].items():
        assert hashlib.sha256((_ROOT / path).read_bytes()).hexdigest() == sha, path
    for path in (
        "recipe-v43.json",
        "prompts/quality-person-research/v31-person/SYSTEM.md",
        "profiles/quality-person-research/v31-person/profile.yaml",
        "prompts/quality-account-research/v42/SYSTEM.md",
        "profiles/quality-account-research/v42/profile.yaml",
    ):
        assert path in launch["resources"], path
    assert not any(
        "v30-person" in p or "quality-account-research/v41" in p for p in launch["resources"]
    )
    load_quality_resources("account", version=43)  # every pinned file loads and matches


@pytest.mark.parametrize(
    ("version", "person", "expected"),
    [(43, False, "v42"), (43, True, "v31-person"), (42, False, "v41"), (42, True, "v30-person")],
)
def test_recipe_selects_its_own_profiles(version, person, expected):
    tools = quality_tools(None, None, purge=False)
    registry = quality_profiles(tools, version=version, person=person)
    assert registry.resolve(AgentRole.ACCOUNT_RESEARCH).profile.version == expected


@pytest.mark.parametrize(
    "path",
    [
        "profiles/quality-person-research/v31-person/profile.yaml",
        "profiles/quality-account-research/v42/profile.yaml",
    ],
)
def test_recipe_43_pins_acquire_v3(path):
    profile = yaml.safe_load(_text(path))
    pin = next(t for t in profile["tools"] if t["name"] == "acquire_research_evidence")
    descriptor = quality_tools(None, None, purge=False).descriptor("acquire_research_evidence", "3")
    assert pin["version"] == "3"
    assert pin["input_schema_sha256"] == descriptor.input_schema_sha256
    assert pin["output_schema_sha256"] == descriptor.output_schema_sha256
    prompt = profile["prompt"]
    assert (
        hashlib.sha256(
            (_ROOT / f"prompts/{prompt['name']}/{prompt['version']}/SYSTEM.md").read_bytes()
        ).hexdigest()
        == prompt["sha256"]
    )


def test_recipe_43_graph_allows_acquire_v3_only():
    recipe = _text("recipe-v43.json")
    assert json.loads(recipe)["version"] == 43
    assert "acquire_research_evidence@3" in recipe
    assert "acquire_research_evidence@2" not in recipe


def test_recipe_42_still_pins_acquire_v2():
    profile = yaml.safe_load(_text("profiles/quality-person-research/v30-person/profile.yaml"))
    pin = next(t for t in profile["tools"] if t["name"] == "acquire_research_evidence")
    assert pin["version"] == "2"
