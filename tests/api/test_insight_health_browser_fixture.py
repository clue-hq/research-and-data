"""Insight Health browser onboarding fixture acceptance."""

from __future__ import annotations

import hashlib
from uuid import UUID

from sqlalchemy import text

from clue_api.trial.browser_fixture import (
    BRAND_ID,
    PRODUCT_ID,
    WORKSPACE_ID,
    seed_insight_health_browser_fixture,
    seed_insight_health_browser_onboarding_result,
)
from clue_core import EntityId, OnboardingInputKind, RawArtifact
from clue_research.stage0 import read_client_kb_claims, submit_onboarding_input
from clue_spine import create_project
from clue_storage import FsStorage, SnapshotSink, flush_snapshots
from tests.db.conftest import run_async
from tests.profiling.conftest import rollback_conn


def test_fixture_is_replay_safe_and_stops_before_stage0(
    require_profiling_db: None,
) -> None:
    del require_profiling_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            projects_before = int(
                (
                    await conn.execute(
                        text("SELECT count(*) FROM project WHERE workspace_id = :workspace_id"),
                        {"workspace_id": WORKSPACE_ID},
                    )
                ).scalar_one()
            )
            icps_before = int(
                (
                    await conn.execute(
                        text("SELECT count(*) FROM icp_spec WHERE workspace_id = :workspace_id"),
                        {"workspace_id": WORKSPACE_ID},
                    )
                ).scalar_one()
            )
            first = await seed_insight_health_browser_fixture(
                conn,
                provider_subject="user_browser_fixture_acceptance",
                display_name="Insight Health GTM Lead",
            )
            replay = await seed_insight_health_browser_fixture(
                conn,
                provider_subject="user_browser_fixture_acceptance",
                display_name="Ignored on replay",
            )
            assert replay == first
            assert (first.workspace_id, first.brand_id, first.product_id) == (
                WORKSPACE_ID,
                BRAND_ID,
                PRODUCT_ID,
            )

            project_count = int(
                (
                    await conn.execute(
                        text("SELECT count(*) FROM project WHERE workspace_id = :workspace_id"),
                        {"workspace_id": WORKSPACE_ID},
                    )
                ).scalar_one()
            )
            icp_count = int(
                (
                    await conn.execute(
                        text("SELECT count(*) FROM icp_spec WHERE workspace_id = :workspace_id"),
                        {"workspace_id": WORKSPACE_ID},
                    )
                ).scalar_one()
            )
            assert project_count == projects_before
            assert icp_count == icps_before

    run_async(scenario())


def test_project_onboarding_result_is_identity_bound_provenance_complete_and_before_icp(
    require_profiling_db: None,
    tmp_path,
) -> None:
    del require_profiling_db

    async def scenario() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=False) as conn:
            icps_before = int(
                (
                    await conn.execute(
                        text("SELECT count(*) FROM icp_spec WHERE workspace_id = :workspace_id"),
                        {"workspace_id": WORKSPACE_ID},
                    )
                ).scalar_one()
            )
            identity = await seed_insight_health_browser_fixture(
                conn,
                provider_subject="user_browser_onboarding_acceptance",
                display_name="Insight Health GTM Lead",
            )
            project = await create_project(
                conn,
                workspace_id=WORKSPACE_ID,
                brand_id=BRAND_ID,
                project_id="prj_browser_onboarding_acceptance",
                name="Browser onboarding acceptance",
            )
            prompt = b"I lead GTM at Insight Health. Start from true zero state."
            sink = SnapshotSink(workspace_id=WORKSPACE_ID)
            artifact_key = sink.capture(
                RawArtifact(
                    ref="fixture://browser-onboarding-prompt",
                    media_type="text/plain",
                    content=prompt,
                ),
                source_key="user_upload",
            )
            await flush_snapshots(conn, storage, sink)
            await submit_onboarding_input(
                conn,
                workspace_id=WORKSPACE_ID,
                brand_id=BRAND_ID,
                project_id=project.project_id,
                kind=OnboardingInputKind.USER_TURN,
                artifact_key=artifact_key,
                content_sha256=hashlib.sha256(prompt).hexdigest(),
                actor="human",
            )

            first = await seed_insight_health_browser_onboarding_result(
                conn,
                provider_subject="user_browser_onboarding_acceptance",
                project_id=project.project_id,
                storage=storage,
            )
            replay = await seed_insight_health_browser_onboarding_result(
                conn,
                provider_subject="user_browser_onboarding_acceptance",
                project_id=project.project_id,
                storage=storage,
            )
            assert replay == first
            assert first.user_id == identity.user_id
            assert first.membership_id == identity.membership_id
            assert first.client_kb_version == 1
            assert len(first.client_claim_ids) == 7
            assert len(first.artifact_keys_by_url) == 4

            claims = await read_client_kb_claims(
                conn,
                EntityId(UUID(first.client_entity_id)),
                workspace_id=WORKSPACE_ID,
                version=first.client_kb_version,
                product_id=PRODUCT_ID,
            )
            assert set(claims) == set(first.client_claim_ids)
            assert all(claim.evidence_span for claim in claims.values())
            assert all(claim.artifact_key for claim in claims.values())

            icp_count = int(
                (
                    await conn.execute(
                        text("SELECT count(*) FROM icp_spec WHERE workspace_id = :workspace_id"),
                        {"workspace_id": WORKSPACE_ID},
                    )
                ).scalar_one()
            )
            assert icp_count == icps_before

    run_async(scenario())
