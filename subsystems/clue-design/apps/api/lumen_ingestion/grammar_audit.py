"""`BrandGrammarAudit@1` — the brand's GRAMMAR for sections the agent composes.

Clone-fidelity F2.4. F2.1–F2.3 give a page the client's own bands back verbatim;
this governs the rest — the sections the design trio still writes from scratch,
which is where a generated page reads as AI slop instead of as this brand.

It is a sibling of `BrandBrief@1` (`brief.py`) and rides the kit the same way:
one section of `brand_kit_json`, drafted with the kit version, reviewed with it,
approved with it, pinned by the leg with it. The two do not overlap. The brief is
written by a model and says what the brand FEELS like (characterization, the
chromatic moment, signature compositions). This is arithmetic over evidence the
ingestion already holds and says what the brand's own site MEASURES:

1. **type treatment** — the concrete face/size/weight/leading/tracking of every
   type role that reaches a page, and which of them a real sample anchored;
2. **cadence** — the measured band sequence, how often a dark band happens, and
   the section rhythm;
3. **color frequency** — not palette membership (the card already carries that)
   but USAGE LAW: which surface the page stands on, how rare the statement band
   is, whether the accent ever leaves a control;
4. **surface language** — the measured radii, hairlines, elevation and padding,
   named as kit tokens, as the only shape vocabulary a new section may use;
5. **anti-patterns** — the exclusions those measurements support, plus the house
   anti-slop defaults. An exclusion is as load-bearing as an inclusion.

Three rules are enforced here rather than trusted:

**No model, no network, no clock.** Every rule is computed from the evidence
bundle and the kit in front of it, so the same input extracts a byte-identical
audit forever. That is what lets it be diffed, reviewed and replayed.

**Absence is a finding, and it cannot be faked.** A `GrammarField` carries rules
OR a reason it is empty — never both, never neither. A brand whose capture
measured no bands gets "not known", never a plausible rhythm.

**Token names, not raw values, for anything the kit names.** Same law as the
brief: a rule speaks `radius.button`, and the consumption side
(`lumen_agent.brand_brief`) renders the web class beside it. A class name is
authoring vocabulary and does not belong in a durable kit section; a raw hex
where a token exists splits the vocabulary.
"""

from __future__ import annotations

from typing import Annotated, Any, ClassVar, Iterable, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from .colorspace import hex_alpha, hex_to_oklab, oklab_distance, relative_luminance
from .evidence import BrandEvidence, SectionBackground, SurfaceShape
from .normalizer.bands import DARK_LUMINANCE
from .normalizer.cluster import MERGE_DISTANCE
from .normalizer.typography import (
    TYPE_MEASUREMENT_FIELDS,
    anchor_for_role,
    measured_style_fields,
    resolve_anchors,
)

#: The kit section version. Bump only with a migration story for stored audits.
GRAMMAR_AUDIT_SCHEMA_VERSION = 1

#: Ceilings. They exist so a pathological page (a hundred bands, a kit with a
#: hundred measured radii) cannot mint an unbounded kit section — not to trim an
#: honest audit. Every one of them is well above a real brand's output.
_MAX_RULES = 14
_MAX_TEXT = 400
_MAX_SEQUENCE = 20
_MAX_TOKENS_PER_LINE = 6
_MAX_SURFACE_RULES = 3
_MAX_FAMILY = 60

#: A provenance pointer that begins here was MEASURED off the brand's live site;
#: anything else is an engine scale default. Same prefix the consumption side
#: reads (`lumen_agent.brand_brief._MEASURED_PREFIX`).
_MEASURED_PREFIX = "website:"

#: The type roles that actually reach a rendered web page, and the element the
#: web theme lands each one on (`crates/lumen-web/src/theme.rs::build_base_css`).
#: `type.eyebrow`/`type.stat` are deliberately absent: no web text variant
#: resolves them, so a rule about them would govern nothing.
_WEB_TYPE_ROLES: tuple[tuple[str, str], ...] = (
    ("type.display", "the display line"),
    ("type.headline", "the page's `<h1>`"),
    ("type.title", "an `<h2>`"),
    ("type.subtitle", "an `<h3>`"),
    ("type.body", "body copy"),
    ("type.cta", "button labels"),
)

#: Heading weights at or below this read as a LIGHT brand, at or above the other
#: as a HEAVY one. Between them there is nothing worth saying, and a rule with
#: nothing to say is noise in a prompt.
_LIGHT_WEIGHT = 400
_HEAVY_WEIGHT = 700

#: The largest measured corner that still counts as a square-ish brand. A brand
#: whose own controls sit at 4px does not want a 24px pill.
_TIGHT_RADIUS_PX = 8.0

