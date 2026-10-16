"""design_site_section (Lane B, Contract 4): agent-written Puck sections, per workspace."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_db import db_lifespan
from clue_design import site_sections
from clue_design.errors import DesignNotFoundError
from clue_design.storage import (
    SOURCE_KEY_ASSET,
    SOURCE_KEY_SITE_SECTION,
    read_design_blob,
    read_public_design_blob,
    register_design_bytes,
)
from clue_storage import FsStorage
from clue_storage.protocol import content_address
from tests.design.conftest import run_async

SCHEMA = {"type": "object", "properties": {"id": {"type": "string"}, "surface": {"type": "string"}}}


async def _seed_ws(conn: AsyncConnection) -> str:
    ws = f"ws_test_sections_{uuid4().hex[:12]}"
    await conn.execute(
        text("INSERT INTO workspace (workspace_id, name) VALUES (:w, :w)"), {"w": ws}
    )
    return ws


async def _record(
    conn: AsyncConnection, ws: str, digest: str, name: str = "StepsBand", run: str = "run_1"
) -> dict:
    return await site_sections.record_site_section(
        conn,
        workspace_id=ws,
        digest=digest,
        name=name,
        source_sha256="b" * 64,
        css_sha256="c" * 64,
        props_schema=SCHEMA,
        created_by_run_id=run,
    )


def test_a_section_is_recorded_once_and_read_back_only_in_its_workspace(
    require_design_db: None,
) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn)
            first = await _record(conn, ws, "a" * 64)
            again = await _record(conn, ws, "a" * 64, run="run_2")
            assert again == first  # content-addressed: a repeat records nothing new
            assert first["module_sha256"] == "a" * 64 and first["props_schema"] == SCHEMA
            assert first["created_by_run_id"] == "run_1"
            rows = await site_sections.get_site_sections(
                conn, workspace_id=ws, digests=["f" * 64, "a" * 64]
            )
            assert [row["digest"] for row in rows] == ["a" * 64]
            other = await _seed_ws(conn)
            assert (
                await site_sections.get_site_sections(conn, workspace_id=other, digests=["a" * 64])
                == []
            )
            await txn.rollback()

    run_async(_check())


def test_the_newest_section_of_each_name_is_listed(require_design_db: None) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn)
            await _record(conn, ws, "1" * 64, name="StepsBand")
            await _record(conn, ws, "2" * 64, name="QuoteBand")
            await _record(conn, ws, "0" * 64, name="StepsBand")  # written later, sorts first
            latest = await site_sections.list_latest_site_sections(conn, workspace_id=ws)
            assert {row["name"]: row["digest"] for row in latest} == {
                "QuoteBand": "2" * 64,
                "StepsBand": "0" * 64,
            }
            await txn.rollback()

    run_async(_check())


def test_rows_are_immutable_and_shaped(require_design_db: None) -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn)
            await _record(conn, ws, "a" * 64)
            with pytest.raises(DBAPIError):
                async with conn.begin_nested():
                    await conn.execute(
                        text(
                            "UPDATE design_site_section SET name = 'Other' WHERE workspace_id = :w"
                        ),
                        {"w": ws},
                    )
            with pytest.raises(DBAPIError):
                async with conn.begin_nested():
                    await _record(conn, ws, "d" * 64, name="lowercase")
            await txn.rollback()

    run_async(_check())


def test_a_site_section_module_is_not_served_by_the_public_asset_store(
    require_design_db: None, tmp_path: Path
) -> None:
    """Review focus 3 / Contract 4: agent code is reachable only through a short-lived link."""

    async def _check() -> None:
        storage = FsStorage(tmp_path / "blobs")
        module = b"export const schema = 1;\n//# clue-section StepsBand\n"
        image = b"\x89PNG\r\n\x1a\nnot really"
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            ws = await _seed_ws(conn)
            await register_design_bytes(
                conn,
                storage,
                workspace_id=ws,
                data=module,
                media_type="text/javascript",
                source_key=SOURCE_KEY_SITE_SECTION,
            )
            await register_design_bytes(
                conn,
                storage,
                workspace_id=ws,
                data=image,
                media_type="image/png",
                source_key=SOURCE_KEY_ASSET,
            )
            with pytest.raises(DesignNotFoundError):
                await read_public_design_blob(conn, storage, sha256=content_address(module))
            _, served = await read_public_design_blob(conn, storage, sha256=content_address(image))
            assert served == image
            # The workspace-scoped read (the renderer, the link verifier) still reads it.
            media_type, data = await read_design_blob(
                conn, storage, workspace_id=ws, sha256=content_address(module)
            )
            assert (media_type, data) == ("text/javascript", module)
            await txn.rollback()

    run_async(_check())
