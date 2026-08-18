"""§3.1 rows 5 and 8: employee-range / revenue-band derivation from governed evidence.

The two derive-only account fields own no acquisition source. They are reused when the workspace
already holds a fresh governed claim, and otherwise derived — deterministically, from the exact
governed employee-count / annual-revenue claim that is already on file — or left honestly
unresolved. A derived claim is ``platform_inferred`` provenance over the *source claim's* own
method/tier/url/span, and is never labelled ``human``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from clue_agents.account_entity_research import AssessAccountCoverageInput
from clue_agents.contracts import ModelPolicy
from clue_agents.entity_research_contracts import EntityResearchToolCall
from clue_agents.entity_research_runtime import ActiveEntityResearchToolExecution
from clue_api.account_entity_research import AccountResearchStateStore
from clue_api.account_entity_research_composition import (
    AccountResearchDefinitionResolver,
    StaticAccountResearchProviderActions,
    account_research_profile_sha256,
)
from clue_api.account_field_derivation import (
    DERIVED_ACCOUNT_FIELD_SOURCES,
    AccountFieldDerivation,
    derive_account_fields,
)
from clue_api.entity_research_tools import (
    EntityResearchProviderAction,
    EntityResearchProviderCausationStore,
    EntityResearchResultStore,
    EntityResearchToolRequestStore,
    GovernedEntityResearchToolFactory,
    ProviderActionBinding,
)
from clue_api.trial.account_deep_fixture import seed_insight_health_account_deep_fixture
from clue_core import (
    ClaimProvenanceKind,
    EntityId,
    ExtractionMethod,
    ProjectRunId,
    ResearchMode,
    RunId,
    account_claim,
    new_project_run_id,
    revalidate_with,
)
from clue_core.entity_research import (
    EntityResearchJobAuthorization,
    EntityResearchSelection,
    FieldSourceAuthority,
    ResearchRunKind,
    ResearchRunLifecycleContract,
)
from clue_fleet import DbEntityResearchJobStore, EntityResearchRunEnvelope
from clue_fleet.entity_research import EntityResearchExecutionFence
from clue_research.claimstore import WorkspaceScope, claims_for, insert_claim
from clue_research.durable import insert_account_run, pin_account_run_research_directive
from clue_research.identity import insert_account_entity, stamp_reuse
from clue_research.profiling.committee import load_committee_pack
from clue_research.sources import seed_source_manifests
from clue_research.stage0 import load_client_knowledge_pack
from clue_storage import FsStorage
from tests._workspace import seed_run
from tests.api.account_deep_test_support import confirmed_account_research_direction
from tests.api.test_account_deep_fixture_a1 import _pages
from tests.api.test_account_entity_research_r5_db import _NestedConnFactory
from tests.db.conftest import run_async
from tests.fleet.entity_research_r2_helpers import run_envelope
from tests.profiling.conftest import (
    require_profiling_db as require_profiling_db,
)
from tests.profiling.conftest import (
    rollback_conn,
)

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_COUNT = "core.employee_count"
_RANGE = "core.employee_range"
_REVENUE = "core.annual_revenue"
_BAND = "core.revenue_band"


async def _seed_account(conn: Any, *, workspace_id: str) -> tuple[EntityId, str, ProjectRunId]:
    project_run_id = ProjectRunId(new_project_run_id())
    project_id = await seed_run(
        conn,
        project_run_id=project_run_id,
        workspace_id=workspace_id,
        project_id=f"prj-{workspace_id}",
    )
    account_id = await insert_account_entity(
        conn,
        workspace_id=workspace_id,
        canonical_name="Insight Health AI",
        primary_domain=f"{workspace_id}.example",
    )
    return EntityId(account_id), project_id, project_run_id


async def _seed_source_claim(
    conn: Any,
    *,
    workspace_id: str,
    account_id: EntityId,
    project_run_id: ProjectRunId,
    field_key: str,
    value: Any,
    extraction_method: ExtractionMethod = ExtractionMethod.API,
    source_tier: int = 1,
    observed_at: datetime | None = None,
    evidence_span: str | None = "evidence for the governed source value",
) -> UUID:
    claim = revalidate_with(
        stamp_reuse(
            account_claim(
                entity_id=account_id,
                field_key=field_key,
                value_json=value,
                source_tier=source_tier,
                extraction_method=extraction_method,
                confidence=0.9,
                run_id=RunId(project_run_id),
                research_mode=ResearchMode.ACCOUNT_PROFILING,
                source_url="https://sumble.com/l/org/insight-health-ai",
                evidence_span=evidence_span,
                observed_at=observed_at,
            ),
            workspace_id=workspace_id,
        ),
        source_key="sumble_organizations",
    )
    return await insert_claim(conn, claim)


def _by_field(
    outcomes: tuple[AccountFieldDerivation, ...],
) -> dict[str, AccountFieldDerivation]:
    return {item.field_key: item for item in outcomes}


def test_the_derived_field_map_covers_exactly_the_two_zero_acquisition_derived_rows() -> None:
    assert dict(DERIVED_ACCOUNT_FIELD_SOURCES) == {
        _RANGE: _COUNT,
        _BAND: _REVENUE,
    }


def test_a_fresh_governed_employee_count_settles_the_registered_employee_range_band() -> None:
    async def scenario() -> None:
        workspace_id = "ws-derive-range"
        async with rollback_conn() as conn:
            account_id, project_id, project_run_id = await _seed_account(
                conn, workspace_id=workspace_id
            )
            source_claim_id = await _seed_source_claim(
                conn,
                workspace_id=workspace_id,
                account_id=account_id,
                project_run_id=project_run_id,
                field_key=_COUNT,
                value=1200,
                evidence_span='"employee_count":1200',
            )
            outcomes = _by_field(
                await derive_account_fields(
                    conn,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    project_run_id=project_run_id,
                    account_entity_id=account_id,
                    field_keys=(_RANGE, _BAND),
                )
            )
            assert outcomes[_RANGE].reason == "derived"
            assert outcomes[_RANGE].claim_id is not None
            assert str(outcomes[_RANGE].source_claim_id) == str(source_claim_id)
            # No governed revenue evidence exists, so the band is honestly unresolved.
            assert outcomes[_BAND].claim_id is None
            assert outcomes[_BAND].reason == "derivation_source_missing"

            derived = await claims_for(
                conn,
                account_id,
                _RANGE,
                scope=WorkspaceScope.for_workspace(workspace_id),
            )
            assert len(derived) == 1
            claim = derived[0]
            assert claim.value_json == {"label": "1001-5000", "min": 1001, "max": 5000}
            assert claim.provenance_kind is ClaimProvenanceKind.PLATFORM_INFERRED
            # The source claim's own provenance, verbatim — never a new, invented citation.
            assert claim.extraction_method is ExtractionMethod.API
            assert claim.extraction_method is not ExtractionMethod.HUMAN
            assert int(claim.source_tier) == 1
            assert claim.source_url == "https://sumble.com/l/org/insight-health-ai"
            assert claim.evidence_span == '"employee_count":1200'
            assert claim.run_id == RunId(project_run_id)
            assert (
                await claims_for(
                    conn, account_id, _BAND, scope=WorkspaceScope.for_workspace(workspace_id)
                )
                == []
            )

    run_async(scenario())


def test_revenue_band_derives_from_governed_revenue_and_is_idempotent_on_entity_field_run() -> None:
    async def scenario() -> None:
        workspace_id = "ws-derive-band"
        async with rollback_conn() as conn:
            account_id, project_id, project_run_id = await _seed_account(
                conn, workspace_id=workspace_id
            )
            await _seed_source_claim(
                conn,
                workspace_id=workspace_id,
                account_id=account_id,
                project_run_id=project_run_id,
                field_key=_REVENUE,
                value={
                    "amount": 12_500_000,
                    "currency": "USD",
                    "as_of": "2026-06-30",
                    "estimate_kind": "provider_estimate",
                },
            )

            async def derive() -> dict[str, AccountFieldDerivation]:
                return _by_field(
                    await derive_account_fields(
                        conn,
                        workspace_id=workspace_id,
                        project_id=project_id,
                        project_run_id=project_run_id,
                        account_entity_id=account_id,
                        field_keys=(_BAND,),
                    )
                )

            first = await derive()
            assert first[_BAND].reason == "derived"
            band = await claims_for(
                conn, account_id, _BAND, scope=WorkspaceScope.for_workspace(workspace_id)
            )
            assert len(band) == 1
            assert band[0].value_json == "10m_50m"
            assert band[0].provenance_kind is ClaimProvenanceKind.PLATFORM_INFERRED

            second = await derive()
            assert second[_BAND].claim_id == first[_BAND].claim_id
            assert (
                len(
                    await claims_for(
                        conn, account_id, _BAND, scope=WorkspaceScope.for_workspace(workspace_id)
                    )
                )
                == 1
            )
            assert second[_BAND].reason == "existing_claim_fresh"

    run_async(scenario())


def test_absent_or_stale_source_evidence_leaves_the_field_honestly_unresolved() -> None:
    async def scenario() -> None:
        workspace_id = "ws-derive-stale"
        async with rollback_conn() as conn:
            account_id, project_id, project_run_id = await _seed_account(
                conn, workspace_id=workspace_id
            )
            # 400 days old: outside both the 90-day headcount TTL and the 365-day revenue TTL.
            stale = datetime.now(UTC) - timedelta(days=400)
            await _seed_source_claim(
                conn,
                workspace_id=workspace_id,
                account_id=account_id,
                project_run_id=project_run_id,
                field_key=_COUNT,
                value=1200,
                observed_at=stale,
            )
            await _seed_source_claim(
                conn,
                workspace_id=workspace_id,
                account_id=account_id,
                project_run_id=project_run_id,
                field_key=_REVENUE,
                value={
                    "amount": 12_500_000,
                    "currency": "USD",
                    "as_of": "2025-06-30",
                    "estimate_kind": "provider_estimate",
                },
                observed_at=stale,
            )
            outcomes = _by_field(
                await derive_account_fields(
                    conn,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    project_run_id=project_run_id,
                    account_entity_id=account_id,
                    field_keys=(_RANGE, _BAND),
                )
            )
            for field_key in (_RANGE, _BAND):
                assert outcomes[field_key].claim_id is None
                assert outcomes[field_key].reason == "derivation_source_missing"
                assert (
                    await claims_for(
                        conn,
                        account_id,
                        field_key,
                        scope=WorkspaceScope.for_workspace(workspace_id),
                    )
                    == []
                )

    run_async(scenario())


def test_a_human_asserted_source_never_becomes_a_human_labelled_derived_claim() -> None:
    """Ruling: a derived claim carries the source's method, and that method is never ``human``."""

    async def scenario() -> None:
        workspace_id = "ws-derive-human"
        async with rollback_conn() as conn:
            account_id, project_id, project_run_id = await _seed_account(
                conn, workspace_id=workspace_id
            )
            await _seed_source_claim(
                conn,
                workspace_id=workspace_id,
                account_id=account_id,
                project_run_id=project_run_id,
                field_key=_COUNT,
                value=1200,
                extraction_method=ExtractionMethod.HUMAN,
            )
            outcomes = _by_field(
                await derive_account_fields(
                    conn,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    project_run_id=project_run_id,
                    account_entity_id=account_id,
                    field_keys=(_RANGE,),
                )
            )
            assert outcomes[_RANGE].claim_id is None
            assert outcomes[_RANGE].reason == "derivation_source_not_derivable"
            assert (
                await claims_for(
                    conn, account_id, _RANGE, scope=WorkspaceScope.for_workspace(workspace_id)
                )
                == []
            )

    run_async(scenario())


