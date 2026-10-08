"""Complete originals, scoped reads, exact locators and revocation on the real substrate."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from clue_api.arv2.account_research_catalog import arv2_account_profile_sha256
from clue_api.arv2.account_research_launch import launch_arv2_account_research
from clue_api.arv2.quality_evidence import (
    EvidenceGrant,
    EvidenceUnavailable,
    JsonSupport,
    TextSupport,
    grant_manifest,
    list_sources,
    persist_source,
    read_source,
    record_disposition,
    resolve_source,
    revoke_grant,
    search_source,
    validate_support,
)
from clue_api.arv2.research_operations import OperationScope, begin
from clue_storage import ArtifactIntegrityError, artifact_key, content_address, record_artifact
from clue_storage.fs import FsStorage
from tests.arv2.icp_fixture import seed_icp_fixture, settings_for
from tests.arv2.test_account_research_launch_db import _request
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
    rollback_conn,
    run_async,
)

pytestmark = pytest.mark.usefixtures("require_claimstore_db")
NOW = datetime(2026, 9, 22, tzinfo=UTC)


async def seed(conn, storage):
    f = await seed_icp_fixture(conn, storage)
    receipt = await launch_arv2_account_research(
        conn,
        _request(f),
        storage=storage,
        settings=settings_for(
            arv2_account_research_enabled=True, arv2_research_catalog_version="v2"
        ),
        profile_sha256=arv2_account_profile_sha256(version="v2"),
    )
    return [
        OperationScope(f.workspace_id, receipt.run_id, jid, UUID(str(aid)))
        for jid, aid in zip(receipt.job_ids, f.accounts, strict=True)
    ]


async def save(
    conn,
    storage,
    scope,
    body,
    *,
    url="https://example.test/source",
    original=None,
    kind="web_snapshot",
):
    return await persist_source(
        conn,
        storage,
        scope,
        kind=kind,
        body=body,
        original_key=original,
        origin_locator="fixture",
        observed_at=NOW,
        source_url=url,
    )


def test_complete_report_pages_exact_spans_and_new_worker_reconstruction(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            scope, _ = await seed(conn, storage)
            report = (
                "Opening summary.\n"
                + ("Background context.\n" * 1200)
                + "Distinct referral intake finding."
            )
            source = await save(conn, storage, scope, report, kind="research_report")
            assert (
                await save(conn, storage, scope, report, kind="research_report")
            ).source_id == source.source_id
            grant = await grant_manifest(conn, scope, consumer_id=uuid4())
            rebuilt = EvidenceGrant(scope, grant.consumer_id, grant.grant_id)
            first = await read_source(
                conn, FsStorage(tmp_path), rebuilt, source.source_id, limit=100
            )
            assert first["next_start"] == 100
            match = await search_source(
                conn, storage, grant, source.source_id, query="Distinct referral"
            )
            start = match["matches"][0]["start"]
            quote = "Distinct referral intake finding."
            valid = TextSupport(
                source_id=source.source_id, start=start, end=start + len(quote), quote=quote
            )
            await validate_support(conn, storage, grant, valid)
            with pytest.raises(EvidenceUnavailable, match="exact contiguous"):
                await validate_support(
                    conn,
                    storage,
                    grant,
                    valid.model_copy(update={"quote": "Opening summary. " + quote}),
                )
            with pytest.raises(EvidenceUnavailable):
                await resolve_source(conn, grant, uuid4())
            did = await record_disposition(
                conn,
                storage,
                grant,
                source_id=source.source_id,
                unit_locator=f"{start}:{start + len(quote)}",
                decision="gap",
                receipt={"reason": "needs original page"},
            )
            assert did == await record_disposition(
                conn,
                storage,
                grant,
                source_id=source.source_id,
                unit_locator=f"{start}:{start + len(quote)}",
                decision="gap",
                receipt={"reason": "needs original page"},
            )

    run_async(case())


def test_grant_freezes_manifest_and_denies_other_account_and_workspace(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            scope, other = await seed(conn, storage)
            first = await save(conn, storage, scope, "Same original.", url="https://one.test/a")
            grant = await grant_manifest(conn, scope, consumer_id=uuid4())
            second = await save(conn, storage, scope, "Same original.", url="https://two.test/a")
            foreign = await save(conn, storage, other, "Other account.")
            assert first.artifact_key == second.artifact_key and first.source_id != second.source_id
            for denied in (second.source_id, foreign.source_id):
                with pytest.raises(EvidenceUnavailable):
                    await resolve_source(conn, grant, denied)
            with pytest.raises(EvidenceUnavailable):
                await list_sources(
                    conn, replace(grant, scope=replace(scope, workspace_id="foreign"))
                )
            assert len((await list_sources(conn, grant))["sources"]) == 1
            fresh = await grant_manifest(conn, scope, consumer_id=grant.consumer_id)
            assert fresh.grant_id != grant.grant_id
            page = await list_sources(conn, fresh, limit=1)
            assert page["next_after"] == first.revision
            page = await list_sources(conn, fresh, limit=1, after=page["next_after"])
            assert (
                page["sources"][0]["source_id"] == str(second.source_id)
                and page["next_after"] is None
            )
            await revoke_grant(conn, fresh)
            with pytest.raises(EvidenceUnavailable):
                await read_source(conn, storage, fresh, first.source_id)

    run_async(case())


def test_provider_pointer_type_and_erasure_propagate_to_derived_copies(tmp_path):
    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            scope, _ = await seed(conn, storage)
            raw = json.dumps({"provider": "fixture", "body": {"count": 64}}).encode()
            sha = content_address(raw)
            key = artifact_key(scope.workspace_id, sha)
            await record_artifact(
                conn,
                workspace_id=scope.workspace_id,
                storage_key=key,
                content_sha256=sha,
                media_type="application/json",
                size_bytes=len(raw),
            )
            await storage.put(key, raw, media_type="application/json")
            source = await save(
                conn,
                storage,
                scope,
                {"a/b": {"~count": [64]}},
                original=key,
                kind="provider_record",
            )
            grant = await grant_manifest(conn, scope, consumer_id=uuid4())
            support = JsonSupport(
                source_id=source.source_id, pointer="/a~1b/~0count/0", expected_value=64
            )
            await validate_support(conn, storage, grant, support)
            for wrong in ("64", True, 65):
                with pytest.raises(EvidenceUnavailable):
                    await validate_support(
                        conn, storage, grant, support.model_copy(update={"expected_value": wrong})
                    )
            with pytest.raises(EvidenceUnavailable):
                await validate_support(
                    conn, storage, grant, support.model_copy(update={"pointer": "/a~1b/~0count/00"})
                )
            await conn.execute(
                text(
                    "UPDATE artifact SET privacy_erased=true,erased_at=now(), "
                    "erasure_reason='privacy' "
                    "WHERE storage_key=:key"
                ),
                {"key": key},
            )
            assert (
                await conn.execute(
                    text("SELECT privacy_erased FROM artifact WHERE storage_key=:key"),
                    {"key": source.artifact_key},
                )
            ).scalar_one()
            with pytest.raises(ArtifactIntegrityError):
                await read_source(conn, storage, grant, source.source_id)
            listed = (await list_sources(conn, grant))["sources"]
            assert listed == [
                {
                    "source_id": str(source.source_id),
                    "revision": source.revision,
                    "available": False,
                }
            ]

    run_async(case())


def test_provider_drain_preserves_full_report_and_source_pages_with_ledger_join(tmp_path):
    from clue_api.arv2.provider_ledger import (
        BufferedLedger,
        BufferedRawSink,
        LedgerStamp,
        drain_provider_calls,
    )
    from clue_api.arv2.quality_acquisition import index_acquisition
    from clue_api.arv2.sinks import LedgerRow
    from tests.arv2.test_committee_discovery_v2_db import Artifacts
    from tests.arv2.test_provider_ledger import _record

    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            scope, _ = await seed(conn, storage)
            raw = BufferedRawSink()
            ledger = BufferedLedger()
            source_body = "Exact official referral information."
            report_body = "Report introduction.\n" + ("Full unabridged finding.\n" * 1400)
            ref = raw.save(
                _record(NOW),
                json.dumps(
                    {
                        "output": {"content": {"report": report_body}},
                        "results": [{"url": "https://clinic.test/referral", "text": source_body}],
                    }
                ).encode(),
            )
            ledger.record(
                LedgerRow(
                    row_id="test-quality-ledger",
                    call_id="test-quality-call",
                    phase="result",
                    provider="exa",
                    operation="deep",
                    label="quality",
                    recorded_at=NOW,
                    http_status=200,
                    raw_ref=ref,
                    outcome="ok",
                )
            )
            project = (
                await conn.execute(
                    text("SELECT project_id FROM arv2_research_run WHERE run_id=:id"),
                    {"id": scope.run_id},
                )
            ).scalar_one()
            report = await drain_provider_calls(
                conn,
                raw=raw,
                ledger=ledger,
                artifacts=Artifacts(conn, storage),
                stamp=LedgerStamp(
                    workspace_id=scope.workspace_id, project_id=project, job_id=scope.job_id
                ),
            )
            refs = await index_acquisition(conn, storage, scope, report)
            by_locator = {r.origin_locator: r for r in refs}
            assert {locator: r.kind for locator, r in by_locator.items()} == {
                "response-body": "provider_record",
                "output.report": "research_report",
                "results/0": "provider_record",
                "results/0/text": "web_snapshot",
            }
            assert all(r.ledger_id is not None for r in refs)
            grant = await grant_manifest(conn, scope, consumer_id=uuid4())
            read = await read_source(
                conn,
                storage,
                grant,
                by_locator["output.report"].source_id,
                start=len(report_body) - 100,
            )
            assert read["text"] == report_body[-100:]
            full_result = await read_source(conn, storage, grant, by_locator["results/0"].source_id)
            assert json.loads(full_result["text"]) == {
                "url": "https://clinic.test/referral",
                "text": source_body,
            }
            original = await read_source(
                conn, storage, grant, by_locator["results/0/text"].source_id
            )
            assert original["text"] == source_body
            assert original["source_url"] == "https://clinic.test/referral"
            again = await index_acquisition(conn, storage, scope, report)
            assert [r.source_id for r in refs] == [r.source_id for r in again]

    run_async(case())


def test_operation_navigation_stays_scoped_and_marks_erased_sources_unavailable(tmp_path):
    from clue_api.arv2.quality_source_navigation import operation_source_navigation

    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            scope, other = await seed(conn, storage)
            target_op, _ = await begin(conn, scope, "account_deep", {"query": "target"})
            other_op, _ = await begin(conn, scope, "account_deep", {"query": "other"})
            target, unrelated = target_op.operation_id, other_op.operation_id
            refs = []
            for subject, operation, body in (
                (scope, target, "Included excerpt"),
                (scope, target, "Later erased excerpt"),
                (scope, unrelated, "Another purchase"),
                (other, target, "Other account"),
            ):
                refs.append(
                    await persist_source(
                        conn,
                        storage,
                        subject,
                        kind="web_snapshot",
                        body=body,
                        original_key=None,
                        origin_locator="results/0/highlights/0",
                        observed_at=NOW,
                        source_url="https://example.test/source",
                        operation_id=operation,
                        metadata={"content_kind": "highlight"},
                    )
                )
            grant = await grant_manifest(conn, scope, consumer_id=uuid4())
            result = await operation_source_navigation(conn, grant, target)
            assert {x["source_id"] for x in result["sources"]} == {
                str(r.source_id) for r in refs[:2]
            }
            await conn.execute(
                text(
                    "UPDATE artifact SET privacy_erased=true,erased_at=now(),"
                    "erasure_reason='privacy' "
                    "WHERE storage_key=:key"
                ),
                {"key": refs[1].artifact_key},
            )
            result = await operation_source_navigation(conn, grant, target)
            assert [x["source_id"] for x in result["sources"]] == [str(refs[0].source_id)]
            assert result["unavailable_source_count"] == 1

    run_async(case())


def test_recovery_pages_through_more_receipts_than_one_batch_and_terminates(tmp_path, monkeypatch):
    """Publication is deferred to the end of recovery, so paging must exclude what it already
    prepared instead of relying on "not yet published" (research slowness fix 2026-10-03)."""
    from clue_api.arv2 import quality_acquisition
    from clue_api.arv2.provider_ledger import (
        BufferedLedger,
        BufferedRawSink,
        LedgerStamp,
        drain_provider_calls,
    )
    from clue_api.arv2.sinks import LedgerRow
    from tests.arv2.test_committee_discovery_v2_db import Artifacts
    from tests.arv2.test_provider_ledger import _record

    monkeypatch.setattr(quality_acquisition, "_RECOVERY_BATCH", 2)

    async def case():
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path)
            scope, _ = await seed(conn, storage)
            raw = BufferedRawSink()
            ledger = BufferedLedger()
            for i in range(5):
                ref = raw.save(
                    _record(NOW),
                    json.dumps(
                        {"results": [{"url": f"https://e.test/{i}", "text": f"Page {i} text."}]}
                    ).encode(),
                )
                ledger.record(
                    LedgerRow(
                        row_id=f"test-recovery-ledger-{i}",
                        call_id=f"test-recovery-call-{i}",
                        phase="result",
                        provider="exa",
                        operation="search",
                        label="quality",
                        recorded_at=NOW,
                        http_status=200,
                        raw_ref=ref,
                        outcome="ok",
                    )
                )
            project = (
                await conn.execute(
                    text("SELECT project_id FROM arv2_research_run WHERE run_id=:id"),
                    {"id": scope.run_id},
                )
            ).scalar_one()
            await drain_provider_calls(
                conn,
                raw=raw,
                ledger=ledger,
                artifacts=Artifacts(conn, storage),
                stamp=LedgerStamp(
                    workspace_id=scope.workspace_id, project_id=project, job_id=scope.job_id
                ),
            )
            refs = await asyncio.wait_for(
                quality_acquisition.recover_acquisitions(conn, storage, scope), 30
            )
            assert len({r.ledger_id for r in refs}) == 5
            assert len({r.source_id for r in refs}) == len(refs)
            revisions = sorted(r.revision for r in refs)
            assert revisions == list(range(revisions[0], revisions[0] + len(refs)))
            assert await quality_acquisition.recover_acquisitions(conn, storage, scope) == ()

    run_async(case())


class _CountingStorage:
    """Counts storage round trips and how many uploads run at once (W2-16)."""

    def __init__(self, inner: FsStorage) -> None:
        self.inner, self.gets, self.puts, self.inflight, self.max_inflight = inner, 0, 0, 0, 0

    async def get(self, key: str) -> bytes:
        self.gets += 1
        return await self.inner.get(key)

    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        self.puts += 1
        self.inflight += 1
        self.max_inflight = max(self.max_inflight, self.inflight)
        try:
            await asyncio.sleep(0.01)  # an upload takes time; parallel uploads overlap
            await self.inner.put(key, data, media_type=media_type)
        finally:
            self.inflight -= 1

    def __getattr__(self, name: str):
        return getattr(self.inner, name)


async def _drained_deep_call(conn, storage, scope):
    from clue_api.arv2.provider_ledger import (
        BufferedLedger,
        BufferedRawSink,
        LedgerStamp,
        drain_provider_calls,
    )
    from clue_api.arv2.sinks import LedgerRow
    from tests.arv2.test_committee_discovery_v2_db import Artifacts
    from tests.arv2.test_provider_ledger import _record

    raw, ledger = BufferedRawSink(), BufferedLedger()
    results = [
        {"url": f"https://clinic.test/{i}", "title": f"Page {i}", "text": f"Page {i} text."}
        for i in range(5)
    ]
    ref = raw.save(
        _record(NOW),
        json.dumps({"output": {"content": {"report": "A report."}}, "results": results}).encode(),
    )
    ledger.record(
        LedgerRow(
            row_id=f"test-w216-{uuid4()}",
            call_id="test-w216-call",
            phase="result",
            provider="exa",
            operation="deep",
            label="quality",
            recorded_at=NOW,
            http_status=200,
            raw_ref=ref,
            outcome="ok",
        )
    )
    project = (
        await conn.execute(
            text("SELECT project_id FROM arv2_research_run WHERE run_id=:id"), {"id": scope.run_id}
        )
    ).scalar_one()
    return await drain_provider_calls(
        conn,
        raw=raw,
        ledger=ledger,
        artifacts=Artifacts(conn, storage),
        stamp=LedgerStamp(workspace_id=scope.workspace_id, project_id=project, job_id=scope.job_id),
    )


def test_indexing_a_drained_call_reads_nothing_back_and_uploads_in_parallel(tmp_path):
    """W2-16: the drain already holds the response; indexing must not download it again (once
    per source today), and the source files are uploaded together, not one after another."""
    from clue_api.arv2.quality_acquisition import index_acquisition

    async def case():
        async with rollback_conn() as conn:
            fs = FsStorage(tmp_path)
            scope, _ = await seed(conn, fs)
            storage = _CountingStorage(fs)
            report = await _drained_deep_call(conn, storage, scope)
            (key,) = report.raw_artifact_keys.values()
            assert report.raw_bodies[key] == await fs.get(key)
            storage.gets = storage.puts = storage.max_inflight = 0
            refs = await index_acquisition(conn, storage, scope, report)
            assert storage.gets == 0
            assert storage.puts == len({r.artifact_key for r in refs})
            assert storage.max_inflight > 1
            kinds = sorted(r.kind for r in refs)
            assert kinds.count("web_snapshot") == 5 and "research_report" in kinds

    run_async(case())


def test_an_original_erased_before_indexing_still_blocks_it(tmp_path):
    from clue_api.arv2.quality_acquisition import index_acquisition

    async def case():
        async with rollback_conn() as conn:
            fs = FsStorage(tmp_path)
            scope, _ = await seed(conn, fs)
            report = await _drained_deep_call(conn, fs, scope)
            (key,) = report.raw_artifact_keys.values()
            await conn.execute(
                text("UPDATE artifact SET erased_at=now() WHERE storage_key=:key"), {"key": key}
            )
            with pytest.raises(ArtifactIntegrityError, match="erased"):
                await index_acquisition(conn, fs, scope, report)

    run_async(case())


# -- W2-15 option B: source files are uploaded before the worker's database lock ---------------


def _connections(conn):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def factory():
        yield conn

    return factory


async def _early(conn, storage, scope, report):
    from clue_api.arv2.quality_acquisition import upload_sources_early

    return await upload_sources_early(
        _connections(conn),
        storage,
        scope,
        report.result_rows,
        report.raw_artifact_keys,
        report.raw_bodies,
    )


def _report_key(scope, report) -> str:
    """The storage key of the drained call's research-report source file."""
    from clue_api.arv2.quality_acquisition import planned_source_files

    files = planned_source_files(
        scope, report.result_rows, report.raw_artifact_keys, report.raw_bodies
    )
    return next(key for key, (data, _) in files.items() if data == b"A report.")


