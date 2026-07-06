from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


JsonObject = Dict[str, Any]


class ActorEnvelope(BaseModel):
    kind: str = "api"
    id: Optional[str] = None


class CreateDocumentRequest(BaseModel):
    document_id: Optional[str] = None
    title: str = "Untitled document"
    artifact_type: Optional[str] = None
    medium: Optional[Any] = None
    scene: Optional[JsonObject] = None
    brand_kit: Optional[JsonObject] = None


class ReplaceSceneRequest(BaseModel):
    scene: JsonObject


class EditScopeEnvelope(BaseModel):
    mode: Literal["strict", "advisory"] = "strict"
    allowed: List[JsonObject] = Field(default_factory=list)


class ApplyOperationsRequest(BaseModel):
    operations: List[JsonObject] = Field(default_factory=list)
    actor: ActorEnvelope = Field(default_factory=ActorEnvelope)
    source: Literal["editor", "agent", "api", "system"] = "api"
    snapshot_reason: Optional[str] = None
    base_version: Optional[int] = None
    intent: Optional[str] = None
    checkpoint: Optional[str] = None
    scope: Optional[EditScopeEnvelope] = None


class ApplyStructuredEditRequest(BaseModel):
    edit: JsonObject
    actor: ActorEnvelope = Field(default_factory=ActorEnvelope)
    source: Literal["editor", "agent", "api", "system"] = "api"
    snapshot_reason: Optional[str] = None
    base_version: Optional[int] = None
    checkpoint: Optional[str] = None
    scope: Optional[EditScopeEnvelope] = None


class CreateSnapshotRequest(BaseModel):
    snapshot_id: Optional[str] = None
    reason: str = "manual"


class PreflightRequest(BaseModel):
    brand_kit: Optional[JsonObject] = None
    brand_kit_id: Optional[str] = None
    brand_kit_version: Optional[int] = None
    generated_default_brand_kit: Optional[JsonObject] = None
    mode: Optional[JsonObject] = None
    strict_no_fallback: bool = False
    persist_effective_brand: bool = True


class PreflightPreviewRequest(BaseModel):
    scene: JsonObject
    brand_kit: Optional[JsonObject] = None
    brand_kit_id: Optional[str] = None
    brand_kit_version: Optional[int] = None
    generated_default_brand_kit: Optional[JsonObject] = None
    mode: Optional[JsonObject] = None
    strict_no_fallback: bool = False


class ExportPreviewRequest(BaseModel):
    scene: JsonObject
    format: Literal["svg", "png", "pdf", "figma_manifest"] = "svg"
    page_ids: List[str] = Field(default_factory=list)
    profile: Optional[JsonObject] = None


class ExportDocumentRequest(BaseModel):
    format: Literal["svg", "png", "pdf", "figma_manifest"] = "svg"
    page_ids: List[str] = Field(default_factory=list)
    profile_name: Optional[str] = None
    profile: Optional[JsonObject] = None
    brand_kit: Optional[JsonObject] = None
    brand_kit_id: Optional[str] = None
    brand_kit_version: Optional[int] = None
    generated_default_brand_kit: Optional[JsonObject] = None
    mode: Optional[JsonObject] = None
    strict_no_fallback: bool = False
    persist_effective_brand: bool = True
    persist_preflight: bool = True


class AgentTurnPreviewRequest(BaseModel):
    prompt: str
    scene: JsonObject
    document_id: Optional[str] = None
    active_page_id: Optional[str] = None
    # 2c selection chips: the node ids the human chipped as edit targets.
    # (The singular selected_node_id back-compat field was dropped after its
    # one-release window; legacy senders' extra key is ignored by pydantic.)
    target_node_ids: List[str] = Field(default_factory=list)
    diagnostics: List[JsonObject] = Field(default_factory=list)
    # 2e: the document's standing agent instructions, sent by the editor with
    # every turn and folded into the prompt context.
    agent_instructions: Optional[str] = None
    max_iterations: Optional[int] = None
    # Editor model picker: a runtime model id ("openai:<openrouter-id>" /
    # "anthropic:<id>"); None = the runtime's configured default.
    model: Optional[str] = None


class SetAgentInstructionsRequest(BaseModel):
    instructions: Optional[str] = None


class SetLayoutManagedEditingRequest(BaseModel):
    enabled: bool = False