#: The range a unitless line-height can plausibly be, outside which the number is not a leading
#: at all (F3.4). The F2 walk's audit legislated `type.title` at **leading 2.2** and, before the
#: anchor picking was fixed, `type.headline` at **3.45** — measurements taken off a collapsed
#: element, stated to an agent as this brand's law. There is no honest way to correct such a
#: number, so the line ABSTAINS from it: an audit that says nothing about leading leaves the
#: theme ramp to decide, while one that says 2.2 makes every heading on every generated page wrong
#: and cites the brand's own site as the reason.
_PLAUSIBLE_LEADING = (0.8, 2.0)

Text = Annotated[str, StringConstraints(min_length=1, max_length=_MAX_TEXT)]

#: `measured` — read off the brand's own site. `derived` — an engine scale/ramp
#: default the brand never anchored, stated as exactly that. `default` — a house
#: rule that holds for every brand and is not a claim about this one.
Basis = Literal["measured", "derived", "default"]


class GrammarRule(BaseModel):
    """One law, plus the thing that entitles us to state it."""

    model_config = ConfigDict(extra="forbid")

    rule: Text
    evidence: Text
    basis: Basis


class GrammarField(BaseModel):
    """One of the five fields: rules, or a stated absence — never both.

    The XOR is the honesty rule made structural. A field that could carry an
    empty rule list and no reason would let a silent extraction bug read as "this
    brand has no cadence", which is a claim nobody measured.
    """

    model_config = ConfigDict(extra="forbid")

    rules: list[GrammarRule] = Field(default_factory=list, max_length=_MAX_RULES)
    absent: Optional[Text] = None

    @model_validator(mode="after")
    def _rules_xor_absence(self) -> "GrammarField":
        if bool(self.rules) == bool(self.absent):
            raise ValueError(
                "a grammar field carries rules OR a reason it is empty, never both and never neither"
            )
        return self


class BrandGrammarAudit(BaseModel):
    """`BrandGrammarAudit@1` — the whole kit section."""

    model_config = ConfigDict(extra="forbid")

    FIELD_NAMES: ClassVar[tuple[str, ...]] = (
        "type_treatment",
        "cadence",
        "color_frequency",
        "surface_language",
        "anti_patterns",
    )

    schema_version: Literal[1] = GRAMMAR_AUDIT_SCHEMA_VERSION
    type_treatment: GrammarField
    cadence: GrammarField
    color_frequency: GrammarField
    surface_language: GrammarField
    anti_patterns: GrammarField


def extract_grammar_audit(
    evidence: BrandEvidence, brand_kit: dict[str, Any]
) -> BrandGrammarAudit:
    """The audit this evidence and this kit honestly support.

    Pure: no model, no network, no I/O, no clock. Ordered iteration everywhere,
    so the same pair extracts the same audit byte for byte.
    """
    bands = _usable_bands(evidence.geometry.background_sequence)
    surfaces = list(evidence.geometry.surfaces)
    measured = _measured_tokens(brand_kit)
    dark = [band for band in bands if _tone(band) == "dark"]

    return BrandGrammarAudit(
        type_treatment=_type_treatment(evidence, brand_kit),
        cadence=_cadence(
            evidence.geometry.background_sequence, bands, dark, brand_kit, measured
        ),
        color_frequency=_color_frequency(
            bands,
            surfaces,
            brand_kit,
            len(evidence.geometry.background_sequence) - len(bands),
        ),
        surface_language=_surface_language(brand_kit, measured, surfaces),
        anti_patterns=_anti_patterns(
            evidence, brand_kit, bands, dark, surfaces, measured
        ),
    )


# --- 1. type treatment --------------------------------------------------------------


