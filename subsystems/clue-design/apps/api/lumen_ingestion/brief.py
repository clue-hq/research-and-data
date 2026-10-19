"""`BrandBrief@1` — the per-brand Creative Brief that rides the kit (slice 3).

Tier 2 of the design-brief plan. The kit's TOKENS carry the brand's vocabulary
(what its colors, type, radii and shadows *are*); this carries its GRAMMAR (where
those tokens go, how often, and what the brand demonstrably never does). It is a
first-class kit section — `brand_kit_json.brief` — drafted with the kit version,
reviewed with it on `/brand-context`, approved with it, and pinned by the leg
with it. Not a loose file, and not prose: fixed sections, so consumption stays
deterministic and size-capped.

Two rules are enforced here rather than trusted:

**The token law extends to the brief.** Every value that names a color, a type
role, a radius, a spacing step or a shadow is a kit TOKEN NAME — never a raw hex,
never a pixel value. It is enforced twice: a shape check on the field (a `#...`
or an `8px` is not a token name) and a resolution check against the kit's own
token set (`surface.invented` is refused by the kit that has no such token). A
brief that smuggled a raw value in would push it straight into a generated
document, where the engine's theme-token law forbids it.

**Absence is a finding.** Every list section may be empty and every optional
field may be null. "This brand uses no shadows" is a correct, strong brief; a
fabricated section is the only real failure. The refusal path (`BriefRefused`)
therefore never blocks a kit — the caller publishes briefless with a diagnostic.
"""

from __future__ import annotations

from typing import Annotated, Any, Iterator, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

#: The kit section version. Bump only with a migration story for stored briefs.
BRIEF_SCHEMA_VERSION = 1

#: A token NAME: dotted segments of letters/digits/underscore/hyphen, starting
#: with a letter. `surface.brand`, `radius.button`, `type.body.small`, and the
#: ingestion aliases (`Aqua`) all pass; `#30d8a7`, `8px`, `rgba(50,50,93,.12)`
#: and `12` all fail. This is the SHAPE half of the token law — the resolution
#: half lives in `validate_brief`.
TOKEN_NAME_PATTERN = r"^[A-Za-z][A-Za-z0-9_-]*(?:\.[A-Za-z0-9_-]+)*$"

TokenRef = Annotated[str, StringConstraints(pattern=TOKEN_NAME_PATTERN, max_length=120)]

Confidence = Literal["low", "medium", "high"]

#: Where a palette token is allowed to land. The grammar, not the value — this
#: is what keeps "navy is ink only" from becoming a navy page background.
PaletteScope = Literal[
    "canvas",
    "ink",
    "accent-punctuation",
    "tinted-card",
    "statement-surface",
    "motif",
]

#: `STRONG` = observed as a repeated pattern; `SINGLE` = a one-off anchor.
CompositionStrength = Literal["STRONG", "SINGLE"]

#: Generous ceilings. They exist so a runaway generation cannot mint an
#: unbounded kit section — not to trim an honest brief. A brief that trips one
#: is refused (and the kit publishes briefless), so they are set well above any
#: plausible per-brand output.
_MAX_COMPOSITIONS = 24
_MAX_PALETTE_ENTRIES = 48
_MAX_BANDS = 48
_MAX_CONSTRAINTS = 40
_MAX_RECIPES = 48
_MAX_DIAGNOSTICS = 40
_MAX_TEXT = 800


