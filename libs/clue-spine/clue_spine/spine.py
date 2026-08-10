"""The object spine: workspace-owned brands/projects and brand-owned products (Phase A3.2).

Frozen row models + plain async CRUD in the repo's raw-SQL style (the ``icp/spec.py`` pattern).
Deliberately ceremony-free (founder ruling, 2026-07-17): one implementation will ever exist, so
there is no protocol / repository / service layer — just functions over ``AsyncConnection``.

Invalid states are impossible **by schema**, not by handler code, so constraint violations
(a product or project pointing at a brand/product in another workspace; a duplicate product name
under a brand) surface as raw
:class:`sqlalchemy.exc.IntegrityError` — deliberately NOT caught or wrapped here: the DB
constraint IS the enforcement.

Ids are ``text`` (legacy ids slot in unchanged); fresh ones are minted by the ``new_*_id``
factories below (prefixed uuid4 hex, the ``clue_core.new_*_id`` factory pattern over text keys).
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import UtcDatetime, decode_jsonb, serialize_value_json

WorkspaceStatus = Literal["active", "archived"]
ProductStatus = Literal["active", "archived"]
ProjectStatus = Literal["draft", "active", "archived"]


# --- id factories (prefixed uuid4 hex over text PKs) ------------------------
def new_workspace_id() -> str:
    return "ws_" + uuid4().hex


def new_brand_id() -> str:
    return "brd_" + uuid4().hex


def new_product_id() -> str:
    return "prd_" + uuid4().hex


def new_project_id() -> str:
    return "prj_" + uuid4().hex


# --- row models -------------------------------------------------------------
class Workspace(BaseModel):
    """A ``workspace`` row — the tenancy root every subsystem keys on (``workspace_id``)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str
    name: str
    status: WorkspaceStatus = "active"
    created_at: UtcDatetime


class Brand(BaseModel):
    """A workspace-owned brand-kit identity. A workspace may own multiple brands."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    brand_id: str
    workspace_id: str
    name: str
    created_at: UtcDatetime


class Product(BaseModel):
    """A ``product`` row — structurally pinned to a brand in its own workspace (composite FK)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    product_id: str
    brand_id: str
    workspace_id: str
    name: str
    aliases: tuple[str, ...] = ()
    status: ProductStatus = "active"
    created_at: UtcDatetime


class Project(BaseModel):
    """A ``project`` row — the end-to-end ABM motion (§1a vocabulary). ``product_id`` is optional,
    but when set the composite FK pins it to a product in the same workspace."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: str
    workspace_id: str
    brand_id: str
    product_id: str | None = None
    name: str
    status: ProjectStatus = "draft"
    created_at: UtcDatetime


# --- workspace --------------------------------------------------------------
async def create_workspace(
    conn: AsyncConnection, *, name: str, workspace_id: str | None = None
) -> Workspace:
    """Insert a workspace and return it (id minted unless a legacy one is supplied)."""
    result = await conn.execute(
        text(
            "INSERT INTO workspace (workspace_id, name) VALUES (:workspace_id, :name) "
            "RETURNING workspace_id, name, status, created_at"
        ),
        {"workspace_id": workspace_id or new_workspace_id(), "name": name},
    )
    return Workspace(**dict(result.mappings().one()))


async def get_workspace(conn: AsyncConnection, workspace_id: str) -> Workspace | None:
    result = await conn.execute(
        text(
            "SELECT workspace_id, name, status, created_at FROM workspace "
            "WHERE workspace_id = :workspace_id"
        ),
        {"workspace_id": workspace_id},
    )
    row = result.mappings().first()
    return Workspace(**dict(row)) if row is not None else None


# --- brand ------------------------------------------------------------------
async def create_brand(
    conn: AsyncConnection, *, workspace_id: str, name: str, brand_id: str | None = None
) -> Brand:
    """Insert a workspace-owned brand and return it."""
    result = await conn.execute(
        text(
            "INSERT INTO brand (brand_id, workspace_id, name) "
            "VALUES (:brand_id, :workspace_id, :name) "
            "RETURNING brand_id, workspace_id, name, created_at"
        ),
        {"brand_id": brand_id or new_brand_id(), "workspace_id": workspace_id, "name": name},
    )
    return Brand(**dict(result.mappings().one()))


async def get_brand(conn: AsyncConnection, *, workspace_id: str, brand_id: str) -> Brand | None:
    """Return a brand only when it belongs to ``workspace_id``."""
    result = await conn.execute(
        text(
            "SELECT brand_id, workspace_id, name, created_at FROM brand "
            "WHERE brand_id = :brand_id AND workspace_id = :workspace_id"
        ),
        {"brand_id": brand_id, "workspace_id": workspace_id},
    )
    row = result.mappings().first()
    return Brand(**dict(row)) if row is not None else None


async def list_brands_for_workspace(conn: AsyncConnection, workspace_id: str) -> list[Brand]:
    """Return all brands owned by a workspace, deterministically ordered."""
    result = await conn.execute(
        text(
            "SELECT brand_id, workspace_id, name, created_at FROM brand "
            "WHERE workspace_id = :workspace_id ORDER BY name, brand_id"
        ),
        {"workspace_id": workspace_id},
    )
    return [Brand(**dict(row)) for row in result.mappings().all()]


# --- product ----------------------------------------------------------------
_PRODUCT_COLUMNS = "product_id, brand_id, workspace_id, name, aliases, status, created_at"


def _row_to_product(row: dict[str, Any]) -> Product:
    return Product(
        product_id=row["product_id"],
        brand_id=row["brand_id"],
        workspace_id=row["workspace_id"],
        name=row["name"],
        aliases=tuple(decode_jsonb(row["aliases"]) or ()),
        status=row["status"],
        created_at=row["created_at"],
    )


async def create_product(
    conn: AsyncConnection,
    *,
    brand_id: str,
    workspace_id: str,
    name: str,
    aliases: tuple[str, ...] = (),
    product_id: str | None = None,
) -> Product:
    """Insert a product under a brand and return it. The composite FK
    ``(brand_id, workspace_id) → brand`` makes a cross-workspace brand reference impossible
    (IntegrityError); ``product_name_per_brand`` rejects a duplicate name under the brand."""
    result = await conn.execute(
        text(
            "INSERT INTO product (product_id, brand_id, workspace_id, name, aliases) "
            "VALUES (:product_id, :brand_id, :workspace_id, :name, CAST(:aliases AS jsonb)) "
            f"RETURNING {_PRODUCT_COLUMNS}"
        ),
        {
            "product_id": product_id or new_product_id(),
            "brand_id": brand_id,
            "workspace_id": workspace_id,
            "name": name,
            "aliases": serialize_value_json(list(aliases)),
        },
    )
    return _row_to_product(dict(result.mappings().one()))


async def get_product(conn: AsyncConnection, product_id: str) -> Product | None:
    result = await conn.execute(
        text(f"SELECT {_PRODUCT_COLUMNS} FROM product WHERE product_id = :product_id"),
        {"product_id": product_id},
    )
    row = result.mappings().first()
    return _row_to_product(dict(row)) if row is not None else None


async def list_products(conn: AsyncConnection, brand_id: str) -> list[Product]:
    """All products under a brand (the natural key: products live under a brand;
    ``product_name_per_brand`` is keyed the same way), name-ordered."""
    result = await conn.execute(
        text(f"SELECT {_PRODUCT_COLUMNS} FROM product WHERE brand_id = :brand_id ORDER BY name"),
        {"brand_id": brand_id},
    )
    return [_row_to_product(dict(row)) for row in result.mappings().all()]


# --- project ----------------------------------------------------------------
_PROJECT_COLUMNS = "project_id, workspace_id, brand_id, product_id, name, status, created_at"


async def create_project(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    brand_id: str,
    name: str,
    product_id: str | None = None,
    project_id: str | None = None,
    status: ProjectStatus = "draft",
) -> Project:
    """Insert a project and return it. Composite FKs pin ``brand_id`` — and ``product_id`` when
    set — to the project's own workspace (a cross-workspace reference is an IntegrityError)."""
    result = await conn.execute(
        text(
            "INSERT INTO project (project_id, workspace_id, brand_id, product_id, name, status) "
            "VALUES (:project_id, :workspace_id, :brand_id, :product_id, :name, :status) "
            f"RETURNING {_PROJECT_COLUMNS}"
        ),
        {
            "project_id": project_id or new_project_id(),
            "workspace_id": workspace_id,
            "brand_id": brand_id,
            "product_id": product_id,
            "name": name,
            "status": status,
        },
    )
    return Project(**dict(result.mappings().one()))


