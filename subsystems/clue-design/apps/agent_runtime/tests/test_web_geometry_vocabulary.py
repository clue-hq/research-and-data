"""G3 — the brand-geometry vocabulary the authoring stack SPEAKS must BE the
vocabulary the engine resolves.

G1 made ten utilities law in the web grammar: `GEOMETRY_UTILITIES` in
`crates/lumen-web/src/theme.rs` is the single closed source of truth — one row
per utility, carrying the kit token chain it resolves. G3 taught that vocabulary
to the prompt, the create-website skill, and the recipe renderer, so the same ten
names now live in four places. They are only useful if they cannot drift apart:
the Rust table is the source of truth and the three prose copies are checked
against it, exactly as `test_web_icon_vocabulary.py` guards the icon registry.

Only the CHAIN HEAD is asserted for the mapping (`radius.button`, not
`radius.control`/`radius.md`): the fallback rungs are the engine's business and
have no utility of their own to name.
"""

from __future__ import annotations

import re
from pathlib import Path

from lumen_agent.brand_brief import GEOMETRY_TOKEN_UTILITIES
from lumen_agent.prompts_web import WEB_GEOMETRY_UTILITIES, build_web_author_prompt

REPO_ROOT = Path(__file__).resolve().parents[3]
THEME_RS = REPO_ROOT / "crates" / "lumen-web" / "src" / "theme.rs"
SKILL_MD = (
    REPO_ROOT
    / "apps"
    / "agent_runtime"
    / "knowledge_docs"
    / "skills"
    / "create-website"
    / "SKILL.md"
)

#: The heading the create-website skill's geometry block opens with. Split-on,
#: not searched for: the assertion is about THAT block, not the whole file.
SKILL_BLOCK_MARKER = "**Brand geometry — ten utilities that resolve the kit's own shape.**"


def _engine_rows() -> list[tuple[str, str]]:
    """`(utility, chain head)` for every row of `GEOMETRY_UTILITIES`, in order."""
    source = THEME_RS.read_text(encoding="utf-8")
    body = source.split(
        "const GEOMETRY_UTILITIES: &[(&str, &str, GeometryGroup, &[&str], &str)] = &[",
        1,
    )[1].split("\n];", 1)[0]
    return re.findall(
        r'\(\s*"([a-z0-9-]+)",\s*"[a-z0-9-]+",\s*GeometryGroup::\w+,\s*&\[\s*"([a-z0-9.]+)"',
        body,
    )


def _prompt_constant_names() -> list[str]:
    """The utility names the prompt constant glosses, one per line."""
    return re.findall(r"^([a-z][a-z0-9-]*) — ", WEB_GEOMETRY_UTILITIES, flags=re.MULTILINE)


def test_the_engine_table_parse_finds_a_plausible_geometry_vocabulary() -> None:
    """Guard the guard: a parse that silently matched nothing would make every
    other assertion in this module vacuous."""
    rows = _engine_rows()
    assert len(rows) == 10
    assert ("rounded-button", "radius.button") in rows
    assert ("p-card", "space.card.padding") in rows
    assert ("shadow-brand", "shadow.brand") in rows
    # The spelling trap: `border-card` is a COLOR class, never the hairline.
    assert "border-card" not in [utility for utility, _ in rows]


def test_the_author_prompt_constant_lists_exactly_the_ten_utilities() -> None:
    assert _prompt_constant_names() == [utility for utility, _ in _engine_rows()]


def test_the_author_prompt_carries_the_geometry_vocabulary() -> None:
    prompt = build_web_author_prompt(brand_card="{}", theme_token_names="primary")
    for utility, _ in _engine_rows():
        assert utility in prompt, utility


def test_the_create_website_skill_geometry_block_names_all_ten() -> None:
    text = SKILL_MD.read_text(encoding="utf-8")
    assert SKILL_BLOCK_MARKER in text
    block = text.split(SKILL_BLOCK_MARKER, 1)[1].split("\n## ", 1)[0]
    for utility, chain_head in _engine_rows():
        assert f"`{utility}`" in block, utility
        assert chain_head in block, chain_head


def test_the_recipe_mapping_table_is_exactly_the_engine_chain_heads() -> None:
    """A recipe slot names a KIT TOKEN; the author writes a CLASS. The mapping is
    that translation, and it is only sound while it matches the chains."""
    assert GEOMETRY_TOKEN_UTILITIES == {
        chain_head: utility for utility, chain_head in _engine_rows()
    }
