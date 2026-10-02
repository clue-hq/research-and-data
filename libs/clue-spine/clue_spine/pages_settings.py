"""``workspace_pages_settings`` — one row of page defaults per workspace.

Custom-domain publishing (design 2026-09-17 §4.2). A missing row means all defaults. Updates are
partial: a field left ``UNSET`` is untouched, ``None`` clears it. Readers: the Settings → Pages
screen (platform API), the page origin (fallback URL, favicon — live), and the design API's publish
(description + social-preview defaults, at publish time).
"""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import UtcDatetime


class Unset:
    """The "leave it alone" marker for partial updates."""

    def __repr__(self) -> str:
        return "UNSET"


UNSET: Final = Unset()

_COLUMNS = (
    "fallback_url",
    "page_title",
    "page_description",
    "favicon_sha256",
    "social_preview_sha256",
)


class PagesSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    workspace_id: str
    fallback_url: str | None = None
    page_title: str | None = None
    page_description: str | None = None
    favicon_sha256: str | None = None
    social_preview_sha256: str | None = None
    updated_at: UtcDatetime | None = None


async def get_pages_settings(conn: AsyncConnection, workspace_id: str) -> PagesSettings:
    result = await conn.execute(
        text(
            "SELECT workspace_id, fallback_url, page_title, page_description, favicon_sha256, "
            "social_preview_sha256, updated_at FROM workspace_pages_settings "
            "WHERE workspace_id = :w"
        ),
        {"w": workspace_id},
    )
    row = result.mappings().first()
    return (
        PagesSettings(**dict(row)) if row is not None else PagesSettings(workspace_id=workspace_id)
    )


async def update_pages_settings(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    fallback_url: str | None | Unset = UNSET,
    page_title: str | None | Unset = UNSET,
    page_description: str | None | Unset = UNSET,
    favicon_sha256: str | None | Unset = UNSET,
    social_preview_sha256: str | None | Unset = UNSET,
) -> PagesSettings:
    provided = {
        name: value
        for name, value in zip(
            _COLUMNS,
            (fallback_url, page_title, page_description, favicon_sha256, social_preview_sha256),
            strict=True,
        )
        if not isinstance(value, Unset)
    }
    if not provided:
        return await get_pages_settings(conn, workspace_id)
    columns = ", ".join(provided)
    placeholders = ", ".join(f":{name}" for name in provided)
    assignments = ", ".join(f"{name} = EXCLUDED.{name}" for name in provided)
    result = await conn.execute(
        text(
            f"INSERT INTO workspace_pages_settings (workspace_id, {columns}) "
            f"VALUES (:w, {placeholders}) "
            f"ON CONFLICT (workspace_id) DO UPDATE SET {assignments}, updated_at = now() "
            "RETURNING workspace_id, fallback_url, page_title, page_description, favicon_sha256, "
            "social_preview_sha256, updated_at"
        ),
        {"w": workspace_id, **provided},
    )
    return PagesSettings(**dict(result.mappings().one()))
