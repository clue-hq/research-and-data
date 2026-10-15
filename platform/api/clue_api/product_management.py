"""Product management: add, rename, merge, remove and undo a brand's products (spec 2026-10-15).

The ``product`` table is the brand's one product list. Every action here runs in the caller's
transaction and moves everything that depends on that list together:

1. the spine row(s) (``clue_spine`` rename / merge / archive / restore);
2. the product pages in Brand context — a product's *main page* is the current servable
   brand-level ``product-research`` document whose front matter names it. Pages are never deleted:
   a retired page is ``superseded``, and an undo publishes its bytes again as a new version;
3. ``product/catalog.md``, regenerated from the active products (``generated: true``);
4. one ``product_change`` row (append-only) saying who did what;
5. every project whose current product set used an affected product gets a new set version
   tagged with the change, and a ``product_change_project`` row — the chat notice's source.

The brand row is locked first, so two actions on one brand run one after the other and the second
sees the first's result (and refuses if its product is no longer active).

A person acts through the Brand-context routes; the Head of ABM through ``manage_products@1``.
When a page is needed and no markdown was given (an app-made add or merge), a ``running`` page row
is opened and the result says ``page_pending``: the caller offers the background page writer after
its transaction commits.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

from sqlalchemy import bindparam, text
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.knowledge_frontmatter import parse_front_matter
from clue_api.arv2.onboarding_documents import KnowledgeDocument, render_markdown, slugify
from clue_api.arv2.onboarding_lineage import normalize_identity
from clue_api.knowledge_bytes import read_knowledge_bytes, read_one_knowledge_bytes
from clue_core import decode_jsonb, serialize_value_json
from clue_spine import (
    Product,
    archive_product,
    confirm_project_product_set,
    create_product,
    current_project_product_set,
    get_product,
    list_products,
    list_project_product_sets,
    merge_products,
    remove_product_aliases,
    rename_product,
    restore_product,
)
from clue_storage import (
    StorageBackend,
    artifact_key,
    content_address,
    record_artifact,
)

__all__ = [
    "CATALOG_PATH",
    "BrandProduct",
    "ProductActor",
    "ProductChangeLine",
    "ProductChangeRefused",
    "ProductChangeResult",
    "ProjectSetOutcome",
    "add_product",
    "change_details",
    "describe_change",
    "list_brand_products",
    "main_page_of",
    "mark_product_page_failed",
    "page_summary",
    "merge_products_action",
    "publish_product_page",
    "read_brand_document",
    "recent_change_lines",
    "recent_product_changes",
    "regenerate_catalog",
    "remove_product_action",
    "rename_product_action",
    "undo_product_change",
]

CATALOG_PATH = "product/catalog.md"
_PRODUCT_FOLDER = "product"
_PAGE_KIND = "product-research"
_CATALOG_KIND = "product-catalog"
_SERVABLE = ("ready", "proposed", "confirmed")
#: Versions a write may retire. A ``confirmed`` version is a project's approved pin and is never
#: touched (the ``save_knowledge_document`` rule).
_RETIRABLE = ("ready", "proposed")
_NAME_MAX = 240
_CATALOG_CARRIED = (
    "short_description",
    "offering_kind",
    "family",
    "lifecycle",
    "official_url",
    "sources",
)
_SOURCE_KEY = "brand_product_management"


# --- results and refusals ---------------------------------------------------------------------


@dataclass(frozen=True)
class ProductActor:
    """Who acted: always a person; ``turn_id`` when the Head of ABM acted for them in a chat."""

    user_id: str
    turn_id: UUID | None = None


class ProductChangeRefused(ValueError):
    """An action that cannot happen. ``code`` is stable and machine-readable:
    ``product_not_found``, ``product_not_active``, ``product_name_taken``, ``name_invalid``,
    ``merge_invalid``, ``change_not_found``, ``change_not_undoable``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ProjectSetOutcome:
    project_id: str
    outcome: Literal["updated", "needs_choice", "restored", "left_as_is"]
    selection_version: int | None


@dataclass(frozen=True)
class ProductChangeResult:
    change_id: UUID
    kind: str
    text: str
    product: Product
    page_document_id: UUID | None
    page_pending: bool
    catalog_document_id: UUID
    projects: tuple[ProjectSetOutcome, ...]
    replayed: bool = False
    #: Where the product's page lives now (add, rename, merge); ``None`` when it has none.
    page_path: str | None = None


@dataclass(frozen=True)
class BrandProduct:
    product_id: str
    name: str
    aliases: tuple[str, ...]
    page_document_id: UUID | None
    page_path: str | None
    page_pending: bool


@dataclass(frozen=True)
class ProductChangeLine:
    change_id: UUID
    kind: str
    text: str
    created_at: datetime
    undoable: bool


# --- documents --------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Doc:
    document_id: UUID
    path: str
    kind: str
    version: int
    status: str
    front: dict[str, Any] = field(default_factory=dict)
    body: str = ""


_CURRENT_SERVABLE = text(
    "SELECT d.document_id, d.path, d.kind, d.version, d.status, d.artifact_key, "
    " d.artifact_sha256 FROM brand_knowledge_document d "
    "WHERE d.workspace_id = :ws AND d.brand_id = :brand AND d.folder = :folder "
    " AND d.project_id IS NULL AND d.status IN :servable "
    " AND d.version = (SELECT MAX(d2.version) FROM brand_knowledge_document d2 "
    "   WHERE d2.workspace_id = d.workspace_id AND d2.brand_id = d.brand_id "
    "     AND d2.path = d.path AND d2.project_id IS NULL AND d2.status IN :servable) "
    "ORDER BY d.path"
).bindparams(bindparam("servable", expanding=True))


async def _read_doc(
    conn: AsyncConnection, storage: StorageBackend, *, workspace_id: str, row: RowMapping
) -> _Doc:
    raw = (
        await read_one_knowledge_bytes(
            conn,
            storage,
            workspace_id=workspace_id,
            ref=(str(row["artifact_key"]), str(row["artifact_sha256"])),
        )
        if row["artifact_key"]
        else None
    )
    return _doc_of(row, raw)


