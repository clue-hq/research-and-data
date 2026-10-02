"""M8D R2 subject-neutral entity-research jobs over the shared leased fleet.

This module owns no provider, source, field, committee, or agent decision.  It projects the frozen
R0 account/contact authorizations into one durable run/job envelope and executes both subject types
through the existing ``fleet_task`` queue and ``work_lease`` fence.  R3 supplies the actual
``create_agent()`` driver; R2 supplies only lifecycle authority:

* exact, separately confirmed run and job scope;
* atomic job creation plus offer to the shared queue;
* bounded per-run concurrency admission under the generic lease generation;
* durable checkpoint references and external wait/wake without a resident worker;
* terminal cancellation/finalization only with an accepted engine receipt; and
* append-only state events for observation and replay.

The production R1 launch quarantine remains in force until a later slice composes this handler with
an entity-agent driver.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Sequence
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Protocol, Self, runtime_checkable
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator
from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import ProjectRunId, UtcDatetime, decode_jsonb, serialize_value_json
from clue_core.entity_research import (
    EntityResearchJobAuthorization,
    ResearchFinalizationOutcome,
    ResearchFinalizationReceipt,
    ResearchJobState,
    ResearchRunKind,
    ResearchRunLifecycleContract,
    ResearchSubjectType,
)
from clue_db import ConnFactory, transaction
from clue_fleet.enums import FleetTaskKind, FleetTaskStatus
from clue_fleet.lease import WorkId
from clue_fleet.queue import cancel_work_tasks, enqueue_task, finish_task
from clue_fleet.work_worker import WorkContext, WorkResult

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
NonEmptyStr = Annotated[str, Field(min_length=1)]
Money = Annotated[Decimal, Field(ge=0)]


class EntityResearchRunState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_EXTERNAL = "waiting_external"
    TERMINAL = "terminal"


class EntityResearchJobEventKind(StrEnum):
    QUEUED = "queued"
    LEASED = "leased"
    STARTED = "started"
    CHECKPOINTED = "checkpointed"
    WAITING_EXTERNAL = "waiting_external"
    WOKEN = "woken"
    FINALIZED = "finalized"
    CANCELLED = "cancelled"
    LEASE_TAKEN_OVER = "lease_taken_over"


class EntityResearchWaitState(StrEnum):
    ACTIVE = "active"
    WOKEN = "woken"
    CANCELLED = "cancelled"


class EntityResearchDriverDisposition(StrEnum):
    WAITING_EXTERNAL = "waiting_external"
    FINALIZED = "finalized"


class EntityResearchJobEnvelope(BaseModel):
    """One exact selected subject plus its mechanical queue/budget policy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    authorization: EntityResearchJobAuthorization
    priority: int = 0
    budget_envelope_ref: NonEmptyStr
    budget_cap_cents: Money


class EntityResearchRunEnvelope(BaseModel):
    """One separately launched account or contact run over the shared job machinery."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    lifecycle: ResearchRunLifecycleContract
    jobs: tuple[EntityResearchJobEnvelope, ...] = Field(min_length=1)
    budget_cap_cents: Money
    concurrency_limit: int = Field(ge=1)

    @model_validator(mode="after")
    def _jobs_are_exact_projection(self) -> Self:
        selection = self.lifecycle.selection
        selected = {subject.subject_entity_id for subject in selection.subjects}
        job_ids = [job.authorization.job_id for job in self.jobs]
        subjects = [job.authorization.subject_entity_id for job in self.jobs]
        checkpoint_threads = [job.authorization.checkpoint_thread_id for job in self.jobs]
        if len(job_ids) != len(set(job_ids)):
            raise ValueError("entity research job ids must be unique")
        if len(subjects) != len(set(subjects)) or set(subjects) != selected:
            raise ValueError("entity research jobs must exactly cover the confirmed selection")
        if len(checkpoint_threads) != len(set(checkpoint_threads)):
            raise ValueError("entity research checkpoint threads must be unique within a run")
        for job in self.jobs:
            authorization = job.authorization
            if authorization.research_run_id != self.lifecycle.run_id:
                raise ValueError("entity research job belongs to a different research run")
            if authorization.selection != selection:
                raise ValueError("entity research job does not carry the run's exact selection")
            if authorization.subject_type is not selection.subject_type:
                raise ValueError("entity research job subject differs from the run selection")
            if job.budget_cap_cents > self.budget_cap_cents:
                raise ValueError("entity job budget cannot exceed its run-wide cap")
        return self


class EntityResearchRunRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    research_run_id: UUID
    run_kind: ResearchRunKind
    subject_type: ResearchSubjectType
    workspace_id: NonEmptyStr
    project_id: NonEmptyStr
    product_id: NonEmptyStr
    project_run_id: UUID
    selection_id: UUID
    lifecycle: ResearchRunLifecycleContract
    lifecycle_sha256: Sha256
    budget_envelope_ref: NonEmptyStr
    budget_cap_cents: Money
    spent_cents: Money
    concurrency_limit: int = Field(ge=1)
    state: EntityResearchRunState
    created_at: UtcDatetime
    updated_at: UtcDatetime
    terminal_at: UtcDatetime | None = None

    @model_validator(mode="after")
    def _terminal_shape(self) -> Self:
        # ``CLUE_BUDGET_CONTROLS_ENABLED=false`` deliberately makes spend record-only. In that
        # deployment mode the database may honestly contain spend above the immutable reviewed
        # cap; writers remain responsible for refusing that transition when enforcement is on.
        if (self.state is EntityResearchRunState.TERMINAL) != (self.terminal_at is not None):
            raise ValueError("entity research run terminal state requires terminal_at")
        return self


class EntityResearchJobRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    job_id: UUID
    research_run_id: UUID
    subject_type: ResearchSubjectType
    subject_entity_id: UUID
    parent_account_id: UUID | None
    workspace_id: NonEmptyStr
    project_id: NonEmptyStr
    product_id: NonEmptyStr
    project_run_id: UUID
    authorization: EntityResearchJobAuthorization
    authorization_sha256: Sha256
    priority: int
    budget_envelope_ref: NonEmptyStr
    budget_cap_cents: Money
    spent_cents: Money
    checkpoint_thread_id: NonEmptyStr
    checkpoint_ref: NonEmptyStr | None
    checkpoint_sha256: Sha256 | None
    current_state_sha256: Sha256
    state: ResearchJobState
    current_wait_ref: NonEmptyStr | None
    active_worker_id: str | None
    lease_generation: int | None = Field(default=None, ge=1)
    finalization_outcome: ResearchFinalizationOutcome | None
    finalization_receipt_ref: NonEmptyStr | None
    created_at: UtcDatetime
    updated_at: UtcDatetime
    terminal_at: UtcDatetime | None

    @model_validator(mode="after")
    def _lifecycle_shape(self) -> Self:
        # Overspend is a valid recorded observation when deployment budget enforcement is off.
        # The persistence boundary, which has the deployment switch, enforces caps in ON mode.
        active = self.state in {ResearchJobState.LEASED, ResearchJobState.RUNNING}
        if active != (self.active_worker_id is not None and self.lease_generation is not None):
            raise ValueError("active entity research job requires a worker and lease generation")
        if not active and self.active_worker_id is not None:
            raise ValueError("inactive entity research job cannot retain an active worker")
        waiting = self.state is ResearchJobState.WAITING_EXTERNAL
        if waiting != (self.current_wait_ref is not None):
            raise ValueError("waiting entity research job requires one current wait reference")
        if waiting and (self.checkpoint_ref is None or self.checkpoint_sha256 is None):
            raise ValueError("waiting entity research job requires a durable checkpoint")
        terminal = self.state is ResearchJobState.TERMINAL
        terminal_values = (
            self.finalization_outcome,
            self.finalization_receipt_ref,
            self.terminal_at,
        )
        if (terminal and not all(value is not None for value in terminal_values)) or (
            not terminal and any(value is not None for value in terminal_values)
        ):
            raise ValueError("terminal entity research job requires accepted finalization")
        return self


class EntityResearchJobEventRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    event_id: UUID
    event_seq: int = Field(ge=1)
    research_run_id: UUID
    job_id: UUID
    event_kind: EntityResearchJobEventKind
    from_state: ResearchJobState | None
    to_state: ResearchJobState
    actor: NonEmptyStr
    references: dict[str, JsonValue]
    occurred_at: UtcDatetime


class EntityResearchExecutionFence(BaseModel):
    """One exact drive of one job: its task, its holder, its lease, and its attempt ordinal.

    ``task_attempt`` is the durable per-task claim counter (``fleet_task.attempts``, incremented
    by every claim and never reset — a re-offered task keeps its row). It is part of the fence
    because ``lease_generation`` alone does **not** identify a drive: ``release_work_lease``
    deletes the ``work_lease`` row, so the next acquisition starts again at generation 1. Two
    drives of the same job at the same durable state therefore share
    ``(job, lease_generation, current_state_sha256)``, and the R3 journal's immutable
    exact-construction row would be replayed under a *different* construction whenever anything
    that constructs the agent moved between them (code, deployment config, run budget, committee
    plan) — a legitimate resume after a crash, refused as tampering. Composition keys the agent
    turn id on the attempt as well, so every drive is its own turn and the R3 guard keeps its
    real meaning: one turn id, one immutable construction.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: UUID
    worker_id: NonEmptyStr
    lease_generation: int = Field(ge=1)
    task_attempt: int = Field(ge=1)


class EntityResearchBeginResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    admitted: bool
    reason: Literal["admitted", "concurrency_limit", "waiting_external", "terminal"]
    job: EntityResearchJobRow


class EntityResearchDriverResult(BaseModel):
    """The only two honest returns from the future R3 entity-agent driver."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    disposition: EntityResearchDriverDisposition
    wait_ref: NonEmptyStr | None = None
    checkpoint_ref: NonEmptyStr | None = None
    checkpoint_sha256: Sha256 | None = None
    current_state_sha256: Sha256 | None = None
    finalization_receipt: ResearchFinalizationReceipt | None = None

    @model_validator(mode="after")
    def _result_is_one_honest_boundary(self) -> Self:
        if self.disposition is EntityResearchDriverDisposition.WAITING_EXTERNAL:
            if not all(
                (
                    self.wait_ref,
                    self.checkpoint_ref,
                    self.checkpoint_sha256,
                    self.current_state_sha256,
                )
            ):
                raise ValueError("external wait requires exact wait and checkpoint state")
            if self.finalization_receipt is not None:
                raise ValueError("waiting entity job cannot carry terminal authority")
        else:
            if self.finalization_receipt is None:
                raise ValueError("finalized entity job requires an accepted engine receipt")
            if any(
                value is not None
                for value in (
                    self.wait_ref,
                    self.checkpoint_ref,
                    self.checkpoint_sha256,
                    self.current_state_sha256,
                )
            ):
                raise ValueError("finalized entity job cannot also request an external wait")
        return self


class EntityResearchJobError(RuntimeError):
    pass


class EntityResearchRunConflict(EntityResearchJobError):
    pass


class EntityResearchJobNotFound(EntityResearchJobError):
    pass


class EntityResearchLeaseLost(EntityResearchJobError):
    pass


class EntityResearchInvalidTransition(EntityResearchJobError):
    pass


@runtime_checkable
class EntityResearchJobStore(Protocol):
    async def launch(self, envelope: EntityResearchRunEnvelope) -> EntityResearchRunRow: ...

    async def get_run(self, research_run_id: UUID) -> EntityResearchRunRow | None: ...

    async def get_job(self, job_id: UUID) -> EntityResearchJobRow | None: ...

    async def list_jobs(self, research_run_id: UUID) -> tuple[EntityResearchJobRow, ...]: ...

    async def list_events(self, job_id: UUID) -> tuple[EntityResearchJobEventRow, ...]: ...

    async def begin(
        self, job_id: UUID, *, fence: EntityResearchExecutionFence
    ) -> EntityResearchBeginResult: ...

    async def checkpoint(
        self,
        job_id: UUID,
        *,
        fence: EntityResearchExecutionFence,
        checkpoint_ref: str,
        checkpoint_sha256: str,
        current_state_sha256: str,
    ) -> EntityResearchJobRow: ...

    async def wait_external(
        self,
        job_id: UUID,
        *,
        fence: EntityResearchExecutionFence,
        wait_ref: str,
        checkpoint_ref: str,
        checkpoint_sha256: str,
        current_state_sha256: str,
    ) -> EntityResearchJobRow: ...

    async def wake(self, job_id: UUID, *, wait_ref: str, actor: str) -> EntityResearchJobRow: ...

    async def finalize(
        self,
        job_id: UUID,
        *,
        fence: EntityResearchExecutionFence,
        receipt: ResearchFinalizationReceipt,
    ) -> EntityResearchJobRow: ...

    async def cancel(
        self,
        job_id: UUID,
        *,
        receipt: ResearchFinalizationReceipt,
        actor: str,
    ) -> EntityResearchJobRow: ...

    async def cancel_run(
        self,
        research_run_id: UUID,
        *,
        receipts: Sequence[tuple[UUID, ResearchFinalizationReceipt]],
        actor: str,
    ) -> EntityResearchRunRow: ...


@runtime_checkable
class EntityResearchJobDriver(Protocol):
    async def run(
        self,
        job: EntityResearchJobRow,
        *,
        fence: EntityResearchExecutionFence,
        stop_requested: asyncio.Event,
        lease_lost: asyncio.Event,
    ) -> EntityResearchDriverResult: ...


def _canonical_payload(model: BaseModel) -> dict[str, JsonValue]:
    return model.model_dump(mode="json")


def _payload_sha256(model: BaseModel) -> str:
    encoded = json.dumps(
        _canonical_payload(model),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _decode_object(value: object) -> dict[str, object]:
    decoded = decode_jsonb(value)
    return dict(decoded) if isinstance(decoded, dict) else {}


_RUN_COLUMNS = """
research_run_id, run_kind, subject_type, workspace_id, project_id, product_id, project_run_id,
selection_id, lifecycle_json, lifecycle_sha256, budget_envelope_ref, budget_cap_cents, spent_cents,
concurrency_limit, state, created_at, updated_at, terminal_at
"""

_JOB_COLUMNS = """
job_id, research_run_id, subject_type, subject_entity_id, parent_account_id, workspace_id,
project_id, product_id, project_run_id, authorization_json, authorization_sha256, priority,
budget_envelope_ref, budget_cap_cents, spent_cents, checkpoint_thread_id, checkpoint_ref,
checkpoint_sha256, current_state_sha256, state, current_wait_ref, active_worker_id,
lease_generation, finalization_outcome, finalization_receipt_ref, created_at, updated_at,
terminal_at
"""


def _run_row(raw: RowMapping) -> EntityResearchRunRow:
    row = dict(raw)
    lifecycle_json = row.pop("lifecycle_json")
    return EntityResearchRunRow.model_validate(
        {
            **row,
            "lifecycle": ResearchRunLifecycleContract.model_validate(
                _decode_object(lifecycle_json)
            ),
        }
    )


def _job_row(raw: RowMapping) -> EntityResearchJobRow:
    row = dict(raw)
    authorization_json = row.pop("authorization_json")
    return EntityResearchJobRow.model_validate(
        {
            **row,
            "authorization": EntityResearchJobAuthorization.model_validate(
                _decode_object(authorization_json)
            ),
        }
    )


async def _read_run(
    conn: AsyncConnection,
    research_run_id: UUID,
    *,
    for_update: bool = False,
) -> EntityResearchRunRow | None:
    suffix = " FOR UPDATE" if for_update else ""
    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {_RUN_COLUMNS} FROM entity_research_run "
                    f"WHERE research_run_id = :id{suffix}"
                ),
                {"id": research_run_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    return _run_row(row) if row is not None else None


async def _read_job(
    conn: AsyncConnection,
    job_id: UUID,
    *,
    for_update: bool = False,
) -> EntityResearchJobRow | None:
    suffix = " FOR UPDATE" if for_update else ""
    row = (
        (
            await conn.execute(
                text(f"SELECT {_JOB_COLUMNS} FROM entity_research_job WHERE job_id = :id{suffix}"),
                {"id": job_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    return _job_row(row) if row is not None else None


async def _lock_run_and_job(
    conn: AsyncConnection,
    job_id: UUID,
) -> tuple[EntityResearchRunRow, EntityResearchJobRow]:
    """Lock aggregate before child so concurrent job transitions cannot stale run state."""

    initial = await _read_job(conn, job_id)
    if initial is None:
        raise EntityResearchJobNotFound(str(job_id))
    run = await _read_run(conn, initial.research_run_id, for_update=True)
    assert run is not None
    job = await _read_job(conn, job_id, for_update=True)
    assert job is not None
    return run, job


async def append_entity_research_job_event(
    conn: AsyncConnection,
    *,
    run_id: UUID,
    job_id: UUID,
    kind: EntityResearchJobEventKind,
    from_state: ResearchJobState | None,
    to_state: ResearchJobState,
    actor: str,
    references: dict[str, JsonValue] | None = None,
) -> None:
    await conn.execute(
        text(
            """
            INSERT INTO entity_research_job_event
                (event_id, research_run_id, job_id, event_kind, from_state, to_state, actor,
                 references_json)
            VALUES
                (:event_id, :run_id, :job_id, :kind, :from_state, :to_state, :actor,
                 CAST(:references AS jsonb))
            """
        ),
        {
            "event_id": uuid4(),
            "run_id": run_id,
            "job_id": job_id,
            "kind": kind.value,
            "from_state": from_state.value if from_state is not None else None,
            "to_state": to_state.value,
            "actor": actor,
            "references": serialize_value_json(references or {}),
        },
    )


async def _refresh_run_state(conn: AsyncConnection, research_run_id: UUID) -> None:
    counts = (
        (
            await conn.execute(
                text(
                    """
                SELECT
                    count(*) FILTER (WHERE state = 'terminal') AS terminal_count,
                    count(*) FILTER (WHERE state = 'waiting_external') AS waiting_count,
                    count(*) FILTER (WHERE state IN ('leased', 'running')) AS running_count,
                    count(*) AS total_count
                FROM entity_research_job
                WHERE research_run_id = :run_id
                """
                ),
                {"run_id": research_run_id},
            )
        )
        .mappings()
        .one()
    )
    total = int(counts["total_count"])
    terminal = int(counts["terminal_count"])
    waiting = int(counts["waiting_count"])
    running = int(counts["running_count"])
    if total > 0 and terminal == total:
        state = EntityResearchRunState.TERMINAL
    elif running:
        state = EntityResearchRunState.RUNNING
    elif waiting and waiting + terminal == total:
        state = EntityResearchRunState.WAITING_EXTERNAL
    else:
        state = EntityResearchRunState.QUEUED
    await conn.execute(
        text(
            """
            UPDATE entity_research_run
            SET state = :state,
                terminal_at = CASE WHEN :state = 'terminal' THEN COALESCE(terminal_at, now())
                                   ELSE NULL END,
                updated_at = now()
            WHERE research_run_id = :run_id
            """
        ),
        {"run_id": research_run_id, "state": state.value},
    )


async def launch_entity_research_run(
    conn: AsyncConnection,
    envelope: EntityResearchRunEnvelope,
) -> EntityResearchRunRow:
    """Persist an exact run and offer every job in the same transaction as the fleet rows."""

    lifecycle = envelope.lifecycle
    selection = lifecycle.selection
    lifecycle_sha = _payload_sha256(lifecycle)
    inserted = (
        await conn.execute(
            text(
                """
                INSERT INTO entity_research_run
                    (research_run_id, run_kind, subject_type, workspace_id, project_id, product_id,
                     project_run_id, selection_id, contact_selection_id, lifecycle_json,
                     lifecycle_sha256,
                     budget_envelope_ref, budget_cap_cents, concurrency_limit)
                VALUES
                    (:run_id, :run_kind, :subject_type, :workspace_id, :project_id, :product_id,
                     :project_run_id, :selection_id, :contact_selection_id,
                     CAST(:lifecycle AS jsonb), :lifecycle_sha,
                     :budget_ref, :budget_cap, :concurrency_limit)
                ON CONFLICT DO NOTHING
                RETURNING research_run_id
                """
            ),
            {
                "run_id": lifecycle.run_id,
                "run_kind": lifecycle.run_kind.value,
                "subject_type": selection.subject_type.value,
                "workspace_id": selection.workspace_id,
                "project_id": selection.project_id,
                "product_id": selection.product_id,
                "project_run_id": selection.project_run_id,
                "selection_id": selection.selection_id,
                "contact_selection_id": (
                    selection.selection_id
                    if lifecycle.run_kind is ResearchRunKind.CONTACT_RESEARCH
                    else None
                ),
                "lifecycle": serialize_value_json(_canonical_payload(lifecycle)),
                "lifecycle_sha": lifecycle_sha,
                "budget_ref": selection.budget_envelope_ref,
                "budget_cap": envelope.budget_cap_cents,
                "concurrency_limit": envelope.concurrency_limit,
            },
        )
    ).first()
    current = await _read_run(conn, lifecycle.run_id, for_update=True)
    if current is None:
        raise EntityResearchRunConflict(
            f"selection {selection.selection_id} already belongs to another research run"
        )
    if inserted is None and (
        current.lifecycle_sha256 != lifecycle_sha
        or current.budget_cap_cents != envelope.budget_cap_cents
        or current.concurrency_limit != envelope.concurrency_limit
    ):
        raise EntityResearchRunConflict(
            f"research run {lifecycle.run_id} already exists with different immutable authority"
        )

    for job_envelope in envelope.jobs:
        authorization = job_envelope.authorization
        authorization_sha = _payload_sha256(authorization)
        state_sha = hashlib.sha256(f"authorization:{authorization_sha}".encode()).hexdigest()
        job_inserted = (
            await conn.execute(
                text(
                    """
                    INSERT INTO entity_research_job
                        (job_id, research_run_id, subject_type, subject_entity_id,
                         parent_account_id, workspace_id, project_id, product_id, project_run_id,
                         authorization_json, authorization_sha256, priority, budget_envelope_ref,
                         budget_cap_cents, checkpoint_thread_id, initial_state_sha256,
                         current_state_sha256)
                    VALUES
                        (:job_id, :run_id, :subject_type, :subject_id, :parent_account_id,
                         :workspace_id, :project_id, :product_id, :project_run_id,
                         CAST(:authorization AS jsonb), :authorization_sha, :priority, :budget_ref,
                         :budget_cap, :checkpoint_thread_id, :state_sha, :state_sha)
                    ON CONFLICT DO NOTHING
                    RETURNING job_id
                    """
                ),
                {
                    "job_id": authorization.job_id,
                    "run_id": lifecycle.run_id,
                    "subject_type": authorization.subject_type.value,
                    "subject_id": authorization.subject_entity_id,
                    "parent_account_id": authorization.parent_account_id,
                    "workspace_id": authorization.workspace_id,
                    "project_id": authorization.project_id,
                    "product_id": authorization.product_id,
                    "project_run_id": authorization.project_run_id,
                    "authorization": serialize_value_json(_canonical_payload(authorization)),
                    "authorization_sha": authorization_sha,
                    "priority": job_envelope.priority,
                    "budget_ref": job_envelope.budget_envelope_ref,
                    "budget_cap": job_envelope.budget_cap_cents,
                    "checkpoint_thread_id": authorization.checkpoint_thread_id,
                    "state_sha": state_sha,
                },
            )
        ).first()
        current_job = await _read_job(conn, authorization.job_id, for_update=True)
        if current_job is None:
            raise EntityResearchRunConflict(
                f"entity research job {authorization.job_id} conflicts with this run's exact "
                "subject or checkpoint set"
            )
        if job_inserted is None and (
            current_job.authorization_sha256 != authorization_sha
            or current_job.research_run_id != lifecycle.run_id
            or current_job.priority != job_envelope.priority
            or current_job.budget_envelope_ref != job_envelope.budget_envelope_ref
            or current_job.budget_cap_cents != job_envelope.budget_cap_cents
        ):
            raise EntityResearchRunConflict(
                f"entity research job {authorization.job_id} already exists with "
                "different authority"
            )
        if job_inserted is not None:
            await append_entity_research_job_event(
                conn,
                run_id=lifecycle.run_id,
                job_id=authorization.job_id,
                kind=EntityResearchJobEventKind.QUEUED,
                from_state=None,
                to_state=ResearchJobState.QUEUED,
                actor=selection.confirmed_by,
                references={"selection_id": str(selection.selection_id)},
            )
        await enqueue_task(
            conn,
            kind=FleetTaskKind.ENTITY_RESEARCH_JOB,
            project_run_id=ProjectRunId(authorization.job_id),
            dedup_key=str(authorization.job_id),
            priority=job_envelope.priority,
            payload={"job_id": str(authorization.job_id)},
        )

    jobs = (
        await conn.execute(
            text("SELECT count(*) FROM entity_research_job WHERE research_run_id = :run_id"),
            {"run_id": lifecycle.run_id},
        )
    ).scalar_one()
    if int(jobs) != len(envelope.jobs):
        raise EntityResearchRunConflict("existing research run contains a different exact job set")
    result = await _read_run(conn, lifecycle.run_id)
    assert result is not None
    return result


def _fence_matches(job: EntityResearchJobRow, fence: EntityResearchExecutionFence) -> bool:
    return (
        job.active_worker_id == fence.worker_id
        and job.lease_generation == fence.lease_generation
        and job.state is ResearchJobState.RUNNING
    )


async def _assert_live_fleet_fence(
    conn: AsyncConnection,
    job_id: UUID,
    fence: EntityResearchExecutionFence,
) -> None:
    """Prove the domain fence still owns both the task claim and generic work lease."""

    owns = (
        await conn.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1
                    FROM fleet_task AS task
                    JOIN work_lease AS lease ON lease.work_id = task.work_id
                    WHERE task.task_id = :task_id
                      AND task.kind = CAST(:kind AS fleet_task_kind)
                      AND task.work_id = :job_id
                      AND task.status = 'claimed'
                      AND task.claimed_by = :worker_id
                      AND lease.work_id = :job_id
                      AND lease.worker_id = :worker_id
                      AND lease.generation = :generation
                      AND lease.expires_at > now()
                )
                """
            ),
            {
                "task_id": fence.task_id,
                "kind": FleetTaskKind.ENTITY_RESEARCH_JOB.value,
                "job_id": job_id,
                "worker_id": fence.worker_id,
                "generation": fence.lease_generation,
            },
        )
    ).scalar_one()
    if not owns:
        raise EntityResearchLeaseLost(
            "entity research writer no longer owns its fleet task and live lease"
        )


