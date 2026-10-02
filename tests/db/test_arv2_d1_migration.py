"""D1 (master plan §4, source map §2.2): the display substrate lands as one reversible revision."""

from __future__ import annotations

import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import text

from clue_db import db_lifespan

# ``migrated_db``/``require_claimstore_db`` live in ``tests/claimstore/conftest.py``, which pytest
# does not apply to this package; importing them here registers them for this module.
from tests.claimstore.conftest import (  # noqa: F401
    _alembic_config,
    migrated_db,
    require_claimstore_db,
)
from tests.db.conftest import run_async

_EXPECTED_TABLES = {
    "display_block",
    "display_section_recipe",
    "provider_call_ledger",
    "account_activity_event",
}
_EXPECTED_COLUMNS = {
    ("claim", "signal_priority"),
    ("claim", "outreach_safe"),
    ("claim", "write_markers"),
    ("account_entity", "owner_user_id"),
    ("account_entity", "created_by_user_id"),
    ("workspace_field_definition", "presentation"),
}


def test_single_alembic_head() -> None:
    heads = ScriptDirectory.from_config(_alembic_config()).get_heads()
    assert len(heads) == 1, heads


@pytest.mark.usefixtures("require_claimstore_db")
def test_d1_objects_exist_at_head() -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn:
            tables = {
                row[0]
                for row in await conn.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = 'public'"
                    )
                )
            }
            assert tables >= _EXPECTED_TABLES, _EXPECTED_TABLES - tables
            cols = {
                (row[0], row[1])
                for row in await conn.execute(
                    text(
                        "SELECT table_name, column_name FROM information_schema.columns "
                        "WHERE table_schema = 'public'"
                    )
                )
            }
            assert cols >= _EXPECTED_COLUMNS, _EXPECTED_COLUMNS - cols
            defaults = {
                row[0]: (row[1], row[2])
                for row in await conn.execute(
                    text(
                        "SELECT column_name, column_default, is_nullable "
                        "FROM information_schema.columns WHERE table_name = 'claim' "
                        "AND column_name IN ('signal_priority','outreach_safe','write_markers')"
                    )
                )
            }
            assert defaults["signal_priority"] == ("3", "NO")
            assert defaults["outreach_safe"] == ("true", "NO")
            assert defaults["write_markers"][1] == "YES"

    run_async(_check())


@pytest.mark.usefixtures("require_claimstore_db")
def test_persona_schemas_admit_user_after_migration() -> None:
    """D8: the three persona-bearing registry rows carry ``user`` once packs have loaded."""

    async def _check() -> None:
        from clue_research.claimstore.packs import load_core_pack
        from clue_research.profiling.committee.fields import load_committee_pack

        async with db_lifespan() as engine:
            conn = await engine.connect()
            trans = await conn.begin()
            try:
                await load_core_pack(conn)
                await load_committee_pack(conn)  # raises FieldRedefinitionError if drifted
                row = (
                    await conn.execute(
                        text(
                            "SELECT value_schema->'enum' FROM field_definition "
                            "WHERE field_key = 'contact.persona'"
                        )
                    )
                ).scalar_one()
                assert "user" in row
            finally:
                await trans.rollback()
                await conn.close()

    run_async(_check())