def _type_treatment(evidence: BrandEvidence, brand_kit: dict[str, Any]) -> GrammarField:
    typography = _group(brand_kit, "typography")
    if not typography:
        return GrammarField(
            absent="this kit carries no `type.*` roles, so nothing is known about its type treatment."
        )

    anchors = resolve_anchors(evidence)
    # Source authority leads so a truncated block cannot elevate derived ramp
    # values over the measured responsive style of the selected component.
    rules: list[GrammarRule] = [
        GrammarRule(
            rule=(
                "For captured/adapted bands and equivalent new roles, preserve the measured source "
                "typography and responsive CSS. The theme's type ramp is a fallback where source "
                "measurements are unavailable; derived/substituted values are not observed facts. "
                "Inspect and bind source roles before raw composition, rather than adding generic "
                "size/weight utilities."
            ),
            evidence=(
                "house rule: measured component styles govern reuse; "
                "kit roles supply fallback values"
            ),
            basis="default",
        )
    ]
    role_rules: list[GrammarRule] = []
    heading_weight: Optional[int] = None
    for role, where in _WEB_TYPE_ROLES:
        style = _style_value(typography.get(role))
        if style is None:
            continue
        anchor = anchor_for_role(role.removeprefix("type."), anchors)
        measured = measured_style_fields(anchors, role, style)
        derived = TYPE_MEASUREMENT_FIELDS - measured
        observation = (
            f"measured {', '.join(sorted(measured))} at {_locator(anchor)[:100]}; "
            if measured else ""
        )
        qualification = (
            f"derived/substituted {', '.join(sorted(derived))}; these are not observed brand facts"
            if derived else "all listed type properties match the selected sample"
        )
        role_rules.append(
            GrammarRule(
                # The `derived` basis is what says "computed, not observed", and
                # the injected block renders it as a marker — saying it twice in
                # one line spends characters on nothing.
                rule=f"`{role}` ({where}) is {_style_text(style)}.",
                evidence=observation + qualification,
                basis="derived" if derived else "measured",
            )
        )
        if role == "type.headline" and "font_weight" in measured:
            weight = style.get("font_weight")
            if isinstance(weight, int):
                heading_weight = weight

    if heading_weight is not None and heading_weight <= _LIGHT_WEIGHT:
        rules.append(
            GrammarRule(
                rule=(
                    f"This brand's headings are LIGHT (weight {heading_weight}). A bold "
                    "heading is not this brand."
                ),
                evidence="measured on the site's own h1",
                basis="measured",
            )
        )
    elif heading_weight is not None and heading_weight >= _HEAVY_WEIGHT:
        rules.append(
            GrammarRule(
                rule=(
                    f"This brand's headings are HEAVY (weight {heading_weight}). A thin "
                    "display line is not this brand."
                ),
                evidence="measured on the site's own h1",
                basis="measured",
            )
        )

    unpaintable = _families_without_binaries(brand_kit, typography)
    if unpaintable:
        # The Sohne caveat (F2 close-out, F3.4). stripe.com's first walk produced an audit that
        # legislated in `sohne-var` — a family the kit held no binaries for, because the capture
        # never descended into the `@media`-nested `@font-face` that named it. The root cause is
        # closed, and the SHAPE is not: an audit's type roles come off the kit's tokens and the
        # kit's faces come off the capture, and nothing made the two agree. Whenever they do not,
        # the audit is legislating in a typeface nothing downstream can paint, and the honest
        # move is to say so in the same breath rather than to leave an agent obeying a font that
        # will silently fall back.
        named = ", ".join(f"`{family}`" for family in unpaintable[:_MAX_TOKENS_PER_LINE])
        rules.append(
            GrammarRule(
                rule=(
                    f"CAVEAT — this kit holds no font files for {named}, so the treatment below "
                    "names a typeface nothing here can paint; expect the fallback stack. Do not "
                    "read the face as available."
                ),
                evidence="the kit's own font assets carry no faces for that family",
                basis="measured",
            )
        )

    # A measured fact about the whole ramp outranks any single role's listing, so
    # it sits above them and below the law.
    return GrammarField(rules=_capped(rules + role_rules))


def _families_without_binaries(
    brand_kit: dict[str, Any], typography: dict[str, Any]
) -> list[str]:
    """The families this audit's type roles name that the kit holds no faces for.

    Compares on the FIRST family of each role's stack, because that is the one a browser reaches
    for and the rest are the fallback the caveat is warning about. Case- and quote-insensitive: a
    kit writes ``sohne-var`` and a stylesheet writes ``"Sohne Var"`` for the same thing often
    enough that an exact match would report a caveat about every site.

    Returns ``[]`` when the kit declares no font assets AT ALL — that is "nothing is known about
    this kit's faces", not "this kit cannot paint anything", and a caveat off no evidence is the
    kind of confident wrongness the whole audit is written against.

    A kit that DOES declare fonts and holds no binaries for any of them is the opposite case, and
    it is the strongest case this caveat exists for — it is stripe's first walk exactly: the kit
    knew about ``sohne-var`` and had zero faces for it. That used to fall through the same
    early return, because "nothing paintable" and "nothing declared" were being tested with one
    condition (F3.4 fix round, F-5). They are now two.

    **A SYSTEM font is paintable with no faces at all**, and that is the third case. The
    normalizer records ``source.kind == "system"`` for a family it found no webfont for — the
    engine's own Inter default is the everyday one — and such a family needs no binaries from us
    because nothing is being served. Caveating it would say a brand cannot paint the font it is
    already painting in, which is the confident wrongness this function's own last paragraph is
    about.
    """
    fonts = ((brand_kit.get("assets") or {}).get("fonts")) or {}
    if not isinstance(fonts, dict) or not fonts:
        return []
    paintable = {
        _family_key(font.get("family"))
        for font in fonts.values()
        if isinstance(font, dict) and _is_paintable(font)
    }
    paintable.discard("")
    missing: list[str] = []
    for role, _where in _WEB_TYPE_ROLES:
        style = _style_value(typography.get(role))
        if style is None:
            continue
        family = _first_family(style.get("font_family"))
        key = _family_key(family)
        if not key or key in paintable or family in missing:
            continue
        missing.append(family)
    return missing


