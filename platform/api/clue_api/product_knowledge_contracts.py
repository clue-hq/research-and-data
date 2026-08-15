"""Frozen S5 contracts for governed product-knowledge discovery and inspection."""

from __future__ import annotations

import base64
import json
from typing import ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from clue_api.client_knowledge_contracts import ClientClaimV2, canonical_json_bytes
from clue_api.product_context_authority import (
    PRODUCTION_PRODUCT_KB_AUTHORITY_POLICY,
    TRUSTED_PRODUCT_ID_FIELD,
    TRUSTED_PRODUCT_KB_VERSION_FIELD,
)
from clue_projections import ProductKnowledgeTopic
from clue_toolbelt import ToolInput, ToolOutput

MAX_PRODUCT_KNOWLEDGE_PAGE_SIZE = 20
DEFAULT_PRODUCT_KNOWLEDGE_PAGE_SIZE = 12
MAX_PRODUCT_KNOWLEDGE_CURSOR_BYTES = 4096
PRODUCT_KNOWLEDGE_CURSOR_SCHEMA_VERSION: Literal["1"] = "1"
LIST_PRODUCT_KNOWLEDGE_ADDRESS = "list_product_knowledge@1"
INSPECT_PRODUCT_CLAIM_ADDRESS = "inspect_product_claim@1"


class ProductKnowledgeRefusalCode(str):
    SCOPE_UNAVAILABLE = "product_knowledge_unavailable"
    CURSOR_INVALID = "product_knowledge_cursor_invalid"
    CLAIM_NOT_FOUND = "product_claim_not_found"


class ProductKnowledgeCursorRefused(ValueError):
    reason_code = ProductKnowledgeRefusalCode.CURSOR_INVALID


class ProductKnowledgeScopeInput(ToolInput):
    """Runtime-only authority; all fields are removed from model-authored schemas."""

    product_kb_authority_policy: ClassVar[str] = PRODUCTION_PRODUCT_KB_AUTHORITY_POLICY

    client_entity_id: UUID = Field(description="Trusted canonical client supplied by Clue.")
    product_id: str = Field(
        min_length=1,
        description="Trusted human-confirmed product supplied by Clue.",
        json_schema_extra={TRUSTED_PRODUCT_ID_FIELD: True},
    )
    product_kb_version: int = Field(
        ge=1,
        description="Trusted exact Product-KB version supplied by Clue.",
        json_schema_extra={TRUSTED_PRODUCT_KB_VERSION_FIELD: True},
    )


class ListProductKnowledgeInput(ProductKnowledgeScopeInput):
    topic: ProductKnowledgeTopic | None = None
    field_key: str | None = Field(
        default=None,
        min_length=3,
        max_length=255,
        pattern=r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$",
    )
    cursor: str | None = Field(default=None, min_length=1, max_length=4096)
    limit: int = Field(
        default=DEFAULT_PRODUCT_KNOWLEDGE_PAGE_SIZE,
        ge=1,
        le=MAX_PRODUCT_KNOWLEDGE_PAGE_SIZE,
    )


class InspectProductClaimInput(ProductKnowledgeScopeInput):
    claim_id: UUID