def _doc_of(row: RowMapping, raw: bytes | None) -> _Doc:
    front: dict[str, Any] = {}
    body = ""
    if raw is not None:
        try:
            front, body = parse_front_matter(raw.decode("utf-8"), preserve_body=True)
        except (UnicodeDecodeError, ValueError):
            front, body = {}, raw.decode("utf-8", errors="replace")
    return _Doc(
        document_id=row["document_id"],
        path=str(row["path"]),
        kind=str(row["kind"]),
        version=int(row["version"]),
        status=str(row["status"]),
        front=front,
        body=body,
    )


async def _product_folder(
    conn: AsyncConnection, storage: StorageBackend, *, workspace_id: str, brand_id: str
) -> list[_Doc]:
    rows = await conn.execute(
        _CURRENT_SERVABLE,
        {
            "ws": workspace_id,
            "brand": brand_id,
            "folder": _PRODUCT_FOLDER,
            "servable": list(_SERVABLE),
        },
    )
    found = list(rows.mappings().all())
    # Fetched together and cached by content, like the Brand-context tree (2026-10-15).
    contents = await read_knowledge_bytes(
        conn,
        storage,
        workspace_id=workspace_id,
        refs=[(str(r["artifact_key"]), str(r["artifact_sha256"])) for r in found],
    )
    docs: list[_Doc] = []
    for row in found:
        raw = contents[(str(row["artifact_key"]), str(row["artifact_sha256"]))]
        if isinstance(raw, Exception):
            raise raw
        docs.append(_doc_of(row, raw))
    return docs


def _main_pages(docs: Sequence[_Doc]) -> dict[str, _Doc]:
    """Product id → its main page (the newest servable product page naming it)."""
    pages: dict[str, _Doc] = {}
    for doc in docs:
        product_id = doc.front.get("product_id")
        if doc.kind != _PAGE_KIND or not isinstance(product_id, str) or not product_id:
            continue
        held = pages.get(product_id)
        if held is None or doc.version > held.version:
            pages[product_id] = doc
    return pages


async def _pending_pages(conn: AsyncConnection, *, workspace_id: str, brand_id: str) -> set[str]:
    """Paths whose newest brand-level version is a ``running`` page still being written."""
    rows = await conn.execute(
        text(
            "SELECT d.path FROM brand_knowledge_document d WHERE d.workspace_id = :ws "
            "AND d.brand_id = :brand AND d.folder = 'product' AND d.project_id IS NULL "
            "AND d.status = 'running' AND d.version = (SELECT MAX(d2.version) "
            " FROM brand_knowledge_document d2 WHERE d2.workspace_id = d.workspace_id "
            " AND d2.brand_id = d.brand_id AND d2.path = d.path AND d2.project_id IS NULL)"
        ),
        {"ws": workspace_id, "brand": brand_id},
    )
    return {str(path) for path in rows.scalars().all()}


async def _next_version(
    conn: AsyncConnection, *, workspace_id: str, brand_id: str, path: str
) -> int:
    return int(
        (
            await conn.execute(
                text(
                    "SELECT COALESCE(MAX(version), 0) + 1 FROM brand_knowledge_document "
                    "WHERE workspace_id = :ws AND brand_id = :brand AND path = :path "
                    "AND project_id IS NULL"
                ),
                {"ws": workspace_id, "brand": brand_id, "path": path},
            )
        ).scalar_one()
    )


async def _store(
    conn: AsyncConnection, storage: StorageBackend, *, workspace_id: str, data: bytes
) -> tuple[str, str]:
    sha = content_address(data)
    key = artifact_key(workspace_id, sha)
    await record_artifact(
        conn,
        storage_key=key,
        workspace_id=workspace_id,
        content_sha256=sha,
        media_type="text/markdown",
        size_bytes=len(data),
        source_key=_SOURCE_KEY,
    )
    await storage.put(key, data, media_type="text/markdown")
    return key, sha


async def _retire_path(
    conn: AsyncConnection, *, workspace_id: str, brand_id: str, path: str, below: int | None = None
) -> list[UUID]:
    """Supersede every retirable brand-level version of ``path`` (below ``below`` when given)."""
    rows = await conn.execute(
        text(
            "UPDATE brand_knowledge_document SET status = 'superseded', updated_at = now() "
            "WHERE workspace_id = :ws AND brand_id = :brand AND path = :path "
            "AND project_id IS NULL AND status IN :retirable "
            "AND (CAST(:below AS integer) IS NULL OR version < CAST(:below AS integer)) "
            "RETURNING document_id"
        ).bindparams(bindparam("retirable", expanding=True)),
        {
            "ws": workspace_id,
            "brand": brand_id,
            "path": path,
            "retirable": list(_RETIRABLE),
            "below": below,
        },
    )
    return list(rows.scalars().all())


async def _write_doc(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    workspace_id: str,
    brand_id: str,
    path: str,
    kind: str,
    front: dict[str, Any],
    body: str,
) -> UUID:
    """Publish ``ready`` bytes as the next brand-level version of ``path``; retire older ones."""
    data = render_markdown(
        KnowledgeDocument(
            kind=kind, folder=_PRODUCT_FOLDER, path=path, front_matter=front, body=body, cost=None
        )
    ).encode("utf-8")
    key, sha = await _store(conn, storage, workspace_id=workspace_id, data=data)
    version = await _next_version(conn, workspace_id=workspace_id, brand_id=brand_id, path=path)
    previous = (
        await conn.execute(
            text(
                "SELECT document_id FROM brand_knowledge_document WHERE workspace_id = :ws "
                "AND brand_id = :brand AND path = :path AND project_id IS NULL "
                "AND status IN :servable ORDER BY version DESC LIMIT 1"
            ).bindparams(bindparam("servable", expanding=True)),
            {"ws": workspace_id, "brand": brand_id, "path": path, "servable": list(_SERVABLE)},
        )
    ).scalar_one_or_none()
    document_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO brand_knowledge_document (document_id, workspace_id, brand_id, folder, "
            " path, kind, version, status, artifact_key, artifact_sha256, supersedes_document_id) "
            "VALUES (:id, :ws, :brand, :folder, :path, :kind, :version, 'ready', :key, :sha, "
            " :previous)"
        ),
        {
            "id": document_id,
            "ws": workspace_id,
            "brand": brand_id,
            "folder": _PRODUCT_FOLDER,
            "path": path,
            "kind": kind,
            "version": version,
            "key": key,
            "sha": sha,
            "previous": previous,
        },
    )
    await _retire_path(conn, workspace_id=workspace_id, brand_id=brand_id, path=path, below=version)
    return document_id


