"""Real shared-store persistence, source scope, savepoint recovery and replay."""

import hashlib
from dataclasses import replace
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_api.arv2 import dossier_import, import_storage
from clue_api.arv2.quality_evidence import grant_manifest, revoke_grant
from clue_storage import StorageError
from clue_storage.fs import FsStorage
from tests.arv2.test_dossier_json import document, finding
from tests.arv2.test_quality_claims_db import setup
from tests.arv2.test_quality_evidence_db import save
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


async def context(conn, tmp_path):
    storage = FsStorage(tmp_path)
    op, job, cid = await setup(conn, storage)
    job = replace(job, catalog_version="v4", input_refs={"quality_recipe_version": 15})
    source = await save(
        conn,
        storage,
        op,
        "Original source — exact public words.",
        url="https://example.test/interview",
    )
    grant = await grant_manifest(conn, op, consumer_id=uuid4())
    return (
        storage,
        job,
        grant,
        {
            "context_id": cid,
            "actor_ref": "dossier-import-test",
            "import_id": uuid4(),
            "source_aliases": {"/evidence/001-interview.json": source.source_id},
        },
    )


async def invoke(conn, ctx, body):
    storage, job, grant, kwargs = ctx
    return await dossier_import.import_account_dossier(
        conn,
        storage,
        job,
        grant,
        body=body,
        expected_sha256=hashlib.sha256(body).hexdigest(),
        **kwargs,
    )


