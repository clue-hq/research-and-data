"""The site agent's package: prompt and skills carried from the Puck spike (Lane B Task 4)."""

from __future__ import annotations

from pathlib import Path

from lumen_agent.site import inputs
from lumen_agent.site.inputs import AccountLogo, SiteSection, SiteTurnInputs

SITE = Path(inputs.__file__).resolve().parent
SPIKE = Path(__file__).resolve().parents[5] / "trials" / "puck-spike" / "agent"
UNCHANGED = [
    "skills/account-page-copy/SKILL.md",
    # skills-e5/rebuilding-a-section left the spike's text on 2026-10-16 (S2a-2, founder-approved
    # wording: mark the words a marketer edits on the page; SKILLS-CHANGELOG.md).
]


def test_the_untouched_skills_are_the_spikes_word_for_word() -> None:
    for relative in UNCHANGED:
        assert (SITE / relative).read_bytes() == (SPIKE / relative).read_bytes(), relative


def test_the_package_ships_its_prompt_and_six_skills() -> None:
    assert (SITE / "system_prompt.md").is_file()
    assert sorted(p.parent.name for p in (SITE / "skills").glob("*/SKILL.md")) == [
        "account-page-copy", "building-with-puck", "images-and-logos", "page-review",
    ]
    assert sorted(p.parent.name for p in (SITE / "skills-e5").glob("*/SKILL.md")) == [
        "rebuilding-a-section", "writing-a-section",
    ]


def test_the_inputs_default_to_an_empty_turn() -> None:
    section = SiteSection(name="StepsBand", digest="a" * 64, props_schema={}, module_js="", css="")
    logo = AccountLogo(cell="light_lockup", file="/asset-store/" + "b" * 64, content_type="image/svg+xml")
    turn = SiteTurnInputs(
        document_id="doc_1", workspace_id="ws_1", brief="b", account_name="Acme",
        seller="Garner Health", brand={"assets": {}, "clones": {}}, catalog={},
        agent_sections={"StepsBand": section}, account_logos=[logo],
    )
    assert turn.overview == [] and turn.claims == [] and turn.held_claim_ids == frozenset()
    assert turn.assets is None and turn.renderer is None and logo.alternative is False


def test_the_approved_prompt_and_skill_changes_are_in_place() -> None:
    prompt = (SITE / "system_prompt.md").read_text()
    assert "- `project-context/`: the project's own instructions and decisions" in prompt
    assert "It saves a version when the page is valid." not in prompt
    assert "brings back an earlier saved version of the site (`site.md` lists them)." in prompt
    assert "- `search_assets`: finds the seller's other images" in prompt
    assert "and for new sections `writing-a-section` and" in prompt
    assert "the site's one header and one footer, each a section like those on a page" in prompt
    assert '"Prepared for …", optional links' not in prompt
    assert "- `fetch_logo`: finds a company's real published logos by its website domain" in prompt
    building = (SITE / "skills/building-with-puck/SKILL.md").read_text()
    assert "**The footer: use the plain footer.** Every site starts with the plain footer" in building
    assert "**When the brand has no header template**, use the plain header:" in building
    assert "brings back the last good version." not in building
    assert "bring back an earlier saved version with `restore_version`" in building
    images = (SITE / "skills/images-and-logos/SKILL.md").read_text()
    assert "Find them with `search_assets`" in images
    assert "beside the seller's logo: the template's `account_logo`" in images
    assert 'header\'s "Prepared for" place' not in images
    assert "call `fetch_logo` with\n  the account's website domain" in images
    section = (SITE / "skills-e5/writing-a-section/SKILL.md").read_text()
    assert "surface: z.string()," in section
    assert 'z.enum(["page", "card", "muted", "brandSubtle", "brand", "inverse"])' not in section
    assert "kit.Link" in section and "brand-motion-pulse" in section
