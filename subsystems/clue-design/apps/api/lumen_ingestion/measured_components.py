"""`MeasuredComponents@1` — every measured style of the brand's site, in this kit's token names.

A code-owned kit section (`brand_kit_json.measured_components`, Wave 2 A9), the sibling of the
model-written `BrandBrief@1` and the arithmetic `BrandGrammarAudit@1`: it rides the kit the same way
(attached after the engine round trip, carried across every re-validation by
`lumen_api.brand_kit_sections`) and overlaps neither. The brief's `component_recipes` hold what the
model judged — which styles are page buttons, notes, confidence. This holds what the capture
MEASURED, as a complete recipe per `(component, variant)`: every slot of the rest look and of each
state names a token of this kit, and so does every transition's timing and the icon. site-kit joins
the two by `(component, variant)`.

No model writes it, so nothing here is judgement: the shapes below and the token law (every name
resolves in this kit) are checked, and a section that fails either is dropped with a diagnostic
(LUMI0608), never published half-true.
"""

from __future__ import annotations

from typing import Annotated, Any, Iterator, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from .brief import TOKEN_NAME_PATTERN

MEASURED_COMPONENTS_SCHEMA_VERSION = 1

TokenRef = Annotated[str, StringConstraints(pattern=TOKEN_NAME_PATTERN, max_length=160)]
Text = Annotated[str, StringConstraints(min_length=1, max_length=400)]
#: The slot vocabulary `normalizer/component_tokens.py` writes; site-kit's `looks.ts` reads the same.
SLOT_PATTERN = (
    r"^(fill|label|border|border-width(-(top|right|bottom|left))?|border-style|radius(-(tl|tr|br|bl))?"
    r"|padding-(top|right|bottom|left)|height|gap|font|case|decoration|decoration-thickness|underline-offset"
    r"|shadow(-\d+)?|opacity|transform|filter|cursor|outline|outline-width|outline-style|outline-offset"
    r"|icon-color|icon-transform|icon-opacity)$"
)
Slot = Annotated[str, StringConstraints(pattern=SLOT_PATTERN)]
State = Literal["hover", "pressed", "focus", "disabled"]
#: A measured style's name (Task X2 `look_names`, founder Q-A9-6): `<fill>.<its colour>` — six or eight
#: hex digits, or `none` — with a 4-hex suffix (12 in the rare collision) when two looks of one
#: component share the colour. Never the old rank form `solid.2`.
VARIANT_PATTERN = r"^(solid|outline|ghost)\.([0-9a-f]{6}|[0-9a-f]{8}|none)(\.([0-9a-f]{4}|[0-9a-f]{12}))?$"


class MeasuredComponentsRefused(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MeasuredTransition(_Section):
    target: Literal["self", "label", "icon"]
    property: Annotated[str, StringConstraints(pattern=r"^(all|[a-z-]{1,60})$")]
    duration: TokenRef
    easing: TokenRef
    delay: TokenRef | None = None


class MeasuredIcon(_Section):
    token: TokenRef
    position: Literal["start", "end"]


class MeasuredRecipe(_Section):
    component: Literal["button", "link", "nav_link", "card", "chip", "input", "image"]
    variant: Annotated[str, StringConstraints(pattern=VARIANT_PATTERN)]
    count: int = Field(ge=1)
    probed: Literal["pointer", "forced", "rest-only"]
    source: Text
    rest: dict[Slot, TokenRef] = {}
    states: dict[State, dict[Slot, TokenRef]] = {}
    motion: list[MeasuredTransition] = Field(default_factory=list, max_length=24)
    icon: MeasuredIcon | None = None
    browser_focus_ring: bool = False


class ScriptedNote(_Section):
    kind: Literal["scripted", "canvas", "video"]
    where: Text


class MeasuredMotion(_Section):
    animations: list[TokenRef] = Field(default_factory=list, max_length=12)
    reveals: list[TokenRef] = Field(default_factory=list, max_length=6)
    scripted: list[ScriptedNote] = Field(default_factory=list, max_length=12)


class MeasuredComponents(_Section):
    schema_version: Literal[1] = MEASURED_COMPONENTS_SCHEMA_VERSION
    source: Text
    styles: list[MeasuredRecipe] = Field(default_factory=list, max_length=40)
    motion: MeasuredMotion = MeasuredMotion()


def token_references(section: MeasuredComponents) -> Iterator[tuple[str, str]]:
    for index, style in enumerate(section.styles):
        where = f"styles[{index}]({style.component} {style.variant})"
        for slot, token in style.rest.items():
            yield f"{where}.rest.{slot}", token
        for state, slots in style.states.items():
            for slot, token in slots.items():
                yield f"{where}.{state}.{slot}", token
        for step, transition in enumerate(style.motion):
            for key in ("duration", "easing", "delay"):
                token = getattr(transition, key)
                if token:
                    yield f"{where}.motion[{step}].{key}", token
        if style.icon:
            yield f"{where}.icon", style.icon.token
    for index, token in enumerate(section.motion.animations):
        yield f"motion.animations[{index}]", token
    for index, token in enumerate(section.motion.reveals):
        yield f"motion.reveals[{index}]", token


def validate_measured_components(payload: Any, *, token_names: set[str]) -> dict:
    """The section as stored, or `MeasuredComponentsRefused` naming what is wrong."""
    try:
        section = MeasuredComponents.model_validate(payload)
    except ValidationError as error:
        first = error.errors()[0]
        raise MeasuredComponentsRefused(
            f"MeasuredComponents@1 validation failed at {'.'.join(str(p) for p in first['loc'])}: {first['msg']}"
        ) from error
    unresolved = sorted(f"{where}={token}" for where, token in token_references(section) if token not in token_names)
    if unresolved:
        raise MeasuredComponentsRefused("names tokens this kit does not carry: " + ", ".join(unresolved[:8]))
    return section.model_dump(mode="json")
