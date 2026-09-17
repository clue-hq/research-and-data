"""Executable S5.0 product-knowledge consumption decision.

S5.0 is a contract gate, not the catalog/runtime implementation.  This provider-, storage-, and
database-free module freezes the architecture that S5 must implement without registering a new
card, tool, migration, or production policy prematurely.

Company knowledge remains the ``product_id IS NULL`` Client-KB.  Detailed product knowledge uses
the independently versioned Client-KB sequence whose ``product_id`` is the human-confirmed project
product.  Opening selected-product context uses both a bounded card and governed exact-read tools;
the model supplies filters or a claim reference but never any scope coordinate.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    "COMPANY_AND_SELECTED_PRODUCT_SCOPE_POLICY_V2",
    "COMPANY_AND_SELECTED_PRODUCT_SCOPE_POLICY_V3",
    "LIST_PRODUCT_KNOWLEDGE_ADDRESS",
    "INSPECT_PRODUCT_CLAIM_ADDRESS",
    "MODEL_VISIBLE_LIST_PRODUCT_KNOWLEDGE_FIELDS",
    "MODEL_VISIBLE_INSPECT_PRODUCT_CLAIM_FIELDS",
    "TRUSTED_PRODUCT_KNOWLEDGE_FIELDS",
    "PRODUCT_KNOWLEDGE_CONSUMPTION_DECISION_VERSION",
    "S50_CONTEXT_STATES",
    "S50_RATIFIED_DECISIONS",
    "ProductKnowledgeContextState",
]

PRODUCT_KNOWLEDGE_CONSUMPTION_DECISION_VERSION = "product-knowledge-consumption-s50-v1"
COMPANY_AND_SELECTED_PRODUCT_SCOPE_POLICY_V2 = "company-and-selected-product-v2"
# V2 remains readable for immutable historical receipts. Founder ruling 2026-08-19 supersedes
# its ``selected_without_product_knowledge`` state for every new turn: selecting a product now
# bootstraps an empty Product-KB, and V3 makes that lineage mandatory whenever product identity is
# present on the receipt.
COMPANY_AND_SELECTED_PRODUCT_SCOPE_POLICY_V3 = "company-and-selected-product-required-v3"

LIST_PRODUCT_KNOWLEDGE_ADDRESS = "list_product_knowledge@1"
INSPECT_PRODUCT_CLAIM_ADDRESS = "inspect_product_claim@1"

# These are deliberately parallel to S4, but they are separate addresses and contracts.  Adding
# ``product_id`` to the company tools would let a model-authored argument change authority.
MODEL_VISIBLE_LIST_PRODUCT_KNOWLEDGE_FIELDS = ("topic", "field_key", "cursor", "limit")
MODEL_VISIBLE_INSPECT_PRODUCT_CLAIM_FIELDS = ("claim_id",)
TRUSTED_PRODUCT_KNOWLEDGE_FIELDS = (
    "workspace_id",
    "client_entity_id",
    "product_id",
    "product_kb_version",
)

S50_RATIFIED_DECISIONS = (
    "company_facts_use_account_wide_client_kb",
    "product_facts_use_independent_product_scoped_kb",
    "selected_product_uses_bounded_card_and_governed_tools",
    "product_scope_is_derived_only_from_trusted_turn_pin",
    "client_knowledge_card_v2_owns_bounded_product_catalog",
)

_BASE_CARDS = (
    "client_knowledge@2",
    "project_conversation@2",
    "stage0_project_state@1",
)
_CLIENT_TOOLS = ("list_client_knowledge@2", "inspect_client_claim@2")
_PRODUCT_TOOLS = (LIST_PRODUCT_KNOWLEDGE_ADDRESS, INSPECT_PRODUCT_CLAIM_ADDRESS)
_ALLOWED_CARDS = {*_BASE_CARDS, "product_profile@1", "product_knowledge@1"}
_ALLOWED_TOOLS = {*_CLIENT_TOOLS, *_PRODUCT_TOOLS}


class ProductKnowledgeContextState(BaseModel):
    """One post-recon model-visible state frozen by the S5.0 decision.

    ``product_kb_version`` is the independent product-scoped version, not the company version and
    not a project-selected value.  A selected product may honestly have no product knowledge yet;
    its durable identity profile remains available while the knowledge card/tools remain absent.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: Literal[
        "catalog_unselected",
        "selected_without_product_knowledge",
        "selected_with_product_knowledge",
        "selected_other_product",
    ]
    company_client_kb_version: int = Field(ge=1)
    confirmed_product_id: str | None
    product_kb_version: int | None = Field(default=None, ge=1)
    cards: tuple[str, ...]
    model_tools: tuple[str, ...]

    @model_validator(mode="after")
    def context_is_coherent(self) -> Self:
        cards = set(self.cards)
        tools = set(self.model_tools)
        if len(cards) != len(self.cards) or len(tools) != len(self.model_tools):
            raise ValueError("context cards and model tools must be unique")
        if not cards <= _ALLOWED_CARDS or not tools <= _ALLOWED_TOOLS:
            raise ValueError("context state contains an unratified card or tool")
        if self.confirmed_product_id is not None and not self.confirmed_product_id.strip():
            raise ValueError("a confirmed product id cannot be blank")
        if not set(_BASE_CARDS).issubset(cards) or not set(_CLIENT_TOOLS).issubset(tools):
            raise ValueError("every post-recon state requires company and active-project context")
        selected = self.confirmed_product_id is not None
        has_profile = "product_profile@1" in cards
        has_product_knowledge = "product_knowledge@1" in cards
        has_product_tools = bool(set(_PRODUCT_TOOLS).intersection(tools))
        if selected != has_profile:
            raise ValueError("selected-product identity and ProductProfileCard must agree")
        if self.product_kb_version is not None and not selected:
            raise ValueError("product knowledge cannot exist without a confirmed project product")
        if has_product_knowledge != (self.product_kb_version is not None):
            raise ValueError("ProductKnowledgeCard availability must match the pinned version")
        if has_product_tools != (self.product_kb_version is not None):
            raise ValueError("product tools are exposed only with a trusted product-KB pin")
        if has_product_tools and not set(_PRODUCT_TOOLS).issubset(tools):
            raise ValueError("product list and inspect tools are admitted as one paired surface")
        return self


S50_CONTEXT_STATES = (
    ProductKnowledgeContextState(
        name="catalog_unselected",
        company_client_kb_version=7,
        confirmed_product_id=None,
        cards=_BASE_CARDS,
        model_tools=_CLIENT_TOOLS,
    ),
    ProductKnowledgeContextState(
        name="selected_without_product_knowledge",
        company_client_kb_version=7,
        confirmed_product_id="prd_a",
        cards=(*_BASE_CARDS, "product_profile@1"),
        model_tools=_CLIENT_TOOLS,
    ),
    ProductKnowledgeContextState(
        name="selected_with_product_knowledge",
        company_client_kb_version=7,
        confirmed_product_id="prd_a",
        product_kb_version=3,
        cards=(*_BASE_CARDS, "product_profile@1", "product_knowledge@1"),
        model_tools=(*_CLIENT_TOOLS, *_PRODUCT_TOOLS),
    ),
    ProductKnowledgeContextState(
        name="selected_other_product",
        company_client_kb_version=7,
        confirmed_product_id="prd_b",
        product_kb_version=2,
        cards=(*_BASE_CARDS, "product_profile@1", "product_knowledge@1"),
        model_tools=(*_CLIENT_TOOLS, *_PRODUCT_TOOLS),
    ),
)
