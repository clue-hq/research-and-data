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
    generated_default_brand_kit: Optional[JsonObject] = None
    strict_no_fallback: bool = False
    persist_effective_brand: bool = True


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

