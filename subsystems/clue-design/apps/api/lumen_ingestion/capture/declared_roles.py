"""Declared CSS custom properties → semantic role assignments (clone-fidelity F0.3).

Why this module exists
----------------------
On a Webflow / Framer / shadcn-class site the palette is not something to be *inferred* —
it is **stated**::

    :root {
      --base-color-brand--green: #30d8a7;
      --base-color-background--page: #fbfbf9;
    }

Until F0.3 we threw that statement away: every custom property became one more anonymous
weight-3.0 swatch, and the kit's brand color came out of a clustering heuristic that could
just as easily crown a hero-section purple used three times. The declaration is the highest
fidelity signal the page carries, so it is now applied as a DIRECT role assignment (basis
``declared``, pointer ``custom-prop:<name>``, confidence :data:`DECLARED_ROLE_CONFIDENCE`)
that outranks the clustered candidate. Properties whose names carry no role word keep
exactly today's weighted-evidence behaviour.

The rules, in one place
-----------------------
**Names decide, never values.** A hex is never allowed to trigger a role by itself: a
property called ``--base-color-neutral--white`` states a color, not a job, and a page whose
brand happens to be white must reach that conclusion through evidence like any other. Colour
WORDS in a name (``green``, ``violet``, ``navy``) are likewise inert — ``--violet`` maps to
nothing, ``--brand-violet`` maps to the brand because of ``brand``.

**Strong words name a role; weak words only break a tie.** ``primary``/``secondary`` are the
weak pair, because they are qualifiers at least as often as they are roles: ``--color-primary``
is a brand color, but ``--text-primary`` is the primary TEXT color, not the brand. So a name
is read for strong words first (``background``/``text``/``brand``/``accent`` and friends) and
only falls back to the weak pair when it carries none.

**A name that mixes two strong families states nothing we can trust.** ``--body-bg`` reads as
both text and surface; refusing is honest, and the property still reaches the clusterer as
ordinary evidence.

**A variant is not the anchor.** ``--background-hover``, ``--text-muted``, ``--border-color``
and ``--brand-500`` all describe a *derivative* of a role. They are disqualified outright,
which is what keeps a pale 100-step tint from being crowned the brand color.

The four roles here are exactly the anchors ``normalizer.roles.assign_light_roles`` derives
everything else from — this module cannot mint a role the normalizer does not already own.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass

#: The anchor roles the normalizer assigns from evidence. Everything else in the kit's
#: semantic color set is derived from these four, so these are the only roles a declaration
#: is allowed to claim.
ROLE_SURFACE_PAGE = "surface.page"
ROLE_TEXT_PRIMARY = "text.primary"
ROLE_SURFACE_BRAND = "surface.brand"
ROLE_SURFACE_ACCENT = "surface.accent"

DECLARED_ROLES = (
    ROLE_SURFACE_PAGE,
    ROLE_TEXT_PRIMARY,
    ROLE_SURFACE_BRAND,
    ROLE_SURFACE_ACCENT,
)

#: (The confidence a declared role carries lives with the rest of the basis vocabulary, in
#: ``normalizer.roles.DECLARED_ROLE_CONFIDENCE`` — capture states the declaration, the
#: normalizer decides what a basis is worth.)

#: Words that NAME a role. First column is the word as it appears in a property name.
_STRONG_WORDS: dict[str, str] = {
    # page surface
    "background": ROLE_SURFACE_PAGE,
    "backgrounds": ROLE_SURFACE_PAGE,
    "backdrop": ROLE_SURFACE_PAGE,
    "bg": ROLE_SURFACE_PAGE,
    "surface": ROLE_SURFACE_PAGE,
    "page": ROLE_SURFACE_PAGE,
    "canvas": ROLE_SURFACE_PAGE,
    # primary text
    "text": ROLE_TEXT_PRIMARY,
    "foreground": ROLE_TEXT_PRIMARY,
    "fg": ROLE_TEXT_PRIMARY,
    "ink": ROLE_TEXT_PRIMARY,
    "copy": ROLE_TEXT_PRIMARY,
    "body": ROLE_TEXT_PRIMARY,
    # brand
    "brand": ROLE_SURFACE_BRAND,
    # accent
    "accent": ROLE_SURFACE_ACCENT,
}

#: Words that mean a role only when the name carries no strong word (see module docstring).
_WEAK_WORDS: dict[str, str] = {
    "primary": ROLE_SURFACE_BRAND,
    "secondary": ROLE_SURFACE_ACCENT,
}

#: Any of these in a name means "a derivative of a role", not the role itself.
_DISQUALIFYING_WORDS = frozenset(
    {
        # interaction states — F0.3 captures those as StateStyle evidence instead
        "hover",
        "focus",
        "active",
        "disabled",
        "visited",
        "pressed",
        "checked",
        "selected",
        # tonal variants
        "muted",
        "subtle",
        "faint",
        "soft",
        "weak",
        "strong",
        "inverse",
        "inverted",
        "invert",
        "contrast",
        "alt",
        "alternate",
        "hint",
        "placeholder",
        "disabled",
        "dim",
        # a DARK variant is the other colorway's anchor, not this one's
        "dark",
        "night",
        # not a fill at all
        "border",
        "outline",
        "ring",
        "stroke",
        "divider",
        "shadow",
        "overlay",
        "gradient",
        "scrollbar",
        "selection",
        "highlight",
        "link",
        # semantic status colors are their own family
        "error",
        "warning",
        "success",
        "danger",
        "info",
        "destructive",
    }
)

#: Words that hint "this is the LIGHT page surface" — used only to rank competing
#: page-surface declarations, never to create a match (the brief's `white`/`light` hint).
_LIGHT_HINT_WORDS = frozenset({"white", "light", "lightest", "paper"})


def _words(property_name: str) -> list[str]:
    """The name's words, lowercased. Splits kebab, snake, and camel boundaries."""
    text = property_name.lstrip("-")
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "-", text)
    return [word for word in re.split(r"[^A-Za-z0-9]+", text.lower()) if word]


