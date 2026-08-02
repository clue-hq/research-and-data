"""Acceptance tests for the Insight Health/Aura Stage-0 discovery handoff fixture."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import text

from clue_api.trial.discovery_fixture import (
    AMBIENT_URL,
    AURA_ANYWHERE_URL,
    FIXTURE_COMPILER_VERSION,
    HOME_URL,
    ICP_KEY,
    NEUROSURGERY_URL,
    PRODUCT_ID,
    PROJECT_RUN_ID,
    REQUIRED_URLS,
    WORKSPACE_ID,
    FixtureInputError,
    OfficialSitePage,
    load_firecrawl_search_pages,
    seed_insight_health_discovery_fixture,
)
from clue_core import (
    EntityId,
    ExtractionMethod,
    ProjectPhase,
    ReadinessDecisionId,
    ReadinessVerdict,
    VerificationStatus,
    decode_jsonb,
)
from clue_research.durable import get_project_run
from clue_research.icp import get_active_icp
from clue_research.stage0 import get_readiness_decision, read_client_kb_claims
from clue_storage import FsStorage
from tests.db.conftest import run_async
from tests.stage0.conftest import rollback_conn


def _pages() -> dict[str, OfficialSitePage]:
    return {
        HOME_URL: OfficialSitePage(
            url=HOME_URL,
            title="Insight Health AI",
            markdown=(
                "# The AI referral coordinator for specialty practices.\n\n"
                "MagicDocs reads inbound referrals and routes each to the right EHR work queue "
                "so nothing stalls on the fax machine.\n\n"
                "## Pricing\n\n"
                "Pay by the month or the year, and cancel at any time\n\n"
                "Free Forever\n\n"
                "Save 2+ hours every day. The quickest and easiest way to try AuraTM Scribe.\n\n"
                "Pro\n\n$49.99\n\nPer clinician\n\nEnterprise\n\nCustom\n\n"
                "Includes Virtual Care Assistant (VCA) + AuraTM AI Scribe."
            ),
        ),
        AMBIENT_URL: OfficialSitePage(
            url=AMBIENT_URL,
            title="Aura AI scribe for clinical notes",
            markdown=(
                "## Fully Customizable Note Format\n\n"
                "AuraTM AI Scribe offers unlimited customization beyond APSO, SOAP, and H&P "
                "formats.\n\n"
                "## Integrated ICD-10 and CPT Coding\n\n"
                "AuraTM AI Scribe recommends appropriate ICD-10 diagnosis codes and CPT "
                "procedure codes.\n\n"
                "## iOS App and Chrome Extension\n\n"
                "The Chrome extension stays within the same browser window as your EHR, "
                "providing an integrated view between your AI scribe notes and web-based EHR "
                "system without disruptive switching between applications."
            ),
        ),
        AURA_ANYWHERE_URL: OfficialSitePage(
            url=AURA_ANYWHERE_URL,
            title="Aura Anywhere",
            markdown=(
                "### Ambient Documentation\n\n"
                "AuraTM listens to patient-provider conversations and generates structured "
                "clinical notes in real time. Providers focus on the patient while documentation "
                "happens in the background.\n\n"
                "### Multi-Tenant Architecture\n\n"
                "Each organization operates in isolation with their own configurations, "
                "templates, and data boundaries."
            ),
        ),
        NEUROSURGERY_URL: OfficialSitePage(
            url=NEUROSURGERY_URL,
            title="Neurosurgery Referral Management",
            markdown=(
                "## Case Study: 15-Provider Neurosurgery Practice\n\n"
                "Key Challenges\n\n"
                "High volume of patient referrals (500+/month)\n\n"
                "Staff spending 20+ hours/week on phone screenings\n\n"
                "Inappropriate referrals consuming surgeon time\n\n"
                "20% no-show rate causing scheduling inefficiency\n\n"
                "Solution Implementation\n\n"
                "Results\n\n$350k\n\nAnnual Overhead Savings\n\n15 min\n\n"
                "Saved Per Consultation\n\n12x+\n\nReturn on Investment\n\n"
                '"For the first time my notes are actually done by the time my clinic is done. '
                'The Virtual Care Assistant has transformed our referral process."\n\n'
                "\\- Neurosurgeon, The Oregon Clinic"
            ),
        ),
    }


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

            decision = await get_readiness_decision(
                conn,
                ReadinessDecisionId(UUID(first.readiness_decision_id)),
                workspace_id=WORKSPACE_ID,
            )
            assert decision is not None
            assert decision.verdict is ReadinessVerdict.READY
            assert decision.metrics["coverage_ratio"] == pytest.approx(7 / 9)
            assert decision.metrics["verified_claims"] == 0

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

    run_async(_run())
