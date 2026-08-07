"""D1 acceptance tests for the ``design_*`` schema (PD contract §7).

Four properties, straight from the contract:

1. **Enum parity** — every Postgres ``design_*`` enum type mirrors its ``clue_design.enums``
   StrEnum exactly (labels AND definition order), the fleet-precedent lock-step guard.
2. **Immutability triggers** — ``design_web_publish_revision`` rejects UPDATE and DELETE;
   the three custom-component content tables reject UPDATE.
3. **Tenancy isolation** — a cross-workspace composite-FK insert fails with IntegrityError:
   the design tenancy laws are structural, not handler code.
4. **Single alembic head** — offline (no DB): the D1 chain keeps exactly one head, descending
   from the ratified base ``c6d84aa84b79``.

Write-path tests run inside transactions whose asserted failure (or explicit rollback) leaves
the shared dev DB clean.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_db import db_lifespan
from clue_design.enums import DESIGN_PG_ENUMS
from tests.design.conftest import _alembic_config, run_async

_D1_BASE = "c6d84aa84b79"
_SHA = "0" * 64


async def _pg_enum_labels(conn: AsyncConnection, type_name: str) -> list[str]:
    rows = await conn.execute(
        text(
            "SELECT e.enumlabel FROM pg_type t "
            "JOIN pg_enum e ON e.enumtypid = t.oid "
            "WHERE t.typname = :name ORDER BY e.enumsortorder"
        ),
        {"name": type_name},
    )
    return [r[0] for r in rows]


def _ws(tag: str) -> str:
    return f"ws_test_design_{tag}_{uuid4().hex[:12]}"


async def _seed_workspace(conn: AsyncConnection, workspace_id: str) -> None:
    await conn.execute(
        text("INSERT INTO workspace (workspace_id, name) VALUES (:w, :w)"),
        {"w": workspace_id},
    )


async def _seed_document(conn: AsyncConnection, doc_id: str, workspace_id: str) -> None:
    await conn.execute(
        text(
            "INSERT INTO design_document (id, workspace_id, title, status, current_scene_json)"
            " VALUES (:d, :w, 'T', 'draft', '{}'::jsonb)"
        ),
        {"d": doc_id, "w": workspace_id},
    )


async def _seed_publish_revision(
    conn: AsyncConnection, publish_id: str, workspace_id: str, doc_id: str
) -> None:
    await conn.execute(
        text(
            "INSERT INTO design_web_publish_revision "
            "(publish_id, workspace_id, slug, document_id, doc_version, html, html_digest,"
            " manifest_json, manifest_digest, package_digest) "
            "VALUES (:p, :w, 'slug', :d, 1, '<html/>', :sha, '{}'::jsonb, :sha, :sha)"
        ),
        {"p": publish_id, "w": workspace_id, "d": doc_id, "sha": _SHA},
    )


def test_design_enum_parity(require_design_db: None) -> None:
    """Every design PG enum mirrors its clue_design StrEnum: labels and order, lock-step."""

    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn:
            for type_name, py_enum in DESIGN_PG_ENUMS.items():
                labels = await _pg_enum_labels(conn, type_name)
                members = [m.value for m in py_enum]
                assert labels == members, (
                    f"{type_name}: DB labels {labels} != clue_design members {members}"
                )

    run_async(_check())


def test_web_publish_revision_rejects_update_and_delete(require_design_db: None) -> None:
    """Publish history is append-only: the trigger rejects UPDATE and DELETE."""

    async def _check() -> None:
        ws, doc = _ws("pubrev"), f"doc_{uuid4().hex}"
        publish_id = f"webpub_{_SHA}"
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            await _seed_workspace(conn, ws)
            await _seed_document(conn, doc, ws)
            await _seed_publish_revision(conn, publish_id, ws, doc)
            for mutation in (
                "UPDATE design_web_publish_revision SET html = 'x' WHERE publish_id = :p",
                "DELETE FROM design_web_publish_revision WHERE publish_id = :p",
            ):
                nested = await conn.begin_nested()
                with pytest.raises(DBAPIError, match="immutable|append-only"):
                    await conn.execute(text(mutation), {"p": publish_id})
                await nested.rollback()
            await txn.rollback()

    run_async(_check())


def test_custom_component_content_tables_reject_update(require_design_db: None) -> None:
    """The content-addressed component tables (source revision, artifact, compilation) are
    immutable: UPDATE is rejected by trigger on each."""

    async def _check() -> None:
        ws, acc = _ws("cc"), f"acc_{uuid4().hex}"
        rev_id, art_id, cmp_id = f"ccsrc_{_SHA}", f"ccart_{_SHA}", f"cccmp_{uuid4().hex}"
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            await _seed_workspace(conn, ws)
            await conn.execute(
                text(
                    "INSERT INTO design_account (account_id, workspace_id, name)"
                    " VALUES (:a, :w, 'Acme')"
                ),
                {"a": acc, "w": ws},
            )
            await conn.execute(
                text(
                    "INSERT INTO design_custom_component (workspace_id, account_id, slug)"
                    " VALUES (:w, :a, 'hero')"
                ),
                {"a": acc, "w": ws},
            )
            await conn.execute(
                text(
                    "INSERT INTO design_custom_component_source_revision "
                    "(revision_id, workspace_id, account_id, slug, source_version,"
                    " entry_path, snapshot_digest_algorithm, snapshot_digest_value,"
                    " snapshot_opaque_ref, snapshot_byte_length, files_manifest_json,"
                    " provenance_json) "
                    "VALUES (:r, :w, :a, 'hero', 1, 'hero.tsx', 'sha256', :sha,"
                    " 'sha256/00/x', 1, '{}'::jsonb, '{}'::jsonb)"
                ),
                {"r": rev_id, "a": acc, "w": ws, "sha": _SHA},
            )
            await conn.execute(
                text(
                    "INSERT INTO design_custom_component_artifact "
                    "(artifact_id, workspace_id, account_id, slug,"
                    " source_digest_algorithm, source_digest_value, source_opaque_ref,"
                    " source_byte_length, bundle_digest_algorithm, bundle_digest_value,"
                    " bundle_opaque_ref, bundle_byte_length, manifest_json,"
                    " provenance_json) "
                    "VALUES (:t, :w, :a, 'hero', 'sha256', :sha, 'sha256/00/x', 1,"
                    " 'sha256', :sha, 'sha256/00/y', 1, '{}'::jsonb, '{}'::jsonb)"
                ),
                {"t": art_id, "a": acc, "w": ws, "sha": _SHA},
            )
            await conn.execute(
                text(
                    "INSERT INTO design_custom_component_compilation "
                    "(compilation_id, workspace_id, account_id, slug,"
                    " source_revision_id, source_version, status,"
                    " compiler_protocol_version, compiler_version, diagnostics_json) "
                    "VALUES (:c, :w, :a, 'hero', :r, 1, 'succeeded', 1, 'v1',"
                    " '[]'::jsonb)"
                ),
                {"c": cmp_id, "a": acc, "w": ws, "r": rev_id},
            )
            for mutation, params in (
                (
                    "UPDATE design_custom_component_source_revision "
                    "SET entry_path = 'x' WHERE revision_id = :k",
                    {"k": rev_id},
                ),
                (
                    "UPDATE design_custom_component_artifact "
                    "SET slug = 'hero' WHERE artifact_id = :k",
                    {"k": art_id},
                ),
                (
                    "UPDATE design_custom_component_compilation "
                    "SET compiler_version = 'v2' WHERE compilation_id = :k",
                    {"k": cmp_id},
                ),
            ):
                nested = await conn.begin_nested()
                with pytest.raises(DBAPIError, match="immutable"):
                    await conn.execute(text(mutation), params)
                await nested.rollback()
            await txn.rollback()

    run_async(_check())


def test_cross_workspace_child_insert_is_unrepresentable(require_design_db: None) -> None:
    """Tenancy law §3: a child row claiming workspace B against a parent in workspace A
    violates the composite FK — IntegrityError, not handler code."""

    async def _check() -> None:
        ws_a, ws_b, doc = _ws("iso_a"), _ws("iso_b"), f"doc_{uuid4().hex}"
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            await _seed_workspace(conn, ws_a)
            await _seed_workspace(conn, ws_b)
            await _seed_document(conn, doc, ws_a)
            nested = await conn.begin_nested()
            with pytest.raises(IntegrityError):
                await conn.execute(
                    text(
                        "INSERT INTO design_snapshot "
                        "(snapshot_id, workspace_id, document_id, version, scene_json,"
                        " reason) "
                        "VALUES (:s, :w, :d, 1, '{}'::jsonb, 'test')"
                    ),
                    {"s": f"snap_{uuid4().hex}", "w": ws_b, "d": doc},
                )
            await nested.rollback()
            await txn.rollback()

    run_async(_check())


def test_design_account_cannot_bind_foreign_workspace_entity(require_design_db: None) -> None:
    """O1's composite FK: binding a design account to an account_entity in another workspace
    is unrepresentable."""

    async def _check() -> None:
        ws_a, ws_b = _ws("ent_a"), _ws("ent_b")
        entity_id = uuid4()
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            await _seed_workspace(conn, ws_a)
            await _seed_workspace(conn, ws_b)
            await conn.execute(
                text(
                    "INSERT INTO account_entity (id, canonical_name, workspace_id)"
                    " VALUES (:i, 'Acme', :w)"
                ),
                {"i": entity_id, "w": ws_a},
            )
            nested = await conn.begin_nested()
            with pytest.raises(IntegrityError):
                await conn.execute(
                    text(
                        "INSERT INTO design_account "
                        "(account_id, workspace_id, account_entity_id, name)"
                        " VALUES (:a, :w, :e, 'Acme')"
                    ),
                    {"a": f"acc_{uuid4().hex}", "w": ws_b, "e": entity_id},
                )
            await nested.rollback()
            # Same entity in its OWN workspace binds fine (the FK is scoping, not a block).
            await conn.execute(
                text(
                    "INSERT INTO design_account "
                    "(account_id, workspace_id, account_entity_id, name)"
                    " VALUES (:a, :w, :e, 'Acme')"
                ),
                {"a": f"acc_{uuid4().hex}", "w": ws_a, "e": entity_id},
            )
            await txn.rollback()

    run_async(_check())


def test_single_alembic_head_descending_from_the_ratified_base() -> None:
    """Offline guard: the D1 chain keeps exactly one head, and it descends from the ratified
    base ``c6d84aa84b79`` (the founder's single-head ruling)."""
    script = ScriptDirectory.from_config(_alembic_config())
    heads = script.get_heads()
    assert len(heads) == 1, f"expected exactly one alembic head, got {heads}"
    lineage = {rev.revision for rev in script.iterate_revisions(heads[0], "base")}
    assert _D1_BASE in lineage, f"head {heads[0]} does not descend from {_D1_BASE}"