def _is_paintable(font: Any) -> bool:
    """Can this declared family be rendered — either because we hold its bytes, or because it
    needs none? See :func:`_families_without_binaries` for the three cases."""
    if not isinstance(font, dict):
        return False
    if font.get("faces"):
        return True
    source = font.get("source")
    kind = source.get("kind") if isinstance(source, dict) else None
    return kind == "system"


def _first_family(stack: Any) -> str:
    """``'sohne-var, Helvetica, sans-serif'`` -> ``'sohne-var'``."""
    if not isinstance(stack, str):
        return ""
    return stack.split(",")[0].strip().strip("\"'")[:_MAX_FAMILY]


def _family_key(family: Any) -> str:
    if not isinstance(family, str):
        return ""
    return " ".join(family.strip().strip("\"'").lower().replace("-", " ").split())


def _style_value(entry: Any) -> Optional[dict[str, Any]]:
    default = _default_value(entry)
    return default if isinstance(default, dict) and default.get("kind") == "style" else None


def _style_text(style: dict[str, Any]) -> str:
    # The family is the one part of this line that comes from unbounded captured
    # text — a site can declare its whole CSS stack as one family — and the rule
    # is length-capped, so an uncapped family would cost the entire audit rather
    # than one long word.
    parts = [str(style.get("font_family") or "").strip()[:_MAX_FAMILY]]
    size = style.get("font_size")
    if isinstance(size, (int, float)):
        parts.append(f"{_trim(size)}px")
    weight = style.get("font_weight")
    if isinstance(weight, int):
        parts.append(f"weight {weight}")
    line_height = style.get("line_height")
    if isinstance(line_height, (int, float)):
        low, high = _PLAUSIBLE_LEADING
        if low <= line_height <= high:
            parts.append(f"leading {_trim(line_height)}")
        else:
            # Said, not silently swallowed: the number is evidence that the anchor measured the
            # wrong thing, and a reader who sees the gap should be able to tell "this brand has
            # no measured leading" from "we measured one and would not repeat it".
            parts.append(
                f"leading not stated (the anchor measured {_trim(line_height)}, which is not a "
                "line-height)"
            )
    spacing = style.get("letter_spacing")
    if isinstance(spacing, (int, float)) and spacing:
        parts.append(f"tracking {_trim(spacing)}em")
    return " / ".join(part for part in parts if part)


def _locator(sample: Any) -> str:
    locator = getattr(getattr(sample, "pointer", None), "locator", "")
    return str(locator)[:160]


# --- 2. cadence ---------------------------------------------------------------------


def _cadence(
    sequence: list[SectionBackground],
    bands: list[SectionBackground],
    dark: list[SectionBackground],
    brand_kit: dict[str, Any],
    measured: dict[str, str],
) -> GrammarField:
    if not sequence:
        return GrammarField(
            absent=(
                "the capture measured no band sequence for this site, so nothing is known "
                "about its section rhythm."
            )
        )

    tones = [_tone(band) for band in sequence]
    shown = tones[:_MAX_SEQUENCE]
    overflow = len(tones) - len(shown)
    rendered = ", ".join(shown) + (f" (+{overflow} more)" if overflow else "")
    rules = [
        GrammarRule(
            rule=(
                f"The site's own band sequence, top to bottom: {rendered} "
                f"({len(sequence)} measured bands). Compose new sections into that rhythm."
            ),
            evidence="measured band backgrounds, in the order the page paints them",
            basis="measured",
        )
    ]

    total = len(bands)
    unread = len(sequence) - total
    noun = _band_noun(unread)
    caveat = _unread_caveat(unread, len(sequence))
    if not _counts_for_the_page(bands, sequence):
        # The refusals are the majority (or everything): whatever the readable
        # minority says about light and dark is not a fact about this page, and a
        # law built on it would be the opposite of the truth on an ordinary
        # photo-led brand.
        rules.append(
            GrammarRule(
                rule=(
                    "This site's light/dark balance is NOT KNOWN: "
                    f"{unread} of {len(sequence)} bands carry an image, a gradient or a "
                    "translucent paint, so their color could not be read. Do not read the "
                    "sequence above as a count."
                ),
                evidence=(
                    f"the capture could read the color of only {total} of {len(sequence)} bands"
                ),
                basis="measured",
            )
        )
    elif total:
        count = len(dark)
        if count == 0:
            rules.append(
                GrammarRule(
                    rule=(
                        f"No dark band among the {total} {noun} on this site: all of them are "
                        f"light. A dark section would be new to this brand.{caveat}"
                    ),
                    evidence=f"0 of {total} {noun} below the dark-luminance threshold",
                    basis="measured",
                )
            )
        elif count * 3 <= total:
            rules.append(
                GrammarRule(
                    rule=(
                        f"A dark band is the exception here — {count} of {total}. Use it as an "
                        f"interval between light sections, never as the page's default "
                        f"surface.{caveat}"
                    ),
                    evidence=f"{count} of {total} {noun} are dark",
                    basis="measured",
                )
            )
        else:
            rules.append(
                GrammarRule(
                    rule=(
                        f"Dark is a working surface for this brand — {count} of {total} {noun}. "
                        f"A light-only page would not read as this site.{caveat}"
                    ),
                    evidence=f"{count} of {total} {noun} are dark",
                    basis="measured",
                )
            )

    rhythm = _measured_number(brand_kit, measured, "space.section")
    if rhythm is not None:
        rules.append(
            GrammarRule(
                rule=(
                    f"Band rhythm is {_trim(rhythm)}px — `space.section`. Write it as the "
                    "utility, never as a raw vertical padding step."
                ),
                evidence=measured["space.section"],
                basis="measured",
            )
        )
    else:
        rules.append(
            GrammarRule(
                rule=(
                    "No section rhythm was measured on this site; `space.section` falls back to "
                    "the platform default. Still write the utility — the number is not a brand fact."
                ),
                evidence="no `website:` provenance on `space.section`",
                basis="derived",
            )
        )
    return GrammarField(rules=_capped(rules))