async def _gone(storage, key) -> bool:
    try:
        await storage.get(key)
    except Exception:
        return True
    return False


def test_source_files_uploaded_before_the_lock_are_not_uploaded_again(tmp_path):
    from clue_api.arv2.quality_acquisition import index_acquisition

    async def case():
        async with rollback_conn() as conn:
            fs = FsStorage(tmp_path)
            scope, _ = await seed(conn, fs)
            storage = _CountingStorage(fs)
            report = await _drained_deep_call(conn, storage, scope)
            storage.puts = 0
            uploaded = await _early(conn, storage, scope, report)
            assert storage.puts == len(uploaded) > 5
            storage.puts = storage.gets = 0
            refs = await index_acquisition(conn, storage, scope, report, uploaded=uploaded)
            assert storage.puts == 0 and storage.gets == 0
            assert {r.artifact_key for r in refs} <= uploaded
            for ref in refs:
                assert await fs.get(ref.artifact_key)

    run_async(case())


def test_a_source_file_purged_after_its_early_upload_is_uploaded_again(tmp_path):
    """The race the row lock used to exclude: an erased row's purge deletes the blob between the
    early upload and indexing. Indexing resurrects the row and must put the blob back."""
    from clue_api.arv2.quality_acquisition import index_acquisition
    from clue_storage import mark_erased, record_artifact

    async def case():
        async with rollback_conn() as conn:
            fs = FsStorage(tmp_path)
            scope, _ = await seed(conn, fs)
            report = await _drained_deep_call(conn, fs, scope)
            key = _report_key(scope, report)
            await record_artifact(
                conn,
                storage_key=key,
                workspace_id=scope.workspace_id,
                content_sha256=key.rsplit("/", 1)[1],
                media_type="text/plain",
                size_bytes=len(b"A report."),
            )
            await mark_erased(conn, key)
            uploaded = await _early(conn, fs, scope, report)
            assert key in uploaded
            # The purge runs now: blob deleted, row stamped purged.
            await fs.delete(key)
            await conn.execute(
                text("UPDATE artifact SET purged_at=now() WHERE storage_key=:k"), {"k": key}
            )
            await index_acquisition(conn, fs, scope, report, uploaded=uploaded)
            assert await fs.get(key) == b"A report."
            row = (
                await conn.execute(
                    text("SELECT erased_at, purged_at FROM artifact WHERE storage_key=:k"),
                    {"k": key},
                )
            ).one()
            assert row.erased_at is None and row.purged_at is None

    run_async(case())


