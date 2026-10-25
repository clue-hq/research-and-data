"""CRM Phase 3 (Task 2): the schema of Clue's CRM list registry (R-11.11).

``crm_list`` holds one row per list or campaign of a connection, ``crm_list_project`` links it to
every project that uses it, and ``crm_write`` gains ``source_claim_ids`` and ``clue_entity_id``.
The round trip commits populated rows to the throwaway DB, downgrades to the previous revision
(the registry's rows go with its tables; the write keeps every other column) and upgrades again,
so the DB is always left at head.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

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
_PREVIOUS_REVISION = "01b066d230e7"
_TABLES = ("crm_list", "crm_list_project")


def _alembic_config() -> Config:
    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "alembic"))
    return cfg


async def _refused(conn: AsyncConnection, sql: str, params: dict[str, Any], match: str) -> None:
    savepoint = await conn.begin_nested()
    with pytest.raises(IntegrityError, match=match):
        await conn.execute(text(sql), params)
    await savepoint.rollback()


_INSERT_LIST = (
    "INSERT INTO crm_list (list_id, workspace_id, connection_id, provider, crm_object, "
    "crm_list_id, name, kind, created_by_clue) VALUES (:id, :ws, :c, 'hubspot', :object, "
    ":crm_id, 'Q4 committees', :kind, true)"
)


async def _write_rows() -> dict[str, Any]:
    async with db_lifespan() as engine, engine.connect() as conn:
        tx = await conn.begin()
        seeded = await _seed_chain(conn)
        ws, connection = seeded["ws"], seeded["connection"]
        proposal, write_id, list_id = uuid4(), uuid4(), uuid4()
        await conn.execute(
            text(
                "INSERT INTO crm_write_proposal (proposal_id, workspace_id, connection_id, "
                "project_id, thread_id, turn_id, status) "
                "VALUES (:id, :ws, :c, :p, :t, :turn, 'finished')"
            ),
            {
                "id": proposal,
                "ws": ws,
                "c": connection,
                "p": seeded["project"],
                "t": seeded["thread"],
                "turn": seeded["agent_turn"],
            },
        )
        claim = uuid4()
        await conn.execute(
            text(
                "INSERT INTO crm_write (write_id, proposal_id, workspace_id, connection_id, "
                "ordinal, slug, arguments, kind, object, record_label, overwrites_person, reason, "
                "scope_key, selected, status, idempotency_key, source_claim_ids, clue_entity_id) "
                "VALUES (:id, :proposal, :ws, :c, 0, 'HUBSPOT_CREATE_LIST', "
                "CAST('{}' AS jsonb), 'create', 'list', 'Q4 committees', false, 'campaign', "
                "'kind:create', true, 'succeeded', :key, :claims, 'acct-1')"
            ),
            {
                "id": write_id,
                "proposal": proposal,
                "ws": ws,
                "c": connection,
                "key": f"crm-write:{write_id}",
                "claims": [claim],
            },
        )
        base = {"ws": ws, "c": connection, "object": "contact", "kind": "hubspot_list"}
        await conn.execute(text(_INSERT_LIST), {**base, "id": list_id, "crm_id": "17"})
        await _refused(
            conn,
            _INSERT_LIST,
            {**base, "id": uuid4(), "crm_id": "17"},
            "crm_list_connection_crm_id",
        )
        await _refused(
            conn,
            _INSERT_LIST,
            {**base, "id": uuid4(), "crm_id": "18", "object": "deal"},
            "crm_list_crm_object",
        )
        await _refused(
            conn,
            _INSERT_LIST,
            {**base, "id": uuid4(), "crm_id": "18", "kind": "static"},
            "crm_list_kind",
        )
        link = (
            "INSERT INTO crm_list_project (list_id, project_id, workspace_id, linked_by) "
            "VALUES (:l, :p, :ws, :by)"
        )
        await conn.execute(
            text(link), {"l": list_id, "p": seeded["project"], "ws": ws, "by": "clue_created"}
        )
        await _refused(
            conn,
            link,
            {"l": list_id, "p": seeded["project"], "ws": ws, "by": "clue_created"},
            "crm_list_project_pkey",
        )
        await tx.commit()
        return {"ws": ws, "write_id": write_id, "claim": claim}


async def _state(write_id: UUID) -> dict[str, Any]:
    async with db_lifespan() as engine, engine.connect() as conn:
        tables = {
            t: (await conn.execute(text("SELECT to_regclass(:t)"), {"t": t})).scalar_one()
            for t in _TABLES
        }
        columns = {
            str(row.column_name): (str(row.data_type), str(row.is_nullable))
            for row in await conn.execute(
                text(
                    "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
                    "WHERE table_name = 'crm_write' "
                    "AND column_name IN ('source_claim_ids', 'clue_entity_id')"
                )
            )
        }
        write = (
            (
                await conn.execute(
                    text("SELECT * FROM crm_write WHERE write_id = :id"), {"id": write_id}
                )
            )
            .mappings()
            .one_or_none()
        )
        return {"tables": tables, "columns": columns, "write": write}


@pytest.mark.usefixtures("require_db")
def test_crm_lists_round_trip_with_populated_rows() -> None:
    cfg = _alembic_config()
    command.upgrade(cfg, "head")
    try:
        written = run_async(_write_rows())
        at_head = run_async(_state(written["write_id"]))
        assert all(at_head["tables"].values())
        assert at_head["columns"] == {
            "source_claim_ids": ("ARRAY", "NO"),
            "clue_entity_id": ("text", "YES"),
        }
        assert at_head["write"]["source_claim_ids"] == [written["claim"]]

        command.downgrade(cfg, _PREVIOUS_REVISION)
        below = run_async(_state(written["write_id"]))
        assert not any(below["tables"].values())
        assert below["columns"] == {}
        assert below["write"] is not None  # the write itself survives
    finally:
        command.upgrade(cfg, "head")
    again = run_async(_state(written["write_id"]))
    assert all(again["tables"].values())
    # A write logged before this revision cites no claims and no entity.
    assert again["write"]["source_claim_ids"] == []
    assert again["write"]["clue_entity_id"] is None
