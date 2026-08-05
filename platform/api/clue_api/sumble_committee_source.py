"""S2C snapshot-backed Sumble adapter for the provider-neutral CommitteeSource seam."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from pydantic import JsonValue, TypeAdapter

from clue_core import (
    AccountEntity,
    CommitteeAcquisitionOperationId,
    CommitteeAcquisitionState,
    CommitteeSnapshotState,
    EntityId,
    UtcDatetime,
)
from clue_db import ConnFactory, transaction
from clue_research.durable import (
    enumerate_discovery_subject_artifacts,
    get_committee_acquisition_operation,
    list_committee_acquisition_snapshots,
)
from clue_research.profiling.committee import (
    CURRENT_LOCATION,
    CURRENT_TITLE,
    JOB_FUNCTION,
    JOB_LEVEL,
    ORGANIZATION_RELATIONSHIP,
    TEAM_MEMBERSHIP,
    CandidateFactProvenance,
    CandidateProfessionalFact,
    CommitteePersonCandidate,
)
from clue_research.resolvers.sumble.people import (
    PEOPLE_SOURCE_KEY,
    SumblePersonRecord,
    normalize_people,
)
from clue_research.resolvers.sumble.teams import (
    TEAMS_SOURCE_KEY,
    SumbleRelationshipBasis,
    SumbleTeamMemberRecord,
    SumbleTeamRecord,
    normalize_teams,
)
from clue_storage import StorageBackend, get_artifact

_JSON_OBJECT = TypeAdapter(dict[str, object])


@dataclass(frozen=True)
class _SnapshotLineage:
    source_key: str
    artifact_key: str
    operation_ref: str
    snapshot_ref: str
    request_ref: str
    observed_at: UtcDatetime | None


class SumbleCommitteeSourceError(RuntimeError):
    pass


class SumbleCommitteeSnapshotNotReady(SumbleCommitteeSourceError):
    pass


class SumbleCommitteeSnapshotUnavailable(SumbleCommitteeSourceError):
    pass


class SumbleCommitteeSource:
    """Read exact ready acquisitions; never dispatch a provider request from committee work."""

    source_key = PEOPLE_SOURCE_KEY
    tier = 1

    def __init__(
        self,
        *,
        operation_ids: Mapping[EntityId, CommitteeAcquisitionOperationId],
        storage: StorageBackend,
        conn_factory: ConnFactory = transaction,
        default_confidence: float = 0.9,
    ) -> None:
        if not 0 <= default_confidence <= 1:
            raise ValueError("Sumble committee default confidence must be between zero and one")
        self._operation_ids = dict(operation_ids)
        self._storage = storage
        self._conn_factory = conn_factory
        self._default_confidence = default_confidence

    async def find_candidates(
        self, account: AccountEntity, *, limit: int
    ) -> Sequence[CommitteePersonCandidate]:
        if not 1 <= limit <= 200:
            raise ValueError("Sumble committee candidate limit must be between 1 and 200")
        operation_id = self._operation_ids.get(account.id)
        if operation_id is None:
            return ()
        async with self._conn_factory() as conn:
            operation = await get_committee_acquisition_operation(
                conn,
                workspace_id=account.workspace_id,
                operation_id=operation_id,
            )
            if operation is None:
                raise SumbleCommitteeSnapshotUnavailable(
                    "configured Sumble committee operation does not exist in this workspace"
                )
            if (
                operation.request.account_id != account.id
                or operation.request.workspace_id != account.workspace_id
            ):
                raise SumbleCommitteeSnapshotUnavailable(
                    "Sumble committee operation is not locked to the requested account"
                )
            if operation.state is not CommitteeAcquisitionState.READY:
                raise SumbleCommitteeSnapshotNotReady(
                    f"Sumble committee operation is {operation.state.value}, not ready"
                )
            snapshots = await list_committee_acquisition_snapshots(
                conn,
                workspace_id=account.workspace_id,
                operation_id=operation.operation_id,
            )
            by_source = {item.source_key: item for item in snapshots}
            if set(by_source) != {TEAMS_SOURCE_KEY, PEOPLE_SOURCE_KEY} or any(
                item.state is not CommitteeSnapshotState.SUCCEEDED for item in snapshots
            ):
                raise SumbleCommitteeSnapshotNotReady(
                    "ready Sumble committee operation lacks terminal Teams and People snapshots"
                )
            subject_edges = await enumerate_discovery_subject_artifacts(
                conn,
                workspace_id=account.workspace_id,
                subject_kind="account",
                subject_entity_id=account.id,
            )
            live_keys = {edge.artifact_key for edge in subject_edges}
            response_keys: dict[str, str] = {}
            lineage_by_source: dict[str, _SnapshotLineage] = {}
            for source_key, snapshot in by_source.items():
                key = snapshot.response_artifact_key
                if key is None or key not in live_keys:
                    raise SumbleCommitteeSnapshotUnavailable(
                        "Sumble committee response is erased or no longer owned by the account"
                    )
                artifact = await get_artifact(conn, key)
                if artifact is None or artifact.erased_at is not None:
                    raise SumbleCommitteeSnapshotUnavailable(
                        "Sumble committee response artifact is unavailable"
                    )
                response_keys[source_key] = key
                lineage_by_source[source_key] = _SnapshotLineage(
                    source_key=source_key,
                    artifact_key=key,
                    operation_ref=f"committee-operation:{operation.operation_id}",
                    snapshot_ref=(
                        f"committee-snapshot:{operation.operation_id}:{source_key}:"
                        f"{snapshot.request_fingerprint}"
                    ),
                    request_ref=f"committee-request:{source_key}:{snapshot.request_fingerprint}",
                    observed_at=snapshot.updated_at or snapshot.created_at,
                )

        teams_payload = _decode(await self._storage.get(response_keys[TEAMS_SOURCE_KEY]))
        people_payload = _decode(await self._storage.get(response_keys[PEOPLE_SOURCE_KEY]))
        organization_id = int(operation.request.provider_organization_id)
        teams = normalize_teams(
            teams_payload,
            expected_organization_id=organization_id,
            max_people_per_team=operation.request.related_people_per_team,
            max_jobs_per_team=operation.request.jobs_per_team,
        )
        people = normalize_people(
            people_payload,
            expected_organization_id=organization_id,
        )
        # ``people_limit`` is compiled directly from the confirmed directive's
        # committee ``candidate_cap``.  The provider may return that many People
        # rows *and* additional related people nested under Teams, so applying only
        # the committee worker's generic per-source limit would exceed the user's
        # authorized total.  The stricter of the two limits governs the combined
        # snapshot-backed source.
        effective_limit = min(limit, operation.request.people_limit)
        memberships = _memberships(teams.teams)
        people_by_id = _people_by_provider_id(people.people)
        selected_person_ids = _select_provider_person_ids(
            people_ids=tuple(people_by_id),
            membership_ids=tuple(memberships),
            strong_ids=_strong_provider_person_ids(people_by_id, memberships),
            limit=effective_limit,
        )
        candidates: list[CommitteePersonCandidate] = []
        for provider_person_id in selected_person_ids:
            team_rows = memberships.get(provider_person_id, ())
            person = people_by_id.get(provider_person_id)
            if person is not None:
                candidates.append(
                    self._candidate(
                        provider_person_id=provider_person_id,
                        source_url=person.source_url,
                        linkedin_url=person.linkedin_url,
                        name=person.name,
                        title=person.job_title,
                        job_function=person.job_function,
                        job_level=person.job_level,
                        location=person.location,
                        country=person.country,
                        organization_id=person.current_employer_organization_id,
                        organization_name=person.current_employer_name,
                        role_start_date=person.current_role_start_date,
                        team_rows=team_rows,
                        direct_lineage=lineage_by_source[PEOPLE_SOURCE_KEY],
                        teams_lineage=lineage_by_source[TEAMS_SOURCE_KEY],
                        evidence_refs=(
                            response_keys[PEOPLE_SOURCE_KEY],
                            *((response_keys[TEAMS_SOURCE_KEY],) if team_rows else ()),
                        ),
                    )
                )
                continue
            member = team_rows[0][1]
            candidates.append(
                self._candidate(
                    provider_person_id=provider_person_id,
                    source_url=member.source_url,
                    linkedin_url=member.linkedin_url,
                    name=member.name,
                    title=member.job_title,
                    job_function=member.job_function,
                    job_level=member.job_level,
                    location=member.location,
                    country=member.country,
                    organization_id=member.current_employer_organization_id,
                    organization_name=member.current_employer_name,
                    role_start_date=member.current_role_start_date,
                    team_rows=team_rows,
                    direct_lineage=lineage_by_source[TEAMS_SOURCE_KEY],
                    teams_lineage=lineage_by_source[TEAMS_SOURCE_KEY],
                    evidence_refs=(response_keys[TEAMS_SOURCE_KEY],),
                )
            )
        return tuple(candidates)

    def _candidate(
        self,
        *,
        provider_person_id: int,
        source_url: str,
        linkedin_url: str | None,
        name: str | None,
        title: str | None,
        job_function: str | None,
        job_level: str | None,
        location: str | None,
        country: str | None,
        organization_id: int,
        organization_name: str | None,
        role_start_date: str | None,
        team_rows: tuple[tuple[SumbleTeamRecord, SumbleTeamMemberRecord], ...],
        direct_lineage: _SnapshotLineage,
        teams_lineage: _SnapshotLineage,
        evidence_refs: tuple[str, ...],
    ) -> CommitteePersonCandidate:
        team_names = tuple(dict.fromkeys(team.name for team, _member in team_rows))
        relationships = tuple(
            dict.fromkeys(member.relationship_basis.value for _team, member in team_rows)
        )
        confidences = tuple(
            member.relationship_confidence
            for _team, member in team_rows
            if member.relationship_confidence is not None
        )
        confidence = max(confidences, default=self._default_confidence)
        signal_parts = ["provider_returned_current_employee"]
        if team_names:
            signal_parts.append(f"teams={','.join(team_names)}")
            signal_parts.append(
                f"relationship={SumbleRelationshipBasis.PROVIDER_INFERRED_TEAM_MEMBERSHIP.value}"
            )
        geo: dict[str, JsonValue] = {
            key: value
            for key, value in (("location", location), ("country", country))
            if value is not None
        }
        professional_facts = self._professional_facts(
            person_source_url=source_url,
            title=title,
            job_function=job_function,
            job_level=job_level,
            location=location,
            country=country,
            organization_id=organization_id,
            organization_name=organization_name,
            role_start_date=role_start_date,
            team_rows=team_rows,
            direct_lineage=direct_lineage,
            teams_lineage=teams_lineage,
            direct_confidence=self._default_confidence,
        )
        return CommitteePersonCandidate(
            source_key=self.source_key,
            source_person_id=str(provider_person_id),
            linkedin_url=linkedin_url,
            full_name=name,
            title=title,
            job_function=job_function,
            job_level=job_level,
            team_names=team_names,
            relationship_labels=relationships,
            geo=geo or None,
            source_url=source_url,
            matched_signal="; ".join(signal_parts),
            evidence_refs=tuple(dict.fromkeys(evidence_refs)),
            professional_facts=professional_facts,
            discovery_confidence=confidence,
            cost_cents=Decimal(0),
        )

    def _professional_facts(
        self,
        *,
        person_source_url: str,
        title: str | None,
        job_function: str | None,
        job_level: str | None,
        location: str | None,
        country: str | None,
        organization_id: int,
        organization_name: str | None,
        role_start_date: str | None,
        team_rows: tuple[tuple[SumbleTeamRecord, SumbleTeamMemberRecord], ...],
        direct_lineage: _SnapshotLineage,
        teams_lineage: _SnapshotLineage,
        direct_confidence: float,
    ) -> tuple[CandidateProfessionalFact, ...]:
        facts: list[CandidateProfessionalFact] = []

        def returned(field_key: str, value: JsonValue, label: str) -> None:
            facts.append(
                CandidateProfessionalFact(
                    field_key=field_key,
                    value_json=value,
                    provenance_kind=CandidateFactProvenance.PROVIDER_RETURNED,
                    source_key=direct_lineage.source_key,
                    source_tier=1,
                    source_url=person_source_url,
                    evidence_span=f"provider_returned {label}: {value}",
                    artifact_key=direct_lineage.artifact_key,
                    source_operation_ref=direct_lineage.operation_ref,
                    source_snapshot_ref=direct_lineage.snapshot_ref,
                    source_request_ref=direct_lineage.request_ref,
                    observed_at=direct_lineage.observed_at,
                    confidence=direct_confidence,
                )
            )

        for field_key, value, label in (
            (CURRENT_TITLE, title, "job_title"),
            (JOB_FUNCTION, job_function, "job_function"),
            (JOB_LEVEL, job_level, "job_level"),
        ):
            if value is not None and value.strip():
                returned(field_key, value, label)

        location_value: dict[str, JsonValue] = {
            key: value
            for key, value in (("raw", location), ("country", country))
            if value is not None and value.strip()
        }
        if location_value:
            returned(CURRENT_LOCATION, location_value, "current_location")

        relationship: dict[str, JsonValue] = {
            "relationship": "current_employee",
            "basis": "provider_returned_current_employer",
            "organization_id": organization_id,
        }
        if organization_name is not None and organization_name.strip():
            relationship["organization_name"] = organization_name
        if role_start_date is not None and role_start_date.strip():
            relationship["role_start_date"] = role_start_date
        returned(
            ORGANIZATION_RELATIONSHIP,
            relationship,
            "current_employer",
        )

        if team_rows:
            memberships: list[JsonValue] = []
            confidences: list[float] = []
            for team, member in team_rows:
                membership: dict[str, JsonValue] = {
                    "provider_team_id": team.provider_team_id,
                    "name": team.name,
                    "organization_id": team.organization_id,
                    "relationship_basis": member.relationship_basis.value,
                    "source_url": team.source_url,
                }
                if member.relationship_confidence is not None:
                    membership["confidence"] = member.relationship_confidence
                    confidences.append(member.relationship_confidence)
                memberships.append(membership)
            facts.append(
                CandidateProfessionalFact(
                    field_key=TEAM_MEMBERSHIP,
                    value_json=memberships,
                    provenance_kind=CandidateFactProvenance.PROVIDER_MODELED,
                    source_key=teams_lineage.source_key,
                    source_tier=1,
                    source_url=team_rows[0][0].source_url,
                    evidence_span=(
                        "provider_modeled team_membership: "
                        + ", ".join(team.name for team, _member in team_rows)
                    ),
                    artifact_key=teams_lineage.artifact_key,
                    source_operation_ref=teams_lineage.operation_ref,
                    source_snapshot_ref=teams_lineage.snapshot_ref,
                    source_request_ref=teams_lineage.request_ref,
                    observed_at=teams_lineage.observed_at,
                    confidence=max(confidences, default=direct_confidence),
                )
            )
        return tuple(facts)


def _memberships(
    teams: tuple[SumbleTeamRecord, ...],
) -> dict[int, tuple[tuple[SumbleTeamRecord, SumbleTeamMemberRecord], ...]]:
    grouped: dict[int, list[tuple[SumbleTeamRecord, SumbleTeamMemberRecord]]] = {}
    for team in teams:
        for member in team.related_people:
            grouped.setdefault(member.provider_person_id, []).append((team, member))
    return {key: tuple(value) for key, value in grouped.items()}


def _people_by_provider_id(
    people: tuple[SumblePersonRecord, ...],
) -> dict[int, SumblePersonRecord]:
    """Preserve provider order while refusing conflicting duplicate person identities."""

    by_id: dict[int, SumblePersonRecord] = {}
    for person in people:
        provider_person_id = person.provider_person_id
        existing = by_id.get(provider_person_id)
        if existing is not None and existing != person:
            raise SumbleCommitteeSnapshotUnavailable(
                "Sumble People snapshot repeats one provider person id with conflicting content"
            )
        by_id.setdefault(provider_person_id, person)
    return by_id


def _select_provider_person_ids(
    *,
    people_ids: tuple[int, ...],
    membership_ids: tuple[int, ...],
    strong_ids: frozenset[int],
    limit: int,
) -> tuple[int, ...]:
    """Bound the union without systematically discarding the paid organization graph.

    Strong identities are selected before weak rows that the admission gate will drop. Within each
    strength band, people present in both snapshots are richest and come first. Remaining capacity
    alternates Teams-only and People-only identities, starting with Teams, while retaining provider
    order inside each class. This guarantees Teams representation whenever the graph contains a
    strong candidate and capacity remains; a full People page can no longer erase every Teams-only
    row.
    """

    membership_set = set(membership_ids)
    people_set = set(people_ids)
    overlap = tuple(person_id for person_id in people_ids if person_id in membership_set)
    teams_only = tuple(person_id for person_id in membership_ids if person_id not in people_set)
    people_only = tuple(person_id for person_id in people_ids if person_id not in membership_set)
    selected: list[int] = []
    for strong in (True, False):
        for person_id in overlap:
            if (person_id in strong_ids) is strong and len(selected) < limit:
                selected.append(person_id)
        teams_band = [person_id for person_id in teams_only if (person_id in strong_ids) is strong]
        people_band = [
            person_id for person_id in people_only if (person_id in strong_ids) is strong
        ]
        while len(selected) < limit and (teams_band or people_band):
            if teams_band and len(selected) < limit:
                selected.append(teams_band.pop(0))
            if people_band and len(selected) < limit:
                selected.append(people_band.pop(0))
        if len(selected) >= limit:
            break
    return tuple(selected)


def _strong_provider_person_ids(
    people: Mapping[int, SumblePersonRecord],
    memberships: Mapping[int, tuple[tuple[SumbleTeamRecord, SumbleTeamMemberRecord], ...]],
) -> frozenset[int]:
    strong = {
        person_id
        for person_id, person in people.items()
        if person.linkedin_url is not None and person.linkedin_url.strip()
    }
    strong.update(
        person_id
        for person_id, rows in memberships.items()
        if any(
            member.linkedin_url is not None and member.linkedin_url.strip()
            for _team, member in rows
        )
    )
    return frozenset(strong)


def _decode(body: bytes) -> dict[str, object]:
    try:
        return _JSON_OBJECT.validate_python(json.loads(body))
    except Exception as exc:
        raise SumbleCommitteeSnapshotUnavailable(
            "Sumble committee response artifact is not a JSON object"
        ) from exc


__all__ = [
    "SumbleCommitteeSnapshotNotReady",
    "SumbleCommitteeSnapshotUnavailable",
    "SumbleCommitteeSource",
    "SumbleCommitteeSourceError",
]
