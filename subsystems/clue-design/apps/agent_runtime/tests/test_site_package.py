"""The site agent's package: prompt and skills carried from the Puck spike (Lane B Task 4)."""

from __future__ import annotations

from pathlib import Path

from lumen_agent.site import inputs
from lumen_agent.site.inputs import AccountLogo, SiteSection, SiteTurnInputs

SITE = Path(inputs.__file__).resolve().parent
SPIKE = Path(__file__).resolve().parents[5] / "trials" / "puck-spike" / "agent"
UNCHANGED: list[str] = [
    # skills-e5/rebuilding-a-section left the spike's text on 2026-10-16 (S2a-2, founder-approved
    # wording: mark the words a marketer edits on the page; SKILLS-CHANGELOG.md). account-page-copy,
    # the last skill still word for word the spike's, was retired by the site alignment (2026-10-28).
]


def test_the_untouched_skills_are_the_spikes_word_for_word() -> None:
    for relative in UNCHANGED:
        assert (SITE / relative).read_bytes() == (SPIKE / relative).read_bytes(), relative


def test_the_package_ships_its_prompt_and_skills() -> None:
    # The site alignment's skill set (SKILL-SET-MAP.md, ruling S5: the page kinds are one skill with
    # reference files).
    assert (SITE / "system_prompt.md").is_file()
    assert sorted(p.parent.name for p in (SITE / "skills").glob("*/SKILL.md")) == [
        "building-with-puck", "evidence", "imagery-and-media", "page-copy", "page-design", "page-kinds",
        "page-review", "planning-a-page",
    ]
    assert sorted(p.name for p in (SITE / "skills/page-kinds/references").glob("*.md")) == [
        "contact.md", "decision-material.md", "event.md", "general-campaign.md", "one-to-few.md",
        "one-to-one.md", "product-campaign.md",
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
    # Ruling S2 (2026-10-27): the prompt points at the listed skills instead of naming them.
    assert "1. Your skills are listed at the end of this prompt" in prompt
    assert "the site's one header and one footer, each a section like those on a page" in prompt
    assert '"Prepared for …", optional links' not in prompt
    assert "- `fetch_logo`: finds a company's real published logos by its website domain" in prompt
    building = (SITE / "skills/building-with-puck/SKILL.md").read_text()
    assert "**The footer.** Which footer depends on the kind of page" in building
    assert "**The header: the seller's own, by page kind.**" in building  # rulings R7.6-R7.8
    assert "**When the brand has no header template**, use the plain header." in building
    assert "brings back the last good version." not in building
    assert "bring back an earlier saved version with `restore_version`" in building
    images = (SITE / "skills/imagery-and-media/SKILL.md").read_text()
    assert "found with\n   `search_assets`" in images
    assert "call `fetch_logo` with the account's website domain" in images
    assert "It must not show" not in images  # ruling M2.3
    section = (SITE / "skills-e5/writing-a-section/SKILL.md").read_text()
    assert "surface: z.string()," in section
    assert 'z.enum(["page", "card", "muted", "brandSubtle", "brand", "inverse"])' not in section
    assert "kit.Link" in section and "brand-motion-pulse" in section


def test_every_skill_and_reference_the_set_points_to_exists() -> None:
    # SKILL-SET-MAP.md §10: every named skill and reference must exist. Code tokens written in
    # kebab case (class names, attributes) are not skill names.
    import re

    code_words = {"aria-label", "data-clue-el", "data-new-tab", "mt-stack-tight", "prefers-reduced-motion",
                  "py-section", "font-headline", "font-title", "font-body"}
    skills = {p.parent.name for p in SITE.glob("skills*/*/SKILL.md")}
    texts = [SITE / "system_prompt.md", *SITE.glob("skills*/*/SKILL.md"), *SITE.glob("skills/*/references/*.md")]
    for path in texts:
        text = path.read_text()
        for name in set(re.findall(r"`([a-z]+(?:-[a-z]+)+)`", text)) - code_words:
            assert name in skills, f"{path.name} points to `{name}`, which is not a skill"
        if "`evidence`" in text:
            assert "evidence" in skills
    references = SITE / "skills/page-kinds/references"
    for name in re.findall(r"`([a-z-]+\.md)`", (SITE / "skills/page-kinds/SKILL.md").read_text()):
        assert (references / name).is_file(), name
