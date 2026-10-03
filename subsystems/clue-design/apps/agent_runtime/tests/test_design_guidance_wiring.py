"""`design-guidance` is wired must-read into the WEB turn (tier-1 wiring, slice 1).

The craft skill itself (`knowledge_docs/skills/design-guidance/SKILL.md`) is the
content; this suite guards the WIRING around it:

- it registers the way its 13 siblings do (implicitly, by directory — the
  materializer copies every skill dir, there is no manifest to forget);
- the orchestrator and the author prompts name it must-read, in the same
  referencing idiom the existing skill/recipe pointers use;
- the reviewer's brief-consumption hooks are reached through the required
  reference in the materialized `review-website` skill;
- the knowledge tree's root doc (`AGENT.md`, materialized as the agent's
  `/.deepagent/AGENTS.md`) references it for website work;
- the SCENE prompts are untouched — D4 scopes brief consumption to web
  documents in v1, and the ad/scene path keeps today's brand card.
"""

from __future__ import annotations

import types
from pathlib import Path

from lumen_agent.knowledge import parse_frontmatter
from lumen_agent.materialize import materialize_agent_workspace
from lumen_agent.prompts import (
    build_author_prompt,
    build_orchestrator_prompt,
    build_reviewer_prompt,
)
from lumen_agent.prompts_web import (
    build_web_author_prompt,
    build_web_orchestrator_prompt,
    build_web_reviewer_prompt,
)
from test_web_skill_family import read_required_skill_reference

RUNTIME_ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_DOCS = RUNTIME_ROOT / "knowledge_docs"
SKILLS_DIR = KNOWLEDGE_DOCS / "skills"
SKILL_NAME = "design-guidance"


# ============================================================================
# 1. The knowledge tree picks it up (registration is implicit, by directory)
# ============================================================================


def test_the_design_guidance_skill_is_a_directory_in_the_authored_tree() -> None:
    assert (SKILLS_DIR / SKILL_NAME / "SKILL.md").is_file()


def test_every_skill_declares_frontmatter_naming_its_own_directory() -> None:
    """Skill discovery is name+description frontmatter, so a new skill loads only
    if it parses like its siblings. Asserted over ALL of them: the new one is
    held to exactly the bar the existing tree already meets."""

    skill_dirs = sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir())
    assert SKILLS_DIR / SKILL_NAME in skill_dirs

    for skill_dir in skill_dirs:
        skill_file = skill_dir / "SKILL.md"
        assert skill_file.is_file(), f"{skill_dir.name} has no SKILL.md"
        meta, body = parse_frontmatter(skill_file.read_text(encoding="utf-8"))
        assert meta.get("name") == skill_dir.name, (
            f"{skill_dir.name}: frontmatter `name` must match the directory"
        )
        assert meta.get("description"), f"{skill_dir.name}: no `description`"
        assert body.strip(), f"{skill_dir.name}: empty body"


def test_the_materializer_serves_design_guidance_to_the_agent(tmp_path) -> None:
    """The load smoke: a real materialize of the REAL tree puts the skill on both
    surfaces the agent reads — `/.deepagent/skills/` (the SkillsMiddleware source)
    and the `/knowledge_docs/` copy (intra-doc references)."""

    ws = tmp_path / "ws"
    config = types.SimpleNamespace(workspace_root=ws)

    materialize_agent_workspace(config)

    served = ws / ".deepagent" / "skills" / SKILL_NAME / "SKILL.md"
    assert served.is_file()
    assert served.read_text(encoding="utf-8") == (
        SKILLS_DIR / SKILL_NAME / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert (ws / "knowledge_docs" / "skills" / SKILL_NAME / "SKILL.md").is_file()


# ============================================================================
# 2. The web prompts name it must-read
# ============================================================================


def _web_orchestrator_prompt() -> str:
    return build_web_orchestrator_prompt(
        doc_title="Harbor & Sage",
        has_existing_content=False,
        brand_card="warm, coastal",
        review_cap=6,
        author_cap=4,
    )


def test_the_web_orchestrator_prompt_names_design_guidance_must_read(tmp_path) -> None:
    prompt = _web_orchestrator_prompt()

    assert SKILL_NAME in prompt
    # The pointer is a pointer, not a paraphrase of the skill: the orchestrator
    # is told to READ it, and the existing recipe pointer survives beside it.
    assert "read" in prompt.lower().split(SKILL_NAME)[0][-200:]
    recipe = "knowledge_docs/knowledge/web/landing-page.md"
    assert f"For landing-page composition, read {recipe}" in prompt
    materialize_agent_workspace(types.SimpleNamespace(workspace_root=tmp_path))
    assert (tmp_path / recipe).read_bytes() == (RUNTIME_ROOT / recipe).read_bytes()


def test_the_web_author_prompt_names_design_guidance_beside_create_website() -> None:
    prompt = build_web_author_prompt(
        brand_card="warm, coastal",
        theme_token_names="bg-light, text-dark, bg-primary",
    )

    assert SKILL_NAME in prompt
    assert "create-website" in prompt
    # Both are named in the same "read your skill" pointer, so neither is optional.
    head, _, tail = prompt.partition("create-website")
    assert SKILL_NAME in head[-300:] or SKILL_NAME in tail[:300]


def test_the_web_reviewer_prompt_still_delegates_to_its_skill_file() -> None:
    """The reviewer's brief hooks are a SKILL.md edit, not a prompt edit — its
    prompt keeps pointing at review-website and keeps its anchor-check wording."""

    prompt = build_web_reviewer_prompt()

    assert "Read your skill:\nreview-website" in prompt
    assert "brand expression generic" in prompt


# ============================================================================
# 3. The reviewer's brief-consumption hooks (review-website/SKILL.md)
# ============================================================================


def test_review_website_consumes_the_briefs_constraints_and_rhythm(tmp_path) -> None:
    assert "Read your skill:\nreview-website" in build_web_reviewer_prompt()
    text = read_required_skill_reference(
        tmp_path, "review-website", "fidelity and behavior checks",
    )
    lowered = text.lower()

    assert "creative brief" in lowered
    # (a) constraints[] are review criteria — a violation is a reportable defect.
    assert "constraints" in lowered
    assert "defect" in lowered
    # (b) the background rhythm is checked against the brief's when present.
    assert "background rhythm" in lowered
    # Generic expression is advisory; violating a required source/brief property
    # is a defect. Neither an anchor label nor a score can erase that distinction.
    flat = " ".join(lowered.split())
    assert '"brand expression generic"' in flat
    assert "advisory unless" in flat
    assert "a violation is a reportable defect" in flat
    assert "trace the contrast chain" in flat


# ============================================================================
# 4. The knowledge tree's root doc
# ============================================================================


def test_the_root_agent_doc_references_design_guidance_for_website_work() -> None:
    text = (KNOWLEDGE_DOCS / "AGENT.md").read_text(encoding="utf-8")

    assert f"skills/{SKILL_NAME}" in text
    lowered = text.lower()
    assert "website" in lowered
    # It is named as a must-read, not an optional extra.
    assert "must-read" in lowered


# ============================================================================
# 5. Scene prompts are untouched (D4: web documents only in v1)
# ============================================================================


def test_the_scene_prompts_do_not_mention_design_guidance() -> None:
    for build in (build_orchestrator_prompt, build_author_prompt, build_reviewer_prompt):
        assert SKILL_NAME not in build("/run_1")
