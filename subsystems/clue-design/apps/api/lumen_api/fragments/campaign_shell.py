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

* :func:`campaign_shell_shape_notes` is the Ploy campaign-shell rule (ruling R23-3), DEMOTED TO
  ADVICE by founder ruling R-F5-8. The header holds exactly one anchor and it is the CTA; the
  footer's anchors are all legal links; neither holds a ``<nav>``, a menu or a button. It runs at
  MINT, on the rendered subtree, so every caller — this module's own composer and any future one
  — is TOLD what it just put into a shell. It refuses nothing: links are structurally free.
  (:func:`assert_campaign_shell_shape` is the same detections in raising form, kept for the tests
  that pin them; no production path calls it.)
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
#: — named here for the reader (and the tests). The compose-time warnings about them are NOT
#: currently surfaced in the tool's report, so nothing filters on this set yet; if mint reporting
#: ever starts carrying render warnings, this is the set to exempt (fix-round M1).
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


#: What counts as a legal page, in the order a footer lists them, with the CANONICAL label each
#: ships under. The label is what the link IS, never the anchor's arbitrary words — a truncated
#: blog title is not a footer label (fix-round C1).
_LEGAL_KINDS: tuple[tuple[str, str], ...] = (
    ("privacy", "Privacy Policy"),
    ("terms", "Terms of Service"),
)

#: An honest cap. A footer that discovered nine "legal" links found a nav, not a legal block.
MAX_LEGAL_LINKS = len(_LEGAL_KINDS)

#: Splits a path segment into words: `privacy-policy` → {privacy, policy}.
_SEGMENT_WORDS = re.compile(r"[^a-z0-9]+")

#: The words that, inside ONE path segment, make "conditions" mean terms-and-conditions rather
#: than a medical conditions page ("Conditions we treat" was the review's live false positive).
_CONDITIONS_COMPANIONS = frozenset({"terms", "use", "service", "sale"})


def _classify_legal_path(path: str) -> str | None:
    """``privacy``/``terms`` when a WHOLE path segment says so, else ``None``.

    The path decides and the anchor's words never do (fix-round C1): the review broke the old
    substring match live — ``tos`` inside ``/photos``, "conditions" on ``/conditions/diabetes``,
    a blog title carrying the word "privacy". Segment words are exact, so none of those match,
    while ``/privacy-policy``, ``/legal/terms`` and ``/terms-and-conditions`` all still do.
    """
    for segment in (path or "").lower().split("/"):
        words = {word for word in _SEGMENT_WORDS.split(segment) if word}
        if "privacy" in words:
            return "privacy"
        if "terms" in words or "tos" in words:
            return "terms"
        if "conditions" in words and words & _CONDITIONS_COMPANIONS:
            return "terms"
    return None


def _same_site(candidate_host: str, base_host: str) -> bool:
    """Is this the seller's own host? Equal or related-by-subdomain, ``www.``/port disregarded.

    Deliberately suffix-of rather than a registrable-domain guess: without a public-suffix list,
    "last two labels" would call every ``*.co.uk`` pair the same site. Both directions are
    accepted on purpose — evidence on ``blog.seller.example`` may link ``seller.example/privacy``
    (parent-of), and apex evidence may link a subdomain (child-of). The residual acceptance that
    buys (fix-round N2, recorded): footer evidence served from ``shop.host.example`` whose
    author linked the LANDLORD's ``host.example/privacy`` ships it — reachable only through the
    seller's own footer linking its platform's policy, which is also what their live site shows.
    Ports are stripped (a same-host link with an explicit port is the same site, not a
    stranger); genuinely unrelated hosts are dropped and reported.
    """

    def _fold(host: str) -> str:
        bare = host.lower().rpartition("@")[2].partition(":")[0]
        return bare.removeprefix("www.")

    trimmed_candidate = _fold(candidate_host)
    trimmed_base = _fold(base_host)
    if not trimmed_candidate or not trimmed_base:
        return False
    return (
        trimmed_candidate == trimmed_base
        or trimmed_candidate.endswith("." + trimmed_base)
        or trimmed_base.endswith("." + trimmed_candidate)
    )


