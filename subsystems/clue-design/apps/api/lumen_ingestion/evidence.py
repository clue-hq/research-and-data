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
    pointer: EvidencePointer


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
    pointer: EvidencePointer

    @field_validator("dominant_colors")
    @classmethod
    def _dominant(cls, value: list[str]) -> list[str]:
        return [_normalize_hex(item) for item in value]


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


class BrandEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    source: dict
    colors: list[ColorEvidence] = []
    type_samples: list[TypeSample] = []
    fonts: list[FontEvidence] = []
    logos: list[LogoEvidence] = []
    images: list[ImageEvidence] = []
    numbers: list[NumberSample] = []
    shadows: list[ShadowSample] = []
    rules: list[RuleEvidence] = []
    screenshots: list[str] = []
    narrative: NarrativeEvidence = NarrativeEvidence()
