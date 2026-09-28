"""Corrections affect real live reads; history and outbox survive replay."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_core import Claim, EntityType, ExtractionMethod, ResearchMode, ReuseScope, new_run_id
from clue_db import db_lifespan
from clue_research.claimstore import (
    WorkspaceScope,
    claims_by_ids,
    claims_for,
    claims_for_entities,
    current_value,
    insert_claim,
    load_core_pack,
)
from clue_research.claimstore.quality import (
    QualityConflict,
    QualityScopeError,
    assess_claim,
    deliver_invalidations,
    dependency_revision,
    uncertain_findings,
)
from clue_research.identity import insert_account_entity
from clue_storage import artifact_key, content_address, record_artifact
from tests._workspace import seed_workspace

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


async def setup(conn):
    ws = await seed_workspace(conn, f"quality-{uuid4()}")
    entity = await insert_account_entity(conn, workspace_id=ws, canonical_name="Test account")
    raw = b"Provider observed employee count 64."
    sha = content_address(raw)
    key = artifact_key(ws, sha)
    await record_artifact(
        conn,
        workspace_id=ws,
        storage_key=key,
        content_sha256=sha,
        media_type="text/plain",
        size_bytes=len(raw),
    )
    return ws, entity, key


def draft(ws, entity, key, value=64):
    return Claim(
        entity_id=entity,
        entity_type=EntityType.ACCOUNT,
        field_key="core.employee_count",
        value_json=value,
        source_tier=1,
        extraction_method=ExtractionMethod.API,
        artifact_key=key,
        confidence=0.8,
        run_id=new_run_id(),
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        reuse_scope=ReuseScope.TENANT_PRIVATE,
        workspace_id=ws,
        write_markers={"quality_required": True},
    )


async def assess(conn, ws, entity, cid, key, **options):
    return await assess_claim(
        conn,
        workspace_id=ws,
        entity_id=entity,
        claim_id=cid,
        operation_id=options.pop("operation_id", uuid4()),
        expected_revision=options.pop("revision", 0),
        conclusion=options.pop("conclusion", "supported"),
        rationale_key=key,
        actor_ref="fixture-specialist",
        support_artifacts=(key,),
        **options,
    )


def test_unassessed_invalid_and_unresolved_are_not_ordinary_facts():
    async def case():
        async with rollback_conn() as conn:
            ws, entity, key = await setup(conn)
            scope = WorkspaceScope.for_workspace(ws)
            cid = await insert_claim(conn, draft(ws, entity, key))
            assert not await claims_for(conn, entity, scope=scope)
            assert len(await claims_for(conn, entity, scope=scope, include_superseded=True)) == 1
            await assess(conn, ws, entity, cid, key)
            assert (
                await current_value(conn, entity, "core.employee_count", scope=scope)
            ).value_json == 64
            await assess(
                conn, ws, entity, cid, key, revision=1, conclusion="unresolved", kind="conflict"
            )
            assert not await claims_for_entities(conn, [entity], scope=scope)
            assert not await claims_by_ids(conn, [cid], scope=scope)
            assert await current_value(conn, entity, "core.employee_count", scope=scope) is None
            assert (await uncertain_findings(conn, workspace_id=ws, entity_id=entity))[0][
                "conclusion"
            ] == "unresolved"
            await assess(
                conn, ws, entity, cid, key, revision=2, conclusion="invalid", kind="withdrawal"
            )
            assert not await uncertain_findings(conn, workspace_id=ws, entity_id=entity)
            assert len(await claims_for(conn, entity, scope=scope, include_superseded=True)) == 1
            assert await dependency_revision(conn, workspace_id=ws, entity_id=entity) == 3

    run_async(case())


def test_effective_supersession_replay_and_stale_revision():
    async def case():
        async with rollback_conn() as conn:
            ws, entity, key = await setup(conn)
            scope = WorkspaceScope.for_workspace(ws)
            wrong = await insert_claim(conn, draft(ws, entity, key, 640))
            right = await insert_claim(conn, draft(ws, entity, key, 64))
            await assess(conn, ws, entity, wrong, key)
            await assess(conn, ws, entity, right, key)
            op = uuid4()
            result = await assess(
                conn,
                ws,
                entity,
                wrong,
                key,
                revision=1,
                conclusion="invalid",
                kind="correction",
                replacement_id=right,
                operation_id=op,
            )
            replay = await assess(
                conn,
                ws,
                entity,
                wrong,
                key,
                revision=1,
                conclusion="invalid",
                kind="correction",
                replacement_id=right,
                operation_id=op,
            )
            assert replay.replayed and replay.assessment_id == result.assessment_id
            assert [c.id for c in await claims_for(conn, entity, scope=scope)] == [right]
            history = await claims_by_ids(conn, [wrong], scope=scope, include_superseded=True)
            assert history[wrong].value_json == 640 and history[wrong].superseded_by == right
            assert (
                await current_value(conn, entity, "core.employee_count", scope=scope)
            ).value_json == 64
            with pytest.raises(QualityConflict):
                await assess(conn, ws, entity, wrong, key, revision=1, conclusion="invalid")
            with pytest.raises(QualityConflict):
                await assess(conn, ws, entity, right, key, operation_id=op)
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM claim_quality_event WHERE "
                        "workspace_id=:ws AND delivered_at IS NULL"
                    ),
                    {"ws": ws},
                )
            ).scalar_one() == 3

    run_async(case())


def test_scope_and_erased_evidence_cannot_be_promoted():
    async def case():
        async with rollback_conn() as conn:
            ws, entity, key = await setup(conn)
            scope = WorkspaceScope.for_workspace(ws)
            cid = await insert_claim(conn, draft(ws, entity, key))
            with pytest.raises(QualityScopeError):
                await assess(conn, "foreign", entity, cid, key)
            await assess(conn, ws, entity, cid, key)
            await conn.execute(
                text(
                    "UPDATE artifact SET privacy_erased=true,erased_at=now() WHERE storage_key=:key"
                ),
                {"key": key},
            )
            assert not await claims_for(conn, entity, scope=scope)
            assert await current_value(conn, entity, "core.employee_count", scope=scope) is None

    run_async(case())


def test_concurrent_corrections_and_crashed_delivery_are_recoverable():
    async def case():
        # Committed synthetic records are confined to the isolated quality test database.
        async with db_lifespan() as engine:
            async with engine.begin() as conn:
                await load_core_pack(conn)
                ws, entity, key = await setup(conn)
                cid = await insert_claim(conn, draft(ws, entity, key))
                await assess(conn, ws, entity, cid, key)

            async def contender():
                async with engine.begin() as conn:
                    return await assess(
                        conn,
                        ws,
                        entity,
                        cid,
                        key,
                        revision=1,
                        conclusion="unresolved",
                        kind="conflict",
                    )

            results = await asyncio.gather(contender(), contender(), return_exceptions=True)
            assert sum(isinstance(r, QualityConflict) for r in results) == 1
            assert sum(not isinstance(r, BaseException) for r in results) == 1

            async def crash(conn, event):
                await conn.execute(
                    text("UPDATE claim_quality_event SET delivered_at=now() WHERE event_id=:id"),
                    {"id": event["event_id"]},
                )
                raise RuntimeError("simulated crash before commit")

            with pytest.raises(RuntimeError, match="simulated crash"):
                async with engine.begin() as conn:
                    await deliver_invalidations(conn, workspace_id=ws, apply=crash)

            delivered = []

            async def project(conn, event):
                delivered.append(event["event_id"])

            async with engine.begin() as conn:
                assert await deliver_invalidations(conn, workspace_id=ws, apply=project) == 2
            async with engine.begin() as conn:
                assert await deliver_invalidations(conn, workspace_id=ws, apply=project) == 0
            assert len(set(delivered)) == 2

    run_async(case())
