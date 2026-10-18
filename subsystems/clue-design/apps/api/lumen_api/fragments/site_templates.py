"""Site header and footer templates (site element inspector, plan 6, rulings R4-R6).

A microsite's header and footer start from the seller's OWN top bar and footer, so they look like the
seller's site, made ABM-focused: the seller's logo beside the account's, a line addressing the account,
the site's own pages as the menu and one call to action; a footer with the seller's mark, the copyright
line and the legal links. Derived once per brand kit, from the kit's captured ``nav`` and ``footer``
fragments, and minted as copied sections so the marketer edits them with the clone tools.

**Deterministic, never a model.** Every rule below is structural and the same input gives the same
bytes. The input is a fragment payload's sanitized markup; the output is markup plus the slots to
annotate it with, handed to the mint's own door (sanitize, annotate, scope the CSS, content-address).

What goes:

* the parts that only work with the seller's JavaScript or lead away: hidden elements, closed panels,
  dialogs, dropdown lists and toggles, menu buttons with no words, forms and inputs;
* everything that is not a kept part and shows something (text, a link, a button, an image), so link
  columns, newsletters, social icons, co-brand text and the seller's other buttons go, while empty
  decorative elements (backgrounds, overlays) stay.

What stays, header: the logo, the menu (marked, reduced to one pattern item that the renderer repeats
once per page of the site: ``site-kit/src/clone.ts``) and the last link that is not a sign-in. Footer:
the logo, the copyright line and the legal links. Then every remaining text gets a slot, so every word
can be changed in place.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html import escape

from selectolax.lexbor import LexborHTMLParser, LexborNode

from .slots import SLOT_MARKER_ATTR, SlotSpec

#: ``section_role`` of the two templates (a kit's own; the older ABM pair is ``campaign_*``).
SITE_HEADER_ROLE = "site_header"
SITE_FOOTER_ROLE = "site_footer"
SITE_TEMPLATE_ROLES: tuple[str, ...] = (SITE_HEADER_ROLE, SITE_FOOTER_ROLE)

#: ``provenance["composed"]`` on a template row.
COMPOSED_SITE_TEMPLATE = "site_template"

#: The marks the renderer reads to draw the site's pages as the menu (``site-kit/src/clone.ts``).
MENU_ATTR = "data-clue-menu"
MENU_ITEM_ATTR = "data-clue-menu-item"
MENU_LABEL_ATTR = "data-clue-menu-label"

#: What the account line says before the agent writes it for the account.
ACCOUNT_LINE_FALLBACK = "Prepared for you"
#: The account's logo when the seller's logo carries no height of its own.
ACCOUNT_LOGO_HEIGHT = "1.75em"

#: Parts that only work with the seller's JavaScript, or that are never the page's to show.
_INTERACTIVE = (
    "[hidden], [data-closed], [role=dialog], [aria-haspopup], [aria-expanded], "
    ".w-dropdown, .w-dropdown-list, .w-dropdown-toggle, "
    "form, input, select, textarea, iframe, noscript, script, template"
)
_SIGN_IN = re.compile(r"^(log ?in|sign ?in|sign ?up)$", re.IGNORECASE)
_COPYRIGHT = re.compile(r"©|copyright|all rights reserved", re.IGNORECASE)
_LEGAL = re.compile(r"privacy|terms|cookie|legal", re.IGNORECASE)
_CONTENT = "a, button, img, svg, video, picture, input"
#: A slot the derivation has chosen but not yet turned into a selector (removed before returning).
_PENDING = "data-clue-slot-pending"
_CTA_MARK = "data-clue-cta-pending"


class TemplateNotDerivable(Exception):
    """The capture has no part a template needs (a header without a logo; a footer without a logo or
    a copyright/legal row). The kit then has no template of that role and sites use the fallback."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class DerivedTemplate:
    """The template's markup (no slot markers yet), its slots, the CSS its account parts need, and
    what the derivation could not do."""

    html: str
    slots: tuple[SlotSpec, ...]
    css_addition: str
    notes: tuple[str, ...]


