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

from clue_core import EntityId, EntityType, new_entity_id
from clue_research.identity import (
    CrossWorkspaceMergeError,
    Observation,
    ResolutionMethod,
    ResolutionResult,
    embed_account,
    get_account,
    get_contact,
    insert_account_entity,
    insert_contact_entity,
    mark_merged,
    resolve,
)

from .conftest import rollback_conn, run_async


def _candidate_ids(result: ResolutionResult) -> set[EntityId]:
    """The set of resolved candidate entity ids (empty when nothing matched)."""
    return {c.entity_id for c in result.candidates}


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


# --- [B3×research] slice 2 — workspace-scoped resolution ---------------------
# Each test proves one candidate stage is workspace-scoped: the same resolve finds the entity in
# its own workspace and finds *nothing* of it in a foreign workspace. Constructed so the named
# stage is the *only* path that could surface the entity (so a broken filter on that stage would
# leak it into ws_b), the others being starved (no embedding → no ANN, distinct name-key → no
# alias-block, low trigram similarity → no trigram, no strong key → no deterministic hit).


def test_deterministic_domain_match_is_workspace_scoped() -> None:
    """An exact-domain deterministic hit only fires within the observation's workspace."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws_a = await seed_workspace(conn, "ws_ra")
            ws_b = await seed_workspace(conn, "ws_rb")
            id_a = await insert_account_entity(
                conn, canonical_name="Acme", primary_domain="acme.com", workspace_id=ws_a
            )
            obs = Observation(name="Acme", entity_type=EntityType.ACCOUNT, domain="acme.com")

            hit_a = await resolve(conn, obs, workspace_id=ws_a)
            assert hit_a.method is ResolutionMethod.DETERMINISTIC
            assert hit_a.top is not None and hit_a.top.entity_id == id_a

            miss_b = await resolve(conn, obs, workspace_id=ws_b)
            assert miss_b.method is not ResolutionMethod.DETERMINISTIC
            assert id_a not in _candidate_ids(miss_b)

    run_async(_run())


def test_deterministic_registry_match_is_workspace_scoped() -> None:
    """An exact registry-id deterministic hit only fires within the observation's workspace."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws_a = await seed_workspace(conn, "ws_ra")
            ws_b = await seed_workspace(conn, "ws_rb")
            id_a = await insert_account_entity(
                conn,
                canonical_name="Acme",
                registry_ids={"DUNS": "123456789"},
                workspace_id=ws_a,
            )
            obs = Observation(
                name="Acme", entity_type=EntityType.ACCOUNT, registry_ids={"duns": "12-345-6789"}
            )

            hit_a = await resolve(conn, obs, workspace_id=ws_a)
            assert hit_a.method is ResolutionMethod.DETERMINISTIC
            assert hit_a.top is not None and hit_a.top.entity_id == id_a

            miss_b = await resolve(conn, obs, workspace_id=ws_b)
            assert miss_b.method is not ResolutionMethod.DETERMINISTIC
            assert id_a not in _candidate_ids(miss_b)

    run_async(_run())


