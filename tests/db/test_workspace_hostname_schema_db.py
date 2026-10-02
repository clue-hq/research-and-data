"""Custom-domain publishing S1 Task 2: the hostname registry's invariants live in the schema."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

# ``migrated_db``/``require_spine_db`` live in ``tests/clue_spine/conftest.py``, which pytest
# does not apply to this package; importing them here registers them for this module.
from tests.clue_spine.conftest import (  # noqa: F401
    migrated_db,
    require_spine_db,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_spine_db")

_SYSTEM = (
    "INSERT INTO workspace_hostname (hostname, workspace_id, kind, status) "
    "VALUES (:h, :w, 'system', 'active')"
)
_CUSTOM = (
    "INSERT INTO workspace_hostname (hostname, workspace_id, kind, status, cname_target, "
    "ownership_txt_name, ownership_txt_value) VALUES (:h, :w, 'custom', 'pending_dns', "
    "'pages.cluehq.ai', '_cf-custom-hostname.' || :h, 'token')"
)


async def _workspace(conn) -> str:
    workspace_id = "ws_" + uuid4().hex
    await conn.execute(
        text("INSERT INTO workspace (workspace_id, name) VALUES (:w, :w)"), {"w": workspace_id}
    )
    return workspace_id


def test_one_system_and_one_custom_row_per_workspace() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = await _workspace(conn)
            await conn.execute(text(_SYSTEM), {"h": f"{uuid4().hex[:8]}.pages.cluehq.ai", "w": ws})
            with pytest.raises(IntegrityError):
                async with conn.begin_nested():
                    await conn.execute(
                        text(_SYSTEM), {"h": f"{uuid4().hex[:8]}.pages.cluehq.ai", "w": ws}
                    )
            await conn.execute(text(_CUSTOM), {"h": f"go.{uuid4().hex[:6]}.example", "w": ws})
            with pytest.raises(IntegrityError):
                async with conn.begin_nested():
                    await conn.execute(
                        text(_CUSTOM), {"h": f"go2.{uuid4().hex[:6]}.example", "w": ws}
                    )

    run_async(scenario())


def test_a_hostname_belongs_to_exactly_one_workspace() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            first, second = await _workspace(conn), await _workspace(conn)
            hostname = f"go.{uuid4().hex[:6]}.example"
            await conn.execute(text(_CUSTOM), {"h": hostname, "w": first})
            with pytest.raises(IntegrityError):
                async with conn.begin_nested():
                    await conn.execute(text(_CUSTOM), {"h": hostname, "w": second})

    run_async(scenario())


def test_system_rows_are_always_active_and_carry_no_custom_columns() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = await _workspace(conn)
            with pytest.raises(IntegrityError):
                async with conn.begin_nested():
                    await conn.execute(
                        text(
                            "INSERT INTO workspace_hostname (hostname, workspace_id, kind, status) "
                            "VALUES (:h, :w, 'system', 'pending_dns')"
                        ),
                        {"h": f"{uuid4().hex[:8]}.pages.cluehq.ai", "w": ws},
                    )
            with pytest.raises(IntegrityError):
                async with conn.begin_nested():
                    await conn.execute(
                        text(
                            "INSERT INTO workspace_hostname (hostname, workspace_id, kind, status, "
                            "cname_target) VALUES (:h, :w, 'system', 'active', 'pages.cluehq.ai')"
                        ),
                        {"h": f"{uuid4().hex[:8]}.pages.cluehq.ai", "w": ws},
                    )

    run_async(scenario())


def test_hostnames_are_lowercase_without_trailing_dot_and_custom_rows_carry_ownership() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = await _workspace(conn)
            for bad in (f"Go.{uuid4().hex[:6]}.example", f"go.{uuid4().hex[:6]}.example."):
                with pytest.raises(IntegrityError):
                    async with conn.begin_nested():
                        await conn.execute(text(_CUSTOM), {"h": bad, "w": ws})
            with pytest.raises(IntegrityError):
                async with conn.begin_nested():
                    await conn.execute(
                        text(
                            "INSERT INTO workspace_hostname (hostname, workspace_id, kind, status) "
                            "VALUES (:h, :w, 'custom', 'pending_dns')"
                        ),
                        {"h": f"go.{uuid4().hex[:6]}.example", "w": ws},
                    )

    run_async(scenario())


def test_pages_settings_fallback_must_be_https() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = await _workspace(conn)
            await conn.execute(
                text(
                    "INSERT INTO workspace_pages_settings (workspace_id, fallback_url) "
                    "VALUES (:w, 'https://www.example.com')"
                ),
                {"w": ws},
            )
            with pytest.raises(IntegrityError):
                async with conn.begin_nested():
                    await conn.execute(
                        text(
                            "UPDATE workspace_pages_settings SET fallback_url = 'http://x.example' "
                            "WHERE workspace_id = :w"
                        ),
                        {"w": ws},
                    )

    run_async(scenario())
