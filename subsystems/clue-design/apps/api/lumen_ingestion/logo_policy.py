"""W1.6 — the logo placement policy vocabulary.

THE DEFECT (Cursor pilot, `.context/ref-ads-pilot-cursor-report.md` §6/§9.5).
The references demanded a reversed wordmark on a dark field, the kit's logo
policy said `allowed_backgrounds: ["surface.page", "surface.card"]`, and there
was no way for the kit to say otherwise — so the agent placed the reversed mark
on `$surface.inverse`, took the `LUMB0810` diagnostic, and recorded the
deviation rather than hiding it. The vocabulary, not the agent, was the problem.

WHAT `allowed_backgrounds` IS. A `Vec<String>` on the Rust `LogoAsset`
(`crates/lumen-core/src/brand.rs`, the `LogoAsset` struct): a flat list of
colour-token paths, compared by exact string equality against the nearest
brand-background token above the logo node. It is SLOT-level, not variant-level
— one list per `primary`/`mark`/`wordmark` slot, shared by every variant in it.
An empty list disables the check entirely.

WHAT THIS MODULE DOES. It is the one place that decides which surfaces a logo
slot may sit on, given the colour modes of the variants the slot actually holds.
Both producers call it, so ingestion and human curation cannot drift:

- `normalizer.emit.BrandKitBuilder.add_logos` — the ingestion path;
- `lumen_api.main.set_brand_kit_logo` — the human curation path.

THE RULE. The light surfaces are always allowed; that is the baseline every kit
has always carried, and keeping it means this can never introduce a diagnostic
where none fired before. A slot that holds a REVERSED or LIGHT variant
additionally allows the dark surfaces, because a reversed mark exists precisely
to sit on an inverse or brand field — that is the allowance the Cursor pilot
could not express. `surface.brand` rides with `surface.inverse` because it is
the same placement for the same reason: a dark field the light mark belongs on,
and LUMB0810 fired there for the identical reason it fired on inverse.

Net effect: strictly more permissive than before, never less. LUMB0810 stays
advisory (founder ruling D5) and blocks nothing — see
`tests/test_logo_policy.py` for the pins on that.

KNOWN LIMIT (not fixable from Python). Because the policy is slot-level, a slot
holding both a full-colour and a reversed variant permits EITHER on EITHER
surface. Saying "the reversed variant may go on inverse, the full-colour one may
not" needs a per-variant field on the Rust `LogoVariant` struct plus a change to
the check in `validate_scene_brand_governance` — an engine change, deliberately
out of scope here.
"""

from __future__ import annotations

from collections.abc import Iterable

#: Surfaces a logo may always sit on. The pre-W1.6 default, unchanged.
LIGHT_SURFACES: tuple[str, ...] = ("surface.page", "surface.card")

#: Surfaces a slot may additionally sit on once it holds a light/reversed variant.
DARK_SURFACES: tuple[str, ...] = ("surface.inverse", "surface.brand")

#: The `LogoColorMode` values that mean "this mark is drawn light, for dark fields".
#: Mirrors the Rust enum's wire values (`full_color | one_color | reversed | dark | light`).
INVERSE_CAPABLE_COLOR_MODES: frozenset[str] = frozenset({"reversed", "light"})


def allows_inverse_surfaces(color_modes: Iterable[str | None]) -> bool:
    """True when at least one variant is drawn for a dark field."""
    return any(
        (mode or "").strip().lower() in INVERSE_CAPABLE_COLOR_MODES for mode in color_modes
    )


def allowed_backgrounds_for(color_modes: Iterable[str | None]) -> list[str]:
    """The slot's `allowed_backgrounds`, given the colour modes of its variants.

    Order is stable (page, card, inverse, brand) so kit serializations stay
    comparable and golden fixtures do not churn.
    """
    modes = list(color_modes)
    allowed = list(LIGHT_SURFACES)
    if allows_inverse_surfaces(modes):
        allowed.extend(DARK_SURFACES)
    return allowed


def extend_allowed_backgrounds(
    existing: Iterable[str] | None, color_modes: Iterable[str | None]
) -> list[str]:
    """Widen a slot's existing policy for the variants now in it, never narrowing it.

    Used by the human curation path, where a slot already carries a policy some
    earlier pass chose. Promoting a reversed logo into a slot ingested as
    light-only must not leave the kit saying that mark may never sit on a dark
    field — but neither may it silently drop an allowance somebody added.

    An EMPTY existing list is left empty: in the engine an empty list means "do
    not check this slot at all", and quietly turning a slot's check on is a
    behaviour change this module has no business making.
    """
    current = [entry for entry in (existing or []) if isinstance(entry, str)]
    if not current:
        return current
    if not allows_inverse_surfaces(color_modes):
        return current
    return current + [surface for surface in DARK_SURFACES if surface not in current]
