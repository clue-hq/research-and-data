"""Acceptance tests for the Insight Health/Aura Stage-0 discovery handoff fixture."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import text

from clue_api.trial.discovery_fixture import (
    BRAND_ID,
    FIXTURE_COMPILER_VERSION,
    HOME_URL,
    ICP_KEY,
    PRODUCT_ID,
    PROJECT_ID,
    PROJECT_RUN_ID,
    REQUIRED_URLS,
    WORKSPACE_ID,
    FixtureInputError,
    OfficialSitePage,
    load_firecrawl_search_pages,
    recorded_insight_health_pages,
    seed_insight_health_discovery_fixture,
)
from clue_config import DEFAULT_STAGE0_POLICY
from clue_core import (
    EntityId,
    ExtractionMethod,
    ProductContextVersionId,
    ProjectPhase,
    ReadinessDecisionId,
    ReadinessGate,
    ReadinessVerdict,
    VerificationStatus,
    decode_jsonb,
)
from clue_research.durable import get_project_run
from clue_research.icp import get_active_icp
from clue_research.stage0 import evaluate_readiness, get_readiness_decision, read_client_kb_claims
from clue_storage import FsStorage
from tests.db.conftest import run_async
from tests.stage0.conftest import rollback_conn


def _pages() -> dict[str, OfficialSitePage]:
    return recorded_insight_health_pages()


def _firecrawl_payload(pages: list[OfficialSitePage]) -> dict[str, object]:
    return {
        "success": True,
        "data": {
            "web": [
                {
                    "url": page.url,
                    "title": page.title,
                    "description": "fixture",
                    "markdown": page.markdown,
                }
                for page in pages
            ]
        },
    }


def test_firecrawl_loader_requires_every_official_page_and_rejects_conflicts(
    tmp_path: Path,
) -> None:
    pages = _pages()
    partial = tmp_path / "partial.json"
    partial.write_text(
        json.dumps(_firecrawl_payload([pages[HOME_URL]])),
        encoding="utf-8",
    )
    with pytest.raises(FixtureInputError, match="required Insight Health pages are missing"):
        load_firecrawl_search_pages((partial,))

    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text(
        json.dumps(_firecrawl_payload(list(pages.values()))),
        encoding="utf-8",
    )
    changed_home = pages[HOME_URL].model_copy(update={"markdown": "changed"})
    second.write_text(
        json.dumps(_firecrawl_payload([changed_home])),
        encoding="utf-8",
    )
    with pytest.raises(FixtureInputError, match="conflicting harvested snapshots"):
        load_firecrawl_search_pages((first, second))


def test_discovery_fixture_is_real_db_backed_provenance_complete_and_replay_safe(
    require_profiling_db: None,
    tmp_path: Path,
) -> None:
    del require_profiling_db

    async def _run() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        pages = _pages()
        async with rollback_conn(seed=False) as conn:
            first = await seed_insight_health_discovery_fixture(
                conn,
                pages=pages,
                storage=storage,
            )
            assert first.fixture_version == FIXTURE_COMPILER_VERSION
            assert first.workspace_id == WORKSPACE_ID
            assert first.product_id == PRODUCT_ID
            assert first.icp_key == ICP_KEY
            assert first.project_run_id == str(PROJECT_RUN_ID)
            assert first.project_phase == ProjectPhase.DISCOVERY.value
            assert first.readiness_verdict == ReadinessVerdict.READY.value
            assert tuple(first.artifact_keys_by_url) == REQUIRED_URLS
            assert len(first.client_claim_ids) == 7

            claims = await read_client_kb_claims(
                conn,
                EntityId(UUID(first.client_entity_id)),
                workspace_id=WORKSPACE_ID,
                version=first.client_kb_version,
                product_id=PRODUCT_ID,
            )
            assert set(claims) == set(first.client_claim_ids)
            for field_key, claim in claims.items():
                assert str(claim.id) == first.client_claim_ids[field_key]
                assert claim.source_tier == 2
                assert claim.extraction_method is ExtractionMethod.SCRAPE
                assert claim.source_key == "firecrawl_site"
                assert claim.verification_status is VerificationStatus.UNVERIFIED
                assert claim.artifact_key is not None
                assert claim.source_url in pages
                assert claim.evidence_span is not None
                assert claim.evidence_span in pages[claim.source_url].markdown
                assert await storage.get(claim.artifact_key) == pages[
                    claim.source_url
                ].markdown.encode("utf-8")

            spec = await get_active_icp(conn, WORKSPACE_ID, ICP_KEY)
            assert spec is not None
            assert spec.version == first.icp_version == 1
            assert spec.client_entity_id is not None
            assert str(spec.client_entity_id) == first.client_entity_id
            assert spec.client_kb_version == first.client_kb_version
            assert spec.product_id == PRODUCT_ID
            assert spec.discovery_strategy["requested_count"] == 2
            assert spec.discovery_strategy["discovery_completion_policy"] == (
                "closed_durable_batch"
            )
            assert spec.discovery_strategy["advance_only_after"] == (
                "immutable_discovery_batch_seal"
            )
            assert spec.discovery_strategy["scoring_mode"] == "disabled"
            assert spec.discovery_strategy["selection_mode"] == "discovery_criteria"
            assert spec.discovery_strategy["approved_tier"] == "high"

            decision = await get_readiness_decision(
                conn,
                ReadinessDecisionId(UUID(first.readiness_decision_id)),
                workspace_id=WORKSPACE_ID,
            )
            assert decision is not None
            assert decision.verdict is ReadinessVerdict.READY
            # 7 of the 11 baseline client fields are filled by this fixture. The denominator grew
            # 9 → 11 when client.competitor / client.buyer_profile were registered: both are
            # tier-3-only (exa_search), so this tier-2 fixture leaves them honestly empty.
            assert decision.metrics["coverage_ratio"] == pytest.approx(7 / 11)
            assert decision.metrics["verified_claims"] == 0
            assert decision.metrics["workspace_readiness_policy_version"] == 0
            assert decision.metrics["workspace_required_field_keys"] == []
            assert decision.metrics["workspace_required_missing_field_keys"] == []

            project_run = await get_project_run(conn, PROJECT_RUN_ID)
            assert project_run is not None
            assert project_run.phase is ProjectPhase.DISCOVERY
            assert project_run.product_id == PRODUCT_ID
            assert str(project_run.product_context_version_id) == (first.product_context_version_id)

            context_row = (
                (
                    await conn.execute(
                        text(
                            "SELECT claim_refs, artifact_refs FROM product_context_version "
                            "WHERE id = :id"
                        ),
                        {"id": UUID(first.product_context_version_id)},
                    )
                )
                .mappings()
                .one()
            )
            assert set(decode_jsonb(context_row["claim_refs"])) == set(
                first.client_claim_ids.values()
            )
            assert set(decode_jsonb(context_row["artifact_refs"])) == set(
                first.artifact_keys_by_url.values()
            )

            tables = (
                "workspace",
                "brand",
                "product",
                "project",
                "account_entity",
                "artifact",
                "claim",
                "icp_spec",
                "onboarding_input",
                "product_context_version",
                "readiness_decision",
                "project_run",
            )
            counts_before = {
                table: int((await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one())
                for table in tables
            }
            second = await seed_insight_health_discovery_fixture(
                conn,
                pages=pages,
                storage=storage,
            )
            counts_after = {
                table: int((await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one())
                for table in tables
            }
            assert second == first
            assert counts_after == counts_before

            replay_metrics = {
                key: value
                for key, value in decision.metrics.items()
                if not key.startswith("workspace_")
            }
            replay_metrics["coverage_ratio"] = 0.8
            with pytest.raises(
                ValueError, match="readiness decision id replayed with different immutable payload"
            ):
                await evaluate_readiness(
                    conn,
                    workspace_id=WORKSPACE_ID,
                    brand_id=BRAND_ID,
                    product_id=PRODUCT_ID,
                    project_id=PROJECT_ID,
                    client_entity_id=EntityId(UUID(first.client_entity_id)),
                    client_kb_version=first.client_kb_version,
                    icp_key=first.icp_key,
                    icp_version=first.icp_version,
                    product_context_version_id=ProductContextVersionId(
                        UUID(first.product_context_version_id)
                    ),
                    gate=ReadinessGate.DISCOVERY_SPEND,
                    spec=DEFAULT_STAGE0_POLICY.readiness,
                    metrics=replay_metrics,
                    created_by_actor="system",
                    readiness_decision_id=ReadinessDecisionId(UUID(first.readiness_decision_id)),
                )

    run_async(_run())