def _validate_receipt(
    job: EntityResearchJobRow,
    receipt: ResearchFinalizationReceipt,
    *,
    required_outcome: ResearchFinalizationOutcome | None = None,
) -> str:
    proposal = receipt.proposal
    if proposal.subject_type is not job.subject_type:
        raise EntityResearchInvalidTransition("finalization receipt has the wrong subject type")
    if proposal.target_entity_id != job.subject_entity_id:
        raise EntityResearchInvalidTransition("finalization receipt targets a different entity")
    if receipt.accepted_state_sha256 != job.current_state_sha256:
        raise EntityResearchInvalidTransition("finalization receipt accepts stale job state")
    if required_outcome is not None and proposal.outcome is not required_outcome:
        raise EntityResearchInvalidTransition(
            f"finalization receipt must have outcome {required_outcome.value}"
        )
    return f"entity-research-finalization:{receipt.receipt_id}"


async def begin_entity_research_job(
    conn: AsyncConnection,
    job_id: UUID,
    *,
    fence: EntityResearchExecutionFence,
) -> EntityResearchBeginResult:
    run, job = await _lock_run_and_job(conn, job_id)
    if job.state is ResearchJobState.TERMINAL:
        return EntityResearchBeginResult(admitted=False, reason="terminal", job=job)
    if job.state is ResearchJobState.WAITING_EXTERNAL:
        return EntityResearchBeginResult(admitted=False, reason="waiting_external", job=job)
    await _assert_live_fleet_fence(conn, job_id, fence)
    if (
        job.state in {ResearchJobState.LEASED, ResearchJobState.RUNNING}
        and job.active_worker_id == fence.worker_id
        and job.lease_generation == fence.lease_generation
    ):
        if job.state is ResearchJobState.LEASED:
            await conn.execute(
                text(
                    """
                    UPDATE entity_research_job
                    SET state = 'running', updated_at = now()
                    WHERE job_id = :job_id
                    """
                ),
                {"job_id": job_id},
            )
        await append_entity_research_job_event(
            conn,
            run_id=job.research_run_id,
            job_id=job_id,
            kind=EntityResearchJobEventKind.STARTED,
            from_state=ResearchJobState.LEASED,
            to_state=ResearchJobState.RUNNING,
            actor=fence.worker_id,
            references={"lease_generation": fence.lease_generation},
        )
        current = await _read_job(conn, job_id)
        assert current is not None
        return EntityResearchBeginResult(admitted=True, reason="admitted", job=current)

    active = int(
        (
            await conn.execute(
                text(
                    """
                    SELECT count(*) FROM entity_research_job
                    WHERE research_run_id = :run_id
                      AND job_id <> :job_id
                      AND state IN ('leased', 'running')
                    """
                ),
                {"run_id": job.research_run_id, "job_id": job_id},
            )
        ).scalar_one()
    )
    if active >= run.concurrency_limit:
        return EntityResearchBeginResult(admitted=False, reason="concurrency_limit", job=job)

    takeover = job.state in {ResearchJobState.LEASED, ResearchJobState.RUNNING}
    await conn.execute(
        text(
            """
            UPDATE entity_research_job
            SET state = 'leased', active_worker_id = :worker_id,
                lease_generation = :generation, updated_at = now()
            WHERE job_id = :job_id AND state <> 'terminal'
            """
        ),
        {
            "job_id": job_id,
            "worker_id": fence.worker_id,
            "generation": fence.lease_generation,
        },
    )
    await append_entity_research_job_event(
        conn,
        run_id=job.research_run_id,
        job_id=job_id,
        kind=(
            EntityResearchJobEventKind.LEASE_TAKEN_OVER
            if takeover
            else EntityResearchJobEventKind.LEASED
        ),
        from_state=job.state,
        to_state=ResearchJobState.LEASED,
        actor=fence.worker_id,
        references={
            "task_id": str(fence.task_id),
            "lease_generation": fence.lease_generation,
        },
    )
    await conn.execute(
        text(
            """
            UPDATE entity_research_job SET state = 'running', updated_at = now()
            WHERE job_id = :job_id AND state = 'leased'
            """
        ),
        {"job_id": job_id},
    )
    await append_entity_research_job_event(
        conn,
        run_id=job.research_run_id,
        job_id=job_id,
        kind=EntityResearchJobEventKind.STARTED,
        from_state=ResearchJobState.LEASED,
        to_state=ResearchJobState.RUNNING,
        actor=fence.worker_id,
        references={"lease_generation": fence.lease_generation},
    )
    await _refresh_run_state(conn, job.research_run_id)
    current = await _read_job(conn, job_id)
    assert current is not None
    return EntityResearchBeginResult(admitted=True, reason="admitted", job=current)


