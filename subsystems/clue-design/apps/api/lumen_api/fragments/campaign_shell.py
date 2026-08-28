"""The campaign shell: an ABM page's own header and footer (clone-fidelity F4.1).

A cloned homepage wears the client's real global navigation, and that is right for a homepage.
It is wrong for an ABM page. **Every nav link is an escape route** — a visitor who came to read
one page written for their company leaves it for the pricing page, the careers page, the blog,
and the campaign is over. So an ABM page gets a *page-local* shell instead: a minimal header
carrying the seller's mark, the words "Prepared for <account>", the target's own logo when we
hold one, and exactly ONE call to action; and a footer carrying the seller's mark, a copyright
line, and the seller's legal links — nothing else.

**The shells are fragments, minted through the same door every clone goes through** (ruling
R23-1). Composed with engine primitives, rendered by the engine, lifted out of that render,
sanitized, scoped, content-addressed, born ``draft``, released by the human who approves the
brand kit. There is no second, softer path for markup we wrote ourselves — that is the whole
point of the repair seam this is modeled on (F3.1 / ruling R17-1).

**One header and one footer per brand kit.** Nothing here is per-account: an account's name and
logo, and the campaign's call to action, arrive at the ONE artifact through its slots (F1.4), so
a thousand accounts share two fragments.

The three structural rules, stated as code rather than as prompt advice:

* :func:`assert_campaign_shell_shape` is the Ploy campaign-shell rule (ruling R23-3). The header
  holds exactly one anchor and it is the CTA; the footer's anchors are all legal links; neither
  holds a ``<nav>``, a menu or a button. It runs at MINT, on the rendered subtree, so no caller —
  not this module's own composer, not a future one — can put an escape route into a shell.
* :func:`campaign_shell_slots` is the slot contract (ruling R23-2), spelled once. The header
  declares exactly ``prepared_for``, ``target_logo``, ``cta_href``, ``cta_label``; the footer
  declares none, because nothing in it is per-account.
* An EMPTY target logo is CORRECT, permanently (the never-synthesize register). We do not invent
  a company's mark, and the ladder does not always find one. So the co-brand slot's own default
  is :data:`COBRAND_PLACEHOLDER_PNG` — a 1×1 fully transparent pixel, which is the only spelling
  of "nothing goes here" the engine will accept (it refuses an ``<img>`` with no asset outright).
  Unbound, the header shows no second mark at all: no broken image, no grey box, no words.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from html import escape
from urllib.parse import urljoin, urlsplit

from selectolax.lexbor import LexborHTMLParser

from .refs import FragmentRefused
from .slots import SlotSpec

# --------------------------------------------------------------------------- #
# what a shell IS
# --------------------------------------------------------------------------- #

#: ``section_role`` on the two shell rows. Deliberately NOT ``nav``/``footer`` — those are the
#: harvested roles, and a picker that showed the campaign header under ``nav`` would offer it as
#: a replacement for the client's real navigation, which is exactly the confusion F4.1 exists to
#: end. The column is free text (the registry's CHECK asks only that it be non-empty), so the
#: vocabulary extends by naming, not by migration.
CAMPAIGN_SHELL_HEADER = "campaign_header"
CAMPAIGN_SHELL_FOOTER = "campaign_footer"
CAMPAIGN_SHELL_ROLES: tuple[str, ...] = (CAMPAIGN_SHELL_HEADER, CAMPAIGN_SHELL_FOOTER)

#: ``provenance["composed"]`` on a shell row — the marker that tells a shell from a harvested
#: clone at every surface that lists them (discovery, the inspector, the recreate). A harvested
#: section never carries it.
COMPOSED_CAMPAIGN_SHELL = "campaign_shell"

#: ``source_url`` for a shell. The column is NOT NULL and non-empty, and a shell came from no
#: page — so it says so, in a form no fetcher could mistake for a URL to go and get. It is also
#: what keeps a shell out of the whole-page recreate: the recreate groups by page, and this is
#: not one of the client's pages.
CAMPAIGN_SHELL_SOURCE_URL = "composed:campaign-shell"

#: Marker classes. They survive the engine render verbatim (they are ordinary node classes) and
#: are what the slot annotator's selectors match, so the artifact's editable spots are located by
#: something WE minted rather than by a structural nth-child path that a render change could
#: silently re-point. They compile to no CSS — an unknown utility is a warning at ingest and
#: nothing at all downstream — and they stay in the stored markup as a legible record of which
#: element is which.
MARK_PREPARED_FOR = "lumen-shell-prepared-for"
MARK_TARGET_LOGO = "lumen-shell-target-logo"
MARK_CTA = "lumen-shell-cta"
MARK_CTA_LABEL = "lumen-shell-cta-label"
MARK_LEGAL = "lumen-shell-legal"
MARK_SELLER_MARK = "lumen-shell-seller-mark"

#: The classes the engine will warn about as unknown utilities (``LUMW0220``). Ours, deliberately
#: — named here so the mint can drop that one warning from its report instead of handing the
#: caller noise about a marker it planted itself.
CAMPAIGN_SHELL_MARKER_CLASSES: frozenset[str] = frozenset(
    {MARK_PREPARED_FOR, MARK_TARGET_LOGO, MARK_CTA, MARK_CTA_LABEL, MARK_LEGAL, MARK_SELLER_MARK}
)

#: The section ids the composed markup carries, so the mint can lift each shell out of the
#: engine's render of it by name (``render.rs`` emits a section's own anchor id).
CAMPAIGN_SHELL_SECTION_IDS = {
    CAMPAIGN_SHELL_HEADER: "sec_campaign_header",
    CAMPAIGN_SHELL_FOOTER: "sec_campaign_footer",
}

#: The framing, and it is STRUCTURAL. "Prepared for" is static text in the artifact and only the
#: name after it is a slot, so no binding — agent, derive or human — can turn a prepared-for
#: header into a claim of partnership or custom (F4.2's relationship-language guardrail, made
#: impossible rather than discouraged).
PREPARED_FOR_PREFIX = "Prepared for "

#: What the header says with nothing bound. Never a fabricated company: a shell serves every
#: account, and the one it is looking at is always supplied at derive time.
DEFAULT_PREPARED_FOR = "your team"

#: The one action, before a campaign names its own. A page-local anchor, so the default can never
#: itself become an escape route.
DEFAULT_CTA_LABEL = "Book a walkthrough"
DEFAULT_CTA_HREF = "#contact"

#: The engine asset id the co-brand placeholder is upserted under.
COBRAND_PLACEHOLDER_ASSET_ID = "campaign_shell_cobrand"
COBRAND_PLACEHOLDER_MEDIA_TYPE = "image/png"

#: A 1×1 fully transparent PNG (palette + ``tRNS``, 95 bytes). The empty state of the co-brand
#: slot, and the ONLY reason it exists: ``ingest.rs`` refuses an ``<img>`` with no ``data-asset``
#: outright (``LUMW0111``, an error), so a header composed through the engine cannot carry an
#: image element with nothing in it. This is not a placeholder in the visible sense and must
#: never become one — it is invisible, has no alt text, and adds one pixel of layout under a
#: ``max-h`` cap that cannot inflate it. Synthesizing a target's LOGO stays forbidden; this
#: synthesizes the absence of one.
COBRAND_PLACEHOLDER_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010103000000"
    "25db56ca00000003504c5445000000a77a3dda0000000174524e530040"
    "e6d8660000000a4944415408d76360000000020001e221bc3300000000"
    "49454e44ae426082"
)


# --------------------------------------------------------------------------- #
# the slot contract (ruling R23-2)
# --------------------------------------------------------------------------- #

_HEADER_SLOTS: tuple[SlotSpec, ...] = (
    # The account's display name — only the name. The framing around it is not a slot.
    SlotSpec(selector=f".{MARK_PREPARED_FOR}", key="prepared_for", kind="text"),
    # The target's own mark, bound by the logo ladder at derive or authoring time. Empty is a
    # correct answer, and the artifact's own default is the transparent pixel.
    SlotSpec(selector=f".{MARK_TARGET_LOGO}", key="target_logo", kind="image"),
    # The ONE action. Two slots on two elements: the anchor takes the target, the label inside it
    # takes the words. (`slots.py` refuses two slots on one element, which is why the CTA is
    # composed as a container-link wrapping its own text rather than as a button whose label is
    # the anchor's only content.)
    SlotSpec(selector=f".{MARK_CTA}", key="cta_href", kind="href"),
    SlotSpec(selector=f".{MARK_CTA_LABEL}", key="cta_label", kind="text"),
)

#: The footer declares NO slots, and that is the ruling read literally: it carries the seller's
#: mark, the seller's copyright and the seller's legal links, none of which is per-account. A
#: slot nothing could ever bind is a control in a picker that does nothing.
_FOOTER_SLOTS: tuple[SlotSpec, ...] = ()

CAMPAIGN_SHELL_SLOTS = {
    CAMPAIGN_SHELL_HEADER: _HEADER_SLOTS,
    CAMPAIGN_SHELL_FOOTER: _FOOTER_SLOTS,
}


def campaign_shell_slots(role: str) -> tuple[SlotSpec, ...]:
    """The ruled slots for one shell role. Raises for a role that is not a shell."""
    try:
        return CAMPAIGN_SHELL_SLOTS[role]
    except KeyError:
        raise ValueError(
            f"{role!r} is not a campaign shell role; expected one of "
            f"{', '.join(CAMPAIGN_SHELL_ROLES)}"
        ) from None


# --------------------------------------------------------------------------- #
# the seller's legal links, from evidence
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class LegalLink:
    """One of the seller's legal pages, as their own site links to it."""

    kind: str
    label: str
    href: str