# --- 3. color frequency -------------------------------------------------------------


def _color_frequency(
    bands: list[SectionBackground],
    surfaces: list[SurfaceShape],
    brand_kit: dict[str, Any],
    unread: int,
) -> GrammarField:
    controls = _control_fills(surfaces)
    if not bands and not controls:
        return GrammarField(
            absent=(
                "the capture measured neither band backgrounds nor control fills, so nothing "
                "is known about how often this brand uses a color."
            )
        )

    rules: list[GrammarRule] = []
    groups = _band_groups(bands)
    total = len(bands)
    # One token names at most one band color. Two near-whites can both resolve to
    # `surface.canvas`, and printing that name twice would teach the agent that
    # one token paints two different pixels.
    claimed: set[str] = set()
    for position, (value, members) in enumerate(groups[:_MAX_SURFACE_RULES]):
        token = _surface_token(value, brand_kit)
        if token in claimed:
            token = None
        elif token:
            claimed.add(token)
        named = f"`{value}`" + (f" (`{token}`)" if token else "")
        # The denominator is the bands whose color could be READ, and it says so
        # when that is not every band the capture saw.
        share = f"{len(members)} of {total} {_band_noun(unread)}"
        if position == 0:
            rules.append(
                GrammarRule(
                    rule=(
                        f"{named} carries {share} — this page's default canvas. "
                        "A new section stands on it unless it has a reason not to."
                    ),
                    evidence="counted over the measured band sequence",
                    basis="measured",
                )
            )
        else:
            rules.append(
                GrammarRule(
                    rule=f"{named} carries {share}. Use it exactly that sparingly.",
                    evidence="counted over the measured band sequence",
                    basis="measured",
                )
            )

    band_values = {value for value, _ in groups}
    accent = next(
        ((value, count) for value, count in controls if value not in band_values), None
    )
    if accent is not None:
        value, count = accent
        token = _surface_token(value, brand_kit)
        named = f"`{value}`" + (f" (`{token}`)" if token else "")
        # The cross-check can only see the bands whose color was READ, so when
        # some were not, the claim says which set it checked rather than
        # implying it looked at the whole page.
        against = (
            "and not one band background"
            if not unread
            else f"and not one of the {total} band backgrounds whose color could be read"
        )
        rules.append(
            GrammarRule(
                rule=(
                    f"{named} fills controls and nothing else — {count} measured button/chip "
                    f"variants, {against}. Keep it at control scale; a band painted in it is "
                    "not this brand."
                ),
                evidence="measured control fills, cross-checked against the band backgrounds",
                basis="measured",
            )
        )
    return GrammarField(rules=_capped(rules))