async def _privacy_erase(conn, key) -> None:
    await conn.execute(
        text(
            "UPDATE artifact SET privacy_erased=true, erasure_reason='privacy', "
            "erased_at=now(), purged_at=now(), source_url=NULL WHERE storage_key=:k"
        ),
        {"k": key},
    )


def test_a_privacy_erased_source_file_is_never_uploaded_early(tmp_path):
    from clue_api.arv2.quality_acquisition import index_acquisition
    from clue_storage import record_artifact

    async def case():
        async with rollback_conn() as conn:
            fs = FsStorage(tmp_path)
            scope, _ = await seed(conn, fs)
            report = await _drained_deep_call(conn, fs, scope)
            key = _report_key(scope, report)
            await record_artifact(
                conn,
                storage_key=key,
                workspace_id=scope.workspace_id,
                content_sha256=key.rsplit("/", 1)[1],
                media_type="text/plain",
                size_bytes=len(b"A report."),
            )
            await _privacy_erase(conn, key)
            uploaded = await _early(conn, fs, scope, report)
            assert key not in uploaded and await _gone(fs, key)
            with pytest.raises(ArtifactIntegrityError):
                await index_acquisition(conn, fs, scope, report, uploaded=uploaded)
            assert await _gone(fs, key)

    run_async(case())