#: What counts as a legal page, in the order a footer lists them. Matched against the link's
#: path and its own words — never against a guess about a url we never saw.
_LEGAL_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    ("privacy", "Privacy", re.compile(r"privacy", re.I)),
    ("terms", "Terms", re.compile(r"terms|conditions|tos\b", re.I)),
)

#: An honest cap. A footer that discovered nine "legal" links found a nav, not a legal block.
MAX_LEGAL_LINKS = len(_LEGAL_PATTERNS)


def discover_legal_links(evidence: Iterable[tuple[str, str]]) -> tuple[LegalLink, ...]:
    """The seller's privacy/terms links, read out of markup their own site produced.

    ``evidence`` is ``(html, base_url)`` pairs — harvested footer/nav fragments, whose anchors are
    the client's actual legal links. Relative hrefs are resolved against the page they came from,
    because a campaign page is served from OUR origin and a bare ``/privacy`` on it would 404;
    an href that cannot be made absolute is DROPPED rather than shipped broken.

    Finds nothing → returns nothing, and the footer is composed without a legal block. That is
    the empty-and-clean answer R23-2 asks for, not a failure.
    """
    found: dict[str, LegalLink] = {}
    for html, base_url in evidence:
        if not html:
            continue
        try:
            tree = LexborHTMLParser(html)
        except Exception:  # pragma: no cover - lexbor does not raise on real markup
            continue
        for node in tree.css("a"):
            href = (node.attributes.get("href") or "").strip()
            if not href:
                continue
            words = " ".join((node.text(deep=True) or "").split())
            absolute = _absolute_http_href(href, base_url)
            if absolute is None:
                continue
            for kind, label, pattern in _LEGAL_PATTERNS:
                if kind in found:
                    continue
                # The PATH, not the whole url: a link to `https://privacy.example/about` is not a
                # privacy policy, and the host is where that false positive lives.
                path = urlsplit(absolute).path or ""
                if pattern.search(path) or pattern.search(words):
                    found[kind] = LegalLink(kind=kind, label=words[:40] or label, href=absolute)
                    break
    return tuple(found[kind] for kind, _label, _pattern in _LEGAL_PATTERNS if kind in found)


