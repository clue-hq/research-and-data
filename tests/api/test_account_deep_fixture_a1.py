"""M8B Slice A1 acceptance: the synthetic account-deep handoff and both execution paths.

The fixture is deliberately provider-free.  It persists immutable recorded responses and binds
network-free doubles behind the existing resolver/committee seams; the tests still exercise the
real claim store, discovery seal, high-tier resolver, account profiler, committee worker, durable
account-run repository, scheduler, and ``AccountDeepOrchestrator`` production composition.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.deep import build_deep_phase_handler
from clue_api.trial.account_deep_fixture import (
    ACCOUNT_DOMAIN,
    ACCOUNT_NAME,
    DEEP_FIELD_KEYS,
    DEEP_ICP_KEY,
    DEFAULT_RECORDED_FIELDS,
    DEFAULT_RESEARCH_DIRECTIVE,
    DISCOVERY_BATCH_ID,
    DISCOVERY_ITEM_ID,
    DISCOVERY_OPERATION_ID,
    FIXTURE_VERSION,
    PROJECT_RUN_ID,
    InsightHealthAccountDeepFixtureResult,
    RecordedAccountDeepResolver,
    build_recorded_account_resolvers,
    build_recorded_committee_source,
    seed_insight_health_account_deep_fixture,
)
from clue_api.trial.discovery_fixture import (
    AMBIENT_URL,
    AURA_ANYWHERE_URL,
    BRAND_ID,
    HOME_URL,
    NEUROSURGERY_URL,
    PRODUCT_ID,
    PROJECT_ID,
    WORKSPACE_ID,
    OfficialSitePage,
)
from clue_api.trial.discovery_fixture import (
    ICP_KEY as DISCOVERY_ICP_KEY,
)
from clue_api.trial.discovery_fixture import (
    PROJECT_RUN_ID as DISCOVERY_PROJECT_RUN_ID,
)
from clue_config import ConfigOverlay, ConfigVersion, OverlayStore
from clue_core import (
    DiscoveryBatchState,
    DiscoveryOperationState,
    ExtractionMethod,
    FieldClass,
    PhaseContext,
    PhaseStatus,
    ProjectPhase,
    ResearchMode,
    WorkerStatus,
    new_operation_id,
    new_run_id,
)
from clue_research.claimstore import WorkspaceScope, claims_for
from clue_research.discovery_scoring import DISCOVERY_ENVELOPE_POLICY_V1
from clue_research.durable import (
    AccountRunStatus,
    AccountRunSubPhase,
    BudgetEngine,
    DbBudgetStore,
    PhaseCheckpointStatus,
    create_account_deep_launch,
    get_account_run,
    get_checkpoint,
    get_discovery_batch,
    get_discovery_batch_seal,
    get_discovery_field_resolution,
    get_discovery_item,
    get_discovery_operation,
    get_project_run,
)
from clue_research.icp import get_active_icp, get_icp_version, get_source_profile
from clue_research.profiling import profile_account
from clue_research.sources import (
    bind_resolver,
    get_resolver,
    is_resolver_bound,
    unbind_resolver,
)
from clue_research.verification import PreSpendGateImpl
from clue_storage import FsStorage
from tests.api.account_deep_test_support import confirmed_account_research_direction
from tests.db.conftest import run_async
from tests.profiling.conftest import FakeGateway
from tests.stage0.conftest import rollback_conn


@pytest.fixture(autouse=True)
def _restore_recorded_resolver_bindings() -> Iterator[None]:
    """The A1 doubles must not leak into later tests or replace a production test binding."""

    source_keys = {record.source_key for record in DEFAULT_RECORDED_FIELDS}
    previous = {
        source_key: get_resolver(source_key)
        for source_key in source_keys
        if is_resolver_bound(source_key)
    }
    yield
    for source_key in source_keys:
        unbind_resolver(source_key)
    for source_key, resolver in previous.items():
        bind_resolver(source_key, resolver)


def _pages() -> dict[str, OfficialSitePage]:
    """The same official Insight Health inputs accepted by the additive discovery fixture."""

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


async def _seed(
    conn: AsyncConnection, tmp_path: Path
) -> tuple[FsStorage, InsightHealthAccountDeepFixtureResult]:
    storage = FsStorage(tmp_path / "artifacts")
    result = await seed_insight_health_account_deep_fixture(
        conn,
        pages=_pages(),
        storage=storage,
    )
    return storage, result


def _bind_recorded_resolvers(
    result: InsightHealthAccountDeepFixtureResult,
) -> dict[str, RecordedAccountDeepResolver]:
    resolvers = build_recorded_account_resolvers(result)
    for source_key, resolver in resolvers.items():
        bind_resolver(source_key, resolver)
    return resolvers


def _fixture_config_store() -> OverlayStore:
    policies = DEFAULT_RESEARCH_DIRECTIVE.policies
    store = OverlayStore()
    store.set_icp_overlay(
        WORKSPACE_ID,
        DEEP_ICP_KEY,
        ConfigOverlay(
            version=ConfigVersion(layer="icp", version=1, label="account-deep-fixture"),
            policy=policies.jurisdiction_policy,
            recursion_policy=policies.recursion_policy,
            source_plan_policy=policies.source_plan_policy,
        ),
    )
    return store


class _TaskReentrantConnectionFactory:
    """Serialize sibling tasks over one rollback connection while allowing nested gate reads.

    Production uses a pool, so parallel aspect workers receive independent connections.  A
    rollback-isolated test owns one physical connection; handing it to sibling tasks concurrently
    triggers asyncpg's ``another operation is in progress`` guard.  This adapter preserves the
    same connection/transaction while serializing sibling tasks and allowing a worker to re-enter
    the factory for its injected pre-spend gate.
    """

    def __init__(self, conn: AsyncConnection) -> None:
        self._conn = conn
        self._lock = asyncio.Lock()
        self._owner: asyncio.Task[Any] | None = None
        self._depth = 0

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[AsyncConnection]:
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("connection factory requires an active asyncio task")
        if self._owner is task:
            self._depth += 1
            try:
                yield self._conn
            finally:
                self._depth -= 1
            return
        async with self._lock:
            self._owner = task
            self._depth = 1
            try:
                yield self._conn
            finally:
                self._depth = 0
                self._owner = None


def test_a1_fixture_is_deep_eligible_additive_and_read_only_on_replay(
    require_profiling_db: None,
    tmp_path: Path,
) -> None:
    del require_profiling_db

    async def _run() -> None:
        async with rollback_conn(seed=False) as conn:
            storage, first = await _seed(conn, tmp_path)
            assert first.fixture_version == FIXTURE_VERSION
            assert first.deep_icp_key == DEEP_ICP_KEY
            assert first.deep_field_keys == DEEP_FIELD_KEYS
            assert first.project_run_id == PROJECT_RUN_ID
            assert first.project_phase is ProjectPhase.DEEP
            assert first.selected_account_id is not None

            # Additive means a second ICP/project run, not an edit or advancement of Stage 0's
            # original discovery fixture.
            original_icp = await get_active_icp(conn, WORKSPACE_ID, DISCOVERY_ICP_KEY)
            original_run = await get_project_run(conn, DISCOVERY_PROJECT_RUN_ID)
            assert original_icp is not None
            assert original_run is not None
            assert original_run.phase is ProjectPhase.DISCOVERY
            original_icp_dump = original_icp.model_dump(mode="json")
            original_run_dump = original_run.model_dump(mode="json")

            deep_icp = await get_icp_version(
                conn, WORKSPACE_ID, first.deep_icp_key, first.deep_icp_version
            )
            assert deep_icp is not None
            assert tuple(deep_icp.field_keys) == DEEP_FIELD_KEYS
            assert deep_icp.enabled_packs == ("healthcare_practice",)
            assert deep_icp.discovery_strategy["scoring_mode"] == "disabled"
            assert deep_icp.discovery_strategy["selection_mode"] == "discovery_criteria"
            assert deep_icp.discovery_strategy["approved_tier"] == "high"
            assert deep_icp.source_profile_ref["excluded"] == [
                "parallel_task",
                "sumble_contact_reveal",
            ]

            profile = await get_source_profile(
                conn,
                "healthcare_practice",
                workspace_id=WORKSPACE_ID,
                icp_key=DEEP_ICP_KEY,
            )
            by_class = {
                field_class: tuple(source.source_key for source in sources)
                for field_class, sources in profile.by_field_class.items()
            }
            assert by_class[FieldClass.ACCOUNT] == (
                "sumble_jobs",
                "firecrawl_site",
                "exa_deep",
            )
            assert by_class[FieldClass.CORE] == (
                "sumble_tech_stack",
                "firecrawl_site",
                "exa_deep",
            )
            assert by_class[FieldClass.ACCOUNT_RESONANCE] == (
                "firecrawl_site",
                "exa_deep",
            )
            assert all("parallel_task" not in sources for sources in by_class.values())

            batch = await get_discovery_batch(
                conn, workspace_id=WORKSPACE_ID, batch_id=DISCOVERY_BATCH_ID
            )
            operation = await get_discovery_operation(
                conn, workspace_id=WORKSPACE_ID, operation_id=DISCOVERY_OPERATION_ID
            )
            item = await get_discovery_item(
                conn, workspace_id=WORKSPACE_ID, item_snapshot_id=DISCOVERY_ITEM_ID
            )
            seal = await get_discovery_batch_seal(
                conn, workspace_id=WORKSPACE_ID, batch_id=DISCOVERY_BATCH_ID
            )
            assert batch is not None and batch.state is DiscoveryBatchState.SEALED
            assert operation is not None
            assert operation.state is DiscoveryOperationState.SUCCEEDED
            assert operation.final_reconciled_at is not None
            assert operation.pagination_exhausted_at is not None
            assert item is not None and item.raw_artifact_key
            assert seal is not None and seal.seal_sha256 == first.discovery_seal_sha256

            for logical_field in DISCOVERY_ENVELOPE_POLICY_V1.required_fields:
                resolution = await get_discovery_field_resolution(
                    conn,
                    workspace_id=WORKSPACE_ID,
                    batch_id=DISCOVERY_BATCH_ID,
                    account_entity_id=first.selected_account_id,
                    logical_field_key=logical_field,
                )
                assert resolution is not None
                assert resolution.winning_claim_id is not None

            run = await get_project_run(conn, PROJECT_RUN_ID)
            assert run is not None
            assert run.phase is ProjectPhase.DEEP
            assert run.status.value == "active"
            checkpoints = {
                phase: await get_checkpoint(conn, PROJECT_RUN_ID, phase)
                for phase in (
                    ProjectPhase.DISCOVERY,
                    ProjectPhase.SCORING,
                    ProjectPhase.TIER_CHECKPOINT,
                )
            }
            assert all(
                checkpoint is not None and checkpoint.status is PhaseCheckpointStatus.COMMITTED
                for checkpoint in checkpoints.values()
            )
            tier_checkpoint = checkpoints[ProjectPhase.TIER_CHECKPOINT]
            assert tier_checkpoint is not None
            assert tier_checkpoint.payload["decision_action"] == "approve"
            assert tier_checkpoint.payload["discovery_seal_sha256"] == seal.seal_sha256
            assert tier_checkpoint.payload["fixture_research_directive_ref"] == first.directive_ref
            assert tier_checkpoint.payload["contact_reveals_allowed"] is False

            tier_claims = await claims_for(
                conn,
                first.selected_account_id,
                "account.scoring.tier",
                scope=WorkspaceScope.for_workspace(WORKSPACE_ID),
            )
            exact_tier = [
                claim for claim in tier_claims if str(claim.id) == str(first.tier_claim_id)
            ]
            assert len(exact_tier) == 1
            tier_value = exact_tier[0].value_json
            assert isinstance(tier_value, dict)
            assert tier_value["tier"] == "high"
            assert tier_value["decision_basis"] == "discovery_criteria"
            assert tier_value["project_run_id"] == str(PROJECT_RUN_ID)
            assert tier_value["discovery_batch_id"] == str(DISCOVERY_BATCH_ID)
            assert tier_value["discovery_seal_sha256"] == seal.seal_sha256
            assert tier_value["icp_key"] == DEEP_ICP_KEY
            assert tier_value["icp_version"] == first.deep_icp_version

            directive = json.loads((await storage.get(first.directive_ref)).decode("utf-8"))
            assert directive == DEFAULT_RESEARCH_DIRECTIVE.model_dump(mode="json")
            assert directive["status"] == "confirmed"
            assert directive["contact_reveals_allowed"] is False
            assert directive["policies"]["account_budget_cap_cents"] == "500"
            assert directive["policies"]["jurisdiction_policy"]["jurisdiction"] == "us_state"
            assert (
                directive["policies"]["jurisdiction_policy"]["posture"]
                == "professional_public_only"
            )
            assert (
                directive["policies"]["jurisdiction_policy"]["allow_map"]["sensitive"]
                == "stored_unusable"
            )
            assert directive["policies"]["field_freshness_days"] == {
                "account.hiring_velocity_eng": 30,
                "core.primary_tech_stack": 90,
                "account.operational_pain": 90,
                "account.strategic_moves": 90,
                "account.resonance.culture": 60,
            }
            assert (
                directive["policies"]["recursion_policy"]["by_tier"]["high"]["max_aspect_workers"]
                == 6
            )
            assert directive["policies"]["source_plan_policy"] == {
                "prefer_deep_sources": True,
                "tier_scope": None,
                "version": 1,
            }
            assert {question["question_id"] for question in directive["questions"]} == {
                "referral-coordination",
                "fax-workflow",
                "phone-reception",
                "dac-coordination",
            }
            for source_key, artifact_key in first.provider_artifact_keys.items():
                provider_payload = json.loads((await storage.get(artifact_key)).decode("utf-8"))
                assert provider_payload["source_key"] == source_key
                assert provider_payload["account"]["primary_domain"] == ACCOUNT_DOMAIN
                assert provider_payload["contains_contact_reveals"] is False
                for person in provider_payload["people"]:
                    assert "verified_email" not in person
                    assert "email" not in person
                    assert "phone" not in person

            # The fixture ends before the per-account orchestrator cursor exists.
            assert await get_account_run(conn, first.expected_account_run_id) is None

            tables = (
                "account_entity",
                "artifact",
                "claim",
                "icp_spec",
                "source_profile_override",
                "project_run",
                "project_phase_checkpoint",
                "discovery_plan",
                "discovery_batch",
                "discovery_operation",
                "discovery_page_receipt",
                "discovery_item_snapshot",
                "discovery_candidate_link",
                "discovery_field_resolution",
                "discovery_batch_seal",
                "account_run",
            )
            counts_before = {
                table: int((await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one())
                for table in tables
            }
            mutable_timestamps_before = {
                "project_run": run.updated_at,
                **{
                    phase.value: checkpoint.updated_at
                    for phase, checkpoint in checkpoints.items()
                    if checkpoint is not None
                },
            }

            second = await seed_insight_health_account_deep_fixture(
                conn,
                pages=_pages(),
                storage=storage,
            )
            counts_after = {
                table: int((await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one())
                for table in tables
            }
            replay_run = await get_project_run(conn, PROJECT_RUN_ID)
            assert replay_run is not None
            replay_checkpoints = {
                phase: await get_checkpoint(conn, PROJECT_RUN_ID, phase) for phase in checkpoints
            }
            mutable_timestamps_after = {
                "project_run": replay_run.updated_at,
                **{
                    phase.value: checkpoint.updated_at
                    for phase, checkpoint in replay_checkpoints.items()
                    if checkpoint is not None
                },
            }
            assert second == first
            assert counts_after == counts_before
            assert mutable_timestamps_after == mutable_timestamps_before
            replay_original_icp = await get_active_icp(conn, WORKSPACE_ID, DISCOVERY_ICP_KEY)
            replay_original_run = await get_project_run(conn, DISCOVERY_PROJECT_RUN_ID)
            assert replay_original_icp is not None
            assert replay_original_run is not None
            assert replay_original_icp.model_dump(mode="json") == original_icp_dump
            assert replay_original_run.model_dump(mode="json") == original_run_dump

    run_async(_run())


def test_a1_direct_profiler_fills_non_empty_deep_gaps_and_replays_without_calls(
    require_profiling_db: None,
    tmp_path: Path,
) -> None:
    del require_profiling_db

    async def _run() -> None:
        async with rollback_conn(seed=False) as conn:
            _storage, fixture = await _seed(conn, tmp_path)
            spec = await get_icp_version(
                conn, WORKSPACE_ID, fixture.deep_icp_key, fixture.deep_icp_version
            )
            assert spec is not None
            resolvers = _bind_recorded_resolvers(fixture)
            account_run_id = new_run_id()
            session_factory = _TaskReentrantConnectionFactory(conn)
            policies = DEFAULT_RESEARCH_DIRECTIVE.policies
            gate = PreSpendGateImpl(conn_factory=session_factory)
            config_store = _fixture_config_store()

            # The upstream discovery fixture's shallow ICP is deliberately unsuitable for deep
            # account research.  It must converge as an explicit zero-gap result instead of
            # masquerading as a populated account profile.
            shallow_spec = await get_active_icp(conn, WORKSPACE_ID, DISCOVERY_ICP_KEY)
            assert shallow_spec is not None
            shallow = await profile_account(
                account_entity_id=fixture.selected_account_id,
                spec=shallow_spec,
                tier="high",
                run_id=new_run_id(),
                project_run_id=fixture.project_run_id,
                workspace_id=WORKSPACE_ID,
                budget_cap_cents=policies.account_budget_cap_cents,
                session_factory=session_factory,
                recursion_policy=policies.recursion_policy,
                gateway=FakeGateway(),
                pre_spend_gate=gate,
                config_store=config_store,
            )
            assert shallow.status is WorkerStatus.OK
            assert shallow.gap_field_count == 0
            assert shallow.fields_targeted == 0
            assert shallow.claim_refs == ()

            result = await profile_account(
                account_entity_id=fixture.selected_account_id,
                spec=spec,
                tier="high",
                run_id=account_run_id,
                project_run_id=fixture.project_run_id,
                workspace_id=WORKSPACE_ID,
                budget_cap_cents=policies.account_budget_cap_cents,
                session_factory=session_factory,
                recursion_policy=policies.recursion_policy,
                gateway=FakeGateway(),
                pre_spend_gate=gate,
                config_store=config_store,
            )
            assert result.status is WorkerStatus.OK
            assert result.gap_field_count == 4
            assert result.fields_targeted == 4
            assert result.fields_filled == 4
            assert result.fields_empty == 0
            assert len(result.claim_refs) == 4

            expected = {
                "account.hiring_velocity_eng": ("sumble_jobs", 1, ExtractionMethod.API),
                "account.operational_pain": (
                    "exa_deep",
                    4,
                    ExtractionMethod.LLM_SYNTHESIS,
                ),
                "account.strategic_moves": (
                    "exa_deep",
                    4,
                    ExtractionMethod.LLM_SYNTHESIS,
                ),
                "account.resonance.culture": (
                    "exa_deep",
                    4,
                    ExtractionMethod.LLM_SYNTHESIS,
                ),
            }
            for field_key, (source_key, tier, method) in expected.items():
                written = [
                    claim
                    for claim in await claims_for(
                        conn,
                        fixture.selected_account_id,
                        field_key,
                        scope=WorkspaceScope.for_workspace(WORKSPACE_ID),
                    )
                    if claim.run_id == account_run_id
                ]
                assert len(written) == 1
                claim = written[0]
                assert claim.source_key == source_key
                assert claim.source_tier == tier
                assert claim.extraction_method is method
                assert claim.research_mode is ResearchMode.ACCOUNT_PROFILING
                assert claim.source_url
                assert claim.evidence_span
                assert ACCOUNT_DOMAIN in claim.evidence_span or ACCOUNT_NAME in claim.evidence_span
                assert claim.artifact_key == fixture.provider_artifact_keys[source_key]

            governed = (
                (
                    await conn.execute(
                        text(
                            "SELECT field_key, source_key, decision, effective_plan_sha256 "
                            "FROM gate_decision WHERE run_id=:run_id "
                            "AND effective_plan_sha256 IS NOT NULL ORDER BY field_key"
                        ),
                        {"run_id": account_run_id},
                    )
                )
                .mappings()
                .all()
            )
            assert [(row["field_key"], row["source_key"]) for row in governed] == [
                ("account.hiring_velocity_eng", "sumble_jobs"),
                ("account.operational_pain", "exa_deep"),
                ("account.resonance.culture", "exa_deep"),
                ("account.strategic_moves", "exa_deep"),
            ]
            assert all(row["decision"] == "pass" for row in governed)
            assert all(row["effective_plan_sha256"] for row in governed)

            calls_before = {
                source_key: tuple(resolver.calls) for source_key, resolver in resolvers.items()
            }
            claim_count_before = int(
                (await conn.execute(text("SELECT count(*) FROM claim"))).scalar_one()
            )
            replay = await profile_account(
                account_entity_id=fixture.selected_account_id,
                spec=spec,
                tier="high",
                run_id=account_run_id,
                project_run_id=fixture.project_run_id,
                workspace_id=WORKSPACE_ID,
                budget_cap_cents=policies.account_budget_cap_cents,
                session_factory=session_factory,
                recursion_policy=policies.recursion_policy,
                gateway=FakeGateway(),
                pre_spend_gate=gate,
                config_store=config_store,
            )
            assert replay.status is WorkerStatus.OK
            # Tier-4 unverified claims remain honest gaps until verification, but the same run id
            # reuses them through the waterfall instead of calling a provider or inserting again.
            assert replay.gap_field_count == 3
            assert len(replay.claim_refs) == 3
            assert int((await conn.execute(text("SELECT count(*) FROM claim"))).scalar_one()) == (
                claim_count_before
            )
            assert {
                source_key: tuple(resolver.calls) for source_key, resolver in resolvers.items()
            } == calls_before

    run_async(_run())


def test_a1_full_production_entry_creates_and_completes_real_account_run(
    require_profiling_db: None,
    tmp_path: Path,
) -> None:
    del require_profiling_db

    async def _run() -> None:
        async with rollback_conn(seed=False) as conn:
            storage, fixture = await _seed(conn, tmp_path)
            spec = await get_icp_version(
                conn, WORKSPACE_ID, fixture.deep_icp_key, fixture.deep_icp_version
            )
            assert spec is not None
            _, account_spec = await confirmed_account_research_direction(
                conn,
                workspace_id=WORKSPACE_ID,
                project_id=PROJECT_ID,
                product_id=PRODUCT_ID,
                account_id=fixture.selected_account_id,
                icp_key=fixture.deep_icp_key,
                icp_version=fixture.deep_icp_version,
                # The core tech-stack field is already populated by the fixture and is not a
                # registered deep-research field. Confirm only the four actual Pass-B gaps.
                field_keys=(DEEP_FIELD_KEYS[0], *DEEP_FIELD_KEYS[2:]),
            )
            directive = account_spec.research_directive
            assert directive is not None
            await create_account_deep_launch(
                conn,
                workspace_id=WORKSPACE_ID,
                project_run_id=fixture.project_run_id,
                directive_id=directive.directive_id,
                account_entity_ids=(fixture.selected_account_id,),
                approved_budget_cap_cents=Decimal("300"),
                expected_estimated_cost_cents=Decimal("300"),
                created_by="human:account-deep-fixture",
                source_operation_id=new_operation_id(),
                source_action_ref="turn:account-deep-fixture-launch",
            )
            resolvers = _bind_recorded_resolvers(fixture)
            committee = build_recorded_committee_source(fixture)
            gateway = FakeGateway()
            session_factory = _TaskReentrantConnectionFactory(conn)
            policies = DEFAULT_RESEARCH_DIRECTIVE.policies
            config_store = _fixture_config_store()

            async def _profile_account_in_fixture_transaction(**kwargs: Any) -> Any:
                return await profile_account(session_factory=session_factory, **kwargs)

            composition = build_deep_phase_handler(
                spec=spec,
                gateway=gateway,
                committee_sources=(committee,),
                recursion_policy=policies.recursion_policy,
                role_model="fixture-role-model",
                budget=BudgetEngine(store=DbBudgetStore(conn_factory=session_factory)),
                pre_spend_gate=PreSpendGateImpl(conn_factory=session_factory),
                session_factory=session_factory,
                storage=storage,
                lock_factory=None,
                budget_cap_cents=policies.account_budget_cap_cents,
                profile_account_fn=_profile_account_in_fixture_transaction,
                config_store=config_store,
            )
            ctx = PhaseContext(
                project_run_id=fixture.project_run_id,
                project_id=PROJECT_ID,
                brand_id=BRAND_ID,
                phase=ProjectPhase.DEEP,
                workspace_id=WORKSPACE_ID,
                icp_key=fixture.deep_icp_key,
                icp_version=fixture.deep_icp_version,
                budget_cap_cents=Decimal("1000"),
                params={},
            )

            assert await get_account_run(conn, fixture.expected_account_run_id) is None
            result = await composition.handler.run(ctx)
            if result.accounts_processed == 0:
                failed_state = await get_account_run(conn, fixture.expected_account_run_id)
                raise AssertionError(
                    "full entry isolated an account error; durable state="
                    f"{failed_state.model_dump(mode='json') if failed_state else None}"
                )
            assert result.status is PhaseStatus.COMPLETED
            assert result.accounts_processed == 1
            assert result.payload["deep_count"] == 1
            assert result.payload["accounts_failed"] == 0
            accounts = result.payload["accounts"]
            assert isinstance(accounts, list) and len(accounts) == 1
            manifest = cast(dict[str, Any], accounts[0])
            assert manifest["status"] == "completed"
            assert manifest["account_entity_id"] == str(fixture.selected_account_id)
            assert manifest["account_run_id"] == str(fixture.expected_account_run_id)
            assert len(manifest["committee_member_ids"]) == 2
            references_index = cast(dict[str, list[str]], manifest["references_index"])
            assert set(references_index) >= {"account", "committee"}
            assert len(references_index["account"]) == 4
            assert all(
                isinstance(claim_id, str)
                for section in references_index.values()
                for claim_id in section
            )

            account_run = await get_account_run(conn, fixture.expected_account_run_id)
            assert account_run is not None
            assert account_run.project_run_id == fixture.project_run_id
            assert account_run.entity_id == fixture.selected_account_id
            assert account_run.tier == "high"
            assert account_run.status is AccountRunStatus.DONE
            assert account_run.sub_phase is AccountRunSubPhase.CONTACTS_COMPLETE
            assert account_run.budget_cap_cents == Decimal("300")
            assert set(account_run.references_index) >= {"account", "committee"}
            assert len(account_run.references_index["account"]) == 4
            governed_rows = (
                (
                    await conn.execute(
                        text(
                            "SELECT field_key, source_key, decision, effective_plan_sha256 "
                            "FROM gate_decision WHERE run_id = :run_id "
                            "AND effective_plan_sha256 IS NOT NULL ORDER BY field_key"
                        ),
                        {"run_id": fixture.expected_account_run_id},
                    )
                )
                .mappings()
                .all()
            )
            assert [(row["field_key"], row["source_key"]) for row in governed_rows] == [
                ("account.hiring_velocity_eng", "sumble_jobs"),
                ("account.operational_pain", "exa_deep"),
                ("account.resonance.culture", "exa_deep"),
                ("account.strategic_moves", "exa_deep"),
            ]
            assert all(row["decision"] == "pass" for row in governed_rows)
            assert all(row["effective_plan_sha256"] for row in governed_rows)
            production_claims = (
                (
                    await conn.execute(
                        text(
                            "SELECT field_key, source_key FROM claim WHERE run_id=:run_id "
                            "AND field_key = ANY(:field_keys) ORDER BY field_key"
                        ),
                        {
                            "run_id": fixture.expected_account_run_id,
                            "field_keys": list(DEEP_FIELD_KEYS),
                        },
                    )
                )
                .mappings()
                .all()
            )
            assert [(row["field_key"], row["source_key"]) for row in production_claims] == [
                ("account.hiring_velocity_eng", "sumble_jobs"),
                ("account.operational_pain", "exa_deep"),
                ("account.resonance.culture", "exa_deep"),
                ("account.strategic_moves", "exa_deep"),
            ]
            assert committee.calls and committee.calls[0][0] == fixture.selected_account_id
            assert gateway.complete_calls == 2

            claim_count_before = int(
                (await conn.execute(text("SELECT count(*) FROM claim"))).scalar_one()
            )
            contact_count_before = int(
                (await conn.execute(text("SELECT count(*) FROM contact_entity"))).scalar_one()
            )
            resolver_calls_before = {
                key: tuple(resolver.calls) for key, resolver in resolvers.items()
            }
            committee_calls_before = tuple(committee.calls)
            gateway_calls_before = gateway.complete_calls

            replay = await composition.handler.run(ctx)
            assert replay.status is PhaseStatus.COMPLETED
            assert replay.accounts_processed == 1
            assert int((await conn.execute(text("SELECT count(*) FROM claim"))).scalar_one()) == (
                claim_count_before
            )
            assert (
                int((await conn.execute(text("SELECT count(*) FROM contact_entity"))).scalar_one())
                == contact_count_before
            )
            assert {
                key: tuple(resolver.calls) for key, resolver in resolvers.items()
            } == resolver_calls_before
            assert tuple(committee.calls) == committee_calls_before
            assert gateway.complete_calls == gateway_calls_before
            original_run = await get_project_run(conn, DISCOVERY_PROJECT_RUN_ID)
            assert original_run is not None
            assert original_run.phase is ProjectPhase.DISCOVERY

    run_async(_run())
