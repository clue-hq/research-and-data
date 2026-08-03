"""S2C snapshot-backed Sumble adapter for the provider-neutral CommitteeSource seam."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from decimal import Decimal

from pydantic import JsonValue, TypeAdapter

from clue_core import (
    AccountEntity,
    CommitteeAcquisitionOperationId,
    CommitteeAcquisitionState,
    CommitteeSnapshotState,
    EntityId,
)
from clue_db import ConnFactory, transaction
from clue_research.durable import (
    enumerate_discovery_subject_artifacts,
    get_committee_acquisition_operation,
    list_committee_acquisition_snapshots,
)
from clue_research.profiling.committee import CommitteePersonCandidate
from clue_research.resolvers.sumble.people import PEOPLE_SOURCE_KEY, normalize_people
from clue_research.resolvers.sumble.teams import (
    TEAMS_SOURCE_KEY,
    SumbleRelationshipBasis,
    SumbleTeamMemberRecord,
    SumbleTeamRecord,
    normalize_teams,
)
from clue_storage import StorageBackend, get_artifact

_JSON_OBJECT = TypeAdapter(dict[str, object])


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
        memberships = _memberships(teams.teams)
        candidates: list[CommitteePersonCandidate] = []
        seen_provider_ids: set[int] = set()
        for person in people.people:
            team_rows = memberships.get(person.provider_person_id, ())
            candidates.append(
                self._candidate(
                    provider_person_id=person.provider_person_id,
                    source_url=person.source_url,
                    linkedin_url=person.linkedin_url,
                    name=person.name,
                    title=person.job_title,
                    job_function=person.job_function,
                    job_level=person.job_level,
                    location=person.location,
                    country=person.country,
                    team_rows=team_rows,
                    evidence_refs=(
                        response_keys[PEOPLE_SOURCE_KEY],
                        *((response_keys[TEAMS_SOURCE_KEY],) if team_rows else ()),
                    ),
                )
            )
            seen_provider_ids.add(person.provider_person_id)
        for provider_person_id, team_rows in memberships.items():
            if provider_person_id in seen_provider_ids:
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
                    team_rows=team_rows,
                    evidence_refs=(response_keys[TEAMS_SOURCE_KEY],),
                )
            )
        return tuple(candidates[:limit])

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
        team_rows: tuple[tuple[SumbleTeamRecord, SumbleTeamMemberRecord], ...],
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
            discovery_confidence=confidence,
            cost_cents=Decimal(0),
        )


def _memberships(
    teams: tuple[SumbleTeamRecord, ...],
) -> dict[int, tuple[tuple[SumbleTeamRecord, SumbleTeamMemberRecord], ...]]:
    grouped: dict[int, list[tuple[SumbleTeamRecord, SumbleTeamMemberRecord]]] = {}
    for team in teams:
        for member in team.related_people:
            grouped.setdefault(member.provider_person_id, []).append((team, member))
    return {key: tuple(value) for key, value in grouped.items()}


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
