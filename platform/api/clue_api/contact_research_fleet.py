"""M8D R8 exact-set contact-run aggregation over the shared R2 fleet substrate."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Self
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import serialize_value_json
from clue_core.entity_research import (
    ResearchFinalizationOutcome,
    ResearchJobState,
    ResearchRunKind,
    ResearchRunLifecycleContract,
    ResearchSubjectType,
)
from clue_fleet import EntityResearchJobError, EntityResearchJobWorkHandler, EntityResearchRunState
from clue_fleet.enums import FleetTaskKind
from clue_fleet.work_worker import WorkContext, WorkResult

ConnFactory = Callable[[], AbstractAsyncContextManager[AsyncConnection]]
NonEmptyStr = Annotated[str, Field(min_length=1)]
_RETURN_NAMESPACE = uuid5(NAMESPACE_URL, "clue:m8d:r8:contact-fleet-return")


class ContactResearchFleetError(RuntimeError):
    pass


class ContactResearchFleetState(StrEnum):
    ACTIVE = "active"
    WAITING_EXTERNAL = "waiting_external"
    TERMINAL = "terminal"


class ContactResearchJobSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    job_id: UUID
    contact_entity_id: UUID
    parent_account_id: UUID
    state: ResearchJobState
    finalization_outcome: ResearchFinalizationOutcome | None
    finalization_receipt_ref: str | None
    coverage_ref: str | None
    completed_field_keys: tuple[str, ...]
    unresolved_field_keys: tuple[str, ...]
    result_refs: tuple[str, ...]
    facet_refs: tuple[str, ...]
    channel_operation_refs: tuple[str, ...]
    review_item_refs: tuple[str, ...]
    spent_cents: Decimal = Field(ge=0)


class ContactResearchFleetProjection(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    research_run_id: UUID
    workspace_id: NonEmptyStr
    project_id: NonEmptyStr
    product_id: NonEmptyStr
    project_run_id: UUID
    account_entity_id: UUID
    contact_selection_id: UUID
    fleet_state: ContactResearchFleetState
    selected_contact_ids: tuple[UUID, ...] = Field(min_length=1)
    jobs: tuple[ContactResearchJobSummary, ...] = Field(min_length=1)
    completed_count: int = Field(ge=0)
    needs_review_count: int = Field(ge=0)
    waiting_count: int = Field(ge=0)
    terminal_count: int = Field(ge=0)
    result_refs: tuple[str, ...]
    review_item_refs: tuple[str, ...]
    provider_operation_count: int = Field(ge=0)
    account_tool_request_count: int = Field(ge=0)
    unselected_contact_request_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _scope_is_exact(self) -> Self:
        job_ids = tuple(job.contact_entity_id for job in self.jobs)
        if set(job_ids) != set(self.selected_contact_ids) or len(job_ids) != len(set(job_ids)):
            raise ValueError("contact fleet jobs differ from the exact selected contact set")
        if self.account_tool_request_count or self.unselected_contact_request_count:
            raise ValueError("contact fleet observed a widened account or contact request")
        return self


class ContactResearchFleetReturn(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    return_id: UUID
    return_kind: str
    projection: ContactResearchFleetProjection
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ContactResearchFleetService:
    def __init__(self, *, conn_factory: ConnFactory) -> None:
        self._conn_factory = conn_factory

    async def project(self, research_run_id: UUID) -> ContactResearchFleetProjection:
        async with self._conn_factory() as conn:
            run = (
                (
                    await conn.execute(
                        text(
                            "SELECT run.*, launch.account_entity_id, "
                            "launch.contact_selection_id FROM entity_research_run run JOIN "
                            "entity_research_contact_launch launch USING (research_run_id) "
                            "WHERE run.research_run_id=:run_id"
                        ),
                        {"run_id": research_run_id},
                    )
                )
                .mappings()
                .first()
            )
            if run is None:
                raise ContactResearchFleetError("contact research run is absent")
            lifecycle = ResearchRunLifecycleContract.model_validate(run["lifecycle_json"])
            if (
                lifecycle.run_kind is not ResearchRunKind.CONTACT_RESEARCH
                or lifecycle.selection.subject_type is not ResearchSubjectType.CONTACT
            ):
                raise ContactResearchFleetError("aggregation received a non-contact run")
            selected = tuple(subject.subject_entity_id for subject in lifecycle.selection.subjects)
            rows = (
                (
                    await conn.execute(
                        text(
                            "SELECT job.*, authority.contact_id, authority.account_id, "
                            "coverage.coverage_id, coverage.completed_field_keys, "
                            "coverage.unresolved_field_keys, coverage.result_refs, "
                            "coverage.facet_refs, coverage.channel_operation_refs FROM "
                            "entity_research_job job JOIN "
                            "entity_research_contact_job_authority authority USING (job_id) "
                            "LEFT JOIN LATERAL (SELECT item.* FROM "
                            "entity_research_contact_coverage item WHERE item.job_id=job.job_id "
                            "ORDER BY item.created_at DESC, item.coverage_id DESC LIMIT 1) "
                            "coverage ON TRUE WHERE job.research_run_id=:run_id "
                            "ORDER BY job.priority, job.job_id"
                        ),
                        {"run_id": research_run_id},
                    )
                )
                .mappings()
                .all()
            )
            if {UUID(str(row["contact_id"])) for row in rows} != set(selected):
                raise ContactResearchFleetError(
                    "persisted contact jobs differ from the exact selection"
                )
            summaries: list[ContactResearchJobSummary] = []
            all_results: list[str] = []
            all_reviews: list[str] = []
            for row in rows:
                review_ids = (
                    (
                        await conn.execute(
                            text(
                                "SELECT review_item_id FROM entity_research_contact_review_item "
                                "WHERE job_id=:job_id AND state='open' ORDER BY created_at, "
                                "review_item_id"
                            ),
                            {"job_id": row["job_id"]},
                        )
                    )
                    .scalars()
                    .all()
                )
                result_refs = tuple(str(value) for value in (row["result_refs"] or ()))
                review_refs = tuple(f"contact-review:{value}" for value in review_ids)
                all_results.extend(value for value in result_refs if value not in all_results)
                all_reviews.extend(value for value in review_refs if value not in all_reviews)
                summaries.append(
                    ContactResearchJobSummary(
                        job_id=row["job_id"],
                        contact_entity_id=row["contact_id"],
                        parent_account_id=row["account_id"],
                        state=ResearchJobState(str(row["state"])),
                        finalization_outcome=(
                            ResearchFinalizationOutcome(str(row["finalization_outcome"]))
                            if row["finalization_outcome"] is not None
                            else None
                        ),
                        finalization_receipt_ref=row["finalization_receipt_ref"],
                        coverage_ref=(
                            f"contact-coverage:{row['coverage_id']}"
                            if row["coverage_id"] is not None
                            else None
                        ),
                        completed_field_keys=tuple(
                            str(value) for value in (row["completed_field_keys"] or ())
                        ),
                        unresolved_field_keys=tuple(
                            str(value) for value in (row["unresolved_field_keys"] or ())
                        ),
                        result_refs=result_refs,
                        facet_refs=tuple(str(value) for value in (row["facet_refs"] or ())),
                        channel_operation_refs=tuple(
                            str(value) for value in (row["channel_operation_refs"] or ())
                        ),
                        review_item_refs=review_refs,
                        spent_cents=Decimal(row["spent_cents"]),
                    )
                )
            account_requests = int(
                (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM entity_research_tool_request WHERE "
                            "research_run_id=:run_id AND subject_type='account'"
                        ),
                        {"run_id": research_run_id},
                    )
                ).scalar_one()
            )
            unselected_requests = int(
                (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM entity_research_tool_request WHERE "
                            "research_run_id=:run_id AND subject_type='contact' AND NOT "
                            "(target_entity_id=ANY(:selected))"
                        ),
                        {"run_id": research_run_id, "selected": list(selected)},
                    )
                ).scalar_one()
            )
            operation_count = int(
                (
                    await conn.execute(
                        text(
                            "SELECT count(DISTINCT operation_ref) FROM (SELECT "
                            "'provider:' || provider_operation_ref AS operation_ref FROM "
                            "entity_research_provider_observation observation JOIN "
                            "entity_research_tool_request request_row ON "
                            "request_row.tool_request_id="
                            "observation.tool_request_id WHERE request_row.research_run_id=:run_id "
                            "UNION ALL SELECT 'channel:' || channel_operation_id::text FROM "
                            "entity_research_contact_channel_causation WHERE "
                            "research_run_id=:run_id"
                            ") operations"
                        ),
                        {"run_id": research_run_id},
                    )
                ).scalar_one()
            )
        run_state = EntityResearchRunState(str(run["state"]))
        fleet_state = (
            ContactResearchFleetState.TERMINAL
            if run_state is EntityResearchRunState.TERMINAL
            else (
                ContactResearchFleetState.WAITING_EXTERNAL
                if run_state is EntityResearchRunState.WAITING_EXTERNAL
                else ContactResearchFleetState.ACTIVE
            )
        )
        projection = ContactResearchFleetProjection(
            research_run_id=research_run_id,
            workspace_id=str(run["workspace_id"]),
            project_id=str(run["project_id"]),
            product_id=str(run["product_id"]),
            project_run_id=run["project_run_id"],
            account_entity_id=run["account_entity_id"],
            contact_selection_id=run["contact_selection_id"],
            fleet_state=fleet_state,
            selected_contact_ids=selected,
            jobs=tuple(summaries),
            completed_count=sum(
                job.finalization_outcome is ResearchFinalizationOutcome.COMPLETED
                for job in summaries
            ),
            needs_review_count=sum(
                job.finalization_outcome is ResearchFinalizationOutcome.NEEDS_REVIEW
                for job in summaries
            ),
            waiting_count=sum(job.state is ResearchJobState.WAITING_EXTERNAL for job in summaries),
            terminal_count=sum(job.state is ResearchJobState.TERMINAL for job in summaries),
            result_refs=tuple(all_results),
            review_item_refs=tuple(all_reviews),
            provider_operation_count=operation_count,
            account_tool_request_count=account_requests,
            unselected_contact_request_count=unselected_requests,
        )
        if fleet_state in {
            ContactResearchFleetState.WAITING_EXTERNAL,
            ContactResearchFleetState.TERMINAL,
        }:
            await self._persist_return(projection)
        return projection

    async def read(
        self,
        research_run_id: UUID,
        *,
        workspace_id: str,
    ) -> ContactResearchFleetProjection | None:
        async with self._conn_factory() as conn:
            exists = (
                await conn.execute(
                    text(
                        "SELECT 1 FROM entity_research_contact_launch WHERE "
                        "research_run_id=:run_id AND workspace_id=:workspace_id"
                    ),
                    {"run_id": research_run_id, "workspace_id": workspace_id},
                )
            ).scalar_one_or_none()
        return None if exists is None else await self.project(research_run_id)

    async def latest_return(
        self,
        research_run_id: UUID,
        *,
        workspace_id: str,
    ) -> ContactResearchFleetReturn | None:
        async with self._conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT return_id, return_kind, payload_json, payload_sha256 FROM "
                            "entity_research_contact_fleet_return WHERE research_run_id=:run_id "
                            "AND workspace_id=:workspace_id ORDER BY return_seq DESC LIMIT 1"
                        ),
                        {"run_id": research_run_id, "workspace_id": workspace_id},
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        return ContactResearchFleetReturn(
            return_id=row["return_id"],
            return_kind=str(row["return_kind"]),
            projection=ContactResearchFleetProjection.model_validate(row["payload_json"]),
            payload_sha256=str(row["payload_sha256"]),
        )

    async def run_id_for_job(self, job_id: UUID) -> UUID | None:
        async with self._conn_factory() as conn:
            return (
                await conn.execute(
                    text(
                        "SELECT research_run_id FROM entity_research_job WHERE job_id=:job_id "
                        "AND subject_type='contact'"
                    ),
                    {"job_id": job_id},
                )
            ).scalar_one_or_none()

    async def _persist_return(self, projection: ContactResearchFleetProjection) -> None:
        payload = projection.model_dump(mode="json")
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        digest = hashlib.sha256(encoded).hexdigest()
        return_id = uuid5(_RETURN_NAMESPACE, f"{projection.research_run_id}:{digest}")
        async with self._conn_factory() as conn:
            await conn.execute(
                text(
                    "INSERT INTO entity_research_contact_fleet_return "
                    "(return_id, research_run_id, workspace_id, return_kind, payload_json, "
                    "payload_sha256) VALUES (:return_id, :run_id, :workspace_id, :kind, "
                    "CAST(:payload AS jsonb), :digest) ON CONFLICT DO NOTHING"
                ),
                {
                    "return_id": return_id,
                    "run_id": projection.research_run_id,
                    "workspace_id": projection.workspace_id,
                    "kind": projection.fleet_state.value,
                    "payload": serialize_value_json(payload),
                    "digest": digest,
                },
            )


class ContactResearchFleetWorkHandler:
    kind = FleetTaskKind.ENTITY_RESEARCH_JOB

    def __init__(
        self,
        *,
        inner: EntityResearchJobWorkHandler,
        fleets: ContactResearchFleetService,
    ) -> None:
        self._inner = inner
        self._fleets = fleets

    async def handle(self, context: WorkContext) -> WorkResult:
        raw_job_id = context.payload.get("job_id")
        if not isinstance(raw_job_id, str):
            raise EntityResearchJobError("contact fleet work payload has no job_id")
        job_id = UUID(raw_job_id)
        run_id = await self._fleets.run_id_for_job(job_id)
        if run_id is None:
            raise EntityResearchJobError("contact fleet job is absent or not a contact")
        result = await self._inner.handle(context)
        projection = await self._fleets.project(run_id)
        return WorkResult(
            outcome=result.outcome,
            references={
                **result.references,
                "research_run_id": str(run_id),
                "contact_fleet_state": projection.fleet_state.value,
            },
            requeue=result.requeue,
            task_finalized=result.task_finalized,
        )


__all__ = [
    "ContactResearchFleetError",
    "ContactResearchFleetProjection",
    "ContactResearchFleetReturn",
    "ContactResearchFleetService",
    "ContactResearchFleetState",
    "ContactResearchFleetWorkHandler",
    "ContactResearchJobSummary",
]
