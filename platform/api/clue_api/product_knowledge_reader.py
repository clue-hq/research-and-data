"""S5-C exact-version, retention-safe product-scoped Client-KB reader."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.client_context_binding import get_workspace_client_binding
from clue_core import Claim, ClaimId, EntityId
from clue_projections import ProductKnowledgeTopic, product_knowledge_topic
from clue_research.claimstore import (
    FieldFilters,
    FieldRegistryScope,
    ResolvedFieldDefinition,
    WorkspaceScope,
    claims_by_ids,
    claims_for,
    list_effective_fields,
)
from clue_research.identity import get_account
from clue_research.stage0 import (
    CLIENT_KB_VERSION,
    PRODUCT_KNOWLEDGE_FIELDS,
    read_client_kb_claims,
)
from clue_spine import get_product

PRODUCT_KNOWLEDGE_READER_POLICY_VERSION = "product-knowledge-reader-v1"


def _marker_version(value: object) -> int | None:
    if not isinstance(value, dict):
        return None
    version = value.get("version")
    return version if isinstance(version, int) and version >= 1 else None


@dataclass(frozen=True, slots=True)
class PinnedProductKnowledge:
    workspace_id: str
    client_entity_id: EntityId
    product_id: str
    product_kb_version: int
    claims_by_field: Mapping[str, Claim]
    claims_by_id: Mapping[ClaimId, Claim]
    definitions: Mapping[str, ResolvedFieldDefinition]
    ordered_field_keys: tuple[str, ...]

    def claim(self, claim_id: ClaimId) -> Claim | None:
        return self.claims_by_id.get(claim_id)


@dataclass(frozen=True, slots=True)
class PinnedProductKnowledgePage:
    field_keys: tuple[str, ...]
    total_matching: int
    has_more: bool
    next_after_field_key: str | None


class ProductKnowledgePositionInvalid(ValueError):
    pass


async def load_pinned_product_knowledge(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    client_entity_id: EntityId,
    product_id: str,
    product_kb_version: int,
) -> PinnedProductKnowledge | None:
    """Collapse foreign/unknown/wrong-version/cross-product into one absent result."""

    binding = await get_workspace_client_binding(conn, workspace_id=workspace_id)
    account = await get_account(conn, client_entity_id)
    product = await get_product(conn, product_id)
    if (
        binding is None
        or binding.client_entity_id != client_entity_id
        or account is None
        or account.workspace_id != workspace_id
        or product is None
        or product.workspace_id != workspace_id
    ):
        return None
    scope = WorkspaceScope.for_workspace(workspace_id)
    markers = await claims_for(
        conn,
        client_entity_id,
        CLIENT_KB_VERSION,
        include_superseded=True,
        scope=scope,
    )
    if not any(
        str(marker.product_id) == product_id
        and _marker_version(marker.value_json) == product_kb_version
        for marker in markers
    ):
        return None
    selected = await read_client_kb_claims(
        conn,
        client_entity_id,
        workspace_id=workspace_id,
        version=product_kb_version,
        product_id=product_id,
    )
    # A product marker is not authority to expose arbitrary company/dynamic fields. S5's frozen
    # product taxonomy is the only admissible field set for this reader.
    selected = {
        field_key: claim
        for field_key, claim in selected.items()
        if field_key in PRODUCT_KNOWLEDGE_FIELDS and str(claim.product_id) == product_id
    }
    eligible = await claims_by_ids(
        conn,
        (claim.id for claim in selected.values()),
        scope=scope,
        include_superseded=True,
        include_expired=False,
    )
    claims = {field_key: claim for field_key, claim in selected.items() if claim.id in eligible}
    resolved = await list_effective_fields(
        conn,
        scope=FieldRegistryScope.for_workspace(workspace_id),
        filters=FieldFilters(pack="client", active=None),
        include_retired=True,
    )
    ordered = tuple(field for field in PRODUCT_KNOWLEDGE_FIELDS if field in claims)
    return PinnedProductKnowledge(
        workspace_id=workspace_id,
        client_entity_id=client_entity_id,
        product_id=product_id,
        product_kb_version=product_kb_version,
        claims_by_field=MappingProxyType(claims),
        claims_by_id=MappingProxyType({claim.id: claim for claim in claims.values()}),
        definitions=MappingProxyType({item.field_def.field_key: item for item in resolved}),
        ordered_field_keys=ordered,
    )


def select_product_knowledge_page(
    pinned: PinnedProductKnowledge,
    *,
    topic: ProductKnowledgeTopic | None,
    field_key: str | None,
    after_field_key: str | None,
    limit: int,
) -> PinnedProductKnowledgePage:
    if limit < 1:
        raise ValueError("Product-KB page limit must be positive")
    if after_field_key is None:
        start = 0
    else:
        try:
            start = pinned.ordered_field_keys.index(after_field_key) + 1
        except ValueError as exc:
            raise ProductKnowledgePositionInvalid(
                "cursor position is absent from the pinned Product-KB"
            ) from exc

    def included(candidate: str) -> bool:
        return (topic is None or product_knowledge_topic(candidate) is topic) and (
            field_key is None or candidate == field_key
        )

    matching = tuple(item for item in pinned.ordered_field_keys if included(item))
    candidates = tuple(item for item in pinned.ordered_field_keys[start:] if included(item))
    page = candidates[:limit]
    has_more = len(candidates) > len(page)
    return PinnedProductKnowledgePage(
        field_keys=page,
        total_matching=len(matching),
        has_more=has_more,
        next_after_field_key=page[-1] if has_more and page else None,
    )


__all__ = [
    "PRODUCT_KNOWLEDGE_READER_POLICY_VERSION",
    "PinnedProductKnowledge",
    "PinnedProductKnowledgePage",
    "ProductKnowledgePositionInvalid",
    "load_pinned_product_knowledge",
    "select_product_knowledge_page",
]
