"""Research step lineage: one watermark row per saved step, the same erasure guarantee.

Until 2026-10-12 every saved agent step (model request and reply, tool result, plan, dossier) was
linked to every evidence source of its run and account: steps x sources rows, about 460,000 per
account run and 94% of the lane database. A step's parents were always "every source published up
to now" (filtered by subject) plus its context, so one revision number per step says the same thing.
Erasing a source at revision r erases every step whose watermark is at least r.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from typing import Any
from uuid import uuid4

import pytest
from scripts.backfill_artifact_lineage import convert, next_children
from sqlalchemy import text

from clue_api.arv2.account_research_store import create_job
from clue_api.arv2.research_operations import OperationScope
from clue_api.quality_research_artifacts import ResearchArtifacts, lineage_lock_name
from clue_research.identity import insert_contact_entity
from clue_storage import ArtifactIntegrityError, artifact_key, content_address
from clue_storage.fs import FsStorage
from tests.arv2.test_quality_claims_db import setup
from tests.arv2.test_quality_evidence_db import save
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


def _borrowed(conn: Any) -> Any:
    @asynccontextmanager
    async def factory() -> AsyncIterator[Any]:
        yield conn

    return factory


def _sink(conn: Any, storage: Any, job: Any, cid: Any) -> ResearchArtifacts:
    sink = ResearchArtifacts(storage=storage, conn_factory=_borrowed(conn))
    sink.scope = job
    sink.context_id = cid
    return sink


async def _step(conn: Any, storage: Any, job: Any, cid: Any, body: bytes) -> str:
    ref = await _sink(conn, storage, job, cid).persist_body(
        workspace_id=job.workspace_id, data=body, media_type="application/json"
    )
    return ref.artifact_key


async def _erase(conn: Any, key: str) -> None:
    await conn.execute(
        text(
            "UPDATE artifact SET privacy_erased=true, erasure_reason='privacy', "
            "erased_at=now() WHERE storage_key=:key"
        ),
        {"key": key},
    )


async def _erased(conn: Any, key: str) -> bool:
    return bool(
        (
            await conn.execute(
                text("SELECT privacy_erased FROM artifact WHERE storage_key=:key"), {"key": key}
            )
        ).scalar_one()
    )


async def _person(conn: Any, op: Any, account_job: Any, name: str) -> tuple[Any, Any]:
    contact = await insert_contact_entity(
        conn, account_entity_id=account_job.account_id, full_name=name
    )
    jid = uuid4()
    await create_job(
        conn,
        job_id=jid,
        run_id=op.run_id,
        workspace_id=op.workspace_id,
        account_entity_id=op.account_id,
        subject_type="person",
        subject_entity_id=contact,
        profile_sha256="a" * 64,
    )
    job = replace(account_job, job_id=jid, subject_kind="person", contact_id=contact)
    return job, OperationScope(op.workspace_id, op.run_id, jid, op.account_id)


def test_a_step_stores_one_watermark_and_no_link_per_source(tmp_path) -> None:
    async def case() -> None:
        async with rollback_conn() as conn:
            fs = FsStorage(tmp_path)
            op, job, cid = await setup(conn, fs)
            for i in range(25):
                await save(conn, fs, op, f"Source body number {i}.", url=f"https://e.test/{i}")
            step = await _step(conn, fs, job, cid, b'{"step":1}')
            links = (
                await conn.execute(
                    text("SELECT count(*) FROM artifact_derivation WHERE child_key=:key"),
                    {"key": step},
                )
            ).scalar_one()
            assert links == 0
            manifest = (
                await conn.execute(
                    text(
                        "SELECT revision FROM arv2_evidence_manifest WHERE workspace_id=:ws "
                        "AND run_id=:run AND account_id=:account"
                    ),
                    {"ws": op.workspace_id, "run": op.run_id, "account": op.account_id},
                )
            ).scalar_one()
            rows = (
                (
                    await conn.execute(
                        text(
                            "SELECT run_id, account_id, subject_key, evidence_revision "
                            "FROM artifact_evidence_watermark WHERE child_key=:key"
                        ),
                        {"key": step},
                    )
                )
                .mappings()
                .all()
            )
            assert [dict(r) for r in rows] == [
                {
                    "run_id": op.run_id,
                    "account_id": op.account_id,
                    "subject_key": op.account_id,
                    "evidence_revision": manifest,
                }
            ]
            contexts = (
                (
                    await conn.execute(
                        text("SELECT context_id FROM artifact_context_lineage WHERE child_key=:k"),
                        {"k": step},
                    )
                )
                .scalars()
                .all()
            )
            assert contexts == [cid]

    run_async(case())


def test_erasing_a_source_saved_before_the_step_erases_the_step(tmp_path) -> None:
    async def case() -> None:
        async with rollback_conn() as conn:
            fs = FsStorage(tmp_path)
            op, job, cid = await setup(conn, fs)
            first = await save(conn, fs, op, "First source.", url="https://e.test/1")
            await save(conn, fs, op, "Second source.", url="https://e.test/2")
            step = await _step(conn, fs, job, cid, b'{"step":2}')
            assert not await _erased(conn, step)
            await _erase(conn, first.artifact_key)
            assert await _erased(conn, step)

    run_async(case())


def test_a_source_published_after_the_step_does_not_erase_it(tmp_path) -> None:
    async def case() -> None:
        async with rollback_conn() as conn:
            fs = FsStorage(tmp_path)
            op, job, cid = await setup(conn, fs)
            await save(conn, fs, op, "Before.", url="https://e.test/before")
            step = await _step(conn, fs, job, cid, b'{"step":3}')
            later = await save(conn, fs, op, "After.", url="https://e.test/after")
            await _erase(conn, later.artifact_key)
            assert not await _erased(conn, step)

    run_async(case())


def test_person_steps_follow_the_subject_rule(tmp_path) -> None:
    """An account step sees every subject; a person step sees the account and itself only."""

    async def case() -> None:
        async with rollback_conn() as conn:
            fs = FsStorage(tmp_path)
            op, account_job, cid = await setup(conn, fs)
            pat, pat_op = await _person(conn, op, account_job, "Pat Fixture")
            _quinn, quinn_op = await _person(conn, op, account_job, "Quinn Fixture")
            account_source = await save(conn, fs, op, "Account fact.", url="https://e.test/a")
            pat_source = await save(conn, fs, pat_op, "Pat fact.", url="https://e.test/p")
            quinn_source = await save(conn, fs, quinn_op, "Quinn fact.", url="https://e.test/q")
            pat_step = await _step(conn, fs, pat, cid, b'{"pat":1}')
            account_step = await _step(conn, fs, account_job, cid, b'{"account":1}')

            savepoint = await conn.begin_nested()
            await _erase(conn, quinn_source.artifact_key)
            assert not await _erased(conn, pat_step)
            assert await _erased(conn, account_step)
            await savepoint.rollback()

            for source in (pat_source, account_source):
                savepoint = await conn.begin_nested()
                await _erase(conn, source.artifact_key)
                assert await _erased(conn, pat_step)
                await savepoint.rollback()

    run_async(case())


def test_erasing_a_context_document_erases_the_step(tmp_path) -> None:
    async def case() -> None:
        async with rollback_conn() as conn:
            fs = FsStorage(tmp_path)
            op, job, cid = await setup(conn, fs)
            await save(conn, fs, op, "A source.", url="https://e.test/c")
            step = await _step(conn, fs, job, cid, b'{"step":5}')
            document = (
                await conn.execute(
                    text(
                        "SELECT artifact_key FROM arv2_context_document "
                        "WHERE context_id=:cid ORDER BY artifact_key LIMIT 1"
                    ),
                    {"cid": cid},
                )
            ).scalar_one()
            await _erase(conn, document)
            assert await _erased(conn, step)

    run_async(case())


def test_a_step_cannot_be_saved_once_a_source_in_scope_is_erased(tmp_path) -> None:
    async def case() -> None:
        async with rollback_conn() as conn:
            fs = FsStorage(tmp_path)
            op, job, cid = await setup(conn, fs)
            source = await save(conn, fs, op, "Erased soon.", url="https://e.test/e")
            await _erase(conn, source.artifact_key)
            with pytest.raises(ArtifactIntegrityError):
                await _step(conn, fs, job, cid, b'{"step":6}')

    run_async(case())


def test_the_same_bytes_saved_again_keep_the_higher_watermark(tmp_path) -> None:
    async def case() -> None:
        async with rollback_conn() as conn:
            fs = FsStorage(tmp_path)
            op, job, cid = await setup(conn, fs)
            await save(conn, fs, op, "One.", url="https://e.test/one")
            step = await _step(conn, fs, job, cid, b'{"same":1}')
            later = await save(conn, fs, op, "Two.", url="https://e.test/two")
            assert step == await _step(conn, fs, job, cid, b'{"same":1}')
            await _erase(conn, later.artifact_key)
            assert await _erased(conn, step)

    run_async(case())


def test_saving_holds_the_shared_lineage_lock_and_erasing_takes_it_exclusively(tmp_path) -> None:
    """The lock closes the window between a step's erasure check and its watermark row."""

    held = (
        "SELECT mode FROM pg_locks WHERE pid=pg_backend_pid() AND locktype='advisory' "
        "AND (classid::bigint<<32 | objid::bigint)=:key"
    )

    async def case() -> None:
        async with rollback_conn() as conn:
            fs = FsStorage(tmp_path)
            op, job, cid = await setup(conn, fs)
            source = await save(conn, fs, op, "Locked.", url="https://e.test/l")
            key = (
                await conn.execute(
                    text("SELECT hashtextextended(:name, 0)"),
                    {"name": lineage_lock_name(op.workspace_id, op.run_id, op.account_id)},
                )
            ).scalar_one()
            await _step(conn, fs, job, cid, b'{"step":8}')
            modes = set((await conn.execute(text(held), {"key": key})).scalars())
            assert "ShareLock" in modes
            await _erase(conn, source.artifact_key)
            modes = set((await conn.execute(text(held), {"key": key})).scalars())
            assert "ExclusiveLock" in modes

    run_async(case())


