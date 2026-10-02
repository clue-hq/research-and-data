"""Ledger A2: two processes seeding the field registry together must both succeed.

``register_field`` is a read-then-insert. Two fleet workers booting at once both read "absent",
both INSERT, and the loser dies on ``field_definition_pkey`` (three of four workers, 2026-09-11).
``load_research_packs`` now takes a transaction-scoped advisory lock first, so the second seeder
waits until the first has committed and then finds the row.

The race is reproduced with a probe loader that sleeps *after* its insert, inside the window a
peer would read into. Without the lock this test fails with the very IntegrityError the workers
died on; with it, both seeders complete and exactly one row exists.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import text

from clue_api import composition
from clue_api.composition import RESEARCH_PACK_SEED_LOCK_KEY, load_research_packs
from clue_core import FieldDef, PassKind, ReuseScope
from clue_db import db_lifespan
from clue_research.claimstore import register_field
from tests.claimstore.conftest import migrated_db, require_claimstore_db  # noqa: F401
from tests.db.conftest import run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")

PROBE_FIELD = "core.zz_seed_race_probe"


async def _probe_loader(conn) -> None:  # noqa: ANN001 - the PackLoader protocol's own shape
    await register_field(
        conn,
        FieldDef(
            field_key=PROBE_FIELD,
            value_type="str",
            pass_kind=PassKind.SCORING,
            reuse_scope=ReuseScope.PUBLIC_FOOTPRINT,
        ),
    )
    # Hold the insert uncommitted long enough for a concurrent seeder to have read "absent".
    await asyncio.sleep(0.3)


async def _cleanup() -> None:
    async with db_lifespan() as engine, engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM field_definition WHERE field_key = :key"), {"key": PROBE_FIELD}
        )


def test_two_concurrent_seeds_both_succeed_and_seed_once() -> None:
    async def seed_once(engine) -> None:  # noqa: ANN001
        async with engine.begin() as conn:
            await load_research_packs(conn)

    async def body() -> int:
        composition.RESEARCH_PACK_LOADERS.append(_probe_loader)
        try:
            async with db_lifespan() as engine:
                await asyncio.gather(seed_once(engine), seed_once(engine))
                async with engine.connect() as conn:
                    return int(
                        (
                            await conn.execute(
                                text("SELECT count(*) FROM field_definition WHERE field_key = :k"),
                                {"k": PROBE_FIELD},
                            )
                        ).scalar_one()
                    )
        finally:
            composition.RESEARCH_PACK_LOADERS.remove(_probe_loader)
            await _cleanup()

    assert run_async(body()) == 1


def test_seed_outside_a_transaction_is_refused() -> None:
    """A transaction lock taken on autocommit releases at once — refuse, never pretend."""

    async def body() -> None:
        async with db_lifespan() as engine, engine.connect() as conn:
            with pytest.raises(RuntimeError, match="inside a transaction"):
                await load_research_packs(conn)

    run_async(body())


def test_the_lock_key_is_the_documented_crc() -> None:
    import zlib

    assert zlib.crc32(b"clue.research_pack_seed") == RESEARCH_PACK_SEED_LOCK_KEY
