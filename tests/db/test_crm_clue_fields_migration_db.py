"""CRM Phase 4 (Task 1): the schema of the Clue-fields registry (R-13.1, R-13.2).

``crm_clue_fields`` holds one row per connection: what Clue set up in that CRM (the field names it
created, the Salesforce permission set id, the HubSpot duplicate label type id), its status
(``ready`` | ``partial`` | ``gone``) and when a field was found gone. The round trip commits a
populated row to the throwaway DB, downgrades to the previous revision (the registry goes with its
rows; the connection survives) and upgrades again, so the DB is always left at head.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_db import db_lifespan

from .conftest import run_async
from .test_crm_write_foundation_migration import _seed_chain

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PREVIOUS_REVISION = "31b850b308e6"


def _alembic_config() -> Config:
    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "alembic"))
    return cfg


async def _refused(conn: AsyncConnection, sql: str, params: dict[str, Any], match: str) -> None:
    savepoint = await conn.begin_nested()
    with pytest.raises(IntegrityError, match=match):
        await conn.execute(text(sql), params)
    await savepoint.rollback()


_INSERT = (
    "INSERT INTO crm_clue_fields (connection_id, workspace_id, provider, status, created_names, "
    "permission_set_id, label_type_id) VALUES (:c, :ws, :provider, :status, :names, :ps, :label)"
)


async def _write_rows() -> dict[str, Any]:
    async with db_lifespan() as engine, engine.connect() as conn:
        tx = await conn.begin()
        seeded = await _seed_chain(conn)
        ws, connection = seeded["ws"], seeded["connection"]  # a HubSpot connection
        base = {
            "c": connection,
            "ws": ws,
            "provider": "hubspot",
            "status": "ready",
            "names": ["companies.clue_tier", "contacts.clue_id"],
            "ps": None,
            "label": "17",
        }
        # The workspace and provider must be the connection's own (composite FK).
        await _refused(conn, _INSERT, {**base, "provider": "salesforce", "label": None}, "_fk")
        await _refused(conn, _INSERT, {**base, "status": "done"}, "crm_clue_fields_status")
        # A permission set is Salesforce's; a duplicate label is HubSpot's.
        await _refused(conn, _INSERT, {**base, "ps": "0PS1"}, "crm_clue_fields_provider_ids")
        await conn.execute(text(_INSERT), base)
        await _refused(conn, _INSERT, base, "crm_clue_fields_pkey")
        await tx.commit()
        return {"ws": ws, "connection": connection}


async def _state(connection: UUID) -> dict[str, Any]:
    async with db_lifespan() as engine, engine.connect() as conn:
        table = (await conn.execute(text("SELECT to_regclass('crm_clue_fields')"))).scalar_one()
        row = None
        if table is not None:
            row = (
                (
                    await conn.execute(
                        text("SELECT * FROM crm_clue_fields WHERE connection_id = :c"),
                        {"c": connection},
                    )
                )
                .mappings()
                .one_or_none()
            )
        survives = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM workspace_integration_connection WHERE connection_id = :c"
                ),
                {"c": connection},
            )
        ).scalar_one()
        anchor = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM pg_constraint "
                    "WHERE conname = 'workspace_integration_connection_provider_anchor'"
                )
            )
        ).scalar_one()
        return {"table": table, "row": row, "connection": survives, "anchor": anchor}


@pytest.mark.usefixtures("require_db")
def test_crm_clue_fields_round_trip_with_a_populated_row() -> None:
    cfg = _alembic_config()
    command.upgrade(cfg, "head")
    try:
        written = run_async(_write_rows())
        at_head = run_async(_state(written["connection"]))
        assert at_head["table"] is not None
        assert at_head["anchor"] == 1
        row = at_head["row"]
        assert row["status"] == "ready"
        assert row["created_names"] == ["companies.clue_tier", "contacts.clue_id"]
        assert row["gone_names"] == []
        assert row["gone_at"] is None
        assert row["label_type_id"] == "17"

        command.downgrade(cfg, _PREVIOUS_REVISION)
        below = run_async(_state(written["connection"]))
        assert below["table"] is None
        assert below["anchor"] == 0
        assert below["connection"] == 1  # the connection itself survives
    finally:
        command.upgrade(cfg, "head")
    again = run_async(_state(written["connection"]))
    assert again["table"] is not None
    assert again["row"] is None  # the registry's rows went with the table
