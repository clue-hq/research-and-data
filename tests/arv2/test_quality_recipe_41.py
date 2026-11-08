"""Recipe 41: the account agent fills the buying committee by seat and judges each candidate itself.

Founder ruling 2026-11-08: economic buyer, champion and technical evaluator first; the remaining
places go to sponsor, end user or blocker; AI Ark and Exa find candidates but never choose them.
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


def test_recipe_41_pins_match_files():
    launch = json.loads(_text("launch-v4-r41.json"))
    assert launch["recipe_version"] == 41
    for path, sha in launch["resources"].items():
        assert hashlib.sha256((_ROOT / path).read_bytes()).hexdigest() == sha, path
    assert "prompts/quality-account-research/v40/SYSTEM.md" in launch["resources"]
    assert "skills/account-review/v2/SKILL.md" in launch["resources"]


@pytest.mark.parametrize(
    ("version", "person", "expected"),
    [(41, False, "v40"), (41, True, "v29-person"), (40, False, "v39"), (40, True, "v29-person")],
)
def test_recipe_selects_its_own_profiles(version, person, expected):
    tools = quality_tools(None, None, purge=False)
    registry = quality_profiles(tools, version=version, person=person)
    assert registry.resolve(AgentRole.ACCOUNT_RESEARCH).profile.version == expected


def test_prompt_fills_core_seats_and_judges_candidates_itself():
    prompt = _text("prompts/quality-account-research/v40/SYSTEM.md")
    assert "Fill the economic buyer, champion and technical evaluator seats first." in prompt
    assert "they never decide who belongs on the committee. You do." in prompt
    assert "followed it up with further questions" in prompt
    labels = "economic_buyer, executive_sponsor, champion, technical_evaluator, user or blocker"
    assert labels in prompt
    assert "If a slot is free, do not leave it empty" not in prompt


def test_skills_carry_the_seat_rules():
    dossier = _text("skills/account-dossier/v18/SKILL.md")
    assert "or force a role per seat" not in dossier
    assert "These searches find candidates; they do not choose them." in dossier
    review = _text("skills/account-review/v2/SKILL.md")
    assert "each person with their seat" in review
    briefing = _text("skills/person-research-briefing/v7/SKILL.md")
    assert "Name the seat you chose them for" in briefing
