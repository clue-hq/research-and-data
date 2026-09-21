"""Governed asset-registry tools (Part II slice D6 Round C — domain 3).

Seven durable operations over the asset library. Every one of them follows the R-D6-B4 shape:
the ROUTE runs the engine (``ingest_asset`` / ``generate_qr`` / ``generate_asset``), the provider
(``image_provider.generate``/``edit``) and the byte write-back (``register_engine_write``, which
is content-addressed and therefore not a mutation the gate needs to protect), and the tool
governs the registry row that results.

Replay honesty, per tool, because the four *registration* paths genuinely differ:

* :class:`RegisterAssetRecordTool` (``design_register_asset_record``) — ``OPERATION_IDEMPOTENT``.
  The upload route and the registered-provider generation branch both mint ``asset_<uuid4>`` /
  ``asset_gen_<uuid4>`` per request, so re-uploading identical bytes deliberately produces a
  SECOND library row (the library is a curation surface: two people uploading the same logo want
  two entries with their own labels and tags). D6 preserves that; it does not "fix" it into a
  dedup.
* :class:`RegisterQrAssetTool` (``design_register_qr_asset``) — ``DOMAIN_IDEMPOTENT``. A QR code
  is a pure function of its payload: the same data + error-correction level + print geometry +
  label render the same bytes, which is why the engine already reports ``deduplicated`` on the
  second call. The only thing that was NOT deterministic was the row id (``asset_qr_<uuid4>``),
  so an identical repeat accumulated library rows pointing at one blob. The route now derives
  ``asset_qr_<sha256(payload)[:12]>`` and the write is an upsert, so the domain key is real.
* :class:`RegisterGeneratedAssetTool` (``design_register_generated_asset``) —
  ``DOMAIN_IDEMPOTENT`` on the **generation ledger key**. The ledger (``design_generation_result``,
  D6 Round C) is consulted INSIDE the write: a claimed key returns the claimed asset and
  registers nothing, so two identical requests that both raced past the route's pre-spend probe
  still converge on one asset. Note the honest boundary — the tool cannot un-spend the provider
  call the route already made; it can only stop the second asset from existing. Avoiding the
  spend is the route's pre-probe (``get_generation_result``), which is a READ and therefore not
  a tool.
* :class:`RegisterCapturedAssetsTool` (``design_register_captured_assets``) —
  ``DOMAIN_IDEMPOTENT``, and BULK. The ingestion worker promotes every asset one capture
  produced; their ids are content-derived (``asset_ing_<sha>``), so re-running a re-offered job
  converges. It takes the whole list because that is one logical gesture — and because a
  per-record invocation would cost one private engine and five journal transactions *per
  captured image*.

The three lifecycle tools are unsurprising: ``design_set_asset_status`` is a value assignment
(archive/restore, ``DOMAIN``), ``design_set_asset_description`` is a partial patch whose merge is
now ONE statement in the DAL (``DOMAIN``; see below), and ``design_delete_asset`` is the one
destructive write (``OPERATION``).

**The description patch race.** ``PUT /assets/{id}/description`` merged in Python across two
transactions — read the row, substitute the caller's non-``None`` fields, write the whole record
back. Two concurrent patches of different fields each wrote the view they had read, so the later
one silently reverted the earlier one's field. The merge is a single ``COALESCE`` upsert now
(``clue_design.descriptions.merge_human``), evaluated under the conflicting row's own lock.

**Delete is a precondition plus two writes, deliberately in one tool core.** The reference check
(no document scene may still name the asset) is a precondition; the row delete and the
digest-by-digest byte GC are the operation. Splitting them would leave a window in which the row
is gone and the bytes are not, with nothing recording that the GC is owed. The GC itself is the
unchanged ``delete_stored_digest`` path: durable custody first (the seam tombstones the
``artifact`` row and deletes the blob), then the engine cache mirror — so a failure part-way
leaves a transient copy, never an orphaned durable one.
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

from pydantic import Field

from .base import DesignTool

__all__ = [
    "AssetDeletionRef",
    "AssetDescriptionRef",
    "AssetRef",
    "CapturedAssetsRef",
    "DeleteAssetInput",
    "DeleteAssetTool",
    "RegisterAssetRecordInput",
    "RegisterAssetRecordTool",
    "RegisterCapturedAssetsInput",
    "RegisterCapturedAssetsTool",
    "RegisterGeneratedAssetInput",
    "RegisterGeneratedAssetTool",
    "RegisterQrAssetTool",
    "SetAssetDescriptionInput",
    "SetAssetDescriptionTool",
    "SetAssetStatusInput",
    "SetAssetStatusTool",
    "delete_asset_and_orphaned_bytes",
]

JsonObject = dict[str, Any]

#: The closed status vocabulary the archive/restore routes assign.
ASSET_STATUSES = ("ready", "archived")


class AssetRef(ToolOutput):
    """One registry row, by reference. Never the record — the route re-reads it for its DTO."""

    asset_id: str
    kind: str
    status: str
    digest: str | None
    #: ``False`` when the generation ledger already held this key and nothing was written.
    created: bool = True


class CapturedAssetsRef(ToolOutput):
    asset_ids: list[str]
    count: int


class AssetDeletionRef(ToolOutput):
    asset_id: str
    removed_digests: list[str]


class AssetDescriptionRef(ToolOutput):
    asset_id: str
    origin: str


def _asset_ref(stored: JsonObject, *, created: bool = True) -> AssetRef:
    record = stored["asset"]
    media = record.get("media") or {}
    digest = (media.get("digest") or {}).get("value")
    return AssetRef(
        asset_id=record["id"],
        kind=record.get("kind") or "other",
        status=record.get("status") or "ready",
        digest=digest,
        created=created,
    )


def _asset_missing(repository: Any, asset_id: str) -> tuple[PreconditionFailure, ...]:
    from ..database import NotFoundError

    try:
        repository.require_asset_record(asset_id)
    except NotFoundError:
        return (
            PreconditionFailure(
                reason_code="design_asset_not_found",
                message=f"no asset {asset_id!r} in this workspace",
            ),
        )
    return ()


# ---------------------------------------------------------------------------------------------
# the destructive operation core (one implementation; the route owns none of it)
# ---------------------------------------------------------------------------------------------


def delete_asset_and_orphaned_bytes(
    *, repository: Any, blobs: Any, cache_dir: str, asset_id: str
) -> list[str]:
    """Delete one registry row and every digest it leaves unreferenced. Returns those digests.

    The ported byte lifecycle, verbatim (Decision 4): bytes leave the store only when no
    remaining asset record and no document scene references their digest.
    """
    from pathlib import Path

    from ..asset_custody import cache_blob_path, record_digests

    record = repository.require_asset_record(asset_id)["asset"]
    repository.delete_asset_record(asset_id)

    removed: list[str] = []
    for digest_value, _media_type in record_digests(record):
        if repository.count_assets_with_digest(digest_value):
            continue
        if repository.count_documents_referencing(digest_value):
            continue
        destroyed = blobs.delete(digest_value)
        cache_path: Path = cache_blob_path(cache_dir, digest_value)
        if cache_path.is_file():
            cache_path.unlink()
        if destroyed:
            removed.append(digest_value)
    return removed


# ---------------------------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------------------------


class RegisterAssetRecordInput(ToolInput):
    #: The engine's canonical ``AssetRecord``, already re-pointed at durable storage keys by
    #: ``register_engine_write``. It carries its own id.
    record: JsonObject


class RegisterAssetRecordTool(DesignTool):
    """Register one engine-produced asset record in the library."""

    name = "design_register_asset_record"
    version = "1"
    model_description = (
        "Register an engine-produced asset record in the design asset library. Returns the "
        "asset reference (id, kind, status, digest), never the record or its bytes."
    )
    input_model: ClassVar[type[ToolInput]] = RegisterAssetRecordInput
    output_model: ClassVar[type[ToolOutput]] = AssetRef
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity="workspace + record.id + ToolContext.operation_id",
        operation_id_required=True,
        external_boundary=ExternalReplayBoundary.NONE,
        notes=(
            "the asset id is minted per request (asset_<uuid4> / asset_gen_<uuid4>), so a "
            "re-upload of identical bytes is deliberately a second library row — the library is "
            "a curation surface, not a byte store. Only a same-operation retry replays"
        ),
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=()
    )

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, RegisterAssetRecordInput)
        if getattr(inputs, "enrichment", None) is not None:
            from ..asset_enrichment import register_upload
            stored = register_upload(ctx.workspace_id, inputs.record, inputs.enrichment)
        else:
            stored = self.host.repository(ctx.workspace_id).create_asset_record(inputs.record)
        return _asset_ref(stored)


class RegisterAssetRecordV2Input(RegisterAssetRecordInput):
    enrichment: JsonObject | None = None


class RegisterAssetRecordV2Tool(RegisterAssetRecordTool):
    version = "2"
    input_model: ClassVar[type[ToolInput]] = RegisterAssetRecordV2Input



class RegisterQrAssetTool(RegisterAssetRecordTool):
    """Register one generated QR asset, whose id is derived from its payload."""

    name = "design_register_qr_asset"
    version = "1"
    model_description = (
        "Register a generated QR code in the design asset library. The QR is a pure function "
        "of its payload, so the row id is content-derived and a repeat converges on one row."
    )
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="workspace + asset_qr_<sha256 of the QR request payload>",
        external_boundary=ExternalReplayBoundary.NONE,
        notes=(
            "the rendered SVG is deterministic in (data, ec_level, print_media, "
            "target_width_mm, label), so the route derives the row id from that payload and the "
            "registry write is an upsert: an identical repeat refreshes ONE row instead of "
            "accumulating rows that all point at the same blob"
        ),
    )


class RegisterGeneratedAssetInput(RegisterAssetRecordInput):
    #: ``lumen_api.image_cache.generation_key`` over the normalized request. The ledger row keyed
    #: on it is what makes a repeat free.
    generation_key: str


class RegisterGeneratedAssetTool(DesignTool):
    """Register a provider-generated asset and claim its generation-ledger key."""

    name = "design_register_generated_asset"
    version = "1"
    model_description = (
        "Register a provider-generated image in the design asset library and claim its "
        "generation-ledger key, so an identical later request re-places this asset instead of "
        "re-paying the provider. Returns the asset reference."
    )
    input_model: ClassVar[type[ToolInput]] = RegisterGeneratedAssetInput
    output_model: ClassVar[type[ToolOutput]] = AssetRef
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="workspace + generation_key (design_generation_result)",
        external_boundary=ExternalReplayBoundary.NONE,
        notes=(
            "the ledger is consulted inside the write, so a claimed key returns the claimed "
            "asset and registers nothing. The boundary is NONE because this tool makes no "
            "external call — the provider spend happens in the route BEFORE the invocation, so "
            "replay cannot un-spend it. Avoiding the spend is the route's pre-spend ledger "
            "probe (a read); this write is what stops a SECOND asset from existing when two "
            "identical requests race past that probe"
        ),
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("generation_key",)
    )

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, RegisterGeneratedAssetInput)
        result = self.host.repository(ctx.workspace_id).record_generation_result(
            inputs.generation_key, inputs.record
        )
        return _asset_ref({"asset": result["asset"]}, created=bool(result["created"]))


class RegisterCapturedAssetsInput(ToolInput):
    #: Every asset one ingestion capture produced, in capture order. Ids are content-derived.
    records: list[JsonObject]


class RegisterCapturedAssetsTool(DesignTool):
    """Promote every asset one ingestion capture produced into the library — one transaction."""

    name = "design_register_captured_assets"
    version = "1"
    model_description = (
        "Promote the assets a brand-kit ingestion capture produced into the design asset "
        "library. Returns the registered asset ids."
    )
    input_model: ClassVar[type[ToolInput]] = RegisterCapturedAssetsInput
    output_model: ClassVar[type[ToolOutput]] = CapturedAssetsRef
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="workspace + the records' content-derived asset ids",
        external_boundary=ExternalReplayBoundary.NONE,
        notes=(
            "ingestion asset ids are content-derived (asset_ing_<sha>) and the write is an "
            "upsert, so a re-offered ingestion job converges on the same rows rather than "
            "accumulating duplicates. Bulk on purpose: one capture is one gesture, and a "
            "per-record invocation would cost a private engine per captured image"
        ),
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=()
    )

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, RegisterCapturedAssetsInput)
        asset_ids = self.host.repository(ctx.workspace_id).create_asset_records(inputs.records)
        return CapturedAssetsRef(asset_ids=asset_ids, count=len(asset_ids))


# ---------------------------------------------------------------------------------------------
# lifecycle
# ---------------------------------------------------------------------------------------------


class SetAssetStatusInput(ToolInput):
    asset_id: str
    status: str


class SetAssetStatusTool(DesignTool):
    """Archive or restore one library asset (the archive-first lifecycle)."""

    name = "design_set_asset_status"
    version = "1"
    model_description = (
        "Archive a design asset (hiding it from the default library listing) or restore it to "
        "ready. Returns the asset reference."
    )
    input_model: ClassVar[type[ToolInput]] = SetAssetStatusInput
    output_model: ClassVar[type[ToolOutput]] = AssetRef
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="workspace + asset_id (design_asset.status)",
        external_boundary=ExternalReplayBoundary.NONE,
        notes="effect-free by value: assigning the same status twice converges on the same row",
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("asset_id", "status")
    )

    def check(self, inputs: ToolInput, ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
        assert isinstance(inputs, SetAssetStatusInput)
        if inputs.status not in ASSET_STATUSES:
            return (
                PreconditionFailure(
                    reason_code="design_asset_status_invalid",
                    message=(
                        f"asset status {inputs.status!r} is not one of "
                        f"{', '.join(ASSET_STATUSES)}"
                    ),
                ),
            )
        return _asset_missing(self.host.repository(ctx.workspace_id), inputs.asset_id)

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, SetAssetStatusInput)
        stored = self.host.repository(ctx.workspace_id).update_asset_status(
            inputs.asset_id, inputs.status
        )
        return _asset_ref(stored, created=False)


class DeleteAssetInput(ToolInput):
    asset_id: str


class DeleteAssetTool(DesignTool):
    """Hard-delete one library asset and garbage-collect the bytes it orphans."""

    name = "design_delete_asset"
    version = "1"
    model_description = (
        "Permanently delete a design asset and destroy any stored bytes it leaves unreferenced. "
        "Refused while any document scene still references the asset — archive it instead."
    )
    input_model: ClassVar[type[ToolInput]] = DeleteAssetInput
    output_model: ClassVar[type[ToolOutput]] = AssetDeletionRef
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity="workspace + asset_id + ToolContext.operation_id",
        operation_id_required=True,
        external_boundary=ExternalReplayBoundary.NONE,
        notes=(
            "destructive and unrecoverable: the bytes are gone, so a blind retry of a stale "
            "request could destroy an asset re-registered under the same id in between. The "
            "second run is also NOT a no-op from the caller's view — it refuses "
            "design_asset_not_found — so the A9 record is what makes a retry answer the same "
            "thing twice"
        ),
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("asset_id",)
    )

    def check(self, inputs: ToolInput, ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
        assert isinstance(inputs, DeleteAssetInput)
        repository = self.host.repository(ctx.workspace_id)
        if failures := _asset_missing(repository, inputs.asset_id):
            return failures
        referencing = repository.count_documents_referencing(f'"{inputs.asset_id}"')
        if referencing:
            return (
                PreconditionFailure(
                    reason_code="design_asset_referenced",
                    message=(
                        f"asset {inputs.asset_id} is referenced by {referencing} document(s); "
                        "archive it instead or remove the references first"
                    ),
                ),
            )
        return ()

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, DeleteAssetInput)
        removed = delete_asset_and_orphaned_bytes(
            repository=self.host.repository(ctx.workspace_id),
            blobs=self.host.blobs(ctx.workspace_id),
            cache_dir=self.host.engine_cache_dir(ctx.workspace_id),  # type: ignore[misc]
            asset_id=inputs.asset_id,
        )
        return AssetDeletionRef(asset_id=inputs.asset_id, removed_digests=removed)


from clue_design.asset_context import AssetContextPatch, AssetOverrides


class SetAssetDescriptionInput(ToolInput):
    asset_id: str
    title: str | None = None
    description: str | None = None
    usage: str | None = None
    tags: list[str] | None = None


class SetAssetDescriptionV2Input(SetAssetDescriptionInput, AssetContextPatch):
    title: str | None = Field(default=None, max_length=120)
    reset_fields: list[str] = []


class SetAssetDescriptionTool(DesignTool):
    """Patch one asset's human-authored library metadata."""

    name = "design_set_asset_description"
    version = "1"
    model_description = (
        "Patch a design asset's human-authored library metadata (title, description, usage, "
        "tags). Omitted fields are preserved. Returns the description reference."
    )
    input_model: ClassVar[type[ToolInput]] = SetAssetDescriptionInput
    output_model: ClassVar[type[ToolOutput]] = AssetDescriptionRef
    replay: ClassVar[ReplaySafety] = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="workspace + asset_id (design_asset_description)",
        external_boundary=ExternalReplayBoundary.NONE,
        notes=(
            "a value assignment merged in SQL: applying the same patch twice converges, and two "
            "concurrent patches of different fields compose rather than clobbering (the merge "
            "is a COALESCE upsert evaluated under the conflicting row's lock)"
        ),
    )
    effect_class: ClassVar[ToolEffectClass] = ToolEffectClass.WRITE
    parameter_policy: ClassVar[JournalParameterPolicy] = JournalParameterPolicy(
        safe_display_fields=("asset_id",)
    )

    def check(self, inputs: ToolInput, ctx: ToolContext) -> tuple[PreconditionFailure, ...]:
        assert isinstance(inputs, SetAssetDescriptionInput)
        return _asset_missing(self.host.repository(ctx.workspace_id), inputs.asset_id)

    def run(self, inputs: ToolInput, ctx: ToolContext) -> ToolOutput:
        assert isinstance(inputs, SetAssetDescriptionInput)
        from clue_design import descriptions
        from ..design_store import DesignStoreBridge
        values = inputs.model_dump(exclude={"asset_id", "reset_fields"}, exclude_none=True)
        DesignStoreBridge(ctx.workspace_id)._run(lambda conn: descriptions.patch_overrides(
            conn, workspace_id=ctx.workspace_id, asset_id=inputs.asset_id,
            values=values, reset_fields=getattr(inputs, "reset_fields", []),
        ))
        return AssetDescriptionRef(asset_id=inputs.asset_id, origin="human")


class SetAssetDescriptionV2Tool(SetAssetDescriptionTool):
    version = "2"
    input_model: ClassVar[type[ToolInput]] = SetAssetDescriptionV2Input