def test_all_statuses_exact_roundtrip_replay_and_immutable_import(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            ctx = await context(conn, tmp_path)
            entries = [
                finding(),
                finding(
                    "F002", review={"status": "duplicate", "reason": "Same", "duplicate_of": "F001"}
                ),
                finding(
                    "F003",
                    review={
                        "status": "potential_conflict",
                        "reason": "Unclear",
                        "conflicts_with": ["F001"],
                    },
                ),
                finding(
                    "F004",
                    review={
                        "status": "wrong_entity",
                        "reason": "Namesake",
                        "expected_entity": {"name": "Other"},
                    },
                ),
                finding(
                    "F005", review={"status": "insufficient_context", "reason": "Partial source"}
                ),
                finding("F006", source_paths=[]),
            ]
            body = document(*reversed(entries))
            first = await invoke(conn, ctx, body)
            assert first["complete"] and first["stored"] == 6, first
            assert all(c["content_and_metadata_equal"] for c in first["roundtrip_checks"])
            mapping = {r["id"]: r["claim_id"] for r in first["entries"]}
            for entry in entries:
                value = (
                    await conn.execute(
                        text("SELECT value_json FROM claim WHERE id=:id"),
                        {"id": mapping[entry["id"]]},
                    )
                ).scalar_one()
                assert value["dossier_entry"]["original"] == entry
                assert value["finding"] == entry["finding"]
                assert value["review"]["status"] == entry["review"]["status"]
                if entry["id"] == "F002":
                    assert value["review"]["duplicate_of"] == str(mapping["F001"])
                if entry["id"] == "F003":
                    assert value["review"]["conflicts_with"] == [str(mapping["F001"])]
            repeated = await invoke(conn, ctx, body)
            assert repeated["complete"] and all(r["replayed"] for r in repeated["entries"])
            assert mapping == {r["id"]: r["claim_id"] for r in repeated["entries"]}
            with pytest.raises(ValueError, match="different JSON"):
                await invoke(conn, ctx, document(finding(finding="Changed")))

    run_async(case())


def test_failed_write_savepoint_rolls_back_and_retry_fills_only_missing_records(
    tmp_path, monkeypatch
):
    async def case():
        async with rollback_conn() as conn:
            ctx = await context(conn, tmp_path)
            original = dossier_import.submit_proposal

            async def fail_after_write(*args, **kwargs):
                receipt = await original(*args, **kwargs)
                if args[4].value["dossier_entry"]["id"] == "F001":
                    raise RuntimeError("Simulated interruption after DB writes")
                return receipt

            monkeypatch.setattr(dossier_import, "submit_proposal", fail_after_write)
            body = document(
                finding(),
                finding(
                    "F002", review={"status": "duplicate", "reason": "Same", "duplicate_of": "F001"}
                ),
                finding("F003"),
            )
            partial = await invoke(conn, ctx, body)
            assert not partial["complete"] and partial["stored"] == 1
            assert partial["entries"][0]["id"] == "F003" and len(partial["errors"]) == 2
            monkeypatch.setattr(dossier_import, "submit_proposal", original)
            repaired = await invoke(conn, ctx, body)
            assert repaired["complete"] and repaired["stored"] == 3
            assert next(r for r in repaired["entries"] if r["id"] == "F003")["replayed"]
            count = (
                await conn.execute(
                    text("SELECT count(*) FROM arv2_quality_proposal WHERE job_id=:job"),
                    {"job": ctx[1].job_id},
                )
            ).scalar_one()
            assert count == 3

    run_async(case())


def test_unknown_sources_revoked_grant_and_cross_context_never_become_success(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            ctx = await context(conn, tmp_path)
            result = await invoke(
                conn,
                ctx,
                document(finding(source_paths=["/evidence/missing.json"]), finding("F002")),
            )
            assert not result["complete"] and result["stored"] == 1
            storage, job, grant, kwargs = ctx
            with pytest.raises(ValueError, match="pinned research context"):
                await invoke(
                    conn,
                    (storage, job, grant, {**kwargs, "context_id": uuid4()}),
                    document(finding()),
                )
            with pytest.raises(ValueError, match="does not belong"):
                await invoke(
                    conn,
                    (storage, replace(job, job_id=uuid4()), grant, kwargs),
                    document(finding()),
                )
            await revoke_grant(conn, grant)
            with pytest.raises(Exception, match="revoked|unavailable|grant"):
                await invoke(conn, ctx, document(finding()))

    run_async(case())


def test_person_dossier_stays_on_contact_and_cannot_be_retargeted_to_account(tmp_path):
    from clue_api.arv2.account_research_store import create_job
    from clue_api.arv2.research_operations import OperationScope
    from clue_research.identity import insert_contact_entity

    async def case():
        async with rollback_conn() as conn:
            storage, account, _, kwargs = await context(conn, tmp_path)
            contact = await insert_contact_entity(
                conn, account_entity_id=account.account_id, full_name="Alex Fixture"
            )
            jid = uuid4()
            await create_job(
                conn,
                job_id=jid,
                run_id=account.run_id,
                workspace_id=account.workspace_id,
                account_entity_id=account.account_id,
                subject_type="person",
                subject_entity_id=contact,
                profile_sha256="a" * 64,
            )
            job = replace(account, job_id=jid, subject_kind="person", contact_id=contact)
            op = OperationScope(job.workspace_id, job.run_id, jid, job.account_id)
            source = await save(conn, storage, op, "I built this side project.")
            grant = await grant_manifest(conn, op, consumer_id=uuid4())
            kwargs["source_aliases"] = {"/evidence/001-interview.json": source.source_id}
            ctx = (storage, job, grant, kwargs)
            result = await invoke(
                conn, ctx, document(finding(finding="I built this side project."))
            )
            assert result["complete"] and result["stored"] == 1, result
            row = (
                await conn.execute(
                    text(
                        "SELECT entity_id,entity_type,field_key,outreach_safe "
                        "FROM claim WHERE id=:id"
                    ),
                    {"id": result["entries"][0]["claim_id"]},
                )
            ).one()
            assert row.entity_id == contact and row.entity_type == "contact"
            assert row.field_key == "contact.research_finding" and not row.outreach_safe
            assert (
                await invoke(conn, ctx, document(finding(finding="I built this side project.")))
            )["entries"][0]["replayed"]
            with pytest.raises(ValueError, match="subject does not match"):
                await invoke(
                    conn,
                    (storage, replace(job, subject_kind="account", contact_id=None), grant, kwargs),
                    document(finding()),
                )

    run_async(case())


def test_reciprocal_conflicts_rollback_together_then_retry_with_exact_links(tmp_path, monkeypatch):
    async def case():
        async with rollback_conn() as conn:
            ctx = await context(conn, tmp_path)
            original = dossier_import.submit_proposal

            async def fail_second(*args, **kwargs):
                receipt = await original(*args, **kwargs)
                if args[4].value["dossier_entry"]["id"] == "F002":
                    raise RuntimeError("Injected second linked write failure")
                return receipt

            a = finding(
                review={
                    "status": "potential_conflict",
                    "reason": "Unclear",
                    "conflicts_with": ["F002"],
                }
            )
            b = finding(
                "F002",
                review={
                    "status": "potential_conflict",
                    "reason": "Unclear",
                    "conflicts_with": ["F001"],
                },
            )
            dependent = finding(
                "F004", review={"status": "duplicate", "reason": "Same", "duplicate_of": "F001"}
            )
            body = document(dependent, a, b, finding("F003"))
            before = (await conn.execute(text("SELECT count(*) FROM claim"))).scalar_one()
            monkeypatch.setattr(dossier_import, "submit_proposal", fail_second)
            partial = await invoke(conn, ctx, body)
            assert not partial["complete"] and partial["stored"] == 1, partial
            assert [e["id"] for e in partial["entries"]] == ["F003"]
            assert {e["id"] for e in partial["errors"]} == {"F001", "F002", "F004"}
            assert (
                await conn.execute(text("SELECT count(*) FROM claim"))
            ).scalar_one() == before + 1
            monkeypatch.setattr(dossier_import, "submit_proposal", original)
            repaired = await invoke(conn, ctx, body)
            assert repaired["complete"] and repaired["stored"] == 4, repaired
            ids = {e["id"]: e["claim_id"] for e in repaired["entries"]}
            for key, other in (("F001", "F002"), ("F002", "F001")):
                value = (
                    await conn.execute(
                        text("SELECT value_json FROM claim WHERE id=:id"), {"id": ids[key]}
                    )
                ).scalar_one()
                assert value["review"]["conflicts_with"] == [str(ids[other])]
                assert value["review"]["status"] == "potential_conflict"
            replay = await invoke(conn, ctx, body)
            assert replay["complete"] and all(e["replayed"] for e in replay["entries"])
            assert ids == {e["id"]: e["claim_id"] for e in replay["entries"]}

    run_async(case())


class _CountingStorage:
    """Counts reads per key and fails an upload on request; delegates everything else."""

    def __init__(self, inner: Any, *, fail_put: bool = False) -> None:
        self._inner = inner
        self._fail_put = fail_put
        self.gets: dict[str, int] = {}

    async def get(self, key: str) -> bytes:
        self.gets[key] = self.gets.get(key, 0) + 1
        return await self._inner.get(key)

    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        if self._fail_put:
            raise StorageError("simulated upload failure")
        await self._inner.put(key, data, media_type=media_type)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def test_import_reads_each_blob_once_however_many_findings_cite_it(tmp_path):
    """Research slowness fix 2026-10-03: the context manifest and each cited source used to be
    read from storage once per finding, one round trip at a time."""

    async def case():
        async with rollback_conn() as conn:
            storage, job, grant, kwargs = await context(conn, tmp_path)
            counting = _CountingStorage(storage)
            body = document(finding("F001"), finding("F002"), finding("F003"))
            result = await invoke(conn, (counting, job, grant, kwargs), body)
            assert result["stored"] == 3
            assert counting.gets and max(counting.gets.values()) == 1

    run_async(case())


def test_an_artifact_erased_after_prefetch_is_still_refused(tmp_path, monkeypatch):
    async def case():
        async with rollback_conn() as conn:
            ctx = await context(conn, tmp_path)
            _storage, _job, _grant, kwargs = ctx
            source_id = next(iter(kwargs["source_aliases"].values()))
            original_prefetch = import_storage.ImportStorage.prefetch

            async def prefetch_then_erase(self, keys):
                await original_prefetch(self, keys)
                await conn.execute(
                    text(
                        "UPDATE artifact SET erased_at=now() WHERE storage_key=("
                        "SELECT artifact_key FROM arv2_evidence_source WHERE source_id=:id)"
                    ),
                    {"id": source_id},
                )

            monkeypatch.setattr(import_storage.ImportStorage, "prefetch", prefetch_then_erase)
            result = await invoke(conn, ctx, document(finding("F001")))
            assert not result["complete"] and result["stored"] == 0

    run_async(case())


def test_a_failed_upload_fails_the_import(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            storage, job, grant, kwargs = await context(conn, tmp_path)
            failing = _CountingStorage(storage, fail_put=True)
            with pytest.raises(StorageError):
                await invoke(conn, (failing, job, grant, kwargs), document(finding("F001")))

    run_async(case())