def _absolute_http_href(href: str, base_url: str) -> str | None:
    """One anchor's target as an absolute http(s) url, or ``None`` if it cannot be one."""
    candidate = urljoin(base_url or "", href) if not href.lower().startswith("http") else href
    parts = urlsplit(candidate)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    return candidate


# --------------------------------------------------------------------------- #
# the composition
# --------------------------------------------------------------------------- #


def compose_campaign_header(
    *,
    seller_name: str,
    seller_logo_asset_id: str,
    cobrand_asset_id: str = COBRAND_PLACEHOLDER_ASSET_ID,
    prepared_for: str = DEFAULT_PREPARED_FOR,
    cta_label: str = DEFAULT_CTA_LABEL,
    cta_href: str = DEFAULT_CTA_HREF,
) -> str:
    """The header, in the engine's constrained-HTML wire format. One strip, one action.

    A campaign header is a STRIP, not a hero: one row, both marks at a capped height, the
    prepared-for line, and the CTA at the far end. Styling is the kit's own theme tokens and the
    platform's geometry utilities, so the shell reads as the seller's chrome beside a cloned
    section rather than as something a tool bolted on.
    """
    return (
        f'<section id="{CAMPAIGN_SHELL_SECTION_IDS[CAMPAIGN_SHELL_HEADER]}" '
        'class="w-full border-b border-border bg-light">'
        '<div class="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 '
        'px-6 py-4">'
        '<div class="flex items-center gap-3">'
        f'<img data-asset="{escape(seller_logo_asset_id, quote=True)}" '
        f'alt="{escape(seller_name, quote=True)}" '
        f'class="{MARK_SELLER_MARK} max-h-8 w-auto">'
        # The co-brand mark. `max-h` caps a real logo and cannot inflate the 1×1 default, so the
        # unbound header is a header with one mark on it and no hole where a second would go.
        f'<img data-asset="{escape(cobrand_asset_id, quote=True)}" alt="" '
        f'class="{MARK_TARGET_LOGO} max-h-8 w-auto">'
        '<p class="text-sm text-muted">'
        f"{escape(PREPARED_FOR_PREFIX)}"
        f'<span class="{MARK_PREPARED_FOR}">{escape(prepared_for)}</span>'
        "</p>"
        "</div>"
        f'<div data-href="{escape(cta_href, quote=True)}" '
        f'class="{MARK_CTA} inline-flex items-center rounded-md bg-primary px-5 py-2">'
        '<p class="text-sm font-semibold text-inverse">'
        f'<span class="{MARK_CTA_LABEL}">{escape(cta_label)}</span>'
        "</p>"
        "</div>"
        "</div></section>"
    )


