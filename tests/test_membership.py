"""FI-2 P1 — ``project_account``, the account↔project membership junction (spec §2).

Which projects target an account is first-class, queryable state (R4), not folklore recomputed
from discovery lineage. These tests exercise the real Postgres table: the composite workspace
anchors, the first-add-wins upsert, the ``added_at``-ascending ordering that defines
``primaryProjectId``, and the merge re-pointing that keeps membership attached to the survivor.

The suite needs a reachable, migrated database; it reuses the identity harness's session-scoped
migration + rollback isolation (DRY — the account rows it seeds are identity rows).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from clue_core import EntityType
from clue_research.identity import insert_account_entity, mark_merged
from clue_research.membership import (
    ADDED_VIA,
    accounts_for_project,
    ensure_project_account,
    projects_for_accounts,
    repoint_project_accounts,
)
from tests._workspace import seed_project, seed_workspace

# The identity harness owns the migrated-DB gate; import its fixtures into this module's namespace
# so a top-level test file (membership is a top-level ``clue_research`` module) gets them.
from tests.identity.conftest import migrated_db as migrated_db
from tests.identity.conftest import require_identity_db as require_identity_db
from tests.identity.conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_identity_db")


def test_membership_round_trips_through_both_readers() -> None:
    """An upserted membership is readable account-first and project-first."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            project = await seed_project(conn, "ws_m1")
            account = await insert_account_entity(
                conn, canonical_name="Acme", primary_domain="acme-m1.com", workspace_id="ws_m1"
            )
            await ensure_project_account(
                conn,
                workspace_id="ws_m1",
                project_id=project.project_id,
                account_entity_id=account,
                added_via="discovered",
            )
            assert await projects_for_accounts(
                conn, workspace_id="ws_m1", account_ids=[account]
            ) == {account: (project.project_id,)}
            assert await accounts_for_project(
                conn, workspace_id="ws_m1", project_id=project.project_id
            ) == (account,)

    run_async(_run())


def test_adding_the_same_account_twice_keeps_the_first_add() -> None:
    """Idempotent upsert: the first channel/time wins; a later add is a no-op on the row."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            project = await seed_project(conn, "ws_m2")
            account = await insert_account_entity(
                conn, canonical_name="Acme", primary_domain="acme-m2.com", workspace_id="ws_m2"
            )
            first = datetime(2026, 1, 1, tzinfo=UTC)
            await ensure_project_account(
                conn,
                workspace_id="ws_m2",
                project_id=project.project_id,
                account_entity_id=account,
                added_via="discovered",
                added_at=first,
            )
            await ensure_project_account(
                conn,
                workspace_id="ws_m2",
                project_id=project.project_id,
                account_entity_id=account,
                added_via="imported",
                added_at=first + timedelta(days=1),
            )
            rows = (
                (
                    await conn.execute(
                        text(
                            "SELECT added_via, added_at FROM project_account "
                            "WHERE workspace_id = 'ws_m2' AND account_entity_id = :a"
                        ),
                        {"a": account},
                    )
                )
                .mappings()
                .all()
            )
            assert len(rows) == 1
            assert rows[0]["added_via"] == "discovered"
            assert rows[0]["added_at"] == first

    run_async(_run())


def test_projects_are_ordered_oldest_membership_first() -> None:
    """``projects_for_accounts`` is added_at-ascending — element 0 is the primaryProjectId."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            earlier = await seed_project(conn, "ws_m3", name="Earlier")
            later = await seed_project(conn, "ws_m3", name="Later")
            account = await insert_account_entity(
                conn, canonical_name="Acme", primary_domain="acme-m3.com", workspace_id="ws_m3"
            )
            t1 = datetime(2026, 1, 1, tzinfo=UTC)
            t2 = t1 + timedelta(days=30)
            # Insert the *later* membership first so the ordering cannot come from insert order.
            await ensure_project_account(
                conn,
                workspace_id="ws_m3",
                project_id=later.project_id,
                account_entity_id=account,
                added_via="manual",
                added_at=t2,
            )
            await ensure_project_account(
                conn,
                workspace_id="ws_m3",
                project_id=earlier.project_id,
                account_entity_id=account,
                added_via="discovered",
                added_at=t1,
            )
            assert await projects_for_accounts(
                conn, workspace_id="ws_m3", account_ids=[account]
            ) == {account: (earlier.project_id, later.project_id)}

    run_async(_run())


