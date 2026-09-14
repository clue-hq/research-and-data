"""The scene family's compact, provider-neutral authoring handoff.

Validation proves internal consistency, not that an evidence excerpt is true or
an asset exists. The runtime checks catalog membership and available asset IDs;
the director must ground evidence in supplied or actually retrieved sources.
"""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

CREATIVE_DIRECTION_FILENAME = "creative-direction.json"
NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
ReferenceRole = Literal["source", "treatment", "composition"]


class DirectionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", serialize_by_alias=True)


class EvidenceReference(DirectionModel):
    id: NonEmpty
    source: NonEmpty
    excerpt: NonEmpty


class CopyBlock(DirectionModel):
    id: NonEmpty
    role: Literal["headline", "support", "cta", "attribution"]
    text: NonEmpty
    claim_kind: Literal["positioning", "assertion", "quote", "statistic"] = "positioning"
    evidence_refs: list[NonEmpty] = Field(default_factory=list)


class SourceRole(DirectionModel):
    asset_id: NonEmpty
    role: Literal["source", "treatment", "composition", "logo", "product"]


class PlaybookEvidenceRequirements(DirectionModel):
    """Declarative evidence prerequisites, never layout or CTA requirements."""

    source_role: Literal["source", "treatment", "composition", "logo", "product"] | None = None
    claim_kinds: list[Literal["assertion", "quote", "statistic"]] = Field(default_factory=list)
    attribution: bool = False


class LayerPlacement(DirectionModel):
    """Fractions of the artboard, converted to layout points by the author."""

    x: float = Field(ge=0, le=1, allow_inf_nan=False)
    y: float = Field(ge=0, le=1, allow_inf_nan=False)
    width: float = Field(gt=0, le=1, allow_inf_nan=False)
    height: float = Field(gt=0, le=1, allow_inf_nan=False)
    fit: Literal["contain", "cover"] = "contain"

    @model_validator(mode="after")
    def inside_artboard(self) -> Self:
        if self.x + self.width > 1.000001 or self.y + self.height > 1.000001:
            raise ValueError("layer placement extends outside the artboard")
        return self


class DirectionLayer(DirectionModel):
    id: NonEmpty
    kind: Literal["native_text", "native_geometry", "authentic_image", "generated_image"]
    purpose: NonEmpty
    copy_id: NonEmpty | None = None
    asset_id: NonEmpty | None = None
    reference_asset_ids: list[NonEmpty] = Field(default_factory=list)
    reference_roles: list[ReferenceRole] = Field(default_factory=list)
    placement: LayerPlacement

    @model_validator(mode="after")
    def compatible_sources(self) -> Self:
        if self.kind == "native_text" and not self.copy_id:
            raise ValueError("native_text requires copy_id")
        if self.copy_id and self.kind != "native_text":
            raise ValueError("copy must remain native_text")
        if self.kind == "authentic_image" and not self.asset_id:
            raise ValueError("authentic_image requires a real asset_id")
        if self.asset_id and self.kind not in {"authentic_image", "generated_image"}:
            raise ValueError("only image layers may bind an asset")
        if len(self.reference_asset_ids) != len(self.reference_roles):
            raise ValueError("reference_roles must align with reference_asset_ids")
        if self.reference_asset_ids and self.kind != "generated_image":
            raise ValueError("conditioning references belong to generated_image layers")
        if len(self.reference_asset_ids) > 4 or len(set(self.reference_asset_ids)) != len(
            self.reference_asset_ids
        ):
            raise ValueError("select at most four distinct references")
        return self


class ArtboardPlacement(DirectionModel):
    width: float = Field(gt=0, allow_inf_nan=False)
    height: float = Field(gt=0, allow_inf_nan=False)
    unit: Literal["px", "pt", "mm", "in"]


class CreativeDirection(DirectionModel):
    schema_version: Literal[1] = 1
    objective: NonEmpty
    audience: NonEmpty
    # Membership is owned by the selected knowledge view's catalog. Adding a
    # reviewed family is a catalog/skill change, never a new Python enum value.
    playbook: Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")]
    intent: Literal["native", "reuse", "edit", "close_companion", "new_concept", "palette_only"]
    copy_blocks: list[CopyBlock] = Field(alias="copy")
    evidence: list[EvidenceReference] = Field(default_factory=list)
    source_roles: list[SourceRole] = Field(default_factory=list)
    preserve: list[NonEmpty]
    vary: list[NonEmpty]
    layers: list[DirectionLayer] = Field(min_length=1)
    placement: ArtboardPlacement
    review_needs: list[NonEmpty] = Field(min_length=1)
    assumptions: list[NonEmpty] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent_handoff(self) -> Self:
        if not self.copy_blocks and self.intent != "edit":
            raise ValueError("a new creative requires copy; a scoped edit may omit it")
        for label, records in (
            ("copy", self.copy_blocks),
            ("evidence", self.evidence),
            ("layers", self.layers),
        ):
            if len({record.id for record in records}) != len(records):
                raise ValueError(f"duplicate {label} id")
        if {s.casefold() for s in self.preserve} & {s.casefold() for s in self.vary}:
            raise ValueError("a choice cannot be both preserved and varied")
        evidence_ids = {item.id for item in self.evidence}
        for item in self.copy_blocks:
            if not set(item.evidence_refs) <= evidence_ids:
                raise ValueError("copy points to unknown evidence")
            if item.claim_kind != "positioning" and not item.evidence_refs:
                raise ValueError("factual copy requires evidence references")
            if item.claim_kind == "quote" and not self._has_attribution(item):
                raise ValueError("quoted copy requires attribution linked to its evidence")
        copy_ids = {item.id for item in self.copy_blocks}
        if {layer.copy_id for layer in self.layers if layer.copy_id} != copy_ids:
            raise ValueError("every copy block must bind to a native text layer")
        sources = {source.asset_id for source in self.source_roles}
        for layer in self.layers:
            if layer.kind == "authentic_image" and layer.asset_id not in sources:
                raise ValueError("authentic image is absent from source_roles")
            if not set(layer.reference_asset_ids) <= sources:
                raise ValueError("conditioning image is absent from source_roles")
        return self

    def _has_attribution(self, item: CopyBlock) -> bool:
        return any(
            credit.role == "attribution"
            and credit.id != item.id
            and bool(set(credit.evidence_refs) & set(item.evidence_refs))
            for credit in self.copy_blocks
        )

    def validate_evidence_requirements(self, requirements: PlaybookEvidenceRequirements) -> None:
        """Keep family prerequisites data-driven without weakening proof custody.

        A scoped repair retains relevant unchanged proof/source bindings in this
        handoff; the round delta identifies mutations. Intent alone never exempts
        a missing source or attribution.
        """
        if requirements.source_role:
            sources = {s.asset_id for s in self.source_roles if s.role == requirements.source_role}
            if not any(
                layer.kind == "authentic_image" and layer.asset_id in sources
                for layer in self.layers
            ):
                raise ValueError(
                    f"Selected playbook requires a supplied {requirements.source_role} image"
                )
        proof = [c for c in self.copy_blocks if c.claim_kind in requirements.claim_kinds]
        if requirements.claim_kinds and not proof:
            raise ValueError("Selected playbook requires sourced proof of a registered claim kind")
        if requirements.attribution and (
            not proof or any(not self._has_attribution(item) for item in proof)
        ):
            raise ValueError("Selected playbook requires attribution linked to its proof")
