"""Lineup entries → spine product rows, with artifact-keyed lineage.

A port of the S5-B resolution ladder onto ``onboarding_product_lineage``, keyed on the catalog
DOCUMENT rather than a Client-KB claim (standing rule, catalog contract §10), and extended with a
fourth rung. Per entry, in order:

1. a lineage row already written for this ``(document, ordinal)`` — mirrored verbatim;
2. a prior lineage row that bound this exact fingerprint to a product — ``lineage_reused``,
   whichever rung made that binding (a durable decision is replayed, never re-derived);
3. the entry's spelling key against the names and aliases on file — one hit ``alias_reused``
   (writing the observed spelling back as an alias), several hits ``unresolved_ambiguous``;
4. everything left over, in ONE batched model reconciliation after the loop — a ``high``-confidence
   match becomes ``model_reused`` (again writing the spelling back), anything less confident mints
   and is flagged ``model_unsure`` for the human gate.

Name normalization is a comparison aid, never a merge key by itself; the model never merges by
itself either. Nothing here renames, merges or archives a product row: the only spine writes are
``INSERT product`` and ``add_product_aliases``. No Client-KB version, readiness decision or Stage-0
pin is read or written anywhere on this path.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_spine import Product, add_product_aliases, list_products

if TYPE_CHECKING:  # pragma: no cover — types only
    # ``onboarding_reconcile`` imports :class:`CatalogProduct` from this module, so importing it
    # back at module scope would be a cycle. The runtime import lives inside ``_model_stage``,
    # by which time both modules are fully loaded.
    from clue_api.arv2.onboarding_reconcile import CatalogReconciler, ReconcileDecision

__all__ = ["CatalogProduct", "ProductLink", "normalize_identity", "synchronize_catalog"]

POLICY_VERSION = "onboarding-catalog-sync-v1"


@dataclass(frozen=True)
class CatalogProduct:
    name: str
    short_description: str
    aliases: tuple[str, ...] = ()
    #: The entry's own product page, when the catalog document names one. Evidence for the model
    #: stage of the identity ladder; deliberately NOT part of :func:`_fingerprint`, whose payload is
    #: frozen so an unchanged re-run still recognises the lineage it wrote last time.
    official_url: str | None = None


@dataclass(frozen=True)
class ProductLink:
    product_id: str | None
    name: str
    resolution_state: str
    candidate_count: int
    lineage_id: UUID
    #: The model stage's own account of itself, mirrored from the lineage row. Both stay ``None``
    #: for every deterministic rung — a NULL says "no model decided this".
    reconcile_confidence: str | None = None
    reconcile_reason: str | None = None
    #: The entry reached its product through a product a person merged away (spec 2026-10-15 §9):
    #: the survivor already has its page, so the driver does not research it again under this
    #: entry's name. Not stored — a replayed link reports ``False``.
    redirected: bool = False


#: Trademark/service-mark/copyright marks a company decorates its own product names with. They are
#: stripped BEFORE NFKC, which would otherwise expand ``™`` into the letters ``tm`` and make
#: ``Aura™`` normalize to ``auratm`` — a different identity from ``Aura``.
_MARKS = str.maketrans("", "", "™®©℠")

#: The alphanumeric runs :func:`normalize_identity` joins into a spelling key — nothing else is
#: identity. Every word is kept; there is no stoplist of "generic" tokens (founder ruling
#: 2026-09-08).
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


def _keys(entry: CatalogProduct) -> tuple[str, ...]:
    """Every spelling key this entry answers to, name first, in a stable order.

    An empty key is not an identity (a name of nothing but punctuation or marks normalizes to
    ""), so it is dropped and may never match another empty one.
    """
    out: list[str] = []
    for spelling in (entry.name, *entry.aliases):
        key = normalize_identity(spelling)
        if key and key not in out:
            out.append(key)
    return tuple(out)


def _candidates(entry: CatalogProduct, products: Sequence[Product]) -> list[Product]:
    observed = set(_keys(entry))
    hits: list[Product] = []
    for product in products:
        names = {normalize_identity(product.name)} | {
            normalize_identity(a) for a in product.aliases if a.strip()
        }
        if observed & names:
            hits.append(product)
    return hits


def _should_reconcile(*, existing: int, leftovers: int) -> bool:
    """Is the model stage worth a call?

    Only when something was actually left over, and only when the answer is not already known:
    a single leftover with nothing on file to compare against can only be a new product, so
    asking would spend a call to hear what the ladder already knows.
    """
    return leftovers > 0 and (existing > 0 or leftovers > 1)


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
    """The product a prior lineage row bound this exact fingerprint to, whichever rung decided it.

    Replay is unconditional on state (controller ruling 2026-09-09): a lineage row IS the durable
    decision, and a high-confidence model merge was applied automatically by design while a
    ``model_unsure`` row bound its entry to the row it minted. Re-deriving either through the
    spelling rung is not guaranteed to reach the same answer — a second product carrying the same
    alias would turn the entry ``unresolved_ambiguous`` — so the binding is replayed, not redone,
    and the identical entry never reaches the model a second time.
    """
    return (
        await conn.execute(
            text(
                "SELECT product_id FROM onboarding_product_lineage WHERE workspace_id = :ws "
                "AND brand_id = :brand AND entry_fingerprint_sha256 = :fp "
                "AND product_id IS NOT NULL "
                "ORDER BY synchronized_at DESC LIMIT 1"
            ),
            {"ws": workspace_id, "brand": brand_id, "fp": fingerprint},
        )
    ).scalar_one_or_none()


@dataclass(frozen=True)
class _Pending:
    """An entry the deterministic rungs could not place, held until the model stage runs."""

    ordinal: int
    entry: CatalogProduct
    fingerprint: str
    lineage_id: UUID


def _lineage_id(document_id: UUID, ordinal: int) -> UUID:
    return uuid5(NAMESPACE_URL, f"onboarding-product-lineage:{document_id}:{ordinal}")


async def _mint(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    brand_id: str,
    document_id: UUID,
    pending: _Pending,
) -> str:
    """Insert a new product row for this entry. One recipe for every mint — ``created`` and
    ``model_unsure`` differ only in what the lineage row says about *why*, never in the id."""
    minted = uuid5(
        NAMESPACE_URL,
        f"onboarding-catalog:{workspace_id}:{brand_id}:{document_id}:{pending.ordinal}:"
        f"{pending.fingerprint}",
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
            "name": pending.entry.name,
            "aliases": json.dumps(list(pending.entry.aliases)),
        },
    )
    return product_id


async def _write_back(
    conn: AsyncConnection, *, product_id: str, workspace_id: str, entry: CatalogProduct
) -> Product:
    """Record the spelling this run observed on the row it resolved to.

    Every merge — rung 3 and the model stage alike — hands the writer the observed name plus the
    entry's own aliases and lets IT decide what is new (a spelling that folds onto the name or an
    alias already there buys no new match). Never a rename: the only edit is an append.
    """
    return await add_product_aliases(
        conn,
        product_id=product_id,
        workspace_id=workspace_id,
        aliases=(entry.name, *entry.aliases),
    )


async def _record(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    brand_id: str,
    document_id: UUID,
    pending: _Pending,
    product_id: str | None,
    state: str,
    count: int,
    confidence: str | None = None,
    reason: str | None = None,
    redirected: bool = False,
) -> ProductLink:
    """Write the lineage row for one entry and return the link that mirrors it.

    A ``removed_by_person`` row keeps the removed product's id (the durable record of what the
    entry matched) while its link carries none, so nothing downstream researches it again.
    """
    await conn.execute(
        text(
            "INSERT INTO onboarding_product_lineage (lineage_id, workspace_id, brand_id, "
            " document_id, entry_ordinal, entry_fingerprint_sha256, product_id, "
            " resolution_state, candidate_count, reconcile_confidence, reconcile_reason) "
            "VALUES (:id, :ws, :brand, :doc, :ordinal, :fp, :product_id, :state, :count, "
            " :confidence, :reason) "
            "ON CONFLICT (document_id, entry_ordinal) DO NOTHING"
        ),
        {
            "id": pending.lineage_id,
            "ws": workspace_id,
            "brand": brand_id,
            "doc": document_id,
            "ordinal": pending.ordinal,
            "fp": pending.fingerprint,
            "product_id": product_id,
            "state": state,
            "count": count,
            "confidence": confidence,
            "reason": reason,
        },
    )
    return ProductLink(
        None if state == REMOVED_BY_PERSON else product_id,
        pending.entry.name,
        state,
        count,
        pending.lineage_id,
        confidence,
        reason,
        redirected,
    )


#: A person removed the product this entry names (spec 2026-10-15 §9). The row keeps the removed
#: product's id; the link carries none.
REMOVED_BY_PERSON = "removed_by_person"


def _current(products: Sequence[Product], product_id: str | None) -> Product | None:
    """What a product id stands for today: itself, or the product it was merged into."""
    by_id = {p.product_id: p for p in products}
    product = by_id.get(product_id) if product_id else None
    for _ in range(8):
        if product is None or product.merged_into is None:
            return product
        product = by_id.get(product.merged_into)
    return None


def _replace(products: list[Product], refreshed: Product) -> list[Product]:
    return [refreshed if p.product_id == refreshed.product_id else p for p in products]


async def _model_stage(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    brand_id: str,
    document_id: UUID,
    leftovers: Sequence[_Pending],
    existing: list[Product],
    run_entries: dict[str, CatalogProduct],
    reconciler: CatalogReconciler | None,
) -> tuple[list[Product], list[tuple[_Pending, str, ProductLink]]]:
    """Rung 4: one batched reconciliation over everything the deterministic rungs left over.

    Returns the (possibly grown) product rows and, per leftover in order, the product it resolved
    to and the link recording it. Applies ``high``-confidence matches only; every other ``same_*``
    verdict mints and is flagged ``model_unsure`` with the model's own suggestion in the reason,
    so a wrong guess costs a duplicate for the human gate rather than a silent bad merge.
    """
    # See the module-scope note: the runtime import lives here to break the import cycle with
    # ``onboarding_reconcile``, which imports ``CatalogProduct`` from this module.
    from clue_api.arv2.onboarding_reconcile import ExistingProduct

    decisions: tuple[ReconcileDecision, ...] = ()
    if reconciler is not None and _should_reconcile(
        existing=len(existing), leftovers=len(leftovers)
    ):
        # A row's description and page are this run's own catalog entry whenever an entry in this
        # run named that row (controller ruling); otherwise there is nothing honest to show, since
        # the spine's ``product`` row carries neither a description nor a URL.
        shown: list[ExistingProduct] = []
        for product in existing:
            seen = run_entries.get(product.product_id)
            shown.append(
                ExistingProduct(
                    product_id=product.product_id,
                    name=product.name,
                    aliases=product.aliases,
                    official_url=seen.official_url if seen is not None else None,
                    description=seen.short_description if seen is not None else "",
                )
            )
        decisions = await reconciler.reconcile(
            existing=tuple(shown), candidates=tuple(pending.entry for pending in leftovers)
        )
    # The leftovers are unique by spelling key (the caller folded in-run repeats away before
    # asking), so their names are unique too and a name-keyed lookup is unambiguous. A candidate
    # the reconciler skipped simply falls through to today's behaviour: mint it.
    by_name = {decision.candidate: decision for decision in decisions}
    resolved_by_name: dict[str, str] = {}
    out: list[tuple[_Pending, str, ProductLink]] = []
    for pending in leftovers:
        entry = pending.entry
        decision = by_name.get(entry.name)
        target: str | None = None
        suggestion: str | None = None
        if decision is not None and decision.decision == "same_as_existing":
            match = next((p for p in existing if p.product_id == decision.product_id), None)
            target = match.product_id if match is not None else None
            suggestion = match.name if match is not None else str(decision.product_id)
        elif decision is not None and decision.decision == "same_as_candidate":
            # An earlier candidate in this same batch: it has already been resolved above, so the
            # id it minted or matched is known. (The validator only admits EARLIER references, so
            # the merge can never depend on an entry that has not been decided yet.)
            suggestion = decision.candidate_name
            target = resolved_by_name.get(suggestion) if suggestion is not None else None
        if target is not None and decision is not None and decision.confidence == "high":
            existing = _replace(
                existing,
                await _write_back(conn, product_id=target, workspace_id=workspace_id, entry=entry),
            )
            link = await _record(
                conn,
                workspace_id=workspace_id,
                brand_id=brand_id,
                document_id=document_id,
                pending=pending,
                product_id=target,
                state="model_reused",
                count=1,
                confidence=decision.confidence,
                reason=decision.reason or None,
            )
            product_id = target
        else:
            product_id = await _mint(
                conn,
                workspace_id=workspace_id,
                brand_id=brand_id,
                document_id=document_id,
                pending=pending,
            )
            if suggestion is not None:
                # The model saw a match but not confidently enough to merge on (or named a
                # reference that no longer resolves). Mint exactly like ``created`` and carry the
                # suggestion into the row so the human gate can act on it.
                state, count = "model_unsure", 1
                said = decision.reason if decision is not None else ""
                reason: str | None = f"suggested: {suggestion} — {said}"
            else:
                state, count = "created", 0
                reason = decision.reason or None if decision is not None else None
            link = await _record(
                conn,
                workspace_id=workspace_id,
                brand_id=brand_id,
                document_id=document_id,
                pending=pending,
                product_id=product_id,
                state=state,
                count=count,
                confidence=decision.confidence if decision is not None else None,
                reason=reason,
            )
            existing = await list_products(conn, brand_id)
        resolved_by_name[entry.name] = product_id
        run_entries[product_id] = entry
        out.append((pending, product_id, link))
    return existing, out


async def synchronize_catalog(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    brand_id: str,
    document_id: UUID,
    products: Sequence[CatalogProduct],
    reconciler: CatalogReconciler | None = None,
) -> tuple[ProductLink, ...]:
    await _assert_document_scope(
        conn, workspace_id=workspace_id, brand_id=brand_id, document_id=document_id
    )
    existing = await list_products(conn, brand_id)
    if any(p.workspace_id != workspace_id for p in existing):
        raise ValueError("catalog brand crossed its workspace")
    links: list[ProductLink | None] = [None] * len(products)
    #: Leftovers for rung 4, and the entries that merely repeat a leftover's spelling.
    leftovers: list[_Pending] = []
    leftover_by_key: dict[str, int] = {}
    repeats: list[tuple[_Pending, int]] = []
    #: The product rows THIS run named, and with what — the description and page the model stage
    #: shows for a row it may be asked to match against (controller ruling).
    run_entries: dict[str, CatalogProduct] = {}

    for ordinal, entry in enumerate(products):
        pending = _Pending(ordinal, entry, _fingerprint(entry), _lineage_id(document_id, ordinal))
        already = (
            (
                await conn.execute(
                    text(
                        "SELECT product_id, resolution_state, candidate_count, "
                        " entry_fingerprint_sha256, reconcile_confidence, reconcile_reason "
                        "FROM onboarding_product_lineage WHERE lineage_id = :id"
                    ),
                    {"id": pending.lineage_id},
                )
            )
            .mappings()
            .first()
        )
        if already is not None:
            # This ordinal was already synchronized against this document, so the durable row IS
            # the answer and the link merely mirrors it — product id, state, candidate count and
            # the reconcile columns verbatim. A ``ProductLink`` is a projection of the lineage row,
            # never a value the table does not hold, so a replay of a ``created`` entry reports
            # ``created`` and a replayed model verdict is never re-asked.
            #
            # A document version is immutable, so the same ordinal must carry the same entry. When
            # it does not, the caller re-published a *different* catalog under the same document
            # id: the append-only row cannot be corrected and returning it would hand back a link
            # for the wrong entry, so this fails loud instead.
            if str(already["entry_fingerprint_sha256"]) != pending.fingerprint:
                raise ValueError("catalog document entry changed under its lineage")
            confidence = already["reconcile_confidence"]
            reason = already["reconcile_reason"]
            state = str(already["resolution_state"])
            links[ordinal] = ProductLink(
                None if state == REMOVED_BY_PERSON else already["product_id"],
                entry.name,
                str(already["resolution_state"]),
                int(already["candidate_count"]),
                pending.lineage_id,
                str(confidence) if confidence is not None else None,
                str(reason) if reason is not None else None,
            )
            if already["product_id"] is not None and state != REMOVED_BY_PERSON:
                run_entries[str(already["product_id"])] = entry
            continue

        prior = await _prior_product_id(
            conn, workspace_id=workspace_id, brand_id=brand_id, fingerprint=pending.fingerprint
        )
        # Every product a rung reaches is mapped to what it stands for today: a merged product to
        # its survivor, and an archived one is a product a person removed (spec 2026-10-15 §9).
        target = _current(existing, prior)
        if target is not None:
            if target.status == "archived":
                links[ordinal] = await _record(
                    conn,
                    workspace_id=workspace_id,
                    brand_id=brand_id,
                    document_id=document_id,
                    pending=pending,
                    product_id=target.product_id,
                    state=REMOVED_BY_PERSON,
                    count=1,
                )
                continue
            links[ordinal] = await _record(
                conn,
                workspace_id=workspace_id,
                brand_id=brand_id,
                document_id=document_id,
                pending=pending,
                product_id=target.product_id,
                state="lineage_reused",
                count=1,
                redirected=target.product_id != prior,
            )
            run_entries[target.product_id] = entry
            continue

        hits = _candidates(entry, existing)
        targets = list(
            {
                t.product_id: t
                for t in (_current(existing, h.product_id) for h in hits)
                if t is not None
            }.values()
        )
        if len(targets) == 1 and targets[0].status == "archived":
            links[ordinal] = await _record(
                conn,
                workspace_id=workspace_id,
                brand_id=brand_id,
                document_id=document_id,
                pending=pending,
                product_id=targets[0].product_id,
                state=REMOVED_BY_PERSON,
                count=1,
            )
            continue
        if len(targets) == 1:
            reached = targets[0]
            existing = _replace(
                existing,
                await _write_back(
                    conn, product_id=reached.product_id, workspace_id=workspace_id, entry=entry
                ),
            )
            links[ordinal] = await _record(
                conn,
                workspace_id=workspace_id,
                brand_id=brand_id,
                document_id=document_id,
                pending=pending,
                product_id=reached.product_id,
                state="alias_reused",
                count=1,
                redirected=any(h.status != "active" for h in hits),
            )
            run_entries[reached.product_id] = entry
            continue
        if targets:
            links[ordinal] = await _record(
                conn,
                workspace_id=workspace_id,
                brand_id=brand_id,
                document_id=document_id,
                pending=pending,
                product_id=None,
                state="unresolved_ambiguous",
                count=len(targets),
            )
            continue

        # Rung 4's queue. Leftovers are kept unique by spelling key within the run (controller
        # ruling): a later entry whose key is an earlier leftover's key follows that leftover
        # wherever it lands, recorded as ``alias_reused``, so the model never sees two candidates
        # with one key and its name-keyed answer stays unambiguous.
        keys = _keys(entry)
        repeat_of = next((leftover_by_key[key] for key in keys if key in leftover_by_key), None)
        if repeat_of is not None:
            repeats.append((pending, repeat_of))
            continue
        for key in keys:
            leftover_by_key.setdefault(key, len(leftovers))
        leftovers.append(pending)

    if leftovers:
        existing, resolutions = await _model_stage(
            conn,
            workspace_id=workspace_id,
            brand_id=brand_id,
            document_id=document_id,
            leftovers=leftovers,
            # The model only ever matches against the products on the list today.
            existing=[p for p in existing if p.status == "active"],
            run_entries=run_entries,
            reconciler=reconciler,
        )
        for pending, _, link in resolutions:
            links[pending.ordinal] = link
        for pending, index in repeats:
            product_id = resolutions[index][1]
            existing = _replace(
                existing,
                await _write_back(
                    conn,
                    product_id=product_id,
                    workspace_id=workspace_id,
                    entry=pending.entry,
                ),
            )
            links[pending.ordinal] = await _record(
                conn,
                workspace_id=workspace_id,
                brand_id=brand_id,
                document_id=document_id,
                pending=pending,
                product_id=product_id,
                state="alias_reused",
                count=1,
            )

    filled = [link for link in links if link is not None]
    if len(filled) != len(products):
        raise AssertionError("every catalog entry must leave the ladder with a lineage row")
    return tuple(filled)
