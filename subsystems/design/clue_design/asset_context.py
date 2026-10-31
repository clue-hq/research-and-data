"""Versioned asset analysis contract; source evidence is supplied, never model-authored."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = 1
PROMPT_VERSION = "asset-context-v1"

CreativeType = Literal[
    "ad",
    "logo",
    "background",
    "product_image",
    "product_screenshot",
    "photo",
    "illustration",
    "icon",
    "badge_seal",
    "other",
    "unknown",
]
#: What the describing model may answer. Only code calls an asset an ad: a harvested ad is one
#: by where it came from, and a person may mark any asset as one (spec 2026-10-30, reference ads).
AI_CREATIVE_TYPES: tuple[str, ...] = tuple(value for value in get_args(CreativeType) if value != "ad")

UsageRole = Literal[
    "section_background", "hero_image", "card_image", "inline_image", "reference_only"
]
LogoRelationship = Literal["own_brand", "customer", "partner", "third_party", "unknown"]
AssetSource = Literal["website", "linkedin_ad", "user_upload", "generated", "pdf", "unknown"]


class ContextModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceOccurrence(ContextModel):
    """One supplied placement; identical pixels never establish a brand relationship."""

    occurrence_id: str = Field(min_length=1)
    source: AssetSource
    brand_kit_id: str | None = None
    page_url: str | None = None
    locator: str | None = None
    surrounding_text: str | None = None
    alt: str | None = None
    placement: str | None = None
    creative_id: str | None = None
    ad_permalink: str | None = None
    advertiser: str | None = None
    headline: str | None = None
    commentary: str | None = None
    user_note: str | None = None


class VisualObservations(ContextModel):
    subjects: list[str]
    composition: str
    colors: list[str]
    readable_text: list[str]
    typography: str
    logo_placement: str
    negative_space: str
    transparency: str


class SourceInterpretation(ContextModel):
    occurrence_id: str
    observed_usage: str
    logo_relationship: LogoRelationship
    relationship_evidence: str
    messaging_angle: str
    tone: str
    cta: str
    visual_hierarchy: str
    copy_density: str
    product_or_use_case_hypothesis: str
    audience_hypothesis: str
    design_patterns: list[str]
    uncertainties: list[str]


class AssetAnalysis(ContextModel):
    """One model response produces both the reference and the detailed agent view."""

    creative_type: CreativeType
    usage_roles: list[UsageRole]
    classification_reason: str
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1)
    usage: str = Field(min_length=1)
    avoid_when: str
    placement: str
    tags: list[str]
    observed: VisualObservations
    source_interpretations: list[SourceInterpretation]
    uncertainties: list[str]
    reuse_boundary: str


class AssetOverrides(ContextModel):
    """Omission preserves a field; reset_fields explicitly returns it to the suggestion."""

    title: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=12000)
    usage: str | None = Field(default=None, max_length=12000)
    avoid_when: str | None = Field(default=None, max_length=12000)
    placement: str | None = Field(default=None, max_length=12000)
    tags: list[str] | None = None
    creative_type: CreativeType | None = None
    usage_roles: list[UsageRole] | None = None
    user_note: str | None = Field(default=None, max_length=4000)


OVERRIDE_FIELDS = frozenset(AssetOverrides.model_fields)


class AssetContextPatch(AssetOverrides):
    reset_fields: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_resets(self) -> AssetContextPatch:
        resets = set(self.reset_fields)
        assigned = self.model_fields_set - {"reset_fields"}
        if not resets <= OVERRIDE_FIELDS or resets & assigned:
            raise ValueError("reset fields must be known and cannot also be assigned")
        return self


def fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def merge_occurrences(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Latest evidence for the same occurrence wins; other brands/placements survive."""
    merged = {}
    for group in groups:
        for raw in group:
            occurrence = SourceOccurrence.model_validate(raw)
            merged[occurrence.occurrence_id] = occurrence.model_dump(mode="json")
    return [merged[key] for key in sorted(merged)]


def validate_analysis(value: dict[str, Any], occurrences: list[dict[str, Any]]) -> dict[str, Any]:
    analysis = AssetAnalysis.model_validate(value).model_dump()
    expected = {item["occurrence_id"] for item in occurrences}
    actual = [item["occurrence_id"] for item in analysis["source_interpretations"]]
    if set(actual) != expected or len(actual) != len(expected):
        raise ValueError("source interpretations must match supplied occurrences exactly")
    return analysis


def effective_context(row: dict[str, Any], *, harvested: bool = False) -> dict[str, Any]:
    """Legacy scalar columns remain compatible, with richer fields added at the read seam.

    The shown type follows one rule (spec 2026-10-30, reference ads §5.2): the person's choice;
    else ``ad`` for an asset the Adyntel harvest brought in (``harvested``); else ``other`` where
    the model said ``ad``; else the model's type.
    """
    generated = row.get("analysis") or {}
    overrides = row.get("overrides") or {}
    result = {**row, **generated, **overrides}
    if "creative_type" not in overrides:
        if harvested:
            result["creative_type"] = "ad"
        elif result.get("creative_type") == "ad":
            result["creative_type"] = "other"
    result["creative_type"] = result.get("creative_type") or "unknown"
    result["usage_roles"] = result.get("usage_roles") or []
    result["classification_origin"] = "human" if "creative_type" in overrides else "ai"
    result["source_occurrences"] = (row.get("analysis_input") or {}).get("source_occurrences", [])
    result["agent_context"] = {
        "analysis_input": row.get("analyzed_input") or {},
        "observed": generated.get("observed"),
        "source_interpretations": generated.get("source_interpretations", []),
        "guidance": {key: result.get(key) for key in ("usage", "avoid_when", "placement")},
        "uncertainties": generated.get("uncertainties", []),
        "reuse_boundary": generated.get("reuse_boundary"),
        "preview": (row.get("analyzed_input") or {}).get("preview"),
    }
    return result
