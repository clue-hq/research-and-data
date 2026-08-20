"""The provider-returned truth floor, end to end on real Postgres (founder ruling 2026-08-20).

The live v9 execution (job ``cd6a779e``, operation ``8500325f``) fetched seven real, current
Millennium Physician Group employees and admitted one. Four of the six it did not admit were
routed to review for a single reason: their provider facts arrived through Sumble's **Teams**
organization map rather than the People page, so they carried no ``sumble_people`` fact and the
admission ladder's grounding filter could not see them.

Founder ruling: a candidate the provider returned is admissible ground, People rows and Teams rows
alike. This module proves that floor where it actually has to hold — not only in the admission
predicate, but through the durable claim writes and the committee projection, which previously
demanded direct People facts from every admitted member and would have suspended the job.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.account_entity_research import AccountBuyingUnitScope
from clue_api.entity_research_tools import ProviderObservationDisposition
from clue_api.sumble_committee_acquisition import (
    SumbleCommitteeAcquisitionCoordinator,
    compile_sumble_committee_preflight,
)
from clue_api.sumble_committee_source import SumbleCommitteeSource
from clue_api.sumble_entity_research_tools import (
    SumbleCommitteeSemanticResearchAction,
    SumbleEntityResearchLineageReader,
)
from clue_core import RunId
from clue_core.entity_research import (
    ResearchClaimDelta,
    ResearchFieldOutcome,
    ResearchSubjectType,
)
from clue_research.identity import get_account
from clue_research.resolvers.sumble.people import PEOPLE_SOURCE_KEY
from clue_research.resolvers.sumble.teams import TEAMS_SOURCE_KEY, SumbleTeamsResponse
from clue_storage import FsStorage
from tests.api.test_account_entity_research_r5_db import _committee_tool_request
from tests.api.test_sumble_committee_acquisition_s2b import _CommitteeTransport, _payload
from tests.api.test_sumble_committee_acquisition_s2b import _setup as _committee_setup
from tests.db.conftest import run_async
from tests.durable.conftest import rollback_conn
from tests.profiling.conftest import FakeGateway, seed_packs

pytestmark = pytest.mark.usefixtures("require_profiling_db")

# The provider person id that exists ONLY inside the Teams organization map — the live v9
# ambiguous class (Brian Fox, Tesha Simpson, Truly Peterson MD, Dionne Leverette).
_TEAMS_ONLY_PERSON_ID = 2002
_ORGANIZATION_ID = 1726684


class _ForbiddenGateway(FakeGateway):
    """An ``LLMGateway`` that makes the retirement of the role leaf call structural, not counted.

    Founder ruling 2026-08-20: role inference belongs to the per-account agent, and the external
    ``roles.py`` leaf call retires from this path. Asserting ``complete_calls == 0`` proves it did
    not happen this time; a gateway that detonates proves the path has no branch that could.
    """

    def complete(self, *, model: str, messages: Any, **opts: object) -> Any:
        raise AssertionError(
            "committee discovery must judge no roles: the account agent owns role inference "
            f"(a completion was requested from {model!r})"
        )


class _TeamsOnlyMemberTransport(_CommitteeTransport):
    """The recorded s2b double, with one extra related person the People page never returns.

    Everything else is byte-identical to the recorded fixtures: the same organization, the same
    single team, the same People page. The only difference is the shape the live run actually hit
    — an organization-map person with no People row of their own.
    """

    def search_teams(
        self, body: Mapping[str, Any], *, maximum_credits: int
    ) -> tuple[SumbleTeamsResponse, Any]:
        del body
        assert maximum_credits == 12
        self.calls.append("teams")
        payload = _payload("teams_succeeded.json")
        payload["id"] = self._teams_operation_id
        team = payload["teams"][0]
        seed = team["related_people"][0]
        extra = deepcopy(seed)
        extra["person_id"] = _TEAMS_ONLY_PERSON_ID
        extra["sumble_url"] = "https://sumble.com/l/person/dionne-teams-only"
        extra["attributes"] = {
            **seed["attributes"],
            "name": "Dionne Leverette",
            "linkedin_url": "https://www.linkedin.com/in/dionne-leverette-teams-only",
            "job_title": "SVP Human Resources",
            "job_function": "Human Resources",
            "job_level": "SVP",
            "current_employer": {
                "organization_id": _ORGANIZATION_ID,
                "name": "Insight Health",
                "start_date": "2021-09",
            },
        }
        team["related_people"] = [seed, extra]
        return SumbleTeamsResponse.model_validate(payload), payload


def _scope(
    account_id: UUID, *, match_policy: Literal["company_wide", "same_office_strict"]
) -> AccountBuyingUnitScope:
    """The buying unit the agent declares: an organization-wide unit with advisory functions."""

    return AccountBuyingUnitScope(
        scope_id=UUID("11111111-2222-4333-8444-555555555555"),
        account_entity_id=account_id,
        office_label="Insight Health — organization-wide buying unit",
        locality="New York",
        target_functions=("Operations",),
        evidence_refs=("research-evidence:3f4a5b6c-7d8e-4f90-a1b2-c3d4e5f6a7b8",),
        match_policy=match_policy,
    )


async def _ready_operation(
    conn: AsyncConnection,
    coordinator: SumbleCommitteeAcquisitionCoordinator,
    preflight: Any,
) -> Any:
    ready = await coordinator.start(preflight)
    for _ in range(2):  # the People submission settles on the polling path
        await conn.execute(
            text("UPDATE committee_acquisition_operation SET next_poll_at=:past WHERE id=:id"),
            {
                "id": ready.operation.operation_id,
                "past": datetime.now(UTC) - timedelta(seconds=1),
            },
        )
        ready = await coordinator.start(preflight)
    assert ready.operation.state.value == "ready"
    return ready


async def _journal_reservation(conn: AsyncConnection, provider_operation: Any) -> None:
    """In production the engine journals the reservation through ``before_dispatch`` first."""

    await conn.execute(
        text(
            """
            INSERT INTO entity_research_provider_operation
                (operation_ref, provider_kind, workspace_id, project_id, project_run_id,
                 subject_type, target_entity_id, parent_account_id, source_key,
                 field_keys, request_artifact_ref, reserved_at, dispatched_at)
            VALUES
                (:operation_ref, :provider_kind, :workspace_id, :project_id, :project_run_id,
                 :subject_type, :target_entity_id, :parent_account_id, :source_key,
                 :field_keys, :request_artifact_ref, :reserved_at, :dispatched_at)
            """
        ),
        {
            "operation_ref": provider_operation.operation_ref,
            "provider_kind": provider_operation.provider_kind,
            "workspace_id": provider_operation.workspace_id,
            "project_id": provider_operation.project_id,
            "project_run_id": provider_operation.project_run_id,
            "subject_type": provider_operation.subject_type.value,
            "target_entity_id": provider_operation.target_entity_id,
            "parent_account_id": provider_operation.parent_account_id,
            "source_key": provider_operation.source_key,
            "field_keys": list(provider_operation.field_keys),
            "request_artifact_ref": provider_operation.request_artifact_ref,
            "reserved_at": provider_operation.reserved_at,
            "dispatched_at": provider_operation.dispatched_at,
        },
    )


def test_a_teams_only_candidate_is_admitted_claimed_and_projected(tmp_path: Path) -> None:
    """A provider-returned Teams-map person reaches the agent with their own evidence.

    Three things had to hold together, and only the first was ever true:

    1. ``_office_candidates`` selects them (the ``sumble_people`` grounding filter retires);
    2. their professional facts land as durable ``sumble_teams`` claims (the M8C C1 lineage
       trigger and shape CHECK already accept a Teams-stamped professional claim);
    3. the committee projection carries those facts to the agent, instead of refusing the member
       for lacking direct People facts — which is what a live run would have hit.

    Zero gateway calls happen anywhere along that path: role judgment is the account agent's.
    """

    async def scenario() -> None:
        storage = FsStorage(tmp_path / "artifacts")
        async with rollback_conn(seed_pack=True) as conn:
            durable = await _committee_setup(conn, storage, workspace_id="ws-provider-floor")

            @asynccontextmanager
            async def same_connection() -> AsyncIterator[AsyncConnection]:
                yield conn

            coordinator = SumbleCommitteeAcquisitionCoordinator(
                transport=_TeamsOnlyMemberTransport(),
                storage=storage,
                cents_per_credit=Decimal("0.5"),
                conn_factory=same_connection,
                poll_after_seconds=30,
            )
            preflight = compile_sumble_committee_preflight(durable, cents_per_credit=Decimal("0.5"))
            ready = await _ready_operation(conn, coordinator, preflight)

            source = SumbleCommitteeSource(
                operation_ids={durable.account_id: ready.operation.operation_id},
                storage=storage,
                conn_factory=same_connection,
            )
            account = await get_account(conn, durable.account_id)
            assert account is not None
            candidates = tuple(await source.find_candidates(account, limit=durable.people_limit))

            # The paid operation returned two people: one on both pages, one only in the org map.
            assert len(candidates) == 2
            people_path, teams_only = candidates
            assert people_path.source_person_id == "1001"
            assert teams_only.source_person_id == str(_TEAMS_ONLY_PERSON_ID)
            assert {fact.source_key for fact in people_path.professional_facts} == {
                PEOPLE_SOURCE_KEY,
                TEAMS_SOURCE_KEY,
            }
            # This is the whole live defect in one assertion: not one People fact anywhere.
            assert {fact.source_key for fact in teams_only.professional_facts} == {TEAMS_SOURCE_KEY}

            # (1) admission — the provider-returned floor admits both.
            scope = _scope(UUID(str(durable.account_id)), match_policy="company_wide")
            selected, excluded, ambiguous = (
                SumbleCommitteeSemanticResearchAction._office_candidates(candidates, scope=scope)
            )
            assert selected == candidates
            assert (excluded, ambiguous) == (0, 0)

            await seed_packs(conn)
            gateway = _ForbiddenGateway()
            action = SumbleCommitteeSemanticResearchAction(
                preflight=preflight,
                coordinator=coordinator,
                storage=storage,
                conn_factory=same_connection,
                gateway=gateway,
                role_model="provider-floor-role-model-must-not-be-called",
            )
            committee = await action._discover_committee_members(
                conn,
                account_entity_id=durable.account_id,
                run_id=RunId(UUID(str(durable.project_run_id))),
                workspace_id=durable.workspace_id,
                selected=selected,
                budget_cap_cents=durable.money_budget_cap_cents,
            )

            # (2) durable claims — both members, no role work, no model consulted.
            assert committee.admitted == 2
            assert gateway.complete_calls == 0  # and a call would have detonated the double
            assert all(member.professional_claim_ids for member in committee.members)
            teams_member = committee.members[1]
            member_sources = {
                str(value)
                for value in (
                    (
                        await conn.execute(
                            text("SELECT DISTINCT source_key FROM claim WHERE id=ANY(:ids)"),
                            {
                                "ids": [
                                    UUID(str(value))
                                    for value in teams_member.professional_claim_ids
                                ]
                            },
                        )
                    )
                    .scalars()
                    .all()
                )
            }
            assert member_sources == {TEAMS_SOURCE_KEY}

            # (3) projection — the member reaches the agent carrying their own evidence.
            request = _committee_tool_request(durable)
            provider_operation = action._committee_descriptor(
                ready.operation,
                disposition=ProviderObservationDisposition.CAUSED,
                include_dispatch=True,
            )
            await _journal_reservation(conn, provider_operation)
            _snapshot_ref, subjects = await action._persist_committee_projection(
                request=request,
                operation=ready.operation,
                provider_operation=provider_operation,
                committee=committee,
                excluded=excluded,
                ambiguous=ambiguous,
            )

            assert len(subjects) == 2
            by_contact = {
                subject.target_entity_id: subject
                for subject in subjects
                if subject.subject_type is ResearchSubjectType.CONTACT
            }
            projected = by_contact[UUID(str(teams_member.contact_entity_id))]
            assert projected.fields
            assert {field.field_key for field in projected.fields} >= {
                "contact.current_title",
                "contact.job_function",
                "contact.organization_relationship",
            }
            assert all(
                field.outcome is ResearchFieldOutcome.FOUND
                and field.claim_delta is ResearchClaimDelta.ACCEPTED
                and field.evidence
                for field in projected.fields
            )
            # Every projected span is verbatim inside the exact retained Teams artifact.
            for field in projected.fields:
                for item in field.evidence:
                    assert item.source_key == TEAMS_SOURCE_KEY
                    retained = await storage.get(item.artifact_ref.removeprefix("artifact:"))
                    assert item.evidence_span in retained.decode("utf-8")

            # The widening is bounded by the provider's own ledger: exactly the source keys of
            # this operation's succeeded component snapshots, never an open door.
            lineage = await SumbleEntityResearchLineageReader(
                provider_kind="sumble_committee", conn_factory=same_connection
            ).load(
                request=request,
                operation=provider_operation,
                snapshot_ref=_snapshot_ref,
            )
            assert lineage.claim_source_keys == (PEOPLE_SOURCE_KEY, TEAMS_SOURCE_KEY)
            assert all(
                ref.startswith(f"committee-snapshot:{ready.operation.operation_id}:")
                for ref in lineage.claim_source_snapshot_refs
            )

            # The projection's ledger row records an all-admitted board.
            metadata = (
                await conn.execute(
                    text(
                        "SELECT metadata_json FROM entity_research_sumble_projection "
                        "WHERE provider_operation_ref=:operation_ref"
                    ),
                    {"operation_ref": provider_operation.operation_ref},
                )
            ).scalar_one()
            assert json.loads(json.dumps(metadata)) == {
                "excluded_candidate_count": 0,
                "ambiguous_candidate_count": 0,
            }

    run_async(scenario())