def test_a_non_usd_revenue_amount_is_not_forced_into_a_usd_band() -> None:
    async def scenario() -> None:
        workspace_id = "ws-derive-currency"
        async with rollback_conn() as conn:
            account_id, project_id, project_run_id = await _seed_account(
                conn, workspace_id=workspace_id
            )
            await _seed_source_claim(
                conn,
                workspace_id=workspace_id,
                account_id=account_id,
                project_run_id=project_run_id,
                field_key=_REVENUE,
                value={
                    "amount": 12_500_000,
                    "currency": "EUR",
                    "as_of": "2026-06-30",
                    "estimate_kind": "provider_estimate",
                },
            )
            outcomes = _by_field(
                await derive_account_fields(
                    conn,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    project_run_id=project_run_id,
                    account_entity_id=account_id,
                    field_keys=(_BAND,),
                )
            )
            assert outcomes[_BAND].claim_id is None
            assert outcomes[_BAND].reason == "derivation_source_not_derivable"

    run_async(scenario())


def _coverage_envelope(
    *,
    account_id: UUID,
    workspace_id: str,
    project_id: str,
    product_id: str,
    project_run_id: UUID,
    profile_sha256: str,
    directive_ref: str,
    directive_sha256: str,
    admitted_field_keys: tuple[str, ...],
) -> EntityResearchRunEnvelope:
    """One account run/job envelope whose admitted axis is exactly the acquisition fields."""

    base = run_envelope(ResearchRunKind.ACCOUNT_RESEARCH)
    original = base.lifecycle.selection
    selection = EntityResearchSelection.model_validate(
        original.model_copy(
            update={
                "workspace_id": workspace_id,
                "project_id": project_id,
                "product_id": product_id,
                "project_run_id": project_run_id,
                "directive_ref": directive_ref,
                "directive_sha256": directive_sha256,
                "subjects": (
                    original.subjects[0].model_copy(update={"subject_entity_id": account_id}),
                ),
                "admitted_field_keys": admitted_field_keys,
                "admitted_source_keys": ("sumble_organizations", "sumble_people"),
                "field_source_authority": tuple(
                    FieldSourceAuthority(field_key=key, source_keys=("sumble_organizations",))
                    for key in admitted_field_keys
                ),
                "committee_source_keys": ("sumble_people",),
                "research_questions": ("What is the current operational burden?",),
            }
        ).model_dump(mode="python")
    )
    lifecycle = ResearchRunLifecycleContract.model_validate(
        base.lifecycle.model_copy(update={"selection": selection}).model_dump(mode="python")
    )
    original_job = base.jobs[0]
    authorization = EntityResearchJobAuthorization.model_validate(
        original_job.authorization.model_copy(
            update={
                "subject_entity_id": account_id,
                "workspace_id": workspace_id,
                "project_id": project_id,
                "product_id": product_id,
                "project_run_id": project_run_id,
                "selection": selection,
                "agent_profile_ref": "agent-profile:account-research:v1",
                "agent_profile_sha256": profile_sha256,
            }
        ).model_dump(mode="python")
    )
    return EntityResearchRunEnvelope.model_validate(
        base.model_copy(
            update={
                "lifecycle": lifecycle,
                "jobs": (original_job.model_copy(update={"authorization": authorization}),),
            }
        ).model_dump(mode="python")
    )


