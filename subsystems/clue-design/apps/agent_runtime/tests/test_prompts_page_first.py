"""Editor Quality Plan 2, item C: the page-first rule reaches every role that can spend."""

from __future__ import annotations

import inspect
from pathlib import Path

from lumen_agent import prompts

SKILL = (
    Path(prompts.__file__).resolve().parents[1]
    / "knowledge_docs" / "skills" / "linkedin-square-ad" / "SKILL.md"
)

DIRECTOR_RULE = (
    "PAGE BEFORE ASSETS: on a document with no page yet (artboard_id is null and the scene "
    "digest shows zero pages), delegate the author's whole-design compile FIRST and only "
    "then fetch logos or generate imagery — generate_image, generate_qr and fetch_logo refuse "
    "on a pageless scene (`scene.page_required`) without spending, so calling them first only "
    "wastes a tool call."
)
AUTHOR_RULE = (
    "PAGE FIRST. On a document with no page, the `page …` line is the FIRST line of your "
    "first compile, and that compile is the whole design. Nothing can be registered in a "
    "pageless scene: generate_image, generate_qr and fetch_logo refuse before spending "
    "(`scene.page_required`) until a page exists — never call an asset tool on a pageless "
    "scene."
)
WORK_LOOP_RULE = (
    "On a pageless document the page line leads that block; imagery, logos and QR codes "
    "come AFTER the page exists — the asset tools refuse on a pageless scene without "
    "spending."
)
SKILL_RULE = (
    "Author it in your FIRST compile, before any imagery or logo — a pageless scene "
    "registers nothing."
)


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_the_director_template_orders_the_page_before_assets():
    assert _flat(DIRECTOR_RULE) in _flat(prompts._ORCHESTRATOR_TEMPLATE)


def test_the_author_teaching_body_puts_the_page_line_first():
    # The plan named `_AUTHOR_HEADER`, but the anchor bullet it points at ("- YOU author
    # every page…") lives in `_AUTHOR_TEACHING_BODY`; `_AUTHOR_HEADER` is the intro plus the
    # numbered work loop and carries no bullet list. Both constants are assembled into the
    # live author prompt, so the rule reaches the author either way. Repointed on the
    # controller's ruling.
    assert _flat(AUTHOR_RULE) in _flat(prompts._AUTHOR_TEACHING_BODY)


def test_the_fast_loop_work_loop_orders_assets_after_the_page():
    assert _flat(WORK_LOOP_RULE) in _flat(prompts._AUTHOR_FAST_LOOP_WORK_LOOP)


def test_every_rule_names_the_guard_code_the_tools_actually_return():
    from lumen_agent.tools.substrate import PAGE_REQUIRED_CODE

    source = inspect.getsource(prompts)
    assert source.count(PAGE_REQUIRED_CODE) >= 2  # director + author header


def test_the_linkedin_ad_skill_orders_the_page_first():
    assert _flat(SKILL_RULE) in _flat(SKILL.read_text())
