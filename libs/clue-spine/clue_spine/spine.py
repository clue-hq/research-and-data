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

import unicodedata
from collections.abc import Sequence
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import UtcDatetime, decode_jsonb, serialize_value_json
from clue_spine.hostnames import DEFAULT_PAGES_SYSTEM_SUFFIX, ensure_system_hostname

WorkspaceStatus = Literal["active", "archived"]
ProductStatus = Literal["active", "archived"]
ProjectStatus = Literal["draft", "active", "archived"]
ProjectKind = Literal["marketing", "system"]


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
    description: str = ""
    pinned: bool = False
    kind: ProjectKind = "marketing"
    updated_at: UtcDatetime
    archived_at: UtcDatetime | None = None


# --- workspace --------------------------------------------------------------
async def create_workspace(
    conn: AsyncConnection,
    *,
    name: str,
    workspace_id: str | None = None,
    pages_system_suffix: str = DEFAULT_PAGES_SYSTEM_SUFFIX,
) -> Workspace:
    """Insert a workspace and return it (id minted unless a legacy one is supplied).

    Also allocates the workspace's permanent system hostname (``<label>.<pages_system_suffix>``) in
    the SAME transaction (custom-domain publishing §4.1), so every creator — owner provisioning,
    self-serve provisioning, scripts, tests — gets one without knowing about it. Composition roots
    pass ``settings.pages_system_suffix``; the default is the production suffix.
    """
    result = await conn.execute(
        text(
            "INSERT INTO workspace (workspace_id, name) VALUES (:workspace_id, :name) "
            "RETURNING workspace_id, name, status, created_at"
        ),
        {"workspace_id": workspace_id or new_workspace_id(), "name": name},
    )
    workspace = Workspace(**dict(result.mappings().one()))
    await ensure_system_hostname(
        conn, workspace_id=workspace.workspace_id, name=name, suffix=pages_system_suffix
    )
    return workspace


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


