"""[B3×research] slice 1 — workspace-local entity schema + stamped writers.

Accounts are workspace-local (founder ruling 2026-07-22): Company X in two workspaces is two
``account_entity`` rows, never shared. These tests exercise the real Postgres constraints the
migration installs — workspace-scoped strong-key uniqueness (legacy NULL rows keep global
semantics), the contact→account workspace anchor (a contact inherits its parent's workspace), and
the app-level + FK cross-workspace merge fence. They skip without a reachable DB, like the rest of
the identity suite.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import EntityType, new_entity_id
from clue_research.identity import (
    CrossWorkspaceMergeError,
    get_account,
    get_contact,
    insert_account_entity,
    insert_contact_entity,
    mark_merged,
)

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_identity_db")


async def seed_workspace(conn: AsyncConnection, workspace_id: str) -> str:
    """Insert a workspace row (idempotent) so the workspace FK is satisfiable."""
    await conn.execute(
        text(
            "INSERT INTO workspace (workspace_id, name) VALUES (:w, :w) "
            "ON CONFLICT (workspace_id) DO NOTHING"
        ),
        {"w": workspace_id},
    )
    return workspace_id


def test_insert_account_stamps_workspace() -> None:
    """A stamped account round-trips its workspace_id; brand_id stays None when unset."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = await seed_workspace(conn, "ws_t1")
            eid = await insert_account_entity(
                conn, canonical_name="Acme", primary_domain="acme.com", workspace_id=ws
            )
            account = await get_account(conn, eid)
            assert account is not None
            assert account.workspace_id == ws
            assert account.brand_id is None

    run_async(_run())


def test_same_domain_two_workspaces_coexist() -> None:
    """The same primary_domain under two workspaces yields two distinct accounts (no collision)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            a = await seed_workspace(conn, "ws_a")
            b = await seed_workspace(conn, "ws_b")
            id_a = await insert_account_entity(
                conn, canonical_name="Acme", primary_domain="acme.com", workspace_id=a
            )
            id_b = await insert_account_entity(
                conn, canonical_name="Acme", primary_domain="acme.com", workspace_id=b
            )
            assert id_a != id_b

    run_async(_run())


def test_same_domain_same_workspace_collides() -> None:
    """Two accounts sharing a domain within one workspace violate the scoped unique index."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = await seed_workspace(conn, "ws_dup")
            await insert_account_entity(
                conn, canonical_name="Acme", primary_domain="acme.com", workspace_id=ws
            )
            trans = await conn.begin_nested()
            with pytest.raises(IntegrityError):
                await insert_account_entity(
                    conn, canonical_name="Acme 2", primary_domain="acme.com", workspace_id=ws
                )
            await trans.rollback()

    run_async(_run())


def test_contact_inherits_parent_workspace() -> None:
    """insert_contact_entity stamps the contact's workspace from its parent account atomically."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = await seed_workspace(conn, "ws_c")
            acc = await insert_account_entity(conn, canonical_name="Acme", workspace_id=ws)
            cid = await insert_contact_entity(conn, account_entity_id=acc, full_name="Jo Doe")
            contact = await get_contact(conn, cid)
            assert contact is not None
            assert contact.workspace_id == ws

    run_async(_run())


def test_contact_strong_key_scoped_per_workspace() -> None:
    """Same linkedin_url under accounts in two workspaces coexists; a dup within one collides."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws1 = await seed_workspace(conn, "ws_ck1")
            ws2 = await seed_workspace(conn, "ws_ck2")
            acc1 = await insert_account_entity(conn, canonical_name="A", workspace_id=ws1)
            acc2 = await insert_account_entity(conn, canonical_name="B", workspace_id=ws2)
            url = "https://www.linkedin.com/in/jo/"
            c1 = await insert_contact_entity(
                conn, account_entity_id=acc1, full_name="Jo", linkedin_url=url
            )
            # Same url under a different-workspace account is fine (scoped uniqueness).
            c2 = await insert_contact_entity(
                conn, account_entity_id=acc2, full_name="Jo", linkedin_url=url
            )
            assert c1 != c2
            # A duplicate within the same workspace collides.
            acc1b = await insert_account_entity(conn, canonical_name="A2", workspace_id=ws1)
            trans = await conn.begin_nested()
            with pytest.raises(IntegrityError):
                await insert_contact_entity(
                    conn, account_entity_id=acc1b, full_name="Jo dup", linkedin_url=url
                )
            await trans.rollback()

    run_async(_run())


def test_cross_workspace_merge_refused() -> None:
    """mark_merged refuses a loser/survivor pair in different workspaces (app-level fence)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws1 = await seed_workspace(conn, "ws_m1")
            ws2 = await seed_workspace(conn, "ws_m2")
            e1 = await insert_account_entity(conn, canonical_name="A", workspace_id=ws1)
            e2 = await insert_account_entity(conn, canonical_name="B", workspace_id=ws2)
            with pytest.raises(CrossWorkspaceMergeError):
                await mark_merged(conn, EntityType.ACCOUNT, e1, e2)

    run_async(_run())


def test_same_workspace_merge_allowed() -> None:
    """Two accounts in the *same* workspace still merge (the fence only blocks cross-workspace)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = await seed_workspace(conn, "ws_same")
            loser = await insert_account_entity(conn, canonical_name="Loser", workspace_id=ws)
            survivor = await insert_account_entity(conn, canonical_name="Survivor", workspace_id=ws)
            await mark_merged(conn, EntityType.ACCOUNT, loser, survivor)
            merged = await get_account(conn, loser)
            assert merged is not None and merged.merged_into == survivor

    run_async(_run())


def test_legacy_null_workspace_account_still_insertable_via_raw_sql() -> None:
    """The memory-lane fail-closed semantics depend on NULL-workspace rows staying representable.

    A legacy account with a NULL workspace_id inserts and keeps global strong-key uniqueness (a
    second NULL-workspace row with the same domain collides on the legacy partial index).
    """

    async def _run() -> None:
        async with rollback_conn() as conn:
            eid = new_entity_id()
            await conn.execute(
                text(
                    "INSERT INTO account_entity (id, canonical_name, primary_domain) "
                    "VALUES (:id, 'Legacy', 'legacy.com')"
                ),
                {"id": eid},
            )
            account = await get_account(conn, eid)
            assert account is not None and account.workspace_id is None
            # Global uniqueness still holds for legacy NULL-workspace rows.
            trans = await conn.begin_nested()
            with pytest.raises(IntegrityError):
                await conn.execute(
                    text(
                        "INSERT INTO account_entity (canonical_name, primary_domain) "
                        "VALUES ('Legacy 2', 'legacy.com')"
                    )
                )
            await trans.rollback()

    run_async(_run())
