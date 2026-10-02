"""M8D R9 atomic tool-batch admission, partial results, and exact external-wait joining."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from decimal import Decimal
from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid5

from langchain_core.messages import ToolMessage
from pydantic import BaseModel, JsonValue
from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.entity_research_contracts import (
    EntityResearchRuntimeContext,
    EntityResearchToolCall,
    canonical_sha256,
)
from clue_agents.entity_research_runtime import (
    EntityResearchExternalWait,
    EntityResearchGovernedToolRefusal,
    EntityResearchToolBatchCoordinator,
    EntityResearchToolReplay,
)
from clue_api.entity_research_tools import field_key_on_subject_axis
from clue_core import serialize_value_json
from clue_core.entity_research import ResearchJobState
from clue_db import ConnFactory, transaction
from clue_fleet import (
    DbEntityResearchJobStore,
    EntityResearchExecutionFence,
    EntityResearchJobRow,
    wake_entity_research_job,
)

_BATCH_NAMESPACE = uuid5(NAMESPACE_URL, "clue:m8d:r9:tool-batch")
_RESERVATION_NAMESPACE = uuid5(NAMESPACE_URL, "clue:m8d:r9:budget-reservation")
_PERMIT_NAMESPACE = uuid5(NAMESPACE_URL, "clue:m8d:r9:provider-permit")
_EVENT_NAMESPACE = uuid5(NAMESPACE_URL, "clue:m8d:r9:batch-event")
_WAIT_NAMESPACE = uuid5(NAMESPACE_URL, "clue:m8d:r9:batch-wait")


class EntityResearchParallelAdmissionError(RuntimeError):
    """A batch cannot safely execute under its exact dependencies, limits, or budget."""


class EntityResearchParallelRoundShapeRefusal(
    EntityResearchParallelAdmissionError, EntityResearchGovernedToolRefusal
):
    """The model's *wave shape* is inadmissible — repairable, and never a dead job.

    ``_validate_batch`` runs before any row is written, any budget is reserved and any provider is
    touched: it only reads the calls the model just proposed. Refusing one is therefore the same
    species as any other guard refusal (R10) — the model re-plans its round — while every other
    admission failure (budget, provider concurrency, replayed identity, missing member) remains an
    ordinary suspending error because those are facts about durable state, not about the wave.
    Kept a subclass of the admission error so existing callers and tests that catch the family are
    unaffected.
    """

    def __init__(self, detail: str) -> None:
        EntityResearchGovernedToolRefusal.__init__(
            self, detail, code="parallel_round_shape_rejected"
        )


@dataclass(frozen=True, slots=True)
class _MemberPlan:
    call: EntityResearchToolCall
    reservation_id: UUID | None
    permit_id: UUID | None
    joined_result: dict[str, JsonValue] | None = None
    joined_result_sha256: str | None = None


def _json_object(value: object) -> dict[str, JsonValue]:
    if isinstance(value, ToolMessage):
        value = value.content
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError as error:
                raise EntityResearchParallelAdmissionError(
                    "entity research tool message must contain a JSON object"
                ) from error
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", exclude_none=False)
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=str,
    )
    decoded = json.loads(encoded)
    if not isinstance(decoded, dict):
        raise EntityResearchParallelAdmissionError("entity research tool result must be an object")
    return cast(dict[str, JsonValue], decoded)


def _field_values(call: EntityResearchToolCall) -> tuple[str, ...]:
    values = call.arguments.get("field_keys", ())
    return tuple(str(value) for value in values) if isinstance(values, (list, tuple)) else ()


def _source_values(call: EntityResearchToolCall) -> tuple[str, ...]:
    values = call.arguments.get("source_keys", ())
    return tuple(str(value) for value in values) if isinstance(values, (list, tuple)) else ()


def _facet_value(call: EntityResearchToolCall) -> str | None:
    value = call.arguments.get("facet_key")
    return str(value) if isinstance(value, str) and value else None


def _result_subjects(value: object) -> set[tuple[str, UUID]]:
    """Index every structured entity projection whose value is duplicated for cold joining."""

    found: set[tuple[str, UUID]] = set()
    if isinstance(value, Mapping):
        subject_type = value.get("subject_type")
        target = value.get("target_entity_id")
        if subject_type in {"account", "contact"} and target is not None:
            with suppress(ValueError):
                found.add((str(subject_type), UUID(str(target))))
        for nested in value.values():
            found.update(_result_subjects(nested))
    elif isinstance(value, (list, tuple)):
        for nested in value:
            found.update(_result_subjects(nested))
    return found


def _batch_payload(
    context: EntityResearchRuntimeContext,
    calls: Sequence[EntityResearchToolCall],
) -> dict[str, JsonValue]:
    return {
        "contract": "m8d-r9-tool-batch-v1",
        "agent_turn_id": str(context.agent_turn_id),
        "agent_execution_id": str(context.agent_execution_id),
        "research_run_id": str(context.authorization.research_run_id),
        "job_id": str(context.authorization.job_id),
        "subject_type": context.authorization.subject_type.value,
        "target_entity_id": str(context.authorization.subject_entity_id),
        "concurrency_cap": context.stop_policy.max_parallel_tools,
        "calls": [call.model_dump(mode="json", exclude_none=False) for call in calls],
        "wait_policy": "persist_release_slot_resume_same_checkpoint",
    }


class DbEntityResearchToolBatchCoordinator(EntityResearchToolBatchCoordinator):
    """Serialize admission at job/run/provider scope before any concurrent handler dispatch.

    ``enforce_budget`` is the FI pilot budget-controls switch, threaded from ``Settings`` at the
    fleet composition roots (never read globally here — the coordinator stays injectable). With it
    False the job/run cap comparison in :meth:`_check_budget` no longer *refuses* a batch, and
    nothing else changes: the reservation, permit, and settlement rows are written exactly as they
    are with it True, so a pilot deployment's spend is recorded honestly and simply exceeds the cap
    instead of being stopped. Provider concurrency/rate limits are not money and stay enforced.
    """

    def __init__(
        self,
        *,
        conn_factory: ConnFactory = transaction,
        sibling_poll_seconds: float = 0.01,
        enforce_budget: bool = True,
    ) -> None:
        if sibling_poll_seconds <= 0:
            raise ValueError("parallel sibling poll interval must be positive")
        self._conn_factory = conn_factory
        self._sibling_poll_seconds = sibling_poll_seconds
        self._enforce_budget = enforce_budget

    async def admit(
        self,
        *,
        context: EntityResearchRuntimeContext,
        calls: Sequence[EntityResearchToolCall],
    ) -> None:
        self._validate_batch(context, calls)
        payload = _batch_payload(context, calls)
        batch_sha = canonical_sha256(payload)
        batch_id = uuid5(_BATCH_NAMESPACE, f"{context.agent_turn_id}:{batch_sha}")
        async with self._conn_factory() as conn:
            scope = await self._lock_scope(conn, context)
            existing = (
                (
                    await conn.execute(
                        text(
                            "SELECT batch_sha256, batch_json FROM entity_research_tool_batch "
                            "WHERE batch_id=:batch_id"
                        ),
                        {"batch_id": batch_id},
                    )
                )
                .mappings()
                .first()
            )
            if existing is not None:
                if (
                    str(existing["batch_sha256"]) != batch_sha
                    or canonical_sha256(existing["batch_json"]) != batch_sha
                ):
                    raise EntityResearchParallelAdmissionError(
                        "tool batch identity replayed with different authority"
                    )
                return

            external = [call for call in calls if call.provider_family is not None]
            for rate_ref in sorted({cast(str, call.provider_rate_limit_ref) for call in external}):
                await conn.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:value, 0))"),
                    {"value": rate_ref},
                )

            plans: list[_MemberPlan] = []
            new_reservations: list[tuple[UUID, EntityResearchToolCall]] = []
            new_permits: list[tuple[UUID, EntityResearchToolCall]] = []
            for call in calls:
                joined = (
                    await self._prior_completed(conn, context=context, call=call)
                    if call.provider_family is not None
                    else None
                )
                if joined is not None:
                    joined_reservation_id = cast(UUID | None, joined["budget_reservation_id"])
                    self._assert_joined_metadata(call, joined)
                    plans.append(
                        _MemberPlan(
                            call=call,
                            reservation_id=joined_reservation_id,
                            permit_id=None,
                            joined_result=cast(dict[str, JsonValue], joined["result_json"]),
                            joined_result_sha256=str(joined["result_sha256"]),
                        )
                    )
                    continue
                reservation_id: UUID | None = None
                permit_id: UUID | None = None
                if call.provider_family is not None:
                    active = await self._active_reservation(
                        conn,
                        context=context,
                        call=call,
                    )
                    if active is not None:
                        self._assert_reservation_metadata(call, active)
                        reservation_id = UUID(str(active["reservation_id"]))
                    else:
                        reservation_id = uuid5(
                            _RESERVATION_NAMESPACE,
                            f"{batch_id}:{call.tool_call_id}",
                        )
                        new_reservations.append((reservation_id, call))
                    if active is None or not bool(active["has_active_permit"]):
                        permit_id = uuid5(_PERMIT_NAMESPACE, f"{batch_id}:{call.tool_call_id}")
                        new_permits.append((permit_id, call))
                plans.append(
                    _MemberPlan(
                        call=call,
                        reservation_id=reservation_id,
                        permit_id=permit_id,
                    )
                )

            await self._check_budget(
                conn,
                context=context,
                scope=scope,
                new_reservations=new_reservations,
            )
            await self._check_provider_limits(conn, new_permits)
            await conn.execute(
                text(
                    """
                    INSERT INTO entity_research_tool_batch
                        (batch_id, agent_turn_id, agent_execution_id, research_run_id, job_id,
                         subject_type, target_entity_id, workspace_id, concurrency_cap,
                         call_count, batch_json, batch_sha256)
                    VALUES
                        (:batch_id, :turn_id, :execution_id, :run_id, :job_id, :subject_type,
                         :target_id, :workspace_id, :cap, :count, CAST(:payload AS jsonb), :sha)
                    """
                ),
                {
                    "batch_id": batch_id,
                    "turn_id": context.agent_turn_id,
                    "execution_id": context.agent_execution_id,
                    "run_id": context.authorization.research_run_id,
                    "job_id": context.authorization.job_id,
                    "subject_type": context.authorization.subject_type.value,
                    "target_id": context.authorization.subject_entity_id,
                    "workspace_id": context.authorization.workspace_id,
                    "cap": context.stop_policy.max_parallel_tools,
                    "count": len(calls),
                    "payload": serialize_value_json(payload),
                    "sha": batch_sha,
                },
            )
            for reservation_id, call in new_reservations:
                await self._insert_reservation(
                    conn,
                    context=context,
                    reservation_id=reservation_id,
                    call=call,
                )
            for plan in plans:
                await self._insert_member(conn, batch_id=batch_id, plan=plan)
                if plan.permit_id is not None:
                    await self._insert_permit(
                        conn,
                        context=context,
                        batch_id=batch_id,
                        permit_id=plan.permit_id,
                        call=plan.call,
                    )
                if plan.joined_result is not None:
                    assert plan.joined_result_sha256 is not None
                    await self._insert_event(
                        conn,
                        batch_id=batch_id,
                        call=plan.call,
                        event_kind="completed",
                        disposition="joined_settled_result",
                        result=plan.joined_result,
                        result_sha256=plan.joined_result_sha256,
                    )

    async def replay(
        self,
        *,
        context: EntityResearchRuntimeContext,
        call: EntityResearchToolCall,
    ) -> EntityResearchToolReplay:
        async with self._conn_factory() as conn:
            member = await self._member(conn, context=context, call=call)
            event = (
                (
                    await conn.execute(
                        text(
                            "SELECT result_json, result_sha256 FROM "
                            "entity_research_tool_batch_event WHERE batch_id=:batch_id AND "
                            "raw_tool_call_id=:call_id AND event_kind='completed' AND "
                            "result_erased_at IS NULL"
                        ),
                        {"batch_id": member["batch_id"], "call_id": call.tool_call_id},
                    )
                )
                .mappings()
                .first()
            )
        if event is None:
            return EntityResearchToolReplay(found=False)
        result = cast(dict[str, JsonValue], event["result_json"])
        if canonical_sha256(result) != str(event["result_sha256"]):
            raise EntityResearchParallelAdmissionError("joined tool result digest changed")
        return EntityResearchToolReplay(found=True, result=result)

    async def completed(
        self,
        *,
        context: EntityResearchRuntimeContext,
        call: EntityResearchToolCall,
        result: object,
    ) -> None:
        result_json = _json_object(result)
        result_sha = canonical_sha256(result_json)
        async with self._conn_factory() as conn:
            member = await self._member(conn, context=context, call=call)
            event_id = await self._insert_event(
                conn,
                batch_id=UUID(str(member["batch_id"])),
                call=call,
                event_kind="completed",
                disposition="settled",
                result=result_json,
                result_sha256=result_sha,
            )
            await self._release_permit(
                conn,
                batch_id=UUID(str(member["batch_id"])),
                call=call,
                event_id=event_id,
                disposition="completed",
            )
            reservation_id = member["budget_reservation_id"]
            if reservation_id is not None:
                reserved = Decimal(str(member["budget_reservation_cents"]))
                settled = self._settled_cost(call, result_json)
                if settled > reserved:
                    raise EntityResearchParallelAdmissionError(
                        "settled provider cost exceeds its atomic reservation"
                    )
                await self._release_budget(
                    conn,
                    reservation_id=UUID(str(reservation_id)),
                    event_id=event_id,
                    disposition="settled",
                    settled_cost=settled,
                )

    async def waiting(
        self,
        *,
        context: EntityResearchRuntimeContext,
        call: EntityResearchToolCall,
        wait: EntityResearchExternalWait,
    ) -> EntityResearchExternalWait:
        async with self._conn_factory() as conn:
            member = await self._member(conn, context=context, call=call)
            batch_id = UUID(str(member["batch_id"]))
            event_id = await self._insert_event(
                conn,
                batch_id=batch_id,
                call=call,
                event_kind="waiting_external",
                disposition="durable_external_wait",
                member_wait_ref=wait.wait_ref,
            )
            await self._release_permit(
                conn,
                batch_id=batch_id,
                call=call,
                event_id=event_id,
                disposition="waiting_external",
            )

        waiting_refs = await self._await_siblings(batch_id)
        composite_id = uuid5(_WAIT_NAMESPACE, f"{batch_id}:{canonical_sha256(waiting_refs)}")
        composite_ref = f"entity-research-batch-wait:{composite_id}"
        async with self._conn_factory() as conn:
            batch = (
                (
                    await conn.execute(
                        text(
                            "SELECT research_run_id, job_id FROM entity_research_tool_batch "
                            "WHERE batch_id=:batch_id"
                        ),
                        {"batch_id": batch_id},
                    )
                )
                .mappings()
                .one()
            )
            await conn.execute(
                text(
                    """
                    INSERT INTO entity_research_tool_batch_wait
                        (batch_id, wait_ref, research_run_id, job_id, member_wait_refs)
                    VALUES (:batch_id, :wait_ref, :run_id, :job_id, :member_wait_refs)
                    ON CONFLICT (batch_id) DO NOTHING
                    """
                ),
                {
                    "batch_id": batch_id,
                    "wait_ref": composite_ref,
                    "run_id": batch["research_run_id"],
                    "job_id": batch["job_id"],
                    "member_wait_refs": list(waiting_refs),
                },
            )
            stored = (
                (
                    await conn.execute(
                        text(
                            "SELECT wait_ref, member_wait_refs FROM "
                            "entity_research_tool_batch_wait WHERE batch_id=:batch_id"
                        ),
                        {"batch_id": batch_id},
                    )
                )
                .mappings()
                .one()
            )
            if (
                str(stored["wait_ref"]) != composite_ref
                or tuple(str(value) for value in stored["member_wait_refs"]) != waiting_refs
            ):
                raise EntityResearchParallelAdmissionError("batch wait replay changed")
            for member_wait_ref in waiting_refs:
                await conn.execute(
                    text(
                        "INSERT INTO entity_research_tool_batch_wait_member "
                        "(batch_id, member_wait_ref) VALUES (:batch_id, :member_wait_ref) "
                        "ON CONFLICT DO NOTHING"
                    ),
                    {"batch_id": batch_id, "member_wait_ref": member_wait_ref},
                )
            state_sha = (
                await conn.execute(
                    text(
                        "SELECT current_state_sha256 FROM entity_research_job WHERE job_id=:job_id"
                    ),
                    {"job_id": batch["job_id"]},
                )
            ).scalar_one()
        return EntityResearchExternalWait(
            wait_ref=composite_ref,
            current_state_sha256=str(state_sha),
        )

    async def failed(
        self,
        *,
        context: EntityResearchRuntimeContext,
        call: EntityResearchToolCall,
        error: BaseException,
    ) -> None:
        async with self._conn_factory() as conn:
            member = await self._member(conn, context=context, call=call)
            batch_id = UUID(str(member["batch_id"]))
            prior_failure_id = (
                await conn.execute(
                    text(
                        "SELECT event_id FROM entity_research_tool_batch_event "
                        "WHERE batch_id=:batch_id AND raw_tool_call_id=:call_id "
                        "AND event_kind='failed'"
                    ),
                    {"batch_id": batch_id, "call_id": call.tool_call_id},
                )
            ).scalar_one_or_none()
            if prior_failure_id is None:
                event_id = await self._insert_event(
                    conn,
                    batch_id=batch_id,
                    call=call,
                    event_kind="failed",
                    disposition="handler_failed",
                    error={
                        "error_type": type(error).__name__,
                        "message": str(error)[:2000],
                    },
                )
            else:
                # A checkpoint retry can re-enter the same admitted tool call after its first
                # handler failure. The batch ledger intentionally has one immutable ``failed``
                # marker per member; retry-specific errors remain append-only in the agent-event
                # journal, and a later ``completed`` event supersedes this marker for settlement.
                # Requiring a later exception to equal the first one masks the real retry error
                # as "tool batch event replay changed" and prevents safe retained-response
                # recovery from ever reaching completion.
                event_id = UUID(str(prior_failure_id))
            await self._release_permit(
                conn,
                batch_id=batch_id,
                call=call,
                event_id=event_id,
                disposition="failed",
            )
            reservation_id = member["budget_reservation_id"]
            if reservation_id is not None and not await self._reservation_was_dispatched_or_waiting(
                conn,
                reservation_id=UUID(str(reservation_id)),
            ):
                await self._release_budget(
                    conn,
                    reservation_id=UUID(str(reservation_id)),
                    event_id=event_id,
                    disposition="failed_before_dispatch",
                    settled_cost=Decimal(0),
                )

    @staticmethod
    def _validate_batch(
        context: EntityResearchRuntimeContext,
        calls: Sequence[EntityResearchToolCall],
    ) -> None:
        if not calls:
            raise EntityResearchParallelAdmissionError("tool batch exceeds its concurrency cap")
        if len(calls) > context.stop_policy.max_parallel_tools:
            raise EntityResearchParallelRoundShapeRefusal("tool batch exceeds its concurrency cap")
        identities = [call.tool_call_id for call in calls]
        if len(identities) != len(set(identities)):
            raise EntityResearchParallelRoundShapeRefusal("tool batch call ids must be unique")
        if len(calls) > 1 and any(
            call.arguments.get("parent_operation_ref") is not None for call in calls
        ):
            raise EntityResearchParallelRoundShapeRefusal(
                "additive follow-up is dependent and cannot share a parallel batch"
            )
        fields: dict[str, str] = {}
        for call in calls:
            for field_key in _field_values(call):
                if not field_key_on_subject_axis(context.authorization.subject_type, field_key):
                    raise EntityResearchParallelRoundShapeRefusal(
                        "parallel tool call contains a cross-axis field"
                    )
                previous = fields.setdefault(field_key, call.tool_call_id)
                if previous != call.tool_call_id:
                    raise EntityResearchParallelRoundShapeRefusal(
                        "parallel field overlap lacks explicit corroboration authority"
                    )
        grouped: dict[str, list[EntityResearchToolCall]] = {}
        for call in calls:
            grouped.setdefault(call.tool_name, []).append(call)
        for name, duplicates in grouped.items():
            if len(duplicates) < 2:
                continue
            if all(
                call.provider_family is None
                and not _source_values(call)
                and not _field_values(call)
                for call in duplicates
            ):
                # Not provider work at all: a repeated read tool buys nothing, reserves nothing and
                # partitions nothing. It has no source keys either, so the disjoint-partition test
                # below would refuse it as "duplicate provider work" — which is how a live round
                # holding two persisted-result reads suspended its job. All three conditions are
                # required together so an unbound provider call can never slip through this door.
                continue
            facets = {_facet_value(call) for call in duplicates}
            if (
                name in {"delegate_account_facet", "delegate_contact_facet"}
                and None not in facets
                and len(facets) == len(duplicates)
            ):
                continue
            source_sets = [set(_source_values(call)) for call in duplicates]
            if all(source_sets) and not any(
                left & right
                for index, left in enumerate(source_sets)
                for right in source_sets[index + 1 :]
            ):
                continue
            raise EntityResearchParallelRoundShapeRefusal(
                "duplicate parallel provider work is not independently partitioned"
            )

    @staticmethod
    async def _lock_scope(
        conn: AsyncConnection,
        context: EntityResearchRuntimeContext,
    ) -> RowMapping:
        row = (
            (
                await conn.execute(
                    text(
                        """
                        SELECT job.state AS job_state, job.spent_cents AS job_spent,
                               job.budget_cap_cents AS job_cap,
                               job.budget_envelope_ref AS job_budget_ref,
                               run.spent_cents AS run_spent, run.budget_cap_cents AS run_cap
                        FROM entity_research_run run JOIN entity_research_job job
                          ON job.research_run_id=run.research_run_id
                        WHERE job.job_id=:job_id AND run.research_run_id=:run_id
                          AND job.workspace_id=:workspace_id
                        FOR UPDATE OF run, job
                        """
                    ),
                    {
                        "job_id": context.authorization.job_id,
                        "run_id": context.authorization.research_run_id,
                        "workspace_id": context.authorization.workspace_id,
                    },
                )
            )
            .mappings()
            .first()
        )
        if row is None or str(row["job_state"]) != ResearchJobState.RUNNING.value:
            raise EntityResearchParallelAdmissionError(
                "tool batch lacks the exact running job authority"
            )
        return row

    async def _check_budget(
        self,
        conn: AsyncConnection,
        *,
        context: EntityResearchRuntimeContext,
        scope: RowMapping,
        new_reservations: Sequence[tuple[UUID, EntityResearchToolCall]],
    ) -> None:
        # A pure replay/resume wave introduces no new spend exposure. The original admission
        # already reserved its worst-case cost atomically; meanwhile the provider settlement
        # path may have folded actual spend into the job/run before the tool result event was
        # recorded. Re-applying ``spent + active reservation`` here would double-count that
        # one operation and strand its exact recovery at a tight cap. Mixed waves still take
        # the conservative path below because they contain genuinely new reservations.
        if not new_reservations:
            return
        # FI pilot budget-controls (ratified 2026-08-11): enforcement off means *record-only*.
        # Skipping only the comparison below lets ``admit`` fall through to the batch, reservation,
        # permit, and member writes it always makes, so the wave executes and its worst-case cost
        # is still reserved and later settled — the spend record is complete and simply exceeds the
        # cap honestly. Deliberately placed after the no-new-reservations short-circuit so both
        # modes agree about which waves are new.
        if not self._enforce_budget:
            return
        active_job = Decimal(
            str(
                (
                    await conn.execute(
                        text(
                            "SELECT COALESCE(sum(reserved.reserved_cents), 0) FROM "
                            "entity_research_budget_reservation reserved LEFT JOIN "
                            "entity_research_budget_reservation_release release USING "
                            "(reservation_id) WHERE reserved.job_id=:job_id AND "
                            "release.reservation_id IS NULL"
                        ),
                        {"job_id": context.authorization.job_id},
                    )
                ).scalar_one()
            )
        )
        active_run = Decimal(
            str(
                (
                    await conn.execute(
                        text(
                            "SELECT COALESCE(sum(reserved.reserved_cents), 0) FROM "
                            "entity_research_budget_reservation reserved LEFT JOIN "
                            "entity_research_budget_reservation_release release USING "
                            "(reservation_id) WHERE reserved.research_run_id=:run_id AND "
                            "release.reservation_id IS NULL"
                        ),
                        {"run_id": context.authorization.research_run_id},
                    )
                ).scalar_one()
            )
        )
        requested = sum(
            (call.budget_reservation_cents for _, call in new_reservations),
            Decimal(0),
        )
        if Decimal(str(scope["job_spent"])) + active_job + requested > Decimal(
            str(scope["job_cap"])
        ):
            raise EntityResearchParallelAdmissionError(
                "atomic tool batch exceeds the exact job budget"
            )
        if Decimal(str(scope["run_spent"])) + active_run + requested > Decimal(
            str(scope["run_cap"])
        ):
            raise EntityResearchParallelAdmissionError(
                "atomic tool batch exceeds the exact research-run budget"
            )

    @staticmethod
    async def _check_provider_limits(
        conn: AsyncConnection,
        permits: Sequence[tuple[UUID, EntityResearchToolCall]],
    ) -> None:
        grouped: dict[str, list[EntityResearchToolCall]] = {}
        for _, call in permits:
            grouped.setdefault(cast(str, call.provider_rate_limit_ref), []).append(call)
        for rate_ref, calls in grouped.items():
            limits = {cast(int, call.provider_concurrency_limit) for call in calls}
            if len(limits) != 1:
                raise EntityResearchParallelAdmissionError(
                    "one provider rate-limit policy resolved conflicting limits"
                )
            limit = limits.pop()
            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT count(*) AS active, "
                            "array_agg(DISTINCT permit.concurrency_limit) "
                            "AS limits FROM entity_research_provider_permit permit LEFT JOIN "
                            "entity_research_provider_permit_release release USING (permit_id) "
                            "WHERE permit.provider_rate_limit_ref=:rate_ref AND "
                            "release.permit_id IS NULL"
                        ),
                        {"rate_ref": rate_ref},
                    )
                )
                .mappings()
                .one()
            )
            observed = {int(value) for value in (row["limits"] or ())}
            if observed and observed != {limit}:
                raise EntityResearchParallelAdmissionError(
                    "provider concurrency policy changed while permits are active"
                )
            if int(row["active"]) + len(calls) > limit:
                raise EntityResearchParallelAdmissionError(
                    f"provider concurrency limit is exhausted for {rate_ref}"
                )

    @staticmethod
    async def _insert_reservation(
        conn: AsyncConnection,
        *,
        context: EntityResearchRuntimeContext,
        reservation_id: UUID,
        call: EntityResearchToolCall,
    ) -> None:
        await conn.execute(
            text(
                """
                INSERT INTO entity_research_budget_reservation
                    (reservation_id, research_run_id, job_id, workspace_id,
                     budget_envelope_ref, tool_name, tool_input_sha256, provider_family,
                     reserved_cents)
                VALUES (:reservation_id, :run_id, :job_id, :workspace_id, :budget_ref,
                        :tool_name, :input_sha, :provider_family, :reserved)
                """
            ),
            {
                "reservation_id": reservation_id,
                "run_id": context.authorization.research_run_id,
                "job_id": context.authorization.job_id,
                "workspace_id": context.authorization.workspace_id,
                "budget_ref": context.authorization.effective_budget_envelope_ref,
                "tool_name": call.tool_name,
                "input_sha": call.tool_input_sha256,
                "provider_family": call.provider_family,
                "reserved": call.budget_reservation_cents,
            },
        )

    @staticmethod
    async def _insert_member(
        conn: AsyncConnection,
        *,
        batch_id: UUID,
        plan: _MemberPlan,
    ) -> None:
        call = plan.call
        await conn.execute(
            text(
                """
                INSERT INTO entity_research_tool_batch_member
                    (batch_id, raw_tool_call_id, tool_name, tool_version, tool_input_sha256,
                     field_keys, source_keys, facet_key, provider_family,
                     budget_reservation_cents, provider_rate_limit_ref,
                     provider_concurrency_limit, budget_reservation_id)
                VALUES (:batch_id, :call_id, :tool_name, :version, :input_sha, :field_keys,
                        :source_keys, :facet_key, :provider_family, :reserved, :rate_ref,
                        :provider_limit, :reservation_id)
                """
            ),
            {
                "batch_id": batch_id,
                "call_id": call.tool_call_id,
                "tool_name": call.tool_name,
                "version": call.tool_version,
                "input_sha": call.tool_input_sha256,
                "field_keys": list(_field_values(call)),
                "source_keys": list(_source_values(call)),
                "facet_key": _facet_value(call),
                "provider_family": call.provider_family,
                "reserved": call.budget_reservation_cents,
                "rate_ref": call.provider_rate_limit_ref,
                "provider_limit": call.provider_concurrency_limit,
                "reservation_id": plan.reservation_id,
            },
        )

    @staticmethod
    async def _insert_permit(
        conn: AsyncConnection,
        *,
        context: EntityResearchRuntimeContext,
        batch_id: UUID,
        permit_id: UUID,
        call: EntityResearchToolCall,
    ) -> None:
        await conn.execute(
            text(
                """
                INSERT INTO entity_research_provider_permit
                    (permit_id, batch_id, raw_tool_call_id, research_run_id, job_id,
                     provider_family, provider_rate_limit_ref, concurrency_limit)
                VALUES (:permit_id, :batch_id, :call_id, :run_id, :job_id,
                        :provider_family, :rate_ref, :provider_limit)
                """
            ),
            {
                "permit_id": permit_id,
                "batch_id": batch_id,
                "call_id": call.tool_call_id,
                "run_id": context.authorization.research_run_id,
                "job_id": context.authorization.job_id,
                "provider_family": call.provider_family,
                "rate_ref": call.provider_rate_limit_ref,
                "provider_limit": call.provider_concurrency_limit,
            },
        )

    @staticmethod
    async def _member(
        conn: AsyncConnection,
        *,
        context: EntityResearchRuntimeContext,
        call: EntityResearchToolCall,
    ) -> RowMapping:
        row = (
            (
                await conn.execute(
                    text(
                        """
                        SELECT member.*, batch.research_run_id, batch.job_id,
                               batch.agent_execution_id, batch.target_entity_id
                        FROM entity_research_tool_batch_member member
                        JOIN entity_research_tool_batch batch
                          ON batch.batch_id=member.batch_id
                        WHERE batch.agent_turn_id=:turn_id
                          AND member.raw_tool_call_id=:call_id
                        """
                    ),
                    {"turn_id": context.agent_turn_id, "call_id": call.tool_call_id},
                )
            )
            .mappings()
            .first()
        )
        if row is None or (
            row["research_run_id"] != context.authorization.research_run_id
            or row["job_id"] != context.authorization.job_id
            or row["agent_execution_id"] != context.agent_execution_id
            or row["target_entity_id"] != context.authorization.subject_entity_id
            or str(row["tool_name"]) != call.tool_name
            or str(row["tool_input_sha256"]) != call.tool_input_sha256
        ):
            raise EntityResearchParallelAdmissionError(
                "tool execution lacks its exact admitted batch member"
            )
        return row

    @staticmethod
    async def _prior_completed(
        conn: AsyncConnection,
        *,
        context: EntityResearchRuntimeContext,
        call: EntityResearchToolCall,
    ) -> RowMapping | None:
        return (
            (
                await conn.execute(
                    text(
                        """
                        SELECT event.result_json, event.result_sha256,
                               member.provider_family, member.budget_reservation_cents,
                               member.provider_rate_limit_ref,
                               member.provider_concurrency_limit,
                               member.budget_reservation_id
                        FROM entity_research_tool_batch_event event
                        JOIN entity_research_tool_batch_member member
                          ON member.batch_id=event.batch_id
                         AND member.raw_tool_call_id=event.raw_tool_call_id
                        JOIN entity_research_tool_batch batch
                          ON batch.batch_id=member.batch_id
                        WHERE batch.job_id=:job_id AND batch.target_entity_id=:target_id
                          AND member.tool_name=:tool_name
                          AND member.tool_input_sha256=:input_sha
                          AND event.event_kind='completed'
                          AND event.result_erased_at IS NULL
                        ORDER BY event.event_seq DESC LIMIT 1
                        """
                    ),
                    {
                        "job_id": context.authorization.job_id,
                        "target_id": context.authorization.subject_entity_id,
                        "tool_name": call.tool_name,
                        "input_sha": call.tool_input_sha256,
                    },
                )
            )
            .mappings()
            .first()
        )

    @staticmethod
    async def _active_reservation(
        conn: AsyncConnection,
        *,
        context: EntityResearchRuntimeContext,
        call: EntityResearchToolCall,
    ) -> RowMapping | None:
        return (
            (
                await conn.execute(
                    text(
                        """
                        SELECT reservation.*, linked.provider_rate_limit_ref,
                               linked.provider_concurrency_limit,
                               EXISTS (
                                   SELECT 1 FROM entity_research_provider_permit permit
                                   JOIN entity_research_tool_batch_member permit_member
                                     ON permit_member.batch_id=permit.batch_id
                                    AND permit_member.raw_tool_call_id=permit.raw_tool_call_id
                                   LEFT JOIN entity_research_provider_permit_release permit_release
                                     USING (permit_id)
                                   WHERE permit_member.budget_reservation_id=
                                         reservation.reservation_id
                                     AND permit_release.permit_id IS NULL
                               ) AS has_active_permit
                        FROM entity_research_budget_reservation reservation
                        LEFT JOIN entity_research_budget_reservation_release release
                          USING (reservation_id)
                        JOIN entity_research_tool_batch_member linked
                          ON linked.budget_reservation_id=reservation.reservation_id
                        WHERE reservation.job_id=:job_id
                          AND reservation.tool_name=:tool_name
                          AND reservation.tool_input_sha256=:input_sha
                          AND release.reservation_id IS NULL
                        ORDER BY reservation.created_at DESC, linked.created_at DESC
                        LIMIT 1 FOR UPDATE OF reservation
                        """
                    ),
                    {
                        "job_id": context.authorization.job_id,
                        "tool_name": call.tool_name,
                        "input_sha": call.tool_input_sha256,
                    },
                )
            )
            .mappings()
            .first()
        )

    @staticmethod
    def _assert_joined_metadata(call: EntityResearchToolCall, row: RowMapping) -> None:
        observed = (
            row["provider_family"],
            Decimal(str(row["budget_reservation_cents"])),
            row["provider_rate_limit_ref"],
            row["provider_concurrency_limit"],
        )
        expected = (
            call.provider_family,
            call.budget_reservation_cents,
            call.provider_rate_limit_ref,
            call.provider_concurrency_limit,
        )
        if observed != expected:
            raise EntityResearchParallelAdmissionError(
                "settled tool replay resolved different provider admission authority"
            )

    @staticmethod
    def _assert_reservation_metadata(
        call: EntityResearchToolCall,
        row: RowMapping,
    ) -> None:
        if (
            str(row["provider_family"]) != call.provider_family
            or Decimal(str(row["reserved_cents"])) != call.budget_reservation_cents
            or str(row["provider_rate_limit_ref"]) != call.provider_rate_limit_ref
            or int(row["provider_concurrency_limit"]) != call.provider_concurrency_limit
        ):
            raise EntityResearchParallelAdmissionError(
                "active tool replay changed its atomic provider admission"
            )

    @staticmethod
    async def _insert_event(
        conn: AsyncConnection,
        *,
        batch_id: UUID,
        call: EntityResearchToolCall,
        event_kind: str,
        disposition: str,
        member_wait_ref: str | None = None,
        result: dict[str, JsonValue] | None = None,
        result_sha256: str | None = None,
        error: dict[str, JsonValue] | None = None,
    ) -> UUID:
        event_id = uuid5(
            _EVENT_NAMESPACE,
            f"{batch_id}:{call.tool_call_id}:{event_kind}",
        )
        await conn.execute(
            text(
                """
                INSERT INTO entity_research_tool_batch_event
                    (event_id, batch_id, raw_tool_call_id, event_kind, disposition,
                     member_wait_ref, result_json, result_sha256, error_json)
                VALUES (:event_id, :batch_id, :call_id, :event_kind, :disposition,
                        :member_wait_ref, CAST(:result AS jsonb), :result_sha,
                        CAST(:error AS jsonb))
                ON CONFLICT (batch_id, raw_tool_call_id, event_kind) DO NOTHING
                """
            ),
            {
                "event_id": event_id,
                "batch_id": batch_id,
                "call_id": call.tool_call_id,
                "event_kind": event_kind,
                "disposition": disposition,
                "member_wait_ref": member_wait_ref,
                "result": serialize_value_json(result) if result is not None else None,
                "result_sha": result_sha256,
                "error": serialize_value_json(error) if error is not None else None,
            },
        )
        stored = (
            (
                await conn.execute(
                    text(
                        "SELECT event_id, disposition, member_wait_ref, result_json, "
                        "result_sha256, error_json, result_erased_at FROM "
                        "entity_research_tool_batch_event "
                        "WHERE batch_id=:batch_id AND raw_tool_call_id=:call_id AND "
                        "event_kind=:event_kind"
                    ),
                    {
                        "batch_id": batch_id,
                        "call_id": call.tool_call_id,
                        "event_kind": event_kind,
                    },
                )
            )
            .mappings()
            .one()
        )
        if (
            stored["result_erased_at"] is not None
            or str(stored["disposition"]) != disposition
            or stored["member_wait_ref"] != member_wait_ref
            or stored["result_json"] != result
            or stored["result_sha256"] != result_sha256
            or stored["error_json"] != error
        ):
            raise EntityResearchParallelAdmissionError("tool batch event replay changed")
        if event_kind == "completed" and result is not None:
            batch = (
                (
                    await conn.execute(
                        text(
                            "SELECT workspace_id, subject_type, target_entity_id FROM "
                            "entity_research_tool_batch WHERE batch_id=:batch_id"
                        ),
                        {"batch_id": batch_id},
                    )
                )
                .mappings()
                .one()
            )
            subjects = _result_subjects(result)
            subjects.add((str(batch["subject_type"]), UUID(str(batch["target_entity_id"]))))
            for subject_type, target_entity_id in sorted(
                subjects, key=lambda item: (item[0], str(item[1]))
            ):
                await conn.execute(
                    text(
                        "INSERT INTO entity_research_tool_batch_result_subject "
                        "(event_id, workspace_id, subject_type, target_entity_id) "
                        "VALUES (:event_id, :workspace_id, :subject_type, :target_entity_id) "
                        "ON CONFLICT DO NOTHING"
                    ),
                    {
                        "event_id": event_id,
                        "workspace_id": batch["workspace_id"],
                        "subject_type": subject_type,
                        "target_entity_id": target_entity_id,
                    },
                )
        return UUID(str(stored["event_id"]))

    @staticmethod
    async def _release_permit(
        conn: AsyncConnection,
        *,
        batch_id: UUID,
        call: EntityResearchToolCall,
        event_id: UUID,
        disposition: str,
    ) -> None:
        permit_ids = (
            (
                await conn.execute(
                    text(
                        """
                        SELECT DISTINCT permit.permit_id
                        FROM entity_research_tool_batch_member current_member
                        JOIN entity_research_tool_batch_member holder
                          ON holder.budget_reservation_id=current_member.budget_reservation_id
                        JOIN entity_research_provider_permit permit
                          ON permit.batch_id=holder.batch_id
                         AND permit.raw_tool_call_id=holder.raw_tool_call_id
                        LEFT JOIN entity_research_provider_permit_release release
                          USING (permit_id)
                        WHERE current_member.batch_id=:batch_id
                          AND current_member.raw_tool_call_id=:call_id
                          AND release.permit_id IS NULL
                        """
                    ),
                    {"batch_id": batch_id, "call_id": call.tool_call_id},
                )
            )
            .scalars()
            .all()
        )
        for permit_id in permit_ids:
            await conn.execute(
                text(
                    "INSERT INTO entity_research_provider_permit_release "
                    "(permit_id, disposition, released_by_event_id) "
                    "VALUES (:permit_id, :disposition, :event_id) ON CONFLICT DO NOTHING"
                ),
                {
                    "permit_id": permit_id,
                    "disposition": disposition,
                    "event_id": event_id,
                },
            )

    @staticmethod
    async def _release_budget(
        conn: AsyncConnection,
        *,
        reservation_id: UUID,
        event_id: UUID,
        disposition: str,
        settled_cost: Decimal,
    ) -> None:
        await conn.execute(
            text(
                "INSERT INTO entity_research_budget_reservation_release "
                "(reservation_id, disposition, settled_cost_cents, released_by_event_id) "
                "VALUES (:reservation_id, :disposition, :cost, :event_id) "
                "ON CONFLICT DO NOTHING"
            ),
            {
                "reservation_id": reservation_id,
                "disposition": disposition,
                "cost": settled_cost,
                "event_id": event_id,
            },
        )

    async def _await_siblings(self, batch_id: UUID) -> tuple[str, ...]:
        while True:
            async with self._conn_factory() as conn:
                rows = (
                    (
                        await conn.execute(
                            text(
                                """
                                SELECT member.raw_tool_call_id,
                                       (SELECT event.event_kind FROM
                                           entity_research_tool_batch_event event
                                        WHERE event.batch_id=member.batch_id AND
                                              event.raw_tool_call_id=member.raw_tool_call_id
                                        ORDER BY CASE event.event_kind
                                            WHEN 'completed' THEN 3
                                            WHEN 'failed' THEN 2 ELSE 1 END DESC,
                                            event.event_seq DESC LIMIT 1) AS event_kind,
                                       (SELECT event.member_wait_ref FROM
                                           entity_research_tool_batch_event event
                                        WHERE event.batch_id=member.batch_id AND
                                              event.raw_tool_call_id=member.raw_tool_call_id AND
                                              event.event_kind='waiting_external'
                                        ORDER BY event.event_seq DESC LIMIT 1) AS member_wait_ref
                                FROM entity_research_tool_batch_member member
                                WHERE member.batch_id=:batch_id
                                ORDER BY member.raw_tool_call_id
                                """
                            ),
                            {"batch_id": batch_id},
                        )
                    )
                    .mappings()
                    .all()
                )
            if rows and all(row["event_kind"] is not None for row in rows):
                if any(str(row["event_kind"]) == "failed" for row in rows):
                    raise EntityResearchParallelAdmissionError(
                        "parallel sibling failed after atomic admission"
                    )
                waiting = tuple(
                    sorted(
                        str(row["member_wait_ref"])
                        for row in rows
                        if row["member_wait_ref"] is not None
                    )
                )
                if not waiting:
                    raise EntityResearchParallelAdmissionError(
                        "external-wait member settled without a durable wait reference"
                    )
                return waiting
            await asyncio.sleep(self._sibling_poll_seconds)

    @staticmethod
    def _settled_cost(
        call: EntityResearchToolCall,
        result: Mapping[str, JsonValue],
    ) -> Decimal:
        if call.tool_name in {
            "research_account_deep",
            "enrich_account",
            "discover_buying_committee",
            "research_contact_deep",
            "enrich_contact",
        }:
            rows = result.get("results", ())
            if not isinstance(rows, list):
                rows = list(rows) if isinstance(rows, tuple) else []
            return sum(
                (
                    Decimal(str(row.get("cost_cents", 0)))
                    for row in rows
                    if isinstance(row, Mapping)
                ),
                Decimal(0),
            )
        if call.tool_name == "reveal_contact_channel":
            return Decimal(str(result.get("acquisition_cost_cents", 0)))
        if call.tool_name == "validate_contact_channel":
            return Decimal(str(result.get("validation_cost_cents", 0)))
        return Decimal(0)

    @staticmethod
    async def _reservation_was_dispatched_or_waiting(
        conn: AsyncConnection,
        *,
        reservation_id: UUID,
    ) -> bool:
        value = (
            await conn.execute(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM entity_research_tool_batch_member member
                        JOIN entity_research_tool_batch batch USING (batch_id)
                        JOIN entity_research_tool_batch_event event
                          ON event.batch_id=member.batch_id
                         AND event.raw_tool_call_id=member.raw_tool_call_id
                        WHERE member.budget_reservation_id=:reservation_id
                          AND event.event_kind='waiting_external'
                    ) OR EXISTS (
                        SELECT 1 FROM entity_research_tool_batch_member member
                        JOIN entity_research_tool_batch batch USING (batch_id)
                        JOIN entity_research_tool_request request_row
                          ON request_row.agent_turn_id=batch.agent_turn_id
                         AND request_row.raw_tool_call_id=member.raw_tool_call_id
                        JOIN entity_research_provider_observation observation
                          ON observation.tool_request_id=request_row.tool_request_id
                        WHERE member.budget_reservation_id=:reservation_id
                          AND observation.disposition='caused'
                    ) OR EXISTS (
                        SELECT 1 FROM entity_research_tool_batch_member member
                        JOIN entity_research_tool_batch batch USING (batch_id)
                        JOIN entity_research_contact_channel_causation causation
                          ON causation.agent_turn_id=batch.agent_turn_id
                         AND causation.tool_call_id=member.raw_tool_call_id
                        WHERE member.budget_reservation_id=:reservation_id
                          AND causation.disposition='caused'
                    )
                    """
                ),
                {"reservation_id": reservation_id},
            )
        ).scalar_one()
        return bool(value)


