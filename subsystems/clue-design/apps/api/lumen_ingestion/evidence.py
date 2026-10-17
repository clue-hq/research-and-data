"""`BrandEvidence` — the raw, source-agnostic intermediate representation (IR)
that capture code (website/PDF/upload) emits and the normalizer consumes.

Everything here is evidence *observed* about a brand, not yet a Brand Kit. The
normalizer (see `normalizer/`) turns a `BrandEvidence` bundle into a validated
engine Brand Kit. Schema version is 1.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator


def _normalize_hex(value: str) -> str:
    text = value.strip()
    if not text.startswith("#"):
        text = "#" + text
    body = text[1:]
    if len(body) == 3:
        body = "".join(ch * 2 for ch in body)
    elif len(body) == 4:
        body = "".join(ch * 2 for ch in body)
    if len(body) not in (6, 8):
        raise ValueError(f"invalid hex color {value!r}")
    try:
        int(body, 16)
    except ValueError as error:
        raise ValueError(f"invalid hex color {value!r}") from error
    return "#" + body.upper()


class EvidencePointer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["website", "pdf", "upload", "derived"]
    locator: str
    detail: str | None = None


class ColorEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str
    weight: float = 1.0
    theme: Literal["light", "dark"] = "light"
    role_hints: list[str] = []
    name: str | None = None
    pointer: EvidencePointer

    @field_validator("value")
    @classmethod
    def _hex(cls, value: str) -> str:
        return _normalize_hex(value)

    @field_validator("weight")
    @classmethod
    def _weight(cls, value: float) -> float:
        if value < 0:
            raise ValueError("weight must be >= 0")
        return value


class TypeSample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    family: str | None = None
    weight: int | None = None
    size_px: float | None = None
    line_height: float | None = None
    letter_spacing: float | None = None
    #: A rendered heading's own text colour, the colour behind it (composited up to the first
    #: opaque background; None over an image) and its box area. The heading ink comes from these.
    color: str | None = None
    background: str | None = None
    area: float | None = None
    pointer: EvidencePointer
    #: Which rendered sample it came from (responsive brand type reads the same one at each width).
    sample_index: int | None = None

    @field_validator("color", "background")
    @classmethod
    def _colors(cls, value: str | None) -> str | None:
        return _normalize_hex(value) if value else value


class FontFaceEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weight: int | None = None
    style: str = "normal"
    asset_id: str | None = None
    source_url: str | None = None
    format: str | None = None


class FontEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    family: str
    role_hint: Literal["heading", "body", "unknown"] = "unknown"
    faces: list[FontFaceEvidence] = []
    fallback_stack: list[str] = []
    license_hint: str | None = None
    pointer: EvidencePointer


class LogoEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str
    color_mode_hint: Literal["full_color", "one_color", "reversed", "dark", "light"] | None = None
    usage_hint: Literal["primary", "mark", "wordmark"] | None = None
    width: float | None = None
    height: float | None = None
    background_hint: str | None = None
    # Description-engine metadata (brandkit ingestion v1 slice 3). Additive and
    # optional; schema_version stays 1 and existing evidence deserializes
    # unchanged (all default None/[]).
    title: str | None = None
    description: str | None = None
    usage_note: str | None = None
    tags: list[str] = []
    source_occurrences: list[dict] = []
    pointer: EvidencePointer

    @field_validator("background_hint")
    @classmethod
    def _bg(cls, value: str | None) -> str | None:
        return _normalize_hex(value) if value else value


class ImageEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_id: str
    width: int | None = None
    height: int | None = None
    transparency: bool | None = None
    dominant_colors: list[str] = []
    kind_hint: Literal["photo", "illustration", "screenshot", "icon", "og_image"] | None = None
    # Description-engine metadata (brandkit ingestion v1 slice 3). Additive and
    # optional; schema_version stays 1 and existing evidence deserializes
    # unchanged (all default None/[]).
    title: str | None = None
    description: str | None = None
    usage_note: str | None = None
    tags: list[str] = []
    source_occurrences: list[dict] = []
    pointer: EvidencePointer

    @field_validator("dominant_colors")
    @classmethod
    def _dominant(cls, value: list[str]) -> list[str]:
        return [_normalize_hex(item) for item in value]


class DeclaredRoleEvidence(BaseModel):
    """A role the site DECLARED, in its own stylesheet, via a named custom property.

    Clone-fidelity F0.3. ``--base-color-brand--green: #30d8a7`` is not a swatch to be
    clustered with everything else on the page — it is the site stating what its brand color
    is. The normalizer applies these as direct role assignments (basis ``declared``) that
    outrank the clustered candidate; the name→role table and its refusals live in
    ``capture/declared_roles.py``.

    Additive and optional: ``schema_version`` stays 1 and pre-F0.3 evidence deserializes
    unchanged (the list defaults empty, which is also what every non-website capture emits).
    """

    model_config = ConfigDict(extra="forbid")

    #: One of the four anchors `normalizer.roles.assign_light_roles` derives the kit from.
    role: Literal["surface.page", "text.primary", "surface.brand", "surface.accent"]
    #: The custom property that stated it, `--` prefix included.
    property_name: str
    value: str
    pointer: EvidencePointer

    @field_validator("value")
    @classmethod
    def _hex(cls, value: str) -> str:
        return _normalize_hex(value)


class StateStyle(BaseModel):
    """One interaction state, read off the site's own CSS rule (clone-fidelity F0.3).

    A clone that renders a site's buttons in the right color but does nothing on hover is
    visibly not the site. These are the site's *declared* states — ``.btn:hover { … }`` — not
    a guess derived from the resting style, and only the properties the rule actually sets
    are recorded (everything else stays ``None``, never a fabricated default).

    Evidence only: F0.3 deliberately mints no kit tokens from these. The design-brief agent
    and the F2 fragment harvest are the consumers.
    """

    model_config = ConfigDict(extra="forbid")

    #: The selector verbatim, e.g. ``.btn:hover`` — F2 matches harvested markup against it.
    selector: str
    state: Literal["hover", "focus", "focus-visible", "active", "disabled"]
    #: ``dark`` when the rule sits inside ``@media (prefers-color-scheme: dark)``.
    scheme: Literal["light", "dark"] = "light"
    background: str | None = None
    color: str | None = None
    border_color: str | None = None
    #: Kept as the declared CSS text: a shadow is a composite value the kit models
    #: separately, and re-serializing it here would lose more than it gained.
    box_shadow: str | None = None
    opacity: float | None = None
    text_decoration: str | None = None
    pointer: EvidencePointer

    @field_validator("background", "color", "border_color")
    @classmethod
    def _colors(cls, value: str | None) -> str | None:
        return _normalize_hex(value) if value else value


class NumberSample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["spacing", "radius", "stroke_width", "opacity"]
    value: float
    weight: float = 1.0
    role_hints: list[str] = []
    pointer: EvidencePointer


class ShadowSample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float
    y: float
    blur: float
    spread: float = 0.0
    color: str = "#000000"
    opacity: float = 0.15
    pointer: EvidencePointer

    @field_validator("color")
    @classmethod
    def _color(cls, value: str) -> str:
        return _normalize_hex(value)


class SurfaceShape(BaseModel):
    """One measured visual variant of a brand surface (design-brief slice 2).

    The kit's number tokens carry the brand's *scale*; this carries the brand's
    *components* — the exact shape of the buttons, cards and inputs the site
    actually draws, in the terms the design-brief agent needs to write component
    recipes (slice 3). Structural only: ``fill`` is read from what is painted
    (a background, a border, or neither), never guessed from a class name.
    """

    model_config = ConfigDict(extra="forbid")

    surface: Literal[
        "button", "card", "input", "chip", "nav", "divider", "image", "focus_ring"
    ]
    variant: str
    count: int = 1
    fill: Literal["solid", "outline", "ghost"] = "solid"
    radius_px: list[float] = []
    pill: bool = False
    padding_px: list[float] = []
    border_width_px: list[float] = []
    border_style: str | None = None
    border_color: str | None = None
    shadow: str | None = None
    background: str | None = None
    text_color: str | None = None
    font: str | None = None
    pointer: EvidencePointer

    @field_validator("border_color", "background", "text_color")
    @classmethod
    def _colors(cls, value: str | None) -> str | None:
        return _normalize_hex(value) if value else value


class SectionBackground(BaseModel):
    """One band of the page's background rhythm, in DOM order (slice 2).

    Not a token — the *sequence* is the finding ("brand, then white, then near-
    black"), and slice 3's brief renders it as ``background_rhythm``.
    """

    model_config = ConfigDict(extra="forbid")

    index: int
    background: str | None = None
    gradient: bool = False
    has_image: bool = False
    ink: str | None = None
    height_px: float = 0.0
    pointer: EvidencePointer

    @field_validator("background", "ink")
    @classmethod
    def _bg(cls, value: str | None) -> str | None:
        return _normalize_hex(value) if value else value


class StyleLook(BaseModel):
    """One look of a measured element style (Wave 2 A9): what a browser computed for it.

    The rest look carries everything measured; a state's look carries only what changed from rest,
    with `"none"` for a shadow, transform or filter the state removes, and `#00000000` for a colour
    the state clears. Colours are normalized hex.
    """

    model_config = ConfigDict(extra="forbid")

    background: str | None = None
    color: str | None = None
    #: The colour of the element that paints the words, when it is not the element itself.
    label_color: str | None = None
    border_color: str | None = None
    border_width: list[float] = []
    border_style: str | None = None
    radius: list[float] = []
    pill: bool | None = None
    padding: list[float] = []
    height: float | None = None
    gap: float | None = None
    font_family: str | None = None
    font_size: float | None = None
    font_weight: float | None = None
    #: px, as computed.
    line_height: float | None = None
    #: px, as computed.
    letter_spacing: float | None = None
    text_transform: str | None = None
    decoration_line: str | None = None
    decoration_thickness: str | None = None
    underline_offset: str | None = None
    box_shadow: str | None = None
    opacity: float | None = None
    transform: str | None = None
    filter: str | None = None
    cursor: str | None = None
    outline_color: str | None = None
    outline_width: float | None = None
    outline_style: str | None = None
    outline_offset: float | None = None
    #: The browser's own focus ring showed: the site styles no focus look of its own.
    browser_focus_ring: bool | None = None
    icon_transform: str | None = None
    icon_color: str | None = None
    icon_opacity: float | None = None

    @field_validator("background", "color", "label_color", "border_color", "outline_color", "icon_color")
    @classmethod
    def _colors(cls, value: str | None) -> str | None:
        return _normalize_hex(value) if value else value


class StyleTransition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target: Literal["self", "label", "icon"]
    property: str
    duration_ms: float
    easing: str = "ease"
    delay_ms: float = 0.0


class StyleIcon(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["svg", "glyph", "img"]
    position: Literal["start", "end"] = "end"
    glyph: str | None = None
    #: Cleaned to drawing elements only (`capture.motion.clean_icon_svg`).
    svg: str | None = None
    width: float | None = None
    height: float | None = None


class MeasuredStyle(BaseModel):
    """One visual variant of an element class, in every state the capture could reach (Wave 2 A9).

    `variant` is the same look-keyed `<fill>.<hex>` name (`solid.047464`) the shape records and the
    brief's recipes use, so a recipe and its measurement join by `(surface, variant)`. `probed` says
    how the hover was read: by a real pointer, forced through CSS (the element was covered), or not
    at all (rest only, beyond the state pass's caps or time).
    """

    model_config = ConfigDict(extra="forbid")

    surface: Literal["button", "link", "nav_link", "card", "chip", "input", "image"]
    variant: str
    count: int = 1
    probed: Literal["pointer", "forced", "rest-only"] = "rest-only"
    rest: StyleLook = StyleLook()
    hover: StyleLook | None = None
    pressed: StyleLook | None = None
    focus: StyleLook | None = None
    disabled: StyleLook | None = None
    transitions: list[StyleTransition] = []
    icon: StyleIcon | None = None
    pointer: EvidencePointer


class KeyframeStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offset: float
    declarations: dict[str, str] = {}


class MeasuredAnimation(BaseModel):
    """A CSS animation running on the page, with its `@keyframes` from the captured stylesheets."""

    model_config = ConfigDict(extra="forbid")

    name: str
    duration_ms: float
    easing: str = "ease"
    delay_ms: float = 0.0
    iterations: str = "1"
    direction: str = "normal"
    fill_mode: str = "none"
    count: int = 1
    where: str = ""
    frames: list[KeyframeStep] = []
    pointer: EvidencePointer


class MeasuredReveal(BaseModel):
    """An entrance reveal whose motion is CSS (a script only adds the class that starts it)."""

    model_config = ConfigDict(extra="forbid")

    where: str
    count: int = 1
    from_opacity: float | None = None
    from_transform: str | None = None
    duration_ms: float = 0.0
    easing: str = "ease"
    delay_ms: float = 0.0
    trigger: list[str] = []
    pointer: EvidencePointer


class ScriptedMotion(BaseModel):
    """Motion only a script can make (a canvas, a playing video, inline styles rewritten every
    frame): recorded so a page can say it exists, never reproduced."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["scripted", "canvas", "video"]
    where: str
    pointer: EvidencePointer


class MotionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    animations: list[MeasuredAnimation] = []
    reveals: list[MeasuredReveal] = []
    scripted: list[ScriptedMotion] = []


class GeometryEvidence(BaseModel):
    """Structured shape evidence retained for the design-brief agent.

    Additive and optional; ``schema_version`` stays 1 and pre-slice-2 evidence
    deserializes unchanged (both lists default empty).
    """

    model_config = ConfigDict(extra="forbid")

    surfaces: list[SurfaceShape] = []
    background_sequence: list[SectionBackground] = []
    styles: list[MeasuredStyle] = []
    motion: MotionEvidence = MotionEvidence()


class RuleEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal[
        "clearspace",
        "min_size",
        "combination",
        "dont",
        "tone",
        "imagery",
        "iconography",
        "accessibility",
        "print",
    ]
    text: str
    numeric_value: float | None = None
    pointer: EvidencePointer


class NarrativeEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brand_name: str | None = None
    url: str | None = None
    tagline: str | None = None
    summary_facts: list[str] = []
    text_excerpt: str | None = None

    @field_validator("text_excerpt")
    @classmethod
    def _excerpt(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value[:4000]


class _HexEntry(BaseModel):
    """Base for render-truth entries: a normalized hex color plus per-kind fields."""

    model_config = ConfigDict(extra="forbid")

    hex: str

    @field_validator("hex")
    @classmethod
    def _hex_normalized(cls, value: str) -> str:
        return _normalize_hex(value)


class CensusCluster(_HexEntry):
    """One perceptually-merged color family from the rendered-page pixel census."""

    share: float  # fraction of unmasked chrome pixels


class RegionColorFamily(_HexEntry):
    """Modal rendered color of a role region (e.g. buttons), with how many regions agree."""

    count: int


class AccentTextFamily(_HexEntry):
    """A chromatic text color (links/eyebrows/tabs) that differs from the body text."""

    count: int


class GradientStopFamily(_HexEntry):
    """A computed gradient-stop color, weighted by the page-area fraction it paints."""

    area_fraction: float


class RenderTruth(BaseModel):
    """What the rendered page actually showed — the election authority for colors.

    Produced by :mod:`lumen_ingestion.census` from the rendered tier's screenshot
    plus the render probe. ``None``/absent on every pre-probe bundle and every
    non-website capture, in which case the normalizer keeps the evidence-cluster
    election. Stylesheet mentions can NAME colors; only this can elect them.
    """

    model_config = ConfigDict(extra="forbid")

    page_clusters: list[CensusCluster] = []
    fold_clusters: list[CensusCluster] = []
    button_families: list[RegionColorFamily] = []
    accent_text: list[AccentTextFamily] = []
    gradient_stops: list[GradientStopFamily] = []
    body_bg: str | None = None
    body_text: str | None = None
    resolved_tokens: dict[str, str] = {}
    masked_fraction: float = 0.0
    #: Fraction of the first viewport covered by <canvas> — a large value plus a
    #: near-monochrome census means a WebGL hero likely did not paint headless,
    #: and the kit must say so instead of pretending the page is white.
    canvas_viewport_fraction: float = 0.0


class TypeWidth(BaseModel):
    """Responsive brand type: the type samples as drawn at one narrower window width."""

    model_config = ConfigDict(extra="forbid")

    width: int
    type_samples: list[TypeSample] = []


class TypeWidths(BaseModel):
    """The capture's own width and the type samples at each narrower width it read."""

    model_config = ConfigDict(extra="forbid")

    capture_width: int
    widths: list[TypeWidth] = []


class BrandEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    source: dict
    description_progress: dict = {}
    colors: list[ColorEvidence] = []
    type_samples: list[TypeSample] = []
    fonts: list[FontEvidence] = []
    logos: list[LogoEvidence] = []
    images: list[ImageEvidence] = []
    numbers: list[NumberSample] = []
    shadows: list[ShadowSample] = []
    # Source-truth styling (clone-fidelity F0.3). Both additive and both empty for every
    # pre-F0.3 bundle and every non-website capture, so `schema_version` stays 1.
    declared_roles: list[DeclaredRoleEvidence] = []
    state_styles: list[StateStyle] = []
    # Rendered-pixel election authority (Phase-1 brand-color overhaul). Additive
    # and None for every pre-probe bundle and every non-website capture, so
    # `schema_version` stays 1 and old bundles keep the cluster election.
    render_truth: RenderTruth | None = None
    # Responsive brand type: additive and None for every earlier bundle and every non-website
    # capture, so `schema_version` stays 1.
    type_widths: TypeWidths | None = None
    geometry: GeometryEvidence = GeometryEvidence()
    rules: list[RuleEvidence] = []
    screenshots: list[str] = []
    narrative: NarrativeEvidence = NarrativeEvidence()