def compose_campaign_footer(
    *,
    seller_name: str,
    seller_logo_asset_id: str,
    legal_links: Sequence[LegalLink] = (),
) -> str:
    """The footer: the seller's mark, their copyright, their legal links. Nothing else.

    **No year in the copyright.** A year would make the artifact's content-address change every
    January — a new fragment, unreleased, on every page that pins the old one — to say something
    no reader needs. A dated copyright that goes stale is worse than an undated one.

    With no legal links the block is simply absent (R23-2's "empty-and-clean"): no empty bullet
    separator, no "Privacy" that goes nowhere.
    """
    legal = ""
    if legal_links:
        # Each legal link is a CONTAINER-link, not an inline anchor inside a paragraph. Inline
        # rich text keeps `class` on a `<span>` and DROPS it on an `<a>` (`inline.rs`'s attribute
        # allowlist), so an inline legal link would reach the mint carrying no marker and the
        # shape gate would read it as an escape route. Found on the first live walk; this shape
        # is the reason the footer's links survive their own gate.
        anchors = "".join(
            f'<div data-href="{escape(link.href, quote=True)}" '
            f'class="{MARK_LEGAL} inline-flex items-center">'
            f'<p class="text-xs text-muted">{escape(link.label)}</p></div>'
            for link in legal_links[:MAX_LEGAL_LINKS]
        )
        legal = f'<div class="flex flex-wrap items-center gap-4">{anchors}</div>'
    return (
        f'<section id="{CAMPAIGN_SHELL_SECTION_IDS[CAMPAIGN_SHELL_FOOTER]}" '
        'class="w-full border-t border-border bg-light">'
        '<div class="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-4 '
        'px-6 py-6">'
        f'<img data-asset="{escape(seller_logo_asset_id, quote=True)}" '
        f'alt="{escape(seller_name, quote=True)}" '
        f'class="{MARK_SELLER_MARK} max-h-6 w-auto">'
        f'<p class="text-xs text-muted">&copy; {escape(seller_name)}. '
        "All rights reserved.</p>"
        f"{legal}"
        "</div></section>"
    )


# --------------------------------------------------------------------------- #
# the no-escape-route rule (ruling R23-3)
# --------------------------------------------------------------------------- #

