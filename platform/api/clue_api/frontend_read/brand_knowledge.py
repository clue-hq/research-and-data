"""The brand-context Knowledge reads (ARV2-ONBOARDING-PLAN.md §7; O5).

Three workspace-scoped reads on the ``/frontend/v1`` router: the folder tree of the
brand's *servable* knowledge documents (``ready`` / ``proposed`` / ``confirmed``, highest such
version per path — founder ruling 2026-09-08: no status chip, so nothing else is listed), one
document with its markdown, front matter and flattened sources, and the onboarding run's status
(the O3 read, mirrored here so the page has one surface). Folder order and labels are the
dummy's. The ``design`` folder is the brand kit's and is never served here.
Human edits append immutable document versions through the matching PUT route.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import Field
from sqlalchemy import bindparam, text
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.knowledge_frontmatter import parse_front_matter
from clue_api.arv2.onboarding_documents import KnowledgeDocument, render_markdown
from clue_api.arv2.onboarding_store import read_current_run
from clue_api.auth_wiring import principal_from_request
from clue_api.frontend_read.accounts_list import WireModel
from clue_api.frontend_read.app import WorkspaceDep
from clue_api.knowledge_bytes import read_knowledge_bytes, read_one_knowledge_bytes
from clue_api.product_management import regenerate_catalog
from clue_db import ConnFactory
from clue_obs import get_logger
from clue_spine import list_products
from clue_storage import (
    StorageBackend,
    artifact_key,
    content_address,
    record_artifact,
)

log = get_logger("clue_api.frontend_read.brand_knowledge")

__all__ = [
    "SERVABLE_STATUSES",
    "KnowledgeDocumentDetailWire",
    "KnowledgeDocumentWire",
    "KnowledgeFolderWire",
    "KnowledgeSourceWire",
    "KnowledgeTreeWire",
    "OnboardingStatusWire",
    "OnboardingStepWire",
    "read_knowledge_document",
    "read_knowledge_tree",
    "read_onboarding_status",
    "register_brand_knowledge_routes",
    "resolve_knowledge_brand",
]

SERVABLE_STATUSES: tuple[str, ...] = ("ready", "proposed", "confirmed")
#: The dummy's folder order and labels (`brand-context.fixture.ts`); ``design`` is the kit's.
FOLDERS: tuple[tuple[str, str], ...] = (
    ("company", "Company"),
    ("product", "Product"),
    ("audience", "Audience"),
    ("proof", "Proof"),
)


class KnowledgeDocumentWire(WireModel):
    id: str
    path: str
    title: str
    kind: str
    version: int
    status: str
    updated_at: str
    product_id: str | None
    icp_key: str | None
    #: Every product the document names (``product_id`` for a page, ``product_ids`` otherwise).
    product_ids: list[str] = Field(default_factory=list)
    #: The catalog generated from the product list — read-only in the editor.
    generated: bool = False


class KnowledgeFolderWire(WireModel):
    key: str
    label: str
    documents: list[KnowledgeDocumentWire]


class KnowledgeTreeWire(WireModel):
    brand_id: str | None
    folders: list[KnowledgeFolderWire]


class KnowledgeSourceWire(WireModel):
    section: str
    url: str
    title: str | None
    confidence: str | None


class KnowledgeDocumentDetailWire(WireModel):
    id: str
    path: str
    title: str
    kind: str
    version: int
    status: str
    updated_at: str
    product_id: str | None
    icp_key: str | None
    product_ids: list[str] = Field(default_factory=list)
    generated: bool = False
    markdown: str
    front_matter: dict[str, Any]
    sources: list[KnowledgeSourceWire]


class KnowledgeDocumentUpdate(WireModel):
    body: str = Field(max_length=1_000_000)
    expected_revision: int = Field(ge=1, strict=True)
    #: The products this document is about (spec 2026-10-15 §4.1), set through the editor's
    #: picker. ``None`` leaves the document's link as it is; a product page takes exactly one.
    product_ids: list[str] | None = Field(default=None, max_length=50)


_PRODUCT_PAGE_KIND = "product-research"


async def _validated_product_link(
    conn: AsyncConnection, *, brand_id: str, kind: str, ids: list[str]
) -> list[str]:
    """The picker's choice, checked: every id an active product of this brand, and exactly one
    for a product page (a page is about one product)."""
    chosen = list(dict.fromkeys(ids))
    active = {p.product_id for p in await list_products(conn, brand_id) if p.status == "active"}
    if not set(chosen) <= active or (kind == _PRODUCT_PAGE_KIND and len(chosen) != 1):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "PRODUCT_LINK_INVALID",
                "message": "Choose products from this brand's list (one for a product page).",
            },
        )
    return chosen


def _revision_conflict() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "DOCUMENT_REVISION_CONFLICT",
            "message": "A newer version exists or is being prepared. The draft was not saved.",
        },
    )


async def save_knowledge_document(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    workspace_id: str,
    document_id: UUID,
    update: KnowledgeDocumentUpdate,
    user_id: str,
) -> KnowledgeDocumentDetailWire:
    """Append human-edited Markdown. Never mutate bytes pinned by an existing turn or gate.

    Brand-level rows only: this surface edits the brand's knowledge, so a project-scoped document
    is a 404 here, and the version it appends is the next **brand** version of that path.
    """
    row = (
        (
            await conn.execute(
                text(
                    "SELECT * FROM brand_knowledge_document "
                    "WHERE workspace_id = :ws AND document_id = :id "
                    "AND folder IN ('company', 'product', 'audience', 'proof') "
                    "AND project_id IS NULL FOR UPDATE"
                ),
                {"ws": workspace_id, "id": document_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "KNOWLEDGE_DOCUMENT_NOT_FOUND", "message": "Document not found."},
        )
    # Serialize competing human saves for this brand. Other publishers may race to insert the
    # next version; the database unique constraint remains the final arbiter (409 at the route).
    await conn.execute(
        text(
            "SELECT brand_id FROM brand WHERE workspace_id = :ws AND brand_id = :brand FOR UPDATE"
        ),
        {"ws": workspace_id, "brand": row["brand_id"]},
    )
    latest = await conn.scalar(
        text(
            "SELECT MAX(version) FROM brand_knowledge_document WHERE workspace_id = :ws "
            "AND brand_id = :brand AND path = :path AND project_id IS NULL"
        ),
        {"ws": workspace_id, "brand": row["brand_id"], "path": row["path"]},
    )
    if (
        row["status"] not in SERVABLE_STATUSES
        or row["version"] != update.expected_revision
        or latest != row["version"]
    ):
        raise _revision_conflict()
    front, original = await _front_and_body(conn, storage, workspace_id=workspace_id, row=row)
    if front.get("generated") is True:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "CATALOG_IS_GENERATED",
                "message": "The catalog is generated from your products. Rename, merge or "
                "remove a product to change it.",
            },
        )
    link_changed = False
    if update.product_ids is not None:
        linked = await _validated_product_link(
            conn, brand_id=str(row["brand_id"]), kind=str(row["kind"]), ids=update.product_ids
        )
        before = (front.get("product_id"), front.get("product_ids"))
        if row["kind"] == _PRODUCT_PAGE_KIND:
            front["product_id"] = linked[0]
        elif linked:
            front["product_ids"] = linked
        else:
            front.pop("product_ids", None)
        link_changed = before != (front.get("product_id"), front.get("product_ids"))
    if original == update.body and not link_changed:
        existing = await read_knowledge_document(
            conn, storage, workspace_id=workspace_id, document_id=document_id
        )
        assert existing is not None
        return existing
    status = "proposed" if row["status"] == "confirmed" else row["status"]
    # A human text edit cannot carry forward another version's approval stamp. Retain the
    # old confirmed row for projects already pinned to it; this version returns to review.
    if row["status"] == "confirmed":
        for key in (
            "confirmed_by",
            "confirmed_at",
            "confirmed_for_project_id",
            "product_selection_version",
        ):
            front.pop(key, None)
    front["status"] = status
    front["user_edit"] = {
        "user_id": user_id,
        "edited_at": datetime.now(UTC).isoformat(),
        "source_document_id": str(document_id),
        "source_version": row["version"],
    }
    data = render_markdown(
        KnowledgeDocument(
            kind=row["kind"],
            folder=row["folder"],
            path=row["path"],
            front_matter=front,
            body=update.body,
            cost=None,
        )
    ).encode("utf-8")
    sha = content_address(data)
    key = artifact_key(workspace_id, sha)
    await record_artifact(
        conn,
        storage_key=key,
        workspace_id=workspace_id,
        content_sha256=sha,
        media_type="text/markdown",
        size_bytes=len(data),
        source_key="brand_knowledge_user_edit",
    )
    await storage.put(key, data, media_type="text/markdown")
    new_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO brand_knowledge_document "
            "(document_id, workspace_id, brand_id, folder, path, kind, "
            "version, status, artifact_key, artifact_sha256, supersedes_document_id) "
            "VALUES (:id, :ws, :brand, :folder, :path, :kind, "
            ":version, :status, :key, :sha, :previous)"
        ),
        {
            "id": new_id,
            "ws": workspace_id,
            "brand": row["brand_id"],
            "folder": row["folder"],
            "path": row["path"],
            "kind": row["kind"],
            "version": row["version"] + 1,
            "status": status,
            "key": key,
            "sha": sha,
            "previous": document_id,
        },
    )
    if row["status"] != "confirmed":
        await conn.execute(
            text(
                "UPDATE brand_knowledge_document SET status = 'superseded', updated_at = now() "
                "WHERE document_id = :id"
            ),
            {"id": document_id},
        )
    if row["kind"] == _PRODUCT_PAGE_KIND:
        # A product's page is how a person corrects its catalog line (spec 2026-10-15).
        await regenerate_catalog(
            conn,
            storage,
            workspace_id=workspace_id,
            brand_id=str(row["brand_id"]),
            change_id=None,
        )
    saved = await read_knowledge_document(
        conn, storage, workspace_id=workspace_id, document_id=new_id
    )
    assert saved is not None
    return saved


class OnboardingStepWire(WireModel):
    kind: str
    subject_ref: str | None
    phase: str
    status: str
    started_at: str | None
    finished_at: str | None
    cost_usd: str
    failure_code: str | None


class OnboardingStatusWire(WireModel):
    run_id: str | None
    status: str
    steps: list[OnboardingStepWire]
    cost_usd: str


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _title(path: str, body: str) -> str:
    """The first ``# `` heading of the body, else the file name without ``.md``."""
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    name = path.rsplit("/", 1)[-1]
    return name[:-3] if name.endswith(".md") else name


