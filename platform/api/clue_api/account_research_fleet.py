"""M8D R6 account-fleet admission, supervision, steering, and user return.

The R2 queue remains subject-neutral and the R5 account agent remains the only component that
chooses research tools.  This module adds the mechanical account-run shell around them:

* launch one immutable, user-confirmed exact account set;
* admit a deterministic canary and hold the remainder without changing selection authority;
* release the remainder only after a persisted deterministic health decision;
* journal bounded pause/resume/reprioritise steering;
* turn worker errors into an honest, resumable suspension; and
* expose a complete run/result/review projection without creating contact jobs.

No provider is named here and no research decision is made here.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self, cast
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator
from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import ProjectRunId, UtcDatetime, serialize_value_json
from clue_core.entity_research import (
    FinalizationVerification,
    ResearchFinalizationOutcome,
    ResearchFinalizationProposal,
    ResearchFinalizationReceipt,
    ResearchJobState,
    ResearchRunKind,
    ResearchSubjectType,
)
from clue_db import ConnFactory, transaction
from clue_fleet.entity_research import (
    EntityResearchJobError,
    EntityResearchJobWorkHandler,
    EntityResearchRunEnvelope,
    cancel_entity_research_run,
    launch_entity_research_run,
)
from clue_fleet.enums import FleetTaskKind
from clue_fleet.lease import WorkId
from clue_fleet.queue import cancel_work_tasks, enqueue_task
from clue_fleet.work_worker import WorkContext, WorkResult

Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

_RETURN_NAMESPACE = uuid5(NAMESPACE_URL, "clue:m8d:r6:account-fleet-return")
_CANCELLATION_NAMESPACE = uuid5(NAMESPACE_URL, "clue:m8d:r6:account-fleet-cancellation")


class AccountResearchFleetError(RuntimeError):
    pass


class AccountResearchFleetState(StrEnum):
    CANARY = "canary"
    OPEN = "open"
    WAITING_EXTERNAL = "waiting_external"
    SUSPENDED = "suspended"
    TERMINAL = "terminal"


class AccountResearchFleetCohort(StrEnum):
    CANARY = "canary"
    REMAINDER = "remainder"


class AccountResearchAdmissionState(StrEnum):
    ADMITTED = "admitted"
    HELD = "held"
    RELEASED = "released"
    PAUSED = "paused"
    TERMINAL = "terminal"


class AccountResearchFleetPolicy(BaseModel):
    """Versioned deterministic canary policy; no transcript or per-turn LLM judge."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    version: Literal["m8d-r6-supervisor-v1"] = "m8d-r6-supervisor-v1"
    canary_size: int = Field(default=10, ge=1, le=100)
    maximum_needs_review_fraction: Decimal = Field(default=Decimal("0.50"), ge=0, le=1)
    blocking_outcomes: tuple[ResearchFinalizationOutcome, ...] = (
        ResearchFinalizationOutcome.FAILED,
        ResearchFinalizationOutcome.BUDGET_STOPPED,
    )

    @model_validator(mode="after")
    def _outcomes_are_unique(self) -> Self:
        if len(self.blocking_outcomes) != len(set(self.blocking_outcomes)):
            raise ValueError("account fleet blocking outcomes must be unique")
        return self

    @property
    def policy_sha256(self) -> str:
        return _sha(self.model_dump(mode="json"))

    @property
    def policy_ref(self) -> str:
        return f"account-fleet-supervisor:{self.version}:{self.policy_sha256}"


class AccountResearchFleetRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    research_run_id: UUID
    workspace_id: str
    project_id: str
    product_id: str
    project_run_id: UUID
    canary_job_ids: tuple[UUID, ...]
    supervisor_policy_ref: str
    supervisor_policy: AccountResearchFleetPolicy
    supervisor_policy_sha256: Sha256
    state: AccountResearchFleetState
    diagnosis: dict[str, JsonValue]
    created_by: str
    source_operation_id: UUID
    source_action_ref: str
    created_at: UtcDatetime
    updated_at: UtcDatetime
    suspended_at: UtcDatetime | None
    terminal_at: UtcDatetime | None


class AccountResearchJobSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    job_id: UUID
    account_run_id: UUID | None
    account_entity_id: UUID
    cohort: AccountResearchFleetCohort
    admission_state: AccountResearchAdmissionState
    effective_priority: int
    job_state: ResearchJobState
    finalization_outcome: ResearchFinalizationOutcome | None
    finalization_receipt_ref: str | None
    current_wait_ref: str | None
    spent_cents: Decimal
    result_refs: tuple[str, ...] = ()
    committee_member_ids: tuple[UUID, ...] = ()
    review_item_refs: tuple[str, ...] = ()