def test_contact_strong_key_match_is_workspace_scoped() -> None:
    """A contact strong-key (linkedin/email) deterministic hit is scoped to its own workspace."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws_a = await seed_workspace(conn, "ws_ra")
            ws_b = await seed_workspace(conn, "ws_rb")
            acc_a = await insert_account_entity(conn, canonical_name="A", workspace_id=ws_a)
            await insert_account_entity(conn, canonical_name="B", workspace_id=ws_b)
            url = "https://www.linkedin.com/in/jo/"
            cid = await insert_contact_entity(
                conn, account_entity_id=acc_a, full_name="Jo", linkedin_url=url
            )
            obs = Observation(name="Jo", entity_type=EntityType.CONTACT, linkedin_url=url)

            hit_a = await resolve(conn, obs, workspace_id=ws_a)
            assert hit_a.method is ResolutionMethod.DETERMINISTIC
            assert hit_a.top is not None and hit_a.top.entity_id == cid

            miss_b = await resolve(conn, obs, workspace_id=ws_b)
            assert miss_b.method is not ResolutionMethod.DETERMINISTIC
            assert cid not in _candidate_ids(miss_b)

    run_async(_run())


def test_alias_block_candidates_are_workspace_scoped() -> None:
    """The alias-array-overlap candidate query filters by workspace (only stage that can match)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws_a = await seed_workspace(conn, "ws_ra")
            ws_b = await seed_workspace(conn, "ws_rb")
            # Canonical name is far from the probe (kills trigram); an alias equals the probe's
            # name-key (only alias-block can match); not embedded (kills ANN); no domain.
            id_a = await insert_account_entity(
                conn, canonical_name="Zeta Industries", aliases=["Acme"], workspace_id=ws_a
            )
            obs = Observation(name="Acme", entity_type=EntityType.ACCOUNT)

            hit_a = await resolve(conn, obs, workspace_id=ws_a)
            assert id_a in _candidate_ids(hit_a)

            miss_b = await resolve(conn, obs, workspace_id=ws_b)
            assert id_a not in _candidate_ids(miss_b)

    run_async(_run())


def test_trigram_candidates_are_workspace_scoped() -> None:
    """The trigram-similarity candidate query filters by workspace (only stage that can match)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws_a = await seed_workspace(conn, "ws_ra")
            ws_b = await seed_workspace(conn, "ws_rb")
            # A near-duplicate probe (typo) → high trigram similarity but a *different* name-key
            # (kills alias-block); not embedded (kills ANN); no domain (kills deterministic).
            id_a = await insert_account_entity(
                conn, canonical_name="Acme Corporation", workspace_id=ws_a
            )
            obs = Observation(name="Acme Corporatn", entity_type=EntityType.ACCOUNT)

            hit_a = await resolve(conn, obs, workspace_id=ws_a)
            assert id_a in _candidate_ids(hit_a)

            miss_b = await resolve(conn, obs, workspace_id=ws_b)
            assert id_a not in _candidate_ids(miss_b)

    run_async(_run())


def test_ann_candidates_are_workspace_scoped() -> None:
    """The pgvector ANN join filters by workspace (only stage that can surface the entity)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            ws_a = await seed_workspace(conn, "ws_ra")
            ws_b = await seed_workspace(conn, "ws_rb")
            # Embedded → reachable by ANN (nearest of the embedded set); canonical name shares no
            # trigrams/name-key with the probe (kills trigram + alias-block); no domain.
            id_a = await insert_account_entity(
                conn, canonical_name="Zeta Industries", workspace_id=ws_a
            )
            await embed_account(conn, id_a)
            obs = Observation(name="Acme", entity_type=EntityType.ACCOUNT)

            hit_a = await resolve(conn, obs, workspace_id=ws_a)
            assert id_a in _candidate_ids(hit_a)

            miss_b = await resolve(conn, obs, workspace_id=ws_b)
            assert id_a not in _candidate_ids(miss_b)

    run_async(_run())


def test_legacy_null_workspace_rows_invisible_to_scoped_resolution() -> None:
    """A legacy NULL-workspace row is unreachable by a scoped resolve (fail-closed), though a
    caller who passes no workspace still finds it (the transitional unscoped arm)."""

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
            obs = Observation(name="Legacy", entity_type=EntityType.ACCOUNT, domain="legacy.com")

            # Unscoped (workspace_id=None) still sees the legacy row — behaviour preserved.
            unscoped = await resolve(conn, obs)
            assert unscoped.method is ResolutionMethod.DETERMINISTIC
            assert unscoped.top is not None and unscoped.top.entity_id == EntityId(eid)

            # Scoped resolve cannot see it (NULL workspace != 'ws_x').
            scoped = await resolve(conn, obs, workspace_id="ws_x")
            assert scoped.method is not ResolutionMethod.DETERMINISTIC
            assert EntityId(eid) not in _candidate_ids(scoped)

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