def _optional_str(front: Mapping[str, Any], key: str) -> str | None:
    value = front.get(key)
    return value if isinstance(value, str) and value else None


def _sources(front: Mapping[str, Any]) -> list[KnowledgeSourceWire]:
    """Flatten the mappers' ``sources`` map (field → {citations[], confidence}) — O2's shape."""
    raw = front.get("sources")
    if not isinstance(raw, dict):
        return []
    out: list[KnowledgeSourceWire] = []
    for section in sorted(raw):
        entry = raw[section]
        if not isinstance(entry, dict):
            continue
        confidence = entry.get("confidence")
        for citation in entry.get("citations") or []:
            if isinstance(citation, dict) and isinstance(citation.get("url"), str):
                title = citation.get("title")
                out.append(
                    KnowledgeSourceWire(
                        section=str(section),
                        url=citation["url"],
                        title=title if isinstance(title, str) else None,
                        confidence=confidence if isinstance(confidence, str) else None,
                    )
                )
    return out


async def resolve_knowledge_brand(
    conn: AsyncConnection, *, workspace_id: str, brand_id: str | None
) -> str | None:
    """The brand whose knowledge this workspace is reading.

    An explicit ``brand_id`` wins when it belongs to the workspace (a foreign id resolves to
    ``None`` rather than leaking another tenant's tree); otherwise the newest ``onboarding_run``'s
    brand; otherwise the workspace's *only* brand. Ambiguity (several brands, no run) is ``None``,
    never a guess.
    """
    if brand_id is not None:
        owned = (
            await conn.execute(
                text("SELECT brand_id FROM brand WHERE workspace_id = :ws AND brand_id = :brand"),
                {"ws": workspace_id, "brand": brand_id},
            )
        ).scalar_one_or_none()
        return str(owned) if owned is not None else None
    newest_run = (
        await conn.execute(
            text(
                "SELECT brand_id FROM onboarding_run WHERE workspace_id = :ws "
                "ORDER BY requested_at DESC LIMIT 1"
            ),
            {"ws": workspace_id},
        )
    ).scalar_one_or_none()
    if newest_run is not None:
        return str(newest_run)
    brands = (
        (
            await conn.execute(
                text(
                    "SELECT brand_id FROM brand WHERE workspace_id = :ws "
                    "ORDER BY created_at, brand_id"
                ),
                {"ws": workspace_id},
            )
        )
        .scalars()
        .all()
    )
    return str(brands[0]) if len(brands) == 1 else None


