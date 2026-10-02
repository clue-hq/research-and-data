"""The durable project ICP pin table (ARV2 onboarding O6, Task 9b).

A project pins exactly one confirmed ICP document version, by document id, and the pin is written
when a human approves the ICP confirmation gate. The durable half of that ruling is this table:
append-only rows sequenced by ``pin_seq``, the current pin being the greatest one, each anchored to
its project, its brand and the exact document version it names.

Two shapes are asserted from the database rather than trusted from the writer: the digest is a bare
64-hex sha256 (so a launch can compare it to ``brand_knowledge_document.artifact_sha256`` without
normalizing), and the append-only trigger refuses both UPDATE and DELETE — a pin that could be
edited would not be a receipt of what a human approved.
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

from .conftest import run_async

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ALEMBIC_INI = _REPO_ROOT / "alembic.ini"
#: The revision this migration chains off — the revision a downgrade lands on.
_PREVIOUS_REVISION = "fcb4a7b0b465"
_TABLE = "project_icp_pin"


def _alembic_config() -> Config:
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "alembic"))
    return cfg


async def _table_exists(conn: AsyncConnection) -> bool:
    found = await conn.execute(text("SELECT to_regclass(:name)"), {"name": _TABLE})
    return found.scalar_one() is not None


async def _constraint_definitions(conn: AsyncConnection) -> dict[str, str]:
    rows = await conn.execute(
        text(
            "SELECT conname, pg_get_constraintdef(oid) AS definition FROM pg_constraint "
            "WHERE conrelid = to_regclass(:name)"
        ),
        {"name": _TABLE},
    )
    return {str(row.conname): str(row.definition) for row in rows}


async def _columns(conn: AsyncConnection) -> dict[str, tuple[str, str]]:
    rows = await conn.execute(
        text(
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
            "WHERE table_name = :name"
        ),
        {"name": _TABLE},
    )
    return {str(r.column_name): (str(r.data_type), str(r.is_nullable)) for r in rows}


@pytest.mark.usefixtures("require_db")
def test_the_project_icp_pin_table_carries_its_columns_anchors_and_digest_check() -> None:
    async def scenario() -> tuple[dict[str, tuple[str, str]], dict[str, str]]:
        async with db_lifespan() as engine, engine.connect() as conn:
            assert await _table_exists(conn)
            return await _columns(conn), await _constraint_definitions(conn)

    columns, constraints = run_async(scenario())

    assert columns["workspace_id"] == ("text", "NO")
    assert columns["project_id"] == ("text", "NO")
    assert columns["pin_seq"] == ("integer", "NO")
    assert columns["brand_id"] == ("text", "NO")
    assert columns["document_id"] == ("uuid", "NO")
    assert columns["icp_key"] == ("text", "NO")
    assert columns["artifact_key"] == ("text", "NO")
    assert columns["artifact_sha256"] == ("text", "NO")
    # Nullable on purpose: a project may confirm its ICP before it confirms a product set.
    assert columns["product_selection_version"] == ("integer", "YES")
    assert columns["pinned_by_user_id"] == ("text", "NO")
    assert columns["pinned_at"] == ("timestamp with time zone", "NO")

    definitions = "\n".join(constraints.values())
    assert "PRIMARY KEY (project_id, pin_seq)" in definitions
    assert "FOREIGN KEY (project_id, workspace_id) REFERENCES project" in definitions
    assert "FOREIGN KEY (brand_id, workspace_id) REFERENCES brand" in definitions
    assert "FOREIGN KEY (document_id) REFERENCES brand_knowledge_document" in definitions
    assert "artifact_sha256 ~ '^[0-9a-f]{64}$'" in definitions.replace("::text", "")


@pytest.mark.usefixtures("require_db")
def test_the_pin_is_append_only_at_the_database() -> None:
    """The shared append-only trigger fires on both UPDATE and DELETE.

    The refusal itself is proven over real rows in ``tests/api/test_project_icp_pin_db.py``; what
    belongs here is that the migration installed the guard at all, and on both verbs — a pin that
    could be edited or dropped would not be a receipt of what a human approved.
    """

    async def scenario() -> list[tuple[str, str]]:
        async with db_lifespan() as engine, engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT tgname, pg_get_triggerdef(oid) AS definition FROM pg_trigger "
                    "WHERE tgrelid = to_regclass(:name) AND NOT tgisinternal"
                ),
                {"name": _TABLE},
            )
            return [(str(row.tgname), str(row.definition)) for row in rows]

    triggers = run_async(scenario())

    assert [name for name, _ in triggers] == ["project_icp_pin_append_only"]
    definition = triggers[0][1]
    assert "BEFORE DELETE OR UPDATE" in definition
    assert "execution_reject_append_only_mutation()" in definition


@pytest.mark.usefixtures("require_db")
def test_a_malformed_artifact_digest_is_refused() -> None:
    """A ``sha256:``-prefixed (or otherwise malformed) digest cannot reach the table.

    PostgreSQL evaluates a table's CHECK constraints while forming the row and fires referential
    triggers only afterwards, so this insert reports the digest violation even though its ids name
    nothing. That is the point: the shape is refused before anything else about the row matters.
    """

    async def scenario() -> None:
        async with db_lifespan() as engine:
            conn = await engine.connect()
            trans = await conn.begin()
            try:
                await conn.execute(
                    text(
                        "INSERT INTO project_icp_pin (workspace_id, project_id, pin_seq, "
                        "  brand_id, document_id, icp_key, artifact_key, artifact_sha256, "
                        "  pinned_by_user_id) "
                        "VALUES ('ws-o6-check', 'prj-o6-check', 1, 'brn-o6-check', :doc, 'gi', "
                        "  'ws/key', :digest, 'usr-o6-check')"
                    ),
                    {"doc": uuid4(), "digest": f"sha256:{'a' * 64}"},
                )
            finally:
                await trans.rollback()
                await conn.close()

    with pytest.raises(DBAPIError, match="project_icp_pin_artifact_sha256"):
        run_async(scenario())


@pytest.mark.usefixtures("require_db")
def test_the_project_icp_pin_table_round_trips_down_and_up() -> None:
    """down to the previous revision drops the table; up restores it."""

    async def exists() -> bool:
        async with db_lifespan() as engine, engine.connect() as conn:
            return await _table_exists(conn)

    cfg = _alembic_config()
    command.upgrade(cfg, "head")
    assert run_async(exists()) is True

    command.downgrade(cfg, _PREVIOUS_REVISION)
    assert run_async(exists()) is False

    command.upgrade(cfg, "head")
    assert run_async(exists()) is True
