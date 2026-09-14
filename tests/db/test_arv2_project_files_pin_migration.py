"""The per-turn project-files pin table (project context files, Task 1).

A production Head-of-ABM turn opens on a compiled set of per-project files (``status.md``,
``decisions.md``) seeded under ``inputs/project/``. Those files are recompiled as the project
moves, so a turn that resolved "the current files" independently on every attempt could seed one
set, crash, and seed a different set on the retry. This table applies the discipline
``agent_turn_knowledge_pin`` applies to brand documents: one insert-once row per turn, written
before composition, carrying the exact file refs and a digest over them.

The digest is a bare 64-hex sha256 (never a ``sha256:``-prefixed one), enforced by a CHECK — so a
writer that stamps the wrong shape fails at the database rather than producing a pin nobody can
compare. The row is append-only: a trigger refuses every UPDATE and DELETE, so "what this turn
opened with" cannot be edited after the fact.
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
from tests._identity import seed_principal
from tests._workspace import seed_project

from .conftest import run_async

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ALEMBIC_INI = _REPO_ROOT / "alembic.ini"
#: The revision this migration chains off — the revision a downgrade lands on.
_PREVIOUS_REVISION = "c90aaea30a88"
_TABLE = "agent_turn_project_files"


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


async def _trigger_names(conn: AsyncConnection) -> set[str]:
    rows = await conn.execute(
        text(
            "SELECT tgname FROM pg_trigger WHERE tgrelid = to_regclass(:name) AND NOT tgisinternal"
        ),
        {"name": _TABLE},
    )
    return {str(row.tgname) for row in rows}


async def _index_definitions(conn: AsyncConnection) -> dict[str, str]:
    rows = await conn.execute(
        text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = :name"),
        {"name": _TABLE},
    )
    return {str(row.indexname): str(row.indexdef) for row in rows}


async def _seed_submitted_turn(conn: AsyncConnection, *, workspace_id: str) -> tuple[str, str]:
    """Materialise a real ``agent_turn_submission`` and return ``(turn_id, project_id)``.

    Both of the pin's foreign keys are composite on ``workspace_id``, so only a genuinely
    submitted turn in a genuine project can be pinned — which is what this seeds.
    """

    project = await seed_project(conn, workspace_id, name="Project files pin")
    principal = await seed_principal(
        conn, workspace_id=workspace_id, user_id="usr-project-files-pin"
    )
    sha = "c" * 64
    artifact_key = f"{workspace_id}/{sha}"
    await conn.execute(
        text(
            "INSERT INTO artifact (storage_key, workspace_id, content_sha256, media_type, "
            "size_bytes) VALUES (:key, :workspace, :sha, 'text/plain', 11)"
        ),
        {"key": artifact_key, "workspace": workspace_id, "sha": sha},
    )
    onboarding_input_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO onboarding_input "
            "(id, workspace_id, brand_id, project_id, kind, artifact_key, content_sha256, actor) "
            "VALUES (:id, :workspace, :brand, :project, 'user_turn', :key, :sha, 'human')"
        ),
        {
            "id": onboarding_input_id,
            "workspace": workspace_id,
            "brand": project.brand_id,
            "project": project.project_id,
            "key": artifact_key,
            "sha": sha,
        },
    )
    thread_id = "thr-project-files-pin"
    await conn.execute(
        text(
            "INSERT INTO agent_thread (id, workspace_id, project_id) "
            "VALUES (:thread, :workspace, :project)"
        ),
        {"thread": thread_id, "workspace": workspace_id, "project": project.project_id},
    )
    turn_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO agent_turn_submission "
            "(turn_id, workspace_id, project_id, thread_id, submitted_by_user_id, "
            " submitted_via_membership_id, onboarding_input_id, message_artifact_key, "
            " message_sha256) "
            "VALUES (:turn, :workspace, :project, :thread, :user, :membership, :input, :key, :sha)"
        ),
        {
            "turn": turn_id,
            "workspace": workspace_id,
            "project": project.project_id,
            "thread": thread_id,
            "user": principal.user_id,
            "membership": principal.membership_id,
            "input": onboarding_input_id,
            "key": artifact_key,
            "sha": sha,
        },
    )
    return str(turn_id), project.project_id


@pytest.mark.usefixtures("require_db")
def test_the_project_files_pin_table_carries_its_columns_anchors_guard_and_index() -> None:
    async def scenario() -> tuple[
        dict[str, tuple[str, str]], dict[str, str], set[str], dict[str, str]
    ]:
        async with db_lifespan() as engine, engine.connect() as conn:
            assert await _table_exists(conn)
            return (
                await _columns(conn),
                await _constraint_definitions(conn),
                await _trigger_names(conn),
                await _index_definitions(conn),
            )

    columns, constraints, triggers, indexes = run_async(scenario())

    assert columns["turn_id"] == ("uuid", "NO")
    assert columns["workspace_id"] == ("text", "NO")
    assert columns["project_id"] == ("text", "NO")
    assert columns["files"] == ("jsonb", "NO")
    assert columns["files_sha256"] == ("text", "NO")
    assert columns["pinned_at"] == ("timestamp with time zone", "NO")

    definitions = "\n".join(constraints.values()).replace("::text", "")
    # The turn anchor is the one agent_turn_knowledge_pin uses, so a pin can only name a turn that
    # was really submitted in its own workspace; the project anchor is composite for the same
    # reason — no pin can name another tenant's project.
    assert "FOREIGN KEY (turn_id, workspace_id) REFERENCES agent_turn_submission" in definitions
    assert "FOREIGN KEY (project_id, workspace_id) REFERENCES project" in definitions
    assert "PRIMARY KEY (turn_id)" in definitions
    assert "jsonb_typeof(files) = 'array'" in definitions
    assert "files_sha256 ~ '^[0-9a-f]{64}$'" in definitions

    assert "agent_turn_project_files_append_only" in triggers
    assert indexes["agent_turn_project_files_project"].endswith(
        "(workspace_id, project_id, pinned_at DESC)"
    )


@pytest.mark.usefixtures("require_db")
def test_a_malformed_files_digest_is_refused() -> None:
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
                        "INSERT INTO agent_turn_project_files "
                        "(turn_id, workspace_id, project_id, files, files_sha256) "
                        "VALUES (:turn, 'ws-pf-check', 'prj-pf-check', '[]'::jsonb, :digest)"
                    ),
                    {"turn": uuid4(), "digest": f"sha256:{'a' * 64}"},
                )
            finally:
                await trans.rollback()
                await conn.close()

    with pytest.raises(DBAPIError, match="agent_turn_project_files_sha256"):
        run_async(scenario())


@pytest.mark.usefixtures("require_db")
def test_a_pinned_row_cannot_be_edited_afterwards() -> None:
    """A real pin inserts once; the append-only trigger refuses any later UPDATE."""

    async def scenario() -> None:
        async with db_lifespan() as engine:
            conn = await engine.connect()
            trans = await conn.begin()
            try:
                turn_id, project_id = await _seed_submitted_turn(conn, workspace_id="ws-pf-append")
                await conn.execute(
                    text(
                        "INSERT INTO agent_turn_project_files "
                        "(turn_id, workspace_id, project_id, files, files_sha256) "
                        "VALUES (:turn, :workspace, :project, :files, :digest)"
                    ),
                    {
                        "turn": turn_id,
                        "workspace": "ws-pf-append",
                        "project": project_id,
                        "files": '[{"path": "inputs/project/status.md"}]',
                        "digest": "b" * 64,
                    },
                )
                await conn.execute(
                    text(
                        "UPDATE agent_turn_project_files SET files_sha256 = :digest "
                        "WHERE turn_id = :turn"
                    ),
                    {"turn": turn_id, "digest": "d" * 64},
                )
            finally:
                await trans.rollback()
                await conn.close()

    with pytest.raises(DBAPIError, match="agent_turn_project_files is append-only"):
        run_async(scenario())


@pytest.mark.usefixtures("require_db")
def test_the_project_files_pin_table_round_trips_down_and_up() -> None:
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
