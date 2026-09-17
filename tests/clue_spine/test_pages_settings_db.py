from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from clue_spine import create_workspace
from clue_spine.pages_settings import UNSET, get_pages_settings, update_pages_settings

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_spine_db")


def test_defaults_then_partial_updates_then_clear() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = await create_workspace(
                conn, name="Pages " + uuid4().hex[:4], pages_system_suffix="pages.test"
            )
            initial = await get_pages_settings(conn, ws.workspace_id)
            assert initial.fallback_url is None and initial.updated_at is None
            first = await update_pages_settings(
                conn,
                workspace_id=ws.workspace_id,
                fallback_url="https://www.acme.com",
                page_title="Acme",
            )
            assert first.fallback_url == "https://www.acme.com" and first.page_title == "Acme"
            assert first.page_description is None and first.updated_at is not None
            second = await update_pages_settings(
                conn, workspace_id=ws.workspace_id, page_description="Hello"
            )
            assert second.fallback_url == "https://www.acme.com"  # untouched
            assert second.page_description == "Hello"
            cleared = await update_pages_settings(
                conn, workspace_id=ws.workspace_id, fallback_url=None
            )
            assert cleared.fallback_url is None and cleared.page_title == "Acme"
            assert (await get_pages_settings(conn, ws.workspace_id)) == cleared
            assert UNSET is not None
            with pytest.raises(IntegrityError):
                async with conn.begin_nested():
                    await update_pages_settings(
                        conn, workspace_id=ws.workspace_id, fallback_url="http://insecure.example"
                    )

    run_async(scenario())
