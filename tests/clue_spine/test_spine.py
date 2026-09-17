"""DB-backed tests for the object spine (Phase A3.2).

CRUD round-trips over workspace-owned brands/projects and brand-owned products, plus the
invalid-states-impossible
constraint battery: the constraints ARE the enforcement (founder ruling), so violations are
asserted as raw ``IntegrityError`` from the DB — never handler logic. Also proves
``project_run.project_id`` (runs execute *for* a project) accepts a valid project and rejects a
dangling one.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_spine import (
    create_brand,
    create_product,
    create_project,
    create_workspace,
    get_brand,
    get_product,
    get_project,
    get_workspace,
    list_brands_for_workspace,
    list_products,
    list_projects,
)

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_spine_db")


async def _seed(conn: AsyncConnection) -> tuple[str, str]:
    """A workspace with its brand; returns (workspace_id, brand_id)."""
    ws = await create_workspace(conn, name="Acme")
    brand = await create_brand(conn, workspace_id=ws.workspace_id, name="Acme Brand")
    return ws.workspace_id, brand.brand_id


# --- CRUD round-trips -------------------------------------------------------
def test_workspace_and_multiple_brands_round_trip() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = await create_workspace(conn, name="Acme")
            assert ws.workspace_id.startswith("ws_")
            assert ws.status == "active"
            assert await get_workspace(conn, ws.workspace_id) == ws
            assert await get_workspace(conn, "ws_missing") is None

            primary = await create_brand(conn, workspace_id=ws.workspace_id, name="Primary")
            secondary = await create_brand(conn, workspace_id=ws.workspace_id, name="Secondary")
            assert primary.brand_id.startswith("brd_")
            assert secondary.brand_id.startswith("brd_")
            assert (
                await get_brand(conn, workspace_id=ws.workspace_id, brand_id=primary.brand_id)
                == primary
            )
            assert await list_brands_for_workspace(conn, ws.workspace_id) == [
                primary,
                secondary,
            ]
            assert await list_brands_for_workspace(conn, "ws_missing") == []

            other = await create_workspace(conn, name="Other")
            assert (
                await get_brand(conn, workspace_id=other.workspace_id, brand_id=primary.brand_id)
                is None
            )
            assert (
                await get_brand(conn, workspace_id=ws.workspace_id, brand_id="brd_missing") is None
            )

            # Legacy ids slot in unchanged (text PK).
            legacy = await create_workspace(conn, name="Legacy", workspace_id="client-42")
            assert legacy.workspace_id == "client-42"

    run_async(scenario())


def test_product_round_trip_and_listing() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            workspace_id, brand_id = await _seed(conn)
            widget = await create_product(
                conn,
                brand_id=brand_id,
                workspace_id=workspace_id,
                name="Widget",
                aliases=("The Widget", "widget-pro"),
            )
            assert widget.product_id.startswith("prd_")
            assert widget.aliases == ("The Widget", "widget-pro")
            assert widget.status == "active"
            assert await get_product(conn, widget.product_id) == widget
            assert await get_product(conn, "prd_missing") is None

            anvil = await create_product(
                conn, brand_id=brand_id, workspace_id=workspace_id, name="Anvil"
            )
            assert anvil.aliases == ()
            assert await list_products(conn, brand_id) == [anvil, widget]  # name-ordered

    run_async(scenario())


def test_project_round_trip_and_status_filter() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            workspace_id, brand_id = await _seed(conn)
            product = await create_product(
                conn, brand_id=brand_id, workspace_id=workspace_id, name="Widget"
            )
            with_product = await create_project(
                conn,
                workspace_id=workspace_id,
                brand_id=brand_id,
                product_id=product.product_id,
                name="Q3 outbound",
            )
            assert with_product.project_id.startswith("prj_")
            assert with_product.status == "draft"
            assert with_product.product_id == product.product_id
            without_product = await create_project(
                conn, workspace_id=workspace_id, brand_id=brand_id, name="Q4 outbound"
            )
            assert without_product.product_id is None
            assert await get_project(conn, with_product.project_id) == with_product
            assert await get_project(conn, "prj_missing") is None

            listed = await list_projects(conn, workspace_id)
            assert set(listed) == {with_product, without_product}
            assert await list_projects(conn, workspace_id, status="draft") == listed
            assert await list_projects(conn, workspace_id, status="archived") == []

    run_async(scenario())


# --- constraints ARE the enforcement ----------------------------------------
def test_projects_can_select_different_brands_in_one_workspace() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            workspace_id, first_brand_id = await _seed(conn)
            second = await create_brand(conn, workspace_id=workspace_id, name="Second Brand")
            first_project = await create_project(
                conn,
                workspace_id=workspace_id,
                brand_id=first_brand_id,
                name="First brand project",
            )
            second_project = await create_project(
                conn,
                workspace_id=workspace_id,
                brand_id=second.brand_id,
                name="Second brand project",
            )
            assert first_project.brand_id == first_brand_id
            assert second_project.brand_id == second.brand_id

    run_async(scenario())


def test_product_cannot_point_at_brand_in_another_workspace() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            _, brand_id = await _seed(conn)
            other = await create_workspace(conn, name="Other")
            with pytest.raises(IntegrityError, match="product_brand_fk"):
                await create_product(
                    conn, brand_id=brand_id, workspace_id=other.workspace_id, name="Smuggled"
                )

    run_async(scenario())


def test_project_cannot_point_at_brand_in_another_workspace() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            _, brand_id = await _seed(conn)
            other = await create_workspace(conn, name="Other")
            with pytest.raises(IntegrityError, match="project_brand_fk"):
                await create_project(
                    conn,
                    workspace_id=other.workspace_id,
                    brand_id=brand_id,
                    name="Smuggled",
                )

    run_async(scenario())


def test_project_cannot_use_product_from_another_workspace() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            workspace_id, brand_id = await _seed(conn)
            product = await create_product(
                conn, brand_id=brand_id, workspace_id=workspace_id, name="Widget"
            )
            other_ws = await create_workspace(conn, name="Other")
            other_brand = await create_brand(
                conn, workspace_id=other_ws.workspace_id, name="Other Brand"
            )
            with pytest.raises(IntegrityError, match="project_product_fk"):
                await create_project(
                    conn,
                    workspace_id=other_ws.workspace_id,
                    brand_id=other_brand.brand_id,
                    product_id=product.product_id,
                    name="Smuggled",
                )

    run_async(scenario())


def test_duplicate_product_name_under_brand_rejected_by_constraint() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            workspace_id, brand_id = await _seed(conn)
            await create_product(conn, brand_id=brand_id, workspace_id=workspace_id, name="Widget")
            with pytest.raises(IntegrityError, match="product_name_per_brand"):
                await create_product(
                    conn, brand_id=brand_id, workspace_id=workspace_id, name="Widget"
                )

    run_async(scenario())


# --- project_run executes FOR a project ------------------------------------
_INSERT_RUN = text(
    """
    INSERT INTO project_run (id, project_id, brand_id, workspace_id, icp_key, icp_version)
    VALUES (:id, :project_id, :brand_id, :workspace_id, :icp_key, 1)
    RETURNING project_id
    """
)


def test_project_run_accepts_valid_project_id() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            workspace_id, brand_id = await _seed(conn)
            project = await create_project(
                conn, workspace_id=workspace_id, brand_id=brand_id, name="Q3 outbound"
            )
            result = await conn.execute(
                _INSERT_RUN,
                {
                    "id": uuid4(),
                    "workspace_id": workspace_id,
                    "icp_key": "default",
                    "project_id": project.project_id,
                    "brand_id": project.brand_id,
                },
            )
            assert result.scalar_one() == project.project_id

    run_async(scenario())


def test_project_run_rejects_dangling_project_id() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            workspace_id, brand_id = await _seed(conn)
            with pytest.raises(IntegrityError, match="project_run_project_context_fk"):
                await conn.execute(
                    _INSERT_RUN,
                    {
                        "id": uuid4(),
                        "workspace_id": workspace_id,
                        "icp_key": "default",
                        "project_id": "prj_missing",
                        "brand_id": brand_id,
                    },
                )

    run_async(scenario())


def test_project_run_rejects_a_different_same_workspace_brand() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            workspace_id, project_brand_id = await _seed(conn)
            other_brand = await create_brand(
                conn, workspace_id=workspace_id, name="Different sender"
            )
            project = await create_project(
                conn,
                workspace_id=workspace_id,
                brand_id=project_brand_id,
                name="Pinned sender project",
            )
            with pytest.raises(IntegrityError, match="project_run_project_context_fk"):
                await conn.execute(
                    _INSERT_RUN,
                    {
                        "id": uuid4(),
                        "workspace_id": workspace_id,
                        "icp_key": "default",
                        "project_id": project.project_id,
                        "brand_id": other_brand.brand_id,
                    },
                )

    run_async(scenario())


def test_create_workspace_has_a_system_hostname_under_the_default_suffix() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = await create_workspace(conn, name="Hostname Default")
            row = (
                await conn.execute(
                    text(
                        "SELECT hostname FROM workspace_hostname "
                        "WHERE workspace_id = :w AND kind = 'system'"
                    ),
                    {"w": ws.workspace_id},
                )
            ).first()
            assert row is not None and row[0] == "hostname-default.pages.cluehq.ai"

    run_async(scenario())
