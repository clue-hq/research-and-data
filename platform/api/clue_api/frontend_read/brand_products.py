"""Brand-context product routes (spec 2026-10-15 product management §10).

The Product folder's actions — add, rename, merge, remove and undo — over
:mod:`clue_api.product_management`, which does the work in one transaction. A person's add or merge
leaves the product page pending; the route offers the background writer once its transaction has
committed (rows first, offer second — the fleet rule).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.auth_wiring import principal_from_request
from clue_api.frontend_read.accounts_list import WireModel
from clue_api.frontend_read.app import WorkspaceDep
from clue_api.frontend_read.brand_knowledge import resolve_knowledge_brand
from clue_api.product_management import (
    ProductActor,
    ProductChangeRefused,
    ProductChangeResult,
    add_product,
    list_brand_products,
    merge_products_action,
    recent_product_changes,
    remove_product_action,
    rename_product_action,
    undo_product_change,
)
from clue_api.product_page_writer import offer_product_page
from clue_db import ConnFactory
from clue_fleet import WorkQueue
from clue_storage import StorageBackend

__all__ = ["register_brand_product_routes"]

LOCAL_USER_ID = "local-development-user"
#: How far back the Product folder's "Recent changes" list reaches.
RECENT_CHANGES_WINDOW = timedelta(days=30)

_STATUS = {
    "product_not_found": 404,
    "change_not_found": 404,
    "product_not_active": 409,
    "product_name_taken": 409,
    "change_not_undoable": 409,
    "name_invalid": 422,
    "merge_invalid": 422,
}


class BrandProductWire(WireModel):
    product_id: str
    name: str
    aliases: list[str]
    page_document_id: str | None
    page_path: str | None
    page_pending: bool


class ProductChangeLineWire(WireModel):
    change_id: str
    kind: str
    text: str
    created_at: str
    undoable: bool


class BrandProductsWire(WireModel):
    brand_id: str | None
    products: list[BrandProductWire]
    recent_changes: list[ProductChangeLineWire]


class ProductChangeWire(WireModel):
    change_id: str
    kind: str
    text: str
    product_id: str
    product_name: str
    page_document_id: str | None
    page_pending: bool
    #: Where the product's page lives now — the editor opens it there after a rename.
    page_path: str | None
    projects_updated: int
    projects_needing_choice: int


class AddProductBody(WireModel):
    name: str = Field(max_length=240)
    description: str | None = Field(default=None, max_length=2_000)


class RenameProductBody(WireModel):
    name: str = Field(max_length=240)


class MergeProductsBody(WireModel):
    product_ids: list[str] = Field(min_length=1, max_length=200)
    into_product_id: str | None = None
    new_name: str | None = Field(default=None, max_length=240)


#: One action over (connection, storage, resolved brand, actor).
_Perform = Callable[
    [AsyncConnection, StorageBackend, str, ProductActor], Awaitable[ProductChangeResult]
]


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _change_wire(result: ProductChangeResult) -> ProductChangeWire:
    return ProductChangeWire(
        change_id=str(result.change_id),
        kind=result.kind,
        text=result.text,
        product_id=result.product.product_id,
        product_name=result.product.name,
        page_document_id=str(result.page_document_id) if result.page_document_id else None,
        page_pending=result.page_pending,
        page_path=result.page_path,
        projects_updated=sum(p.outcome in ("updated", "restored") for p in result.projects),
        projects_needing_choice=sum(p.outcome == "needs_choice" for p in result.projects),
    )


def _refused(error: ProductChangeRefused) -> HTTPException:
    return HTTPException(
        status_code=_STATUS.get(error.code, 409),
        detail={"code": error.code.upper(), "message": str(error)},
    )


def register_brand_product_routes(
    router: APIRouter,
    *,
    conn_factory: ConnFactory,
    storage: StorageBackend | None,
    work_queue: WorkQueue | None = None,
    allow_local_mutations: bool = False,
) -> None:
    def require_storage() -> StorageBackend:
        if storage is None:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "KNOWLEDGE_STORAGE_UNAVAILABLE",
                    "message": "Document storage is unavailable.",
                },
            )
        return storage

    def writer(request: Request) -> str:
        principal = principal_from_request(request)
        if principal is not None:
            principal.require("project.write")
            return principal.user_id
        if allow_local_mutations:
            return LOCAL_USER_ID
        raise HTTPException(
            status_code=401,
            detail={"code": "UNAUTHORIZED", "message": "An authenticated session is required."},
        )

    async def brand_of(conn: AsyncConnection, workspace_id: str, brand_id: str | None) -> str:
        resolved = await resolve_knowledge_brand(conn, workspace_id=workspace_id, brand_id=brand_id)
        if resolved is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "BRAND_NOT_FOUND", "message": "This workspace has no brand."},
            )
        return resolved

    async def ensure_local_user(conn: AsyncConnection, user_id: str) -> None:
        # The change log names a real person; the local-header development mode has no session, so
        # its stand-in user is created on first use (never in an authenticated deployment).
        if user_id == LOCAL_USER_ID and allow_local_mutations:
            await conn.execute(
                text(
                    "INSERT INTO platform_user (user_id, display_name) VALUES (:id, 'Local') "
                    "ON CONFLICT (user_id) DO NOTHING"
                ),
                {"id": user_id},
            )

    async def act(
        request: Request, workspace_id: str, brand_id: str | None, perform: _Perform
    ) -> ProductChangeWire:
        user_id = writer(request)
        backend = require_storage()
        try:
            async with conn_factory() as conn:
                await ensure_local_user(conn, user_id)
                brand = await brand_of(conn, workspace_id, brand_id)
                result = await perform(conn, backend, brand, ProductActor(user_id))
        except ProductChangeRefused as error:
            raise _refused(error) from error
        # Committed: now the background page writer may see the pending row.
        await offer_product_page(
            work_queue,
            result=result,
            workspace_id=workspace_id,
            brand_id=brand,
            actor_user_id=user_id,
        )
        return _change_wire(result)

    @router.get("/brand-context/products", response_model=BrandProductsWire)
    async def get_products(
        workspace_id: WorkspaceDep,
        brand_id: str | None = Query(default=None, alias="brandId"),
    ) -> BrandProductsWire:
        backend = require_storage()
        async with conn_factory() as conn:
            resolved = await resolve_knowledge_brand(
                conn, workspace_id=workspace_id, brand_id=brand_id
            )
            if resolved is None:
                return BrandProductsWire(brand_id=None, products=[], recent_changes=[])
            products = await list_brand_products(
                conn, backend, workspace_id=workspace_id, brand_id=resolved
            )
            changes = await recent_product_changes(
                conn,
                workspace_id=workspace_id,
                brand_id=resolved,
                since=datetime.now(UTC) - RECENT_CHANGES_WINDOW,
            )
        return BrandProductsWire(
            brand_id=resolved,
            products=[
                BrandProductWire(
                    product_id=p.product_id,
                    name=p.name,
                    aliases=list(p.aliases),
                    page_document_id=str(p.page_document_id) if p.page_document_id else None,
                    page_path=p.page_path,
                    page_pending=p.page_pending,
                )
                for p in products
            ],
            recent_changes=[
                ProductChangeLineWire(
                    change_id=str(c.change_id),
                    kind=c.kind,
                    text=c.text,
                    created_at=_iso(c.created_at),
                    undoable=c.undoable,
                )
                for c in changes
            ],
        )

    @router.post("/brand-context/products", response_model=ProductChangeWire)
    async def post_product(
        request: Request,
        workspace_id: WorkspaceDep,
        body: AddProductBody,
        brand_id: str | None = Query(default=None, alias="brandId"),
    ) -> ProductChangeWire:
        return await act(
            request,
            workspace_id,
            brand_id,
            lambda conn, backend, brand, actor: add_product(
                conn,
                backend,
                workspace_id=workspace_id,
                brand_id=brand,
                actor=actor,
                name=body.name,
                description=body.description,
            ),
        )

    @router.post("/brand-context/products/merge", response_model=ProductChangeWire)
    async def post_merge(
        request: Request,
        workspace_id: WorkspaceDep,
        body: MergeProductsBody,
        brand_id: str | None = Query(default=None, alias="brandId"),
    ) -> ProductChangeWire:
        return await act(
            request,
            workspace_id,
            brand_id,
            lambda conn, backend, brand, actor: merge_products_action(
                conn,
                backend,
                workspace_id=workspace_id,
                brand_id=brand,
                actor=actor,
                product_ids=body.product_ids,
                into_product_id=body.into_product_id,
                new_name=body.new_name,
            ),
        )

    @router.post("/brand-context/products/{product_id}/rename", response_model=ProductChangeWire)
    async def post_rename(
        request: Request,
        workspace_id: WorkspaceDep,
        product_id: str,
        body: RenameProductBody,
        brand_id: str | None = Query(default=None, alias="brandId"),
    ) -> ProductChangeWire:
        return await act(
            request,
            workspace_id,
            brand_id,
            lambda conn, backend, brand, actor: rename_product_action(
                conn,
                backend,
                workspace_id=workspace_id,
                brand_id=brand,
                actor=actor,
                product_id=product_id,
                name=body.name,
            ),
        )

    @router.post("/brand-context/products/{product_id}/remove", response_model=ProductChangeWire)
    async def post_remove(
        request: Request,
        workspace_id: WorkspaceDep,
        product_id: str,
        brand_id: str | None = Query(default=None, alias="brandId"),
    ) -> ProductChangeWire:
        return await act(
            request,
            workspace_id,
            brand_id,
            lambda conn, backend, brand, actor: remove_product_action(
                conn,
                backend,
                workspace_id=workspace_id,
                brand_id=brand,
                actor=actor,
                product_id=product_id,
            ),
        )

    @router.post(
        "/brand-context/product-changes/{change_id}/undo", response_model=ProductChangeWire
    )
    async def post_undo(
        request: Request,
        workspace_id: WorkspaceDep,
        change_id: UUID,
        brand_id: str | None = Query(default=None, alias="brandId"),
    ) -> ProductChangeWire:
        return await act(
            request,
            workspace_id,
            brand_id,
            lambda conn, backend, brand, actor: undo_product_change(
                conn,
                backend,
                workspace_id=workspace_id,
                brand_id=brand,
                actor=actor,
                change_id=change_id,
            ),
        )