def _control_fills(surfaces: Iterable[SurfaceShape]) -> list[tuple[str, int]]:
    """Opaque solid fills measured on controls, most-used first."""
    counts: dict[str, int] = {}
    for shape in surfaces:
        if shape.surface not in ("button", "chip"):
            continue
        if shape.fill != "solid" or not shape.background:
            continue
        if hex_alpha(shape.background) < 1.0:
            continue
        value = _rgb(shape.background)
        counts[value] = counts.get(value, 0) + max(1, shape.count)
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def _band_groups(bands: list[SectionBackground]) -> list[tuple[str, list[SectionBackground]]]:
    """Bands grouped by exact background, biggest presence first."""
    groups: dict[str, list[SectionBackground]] = {}
    for band in bands:
        groups.setdefault(_rgb(band.background or ""), []).append(band)
    return sorted(
        groups.items(),
        key=lambda item: (-len(item[1]), -sum(b.height_px for b in item[1]), item[0]),
    )


def _surface_token(value: str, brand_kit: dict[str, Any]) -> Optional[str]:
    """The kit's own name for this color, when it carries one.

    SURFACE roles only. `#FFFFFF` is very often also `text.inverse`, and naming a
    page band after an ink role would teach the wrong vocabulary.
    """
    try:
        lab = hex_to_oklab(value)
    except Exception:
        return None
    best: Optional[tuple[float, str]] = None
    for name, entry in _group(brand_kit, "colors").items():
        if not name.startswith("surface."):
            continue
        default = _default_value(entry)
        if not isinstance(default, dict) or default.get("kind") != "hex":
            continue
        raw = default.get("value")
        if not isinstance(raw, str):
            continue
        try:
            distance = oklab_distance(lab, hex_to_oklab(_rgb(raw)))
        except Exception:
            continue
        if distance <= MERGE_DISTANCE and (best is None or (distance, name) < best):
            best = (distance, name)
    return best[1] if best else None


# --- 4. surface language ------------------------------------------------------------

#: The measured shape vocabulary, group by group, in the order a new section
#: writes it. Only the utility HEADS — the tokens a web class actually resolves
#: (`GEOMETRY_UTILITIES`, crates/lumen-web/src/theme.rs) — appear here. The
#: scale rungs behind them (`radius.md`, `shadow.sm`, `space.10`) are the
#: engine's business: an author cannot deploy one, so a rule naming it would be
#: unfollowable noise in a bounded prompt. `space.section` is deliberately
#: absent: the cadence field owns the band rhythm and says it once.
_SURFACE_GROUPS: tuple[tuple[str, tuple[str, ...], str, str], ...] = (
    (
        "radii",
        ("radius.button", "radius.card", "radius.badge"),
        "Corners",
        "the only corner shapes this brand measures",
    ),
    (
        "stroke_widths",
        ("stroke.width.card", "stroke.width.divider"),
        "Hairlines",
        "the only border weights it measures",
    ),
    (
        "shadows",
        ("shadow.brand", "shadow.card"),
        "Elevation",
        "its whole elevation vocabulary",
    ),
    (
        "spacing",
        ("space.card.padding", "space.stack.default"),
        "Spacing",
        "its measured steps",
    ),
)


def _surface_language(
    brand_kit: dict[str, Any],
    measured: dict[str, str],
    surfaces: list[SurfaceShape],
) -> GrammarField:
    rules: list[GrammarRule] = []
    for group, heads, opener, closer in _SURFACE_GROUPS:
        entries = _group(brand_kit, group)
        names = [name for name in heads if name in measured and name in entries]
        rendered = [
            f"`{name}` {value}"
            for name, value in (
                (name, _token_text(entries[name])) for name in names[:_MAX_TOKENS_PER_LINE]
            )
            if value
        ]
        if not rendered:
            continue
        rules.append(
            GrammarRule(
                rule=f"{opener}: {', '.join(rendered)} — {closer}.",
                evidence="read off the brand's own rendered page",
                basis="measured",
            )
        )

    if not _group(brand_kit, "shadows") and surfaces:
        rules.append(
            GrammarRule(
                rule=(
                    "This brand paints no shadow anywhere: not one measured surface is "
                    "elevated. Flat is the brand, not an omission to correct."
                ),
                evidence=f"{len(surfaces)} measured surfaces, none carrying a box-shadow",
                basis="measured",
            )
        )

    if any(shape.pill for shape in surfaces if shape.surface in ("button", "chip")):
        rules.append(
            GrammarRule(
                rule="Controls are fully round (pills) on this site — a squared button is not this brand.",
                evidence="a measured control variant is fully rounded",
                basis="measured",
            )
        )

    if not rules:
        return GrammarField(
            absent=(
                "the capture measured no radii, borders, elevations or spacing off this site; "
                "every shape token on the kit is an engine default."
            )
        )
    return GrammarField(rules=_capped(rules))


# --- 5. anti-patterns ---------------------------------------------------------------

