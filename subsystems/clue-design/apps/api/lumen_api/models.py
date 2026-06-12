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


class ApplyOperationsRequest(BaseModel):
    operations: List[JsonObject] = Field(default_factory=list)
    actor: ActorEnvelope = Field(default_factory=ActorEnvelope)
    source: Literal["editor", "agent", "api", "system"] = "api"
    snapshot_reason: Optional[str] = None


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
    selected_node_id: Optional[str] = None
    diagnostics: List[JsonObject] = Field(default_factory=list)
    max_iterations: Optional[int] = None


class FinalizeTemplateRequest(BaseModel):
    template_revision_id: Optional[str] = None
    snapshot_id: Optional[str] = None
    actor: ActorEnvelope = Field(default_factory=lambda: ActorEnvelope(kind="system"))


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


class BrandCompatibilityRequest(BaseModel):
    from_brand_kit: Optional[JsonObject] = None
    to_brand_kit: Optional[JsonObject] = None
    from_ref: Optional[BrandKitRefRequest] = None
    to_ref: Optional[BrandKitRefRequest] = None
    persist_report: bool = True