class AccountResearchFleetProjection(BaseModel):
    """The references-only return surface the Head-of-ABM can inspect or narrate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    research_run_id: UUID
    workspace_id: str
    project_id: str
    product_id: str
    project_run_id: UUID
    fleet_state: AccountResearchFleetState
    run_state: str
    selected_accounts: int
    queued_accounts: int
    active_accounts: int
    waiting_accounts: int
    paused_accounts: int
    terminal_accounts: int
    completed_accounts: int
    needs_review_accounts: int
    spent_cents: Decimal
    budget_cap_cents: Decimal
    jobs: tuple[AccountResearchJobSummary, ...]
    review_queue: tuple[str, ...]
    contact_research_request_count: int
    contact_research_started: Literal[False] = False
    diagnosis: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _counts_are_complete(self) -> Self:
        if self.selected_accounts != len(self.jobs):
            raise ValueError("account fleet projection omits selected jobs")
        if self.contact_research_request_count:
            raise ValueError("account fleet return cannot contain contact research")
        classified = (
            self.queued_accounts
            + self.active_accounts
            + self.waiting_accounts
            + self.paused_accounts
            + self.terminal_accounts
        )
        if classified != self.selected_accounts:
            raise ValueError("account fleet projection job-state counts are not exhaustive")
        return self


class AccountResearchFleetReturn(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    return_id: UUID
    return_kind: Literal["suspended", "terminal"]
    projection: AccountResearchFleetProjection
    payload_sha256: Sha256


def _sha(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _object(value: object) -> dict[str, JsonValue]:
    return dict(value) if isinstance(value, dict) else {}


@asynccontextmanager
async def _borrow_connection(conn: AsyncConnection) -> AsyncIterator[AsyncConnection]:
    """Let a higher-level compiler keep launch compilation and queue offer atomic."""

    yield conn


def _fleet_row(raw: RowMapping) -> AccountResearchFleetRow:
    row = dict(raw)
    policy = row.pop("supervisor_policy_json")
    diagnosis = row.pop("diagnosis_json")
    return AccountResearchFleetRow.model_validate(
        {
            **row,
            "supervisor_policy": policy,
            "diagnosis": _object(diagnosis),
        }
    )


async def _read_fleet(
    conn: AsyncConnection,
    research_run_id: UUID,
    *,
    for_update: bool = False,
) -> AccountResearchFleetRow | None:
    suffix = " FOR UPDATE" if for_update else ""
    row = (
        (
            await conn.execute(
                text(
                    "SELECT research_run_id, workspace_id, project_id, product_id, "
                    "project_run_id, canary_job_ids, supervisor_policy_ref, "
                    "supervisor_policy_json, supervisor_policy_sha256, state, diagnosis_json, "
                    "created_by, source_action_ref, created_at, updated_at, suspended_at, "
                    "source_operation_id, "
                    "terminal_at FROM entity_research_account_fleet "
                    f"WHERE research_run_id=:run_id{suffix}"
                ),
                {"run_id": research_run_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    return None if row is None else _fleet_row(row)


async def _event(
    conn: AsyncConnection,
    *,
    run_id: UUID,
    actor: str,
    action: str,
    reason_code: str,
    before: dict[str, JsonValue],
    after: dict[str, JsonValue],
    job_id: UUID | None = None,
    references: dict[str, JsonValue] | None = None,
) -> None:
    await conn.execute(
        text(
            """
            INSERT INTO entity_research_account_fleet_control_event
                (event_id, research_run_id, job_id, actor, action, before_json, after_json,
                 reason_code, references_json)
            VALUES
                (:event_id, :run_id, :job_id, :actor, :action, CAST(:before AS jsonb),
                 CAST(:after AS jsonb), :reason_code, CAST(:references AS jsonb))
            """
        ),
        {
            "event_id": uuid4(),
            "run_id": run_id,
            "job_id": job_id,
            "actor": actor,
            "action": action,
            "before": serialize_value_json(before),
            "after": serialize_value_json(after),
            "reason_code": reason_code,
            "references": serialize_value_json(references or {}),
        },
    )


class AccountResearchFleetService:
    """Transactional R6 controller over the R2 run/job and shared queue substrates."""

    def __init__(self, *, conn_factory: ConnFactory = transaction) -> None:
        self._conn_factory = conn_factory

    async def launch(
        self,
        envelope: EntityResearchRunEnvelope,
        *,
        policy: AccountResearchFleetPolicy,
        actor: str,
        source_operation_id: UUID,
        source_action_ref: str,
        account_run_ids: Mapping[UUID, UUID] | None = None,
    ) -> AccountResearchFleetProjection:
        lifecycle = envelope.lifecycle
        if (
            lifecycle.run_kind is not ResearchRunKind.ACCOUNT_RESEARCH
            or lifecycle.selection.subject_type is not ResearchSubjectType.ACCOUNT
            or any(
                item.authorization.subject_type is not ResearchSubjectType.ACCOUNT
                for item in envelope.jobs
            )
        ):
            raise AccountResearchFleetError("R6 launches account-research jobs only")
        if not actor.strip() or not source_action_ref.strip():
            raise AccountResearchFleetError("account fleet launch requires durable human action")
        ordered = tuple(
            sorted(envelope.jobs, key=lambda item: (item.priority, str(item.authorization.job_id)))
        )
        bound_account_runs = dict(account_run_ids or {})
        job_ids = {item.authorization.job_id for item in ordered}
        if bound_account_runs and set(bound_account_runs) != job_ids:
            raise AccountResearchFleetError(
                "account-run bindings must cover the exact account fleet job set"
            )
        canary_ids = tuple(
            item.authorization.job_id for item in ordered[: min(policy.canary_size, len(ordered))]
        )
        async with self._conn_factory() as conn:
            run = await launch_entity_research_run(conn, envelope)
            inserted = (
                await conn.execute(
                    text(
                        """
                        INSERT INTO entity_research_account_fleet
                            (research_run_id, workspace_id, project_id, product_id, project_run_id,
                             canary_job_ids, supervisor_policy_ref, supervisor_policy_json,
                             supervisor_policy_sha256, created_by, source_operation_id,
                             source_action_ref)
                        VALUES
                            (:run_id, :workspace_id, :project_id, :product_id, :project_run_id,
                             :canary_ids, :policy_ref, CAST(:policy AS jsonb), :policy_sha,
                             :actor, :operation_id, :action_ref)
                        ON CONFLICT DO NOTHING RETURNING research_run_id
                        """
                    ),
                    {
                        "run_id": run.research_run_id,
                        "workspace_id": run.workspace_id,
                        "project_id": run.project_id,
                        "product_id": run.product_id,
                        "project_run_id": run.project_run_id,
                        "canary_ids": list(canary_ids),
                        "policy_ref": policy.policy_ref,
                        "policy": serialize_value_json(policy.model_dump(mode="json")),
                        "policy_sha": policy.policy_sha256,
                        "actor": actor,
                        "operation_id": source_operation_id,
                        "action_ref": source_action_ref,
                    },
                )
            ).first()
            fleet = await _read_fleet(conn, run.research_run_id, for_update=True)
            if fleet is None:
                prior_action_run = (
                    await conn.execute(
                        text(
                            "SELECT research_run_id FROM entity_research_account_fleet "
                            "WHERE workspace_id=:workspace_id AND source_action_ref=:action_ref"
                        ),
                        {
                            "workspace_id": run.workspace_id,
                            "action_ref": source_action_ref,
                        },
                    )
                ).scalar_one_or_none()
                if prior_action_run is not None:
                    raise AccountResearchFleetError(
                        "account fleet action replay changed immutable launch authority"
                    )
                raise AccountResearchFleetError("account fleet launch was not persisted")
            if (
                fleet.canary_job_ids != canary_ids
                or fleet.supervisor_policy_sha256 != policy.policy_sha256
                or fleet.created_by != actor
                or fleet.source_operation_id != source_operation_id
                or fleet.source_action_ref != source_action_ref
            ):
                raise AccountResearchFleetError(
                    "account fleet launch replay changed canary, policy, or action authority"
                )
            if inserted is not None:
                canary_set = set(canary_ids)
                for item in ordered:
                    job_id = item.authorization.job_id
                    cohort = (
                        AccountResearchFleetCohort.CANARY
                        if job_id in canary_set
                        else AccountResearchFleetCohort.REMAINDER
                    )
                    admission = (
                        AccountResearchAdmissionState.ADMITTED
                        if cohort is AccountResearchFleetCohort.CANARY
                        else AccountResearchAdmissionState.HELD
                    )
                    await conn.execute(
                        text(
                            """
                            INSERT INTO entity_research_account_fleet_job_control
                                (job_id, research_run_id, account_run_id, cohort, admission_state,
                                 effective_priority)
                            VALUES (:job_id, :run_id, :account_run_id, :cohort, :admission,
                                    :priority)
                            """
                        ),
                        {
                            "job_id": job_id,
                            "run_id": run.research_run_id,
                            "account_run_id": bound_account_runs.get(job_id),
                            "cohort": cohort.value,
                            "admission": admission.value,
                            "priority": item.priority,
                        },
                    )
                    if admission is AccountResearchAdmissionState.HELD:
                        await cancel_work_tasks(
                            conn,
                            kind=FleetTaskKind.ENTITY_RESEARCH_JOB,
                            work_id=WorkId(job_id),
                            result_ref={"outcome": "canary_held", "job_id": str(job_id)},
                        )
                await _event(
                    conn,
                    run_id=run.research_run_id,
                    actor=actor,
                    action="launch",
                    reason_code="exact_set_user_confirmed",
                    before={},
                    after={
                        "state": AccountResearchFleetState.CANARY.value,
                        "canary_job_ids": [str(value) for value in canary_ids],
                        "held_jobs": len(ordered) - len(canary_ids),
                    },
                    references={
                        "source_action_ref": source_action_ref,
                        "source_operation_id": str(source_operation_id),
                    },
                )
            observed_account_runs = {
                row["job_id"]: row["account_run_id"]
                for row in (
                    (
                        await conn.execute(
                            text(
                                "SELECT job_id, account_run_id FROM "
                                "entity_research_account_fleet_job_control "
                                "WHERE research_run_id=:run_id"
                            ),
                            {"run_id": run.research_run_id},
                        )
                    )
                    .mappings()
                    .all()
                )
            }
            expected_account_runs = {job_id: bound_account_runs.get(job_id) for job_id in job_ids}
            if observed_account_runs != expected_account_runs:
                raise AccountResearchFleetError(
                    "account fleet replay changed exact account-run bindings"
                )
            return await self._projection(conn, run.research_run_id, workspace_id=run.workspace_id)

    async def launch_in_transaction(
        self,
        conn: AsyncConnection,
        envelope: EntityResearchRunEnvelope,
        *,
        policy: AccountResearchFleetPolicy,
        actor: str,
        source_operation_id: UUID,
        source_action_ref: str,
        account_run_ids: Mapping[UUID, UUID] | None = None,
    ) -> AccountResearchFleetProjection:
        """Compile compatibility state and offer the fleet under one caller-owned transaction."""

        borrowed = AccountResearchFleetService(conn_factory=lambda: _borrow_connection(conn))
        return await borrowed.launch(
            envelope,
            policy=policy,
            actor=actor,
            source_operation_id=source_operation_id,
            source_action_ref=source_action_ref,
            account_run_ids=account_run_ids,
        )

    async def read(
        self,
        research_run_id: UUID,
        *,
        workspace_id: str,
    ) -> AccountResearchFleetProjection | None:
        async with self._conn_factory() as conn:
            fleet = await _read_fleet(conn, research_run_id)
            if fleet is None or fleet.workspace_id != workspace_id:
                return None
            return await self._projection(conn, research_run_id, workspace_id=workspace_id)

    async def latest_return(
        self,
        research_run_id: UUID,
        *,
        workspace_id: str,
    ) -> AccountResearchFleetReturn | None:
        async with self._conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT return_id, return_kind, payload_json, payload_sha256 "
                            "FROM entity_research_account_fleet_return "
                            "WHERE research_run_id=:run_id AND workspace_id=:workspace_id "
                            "ORDER BY return_seq DESC LIMIT 1"
                        ),
                        {"run_id": research_run_id, "workspace_id": workspace_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return AccountResearchFleetReturn(
            return_id=row["return_id"],
            return_kind=row["return_kind"],
            projection=AccountResearchFleetProjection.model_validate(row["payload_json"]),
            payload_sha256=str(row["payload_sha256"]),
        )

    async def reconcile(self, research_run_id: UUID) -> AccountResearchFleetProjection:
        async with self._conn_factory() as conn:
            fleet = await _read_fleet(conn, research_run_id, for_update=True)
            if fleet is None:
                raise AccountResearchFleetError("account fleet is absent")
            return await self._reconcile_locked(conn, fleet)

    async def pause_job(
        self,
        job_id: UUID,
        *,
        workspace_id: str,
        actor: str,
        reason_code: str,
    ) -> AccountResearchFleetProjection:
        if not actor.strip() or not reason_code.strip():
            raise AccountResearchFleetError("pause requires actor and reason")
        async with self._conn_factory() as conn:
            row = await self._lock_control(conn, job_id, workspace_id=workspace_id)
            run_id = UUID(str(row["research_run_id"]))
            if row["job_state"] in {"leased", "running", "terminal"}:
                raise AccountResearchFleetError(
                    "only queued or external-wait account jobs can be paused"
                )
            prior = str(row["admission_state"])
            if prior != AccountResearchAdmissionState.PAUSED.value:
                await conn.execute(
                    text(
                        "UPDATE entity_research_account_fleet_job_control SET "
                        "admission_state='paused', pause_reason=:reason, updated_at=now() "
                        "WHERE job_id=:job_id"
                    ),
                    {"reason": reason_code, "job_id": job_id},
                )
                await cancel_work_tasks(
                    conn,
                    kind=FleetTaskKind.ENTITY_RESEARCH_JOB,
                    work_id=WorkId(job_id),
                    result_ref={"outcome": "steering_paused", "reason_code": reason_code},
                )
                await _event(
                    conn,
                    run_id=run_id,
                    job_id=job_id,
                    actor=actor,
                    action="pause_job",
                    reason_code=reason_code,
                    before={"admission_state": prior},
                    after={"admission_state": "paused"},
                )
            fleet = await _read_fleet(conn, run_id, for_update=True)
            assert fleet is not None
            return await self._reconcile_locked(conn, fleet)

    async def resume_job(
        self,
        job_id: UUID,
        *,
        workspace_id: str,
        actor: str,
    ) -> AccountResearchFleetProjection:
        async with self._conn_factory() as conn:
            row = await self._lock_control(conn, job_id, workspace_id=workspace_id)
            run_id = UUID(str(row["research_run_id"]))
            if str(row["admission_state"]) != AccountResearchAdmissionState.PAUSED.value:
                raise AccountResearchFleetError("only a paused account job can be resumed")
            next_state = (
                AccountResearchAdmissionState.ADMITTED
                if str(row["cohort"]) == AccountResearchFleetCohort.CANARY.value
                else AccountResearchAdmissionState.RELEASED
            )
            await conn.execute(
                text(
                    "UPDATE entity_research_account_fleet_job_control SET "
                    "admission_state=:state, pause_reason=NULL, updated_at=now() "
                    "WHERE job_id=:job_id"
                ),
                {"state": next_state.value, "job_id": job_id},
            )
            if str(row["job_state"]) == ResearchJobState.QUEUED.value:
                await enqueue_task(
                    conn,
                    kind=FleetTaskKind.ENTITY_RESEARCH_JOB,
                    project_run_id=ProjectRunId(job_id),
                    dedup_key=str(job_id),
                    priority=cast(int, row["effective_priority"]),
                    payload={"job_id": str(job_id)},
                    reopen_terminal=True,
                )
            await _event(
                conn,
                run_id=run_id,
                job_id=job_id,
                actor=actor,
                action="resume_job",
                reason_code="human_resume",
                before={"admission_state": "paused"},
                after={"admission_state": next_state.value},
            )
            fleet = await _read_fleet(conn, run_id, for_update=True)
            assert fleet is not None
            return await self._reconcile_locked(conn, fleet)

    async def reprioritize_job(
        self,
        job_id: UUID,
        *,
        workspace_id: str,
        actor: str,
        priority: int,
    ) -> AccountResearchFleetProjection:
        async with self._conn_factory() as conn:
            row = await self._lock_control(conn, job_id, workspace_id=workspace_id)
            run_id = UUID(str(row["research_run_id"]))
            if str(row["job_state"]) != ResearchJobState.QUEUED.value:
                raise AccountResearchFleetError("only a queued account job can be reprioritized")
            before = cast(int, row["effective_priority"])
            await conn.execute(
                text(
                    "UPDATE entity_research_account_fleet_job_control SET "
                    "effective_priority=:priority, updated_at=now() WHERE job_id=:job_id"
                ),
                {"priority": priority, "job_id": job_id},
            )
            await conn.execute(
                text(
                    "UPDATE fleet_task SET priority=:priority, updated_at=now() "
                    "WHERE kind='entity_research_job' AND work_id=:job_id "
                    "AND status IN ('queued','done')"
                ),
                {"priority": priority, "job_id": job_id},
            )
            await _event(
                conn,
                run_id=run_id,
                job_id=job_id,
                actor=actor,
                action="reprioritize_job",
                reason_code="human_reprioritize",
                before={"effective_priority": before},
                after={"effective_priority": priority},
            )
            return await self._projection(
                conn,
                run_id,
                workspace_id=workspace_id,
            )

    async def cancel(
        self,
        research_run_id: UUID,
        *,
        workspace_id: str,
        actor: str,
        reason_code: str,
    ) -> AccountResearchFleetProjection:
        """Cancel every nonterminal account job under one exact, journaled user action.

        Cancellation uses the R2 terminal-receipt path, which revokes active leases, cancels
        external waits and closes queue tasks. A late provider wake therefore cannot resurrect a
        cancelled job. Existing terminal results remain immutable and visible in the return.
        """

        if not actor.strip() or not reason_code.strip():
            raise AccountResearchFleetError("cancel requires actor and reason")
        async with self._conn_factory() as conn:
            fleet = await _read_fleet(conn, research_run_id, for_update=True)
            if fleet is None or fleet.workspace_id != workspace_id:
                raise AccountResearchFleetError("account fleet is absent or cross-workspace")
            jobs = (
                (
                    await conn.execute(
                        text(
                            "SELECT job_id, subject_type, subject_entity_id, state, "
                            "current_state_sha256 FROM entity_research_job "
                            "WHERE research_run_id=:run_id ORDER BY created_at, job_id FOR UPDATE"
                        ),
                        {"run_id": research_run_id},
                    )
                )
                .mappings()
                .all()
            )
            receipts: list[tuple[UUID, ResearchFinalizationReceipt]] = []
            for row in jobs:
                if str(row["state"]) == ResearchJobState.TERMINAL.value:
                    continue
                job_id = UUID(str(row["job_id"]))
                state_sha = str(row["current_state_sha256"])
                proposal_id = uuid5(
                    _CANCELLATION_NAMESPACE,
                    f"proposal:{job_id}:{state_sha}:{reason_code}",
                )
                proposal = ResearchFinalizationProposal(
                    proposal_id=proposal_id,
                    subject_type=ResearchSubjectType(str(row["subject_type"])),
                    target_entity_id=UUID(str(row["subject_entity_id"])),
                    outcome=ResearchFinalizationOutcome.CANCELLED,
                    current_state_sha256=state_sha,
                    coverage_ledger_ref=f"account-fleet-cancellation:{job_id}:coverage",
                    claim_delta_ledger_ref=f"account-fleet-cancellation:{job_id}:claim-delta",
                    spend_reconciliation_ref=f"account-fleet-cancellation:{job_id}:spend",
                    identity_use_verification_ref=(
                        f"account-fleet-cancellation:{job_id}:identity-use"
                    ),
                )
                receipts.append(
                    (
                        job_id,
                        ResearchFinalizationReceipt(
                            receipt_id=uuid5(
                                _CANCELLATION_NAMESPACE,
                                f"receipt:{job_id}:{state_sha}:{reason_code}",
                            ),
                            proposal=proposal,
                            proposal_ref=f"account-fleet-cancellation:{proposal_id}",
                            engine_actor="engine:account-fleet-cancellation",
                            accepted_at=datetime.now(UTC),
                            accepted_state_sha256=state_sha,
                            verification=FinalizationVerification(
                                no_pending_operations=True,
                                evidence_complete=True,
                                coverage_matches=True,
                                spend_reconciled=True,
                                identity_use_verification_complete=True,
                                policy_scope_respected=True,
                                current_state_matches=True,
                            ),
                        ),
                    )
                )
            if receipts:
                await cancel_entity_research_run(
                    conn,
                    research_run_id,
                    receipts=receipts,
                    actor=actor,
                )
                await _event(
                    conn,
                    run_id=research_run_id,
                    actor=actor,
                    action="cancel_fleet",
                    reason_code=reason_code,
                    before={"state": fleet.state.value},
                    after={
                        "state": AccountResearchFleetState.TERMINAL.value,
                        "cancelled_job_ids": [str(job_id) for job_id, _ in receipts],
                    },
                )
            current = await _read_fleet(conn, research_run_id, for_update=True)
            assert current is not None
            return await self._reconcile_locked(conn, current)

    async def admission_state(self, job_id: UUID) -> AccountResearchAdmissionState:
        async with self._conn_factory() as conn:
            value = (
                await conn.execute(
                    text(
                        "SELECT admission_state FROM "
                        "entity_research_account_fleet_job_control WHERE job_id=:job_id"
                    ),
                    {"job_id": job_id},
                )
            ).scalar_one_or_none()
        if value is None:
            raise AccountResearchFleetError("account job has no R6 admission control")
        return AccountResearchAdmissionState(str(value))

    async def job_run_id(self, job_id: UUID) -> UUID:
        async with self._conn_factory() as conn:
            value = (
                await conn.execute(
                    text(
                        "SELECT research_run_id FROM "
                        "entity_research_account_fleet_job_control WHERE job_id=:job_id"
                    ),
                    {"job_id": job_id},
                )
            ).scalar_one_or_none()
        if value is None:
            raise AccountResearchFleetError("account job has no R6 fleet run")
        return UUID(str(value))

    async def park_unadmitted_claim(
        self,
        job_id: UUID,
        *,
        state: AccountResearchAdmissionState,
    ) -> None:
        async with self._conn_factory() as conn:
            await cancel_work_tasks(
                conn,
                kind=FleetTaskKind.ENTITY_RESEARCH_JOB,
                work_id=WorkId(job_id),
                result_ref={"outcome": state.value, "job_id": str(job_id)},
            )

    async def suspend_failure(
        self,
        context: WorkContext,
        error: BaseException,
    ) -> AccountResearchFleetProjection:
        job_id = UUID(str(context.work_id))
        reason = f"worker_error:{type(error).__name__}"
        async with self._conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT job.research_run_id, job.workspace_id, job.state, "
                            "job.active_worker_id, job.lease_generation, control.admission_state "
                            "FROM entity_research_job job JOIN "
                            "entity_research_account_fleet_job_control control "
                            "ON control.job_id=job.job_id WHERE job.job_id=:job_id FOR UPDATE"
                        ),
                        {"job_id": job_id},
                    )
                )
                .mappings()
                .one()
            )
            if (
                str(row["state"]) not in {"leased", "running"}
                or str(row["active_worker_id"]) != context.worker_id
                or int(row["lease_generation"]) != int(context.lease_generation)
            ):
                raise AccountResearchFleetError(
                    "failed account job no longer owns its domain fence"
                ) from error
            await conn.execute(
                text(
                    "UPDATE entity_research_job SET state='queued', active_worker_id=NULL, "
                    "lease_generation=NULL, updated_at=now() WHERE job_id=:job_id"
                ),
                {"job_id": job_id},
            )
            await conn.execute(
                text(
                    "UPDATE entity_research_account_fleet_job_control SET "
                    "admission_state='paused', pause_reason=:reason, updated_at=now() "
                    "WHERE job_id=:job_id"
                ),
                {"reason": reason, "job_id": job_id},
            )
            await cancel_work_tasks(
                conn,
                kind=FleetTaskKind.ENTITY_RESEARCH_JOB,
                work_id=WorkId(job_id),
                result_ref={"outcome": "supervisor_suspended", "reason_code": reason},
            )
            await _event(
                conn,
                run_id=row["research_run_id"],
                job_id=job_id,
                actor="engine:account-fleet-supervisor",
                action="suspend_job",
                reason_code=reason,
                before={
                    "admission_state": str(row["admission_state"]),
                    "job_state": str(row["state"]),
                },
                after={"admission_state": "paused", "job_state": "queued"},
                references={"error_message_sha256": _sha(str(error))},
            )
            fleet = await _read_fleet(conn, row["research_run_id"], for_update=True)
            assert fleet is not None
            return await self._reconcile_locked(conn, fleet)

    async def _lock_control(
        self,
        conn: AsyncConnection,
        job_id: UUID,
        *,
        workspace_id: str,
    ) -> RowMapping:
        row = (
            (
                await conn.execute(
                    text(
                        "SELECT control.job_id, control.research_run_id, control.cohort, "
                        "control.admission_state, control.effective_priority, job.state AS "
                        "job_state FROM entity_research_account_fleet_job_control control "
                        "JOIN entity_research_job job ON job.job_id=control.job_id "
                        "JOIN entity_research_account_fleet fleet "
                        "ON fleet.research_run_id=control.research_run_id "
                        "WHERE control.job_id=:job_id AND fleet.workspace_id=:workspace_id "
                        "FOR UPDATE OF control"
                    ),
                    {"job_id": job_id, "workspace_id": workspace_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise AccountResearchFleetError("account fleet job is absent or cross-workspace")
        return row

    async def _reconcile_locked(
        self,
        conn: AsyncConnection,
        fleet: AccountResearchFleetRow,
    ) -> AccountResearchFleetProjection:
        raw_rows = (
            (
                await conn.execute(
                    text(
                        "SELECT control.job_id, control.cohort, control.admission_state, "
                        "job.state, job.finalization_outcome FROM "
                        "entity_research_account_fleet_job_control control JOIN "
                        "entity_research_job job ON job.job_id=control.job_id "
                        "WHERE control.research_run_id=:run_id ORDER BY control.job_id FOR UPDATE"
                    ),
                    {"run_id": fleet.research_run_id},
                )
            )
            .mappings()
            .all()
        )
        rows = [dict(row) for row in raw_rows]
        for row in rows:
            if (
                str(row["state"]) == ResearchJobState.TERMINAL.value
                and str(row["admission_state"]) != AccountResearchAdmissionState.TERMINAL.value
            ):
                await conn.execute(
                    text(
                        "UPDATE entity_research_account_fleet_job_control SET "
                        "admission_state='terminal', pause_reason=NULL, updated_at=now() "
                        "WHERE job_id=:job_id"
                    ),
                    {"job_id": row["job_id"]},
                )
                row["admission_state"] = AccountResearchAdmissionState.TERMINAL.value

        paused = [row for row in rows if str(row["admission_state"]) == "paused"]
        all_terminal = all(str(row["state"]) == ResearchJobState.TERMINAL.value for row in rows)
        diagnosis: dict[str, JsonValue] = {}
        next_state = fleet.state
        if paused:
            next_state = AccountResearchFleetState.SUSPENDED
            diagnosis = {
                "reason_code": "account_jobs_suspended",
                "job_ids": [str(row["job_id"]) for row in paused],
            }
        elif all_terminal:
            next_state = AccountResearchFleetState.TERMINAL
        else:
            # Derive admission progress from durable job/control state, never from the previous
            # aggregate label.  This matters after a human resumes a suspended canary: the prior
            # state is ``suspended``, but the same incomplete canary must run again before any
            # remainder is released.
            canary = [row for row in rows if str(row["cohort"]) == "canary"]
            held = [row for row in rows if str(row["admission_state"]) == "held"]
            canary_terminal = all(
                str(row["state"]) == ResearchJobState.TERMINAL.value for row in canary
            )
            if canary_terminal and held:
                outcomes = [
                    ResearchFinalizationOutcome(str(row["finalization_outcome"])) for row in canary
                ]
                blocked = [
                    outcome
                    for outcome in outcomes
                    if outcome in fleet.supervisor_policy.blocking_outcomes
                ]
                review_fraction = Decimal(
                    sum(outcome is ResearchFinalizationOutcome.NEEDS_REVIEW for outcome in outcomes)
                ) / Decimal(len(outcomes))
                contact_calls = await self._contact_request_count(conn, fleet.research_run_id)
                if (
                    blocked
                    or review_fraction > fleet.supervisor_policy.maximum_needs_review_fraction
                    or contact_calls
                ):
                    next_state = AccountResearchFleetState.SUSPENDED
                    diagnosis = {
                        "reason_code": "canary_health_gate_failed",
                        "blocking_outcomes": [value.value for value in blocked],
                        "needs_review_fraction": str(review_fraction),
                        "contact_research_request_count": contact_calls,
                    }
                    for row in held:
                        await conn.execute(
                            text(
                                "UPDATE entity_research_account_fleet_job_control SET "
                                "admission_state='paused', "
                                "pause_reason='canary_health_gate_failed', "
                                "updated_at=now() WHERE job_id=:job_id"
                            ),
                            {"job_id": row["job_id"]},
                        )
                else:
                    next_state = AccountResearchFleetState.OPEN
                    for row in held:
                        await conn.execute(
                            text(
                                "UPDATE entity_research_account_fleet_job_control SET "
                                "admission_state='released', updated_at=now() WHERE job_id=:job_id"
                            ),
                            {"job_id": row["job_id"]},
                        )
                        priority = int(
                            (
                                await conn.execute(
                                    text(
                                        "SELECT effective_priority FROM "
                                        "entity_research_account_fleet_job_control "
                                        "WHERE job_id=:job_id"
                                    ),
                                    {"job_id": row["job_id"]},
                                )
                            ).scalar_one()
                        )
                        await enqueue_task(
                            conn,
                            kind=FleetTaskKind.ENTITY_RESEARCH_JOB,
                            project_run_id=ProjectRunId(row["job_id"]),
                            dedup_key=str(row["job_id"]),
                            priority=priority,
                            payload={"job_id": str(row["job_id"])},
                            reopen_terminal=True,
                        )
                    await _event(
                        conn,
                        run_id=fleet.research_run_id,
                        actor="engine:account-fleet-supervisor",
                        action="open_remainder",
                        reason_code="canary_health_gate_passed",
                        before={"state": fleet.state.value, "held_jobs": len(held)},
                        after={"state": "open", "released_jobs": len(held)},
                    )
            elif not canary_terminal:
                runnable = any(
                    str(row["state"]) in {"queued", "leased", "running"}
                    and str(row["cohort"]) == "canary"
                    for row in canary
                )
                next_state = (
                    AccountResearchFleetState.CANARY
                    if runnable
                    else AccountResearchFleetState.WAITING_EXTERNAL
                )
            else:
                nonterminal = [row for row in rows if str(row["state"]) != "terminal"]
                next_state = (
                    AccountResearchFleetState.WAITING_EXTERNAL
                    if nonterminal
                    and all(str(row["state"]) == "waiting_external" for row in nonterminal)
                    else AccountResearchFleetState.OPEN
                )

        if next_state != fleet.state or diagnosis != fleet.diagnosis:
            await conn.execute(
                text(
                    "UPDATE entity_research_account_fleet SET state=:state, "
                    "diagnosis_json=CAST(:diagnosis AS jsonb), updated_at=now(), "
                    "suspended_at=CASE WHEN :state='suspended' THEN COALESCE(suspended_at,now()) "
                    "ELSE NULL END, terminal_at=CASE WHEN :state='terminal' THEN "
                    "COALESCE(terminal_at,now()) ELSE NULL END WHERE research_run_id=:run_id"
                ),
                {
                    "state": next_state.value,
                    "diagnosis": serialize_value_json(diagnosis),
                    "run_id": fleet.research_run_id,
                },
            )
            await _event(
                conn,
                run_id=fleet.research_run_id,
                actor="engine:account-fleet-supervisor",
                action="reconcile",
                reason_code=str(diagnosis.get("reason_code", "aggregate_state_changed")),
                before={"state": fleet.state.value},
                after={"state": next_state.value, "diagnosis": diagnosis},
            )
        projection = await self._projection(
            conn,
            fleet.research_run_id,
            workspace_id=fleet.workspace_id,
        )
        if next_state in {AccountResearchFleetState.SUSPENDED, AccountResearchFleetState.TERMINAL}:
            await self._persist_return(conn, projection)
        return projection

    async def _persist_return(
        self,
        conn: AsyncConnection,
        projection: AccountResearchFleetProjection,
    ) -> None:
        kind = (
            "terminal"
            if projection.fleet_state is AccountResearchFleetState.TERMINAL
            else "suspended"
        )
        payload = projection.model_dump(mode="json")
        digest = _sha(payload)
        return_id = uuid5(_RETURN_NAMESPACE, f"{projection.research_run_id}:{digest}")
        await conn.execute(
            text(
                "INSERT INTO entity_research_account_fleet_return "
                "(return_id, research_run_id, workspace_id, return_kind, payload_json, "
                "payload_sha256) VALUES (:return_id, :run_id, :workspace_id, :kind, "
                "CAST(:payload AS jsonb), :digest) ON CONFLICT DO NOTHING"
            ),
            {
                "return_id": return_id,
                "run_id": projection.research_run_id,
                "workspace_id": projection.workspace_id,
                "kind": kind,
                "payload": serialize_value_json(payload),
                "digest": digest,
            },
        )

    async def _projection(
        self,
        conn: AsyncConnection,
        research_run_id: UUID,
        *,
        workspace_id: str,
    ) -> AccountResearchFleetProjection:
        fleet = await _read_fleet(conn, research_run_id)
        if fleet is None or fleet.workspace_id != workspace_id:
            raise AccountResearchFleetError("account fleet is absent or cross-workspace")
        run = (
            (
                await conn.execute(
                    text(
                        "SELECT state, spent_cents, budget_cap_cents FROM entity_research_run "
                        "WHERE research_run_id=:run_id AND workspace_id=:workspace_id"
                    ),
                    {"run_id": research_run_id, "workspace_id": workspace_id},
                )
            )
            .mappings()
            .one()
        )
        rows = (
            (
                await conn.execute(
                    text(
                        """
                        SELECT job.job_id, control.account_run_id, job.subject_entity_id,
                               job.state, job.current_wait_ref,
                               job.finalization_outcome, job.finalization_receipt_ref,
                               job.spent_cents, control.cohort, control.admission_state,
                               control.effective_priority,
                               COALESCE(coverage.result_refs, ARRAY[]::text[]) AS result_refs,
                               COALESCE(coverage.committee_member_ids, ARRAY[]::uuid[])
                                   AS committee_member_ids
                        FROM entity_research_job job
                        JOIN entity_research_account_fleet_job_control control
                          ON control.job_id=job.job_id
                        LEFT JOIN LATERAL (
                            SELECT item.result_refs, item.committee_member_ids
                            FROM entity_research_account_coverage item
                            WHERE item.job_id=job.job_id
                            ORDER BY item.created_at DESC, item.coverage_id DESC LIMIT 1
                        ) coverage ON TRUE
                        WHERE job.research_run_id=:run_id
                        ORDER BY control.effective_priority, job.created_at, job.job_id
                        """
                    ),
                    {"run_id": research_run_id},
                )
            )
            .mappings()
            .all()
        )
        review_rows = (
            (
                await conn.execute(
                    text(
                        "SELECT review_item_id, job_id FROM "
                        "entity_research_account_review_item WHERE research_run_id=:run_id "
                        "AND workspace_id=:workspace_id AND state='open' "
                        "ORDER BY created_at, review_item_id"
                    ),
                    {"run_id": research_run_id, "workspace_id": workspace_id},
                )
            )
            .mappings()
            .all()
        )
        reviews_by_job: dict[UUID, list[str]] = {}
        for row in review_rows:
            reviews_by_job.setdefault(row["job_id"], []).append(
                f"account-review:{row['review_item_id']}"
            )
        jobs = tuple(
            AccountResearchJobSummary(
                job_id=row["job_id"],
                account_run_id=row["account_run_id"],
                account_entity_id=row["subject_entity_id"],
                cohort=row["cohort"],
                admission_state=row["admission_state"],
                effective_priority=int(row["effective_priority"]),
                job_state=row["state"],
                finalization_outcome=row["finalization_outcome"],
                finalization_receipt_ref=row["finalization_receipt_ref"],
                current_wait_ref=row["current_wait_ref"],
                spent_cents=Decimal(row["spent_cents"]),
                result_refs=tuple(str(value) for value in row["result_refs"]),
                committee_member_ids=tuple(row["committee_member_ids"]),
                review_item_refs=tuple(reviews_by_job.get(row["job_id"], ())),
            )
            for row in rows
        )

        def count(predicate: Callable[[AccountResearchJobSummary], bool]) -> int:
            return sum(predicate(job) for job in jobs)

        terminal = count(lambda job: job.job_state is ResearchJobState.TERMINAL)
        paused = count(lambda job: job.admission_state is AccountResearchAdmissionState.PAUSED)
        waiting = count(
            lambda job: (
                job.admission_state is not AccountResearchAdmissionState.PAUSED
                and job.job_state is ResearchJobState.WAITING_EXTERNAL
            )
        )
        active = count(
            lambda job: (
                job.admission_state is not AccountResearchAdmissionState.PAUSED
                and job.job_state in {ResearchJobState.LEASED, ResearchJobState.RUNNING}
            )
        )
        queued = len(jobs) - terminal - paused - waiting - active
        contact_calls = await self._contact_request_count(conn, research_run_id)
        return AccountResearchFleetProjection(
            research_run_id=research_run_id,
            workspace_id=fleet.workspace_id,
            project_id=fleet.project_id,
            product_id=fleet.product_id,
            project_run_id=fleet.project_run_id,
            fleet_state=fleet.state,
            run_state=str(run["state"]),
            selected_accounts=len(jobs),
            queued_accounts=queued,
            active_accounts=active,
            waiting_accounts=waiting,
            paused_accounts=paused,
            terminal_accounts=terminal,
            completed_accounts=count(
                lambda job: job.finalization_outcome is ResearchFinalizationOutcome.COMPLETED
            ),
            needs_review_accounts=count(
                lambda job: job.finalization_outcome is ResearchFinalizationOutcome.NEEDS_REVIEW
            ),
            spent_cents=Decimal(run["spent_cents"]),
            budget_cap_cents=Decimal(run["budget_cap_cents"]),
            jobs=jobs,
            review_queue=tuple(reference for job in jobs for reference in job.review_item_refs),
            contact_research_request_count=contact_calls,
            diagnosis=fleet.diagnosis,
        )

    @staticmethod
    async def _contact_request_count(conn: AsyncConnection, research_run_id: UUID) -> int:
        return int(
            (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM entity_research_tool_request "
                        "WHERE research_run_id=:run_id AND subject_type='contact'"
                    ),
                    {"run_id": research_run_id},
                )
            ).scalar_one()
        )


class AccountResearchFleetWorkHandler:
    """R6 admission/supervision wrapper around the unchanged R2/R5 work handler."""

    kind = FleetTaskKind.ENTITY_RESEARCH_JOB

    def __init__(
        self,
        *,
        inner: EntityResearchJobWorkHandler,
        fleets: AccountResearchFleetService,
    ) -> None:
        self._inner = inner
        self._fleets = fleets

    async def handle(self, context: WorkContext) -> WorkResult:
        raw_job_id = context.payload.get("job_id")
        if not isinstance(raw_job_id, str):
            raise EntityResearchJobError("account fleet work payload has no job_id")
        job_id = UUID(raw_job_id)
        research_run_id = await self._fleets.job_run_id(job_id)
        state = await self._fleets.admission_state(job_id)
        if state in {
            AccountResearchAdmissionState.HELD,
            AccountResearchAdmissionState.PAUSED,
            AccountResearchAdmissionState.TERMINAL,
        }:
            await self._fleets.park_unadmitted_claim(job_id, state=state)
            return WorkResult(
                outcome=state.value,
                references={"job_id": str(job_id)},
                task_finalized=True,
            )
        try:
            result = await self._inner.handle(context)
        except Exception as error:
            projection = await self._fleets.suspend_failure(context, error)
            return WorkResult(
                outcome="supervisor_suspended",
                references={
                    "job_id": str(job_id),
                    "research_run_id": str(projection.research_run_id),
                    "fleet_state": projection.fleet_state.value,
                },
                task_finalized=True,
            )
        projection = await self._fleets.reconcile(research_run_id)
        return WorkResult(
            outcome=result.outcome,
            references={
                **result.references,
                "research_run_id": str(projection.research_run_id),
                "account_fleet_state": projection.fleet_state.value,
            },
            requeue=result.requeue,
            task_finalized=result.task_finalized,
        )


__all__ = [
    "AccountResearchAdmissionState",
    "AccountResearchFleetCohort",
    "AccountResearchFleetError",
    "AccountResearchFleetPolicy",
    "AccountResearchFleetProjection",
    "AccountResearchFleetReturn",
    "AccountResearchFleetService",
    "AccountResearchFleetState",
    "AccountResearchFleetWorkHandler",
    "AccountResearchJobSummary",
]