def derive_site_template(role: str, source_html: str, *, placeholder_src: str) -> DerivedTemplate:
    """The ABM ``role`` template (header or footer) from a captured fragment's sanitized markup.

    ``placeholder_src`` is the account logo's default file (the co-brand placeholder, an invisible
    pixel the fragment holds); the agent fills the ``account_logo`` slot when it writes a site.
    """
    if role not in SITE_TEMPLATE_ROLES:
        raise ValueError(f"{role!r} is not a site template role")
    tree = LexborHTMLParser(source_html or "")
    body = tree.body
    if body is None:
        raise TemplateNotDerivable("empty markup")
    for marked in body.css(f"[{SLOT_MARKER_ATTR}]"):
        del marked.attrs[SLOT_MARKER_ATTR]
    _remove_interactive(body)
    logo = _find_logo(body)
    notes: list[str] = []
    css_addition = ""
    account: list[str] = []

    if role == SITE_HEADER_ROLE:
        if logo is None:
            raise TemplateNotDerivable("no logo")
        menu = _find_menu(body, logo)
        cta = _find_cta(body, logo, menu)
        if menu is None:
            notes.append("no menu found: the template draws no page links")
        if cta is None:
            notes.append("no call to action found: the template has no button")
        _prune(body, [node for node in (logo, menu, cta[0] if cta else None) if node is not None])
        if menu is not None:
            _reduce_menu(menu)
        if cta is not None:
            cta[1].attrs[_CTA_MARK] = ""
        height = _logo_height(logo)
        line_class = _menu_link_class(menu)
        # Drawn right after the logo, in this order (inserted after the slots are detected, so the
        # detector never claims them).
        account = [
            f'<span class="clue-account" {_PENDING}="account_shown|visibility">'
            '<span class="clue-account-rule" aria-hidden="true"></span>'
            f'<img class="clue-account-logo" src="{escape(placeholder_src)}" alt="" {_PENDING}="account_logo|image">'
            "</span>",
            f'<span class="{escape(" ".join([*line_class, "clue-account-line"]))}" {_PENDING}="account_line|text">'
            f"{escape(ACCOUNT_LINE_FALLBACK)}</span>",
        ]
        css_addition = (
            ".clue-account{display:inline-flex;align-items:center;gap:0.75em;flex-shrink:0}"
            ".clue-account-rule{align-self:stretch;width:1px;background-color:currentColor;opacity:0.3}"
            f".clue-account-logo{{display:block;height:{height};width:auto}}"
            ".clue-account-line{white-space:nowrap}"
        )
    else:
        copyright_line = _find_copyright(body)
        legal = [a for a in body.css("a") if _LEGAL.search(_text(a)) or _LEGAL.search(a.attributes.get("href") or "")]
        if logo is None or (copyright_line is None and not legal):
            raise TemplateNotDerivable("no legal row or logo")
        _prune(body, [node for node in (logo, copyright_line, *legal) if node is not None])

    return _with_slots(body, account, css_addition, notes)


# --------------------------------------------------------------------------- #
# what goes
# --------------------------------------------------------------------------- #


def _remove_interactive(body: LexborNode) -> None:
    while (node := body.css_first(_INTERACTIVE)) is not None:
        node.decompose()
    while True:
        wordless = [node for node in body.css("button, [role=button]") if not _text(node)]
        if not wordless:
            break
        wordless[0].decompose()


def _prune(root: LexborNode, keep: list[LexborNode]) -> None:
    """Remove every element that holds no kept part and shows something; a kept part stays whole."""
    kept = {node.mem_id for node in keep}

    def holds_kept(node: LexborNode) -> bool:
        return node.mem_id in kept or any(child.mem_id in kept for child in node.traverse(include_text=False))

    def walk(node: LexborNode) -> None:
        for child in _children(node):
            if child.mem_id in kept:
                continue
            if holds_kept(child):
                walk(child)
            elif _text(child) or child.css_first(_CONTENT) is not None or (child.tag or "") in {"a", "button", "img", "svg", "video", "picture"}:
                child.decompose()

    walk(root)


# --------------------------------------------------------------------------- #
# what stays
# --------------------------------------------------------------------------- #


