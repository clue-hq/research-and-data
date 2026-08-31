"""W1.3 — the token vocabulary the author prompt advertises must BE the token
vocabulary the compiled theme carries.

`web_theme_token_names` is injected into the author prompt as "THEME TOKENS";
the engine's class lint checks every color class against the theme the Rust
compiler actually built (`crates/lumen-web/src/theme.rs::compile_web_theme`).
Two independent implementations of the same rule set, so they can drift — and
drift here is expensive: a name the prompt advertises but the theme skipped is
an invitation to write a class that voids the whole page (LUMW0212).

Unlike the icon vocabulary (a closed list in Rust source, checkable by parsing
the registry), the token list is KIT-DEPENDENT — so parity has to be proven
against a COMPILED theme, not against source text. The compiled list is
observable from Python exactly once: the LUMW0212 rejection's hint enumerates
it ("Theme tokens: …", classes.rs::token_list). So this test ingests one page
whose single class references a token that cannot exist, with a purpose-built
kit as the theme, and reads the real compiled vocabulary out of the refusal.

The fixture kit carries every interesting case: a normal extra color, a color
whose sanitized name collides with a semantic token, and colors whose alias
chain dangles or cycles (the LUMW0302 skip Python used to ignore).

The second half of the module guards the OTHER thing this slice states to the
author — the brand card's class advice — against the same lint.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from lumen_agent.brand_card import COLOR_ROLE_NOTE
from lumen_agent.tools.web_substrate import web_theme_token_names

REPO_ROOT = Path(__file__).resolve().parents[3]

pytestmark = pytest.mark.skipif(
    not os.environ.get("LUMEN_CORE_HELPER"),
    reason="requires the real core helper binary",
)

# One class, one token that no kit can ever carry → LUMW0212 with the hint.
PROBE_HTML = '<section id="probe" class="bg-nosuchtoken"><p>probe</p></section>'

HINT_PREFIX = "Theme tokens: "
HINT_SUFFIX = " (plus white/black/transparent/current)."


def _hex(value: str) -> dict:
    return {"value": {"default": {"kind": "hex", "value": value}}}


def _alias(target: str) -> dict:
    return {"value": {"default": {"kind": "alias", "token": target}}}


def _fixture_kit(core) -> dict:
    """The platform default kit (a real, valid kit the helper will parse) plus
    the three cases the two skip rules are made of."""
    kit = core.platform_default_brand_kit()
    colors = kit["tokens"]["colors"]
    colors["parity.teal"] = _hex("#30D8A7")  # (i) normal extra color → kept
    colors["Primary"] = _hex("#123456")  # (ii) sanitizes to the semantic `primary` → skipped
    colors["parity.ghost"] = _alias("parity.absent")  # (iii) dangling alias → skipped
    colors["parity.loop"] = _alias("parity.loop")  # a cycle is unresolvable too
    return kit


def _compiled_token_names(core, kit: dict) -> set:
    """The token names the RUST theme compiler emitted for `kit`, harvested from
    the class lint's own refusal."""
    seed = core.web_new_doc("doc_token_parity", "Parity", None)["web_doc"]
    # A per-document override would add tokens Python cannot see; a fresh doc
    # carries none, and this test's claim depends on that.
    assert not (seed.get("theme") or {}).get("overrides")
    response = core.web_ingest_html(seed, "home", PROBE_HTML, None, brand_kit=kit)
    hints = [
        diagnostic.get("hint")
        for diagnostic in response.get("diagnostics") or []
        if isinstance(diagnostic, dict) and diagnostic.get("code") == "LUMW0212"
    ]
    assert len(hints) == 1, response.get("diagnostics")
    hint = hints[0]
    assert hint.startswith(HINT_PREFIX) and hint.endswith(HINT_SUFFIX), hint
    listed = hint[len(HINT_PREFIX) : -len(HINT_SUFFIX)]
    return {name.strip() for name in listed.split(",") if name.strip()}


