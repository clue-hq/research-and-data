"""Custom-domain publishing S1 Task 4: the hostname registry DAL."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_spine import create_workspace
from clue_spine.hostnames import (
    HostnameRefused,
    active_custom_hostname,
    ensure_system_hostname,
    move_system_hostnames,
    replace_system_label,
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


# --- Review finding S4-1: a system label is unique whatever the domain --------------------------
# The edge's 301 maps an old address to the new one by label alone, so the label must name one
# workspace on every domain at once: `acme.<old>` and `acme.<new>` can never belong to two
# workspaces, or one of them receives the other's published links.
def _two_suffixes() -> tuple[str, str]:
    tag = uuid4().hex[:6]
    return f"old{tag}.test", f"new{tag}.test"


def _label_of(hostname: str | None, suffix: str) -> str:
    assert hostname is not None and hostname.endswith("." + suffix), hostname
    return hostname.removesuffix("." + suffix)


def test_s4_1_a_newcomer_never_gets_a_label_held_on_the_other_domain() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            old, new = _two_suffixes()
            name = _name()
            base = name.lower().replace(" ", "-")
            # An unmoved workspace on the old domain; a newcomer of the same name on the new one.
            unmoved = await create_workspace(conn, name=name, pages_system_suffix=old)
            newcomer = await create_workspace(conn, name=name, pages_system_suffix=new)
            assert _label_of(await system_hostname(conn, unmoved.workspace_id), old) == base
            assert _label_of(await system_hostname(conn, newcomer.workspace_id), new) == (
                f"{base}-2"
            )
            # And the other way round: a label already on the new domain is not handed out on
            # the old one.
            late = await create_workspace(conn, name=name, pages_system_suffix=old)
            assert _label_of(await system_hostname(conn, late.workspace_id), old) == f"{base}-3"

    run_async(scenario())


def test_s4_1_after_a_move_the_old_domain_cannot_reuse_a_moved_label() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            old, new = _two_suffixes()
            name = _name()
            base = name.lower().replace(" ", "-")
            moved = await create_workspace(conn, name=name, pages_system_suffix=old)
            report = await move_system_hostnames(conn, from_suffix=old, to_suffix=new, apply=True)
            assert (report["rows"], report["applied"]) == (1, True)
            assert await system_hostname(conn, moved.workspace_id) == f"{base}.{new}"
            # A process still configured with the old suffix creates a workspace of the same name.
            straggler = await create_workspace(conn, name=name, pages_system_suffix=old)
            assert await system_hostname(conn, straggler.workspace_id) == f"{base}-2.{old}"

    run_async(scenario())


def test_s4_1_a_rename_to_a_label_held_on_another_domain_is_label_taken() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            old, new = _two_suffixes()
            published = await create_workspace(conn, name=_name(), pages_system_suffix=old)
            held = _label_of(await system_hostname(conn, published.workspace_id), old)
            other = await create_workspace(conn, name=_name(), pages_system_suffix=new)
            before = await system_hostname(conn, other.workspace_id)
            with pytest.raises(HostnameRefused) as caught:
                await replace_system_label(
                    conn, workspace_id=other.workspace_id, label=held, suffix=new
                )
            assert caught.value.code == "label_taken"
            assert await system_hostname(conn, other.workspace_id) == before
            assert await system_hostname(conn, published.workspace_id) == f"{held}.{old}"

    run_async(scenario())


def test_s4_1_the_migration_refuses_duplicate_system_labels_by_name() -> None:
    """The label index cannot be built over two workspaces sharing a label; the upgrade names
    them instead of guessing which one keeps it."""
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = (
        Path(__file__).resolve().parents[2]
        / "alembic/versions/abf95e465478_workspace_hostname_system_label_unique.py"
    )
    spec = importlib.util.spec_from_file_location("system_label_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    def upgrade(sync_conn: Any) -> None:
        with Operations.context(MigrationContext.configure(sync_conn)):
            migration.upgrade()

    async def scenario() -> None:
        async with rollback_conn() as conn:
            old, new = _two_suffixes()
            await conn.execute(text("DROP INDEX workspace_hostname_system_label_key"))
            first = await create_workspace(conn, name=_name(), pages_system_suffix=old)
            label = _label_of(await system_hostname(conn, first.workspace_id), old)
            second = "ws_" + uuid4().hex
            await conn.execute(
                text("INSERT INTO workspace (workspace_id, name) VALUES (:w, 'Twin')"),
                {"w": second},
            )
            await conn.execute(
                text(
                    "INSERT INTO workspace_hostname (hostname, workspace_id, kind, status, "
                    "activated_at) VALUES (:h, :w, 'system', 'active', now())"
                ),
                {"h": f"{label}.{new}", "w": second},
            )
            with pytest.raises(RuntimeError) as caught:
                await conn.run_sync(upgrade)
            assert label in str(caught.value)
            assert f"{label}.{old}" in str(caught.value) and f"{label}.{new}" in str(caught.value)
            # Once the duplicate is resolved by hand, the same upgrade builds the index.
            await conn.execute(
                text("DELETE FROM workspace_hostname WHERE workspace_id = :w"), {"w": second}
            )
            await conn.run_sync(upgrade)
            names = await conn.execute(
                text(
                    "SELECT indexname FROM pg_indexes WHERE tablename = 'workspace_hostname' "
                    "AND indexname = 'workspace_hostname_system_label_key'"
                )
            )
            assert names.scalar() == "workspace_hostname_system_label_key"

    run_async(scenario())


def test_s4_1_losing_the_one_system_row_race_still_returns_the_winner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A concurrent creator inserted this workspace's system row between our read and our insert:
    the insert loses (on the one-per-workspace index, or on the label index when the winner took
    the same label) and the winner is returned — never a second row, never an error."""
    from clue_spine import hostnames

    async def scenario() -> None:
        async with rollback_conn() as conn:
            name = _name()
            ws = await create_workspace(conn, name=name, pages_system_suffix=SUFFIX)
            winner = await system_hostname(conn, ws.workspace_id)
            real = hostnames._system_row
            calls = 0

            async def first_read_misses(conn: Any, workspace_id: str) -> Any:
                nonlocal calls
                calls += 1
                return None if calls == 1 else await real(conn, workspace_id)

            monkeypatch.setattr(hostnames, "_system_row", first_read_misses)
            for again_name in (name, "Another " + name):
                calls = 0
                row = await ensure_system_hostname(
                    conn, workspace_id=ws.workspace_id, name=again_name, suffix=SUFFIX
                )
                assert row.hostname == winner, again_name
            count = await conn.execute(
                text(
                    "SELECT count(*) FROM workspace_hostname "
                    "WHERE workspace_id = :w AND kind = 'system'"
                ),
                {"w": ws.workspace_id},
            )
            assert count.scalar() == 1

    run_async(scenario())
