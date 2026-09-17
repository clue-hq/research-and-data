"""F5 Task 14 acceptance: a workspace's HANDLE — the DNS label its published sites hang off.

Founder ruling R-F5-5 (default): every workspace gets a handle derived from its NAME, it stays
editable while nothing has been published, and the first publish LOCKS it. A published URL is
something a marketer pastes into an email; letting the host segment of that URL change later
would break links that are already in the world, so the lock is the whole point of the table.

What each test pins:

* ``ensure`` DERIVES from ``workspace.name`` (not from the opaque workspace id) and is
  IDEMPOTENT — a second call never re-derives and never overwrites a handle a human chose.
* ``set`` replaces it while unlocked, and is refused with ``handle_locked`` once locked.
* ``lock`` is idempotent, and locking a workspace with no handle yet MINTS one — a publish must
  never be able to serve a site off a handle that does not exist.
* Reserved labels (``www`` and friends) are refused as ``handle_invalid``: they are the names a
  hosting domain needs for itself.
* The derived default NEVER COLLIDES SILENTLY — two workspaces with the same name cannot both
  be ``acme-robotics``, so the second one gets ``-<last 4 of its workspace id>``.
* ``get_workspace_by_handle`` is the reverse lookup Task 15's host router needs, and it is the
  one function here that is deliberately NOT workspace-scoped (resolving the tenant IS its job).

DB-gated like its neighbours (``test_web_publish_pages_dal_db.py``): skips without a reachable
``CLUE_DATABASE_URL``, and every write runs inside a transaction that is rolled back, so the
test leaves no rows behind.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_db import db_lifespan
from clue_design import workspace_handles
from tests.design.conftest import run_async


def _ws(tag: str) -> str:
    return f"ws_test_handle_{tag}_{uuid4().hex[:12]}"


def _token() -> str:
    """A per-test label fragment.

    Handles are GLOBALLY unique — that is the point of the table — and this suite shares its
    database with the design API's own suite, whose rows are COMMITTED rather than rolled back.
    A literal ``"acme"`` here would therefore pass until some other suite claimed it and then
    fail forever with ``handle_taken``. Tokenizing keeps every run independent while asserting
    exactly the same things.
    """
    return uuid4().hex[:8]


async def _seed_workspace(conn: AsyncConnection, workspace_id: str, name: str) -> None:
    await conn.execute(
        text("INSERT INTO workspace (workspace_id, name) VALUES (:w, :n)"),
        {"w": workspace_id, "n": name},
    )


def test_ensure_derives_the_handle_from_the_workspace_name(require_design_db: None) -> None:
    """The default handle is the workspace's NAME, shaped into a DNS label — and once it exists
    ``ensure`` returns it untouched, so the derivation runs exactly once in a workspace's life."""

    async def _check() -> None:
        ws, token = _ws("derive"), _token()
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            await _seed_workspace(conn, ws, f"Acme Robotics, Inc. {token}")

            assert await workspace_handles.get_workspace_handle(conn, workspace_id=ws) is None

            created = await workspace_handles.ensure_workspace_handle(conn, workspace_id=ws)
            assert created["handle"] == f"acme-robotics-inc-{token}"
            assert created["locked"] is False

            # A human renames it; ``ensure`` must never claw that back.
            chosen = f"acme-{token}"
            await workspace_handles.set_workspace_handle(conn, workspace_id=ws, handle=chosen)
            again = await workspace_handles.ensure_workspace_handle(conn, workspace_id=ws)
            assert again["handle"] == chosen

            await txn.rollback()

    run_async(_check())


def test_set_replaces_the_handle_until_a_lock_freezes_it(require_design_db: None) -> None:
    """Editable until the first publish, frozen after — the R-F5-5 lifecycle in one walk."""

    async def _check() -> None:
        ws, token = _ws("lock"), _token()
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            await _seed_workspace(conn, ws, f"Acme Robotics {token}")
            await workspace_handles.ensure_workspace_handle(conn, workspace_id=ws)

            chosen = f"acme-eu-{token}"
            updated = await workspace_handles.set_workspace_handle(
                conn, workspace_id=ws, handle=chosen
            )
            assert updated["handle"] == chosen
            assert updated["locked"] is False

            locked = await workspace_handles.lock_workspace_handle(conn, workspace_id=ws)
            assert locked["locked"] is True
            assert locked["handle"] == chosen
            # Locking twice is a no-op, not a second (later) lock timestamp.
            relocked = await workspace_handles.lock_workspace_handle(conn, workspace_id=ws)
            assert relocked["locked_at"] == locked["locked_at"]

            with pytest.raises(ValueError, match="handle_locked"):
                await workspace_handles.set_workspace_handle(
                    conn, workspace_id=ws, handle=f"somebody-else-{token}"
                )
            # And the refusal changed nothing.
            current = await workspace_handles.get_workspace_handle(conn, workspace_id=ws)
            assert current is not None and current["handle"] == chosen

            await txn.rollback()

    run_async(_check())


