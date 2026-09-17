"""Installed-schema guards for the Track O substrate (ARV2-ONBOARDING-PLAN.md §3, §6)."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest
from sqlalchemy import text

from clue_db import db_lifespan

from .conftest import run_async

_REPO_ROOT = Path(__file__).resolve().parents[2]
_VERSIONS = _REPO_ROOT / "alembic" / "versions"


def _migration_module(prefix: str):
    """Load one migration module by its file-name prefix (they are not importable by name)."""
    (path,) = _VERSIONS.glob(f"{prefix}_*.py")
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _onboarding_migration():
    (path,) = _VERSIONS.glob("*_arv2_onboarding_substrate.py")
    return _migration_module(path.stem.split("_")[0])


async def _constraints(conn, table: str) -> dict[str, str]:
    rows = await conn.execute(
        text(
            "SELECT conname, pg_get_constraintdef(oid) AS definition FROM pg_constraint "
            "WHERE conrelid = CAST(:table AS regclass)"
        ),
        {"table": table},
    )
    return {str(row.conname): str(row.definition) for row in rows}


async def _indexes(conn, table: str) -> dict[str, str]:
    rows = await conn.execute(
        text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = :table"),
        {"table": table},
    )
    return {str(row.indexname): str(row.indexdef) for row in rows}


@pytest.mark.usefixtures("require_db")
def test_the_three_onboarding_tables_carry_their_state_contract() -> None:
    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn:
            run = await _constraints(conn, "onboarding_run")
            step = await _constraints(conn, "onboarding_step")
            doc = await _constraints(conn, "brand_knowledge_document")
            doc_indexes = await _indexes(conn, "brand_knowledge_document")

        for status in ("queued", "running", "completed", "completed_with_gaps", "failed"):
            assert status in run["onboarding_run_status"]
        assert "finished_at IS NULL" in run["onboarding_run_finished_when_terminal"]
        assert "brand" in run["onboarding_run_brand_fk"]

        for kind in (
            "overview",
            "lineup",
            "catalog_sync",
            "reviews",
            "synthesis",
            "product_research",
        ):
            assert kind in step["onboarding_step_kind"]
        assert "'fast'" in step["onboarding_step_phase"]
        assert "'background'" in step["onboarding_step_phase"]
        assert "failure_code IS NOT NULL" in step["onboarding_step_failure_pair"]
        assert "brand_knowledge_document" in step["onboarding_step_output_document_fk"]

        # Tenancy is structural: a child pins (parent, workspace) as one unit.
        assert "onboarding_run_workspace_anchor" in run
        assert "(run_id, workspace_id)" in step["onboarding_step_run_fk"]
        assert "(produced_by_step_id, workspace_id)" in doc["brand_knowledge_document_step_fk"]

        for status in (
            "running",
            "ready",
            "empty",
            "failed",
            "proposed",
            "confirmed",
            "superseded",
        ):
            assert status in doc["brand_knowledge_document_status"]
        # The folder and kind CHECKs this migration created were dropped on 2026-09-14 (revision
        # 639d081ad799, free-flowing project documents); the constraint names are gone from
        # pg_constraint, exactly as ``brand_knowledge_document_path_version`` is below.
        assert "brand_knowledge_document_folder" not in doc
        assert "brand_knowledge_document_kind" not in doc
        assert "[0-9a-f]{64}" in doc["brand_knowledge_document_body_when_served"]
        # The path/version identity was a brand-scoped UNIQUE constraint here at O1; the ICP
        # authoring migration re-scoped it per project, so the guarantee now lives in the
        # scope-aware unique index (the constraint name is gone from pg_constraint).
        assert "brand_knowledge_document_path_version" not in doc
        assert "path, version" in doc_indexes["brand_knowledge_document_scope_path_version"]

    run_async(scenario())


@pytest.mark.usefixtures("require_db")
def test_a_document_cannot_be_served_without_bytes() -> None:
    """status=ready with no artifact is the exact lie the CHECK exists to refuse."""
    from sqlalchemy.exc import IntegrityError

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn:
            trans = await conn.begin()
            try:
                await conn.execute(
                    text(
                        "INSERT INTO workspace (workspace_id, name) VALUES ('ws-o1-doc', 'O1') "
                        "ON CONFLICT DO NOTHING"
                    )
                )
                await conn.execute(
                    text(
                        "INSERT INTO brand (brand_id, workspace_id, name) "
                        "VALUES ('brd-o1-doc', 'ws-o1-doc', 'O1') ON CONFLICT DO NOTHING"
                    )
                )
                with pytest.raises(IntegrityError):
                    async with conn.begin_nested():
                        await conn.execute(
                            text(
                                "INSERT INTO brand_knowledge_document "
                                "(document_id, workspace_id, brand_id, folder, path, kind, "
                                " version, status) "
                                "VALUES (gen_random_uuid(), 'ws-o1-doc', 'brd-o1-doc', 'company', "
                                " 'company/overview.md', 'company-overview', 1, 'ready')"
                            )
                        )
                with pytest.raises(IntegrityError):
                    async with conn.begin_nested():
                        await conn.execute(
                            text(
                                "INSERT INTO brand_knowledge_document "
                                "(document_id, workspace_id, brand_id, folder, path, kind, "
                                " version, status) "
                                "VALUES (gen_random_uuid(), 'ws-o1-doc', 'brd-o1-doc', 'company', "
                                " 'product/overview.md', 'company-overview', 1, 'running')"
                            )
                        )
            finally:
                await trans.rollback()

    run_async(scenario())


@pytest.mark.usefixtures("require_db")
def test_a_step_cannot_belong_to_a_workspace_its_run_does_not() -> None:
    """The composite FK is the whole point: a step's workspace IS its run's workspace."""
    from sqlalchemy.exc import IntegrityError

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn:
            trans = await conn.begin()
            try:
                await conn.execute(
                    text(
                        "INSERT INTO workspace (workspace_id, name) "
                        "VALUES ('ws-o1-step', 'O1') ON CONFLICT DO NOTHING"
                    )
                )
                await conn.execute(
                    text(
                        "INSERT INTO brand (brand_id, workspace_id, name) "
                        "VALUES ('brd-o1-step', 'ws-o1-step', 'O1') ON CONFLICT DO NOTHING"
                    )
                )
                await conn.execute(
                    text(
                        "INSERT INTO platform_user (user_id) VALUES ('usr-o1-step') "
                        "ON CONFLICT DO NOTHING"
                    )
                )
                run_id = (
                    await conn.execute(
                        text(
                            "INSERT INTO onboarding_run (run_id, workspace_id, brand_id, "
                            " company_domain, requested_by_user_id) "
                            "VALUES (gen_random_uuid(), 'ws-o1-step', 'brd-o1-step', "
                            " 'example.com', 'usr-o1-step') RETURNING run_id"
                        )
                    )
                ).scalar_one()

                # Same run, its own workspace: accepted.
                await conn.execute(
                    text(
                        "INSERT INTO onboarding_step "
                        "(step_id, run_id, workspace_id, kind, phase) "
                        "VALUES (gen_random_uuid(), :run_id, 'ws-o1-step', 'overview', 'fast')"
                    ),
                    {"run_id": run_id},
                )
                # Same run, a foreign workspace: refused by onboarding_step_run_fk.
                with pytest.raises(IntegrityError):
                    async with conn.begin_nested():
                        await conn.execute(
                            text(
                                "INSERT INTO onboarding_step "
                                "(step_id, run_id, workspace_id, kind, phase) "
                                "VALUES (gen_random_uuid(), :run_id, 'ws-o1-other', "
                                " 'lineup', 'fast')"
                            ),
                            {"run_id": run_id},
                        )
            finally:
                await trans.rollback()

    run_async(scenario())


@pytest.mark.usefixtures("require_db")
def test_the_python_gate_kind_allowlist_mirrors_the_db_check() -> None:
    """insert_gate validates against GATE_KINDS; the trigger/CHECK validate against the DB.

    They must be the same set.
    """
    from clue_api.agent_gate import GATE_KINDS

    async def scenario() -> set[str]:
        async with db_lifespan() as engine, engine.connect() as conn:
            gate = await _constraints(conn, "agent_gate")
        return set(re.findall(r"'([a-z_]+)'", gate["agent_gate_kind"]))

    assert run_async(scenario()) == set(GATE_KINDS)


def _normalized_sql(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def test_the_validator_without_the_product_set_branch_is_the_previous_migrations_text() -> None:
    """downgrade() must reinstall exactly what 064ad0f43519 installed — proven by text, not hope."""
    onboarding = _onboarding_migration()
    previous = _migration_module("064ad0f43519")
    assert _normalized_sql(onboarding._answer_validator(product_set=False)) == _normalized_sql(
        previous._answer_validator(discovery_configuration_revision=True)
    )


def test_the_validator_with_the_branch_adds_only_the_product_set_rules() -> None:
    onboarding = _onboarding_migration()
    with_branch = onboarding._answer_validator(product_set=True)
    for fragment in (
        "presented.kind = 'product_set_selection'",
        "selected_option_refs",
        "jsonb_array_elements_text",
        "candidate ->> 'product_id' = chosen.value",
        "product-set approval cannot repeat a product",
    ):
        assert fragment in with_branch
    assert "presented.kind = 'product_selection'" in with_branch  # the old kind is kept verbatim