class _NoProviderAction(EntityResearchProviderAction):
    async def execute(self, request: Any, *, before_dispatch: Any) -> Any:
        raise AssertionError("coverage assessment must not dispatch a provider")


def test_assess_settles_the_directives_derived_rows_into_the_coverage_ledger(
    tmp_path: Any,
) -> None:
    """The wiring: a run that holds governed headcount closes with its band derived and cited.

    ``core.employee_range`` / ``core.revenue_band`` are not admitted fields (they buy nothing), so
    this proves the coverage ledger answers for them anyway: the derivable one lands *completed*
    with its derived claim in ``claim_refs``, and the one with no governed source lands
    *unresolved* with ``derivation_source_missing``.
    """

    async def scenario() -> None:
        storage = FsStorage(tmp_path / "derivation-coverage")
        async with rollback_conn() as conn:
            await load_committee_pack(conn)
            await load_client_knowledge_pack(conn)
            await seed_source_manifests(conn)
            fixture = await seed_insight_health_account_deep_fixture(
                conn,
                pages=_pages(),
                storage=storage,
            )
            workspace_id = fixture.discovery_fixture.workspace_id
            account_id = UUID(str(fixture.selected_account_id))
            _, account_spec = await confirmed_account_research_direction(
                conn,
                workspace_id=workspace_id,
                project_id=fixture.discovery_fixture.project_id,
                product_id=fixture.discovery_fixture.product_id,
                account_id=fixture.selected_account_id,
                icp_key=fixture.deep_icp_key,
                icp_version=fixture.deep_icp_version,
                field_keys=(_COUNT, _RANGE, _BAND),
                allowed_source_keys=("sumble_organizations",),
            )
            directive = account_spec.research_directive
            assert directive is not None
            await insert_account_run(
                conn,
                account_run_id=fixture.expected_account_run_id,
                project_run_id=fixture.project_run_id,
                entity_id=fixture.selected_account_id,
                tier="high",
            )
            await pin_account_run_research_directive(
                conn,
                account_run_id=fixture.expected_account_run_id,
                pin=directive,
            )
            # The fixture account already holds a governed headcount (42) and a governed revenue
            # band. A second, disagreeing authoritative revenue band puts that row in an open
            # conflict, so it is no longer governed evidence to reuse — and no
            # ``core.annual_revenue`` claim exists to derive a replacement from.
            await _seed_source_claim(
                conn,
                workspace_id=workspace_id,
                account_id=EntityId(account_id),
                project_run_id=ProjectRunId(fixture.project_run_id),
                field_key=_BAND,
                value="1b_plus",
            )
            connection = _NestedConnFactory(conn)
            envelope = _coverage_envelope(
                account_id=account_id,
                workspace_id=workspace_id,
                project_id=fixture.discovery_fixture.project_id,
                product_id=fixture.discovery_fixture.product_id,
                project_run_id=UUID(str(fixture.project_run_id)),
                profile_sha256=account_research_profile_sha256(),
                directive_ref=directive.directive_ref,
                directive_sha256=directive.canonical_json_sha256,
                admitted_field_keys=(_COUNT,),
            )
            jobs = DbEntityResearchJobStore(conn_factory=connection)
            await jobs.launch(envelope)
            authorization = envelope.jobs[0].authorization
            stored_job = await jobs.get_job(authorization.job_id)
            assert stored_job is not None
            live_job = stored_job.model_copy(
                update={"active_worker_id": "b7-test-worker", "lease_generation": 1}
            )
            state = AccountResearchStateStore(conn_factory=connection)
            binding = ProviderActionBinding(action=_NoProviderAction(), version=1)
            resolver = AccountResearchDefinitionResolver(
                tools=GovernedEntityResearchToolFactory(
                    requests=EntityResearchToolRequestStore(
                        conn_factory=connection, storage=storage
                    ),
                    causation=EntityResearchProviderCausationStore(conn_factory=connection),
                    results=EntityResearchResultStore(
                        storage=storage,
                        conn_factory=connection,
                        lineage_readers={},
                    ),
                ),
                state=state,
                provider_actions=StaticAccountResearchProviderActions(
                    {
                        authorization.job_id: {
                            "research_account_deep": binding,
                            "enrich_account": binding,
                            "discover_buying_committee": binding,
                        }
                    }
                ),
                model_policy=ModelPolicy(
                    model_id="b7-test-model",
                    timeout_s=10,
                    max_retries=0,
                    max_output_tokens=4096,
                    temperature=0,
                ),
                conn_factory=connection,
            )
            definition = await resolver.resolve(
                job=live_job,
                fence=EntityResearchExecutionFence(
                    task_id=uuid4(), worker_id="b7-test-worker", lease_generation=1
                ),
            )
            active = ActiveEntityResearchToolExecution(
                context=definition.context,
                call=EntityResearchToolCall(
                    tool_call_id="b7-assess",
                    tool_name="assess_account_coverage",
                    tool_version=1,
                    tool_input_sha256="a" * 64,
                    arguments={"result_refs": [], "assessment_note": "derivation wiring"},
                ),
                journal_event_ref="entity-agent-journal:b7-assess",
            )
            coverage = await state.assess(
                AssessAccountCoverageInput(result_refs=(), assessment_note="derivation wiring"),
                active,
            )
            assert _COUNT in coverage.completed_field_keys
            assert _RANGE in coverage.completed_field_keys
            assert _BAND in coverage.unresolved_field_keys
            assert f"{_BAND}:derivation_source_missing" in coverage.unresolved_reasons
            assert f"{_RANGE}:derived" in coverage.skipped_field_reasons
            derived = await claims_for(
                conn,
                EntityId(account_id),
                _RANGE,
                scope=WorkspaceScope.for_workspace(workspace_id),
            )
            assert len(derived) == 1
            assert derived[0].value_json == {"label": "11-50", "min": 11, "max": 50}
            assert f"claim:{derived[0].id}" in coverage.claim_refs
            assert "account_fields_unresolved" in coverage.review_flags

            stored = (
                (
                    await conn.execute(
                        text(
                            "SELECT completed_field_keys, unresolved_field_keys, "
                            "unresolved_reasons FROM entity_research_account_coverage "
                            "WHERE coverage_id=:id"
                        ),
                        {"id": coverage.coverage_id},
                    )
                )
                .mappings()
                .one()
            )
            assert set(stored["completed_field_keys"]) == {_COUNT, _RANGE}
            assert set(coverage.completed_field_keys + coverage.unresolved_field_keys) == {
                _COUNT,
                _RANGE,
                _BAND,
            }
            assert list(stored["unresolved_field_keys"]) == [_BAND]
            assert f"{_BAND}:derivation_source_missing" in stored["unresolved_reasons"]

    run_async(scenario())