async def checkpoint_entity_research_job(
    conn: AsyncConnection,
    job_id: UUID,
    *,
    fence: EntityResearchExecutionFence,
    checkpoint_ref: str,
    checkpoint_sha256: str,
    current_state_sha256: str,
) -> EntityResearchJobRow:
    _, job = await _lock_run_and_job(conn, job_id)
    await _assert_live_fleet_fence(conn, job_id, fence)
    if not _fence_matches(job, fence):
        raise EntityResearchLeaseLost("checkpoint writer does not own the running entity job")
    await conn.execute(
        text(
            """
            UPDATE entity_research_job
            SET checkpoint_ref = :checkpoint_ref, checkpoint_sha256 = :checkpoint_sha,
                current_state_sha256 = :state_sha, updated_at = now()
            WHERE job_id = :job_id
            """
        ),
        {
            "job_id": job_id,
            "checkpoint_ref": checkpoint_ref,
            "checkpoint_sha": checkpoint_sha256,
            "state_sha": current_state_sha256,
        },
    )
    await append_entity_research_job_event(
        conn,
        run_id=job.research_run_id,
        job_id=job_id,
        kind=EntityResearchJobEventKind.CHECKPOINTED,
        from_state=ResearchJobState.RUNNING,
        to_state=ResearchJobState.RUNNING,
        actor=fence.worker_id,
        references={"checkpoint_ref": checkpoint_ref},
    )
    current = await _read_job(conn, job_id)
    assert current is not None
    return current