_CURRENT_SERVABLE_SQL = text(
    "SELECT d.document_id, d.folder, d.path, d.kind, d.version, d.status, d.updated_at, "
    " d.artifact_key, d.artifact_sha256 "
    "FROM brand_knowledge_document d "
    "WHERE d.workspace_id = :ws AND d.brand_id = :brand AND d.folder IN :folders "
    " AND d.status IN :servable AND d.project_id IS NULL "
    " AND d.version = (SELECT MAX(d2.version) FROM brand_knowledge_document d2 "
    "   WHERE d2.workspace_id = d.workspace_id AND d2.brand_id = d.brand_id "
    "     AND d2.path = d.path AND d2.status IN :servable AND d2.project_id IS NULL) "
    "ORDER BY d.folder, d.path"
).bindparams(bindparam("folders", expanding=True), bindparam("servable", expanding=True))


async def _current_servable(
    conn: AsyncConnection, *, workspace_id: str, brand_id: str
) -> list[RowMapping]:
    rows = await conn.execute(
        _CURRENT_SERVABLE_SQL,
        {
            "ws": workspace_id,
            "brand": brand_id,
            "folders": [key for key, _ in FOLDERS],
            "servable": list(SERVABLE_STATUSES),
        },
    )
    return list(rows.mappings().all())