#: The house anti-slop defaults, verbatim from the design guidance the lane
#: already ships (`create-website`'s Design guidance §2/§3). They hold for every
#: brand, so they are `default` basis — never dressed up as this brand's finding.
_HOUSE_EXCLUSIONS: tuple[str, ...] = (
    "No decorative geometry — blobs, orbs, gradient meshes, scattered shapes — unless this "
    "brand's real presence uses it. It is the clearest AI-slop tell there is.",
    "No placeholder logo grids and no one-of-each parade of primitives: pick one composition "
    "system and apply it across the page.",
)


def _anti_patterns(
    evidence: BrandEvidence,
    brand_kit: dict[str, Any],
    bands: list[SectionBackground],
    dark: list[SectionBackground],
    surfaces: list[SurfaceShape],
    measured: dict[str, str],
) -> GrammarField:
    rules: list[GrammarRule] = []

    sequence = list(evidence.geometry.background_sequence)
    unread = len(sequence) - len(bands)
    # Same gate as the cadence's dark rule, and for the same reason: this is the
    # exclusion built on that count, so it may not outlive the count's honesty.
    # ZERO dark bands is not this rule's case (W8). "No EXTRA dark sections… a SECOND dark band"
    # is wrong when there is no first, and the cadence field one heading above already says the
    # right thing for that page ("A dark section would be new to this brand"). So the exclusion
    # speaks only where there IS a dark band to be extra to; otherwise it abstains rather than
    # legislating from a count of nothing.
    if _counts_for_the_page(bands, sequence) and dark and len(dark) * 3 <= len(bands):
        # The sentence has to be TRUE OF THE COUNT (F3.4). "A second dark band is a rhythm this
        # brand does not have" is right about a site with ONE dark band and plainly false about
        # stripe.com, which has two — the F2 walk's audit said exactly that, of a page whose own
        # sequence one heading above reads `light, light, light, dark, light, dark, light, light`.
        # An exclusion that contradicts the evidence printed beside it teaches an agent to
        # discount both. So at n=1 the law names the second band, and at n>=2 it names the count
        # it actually has and forbids going past it.
        count = len(dark)
        law = (
            "A second dark band is a rhythm this brand does not have."
            if count == 1
            else f"Use dark exactly that sparingly: a {_ordinal(count + 1)} dark band is a rhythm "
            "this brand does not have."
        )
        rules.append(
            GrammarRule(
                rule=(
                    f"No extra dark sections: {count} of {len(bands)} "
                    f"{_band_noun(unread)} {'is' if count == 1 else 'are'} dark. {law}"
                    + _unread_caveat(unread, len(sequence))
                ),
                evidence="counted over the measured band sequence",
                basis="measured",
            )
        )

    # Already correct before the refused-band sweep, and the shape the two rules
    # above were fixed into: it consults the RAW sequence, so "not one" means not
    # one of the bands the capture saw, refused or otherwise.
    if bands and not any(band.gradient for band in sequence):
        rules.append(
            GrammarRule(
                rule="No gradient or mesh band backgrounds: not one measured band on this site uses one.",
                evidence=f"0 of {len(sequence)} measured bands is a gradient",
                basis="measured",
            )
        )

    if surfaces and not _group(brand_kit, "shadows"):
        rules.append(
            GrammarRule(
                rule="No shadows, glows or glassmorphism: nothing measured on this site is elevated.",
                evidence=f"{len(surfaces)} measured surfaces, none carrying a box-shadow",
                basis="measured",
            )
        )

    radii = [
        value
        for value in (
            _measured_number(brand_kit, measured, name)
            for name in ("radius.button", "radius.card", "radius.badge")
        )
        if value is not None
    ]
    if radii and max(radii) <= _TIGHT_RADIUS_PX:
        rules.append(
            GrammarRule(
                rule=(
                    f"No giant pills and no 2xl rounding: the largest corner this brand measures "
                    f"is {_trim(max(radii))}px."
                ),
                evidence="measured control, card and badge radii",
                basis="measured",
            )
        )

    rules.extend(
        GrammarRule(
            rule=text,
            evidence="house default from the lane's design guidance; not a measurement of this brand",
            basis="default",
        )
        for text in _HOUSE_EXCLUSIONS
    )
    return GrammarField(rules=_capped(rules))


# --- shared helpers -----------------------------------------------------------------


def _ordinal(number: int) -> str:
    """``3`` -> ``"third"``. Small and closed: the dark-band law is the only caller, and past a
    handful of dark bands the rule that uses it has already stopped firing."""
    names = {
        2: "second",
        3: "third",
        4: "fourth",
        5: "fifth",
        6: "sixth",
        7: "seventh",
        8: "eighth",
        9: "ninth",
        10: "tenth",
    }
    return names.get(number, f"{number}th")


