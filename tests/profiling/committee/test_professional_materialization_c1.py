"""M8C C1 snapshot-backed professional fact materialization acceptance."""

from __future__ import annotations

from uuid import UUID

import pytest
from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    ClaimProvenanceKind,
    ExtractionMethod,
    IdentityBinding,
    ResearchMode,
    RunId,
    UseClass,
)
from clue_research.claimstore import WorkspaceScope, claims_for
from clue_research.profiling.committee import (
    CURRENT_TITLE,
    ROLE_ON_COMMITTEE,
    TEAM_MEMBERSHIP,
    CandidateFactProvenance,
    CandidateProfessionalFact,
    ProfessionalFactReplayConflict,
    discover_committee,
)
from clue_storage import artifact_key, content_address, record_artifact

from ..conftest import (
    FakeCommitteeSource,
    FakeGateway,
    insert_test_account,
    make_candidate,
    rollback_conn,
    run_async,
    seed_packs,
)

_RUN = RunId(UUID("28c10000-0000-4000-8000-000000000001"))
_WORKSPACE = "workspace-m8c-c1"
_ARTIFACT_BYTES = {
    "fixture_people": b"c1 immutable people response",
    "fixture_teams": b"c1 immutable teams response",
}


async def _seed_artifacts(conn: AsyncConnection) -> None:
    for source_key, body in _ARTIFACT_BYTES.items():
        digest = content_address(body)
        await record_artifact(
            conn,
            storage_key=artifact_key(_WORKSPACE, digest),
            workspace_id=_WORKSPACE,
            content_sha256=digest,
            media_type="application/json",
            size_bytes=len(body),
            source_key=source_key,
            source_url=f"https://sumble.example/{source_key}",
        )


def _fact(
    field_key: str,
    value: JsonValue,
    *,
    source_key: str = "fixture_people",
    kind: CandidateFactProvenance = CandidateFactProvenance.PROVIDER_RETURNED,
) -> CandidateProfessionalFact:
    return CandidateProfessionalFact(
        field_key=field_key,
        value_json=value,
        provenance_kind=kind,
        source_key=source_key,
        source_tier=1,
        source_url=f"https://sumble.example/{source_key}/person-1",
        evidence_span=f"{kind.value} {field_key}: {value}",
        artifact_key=artifact_key(
            _WORKSPACE,
            content_address(_ARTIFACT_BYTES[source_key]),
        ),
        source_operation_ref="committee-operation:operation-1",
        source_snapshot_ref=f"committee-snapshot:operation-1:{source_key}:fingerprint-1",
        source_request_ref=f"committee-request:{source_key}:fingerprint-1",
        confidence=0.93,
    )


