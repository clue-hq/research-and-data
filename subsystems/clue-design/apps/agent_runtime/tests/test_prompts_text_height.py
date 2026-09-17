"""Editor Quality Plan 4, item F: text height is hug — the authoring default reaches the author and the LinkedIn ad skill."""

from __future__ import annotations

from pathlib import Path

from lumen_agent import prompts

SKILL = (
    Path(prompts.__file__).resolve().parents[1]
    / "knowledge_docs" / "skills" / "linkedin-square-ad" / "SKILL.md"
)

AUTHOR_RULE = (
    "TEXT HEIGHT IS HUG. Size every text node `s(W,hug)` or `s(fill,hug)`; a text element "
    "with no `s(...)` hugs on both axes. Never give a text node a fixed height: the box stops "
    "following the copy, the editor outlines empty space, and glyphs that overflow the box "
    "cannot be clicked. Fixed and fill WIDTHS are fine."
)
SKILL_RULE = (
    "**Text height is always hug.** Write `s(W,hug)` or `s(fill,hug)`; never a fixed height on "
    "a text node — the box stops following the copy and the editor outlines empty space. "
    "Widths may be fixed or fill."
)


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_author_teaching_body_says_text_height_is_hug() -> None:
    assert _flat(AUTHOR_RULE) in _flat(prompts._AUTHOR_TEACHING_BODY)


def test_linkedin_ad_skill_says_text_height_is_hug() -> None:
    assert _flat(SKILL_RULE) in _flat(SKILL.read_text(encoding="utf-8"))
