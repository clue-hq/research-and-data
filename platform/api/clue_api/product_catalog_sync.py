"""S5-B conservative Client-KB product-catalog to object-spine synchronization."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import text

from clue_api.client_knowledge_reader import load_pinned_client_knowledge
from clue_core import EntityId
from clue_db import ConnFactory, transaction
from clue_obs import get_logger
from clue_research.official_site import OfficialSiteMaterializationRequest
from clue_research.stage0 import CLIENT_PRODUCT_CATALOG, current_kb_version
from clue_spine import Product, list_products

log = get_logger("clue_api.product_catalog_sync")

PRODUCT_CATALOG_SYNC_POLICY_VERSION = "product-catalog-sync-v1"


class CatalogEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, max_length=240)
    short_description: str = Field(min_length=1, max_length=600)
    aliases: tuple[str, ...] = Field(default=(), max_length=20)


@dataclass(frozen=True, slots=True)
class CatalogLineage:
    lineage_id: UUID
    entry_ordinal: int
    entry_fingerprint_sha256: str
    product_id: str | None
    product_kb_version_at_sync: int | None
    resolution_state: str
    candidate_count: int


@dataclass(frozen=True, slots=True)
class ProductCatalogSyncResult:
    workspace_id: str
    client_entity_id: EntityId
    company_client_kb_version: int
    catalog_claim_id: UUID | None
    lineages: tuple[CatalogLineage, ...]

    @property
    def linked_product_ids(self) -> tuple[str, ...]:
        return tuple(item.product_id for item in self.lineages if item.product_id is not None)


class ProductCatalogScopeError(ValueError):
    pass


def normalize_catalog_identity(value: str) -> str:
    """Conservative comparison normalization, never a merge key by itself."""

    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value).strip()).casefold()


def _fingerprint(entry: CatalogEntry) -> str:
    payload = {
        "name": entry.name,
        "short_description": entry.short_description,
        "aliases": list(entry.aliases),
        "policy": PRODUCT_CATALOG_SYNC_POLICY_VERSION,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def _alias_candidates(entry: CatalogEntry, products: list[Product]) -> list[Product]:
    observed = {normalize_catalog_identity(entry.name)} | {
        normalize_catalog_identity(alias) for alias in entry.aliases
    }
    return [
        product
        for product in products
        if observed
        & {normalize_catalog_identity(alias) for alias in product.aliases if alias.strip()}
    ]


def _name_candidates(entry: CatalogEntry, products: list[Product]) -> list[Product]:
    name = normalize_catalog_identity(entry.name)
    return [product for product in products if normalize_catalog_identity(product.name) == name]


class ProductCatalogSynchronizer:
    """Synchronize one exact company catalog; product rows never overwrite catalog evidence."""

    def __init__(self, conn_factory: ConnFactory = transaction) -> None:
        self._conn_factory = conn_factory

    async def synchronize(
        self,
        request: OfficialSiteMaterializationRequest,
        *,
        company_client_kb_version: int,
    ) -> ProductCatalogSyncResult:
        client_id = EntityId(request.client_entity_id)
        async with self._conn_factory() as conn:
            pinned = await load_pinned_client_knowledge(
                conn,
                workspace_id=request.workspace_id,
                client_entity_id=client_id,
                client_kb_version=company_client_kb_version,
            )
            if pinned is None:
                raise ProductCatalogScopeError("company Client-KB version is unavailable")
            claim = pinned.claims_by_field.get(CLIENT_PRODUCT_CATALOG)
            if claim is None:
                return ProductCatalogSyncResult(
                    workspace_id=request.workspace_id,
                    client_entity_id=client_id,
                    company_client_kb_version=company_client_kb_version,
                    catalog_claim_id=None,
                    lineages=(),
                )
            if claim.product_id is not None:
                raise ProductCatalogScopeError("catalog claim is not account-wide")
            try:
                entries = tuple(
                    CatalogEntry.model_validate(item)
                    for item in (claim.value_json if isinstance(claim.value_json, list) else ())
                )
            except ValidationError as exc:
                raise ProductCatalogScopeError(
                    "catalog claim does not match its field contract"
                ) from exc
            if not isinstance(claim.value_json, list):
                raise ProductCatalogScopeError("catalog claim is not a list")

            brand_row = (
                await conn.execute(
                    text(
                        "SELECT brand_id FROM recon_run WHERE id=:recon_run_id "
                        "AND workspace_id=:workspace_id AND client_entity_id=:client_entity_id"
                    ),
                    {
                        "recon_run_id": request.recon_run_id,
                        "workspace_id": request.workspace_id,
                        "client_entity_id": client_id,
                    },
                )
            ).scalar_one_or_none()
            if brand_row is None:
                raise ProductCatalogScopeError("catalog recon brand is unavailable")
            brand_id = str(brand_row)
            products = await list_products(conn, brand_id)
            if any(product.workspace_id != request.workspace_id for product in products):
                raise ProductCatalogScopeError("catalog brand crossed its workspace")

            output: list[CatalogLineage] = []
            for ordinal, entry in enumerate(entries):
                fingerprint = _fingerprint(entry)
                existing = await self._existing(
                    conn,
                    catalog_claim_id=UUID(str(claim.id)),
                    entry_ordinal=ordinal,
                )
                if existing is not None:
                    if existing.entry_fingerprint_sha256 != fingerprint:
                        raise ProductCatalogScopeError("catalog lineage fingerprint conflict")
                    output.append(existing)
                    continue

                aliases = _alias_candidates(entry, products)
                names = _name_candidates(entry, products)
                if len(aliases) == 1:
                    product_id = aliases[0].product_id
                    state = "alias_reused"
                    candidate_count = 1
                elif aliases or names:
                    product_id = None
                    state = "unresolved_ambiguous"
                    candidate_count = len({item.product_id for item in (*aliases, *names)})
                else:
                    product_identity = (
                        f"catalog:{request.workspace_id}:{brand_id}:{claim.id}:"
                        f"{ordinal}:{fingerprint}"
                    )
                    product_id = f"prd_{uuid5(NAMESPACE_URL, product_identity).hex}"
                    await conn.execute(
                        text(
                            "INSERT INTO product "
                            "(product_id, brand_id, workspace_id, name, aliases) "
                            "VALUES (:product_id, :brand_id, :workspace_id, :name, "
                            "CAST(:aliases AS jsonb)) ON CONFLICT (product_id) DO NOTHING"
                        ),
                        {
                            "product_id": product_id,
                            "brand_id": brand_id,
                            "workspace_id": request.workspace_id,
                            "name": entry.name,
                            "aliases": json.dumps(list(entry.aliases)),
                        },
                    )
                    state = "created"
                    candidate_count = 0
                    products = await list_products(conn, brand_id)

                lineage_id = uuid5(
                    NAMESPACE_URL,
                    f"product-catalog-lineage:{claim.id}:{ordinal}",
                )
                product_kb_version_at_sync = (
                    None
                    if product_id is None
                    else await current_kb_version(
                        conn,
                        client_id,
                        workspace_id=request.workspace_id,
                        product_id=product_id,
                    )
                )
                await conn.execute(
                    text(
                        "INSERT INTO product_catalog_lineage "
                        "(lineage_id, workspace_id, brand_id, client_entity_id, "
                        "company_client_kb_version, catalog_claim_id, entry_ordinal, "
                        "entry_fingerprint_sha256, product_id, product_kb_version_at_sync, "
                        "resolution_state, candidate_count) "
                        "VALUES (:lineage_id, :workspace_id, :brand_id, :client_entity_id, "
                        ":company_version, :catalog_claim_id, :entry_ordinal, :fingerprint, "
                        ":product_id, :product_kb_version_at_sync, :resolution_state, "
                        ":candidate_count) "
                        "ON CONFLICT (catalog_claim_id, entry_ordinal) DO NOTHING"
                    ),
                    {
                        "lineage_id": lineage_id,
                        "workspace_id": request.workspace_id,
                        "brand_id": brand_id,
                        "client_entity_id": client_id,
                        "company_version": company_client_kb_version,
                        "catalog_claim_id": claim.id,
                        "entry_ordinal": ordinal,
                        "fingerprint": fingerprint,
                        "product_id": product_id,
                        "product_kb_version_at_sync": product_kb_version_at_sync,
                        "resolution_state": state,
                        "candidate_count": candidate_count,
                    },
                )
                retained = await self._existing(
                    conn,
                    catalog_claim_id=UUID(str(claim.id)),
                    entry_ordinal=ordinal,
                )
                if retained is None or retained.entry_fingerprint_sha256 != fingerprint:
                    raise ProductCatalogScopeError("catalog lineage race disagreed with input")
                output.append(retained)

        log.info(
            "product_catalog.synchronized",
            workspace_id=request.workspace_id,
            client_entity_id=str(client_id),
            company_client_kb_version=company_client_kb_version,
            catalog_claim_id=str(claim.id),
            entries=len(entries),
            linked=sum(item.product_id is not None for item in output),
            unresolved=sum(item.product_id is None for item in output),
        )
        return ProductCatalogSyncResult(
            workspace_id=request.workspace_id,
            client_entity_id=client_id,
            company_client_kb_version=company_client_kb_version,
            catalog_claim_id=UUID(str(claim.id)),
            lineages=tuple(output),
        )

    @staticmethod
    async def _existing(
        conn: object,
        *,
        catalog_claim_id: UUID,
        entry_ordinal: int,
    ) -> CatalogLineage | None:
        row = (
            (
                await conn.execute(  # type: ignore[attr-defined]
                    text(
                        "SELECT lineage_id, entry_ordinal, entry_fingerprint_sha256, product_id, "
                        "product_kb_version_at_sync, resolution_state, candidate_count "
                        "FROM product_catalog_lineage "
                        "WHERE catalog_claim_id=:catalog_claim_id AND entry_ordinal=:entry_ordinal"
                    ),
                    {
                        "catalog_claim_id": catalog_claim_id,
                        "entry_ordinal": entry_ordinal,
                    },
                )
            )
            .mappings()
            .one_or_none()
        )
        return CatalogLineage(**dict(row)) if row is not None else None


__all__ = [
    "PRODUCT_CATALOG_SYNC_POLICY_VERSION",
    "CatalogEntry",
    "CatalogLineage",
    "ProductCatalogScopeError",
    "ProductCatalogSyncResult",
    "ProductCatalogSynchronizer",
    "normalize_catalog_identity",
]
