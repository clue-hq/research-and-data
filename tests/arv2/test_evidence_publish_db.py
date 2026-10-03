"""Evidence saving: uploads run without the account lock; publication is locked once.

Research slowness fix (2026-10-03): persist_source took the account-wide manifest lock first and
uploaded under it, and acquisition saved many sources in one transaction, so every upload after the
first ran while holding the lock. Real, independent, committed Postgres transactions.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from functools import partial
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_api.arv2.quality_evidence import PreparedSource, prepare_source, publish_sources
from clue_db import db_lifespan
from clue_research.claimstore import load_core_pack
from clue_storage.fs import FsStorage
from tests.arv2 import test_quality_evidence_db as evidence
from tests.arv2.test_quality_claims_db import setup
from tests.claimstore.conftest import migrated_db, require_claimstore_db, run_async  # noqa: F401

pytestmark = pytest.mark.usefixtures("require_claimstore_db")
NOW = datetime(2026, 10, 3, tzinfo=UTC)


class _SlowStorage(FsStorage):
    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        await asyncio.sleep(0.3)
        await super().put(key, data, media_type=media_type)


def _unique_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        evidence,
        "seed_icp_fixture",
        partial(evidence.seed_icp_fixture, workspace_id=f"pub-{uuid4()}", user_id=f"u-{uuid4()}"),
    )


async def _prepare(conn: Any, storage: Any, op: Any, body: str) -> PreparedSource:
    return await prepare_source(
        conn,
        storage,
        op,
        kind="web_snapshot",
        body=body,
        original_key=None,
        origin_locator="fixture",
        observed_at=NOW,
        source_url="https://example.test/" + body.replace(" ", "-"),
    )


def test_two_transactions_upload_in_parallel_and_revisions_stay_gap_free(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _unique_workspace(monkeypatch)

    async def case() -> None:
        async with db_lifespan() as engine:
            async with engine.begin() as conn:
                await load_core_pack(conn)
                op, _, _ = await setup(conn, FsStorage(tmp_path))
            storage = _SlowStorage(tmp_path)

            async def batch(tag: str) -> list[int]:
                async with engine.begin() as conn:
                    prepared = [
                        await _prepare(conn, storage, op, f"{tag} body {i}") for i in range(3)
                    ]
                    refs = await publish_sources(conn, op, prepared)
                    return [r.revision for r in refs]

            started = time.monotonic()
            a, b = await asyncio.gather(batch("alpha"), batch("beta"))
            elapsed = time.monotonic() - started
            # Serial would be ~1.8 s (6 x 0.3 s); parallel uploads take ~0.9 s.
            assert elapsed < 1.5, elapsed
            revisions = sorted(a + b)
            assert revisions == list(range(revisions[0], revisions[0] + 6))

    run_async(case())


def test_the_same_source_saved_concurrently_is_one_row(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _unique_workspace(monkeypatch)

    async def case() -> None:
        async with db_lifespan() as engine:
            async with engine.begin() as conn:
                await load_core_pack(conn)
                op, _, _ = await setup(conn, FsStorage(tmp_path))
            storage = _SlowStorage(tmp_path)

            async def save_same() -> str:
                async with engine.begin() as conn:
                    prepared = [await _prepare(conn, storage, op, "identical body")]
                    (ref,) = await publish_sources(conn, op, prepared)
                    return str(ref.source_id)

            first, second = await asyncio.gather(save_same(), save_same())
            assert first == second
            async with engine.begin() as conn:
                count = (
                    await conn.execute(
                        text("SELECT count(*) FROM arv2_evidence_source WHERE source_id=:id"),
                        {"id": first},
                    )
                ).scalar_one()
            assert count == 1

    run_async(case())
