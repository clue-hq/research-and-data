"""Provider/DB-free S5-A contract acceptance."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from clue_api.product_context_authority import trusted_product_scope_fields
from clue_api.product_knowledge_contracts import (
    InspectProductClaimInput,
    ListProductKnowledgeInput,
    ProductKnowledgeCursor,
    ProductKnowledgeCursorRefused,
    ProductKnowledgeRefusalCode,
    decode_product_knowledge_cursor,
    encode_product_knowledge_cursor,
)
from clue_projections import (
    CLIENT_KNOWLEDGE_CARD_V2_MEDIA_TYPE,
    PRODUCT_KNOWLEDGE_CARD_MEDIA_TYPE,
    PRODUCT_PROFILE_CARD_MEDIA_TYPE,
    ClientKnowledgeCardV2,
    ClientProductCatalog,
    ProductCatalogEntry,
    ProductKnowledgeCard,
    ProductKnowledgeCoverage,
    ProductKnowledgeField,
    ProductKnowledgeTopic,
    ProductProfileCard,
)
from clue_research.stage0 import (
    CLIENT_PRODUCT_CATALOG,
    PRODUCT_KNOWLEDGE_FIELDS,
)

_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures/production_context/s5a_product_contract_fixture.json"
)
_CLIENT = UUID("00000000-0000-4000-8000-000000000001")


def test_fixture_matches_registered_fields_cards_and_tool_contracts() -> None:
    fixture = json.loads(_FIXTURE.read_text())
    assert fixture["company_catalog_field"] == CLIENT_PRODUCT_CATALOG
    assert fixture["product_fields"] == list(PRODUCT_KNOWLEDGE_FIELDS)
    assert fixture["card_media_types"] == {
        "client_knowledge_v2": CLIENT_KNOWLEDGE_CARD_V2_MEDIA_TYPE,
        "product_profile_v1": PRODUCT_PROFILE_CARD_MEDIA_TYPE,
        "product_knowledge_v1": PRODUCT_KNOWLEDGE_CARD_MEDIA_TYPE,
    }
    assert fixture["model_fields"] == {
        "list": ["topic", "field_key", "cursor", "limit"],
        "inspect": ["claim_id"],
    }
    assert fixture["trusted_fields"] == [
        "client_entity_id",
        *trusted_product_scope_fields(ListProductKnowledgeInput),
    ]
    assert trusted_product_scope_fields(InspectProductClaimInput) == (
        "product_id",
        "product_kb_version",
    )
    assert fixture["refusal_codes"] == [
        ProductKnowledgeRefusalCode.SCOPE_UNAVAILABLE,
        ProductKnowledgeRefusalCode.CURSOR_INVALID,
        ProductKnowledgeRefusalCode.CLAIM_NOT_FOUND,
    ]


def test_model_visible_schemas_cannot_author_product_authority() -> None:
    trusted = {"client_entity_id", "product_id", "product_kb_version", "workspace_id"}
    for model, visible in (
        (ListProductKnowledgeInput, {"topic", "field_key", "cursor", "limit"}),
        (InspectProductClaimInput, {"claim_id"}),
    ):
        schema = model.model_json_schema()
        model_visible = set(schema["properties"]) - {
            "client_entity_id",
            *trusted_product_scope_fields(model),
        }
        assert model_visible == visible
        assert model_visible.isdisjoint(trusted)


def test_product_cursor_is_exactly_scope_and_filter_bound() -> None:
    cursor = ProductKnowledgeCursor(
        client_entity_id=_CLIENT,
        product_id="prd_a",
        product_kb_version=4,
        after_field_key="client.product_capability",
        topic=ProductKnowledgeTopic.CAPABILITIES_AND_USE_CASES,
        field_key=None,
        limit=12,
    )
    encoded = encode_product_knowledge_cursor(cursor)
    assert (
        decode_product_knowledge_cursor(
            encoded,
            client_entity_id=_CLIENT,
            product_id="prd_a",
            product_kb_version=4,
            topic=ProductKnowledgeTopic.CAPABILITIES_AND_USE_CASES,
            field_key=None,
            limit=12,
        )
        == cursor
    )
    for changed in (
        {"product_id": "prd_b"},
        {"product_kb_version": 5},
        {"topic": ProductKnowledgeTopic.OVERVIEW},
        {"limit": 11},
    ):
        kwargs = {
            "client_entity_id": _CLIENT,
            "product_id": "prd_a",
            "product_kb_version": 4,
            "topic": ProductKnowledgeTopic.CAPABILITIES_AND_USE_CASES,
            "field_key": None,
            "limit": 12,
            **changed,
        }
        with pytest.raises(ProductKnowledgeCursorRefused):
            decode_product_knowledge_cursor(encoded, **kwargs)


def test_card_ownership_keeps_catalog_profile_and_product_facts_separate() -> None:
    catalog_entry = ProductCatalogEntry(
        product_id="prd_a",
        name="Phone Agents",
        short_description="Healthcare call automation",
        aliases=("Voice",),
        status="active",
        catalog_claim_id=str(UUID(int=2)),
        product_knowledge_available=True,
    )
    company = ClientKnowledgeCardV2(
        client_entity_id=str(_CLIENT),
        company_client_kb_version=7,
        known_fields=(),
        open_gaps=(),
        coverage={},
        knowledge_omissions=(),
        product_catalog=ClientProductCatalog(entries=(catalog_entry,), total=1),
        field_definition_digest="sha256:" + "1" * 64,
    )
    profile = ProductProfileCard(
        product_id="prd_a",
        brand_id="brd_a",
        name="Phone Agents",
        aliases=("Voice",),
        status="active",
    )
    knowledge = ProductKnowledgeCard(
        product_kb_version=4,
        known_fields=(
            ProductKnowledgeField(
                field_key="client.product_capability",
                label="Product Capability",
                description="One grounded capability.",
                topic=ProductKnowledgeTopic.CAPABILITIES_AND_USE_CASES,
                brief_value="Schedules calls",
                claim_id=str(UUID(int=3)),
            ),
        ),
        open_gaps=(),
        coverage=ProductKnowledgeCoverage(required=9, filled=1),
        omissions=(),
        field_definition_digest="sha256:" + "2" * 64,
    )
    assert "product_kb_version" not in company.product_catalog.entries[0].model_fields_set
    assert "product_kb_version" not in ProductProfileCard.model_fields
    assert "product_id" not in ProductKnowledgeCard.model_fields
    assert (
        len({company.content_sha256(), profile.content_sha256(), knowledge.content_sha256()}) == 3
    )


def test_catalog_rejects_duplicate_product_identity_and_bad_counts() -> None:
    item = ProductCatalogEntry(
        product_id="prd_a",
        name="A",
        short_description="A product",
        status="active",
        catalog_claim_id=str(UUID(int=4)),
        product_knowledge_available=False,
    )
    with pytest.raises(ValidationError):
        ClientProductCatalog(entries=(item, item), total=2)
    with pytest.raises(ValidationError):
        ClientProductCatalog(entries=(item,), total=2)
