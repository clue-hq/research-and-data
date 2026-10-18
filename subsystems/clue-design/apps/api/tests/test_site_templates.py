"""Site element inspector, plan 6 (rulings R5, R6): ABM header and footer templates derived from the
seller's own captured header and footer, deterministically. The fixtures are synthetic captures shaped
like real ones (a Webflow header with dropdowns, co-brand text, a Login link and a hamburger; a
Tailwind header with a hidden mega-menu panel and a mobile drawer; two footers with link columns, a
newsletter form and social links)."""

from __future__ import annotations

from pathlib import Path

import pytest
from selectolax.lexbor import LexborHTMLParser

from lumen_api.fragments.site_templates import (
    MENU_ATTR,
    MENU_ITEM_ATTR,
    MENU_LABEL_ATTR,
    SITE_FOOTER_ROLE,
    SITE_HEADER_ROLE,
    TemplateNotDerivable,
    derive_site_template,
)
from lumen_api.fragments.slots import annotate_fragment_slots, slot_key_is_valid

FIXTURES = Path(__file__).parent / "fixtures" / "site_templates"
PLACEHOLDER = "/asset-store/" + "c" * 64


def _derive(name: str, role: str):
    return derive_site_template(role, (FIXTURES / f"{name}.html").read_text(), placeholder_src=PLACEHOLDER)


def _annotated(derived) -> LexborHTMLParser:
    """The template's markup with its slots stamped, as the mint would store it."""
    return LexborHTMLParser(annotate_fragment_slots(derived.html, derived.slots).html)


@pytest.mark.parametrize("name", ["webflow_header", "tailwind_header"])
def test_header_keeps_logo_menu_pattern_and_last_cta(name: str) -> None:
    tree = _annotated(_derive(name, SITE_HEADER_ROLE))
    logos = [a for a in tree.css("a[href='/']") if a.css_first("img, svg")]
    assert len(logos) == 1
    [menu] = tree.css(f"[{MENU_ATTR}]")
    assert len(menu.css(f"[{MENU_ITEM_ATTR}]")) == 1
    assert len(menu.css(f"[{MENU_ITEM_ATTR}] [{MENU_LABEL_ATTR}], [{MENU_ITEM_ATTR}][{MENU_LABEL_ATTR}]")) == 1
    # A button's words may sit beside an empty link laid over it (Webflow), or inside the link.
    outside_menu = [a.parent if (a.parent.tag == "button") else a for a in tree.css("a[href]") if not a.css_first("img, svg") and not _inside(a, menu)]
    assert [" ".join((node.text() or "").split()) for node in outside_menu] == ["Book a demo"], "one call to action, the last one"
    assert tree.css_first("[data-lumen-slot^=cta_href]") is not None, "its link can be changed"
    assert "Log in" not in (tree.body.text() or "") and "Login" not in (tree.body.text() or "")


@pytest.mark.parametrize("name", ["webflow_header", "tailwind_header"])
def test_header_drops_dropdowns_drawers_and_hidden(name: str) -> None:
    tree = _annotated(_derive(name, SITE_HEADER_ROLE))
    assert not tree.css("[hidden], [aria-expanded], [role=dialog], [data-closed], [aria-haspopup], .w-dropdown")
    assert not [b for b in tree.css("button, [role=button]") if not (b.text() or "").strip()]
    text = tree.body.text() or ""
    for gone in ("Resources", "Blog", "Agents", "Mobile menu", "Partner Co"):
        assert gone not in text, gone