async def _open_pending_page(
    conn: AsyncConnection, *, workspace_id: str, brand_id: str, path: str
) -> UUID:
    """A ``running`` page row the background writer fills (no bytes yet, so not served)."""
    document_id = uuid4()
    version = await _next_version(conn, workspace_id=workspace_id, brand_id=brand_id, path=path)
    await conn.execute(
        text(
            "INSERT INTO brand_knowledge_document (document_id, workspace_id, brand_id, folder, "
            " path, kind, version, status) VALUES (:id, :ws, :brand, 'product', :path, "
            " :kind, :version, 'running')"
        ),
        {
            "id": document_id,
            "ws": workspace_id,
            "brand": brand_id,
            "path": path,
            "kind": _PAGE_KIND,
            "version": version,
        },
    )
    return document_id


def _page_front(product: Product, actor: ProductActor, change_id: UUID) -> dict[str, Any]:
    return {
        "kind": _PAGE_KIND,
        "as_of": datetime.now(UTC).date().isoformat(),
        "product_id": product.product_id,
        "product_name": product.name,
        "status": "ready",
        "written_by": {
            "user_id": actor.user_id,
            "turn_id": str(actor.turn_id) if actor.turn_id else None,
            "change_id": str(change_id),
        },
    }


_HEADING = re.compile(r"^\s*#\s+\S", re.MULTILINE)


def _page_body(name: str, markdown: str) -> str:
    """The page as written, with the product's name as its title when it has no heading."""
    body = markdown.strip()
    return body + "\n" if _HEADING.match(body) else f"# {name}\n\n{body}\n"


#: The longest catalog description taken from a page, in characters.
_SUMMARY_MAX = 300
_PLACEHOLDER = re.compile(r"^_[^_].*_$")


def page_summary(body: str) -> str | None:
    """The first real paragraph of a page: headings, placeholders ("_Not established._") and
    tables skipped, whitespace folded, cut at a word near 300 characters. ``None`` when the page
    has no prose yet."""
    for block in body.split("\n\n"):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines or all(line.startswith(("#", "|", "---")) for line in lines):
            continue
        text = " ".join(" ".join(line for line in lines if not line.startswith("#")).split())
        if not text or _PLACEHOLDER.match(text):
            continue
        if len(text) <= _SUMMARY_MAX:
            return text
        return text[:_SUMMARY_MAX].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return None


def _page_path(product: Product, docs: Sequence[_Doc], *, current: _Doc | None) -> str:
    """Where a product's page lives: its current page's path, else its name's slug — never a
    path another product's page holds."""
    if current is not None:
        return current.path
    taken = {
        doc.path
        for doc in docs
        if doc.path == CATALOG_PATH or doc.front.get("product_id") not in (None, product.product_id)
    }
    base = slugify(product.name)
    path, n = f"product/{base}.md", 2
    while path in taken:
        path, n = f"product/{base}-{n}.md", n + 1
    return path


# --- the catalog --------------------------------------------------------------------------------


async def _lineage_product_ids(conn: AsyncConnection, document_id: UUID) -> dict[int, str]:
    rows = await conn.execute(
        text(
            "SELECT entry_ordinal, product_id FROM onboarding_product_lineage "
            "WHERE document_id = :doc AND product_id IS NOT NULL"
        ),
        {"doc": document_id},
    )
    return {int(r["entry_ordinal"]): str(r["product_id"]) for r in rows.mappings().all()}


def _cell(value: Any) -> str:
    return "" if value is None else str(value).replace("|", "\\|").replace("\n", " ")


async def regenerate_catalog(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    workspace_id: str,
    brand_id: str,
    change_id: UUID | None,
) -> UUID:
    """Rebuild ``product/catalog.md`` from the brand's active products.

    Each row keeps the descriptive fields the previous catalog had for that product — matched by
    the entry's own ``product_id``, else by the onboarding lineage of that catalog document, else
    by spelling — so a regeneration never loses what research found.
    """
    docs = await _product_folder(conn, storage, workspace_id=workspace_id, brand_id=brand_id)
    previous = next((d for d in docs if d.path == CATALOG_PATH), None)
    entries = (
        [e for e in (previous.front.get("products") or []) if isinstance(e, dict)]
        if (previous)
        else []
    )
    lineage = await _lineage_product_ids(conn, previous.document_id) if previous else {}
    by_id: dict[str, dict[str, Any]] = {}
    by_spelling: dict[str, dict[str, Any]] = {}
    for ordinal, entry in enumerate(entries):
        pid = entry.get("product_id") or lineage.get(ordinal)
        if isinstance(pid, str) and pid not in by_id:
            by_id[pid] = entry
        for spelling in (entry.get("name"), *(entry.get("aliases") or [])):
            if isinstance(spelling, str) and normalize_identity(spelling):
                by_spelling.setdefault(normalize_identity(spelling), entry)

    pages = _main_pages(docs)
    rows: list[dict[str, Any]] = []
    for product in await list_products(conn, brand_id):
        if product.status != "active" or product.workspace_id != workspace_id:
            continue
        found = by_id.get(product.product_id) or next(
            (
                by_spelling[key]
                for key in (normalize_identity(s) for s in (product.name, *product.aliases))
                if key in by_spelling
            ),
            {},
        )
        row: dict[str, Any] = {
            "product_id": product.product_id,
            "name": product.name,
            "aliases": list(product.aliases),
        }
        row.update({key: found.get(key) for key in _CATALOG_CARRIED})
        # The product's own page is how a person corrects its line, so its first paragraph
        # wins over what onboarding research wrote.
        page = pages.get(product.product_id)
        summary = page_summary(page.body) if page is not None else None
        if summary:
            row["short_description"] = summary
        rows.append(row)

    front: dict[str, Any] = {
        "kind": _CATALOG_KIND,
        "generated": True,
        "change_id": str(change_id) if change_id else None,
        "as_of": datetime.now(UTC).date().isoformat(),
        "company_domain": previous.front.get("company_domain") if previous else None,
        "products": rows,
    }
    lines = [
        "# Product catalog",
        "",
        "_Generated from your products. To change this list, add, rename, merge or remove a "
        "product._",
        "",
    ]
    if rows:
        lines += [
            "| Name | Also called | Kind | Description |",
            "|---|---|---|---|",
            *(
                f"| {_cell(r['name'])} | {_cell(', '.join(r['aliases']))} | "
                f"{_cell(r.get('offering_kind'))} | {_cell(r.get('short_description'))} |"
                for r in rows
            ),
        ]
    else:
        lines.append("_No products yet._")
    return await _write_doc(
        conn,
        storage,
        workspace_id=workspace_id,
        brand_id=brand_id,
        path=CATALOG_PATH,
        kind=_CATALOG_KIND,
        front=front,
        body="\n".join(lines) + "\n",
    )