def _migration() -> Any:
    import importlib.util
    from pathlib import Path

    path = next(Path("alembic/versions").glob("ecc5f641c0d9_*.py"))
    spec = importlib.util.spec_from_file_location("lineage_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _old_style_artifact(
    conn: Any, storage: Any, job: Any, body: bytes, parents: list[str], *, step: bool
) -> str:
    """An artifact saved the pre-2026-10-12 way: one derivation link per parent."""
    from clue_storage import record_artifact

    sha = content_address(body)
    key = artifact_key(job.workspace_id, sha)
    await record_artifact(
        conn,
        storage_key=key,
        workspace_id=job.workspace_id,
        content_sha256=sha,
        media_type="application/json",
        size_bytes=len(body),
    )
    await storage.put(key, body, media_type="application/json")
    if step:
        await conn.execute(
            text(
                "INSERT INTO agent_artifact_project(workspace_id,project_id,artifact_key,"
                "binding_kind) VALUES(:ws,:project,:key,'research_execution')"
            ),
            {"ws": job.workspace_id, "project": job.project_id, "key": key},
        )
    for parent in parents:
        await conn.execute(
            text(
                "INSERT INTO artifact_derivation(workspace_id,parent_key,child_key) "
                "VALUES(:ws,:parent,:key)"
            ),
            {"ws": job.workspace_id, "parent": parent, "key": key},
        )
    return key