def role_for_property_name(property_name: str) -> str | None:
    """The anchor role this custom-property NAME declares, or ``None``.

    ``None`` is the common and correct answer — a property we cannot read a role off of is
    not a failure, it is a property that keeps today's weighted-evidence behaviour.
    """
    words = _words(property_name)
    if not words:
        return None
    if any(word in _DISQUALIFYING_WORDS for word in words):
        return None
    # A bare number in the name is a ramp step (`--brand-500`, `--surface-2`): a tint of a
    # role, not the role. Refusing these is what stops a 100-step wash winning the brand.
    if any(word.isdigit() for word in words):
        return None

    strong = {_STRONG_WORDS[word] for word in words if word in _STRONG_WORDS}
    if len(strong) == 1:
        return next(iter(strong))
    if strong:
        return None  # mixes two role families — states nothing we can trust
    weak = {_WEAK_WORDS[word] for word in words if word in _WEAK_WORDS}
    if len(weak) == 1:
        return next(iter(weak))
    return None


@dataclass(frozen=True)
class DeclaredRole:
    """One resolved role declaration: the role, the property that stated it, the hex."""

    role: str
    property_name: str
    value: str

    @property
    def pointer(self) -> str:
        """The provenance string the ingestion report and kit carry."""
        return f"custom-prop:{self.property_name}"


def _rank(property_name: str, role: str) -> tuple[int, int, str]:
    """Sort key deciding which of several declarations of one role is THE declaration.

    Least-qualified name first (``--background`` beats ``--background-secondary-area``),
    with the light hint preferred for the page surface, then the name itself so the choice
    is deterministic across runs and across stylesheet orderings.
    """
    words = _words(property_name)
    hinted = 0
    if role == ROLE_SURFACE_PAGE and any(word in _LIGHT_HINT_WORDS for word in words):
        hinted = -1
    return (hinted, len(words), property_name)


def declared_roles(
    custom_props: dict[str, str],
    resolve_color: Callable[[str], str | None],
) -> list[DeclaredRole]:
    """Read the role declarations out of a page's custom properties.

    ``resolve_color`` is the caller's color parser (``parse.parse_color_value`` bound to the
    page's own property table), so an alias chain — ``--color-primary: var(--green)`` —
    resolves exactly the way every other color on the page does, cycles and all.

    Returns at most one declaration per role, ordered by :data:`DECLARED_ROLES`.
    """
    candidates: dict[str, list[tuple[tuple[int, int, str], str, str]]] = {}
    for name, raw in custom_props.items():
        role = role_for_property_name(name)
        if role is None:
            continue
        hex_value = resolve_color(raw)
        if not hex_value:
            continue
        candidates.setdefault(role, []).append((_rank(name, role), name, hex_value))

    out: list[DeclaredRole] = []
    for role in DECLARED_ROLES:
        entries = candidates.get(role)
        if not entries:
            continue
        _, name, hex_value = min(entries)
        out.append(DeclaredRole(role=role, property_name=name, value=hex_value))
    return out


def pattern_table() -> Iterable[tuple[str, str, str]]:
    """The name→role table, flattened for documentation and report surfaces.

    Yields ``(word, strength, role)``. Exists so the table can be shown to a human without
    anyone re-typing it into a doc that then drifts.
    """
    for word, role in sorted(_STRONG_WORDS.items()):
        yield word, "strong", role
    for word, role in sorted(_WEAK_WORDS.items()):
        yield word, "weak", role
