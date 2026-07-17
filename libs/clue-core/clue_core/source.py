"""The source capability manifest (M0.2).

``source_manifest`` (staged-flow §7a) sits parallel to the field registry: fields say
*what to know*; a manifest says *where to learn it and how much to trust each place*.
Every source — structured API, scraper, search, video host, podcast index, journal —
registers one. The Source Registry (M4.2) holds the rows; M0.2 defines the shape.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from annotated_types import Ge
from pydantic import BaseModel, ConfigDict, model_validator

from clue_core.enums import EntityScope, IdentityBinding, Modality
from clue_core.field import is_field_key_or_class
from clue_core.primitives import CostCents, SourceTier


class SourceManifest(BaseModel):
    """A source's declared capabilities (staged-flow §7a)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_key: str  # "arxiv" | "youtube" | "apollo" | "g2" | "substack" ...
    modality: Modality
    entity_scope: EntityScope
    yields: tuple[str, ...] = ()  # field_keys / field-classes it can populate
    tier: SourceTier
    cost_cents: CostCents = Decimal(0)
    # Non-negative, matching the M4.2 source_manifest CHECK (so a bad value fails at construction
    # with a typed ValidationError, consistent with tier/cost_cents — not a raw IntegrityError).
    latency_ms: Annotated[int, Ge(0)] | None = None
    geo_coverage: tuple[str, ...] = ()  # region codes, or empty == unspecified/global
    freshness_profile: str | None = None  # e.g. "realtime" | "daily" | "quarterly"
    identity_binding_strength: IdentityBinding | None = None  # how tightly data ties to an entity

    @model_validator(mode="after")
    def _check_yields(self) -> SourceManifest:
        invalid = [y for y in self.yields if not is_field_key_or_class(y)]
        if invalid:
            raise ValueError(f"yields must be field-keys or field-classes; invalid: {invalid}")
        return self
