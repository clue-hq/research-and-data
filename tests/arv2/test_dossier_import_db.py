"""Real shared-store persistence, source scope, savepoint recovery and replay."""

import hashlib
from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_api.arv2 import dossier_import
from clue_api.arv2.quality_evidence import grant_manifest, revoke_grant
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
