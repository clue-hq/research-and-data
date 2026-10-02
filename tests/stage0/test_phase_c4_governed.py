"""Focused C4 contract and DB integration tests for governed Stage 0."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import discover_skills
from clue_api.phase_c_wiring import build_stage0_scrape_binder
from clue_api.stage0_tools import StartReconInput, StartReconTool, start_confirmed_project_run
from clue_config import DEFAULT_STAGE0_POLICY, ReadinessFloor, ReadinessSpec
from clue_core import (
    AccountEntity,
    AccountStatus,
    AdaptContext,
    ClaimDraft,
    ContactEntity,
    Entity,
    EntityType,
    FieldDef,
    ICPCreatedFrom,
    NormalizedText,
    OnboardingInputKind,
    PreSpendDecision,
    PreSpendRequest,
    PreSpendVerdict,
    ProjectPhase,
    ProjectRunId,
    RawArtifact,
    ReadinessGate,
    ReadinessVerdict,
    ReuseScope,
    RunEventTopic,
    TargetLock,
    new_entity_id,
    new_operation_id,
    new_project_run_id,
    new_run_id,
)
from clue_execution.run_events import list_run_events
from clue_research.adapters import CallableClaimExtractor
from clue_research.claimstore import WorkspaceScope, claims_by_ids, insert_claim
from clue_research.durable import ProjectRunStatus
from clue_research.durable.project_run import set_phase
from clue_research.icp import create_icp_spec
from clue_research.identity import insert_account_entity
from clue_research.sources import is_resolver_bound, unbind_resolver
from clue_research.stage0 import (
    InterviewRoute,
    InterviewStatement,
    compile_product_context,
    evaluate_readiness,
    get_recon,
    override_readiness,
    recon_dedupe_hash,
    route_interview_answer,
    start_recon,
    submit_onboarding_input,
)
from clue_research.stage0.fields import CLIENT_PRODUCT_OVERVIEW, CLIENT_VALUE_PROP
from clue_spine import create_brand, create_product, create_project
from clue_storage import artifact_key as make_artifact_key
from clue_storage import record_artifact
from clue_toolbelt import ToolContext
from tests.stage0.conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_stage0_db")

_WORKSPACE = "phase-c4"


class _RecordingGate:
    def __init__(self) -> None:
        self.requests: list[PreSpendRequest] = []
        self.rebound = False

    def with_conn_factory(self, conn_factory: object) -> _RecordingGate:
        del conn_factory
        self.rebound = True
        return self

    async def check(self, request: PreSpendRequest) -> PreSpendDecision:
        assert self.rebound, "StartReconTool must gate against its caller-owned lane transaction"
        self.requests.append(request)
        return PreSpendDecision(verdict=PreSpendVerdict.PASS)

    async def assemble_target_lock(
        self,
        entity: AccountEntity | ContactEntity,
        field: FieldDef,
    ) -> TargetLock:
        return TargetLock(
            entity_id=entity.id,
            no_drift_instruction=f"Remain locked to {entity.id} for {field.field_key}",
        )


class _ReconScraper:
    def scrape(self, ref: str, ctx: AdaptContext) -> RawArtifact:
        return RawArtifact(
            ref=ref,
            media_type="text/markdown",
            content=b"# Client\\nOur value proposition is revenue clarity.",
        )


class _MemoryStorage:
    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        self.blobs[key] = data

    async def get(self, key: str) -> bytes:
        return self.blobs[key]

    async def delete(self, key: str) -> None:
        self.blobs.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self.blobs

    async def presign(self, key: str, *, expires_in: int = 3600) -> str:
        return f"memory://{key}"

    async def list_blobs(self) -> AsyncIterator[tuple[str, datetime]]:
        return
        yield


def test_readiness_policy_has_three_independent_gates() -> None:
    assert set(DEFAULT_STAGE0_POLICY.readiness.floors) == set(ReadinessGate)
    assert (
        DEFAULT_STAGE0_POLICY.readiness.floors[ReadinessGate.ICP_SYNTHESIS].min_coverage_ratio
        == 0.0
    )
    with pytest.raises(ValueError, match="all gates"):
        ReadinessSpec(floors={ReadinessGate.ICP_SYNTHESIS: ReadinessFloor()})


def test_stage0_skill_is_flat_versioned_and_has_the_frozen_allowlist() -> None:
    parent = Path(__file__).resolve().parents[2] / "platform" / "agents" / "skills"
    skills = discover_skills(parent)
    assert len(skills) == 1
    skill = skills[0]
    assert (skill.name, skill.version) == ("stage0-interview", "1")
    assert "start_confirmed_project_run" in skill.tool_allowlist
    assert "override_stage0_readiness" in skill.tool_allowlist


def test_stage0_recon_binds_the_real_official_surface_resolver() -> None:
    binder = build_stage0_scrape_binder(
        extractor=CallableClaimExtractor(lambda normalized, entity, field: [])
    )
    account = AccountEntity(
        id=new_entity_id(),
        canonical_name="C4 Client",
        primary_domain="c4.example",
        workspace_id=_WORKSPACE,
    )
    try:
        binder(account)
        assert binder.key_for(account.id) == account
        assert is_resolver_bound("firecrawl_site")
    finally:
        unbind_resolver("firecrawl_site")


def test_url_only_recon_is_two_speed_gated_snapshotted_and_evented() -> None:
    def extract_value(
        normalized: NormalizedText,
        entity: Entity,
        field: FieldDef,
    ) -> list[ClaimDraft]:
        del entity
        if field.field_key != CLIENT_VALUE_PROP or "revenue clarity" not in normalized.text:
            return []
        return [
            ClaimDraft(
                field_key=field.field_key,
                value="revenue clarity",
                evidence_span="revenue clarity",
                confidence=0.9,
            )
        ]

    async def _run() -> None:
        async with rollback_conn(workspace_id=_WORKSPACE) as conn:
            brand = await create_brand(conn, workspace_id=_WORKSPACE, name="Recon live brand")
            body = "https://recon.example"
            digest = hashlib.sha256(body.encode()).hexdigest()
            artifact_key = make_artifact_key(_WORKSPACE, digest)
            await record_artifact(
                conn,
                storage_key=artifact_key,
                workspace_id=_WORKSPACE,
                content_sha256=digest,
                media_type="text/plain",
                size_bytes=len(body),
            )
            onboarding = await submit_onboarding_input(
                conn,
                workspace_id=_WORKSPACE,
                brand_id=brand.brand_id,
                kind=OnboardingInputKind.WEBSITE,
                artifact_key=artifact_key,
                content_sha256=digest,
                actor="human",
            )
            gate = _RecordingGate()
            storage = _MemoryStorage()
            binder = build_stage0_scrape_binder(
                extractor=CallableClaimExtractor(extract_value),
                scraper=_ReconScraper(),
            )

            @asynccontextmanager
            async def factory() -> AsyncIterator[AsyncConnection]:
                yield conn

            tool = StartReconTool(
                conn_factory=factory,
                pre_spend_gate=gate,
                scrape_binder=binder,
                storage=storage,
                # This harness's factory is same-conn and reentrant, so the emitter's
                # "autonomous" branch still rides the rollback connection — the composed
                # path is exercised without leaking committed rows out of the test.
                field_progress_factory=factory,
            )
            inputs = StartReconInput(
                brand_id=brand.brand_id,
                name="Recon Client",
                website=body,
                onboarding_input_ids=[str(onboarding.onboarding_input_id)],
            )
            ctx = ToolContext(
                workspace_id=_WORKSPACE,
                actor="agent",
                conn_factory=factory,
                operation_id=new_operation_id(),
            )
            try:
                fast = await tool.invoke(inputs, ctx)
                assert fast.references["fast_status"] == "completed"
                assert fast.references["background_status"] == "queued"
                assert gate.rebound is True
                assert gate.requests
                assert storage.blobs

                background = await tool.invoke(inputs, ctx)
                assert background.references["background_status"] == "completed"
                recon_id = UUID(str(background.references["recon_run_id"]))
                events = await list_run_events(
                    conn,
                    workspace_id=_WORKSPACE,
                    run_id=ProjectRunId(recon_id),
                )
                transitions = [
                    event
                    for event in events
                    if event.topic == RunEventTopic.STEP_PROGRESS.value
                    and event.payload.get("kind") == "stage0.recon.transition"
                ]
                assert [
                    (event.payload["lane"], event.payload["status"]) for event in transitions
                ] == [
                    ("fast", "running"),
                    ("fast", "completed"),
                    ("background", "running"),
                    ("background", "completed"),
                ]
                # Budget honesty rides the COMPLETED transitions: the cheap fast lane really
                # does stop at its cap here (so it "completed" without reaching every field),
                # while the wider background lane runs the whole baseline out.
                completed = [
                    event for event in transitions if event.payload["status"] == "completed"
                ]
                assert [
                    (event.payload["lane"], event.payload["budget_exhausted"])
                    for event in completed
                ] == [("fast", True), ("background", False)]

                # Per-field motion: a poller sees real fields start and terminate mid-lane.
                field_events = [
                    event
                    for event in events
                    if event.topic == RunEventTopic.STEP_PROGRESS.value
                    and event.payload.get("kind") == "stage0.recon.field"
                ]
                assert field_events
                for lane in ("fast", "background"):
                    lane_events = [
                        (event.payload["field_key"], event.payload["status"])
                        for event in field_events
                        if event.payload["lane"] == lane
                    ]
                    value_prop = [status for key, status in lane_events if key == CLIENT_VALUE_PROP]
                    assert value_prop[0] == "started"
                    assert value_prop[1] in {"resolved", "empty"}
                # The events are durable *while the lane runs*, not appended after it:
                # every fast field event precedes the fast lane's completed transition.
                fast_completed_seq = next(
                    event.seq
                    for event in transitions
                    if (event.payload["lane"], event.payload["status"]) == ("fast", "completed")
                )
                fast_field_seqs = [
                    event.seq for event in field_events if event.payload["lane"] == "fast"
                ]
                assert fast_field_seqs
                assert max(fast_field_seqs) < fast_completed_seq
            finally:
                unbind_resolver("firecrawl_site")

    run_async(_run())


def test_c4_lineage_readiness_and_confirmed_run_entry() -> None:
    async def _run() -> None:
        async with rollback_conn(workspace_id=_WORKSPACE) as conn:
            brand = await create_brand(conn, workspace_id=_WORKSPACE, name="C4 brand")
            product = await create_product(
                conn,
                workspace_id=_WORKSPACE,
                brand_id=brand.brand_id,
                name="C4 product",
            )
            project = await create_project(
                conn,
                workspace_id=_WORKSPACE,
                brand_id=brand.brand_id,
                product_id=product.product_id,
                name="C4 project",
            )
            client = await insert_account_entity(
                conn,
                canonical_name="C4 Client",
                primary_domain="c4.example",
                workspace_id=_WORKSPACE,
                status=AccountStatus.ACTIVE,
            )
            from clue_core import Claim, EntityType, ExtractionMethod, ResearchMode

            claim = Claim(
                entity_id=client,
                entity_type=EntityType.ACCOUNT,
                field_key=CLIENT_VALUE_PROP,
                value_json="Evidence-backed ABM",
                source_tier=1,
                extraction_method=ExtractionMethod.HUMAN,
                evidence_span="We provide Evidence-backed ABM",
                confidence=1.0,
                run_id=new_run_id(),
                research_mode=ResearchMode.ACCOUNT_PROFILING,
                reuse_scope=ReuseScope.TENANT_PRIVATE,
                workspace_id=_WORKSPACE,
                product_id=None,
            )
            claim_id = await insert_claim(conn, claim)
            spec = await create_icp_spec(
                conn,
                workspace_id=_WORKSPACE,
                icp_key="primary",
                created_from=ICPCreatedFrom.SYNTHESIS,
                activate=True,
                client_entity_id=client,
                client_kb_version=1,
                product_id=product.product_id,
            )
            context = await compile_product_context(
                conn,
                workspace_id=_WORKSPACE,
                brand_id=brand.brand_id,
                product_id=product.product_id,
                client_entity_id=client,
                client_kb_version=1,
                claim_refs=(str(claim_id),),
            )
            other_product = await create_product(
                conn,
                workspace_id=_WORKSPACE,
                brand_id=brand.brand_id,
                name="Other product",
            )
            product_claim = Claim(
                entity_id=client,
                entity_type=EntityType.ACCOUNT,
                field_key=CLIENT_PRODUCT_OVERVIEW,
                value_json="Product-specific context",
                source_tier=1,
                extraction_method=ExtractionMethod.HUMAN,
                evidence_span="Product-specific context",
                confidence=1.0,
                run_id=new_run_id(),
                research_mode=ResearchMode.ACCOUNT_PROFILING,
                reuse_scope=ReuseScope.TENANT_PRIVATE,
                workspace_id=_WORKSPACE,
                product_id=product.product_id,
            )
            product_claim_id = await insert_claim(conn, product_claim)
            with pytest.raises(ValueError, match="foreign, or unscoped claim"):
                await compile_product_context(
                    conn,
                    workspace_id=_WORKSPACE,
                    brand_id=brand.brand_id,
                    product_id=other_product.product_id,
                    client_entity_id=client,
                    client_kb_version=1,
                    claim_refs=(str(product_claim_id),),
                )
            readiness = await evaluate_readiness(
                conn,
                workspace_id=_WORKSPACE,
                brand_id=brand.brand_id,
                product_id=product.product_id,
                project_id=project.project_id,
                client_entity_id=client,
                client_kb_version=1,
                icp_key=spec.icp_key,
                icp_version=spec.version,
                product_context_version_id=context.version_id,
                gate=ReadinessGate.DISCOVERY_SPEND,
                spec=DEFAULT_STAGE0_POLICY.readiness,
                metrics={
                    "coverage_ratio": 0.25,
                    "verified_claims": 1,
                    "open_policy_blocks": 0,
                },
                created_by_actor="agent",
            )
            assert readiness.verdict is ReadinessVerdict.READY
            run_id = new_project_run_id()
            await start_confirmed_project_run(
                conn,
                project_run_id=run_id,
                workspace_id=_WORKSPACE,
                project_id=project.project_id,
                client_entity_id=client,
                client_kb_version=1,
                product_id=product.product_id,
                product_context_version_id=context.version_id,
                readiness_decision_id=readiness.readiness_decision_id,
                icp_key=spec.icp_key,
                icp_version=spec.version,
            )
            from clue_research.durable import get_project_run

            run = await get_project_run(conn, run_id)
            assert run is not None
            assert run.phase is ProjectPhase.DISCOVERY
            assert run.product_context_version_id == context.version_id
            assert run.readiness_decision_id == readiness.readiness_decision_id

            # A delayed/replayed start must neither fail nor rewind a run which Recipe #1 already
            # advanced. The same id still cannot be reused for different immutable authority.
            await set_phase(
                conn,
                run_id,
                phase=ProjectPhase.SCORING,
                status=ProjectRunStatus.ACTIVE,
            )
            await start_confirmed_project_run(
                conn,
                project_run_id=run_id,
                workspace_id=_WORKSPACE,
                project_id=project.project_id,
                client_entity_id=client,
                client_kb_version=1,
                product_id=product.product_id,
                product_context_version_id=context.version_id,
                readiness_decision_id=readiness.readiness_decision_id,
                icp_key=spec.icp_key,
                icp_version=spec.version,
            )
            advanced = await get_project_run(conn, run_id)
            assert advanced is not None and advanced.phase is ProjectPhase.SCORING
            with pytest.raises(ValueError, match="different immutable lineage"):
                await start_confirmed_project_run(
                    conn,
                    project_run_id=run_id,
                    workspace_id=_WORKSPACE,
                    project_id=project.project_id,
                    client_entity_id=client,
                    client_kb_version=1,
                    product_id=product.product_id,
                    product_context_version_id=context.version_id,
                    readiness_decision_id=readiness.readiness_decision_id,
                    icp_key=spec.icp_key,
                    icp_version=spec.version,
                    budget_cap_cents=Decimal("1"),
                )

    run_async(_run())


def test_recon_dedupes_only_inside_one_workspace_and_keeps_background_separate() -> None:
    async def _run() -> None:
        async with rollback_conn(workspace_id=_WORKSPACE) as conn:
            brand = await create_brand(conn, workspace_id=_WORKSPACE, name="Recon brand")
            dedupe = recon_dedupe_hash(
                workspace_id=_WORKSPACE,
                brand_id=brand.brand_id,
                product_id=None,
                identity="https://example.com",
            )
            first = await start_recon(
                conn,
                workspace_id=_WORKSPACE,
                brand_id=brand.brand_id,
                dedupe_hash=dedupe,
                onboarding_input_ids=(),
                fast_budget_cents=Decimal(1),
                background_budget_cents=Decimal(10),
                dedupe_ttl_seconds=60,
            )
            second = await start_recon(
                conn,
                workspace_id=_WORKSPACE,
                brand_id=brand.brand_id,
                dedupe_hash=dedupe,
                onboarding_input_ids=(),
                fast_budget_cents=Decimal(1),
                background_budget_cents=Decimal(10),
                dedupe_ttl_seconds=60,
            )
            assert first.id == second.id
            assert first.fast_run_id != first.background_run_id
            assert await get_recon(conn, first.id, workspace_id="other") is None

    run_async(_run())


def test_interview_uses_exact_quote_and_human_override_is_enforced() -> None:
    async def _run() -> None:
        async with rollback_conn(workspace_id=_WORKSPACE) as conn:
            brand = await create_brand(conn, workspace_id=_WORKSPACE, name="Interview brand")
            product = await create_product(
                conn,
                workspace_id=_WORKSPACE,
                brand_id=brand.brand_id,
                name="Interview product",
            )
            client = await insert_account_entity(
                conn,
                canonical_name="Interview Client",
                primary_domain="interview.example",
                workspace_id=_WORKSPACE,
                status=AccountStatus.ACTIVE,
            )
            body = "Our value proposition is revenue clarity."
            digest = hashlib.sha256(body.encode()).hexdigest()
            artifact_key = make_artifact_key(_WORKSPACE, digest)
            await record_artifact(
                conn,
                storage_key=artifact_key,
                workspace_id=_WORKSPACE,
                content_sha256=digest,
                media_type="text/plain",
                size_bytes=len(body),
            )
            input_ref = await submit_onboarding_input(
                conn,
                workspace_id=_WORKSPACE,
                brand_id=brand.brand_id,
                product_id=product.product_id,
                client_entity_id=client,
                kind=OnboardingInputKind.USER_TURN,
                artifact_key=artifact_key,
                content_sha256=digest,
                actor="human",
            )
            result = await route_interview_answer(
                conn,
                workspace_id=_WORKSPACE,
                brand_id=brand.brand_id,
                product_id=product.product_id,
                client_entity_id=client,
                onboarding_input_id=input_ref.onboarding_input_id,
                artifact_key=artifact_key,
                answer=body,
                statements=(
                    InterviewStatement(
                        route=InterviewRoute.CLAIM,
                        route_key=CLIENT_VALUE_PROP,
                        quote=body,
                        entity_id=client,
                        entity_type=EntityType.ACCOUNT,
                        field_key=CLIENT_VALUE_PROP,
                        value="revenue clarity",
                    ),
                ),
                actor="human",
            )
            assert len(result.claim_refs) == 1
            correction_body = "Correction: our value proposition is pipeline confidence."
            correction_digest = hashlib.sha256(correction_body.encode()).hexdigest()
            correction_artifact = make_artifact_key(_WORKSPACE, correction_digest)
            await record_artifact(
                conn,
                storage_key=correction_artifact,
                workspace_id=_WORKSPACE,
                content_sha256=correction_digest,
                media_type="text/plain",
                size_bytes=len(correction_body),
            )
            correction_input = await submit_onboarding_input(
                conn,
                workspace_id=_WORKSPACE,
                brand_id=brand.brand_id,
                product_id=product.product_id,
                client_entity_id=client,
                kind=OnboardingInputKind.USER_TURN,
                artifact_key=correction_artifact,
                content_sha256=correction_digest,
                actor="human",
            )
            correction_statement = InterviewStatement(
                route=InterviewRoute.CLAIM,
                route_key=CLIENT_VALUE_PROP,
                quote=correction_body,
                entity_id=client,
                entity_type=EntityType.ACCOUNT,
                field_key=CLIENT_VALUE_PROP,
                value="pipeline confidence",
                correction_of_statement_id=result.statement_ids[0],
                correction_of_claim_id=result.claim_refs[0],
            )
            corrected = await route_interview_answer(
                conn,
                workspace_id=_WORKSPACE,
                brand_id=brand.brand_id,
                product_id=product.product_id,
                client_entity_id=client,
                onboarding_input_id=correction_input.onboarding_input_id,
                artifact_key=correction_artifact,
                answer=correction_body,
                statements=(correction_statement,),
                actor="human",
            )
            replayed = await route_interview_answer(
                conn,
                workspace_id=_WORKSPACE,
                brand_id=brand.brand_id,
                product_id=product.product_id,
                client_entity_id=client,
                onboarding_input_id=correction_input.onboarding_input_id,
                artifact_key=correction_artifact,
                answer=correction_body,
                statements=(correction_statement,),
                actor="human",
            )
            assert replayed.claim_refs == corrected.claim_refs
            history = await claims_by_ids(
                conn,
                (*result.claim_refs, *corrected.claim_refs),
                scope=WorkspaceScope.private_for_workspace(_WORKSPACE),
                include_superseded=True,
            )
            assert history[result.claim_refs[0]].superseded_by == corrected.claim_refs[0]
            with pytest.raises(ValueError, match="not textually entailed"):
                await route_interview_answer(
                    conn,
                    workspace_id=_WORKSPACE,
                    brand_id=brand.brand_id,
                    product_id=product.product_id,
                    client_entity_id=client,
                    onboarding_input_id=input_ref.onboarding_input_id,
                    artifact_key=artifact_key,
                    answer=body,
                    statements=(
                        InterviewStatement(
                            route=InterviewRoute.CLAIM,
                            route_key="unsupported",
                            quote=body,
                            entity_id=client,
                            entity_type=EntityType.ACCOUNT,
                            field_key=CLIENT_VALUE_PROP,
                            value="fabricated outcome",
                        ),
                    ),
                    actor="agent",
                )

            decision = await evaluate_readiness(
                conn,
                workspace_id=_WORKSPACE,
                brand_id=brand.brand_id,
                gate=ReadinessGate.ICP_SYNTHESIS,
                spec=DEFAULT_STAGE0_POLICY.readiness,
                metrics={"open_policy_blocks": 1},
                created_by_actor="agent",
            )
            with pytest.raises(PermissionError, match="only a human"):
                await override_readiness(
                    conn,
                    decision_id=decision.readiness_decision_id,
                    workspace_id=_WORKSPACE,
                    gate=ReadinessGate.ICP_SYNTHESIS,
                    actor="agent",
                    reason="just go",
                )

    run_async(_run())