def test_the_harvest_finds_a_plausible_compiled_vocabulary():
    """Guard the guard: a hint parse that silently matched nothing would make
    the parity assertion below vacuous."""
    from lumen_api.core import CoreClient

    core = CoreClient(repo_root=REPO_ROOT)
    names = _compiled_token_names(core, _fixture_kit(core))
    assert {"primary", "accent", "dark", "light", "card", "muted", "border", "inverse"} <= names
    assert all(re.fullmatch(r"[a-z0-9-]+", name) for name in names), names
    assert len(names) > 8  # the kit's own colors are preserved alongside the semantic eight


def test_python_token_names_equal_the_compiled_theme_tokens():
    """The drift guard itself: same kit, same vocabulary, both skip rules."""
    from lumen_api.core import CoreClient

    core = CoreClient(repo_root=REPO_ROOT)
    kit = _fixture_kit(core)
    compiled = _compiled_token_names(core, kit)
    advertised = set(web_theme_token_names(kit).split())
    assert advertised == compiled


def test_the_fixture_actually_exercises_both_skip_rules():
    """If the fixture stopped containing a collision and an unresolvable color,
    the equality above would still pass while proving nothing."""
    from lumen_api.core import CoreClient

    core = CoreClient(repo_root=REPO_ROOT)
    compiled = _compiled_token_names(core, _fixture_kit(core))
    assert "parity-teal" in compiled  # the normal color survives
    assert "parity-ghost" not in compiled  # dangling alias (LUMW0302)
    assert "parity-loop" not in compiled  # cyclic alias
    # `Primary` sanitizes onto the semantic name, which is present exactly once
    # and holds the SEMANTIC value — the collision was skipped, not overwritten.
    assert "primary" in compiled


# --- the brand card's class advice, checked against the lint that judges it ---
#
# The card's color-role block now tells the author how to turn a kit ROLE into a
# class. That advice is only worth stating if it is mechanically right, and only
# the engine can say so: `text.brand` is the class `text-text-brand` because the
# lint strips the LONGEST matching color prefix (`text-`) and looks the rest up
# as a token. Writing the role itself (`text-brand`) parses as prefix `text-` +
# token `brand` — the exact shape behind 153 live rejections.

ROLE_CLASSES = re.findall(r"\b(?:bg|text|border)-[a-z][a-z0-9-]*", COLOR_ROLE_NOTE)


def _kit_with_brand_roles(core) -> dict:
    kit = core.platform_default_brand_kit()
    for role in ("surface.brand", "text.brand", "border.brand"):
        kit["tokens"]["colors"].setdefault(role, _hex("#00525C"))
    return kit


def _error_codes(core, kit: dict, html: str) -> list:
    seed = core.web_new_doc("doc_role_classes", "Roles", None)["web_doc"]
    response = core.web_ingest_html(seed, "home", html, None, brand_kit=kit)
    return [
        diagnostic.get("code")
        for diagnostic in response.get("diagnostics") or []
        if isinstance(diagnostic, dict) and diagnostic.get("severity") == "error"
    ]


def test_every_class_the_card_note_names_lints_clean():
    from lumen_api.core import CoreClient

    core = CoreClient(repo_root=REPO_ROOT)
    assert ROLE_CLASSES == ["bg-surface-brand", "text-text-brand", "border-border-brand"]
    html = f'<section id="probe" class="{" ".join(ROLE_CLASSES)}"><p>probe</p></section>'
    assert _error_codes(core, _kit_with_brand_roles(core), html) == []


def test_the_transposition_the_note_warns_about_really_is_rejected():
    """Guard the note's premise: the role name written as a class is a hard
    error, so the `token` field on each row is not decoration."""
    from lumen_api.core import CoreClient

    core = CoreClient(repo_root=REPO_ROOT)
    html = '<section id="probe" class="bg-light"><p class="text-brand">probe</p></section>'
    assert _error_codes(core, _kit_with_brand_roles(core), html) == ["LUMW0212"]
