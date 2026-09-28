"""Reproduce r18's FK lock cycle using real independent Postgres transactions."""

import asyncio
from functools import partial
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from clue_api.arv2.account_research_store import create_job
from clue_api.arv2.quality_generation import (
    ensure_generation,
    read_generation,
    register_child,
    signal,
)
from clue_db import db_lifespan
from clue_research.claimstore import load_core_pack
from clue_research.identity import insert_contact_entity
from clue_storage.fs import FsStorage
from tests.arv2 import test_quality_evidence_db as evidence
from tests.arv2.test_quality_claims_db import setup
from tests.claimstore.conftest import migrated_db, require_claimstore_db, run_async  # noqa: F401

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


@pytest.mark.parametrize("legacy", [True, False])
def test_nomination_and_signal_fk_cycle(tmp_path, monkeypatch, legacy):
    monkeypatch.setattr(
        evidence,
        "seed_icp_fixture",
        partial(
            evidence.seed_icp_fixture, workspace_id=f"lock-{uuid4()}", user_id=f"user-{uuid4()}"
        ),
    )

    async def case():
        async with db_lifespan() as engine:
            async with engine.begin() as conn:
                await load_core_pack(conn)
                op, _, cid = await setup(conn, FsStorage(tmp_path))
                generation = await ensure_generation(conn, op, context_id=cid)
                contact = await insert_contact_entity(
                    conn, account_entity_id=op.account_id, full_name="Concurrency fixture"
                )
                child = uuid4()
                await create_job(
                    conn,
                    job_id=child,
                    run_id=op.run_id,
                    workspace_id=op.workspace_id,
                    account_entity_id=op.account_id,
                    subject_type="person",
                    subject_entity_id=contact,
                    profile_sha256="a" * 64,
                    input_refs={"parent_job_id": str(op.job_id)},
                )
            barrier = asyncio.Barrier(2)
            event = uuid4()

            async def nominate():
                async with engine.begin() as conn:
                    await conn.execute(text("SET LOCAL statement_timeout='8s'"))
                    strength = "UPDATE" if legacy else "NO KEY UPDATE"
                    await conn.execute(
                        text(
                            "SELECT job_id FROM arv2_research_job WHERE job_id=:job FOR " + strength
                        ),
                        {"job": op.job_id},
                    )
                    await barrier.wait()
                    await register_child(conn, generation, job_id=child)

            async def notify():
                async with engine.begin() as conn:
                    await conn.execute(text("SET LOCAL statement_timeout='8s'"))
                    if legacy:
                        await conn.execute(
                            text(
                                "SELECT generation_id FROM arv2_account_research_generation "
                                "WHERE generation_id=:id FOR UPDATE"
                            ),
                            {"id": generation.generation_id},
                        )
                    else:
                        await read_generation(
                            conn,
                            workspace_id=op.workspace_id,
                            generation_id=generation.generation_id,
                            lock=True,
                        )
                    await barrier.wait()
                    # Replay the FK KEY SHARE acquisition shown in r18's Postgres log.
                    # PostgreSQL can skip rechecking an unchanged FK in a minimal fixture;
                    # explicitly request the same lock so this reproduces the cycle reliably.
                    await conn.execute(
                        text(
                            "SELECT job_id FROM arv2_research_job WHERE job_id=:job FOR KEY SHARE"
                        ),
                        {"job": op.job_id},
                    )
                    return await signal(
                        conn,
                        workspace_id=op.workspace_id,
                        generation_id=generation.generation_id,
                        event_id=event,
                        reason="claim_changed",
                    )

            results = await asyncio.wait_for(
                asyncio.gather(nominate(), notify(), return_exceptions=True), timeout=15
            )
            errors = [r for r in results if isinstance(r, BaseException)]
            if legacy:
                assert len(errors) == 1 and isinstance(errors[0], DBAPIError)
                assert getattr(errors[0].orig, "sqlstate", None) == "40P01"
                return
            assert not errors, errors

            # Concurrent duplicate deliveries remain one event/revision.
            async def repeat(event_id=event):
                async with engine.begin() as conn:
                    return await signal(
                        conn,
                        workspace_id=op.workspace_id,
                        generation_id=generation.generation_id,
                        event_id=event_id,
                        reason="claim_changed",
                    )

            assert (
                await asyncio.wait_for(asyncio.gather(*(repeat() for _ in range(5))), 10) == [1] * 5
            )
            revisions = await asyncio.wait_for(
                asyncio.gather(*(repeat(uuid4()) for _ in range(5))), 10
            )
            assert sorted(revisions) == [2, 3, 4, 5, 6]
            async with engine.begin() as conn:
                assert (
                    await conn.execute(
                        text("SELECT count(*) FROM arv2_generation_child WHERE generation_id=:id"),
                        {"id": generation.generation_id},
                    )
                ).scalar_one() == 1

    run_async(case())
