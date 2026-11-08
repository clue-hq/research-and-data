"""Recipe 42: findings advise the seller, likes can be signals, the person agent researches a team.

Founder rulings 2026-11-08: a finding's interpretation says what the seller should do with it rather
than what it fails to prove; a like of the seller's, a competitor's or the problem's content is
recorded; the person agent researches the part of the company the person runs; a post is cited by
its own URL.
"""

import hashlib
import json
from pathlib import Path

import pytest

from clue_agents import AgentRole
from clue_api.quality_research_wiring import CATALOG_ROOT, quality_profiles, quality_tools

_ROOT = Path(CATALOG_ROOT)


def _text(path: str) -> str:
    return (_ROOT / path).read_text()


def test_recipe_42_pins_match_files():
    launch = json.loads(_text("launch-v4-r42.json"))
    assert launch["recipe_version"] == 42
    for path, sha in launch["resources"].items():
        assert hashlib.sha256((_ROOT / path).read_bytes()).hexdigest() == sha, path
    for path in (
        "prompts/quality-person-research/v30-person/SYSTEM.md",
        "skills/claim-ready-person-dossier/v6/SKILL.md",
        "skills/person-depth-charter/v3/SKILL.md",
    ):
        assert path in launch["resources"]


@pytest.mark.parametrize(
    ("version", "person", "expected"),
    [(42, False, "v41"), (42, True, "v30-person"), (41, False, "v40"), (41, True, "v29-person")],
)
def test_recipe_selects_its_own_profiles(version, person, expected):
    tools = quality_tools(None, None, purge=False)
    registry = quality_profiles(tools, version=version, person=person)
    assert registry.resolve(AgentRole.ACCOUNT_RESEARCH).profile.version == expected


@pytest.mark.parametrize(
    "path",
    [
        "skills/claim-ready-person-dossier/v6/SKILL.md",
        "skills/claim-ready-account-dossier/v4/SKILL.md",
    ],
)
def test_interpretation_advises_the_seller(path):
    skill = _text(path)
    assert "what this finding means for the seller" in skill
    assert "This does not establish a purchasing decision or budget." not in skill


def test_person_agent_records_signal_likes_and_its_team():
    prompt = _text("prompts/quality-person-research/v30-person/SYSTEM.md")
    assert "Likes do not count." not in prompt
    assert "without presenting it as evidence of buying intent" not in prompt
    assert "Research the part of the company they run." in prompt
    assert "search its words to find its own URL before you save the finding" in prompt
    charter = _text("skills/person-depth-charter/v3/SKILL.md")
    assert "Cite the liked post's URL" in charter