#: Elements a shell may not contain at all. A ``<nav>`` is a menu by declaration; a ``<button>``
#: or a ``<select>`` is a second action competing with the one the page is for.
_FORBIDDEN_SHELL_ELEMENTS = ("nav", "button", "select", "menu")


def assert_campaign_shell_shape(role: str, html: str) -> None:
    """Refuse a shell that offers a visitor anywhere to go except the one place it is for.

    Structural, not advisory (ruling R23-3), and it runs at the MINT rather than in the composer
    — so it holds for markup this module composed and for markup anything else ever hands the
    same door. The header carries exactly one anchor and that anchor is the CTA; the footer's
    anchors are all legal links and there are at most two; neither carries a nav landmark, a menu
    or a second control.

    Raises :class:`FragmentRefused` with ``fragment.shell_escape_route``; returns nothing when
    the shape is lawful.
    """
    if role not in CAMPAIGN_SHELL_ROLES:
        raise ValueError(
            f"{role!r} is not a campaign shell role; expected one of "
            f"{', '.join(CAMPAIGN_SHELL_ROLES)}"
        )
    tree = LexborHTMLParser(html)
    body = tree.body
    if body is None:
        raise FragmentRefused(
            "fragment.shell_escape_route", f"the composed {role} has no markup to check"
        )
    for name in _FORBIDDEN_SHELL_ELEMENTS:
        if body.css_first(name) is not None:
            raise FragmentRefused(
                "fragment.shell_escape_route",
                f"a campaign shell carries no <{name}>: every navigation link on an ABM page is "
                "a way off it. The header holds one call to action and the footer holds the "
                "seller's legal links; nothing else.",
                reference=name,
            )

    anchors = body.css("a")
    marker = MARK_CTA if role == CAMPAIGN_SHELL_HEADER else MARK_LEGAL
    for anchor in anchors:
        classes = set((anchor.attributes.get("class") or "").split())
        if marker not in classes:
            href = (anchor.attributes.get("href") or "").strip()
            raise FragmentRefused(
                "fragment.shell_escape_route",
                f"the composed {role} links to {href or '(no href)'!r}, which is not "
                + (
                    "its one call to action"
                    if role == CAMPAIGN_SHELL_HEADER
                    else "one of the seller's legal links"
                )
                + ". Every extra link on an ABM page is a way off it.",
                reference=href or None,
            )
    if role == CAMPAIGN_SHELL_HEADER and len(anchors) != 1:
        raise FragmentRefused(
            "fragment.shell_escape_route",
            f"a campaign header carries exactly ONE call to action; this one carries "
            f"{len(anchors)}.",
        )
    if role == CAMPAIGN_SHELL_FOOTER and len(anchors) > MAX_LEGAL_LINKS:
        raise FragmentRefused(
            "fragment.shell_escape_route",
            f"a campaign footer carries at most {MAX_LEGAL_LINKS} legal links; this one carries "
            f"{len(anchors)}.",
        )


__all__ = [
    "CAMPAIGN_SHELL_FOOTER",
    "CAMPAIGN_SHELL_HEADER",
    "CAMPAIGN_SHELL_MARKER_CLASSES",
    "CAMPAIGN_SHELL_ROLES",
    "CAMPAIGN_SHELL_SECTION_IDS",
    "CAMPAIGN_SHELL_SLOTS",
    "CAMPAIGN_SHELL_SOURCE_URL",
    "COBRAND_PLACEHOLDER_ASSET_ID",
    "COBRAND_PLACEHOLDER_MEDIA_TYPE",
    "COBRAND_PLACEHOLDER_PNG",
    "COMPOSED_CAMPAIGN_SHELL",
    "DEFAULT_CTA_HREF",
    "DEFAULT_CTA_LABEL",
    "DEFAULT_PREPARED_FOR",
    "MARK_CTA",
    "MARK_CTA_LABEL",
    "MARK_LEGAL",
    "MARK_PREPARED_FOR",
    "MARK_SELLER_MARK",
    "MARK_TARGET_LOGO",
    "MAX_LEGAL_LINKS",
    "PREPARED_FOR_PREFIX",
    "LegalLink",
    "assert_campaign_shell_shape",
    "campaign_shell_slots",
    "compose_campaign_footer",
    "compose_campaign_header",
    "discover_legal_links",
]