async def _front_and_body(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    workspace_id: str,
    row: RowMapping,
) -> tuple[dict[str, Any], str]:
    raw = await read_one_knowledge_bytes(
        conn,
        storage,
        workspace_id=workspace_id,
        ref=(str(row["artifact_key"]), str(row["artifact_sha256"])),
    )
    return _parse_document(raw)


def _parse_document(raw: bytes) -> tuple[dict[str, Any], str]:
    try:
        return parse_front_matter(raw.decode("utf-8"), preserve_body=True)
    except (UnicodeDecodeError, ValueError):
        return {}, raw.decode("utf-8", errors="replace")


def _document_wire(
    row: RowMapping, *, front: Mapping[str, Any], body: str
) -> KnowledgeDocumentWire:
    return KnowledgeDocumentWire(
        id=str(row["document_id"]),
        path=str(row["path"]),
        title=_title(str(row["path"]), body),
        kind=str(row["kind"]),
        version=int(row["version"]),
        status=str(row["status"]),
        updated_at=_iso(row["updated_at"]) or "",
        product_id=_optional_str(front, "product_id"),
        icp_key=_optional_str(front, "icp_key"),
        product_ids=_linked_products(front),
        generated=front.get("generated") is True,
    )


def _linked_products(front: Mapping[str, Any]) -> list[str]:
    single = _optional_str(front, "product_id")
    many = front.get("product_ids")
    listed = [p for p in many if isinstance(p, str) and p] if isinstance(many, list) else []
    return list(dict.fromkeys([single, *listed] if single else listed))


