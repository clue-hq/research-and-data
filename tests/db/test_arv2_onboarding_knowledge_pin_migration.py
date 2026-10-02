"""The per-turn brand-knowledge pin table (ARV2 onboarding O6, Task 2).

A production conversation turn pins the brand's current servable knowledge documents once, before
composition, and every later attempt of that turn reads the same pin. The durable half of that
guarantee is this table: one insert-once row per turn, anchored to the same submission the scope
pin is anchored to, carrying the document refs and a digest over them.

The digest is a bare 64-hex sha256 (never a ``sha256:``-prefixed one), enforced by a CHECK — so a
writer that stamps the wrong shape fails at the database rather than producing a pin nobody can
compare.
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
_PREVIOUS_REVISION = "63294c3ce019"
_TABLE = "agent_turn_knowledge_pin"


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
def test_the_knowledge_pin_table_carries_its_columns_anchors_and_digest_check() -> None:
    async def scenario() -> tuple[dict[str, tuple[str, str]], dict[str, str]]:
        async with db_lifespan() as engine, engine.connect() as conn:
            assert await _table_exists(conn)
            return await _columns(conn), await _constraint_definitions(conn)

    columns, constraints = run_async(scenario())

    assert columns["turn_id"] == ("uuid", "NO")
    assert columns["workspace_id"] == ("text", "NO")
    assert columns["brand_id"] == ("text", "NO")
    assert columns["documents"] == ("jsonb", "NO")
    assert columns["documents_sha256"] == ("text", "NO")
    assert columns["pinned_at"] == ("timestamp with time zone", "NO")

    definitions = "\n".join(constraints.values())
    # The turn anchor is the one ``agent_turn_scope_pin`` uses, so a pin can only name a turn that
    # was really submitted in its own workspace.
    assert "FOREIGN KEY (turn_id, workspace_id) REFERENCES agent_turn_submission" in definitions
    assert "FOREIGN KEY (brand_id, workspace_id) REFERENCES brand" in definitions
    assert "PRIMARY KEY (turn_id)" in definitions
    assert "documents_sha256 ~ '^[0-9a-f]{64}$'" in definitions.replace("::text", "")


@pytest.mark.usefixtures("require_db")
def test_a_malformed_documents_digest_is_refused() -> None:
    """A ``sha256:``-prefixed (or otherwise malformed) digest cannot reach the table.

    PostgreSQL evaluates a table's CHECK constraints while forming the row and fires referential
    triggers only afterwards, so this insert reports the digest violation even though its ids name
    nothing. That is the point: the shape is refused before anything else about the row matters.
    The transaction is rolled back either way.
    """

    async def scenario() -> None:
        async with db_lifespan() as engine:
            conn = await engine.connect()
            trans = await conn.begin()
            try:
                await conn.execute(
                    text(
                        "INSERT INTO agent_turn_knowledge_pin "
                        "(turn_id, workspace_id, brand_id, documents, documents_sha256) "
                        "VALUES (:turn, 'ws-o6-check', 'brn-o6-check', '[]'::jsonb, :digest)"
                    ),
                    {"turn": uuid4(), "digest": f"sha256:{'a' * 64}"},
                )
            finally:
                await trans.rollback()
                await conn.close()

    with pytest.raises(DBAPIError, match="agent_turn_knowledge_pin_documents_sha256"):
        run_async(scenario())


@pytest.mark.usefixtures("require_db")
def test_the_knowledge_pin_table_round_trips_down_and_up() -> None:
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