def _counts_for_the_page(
    bands: list[SectionBackground], sequence: list[SectionBackground]
) -> bool:
    """May a count over the READABLE bands be stated as a law about this page?

    Only when the bands whose color could be read are a majority of the sequence.
    A photo-led brand's four dark hero/feature bands are refused for a good
    reason (their stored hex is not what the page shows), but the two bands left
    over are not the page — counting them and calling the result "this site" is
    how "no dark band anywhere" gets said about a dark site.
    """
    return bool(bands) and len(bands) * 2 >= len(sequence)


def _band_noun(unread: int) -> str:
    """What the denominator of a band count is honestly called."""
    return "readable bands" if unread else "measured bands"


def _unread_caveat(unread: int, total: int) -> str:
    """The sentence a band-count LAW carries when some bands could not be read.

    It rides the rule itself rather than the field, because the injected block
    can drop rules independently — a caveat one line away is a caveat that may
    not be there when the law is.
    """
    if not unread:
        return ""
    if unread == 1:
        return (
            f" 1 of the {total} bands carries an image, a gradient or a translucent paint, so "
            f"its color was not read and this counts the other {total - 1}."
        )
    return (
        f" {unread} of the {total} bands carry an image, a gradient or a translucent paint, so "
        f"their colors were not read and this counts the other {total - unread}."
    )


def _usable_bands(sequence: Iterable[SectionBackground]) -> list[SectionBackground]:
    """Bands whose stored color is what the page actually shows.

    Same three refusals `normalizer.bands` makes: a gradient, an image, or a
    translucent paint does not describe the pixels, so it counts toward nothing.
    """
    usable: list[SectionBackground] = []
    for band in sequence:
        if not band.background or band.gradient or band.has_image:
            continue
        if hex_alpha(band.background) < 1.0:
            continue
        usable.append(band)
    return usable


def _tone(band: SectionBackground) -> str:
    if not band.background or band.gradient or band.has_image:
        return "unknown"
    if hex_alpha(band.background) < 1.0:
        return "unknown"
    return "dark" if relative_luminance(band.background) < DARK_LUMINANCE else "light"


def _measured_tokens(brand_kit: dict[str, Any]) -> dict[str, str]:
    """`{token name: its website provenance}` for every measured shape token."""
    found: dict[str, str] = {}
    for group in ("radii", "stroke_widths", "spacing", "shadows"):
        for name, entry in _group(brand_kit, group).items():
            source = _provenance_source(entry)
            if source.startswith(_MEASURED_PREFIX):
                found[name] = source[:_MAX_TEXT]
    return found


def _group(brand_kit: Any, group: str) -> dict[str, Any]:
    tokens = brand_kit.get("tokens") if isinstance(brand_kit, dict) else None
    entries = tokens.get(group) if isinstance(tokens, dict) else None
    return entries if isinstance(entries, dict) else {}


def _default_value(entry: Any) -> Any:
    if not isinstance(entry, dict):
        return None
    value = entry.get("value")
    return value.get("default") if isinstance(value, dict) else None


def _provenance_source(entry: Any) -> str:
    if not isinstance(entry, dict):
        return ""
    provenance = entry.get("provenance")
    source = provenance.get("source") if isinstance(provenance, dict) else None
    return source if isinstance(source, str) else ""


def _measured_number(
    brand_kit: dict[str, Any], measured: dict[str, str], name: str
) -> Optional[float]:
    """A measured number token's value, or None when the kit's is an engine default."""
    if name not in measured:
        return None
    for group in ("radii", "stroke_widths", "spacing"):
        default = _default_value(_group(brand_kit, group).get(name))
        if isinstance(default, dict) and default.get("kind") == "number":
            value = default.get("value")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
    return None


def _token_text(entry: Any) -> str:
    """One token's value as a designer would write it, or '' if unreadable."""
    default = _default_value(entry)
    if not isinstance(default, dict):
        return ""
    if default.get("kind") == "number":
        number = default.get("value")
        if not isinstance(number, (int, float)) or isinstance(number, bool):
            return ""
        return f"{_trim(number)}{default.get('unit') or ''}"
    if "blur" in default and "color" in default:
        parts = [
            _trim(default.get("x") or 0),
            f"{_trim(default.get('y') or 0)}px",
            f"{_trim(default.get('blur') or 0)}px",
            f"{_trim(default.get('spread') or 0)}px",
            str(default.get("color") or ""),
        ]
        return " ".join(part for part in parts if part)
    return ""


def _trim(number: Any) -> str:
    if not isinstance(number, (int, float)) or isinstance(number, bool):
        return ""
    return f"{float(number):g}"


def _rgb(value: str) -> str:
    """An 8-digit hex reduced to its RGB half; anything else passed through."""
    text = value.strip().upper()
    return text[:7] if len(text) == 9 and text.startswith("#") else text


def _capped(rules: list[GrammarRule]) -> list[GrammarRule]:
    return rules[:_MAX_RULES]