def test_locking_a_workspace_with_no_handle_mints_one(require_design_db: None) -> None:
    """A publish LOCKS the handle it just served a site from, so the lock cannot presuppose a
    row: if none exists it derives one and freezes it in the same call."""

    async def _check() -> None:
        ws, token = _ws("mint"), _token()
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            await _seed_workspace(conn, ws, f"Northwind Labs {token}")
            locked = await workspace_handles.lock_workspace_handle(conn, workspace_id=ws)
            assert locked["handle"] == f"northwind-labs-{token}"
            assert locked["locked"] is True
            await txn.rollback()

    run_async(_check())


def test_reserved_and_ill_shaped_handles_are_refused(require_design_db: None) -> None:
    """``www`` and its siblings belong to the hosting domain itself; and a handle that is not a
    DNS label is refused BEFORE the CHECK constraint sees it, so the caller gets a domain error
    rather than a 500 from a poisoned transaction."""

    async def _check() -> None:
        ws, token = _ws("reserved"), _token()
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            await _seed_workspace(conn, ws, f"Acme Robotics {token}")
            await workspace_handles.ensure_workspace_handle(conn, workspace_id=ws)

            for refused in ("www", "WWW", "api", "admin", "pages"):
                with pytest.raises(ValueError, match="handle_invalid"):
                    await workspace_handles.set_workspace_handle(
                        conn, workspace_id=ws, handle=refused
                    )
            for malformed in ("-acme", "acme-", "ac", "Acme Robotics", "a" * 64, ""):
                with pytest.raises(ValueError, match="handle_invalid"):
                    await workspace_handles.set_workspace_handle(
                        conn, workspace_id=ws, handle=malformed
                    )

            # None of it landed.
            current = await workspace_handles.get_workspace_handle(conn, workspace_id=ws)
            assert current is not None and current["handle"] == f"acme-robotics-{token}"
            await txn.rollback()

    run_async(_check())


def test_a_taken_handle_never_collides_silently(require_design_db: None) -> None:
    """Two workspaces named the same thing derive the same default — the second must get its own
    label (``-<last 4 of its workspace id>``), never the first one's rows or a silent no-op.

    And an explicit ``set`` onto somebody else's handle is a loud ``handle_taken``."""

    async def _check() -> None:
        first, second = _ws("dupa"), _ws("dupb")
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            name = f"Contoso {uuid4().hex[:8]}"
            await _seed_workspace(conn, first, name)
            await _seed_workspace(conn, second, name)

            a = await workspace_handles.ensure_workspace_handle(conn, workspace_id=first)
            b = await workspace_handles.ensure_workspace_handle(conn, workspace_id=second)
            assert b["handle"] != a["handle"]
            assert b["handle"] == f"{a['handle']}-{second[-4:]}"

            with pytest.raises(ValueError, match="handle_taken"):
                await workspace_handles.set_workspace_handle(
                    conn, workspace_id=second, handle=a["handle"]
                )
            # Setting a workspace's own handle to what it already is is NOT "taken".
            same = await workspace_handles.set_workspace_handle(
                conn, workspace_id=second, handle=b["handle"]
            )
            assert same["handle"] == b["handle"]
            await txn.rollback()

    run_async(_check())


def test_get_workspace_by_handle_is_the_reverse_lookup(require_design_db: None) -> None:
    """Task 15's host router turns ``{handle}.pages.cluehq.ai`` back into a workspace with this.

    Deliberately NOT workspace-scoped: resolving the tenant is the whole point, and an unknown
    handle answers ``None`` (a 404 for the visitor) rather than raising.
    """

    async def _check() -> None:
        ws = _ws("reverse")
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            await _seed_workspace(conn, ws, f"Reverse {uuid4().hex[:8]}")
            handle = (await workspace_handles.ensure_workspace_handle(conn, workspace_id=ws))[
                "handle"
            ]
            assert await workspace_handles.get_workspace_by_handle(conn, handle=handle) == ws
            assert (
                await workspace_handles.get_workspace_by_handle(
                    conn, handle=f"nobody-{uuid4().hex[:10]}"
                )
                is None
            )
            await txn.rollback()

    run_async(_check())
