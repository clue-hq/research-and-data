"""D3 — the icon vocabulary the web author is told about must BE the vocabulary
the engine accepts.

`<i data-icon="NAME">` with a name outside `lumen_core::icons::ICONS` is a hard
LUMW0114 error, and a single web error rejects the whole authored page. That is
how a real run lost Stripe's header logo: the author placed the logo correctly,
wrote `data-icon="globe"` in a footer, and the entire batch was discarded with
`1 error diagnostic(s); page not stored`.

So the closed set is now stated in the AUTHOR PROMPT (in context for every token
it emits), not only in a skill file it reads once. Three copies therefore exist
— the Rust registry, the prompt constant, and the create-website typed reference — and
they are only useful if they cannot drift apart. This module is that guard: the
Rust registry is the source of truth, the other two are checked against it.
"""

from __future__ import annotations

import re
from pathlib import Path

from lumen_agent.prompts_web import WEB_ICON_NAMES, build_web_author_prompt
from test_web_skill_family import read_required_skill_reference

REPO_ROOT = Path(__file__).resolve().parents[3]
ICONS_RS = REPO_ROOT / "crates" / "lumen-core" / "src" / "icons.rs"


def _registry_icon_names() -> list[str]:
    """The names in `const ICONS: &[(&str, &str)]`, in registry order."""
    source = ICONS_RS.read_text(encoding="utf-8")
    body = source.split("const ICONS: &[(&str, &str)] = &[", 1)[1].split("\n];", 1)[0]
    return re.findall(r'^\s*\("([a-z0-9-]+)",', body, flags=re.MULTILINE)


def test_the_registry_parse_finds_a_plausible_icon_set() -> None:
    """Guard the guard: a parse that silently matched nothing would make every
    other assertion here vacuous."""
    names = _registry_icon_names()
    assert len(names) >= 20
    assert "check" in names and "arrow-right" in names
    assert "globe" not in names  # the exact name that voided a real page


def test_the_author_prompt_vocabulary_matches_the_rust_registry() -> None:
    assert WEB_ICON_NAMES.split() == _registry_icon_names()


def test_the_create_website_skill_vocabulary_matches_the_rust_registry(tmp_path) -> None:
    text = read_required_skill_reference(
        tmp_path, "create-website", "typed authoring reference",
        before="Use the ", after=" before `author_web_page` / `author_web_subtree`.",
    )
    block = text.split("**Icon names — the COMPLETE set.**", 1)[1].split("`.", 1)[0]
    # `*`, not `+`: the single-character icon `x` is a real name.
    listed = re.findall(r"[a-z][a-z0-9-]*", block.split("`", 1)[1])
    assert listed == _registry_icon_names()


def test_the_author_prompt_carries_the_icon_names_and_the_penalty() -> None:
    """A closed vocabulary is only actionable if the author also knows what
    breaking it costs — the whole page, not just the icon."""
    prompt = build_web_author_prompt(brand_card="{}", theme_token_names="primary")
    for name in _registry_icon_names():
        assert name in prompt
    assert "data-icon" in prompt
    assert "rejects the WHOLE page" in prompt