def test_a_source_file_privacy_erased_after_its_early_upload_is_deleted(tmp_path):
    from clue_api.arv2.quality_acquisition import index_acquisition
    from clue_storage import record_artifact

    async def case():
        async with rollback_conn() as conn:
            fs = FsStorage(tmp_path)
            scope, _ = await seed(conn, fs)
            report = await _drained_deep_call(conn, fs, scope)
            key = _report_key(scope, report)
            uploaded = await _early(conn, fs, scope, report)
            assert key in uploaded and await fs.get(key) == b"A report."
            await record_artifact(
                conn,
                storage_key=key,
                workspace_id=scope.workspace_id,
                content_sha256=key.rsplit("/", 1)[1],
                media_type="text/plain",
                size_bytes=len(b"A report."),
            )
            await _privacy_erase(conn, key)
            with pytest.raises(ArtifactIntegrityError):
                await index_acquisition(conn, fs, scope, report, uploaded=uploaded)
            assert await _gone(fs, key)

    run_async(case())


def test_an_early_upload_that_cannot_reach_the_database_falls_back_to_the_lock(tmp_path):
    """The early step runs after the drain has taken its ledger rows and before it writes them,
    so it must never fail the call: on any error nothing counts as uploaded early and indexing
    stores every file under the lock, as before."""
    from contextlib import asynccontextmanager

    from clue_api.arv2.quality_acquisition import index_acquisition, upload_sources_early

    @asynccontextmanager
    async def unreachable():
        raise ConnectionError("database unavailable")
        yield

    async def case():
        async with rollback_conn() as conn:
            fs = FsStorage(tmp_path)
            scope, _ = await seed(conn, fs)
            report = await _drained_deep_call(conn, fs, scope)
            uploaded = await upload_sources_early(
                unreachable,
                fs,
                scope,
                report.result_rows,
                report.raw_artifact_keys,
                report.raw_bodies,
            )
            assert uploaded == frozenset()
            refs = await index_acquisition(conn, fs, scope, report, uploaded=uploaded)
            for ref in refs:
                assert await fs.get(ref.artifact_key)

    run_async(case())