def _find_logo(body: LexborNode) -> LexborNode | None:
    """The first link to the site's root holding an image or icon, else the first image or icon."""
    for anchor in body.css("a"):
        if (anchor.attributes.get("href") or "") in {"/", "", "#"} and anchor.css_first("img, svg") is not None:
            return anchor
    return body.css_first("img, svg")


def _link_items(container: LexborNode) -> list[LexborNode]:
    """The container's direct children that are, or hold exactly one, link."""
    items = []
    for child in _children(container):
        if (child.tag or "") == "a" and child.attributes.get("href") is not None:
            items.append(child)
        elif len(child.css("a[href]")) == 1:
            items.append(child)
    return items


def _find_menu(body: LexborNode, logo: LexborNode) -> LexborNode | None:
    """The element outside the logo with the most link items (at least two); a list or a nav ranks
    one higher, so the seller's menu wins over a row of buttons."""
    best, best_score = None, 0
    for node in body.traverse(include_text=False):
        if _contains(node, logo) or _contains(logo, node):
            continue
        items = len(_link_items(node))
        if items < 2:
            continue
        score = items + (1 if (node.tag or "") in {"nav", "ul", "ol"} or _has_ancestor(node, "nav") else 0)
        if score > best_score:
            best, best_score = node, score
    return best


def _find_cta(body: LexborNode, logo: LexborNode, menu: LexborNode | None) -> tuple[LexborNode, LexborNode] | None:
    """The last link with words outside the logo and the menu that is not a sign-in, as (the part to
    keep, the link). A link laid empty over a button whose words sit beside it (Webflow) takes the
    button's words, and the button is kept with it."""
    found = None
    for anchor in body.css("a[href]"):
        if _contains(logo, anchor) or (menu is not None and _contains(menu, anchor)):
            continue
        button = anchor.parent if anchor.parent is not None and (anchor.parent.tag or "") == "button" else None
        words = _text(anchor) or (_text(button) if button is not None else "")
        if words and not _SIGN_IN.match(words):
            found = (button if button is not None and not _text(anchor) else anchor, anchor)
    return found


def _reduce_menu(menu: LexborNode) -> None:
    """Mark the menu, keep its first link item as the pattern (its words marked as the label), drop
    the rest."""
    items = _link_items(menu)
    pattern = items[0]
    for child in _children(menu):
        if child.mem_id != pattern.mem_id:
            child.decompose()
    menu.attrs[MENU_ATTR] = ""
    pattern.attrs[MENU_ITEM_ATTR] = ""
    label = _deepest_text(pattern) or pattern
    label.attrs[MENU_LABEL_ATTR] = ""


def _find_copyright(body: LexborNode) -> LexborNode | None:
    """The deepest element whose words say ©, copyright or all rights reserved."""
    found = None
    for node in body.traverse(include_text=False):
        if _COPYRIGHT.search(_text(node)) and not any(_COPYRIGHT.search(_text(child)) for child in _children(node)):
            found = found or node
    return found


def _logo_height(logo: LexborNode) -> str:
    image = logo if (logo.tag or "") == "img" else logo.css_first("img")
    height = (image.attributes.get("height") or "") if image is not None else ""
    return f"{int(height)}px" if height.isdigit() and int(height) > 0 else ACCOUNT_LOGO_HEIGHT


def _menu_link_class(menu: LexborNode | None) -> list[str]:
    anchor = menu.css_first("a") if menu is not None else None
    return (anchor.attributes.get("class") or "").split() if anchor is not None else []


# --------------------------------------------------------------------------- #
# slots
# --------------------------------------------------------------------------- #


