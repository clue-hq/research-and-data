"""Governed Brand Ad Assets tools (spec §4/§5 W2, under the D6 gate).

Three durable writes belong to this lane and are not already someone else's:

* :class:`RecordAdCreativesTool` — the harvested creatives' provenance rows.
* :class:`PublishAdDnaCardTool` — one distilled card version.
* :class:`LinkAdPregeneratedAssetsTool` — the links from that version to its imagery.

**The two byte-bearing writes are deliberately NOT here, because they already exist.** The
harvested creatives' asset rows go out through ``design_register_captured_assets`` (bulk,
content-derived ids, the ingestion lane's own promotion tool) and the pre-generated imagery
through ``design_register_generated_asset`` (the generation-ledger-keyed one). Minting an
ad-specific twin of either would have been a second way to do a thing the toolbelt already
does one way.

Replay honesty, per tool:

* ``design_record_ad_creatives`` — ``DOMAIN_IDEMPOTENT``. A creative's id is derived from the
  creative URL (the same key the harvest de-duplicated on), so a re-offered harvest job writes
  the same rows again rather than a second copy of each. It is BULK for the same reason
  ``design_register_captured_assets`` is: one harvest is one gesture, and a per-creative
  invocation would cost a private engine and a journal execution per image.
* ``design_publish_ad_dna_card`` — ``OPERATION_IDEMPOTENT``. Distillation is a model call, so
  two runs produce two genuinely different cards and each deserves its own version; the DAL
  allocates the number under a lock, so concurrent distillations cannot collide. The operation
  id is what stops one caller's retry from becoming two versions.
* ``design_link_ad_pregenerated_assets`` — ``DOMAIN_IDEMPOTENT`` on
  ``(card_id, card_version, asset_id)``. Re-running a partly-succeeded pre-generation step
  re-states the links it already made, which is what lets the step be resumed at all.

There is no approval precondition anywhere in this module, and that is a ruling and not an
omission: harvested references, the card and the pre-generated assets are born active and
immediately usable (D5). The only preconditions are structural ones the database would
otherwise answer with a raw integrity error.
"""

from __future__ import annotations

from typing import Any, ClassVar

from clue_toolbelt import (
    ExternalReplayBoundary,
    JournalParameterPolicy,
    PreconditionFailure,
    ReplayPolicy,
    ReplaySafety,
    ToolContext,
    ToolEffectClass,
    ToolInput,
    ToolOutput,
)

from .base import DesignTool

__all__ = [
    "AdCreativesRef",
    "AdDnaCardRef",
    "AdPregeneratedAssetsRef",
    "LinkAdPregeneratedAssetsInput",
    "LinkAdPregeneratedAssetsTool",
    "PublishAdDnaCardInput",
    "PublishAdDnaCardTool",
    "RecordAdCreativesInput",
    "RecordAdCreativesTool",
]

JsonObject = dict[str, Any]

#: Every field a creative row needs to be meaningful. Checked as a precondition so a missing
#: one is a named refusal rather than a ``KeyError`` inside a transaction.
REQUIRED_CREATIVE_FIELDS = (
    "creative_id",
    "harvest_job_id",
    "provider",
    "ad_id",
    "creative_url",
    "asset_id",
    "fetched_at",
)


class AdCreativesRef(ToolOutput):
    creative_ids: list[str]
    count: int


class AdDnaCardRef(ToolOutput):
    card_id: str
    version: int
    brand_kit_id: str
    brand_kit_version: int
    system_count: int


class AdPregeneratedAssetsRef(ToolOutput):
    card_id: str
    card_version: int
    asset_ids: list[str]
    count: int


class RecordAdCreativesInput(ToolInput):
    #: One row per kept creative — see ``REQUIRED_CREATIVE_FIELDS`` for the mandatory keys.
    creatives: list[JsonObject]


class PublishAdDnaCardInput(ToolInput):
    card_id: str
    brand_kit_id: str
    brand_kit_version: int
    #: The bounded, plain-language card: ``{"visual_systems": [...], ...}``.
    card: JsonObject
    source_creative_ids: list[str] = []
    harvest_job_id: str | None = None
    model: str | None = None


class LinkAdPregeneratedAssetsInput(ToolInput):
    card_id: str
    card_version: int
    #: ``{"asset_id", "visual_system", "prompt", "generation"?}`` per pre-generated asset.
    links: list[JsonObject]


class RecordAdCreativesTool(DesignTool):
    """Record one harvest's creative provenance rows."""

    name = "design_record_ad_creatives"
    version = "1"
    model_description = (
        "Record the provenance rows for one ad-library harvest's kept creatives (ad id, "
        "library detail link, advertiser page, provider, fetch time) against the design "
        "asset rows that already hold their bytes."
    )
    input_model: ClassVar[type[ToolInput]] = RecordAdCreativesInput
    output_model: ClassVar[type[ToolOutput]] = AdCreativesRef
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="workspace + creative_id",
        operation_id_required=False,
        external_boundary=ExternalReplayBoundary.NONE,
        notes=(
            "creative ids are derived from the creative URL the harvest de-duplicated on, so "
            "a re-offered harvest job converges on the same rows; the write is an upsert"
        ),
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=()
    )

    def check(self, inputs: ToolInput, ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
        del ctx
        assert isinstance(inputs, RecordAdCreativesInput)
        for index, creative in enumerate(inputs.creatives):
            if not isinstance(creative, dict):
                return (
                    PreconditionFailure(
                        reason_code="design_ad_creative_malformed",
                        message=f"creative at index {index} is not an object",
                    ),
                )
            missing = [key for key in REQUIRED_CREATIVE_FIELDS if not creative.get(key)]
            if missing:
                return (
                    PreconditionFailure(
                        reason_code="design_ad_creative_incomplete",
                        message=(
                            f"creative at index {index} is missing {', '.join(missing)}; a "
                            "harvested creative without its provenance is not recordable"
                        ),
                    ),
                )
        return ()

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, RecordAdCreativesInput)
        from lumen_ingestion.ad_library.store import AdAssetsStore

        creative_ids = AdAssetsStore(workspace_id=ctx.workspace_id).record_creatives(
            list(inputs.creatives)
        )
        return AdCreativesRef(creative_ids=creative_ids, count=len(creative_ids))


