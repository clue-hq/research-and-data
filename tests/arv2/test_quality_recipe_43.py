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
    assert launch["recipe_version"] == 43
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
    [
        (44, False, "v42"),
        (44, True, "v31-person"),
        (43, False, "v42"),
        (43, True, "v31-person"),
        (42, False, "v41"),
        (42, True, "v30-person"),
    ],
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


def _requirement_lists(recipe):
    """Every place a recipe pins tool versions: graph nodes and the compatibility block."""
    lists = [n.get("requirements", []) for n in recipe["graph"]["nodes"]]
    lists.append(recipe["compatibility"]["execution"])
    lists.extend(recipe["compatibility"].get("nodes", {}).values())
    return lists


def test_recipe_44_graph_allows_acquire_v3_only():
    recipe = json.loads(_text("recipe-v44.json"))
    assert recipe["version"] == 44
    text = json.dumps(recipe)
    assert "acquire_research_evidence@3" in text and "acquire_research_evidence@2" not in text
    pins = [
        r
        for requirements in _requirement_lists(recipe)
        for r in requirements
        if r.get("key") == "acquire_research_evidence"
    ]
    assert len(pins) == 2 and all(r["version"] == "3" for r in pins)


def test_recipe_44_is_43_corrected_and_current():
    """Recipe 44 is recipe 43 with only the research tool's requirement pins set to version 3."""
    r43 = json.loads(_text("recipe-v43.json"))
    r44 = json.loads(_text("recipe-v44.json"))
    assert CURRENT_RECIPE_VERSION >= 44  # recipe 45 is current since 2026-11-12
    r43["version"] = 44
    for requirements in _requirement_lists(r43):
        for r in requirements:
            if r.get("key") == "acquire_research_evidence":
                r["version"] = "3"
    assert r43 == r44
    launch = json.loads(_text("launch-v4-r44.json"))
    assert launch["recipe_version"] == 44
    for path, sha in launch["resources"].items():
        assert hashlib.sha256((_ROOT / path).read_bytes()).hexdigest() == sha, path
    r43_launch = json.loads(_text("launch-v4-r43.json"))["resources"]
    assert set(launch["resources"]) == (set(r43_launch) - {"recipe-v43.json"}) | {"recipe-v44.json"}
    load_quality_resources("account", version=44)


def test_recipe_42_still_pins_acquire_v2():
    profile = yaml.safe_load(_text("profiles/quality-person-research/v30-person/profile.yaml"))
    pin = next(t for t in profile["tools"] if t["name"] == "acquire_research_evidence")
    assert pin["version"] == "2"


def test_account_research_is_told_to_use_the_footprint_jobs():
    """Founder-approved 2026-11-11: the account agent looks for the company's and its leaders'
    recordings with find_podcasts/find_videos, finds the company's X account first, and the old
    discovery wording is gone."""
    prompt = _text("prompts/quality-account-research/v42/SYSTEM.md")
    assert "Look for recordings with find_podcasts and find_videos" in prompt
    assert "Find the company's X account through web search or its own website" in prompt
    assert "Discover media" not in prompt
    skill = _text("skills/account-dossier/v19/SKILL.md")
    assert "Use find_podcasts and find_videos to find recordings" in skill
    assert "Follow candidate references" not in skill
    profile = yaml.safe_load(_text("profiles/quality-account-research/v42/profile.yaml"))
    pinned = {s["name"]: s for s in profile["skills"]}["account-dossier"]
    assert pinned["version"] == "v19"
    sha = hashlib.sha256((_ROOT / "skills/account-dossier/v19/SKILL.md").read_bytes()).hexdigest()
    assert pinned["sha256"] == sha
    launch = json.loads(_text("launch-v4-r43.json"))
    assert "skills/account-dossier/v19/SKILL.md" in launch["resources"]
    assert "skills/account-dossier/v18/SKILL.md" not in launch["resources"]


@pytest.mark.parametrize("version", [42, 44])
def test_recipe_passes_the_graph_validation_its_install_runs(version):
    """Installing a recipe validates its graph against the registered tools. Recipe 43 failed here
    (`missing_tool_pin`: acquire@3 allowed, its requirements still naming version 2) and was
    recorded as a failed proposal, which cannot be changed; recipe 44 is the corrected copy."""
    from clue_execution import RecipeDefinition, validate_graph

    definition = RecipeDefinition.model_validate_json(
        (_ROOT / f"recipe-v{version}.json").read_bytes()
    )
    result = validate_graph(
        definition.graph,
        parameter_schema=definition.parameter_schema,
        tool_catalog=quality_tools(None, None, purge=False),
        max_nodes=definition.max_nodes,
        max_depth=definition.max_depth,
        max_fanout=definition.max_fanout,
        execution_requirements=definition.compatibility.execution,
    )
    assert result.valid, [f"{i.location}:{i.code}" for i in result.issues]