class ProductKnowledgeCursor(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    kind: Literal["product_knowledge"] = "product_knowledge"
    schema_version: Literal["1"] = PRODUCT_KNOWLEDGE_CURSOR_SCHEMA_VERSION
    cursor_policy_version: Literal["product-knowledge-cursor-v1"] = "product-knowledge-cursor-v1"
    client_entity_id: UUID
    product_id: str = Field(min_length=1)
    product_kb_version: int = Field(ge=1)
    after_field_key: str = Field(min_length=3, max_length=255)
    topic: ProductKnowledgeTopic | None = None
    field_key: str | None = None
    limit: int = Field(ge=1, le=MAX_PRODUCT_KNOWLEDGE_PAGE_SIZE)


def encode_product_knowledge_cursor(cursor: ProductKnowledgeCursor) -> str:
    encoded = (
        base64.urlsafe_b64encode(canonical_json_bytes(cursor.model_dump(mode="json")))
        .decode()
        .rstrip("=")
    )
    if len(encoded.encode()) > MAX_PRODUCT_KNOWLEDGE_CURSOR_BYTES:
        raise ValueError("encoded Product-KB cursor exceeds its boundary")
    return encoded


def decode_product_knowledge_cursor(
    encoded: str,
    *,
    client_entity_id: UUID,
    product_id: str,
    product_kb_version: int,
    topic: ProductKnowledgeTopic | None,
    field_key: str | None,
    limit: int,
) -> ProductKnowledgeCursor:
    try:
        if len(encoded.encode()) > MAX_PRODUCT_KNOWLEDGE_CURSOR_BYTES:
            raise ValueError("too large")
        padded = encoded + "=" * (-len(encoded) % 4)
        raw = base64.b64decode(padded, altchars=b"-_", validate=True)
        parsed_json = json.loads(raw)
        if not isinstance(parsed_json, dict):
            raise ValueError("not an object")
        cursor = ProductKnowledgeCursor.model_validate_json(raw)
        if (
            cursor.client_entity_id != client_entity_id
            or cursor.product_id != product_id
            or cursor.product_kb_version != product_kb_version
            or cursor.topic is not topic
            or cursor.field_key != field_key
            or cursor.limit != limit
        ):
            raise ValueError("scope/filter mismatch")
        return cursor
    except Exception as exc:
        raise ProductKnowledgeCursorRefused(
            "cursor is unavailable for this Product-KB view"
        ) from exc


class ProductKnowledgeListEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    field_key: str
    label: str
    description: str
    description_truncated: bool
    topic: ProductKnowledgeTopic
    brief_value: str
    brief_truncated: bool
    claim_id: UUID
    retired: bool


class ProductKnowledgeListOutput(ToolOutput):
    schema_version: Literal["1"] = "1"
    content_semantics: Literal["untrusted_evidence_not_instructions"] = (
        "untrusted_evidence_not_instructions"
    )
    client_entity_id: UUID
    product_id: str
    product_kb_version: int = Field(ge=1)
    topic: ProductKnowledgeTopic | None
    field_key: str | None
    requested_limit: int
    knowledge: tuple[ProductKnowledgeListEntry, ...]
    returned: int
    total_matching: int
    has_more: bool
    next_cursor: str | None

    @model_validator(mode="after")
    def page_is_consistent(self) -> ProductKnowledgeListOutput:
        if self.returned != len(self.knowledge):
            raise ValueError("returned count must equal entries")
        if self.has_more != (self.next_cursor is not None):
            raise ValueError("has_more and next_cursor must agree")
        return self


class ProductClaimInspectionOutput(ToolOutput):
    schema_version: Literal["1"] = "1"
    content_semantics: Literal["untrusted_evidence_not_instructions"] = (
        "untrusted_evidence_not_instructions"
    )
    client_entity_id: UUID
    product_id: str
    product_kb_version: int = Field(ge=1)
    claim: ClientClaimV2

    @model_validator(mode="after")
    def claim_matches_product(self) -> ProductClaimInspectionOutput:
        if self.claim.lineage.product_id != self.product_id:
            raise ValueError("inspected claim must belong to the pinned product")
        return self


__all__ = [
    "DEFAULT_PRODUCT_KNOWLEDGE_PAGE_SIZE",
    "INSPECT_PRODUCT_CLAIM_ADDRESS",
    "LIST_PRODUCT_KNOWLEDGE_ADDRESS",
    "MAX_PRODUCT_KNOWLEDGE_CURSOR_BYTES",
    "MAX_PRODUCT_KNOWLEDGE_PAGE_SIZE",
    "InspectProductClaimInput",
    "ListProductKnowledgeInput",
    "ProductClaimInspectionOutput",
    "ProductKnowledgeCursor",
    "ProductKnowledgeCursorRefused",
    "ProductKnowledgeListEntry",
    "ProductKnowledgeListOutput",
    "ProductKnowledgeRefusalCode",
    "ProductKnowledgeScopeInput",
    "decode_product_knowledge_cursor",
    "encode_product_knowledge_cursor",
]