@pytest.mark.parametrize("name", ["webflow_header", "tailwind_header"])
def test_header_inserts_the_account_after_the_logo(name: str) -> None:
    tree = _annotated(_derive(name, SITE_HEADER_ROLE))
    logo = next(a for a in tree.css("a[href='/']") if a.css_first("img, svg"))
    account = logo.next
    while account is not None and not account.tag.startswith("span"):
        account = account.next
    assert account is not None and "clue-account" in (account.attributes.get("class") or "")
    assert account.attributes.get("data-lumen-slot") == "account_shown"
    image = account.css_first("img.clue-account-logo")
    assert image.attributes.get("data-lumen-slot") == "account_logo" and image.attributes.get("src") == PLACEHOLDER
    line = account.next
    assert line is not None and line.attributes.get("data-lumen-slot") == "account_line"
    assert "clue-account-line" in (line.attributes.get("class") or "")
    menu_link = tree.css_first(f"[{MENU_ATTR}] a")
    for token in (menu_link.attributes.get("class") or "").split():
        assert token in (line.attributes.get("class") or "").split(), "the account line takes the menu link's look"


@pytest.mark.parametrize(("name", "role"), [("webflow_header", SITE_HEADER_ROLE), ("tailwind_header", SITE_HEADER_ROLE), ("webflow_footer", SITE_FOOTER_ROLE), ("tailwind_footer", SITE_FOOTER_ROLE)])
def test_every_text_has_a_slot(name: str, role: str) -> None:
    derived = _derive(name, role)
    keys = [spec.key for spec in derived.slots]
    assert len(keys) == len(set(keys)) and all(slot_key_is_valid(key) for key in keys)
    tree = _annotated(derived)
    menu = tree.css_first(f"[{MENU_ATTR}]")
    for node in tree.body.traverse(include_text=False):
        own = "".join(child.text_content or "" for child in node.iter(include_text=True) if child.tag == "-text").strip()
        if not own or (menu is not None and _inside(node, menu)):
            continue
        assert _slotted(node), f"<{node.tag}> {own!r} has no slot"
    if menu is not None:
        assert not menu.css("[data-lumen-slot]"), "the menu is filled from the site's pages, never a slot"


def _inside(node, ancestor) -> bool:
    current = node
    while current is not None:
        if current.mem_id == ancestor.mem_id:
            return True
        current = current.parent
    return False


def _slotted(node) -> bool:
    current = node
    while current is not None and current.tag not in ("body", "html"):
        if current.attributes.get("data-lumen-slot") and current.attributes.get("data-lumen-slot") != "visible":
            return True
        current = current.parent
    return False


@pytest.mark.parametrize("name", ["webflow_footer", "tailwind_footer"])
def test_footer_keeps_logo_and_legal_row_only(name: str) -> None:
    tree = _annotated(_derive(name, SITE_FOOTER_ROLE))
    text = " ".join((tree.body.text() or "").split())
    assert "©" in text or "Copyright" in text
    hrefs = [a.attributes.get("href") for a in tree.css("a")]
    assert any(h and "privacy" in h for h in hrefs) and any(h and "terms" in h for h in hrefs)
    for gone in ("newsletter", "Solutions", "Employers", "Products", "Agents", "Careers", "AI agents for hospitality"):
        assert gone not in text, gone
    assert not tree.css("form, input") and not tree.css("a[href^='https://x.com']")
    assert [a for a in tree.css("a[href='/']") if a.css_first("img")], "the logo stays"


def test_not_derivable_without_logo() -> None:
    with pytest.raises(TemplateNotDerivable) as refused:
        derive_site_template(SITE_HEADER_ROLE, "<header><nav><a href='/a'>A</a><a href='/b'>B</a></nav></header>", placeholder_src=PLACEHOLDER)
    assert refused.value.reason == "no logo"


def test_footer_not_derivable_without_legal_or_logo() -> None:
    with pytest.raises(TemplateNotDerivable) as refused:
        derive_site_template(SITE_FOOTER_ROLE, "<footer><a href='/a'>A</a><p>Hello</p></footer>", placeholder_src=PLACEHOLDER)
    assert refused.value.reason == "no legal row or logo"


@pytest.mark.parametrize(("name", "role"), [("webflow_header", SITE_HEADER_ROLE), ("tailwind_footer", SITE_FOOTER_ROLE)])
def test_derivation_is_deterministic(name: str, role: str) -> None:
    first, second = _derive(name, role), _derive(name, role)
    assert first.html == second.html and first.slots == second.slots and first.css_addition == second.css_addition
