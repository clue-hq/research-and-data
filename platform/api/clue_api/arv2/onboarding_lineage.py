"""Lineup entries → spine product rows, with artifact-keyed lineage.

A port of the S5-B resolution ladder (exact-fingerprint lineage reuse → single alias/name hit →
ambiguity left open → mint) onto ``onboarding_product_lineage``, keyed on the catalog DOCUMENT
rather than a Client-KB claim (standing rule, catalog contract §10). Name normalization is a
comparison aid, never a merge key by itself; nothing here renames, merges or archives a product.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_spine import Product, list_products

__all__ = ["CatalogProduct", "ProductLink", "normalize_identity", "synchronize_catalog"]

POLICY_VERSION = "onboarding-catalog-sync-v1"


@dataclass(frozen=True)
class CatalogProduct:
    name: str
    short_description: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProductLink:
    product_id: str | None
    name: str
    resolution_state: str
    candidate_count: int
    lineage_id: UUID


#: Trademark/service-mark/copyright marks a company decorates its own product names with. They are
#: stripped BEFORE NFKC, which would otherwise expand ``™`` into the letters ``tm`` and make
#: ``Aura™`` normalize to ``auratm`` — a different identity from ``Aura``.
_MARKS = str.maketrans("", "", "™®©℠")

#: Tokens that say nothing about WHICH product this is. Four live runs on one workspace grew the
#: product rows from 19 to 28 because the lineup called the same offering "AI Front Desk" once and
#: "AI FrontDesk Agent" the next time. Dropping them is a comparison aid only — a normalized hit
#: still has to survive the resolution ladder, and nothing here renames or merges anything.
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


def normalize_identity(value: str) -> str:
    """A comparison key for a product name: mark-free, case-free, spacing- and punctuation-free.

    Whitespace and punctuation are not identity ("Front Desk" and "FrontDesk" are one product), so
    the tokens are joined with nothing. No word is ever dropped: a stoplist of "generic" tokens is a
    one-company heuristic that would silently merge distinct products elsewhere (founder ruling
    2026-09-08). Identity beyond spelling is the resolver ladder's job, not this key's.
    """
    folded = unicodedata.normalize("NFKC", value.translate(_MARKS)).casefold()
    return "".join(_TOKEN.findall(folded))


def _fingerprint(entry: CatalogProduct) -> str:
    payload = {
        "name": entry.name,
        "short_description": entry.short_description,
        "aliases": list(entry.aliases),
        "policy": POLICY_VERSION,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def _candidates(entry: CatalogProduct, products: Sequence[Product]) -> list[Product]:
    # An empty key is not an identity (a name of nothing but punctuation or marks normalizes to
    # ""), so it may never match another empty one.
    observed = {
        key
        for key in {normalize_identity(entry.name)} | {normalize_identity(a) for a in entry.aliases}
        if key
    }
    hits: list[Product] = []
    for product in products:
        names = {normalize_identity(product.name)} | {
            normalize_identity(a) for a in product.aliases if a.strip()
        }
        if observed & names:
            hits.append(product)
    return hits


async def _assert_document_scope(
    conn: AsyncConnection, *, workspace_id: str, brand_id: str, document_id: UUID
) -> None:
    """The lineage's ``document_id`` FK is single-column, so the document's own workspace/brand is
    the only thing that says which brand's catalog this is. Check it before anything is written —
    otherwise a caller could mint one brand's products from another brand's document."""
    row = (
        (
            await conn.execute(
                text(
                    "SELECT workspace_id, brand_id FROM brand_knowledge_document "
                    "WHERE document_id = :id"
                ),
                {"id": document_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None or row["workspace_id"] != workspace_id or row["brand_id"] != brand_id:
        raise ValueError("catalog document is not in this workspace/brand")


async def _prior_product_id(
    conn: AsyncConnection, *, workspace_id: str, brand_id: str, fingerprint: str
) -> str | None:
    return (
        await conn.execute(
            text(
                "SELECT product_id FROM onboarding_product_lineage WHERE workspace_id = :ws "
                "AND brand_id = :brand AND entry_fingerprint_sha256 = :fp "
                "AND product_id IS NOT NULL ORDER BY synchronized_at DESC LIMIT 1"
            ),
            {"ws": workspace_id, "brand": brand_id, "fp": fingerprint},
        )
    ).scalar_one_or_none()


async def synchronize_catalog(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    brand_id: str,
    document_id: UUID,
    products: Sequence[CatalogProduct],
) -> tuple[ProductLink, ...]:
    await _assert_document_scope(
        conn, workspace_id=workspace_id, brand_id=brand_id, document_id=document_id
    )
    existing = await list_products(conn, brand_id)
    if any(p.workspace_id != workspace_id for p in existing):
        raise ValueError("catalog brand crossed its workspace")
    links: list[ProductLink] = []
    for ordinal, entry in enumerate(products):
        fingerprint = _fingerprint(entry)
        lineage_id = uuid5(NAMESPACE_URL, f"onboarding-product-lineage:{document_id}:{ordinal}")
        already = (
            (
                await conn.execute(
                    text(
                        "SELECT product_id, resolution_state, candidate_count, "
                        " entry_fingerprint_sha256 FROM onboarding_product_lineage "
                        "WHERE lineage_id = :id"
                    ),
                    {"id": lineage_id},
                )
            )
            .mappings()
            .first()
        )
        if already is not None:
            # This ordinal was already synchronized against this document, so the durable row IS
            # the answer and the link merely mirrors it — product id, state and candidate count
            # verbatim. A ``ProductLink`` is a projection of the lineage row, never a value the
            # table does not hold, so a replay of a ``created`` entry reports ``created``.
            #
            # A document version is immutable, so the same ordinal must carry the same entry. When
            # it does not, the caller re-published a *different* catalog under the same document
            # id: the append-only row cannot be corrected and returning it would hand back a link
            # for the wrong entry, so this fails loud instead.
            if str(already["entry_fingerprint_sha256"]) != fingerprint:
                raise ValueError("catalog document entry changed under its lineage")
            links.append(
                ProductLink(
                    already["product_id"],
                    entry.name,
                    str(already["resolution_state"]),
                    int(already["candidate_count"]),
                    lineage_id,
                )
            )
            continue
        product_id: str | None
        prior = await _prior_product_id(
            conn, workspace_id=workspace_id, brand_id=brand_id, fingerprint=fingerprint
        )
        if prior is not None and any(p.product_id == prior for p in existing):
            product_id, state, count = prior, "lineage_reused", 1
        else:
            hits = _candidates(entry, existing)
            if len(hits) == 1:
                product_id, state, count = hits[0].product_id, "alias_reused", 1
            elif hits:
                product_id, state, count = (
                    None,
                    "unresolved_ambiguous",
                    len({h.product_id for h in hits}),
                )
            else:
                minted = uuid5(
                    NAMESPACE_URL,
                    f"onboarding-catalog:{workspace_id}:{brand_id}:{document_id}:{ordinal}:"
                    f"{fingerprint}",
                )
                product_id = f"prd_{minted.hex}"
                await conn.execute(
                    text(
                        "INSERT INTO product (product_id, brand_id, workspace_id, name, aliases) "
                        "VALUES (:product_id, :brand_id, :workspace_id, :name, "
                        " CAST(:aliases AS jsonb)) ON CONFLICT (product_id) DO NOTHING"
                    ),
                    {
                        "product_id": product_id,
                        "brand_id": brand_id,
                        "workspace_id": workspace_id,
                        "name": entry.name,
                        "aliases": json.dumps(list(entry.aliases)),
                    },
                )
                state, count = "created", 0
                existing = await list_products(conn, brand_id)
        await conn.execute(
            text(
                "INSERT INTO onboarding_product_lineage (lineage_id, workspace_id, brand_id, "
                " document_id, entry_ordinal, entry_fingerprint_sha256, product_id, "
                " resolution_state, candidate_count) "
                "VALUES (:id, :ws, :brand, :doc, :ordinal, :fp, :product_id, :state, :count) "
                "ON CONFLICT (document_id, entry_ordinal) DO NOTHING"
            ),
            {
                "id": lineage_id,
                "ws": workspace_id,
                "brand": brand_id,
                "doc": document_id,
                "ordinal": ordinal,
                "fp": fingerprint,
                "product_id": product_id,
                "state": state,
                "count": count,
            },
        )
        links.append(ProductLink(product_id, entry.name, state, count, lineage_id))
    return tuple(links)