# --- the change log ---------------------------------------------------------------------------


def describe_change(kind: str, details: Mapping[str, Any]) -> str:
    """One plain sentence for a change — the chat notice and the agent's recent-changes line."""
    if kind == "add":
        return f"{details.get('name')} added"
    if kind == "rename":
        return f"{details.get('before')} renamed to {details.get('after')}"
    if kind == "merge":
        names = [str(n) for n in details.get("names") or []]
        into = details.get("into")
        if len(names) == 1:
            return f"{names[0]} merged into {into}"
        return f"{len(names)} products merged into {into}"
    if kind == "remove":
        return f"{details.get('name')} removed"
    if kind == "restore":
        return f"Undone: {details.get('undid')}"
    return kind


async def _lock_brand(conn: AsyncConnection, *, workspace_id: str, brand_id: str) -> None:
    found = (
        await conn.execute(
            text(
                "SELECT brand_id FROM brand WHERE workspace_id = :ws AND brand_id = :brand "
                "FOR UPDATE"
            ),
            {"ws": workspace_id, "brand": brand_id},
        )
    ).scalar_one_or_none()
    if found is None:
        raise ProductChangeRefused("product_not_found", "this workspace has no such brand")


async def _replayed(
    conn: AsyncConnection, *, workspace_id: str, idempotency_key: str | None
) -> ProductChangeResult | None:
    if idempotency_key is None:
        return None
    row = (
        (
            await conn.execute(
                text(
                    "SELECT * FROM product_change WHERE workspace_id = :ws "
                    "AND idempotency_key = :key"
                ),
                {"ws": workspace_id, "key": idempotency_key},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    return await _result_of(conn, row, replayed=True)


async def _result_of(
    conn: AsyncConnection, row: RowMapping, *, replayed: bool
) -> ProductChangeResult:
    details = decode_jsonb(row["details"]) or {}
    product = await get_product(conn, str(row["product_id"]))
    assert product is not None
    projects = await conn.execute(
        text(
            "SELECT project_id, outcome, selection_version FROM product_change_project "
            "WHERE change_id = :id ORDER BY project_id"
        ),
        {"id": row["change_id"]},
    )
    result = details.get("result") or {}
    page = result.get("page_document_id")
    return ProductChangeResult(
        change_id=row["change_id"],
        kind=str(row["kind"]),
        text=describe_change(str(row["kind"]), details),
        product=product,
        page_document_id=UUID(page) if page else None,
        page_pending=bool(result.get("page_pending")),
        catalog_document_id=UUID(result["catalog_document_id"]),
        page_path=result.get("page_path"),
        projects=tuple(
            ProjectSetOutcome(str(p["project_id"]), p["outcome"], p["selection_version"])
            for p in projects.mappings().all()
        ),
        replayed=replayed,
    )


async def _record_change(
    conn: AsyncConnection,
    *,
    change_id: UUID,
    workspace_id: str,
    brand_id: str,
    kind: str,
    product_id: str,
    affected: Sequence[str],
    details: dict[str, Any],
    actor: ProductActor,
    idempotency_key: str | None,
    undoes: UUID | None = None,
) -> None:
    await conn.execute(
        text(
            "INSERT INTO product_change (change_id, workspace_id, brand_id, kind, product_id, "
            " affected_product_ids, details, actor_user_id, actor_turn_id, undoes_change_id, "
            " idempotency_key, created_at) VALUES (:id, :ws, :brand, :kind, :product, "
            " CAST(:affected AS jsonb), CAST(:details AS jsonb), :user, :turn, :undoes, :key, "
            " clock_timestamp())"
        ),
        {
            "id": change_id,
            "ws": workspace_id,
            "brand": brand_id,
            "kind": kind,
            "product": product_id,
            "affected": serialize_value_json(list(affected)),
            "details": serialize_value_json(details),
            "user": actor.user_id,
            "turn": actor.turn_id,
            "undoes": undoes,
            "key": idempotency_key,
        },
    )


async def _record_project(
    conn: AsyncConnection,
    *,
    change_id: UUID,
    workspace_id: str,
    project_id: str,
    outcome: str,
    selection_version: int | None,
    previous_selection_version: int | None,
) -> ProjectSetOutcome:
    await conn.execute(
        text(
            "INSERT INTO product_change_project (change_id, project_id, workspace_id, outcome, "
            " selection_version, previous_selection_version) VALUES (:change, :project, :ws, "
            " :outcome, :version, :previous)"
        ),
        {
            "change": change_id,
            "project": project_id,
            "ws": workspace_id,
            "outcome": outcome,
            "version": selection_version,
            "previous": previous_selection_version,
        },
    )
    return ProjectSetOutcome(project_id, outcome, selection_version)  # type: ignore[arg-type]


async def _move_project_sets(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    brand_id: str,
    change_id: UUID,
    mapping: Mapping[str, str | None],
    user_id: str,
) -> tuple[ProjectSetOutcome, ...]:
    """Every project whose *current* set holds a mapped product gets the mapped set (D4)."""
    candidates = await conn.execute(
        text(
            "SELECT DISTINCT project_id FROM project_product WHERE workspace_id = :ws "
            "AND brand_id = :brand AND product_id = ANY(:ids) ORDER BY project_id"
        ),
        {"ws": workspace_id, "brand": brand_id, "ids": list(mapping)},
    )
    outcomes: list[ProjectSetOutcome] = []
    for project_id in [str(p) for p in candidates.scalars().all()]:
        current = await current_project_product_set(
            conn, workspace_id=workspace_id, project_id=project_id
        )
        if current is None or not set(current.product_ids) & set(mapping):
            continue
        moved = [mapping.get(pid, pid) for pid in current.product_ids]
        kept = list(dict.fromkeys(pid for pid in moved if pid is not None))
        if not kept:
            outcomes.append(
                await _record_project(
                    conn,
                    change_id=change_id,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    outcome="needs_choice",
                    selection_version=None,
                    previous_selection_version=current.selection_version,
                )
            )
            continue
        written = await confirm_project_product_set(
            conn,
            workspace_id=workspace_id,
            project_id=project_id,
            product_ids=kept,
            gate_id=None,
            confirmed_by_user_id=user_id,
            product_change_id=change_id,
        )
        assert written is not None  # same brand, active products, project locked by its read
        outcomes.append(
            await _record_project(
                conn,
                change_id=change_id,
                workspace_id=workspace_id,
                project_id=project_id,
                outcome="updated",
                selection_version=written.selection_version,
                previous_selection_version=current.selection_version,
            )
        )
    return tuple(outcomes)


# --- validation helpers ------------------------------------------------------------------------


def _clean_name(name: str | None) -> str:
    cleaned = " ".join((name or "").split())
    if not cleaned or len(cleaned) > _NAME_MAX:
        raise ProductChangeRefused(
            "name_invalid", f"a product name needs 1 to {_NAME_MAX} characters"
        )
    return cleaned


async def _active_product(
    conn: AsyncConnection, *, workspace_id: str, brand_id: str, product_id: str
) -> Product:
    product = await get_product(conn, product_id)
    if product is None or product.workspace_id != workspace_id or product.brand_id != brand_id:
        raise ProductChangeRefused("product_not_found", f"no product {product_id} in this brand")
    if product.status != "active":
        raise ProductChangeRefused(
            "product_not_active", f"{product.name} is no longer on the product list"
        )
    return product


async def _refuse_taken_name(
    conn: AsyncConnection, *, brand_id: str, name: str, except_ids: Sequence[str] = ()
) -> None:
    folded = normalize_identity(name)
    for product in await list_products(conn, brand_id):
        if (
            product.status == "active"
            and product.product_id not in except_ids
            and normalize_identity(product.name) == folded
        ):
            raise ProductChangeRefused(
                "product_name_taken", f"the brand already has a product called {product.name}"
            )


def _name_taken(error: IntegrityError) -> ProductChangeRefused:
    if "product_name_per_brand" in str(error.orig):
        return ProductChangeRefused(
            "product_name_taken", "the brand already has an active product with that name"
        )
    raise error


# --- actions ---------------------------------------------------------------------------------


async def add_product(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    workspace_id: str,
    brand_id: str,
    actor: ProductActor,
    name: str,
    description: str | None = None,
    page_markdown: str | None = None,
    idempotency_key: str | None = None,
) -> ProductChangeResult:
    await _lock_brand(conn, workspace_id=workspace_id, brand_id=brand_id)
    if replay := await _replayed(conn, workspace_id=workspace_id, idempotency_key=idempotency_key):
        return replay
    clean = _clean_name(name)
    await _refuse_taken_name(conn, brand_id=brand_id, name=clean)
    try:
        async with conn.begin_nested():
            product = await create_product(
                conn, brand_id=brand_id, workspace_id=workspace_id, name=clean
            )
    except IntegrityError as error:
        raise _name_taken(error) from error
    change_id = uuid4()
    docs = await _product_folder(conn, storage, workspace_id=workspace_id, brand_id=brand_id)
    path = _page_path(product, docs, current=None)
    if page_markdown and page_markdown.strip():
        page_id = await _write_doc(
            conn,
            storage,
            workspace_id=workspace_id,
            brand_id=brand_id,
            path=path,
            kind=_PAGE_KIND,
            front=_page_front(product, actor, change_id),
            body=_page_body(product.name, page_markdown),
        )
        pending = False
    else:
        page_id = await _open_pending_page(
            conn, workspace_id=workspace_id, brand_id=brand_id, path=path
        )
        pending = True
    catalog_id = await regenerate_catalog(
        conn, storage, workspace_id=workspace_id, brand_id=brand_id, change_id=change_id
    )
    details = {
        "name": product.name,
        "description": (description or "").strip() or None,
        "result": {
            "page_document_id": str(page_id),
            "page_pending": pending,
            "catalog_document_id": str(catalog_id),
            "page_path": path,
        },
    }
    await _record_change(
        conn,
        change_id=change_id,
        workspace_id=workspace_id,
        brand_id=brand_id,
        kind="add",
        product_id=product.product_id,
        affected=[product.product_id],
        details=details,
        actor=actor,
        idempotency_key=idempotency_key,
    )
    return ProductChangeResult(
        change_id,
        "add",
        describe_change("add", details),
        product,
        page_id,
        pending,
        catalog_id,
        (),
        page_path=path,
    )


async def rename_product_action(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    workspace_id: str,
    brand_id: str,
    actor: ProductActor,
    product_id: str,
    name: str,
    idempotency_key: str | None = None,
) -> ProductChangeResult:
    await _lock_brand(conn, workspace_id=workspace_id, brand_id=brand_id)
    if replay := await _replayed(conn, workspace_id=workspace_id, idempotency_key=idempotency_key):
        return replay
    before = await _active_product(
        conn, workspace_id=workspace_id, brand_id=brand_id, product_id=product_id
    )
    clean = _clean_name(name)
    await _refuse_taken_name(conn, brand_id=brand_id, name=clean, except_ids=[product_id])
    try:
        async with conn.begin_nested():
            product = await rename_product(
                conn, product_id=product_id, workspace_id=workspace_id, name=clean
            )
    except IntegrityError as error:
        raise _name_taken(error) from error
    change_id = uuid4()
    docs = await _product_folder(conn, storage, workspace_id=workspace_id, brand_id=brand_id)
    page = _main_pages(docs).get(product_id)
    page_id: UUID | None = None
    page_path: str | None = None
    if page is not None:
        new_path = f"product/{slugify(product.name)}.md"
        others = {d.path for d in docs if d.document_id != page.document_id}
        path = page.path if new_path in others else new_path
        front = {**page.front, "product_name": product.name}
        body = page.body
        title = f"# {before.name}"
        if body.lstrip().startswith(title):
            body = body.replace(title, f"# {product.name}", 1)
        page_id = await _write_doc(
            conn,
            storage,
            workspace_id=workspace_id,
            brand_id=brand_id,
            path=path,
            kind=_PAGE_KIND,
            front=front,
            body=body,
        )
        if path != page.path:
            await _retire_path(conn, workspace_id=workspace_id, brand_id=brand_id, path=page.path)
        page_path = path
    catalog_id = await regenerate_catalog(
        conn, storage, workspace_id=workspace_id, brand_id=brand_id, change_id=change_id
    )
    details = {
        "before": before.name,
        "after": product.name,
        "result": {
            "page_document_id": str(page_id) if page_id else None,
            "page_pending": False,
            "catalog_document_id": str(catalog_id),
            "page_path": page_path,
        },
    }
    await _record_change(
        conn,
        change_id=change_id,
        workspace_id=workspace_id,
        brand_id=brand_id,
        kind="rename",
        product_id=product_id,
        affected=[product_id],
        details=details,
        actor=actor,
        idempotency_key=idempotency_key,
    )
    return ProductChangeResult(
        change_id,
        "rename",
        describe_change("rename", details),
        product,
        page_id,
        False,
        catalog_id,
        (),
        page_path=page_path,
    )


async def merge_products_action(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    workspace_id: str,
    brand_id: str,
    actor: ProductActor,
    product_ids: Sequence[str],
    into_product_id: str | None = None,
    new_name: str | None = None,
    page_markdown: str | None = None,
    idempotency_key: str | None = None,
) -> ProductChangeResult:
    """Fold products into one: an existing product (``into_product_id``) or a new one
    (``new_name``; a member already carrying that name becomes the survivor instead)."""
    await _lock_brand(conn, workspace_id=workspace_id, brand_id=brand_id)
    if replay := await _replayed(conn, workspace_id=workspace_id, idempotency_key=idempotency_key):
        return replay
    if (into_product_id is None) == (new_name is None):
        raise ProductChangeRefused(
            "merge_invalid", "merge into an existing product or a new name, not both"
        )
    ordered = list(dict.fromkeys(product_ids))
    members = [
        await _active_product(conn, workspace_id=workspace_id, brand_id=brand_id, product_id=pid)
        for pid in ordered
    ]
    created_survivor = False
    if new_name is not None:
        clean = _clean_name(new_name)
        same = [m for m in members if normalize_identity(m.name) == normalize_identity(clean)]
        if same:
            into_product_id = same[0].product_id
        else:
            await _refuse_taken_name(conn, brand_id=brand_id, name=clean)
            try:
                async with conn.begin_nested():
                    created = await create_product(
                        conn, brand_id=brand_id, workspace_id=workspace_id, name=clean
                    )
            except IntegrityError as error:
                raise _name_taken(error) from error
            into_product_id = created.product_id
            created_survivor = True
    assert into_product_id is not None
    await _active_product(
        conn, workspace_id=workspace_id, brand_id=brand_id, product_id=into_product_id
    )
    folded = [m for m in members if m.product_id != into_product_id]
    if not folded:
        raise ProductChangeRefused("merge_invalid", "choose at least one product to merge in")

    change_id = uuid4()
    docs = await _product_folder(conn, storage, workspace_id=workspace_id, brand_id=brand_id)
    pages = _main_pages(docs)
    retired: dict[str, str] = {}
    for member in folded:
        page = pages.get(member.product_id)
        if page is not None:
            await _retire_path(conn, workspace_id=workspace_id, brand_id=brand_id, path=page.path)
            retired[member.product_id] = str(page.document_id)
    survivor, aliases_added = await merge_products(
        conn,
        product_ids=[m.product_id for m in folded],
        into_product_id=into_product_id,
        workspace_id=workspace_id,
    )
    survivor_page = pages.get(survivor.product_id)
    path = _page_path(survivor, docs, current=survivor_page)
    if page_markdown and page_markdown.strip():
        page_id = await _write_doc(
            conn,
            storage,
            workspace_id=workspace_id,
            brand_id=brand_id,
            path=path,
            kind=_PAGE_KIND,
            front=_page_front(survivor, actor, change_id),
            body=_page_body(survivor.name, page_markdown),
        )
        pending = False
    else:
        page_id = await _open_pending_page(
            conn, workspace_id=workspace_id, brand_id=brand_id, path=path
        )
        pending = True
    catalog_id = await regenerate_catalog(
        conn, storage, workspace_id=workspace_id, brand_id=brand_id, change_id=change_id
    )
    details = {
        "names": [m.name for m in folded],
        "into": survivor.name,
        "aliases_added": list(aliases_added),
        "created_survivor": created_survivor,
        "retired_pages": retired,
        "page_path": path,
        "result": {
            "page_document_id": str(page_id),
            "page_pending": pending,
            "catalog_document_id": str(catalog_id),
            "page_path": path,
        },
    }
    await _record_change(
        conn,
        change_id=change_id,
        workspace_id=workspace_id,
        brand_id=brand_id,
        kind="merge",
        product_id=survivor.product_id,
        affected=[m.product_id for m in folded],
        details=details,
        actor=actor,
        idempotency_key=idempotency_key,
    )
    projects = await _move_project_sets(
        conn,
        workspace_id=workspace_id,
        brand_id=brand_id,
        change_id=change_id,
        mapping={m.product_id: survivor.product_id for m in folded},
        user_id=actor.user_id,
    )
    return ProductChangeResult(
        change_id,
        "merge",
        describe_change("merge", details),
        survivor,
        page_id,
        pending,
        catalog_id,
        projects,
        page_path=path,
    )


async def remove_product_action(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    workspace_id: str,
    brand_id: str,
    actor: ProductActor,
    product_id: str,
    idempotency_key: str | None = None,
) -> ProductChangeResult:
    await _lock_brand(conn, workspace_id=workspace_id, brand_id=brand_id)
    if replay := await _replayed(conn, workspace_id=workspace_id, idempotency_key=idempotency_key):
        return replay
    await _active_product(conn, workspace_id=workspace_id, brand_id=brand_id, product_id=product_id)
    change_id = uuid4()
    docs = await _product_folder(conn, storage, workspace_id=workspace_id, brand_id=brand_id)
    page = _main_pages(docs).get(product_id)
    retired: dict[str, str] = {}
    if page is not None:
        await _retire_path(conn, workspace_id=workspace_id, brand_id=brand_id, path=page.path)
        retired[product_id] = str(page.document_id)
    product = await archive_product(conn, product_id=product_id, workspace_id=workspace_id)
    catalog_id = await regenerate_catalog(
        conn, storage, workspace_id=workspace_id, brand_id=brand_id, change_id=change_id
    )
    details = {
        "name": product.name,
        "retired_pages": retired,
        "result": {
            "page_document_id": None,
            "page_pending": False,
            "catalog_document_id": str(catalog_id),
        },
    }
    await _record_change(
        conn,
        change_id=change_id,
        workspace_id=workspace_id,
        brand_id=brand_id,
        kind="remove",
        product_id=product_id,
        affected=[product_id],
        details=details,
        actor=actor,
        idempotency_key=idempotency_key,
    )
    projects = await _move_project_sets(
        conn,
        workspace_id=workspace_id,
        brand_id=brand_id,
        change_id=change_id,
        mapping={product_id: None},
        user_id=actor.user_id,
    )
    return ProductChangeResult(
        change_id,
        "remove",
        describe_change("remove", details),
        product,
        None,
        False,
        catalog_id,
        projects,
    )


async def _republish(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    workspace_id: str,
    brand_id: str,
    document_id: UUID,
) -> UUID | None:
    row = (
        (
            await conn.execute(
                text(
                    "SELECT document_id, path, kind, version, status, artifact_key, "
                    " artifact_sha256 FROM brand_knowledge_document WHERE document_id = :id "
                    "AND workspace_id = :ws AND brand_id = :brand AND project_id IS NULL"
                ),
                {"id": document_id, "ws": workspace_id, "brand": brand_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None or not row["artifact_key"]:
        return None
    doc = await _read_doc(conn, storage, workspace_id=workspace_id, row=row)
    return await _write_doc(
        conn,
        storage,
        workspace_id=workspace_id,
        brand_id=brand_id,
        path=doc.path,
        kind=doc.kind,
        front=doc.front,
        body=doc.body,
    )


async def undo_product_change(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    workspace_id: str,
    brand_id: str,
    actor: ProductActor,
    change_id: UUID,
) -> ProductChangeResult:
    """Undo a merge or a removal: the products come back, their pages come back, and every
    project the change moved goes back to its earlier set — unless that project's set was changed
    again since, which is then left as it is."""
    await _lock_brand(conn, workspace_id=workspace_id, brand_id=brand_id)
    original = (
        (
            await conn.execute(
                text(
                    "SELECT * FROM product_change WHERE change_id = :id AND workspace_id = :ws "
                    "AND brand_id = :brand"
                ),
                {"id": change_id, "ws": workspace_id, "brand": brand_id},
            )
        )
        .mappings()
        .first()
    )
    if original is None:
        raise ProductChangeRefused("change_not_found", "no such product change in this brand")
    if original["kind"] not in ("merge", "remove"):
        raise ProductChangeRefused("change_not_undoable", "only a merge or a removal can be undone")
    undone = await conn.scalar(
        text("SELECT 1 FROM product_change WHERE undoes_change_id = :id"), {"id": change_id}
    )
    if undone:
        raise ProductChangeRefused("change_not_undoable", "this change was already undone")
    details = decode_jsonb(original["details"]) or {}
    affected = [str(pid) for pid in decode_jsonb(original["affected_product_ids"]) or []]
    survivor_id = str(original["product_id"])

    try:
        async with conn.begin_nested():
            for pid in affected:
                await restore_product(conn, product_id=pid, workspace_id=workspace_id)
    except IntegrityError as error:
        raise _name_taken(error) from error
    except ValueError as error:
        raise ProductChangeRefused("change_not_undoable", str(error)) from error

    undo_id = uuid4()
    if original["kind"] == "merge":
        await remove_product_aliases(
            conn,
            product_id=survivor_id,
            workspace_id=workspace_id,
            aliases=details.get("aliases_added") or [],
        )
        if details.get("created_survivor"):
            survivor = await get_product(conn, survivor_id)
            if survivor is not None and survivor.status == "active":
                await archive_product(conn, product_id=survivor_id, workspace_id=workspace_id)
                if details.get("page_path"):
                    await _retire_path(
                        conn,
                        workspace_id=workspace_id,
                        brand_id=brand_id,
                        path=str(details["page_path"]),
                    )
    for document_id in (details.get("retired_pages") or {}).values():
        await _republish(
            conn,
            storage,
            workspace_id=workspace_id,
            brand_id=brand_id,
            document_id=UUID(str(document_id)),
        )
    catalog_id = await regenerate_catalog(
        conn, storage, workspace_id=workspace_id, brand_id=brand_id, change_id=undo_id
    )
    undo_details = {
        "undid": describe_change(str(original["kind"]), details),
        "result": {
            "page_document_id": None,
            "page_pending": False,
            "catalog_document_id": str(catalog_id),
        },
    }
    await _record_change(
        conn,
        change_id=undo_id,
        workspace_id=workspace_id,
        brand_id=brand_id,
        kind="restore",
        product_id=survivor_id,
        affected=affected,
        details=undo_details,
        actor=actor,
        idempotency_key=None,
        undoes=change_id,
    )
    moved = await conn.execute(
        text(
            "SELECT project_id, selection_version, previous_selection_version "
            "FROM product_change_project WHERE change_id = :id AND outcome = 'updated' "
            "ORDER BY project_id"
        ),
        {"id": change_id},
    )
    projects: list[ProjectSetOutcome] = []
    for row in moved.mappings().all():
        project_id = str(row["project_id"])
        sets = await list_project_product_sets(
            conn, workspace_id=workspace_id, project_id=project_id
        )
        current = sets[-1] if sets else None
        before = next(
            (s for s in sets if s.selection_version == row["previous_selection_version"]), None
        )
        if (
            current is None
            or before is None
            or current.selection_version != row["selection_version"]
        ):
            projects.append(
                await _record_project(
                    conn,
                    change_id=undo_id,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    outcome="left_as_is",
                    selection_version=None,
                    previous_selection_version=current.selection_version if current else None,
                )
            )
            continue
        written = await confirm_project_product_set(
            conn,
            workspace_id=workspace_id,
            project_id=project_id,
            product_ids=before.product_ids,
            gate_id=None,
            confirmed_by_user_id=actor.user_id,
            product_change_id=undo_id,
        )
        assert written is not None
        projects.append(
            await _record_project(
                conn,
                change_id=undo_id,
                workspace_id=workspace_id,
                project_id=project_id,
                outcome="restored",
                selection_version=written.selection_version,
                previous_selection_version=current.selection_version,
            )
        )
    product = await get_product(conn, survivor_id)
    assert product is not None
    return ProductChangeResult(
        undo_id,
        "restore",
        describe_change("restore", undo_details),
        product,
        None,
        False,
        catalog_id,
        tuple(projects),
    )


# --- reads --------------------------------------------------------------------------------------


async def list_brand_products(
    conn: AsyncConnection, storage: StorageBackend, *, workspace_id: str, brand_id: str
) -> list[BrandProduct]:
    docs = await _product_folder(conn, storage, workspace_id=workspace_id, brand_id=brand_id)
    pages = _main_pages(docs)
    pending = await _pending_pages(conn, workspace_id=workspace_id, brand_id=brand_id)
    out: list[BrandProduct] = []
    for product in await list_products(conn, brand_id):
        if product.status != "active" or product.workspace_id != workspace_id:
            continue
        page = pages.get(product.product_id)
        expected = page.path if page else f"product/{slugify(product.name)}.md"
        out.append(
            BrandProduct(
                product_id=product.product_id,
                name=product.name,
                aliases=product.aliases,
                page_document_id=page.document_id if page else None,
                page_path=page.path if page else None,
                page_pending=expected in pending,
            )
        )
    return out


async def recent_product_changes(
    conn: AsyncConnection, *, workspace_id: str, brand_id: str, since: datetime, limit: int = 20
) -> list[ProductChangeLine]:
    rows = await conn.execute(
        text(
            "SELECT c.change_id, c.kind, c.details, c.created_at, "
            " EXISTS (SELECT 1 FROM product_change u WHERE u.undoes_change_id = c.change_id) "
            "   AS undone "
            "FROM product_change c WHERE c.workspace_id = :ws AND c.brand_id = :brand "
            "AND c.created_at >= :since ORDER BY c.created_at DESC LIMIT :limit"
        ),
        {"ws": workspace_id, "brand": brand_id, "since": since, "limit": limit},
    )
    return [
        ProductChangeLine(
            change_id=row["change_id"],
            kind=str(row["kind"]),
            text=describe_change(str(row["kind"]), decode_jsonb(row["details"]) or {}),
            created_at=row["created_at"],
            undoable=row["kind"] in ("merge", "remove") and not row["undone"],
        )
        for row in rows.mappings().all()
    ]


async def recent_change_lines(
    conn: AsyncConnection, *, workspace_id: str, brand_id: str, days: int = 30
) -> tuple[str, ...]:
    """The agent's view of recent product changes: "15 Oct 2026: 8 products merged into Proxon"."""
    since = datetime.now(UTC) - timedelta(days=days)
    changes = await recent_product_changes(
        conn, workspace_id=workspace_id, brand_id=brand_id, since=since
    )
    return tuple(f"{c.created_at:%d %b %Y}: {c.text}" for c in changes)


async def publish_product_page(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    workspace_id: str,
    brand_id: str,
    document_id: UUID,
    product_id: str,
    change_id: UUID,
    actor_user_id: str,
    markdown: str,
) -> bool:
    """Fill a pending (``running``) page with the background writer's markdown.

    Returns ``False`` — and marks the row ``failed`` — when the row is no longer the newest
    version of its path (someone wrote the page meanwhile) or its product left the list.
    """
    row = (
        (
            await conn.execute(
                text(
                    "SELECT path, version, status FROM brand_knowledge_document "
                    "WHERE document_id = :id AND workspace_id = :ws AND brand_id = :brand "
                    "AND project_id IS NULL FOR UPDATE"
                ),
                {"id": document_id, "ws": workspace_id, "brand": brand_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None or row["status"] != "running":
        return False
    newest = await _next_version(
        conn, workspace_id=workspace_id, brand_id=brand_id, path=str(row["path"])
    )
    product = await get_product(conn, product_id)
    if newest != int(row["version"]) + 1 or product is None or product.status != "active":
        await mark_product_page_failed(conn, document_id=document_id)
        return False
    data = render_markdown(
        KnowledgeDocument(
            kind=_PAGE_KIND,
            folder=_PRODUCT_FOLDER,
            path=str(row["path"]),
            front_matter=_page_front(product, ProductActor(actor_user_id), change_id),
            body=_page_body(product.name, markdown),
            cost=None,
        )
    ).encode("utf-8")
    key, sha = await _store(conn, storage, workspace_id=workspace_id, data=data)
    await conn.execute(
        text(
            "UPDATE brand_knowledge_document SET status = 'ready', artifact_key = :key, "
            " artifact_sha256 = :sha, updated_at = now() WHERE document_id = :id"
        ),
        {"key": key, "sha": sha, "id": document_id},
    )
    await _retire_path(
        conn,
        workspace_id=workspace_id,
        brand_id=brand_id,
        path=str(row["path"]),
        below=int(row["version"]),
    )
    return True


async def read_brand_document(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    workspace_id: str,
    brand_id: str,
    document_id: UUID,
) -> tuple[dict[str, Any], str] | None:
    """One brand-level document's front matter and body, whatever its status (a retired page is
    still readable — that is what the page writer and an undo read)."""
    row = (
        (
            await conn.execute(
                text(
                    "SELECT document_id, path, kind, version, status, artifact_key, "
                    " artifact_sha256 FROM brand_knowledge_document WHERE document_id = :id "
                    "AND workspace_id = :ws AND brand_id = :brand AND project_id IS NULL"
                ),
                {"id": document_id, "ws": workspace_id, "brand": brand_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None or not row["artifact_key"]:
        return None
    doc = await _read_doc(conn, storage, workspace_id=workspace_id, row=row)
    return doc.front, doc.body


async def change_details(
    conn: AsyncConnection, *, workspace_id: str, change_id: UUID
) -> dict[str, Any] | None:
    details = await conn.scalar(
        text("SELECT details FROM product_change WHERE change_id = :id AND workspace_id = :ws"),
        {"id": change_id, "ws": workspace_id},
    )
    return None if details is None else dict(decode_jsonb(details) or {})


async def main_page_of(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    workspace_id: str,
    brand_id: str,
    product_id: str,
) -> tuple[dict[str, Any], str] | None:
    docs = await _product_folder(conn, storage, workspace_id=workspace_id, brand_id=brand_id)
    page = _main_pages(docs).get(product_id)
    return None if page is None else (page.front, page.body)


async def mark_product_page_failed(conn: AsyncConnection, *, document_id: UUID) -> None:
    await conn.execute(
        text(
            "UPDATE brand_knowledge_document SET status = 'failed', updated_at = now() "
            "WHERE document_id = :id AND status = 'running'"
        ),
        {"id": document_id},
    )