async def wait_entity_research_job(
    conn: AsyncConnection,
    job_id: UUID,
    *,
    fence: EntityResearchExecutionFence,
    wait_ref: str,
    checkpoint_ref: str,
    checkpoint_sha256: str,
    current_state_sha256: str,
) -> EntityResearchJobRow:
    _, job = await _lock_run_and_job(conn, job_id)
    await _assert_live_fleet_fence(conn, job_id, fence)
    if not _fence_matches(job, fence):
        raise EntityResearchLeaseLost("wait writer does not own the running entity job")
    await conn.execute(
        text(
            """
            INSERT INTO entity_research_job_wait
                (wait_id, research_run_id, job_id, wait_ref, checkpoint_ref, checkpoint_sha256,
                 current_state_sha256)
            VALUES
                (:wait_id, :run_id, :job_id, :wait_ref, :checkpoint_ref, :checkpoint_sha,
                 :state_sha)
            """
        ),
        {
            "wait_id": uuid4(),
            "run_id": job.research_run_id,
            "job_id": job_id,
            "wait_ref": wait_ref,
            "checkpoint_ref": checkpoint_ref,
            "checkpoint_sha": checkpoint_sha256,
            "state_sha": current_state_sha256,
        },
    )
    await conn.execute(
        text(
            """
            UPDATE entity_research_job
            SET state = 'waiting_external', current_wait_ref = :wait_ref,
                checkpoint_ref = :checkpoint_ref, checkpoint_sha256 = :checkpoint_sha,
                current_state_sha256 = :state_sha, active_worker_id = NULL,
                updated_at = now()
            WHERE job_id = :job_id
            """
        ),
        {
            "job_id": job_id,
            "wait_ref": wait_ref,
            "checkpoint_ref": checkpoint_ref,
            "checkpoint_sha": checkpoint_sha256,
            "state_sha": current_state_sha256,
        },
    )
    if not await finish_task(
        conn,
        task_id=fence.task_id,
        worker_id=fence.worker_id,
        status=FleetTaskStatus.DONE,
        result_ref={"outcome": "waiting_external", "wait_ref": wait_ref},
    ):
        raise EntityResearchLeaseLost("fleet task ownership was lost before external wait")
    await append_entity_research_job_event(
        conn,
        run_id=job.research_run_id,
        job_id=job_id,
        kind=EntityResearchJobEventKind.WAITING_EXTERNAL,
        from_state=ResearchJobState.RUNNING,
        to_state=ResearchJobState.WAITING_EXTERNAL,
        actor=fence.worker_id,
        references={"wait_ref": wait_ref, "checkpoint_ref": checkpoint_ref},
    )
    await _refresh_run_state(conn, job.research_run_id)
    current = await _read_job(conn, job_id)
    assert current is not None
    return current


