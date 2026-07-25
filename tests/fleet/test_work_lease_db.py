"""C5.3 monotone work-lease generation fence."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from tests.db.conftest import run_async
from tests.profiling.conftest import rollback_conn

from clue_fleet import (
    LeaseGeneration,
    WorkId,
    acquire_work_lease,
    renew_work_lease,
)

pytestmark = pytest.mark.usefixtures("require_fleet_db")


def test_takeover_increments_generation_and_fences_old_holder() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            work_id = WorkId(uuid4())
            first = await acquire_work_lease(
                conn,
                work_id=work_id,
                worker_id="first",
                ttl=timedelta(0),
            )
            assert first is not None and first.generation == 1
            second = await acquire_work_lease(
                conn,
                work_id=work_id,
                worker_id="second",
                ttl=timedelta(seconds=60),
            )
            assert second is not None and second.generation == 2
            assert not await renew_work_lease(
                conn,
                work_id=work_id,
                worker_id="first",
                generation=LeaseGeneration(first.generation),
                ttl=timedelta(seconds=60),
            )
            assert await renew_work_lease(
                conn,
                work_id=work_id,
                worker_id="second",
                generation=LeaseGeneration(second.generation),
                ttl=timedelta(seconds=60),
            )

    run_async(scenario())