def discover_legal_links(
    evidence: Iterable[tuple[str, str]], *, dropped_foreign: list[str] | None = None
) -> tuple[LegalLink, ...]:
    """The seller's privacy/terms links, read out of markup their own site produced.

    ``evidence`` is ``(html, base_url)`` pairs — harvested footer fragments, whose anchors are
    the client's actual legal links. Relative hrefs are resolved against the page they came from,
    because a campaign page is served from OUR origin and a bare ``/privacy`` on it would 404;
    an href that cannot be made absolute is DROPPED rather than shipped broken.

    Three rules, each the fix for a live false positive (fix-round C1) — a false positive here is
    a gate-blessed escape route in the footer of every account page, so every rule errs empty:

    * **the path decides; the anchor's words never do** (:func:`_classify_legal_path`);
    * **the link must be the seller's own site** — same host as the evidence page or a subdomain
      of it. A legal-looking URL on a third party's host is dropped, and NAMED into
      ``dropped_foreign`` when the caller passes a list, because "found none" would be a lie
      about a footer whose policy is genuinely hosted elsewhere;
    * **the label is canonical** ("Privacy Policy" / "Terms of Service"), never anchor text.

    Finds nothing → returns nothing, and the footer is composed without a legal block. That is
    the empty-and-clean answer R23-2 asks for, not a failure.
    """
    found: dict[str, LegalLink] = {}
    labels = dict(_LEGAL_KINDS)
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
            absolute = _absolute_http_href(href, base_url)
            if absolute is None:
                continue
            kind = _classify_legal_path(urlsplit(absolute).path or "")
            if kind is None or kind in found:
                continue
            if not _same_site(urlsplit(absolute).netloc, urlsplit(base_url or "").netloc):
                if dropped_foreign is not None and absolute not in dropped_foreign:
                    dropped_foreign.append(absolute)
                continue
            found[kind] = LegalLink(kind=kind, label=labels[kind], href=absolute)
    return tuple(found[kind] for kind, _label in _LEGAL_KINDS if kind in found)


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
        # min-w-0 + flex-wrap (F4 wave F-5): a real bound logo made the strip 461px wide at a
        # 375px viewport — the marks group must be allowed to shrink and wrap, and the target
        # mark is width-capped so no fetched logo can widen the page sideways.
        '<div class="flex min-w-0 flex-wrap items-center gap-3">'
        f'<img data-asset="{escape(seller_logo_asset_id, quote=True)}" '
        f'alt="{escape(seller_name, quote=True)}" '
        f'class="{MARK_SELLER_MARK} max-h-8 w-auto">'
        # The co-brand mark. `max-h` caps a real logo and cannot inflate the 1×1 default, so the
        # unbound header is a header with one mark on it and no hole where a second would go.
        f'<img data-asset="{escape(cobrand_asset_id, quote=True)}" alt="" '
        f'class="{MARK_TARGET_LOGO} max-h-8 w-auto max-w-40">'
        '<p class="text-sm text-muted">'
        f"{escape(PREPARED_FOR_PREFIX)}"
        f'<span class="{MARK_PREPARED_FOR}">{escape(prepared_for)}</span>'
        "</p>"
        "</div>"
        # `rounded-button`, not a platform radius: the engine resolves it through the kit's
        # measured `radius.button` chain (theme.rs GEOMETRY_UTILITIES), so the Grammar Audit's
        # measured corner law governs the one control the shell has (fix-round I4 / R23-F4).
        # Container width and the strip's type size have no engine token to consume — those
        # stay platform defaults, stated here rather than silently.
        f'<div data-href="{escape(cta_href, quote=True)}" '
        f'class="{MARK_CTA} inline-flex items-center rounded-button bg-primary px-5 py-2">'
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
# the campaign-shell shape (ruling R23-3), as ADVICE (founder ruling R-F5-8)
# --------------------------------------------------------------------------- #
#
# FOUNDER RULING R-F5-8 (2026-09-02): links are structurally FREE. The shape below is the
# campaign-shell PRACTICE — one call to action in the header, the seller's legal links in the
# footer, no navigation landmark, menu or second control — and every detection it ever made is
# kept exactly as it was. What changed is the consequence: the findings are handed to the agent
# as sentences it can read and judge, not as a refusal that stops a mint. A shell carrying a nav
# is poor practice on a campaign page; it is not forbidden, and nothing here decides for the
# human whose page it is.

#: Elements the campaign-shell practice keeps out of a shell. A ``<nav>`` is a menu by
#: declaration; a ``<button>``, a ``<select>``, an ``<input>`` or a ``<textarea>`` is a second
#: control competing with the one action the page is for; and a ``<map>``/``<area>`` is a
#: navigation target ``css("a")`` does not count (fix-round M3).
_FORBIDDEN_SHELL_ELEMENTS = (
    "nav",
    "button",
    "select",
    "menu",
    "input",
    "textarea",
    "map",
    "area",
)


