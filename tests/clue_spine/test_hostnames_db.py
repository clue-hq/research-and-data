"""Custom-domain publishing S1 Task 4: the hostname registry DAL."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_spine import create_workspace
from clue_spine.hostnames import (
    active_custom_hostname,
    ensure_system_hostname,
    resolve_active_hostname,
    system_hostname,
    system_hostnames_off_suffix,
    workspaces_without_system_hostname,
)

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_spine_db")
SUFFIX = "pages.test"


def _name() -> str:
    return "Acme " + uuid4().hex[:6]


def test_create_workspace_allocates_a_system_hostname_in_the_same_transaction() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            name = _name()
            ws = await create_workspace(conn, name=name, pages_system_suffix=SUFFIX)
            hostname = await system_hostname(conn, ws.workspace_id)
            assert hostname == f"{name.lower().replace(' ', '-')}.{SUFFIX}"
            assert await resolve_active_hostname(conn, hostname) == ws.workspace_id

    run_async(scenario())


def test_ensure_is_idempotent_and_collisions_get_a_numeric_suffix() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            name = _name()
            first = await create_workspace(conn, name=name, pages_system_suffix=SUFFIX)
            second = await create_workspace(conn, name=name, pages_system_suffix=SUFFIX)
            base = await system_hostname(conn, first.workspace_id)
            assert base is not None
            assert await system_hostname(conn, second.workspace_id) == base.replace(
                f".{SUFFIX}", f"-2.{SUFFIX}"
            )
            again = await ensure_system_hostname(
                conn, workspace_id=first.workspace_id, name="Renamed", suffix=SUFFIX
            )
            assert again.hostname == base  # an existing row is returned, never re-allocated

    run_async(scenario())


def test_reserved_labels_and_short_names() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            www = await create_workspace(conn, name="www", pages_system_suffix=SUFFIX)
            assert await system_hostname(conn, www.workspace_id) == f"www-2.{SUFFIX}"
            short = await create_workspace(conn, name="ab", pages_system_suffix=SUFFIX)
            got = await system_hostname(conn, short.workspace_id)
            assert got is not None and got.startswith("ws-") and got.endswith(f".{SUFFIX}")

    run_async(scenario())


def test_resolve_only_returns_active_rows() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = await create_workspace(conn, name=_name(), pages_system_suffix=SUFFIX)
            hostname = f"go.{uuid4().hex[:6]}.example"
            await conn.execute(
                text(
                    "INSERT INTO workspace_hostname (hostname, workspace_id, kind, status, "
                    "cname_target, ownership_txt_name, ownership_txt_value) VALUES "
                    "(:h, :w, 'custom', 'pending_dns', 'pages.test', 'n', 'v')"
                ),
                {"h": hostname, "w": ws.workspace_id},
            )
            assert await resolve_active_hostname(conn, hostname) is None
            assert await active_custom_hostname(conn, ws.workspace_id) is None
            await conn.execute(
                text("UPDATE workspace_hostname SET status = 'active' WHERE hostname = :h"),
                {"h": hostname},
            )
            assert await resolve_active_hostname(conn, hostname) == ws.workspace_id
            assert await active_custom_hostname(conn, ws.workspace_id) == hostname
            assert await resolve_active_hostname(conn, "nobody.example") is None

    run_async(scenario())


def test_backfill_queries() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            bare = "ws_" + uuid4().hex
            await conn.execute(
                text("INSERT INTO workspace (workspace_id, name) VALUES (:w, 'Bare')"), {"w": bare}
            )
            missing = await workspaces_without_system_hostname(conn)
            assert (bare, "Bare") in missing
            await ensure_system_hostname(conn, workspace_id=bare, name="Bare", suffix=SUFFIX)
            assert (bare, "Bare") not in await workspaces_without_system_hostname(conn)
            off = await system_hostnames_off_suffix(conn, "pages.other")
            assert any(h.endswith(f".{SUFFIX}") for h in off)
            assert not [
                h
                for h in await system_hostnames_off_suffix(conn, SUFFIX)
                if h.endswith(f".{SUFFIX}")
            ]

    run_async(scenario())
