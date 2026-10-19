"""What an ABM page is made of (clone-fidelity F4.2, rulings R24-1…R24-6).

F4.1 minted the shells. This module is the **assembly contract**: the law an ABM page obeys,
written once, so the walk that builds the page and anything that later judges it read the same
rules rather than two copies that drift.

The four rules, as code rather than as prompt advice:

* **Chrome is the campaign shells, never the cloned nav.** :data:`ESCAPE_ROUTE_ROLES` names the
  harvested roles that may not be pinned on an ABM page — every link in a nav (and in a site
  footer) is a way off the one page written for this account. The shells' own roles are not in
  it: they ARE the answer. There is deliberately no fallback: a workspace with no released shells
  gets a refusal naming ``mint_campaign_shells``, never the client's real navigation.
* **Personalization is MARKER-BOUND, never baked** (ruling R24-2). An assembled page is a
  TEMPLATE — one document whose slots hold ``{{account.name}}`` / ``{{account.logo}}`` /
  ``{{account.domain}}``, which the F1.4 derive path (``derive.rs``'s ``apply_fragment_slots``)
  substitutes per account. :func:`account_slot_binding` is the one place that knows the single
  awkward truth of that mechanism: a template value rides as ``text`` **whatever the slot's
  kind**, because ``{{account.logo}}`` is not an asset id and only the derive can turn it into
  one.
* **New sections are named** (ruling R24-3). Every section the recipe composes carries an
  ``abm_`` id, so a reviewer — human or machine — can tell a new ABM band from cloned chrome
  without guessing. The engine's id charset has no ``-``, so the plan's ``abm-*`` family is
  spelled ``abm_``. Token-lawfulness of those sections is the EXISTING Grammar Audit machinery;
  nothing here re-checks it.
* **No relationship claims** (ruling R24-5). The seller has not met this account yet.
  :data:`RELATIONSHIP_CLAIM_WORDS` is the vocabulary the prompt law forbids and the shells'
  static text is tested against. It is a review/test vocabulary, NOT a runtime filter over
  agent-authored copy — a page is judged by the rubric and the prompt, not by a word list
  quietly rewriting somebody's sentence.

**The shell picker is an interim law** (T23 review finding I6). Shells carry no supersession
marker, so a kit whose logo or name changed mints a second, genuinely different header and the
old one stays approved. Until the founder rules shell lineage, :func:`newest_released_shell`
picks the newest deterministically **and returns the siblings it stepped over**, so the walk can
say a superseded-looking one exists rather than choosing in silence.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from clue_design.web_fragments import fragment_has_kit_binding

from .campaign_shell import (
    CAMPAIGN_SHELL_FOOTER,
    CAMPAIGN_SHELL_HEADER,
    COMPOSED_CAMPAIGN_SHELL,
)
# The engine's serde tag per artifact slot kind, imported rather than restated: the authored
# path (`_tagged_slot_values`) reads the same map, and two copies of "an image slot binds an
# asset" is exactly the drift that would let a marker ride under the wrong tag.
from .slots import SLOT_KIND_TO_NODE_TAG

JsonObject = dict[str, Any]


class AbmAssemblyRefused(ValueError):
    """An ABM assembly rule was broken. ``code`` is the stable ``abm.*`` label the tool reports.

    Same shape as :class:`~lumen_api.fragments.refs.FragmentRefused` and for the same reason: a
    refusal an agent can act on names WHICH rule and WHICH thing, not that something was wrong.
    """

    def __init__(self, code: str, message: str, *, reference: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.reference = reference


# --------------------------------------------------------------------------- #
# chrome: what may and may not wear an ABM page
# --------------------------------------------------------------------------- #

#: Harvested roles that are escape routes on an ABM page (ruling R24-1). The cloned nav is the
#: obvious one; the cloned site footer is the same defect wearing different clothes — a footer
#: link column is a nav that sits at the bottom. Both are correct on a recreated homepage and
#: wrong here, which is exactly why the rule is about the PAGE KIND and not about the artifact.
#:
#: The shells' own roles (``campaign_header`` / ``campaign_footer``) are deliberately absent:
#: they were composed to hold exactly one anchor and the F4.1 shape gate refuses them otherwise.
ESCAPE_ROUTE_ROLES: frozenset[str] = frozenset({"nav", "footer"})


def is_escape_route_role(section_role: Any) -> bool:
    """Would pinning a clone of this role put a way off the page onto an ABM page?"""
    return str(section_role or "").strip().lower() in ESCAPE_ROUTE_ROLES


def newest_released_shell(
    sections: Sequence[Mapping[str, Any]], role: str, *, kit_id: str | None = None
) -> tuple[JsonObject | None, list[str]]:
    """``(the shell to pin, the released siblings it stepped over)`` for one shell role.

    ``sections`` is the discovery listing (approved rows only). A row counts as a shell when it
    carries the ``composed`` marker AND the role — the marker decides, never the role name alone,
    because ``section_role`` is free text and a harvested band could in principle carry it.

    ``kit_id`` scopes the pick to one brand, and a caller that knows the turn's kit should always
    pass it: in a multi-brand workspace, brand B's shell is brand B's chrome, and wearing it on
    brand A's account page dresses the page as the wrong company (the same defect T23's fix round
    closed for the legal-link evidence read). Left ``None`` the pick is workspace-wide, which is
    right only where there is one brand — so the caller that leaves it out owes the reader a note.

    Newest first by ``(created_at, fragment_id)``: the timestamp is the intent and the id is the
    tie-break, so two shells minted in the same second still pick the same one on every call. A
    picker whose answer depends on row order is a picker that changes the page for no reason.
    """
    wanted_kit = str(kit_id).strip() if kit_id else None
    shells = [
        dict(row)
        for row in sections
        if str((row or {}).get("composed") or "") == COMPOSED_CAMPAIGN_SHELL
        and str((row or {}).get("section_role") or "") == role
        and (wanted_kit is None or fragment_has_kit_binding(dict(row or {}), wanted_kit))
    ]
    if not shells:
        return None, []
    shells.sort(
        key=lambda row: (str(row.get("created_at") or ""), str(row.get("fragment_id") or "")),
        reverse=True,
    )
    return shells[0], [str(row["fragment_id"]) for row in shells[1:]]


# --------------------------------------------------------------------------- #
# personalization: the account markers the F1.4 derive substitutes
# --------------------------------------------------------------------------- #

#: The three account markers the F1.4 derive substitutes. NOT a guarantee that every account
#: carries all three (fix-round M2): ``account_values()`` (``main.py``) always builds ``name``,
#: but emits ``domain`` only when the account has one and ``logo`` only when a logo asset is
#: bound — an unbound marker leaves the artifact's own fallback, reported in the derive's
#: coverage, which is exactly the empty-logo-is-correct behaviour. An account's own ``data``
#: entries reach the derive as ``account.<key>`` too — allowed, just not promised.
ACCOUNT_NAME_MARKER = "{{account.name}}"
ACCOUNT_DOMAIN_MARKER = "{{account.domain}}"
ACCOUNT_LOGO_MARKER = "{{account.logo}}"
ACCOUNT_MARKERS: tuple[str, ...] = (
    ACCOUNT_NAME_MARKER,
    ACCOUNT_DOMAIN_MARKER,
    ACCOUNT_LOGO_MARKER,
)

#: The namespace the derive can substitute into a fragment slot at all. Anything else is carried
#: onto the page verbatim (or, out of bounds, drops the node's whole slot map — ``LUMW0607``),
#: which is a template marker printed to a visitor.
ACCOUNT_NAMESPACE = "account."

#: ``{{ account.name }}`` with or without the padding. Deliberately narrow: the engine's own
#: ``substitute_vars`` grammar, not a general template language.
_MARKER_RE = re.compile(r"\{\{\s*([A-Za-z0-9_.]+)\s*\}\}")

#: Per-account slots on each shell, and what they mean. The header's two are RULED (R23-2): the
#: prepared-for line takes the account's display name and the co-brand mark takes its logo. The
#: CTA pair is the CAMPAIGN's, not the account's, so it is bound only when a caller names it.
#: The footer has none — nothing in it is per-account.
SHELL_ACCOUNT_SLOT_MARKERS: dict[str, dict[str, str]] = {
    CAMPAIGN_SHELL_HEADER: {
        "prepared_for": ACCOUNT_NAME_MARKER,
        "target_logo": ACCOUNT_LOGO_MARKER,
    },
    CAMPAIGN_SHELL_FOOTER: {},
}

#: The shells' slot kinds, from the F4.1 contract, so a binding is tagged without opening the
#: artifact. (``campaign_shell_slots`` is the authority; this mirrors the two we bind.)
_SHELL_SLOT_KINDS: dict[str, str] = {
    "prepared_for": "text",
    "target_logo": "image",
    "cta_href": "href",
    "cta_label": "text",
}


#: The whole ``{{account.…}}`` occurrence, padding and all — the SUBSTRING the delivery guard
#: reports, so a refusal quotes what a visitor would have seen rather than a normalized name.
_ACCOUNT_MARKER_RE = re.compile(r"\{\{\s*account\.[A-Za-z0-9_.]+\s*\}\}")


def template_markers(value: Any) -> tuple[str, ...]:
    """Every ``{{name}}`` in a value, in the order it appears. Non-strings have none."""
    if not isinstance(value, str):
        return ()
    return tuple(match.group(1) for match in _MARKER_RE.finditer(value))


def unresolved_account_markers(html: Any) -> tuple[str, ...]:
    """Every account marker still standing in rendered HTML, deduped, in order (ruling R25-7).

    The delivery guard: an ABM page is a TEMPLATE, and an UN-derived one renders
    ``{{account.name}}`` to whoever opens the URL (reproduced by the T24 review, finding M3).

    Deliberately narrow — ``account.`` and nothing wider. A cloned section is somebody's real
    markup, and a site built on a template engine can legitimately serve ``{{ price }}`` as
    static text; refusing on any pair of braces would refuse a faithful clone for being
    faithful. ``account.`` is OUR grammar (the namespace ``account_values()`` builds and
    ``substitute_vars`` consumes), so a match here is always our own unfinished work.
    """
    if not isinstance(html, str):
        return ()
    return tuple(dict.fromkeys(match.group(0) for match in _ACCOUNT_MARKER_RE.finditer(html)))


def account_slot_binding(key: str, kind: Any, value: Any) -> JsonObject:
    """One tagged fragment-slot value, marker-aware. The whole of R24-2's mechanism.

    The ordinary rule is the engine's: the artifact's slot KIND decides the tag, because an href
    and a paragraph are both JSON strings and only the manifest knows which is which.

    The ONE exception is a template marker, and it is not a convenience — it is the only shape
    that works. ``derive.rs``'s ``apply_fragment_slots`` looks at ``FragmentSlotValue::Text``
    and nothing else: an ``Asset``-tagged value is copied through untouched, deliberately ("the
    asset-id grammar has no room for ``{{…}}``"). So ``{{account.logo}}`` on an ``image`` slot
    must ride as **text**, and the derive turns it into an ``Asset`` when it resolves. Tagged as
    an asset it would be an invalid id that never binds — a silent nothing on every page.

    Refuses, by name, two things the derive cannot do:

    * a marker on a ``visibility`` slot (``abm.untemplatable_slot``) — a boolean has nothing to
      substitute, and the derive copies it through unchanged;
    * a marker outside ``account.*`` (``abm.unknown_marker``) — the derive's value namespace is
      exactly what ``account_values()`` builds, so anything else reaches a visitor as literal
      ``{{…}}``.
    """
    markers = template_markers(value)
    tag = SLOT_KIND_TO_NODE_TAG.get(str(kind))
    if tag is None:
        raise AbmAssemblyRefused(
            "abm.unknown_slot_kind",
            f"slot {key!r} has kind {kind!r}, which this build cannot bind.",
            reference=key,
        )
    if not markers:
        if tag == "visible":
            if not isinstance(value, bool):
                raise AbmAssemblyRefused(
                    "abm.bad_slot_value",
                    f"slot {key!r} controls whether part of the section is shown, so it takes "
                    "true or false.",
                    reference=key,
                )
            return {"visible": value}
        if not isinstance(value, str):
            expected = "an asset id" if tag == "asset" else "a string"
            raise AbmAssemblyRefused(
                "abm.bad_slot_value",
                f"slot {key!r} is a {kind} slot, so it takes {expected}.",
                reference=key,
            )
        return {tag: value}

    if tag == "visible":
        raise AbmAssemblyRefused(
            "abm.untemplatable_slot",
            f"slot {key!r} shows or hides part of the section, and a template marker cannot be "
            "substituted into a true/false value — the derive copies it through untouched, so "
            "the binding would never land. Bind true or false, or leave it alone.",
            reference=key,
        )
    unknown = [name for name in markers if not name.startswith(ACCOUNT_NAMESPACE)]
    if unknown:
        named = ", ".join(f"{{{{{name}}}}}" for name in unknown)
        raise AbmAssemblyRefused(
            "abm.unknown_marker",
            f"slot {key!r} carries {named}, which the account derive cannot substitute — its "
            "values are the account's own (" + ", ".join(ACCOUNT_MARKERS) + ", plus "
            "{{account.<key>}} for the account's data entries). An unknown marker is printed to "
            "the visitor as it stands.",
            reference=key,
        )
    # Text-tagged whatever the kind: see the docstring. This is the mechanism, not a shortcut.
    return {"text": value}


def shell_slot_bindings(
    role: str, *, cta_href: str | None = None, cta_label: str | None = None
) -> JsonObject:
    """The account bindings for one shell, as tagged fragment-slot values.

    The header's two ruled per-account slots always bind, because that IS what the shell is for:
    a header with an unbound ``prepared_for`` says "your team" on a page addressed to one named
    company. The CTA pair binds only when a caller names it — the call to action belongs to the
    campaign, and an unbound one falls back to the artifact's own (a page-local ``#contact``,
    which is never an escape route).
    """
    bindings: JsonObject = {
        key: account_slot_binding(key, _SHELL_SLOT_KINDS[key], marker)
        for key, marker in SHELL_ACCOUNT_SLOT_MARKERS.get(role, {}).items()
    }
    if cta_href is not None:
        bindings["cta_href"] = account_slot_binding("cta_href", "href", cta_href)
    if cta_label is not None:
        bindings["cta_label"] = account_slot_binding("cta_label", "text", cta_label)
    return bindings


# --------------------------------------------------------------------------- #
# the new-section convention (ruling R24-3)
# --------------------------------------------------------------------------- #

#: The plan writes the family ``abm-*``; the engine's node-id charset has no ``-``, so it is
#: spelled with an underscore. A prefix rather than a suffix so an id sorts and reads as what it
#: is at a glance.
ABM_SECTION_ID_PREFIX = "abm_"


def is_abm_section_id(section_id: Any) -> bool:
    """Is this the id of a section the ABM recipe composed (rather than a pinned clone)?"""
    return str(section_id or "").startswith(ABM_SECTION_ID_PREFIX)


# --------------------------------------------------------------------------- #
# relationship language (ruling R24-5) — the vocabulary, for review and for tests
# --------------------------------------------------------------------------- #

#: Words that claim a relationship the seller does not have with this account. The page is a
#: PITCH: the target has not bought, has not partnered, and is not a reference. The framing the
#: shells ship is "Prepared for <name>", and F4.1 made that structural (only the name is a slot).
#:
#: This list is the REVIEW vocabulary — the prompt law forbids these claims and the rubric asks
#: after them, and the shells' own static text is tested against it. It is deliberately NOT a
#: runtime filter over the author's copy: a seller's real customer logo wall on a cloned proof
#: band legitimately says "customers", and a word list cannot tell that from a lie. Judgement is
#: the reviewer's; the structure is the shell's.
RELATIONSHIP_CLAIM_WORDS: tuple[str, ...] = (
    "partner",
    "partnership",
    "customer",
    "trusted by",
    "client of",
    "working together with",
    "in collaboration with",
)


__all__ = [
    "ABM_SECTION_ID_PREFIX",
    "ACCOUNT_DOMAIN_MARKER",
    "ACCOUNT_LOGO_MARKER",
    "ACCOUNT_NAME_MARKER",
    "ACCOUNT_NAMESPACE",
    "ESCAPE_ROUTE_ROLES",
    "ACCOUNT_MARKERS",
    "RELATIONSHIP_CLAIM_WORDS",
    "SHELL_ACCOUNT_SLOT_MARKERS",
    "AbmAssemblyRefused",
    "account_slot_binding",
    "is_abm_section_id",
    "is_escape_route_role",
    "newest_released_shell",
    "shell_slot_bindings",
    "template_markers",
    "unresolved_account_markers",
]
