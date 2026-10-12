"""Recipe 27: every instruction about finding people agrees with the prompt.

Run 4 (2026-10-10) got four different signals: the prompt said "opening rounds", the people-search
tool said "after account deep research" and refused before it, and the account skill said "once the
account picture is developed". Recipe 27 aligns them on early discovery; recipe 26 is unchanged.
Recipe 27 also has the person researcher check that the affiliation is still current and report a
departure, which keeps that person off the committee (run 4 nominated someone who had left).
"""

from types import SimpleNamespace

import yaml

from clue_api.arv2.committee_discovery import discover_people_description
from clue_api.arv2.quality_catalog import CURRENT_RECIPE_VERSION, load_quality_resources


def _bundle(version):
    return load_quality_resources("arv2-account", version=version)


def _body(version, suffix):
    return next(r.body for r in _bundle(version).skills if r.ref.endswith(suffix))


def _profiles(version):
    return {
        r.ref.split(":", 1)[1]: yaml.safe_load(r.body)
        for r in _bundle(version).skills
        if r.ref.endswith("profile.yaml") and "research/v" in r.ref
    }


def test_recipe_27_is_current_and_loads_hash_verified():
    assert CURRENT_RECIPE_VERSION == 27
    assert set(_profiles(27)) == {
        "profiles/quality-account-research/v27/profile.yaml",
        "profiles/quality-person-research/v27-person/profile.yaml",
    }


def test_the_account_profile_pins_the_v27_prompt_and_the_v10_skill():
    profile = _profiles(27)["profiles/quality-account-research/v27/profile.yaml"]
    assert profile["prompt"]["version"] == "v27"
    skills = {s["name"]: s["version"] for s in profile["skills"]}
    assert skills["account-dossier"] == "v10"


def test_the_v27_prompt_starts_the_committee_early_with_evidence_titles_and_retries():
    prompt = " ".join(_body(27, "quality-account-research/v27/SYSTEM.md").split())
    assert "Start the buying committee early, in your opening rounds" in prompt
    assert "several titles per role cluster" in prompt
    assert "matches each person's current title only" in prompt
    assert "check their current employer" in prompt
    assert "search and nominate again" in prompt
    assert "do not stop short of what the evidence supports" in prompt
    # Industry-agnostic examples: the harness is not GTM-specific.
    assert '"clinical operations"' in prompt and '"procurement"' in prompt


def test_the_v10_skill_no_longer_waits_for_the_account_picture():
    skill = " ".join(_body(27, "skills/account-dossier/v10/SKILL.md").split())
    assert "Once the account picture is developed, reason about" not in skill
    assert "Start reasoning about responsibilities and people in your opening rounds" in skill


def test_the_people_search_description_follows_the_recipe():
    new = discover_people_description(SimpleNamespace(input_refs={"quality_recipe_version": 27}))
    old = discover_people_description(SimpleNamespace(input_refs={"quality_recipe_version": 26}))
    assert "after account deep research" not in new
    assert "current title only" in new and '"procurement"' in new
    assert "after account deep research" in old


def test_recipe_26_still_loads_its_own_files():
    assert set(_profiles(26)) == {
        "profiles/quality-account-research/v26/profile.yaml",
        "profiles/quality-person-research/v26-person/profile.yaml",
    }


def test_the_person_prompt_checks_the_affiliation_is_current_and_reports_a_departure():
    prompt = " ".join(_body(27, "quality-person-research/v27-person/SYSTEM.md").split())
    assert "check that it is still true" in prompt
    assert "most recent dated sign of where the person works" in prompt
    assert "stop researching them in depth" in prompt
    assert "at the top of your summary with the dated source" in prompt
    assert "Do not add employment-proof" not in prompt
    old = " ".join(_body(26, "quality-person-research/v26-person/SYSTEM.md").split())
    assert "check that it is still true" not in old


def test_the_account_prompt_keeps_a_departed_person_off_the_committee():
    prompt = " ".join(_body(27, "quality-account-research/v27/SYSTEM.md").split())
    assert "Treat them as a former employee" in prompt
    assert "do not put them on the buying committee" in prompt
    assert "look for whoever holds that responsibility now" in prompt


def test_recipe_27_pins_the_new_person_skills():
    account = _profiles(27)["profiles/quality-account-research/v27/profile.yaml"]
    assert {s["name"]: s["version"] for s in account["skills"]}["person-research-briefing"] == "v5"
    person = _profiles(27)["profiles/quality-person-research/v27-person/profile.yaml"]
    assert {s["name"]: s["version"] for s in person["skills"]}["person-dossier"] == "v6"


def test_the_person_dossier_skill_reads_recent_activity_and_checks_deep_research_quotes():
    skill = " ".join(_body(27, "skills/person-dossier/v6/SKILL.md").split())
    assert "### Read what the person has done recently" in skill
    assert "look back nine months" in skill
    assert "write in /work/review.md that you looked and where" in skill
    assert "Once their recent activity is covered, do not let plentiful current-role posts" in skill
    assert "Treat the deep-research report as a set of leads." in skill
    assert "open the source page yourself and check that the words are there" in skill
    # The recency pass sits after broad discovery; the leads paragraph opens "After Exa".
    recency = skill.index("### Read what the person has done recently")
    assert skill.index("## Discover broadly") < recency
    after_exa = skill.index("## After Exa")
    assert skill.index("Treat the deep-research report as a set of leads.") > after_exa
    assert skill.index("Treat the deep-research report as a set of leads.") < skill.index(
        "### Assess coverage"
    )


def test_the_briefing_skill_hands_over_what_the_account_agent_already_read():
    skill = " ".join(_body(27, "skills/person-research-briefing/v5/SKILL.md").split())
    assert "Include everything you have already read that this person wrote, said or was" in skill
    assert "with its URL, date and the exact passage" in skill
    assert "anything you read but leave out of the brief can be lost" in skill


def test_recipe_26_keeps_its_person_skills():
    account = _profiles(26)["profiles/quality-account-research/v26/profile.yaml"]
    assert {s["name"]: s["version"] for s in account["skills"]}["person-research-briefing"] == "v4"
