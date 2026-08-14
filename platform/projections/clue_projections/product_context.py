"""Frozen S5 product-context card contracts and deterministic taxonomy.

Company portfolio navigation, durable product identity, and product research deliberately have
three owners.  The models in this module keep those boundaries mechanically visible; compilers
are added below the same contracts and never let catalog text become product authority.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

CLIENT_KNOWLEDGE_CARD_V2_MEDIA_TYPE = "application/vnd.clue.client-knowledge-card.v2+json"
PRODUCT_PROFILE_CARD_MEDIA_TYPE = "application/vnd.clue.product-profile-card+json"
PRODUCT_KNOWLEDGE_CARD_MEDIA_TYPE = "application/vnd.clue.product-knowledge-card+json"

CLIENT_KNOWLEDGE_CARD_V2_POLICY_VERSION = "client-knowledge-card-policy-v2"
PRODUCT_PROFILE_CARD_POLICY_VERSION = "product-profile-card-policy-v1"
PRODUCT_KNOWLEDGE_CARD_POLICY_VERSION = "product-knowledge-card-policy-v1"
PRODUCT_KNOWLEDGE_CURSOR_POLICY_VERSION = "product-knowledge-cursor-v1"


def canonical_card_bytes(value: BaseModel) -> bytes:
    return json.dumps(
        value.model_dump(mode="json", exclude_none=True),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


class ProductKnowledgeTopic(StrEnum):
    OVERVIEW = "overview"
    CAPABILITIES_AND_USE_CASES = "capabilities_and_use_cases"
    POSITIONING_AND_DIFFERENTIATION = "positioning_and_differentiation"
    PRICING_AND_INTEGRATIONS = "pricing_and_integrations"
    COMPETITION_AND_PROOF = "competition_and_proof"
    OTHER = "other"


_PRODUCT_FIELD_TOPICS: dict[str, ProductKnowledgeTopic] = {
    "client.product_overview": ProductKnowledgeTopic.OVERVIEW,
    "client.product_capability": ProductKnowledgeTopic.CAPABILITIES_AND_USE_CASES,
    "client.product_use_case": ProductKnowledgeTopic.CAPABILITIES_AND_USE_CASES,
    "client.product_positioning": ProductKnowledgeTopic.POSITIONING_AND_DIFFERENTIATION,
    "client.product_differentiator": ProductKnowledgeTopic.POSITIONING_AND_DIFFERENTIATION,
    "client.product_pricing": ProductKnowledgeTopic.PRICING_AND_INTEGRATIONS,
    "client.product_integration": ProductKnowledgeTopic.PRICING_AND_INTEGRATIONS,
    "client.product_competitor": ProductKnowledgeTopic.COMPETITION_AND_PROOF,
    "client.product_customer_evidence": ProductKnowledgeTopic.COMPETITION_AND_PROOF,
}


def product_knowledge_topic(field_key: str) -> ProductKnowledgeTopic:
    return _PRODUCT_FIELD_TOPICS.get(field_key, ProductKnowledgeTopic.OTHER)


class ProductCatalogEntry(BaseModel):
    """Bounded company-card navigation entry; never selected-product authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    product_id: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=240)
    short_description: str = Field(min_length=1, max_length=600)
    aliases: tuple[str, ...] = Field(default=(), max_length=20)
    status: Literal["active", "archived"]
    catalog_claim_id: str = Field(min_length=1)
    product_knowledge_available: bool


