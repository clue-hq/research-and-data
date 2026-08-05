"""S2C ready-snapshot CommitteeSource and exact-account acceptance."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.sumble_committee_acquisition import (
    SumbleCommitteeAcquisitionCoordinator,
    compile_sumble_committee_preflight,
)
from clue_api.sumble_committee_source import (
    SumbleCommitteeSnapshotNotReady,
    SumbleCommitteeSnapshotUnavailable,
    SumbleCommitteeSource,
    _select_provider_person_ids,
)
from clue_core import (
    ClaimProvenanceKind,
    ExtractionMethod,
    IdentityBinding,
    ResearchMode,
    RunId,
    UseClass,
    new_claim_id,
    new_entity_id,
)
from clue_research.claimstore import WorkspaceScope, claims_for, insert_claim
from clue_research.durable import tombstone_discovery_subject_artifacts
from clue_research.identity import get_account
from clue_research.profiling.committee import (
    CURRENT_LOCATION,
    CURRENT_TITLE,
    JOB_FUNCTION,
    JOB_LEVEL,
    ORGANIZATION_RELATIONSHIP,
    PERSONA,
    ROLE_ON_COMMITTEE,
    TEAM_MEMBERSHIP,
    CandidateFactProvenance,
    discover_committee,
)
from clue_storage import FsStorage
from tests.api.test_sumble_committee_acquisition_s2b import _CommitteeTransport, _setup
from tests.db.conftest import run_async
from tests.durable.conftest import rollback_conn
from tests.profiling.conftest import FakeGateway, insert_test_account, seed_packs

pytestmark = pytest.mark.usefixtures("require_profiling_db")


def test_s2c_bounded_union_prefers_strong_and_preserves_teams_representation() -> None:
    assert _select_provider_person_ids(
        people_ids=(1001, 1002),
        membership_ids=(1001, 2002),
        strong_ids=frozenset({1001, 1002, 2002}),
        limit=2,
    ) == (1001, 2002)
    assert _select_provider_person_ids(
        people_ids=(1001, 1002),
        membership_ids=(1001, 2002),
        strong_ids=frozenset({1001, 1002}),
        limit=2,
    ) == (1001, 1002)


def test_s2c_reads_only_ready_exact_account_snapshots_and_survives_no_provider_calls(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            request = await _setup(conn, storage, workspace_id="ws-s2c-source")

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            transport = _CommitteeTransport()
            coordinator = SumbleCommitteeAcquisitionCoordinator(
                transport=transport,
                storage=storage,
                cents_per_credit=Decimal("0.5"),
                conn_factory=same_connection,
                poll_after_seconds=30,
            )
            preflight = compile_sumble_committee_preflight(request, cents_per_credit=Decimal("0.5"))
            pending = await coordinator.start(preflight)
            account = await get_account(conn, request.account_id)
            assert account is not None
            source = SumbleCommitteeSource(
                operation_ids={request.account_id: pending.operation.operation_id},
                storage=storage,
                conn_factory=same_connection,
            )
            with pytest.raises(SumbleCommitteeSnapshotNotReady, match="not ready"):
                await source.find_candidates(account, limit=10)
            assert transport.calls == ["teams", "people_submit"]

            for _ in range(2):
                await conn.execute(
                    text(
                        "UPDATE committee_acquisition_operation SET next_poll_at=:past WHERE id=:id"
                    ),
                    {
                        "id": pending.operation.operation_id,
                        "past": datetime.now(UTC) - timedelta(seconds=1),
                    },
                )
                ready = await coordinator.start(preflight)
            assert ready.operation.state.value == "ready"
            provider_call_count = len(transport.calls)
            candidates = await source.find_candidates(account, limit=10)
            assert len(candidates) == 1
            candidate = candidates[0]
            assert candidate.source_key == "sumble_people"
            assert candidate.source_person_id == "1001"
            assert candidate.full_name == "Alex Morgan"
            assert candidate.title == "VP of Operations"
            assert candidate.job_function == "Operations"
            assert candidate.job_level == "VP"
            assert candidate.team_names == ("Patient Access Operations",)
            assert candidate.relationship_labels == ("provider_inferred_team_membership",)
            assert candidate.has_strong_key is True
            assert candidate.verified_email is None
            assert candidate.cost_cents == 0
            assert len(candidate.evidence_refs) == 2
            assert {str(fact.field_key) for fact in candidate.professional_facts} == {
                CURRENT_TITLE,
                JOB_FUNCTION,
                JOB_LEVEL,
                TEAM_MEMBERSHIP,
                CURRENT_LOCATION,
                ORGANIZATION_RELATIONSHIP,
            }
            assert {fact.provenance_kind for fact in candidate.professional_facts} == {
                CandidateFactProvenance.PROVIDER_RETURNED,
                CandidateFactProvenance.PROVIDER_MODELED,
            }
            assert all(
                fact.source_url and fact.evidence_span and fact.artifact_key
                for fact in candidate.professional_facts
            )
            assert candidate.discovery_confidence == pytest.approx(0.92)
            assert len(transport.calls) == provider_call_count

            await seed_packs(conn)
            gateway = FakeGateway()
            committee = await discover_committee(
                conn,
                account_entity_id=request.account_id,
                run_id=RunId(request.project_run_id),
                workspace_id=request.workspace_id,
                sources=[source],
                gateway=gateway,
                role_model="s2c-role-model",
            )
            assert committee.admitted == 1
            assert committee.dropped == 0
            assert gateway.complete_calls == 1
            assert len(transport.calls) == provider_call_count
            member = committee.members[0]
            scope = WorkspaceScope.for_workspace(request.workspace_id)
            role_claims = await claims_for(
                conn, member.contact_entity_id, ROLE_ON_COMMITTEE, scope=scope
            )
            persona_claims = await claims_for(conn, member.contact_entity_id, PERSONA, scope=scope)
            assert len(role_claims) == 1
            assert len(persona_claims) == 1
            assert role_claims[0].research_mode is ResearchMode.COMMITTEE_DISCOVERY
            assert persona_claims[0].research_mode is ResearchMode.COMMITTEE_DISCOVERY
            assert role_claims[0].provenance_kind is ClaimProvenanceKind.PLATFORM_INFERRED
            assert persona_claims[0].provenance_kind is ClaimProvenanceKind.PLATFORM_INFERRED

            professional_ids = set(member.professional_claim_ids)
            assert len(professional_ids) == 6
            for field_key in (
                CURRENT_TITLE,
                JOB_FUNCTION,
                JOB_LEVEL,
                TEAM_MEMBERSHIP,
                CURRENT_LOCATION,
                ORGANIZATION_RELATIONSHIP,
            ):
                field_claims = await claims_for(
                    conn, member.contact_entity_id, field_key, scope=scope
                )
                assert len(field_claims) == 1
                field_claim = field_claims[0]
                assert field_claim.id in professional_ids
                assert field_claim.extraction_method is ExtractionMethod.API
                assert field_claim.identity_binding is IdentityBinding.STRONG
                assert field_claim.use_class is UseClass.PROFESSIONAL_PUBLIC
                assert field_claim.source_key in {"sumble_people", "sumble_teams"}
                assert field_claim.source_url
                assert field_claim.evidence_span
                assert field_claim.artifact_key
                assert field_claim.source_operation_ref
                assert field_claim.source_snapshot_ref
                assert field_claim.source_request_ref
                expected_kind = (
                    ClaimProvenanceKind.PROVIDER_MODELED
                    if field_key == TEAM_MEMBERSHIP
                    else ClaimProvenanceKind.PROVIDER_RETURNED
                )
                assert field_claim.provenance_kind is expected_kind

            title_claim = (
                await claims_for(conn, member.contact_entity_id, CURRENT_TITLE, scope=scope)
            )[0]
            adversarial_updates = (
                {
                    "id": new_claim_id(),
                    "source_operation_ref": (
                        "committee-operation:00000000-0000-0000-0000-000000000000"
                    ),
                },
                {
                    "id": new_claim_id(),
                    "source_operation_ref": None,
                    "source_snapshot_ref": None,
                    "source_request_ref": None,
                },
                {
                    "id": new_claim_id(),
                    "provenance_kind": ClaimProvenanceKind.PROVIDER_MODELED,
                },
            )
            for updates in adversarial_updates:
                with pytest.raises(DBAPIError):
                    async with conn.begin_nested():
                        await insert_claim(conn, title_claim.model_copy(update=updates))

            foreign_account = await insert_test_account(conn, workspace_id=request.workspace_id)
            foreign_contact_id = new_entity_id()
            await conn.execute(
                text(
                    "INSERT INTO contact_entity "
                    "(id, account_entity_id, workspace_id, full_name, linkedin_url) "
                    "VALUES (:id, :account_id, :workspace_id, 'Foreign Contact', :linkedin)"
                ),
                {
                    "id": foreign_contact_id,
                    "account_id": foreign_account.id,
                    "workspace_id": request.workspace_id,
                    "linkedin": "https://linkedin.com/in/foreign-c1-contact",
                },
            )
            with pytest.raises(DBAPIError, match="Sumble professional claim lineage"):
                async with conn.begin_nested():
                    await insert_claim(
                        conn,
                        title_claim.model_copy(
                            update={"id": new_claim_id(), "entity_id": foreign_contact_id}
                        ),
                    )

            with pytest.raises(DBAPIError, match="append-only"):
                async with conn.begin_nested():
                    await conn.execute(
                        text(
                            "UPDATE claim SET provenance_kind='provider_modeled' WHERE id=:claim_id"
                        ),
                        {"claim_id": title_claim.id},
                    )

            replay = await discover_committee(
                conn,
                account_entity_id=request.account_id,
                run_id=RunId(request.project_run_id),
                workspace_id=request.workspace_id,
                sources=[source],
                gateway=gateway,
                role_model="s2c-role-model",
            )
            assert replay.claim_refs == committee.claim_refs
            assert len(transport.calls) == provider_call_count

            await tombstone_discovery_subject_artifacts(
                conn,
                workspace_id=request.workspace_id,
                subject_kind="account",
                subject_entity_id=request.account_id,
            )
            with pytest.raises(SumbleCommitteeSnapshotUnavailable, match="erased"):
                await source.find_candidates(account, limit=10)
            assert len(transport.calls) == provider_call_count
            with pytest.raises(DBAPIError, match="Sumble professional claim lineage"):
                async with conn.begin_nested():
                    await insert_claim(
                        conn,
                        title_claim.model_copy(update={"id": new_claim_id()}),
                    )

    run_async(scenario())


def test_s2c_unconfigured_account_is_an_empty_source(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            request = await _setup(conn, storage, workspace_id="ws-s2c-unconfigured")
            account = await get_account(conn, request.account_id)
            assert account is not None

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            source = SumbleCommitteeSource(
                operation_ids={}, storage=storage, conn_factory=same_connection
            )
            assert await source.find_candidates(account, limit=10) == ()

    run_async(scenario())


def test_s2c_combined_people_and_team_candidates_obey_directive_cap(tmp_path: Path) -> None:
    async def scenario() -> None:
        class _DisjointTeamTransport(_CommitteeTransport):
            def search_teams(self, body, *, maximum_credits):  # type: ignore[no-untyped-def]
                response, payload = super().search_teams(body, maximum_credits=maximum_credits)
                payload = deepcopy(payload)
                related = deepcopy(payload["teams"][0]["related_people"][0])
                related["person_id"] = 2002
                related["sumble_url"] = "https://sumble.com/l/person/taylor-rivera"
                related["attributes"]["name"] = "Taylor Rivera"
                related["attributes"]["linkedin_url"] = "https://www.linkedin.com/in/taylor-rivera"
                payload["teams"][0]["related_people"].append(related)
                return type(response).model_validate(payload), payload

            def poll_people(self, request_id, *, maximum_credits):  # type: ignore[no-untyped-def]
                response, payload = super().poll_people(request_id, maximum_credits=maximum_credits)
                if response.status.value != "succeeded":
                    return response, payload
                payload = deepcopy(payload)
                people_only = deepcopy(payload["people"][0])
                people_only["person_id"] = 1002
                people_only["sumble_url"] = "https://sumble.com/l/person/jordan-chen"
                people_only["attributes"]["name"] = "Jordan Chen"
                people_only["attributes"]["linkedin_url"] = (
                    "https://www.linkedin.com/in/jordan-chen"
                )
                payload["people"].append(people_only)
                payload["matched_count"] = 2
                payload["total"] = 2
                return type(response).model_validate(payload), payload

        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            request = await _setup(conn, storage, workspace_id="ws-s2c-candidate-cap")

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            transport = _DisjointTeamTransport()
            coordinator = SumbleCommitteeAcquisitionCoordinator(
                transport=transport,
                storage=storage,
                cents_per_credit=Decimal("0.5"),
                conn_factory=same_connection,
                poll_after_seconds=30,
            )
            preflight = compile_sumble_committee_preflight(request, cents_per_credit=Decimal("0.5"))
            pending = await coordinator.start(preflight)
            for _ in range(2):
                await conn.execute(
                    text(
                        "UPDATE committee_acquisition_operation SET next_poll_at=:past WHERE id=:id"
                    ),
                    {
                        "id": pending.operation.operation_id,
                        "past": datetime.now(UTC) - timedelta(seconds=1),
                    },
                )
                ready = await coordinator.start(preflight)
            assert ready.operation.state.value == "ready"

            account = await get_account(conn, request.account_id)
            assert account is not None
            source = SumbleCommitteeSource(
                operation_ids={request.account_id: ready.operation.operation_id},
                storage=storage,
                conn_factory=same_connection,
            )
            candidates = await source.find_candidates(account, limit=25)
            assert request.people_limit == 2
            assert len(candidates) == 2
            assert [candidate.source_person_id for candidate in candidates] == ["1001", "2002"]
            assert all(candidate.team_names for candidate in candidates)
            assert "1002" not in {candidate.source_person_id for candidate in candidates}

    run_async(scenario())
