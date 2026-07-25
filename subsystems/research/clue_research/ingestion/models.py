"""C3 lane-local inputs, row models, and routing contracts."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from clue_core import (
    ClaimId,
    EntityId,
    EntityType,
    FieldKey,
    IdentityBinding,
    UseClass,
    UtcDatetime,
)
from clue_core.ingestion import IngestionJobId, IngestionSegmentId, IngestionStatus


class MaterialContext(StrEnum):
    CLIENT_ABOUT_SELF = "client_about_self"
    CLIENT_ABOUT_PRODUCT = "client_about_product"
    CLIENT_ABOUT_TARGET = "client_about_target"
    CLIENT_PREFERENCE = "client_preference"
    PROJECT_INSTRUCTION = "project_instruction"
    UNKNOWN = "unknown"


class IngestionFailureCode(StrEnum):
    ARTIFACT_NOT_FOUND = "artifact_not_found"
    ARTIFACT_ERASED = "artifact_erased"
    ARTIFACT_SCOPE_MISMATCH = "artifact_scope_mismatch"
    UNSUPPORTED_MEDIA_TYPE = "unsupported_media_type"
    SIZE_LIMIT_EXCEEDED = "size_limit_exceeded"
    OCR_DISABLED = "ocr_disabled"
    GATE_BLOCKED = "gate_blocked"
    ADAPTER_FAILED = "adapter_failed"
    SEGMENT_LIMIT_EXCEEDED = "segment_limit_exceeded"
    EXTRACTION_FAILED = "extraction_failed"
    RETRY_LIMIT_EXCEEDED = "retry_limit_exceeded"
    INVALID_CONTEXT = "invalid_context"


class IngestionTarget(BaseModel):
    """One typed field the shared ClaimExtractor may extract from the document."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entity_id: EntityId
    entity_type: EntityType
    field_key: FieldKey
    material_context: MaterialContext
    use_class: UseClass | None = None
    manifest_identity_binding: IdentityBinding | None = None


class DeclaredMaterialContext(BaseModel):
    """Caller-declared scope. It contributes to the durable idempotency key."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    brand_id: str
    product_id: str | None = None
    project_id: str | None = None
    targets: tuple[IngestionTarget, ...] = ()
    document_context: MaterialContext = MaterialContext.UNKNOWN

    @model_validator(mode="after")
    def _validate_routes(self) -> DeclaredMaterialContext:
        if self.document_context is MaterialContext.PROJECT_INSTRUCTION and self.project_id is None:
            raise ValueError("project_instruction material requires project_id")
        if (
            self.document_context is MaterialContext.CLIENT_ABOUT_PRODUCT
            and self.product_id is None
        ):
            raise ValueError("client_about_product material requires product_id")
        return self


class IngestionResultRefs(BaseModel):
    """Durable reference-only outputs. No extracted body is stored here."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    claims: tuple[ClaimId, ...] = ()
    proposals: tuple[str, ...] = ()
    memory: tuple[str, ...] = ()
    project_state: tuple[str, ...] = ()
    unmapped_segments: tuple[IngestionSegmentId, ...] = ()


class IngestionJob(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: IngestionJobId
    workspace_id: str
    brand_id: str
    product_id: str | None = None
    project_id: str | None = None
    artifact_key: str
    content_sha256: str
    declared_context: DeclaredMaterialContext
    declared_context_hash: str
    media_type: str
    adapter_key: str
    status: IngestionStatus
    failure_code: IngestionFailureCode | None = None
    failure_detail: str | None = None
    segment_count: int = 0
    result_refs: IngestionResultRefs = IngestionResultRefs()
    retry_count: int = 0
    created_by_actor: str
    created_at: UtcDatetime
    updated_at: UtcDatetime
    completed_at: UtcDatetime | None = None
    erased_at: UtcDatetime | None = None


class IngestionSegment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: IngestionSegmentId
    ingestion_job_id: IngestionJobId
    ordinal: int = Field(ge=0)
    locator: dict[str, JsonValue]
    text_sha256: str
    canonical_artifact_key: str
    created_at: UtcDatetime
