"""Recipe 40: the account agent writes its one brief after its people's research."""

import hashlib
import json
from pathlib import Path

import pytest

from clue_agents import AgentRole
from clue_api.arv2.quality_results import ResearchUnitReport
from clue_api.quality_research_wiring import CATALOG_ROOT, quality_profiles, quality_tools

_ROOT = Path(CATALOG_ROOT)


def _text(path: str) -> str:
    return (_ROOT / path).read_text()


def test_recipe_40_pins_match_files():
    launch = json.loads(_text("launch-v4-r40.json"))
    assert launch["recipe_version"] == 40
    for path, sha in launch["resources"].items():
        assert hashlib.sha256((_ROOT / path).read_bytes()).hexdigest() == sha, path


@pytest.mark.parametrize(
    ("version", "person", "expected"),
    [(40, False, "v39"), (40, True, "v29-person"), (39, False, "v38"), (39, True, "v28-person")],
)
def test_recipe_selects_its_own_profiles(version, person, expected):
    tools = quality_tools(None, None, purge=False)
    registry = quality_profiles(tools, version=version, person=person)
    assert registry.resolve(AgentRole.ACCOUNT_RESEARCH).profile.version == expected


def test_first_turn_asks_for_a_provisional_verdict_not_a_brief():
    prompt = _text("prompts/quality-account-research/v39/SYSTEM.md")
    assert "You will write the page brief later" in prompt
    assert "Write /outputs/page-brief.md." not in prompt
    assert "If a slot is free, do not leave it empty" in prompt


def test_review_skill_carries_the_approved_instruction_and_brief_format():
    skill = _text("skills/account-review/v1/SKILL.md")
    assert "Your people's research is finished, or as finished as it will get." in skill
    assert "If your research was blocked, say so plainly" in skill
    assert "Do not say:" in skill
    assert "also worth knowing" in skill
    assert "Be realistic." in skill


def test_credentials_rule_reaches_the_person_agent():
    rule = "credentials and certifications go in the one job-history finding"
    assert rule in _text("prompts/quality-person-research/v29-person/SYSTEM.md").lower()
    assert rule in _text("skills/claim-ready-person-dossier/v5/SKILL.md").lower()


def _report(**extra):
    return {
        "context_id": "00000000-0000-0000-0000-000000000001",
        "job_id": "00000000-0000-0000-0000-000000000002",
        "summary": "Research was blocked.",
        **extra,
    }


def test_report_accepts_blocked_status():
    report = ResearchUnitReport.model_validate(
        _report(status="blocked", next_actions=["Restore acquisition"])
    )
    assert report.status == "blocked"
    assert report.next_actions == ("Restore acquisition",)


def test_saved_report_without_them_still_loads():
    report = ResearchUnitReport.model_validate(_report())
    assert report.status is None
    assert report.next_actions == ()


def test_report_still_refuses_unknown_fields():
    with pytest.raises(ValueError, match="extra"):
        ResearchUnitReport.model_validate(_report(mood="fine"))