def _with_slots(body: LexborNode, account: list[str], css_addition: str, notes: list[str]) -> DerivedTemplate:
    """The mint's own detector on the template's markup (never inside the menu, which is filled from
    the site's pages), the ruled account parts after the logo, the call to action's link, then a slot
    for every text still without one. Returned as structural selectors over the markup with no marks."""
    from lumen_ingestion.sections.slotdetect import _selector, detect_slots

    html = _inner_html(body)
    detected_body = LexborHTMLParser(html).body
    menu = detected_body.css_first(f"[{MENU_ATTR}]")
    for spec in detect_slots(html).specs:
        node = detected_body.css_first(spec.selector)
        if node is None or (menu is not None and _contains(menu, node)):
            continue
        node.attrs[_PENDING] = f"{spec.key}|{spec.kind}"
    logo = _find_logo(detected_body)
    if logo is not None:
        for part in reversed(account):
            logo.insert_after(_node(part))

    taken = {(node.attributes.get(_PENDING) or "").split("|")[0] for node in detected_body.css(f"[{_PENDING}]")}

    def free(base: str) -> str:
        if base not in taken:
            taken.add(base)
            return base
        number = 2
        while f"{base}_{number}" in taken:
            number += 1
        taken.add(f"{base}_{number}")
        return f"{base}_{number}"

    cta = detected_body.css_first(f"[{_CTA_MARK}]")
    if cta is not None:
        del cta.attrs[_CTA_MARK]
        if not (cta.attributes.get(_PENDING) or "").endswith("|href"):
            if cta.attributes.get(_PENDING):
                del cta.attrs[_PENDING]
            cta.attrs[_PENDING] = f"{free('cta_href')}|href"

    count = 0
    for node in list(detected_body.traverse(include_text=False)):
        if node.parent is None or not _own_text(node) or (menu is not None and _contains(menu, node)):
            continue
        if _has_text_slot(node) or any(_kind(child) == "text" for child in node.traverse(include_text=False) if child.mem_id != node.mem_id):
            continue
        count += 1
        key = free(f"text_{count}")
        if node.attributes.get(_PENDING):
            # The element holds another slot (a link, the whole section): its words get an element.
            for child in list(node.iter(include_text=True)):
                if child.is_text_node and (child.text_content or "").strip():
                    child.replace_with(_node(f"<span {_PENDING}=\"{key}|text\">{escape(child.text_content or '')}</span>"))
                    break
        else:
            node.attrs[_PENDING] = f"{key}|text"

    specs: list[SlotSpec] = []
    for node in list(detected_body.traverse(include_text=False)):
        pending = node.attributes.get(_PENDING)
        if not pending:
            continue
        key, kind = pending.split("|", 1)
        specs.append(SlotSpec(selector=_selector(node), key=key, kind=kind))
    for node in detected_body.css(f"[{_PENDING}]"):
        del node.attrs[_PENDING]
    return DerivedTemplate(html=_inner_html(detected_body), slots=tuple(specs), css_addition=css_addition, notes=tuple(notes))


def _kind(node: LexborNode) -> str:
    pending = node.attributes.get(_PENDING) or ""
    return pending.split("|", 1)[1] if "|" in pending else ""


def _has_text_slot(node: LexborNode) -> bool:
    current: LexborNode | None = node
    while current is not None and (current.tag or "") not in {"body", "html"}:
        if _kind(current) == "text":
            return True
        current = current.parent
    return False


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #


def _node(html: str) -> LexborNode:
    return LexborHTMLParser(html).body.child


def _children(node: LexborNode) -> list[LexborNode]:
    return [child for child in node.iter(include_text=False) if child.tag and not child.tag.startswith("-")]


def _text(node: LexborNode) -> str:
    return " ".join((node.text(deep=True) or "").split())


def _own_text(node: LexborNode) -> str:
    return " ".join("".join(child.text_content or "" for child in node.iter(include_text=True) if child.is_text_node).split())


def _deepest_text(node: LexborNode) -> LexborNode | None:
    found = None
    for candidate in node.traverse(include_text=False):
        if _own_text(candidate):
            found = candidate
    return found


def _contains(ancestor: LexborNode, node: LexborNode) -> bool:
    current: LexborNode | None = node
    while current is not None:
        if current.mem_id == ancestor.mem_id:
            return True
        current = current.parent
    return False


def _has_ancestor(node: LexborNode, tag: str) -> bool:
    current = node.parent
    while current is not None:
        if (current.tag or "") == tag:
            return True
        current = current.parent
    return False


def _inner_html(body: LexborNode) -> str:
    return "".join(child.html or "" for child in body.iter(include_text=True))
