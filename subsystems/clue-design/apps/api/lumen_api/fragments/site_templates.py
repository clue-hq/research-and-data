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
from urllib.parse import urlsplit

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

#: The two header templates the agent chooses between (founder 2026-10-19). An ABM page is normally
#: one page: the seller's logo and the account's on the left, "Prepared for …" in the centre, the
#: button on the right. A site with more pages keeps the line beside the logos, the menu in the centre.
HEADER_ONE_PAGE = "one_page"
HEADER_WITH_MENU = "with_menu"
HEADER_LAYOUTS: tuple[str, ...] = (HEADER_ONE_PAGE, HEADER_WITH_MENU)

#: What the account line says before the agent writes it for the account.
ACCOUNT_LINE_FALLBACK = "Prepared for you"
#: site-kit's phone width (``FALLBACKS.phoneMaxWidth``): below it the menu is hidden.
PHONE_MAX_WIDTH = "767px"
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
#: Where the account parts and the line go (replaced after the slots are detected).
_ACCOUNT_AT = "data-clue-account-at"
_LINE_AT = "data-clue-line-at"


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


def derive_site_template(
    role: str, source_html: str, *, placeholder_src: str, seller_logo_src: str | None = None,
    layout: str | None = None,
) -> DerivedTemplate:
    """The ABM ``role`` template (header or footer) from a captured fragment's sanitized markup.

    ``placeholder_src`` is the account logo's default file (the co-brand placeholder, an invisible
    pixel the fragment holds); the agent fills the ``account_logo`` slot when it writes a site.
    ``seller_logo_src`` is the kit's own logo file: it stands in for a seller's logo drawn in the
    page's code (an inline SVG), which the editor cannot replace (founder 2026-10-18).
    ``layout`` is a header's: :data:`HEADER_ONE_PAGE` (the default) or :data:`HEADER_WITH_MENU`.
    """
    if role not in SITE_TEMPLATE_ROLES:
        raise ValueError(f"{role!r} is not a site template role")
    if role == SITE_HEADER_ROLE:
        layout = layout or HEADER_ONE_PAGE
        if layout not in HEADER_LAYOUTS:
            raise ValueError(f"{layout!r} is not a header layout; expected one of {', '.join(HEADER_LAYOUTS)}")
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
    if logo is not None and (drawn := _drawn_logo_as_file(logo, seller_logo_src)):
        notes.append(drawn)
        if seller_logo_src:
            css_addition = ".clue-seller-logo{display:block;max-width:none;object-fit:contain}"
            logo = _find_logo(body)

    if role == SITE_HEADER_ROLE:
        if logo is None:
            raise TemplateNotDerivable("no logo")
        with_menu = layout == HEADER_WITH_MENU
        found_menu = _find_menu(body, logo)
        menu = found_menu if with_menu else None
        cta = _find_cta(body, logo, found_menu)
        if with_menu and menu is None:
            notes.append("no menu found: the template draws no page links")
        if cta is None:
            notes.append("no call to action found: the template has no button")
        _prune(body, [node for node in (logo, menu, cta[0] if cta else None) if node is not None])
        if menu is not None:
            _reduce_menu(menu)
        if cta is not None:
            cta[1].attrs[_CTA_MARK] = ""
        height = _logo_height(logo)
        _into_zones(logo, menu, cta[0] if cta else None, line_in_centre=not with_menu)
        # Inserted where the markers sit after the slots are detected, so the detector never claims
        # them. The line takes the header's own type (never the seller's menu-link classes, whose
        # phone-drawer box, hover pill and centring broke it on the live sites).
        account = [
            f'<span class="clue-account" {_PENDING}="account_shown|visibility">'
            '<span class="clue-account-rule" aria-hidden="true"></span>'
            f'<img class="clue-account-logo" src="{escape(placeholder_src)}" alt="" {_PENDING}="account_logo|image">'
            "</span>",
            f'<span class="clue-account-line" {_PENDING}="account_line|text">{escape(ACCOUNT_LINE_FALLBACK)}</span>',
        ]
        css_addition += (
            # Three zones over the seller's own header box (its background, height and padding stay):
            # the start and end columns share the room left over, so the centre is the true centre.
            ".clue-header-row{display:grid;grid-template-columns:minmax(0,1fr) auto minmax(0,1fr);"
            "align-items:center;column-gap:1.5em}"
            # Anything else the seller's header box held (a background layer) sits behind the zones.
            ".clue-header-row>:not(.clue-zone){grid-column:1/-1;grid-row:1}"
            # Above the header's own background layers (Garner's absolutely placed `.nav_bg`).
            ".clue-zone{position:relative;z-index:10;display:flex;align-items:center;gap:0.75em;min-width:0}"
            ".clue-zone-start{justify-self:start}.clue-zone-centre{justify-self:center}.clue-zone-end{justify-self:end}"
            ".clue-account{display:inline-flex;align-items:center;gap:0.75em;flex-shrink:0}"
            ".clue-account-rule{align-self:stretch;width:1px;background-color:currentColor;opacity:0.3}"
            f".clue-account-logo{{display:block;height:{height};width:auto;max-width:30vw;object-fit:contain}}"
            # Up to 40% of the window, then an ellipsis rather than pushing the header wide.
            ".clue-account-line{display:block;max-width:40vw;min-width:0;margin:0;padding:0;border:0;"
            "font:inherit;color:inherit;line-height:1.3;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}"
            # Plain words in every state, whatever the seller's stylesheet says about a span in a header.
            ".clue-account-line,.clue-account-line:hover,.clue-account-line:focus,.clue-account-line:focus-visible{"
            "background:none;box-shadow:none;outline:none;border-radius:0;text-decoration:none;cursor:auto}"
            # Phones (site-kit's phone width): the logos and the line; the hero carries the button.
            f"@media (max-width:{PHONE_MAX_WIDTH}){{.clue-header-row{{grid-template-columns:auto minmax(0,1fr)}}"
            ".clue-zone-end{display:none}.clue-zone-centre{justify-self:start}}"
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
    """The first link to the site's root (``/``, or the seller's full address) holding an image or icon;
    else the first image or icon, as the link around it when it has one, so the account parts are
    placed after the link and never inside it."""
    for anchor in body.css("a"):
        href = anchor.attributes.get("href") or ""
        root = href in {"", "#"} or (urlsplit(href).path in {"", "/"} and not urlsplit(href).query)
        if root and anchor.css_first("img, svg") is not None:
            return anchor
    image = body.css_first("img, svg")
    current = image
    while current is not None and (current.tag or "") != "a":
        current = current.parent
    return current if current is not None else image


def _drawn_logo_as_file(logo: LexborNode, seller_logo_src: str | None) -> str | None:
    """A logo drawn in the page's code (an inline SVG and no image) is swapped for the kit's logo file,
    keeping the drawing's classes and size attributes so it sits where the drawing sat. Returns the
    note saying what happened, or None when the logo is already an image or holds no drawing."""
    drawing = logo if (logo.tag or "") == "svg" else logo.css_first("svg")
    if drawing is None or (logo.tag or "") == "img" or logo.css_first("img") is not None:
        return None
    if not seller_logo_src:
        return "the seller's logo is drawn in the page's code and cannot be replaced in the editor"
    attributes = [f'src="{escape(seller_logo_src)}"', 'alt=""']
    classes = " ".join([*(drawing.attributes.get("class") or "").split(), "clue-seller-logo"])
    attributes.append(f'class="{escape(classes)}"')
    for size in ("width", "height"):
        value = drawing.attributes.get(size) or ""
        if value.isdigit():
            attributes.append(f'{size}="{value}"')
    drawing.replace_with(_node(f"<img {' '.join(attributes)}>"))
    return "the seller's logo was drawn in the page's code: the kit's logo file stands in so it can be replaced"


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
        if _contains(node, logo) or _contains(logo, node) or _hidden_on_desktop(node):
            continue
        items = len(_link_items(node))
        if items < 2:
            continue
        score = items + (1 if (node.tag or "") in {"nav", "ul", "ol"} or _has_ancestor(node, "nav") else 0)
        if score > best_score:
            best, best_score = node, score
    return best


_DESKTOP_HIDDEN = re.compile(r"^(sm|md|lg|xl|2xl):hidden$")


def _hidden_on_desktop(node: LexborNode) -> bool:
    """Whether the element (or one around it) is hidden on wider screens by its classes (``lg:hidden``):
    a phone drawer, never the menu a visitor sees on a desktop."""
    current: LexborNode | None = node
    while current is not None:
        if any(_DESKTOP_HIDDEN.match(token) for token in (current.attributes.get("class") or "").split()):
            return True
        current = current.parent
    return False


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


def _lowest_common_ancestor(nodes: list[LexborNode]) -> LexborNode:
    chain = []
    current: LexborNode | None = nodes[0]
    while current is not None:
        chain.append(current)
        current = current.parent
    for candidate in chain:
        if all(_contains(candidate, node) for node in nodes[1:]):
            return candidate
    return chain[-1]


def _into_zones(logo: LexborNode, menu: LexborNode | None, cta: LexborNode | None, *, line_in_centre: bool) -> None:
    """Rebuild the box that holds the kept parts as three zones: the logo and the account's place,
    then the line or the menu, then the call to action. The box keeps its own element and classes (the
    seller's padding and width); whatever else it held stays after the zones (a background layer)."""
    kept = [node for node in (logo, menu, cta) if node is not None]
    row = _lowest_common_ancestor(kept) if len(kept) > 1 else (logo.parent or logo)
    others = [
        child.html or "" for child in _children(row)
        if not any(_contains(child, node) for node in kept)
    ]
    line_at = f"<span {_LINE_AT}></span>"
    start = (logo.html or "") + f"<span {_ACCOUNT_AT}></span>" + ("" if line_in_centre else line_at)
    centre = line_at if line_in_centre else (menu.html or "" if menu is not None else "")
    end = cta.html or "" if cta is not None else ""
    zones = (
        f'<div class="clue-zone clue-zone-start">{start}</div>'
        f'<div class="clue-zone clue-zone-centre">{centre}</div>'
        f'<div class="clue-zone clue-zone-end">{end}</div>'
    )
    if (row.tag or "") in {"body", "html"}:
        # The parts sit loose in the capture: the zones get a box of their own.
        for child in _children(row):
            child.decompose()
        row.insert_child(_node(f'<div class="clue-header-row">{zones}{"".join(others)}</div>'))
        return
    attributes = dict(row.attributes)
    attributes["class"] = " ".join([*(attributes.get("class") or "").split(), "clue-header-row"])
    rendered = " ".join(f'{name}="{escape(value)}"' if value is not None else name for name, value in attributes.items())
    row.replace_with(_node(f"<{row.tag} {rendered}>{zones}{''.join(others)}</{row.tag}>"))


def _logo_height(logo: LexborNode) -> str:
    image = logo if (logo.tag or "") == "img" else logo.css_first("img")
    height = (image.attributes.get("height") or "") if image is not None else ""
    return f"{int(height)}px" if height.isdigit() and int(height) > 0 else ACCOUNT_LOGO_HEIGHT


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
    if account:
        for marker, part in ((_ACCOUNT_AT, account[0]), (_LINE_AT, account[1])):
            at = detected_body.css_first(f"[{marker}]")
            if at is not None:
                at.replace_with(_node(part))

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