async def wake_entity_research_job(
    conn: AsyncConnection,
    job_id: UUID,
    *,
    wait_ref: str,
    actor: str,
) -> EntityResearchJobRow:
    initial = await _read_job(conn, job_id)
    if initial is None:
        raise EntityResearchJobNotFound(str(job_id))
    await _read_run(conn, initial.research_run_id, for_update=True)
    job = await _read_job(conn, job_id, for_update=True)
    assert job is not None
    wait_state = (
        await conn.execute(
            text(
                """
                SELECT state FROM entity_research_job_wait
                WHERE job_id = :job_id AND wait_ref = :wait_ref
                FOR UPDATE
                """
            ),
            {"job_id": job_id, "wait_ref": wait_ref},
        )
    ).scalar_one_or_none()
    if wait_state is None:
        raise EntityResearchInvalidTransition("external wait reference does not belong to this job")
    if job.state is ResearchJobState.TERMINAL:
        raise EntityResearchInvalidTransition(
            "cancelled/finalized entity job cannot be resurrected"
        )
    if wait_state == EntityResearchWaitState.WOKEN.value and job.state is ResearchJobState.QUEUED:
        return job
    if (
        job.state is not ResearchJobState.WAITING_EXTERNAL
        or job.current_wait_ref != wait_ref
        or wait_state != EntityResearchWaitState.ACTIVE.value
    ):
        raise EntityResearchInvalidTransition("external wait is not the job's active wait")
    if job.checkpoint_ref is None:
        raise EntityResearchInvalidTransition("waiting entity research job has no checkpoint")
    await conn.execute(
        text(
            """
            UPDATE entity_research_job_wait
            SET state = 'woken', resolved_at = now(), resolved_by = :actor
            WHERE job_id = :job_id AND wait_ref = :wait_ref AND state = 'active'
            """
        ),
        {"job_id": job_id, "wait_ref": wait_ref, "actor": actor},
    )
    await conn.execute(
        text(
            """
            UPDATE entity_research_job
            SET state = 'queued', current_wait_ref = NULL, active_worker_id = NULL,
                lease_generation = NULL, updated_at = now()
            WHERE job_id = :job_id AND state = 'waiting_external'
            """
        ),
        {"job_id": job_id},
    )
    await append_entity_research_job_event(
        conn,
        run_id=job.research_run_id,
        job_id=job_id,
        kind=EntityResearchJobEventKind.WOKEN,
        from_state=ResearchJobState.WAITING_EXTERNAL,
        to_state=ResearchJobState.QUEUED,
        actor=actor,
        references={"wait_ref": wait_ref, "checkpoint_ref": job.checkpoint_ref},
    )
    await enqueue_task(
        conn,
        kind=FleetTaskKind.ENTITY_RESEARCH_JOB,
        project_run_id=ProjectRunId(job_id),
        dedup_key=str(job_id),
        priority=job.priority,
        payload={"job_id": str(job_id)},
        reopen_terminal=True,
    )
    await _refresh_run_state(conn, job.research_run_id)
    current = await _read_job(conn, job_id)
    assert current is not None
    return current


