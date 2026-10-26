"""Workspace onboarding operations migration (spec 2026-10-25 §12).

The ``repair`` onboarding run kind with its planned steps, the ``workspace_operation`` audit
table, and the two design enum values: ``succeeded_with_gaps`` and ``kit_repair``.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests._identity import seed_principal
from tests._workspace import seed_project
from tests.auth.conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_db")

_INSERT_RUN = text(
    "INSERT INTO onboarding_run (run_id, workspace_id, brand_id, company_domain, "
    " requested_by_user_id, kind, planned_steps) "
    "VALUES (:run_id, :ws, :brand, 'acme.com', :user, 'repair', CAST(:planned AS jsonb))"
)


def test_upgrade_adds_repair_kind_operation_table_and_design_enum_values() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-ops-migration"
            project = await seed_project(conn, ws, name="Ops migration")
            await seed_principal(conn, workspace_id=ws, user_id="usr_ops_migration")
            params = {"ws": ws, "brand": project.brand_id, "user": "usr_ops_migration"}
            await conn.execute(_INSERT_RUN, {**params, "run_id": uuid4(), "planned": "[]"})

            savepoint = await conn.begin_nested()
            with pytest.raises(IntegrityError):
                await conn.execute(_INSERT_RUN, {**params, "run_id": uuid4(), "planned": None})
            await savepoint.rollback()

            await conn.execute(
                text(
                    "INSERT INTO workspace_operation (operation_id, operation, workspace_id, actor)"
                    " VALUES (:id, 'repair', :ws, 'operator:a@b.c')"
                ),
                {"id": uuid4(), "ws": ws},
            )
            statuses = (
                await conn.execute(text("SELECT enum_range(NULL::design_ingestion_status)::text"))
            ).scalar_one()
            kinds = (
                await conn.execute(text("SELECT enum_range(NULL::design_ingestion_kind)::text"))
            ).scalar_one()
            assert "succeeded_with_gaps" in statuses
            assert "kit_repair" in kinds

    run_async(scenario())


def test_planned_steps_belong_only_to_repair_runs() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = "ws-ops-migration-full"
            project = await seed_project(conn, ws, name="Ops migration full")
            await seed_principal(conn, workspace_id=ws, user_id="usr_ops_migration_full")
            with pytest.raises(IntegrityError):
                await conn.execute(
                    text(
                        "INSERT INTO onboarding_run (run_id, workspace_id, brand_id, "
                        " company_domain, requested_by_user_id, kind, planned_steps) "
                        "VALUES (:run_id, :ws, :brand, 'acme.com', :user, 'full', '[]')"
                    ),
                    {
                        "run_id": uuid4(),
                        "ws": ws,
                        "brand": project.brand_id,
                        "user": "usr_ops_migration_full",
                    },
                )

    run_async(scenario())


def test_an_operation_needs_a_known_kind_and_a_non_blank_actor() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            for operation, actor in (("delete_everything", "operator:a@b.c"), ("repair", "  ")):
                savepoint = await conn.begin_nested()
                with pytest.raises(IntegrityError):
                    await conn.execute(
                        text(
                            "INSERT INTO workspace_operation "
                            "(operation_id, operation, workspace_id, actor) "
                            "VALUES (:id, :op, 'ws-x', :actor)"
                        ),
                        {"id": uuid4(), "op": operation, "actor": actor},
                    )
                await savepoint.rollback()

    run_async(scenario())