async def get_project(conn: AsyncConnection, project_id: str) -> Project | None:
    result = await conn.execute(
        text(f"SELECT {_PROJECT_COLUMNS} FROM project WHERE project_id = :project_id"),
        {"project_id": project_id},
    )
    row = result.mappings().first()
    return Project(**dict(row)) if row is not None else None


async def get_project_for_workspace(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
) -> Project | None:
    """Return one project only when it belongs to ``workspace_id``.

    Client-facing reads use this form so a foreign and an unknown project have
    the same scoped miss at the SQL boundary rather than loading a foreign row
    and filtering it after the fact.
    """

    result = await conn.execute(
        text(
            f"SELECT {_PROJECT_COLUMNS} FROM project "
            "WHERE workspace_id = :workspace_id AND project_id = :project_id"
        ),
        {"workspace_id": workspace_id, "project_id": project_id},
    )
    row = result.mappings().first()
    return Project(**dict(row)) if row is not None else None


async def confirm_project_product(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
    product_id: str,
) -> Project | None:
    """Human-authorized project/product confirmation.

    Returns ``None`` without revealing which coordinate was foreign when the project and product
    are not in the same workspace and brand. Repeating the same confirmation is idempotent. A
    project already pinned to a different product is not silently repointed.
    """
    result = await conn.execute(
        text(
            """
            UPDATE project
            SET product_id = product.product_id
            FROM product
            WHERE project.project_id = :project_id
              AND project.workspace_id = :workspace_id
              AND project.brand_id = product.brand_id
              AND project.workspace_id = product.workspace_id
              AND product.product_id = :product_id
              AND (project.product_id IS NULL OR project.product_id = product.product_id)
            RETURNING project.project_id, project.workspace_id, project.brand_id,
                      project.product_id, project.name, project.status, project.created_at
            """
        ),
        {
            "workspace_id": workspace_id,
            "project_id": project_id,
            "product_id": product_id,
        },
    )
    row = result.mappings().one_or_none()
    return Project(**dict(row)) if row is not None else None


async def list_projects(
    conn: AsyncConnection, workspace_id: str, *, status: ProjectStatus | None = None
) -> list[Project]:
    """All projects in a workspace (optionally filtered by status), newest first."""
    params: dict[str, Any] = {"workspace_id": workspace_id}
    where = "workspace_id = :workspace_id"
    if status is not None:
        where += " AND status = :status"
        params["status"] = status
    result = await conn.execute(
        text(
            f"SELECT {_PROJECT_COLUMNS} FROM project WHERE {where} "
            "ORDER BY created_at DESC, project_id"
        ),
        params,
    )
    return [Project(**dict(row)) for row in result.mappings().all()]
