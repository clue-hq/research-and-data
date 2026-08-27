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
from .normalizer.typography import ANCHOR_LABELS, resolve_anchors

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
        color_frequency=_color_frequency(bands, surfaces, brand_kit),
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
    anchored: dict[str, str] = {}
    for label, role in ANCHOR_LABELS.items():
        sample = anchors.samples.get(label)
        if sample is not None:
            anchored.setdefault(f"type.{role}", label)

    rules: list[GrammarRule] = []
    heading_weight: Optional[int] = None
    for role, where in _WEB_TYPE_ROLES:
        style = _style_value(typography.get(role))
        if style is None:
            continue
        label = anchored.get(role)
        rules.append(
            GrammarRule(
                # The `derived` basis is what says "computed, not observed", and
                # the injected block renders it as a marker — saying it twice in
                # one line spends characters on nothing.
                rule=f"`{role}` ({where}) is {_style_text(style)}.",
                evidence=(
                    f"measured off the site's own {label} ({_locator(anchors.samples[label])})"
                    if label
                    else "nothing on the site anchored this role; the engine's ramp computed it "
                    "from the measured body and headline sizes"
                ),
                basis="measured" if label else "derived",
            )
        )
        if role == "type.headline" and label:
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

    rules.append(
        GrammarRule(
            rule=(
                "Headings and body land on the theme's type ramp with no classes of their "
                "own. Never restate size, weight, leading or tracking on a heading: a raw "
                "`text-5xl font-bold` replaces the treatment above with a generic one."
            ),
            evidence="house rule: the kit's type roles compile into the theme base layer",
            basis="default",
        )
    )
    return GrammarField(rules=_capped(rules))


def _style_value(entry: Any) -> Optional[dict[str, Any]]:
    default = _default_value(entry)
    return default if isinstance(default, dict) and default.get("kind") == "style" else None


def _style_text(style: dict[str, Any]) -> str:
    parts = [str(style.get("font_family") or "").strip()]
    size = style.get("font_size")
    if isinstance(size, (int, float)):
        parts.append(f"{_trim(size)}px")
    weight = style.get("font_weight")
    if isinstance(weight, int):
        parts.append(f"weight {weight}")
    line_height = style.get("line_height")
    if isinstance(line_height, (int, float)):
        parts.append(f"leading {_trim(line_height)}")
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
    if total:
        count = len(dark)
        if count == 0:
            rules.append(
                GrammarRule(
                    rule=(
                        f"No dark band anywhere on this site: all {total} measured bands are "
                        "light. A dark section would be new to this brand."
                    ),
                    evidence=f"0 of {total} measured bands below the dark-luminance threshold",
                    basis="measured",
                )
            )
        elif count * 3 <= total:
            rules.append(
                GrammarRule(
                    rule=(
                        f"A dark band is the exception here — {count} of {total}. Use it as an "
                        "interval between light sections, never as the page's default surface."
                    ),
                    evidence=f"{count} of {total} measured bands are dark",
                    basis="measured",
                )
            )
        else:
            rules.append(
                GrammarRule(
                    rule=(
                        f"Dark is a working surface for this brand — {count} of {total} measured "
                        "bands. A light-only page would not read as this site."
                    ),
                    evidence=f"{count} of {total} measured bands are dark",
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
        share = f"{len(members)} of {total}"
        if position == 0:
            rules.append(
                GrammarRule(
                    rule=(
                        f"{named} carries {share} measured bands — this page's default canvas. "
                        "A new section stands on it unless it has a reason not to."
                    ),
                    evidence="counted over the measured band sequence",
                    basis="measured",
                )
            )
        else:
            rules.append(
                GrammarRule(
                    rule=(
                        f"{named} carries {share} measured bands. Use it exactly that sparingly."
                    ),
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
        rules.append(
            GrammarRule(
                rule=(
                    f"{named} fills controls and nothing else — {count} measured button/chip "
                    "variants, and not one band background. Keep it at control scale; a band "
                    "painted in it is not this brand."
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

    if bands and len(dark) * 3 <= len(bands):
        rules.append(
            GrammarRule(
                rule=(
                    f"No extra dark sections: {len(dark)} of {len(bands)} measured bands is "
                    "dark. A second dark band is a rhythm this brand does not have."
                ),
                evidence="counted over the measured band sequence",
                basis="measured",
            )
        )

    if bands and not any(band.gradient for band in evidence.geometry.background_sequence):
        rules.append(
            GrammarRule(
                rule="No gradient or mesh band backgrounds: not one measured band on this site uses one.",
                evidence=f"0 of {len(evidence.geometry.background_sequence)} measured bands is a gradient",
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