@pytest.mark.parametrize(
    ("headcount", "label"),
    [
        (1, "1-10"),
        (10, "1-10"),
        (11, "11-50"),
        (200, "51-200"),
        (501, "501-1000"),
        (10_001, "10001+"),
    ],
)
def test_every_headcount_lands_in_exactly_one_deterministic_band(
    headcount: int, label: str
) -> None:
    async def scenario() -> None:
        workspace_id = f"ws-band-{headcount}"
        async with rollback_conn() as conn:
            account_id, project_id, project_run_id = await _seed_account(
                conn, workspace_id=workspace_id
            )
            await _seed_source_claim(
                conn,
                workspace_id=workspace_id,
                account_id=account_id,
                project_run_id=project_run_id,
                field_key=_COUNT,
                value=headcount,
            )
            await derive_account_fields(
                conn,
                workspace_id=workspace_id,
                project_id=project_id,
                project_run_id=project_run_id,
                account_entity_id=account_id,
                field_keys=(_RANGE,),
            )
            claims = await claims_for(
                conn, account_id, _RANGE, scope=WorkspaceScope.for_workspace(workspace_id)
            )
            assert len(claims) == 1
            assert isinstance(claims[0].value_json, dict)
            assert claims[0].value_json["label"] == label

    run_async(scenario())


