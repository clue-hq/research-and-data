"""Append-only, run-local supervisor controls and effective-state reads."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_config import SupervisorAutomaticAction, SupervisorPolicy
from clue_core import ExecutionId, OperationId, decode_jsonb, serialize_value_json
from clue_db import ConnFactory
from clue_execution.journal import DbExecutionJournal, get_cursor
from clue_execution.models import ControlAction, ControlKind, ExecutionEventType


class ControlPolicyViolation(ValueError):
    """A requested control exceeds the pinned supervisor/original execution authority."""


class ControlEvent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    seq: int
    execution_id: ExecutionId
    operation_id: UUID | None = None
    control_kind: ControlKind
    subject_ref: str
    action: ControlAction
    before: dict[str, JsonValue] = Field(default_factory=dict)
    after: dict[str, JsonValue] = Field(default_factory=dict)
    reason_code: str
    observation_id: UUID | None = None
    diagnosis_id: UUID | None = None
    actor: str
    created_at: datetime


class EffectiveEnvelope(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_nodes: int = Field(ge=1)
    max_depth: int = Field(ge=1)
    max_fanout: int = Field(ge=1)


_EVENT_COLUMNS = (
    "seq, execution_id, operation_id, control_kind, subject_ref, action, before_json, after_json, "
    "reason_code, observation_id, diagnosis_id, actor, created_at"
)


def _json_object(value: object) -> dict[str, JsonValue]:
    decoded = decode_jsonb(value)
    return cast(dict[str, JsonValue], decoded) if isinstance(decoded, dict) else {}


def _event(row: Mapping[str, object]) -> ControlEvent:
    return ControlEvent(
        seq=int(cast(int, row["seq"])),
        execution_id=ExecutionId(UUID(str(row["execution_id"]))),
        operation_id=(
            UUID(str(row["operation_id"])) if row.get("operation_id") is not None else None
        ),
        control_kind=ControlKind(str(row["control_kind"])),
        subject_ref=str(row["subject_ref"]),
        action=ControlAction(str(row["action"])),
        before=_json_object(row["before_json"]),
        after=_json_object(row["after_json"]),
        reason_code=str(row["reason_code"]),
        observation_id=(
            UUID(str(row["observation_id"])) if row.get("observation_id") is not None else None
        ),
        diagnosis_id=(
            UUID(str(row["diagnosis_id"])) if row.get("diagnosis_id") is not None else None
        ),
        actor=str(row["actor"]),
        created_at=cast(datetime, row["created_at"]),
    )


class DbRunControlStore:
    """The authoritative latest-event projection for run-local controls.

    The event history is append-only.  ``operation_id`` makes a tool retry after domain commit
    return the original event, while a latest-by-sequence read determines effective state.
    """

    def __init__(
        self,
        *,
        conn_factory: ConnFactory,
        journal: DbExecutionJournal,
        policy: SupervisorPolicy | None = None,
        policy_for: Callable[[str, str | None], SupervisorPolicy] | None = None,
    ) -> None:
        if (policy is None) == (policy_for is None):
            raise ValueError("supply exactly one of policy or policy_for")
        self._conn_factory = conn_factory
        self._journal = journal
        self._policy_for = policy_for or (
            lambda _workspace_id, _icp_key: cast(SupervisorPolicy, policy)
        )

    async def latest(
        self,
        execution_id: ExecutionId,
        control_kind: ControlKind,
        subject_ref: str,
    ) -> ControlEvent | None:
        async with self._conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            f"""
                            SELECT {_EVENT_COLUMNS}
                            FROM run_control_event
                            WHERE execution_id = :execution_id
                              AND control_kind = :kind
                              AND subject_ref = :subject
                            ORDER BY seq DESC
                            LIMIT 1
                            """
                        ),
                        {
                            "execution_id": execution_id,
                            "kind": control_kind.value,
                            "subject": subject_ref,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
        return _event(dict(row)) if row is not None else None

    async def account_allowed(self, execution_id: ExecutionId, account_id: str) -> bool:
        current = await self.latest(execution_id, ControlKind.ACCOUNT_QUARANTINE, account_id)
        return current is None or not bool(current.after.get("active"))

    async def source_allowed(self, execution_id: ExecutionId, source_key: str) -> bool:
        current = await self.latest(execution_id, ControlKind.SOURCE_BREAKER, source_key)
        return current is None or not bool(current.after.get("active"))

    async def effective_envelope(self, execution_id: ExecutionId) -> EffectiveEnvelope:
        async with self._conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT r.max_nodes, r.max_depth, r.max_fanout
                            FROM execution e
                            JOIN recipe_revision r ON r.id = e.recipe_revision_id
                            WHERE e.id = :execution_id
                            """
                        ),
                        {"execution_id": execution_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise ControlPolicyViolation("envelope controls require a recipe-backed execution")
        original = EffectiveEnvelope.model_validate(dict(row))
        current = await self.latest(execution_id, ControlKind.ENVELOPE, "runtime")
        if current is None or not bool(current.after.get("active")):
            return original
        return EffectiveEnvelope.model_validate(current.after["limits"])

    async def _active_subject_count(
        self,
        conn: AsyncConnection,
        *,
        execution_id: ExecutionId,
        kind: ControlKind,
    ) -> int:
        # ``conn`` is kept unannotated here to avoid widening the public constructor beyond the
        # repository's ConnFactory seam.
        result = await conn.execute(
            text(
                """
                SELECT count(*)
                FROM (
                    SELECT DISTINCT ON (subject_ref) after_json
                    FROM run_control_event
                    WHERE execution_id = :execution_id AND control_kind = :kind
                    ORDER BY subject_ref, seq DESC
                ) latest
                WHERE COALESCE((after_json->>'active')::boolean, false)
                """
            ),
            {"execution_id": execution_id, "kind": kind.value},
        )
        return int(result.scalar_one())

    async def mutate(
        self,
        *,
        workspace_id: str,
        execution_id: ExecutionId,
        operation_id: OperationId,
        control_kind: ControlKind,
        subject_ref: str,
        action: ControlAction,
        reason_code: str,
        actor: str,
        requested_after: dict[str, JsonValue] | None = None,
        observation_id: UUID | None = None,
        diagnosis_id: UUID | None = None,
    ) -> ControlEvent:
        if not subject_ref.strip() or not reason_code.strip():
            raise ControlPolicyViolation("control subject and reason code must be non-empty")
        if actor not in {"human", "agent", "system"}:
            raise ControlPolicyViolation("control actor is invalid")
        async with self._conn_factory() as conn:
            execution = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT e.workspace_id, r.icp_key
                            FROM execution e
                            LEFT JOIN project_run r ON r.id = e.project_run_id
                            WHERE e.id = :execution_id
                            FOR UPDATE OF e
                            """
                        ),
                        {"execution_id": execution_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if execution is None or str(execution["workspace_id"]) != workspace_id:
                raise ControlPolicyViolation("execution is absent or outside the workspace")
            policy = self._policy_for(
                workspace_id,
                str(execution["icp_key"]) if execution["icp_key"] is not None else None,
            )
            if actor == "agent" and SupervisorAutomaticAction(control_kind.value) not in set(
                policy.permitted_automatic_actions
            ):
                raise ControlPolicyViolation(f"{control_kind.value} is not permitted automatically")

            replay = (
                (
                    await conn.execute(
                        text(
                            f"""
                            SELECT {_EVENT_COLUMNS}
                            FROM run_control_event
                            WHERE execution_id = :execution_id AND operation_id = :operation_id
                            """
                        ),
                        {"execution_id": execution_id, "operation_id": operation_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if replay is not None:
                event = _event(dict(replay))
                if (
                    event.control_kind is not control_kind
                    or event.subject_ref != subject_ref
                    or event.action is not action
                ):
                    raise ControlPolicyViolation(
                        "operation id was replayed with a different control mutation"
                    )
                return event

            if observation_id is not None:
                owner = (
                    await conn.execute(
                        text("SELECT execution_id FROM supervisor_observation WHERE id = :id"),
                        {"id": observation_id},
                    )
                ).scalar_one_or_none()
                if owner is None or str(owner) != str(execution_id):
                    raise ControlPolicyViolation("observation does not belong to the execution")
            if diagnosis_id is not None:
                owner = (
                    await conn.execute(
                        text(
                            """
                            SELECT o.execution_id
                            FROM supervisor_diagnosis d
                            JOIN supervisor_observation o ON o.id = d.observation_id
                            WHERE d.id = :id
                            """
                        ),
                        {"id": diagnosis_id},
                    )
                ).scalar_one_or_none()
                if owner is None or str(owner) != str(execution_id):
                    raise ControlPolicyViolation("diagnosis does not belong to the execution")

            current_row = (
                (
                    await conn.execute(
                        text(
                            f"""
                            SELECT {_EVENT_COLUMNS}
                            FROM run_control_event
                            WHERE execution_id = :execution_id
                              AND control_kind = :kind
                              AND subject_ref = :subject
                            ORDER BY seq DESC
                            LIMIT 1
                            """
                        ),
                        {
                            "execution_id": execution_id,
                            "kind": control_kind.value,
                            "subject": subject_ref,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
            before: dict[str, JsonValue] = (
                _event(dict(current_row)).after if current_row is not None else {"active": False}
            )
            after = await self._validated_after(
                conn,
                execution_id=execution_id,
                control_kind=control_kind,
                subject_ref=subject_ref,
                action=action,
                actor=actor,
                before=before,
                requested=requested_after or {},
                policy=policy,
                current_created_at=(
                    cast(datetime, current_row["created_at"]) if current_row is not None else None
                ),
            )
            row = (
                (
                    await conn.execute(
                        text(
                            f"""
                            INSERT INTO run_control_event (
                                execution_id, workspace_id, operation_id, control_kind, subject_ref,
                                action, before_json, after_json, reason_code, observation_id,
                                diagnosis_id, actor
                            ) VALUES (
                                :execution_id, :workspace_id, :operation_id, :kind, :subject,
                                :action, CAST(:before AS jsonb), CAST(:after AS jsonb), :reason,
                                :observation_id, :diagnosis_id, :actor
                            )
                            RETURNING {_EVENT_COLUMNS}
                            """
                        ),
                        {
                            "execution_id": execution_id,
                            "workspace_id": workspace_id,
                            "operation_id": operation_id,
                            "kind": control_kind.value,
                            "subject": subject_ref,
                            "action": action.value,
                            "before": serialize_value_json(before),
                            "after": serialize_value_json(after),
                            "reason": reason_code,
                            "observation_id": observation_id,
                            "diagnosis_id": diagnosis_id,
                            "actor": actor,
                        },
                    )
                )
                .mappings()
                .one()
            )
            cursor = await get_cursor(conn, execution_id)
            await self._journal.append_event(
                conn,
                execution_id=execution_id,
                event_type=ExecutionEventType.SUPERVISOR_ACTIONED,
                actor=actor,
                payload={
                    "control_kind": control_kind.value,
                    "subject_ref": subject_ref,
                    "action": action.value,
                    "reason_code": reason_code,
                    "observation_id": str(observation_id) if observation_id else None,
                    "diagnosis_id": str(diagnosis_id) if diagnosis_id else None,
                },
                expected_state_version=cursor.state_version,
            )
            return _event(dict(row))

    async def _validated_after(
        self,
        conn: AsyncConnection,
        *,
        execution_id: ExecutionId,
        control_kind: ControlKind,
        subject_ref: str,
        action: ControlAction,
        actor: str,
        before: dict[str, JsonValue],
        requested: dict[str, JsonValue],
        policy: SupervisorPolicy,
        current_created_at: datetime | None,
    ) -> dict[str, JsonValue]:
        if control_kind is ControlKind.ENVELOPE:
            if subject_ref != "runtime":
                raise ControlPolicyViolation("the envelope subject must be 'runtime'")
            if action is ControlAction.RELEASE:
                if actor != "human":
                    raise ControlPolicyViolation("only a human may relax an envelope")
                return {"active": False}
            if action is not ControlAction.APPLY:
                raise ControlPolicyViolation("an envelope accepts apply or human release")
            limits_raw = requested.get("limits")
            if not isinstance(limits_raw, dict):
                raise ControlPolicyViolation("an envelope apply requires a limits object")
            proposed = EffectiveEnvelope.model_validate(limits_raw)
            original_row = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT r.max_nodes, r.max_depth, r.max_fanout
                            FROM execution e
                            JOIN recipe_revision r ON r.id = e.recipe_revision_id
                            WHERE e.id = :execution_id
                            """
                        ),
                        {"execution_id": execution_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if original_row is None:
                raise ControlPolicyViolation("envelope controls require a recipe-backed execution")
            original = EffectiveEnvelope.model_validate(dict(original_row))
            current = (
                EffectiveEnvelope.model_validate(before["limits"])
                if bool(before.get("active")) and isinstance(before.get("limits"), dict)
                else original
            )
            for name in ("max_nodes", "max_depth", "max_fanout"):
                if getattr(proposed, name) > getattr(current, name):
                    raise ControlPolicyViolation("automatic envelope changes may only tighten")
                floor = max(
                    1,
                    int(getattr(original, name) * (1.0 - policy.max_envelope_reduction_fraction)),
                )
                if actor == "agent" and getattr(proposed, name) < floor:
                    raise ControlPolicyViolation(
                        "automatic envelope tightening exceeds the policy scope"
                    )
            return {"active": True, "limits": proposed.model_dump(mode="json")}

        if control_kind is ControlKind.ESCALATION:
            if action is ControlAction.APPLY:
                return {"active": True}
            if action is ControlAction.ACKNOWLEDGE:
                return {"active": False, "acknowledged": True}
            raise ControlPolicyViolation("escalation accepts apply or acknowledge")

        if action not in {ControlAction.APPLY, ControlAction.RELEASE}:
            raise ControlPolicyViolation("account/source controls accept apply or release")
        if action is ControlAction.RELEASE:
            if (
                control_kind is ControlKind.SOURCE_BREAKER
                and actor == "agent"
                and current_created_at is not None
            ):
                elapsed = (datetime.now(UTC) - current_created_at).total_seconds()
                if elapsed < policy.breaker_cooldown_s:
                    raise ControlPolicyViolation("source-breaker cooldown has not elapsed")
            return {"active": False}

        limit = (
            policy.max_quarantined_accounts
            if control_kind is ControlKind.ACCOUNT_QUARANTINE
            else policy.max_source_breakers
        )
        already_active = bool(before.get("active"))
        if not already_active:
            active = await self._active_subject_count(
                conn, execution_id=execution_id, kind=control_kind
            )
            if active >= limit:
                raise ControlPolicyViolation(f"{control_kind.value} automatic scope is exhausted")
        return {"active": True}


__all__ = [
    "ControlEvent",
    "ControlPolicyViolation",
    "DbRunControlStore",
    "EffectiveEnvelope",
]