async def _record_finalization(
    conn: AsyncConnection,
    job: EntityResearchJobRow,
    *,
    receipt: ResearchFinalizationReceipt,
    actor: str,
    fence: EntityResearchExecutionFence | None,
    cancellation: bool,
) -> EntityResearchJobRow:
    required = ResearchFinalizationOutcome.CANCELLED if cancellation else None
    receipt_ref = _validate_receipt(job, receipt, required_outcome=required)
    if job.state is ResearchJobState.TERMINAL:
        if job.finalization_receipt_ref == receipt_ref:
            return job
        raise EntityResearchInvalidTransition("entity job already has a different finalization")
    if fence is not None and not _fence_matches(job, fence):
        raise EntityResearchLeaseLost("finalization writer does not own the running entity job")
    if fence is None and not cancellation:
        raise EntityResearchInvalidTransition(
            "non-cancellation finalization requires a lease fence"
        )

    await conn.execute(
        text(
            """
            INSERT INTO entity_research_job_finalization
                (receipt_id, research_run_id, job_id, receipt_ref, proposal_id, outcome,
                 accepted_state_sha256, receipt_json, accepted_at, engine_actor)
            VALUES
                (:receipt_id, :run_id, :job_id, :receipt_ref, :proposal_id, :outcome,
                 :state_sha, CAST(:receipt AS jsonb), :accepted_at, :engine_actor)
            """
        ),
        {
            "receipt_id": receipt.receipt_id,
            "run_id": job.research_run_id,
            "job_id": job.job_id,
            "receipt_ref": receipt_ref,
            "proposal_id": receipt.proposal.proposal_id,
            "outcome": receipt.proposal.outcome.value,
            "state_sha": receipt.accepted_state_sha256,
            "receipt": serialize_value_json(_canonical_payload(receipt)),
            "accepted_at": receipt.accepted_at,
            "engine_actor": receipt.engine_actor,
        },
    )
    if job.current_wait_ref is not None:
        await conn.execute(
            text(
                """
                UPDATE entity_research_job_wait
                SET state = 'cancelled', resolved_at = now(), resolved_by = :actor
                WHERE job_id = :job_id AND wait_ref = :wait_ref AND state = 'active'
                """
            ),
            {"job_id": job.job_id, "wait_ref": job.current_wait_ref, "actor": actor},
        )
    await conn.execute(
        text(
            """
            UPDATE entity_research_job
            SET state = 'terminal', current_wait_ref = NULL, active_worker_id = NULL,
                finalization_outcome = :outcome, finalization_receipt_ref = :receipt_ref,
                terminal_at = now(), updated_at = now()
            WHERE job_id = :job_id AND state <> 'terminal'
            """
        ),
        {
            "job_id": job.job_id,
            "outcome": receipt.proposal.outcome.value,
            "receipt_ref": receipt_ref,
        },
    )
    if fence is not None:
        if not await finish_task(
            conn,
            task_id=fence.task_id,
            worker_id=fence.worker_id,
            status=FleetTaskStatus.DONE,
            result_ref={
                "outcome": receipt.proposal.outcome.value,
                "finalization_receipt_ref": receipt_ref,
            },
        ):
            raise EntityResearchLeaseLost("fleet task ownership was lost before finalization")
    else:
        # Revoke the lease before locking the task.  Heartbeats renew lease then touch task, so
        # using the same lock order prevents a cancellation/heartbeat deadlock.  The next renew
        # fences and cancels the resident driver; domain writes also re-check this live lease.
        await conn.execute(
            text("DELETE FROM work_lease WHERE work_id = :job_id"),
            {"job_id": job.job_id},
        )
        await cancel_work_tasks(
            conn,
            kind=FleetTaskKind.ENTITY_RESEARCH_JOB,
            work_id=WorkId(job.job_id),
            result_ref={"outcome": "cancelled", "finalization_receipt_ref": receipt_ref},
        )
    await append_entity_research_job_event(
        conn,
        run_id=job.research_run_id,
        job_id=job.job_id,
        kind=(
            EntityResearchJobEventKind.CANCELLED
            if receipt.proposal.outcome is ResearchFinalizationOutcome.CANCELLED
            else EntityResearchJobEventKind.FINALIZED
        ),
        from_state=job.state,
        to_state=ResearchJobState.TERMINAL,
        actor=actor,
        references={"finalization_receipt_ref": receipt_ref},
    )
    await _refresh_run_state(conn, job.research_run_id)
    current = await _read_job(conn, job.job_id)
    assert current is not None
    return current


async def finalize_entity_research_job(
    conn: AsyncConnection,
    job_id: UUID,
    *,
    fence: EntityResearchExecutionFence,
    receipt: ResearchFinalizationReceipt,
) -> EntityResearchJobRow:
    _, job = await _lock_run_and_job(conn, job_id)
    await _assert_live_fleet_fence(conn, job_id, fence)
    return await _record_finalization(
        conn,
        job,
        receipt=receipt,
        actor=receipt.engine_actor,
        fence=fence,
        cancellation=False,
    )


async def cancel_entity_research_job(
    conn: AsyncConnection,
    job_id: UUID,
    *,
    receipt: ResearchFinalizationReceipt,
    actor: str,
) -> EntityResearchJobRow:
    _, job = await _lock_run_and_job(conn, job_id)
    return await _record_finalization(
        conn,
        job,
        receipt=receipt,
        actor=actor,
        fence=None,
        cancellation=True,
    )


async def cancel_entity_research_run(
    conn: AsyncConnection,
    research_run_id: UUID,
    *,
    receipts: Sequence[tuple[UUID, ResearchFinalizationReceipt]],
    actor: str,
) -> EntityResearchRunRow:
    run = await _read_run(conn, research_run_id, for_update=True)
    if run is None:
        raise EntityResearchJobNotFound(str(research_run_id))
    jobs_raw = (
        (
            await conn.execute(
                text(
                    f"SELECT {_JOB_COLUMNS} FROM entity_research_job "
                    "WHERE research_run_id = :run_id ORDER BY created_at, job_id FOR UPDATE"
                ),
                {"run_id": research_run_id},
            )
        )
        .mappings()
        .all()
    )
    jobs = tuple(_job_row(row) for row in jobs_raw)
    nonterminal = {job.job_id: job for job in jobs if job.state is not ResearchJobState.TERMINAL}
    by_job = dict(receipts)
    if len(by_job) != len(receipts) or set(by_job) != set(nonterminal):
        raise EntityResearchInvalidTransition(
            "run cancellation requires exactly one accepted receipt per nonterminal job"
        )
    for job_id, job in nonterminal.items():
        await _record_finalization(
            conn,
            job,
            receipt=by_job[job_id],
            actor=actor,
            fence=None,
            cancellation=True,
        )
    current = await _read_run(conn, research_run_id)
    assert current is not None
    return current


