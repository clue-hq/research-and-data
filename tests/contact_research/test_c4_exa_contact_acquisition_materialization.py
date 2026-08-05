"""M8C C4 acceptance: durable exact-contact Exa acquisition and offline materialization."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.api.account_deep_test_support import confirmed_account_research_direction
from tests.api.test_account_deep_fixture_a1 import _pages
from tests.profiling.conftest import migrated_db as migrated_db
from tests.profiling.conftest import require_profiling_db as require_profiling_db
from tests.profiling.conftest import rollback_conn

from clue_api.account_deep_source_policy import bind_healthcare_account_deep_source_override
from clue_api.exa_contact_acquisition import ExaDeepContactAcquisitionService
from clue_api.exa_contact_materialization import (
    ExaDeepContactSnapshotMaterializer,
    ExaDeepContactSnapshotResolverProvider,
)
from clue_api.exa_deep_acquisition import (
    ExaDeepAcquisitionCoordinator,
    ExaDeepAcquisitionOutcome,
)
from clue_api.trial.account_deep_fixture import seed_insight_health_account_deep_fixture
from clue_api.trial.discovery_fixture import PRODUCT_ID, PROJECT_ID, WORKSPACE_ID
from clue_config import ContactResearchPolicy
from clue_core import (
    ContactResearchIntent,
    ContactResearchPolicyPin,
    ContactResearchSelection,
    ContactResearchSelectionBody,
    ContactResearchTarget,
    ICPCreatedFrom,
    IdentityBinding,
    ProjectPhase,
    ResearchQuestion,
    UseClass,
    new_claim_id,
    new_project_run_id,
    new_run_id,
)
from clue_research.claimstore import WorkspaceScope, claims_for
from clue_research.durable import ProjectRunStatus, ensure_project_run, get_project_run
from clue_research.icp import create_icp_spec, get_icp_version
from clue_research.identity import insert_contact_entity
from clue_research.resolvers.exa import ExaDeepContactNormalization
from clue_storage import FsStorage, read_verified_artifact

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_FIXTURES = Path(__file__).parents[1] / "fixtures" / "contact_research" / "exa_c3"
_FIELD = "contact.facet.publications"


def _payload(name: str) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((_FIXTURES / name).read_text(encoding="utf-8")))


class _Transport:
    def __init__(
        self, payload: Mapping[str, Any] | BaseException, tracker: _TrackedConnFactory
    ) -> None:
        self.payload = payload
        self.tracker = tracker
        self.calls = 0

    def search(self, request: object) -> Mapping[str, Any]:
        del request
        assert self.tracker.active == 0, "provider traffic occurred under a database context"
        self.calls += 1
        if isinstance(self.payload, BaseException):
            raise self.payload
        return self.payload


class _NoProviderTransport:
    calls = 0

    def search(self, request: object) -> Mapping[str, Any]:
        del request
        self.calls += 1
        raise AssertionError("fresh-process replay must not call Exa")


class _ProcessCrash(BaseException):
    pass


class _TrackedConnFactory:
    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn
        self.active = 0

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[AsyncConnection]:
        self.active += 1
        try:
            yield self.conn
        finally:
            self.active -= 1


@dataclass(frozen=True)
class _Seed:
    intent: ContactResearchIntent
    policy: ContactResearchPolicyPin


async def _seed(
    conn: AsyncConnection,
    storage: FsStorage,
    *,
    suffix: str,
    contact_reveals_allowed: bool = False,
) -> _Seed:
    fixture = await seed_insight_health_account_deep_fixture(
        conn,
        pages=_pages(),
        storage=storage,
    )
    parent_icp = await get_icp_version(
        conn,
        WORKSPACE_ID,
        fixture.deep_icp_key,
        fixture.deep_icp_version,
    )
    parent_run = await get_project_run(conn, fixture.project_run_id)
    assert parent_icp is not None and parent_run is not None
    assert parent_run.product_context_version_id is not None
    assert parent_run.readiness_decision_id is not None

    icp_key = f"healthcare-contact-c4-{suffix}"
    await bind_healthcare_account_deep_source_override(
        conn,
        workspace_id=WORKSPACE_ID,
        icp_key=icp_key,
        version=1,
    )
    icp = await create_icp_spec(
        conn,
        workspace_id=WORKSPACE_ID,
        icp_key=icp_key,
        created_from=ICPCreatedFrom.CLIENT_EDIT,
        field_keys=(_FIELD,),
        enabled_packs=("healthcare_practice",),
        source_profile_ref={"contract": "m8c-c4-contact-source-profile-v1"},
        created_by="human:c4-test",
        activate=True,
        client_entity_id=parent_icp.client_entity_id,
        client_kb_version=parent_icp.client_kb_version,
        product_id=parent_icp.product_id,
    )
    project_run_id = new_project_run_id()
    await ensure_project_run(
        conn,
        project_run_id=project_run_id,
        project_id=PROJECT_ID,
        workspace_id=WORKSPACE_ID,
        icp_key=icp.icp_key,
        icp_version=icp.version,
        phase=ProjectPhase.DEEP,
        status=ProjectRunStatus.ACTIVE,
        client_entity_id=icp.client_entity_id,
        client_kb_version=icp.client_kb_version,
        product_id=PRODUCT_ID,
        product_context_version_id=parent_run.product_context_version_id,
        readiness_decision_id=parent_run.readiness_decision_id,
    )
    contact_id = await insert_contact_entity(
        conn,
        account_entity_id=fixture.selected_account_id,
        full_name="Alex Rivera",
        linkedin_url=f"https://www.linkedin.com/in/alex-rivera-c4-{suffix}",
        geo={"city": "Portland", "region": "Oregon"},
    )
    question = ResearchQuestion(
        question_id=f"publication-direction-{suffix}",
        text="Which attributable publications discuss referral operations?",
        target_field_key=_FIELD,
        source_family_hints=("exa_deep",),
    )
    _, account_spec = await confirmed_account_research_direction(
        conn,
        workspace_id=WORKSPACE_ID,
        project_id=PROJECT_ID,
        product_id=PRODUCT_ID,
        account_id=fixture.selected_account_id,
        icp_key=icp.icp_key,
        icp_version=icp.version,
        field_keys=(_FIELD,),
        allowed_source_keys=("exa_deep",),
        questions=(question,),
        contact_profiling_allowed=True,
        contact_reveals_allowed=contact_reveals_allowed,
    )
    directive = account_spec.research_directive
    assert directive is not None
    policy = ContactResearchPolicy().pin()
    body = ContactResearchSelectionBody(
        workspace_id=WORKSPACE_ID,
        project_id=PROJECT_ID,
        project_run_id=project_run_id,
        account_entity_id=fixture.selected_account_id,
        research_directive=directive,
        targets=(
            ContactResearchTarget(
                contact_entity_id=contact_id,
                committee_claim_ids=(new_claim_id(),),
                strong_identity_claim_ids=(new_claim_id(),),
                field_keys=(_FIELD,),
                directional_question_ids=(question.question_id,),
            ),
        ),
        policy=policy,
        source_profile_ref=f"source-profile:healthcare-contact-c4-{suffix}",
        jurisdiction_policy_ref="jurisdiction:strict:v1",
        use_policy_ref="use:personal-public-non-sensitive:v1",
        retention_policy_ref="retention:contact:v1",
        budget_reservation_ref=f"budget:contact-c4-{suffix}",
        approved_by="human:owner",
        approved_at=datetime(2026, 8, 5, tzinfo=UTC),
    )
    selection = ContactResearchSelection.from_body(body, effective_policy=policy)
    return _Seed(
        intent=ContactResearchIntent.from_selection(
            selection,
            contact_entity_id=contact_id,
        ),
        policy=policy,
    )


def test_c4_acquires_once_settles_once_materializes_governed_claim_and_replays(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn() as conn:
            seed = await _seed(conn, storage, suffix="success")
            factory = _TrackedConnFactory(conn)
            transport = _Transport(_payload("supported.json"), factory)
            coordinator = ExaDeepAcquisitionCoordinator(
                transport=transport,
                storage=storage,
                conn_factory=factory,
            )
            service = ExaDeepContactAcquisitionService(
                coordinator=coordinator,
                conn_factory=factory,
            )
            spent_before = Decimal(
                (
                    await conn.execute(
                        text("SELECT spent_cents FROM project_run WHERE id=:id"),
                        {"id": seed.intent.project_run_id},
                    )
                ).scalar_one()
            )
            acquired = await service.acquire_intent(
                intent=seed.intent,
                effective_policy=seed.policy,
                observation_window="contact-c4-success",
            )
            assert acquired.provider_calls == 1
            assert transport.calls == 1
            assert len(acquired.results) == 1
            ready = acquired.results[0]
            assert ready.outcome is ExaDeepAcquisitionOutcome.READY
            assert ready.snapshot is not None
            assert ready.snapshot.subject_kind.value == "contact"
            assert ready.snapshot.contact_id == seed.intent.contact_entity_id
            assert ready.snapshot.provider_reported_cost_cents == Decimal(8)

            request_artifact = json.loads(
                (
                    await read_verified_artifact(
                        conn,
                        storage,
                        storage_key=ready.snapshot.request_artifact_key,
                        workspace_id=seed.intent.workspace_id,
                    )
                )[1]
            )
            assert request_artifact["contact_intent_sha256"] == seed.intent.sha256()
            assert request_artifact["contact_target_lock"]["contact_entity_id"] == str(
                seed.intent.contact_entity_id
            )
            assert len(request_artifact["field_source_plans"]) == 1

            run_id = new_run_id()
            provider = ExaDeepContactSnapshotResolverProvider(
                storage=storage,
                conn_factory=factory,
            )
            materializer = ExaDeepContactSnapshotMaterializer(
                provider=provider,
                conn_factory=factory,
            )
            first = await materializer.materialize(
                intent=seed.intent,
                effective_policy=seed.policy,
                run_id=run_id,
            )
            assert len(first.fields) == 1
            assert len(first.fields[0].claim_refs) == 1
            written = await claims_for(
                conn,
                seed.intent.contact_entity_id,
                _FIELD,
                scope=WorkspaceScope.for_workspace(seed.intent.workspace_id),
            )
            provider_claims = [claim for claim in written if claim.source_key == "exa_deep"]
            assert len(provider_claims) == 1
            claim = provider_claims[0]
            assert claim.identity_binding is IdentityBinding.STRONG
            assert claim.use_class is UseClass.PROFESSIONAL_PUBLIC
            assert claim.source_operation_ref == str(ready.operation.operation_id)
            assert claim.source_snapshot_ref == str(ready.snapshot.snapshot_id)
            assert claim.source_request_ref == ready.snapshot.provider_request_id
            assert claim.artifact_key is not None
            assert claim.cost_cents == 0

            no_provider = _NoProviderTransport()
            replay_service = ExaDeepContactAcquisitionService(
                coordinator=ExaDeepAcquisitionCoordinator(
                    transport=no_provider,
                    storage=storage,
                    conn_factory=factory,
                ),
                conn_factory=factory,
            )
            replay = await replay_service.acquire_intent(
                intent=seed.intent,
                effective_policy=seed.policy,
                observation_window="contact-c4-success",
            )
            assert replay.provider_calls == 0
            assert no_provider.calls == 0
            assert replay.results[0].outcome is ExaDeepAcquisitionOutcome.REPLAYED
            second = await ExaDeepContactSnapshotMaterializer(
                provider=ExaDeepContactSnapshotResolverProvider(
                    storage=storage,
                    conn_factory=factory,
                ),
                conn_factory=factory,
            ).materialize(
                intent=seed.intent,
                effective_policy=seed.policy,
                run_id=run_id,
            )
            assert second.fields[0].claim_refs == first.fields[0].claim_refs
            assert Decimal(
                (
                    await conn.execute(
                        text("SELECT spent_cents FROM project_run WHERE id=:id"),
                        {"id": seed.intent.project_run_id},
                    )
                ).scalar_one()
            ) == spent_before + Decimal(8)
            counts = (
                (
                    await conn.execute(
                        text(
                            "SELECT "
                            "(SELECT count(*) FROM external_research_operation "
                            "WHERE contact_id=:contact_id) AS operations, "
                            "(SELECT count(*) FROM external_research_receipt receipt "
                            "JOIN external_research_operation operation "
                            "ON operation.id=receipt.operation_id "
                            "WHERE operation.contact_id=:contact_id) AS receipts"
                        ),
                        {"contact_id": seed.intent.contact_entity_id},
                    )
                )
                .mappings()
                .one()
            )
            assert dict(counts) == {"operations": 1, "receipts": 1}

    from tests.db.conftest import run_async

    run_async(scenario())


@pytest.mark.parametrize("fixture", ("same_name_wrong_employer.json", "contradictory_profile.json"))
def test_c4_rejected_target_evidence_is_retained_but_never_becomes_a_claim(
    tmp_path: Path,
    fixture: str,
) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn() as conn:
            seed = await _seed(conn, storage, suffix=fixture.split(".")[0])
            factory = _TrackedConnFactory(conn)
            transport = _Transport(_payload(fixture), factory)
            service = ExaDeepContactAcquisitionService(
                coordinator=ExaDeepAcquisitionCoordinator(
                    transport=transport,
                    storage=storage,
                    conn_factory=factory,
                ),
                conn_factory=factory,
            )
            acquired = await service.acquire_intent(
                intent=seed.intent,
                effective_policy=seed.policy,
                observation_window=f"contact-c4-{fixture}",
            )
            assert acquired.provider_calls == 1
            snapshot = acquired.results[0].snapshot
            assert snapshot is not None
            normalization = ExaDeepContactNormalization.model_validate_json(
                (
                    await read_verified_artifact(
                        conn,
                        storage,
                        storage_key=snapshot.normalization_artifact_key,
                        workspace_id=seed.intent.workspace_id,
                    )
                )[1]
            )
            assert normalization.synthesis.fields == ()
            assert normalization.citations[0].target_binding.value in {
                "unresolved",
                "contradictory",
            }
            assert normalization.citations[0].reason_codes
            materialized = await ExaDeepContactSnapshotMaterializer(
                provider=ExaDeepContactSnapshotResolverProvider(
                    storage=storage,
                    conn_factory=factory,
                ),
                conn_factory=factory,
            ).materialize(
                intent=seed.intent,
                effective_policy=seed.policy,
                run_id=new_run_id(),
            )
            assert materialized.fields[0].claim_refs == ()
            claims = await claims_for(
                conn,
                seed.intent.contact_entity_id,
                _FIELD,
                scope=WorkspaceScope.for_workspace(seed.intent.workspace_id),
            )
            assert not [claim for claim in claims if claim.source_key == "exa_deep"]

    from tests.db.conftest import run_async

    run_async(scenario())


def test_c4_malformed_dispatched_response_is_retained_and_spend_unknown(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn() as conn:
            seed = await _seed(conn, storage, suffix="malformed")
            factory = _TrackedConnFactory(conn)
            transport = _Transport(_payload("malformed.json"), factory)
            result = await ExaDeepContactAcquisitionService(
                coordinator=ExaDeepAcquisitionCoordinator(
                    transport=transport,
                    storage=storage,
                    conn_factory=factory,
                ),
                conn_factory=factory,
            ).acquire_intent(
                intent=seed.intent,
                effective_policy=seed.policy,
                observation_window="contact-c4-malformed",
            )
            assert result.provider_calls == 1
            assert transport.calls == 1
            assert result.results[0].outcome is ExaDeepAcquisitionOutcome.SPEND_OUTCOME_UNKNOWN
            assert result.results[0].snapshot is None
            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT attempt.response_artifact_key, operation.failure_code "
                            "FROM external_research_operation operation "
                            "JOIN external_research_attempt attempt "
                            "ON attempt.operation_id=operation.id "
                            "WHERE operation.id=:operation_id"
                        ),
                        {"operation_id": result.results[0].operation.operation_id},
                    )
                )
                .mappings()
                .one()
            )
            assert row["response_artifact_key"] is not None
            assert row["failure_code"] == "spend_unknown"
            receipt_count = int(
                (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM external_research_receipt "
                            "WHERE operation_id=:operation_id"
                        ),
                        {"operation_id": result.results[0].operation.operation_id},
                    )
                ).scalar_one()
            )
            assert receipt_count == 0

    from tests.db.conftest import run_async

    run_async(scenario())


def test_c4_stale_policy_and_crash_replay_cause_no_duplicate_provider_call(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn() as conn:
            seed = await _seed(conn, storage, suffix="guards")
            factory = _TrackedConnFactory(conn)
            transport = _Transport(_payload("supported.json"), factory)
            service = ExaDeepContactAcquisitionService(
                coordinator=ExaDeepAcquisitionCoordinator(
                    transport=transport,
                    storage=storage,
                    conn_factory=factory,
                ),
                conn_factory=factory,
            )
            stale_policy = seed.policy.model_copy(update={"max_fields_per_contact": 7})
            with pytest.raises(ValueError, match="effective config policy"):
                await service.acquire_intent(
                    intent=seed.intent,
                    effective_policy=stale_policy,
                    observation_window="contact-c4-stale-policy",
                )
            assert transport.calls == 0

            crash_transport = _Transport(_ProcessCrash(), factory)
            crash_service = ExaDeepContactAcquisitionService(
                coordinator=ExaDeepAcquisitionCoordinator(
                    transport=crash_transport,
                    storage=storage,
                    conn_factory=factory,
                ),
                conn_factory=factory,
            )
            with pytest.raises(_ProcessCrash):
                await crash_service.acquire_intent(
                    intent=seed.intent,
                    effective_policy=seed.policy,
                    observation_window="contact-c4-crash",
                )
            assert crash_transport.calls == 1
            no_provider = _NoProviderTransport()
            joined = await ExaDeepContactAcquisitionService(
                coordinator=ExaDeepAcquisitionCoordinator(
                    transport=no_provider,
                    storage=storage,
                    conn_factory=factory,
                ),
                conn_factory=factory,
            ).acquire_intent(
                intent=seed.intent,
                effective_policy=seed.policy,
                observation_window="contact-c4-crash",
            )
            assert joined.results[0].outcome is ExaDeepAcquisitionOutcome.JOINED_IN_FLIGHT
            assert joined.provider_calls == 0
            assert no_provider.calls == 0
            count = int(
                (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM external_research_operation "
                            "WHERE contact_id=:contact_id"
                        ),
                        {"contact_id": seed.intent.contact_entity_id},
                    )
                ).scalar_one()
            )
            assert count == 1

    from tests.db.conftest import run_async

    run_async(scenario())
