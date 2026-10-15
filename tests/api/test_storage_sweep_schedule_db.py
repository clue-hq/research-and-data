"""One fleet-wide storage sweep per interval, remembered in the database (2026-10-09).

Every fleet worker process used to run the purge + orphan sweep every 6 h on its own timer — about
twenty passes a day across production's five worker containers — and a timer that lives only in a
process restarts with every deploy. The fleet now keeps the time of its last sweep in
``maintenance_run``; each process checks it hourly and sweeps only when it is due, under an
advisory lock so exactly one process sweeps.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

import clue_api.storage_wiring as storage_wiring
from clue_api.storage_wiring import run_orphan_blob_sweep_if_due
from clue_db import db_lifespan

# Fixtures are visible only to a module that imports them.
from tests.storage.conftest import (  # noqa: F401
    migrated_db,
    require_storage_db,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_storage_db")

EVERY = timedelta(hours=48)
T0 = datetime(2026, 10, 9, 12, tzinfo=UTC)


def _recording(monkeypatch: pytest.MonkeyPatch) -> list[tuple[datetime, datetime]]:
    calls: list[tuple[datetime, datetime]] = []

    async def sweep(conn, *, storage=None, grace=None, now=None, privacy_purged_since=None):
        calls.append((now, privacy_purged_since))
        return ("swept",)

    monkeypatch.setattr(storage_wiring, "run_orphan_blob_sweep", sweep)
    return calls


def test_the_fleet_sweeps_once_per_interval_and_remembers_when(monkeypatch) -> None:
    calls = _recording(monkeypatch)

    async def scenario() -> list:
        async with rollback_conn(seed_core=False) as conn:
            await conn.execute(text("DELETE FROM maintenance_run"))
            first = await run_orphan_blob_sweep_if_due(conn, every=EVERY, now=T0)
            too_soon = await run_orphan_blob_sweep_if_due(
                conn, every=EVERY, now=T0 + timedelta(hours=1)
            )
            due = await run_orphan_blob_sweep_if_due(
                conn, every=EVERY, now=T0 + timedelta(hours=49)
            )
            last = (
                await conn.execute(
                    text("SELECT last_run_at FROM maintenance_run WHERE name='storage_sweep'")
                )
            ).scalar_one()
            return [first, too_soon, due, last]

    first, too_soon, due, last = run_async(scenario())
    assert first == ("swept",) and too_soon is None and due == ("swept",)
    assert last == T0 + timedelta(hours=49)
    # The write-back check looks back from the previous sweep, less a day's margin; the very
    # first sweep looks back one interval (plus the margin).
    assert calls == [
        (T0, T0 - EVERY - timedelta(days=1)),
        (T0 + timedelta(hours=49), T0 - timedelta(days=1)),
    ]


def test_only_one_process_sweeps_at_a_time(monkeypatch) -> None:
    calls = _recording(monkeypatch)

    async def scenario() -> object:
        async with db_lifespan() as engine, engine.connect() as holder:
            await holder.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended('storage-sweep', 0))")
            )
            try:
                async with engine.connect() as other, other.begin():
                    return await run_orphan_blob_sweep_if_due(other, every=EVERY, now=T0)
            finally:
                await holder.rollback()

    assert run_async(scenario()) is None
    assert calls == []