async def read_knowledge_tree(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    brand_id: str | None,
    storage: StorageBackend | None,
) -> KnowledgeTreeWire:
    """The four folders, always all four, each carrying its brand's current servable documents.

    Every document's artifact is read for its title, product id and ICP key (sequentially; a tree
    is at most a few dozen documents). A process with no storage still serves the tree, with
    file-name titles and no ids — the shape the page needs, honestly degraded.
    """
    documents: dict[str, list[KnowledgeDocumentWire]] = {key: [] for key, _ in FOLDERS}
    if brand_id is not None:
        rows = await _current_servable(conn, workspace_id=workspace_id, brand_id=brand_id)
        # Every document is opened for its title and links, so they are fetched together and
        # served from the content cache on a reload (2026-10-15: 37 in turn took 8.7 s).
        contents = (
            await read_knowledge_bytes(
                conn,
                storage,
                workspace_id=workspace_id,
                refs=[(str(r["artifact_key"]), str(r["artifact_sha256"])) for r in rows],
            )
            if storage is not None
            else {}
        )
        for row in rows:
            front: dict[str, Any] = {}
            body = ""
            if storage is not None:
                raw = contents.get((str(row["artifact_key"]), str(row["artifact_sha256"])))
                if isinstance(raw, bytes):
                    front, body = _parse_document(raw)
                else:
                    # A missing blob lists the document by name, never 500s the tree.
                    log.warning(
                        "brand_knowledge.document_unreadable",
                        workspace_id=workspace_id,
                        document_id=str(row["document_id"]),
                        path=str(row["path"]),
                    )
            documents[str(row["folder"])].append(_document_wire(row, front=front, body=body))
    return KnowledgeTreeWire(
        brand_id=brand_id,
        folders=[
            KnowledgeFolderWire(key=key, label=label, documents=documents[key])
            for key, label in FOLDERS
        ],
    )


