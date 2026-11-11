"""Recipe 45: the person prompt asks for read_media's identity note (approved 2026-11-12).

Person jobs read prompt v32-person, which is v31-person plus one sentence; the identity_note
argument itself lives in read_media's arguments (not pinned). Account jobs keep v42. Recipe 45 is
recipe 44 with only its version changed.
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
SENTENCE = (
    "When you call read_media, fill identity_note with what identifies the person: their roles "
    "and employers with years, past ones too, and anything else a host might introduce them by "
    "(where they studied, businesses, boards, awards, other spellings of their name). The speaker "
    "check uses it to tell them apart from namesakes. Without it, a recording from an earlier job "
    "can look like someone else."
)


def _text(path: str) -> str:
    return (_ROOT / path).read_text()


def test_v32_person_is_v31_person_plus_the_identity_note_sentence():
    v31 = _text("prompts/quality-person-research/v31-person/SYSTEM.md")
    v32 = _text("prompts/quality-person-research/v32-person/SYSTEM.md")
    anchor = "read the transcript before you decide."
    expected = v31.replace(anchor, f"{anchor} {SENTENCE}", 1).replace(
        "\nversion: v31-person\n", "\nversion: v32-person\n", 1
    )
    assert v32 == expected
    assert v32.count(SENTENCE) == 1


def test_v32_person_profile_is_v31_with_its_own_prompt():
    v31 = yaml.safe_load(_text("profiles/quality-person-research/v31-person/profile.yaml"))
    v32 = yaml.safe_load(_text("profiles/quality-person-research/v32-person/profile.yaml"))
    prompt = v32["prompt"]
    assert v32["version"] == prompt["version"] == "v32-person"
    sha = hashlib.sha256(
        (_ROOT / "prompts/quality-person-research/v32-person/SYSTEM.md").read_bytes()
    ).hexdigest()
    assert prompt["sha256"] == sha
    for key in ("version", "prompt"):
        v31.pop(key), v32.pop(key)
    assert v31 == v32


@pytest.mark.parametrize(
    ("version", "person", "expected"),
    [(45, True, "v32-person"), (45, False, "v42"), (44, True, "v31-person"), (44, False, "v42")],
)
def test_recipe_45_selects_v32_person_for_people_only(version, person, expected):
    registry = quality_profiles(
        quality_tools(None, None, purge=False), version=version, person=person
    )
    assert registry.resolve(AgentRole.ACCOUNT_RESEARCH).profile.version == expected


def test_recipe_45_is_recipe_44_with_its_version_and_is_current():
    r44 = json.loads(_text("recipe-v44.json"))
    r45 = json.loads(_text("recipe-v45.json"))
    assert CURRENT_RECIPE_VERSION == 45
    r44["version"] = 45
    assert r44 == r45


def test_launch_r45_pins_match_files():
    launch = json.loads(_text("launch-v4-r45.json"))
    assert launch["recipe_version"] == 45
    for path, sha in launch["resources"].items():
        assert hashlib.sha256((_ROOT / path).read_bytes()).hexdigest() == sha, path
    r44 = set(json.loads(_text("launch-v4-r44.json"))["resources"])
    swapped = {
        "recipe-v44.json": "recipe-v45.json",
        "prompts/quality-person-research/v31-person/SYSTEM.md": (
            "prompts/quality-person-research/v32-person/SYSTEM.md"
        ),
        "profiles/quality-person-research/v31-person/profile.yaml": (
            "profiles/quality-person-research/v32-person/profile.yaml"
        ),
    }
    assert set(launch["resources"]) == {swapped.get(p, p) for p in r44}
    load_quality_resources("account", version=45)


def test_recipe_45_passes_the_graph_validation_its_install_runs():
    from clue_execution import RecipeDefinition, validate_graph

    definition = RecipeDefinition.model_validate_json((_ROOT / "recipe-v45.json").read_bytes())
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
