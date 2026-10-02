"""``GET /frontend/v1/projects/{project_id}/discovery/current`` — the latest discovery run.

The Target accounts tab polls this while a run is live (spec 2026-09-12 §3): it is the only thing
the frontend reads to know a run is in flight, how far Exa has got, and when to stop polling.
ARV2's own tables are the only source (ruling 2026-09-09). ``found`` is the run's strict + relaxed
count as the driver last recorded it; ``verified`` counts candidates the verifier judged;
``shown`` counts the pass/partial/unclear ones — the rows the tab is about to list.

The two wire models live here rather than in ``contract_v1``: that module's ``V1Model`` base is
camelCase-on-the-wire (``alias_generator=to_camel``) and its parity test binds it to the accounts
Zod set, while this document is snake_case by spec — so it carries the same frozen/extra-forbid
contract discipline without the aliasing.
"""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text

from clue_api.arv2.discovery_store import VERIFIED_PREDICATE, DiscoveryStatus
from clue_api.frontend_read.app import WorkspaceDep
from clue_api.frontend_read.v1_shared import iso_utc
from clue_db import ConnFactory

__all__ = [
    "DiscoveryRunStatusResponseV1",
    "DiscoveryRunStatusV1",
    "register_discovery_status_route",
]


class DiscoveryRunStatusV1(BaseModel):
    """The project's latest discovery run, for the Target accounts tab's live poll (2026-09-12)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str
    status: DiscoveryStatus
    asked: int | None
    found: int
    verified: int
    shown: int
    started_at: str | None
    finished_at: str | None


class DiscoveryRunStatusResponseV1(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    data: DiscoveryRunStatusV1 | None


# ``verified`` counts the candidates the verifier actually JUDGED, which is what the predicate
# imported from the lane says — the tab, ``status.md`` and the agent's own read share that one
# definition, so the number on the screen is the number in the sentence.
_LATEST_RUN = text(
    f"""
    SELECT r.run_id, r.status, r.asked, r.found_strict, r.found_relaxed, r.started_at,
           r.finished_at,
           (SELECT count(*) FROM arv2_discovery_candidate c
             WHERE c.run_id = r.run_id AND {VERIFIED_PREDICATE}) AS verified,
           (SELECT count(*) FROM arv2_discovery_candidate c
             WHERE c.run_id = r.run_id
               AND c.disposition IN ('pass', 'partial', 'unclear')) AS shown
    FROM arv2_discovery_run r
    WHERE r.workspace_id = :workspace_id AND r.project_id = :project_id
    ORDER BY r.created_at DESC, r.run_id DESC
    LIMIT 1
    """
)


def register_discovery_status_route(router: APIRouter, *, conn_factory: ConnFactory) -> None:
    """Register the discovery-status poll on the workspace-scoped ``/frontend/v1`` router."""

    @router.get(
        "/projects/{project_id}/discovery/current", response_model=DiscoveryRunStatusResponseV1
    )
    async def get_discovery_status(
        project_id: str, workspace_id: WorkspaceDep
    ) -> DiscoveryRunStatusResponseV1:
        async with conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        _LATEST_RUN, {"workspace_id": workspace_id, "project_id": project_id}
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            return DiscoveryRunStatusResponseV1(data=None)
        started_at = row["started_at"]
        finished_at = row["finished_at"]
        return DiscoveryRunStatusResponseV1(
            data=DiscoveryRunStatusV1(
                run_id=str(row["run_id"]),
                # The column carries the store's own vocabulary, held to it by the
                # ``arv2_discovery_run_status`` CHECK; pydantic re-checks it here anyway.
                status=cast(DiscoveryStatus, row["status"]),
                asked=row["asked"],
                found=int(row["found_strict"] or 0) + int(row["found_relaxed"] or 0),
                verified=int(row["verified"]),
                shown=int(row["shown"]),
                started_at=iso_utc(started_at) if started_at is not None else None,
                finished_at=iso_utc(finished_at) if finished_at is not None else None,
            )
        )