async def rename_workspace(conn: AsyncConnection, workspace_id: str, name: str) -> Workspace | None:
    """Rename only the workspace; brands retain their independent names."""
    cleaned = name.strip()
    if not cleaned or len(cleaned) > 200:
        raise ValueError("workspace name must contain 1 to 200 characters")
    result = await conn.execute(
        text(
            "UPDATE workspace SET name = :name WHERE workspace_id = :workspace_id "
            "RETURNING workspace_id, name, status, created_at"
        ),
        {"workspace_id": workspace_id, "name": cleaned},
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


#: Trademark/service-mark/copyright marks a company decorates its own product names with. They are
#: stripped BEFORE NFKC, which would otherwise expand ``™`` into the letters ``tm`` and make
#: ``Aura™`` fold to ``auratm`` — a different identity from ``Aura``.
_MARK_TABLE = str.maketrans("", "", "™®©℠")


def _alias_fold(value: str) -> str:
    """A comparison key for a product spelling: mark-free, case-free, spacing- and punctuation-free.

    Deliberately mirrors the onboarding lane's ``normalize_identity`` (it cannot be imported: that
    lives in ``clue_api``, which sits ABOVE the spine). Whitespace and punctuation are not identity
    — "Front Desk" and "FrontDesk" are one spelling — so the alphanumerics are joined with nothing.
    """
    folded = unicodedata.normalize("NFKC", value.translate(_MARK_TABLE)).casefold()
    return "".join(ch for ch in folded if ch.isalnum())


async def add_product_aliases(
    conn: AsyncConnection, *, product_id: str, workspace_id: str, aliases: Sequence[str]
) -> Product:
    """Append observed spellings to a product's aliases and return the refreshed row.

    Never renames, never reorders, never drops an alias: the only edit is an append. A spelling is
    added only when its folded form matches neither the name nor an alias already recorded (marks,
    case, spacing and punctuation ignored) — an alias that folds onto the name buys no new match
    and would only grow the row. Raises :class:`ValueError` when the product is not in this
    workspace, so a caller can never write across the tenancy boundary.
    """
    product = await get_product(conn, product_id)
    if product is None or product.workspace_id != workspace_id:
        raise ValueError("product is not in this workspace")
    seen = {_alias_fold(product.name)} | {_alias_fold(a) for a in product.aliases}
    merged = list(product.aliases)
    for alias in aliases:
        folded = _alias_fold(alias)
        if alias.strip() and folded and folded not in seen:
            merged.append(alias.strip())
            seen.add(folded)
    if merged != list(product.aliases):
        await conn.execute(
            text(
                "UPDATE product SET aliases = CAST(:aliases AS jsonb) "
                "WHERE product_id = :id AND workspace_id = :ws"
            ),
            {"aliases": serialize_value_json(merged), "id": product_id, "ws": workspace_id},
        )
    refreshed = await get_product(conn, product_id)
    assert refreshed is not None  # it was read a moment ago in this same transaction
    return refreshed


async def list_products(conn: AsyncConnection, brand_id: str) -> list[Product]:
    """All products under a brand (the natural key: products live under a brand;
    ``product_name_per_brand`` is keyed the same way), name-ordered."""
    result = await conn.execute(
        text(f"SELECT {_PRODUCT_COLUMNS} FROM product WHERE brand_id = :brand_id ORDER BY name"),
        {"brand_id": brand_id},
    )
    return [_row_to_product(dict(row)) for row in result.mappings().all()]


# --- project ----------------------------------------------------------------
_PROJECT_COLUMNS = (
    "project_id, workspace_id, brand_id, product_id, name, status, created_at, "
    "description, pinned, kind, updated_at, archived_at"
)

#: The name a Home-created project is born with until the conversation namer replaces it (spec
#: 2026-09-18-conversation-naming-design §4.5). One constant: the router births it, the namer's
#: conditional rename matches on it, and the frontend's bootstrap schema pins the same literal.
UNTITLED_PROJECT_NAME = "Untitled project"


async def create_project(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    brand_id: str,
    name: str,
    product_id: str | None = None,
    project_id: str | None = None,
    status: ProjectStatus = "draft",
    description: str = "",
    kind: ProjectKind = "marketing",
) -> Project:
    """Insert a project and return it. Composite FKs pin ``brand_id`` — and ``product_id`` when
    set — to the project's own workspace (a cross-workspace reference is an IntegrityError).

    ``archived_at`` is born from ``status`` so ``project_archived_at_iff`` holds for every row,
    including the system scope anchors that are born archived.
    """
    result = await conn.execute(
        text(
            "INSERT INTO project (project_id, workspace_id, brand_id, product_id, name, status, "
            "description, kind, archived_at) VALUES (:project_id, :workspace_id, :brand_id, "
            ":product_id, :name, :status, :description, :kind, "
            "CASE WHEN :status = 'archived' THEN now() ELSE NULL END) "
            f"RETURNING {_PROJECT_COLUMNS}"
        ),
        {
            "project_id": project_id or new_project_id(),
            "workspace_id": workspace_id,
            "brand_id": brand_id,
            "product_id": product_id,
            "name": name,
            "status": status,
            "description": description,
            "kind": kind,
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


async def set_project_name(
    conn: AsyncConnection, *, workspace_id: str, project_id: str, name: str
) -> Project | None:
    """Rename only the project owned by this workspace; preserve its identity and contents."""
    result = await conn.execute(
        text(
            "UPDATE project SET name = :name, updated_at = clock_timestamp() "
            "WHERE workspace_id = :workspace_id AND project_id = :project_id "
            f"RETURNING {_PROJECT_COLUMNS}"
        ),
        {"workspace_id": workspace_id, "project_id": project_id, "name": name},
    )
    row = result.mappings().first()
    return Project(**dict(row)) if row is not None else None


async def set_project_name_if_untitled(
    conn: AsyncConnection, *, workspace_id: str, project_id: str, name: str
) -> Project | None:
    """Replace the untitled placeholder with a generated name — and only the placeholder.

    The ``name = UNTITLED_PROJECT_NAME`` predicate is the whole manual-wins rule: a human rename
    that landed first turns this into a zero-row no-op, which the caller reads as ``None``.
    """
    result = await conn.execute(
        text(
            "UPDATE project SET name = :name "
            "WHERE workspace_id = :workspace_id AND project_id = :project_id "
            "AND name = :placeholder "
            f"RETURNING {_PROJECT_COLUMNS}"
        ),
        {
            "workspace_id": workspace_id,
            "project_id": project_id,
            "name": name,
            "placeholder": UNTITLED_PROJECT_NAME,
        },
    )
    row = result.mappings().first()
    return Project(**dict(row)) if row is not None else None


async def update_project_details(
    conn: AsyncConnection, *, workspace_id: str, project_id: str, name: str, description: str
) -> Project | None:
    """Title and objective together; bumps ``updated_at`` (spec R10)."""
    result = await conn.execute(
        text(
            "UPDATE project SET name = :name, description = :description, "
            "updated_at = clock_timestamp() "
            "WHERE workspace_id = :workspace_id AND project_id = :project_id "
            f"RETURNING {_PROJECT_COLUMNS}"
        ),
        {
            "workspace_id": workspace_id,
            "project_id": project_id,
            "name": name,
            "description": description,
        },
    )
    row = result.mappings().first()
    return Project(**dict(row)) if row is not None else None


async def set_project_pinned(
    conn: AsyncConnection, *, workspace_id: str, project_id: str, pinned: bool
) -> Project | None:
    """Workspace-wide pin. Deliberately does NOT bump ``updated_at`` (the dummy's rule)."""
    result = await conn.execute(
        text(
            "UPDATE project SET pinned = :pinned "
            "WHERE workspace_id = :workspace_id AND project_id = :project_id "
            f"RETURNING {_PROJECT_COLUMNS}"
        ),
        {"workspace_id": workspace_id, "project_id": project_id, "pinned": pinned},
    )
    row = result.mappings().first()
    return Project(**dict(row)) if row is not None else None


async def set_project_archived(
    conn: AsyncConnection, *, workspace_id: str, project_id: str, archived: bool
) -> Project | None:
    """Flip ``active`` ↔ ``archived``. A ``draft`` row is left alone (``None``)."""
    result = await conn.execute(
        text(
            "UPDATE project SET "
            "status = CASE WHEN :archived THEN 'archived' ELSE 'active' END, "
            "archived_at = CASE WHEN :archived THEN clock_timestamp() ELSE NULL END, "
            "updated_at = clock_timestamp() "
            "WHERE workspace_id = :workspace_id AND project_id = :project_id "
            "AND status IN ('active', 'archived') "
            f"RETURNING {_PROJECT_COLUMNS}"
        ),
        {"workspace_id": workspace_id, "project_id": project_id, "archived": archived},
    )
    row = result.mappings().first()
    return Project(**dict(row)) if row is not None else None


async def touch_project(conn: AsyncConnection, *, workspace_id: str, project_id: str) -> None:
    """The ``updated_at`` bump the instructions and memory routes call after their own write."""
    await conn.execute(
        text(
            "UPDATE project SET updated_at = clock_timestamp() "
            "WHERE workspace_id = :workspace_id AND project_id = :project_id"
        ),
        {"workspace_id": workspace_id, "project_id": project_id},
    )


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


# --- project product set (ARV2-PRODUCT-CATALOG-CONTRACT.md §6.2) -----------
_PROJECT_PRODUCT_COLUMNS = (
    "workspace_id, project_id, brand_id, product_id, selection_version, gate_id, "
    "confirmed_by_user_id, confirmed_at, confirmation_turn_id"
)


class ProjectProductSet(BaseModel):
    """One confirmed version of a project's product set. Rows are append-only; the current set is
    the highest ``selection_version``; a run pins the version it started under (ruling P2)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str
    project_id: str
    brand_id: str
    selection_version: int
    product_ids: tuple[str, ...]
    gate_id: UUID | None
    confirmation_turn_id: UUID | None = None
    confirmed_by_user_id: str
    confirmed_at: UtcDatetime


def _rows_to_sets(rows: list[dict[str, Any]]) -> list[ProjectProductSet]:
    """Group version rows (already ordered by version, then insertion) into sets."""
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(int(row["selection_version"]), []).append(row)
    sets: list[ProjectProductSet] = []
    for version, members in sorted(grouped.items()):
        head = members[0]
        sets.append(
            ProjectProductSet(
                workspace_id=head["workspace_id"],
                project_id=head["project_id"],
                brand_id=head["brand_id"],
                selection_version=version,
                product_ids=tuple(m["product_id"] for m in members),
                gate_id=head["gate_id"],
                confirmation_turn_id=head["confirmation_turn_id"],
                confirmed_by_user_id=head["confirmed_by_user_id"],
                confirmed_at=head["confirmed_at"],
            )
        )
    return sets


async def list_project_product_sets(
    conn: AsyncConnection, *, workspace_id: str, project_id: str
) -> list[ProjectProductSet]:
    """Every confirmed version of the project's product set, oldest first; members keep the
    order the human chose them in (``ctid`` reflects insertion order within one version)."""
    result = await conn.execute(
        text(
            f"SELECT {_PROJECT_PRODUCT_COLUMNS} FROM project_product "
            "WHERE workspace_id = :workspace_id AND project_id = :project_id "
            "ORDER BY selection_version, ctid"
        ),
        {"workspace_id": workspace_id, "project_id": project_id},
    )
    return _rows_to_sets([dict(row) for row in result.mappings().all()])


async def current_project_product_set(
    conn: AsyncConnection, *, workspace_id: str, project_id: str
) -> ProjectProductSet | None:
    sets = await list_project_product_sets(conn, workspace_id=workspace_id, project_id=project_id)
    return sets[-1] if sets else None


async def confirm_project_product_set(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
    product_ids: Sequence[str],
    gate_id: UUID | None,
    confirmed_by_user_id: str,
    confirmation_turn_id: UUID | None = None,
) -> ProjectProductSet | None:
    """Confirm the whole set, recording either a human gate or an automatic turn.

    Returns ``None`` — without revealing which coordinate was foreign — when the project is absent
    from the workspace or any product is not a product of the project's own brand and workspace.
    Repeats in ``product_ids`` collapse, first occurrence wins. Raises ``ValueError`` on an empty
    list: an empty set is not a selection.
    """
    if (gate_id is None) == (confirmation_turn_id is None):
        raise ValueError("confirmation requires exactly one gate or automatic turn")
    ordered = list(dict.fromkeys(product_ids))
    if not ordered:
        raise ValueError("a project product set needs at least one product")
    locked = (
        (
            await conn.execute(
                text(
                    "SELECT brand_id FROM project "
                    "WHERE project_id = :project_id AND workspace_id = :workspace_id FOR UPDATE"
                ),
                {"project_id": project_id, "workspace_id": workspace_id},
            )
        )
        .mappings()
        .first()
    )
    if locked is None:
        return None
    brand_id = str(locked["brand_id"])
    known = (
        (
            await conn.execute(
                text(
                    "SELECT product_id FROM product WHERE product_id = ANY(:ids) "
                    "AND brand_id = :brand_id AND workspace_id = :workspace_id"
                ),
                {"ids": ordered, "brand_id": brand_id, "workspace_id": workspace_id},
            )
        )
        .scalars()
        .all()
    )
    if set(known) != set(ordered):
        return None
    next_version = (
        await conn.execute(
            text(
                "SELECT COALESCE(MAX(selection_version), 0) + 1 FROM project_product "
                "WHERE project_id = :project_id"
            ),
            {"project_id": project_id},
        )
    ).scalar_one()
    for product_id in ordered:
        await conn.execute(
            text(
                "INSERT INTO project_product (workspace_id, project_id, brand_id, product_id, "
                " selection_version, gate_id, confirmed_by_user_id, confirmation_turn_id) "
                "VALUES (:workspace_id, :project_id, :brand_id, :product_id, :version, :gate_id, "
                " :user_id, :confirmation_turn_id)"
            ),
            {
                "workspace_id": workspace_id,
                "project_id": project_id,
                "brand_id": brand_id,
                "product_id": product_id,
                "version": int(next_version),
                "gate_id": gate_id,
                "confirmation_turn_id": confirmation_turn_id,
                "user_id": confirmed_by_user_id,
            },
        )
    sets = await list_project_product_sets(conn, workspace_id=workspace_id, project_id=project_id)
    return sets[-1]


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