class ProductCatalogOmission(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["product_catalog_over_cap"] = "product_catalog_over_cap"
    count: int = Field(ge=1)
    cursor: str = Field(min_length=1, max_length=4096)


class ClientProductCatalog(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    entries: tuple[ProductCatalogEntry, ...]
    total: int = Field(ge=0)
    omissions: tuple[ProductCatalogOmission, ...] = ()

    @model_validator(mode="after")
    def counts_are_consistent(self) -> ClientProductCatalog:
        omitted = sum(item.count for item in self.omissions)
        if len(self.entries) + omitted != self.total:
            raise ValueError("catalog entries and omissions must account for the total")
        if len({item.product_id for item in self.entries}) != len(self.entries):
            raise ValueError("catalog product ids must be unique")
        return self


class ClientKnowledgeCardV2(BaseModel):
    """Company index plus a bounded catalog; detailed product facts are structurally absent."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["2"] = "2"
    card_kind: Literal["client_knowledge"] = "client_knowledge"
    content_semantics: Literal["reference_metadata_is_untrusted_data"] = (
        "reference_metadata_is_untrusted_data"
    )
    compiler_policy_version: Literal["client-knowledge-card-policy-v2"] = (
        CLIENT_KNOWLEDGE_CARD_V2_POLICY_VERSION
    )
    client_entity_id: str = Field(min_length=1)
    company_client_kb_version: int = Field(ge=1)
    known_fields: tuple[dict[str, JsonValue], ...]
    open_gaps: tuple[str, ...]
    coverage: dict[str, JsonValue]
    knowledge_omissions: tuple[dict[str, JsonValue], ...]
    product_catalog: ClientProductCatalog
    field_definition_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    def canonical_bytes(self) -> bytes:
        return canonical_card_bytes(self)

    def content_sha256(self) -> str:
        return f"sha256:{hashlib.sha256(self.canonical_bytes()).hexdigest()}"


class ProductProfileCard(BaseModel):
    """Durable selected-product identity compiled only from the object spine."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = "1"
    card_kind: Literal["product_profile"] = "product_profile"
    compiler_policy_version: Literal["product-profile-card-policy-v1"] = (
        PRODUCT_PROFILE_CARD_POLICY_VERSION
    )
    product_id: str = Field(min_length=1)
    brand_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    aliases: tuple[str, ...]
    status: Literal["active", "archived"]

    def canonical_bytes(self) -> bytes:
        return canonical_card_bytes(self)

    def content_sha256(self) -> str:
        return f"sha256:{hashlib.sha256(self.canonical_bytes()).hexdigest()}"


class ProductKnowledgeField(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    field_key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    description: str = Field(min_length=1)
    topic: ProductKnowledgeTopic
    brief_value: str = Field(min_length=1)
    claim_id: str = Field(min_length=1)
    brief_truncated: bool = False
    description_truncated: bool = False
    retired: bool = False


class ProductKnowledgeCoverage(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    required: int = Field(ge=0)
    filled: int = Field(ge=0)

    @model_validator(mode="after")
    def filled_does_not_exceed_required(self) -> ProductKnowledgeCoverage:
        if self.filled > self.required:
            raise ValueError("filled product fields exceed required fields")
        return self


class ProductKnowledgeOmission(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["product_knowledge_over_cap"] = "product_knowledge_over_cap"
    count: int = Field(ge=1)
    cursor: str = Field(min_length=1, max_length=4096)


class ProductKnowledgeCard(BaseModel):
    """Bounded research index for one exact product-scoped Client-KB version."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1"] = "1"
    card_kind: Literal["product_knowledge"] = "product_knowledge"
    content_semantics: Literal["claim_content_is_untrusted_evidence"] = (
        "claim_content_is_untrusted_evidence"
    )
    compiler_policy_version: Literal["product-knowledge-card-policy-v1"] = (
        PRODUCT_KNOWLEDGE_CARD_POLICY_VERSION
    )
    product_kb_version: int = Field(ge=1)
    known_fields: tuple[ProductKnowledgeField, ...]
    open_gaps: tuple[str, ...]
    coverage: ProductKnowledgeCoverage
    omissions: tuple[ProductKnowledgeOmission, ...]
    field_definition_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    def canonical_bytes(self) -> bytes:
        return canonical_card_bytes(self)

    def content_sha256(self) -> str:
        return f"sha256:{hashlib.sha256(self.canonical_bytes()).hexdigest()}"


class ProductKnowledgeCardPolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal["product-knowledge-card-policy-v1"] = PRODUCT_KNOWLEDGE_CARD_POLICY_VERSION
    max_brief_bytes: int = Field(default=256, ge=1)
    max_description_bytes: int = Field(default=320, ge=1)
    max_known_fields_bytes: int = Field(default=8_000, ge=1)
    max_card_bytes: int = Field(default=16_000, ge=1)


PRODUCT_KNOWLEDGE_CARD_POLICY_V1 = ProductKnowledgeCardPolicy()


__all__ = [
    "CLIENT_KNOWLEDGE_CARD_V2_MEDIA_TYPE",
    "CLIENT_KNOWLEDGE_CARD_V2_POLICY_VERSION",
    "PRODUCT_KNOWLEDGE_CARD_MEDIA_TYPE",
    "PRODUCT_KNOWLEDGE_CARD_POLICY_V1",
    "PRODUCT_KNOWLEDGE_CARD_POLICY_VERSION",
    "PRODUCT_KNOWLEDGE_CURSOR_POLICY_VERSION",
    "PRODUCT_PROFILE_CARD_MEDIA_TYPE",
    "PRODUCT_PROFILE_CARD_POLICY_VERSION",
    "ClientKnowledgeCardV2",
    "ClientProductCatalog",
    "ProductCatalogEntry",
    "ProductCatalogOmission",
    "ProductKnowledgeCard",
    "ProductKnowledgeCardPolicy",
    "ProductKnowledgeCoverage",
    "ProductKnowledgeField",
    "ProductKnowledgeOmission",
    "ProductKnowledgeTopic",
    "ProductProfileCard",
    "canonical_card_bytes",
    "product_knowledge_topic",
]