async def read_knowledge_document(
    conn: AsyncConnection, storage: StorageBackend, *, workspace_id: str, document_id: UUID
) -> KnowledgeDocumentDetailWire | None:
    """One servable document with its markdown, front matter and flattened sources.

    ``None`` when the row is missing, belongs to another workspace, is not servable, lives in a
    folder this surface does not serve, or is scoped to a project — the caller turns all of them
    into the same 404, so a probe cannot distinguish "not yours" from "not there". This is the
    *brand* knowledge surface; a project's own documents are read through the project surface.
    """
    row = (
        (
            await conn.execute(
                text(
                    "SELECT document_id, folder, path, kind, version, status, updated_at, "
                    " artifact_key, artifact_sha256 FROM brand_knowledge_document "
                    "WHERE workspace_id = :ws AND document_id = :id AND status IN :servable "
                    " AND folder IN :folders AND project_id IS NULL"
                ).bindparams(
                    bindparam("servable", expanding=True), bindparam("folders", expanding=True)
                ),
                {
                    "ws": workspace_id,
                    "id": document_id,
                    "servable": list(SERVABLE_STATUSES),
                    "folders": [key for key, _ in FOLDERS],
                },
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        return None
    front, body = await _front_and_body(conn, storage, workspace_id=workspace_id, row=row)
    base = _document_wire(row, front=front, body=body)
    return KnowledgeDocumentDetailWire(
        **base.model_dump(),
        markdown=body,
        front_matter=dict(front),
        sources=_sources(front),
    )


async def read_onboarding_status(
    conn: AsyncConnection, *, workspace_id: str
) -> OnboardingStatusWire:
    """The O3 run status, mirrored onto this surface so the page reads one origin."""
    status = await read_current_run(conn, workspace_id=workspace_id)
    if status is None:
        return OnboardingStatusWire(run_id=None, status="none", steps=[], cost_usd="0")
    return OnboardingStatusWire(
        run_id=str(status.run_id),
        status=status.status,
        steps=[
            OnboardingStepWire(
                kind=step.kind,
                subject_ref=step.subject_ref,
                phase=step.phase,
                status=step.status,
                started_at=_iso(step.started_at),
                finished_at=_iso(step.finished_at),
                cost_usd=str(step.cost_usd),
                failure_code=step.failure_code,
            )
            for step in status.steps
        ],
        cost_usd=str(status.cost_usd),
    )


def register_brand_knowledge_routes(
    router: APIRouter,
    *,
    conn_factory: ConnFactory,
    storage: StorageBackend | None,
    allow_local_mutations: bool = False,
) -> None:
    @router.put(
        "/brand-context/knowledge/documents/{document_id}",
        response_model=KnowledgeDocumentDetailWire,
    )
    async def put_knowledge_document(
        request: Request,
        workspace_id: WorkspaceDep,
        document_id: UUID,
        body: KnowledgeDocumentUpdate,
    ) -> KnowledgeDocumentDetailWire:
        principal = principal_from_request(request)
        if principal is not None:
            principal.require("project.write")
            user_id = principal.user_id
        elif allow_local_mutations:
            user_id = "local-development-user"
        else:
            raise HTTPException(
                status_code=401,
                detail={"code": "UNAUTHORIZED", "message": "An authenticated session is required."},
            )
        if storage is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "KNOWLEDGE_STORAGE_UNAVAILABLE",
                    "message": "Document storage is unavailable.",
                },
            )
        try:
            async with conn_factory() as conn:
                return await save_knowledge_document(
                    conn,
                    storage,
                    workspace_id=workspace_id,
                    document_id=document_id,
                    update=body,
                    user_id=user_id,
                )
        except IntegrityError as exc:
            if "brand_knowledge_document_scope_path_version" in str(exc.orig):
                raise _revision_conflict() from exc
            raise

    @router.get("/brand-context/knowledge", response_model=KnowledgeTreeWire)
    async def get_knowledge_tree(
        workspace_id: WorkspaceDep,
        brand_id: str | None = Query(default=None, alias="brandId"),
    ) -> KnowledgeTreeWire:
        async with conn_factory() as conn:
            resolved = await resolve_knowledge_brand(
                conn, workspace_id=workspace_id, brand_id=brand_id
            )
            return await read_knowledge_tree(
                conn, workspace_id=workspace_id, brand_id=resolved, storage=storage
            )

    @router.get(
        "/brand-context/knowledge/documents/{document_id}",
        response_model=KnowledgeDocumentDetailWire,
    )
    async def get_knowledge_document(
        workspace_id: WorkspaceDep, document_id: UUID
    ) -> KnowledgeDocumentDetailWire:
        if storage is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "KNOWLEDGE_STORAGE_UNAVAILABLE",
                    "message": "this process has no artifact storage configured",
                },
            )
        async with conn_factory() as conn:
            document = await read_knowledge_document(
                conn, storage, workspace_id=workspace_id, document_id=document_id
            )
        if document is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "code": "KNOWLEDGE_DOCUMENT_NOT_FOUND",
                    "message": "no servable knowledge document with this id in this workspace",
                },
            )
        return document

    @router.get("/brand-context/onboarding/current", response_model=OnboardingStatusWire)
    async def get_onboarding_current(workspace_id: WorkspaceDep) -> OnboardingStatusWire:
        async with conn_factory() as conn:
            return await read_onboarding_status(conn, workspace_id=workspace_id)
