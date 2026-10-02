"""The ``persona`` onboarding step kind (O4 Task 1).

The synthesis split gives each ICP its own persona turn, so an onboarding run now carries one
step per ICP alongside the single ``synthesis`` step. The step vocabulary is a CHECK, so admitting
the new kind is a migration — and its downgrade must fail loudly rather than silently strand rows.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_db import db_lifespan
from clue_spine import create_brand
from tests._identity import seed_principal

from .conftest import run_async

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ALEMBIC_INI = _REPO_ROOT / "alembic.ini"
#: The revision this migration chains off — the revision a downgrade lands on.
_PREVIOUS_REVISION = "a3602967bb73"
_OLD_KINDS = ("overview", "lineup", "catalog_sync", "reviews", "synthesis", "product_research")


def _alembic_config() -> Config:
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "alembic"))
    return cfg


async def _step_kind_check(conn: AsyncConnection) -> str:
    definition = await conn.execute(
        text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'onboarding_step'::regclass AND conname = 'onboarding_step_kind'"
        )
    )
    return str(definition.scalar_one())


async def _read_step_kind_check() -> str:
    async with db_lifespan() as engine, engine.connect() as conn:
        return await _step_kind_check(conn)


@pytest.mark.usefixtures("require_db")
def test_the_step_kind_check_admits_persona_without_dropping_a_kind() -> None:
    definition = run_async(_read_step_kind_check())
    assert "'persona'" in definition
    for kind in _OLD_KINDS:
        assert f"'{kind}'" in definition


@pytest.mark.usefixtures("require_db")
def test_a_persona_step_row_inserts_with_its_icp_subject_ref() -> None:
    """One step per ICP: the kind repeats within a run, and ``subject_ref`` is what separates them.

    The connection is never committed, so every row here rolls back on the way out.
    """

    async def scenario() -> list[str]:
        async with db_lifespan() as engine, engine.connect() as conn:
            workspace_id = "ws-o4-persona-step"
            await seed_principal(conn, workspace_id=workspace_id, user_id="usr-o4-persona")
            brand = await create_brand(conn, workspace_id=workspace_id, name="O4 persona brand")
            run_id = uuid4()
            await conn.execute(
                text(
                    "INSERT INTO onboarding_run (run_id, workspace_id, brand_id, company_domain, "
                    "requested_by_user_id) VALUES (:run, :ws, :brand, 'example.com', :user)"
                ),
                {
                    "run": run_id,
                    "ws": workspace_id,
                    "brand": brand.brand_id,
                    "user": "usr-o4-persona",
                },
            )
            for subject_ref in ("gi-groups", "asc-networks"):
                await conn.execute(
                    text(
                        "INSERT INTO onboarding_step (step_id, run_id, workspace_id, kind, "
                        "subject_ref, phase) "
                        "VALUES (:step, :run, :ws, 'persona', :subject, 'background')"
                    ),
                    {
                        "step": uuid4(),
                        "run": run_id,
                        "ws": workspace_id,
                        "subject": subject_ref,
                    },
                )
            rows = await conn.execute(
                text(
                    "SELECT subject_ref FROM onboarding_step "
                    "WHERE run_id = :run AND kind = 'persona' ORDER BY subject_ref"
                ),
                {"run": run_id},
            )
            return [str(r.subject_ref) for r in rows]

    assert run_async(scenario()) == ["asc-networks", "gi-groups"]


@pytest.mark.usefixtures("require_db")
def test_the_downgrade_refuses_to_strand_a_persona_step() -> None:
    """A downgrade that would orphan live rows fails loudly instead of quietly rewriting history."""

    workspace_id = "ws-o4-persona-downgrade"
    run_id = uuid4()
    step_id = uuid4()

    async def seed() -> None:
        async with db_lifespan() as engine, engine.begin() as conn:
            await seed_principal(conn, workspace_id=workspace_id, user_id="usr-o4-downgrade")
            brand = await create_brand(conn, workspace_id=workspace_id, name="O4 downgrade brand")
            await conn.execute(
                text(
                    "INSERT INTO onboarding_run (run_id, workspace_id, brand_id, company_domain, "
                    "requested_by_user_id) VALUES (:run, :ws, :brand, 'example.com', :user)"
                ),
                {
                    "run": run_id,
                    "ws": workspace_id,
                    "brand": brand.brand_id,
                    "user": "usr-o4-downgrade",
                },
            )
            await conn.execute(
                text(
                    "INSERT INTO onboarding_step (step_id, run_id, workspace_id, kind, "
                    "subject_ref, phase) "
                    "VALUES (:step, :run, :ws, 'persona', 'gi-groups', 'background')"
                ),
                {"step": step_id, "run": run_id, "ws": workspace_id},
            )

    async def cleanup() -> None:
        async with db_lifespan() as engine, engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM onboarding_step WHERE step_id = :step"), {"step": step_id}
            )
            await conn.execute(
                text("DELETE FROM onboarding_run WHERE run_id = :run"), {"run": run_id}
            )

    cfg = _alembic_config()
    command.upgrade(cfg, "head")
    run_async(seed())
    try:
        with pytest.raises(DBAPIError, match="persona onboarding steps exist"):
            command.downgrade(cfg, _PREVIOUS_REVISION)
        # The refusal is transactional: the CHECK is untouched and the DB is still at head.
        assert "'persona'" in run_async(_read_step_kind_check())
    finally:
        run_async(cleanup())
        command.upgrade(cfg, "head")


@pytest.mark.usefixtures("require_db")
def test_the_persona_kind_round_trips_down_and_up() -> None:
    """down to the previous revision drops ``persona`` from the CHECK; up restores it."""

    cfg = _alembic_config()
    command.upgrade(cfg, "head")
    command.downgrade(cfg, _PREVIOUS_REVISION)

    downgraded = run_async(_read_step_kind_check())
    assert "'persona'" not in downgraded
    for kind in _OLD_KINDS:
        assert f"'{kind}'" in downgraded

    command.upgrade(cfg, "head")
    assert "'persona'" in run_async(_read_step_kind_check())