@pytest.mark.parametrize(
    ("amount", "band"),
    [
        (Decimal("999999"), "under_1m"),
        (Decimal("1000000"), "1m_10m"),
        (Decimal("50000000"), "50m_100m"),
        (Decimal("999999999"), "500m_1b"),
        (Decimal("1000000000"), "1b_plus"),
    ],
)
def test_every_revenue_amount_lands_in_exactly_one_registered_band(
    amount: Decimal, band: str
) -> None:
    async def scenario() -> None:
        workspace_id = f"ws-rev-{amount}"
        async with rollback_conn() as conn:
            account_id, project_id, project_run_id = await _seed_account(
                conn, workspace_id=workspace_id
            )
            await _seed_source_claim(
                conn,
                workspace_id=workspace_id,
                account_id=account_id,
                project_run_id=project_run_id,
                field_key=_REVENUE,
                value={
                    "amount": float(amount),
                    "currency": "USD",
                    "as_of": "2026-06-30",
                    "estimate_kind": "reported",
                },
            )
            await derive_account_fields(
                conn,
                workspace_id=workspace_id,
                project_id=project_id,
                project_run_id=project_run_id,
                account_entity_id=account_id,
                field_keys=(_BAND,),
            )
            claims = await claims_for(
                conn, account_id, _BAND, scope=WorkspaceScope.for_workspace(workspace_id)
            )
            assert len(claims) == 1
            assert claims[0].value_json == band

    run_async(scenario())