async def _links(conn: Any, key: str) -> set[str]:
    return set(
        (
            await conn.execute(
                text("SELECT parent_key FROM artifact_derivation WHERE child_key=:key"),
                {"key": key},
            )
        ).scalars()
    )


def test_the_backfill_script_converts_old_steps_and_keeps_every_erasure(tmp_path) -> None:
    async def case() -> None:
        async with rollback_conn() as conn:
            fs = FsStorage(tmp_path)
            op, account_job, cid = await setup(conn, fs)
            pat, pat_op = await _person(conn, op, account_job, "Pat Fixture")
            _quinn, quinn_op = await _person(conn, op, account_job, "Quinn Fixture")
            a1 = await save(conn, fs, op, "Account one.", url="https://e.test/a1")
            p1 = await save(conn, fs, pat_op, "Pat one.", url="https://e.test/p1")
            q1 = await save(conn, fs, quinn_op, "Quinn one.", url="https://e.test/q1")
            later = await save(conn, fs, op, "Account later.", url="https://e.test/a2")
            document = (
                await conn.execute(
                    text(
                        "SELECT artifact_key FROM arv2_context_document "
                        "WHERE context_id=:cid ORDER BY artifact_key LIMIT 1"
                    ),
                    {"cid": cid},
                )
            ).scalar_one()
            # A person step that saw the account and Pat (not Quinn), and the context.
            pat_parents = [a1.artifact_key, p1.artifact_key, document]
            pat_step = await _old_style_artifact(
                conn, fs, pat, b'{"old":1}', pat_parents, step=True
            )
            # An account step that saw everyone up to Quinn's source.
            acct_parents = [a1.artifact_key, p1.artifact_key, q1.artifact_key]
            acct_step = await _old_style_artifact(
                conn, fs, account_job, b'{"old":2}', acct_parents, step=True
            )
            # A claim-style artifact citing one source: not a step, never converted.
            precise = await _old_style_artifact(
                conn, fs, account_job, b'{"claim":1}', [a1.artifact_key], step=False
            )
            # Batches of two, in key order, the way the script walks a live database.
            after = ""
            while keys := await next_children(conn, after, 2):
                await convert(conn, keys)
                after = keys[-1]

            assert await _links(conn, pat_step) == set()
            assert await _links(conn, acct_step) == set()
            assert await _links(conn, precise) == {a1.artifact_key}
            watermarks = (
                await conn.execute(
                    text(
                        "SELECT child_key, subject_key, evidence_revision "
                        "FROM artifact_evidence_watermark WHERE child_key = ANY(:keys)"
                    ),
                    {"keys": [pat_step, acct_step, precise]},
                )
            ).all()
            assert {(k, s, r) for k, s, r in watermarks} == {
                (pat_step, pat.contact_id, p1.revision),
                (acct_step, op.account_id, q1.revision),
            }

            # Every erasure today's links made still happens; a later source still does not.
            cases = [
                (a1, {pat_step, acct_step, precise}),
                (p1, {pat_step, acct_step}),
                (q1, {acct_step}),
                (later, set()),
            ]
            for source, expected in cases:
                savepoint = await conn.begin_nested()
                await _erase(conn, source.artifact_key)
                erased = {k for k in (pat_step, acct_step, precise) if await _erased(conn, k)}
                assert erased == expected, source.url
                await savepoint.rollback()
            savepoint = await conn.begin_nested()
            await _erase(conn, document)
            assert await _erased(conn, pat_step)
            await savepoint.rollback()

    run_async(case())