def test_repoint_moves_loser_memberships_and_merges_with_the_survivors() -> None:
    """The survivor gains the loser's projects; a shared project does not duplicate."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            shared = await seed_project(conn, "ws_m4", name="Shared")
            loser_only = await seed_project(conn, "ws_m4", name="Loser only")
            survivor_only = await seed_project(conn, "ws_m4", name="Survivor only")
            loser = await insert_account_entity(
                conn, canonical_name="Acme", primary_domain="acme-m4a.com", workspace_id="ws_m4"
            )
            survivor = await insert_account_entity(
                conn, canonical_name="Acme", primary_domain="acme-m4b.com", workspace_id="ws_m4"
            )
            t1 = datetime(2026, 1, 1, tzinfo=UTC)
            for project_id, account, added_at in (
                (shared.project_id, loser, t1),
                (loser_only.project_id, loser, t1 + timedelta(days=1)),
                (shared.project_id, survivor, t1 + timedelta(days=2)),
                (survivor_only.project_id, survivor, t1 + timedelta(days=3)),
            ):
                await ensure_project_account(
                    conn,
                    workspace_id="ws_m4",
                    project_id=project_id,
                    account_entity_id=account,
                    added_via="discovered",
                    added_at=added_at,
                )

            await repoint_project_accounts(
                conn, workspace_id="ws_m4", loser_id=loser, survivor_id=survivor
            )

            memberships = await projects_for_accounts(
                conn, workspace_id="ws_m4", account_ids=[loser, survivor]
            )
            assert memberships.get(loser, ()) == ()
            # The survivor's own shared-project row is untouched (its later added_at survives),
            # so the union is ordered by the *kept* timestamps: loser_only(t1+1) predates
            # shared(t1+2) and survivor_only(t1+3).
            assert memberships[survivor] == (
                loser_only.project_id,
                shared.project_id,
                survivor_only.project_id,
            )
            assert await accounts_for_project(
                conn, workspace_id="ws_m4", project_id=shared.project_id
            ) == (survivor,)

    run_async(_run())


def test_repointing_an_account_onto_itself_is_refused_not_a_wipe() -> None:
    """Self-re-pointing would mirror onto identical PKs and then DELETE every membership."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            project = await seed_project(conn, "ws_m4b")
            account = await insert_account_entity(
                conn, canonical_name="Acme", primary_domain="acme-m4b.com", workspace_id="ws_m4b"
            )
            await ensure_project_account(
                conn,
                workspace_id="ws_m4b",
                project_id=project.project_id,
                account_entity_id=account,
                added_via="discovered",
            )
            with pytest.raises(ValueError):
                await repoint_project_accounts(
                    conn, workspace_id="ws_m4b", loser_id=account, survivor_id=account
                )
            # Refused before any statement: the connection is usable and nothing was deleted.
            assert await accounts_for_project(
                conn, workspace_id="ws_m4b", project_id=project.project_id
            ) == (account,)

    run_async(_run())


def test_mark_merged_repoints_membership_in_the_same_transaction() -> None:
    """The identity merge itself moves membership — no caller has to remember to."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            project = await seed_project(conn, "ws_m5")
            other = await seed_project(conn, "ws_m5", name="Other")
            loser = await insert_account_entity(
                conn, canonical_name="Acme", primary_domain="acme-m5a.com", workspace_id="ws_m5"
            )
            survivor = await insert_account_entity(
                conn, canonical_name="Acme", primary_domain="acme-m5b.com", workspace_id="ws_m5"
            )
            await ensure_project_account(
                conn,
                workspace_id="ws_m5",
                project_id=project.project_id,
                account_entity_id=loser,
                added_via="imported",
            )
            await ensure_project_account(
                conn,
                workspace_id="ws_m5",
                project_id=other.project_id,
                account_entity_id=survivor,
                added_via="discovered",
            )

            await mark_merged(conn, EntityType.ACCOUNT, loser, survivor)

            memberships = await projects_for_accounts(
                conn, workspace_id="ws_m5", account_ids=[loser, survivor]
            )
            assert memberships.get(loser, ()) == ()
            assert set(memberships[survivor]) == {project.project_id, other.project_id}

    run_async(_run())


def test_unknown_added_via_raises_before_touching_the_database() -> None:
    """A bad caller cannot poison the shared transaction (mirrors ``record_run_lineage``)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            project = await seed_project(conn, "ws_m6")
            account = await insert_account_entity(
                conn, canonical_name="Acme", primary_domain="acme-m6.com", workspace_id="ws_m6"
            )
            with pytest.raises(ValueError):
                await ensure_project_account(
                    conn,
                    workspace_id="ws_m6",
                    project_id=project.project_id,
                    account_entity_id=account,
                    added_via="telepathy",
                )
            # The connection is still usable — nothing was executed.
            assert (
                await accounts_for_project(
                    conn, workspace_id="ws_m6", project_id=project.project_id
                )
                == ()
            )

    run_async(_run())


