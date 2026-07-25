"""Shared setup helpers for the standalone module scripts."""

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_spine import create_workspace, get_workspace


async def ensure_script_workspace(conn: AsyncConnection, workspace_id: str) -> None:
    """Ensure a named demo workspace exists before workspace-local research writes."""
    if await get_workspace(conn, workspace_id) is None:
        await create_workspace(conn, workspace_id=workspace_id, name=workspace_id)


__all__ = ["ensure_script_workspace"]
