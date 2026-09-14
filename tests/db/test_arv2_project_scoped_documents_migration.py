"""Project-scoped knowledge documents and the personas onboarding run kind (ICP authoring, Task 1).

Until now every ``brand_knowledge_document`` was brand-level: a path/version pair was unique per
``(workspace, brand)``, so a project could not own its own ICP variant, its own personas, or its
own project plan without colliding with the brand's copy. This migration gives a document an
optional ``project_id`` (composite-FK anchored to ``project (project_id, workspace_id)``, so a
document can never name another tenant's project) and an optional ``derived_from_document_id`` that
records the lineage of a project-local variant back to the brand document it was cut from.

Uniqueness moves with the scope: the old ``brand_knowledge_document_path_version`` UNIQUE
constraint is replaced by a unique index over ``COALESCE(project_id, '')``, so the brand-level copy
of ``audience/icp.md@1`` and one project's variant of the same path/version coexist while a second
row in the *same* scope is still refused.

``onboarding_run`` gains a ``kind``: the original whole-brand walk is ``'full'`` (the default, so
every existing row keeps its meaning), and ``'personas'`` is a narrow run that generates personas
for one ICP document. The two halves are welded by ``onboarding_run_persona_shape``: a personas run
must name the ICP document it is generating for, and a full run must not.
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
from tests._workspace import seed_project

from .conftest import run_async

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ALEMBIC_INI = _REPO_ROOT / "alembic.ini"
#: The revision this migration chains off — the revision a downgrade lands on.
_PREVIOUS_REVISION = "6c54be5199c8"
_DOCUMENTS = "brand_knowledge_document"
_RUNS = "onboarding_run"


def _alembic_config() -> Config:
    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "alembic"))
    return cfg


async def _columns(conn: AsyncConnection, table: str) -> dict[str, tuple[str, str]]:
    rows = await conn.execute(
        text(
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
            "WHERE table_name = :name"
        ),
        {"name": table},
    )
    return {str(r.column_name): (str(r.data_type), str(r.is_nullable)) for r in rows}


async def _constraint_definitions(conn: AsyncConnection, table: str) -> dict[str, str]:
    rows = await conn.execute(
        text(
            "SELECT conname, pg_get_constraintdef(oid) AS definition FROM pg_constraint "
            "WHERE conrelid = to_regclass(:name)"
        ),
        {"name": table},
    )
    return {str(row.conname): str(row.definition) for row in rows}


async def _index_definitions(conn: AsyncConnection, table: str) -> dict[str, str]:
    rows = await conn.execute(
        text("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = :name"),
        {"name": table},
    )
    return {str(row.indexname): str(row.indexdef) for row in rows}


async def _insert_document(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    brand_id: str,
    project_id: str | None,
    path: str = "audience/icp.md",
    version: int = 1,
) -> None:
    """Insert a ``running`` (artifact-free) document — the ``body_when_served`` CHECK binds only
    the served statuses, so a scope test needs no artifact rows behind it."""

    await conn.execute(
        text(
            "INSERT INTO brand_knowledge_document "
            "(document_id, workspace_id, brand_id, project_id, folder, path, kind, version, "
            " status) "
            "VALUES (:doc, :workspace, :brand, :project, 'audience', :path, 'icp-definition', "
            " :version, 'running')"
        ),
        {
            "doc": uuid4(),
            "workspace": workspace_id,
            "brand": brand_id,
            "project": project_id,
            "path": path,
            "version": version,
        },
    )


@pytest.mark.usefixtures("require_db")
def test_a_document_carries_its_project_scope_and_lineage() -> None:
    async def scenario() -> tuple[dict[str, tuple[str, str]], dict[str, str], dict[str, str]]:
        async with db_lifespan() as engine, engine.connect() as conn:
            return (
                await _columns(conn, _DOCUMENTS),
                await _constraint_definitions(conn, _DOCUMENTS),
                await _index_definitions(conn, _DOCUMENTS),
            )

    columns, constraints, indexes = run_async(scenario())

    # Both are nullable: a brand-level document names no project and was cut from nothing.
    assert columns["project_id"] == ("text", "YES")
    assert columns["derived_from_document_id"] == ("uuid", "YES")

    definitions = "\n".join(constraints.values()).replace("::text", "")
    # Composite on workspace_id, so no document can scope itself to another tenant's project.
    assert "FOREIGN KEY (project_id, workspace_id) REFERENCES project" in definitions
    assert (
        "FOREIGN KEY (derived_from_document_id) REFERENCES brand_knowledge_document" in definitions
    )
    # Both taxonomies this migration widened were dropped outright on 2026-09-14 (revision
    # 639d081ad799): a document's kind is its own word for itself and its folder is the first
    # segment of the path the agent typed, so the closed lists could only refuse a document
    # somebody wrote. The structural rule that replaced them is still here.
    assert "brand_knowledge_document_folder" not in constraints
    assert "brand_knowledge_document_kind" not in constraints
    assert "path ~~ (folder" in constraints["brand_knowledge_document_path_in_folder"]

    # The brand-scoped UNIQUE is gone; the scope-aware unique index took its place.
    assert "brand_knowledge_document_path_version" not in constraints
    assert "brand_knowledge_document_path_version" not in indexes
    scope_index = indexes["brand_knowledge_document_scope_path_version"]
    assert "UNIQUE INDEX" in scope_index
    assert "COALESCE(project_id, ''" in scope_index
    project_index = indexes["brand_knowledge_document_project"]
    assert "(workspace_id, project_id, path, version DESC)" in project_index
    assert "WHERE (project_id IS NOT NULL)" in project_index


@pytest.mark.usefixtures("require_db")
def test_the_same_path_and_version_coexist_in_two_scopes_but_not_in_one() -> None:
    """Brand-level ``audience/icp.md@1`` and a project's variant of it are different documents;
    a second document in the *same* scope is still refused."""

    async def two_scopes() -> None:
        async with db_lifespan() as engine:
            conn = await engine.connect()
            trans = await conn.begin()
            try:
                project = await seed_project(conn, "ws-icp-scope", name="ICP scope")
                await _insert_document(
                    conn,
                    workspace_id="ws-icp-scope",
                    brand_id=project.brand_id,
                    project_id=None,
                )
                await _insert_document(
                    conn,
                    workspace_id="ws-icp-scope",
                    brand_id=project.brand_id,
                    project_id=project.project_id,
                )
            finally:
                await trans.rollback()
                await conn.close()

    run_async(two_scopes())

    async def same_scope_twice() -> None:
        async with db_lifespan() as engine:
            conn = await engine.connect()
            trans = await conn.begin()
            try:
                project = await seed_project(conn, "ws-icp-scope", name="ICP scope")
                for _ in range(2):
                    await _insert_document(
                        conn,
                        workspace_id="ws-icp-scope",
                        brand_id=project.brand_id,
                        project_id=project.project_id,
                    )
            finally:
                await trans.rollback()
                await conn.close()

    with pytest.raises(DBAPIError, match="brand_knowledge_document_scope_path_version"):
        run_async(same_scope_twice())


@pytest.mark.usefixtures("require_db")
def test_the_onboarding_run_carries_the_personas_kind_and_its_welded_shape() -> None:
    async def scenario() -> tuple[dict[str, tuple[str, str]], dict[str, str], dict[str, str]]:
        async with db_lifespan() as engine, engine.connect() as conn:
            return (
                await _columns(conn, _RUNS),
                await _constraint_definitions(conn, _RUNS),
                await _index_definitions(conn, _RUNS),
            )

    columns, constraints, indexes = run_async(scenario())

    # NOT NULL with a default, so every pre-existing run reads as the full walk it was.
    assert columns["kind"] == ("text", "NO")
    assert columns["project_id"] == ("text", "YES")
    assert columns["persona_icp_document_id"] == ("uuid", "YES")

    definitions = "\n".join(constraints.values()).replace("::text", "")
    assert "FOREIGN KEY (project_id, workspace_id) REFERENCES project" in definitions
    assert (
        "FOREIGN KEY (persona_icp_document_id) REFERENCES brand_knowledge_document" in definitions
    )
    assert "'personas'" in constraints["onboarding_run_kind"]
    assert "onboarding_run_persona_shape" in constraints

    open_index = indexes["onboarding_run_persona_open"]
    assert "(persona_icp_document_id)" in open_index
    assert "personas" in open_index


@pytest.mark.usefixtures("require_db")
def test_a_personas_run_that_names_no_icp_document_is_refused() -> None:
    """The welded shape, proven from the database.

    PostgreSQL evaluates a table's CHECK constraints while forming the row and fires referential
    triggers only afterwards, so this insert reports the shape violation even though its ids name
    nothing. That is the point: a personas run with nothing to generate personas *for* is refused
    before anything else about the row matters.
    """

    async def scenario() -> None:
        async with db_lifespan() as engine:
            conn = await engine.connect()
            trans = await conn.begin()
            try:
                await conn.execute(
                    text(
                        "INSERT INTO onboarding_run "
                        "(run_id, workspace_id, brand_id, company_domain, requested_by_user_id, "
                        " kind, persona_icp_document_id) "
                        "VALUES (:run, 'ws-personas', 'brn-personas', 'example.com', "
                        " 'usr-personas', 'personas', NULL)"
                    ),
                    {"run": uuid4()},
                )
            finally:
                await trans.rollback()
                await conn.close()

    with pytest.raises(DBAPIError, match="onboarding_run_persona_shape"):
        run_async(scenario())


@pytest.mark.usefixtures("require_db")
def test_the_project_scope_round_trips_down_and_up() -> None:
    """down to the previous revision restores the brand-scoped UNIQUE verbatim; up re-scopes it."""

    async def shape() -> tuple[set[str], set[str], set[str]]:
        async with db_lifespan() as engine, engine.connect() as conn:
            return (
                set(await _columns(conn, _DOCUMENTS)),
                set(await _constraint_definitions(conn, _DOCUMENTS)),
                set(await _columns(conn, _RUNS)),
            )

    cfg = _alembic_config()
    command.upgrade(cfg, "head")
    document_columns, document_constraints, run_columns = run_async(shape())
    assert "project_id" in document_columns
    assert "brand_knowledge_document_path_version" not in document_constraints
    assert "kind" in run_columns

    command.downgrade(cfg, _PREVIOUS_REVISION)
    document_columns, document_constraints, run_columns = run_async(shape())
    assert "project_id" not in document_columns
    assert "derived_from_document_id" not in document_columns
    assert "brand_knowledge_document_path_version" in document_constraints
    assert "kind" not in run_columns
    assert "persona_icp_document_id" not in run_columns

    command.upgrade(cfg, "head")
    document_columns, document_constraints, run_columns = run_async(shape())
    assert "project_id" in document_columns
    assert "brand_knowledge_document_path_version" not in document_constraints
    assert "kind" in run_columns
