"""S5-C deterministic company-catalog and selected-product card compilers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import cast
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import text

from clue_api.client_knowledge_contracts import truncate_utf8
from clue_api.client_knowledge_reader import load_pinned_client_knowledge
from clue_api.product_knowledge_contracts import (
    DEFAULT_PRODUCT_KNOWLEDGE_PAGE_SIZE,
    ProductKnowledgeCursor,
    encode_product_knowledge_cursor,
)
from clue_api.product_knowledge_reader import load_pinned_product_knowledge
from clue_core import EntityId
from clue_db import ConnFactory, transaction
from clue_projections import (
    CLIENT_KNOWLEDGE_CARD_V2_POLICY,
    PRODUCT_KNOWLEDGE_CARD_POLICY_V1,
    ClientKnowledgeCardV2,
    ClientKnowledgeCardV2Policy,
    ClientProductCatalog,
    ProductCatalogEntry,
    ProductCatalogOmission,
    ProductKnowledgeCard,
    ProductKnowledgeCardPolicy,
    ProductKnowledgeCoverage,
    ProductKnowledgeField,
    ProductKnowledgeOmission,
    ProductProfileCard,
    Stage0CardTooLarge,
    client_knowledge_field_label,
    compile_client_knowledge_card,
    decode_card_cursor,
    encode_card_cursor,
    product_knowledge_topic,
)
from clue_research.stage0 import CLIENT_PRODUCT_CATALOG, PRODUCT_KNOWLEDGE_FIELDS
from clue_spine import get_product


class ProductContextScopeError(LookupError):
    pass


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def _definition_digest(definitions: Mapping[str, tuple[str, int, bool]]) -> str:
    return f"sha256:{hashlib.sha256(_canonical_json(definitions)).hexdigest()}"


def _brief(value: JsonValue) -> str:
    return value if isinstance(value, str) else _canonical_json(value).decode()


async def compile_product_profile_card(
    *,
    workspace_id: str,
    brand_id: str,
    product_id: str,
    conn_factory: ConnFactory = transaction,
) -> ProductProfileCard:
    async with conn_factory() as conn:
        product = await get_product(conn, product_id)
    if product is None or product.workspace_id != workspace_id or product.brand_id != brand_id:
        raise ProductContextScopeError("selected product profile is unavailable")
    return ProductProfileCard(
        product_id=product.product_id,
        brand_id=product.brand_id,
        name=product.name,
        aliases=product.aliases,
        status=product.status,
    )


async def compile_client_knowledge_card_v2(
    *,
    workspace_id: str,
    client_entity_id: EntityId,
    company_client_kb_version: int,
    policy: ClientKnowledgeCardV2Policy = CLIENT_KNOWLEDGE_CARD_V2_POLICY,
    conn_factory: ConnFactory = transaction,
) -> ClientKnowledgeCardV2:
    """Compile V2 without rewriting or changing V1 canonical bytes."""

    v1 = await compile_client_knowledge_card(
        workspace_id=workspace_id,
        client_entity_id=client_entity_id,
        client_kb_version=company_client_kb_version,
        conn_factory=conn_factory,
    )
    async with conn_factory() as conn:
        pinned = await load_pinned_client_knowledge(
            conn,
            workspace_id=workspace_id,
            client_entity_id=client_entity_id,
            client_kb_version=company_client_kb_version,
        )
        if pinned is None:
            raise ProductContextScopeError("company Client-KB scope is unavailable")
        catalog_claim = pinned.claims_by_field.get(CLIENT_PRODUCT_CATALOG)
        lineage_rows = []
        if catalog_claim is not None:
            lineage_rows = list(
                (
                    await conn.execute(
                        text(
                            "SELECT lineage.entry_ordinal, lineage.product_id, "
                            "lineage.product_kb_version_at_sync, product.name, product.aliases, "
                            "product.status FROM product_catalog_lineage AS lineage "
                            "JOIN product ON product.product_id=lineage.product_id "
                            "AND product.workspace_id=lineage.workspace_id "
                            "WHERE lineage.workspace_id=:workspace_id "
                            "AND lineage.client_entity_id=:client_entity_id "
                            "AND lineage.company_client_kb_version=:company_version "
                            "AND lineage.catalog_claim_id=:claim_id "
                            "AND lineage.product_id IS NOT NULL "
                            "ORDER BY lineage.entry_ordinal"
                        ),
                        {
                            "workspace_id": workspace_id,
                            "client_entity_id": client_entity_id,
                            "company_version": company_client_kb_version,
                            "claim_id": catalog_claim.id,
                        },
                    )
                ).mappings()
            )

    catalog_values = (
        catalog_claim.value_json
        if catalog_claim is not None and isinstance(catalog_claim.value_json, list)
        else []
    )
    candidates: list[ProductCatalogEntry] = []
    for row in lineage_rows:
        ordinal = int(row["entry_ordinal"])
        if ordinal >= len(catalog_values) or not isinstance(catalog_values[ordinal], dict):
            raise ProductContextScopeError("catalog lineage no longer matches its exact claim")
        observed = cast(dict[str, JsonValue], catalog_values[ordinal])
        description = observed.get("short_description")
        if not isinstance(description, str) or not description.strip():
            raise ProductContextScopeError("catalog description is unavailable")
        bounded_description, _ = truncate_utf8(
            description,
            policy.max_catalog_description_bytes,
        )
        aliases = row["aliases"] if isinstance(row["aliases"], list) else []
        assert catalog_claim is not None
        candidates.append(
            ProductCatalogEntry(
                product_id=str(row["product_id"]),
                name=str(row["name"]),
                short_description=bounded_description,
                aliases=tuple(str(item) for item in aliases),
                status=str(row["status"]),  # type: ignore[arg-type]
                catalog_claim_id=str(catalog_claim.id),
                product_knowledge_available=row["product_kb_version_at_sync"] is not None,
            )
        )

    included = tuple(candidates[: policy.max_catalog_entries])
    withheld = len(candidates) - len(included)
    catalog_omissions = (
        (
            ProductCatalogOmission(
                count=withheld,
                cursor=encode_card_cursor(
                    {
                        "kind": "product_catalog",
                        "schema_version": "1",
                        "client_entity_id": str(client_entity_id),
                        "company_client_kb_version": company_client_kb_version,
                        "catalog_claim_id": str(catalog_claim.id),
                        "after_product_id": included[-1].product_id,
                    }
                ),
            ),
        )
        if withheld and included and catalog_claim is not None
        else ()
    )
    v1_fields = tuple(
        item for item in v1.knowledge.known_fields if item.field_key != CLIENT_PRODUCT_CATALOG
    )
    card = ClientKnowledgeCardV2(
        client_entity_id=str(client_entity_id),
        company_client_kb_version=company_client_kb_version,
        known_fields=tuple(item.model_dump(mode="json") for item in v1_fields),
        open_gaps=v1.knowledge.open_gaps,
        coverage=v1.knowledge.coverage.model_dump(mode="json"),
        knowledge_omissions=tuple(item.model_dump(mode="json") for item in v1.omissions),
        product_catalog=ClientProductCatalog(
            entries=included,
            total=len(candidates),
            omissions=catalog_omissions,
        ),
        field_definition_digest=v1.compiled_from.field_definition_digest,
    )
    if len(card.canonical_bytes()) > policy.max_card_bytes:
        raise Stage0CardTooLarge("ClientKnowledgeCard@2 exceeds its byte boundary")
    return card


async def read_client_product_catalog_page(
    *,
    workspace_id: str,
    client_entity_id: EntityId,
    company_client_kb_version: int,
    cursor: str,
    limit: int = 20,
    conn_factory: ConnFactory = transaction,
) -> ClientProductCatalog:
    """Resolve one card omission without broadening the exact company/catalog pin."""

    if limit < 1 or limit > 20:
        raise ProductContextScopeError("catalog page limit is unavailable")
    try:
        payload = decode_card_cursor(cursor)
    except Exception as exc:
        raise ProductContextScopeError("catalog cursor is unavailable") from exc
    if (
        payload.get("kind") != "product_catalog"
        or payload.get("schema_version") != "1"
        or payload.get("client_entity_id") != str(client_entity_id)
        or payload.get("company_client_kb_version") != company_client_kb_version
        or not isinstance(payload.get("catalog_claim_id"), str)
        or not isinstance(payload.get("after_product_id"), str)
    ):
        raise ProductContextScopeError("catalog cursor is unavailable")
    full = await compile_client_knowledge_card_v2(
        workspace_id=workspace_id,
        client_entity_id=client_entity_id,
        company_client_kb_version=company_client_kb_version,
        policy=CLIENT_KNOWLEDGE_CARD_V2_POLICY.model_copy(
            update={"max_catalog_entries": 100, "max_card_bytes": 96_000}
        ),
        conn_factory=conn_factory,
    )
    entries = full.product_catalog.entries
    if entries and entries[0].catalog_claim_id != payload["catalog_claim_id"]:
        raise ProductContextScopeError("catalog cursor is unavailable")
    try:
        start = next(
            index + 1
            for index, entry in enumerate(entries)
            if entry.product_id == payload["after_product_id"]
        )
    except StopIteration as exc:
        raise ProductContextScopeError("catalog cursor is unavailable") from exc
    page = entries[start : start + limit]
    withheld = len(entries) - start - len(page)
    omissions = (
        (
            ProductCatalogOmission(
                count=withheld,
                cursor=encode_card_cursor(
                    {
                        **payload,
                        "after_product_id": page[-1].product_id,
                    }
                ),
            ),
        )
        if withheld and page
        else ()
    )
    return ClientProductCatalog(entries=page, total=len(page) + withheld, omissions=omissions)


async def compile_product_knowledge_card(
    *,
    workspace_id: str,
    client_entity_id: EntityId,
    product_id: str,
    product_kb_version: int,
    policy: ProductKnowledgeCardPolicy = PRODUCT_KNOWLEDGE_CARD_POLICY_V1,
    conn_factory: ConnFactory = transaction,
) -> ProductKnowledgeCard:
    async with conn_factory() as conn:
        pinned = await load_pinned_product_knowledge(
            conn,
            workspace_id=workspace_id,
            client_entity_id=client_entity_id,
            product_id=product_id,
            product_kb_version=product_kb_version,
        )
    if pinned is None:
        raise ProductContextScopeError("selected Product-KB version is unavailable")
    entries: list[ProductKnowledgeField] = []
    used = 0
    for field_key in pinned.ordered_field_keys:
        claim = pinned.claims_by_field[field_key]
        definition = pinned.definitions.get(field_key)
        description_source = (
            definition.description
            if definition is not None and definition.description
            else f"Registered Product-KB knowledge for {field_key}."
        )
        description, description_truncated = truncate_utf8(
            description_source,
            policy.max_description_bytes,
        )
        brief, brief_truncated = truncate_utf8(
            _brief(claim.value_json),
            policy.max_brief_bytes,
        )
        entry = ProductKnowledgeField(
            field_key=field_key,
            label=client_knowledge_field_label(field_key),
            description=description,
            topic=product_knowledge_topic(field_key),
            brief_value=brief,
            claim_id=str(claim.id),
            brief_truncated=brief_truncated,
            description_truncated=description_truncated,
            retired=definition is not None and not definition.active,
        )
        size = len(_canonical_json(entry.model_dump(mode="json")))
        if used + size > policy.max_known_fields_bytes:
            break
        used += size
        entries.append(entry)
    withheld = len(pinned.ordered_field_keys) - len(entries)
    omissions = (
        (
            ProductKnowledgeOmission(
                count=withheld,
                cursor=encode_product_knowledge_cursor(
                    ProductKnowledgeCursor(
                        client_entity_id=UUID(str(client_entity_id)),
                        product_id=product_id,
                        product_kb_version=product_kb_version,
                        after_field_key=entries[-1].field_key,
                        topic=None,
                        field_key=None,
                        limit=DEFAULT_PRODUCT_KNOWLEDGE_PAGE_SIZE,
                    )
                ),
            ),
        )
        if withheld and entries
        else ()
    )
    definition_shape = {
        field: (
            pinned.definitions[field].description or "",
            pinned.definitions[field].definition_version,
            pinned.definitions[field].active,
        )
        for field in PRODUCT_KNOWLEDGE_FIELDS
        if field in pinned.definitions
    }
    card = ProductKnowledgeCard(
        product_kb_version=product_kb_version,
        known_fields=tuple(entries),
        open_gaps=tuple(
            field for field in PRODUCT_KNOWLEDGE_FIELDS if field not in pinned.claims_by_field
        ),
        coverage=ProductKnowledgeCoverage(
            required=len(PRODUCT_KNOWLEDGE_FIELDS),
            filled=len(pinned.claims_by_field),
        ),
        omissions=omissions,
        field_definition_digest=_definition_digest(definition_shape),
    )
    if len(card.canonical_bytes()) > policy.max_card_bytes:
        raise Stage0CardTooLarge("ProductKnowledgeCard@1 exceeds its byte boundary")
    return card


__all__ = [
    "ProductContextScopeError",
    "compile_client_knowledge_card_v2",
    "compile_product_knowledge_card",
    "compile_product_profile_card",
    "read_client_product_catalog_page",
]