def test_every_declared_added_via_is_accepted_by_the_check_constraint() -> None:
    """``ADDED_VIA`` mirrors the DB CHECK — drift on either side fails here."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = await seed_workspace(conn, "ws_m7")
            project = await seed_project(conn, ws)
            for index, added_via in enumerate(ADDED_VIA):
                account = await insert_account_entity(
                    conn,
                    canonical_name=f"Acme {index}",
                    primary_domain=f"acme-m7-{index}.com",
                    workspace_id=ws,
                )
                await ensure_project_account(
                    conn,
                    workspace_id=ws,
                    project_id=project.project_id,
                    account_entity_id=account,
                    added_via=added_via,
                )
            assert len(
                await accounts_for_project(conn, workspace_id=ws, project_id=project.project_id)
            ) == len(ADDED_VIA)

    run_async(_run())


def test_membership_cannot_name_an_account_from_another_workspace() -> None:
    """The composite account FK makes a cross-workspace membership unrepresentable."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            project = await seed_project(conn, "ws_m8a")
            await seed_workspace(conn, "ws_m8b")
            foreign = await insert_account_entity(
                conn, canonical_name="Acme", primary_domain="acme-m8.com", workspace_id="ws_m8b"
            )
            with pytest.raises(IntegrityError):
                await ensure_project_account(
                    conn,
                    workspace_id="ws_m8a",
                    project_id=project.project_id,
                    account_entity_id=foreign,
                    added_via="manual",
                )

    run_async(_run())


def test_membership_cannot_name_an_unknown_project() -> None:
    """The composite project FK refuses a membership in a project that does not exist."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws = await seed_workspace(conn, "ws_m9")
            account = await insert_account_entity(
                conn, canonical_name="Acme", primary_domain="acme-m9.com", workspace_id=ws
            )
            with pytest.raises(IntegrityError):
                await ensure_project_account(
                    conn,
                    workspace_id=ws,
                    project_id="no-such-project",
                    account_entity_id=account,
                    added_via="directive",
                )

    run_async(_run())


def test_reads_are_workspace_scoped() -> None:
    """Neither reader crosses a workspace boundary, and an unknown account has no entry."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            mine = await seed_project(conn, "ws_m10a")
            theirs = await seed_project(conn, "ws_m10b")
            here = await insert_account_entity(
                conn, canonical_name="Acme", primary_domain="acme-m10a.com", workspace_id="ws_m10a"
            )
            there = await insert_account_entity(
                conn, canonical_name="Acme", primary_domain="acme-m10b.com", workspace_id="ws_m10b"
            )
            await ensure_project_account(
                conn,
                workspace_id="ws_m10a",
                project_id=mine.project_id,
                account_entity_id=here,
                added_via="discovered",
            )
            await ensure_project_account(
                conn,
                workspace_id="ws_m10b",
                project_id=theirs.project_id,
                account_entity_id=there,
                added_via="discovered",
            )
            assert await projects_for_accounts(
                conn, workspace_id="ws_m10a", account_ids=[here, there, uuid4()]
            ) == {here: (mine.project_id,)}
            assert (
                await accounts_for_project(
                    conn, workspace_id="ws_m10a", project_id=theirs.project_id
                )
                == ()
            )

    run_async(_run())


def test_reading_no_accounts_is_an_empty_result_not_a_query() -> None:
    """An empty ``account_ids`` is a well-defined no-op (an empty IN list is invalid SQL)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            assert await projects_for_accounts(conn, workspace_id="ws_m11", account_ids=[]) == {}

    run_async(_run())