class PublishAdDnaCardTool(DesignTool):
    """Append one distilled ad-DNA card version."""

    name = "design_publish_ad_dna_card"
    version = "1"
    model_description = (
        "Append the next immutable version of a brand's ad-DNA card: its named visual "
        "systems, each with a plain-language layout skeleton, ground treatment, accent spend, "
        "logo placement and type feel."
    )
    input_model: ClassVar[type[ToolInput]] = PublishAdDnaCardInput
    output_model: ClassVar[type[ToolOutput]] = AdDnaCardRef
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity="workspace + card_id + ToolContext.operation_id",
        operation_id_required=True,
        external_boundary=ExternalReplayBoundary.NONE,
        notes=(
            "distillation is a model call, so two runs are two genuinely different cards and "
            "each gets its own version; the version number is allocated under a per-lineage "
            "lock inside the write, so concurrent distillations cannot collide"
        ),
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("card_id", "brand_kit_id", "brand_kit_version")
    )

    def check(self, inputs: ToolInput, ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
        del ctx
        assert isinstance(inputs, PublishAdDnaCardInput)
        systems = inputs.card.get("visual_systems")
        if not isinstance(systems, list) or not systems:
            return (
                PreconditionFailure(
                    reason_code="design_ad_dna_card_empty",
                    message=(
                        "an ad-DNA card must name at least one visual system; a card with "
                        "none is a distillation that failed, and recording it would make "
                        "every later turn believe the brand has no system"
                    ),
                ),
            )
        return ()

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, PublishAdDnaCardInput)
        from lumen_ingestion.ad_library.store import AdAssetsStore

        card = AdAssetsStore(workspace_id=ctx.workspace_id).create_card_version(
            card_id=inputs.card_id,
            brand_kit_id=inputs.brand_kit_id,
            brand_kit_version=inputs.brand_kit_version,
            card=inputs.card,
            source_creative_ids=list(inputs.source_creative_ids),
            harvest_job_id=inputs.harvest_job_id,
            model=inputs.model,
        )
        return AdDnaCardRef(
            card_id=card["card_id"],
            version=int(card["version"]),
            brand_kit_id=card["brand_kit_id"],
            brand_kit_version=int(card["brand_kit_version"]),
            system_count=len(card["card"].get("visual_systems") or []),
        )


class LinkAdPregeneratedAssetsTool(DesignTool):
    """Attach pre-generated imagery to one ad-DNA card version."""

    name = "design_link_ad_pregenerated_assets"
    version = "1"
    model_description = (
        "Link the imagery pre-generated for one ad-DNA card version to that version, "
        "recording which named visual system asked for each asset and the prompt used."
    )
    input_model: ClassVar[type[ToolInput]] = LinkAdPregeneratedAssetsInput
    output_model: ClassVar[type[ToolOutput]] = AdPregeneratedAssetsRef
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="workspace + card_id + card_version + asset_id",
        operation_id_required=False,
        external_boundary=ExternalReplayBoundary.NONE,
        notes=(
            "the link is an upsert on its own composite key, which is what lets a partly "
            "succeeded pre-generation step be resumed instead of restarted"
        ),
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("card_id", "card_version")
    )

    def check(self, inputs: ToolInput, ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
        del ctx
        assert isinstance(inputs, LinkAdPregeneratedAssetsInput)
        for index, link in enumerate(inputs.links):
            if not isinstance(link, dict) or not link.get("asset_id"):
                return (
                    PreconditionFailure(
                        reason_code="design_ad_pregenerated_link_malformed",
                        message=f"link at index {index} names no asset_id",
                    ),
                )
            if not link.get("visual_system"):
                return (
                    PreconditionFailure(
                        reason_code="design_ad_pregenerated_link_unattributed",
                        message=(
                            f"link at index {index} names no visual system; an asset that "
                            "cannot say which system asked for it cannot be placed by one"
                        ),
                    ),
                )
        return ()

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, LinkAdPregeneratedAssetsInput)
        from lumen_ingestion.ad_library.store import AdAssetsStore

        asset_ids = AdAssetsStore(workspace_id=ctx.workspace_id).link_pregenerated_assets(
            card_id=inputs.card_id,
            card_version=inputs.card_version,
            links=list(inputs.links),
        )
        return AdPregeneratedAssetsRef(
            card_id=inputs.card_id,
            card_version=inputs.card_version,
            asset_ids=asset_ids,
            count=len(asset_ids),
        )