class EntityResearchBatchWakeService:
    """Resolve one member wait and wake only its exact all-ready composite R2 job wait."""

    def __init__(self, *, conn_factory: ConnFactory = transaction) -> None:
        self._conn_factory = conn_factory

    @staticmethod
    async def _resolve_if_ready(
        conn: AsyncConnection,
        *,
        batch_id: UUID,
        wait_ref: str,
        job_id: UUID,
        actor: str,
    ) -> bool:
        remaining = int(
            (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM entity_research_tool_batch_wait_member "
                        "WHERE batch_id=:batch_id AND state='active'"
                    ),
                    {"batch_id": batch_id},
                )
            ).scalar_one()
        )
        job = (
            (
                await conn.execute(
                    text(
                        "SELECT state, current_wait_ref FROM entity_research_job "
                        "WHERE job_id=:job_id FOR UPDATE"
                    ),
                    {"job_id": job_id},
                )
            )
            .mappings()
            .one()
        )
        if str(job["state"]) == ResearchJobState.TERMINAL.value:
            await conn.execute(
                text(
                    "UPDATE entity_research_tool_batch_wait SET state='cancelled', "
                    "resolved_at=now(), resolved_by=:actor WHERE batch_id=:batch_id "
                    "AND state='active'"
                ),
                {"actor": actor, "batch_id": batch_id},
            )
            return False
        if (
            remaining == 0
            and str(job["state"]) == ResearchJobState.WAITING_EXTERNAL.value
            and str(job["current_wait_ref"]) == wait_ref
        ):
            await wake_entity_research_job(
                conn,
                job_id,
                wait_ref=wait_ref,
                actor=actor,
            )
            await conn.execute(
                text(
                    "UPDATE entity_research_tool_batch_wait SET state='woken', "
                    "resolved_at=now(), resolved_by=:actor WHERE batch_id=:batch_id "
                    "AND state='active'"
                ),
                {"actor": actor, "batch_id": batch_id},
            )
            return True
        return False

    async def notify_member_ready(self, member_wait_ref: str, *, actor: str) -> int:
        if not member_wait_ref or not actor:
            raise ValueError("batch wake member and actor must be non-empty")
        woken = 0
        async with self._conn_factory() as conn:
            candidates = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT member.batch_id, batch_wait.wait_ref, batch_wait.job_id
                            FROM entity_research_tool_batch_wait_member member
                            JOIN entity_research_tool_batch_wait batch_wait USING (batch_id)
                            WHERE member.member_wait_ref=:member_wait_ref
                              AND batch_wait.state='active'
                            ORDER BY batch_wait.created_at, member.batch_id
                            FOR UPDATE OF member, batch_wait
                            """
                        ),
                        {"member_wait_ref": member_wait_ref},
                    )
                )
                .mappings()
                .all()
            )
            for candidate in candidates:
                await conn.execute(
                    text(
                        "UPDATE entity_research_tool_batch_wait_member SET state='ready', "
                        "ready_at=COALESCE(ready_at, now()), ready_by=COALESCE(ready_by, :actor) "
                        "WHERE batch_id=:batch_id AND member_wait_ref=:member_wait_ref AND "
                        "state='active'"
                    ),
                    {
                        "actor": actor,
                        "batch_id": candidate["batch_id"],
                        "member_wait_ref": member_wait_ref,
                    },
                )
                if await self._resolve_if_ready(
                    conn,
                    batch_id=UUID(str(candidate["batch_id"])),
                    wait_ref=str(candidate["wait_ref"]),
                    job_id=UUID(str(candidate["job_id"])),
                    actor=actor,
                ):
                    woken += 1
        return woken

    async def reconcile_composite(self, wait_ref: str, *, actor: str) -> bool:
        """Close the callback-before-R2-wait race after the composite job wait is persisted."""

        if not wait_ref or not actor:
            raise ValueError("batch wait reference and actor must be non-empty")
        async with self._conn_factory() as conn:
            candidate = (
                (
                    await conn.execute(
                        text(
                            "SELECT batch_id, wait_ref, job_id FROM "
                            "entity_research_tool_batch_wait WHERE wait_ref=:wait_ref AND "
                            "state='active' FOR UPDATE"
                        ),
                        {"wait_ref": wait_ref},
                    )
                )
                .mappings()
                .first()
            )
            if candidate is None:
                return False
            return await self._resolve_if_ready(
                conn,
                batch_id=UUID(str(candidate["batch_id"])),
                wait_ref=str(candidate["wait_ref"]),
                job_id=UUID(str(candidate["job_id"])),
                actor=actor,
            )


class R9EntityResearchJobStore(DbEntityResearchJobStore):
    """R2 store composition that reconciles an already-ready composite immediately after wait."""

    def __init__(self, *, conn_factory: ConnFactory = transaction) -> None:
        super().__init__(conn_factory=conn_factory)
        self._batch_wakes = EntityResearchBatchWakeService(conn_factory=conn_factory)

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
        await super().wait_external(
            job_id,
            fence=fence,
            wait_ref=wait_ref,
            checkpoint_ref=checkpoint_ref,
            checkpoint_sha256=checkpoint_sha256,
            current_state_sha256=current_state_sha256,
        )
        await self._batch_wakes.reconcile_composite(
            wait_ref,
            actor=f"entity-research-wait:{fence.worker_id}",
        )
        current = await self.get_job(job_id)
        if current is None:
            raise EntityResearchParallelAdmissionError(
                "entity research job disappeared after composite wait persistence"
            )
        return current


__all__ = [
    "DbEntityResearchToolBatchCoordinator",
    "EntityResearchBatchWakeService",
    "EntityResearchParallelAdmissionError",
    "EntityResearchParallelRoundShapeRefusal",
    "R9EntityResearchJobStore",
]
