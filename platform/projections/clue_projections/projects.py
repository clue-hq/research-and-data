"""The project directory read (spec 2026-09-19 §2.3): marketing projects of one workspace,
pinned first, then latest activity, keyset paged. ``updated_at`` is the composite
``GREATEST(project.updated_at, MAX(thread.updated_at))`` so the sort reflects conversations
without a write per turn (ruling R10). Read-only and workspace-scoped in SQL."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, cast

from pydantic import AwareDatetime, BaseModel, ConfigDict
from sqlalchemy import text

from clue_db import ConnFactory, transaction
from clue_projections.pagination import InvalidCursorError, decode_cursor, encode_cursor

__all__ = [
    "DEFAULT_PROJECT_DIRECTORY_PAGE_SIZE",
    "MAX_PROJECT_DIRECTORY_PAGE_SIZE",
    "ProjectDirectoryItemView",
    "ProjectDirectoryPage",
    "project_directory_item",
    "project_directory_page",
]

DEFAULT_PROJECT_DIRECTORY_PAGE_SIZE = 50
MAX_PROJECT_DIRECTORY_PAGE_SIZE = 100
DirectoryStatus = Literal["active", "archived"]


class _View(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ProjectDirectoryItemView(_View):
    project_id: str
    title: str
    description: str
    status: DirectoryStatus
    pinned: bool
    brand_id: str
    product_id: str | None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    archived_at: AwareDatetime | None
    chat_count: int
    thread_ids: tuple[str, ...]


class ProjectDirectoryPage(_View):
    items: tuple[ProjectDirectoryItemView, ...]
    next_cursor: str | None = None


_ITEM_SELECT = """
    WITH activity AS (
        SELECT t.project_id,
               MAX(t.updated_at) FILTER (WHERE t.status = 'active') AS last_thread_at,
               COUNT(*)      FILTER (WHERE t.status = 'active')      AS chat_count,
               array_agg(t.id ORDER BY t.updated_at DESC)
                             FILTER (WHERE t.status = 'active')      AS thread_ids
        FROM agent_thread t
        WHERE t.workspace_id = :workspace_id
          -- Only conversations a person started (the rail read applies the same rule).
          AND t.created_by_user_id IS NOT NULL
        GROUP BY t.project_id
    )
    SELECT p.project_id, p.name AS title, p.description, p.status, p.pinned, p.brand_id,
           p.product_id, p.created_at, p.archived_at,
           GREATEST(p.updated_at, COALESCE(a.last_thread_at, p.updated_at)) AS updated_at,
           COALESCE(a.chat_count, 0)                    AS chat_count,
           COALESCE(a.thread_ids, ARRAY[]::text[])      AS thread_ids
    FROM project p
    LEFT JOIN activity a ON a.project_id = p.project_id
    WHERE p.workspace_id = :workspace_id AND p.kind = 'marketing'
"""

_PAGE = text(
    f"""
    SELECT * FROM ({_ITEM_SELECT} AND p.status = :status) ranked
    WHERE CAST(:cursor_pinned AS boolean) IS NULL
       OR (pinned, updated_at, project_id)
          < (CAST(:cursor_pinned AS boolean), CAST(:cursor_updated_at AS timestamptz),
             CAST(:cursor_project_id AS text))
    ORDER BY pinned DESC, updated_at DESC, project_id DESC
    LIMIT :row_limit
    """
)

_ITEM = text(
    f"{_ITEM_SELECT} AND p.project_id = :project_id AND p.status IN ('active', 'archived')"
)


def _item(row: dict[str, object]) -> ProjectDirectoryItemView:
    return ProjectDirectoryItemView(
        project_id=str(row["project_id"]),
        title=str(row["title"]),
        description=str(row["description"]),
        status=cast(DirectoryStatus, str(row["status"])),
        pinned=bool(row["pinned"]),
        brand_id=str(row["brand_id"]),
        product_id=None if row["product_id"] is None else str(row["product_id"]),
        created_at=cast(datetime, row["created_at"]),
        updated_at=cast(datetime, row["updated_at"]),
        archived_at=cast("datetime | None", row["archived_at"]),
        chat_count=int(cast(int, row["chat_count"])),
        thread_ids=tuple(str(t) for t in cast(list[str], row["thread_ids"])),
    )


async def project_directory_page(
    *,
    workspace_id: str,
    status: DirectoryStatus = "active",
    limit: int = DEFAULT_PROJECT_DIRECTORY_PAGE_SIZE,
    cursor: str | None = None,
    conn_factory: ConnFactory = transaction,
) -> ProjectDirectoryPage:
    """One keyset page of the workspace's marketing projects, pinned first then most recent.

    The cursor carries the whole sort key — the pin flag, the composite ``updated_at`` and the
    project id — so a project that is pinned (or whose newest conversation moves) between two
    page reads still pages deterministically instead of repeating or skipping rows.

    Raises :class:`~clue_projections.pagination.InvalidCursorError` for a foreign cursor and
    ``ValueError`` for an out-of-range ``limit``.
    """

    if not 1 <= limit <= MAX_PROJECT_DIRECTORY_PAGE_SIZE:
        raise ValueError(
            f"directory page size must be between 1 and {MAX_PROJECT_DIRECTORY_PAGE_SIZE}"
        )
    cursor_pinned: bool | None = None
    cursor_updated_at: datetime | None = None
    cursor_project_id: str | None = None
    if cursor is not None:
        pinned_part, updated_part, cursor_project_id = decode_cursor(cursor, parts=3)
        if pinned_part not in ("0", "1"):
            raise InvalidCursorError("directory cursor pinned flag must be 0 or 1")
        cursor_pinned = pinned_part == "1"
        try:
            cursor_updated_at = datetime.fromisoformat(updated_part)
        except ValueError as exc:
            raise InvalidCursorError("directory cursor timestamp is not ISO-8601") from exc
    async with conn_factory() as conn:
        rows = (
            (
                await conn.execute(
                    _PAGE,
                    {
                        "workspace_id": workspace_id,
                        "status": status,
                        "cursor_pinned": cursor_pinned,
                        "cursor_updated_at": cursor_updated_at,
                        "cursor_project_id": cursor_project_id,
                        "row_limit": limit + 1,
                    },
                )
            )
            .mappings()
            .all()
        )
    items = tuple(_item(dict(row)) for row in rows[:limit])
    next_cursor = (
        encode_cursor(
            "1" if items[-1].pinned else "0",
            items[-1].updated_at.isoformat(),
            items[-1].project_id,
        )
        if len(rows) > limit and items
        else None
    )
    return ProjectDirectoryPage(items=items, next_cursor=next_cursor)


async def project_directory_item(
    *, workspace_id: str, project_id: str, conn_factory: ConnFactory = transaction
) -> ProjectDirectoryItemView | None:
    """One directory row, or ``None`` when this workspace has no such marketing project.

    A system project, a draft, and another tenant's project are all ``None`` here — the same
    lens the page applies, so a caller cannot reach by id what the listing hides.
    """

    async with conn_factory() as conn:
        row = (
            (await conn.execute(_ITEM, {"workspace_id": workspace_id, "project_id": project_id}))
            .mappings()
            .first()
        )
    return None if row is None else _item(dict(row))