def test_snapshot_facts_replay_once_and_same_name_contacts_cannot_cross_write(
    require_profiling_db: None,
) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await seed_packs(conn)
            await _seed_artifacts(conn)
            account = await insert_test_account(conn, workspace_id=_WORKSPACE)
            first_facts = (
                _fact(CURRENT_TITLE, "VP of Operations"),
                _fact(
                    TEAM_MEMBERSHIP,
                    [
                        {
                            "provider_team_id": 501,
                            "name": "Patient Access Operations",
                            "organization_id": 1726684,
                            "relationship_basis": "provider_inferred_team_membership",
                            "confidence": 0.92,
                            "source_url": "https://sumble.example/team/501",
                        }
                    ],
                    source_key="fixture_teams",
                    kind=CandidateFactProvenance.PROVIDER_MODELED,
                ),
            )
            candidates = [
                make_candidate(
                    source_key="sumble_people",
                    source_person_id="1001",
                    linkedin_url="https://linkedin.com/in/alex-one",
                    full_name="Alex Morgan",
                    title="VP of Operations",
                    source_url="https://sumble.example/person/1001",
                    professional_facts=first_facts,
                ),
                make_candidate(
                    source_key="sumble_people",
                    source_person_id="1002",
                    linkedin_url="https://linkedin.com/in/alex-two",
                    full_name="Alex Morgan",
                    title="Director of Administration",
                    source_url="https://sumble.example/person/1002",
                    professional_facts=(_fact(CURRENT_TITLE, "Director of Administration"),),
                ),
            ]
            source = FakeCommitteeSource(source_key="sumble_people", tier=1, candidates=candidates)
            gateway = FakeGateway()
            first = await discover_committee(
                conn,
                account_entity_id=account.id,
                run_id=_RUN,
                workspace_id=_WORKSPACE,
                sources=[source],
                gateway=gateway,
                role_model="role-model",
            )
            replay = await discover_committee(
                conn,
                account_entity_id=account.id,
                run_id=_RUN,
                workspace_id=_WORKSPACE,
                sources=[source],
                gateway=gateway,
                role_model="role-model",
            )

            assert len(first.members) == 2
            assert first.members[0].contact_entity_id != first.members[1].contact_entity_id
            assert first.claim_refs == replay.claim_refs
            assert first.cost_cents == replay.cost_cents == 0

            scope = WorkspaceScope.for_workspace(_WORKSPACE)
            titles = []
            for member in first.members:
                title_claims = await claims_for(
                    conn, member.contact_entity_id, CURRENT_TITLE, scope=scope
                )
                assert len(title_claims) == 1
                titles.append(title_claims[0].value_json)
                claim = title_claims[0]
                assert claim.id in member.professional_claim_ids
                assert claim.extraction_method is ExtractionMethod.API
                assert claim.research_mode is ResearchMode.COMMITTEE_DISCOVERY
                assert claim.identity_binding is IdentityBinding.STRONG
                assert claim.use_class is UseClass.PROFESSIONAL_PUBLIC
                assert claim.source_key == "fixture_people"
                assert claim.provenance_kind is ClaimProvenanceKind.PROVIDER_RETURNED
                assert claim.source_url and claim.evidence_span and claim.artifact_key
                assert claim.source_operation_ref and claim.source_snapshot_ref
                assert claim.source_request_ref
            assert titles == ["VP of Operations", "Director of Administration"]

            team_claims = await claims_for(
                conn, first.members[0].contact_entity_id, TEAM_MEMBERSHIP, scope=scope
            )
            assert len(team_claims) == 1
            assert team_claims[0].source_key == "fixture_teams"
            assert team_claims[0].provenance_kind is ClaimProvenanceKind.PROVIDER_MODELED
            assert team_claims[0].evidence_span is not None
            assert team_claims[0].evidence_span.startswith("provider_modeled")

            role_claim = (
                await claims_for(
                    conn,
                    first.members[0].contact_entity_id,
                    ROLE_ON_COMMITTEE,
                    scope=scope,
                )
            )[0]
            assert role_claim.extraction_method is ExtractionMethod.LLM_SYNTHESIS
            assert role_claim.source_key is None
            assert role_claim.provenance_kind is ClaimProvenanceKind.PLATFORM_INFERRED
            assert team_claims[0].extraction_method is ExtractionMethod.API

    run_async(scenario())


def test_same_snapshot_identity_cannot_replay_a_changed_value(
    require_profiling_db: None,
) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await seed_packs(conn)
            await _seed_artifacts(conn)
            account = await insert_test_account(conn, workspace_id=_WORKSPACE)
            source = FakeCommitteeSource(
                source_key="sumble_people",
                tier=1,
                candidates=[
                    make_candidate(
                        linkedin_url="https://linkedin.com/in/replay-person",
                        full_name="Replay Person",
                        title="VP Operations",
                        source_url="https://sumble.example/person/replay",
                        professional_facts=(_fact(CURRENT_TITLE, "VP Operations"),),
                    )
                ],
            )
            await discover_committee(
                conn,
                account_entity_id=account.id,
                run_id=_RUN,
                workspace_id=_WORKSPACE,
                sources=[source],
                gateway=FakeGateway(),
                role_model="role-model",
            )
            source.candidates[0] = source.candidates[0].model_copy(
                update={"professional_facts": (_fact(CURRENT_TITLE, "Chief of Staff"),)}
            )
            with pytest.raises(ProfessionalFactReplayConflict, match="snapshot replay changed"):
                await discover_committee(
                    conn,
                    account_entity_id=account.id,
                    run_id=_RUN,
                    workspace_id=_WORKSPACE,
                    sources=[source],
                    gateway=FakeGateway(),
                    role_model="role-model",
                )

    run_async(scenario())