class FinalizeTemplateRequest(BaseModel):
    template_revision_id: Optional[str] = None
    snapshot_id: Optional[str] = None
    actor: ActorEnvelope = Field(default_factory=lambda: ActorEnvelope(kind="system"))


class GenerateQrRequest(BaseModel):
    data: str
    label: Optional[str] = None
    ec_level: Optional[str] = None
    print_media: bool = False
    target_width_mm: Optional[float] = None


class GenerateAssetRequest(BaseModel):
    provider: str
    prompt: str = ""
    output_kind: str = "raster_image"
    width: Optional[int] = None
    height: Optional[int] = None
    mime_type: Optional[str] = None
    transparent_background: Optional[bool] = None
    brand_notes: List[str] = Field(default_factory=list)
    aspect_ratio: Optional[str] = None
    image_size: Optional[str] = None
    reference_asset_ids: List[str] = Field(default_factory=list)
    label: Optional[str] = None
    # Phase 3b image EDIT: when set, the prompt is an edit instruction applied
    # to this existing asset's pixels; the result is a NEW asset whose source
    # records the parent (kind "edited"). Remove-background = an edit with
    # transparent_background=true.
    source_asset_id: Optional[str] = None


class CreateBindingSetRequest(BaseModel):
    binding_set: JsonObject


class DeriveInstanceRequest(BaseModel):
    binding_set_id: Optional[str] = None
    binding_set: Optional[JsonObject] = None
    export_formats: List[str] = Field(default_factory=list)
    export_dpi: Optional[int] = None


class CreateInstanceBatchRequest(BaseModel):
    binding_set_ids: List[str]
    export_formats: List[str] = Field(default_factory=lambda: ["svg", "png"])
    chunk_size: int = 10


class InstancePreviewRequest(BaseModel):
    scene: JsonObject
    binding_set: JsonObject
    format: str = "svg"


class AssetMetadataRequest(BaseModel):
    asset_id: Optional[str] = None
    document_id: Optional[str] = None
    kind: str
    filename: Optional[str] = None
    source_uri: Optional[str] = None
    mime_type: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    dpi: Optional[float] = None
    provenance: JsonObject = Field(default_factory=dict)
    licensing: JsonObject = Field(default_factory=dict)


class BrandKitRefRequest(BaseModel):
    brand_kit_id: str
    version: Optional[int] = None


class CreateBrandKitRequest(BaseModel):
    brand_kit: JsonObject
    source: Literal["manual", "uploaded", "generated", "styles", "platform_default", "api"] = (
        "manual"
    )
    product_ready: bool = True


class CompileStylesBrandKitRequest(BaseModel):
    source: str
    brand_kit_id: str
    version: int = 1
    name: str
    persist: bool = True


class GenerateBrandKitRequest(BaseModel):
    seed: JsonObject
    persist: bool = True


class ValidateBrandKitRequest(BaseModel):
    brand_kit: Optional[JsonObject] = None
    brand_kit_id: Optional[str] = None
    version: Optional[int] = None
    product_ready: bool = True


class AttachBrandKitRequest(BaseModel):
    brand_kit_id: str
    version: Optional[int] = None
    mode: Optional[JsonObject] = None
    actor: ActorEnvelope = Field(default_factory=ActorEnvelope)
    snapshot_reason: Optional[str] = None


class ValidateDocumentBrandGovernanceRequest(BaseModel):
    brand_kit: Optional[JsonObject] = None
    brand_kit_id: Optional[str] = None
    version: Optional[int] = None
    strictness: Literal["advisory", "strict", "finalize"] = "strict"


class IngestWebsiteRequest(BaseModel):
    url: str
    name: Optional[str] = None
    brand_kit_id: Optional[str] = None
    force_render: bool = False


class SetBrandKitApprovalRequest(BaseModel):
    approval_status: Literal["approved", "draft"]


class SetAssetDescriptionRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    usage: Optional[str] = None
    tags: Optional[List[str]] = None


class BrandCompatibilityRequest(BaseModel):
    from_brand_kit: Optional[JsonObject] = None
    to_brand_kit: Optional[JsonObject] = None
    from_ref: Optional[BrandKitRefRequest] = None
    to_ref: Optional[BrandKitRefRequest] = None
    persist_report: bool = True