def test_the_downgrade_expansion_restores_every_link_the_backfill_removed(tmp_path) -> None:
    async def case() -> None:
        migration = _migration()
        async with rollback_conn() as conn:
            fs = FsStorage(tmp_path)
            op, account_job, cid = await setup(conn, fs)
            sources = [
                await save(conn, fs, op, f"Source {i}.", url=f"https://e.test/x{i}")
                for i in range(4)
            ]
            parents = [s.artifact_key for s in sources[:3]]
            step = await _old_style_artifact(conn, fs, account_job, b'{"x":1}', parents, step=True)
            await convert(conn, [step])
            assert await _links(conn, step) == set()
            await conn.execute(text(migration.EXPAND_EVIDENCE_LINKS))
            await conn.execute(text(migration.EXPAND_CONTEXT_LINKS))
            assert await _links(conn, step) == set(parents)

    run_async(case())


def test_running_the_backfill_again_changes_nothing(tmp_path) -> None:
    async def case() -> None:
        async with rollback_conn() as conn:
            fs = FsStorage(tmp_path)
            op, account_job, _cid = await setup(conn, fs)
            sources = [
                await save(conn, fs, op, f"Again {i}.", url=f"https://e.test/g{i}")
                for i in range(3)
            ]
            parents = [s.artifact_key for s in sources]
            step = await _old_style_artifact(conn, fs, account_job, b'{"g":1}', parents, step=True)
            first = await convert(conn, [step])
            assert first.watermarks == 1 and first.links_deleted == 3
            again = await convert(conn, [step])
            assert again.links_deleted == 0
            rows = (
                (
                    await conn.execute(
                        text(
                            "SELECT evidence_revision FROM artifact_evidence_watermark "
                            "WHERE child_key=:key"
                        ),
                        {"key": step},
                    )
                )
                .scalars()
                .all()
            )
            assert rows == [sources[-1].revision]

    run_async(case())