class DbEntityResearchJobStore:
    """Postgres R2 lifecycle store; every transition is one short transaction."""

    def __init__(self, *, conn_factory: ConnFactory = transaction) -> None:
        self._conn_factory = conn_factory

    async def launch(self, envelope: EntityResearchRunEnvelope) -> EntityResearchRunRow:
        async with self._conn_factory() as conn:
            return await launch_entity_research_run(conn, envelope)

    async def get_run(self, research_run_id: UUID) -> EntityResearchRunRow | None:
        async with self._conn_factory() as conn:
            return await _read_run(conn, research_run_id)

    async def get_job(self, job_id: UUID) -> EntityResearchJobRow | None:
        async with self._conn_factory() as conn:
            return await _read_job(conn, job_id)

    async def list_jobs(self, research_run_id: UUID) -> tuple[EntityResearchJobRow, ...]:
        async with self._conn_factory() as conn:
            rows = (
                (
                    await conn.execute(
                        text(
                            f"SELECT {_JOB_COLUMNS} FROM entity_research_job "
                            "WHERE research_run_id = :run_id ORDER BY priority, created_at, job_id"
                        ),
                        {"run_id": research_run_id},
                    )
                )
                .mappings()
                .all()
            )
            return tuple(_job_row(row) for row in rows)

    async def list_events(self, job_id: UUID) -> tuple[EntityResearchJobEventRow, ...]:
        async with self._conn_factory() as conn:
            rows = (
                (
                    await conn.execute(
                        text(
                            """
                        SELECT event_id, event_seq, research_run_id, job_id, event_kind,
                               from_state, to_state, actor, references_json, occurred_at
                        FROM entity_research_job_event
                        WHERE job_id = :job_id
                        ORDER BY event_seq
                        """
                        ),
                        {"job_id": job_id},
                    )
                )
                .mappings()
                .all()
            )
            events: list[EntityResearchJobEventRow] = []
            for raw in rows:
                row = dict(raw)
                references_json = row.pop("references_json")
                events.append(
                    EntityResearchJobEventRow.model_validate(
                        {**row, "references": _decode_object(references_json)}
                    )
                )
            return tuple(events)

    async def begin(
        self,
        job_id: UUID,
        *,
        fence: EntityResearchExecutionFence,
    ) -> EntityResearchBeginResult:
        async with self._conn_factory() as conn:
            return await begin_entity_research_job(conn, job_id, fence=fence)

    async def checkpoint(
        self,
        job_id: UUID,
        *,
        fence: EntityResearchExecutionFence,
        checkpoint_ref: str,
        checkpoint_sha256: str,
        current_state_sha256: str,
    ) -> EntityResearchJobRow:
        async with self._conn_factory() as conn:
            return await checkpoint_entity_research_job(
                conn,
                job_id,
                fence=fence,
                checkpoint_ref=checkpoint_ref,
                checkpoint_sha256=checkpoint_sha256,
                current_state_sha256=current_state_sha256,
            )

    async def wait_external(
        self,
        job_id: UUID,
        *,
        fence: EntityResearchExecutionFence,
        wait_ref: str,
        checkpoint_ref: str,
        checkpoint_sha256: str,
        current_state_sha256: str,
    ) -> EntityResearchJobRow:
        async with self._conn_factory() as conn:
            return await wait_entity_research_job(
                conn,
                job_id,
                fence=fence,
                wait_ref=wait_ref,
                checkpoint_ref=checkpoint_ref,
                checkpoint_sha256=checkpoint_sha256,
                current_state_sha256=current_state_sha256,
            )

    async def wake(self, job_id: UUID, *, wait_ref: str, actor: str) -> EntityResearchJobRow:
        async with self._conn_factory() as conn:
            return await wake_entity_research_job(conn, job_id, wait_ref=wait_ref, actor=actor)

    async def finalize(
        self,
        job_id: UUID,
        *,
        fence: EntityResearchExecutionFence,
        receipt: ResearchFinalizationReceipt,
    ) -> EntityResearchJobRow:
        async with self._conn_factory() as conn:
            return await finalize_entity_research_job(
                conn,
                job_id,
                fence=fence,
                receipt=receipt,
            )

    async def cancel(
        self,
        job_id: UUID,
        *,
        receipt: ResearchFinalizationReceipt,
        actor: str,
    ) -> EntityResearchJobRow:
        async with self._conn_factory() as conn:
            return await cancel_entity_research_job(
                conn,
                job_id,
                receipt=receipt,
                actor=actor,
            )

    async def cancel_run(
        self,
        research_run_id: UUID,
        *,
        receipts: Sequence[tuple[UUID, ResearchFinalizationReceipt]],
        actor: str,
    ) -> EntityResearchRunRow:
        async with self._conn_factory() as conn:
            return await cancel_entity_research_run(
                conn,
                research_run_id,
                receipts=receipts,
                actor=actor,
            )


class EntityResearchJobWorkHandler:
    """One handler for both account and contact jobs; the injected R3 driver supplies agency."""

    kind = FleetTaskKind.ENTITY_RESEARCH_JOB

    def __init__(self, *, store: EntityResearchJobStore, driver: EntityResearchJobDriver) -> None:
        self._store = store
        self._driver = driver

    async def handle(self, context: WorkContext) -> WorkResult:
        raw_job_id = context.payload.get("job_id")
        if not isinstance(raw_job_id, str):
            raise EntityResearchJobError("entity research work payload has no job_id")
        try:
            job_id = UUID(raw_job_id)
        except ValueError as exc:
            raise EntityResearchJobError(
                "entity research work payload has an invalid job_id"
            ) from exc
        if job_id != UUID(str(context.work_id)):
            raise EntityResearchJobError("entity research work payload widens the leased work id")
        fence = EntityResearchExecutionFence(
            task_id=context.task_id,
            worker_id=context.worker_id,
            lease_generation=context.lease_generation,
            task_attempt=context.task_attempt,
        )
        begin = await self._store.begin(job_id, fence=fence)
        if not begin.admitted:
            if begin.reason == "concurrency_limit":
                return WorkResult(
                    outcome="concurrency_limited",
                    references={"job_id": str(job_id)},
                    requeue=True,
                )
            return WorkResult(
                outcome=begin.reason,
                references={"job_id": str(job_id)},
            )
        result = await self._driver.run(
            begin.job,
            fence=fence,
            stop_requested=context.stop_requested,
            lease_lost=context.lease_lost,
        )
        if result.disposition is EntityResearchDriverDisposition.WAITING_EXTERNAL:
            assert result.wait_ref is not None
            assert result.checkpoint_ref is not None
            assert result.checkpoint_sha256 is not None
            assert result.current_state_sha256 is not None
            waiting = await self._store.wait_external(
                job_id,
                fence=fence,
                wait_ref=result.wait_ref,
                checkpoint_ref=result.checkpoint_ref,
                checkpoint_sha256=result.checkpoint_sha256,
                current_state_sha256=result.current_state_sha256,
            )
            return WorkResult(
                outcome="waiting_external",
                references={
                    "job_id": str(job_id),
                    "wait_ref": result.wait_ref,
                    "checkpoint_thread_id": waiting.checkpoint_thread_id,
                },
                task_finalized=True,
            )
        assert result.finalization_receipt is not None
        terminal = await self._store.finalize(
            job_id,
            fence=fence,
            receipt=result.finalization_receipt,
        )
        if terminal.finalization_receipt_ref is None:
            raise EntityResearchInvalidTransition(
                "terminal entity research job has no finalization receipt"
            )
        return WorkResult(
            outcome=(
                terminal.finalization_outcome.value
                if terminal.finalization_outcome is not None
                else "terminal"
            ),
            references={
                "job_id": str(job_id),
                "finalization_receipt_ref": terminal.finalization_receipt_ref,
            },
            task_finalized=True,
        )


__all__ = [
    "DbEntityResearchJobStore",
    "EntityResearchBeginResult",
    "EntityResearchDriverDisposition",
    "EntityResearchDriverResult",
    "EntityResearchExecutionFence",
    "EntityResearchInvalidTransition",
    "EntityResearchJobDriver",
    "EntityResearchJobEnvelope",
    "EntityResearchJobError",
    "EntityResearchJobEventKind",
    "EntityResearchJobEventRow",
    "EntityResearchJobNotFound",
    "EntityResearchJobRow",
    "EntityResearchJobStore",
    "EntityResearchJobWorkHandler",
    "EntityResearchLeaseLost",
    "EntityResearchRunConflict",
    "EntityResearchRunEnvelope",
    "EntityResearchRunRow",
    "EntityResearchRunState",
    "EntityResearchWaitState",
    "begin_entity_research_job",
    "cancel_entity_research_job",
    "cancel_entity_research_run",
    "checkpoint_entity_research_job",
    "finalize_entity_research_job",
    "launch_entity_research_run",
    "wait_entity_research_job",
    "wake_entity_research_job",
]
