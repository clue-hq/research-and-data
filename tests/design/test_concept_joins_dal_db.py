"""D3 acceptance tests: the concept joins (PD contract §6 O1/O2).

Two born-nullable D1 columns become live joins at write time:

* ``design_brand_kit.brand_id`` — the workspace's brand, resolved-or-created at
  ``create_brand_kit`` (R-D3-1): one brand → stamp it; none → mint the interim default brand
  (and the next kit REUSES it); several → NULL, because a wrong bind beats no bind only in
  fiction. An explicit ``brand_id`` wins, and a foreign-workspace one is refused structurally.
* ``design_account.account_entity_id`` — the platform account entity, resolved-or-created from
  the account's DOMAIN at create AND update (R-D3-2): two accounts sharing a domain converge on
  ONE entity; the same domain in two workspaces yields two DISTINCT entities; a domain-less
  account stays NULL; a changed domain re-stamps and a cleared domain NULLs.

All writes run in rolled-back transactions against the session-migrated DB.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_db import db_lifespan
from clue_design import accounts as design_accounts
from clue_design import brand as design_brand
from clue_design.joins import DEFAULT_BRAND_NAME
from tests.design.conftest import run_async


async def _seed_ws(conn: AsyncConnection, tag: str = "join") -> str:
    ws = f"ws_test_{tag}_{uuid4().hex[:10]}"
    await conn.execute(
        text("INSERT INTO workspace (workspace_id, name) VALUES (:w, :w)"), {"w": ws}
    )
    return ws


async def _seed_brand(conn: AsyncConnection, workspace_id: str, name: str) -> str:
    brand_id = f"brd_{uuid4().hex}"
    await conn.execute(
        text("INSERT INTO brand (brand_id, workspace_id, name) VALUES (:b, :w, :n)"),
        {"b": brand_id, "w": workspace_id, "n": name},
    )
    return brand_id


def _kit(kit_id: str, version: int = 1) -> dict[str, Any]:
    return {
        "id": kit_id,
        "version": version,
        "name": f"{kit_id} v{version}",
        "approval_status": "draft",
        "tokens": {},
    }


async def _create_kit(conn: AsyncConnection, workspace_id: str, **kwargs: Any) -> dict[str, Any]:
    return await design_brand.create_brand_kit(
        conn,
        workspace_id=workspace_id,
        brand_kit=_kit(f"kit_{uuid4().hex[:10]}"),
        brand_summary={},
        diagnostics=[],
        source="manual",
        **kwargs,
    )


async def _publish_next(
    conn: AsyncConnection, workspace_id: str, kit_id: str, base_version: int, **kwargs: Any
) -> dict[str, Any]:
    return await design_brand.publish_next_brand_kit_version(
        conn,
        workspace_id=workspace_id,
        brand_kit=_kit(kit_id, base_version),
        brand_summary={},
        diagnostics=[],
        source="website",
        expected_base_version=base_version,
        **kwargs,
    )


async def _brand_names(conn: AsyncConnection, workspace_id: str) -> list[str]:
    rows = await conn.execute(
        text("SELECT name FROM brand WHERE workspace_id = :w ORDER BY name"), {"w": workspace_id}
    )
    return [row.name for row in rows]


# --- brand join (R-D3-1) ---------------------------------------------------------------------


def test_single_brand_workspace_stamps_that_brand(require_design_db: None) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn, "brand1")
            brand_id = await _seed_brand(conn, ws, "Acme")
            created = await _create_kit(conn, ws)
            assert created["brand_id"] == brand_id
            # The stamp survives the read path, not just the insert's return.
            listed = await design_brand.list_brand_kits(conn, workspace_id=ws)
            assert [row["brand_id"] for row in listed] == [brand_id]
            await txn.rollback()

    run_async(_check())


def test_brandless_workspace_gets_one_default_brand_reused_by_later_kits(
    require_design_db: None,
) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn, "brand0")
            first = await _create_kit(conn, ws)
            assert first["brand_id"] is not None
            assert str(first["brand_id"]).startswith("brd_")
            assert await _brand_names(conn, ws) == [DEFAULT_BRAND_NAME]
            # The SECOND kit reuses the default brand — the workspace never grows a second one.
            second = await _create_kit(conn, ws)
            assert second["brand_id"] == first["brand_id"]
            assert await _brand_names(conn, ws) == [DEFAULT_BRAND_NAME]
            await txn.rollback()

    run_async(_check())


def test_multi_brand_workspace_leaves_the_stamp_null(require_design_db: None) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn, "brand2")
            await _seed_brand(conn, ws, "Acme")
            await _seed_brand(conn, ws, "Zenith")
            created = await _create_kit(conn, ws)
            assert created["brand_id"] is None
            # Ambiguity must not be "resolved" by inventing a third (default) brand.
            assert await _brand_names(conn, ws) == ["Acme", "Zenith"]
            await txn.rollback()

    run_async(_check())


def test_explicit_brand_id_wins_over_resolution(require_design_db: None) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn, "brandx")
            await _seed_brand(conn, ws, "Acme")
            chosen = await _seed_brand(conn, ws, "Zenith")
            # Multi-brand would resolve to NULL; the explicit id overrides that.
            created = await _create_kit(conn, ws, brand_id=chosen)
            assert created["brand_id"] == chosen
            await txn.rollback()

    run_async(_check())


def test_explicit_foreign_workspace_brand_is_refused(require_design_db: None) -> None:
    """Fail-closed structurally: ``design_brand_kit_brand_fk`` is composite, so a brand from
    another workspace is unrepresentable rather than validated by hand."""

    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws_a = await _seed_ws(conn, "brand_a")
            ws_b = await _seed_ws(conn, "brand_b")
            foreign = await _seed_brand(conn, ws_b, "Foreign")
            nested = await conn.begin_nested()
            with pytest.raises(IntegrityError):
                await _create_kit(conn, ws_a, brand_id=foreign)
            await nested.rollback()
            await txn.rollback()

    run_async(_check())


# --- brand join across VERSIONS (brand-kit slice 4, 2026-08-18) ------------------------------
#
# A kit's later versions belong to the brand its first version was bound to. Re-resolving per
# version made a re-extract of a linked kit silently UNLINK it the moment its workspace grew a
# second brand — the heuristic's honest "several brands, I cannot tell" answer applied to a
# question that was already answered at birth.


def test_next_version_inherits_the_lineage_brand_even_in_a_multi_brand_workspace(
    require_design_db: None,
) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn, "inherit")
            brand_id = await _seed_brand(conn, ws, "Acme")
            kit_id = f"kit_{uuid4().hex[:10]}"
            born = await design_brand.create_brand_kit(
                conn,
                workspace_id=ws,
                brand_kit=_kit(kit_id),
                brand_summary={},
                diagnostics=[],
                source="website",
            )
            assert born["brand_id"] == brand_id
            # The workspace becomes multi-brand: resolution would now answer NULL.
            await _seed_brand(conn, ws, "Zenith")
            assert (await _create_kit(conn, ws))["brand_id"] is None
            # …but this kit's next version keeps the brand its lineage already names.
            second = await _publish_next(conn, ws, kit_id, 1)
            assert second["version"] == 2
            assert second["brand_id"] == brand_id
            # And so does the one after it, off the inherited stamp.
            assert (await _publish_next(conn, ws, kit_id, 2))["brand_id"] == brand_id
            await txn.rollback()

    run_async(_check())


def test_next_version_of_an_unlinked_kit_still_resolves(require_design_db: None) -> None:
    """Nothing to inherit is not a reason to skip resolution: a kit born NULL in a workspace
    that has since settled on ONE brand gets stamped like any other write."""

    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn, "inherit0")
            first = await _seed_brand(conn, ws, "Acme")
            second = await _seed_brand(conn, ws, "Zenith")
            kit_id = f"kit_{uuid4().hex[:10]}"
            born = await design_brand.create_brand_kit(
                conn,
                workspace_id=ws,
                brand_kit=_kit(kit_id),
                brand_summary={},
                diagnostics=[],
                source="website",
            )
            assert born["brand_id"] is None
            await conn.execute(
                text("DELETE FROM brand WHERE brand_id = :b AND workspace_id = :w"),
                {"b": second, "w": ws},
            )
            assert (await _publish_next(conn, ws, kit_id, 1))["brand_id"] == first
            await txn.rollback()

    run_async(_check())


def test_an_explicit_brand_id_still_wins_over_the_inherited_one(require_design_db: None) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn, "inherit_x")
            born_with = await _seed_brand(conn, ws, "Acme")
            chosen = await _seed_brand(conn, ws, "Zenith")
            kit_id = f"kit_{uuid4().hex[:10]}"
            born = await design_brand.create_brand_kit(
                conn,
                workspace_id=ws,
                brand_kit=_kit(kit_id),
                brand_summary={},
                diagnostics=[],
                source="website",
                brand_id=born_with,
            )
            assert born["brand_id"] == born_with
            published = await _publish_next(conn, ws, kit_id, 1, brand_id=chosen)
            assert published["brand_id"] == chosen
            await txn.rollback()

    run_async(_check())


# --- account join (R-D3-2) -------------------------------------------------------------------


async def _entity(conn: AsyncConnection, entity_id: str) -> Any:
    return (
        await conn.execute(
            text(
                "SELECT canonical_name, primary_domain, status, workspace_id"
                " FROM account_entity WHERE id = CAST(:i AS uuid)"
            ),
            {"i": entity_id},
        )
    ).one()


async def _create_account(
    conn: AsyncConnection, workspace_id: str, name: str, domain: str | None
) -> dict[str, Any]:
    return await design_accounts.create_web_account(
        conn,
        workspace_id=workspace_id,
        account_id=f"acc_{uuid4().hex[:10]}",
        name=name,
        domain=domain,
        logo_asset_id=None,
        data={},
        notes=None,
    )


def test_account_with_domain_creates_and_reuses_one_candidate_entity(
    require_design_db: None,
) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn, "acct")
            first = await _create_account(conn, ws, "Acme Corp", "acme.com")
            entity_id = first["account_entity_id"]
            assert entity_id is not None
            row = await _entity(conn, entity_id)
            assert row.canonical_name == "Acme Corp"
            assert row.primary_domain == "acme.com"
            assert row.status == "candidate"
            assert row.workspace_id == ws
            # A SECOND account on the same domain resolves onto the SAME entity.
            second = await _create_account(conn, ws, "Acme (EMEA)", "acme.com")
            assert second["account_entity_id"] == entity_id
            await txn.rollback()

    run_async(_check())


def test_account_without_domain_stays_unjoined(require_design_db: None) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn, "acct_nd")
            assert (await _create_account(conn, ws, "Nameless", None))["account_entity_id"] is None
            # A blank domain is NO domain, not a resolvable key.
            assert (await _create_account(conn, ws, "Blank", "  "))["account_entity_id"] is None
            await txn.rollback()

    run_async(_check())


def test_update_adding_changing_and_clearing_the_domain_restamps(
    require_design_db: None,
) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn, "acct_up")
            account = await _create_account(conn, ws, "Acme Corp", None)
            account_id = account["account_id"]
            assert account["account_entity_id"] is None

            added = await design_accounts.update_web_account(
                conn, workspace_id=ws, account_id=account_id, patch={"domain": "acme.com"}
            )
            first_entity = added["account_entity_id"]
            assert first_entity is not None
            assert (await _entity(conn, first_entity)).primary_domain == "acme.com"

            # An unrelated patch leaves the stamp alone.
            renamed = await design_accounts.update_web_account(
                conn, workspace_id=ws, account_id=account_id, patch={"notes": "hi"}
            )
            assert renamed["account_entity_id"] == first_entity

            changed = await design_accounts.update_web_account(
                conn, workspace_id=ws, account_id=account_id, patch={"domain": "acme.io"}
            )
            second_entity = changed["account_entity_id"]
            assert second_entity is not None and second_entity != first_entity
            assert (await _entity(conn, second_entity)).primary_domain == "acme.io"

            cleared = await design_accounts.update_web_account(
                conn, workspace_id=ws, account_id=account_id, patch={"domain": None}
            )
            assert cleared["account_entity_id"] is None
            await txn.rollback()

    run_async(_check())


def test_same_domain_in_two_workspaces_yields_two_entities(require_design_db: None) -> None:
    """Accounts are workspace-local: no global account identity, no cross-tenant reuse."""

    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws_a = await _seed_ws(conn, "acct_a")
            ws_b = await _seed_ws(conn, "acct_b")
            in_a = await _create_account(conn, ws_a, "Acme Corp", "acme.com")
            in_b = await _create_account(conn, ws_b, "Acme Corp", "acme.com")
            assert in_a["account_entity_id"] != in_b["account_entity_id"]
            assert (await _entity(conn, in_a["account_entity_id"])).workspace_id == ws_a
            assert (await _entity(conn, in_b["account_entity_id"])).workspace_id == ws_b
            await txn.rollback()

    run_async(_check())
