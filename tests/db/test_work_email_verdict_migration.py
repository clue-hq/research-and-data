"""D4-b task 4: ``core.work_email``'s registered definition is the verdict object, reversibly.

The migration is a *data fix*, not a schema change — it rewrites one ``field_definition`` row so a
re-loaded ``CORE_PACK`` does not hit ``FieldRedefinitionError``. So the assertion is about that
row's content, and about the pack and the database agreeing on it.
"""

from __future__ import annotations

import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import text

from clue_db import db_lifespan
from clue_research.claimstore.packs import WORK_EMAIL_STATUSES, WORK_EMAIL_VALUE_SCHEMA
from clue_research.claimstore.registry import validate_value_against_schema

# ``migrated_db``/``require_claimstore_db`` live in ``tests/claimstore/conftest.py``, which pytest
# does not apply to this package; importing them here registers them for this module.
from tests.claimstore.conftest import (  # noqa: F401
    _alembic_config,
    migrated_db,
    require_claimstore_db,
)
from tests.db.conftest import run_async

_FIELD_KEY = "core.work_email"


def test_single_alembic_head() -> None:
    heads = ScriptDirectory.from_config(_alembic_config()).get_heads()
    assert len(heads) == 1, heads


def test_the_pack_schema_accepts_the_shapes_writers_produce_and_refuses_the_old_one() -> None:
    """The vocabulary is closed and the address+status pair is required (decision 6)."""
    validate_value_against_schema(
        {"address": "nick@zafran.io", "status": "verified_smtp", "checked_at": "2026-08-31T07:52"},
        WORK_EMAIL_VALUE_SCHEMA,
    )
    for status in WORK_EMAIL_STATUSES:
        validate_value_against_schema(
            {"address": "nick@zafran.io", "status": status}, WORK_EMAIL_VALUE_SCHEMA
        )
    for refused in (
        "nick@zafran.io",  # the pre-D4-b bare address: an address nobody graded
        {"address": "nick@zafran.io"},  # an address with no verdict
        {"status": "verified_smtp"},  # a verdict with no address
        {"address": "nick@zafran.io", "status": "probably_fine"},  # outside the vocabulary
    ):
        with pytest.raises(Exception):  # noqa: B017 — ValueSchemaError is the registry's own
            validate_value_against_schema(refused, WORK_EMAIL_VALUE_SCHEMA)


@pytest.mark.usefixtures("require_claimstore_db")
def test_the_stored_definition_at_head_is_the_object_the_pack_declares() -> None:
    async def _check() -> None:
        async with db_lifespan() as engine, engine.connect() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT value_type, value_schema FROM field_definition "
                            "WHERE field_key = :field_key"
                        ),
                        {"field_key": _FIELD_KEY},
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                pytest.skip("no core pack is loaded in this database")
            assert row["value_type"] == "object"
            assert row["value_schema"] == WORK_EMAIL_VALUE_SCHEMA

    run_async(_check())