#: How every note below signs itself, so an agent reading one knows it is reading practice.
_R_F5_8 = "(R-F5-8: allowed, not recommended)"


def campaign_shell_shape_notes(role: str, html: str) -> list[str]:
    """What is off the campaign-shell practice in this markup, as plain sentences.

    The DETECTOR (ruling R23-3, unchanged): the header carries one anchor and that anchor is the
    CTA; the footer's anchors are all legal links and there are at most two; neither carries a
    nav landmark, a menu or a second control. It runs at the MINT rather than in the composer, so
    it sees markup this module composed and markup anything else ever hands the same door.

    The CONSEQUENCE (founder ruling R-F5-8, 2026-09-02): a finding is a note the caller hands
    back to the agent in ``advice``, never a refusal. Every sentence names what was found and
    what the practice is; none of them says the markup is forbidden, because it is not.

    Returns an empty list when the shape follows the practice. Raises :class:`ValueError` on a
    role that is not a shell role at all — that is a programming mistake, not a page's taste.
    """
    if role not in CAMPAIGN_SHELL_ROLES:
        raise ValueError(
            f"{role!r} is not a campaign shell role; expected one of "
            f"{', '.join(CAMPAIGN_SHELL_ROLES)}"
        )
    notes: list[str] = []
    tree = LexborHTMLParser(html)
    body = tree.body
    if body is None:
        return [f"the composed {role} has no markup to check against the campaign-shell practice"]
    for name in _FORBIDDEN_SHELL_ELEMENTS:
        if body.css_first(name) is not None:
            notes.append(
                f"the composed {role} carries a <{name}>; the campaign-shell practice is no "
                "navigation landmark, menu or second control — the header holds one call to "
                "action and the footer holds the seller's legal links. On a campaign page a "
                f"link that leaves is usually poor practice {_R_F5_8}"
            )

    anchors = body.css("a")
    # The COUNT first, then which links: the count is the sentence about the shape, and the
    # per-link ones are the detail underneath it.
    if role == CAMPAIGN_SHELL_HEADER and len(anchors) != 1:
        notes.append(
            f"the campaign header carries {len(anchors)} anchors; the campaign-shell practice "
            f"is one CTA {_R_F5_8}"
        )
    if role == CAMPAIGN_SHELL_FOOTER and len(anchors) > MAX_LEGAL_LINKS:
        notes.append(
            f"the campaign footer carries {len(anchors)} anchors; the campaign-shell practice "
            f"is at most {MAX_LEGAL_LINKS} legal links {_R_F5_8}"
        )
    marker = MARK_CTA if role == CAMPAIGN_SHELL_HEADER else MARK_LEGAL
    for anchor in anchors:
        classes = set((anchor.attributes.get("class") or "").split())
        if marker not in classes:
            href = (anchor.attributes.get("href") or "").strip()
            notes.append(
                f"the composed {role} links to {href or '(no href)'!r}, which is not "
                + (
                    "its one call to action"
                    if role == CAMPAIGN_SHELL_HEADER
                    else "one of the seller's legal links"
                )
                + f"; on a campaign page an extra link is a way off it, which is usually poor "
                f"practice {_R_F5_8}"
            )
    return notes


def assert_campaign_shell_shape(role: str, html: str) -> None:
    """The same findings in raising form — KEPT FOR TESTS AND CALLERS THAT WANT A HARD GATE.

    Since founder ruling R-F5-8 (2026-09-02) NO production path calls this: the mint doors read
    :func:`campaign_shell_shape_notes` and hand the sentences to the agent as advice. It survives
    because the detections deserve a form that can be asserted on in one line, and because
    deleting a public name is a separate decision from demoting a rule.

    Raises :class:`FragmentRefused` with ``fragment.shell_escape_route`` when the markup draws
    any note at all; returns nothing when it draws none.
    """
    notes = campaign_shell_shape_notes(role, html)
    if notes:
        raise FragmentRefused("fragment.shell_escape_route", " ".join(notes))


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
    "campaign_shell_shape_notes",
    "campaign_shell_slots",
    "compose_campaign_footer",
    "compose_campaign_header",
    "discover_legal_links",
]