class BriefRefused(Exception):
    """The brief could not be produced or could not be trusted.

    Carries a human-readable `reason` that goes verbatim into the ingestion
    diagnostic, because "why is this kit briefless?" must be answerable from the
    kit's own record.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


Text = Annotated[str, StringConstraints(min_length=1, max_length=_MAX_TEXT)]


class BriefDiagnostic(_Section):
    """Something the brief agent saw that had no token to land on.

    The token law forbids minting a name or smuggling a hex value, so an
    observation the kit cannot express goes here for a human to act on. This is
    the honest overflow channel, not a second rules section.
    """

    observation: Text
    reason: Text


class Characterization(_Section):
    """The 2–3 word anchor every other section must agree with."""

    words: list[Annotated[str, StringConstraints(min_length=1, max_length=40)]] = Field(
        min_length=2, max_length=3
    )
    support: Text
    confidence: Confidence = "low"


class ChromaticMoment(_Section):
    """The one place the saturated brand color goes big — or the finding that
    there is no such peak (`quiet=True`), which is a deployment rule too."""

    element: Text | None = None
    token: TokenRef | None = None
    surrounding: Text | None = None
    quiet: bool = False
    confidence: Confidence = "low"


class SignatureComposition(_Section):
    name: Text
    structure: Text
    strength: CompositionStrength
    confidence: Confidence = "low"


class PaletteApplication(_Section):
    """One palette token and the SCOPE it is allowed to occupy."""

    token: TokenRef
    scope: PaletteScope
    evidence: Text
    confidence: Confidence = "low"


class BackgroundBand(_Section):
    """One band of the observed background sequence, named by its surface token.

    `token` may be null when the band's color has no kit token — the observation
    then belongs in `diagnostics`, and the band still holds its place in the
    sequence rather than silently vanishing from the rhythm.
    """

    index: int = Field(ge=0)
    token: TokenRef | None = None
    note: Text | None = None


class BackgroundRhythm(_Section):
    bands: list[BackgroundBand] = Field(default_factory=list, max_length=_MAX_BANDS)
    ratio_summary: Text | None = None
    differentiation: Literal["chromatic", "compositional"] | None = None
    confidence: Confidence = "low"


class TypographicPosture(_Section):
    case_posture: Text | None = None
    scale_temperament: Literal["restrained", "substantial", "stadium"] | None = None
    signature_moves: list[Text] = Field(default_factory=list, max_length=16)
    tokens: list[TokenRef] = Field(default_factory=list, max_length=24)
    confidence: Confidence = "low"


class ImageryPosture(_Section):
    diet: (
        Literal["photography-led", "product-ui-led", "text-forward", "abstract", "absent"]
        | None
    ) = None
    slots: list[Text] = Field(default_factory=list, max_length=16)
    #: Regions where imagery is demonstrably ABSENT. An absence is a rule.
    absences: list[Text] = Field(default_factory=list, max_length=16)
    confidence: Confidence = "low"


class BriefConstraint(_Section):
    """A hard law, written so a reviewer can point at a violation."""

    rule: Text
    scope: Text | None = None
    confidence: Confidence = "low"


class ComponentRecipe(_Section):
    """One measured component variant, transcribed in token names.

    A design agent uses these verbatim, which is exactly why every slot is a
    token reference: a raw value here becomes a raw value in a generated node.
    A measured shape with no token to land on goes in `unmapped` (prose), so the
    recipe stays honest without inventing a name.
    """

    component: Annotated[str, StringConstraints(min_length=1, max_length=60)]
    variant: Annotated[str, StringConstraints(min_length=1, max_length=60)]
    radius: TokenRef | None = None
    padding: TokenRef | None = None
    border: TokenRef | None = None
    shadow: TokenRef | None = None
    background: TokenRef | None = None
    text: TokenRef | None = None
    unmapped: list[Text] = Field(default_factory=list, max_length=12)
    confidence: Confidence = "low"


class BrandBrief(_Section):
    """`BrandBrief@1` — the whole kit section."""

    schema_version: Literal[1] = BRIEF_SCHEMA_VERSION
    characterization: Characterization
    chromatic_moment: ChromaticMoment
    signature_compositions: list[SignatureComposition] = Field(
        default_factory=list, max_length=_MAX_COMPOSITIONS
    )
    palette_application: list[PaletteApplication] = Field(
        default_factory=list, max_length=_MAX_PALETTE_ENTRIES
    )
    background_rhythm: BackgroundRhythm
    typographic_posture: TypographicPosture
    imagery_posture: ImageryPosture
    constraints: list[BriefConstraint] = Field(
        default_factory=list, max_length=_MAX_CONSTRAINTS
    )
    component_recipes: list[ComponentRecipe] = Field(
        default_factory=list, max_length=_MAX_RECIPES
    )
    diagnostics: list[BriefDiagnostic] = Field(
        default_factory=list, max_length=_MAX_DIAGNOSTICS
    )


#: Every group of `brand_kit_json.tokens` whose keys are usable token names.
_TOKEN_GROUPS = (
    "colors",
    "typography",
    "numbers",
    "spacing",
    "radii",
    "stroke_widths",
    "opacity",
    "shadows",
    "effects",
    "assets",
    "aliases",
    "styles",
)


def kit_token_names(brand_kit: dict[str, Any]) -> set[str]:
    """Every token name this kit actually carries — the token law's dictionary.

    Aliases count: `accent.primary` is a name a human reads on the kit page, so
    a brief may speak it. Nothing else does — a name outside this set is a name
    the kit cannot resolve, and a rule built on it would be unenforceable.
    """
    tokens = brand_kit.get("tokens") or {}
    names: set[str] = set()
    for group in _TOKEN_GROUPS:
        entries = tokens.get(group)
        if isinstance(entries, dict):
            names.update(str(name) for name in entries)
    return names


def token_references(brief: BrandBrief) -> Iterator[tuple[str, str]]:
    """`(where, token)` for every token reference the brief makes."""
    if brief.chromatic_moment.token:
        yield ("chromatic_moment.token", brief.chromatic_moment.token)
    for index, entry in enumerate(brief.palette_application):
        yield (f"palette_application[{index}].token", entry.token)
    for index, band in enumerate(brief.background_rhythm.bands):
        if band.token:
            yield (f"background_rhythm.bands[{index}].token", band.token)
    for index, token in enumerate(brief.typographic_posture.tokens):
        yield (f"typographic_posture.tokens[{index}]", token)
    for index, recipe in enumerate(brief.component_recipes):
        for slot in ("radius", "padding", "border", "shadow", "background", "text"):
            value = getattr(recipe, slot)
            if value:
                yield (f"component_recipes[{index}].{slot}", value)


def validate_brief(payload: Any, *, token_names: set[str]) -> BrandBrief:
    """Parse and token-check one agent output, or refuse it.

    Refusal is a first-class outcome: the caller publishes the kit briefless with
    a diagnostic. Never let a half-trusted brief through — it would poison every
    page the brand generates from then on.
    """
    if not isinstance(payload, dict):
        raise BriefRefused(
            f"the brief agent returned {type(payload).__name__}, not a BrandBrief@1 object"
        )
    try:
        brief = BrandBrief.model_validate(payload)
    except ValidationError as error:
        raise BriefRefused(f"the brief failed BrandBrief@1 validation: {_summarize(error)}") from error

    unresolved = [
        f"{where}={token!r}"
        for where, token in token_references(brief)
        if token not in token_names
    ]
    if unresolved:
        raise BriefRefused(
            "the brief names tokens this kit does not carry: " + ", ".join(sorted(unresolved))
        )
    return brief


def _summarize(error: ValidationError, *, limit: int = 3) -> str:
    """A short, honest reason string — enough to name the offending value.

    Pydantic reports a pattern failure as "String should match pattern ...",
    which tells a reader nothing about WHICH value was rejected; the raw input is
    appended so a diagnostic can say `#00A37A` out loud.
    """
    parts: list[str] = []
    for detail in error.errors()[:limit]:
        location = ".".join(str(part) for part in detail["loc"])
        message = detail["msg"]
        given = detail.get("input")
        if isinstance(given, str) and given:
            message = f"{message} (got {given!r})"
        parts.append(f"{location}: {message}")
    remaining = len(error.errors()) - len(parts)
    if remaining > 0:
        parts.append(f"and {remaining} more")
    return "; ".join(parts)
