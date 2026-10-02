"""Account continuation coordination. Claims own membership; fleet owns leases.

A completed initial job is immutable history. A generation records only dependencies,
child result references and a monotonic input revision. Signals commit with their source effects;
queue offers can be retried from the same revision after an outage without replaying
initial paid research.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.research_operations import OperationScope
from clue_obs import get_logger
from clue_storage import retain_artifact

log = get_logger("arv2.quality.generation")
Reason = Literal[
    "initial_settled", "person_result", "claim_changed", "media_changed", "manual_refresh"
]


@dataclass(frozen=True)
class Generation:
    generation_id: UUID
    workspace_id: str
    project_id: str
    context_id: UUID
    run_id: UUID
    account_id: UUID
    initial_job_id: UUID
    input_revision: int
    reconciled_revision: int
    state: str


def continuation_work_id(generation: Generation) -> UUID:
    """One fleet lease across generations of the same contextual account."""
    return uuid5(
        NAMESPACE_URL,
        f"research-editorial:{generation.workspace_id}:"
        f"{generation.project_id}:{generation.context_id}:{generation.account_id}",
    )


def _generation(row: Mapping[str, Any]) -> Generation:
    return Generation(**{key: row[key] for key in Generation.__dataclass_fields__})


async def read_generation(
    conn: AsyncConnection, *, workspace_id: str, generation_id: UUID, lock: bool = False
) -> Generation:
    row = (
        (
            await conn.execute(
                text(
                    "SELECT * FROM arv2_account_research_generation WHERE generation_id=:id "
                    # Serialize revision writers without blocking FK KEY SHARE readers
                    # registering children. Generation identity keys never change here.
                    "AND workspace_id=:ws" + (" FOR NO KEY UPDATE" if lock else "")
                ),
                {"id": generation_id, "ws": workspace_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ValueError("research generation unavailable")
    return _generation(dict(row))


async def ensure_generation(
    conn: AsyncConnection, scope: OperationScope, *, context_id: UUID
) -> Generation:
    gid = uuid5(NAMESPACE_URL, f"research-generation:{scope.workspace_id}:{scope.job_id}")
    result = await conn.execute(
        text("""INSERT INTO arv2_account_research_generation
        (generation_id,workspace_id,project_id,context_id,run_id,account_id,initial_job_id)
        SELECT
        :id,j.workspace_id,r.project_id,r.context_id,j.run_id,j.account_entity_id,j.job_id
        FROM arv2_research_job j JOIN arv2_research_run r ON r.run_id=j.run_id AND
        r.workspace_id=j.workspace_id
        WHERE j.job_id=:job AND j.workspace_id=:ws AND j.run_id=:run AND
        j.account_entity_id=:account
          AND (j.subject_type='account' OR j.input_refs->>'parent_job_id' IS NULL)
          AND r.context_id=:context
        ON CONFLICT DO NOTHING RETURNING generation_id"""),
        {
            "id": gid,
            "job": scope.job_id,
            "ws": scope.workspace_id,
            "run": scope.run_id,
            "account": scope.account_id,
            "context": context_id,
        },
    )
    created = result.scalar_one_or_none() is not None
    generation = await read_generation(conn, workspace_id=scope.workspace_id, generation_id=gid)
    if generation.context_id != context_id:
        raise ValueError("generation cannot change project context")
    if created:
        log.info(
            "arv2.quality.generation_created",
            generation_id=str(gid),
            job_id=str(scope.job_id),
            context_id=str(context_id),
        )
    return generation


async def register_child(conn: AsyncConnection, generation: Generation, *, job_id: UUID) -> None:
    # Containment is checked on every replay, even if a row already exists.
    row = (
        await conn.execute(
            text("""SELECT subject_entity_id FROM arv2_research_job
        WHERE job_id=:job AND workspace_id=:ws AND run_id=:run AND account_entity_id=:account
          AND subject_type='person' AND input_refs->>'parent_job_id'=:parent"""),
            {
                "job": job_id,
                "ws": generation.workspace_id,
                "run": generation.run_id,
                "account": generation.account_id,
                "parent": str(generation.initial_job_id),
            },
        )
    ).scalar_one_or_none()
    if row is None:
        raise ValueError("person job is outside this account generation")
    await conn.execute(
        text("""INSERT INTO arv2_generation_child(generation_id,workspace_id,job_id,contact_id)
        VALUES (:id,:ws,:job,:contact) ON CONFLICT DO NOTHING"""),
        {
            "id": generation.generation_id,
            "ws": generation.workspace_id,
            "job": job_id,
            "contact": row,
        },
    )


async def signal(
    conn: AsyncConnection, *, workspace_id: str, generation_id: UUID, event_id: UUID, reason: Reason
) -> int:
    current = await read_generation(
        conn, workspace_id=workspace_id, generation_id=generation_id, lock=True
    )
    prior = (
        await conn.execute(
            text(
                "SELECT input_revision,reason FROM arv2_generation_signal WHERE "
                "generation_id=:id AND event_id=:event"
            ),
            {"id": generation_id, "event": event_id},
        )
    ).one_or_none()
    if prior is not None:
        if prior.reason != reason:
            raise ValueError("generation signal replay has a different reason")
        return int(prior.input_revision)
    revision = current.input_revision + 1
    await conn.execute(
        text("""INSERT INTO arv2_generation_signal
        (generation_id,workspace_id,event_id,input_revision,reason)
        VALUES(:id,:ws,:event,:revision,:reason)"""),
        {
            "id": generation_id,
            "ws": workspace_id,
            "event": event_id,
            "revision": revision,
            "reason": reason,
        },
    )
    await conn.execute(
        text("""UPDATE arv2_account_research_generation SET input_revision=:revision,
        updated_at=clock_timestamp(),
        initial_settled_at=CASE WHEN :reason='initial_settled' THEN
        COALESCE(initial_settled_at,now()) ELSE initial_settled_at END,
        state=CASE WHEN state IN ('suspended','privacy_stopped') THEN state
                   WHEN :reason='initial_settled' OR initial_settled_at IS NOT NULL THEN
        'provisional' ELSE state END
        WHERE generation_id=:id"""),
        {"id": generation_id, "revision": revision, "reason": reason},
    )
    log.info(
        "arv2.quality.generation_signalled",
        generation_id=str(generation_id),
        event_id=str(event_id),
        revision=revision,
        reason=reason,
    )
    return revision


async def record_child_result(
    conn: AsyncConnection, *, workspace_id: str, job_id: UUID, receipt_key: str | None = None
) -> int:
    rows = (
        (
            await conn.execute(
                text("""SELECT c.generation_id,j.status,j.finalization_json
        FROM arv2_generation_child c JOIN arv2_research_job j ON j.job_id=c.job_id AND
        j.workspace_id=c.workspace_id
        WHERE c.job_id=:job AND c.workspace_id=:ws AND j.status IN
        ('completed','needs_review','failed')"""),
                {"job": job_id, "ws": workspace_id},
            )
        )
        .mappings()
        .all()
    )
    from clue_api.arv2.research_operations import fingerprint

    for row in rows:
        # Same durable result is one event regardless of delivery count or worker.
        digest = fingerprint({"status": row["status"], "result": row["finalization_json"]})
        event = uuid5(NAMESPACE_URL, f"research-child-result:{job_id}:{digest}")
        await signal(
            conn,
            workspace_id=workspace_id,
            generation_id=row["generation_id"],
            event_id=event,
            reason="person_result",
        )
        if receipt_key:
            await retain_artifact(
                conn,
                workspace_id=workspace_id,
                storage_key=receipt_key,
                reference_kind="research_generation_result",
                reference_id=f"{row['generation_id']}:{job_id}",
            )
        await conn.execute(
            text("""UPDATE arv2_generation_child SET terminal_status=:status,result_sha256=:sha,
            receipt_key=COALESCE(:key,receipt_key), recorded_at=now() WHERE
        generation_id=:id AND job_id=:job"""),
            {
                "id": row["generation_id"],
                "job": job_id,
                "status": row["status"],
                "sha": digest,
                "key": receipt_key,
            },
        )
    return len(rows)


async def signal_subject_change(conn: AsyncConnection, event: dict[str, Any]) -> None:
    # Publishing a new narrative is an output of reconciliation, not another input round.
    # Corrections/withdrawals still invalidate dependent pages and require reconciliation.
    output_created = (
        await conn.execute(
            text("""SELECT EXISTS(
        SELECT 1 FROM claim c JOIN claim_quality_operation o ON o.claim_id=c.id
        JOIN claim_quality_assessment a ON a.assessment_id=o.assessment_id
        WHERE c.id=:claim AND o.operation_id=:event AND c.workspace_id=:ws
          AND c.field_key='account.value_narrative' AND o.kind='assessment' AND a.revision=1)
        """),
            {
                "claim": event.get("claim_id"),
                "event": event["event_id"],
                "ws": event["workspace_id"],
            },
        )
    ).scalar_one()
    if output_created:
        return
    from clue_core import ResearchScope, resolve_research_scope
    from clue_research.claimstore.registry import FieldRegistryScope, get_effective_field

    context_id = None
    if event.get("claim_id"):
        row = (
            await conn.execute(
                text("""SELECT c.field_key,q.context_id FROM claim c
            JOIN claim_quality_current q ON q.claim_id=c.id
            WHERE c.id=:claim AND c.workspace_id=:ws"""),
                {"claim": event["claim_id"], "ws": event["workspace_id"]},
            )
        ).one_or_none()
        if row:
            field = await get_effective_field(
                conn,
                scope=FieldRegistryScope.for_workspace(event["workspace_id"]),
                field_key=row.field_key,
            )
            if field and resolve_research_scope(field.field_def) is ResearchScope.PROJECT_RELATIVE:
                context_id = row.context_id
    rows = (
        (
            await conn.execute(
                text("""SELECT g.generation_id FROM arv2_account_research_generation g
        WHERE g.workspace_id=:ws
          AND (CAST(:context AS uuid) IS NULL OR g.context_id=CAST(:context AS uuid))
          AND (g.account_id=:subject OR EXISTS(
            SELECT 1 FROM arv2_generation_child c WHERE c.generation_id=g.generation_id
        AND c.contact_id=:subject) OR EXISTS (
            SELECT 1 FROM arv2_research_job j WHERE j.job_id=g.initial_job_id
              AND j.subject_entity_id=:subject))
        ORDER BY g.generation_id"""),
                {"ws": event["workspace_id"], "subject": event["entity_id"], "context": context_id},
            )
        )
        .scalars()
        .all()
    )
    for gid in rows:
        await signal(
            conn,
            workspace_id=event["workspace_id"],
            generation_id=gid,
            event_id=event["event_id"],
            reason="claim_changed",
        )


async def pending_continuations(
    conn: AsyncConnection, *, limit: int = 100, generation_id: UUID | None = None
) -> tuple[Generation, ...]:
    if not 1 <= limit <= 1000:
        raise ValueError("invalid continuation batch size")
    rows = (
        (
            await conn.execute(
                text("""SELECT g.*, (SELECT min(r.input_revision)
          FROM arv2_narrative_reconciliation r WHERE r.generation_id=g.generation_id
            AND r.state IN ('prepared','generated') AND r.input_revision>g.reconciled_revision
          ) AS pending_snapshot FROM arv2_account_research_generation g
        JOIN arv2_research_job j ON j.job_id=g.initial_job_id AND j.workspace_id=g.workspace_id
        WHERE g.input_revision>g.reconciled_revision AND g.initial_settled_at IS NOT NULL
          AND (CAST(:generation AS uuid) IS NULL OR g.generation_id=:generation)
          AND g.state NOT IN ('suspended','privacy_stopped')
          AND j.status IN ('completed','needs_review')
          AND COALESCE(j.input_refs->>'privacy_stopped','false')<>'true'
          AND (COALESCE((j.input_refs->>'quality_recipe_version')::int,0)<20 OR (
            j.subject_type='account' AND NOT EXISTS (SELECT 1 FROM arv2_generation_child c
              JOIN arv2_research_job child ON child.job_id=c.job_id
              WHERE c.generation_id=g.generation_id
                AND child.status NOT IN ('completed','needs_review','failed')
                AND NOT EXISTS (SELECT 1 FROM arv2_research_import_ready i
                  WHERE i.job_id=child.job_id AND i.workspace_id=g.workspace_id))
            AND NOT EXISTS (SELECT 1 FROM arv2_account_research_generation newer
              JOIN arv2_research_job newer_job ON newer_job.job_id=newer.initial_job_id
              WHERE newer_job.subject_type='account' AND newer.workspace_id=g.workspace_id
                AND newer.project_id=g.project_id
                AND newer.account_id=g.account_id AND newer.context_id=g.context_id
                AND (newer.created_at,newer.generation_id)>(g.created_at,g.generation_id))
          ))
        ORDER BY g.updated_at,g.generation_id LIMIT :limit"""),
                {"limit": limit, "generation": generation_id},
            )
        )
        .mappings()
        .all()
    )
    return tuple(
        replace(_generation(dict(row)), input_revision=row["pending_snapshot"])
        if row["pending_snapshot"] is not None
        else _generation(dict(row))
        for row in rows
    )


async def reconcile_generation(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    generation_id: UUID,
    expected_revision: int,
    needs_review: bool = False,
    processed_snapshot: bool = False,
) -> bool:
    current = await read_generation(
        conn, workspace_id=workspace_id, generation_id=generation_id, lock=True
    )
    if (
        current.input_revision < expected_revision
        or (not processed_snapshot and current.input_revision != expected_revision)
    ) or current.state in (
        "suspended",
        "privacy_stopped",
    ):
        return False
    if current.reconciled_revision >= expected_revision:
        return True
    statuses = (
        (
            await conn.execute(
                text("""SELECT j.status FROM arv2_generation_child c
        JOIN arv2_research_job j ON j.job_id=c.job_id AND j.workspace_id=c.workspace_id
        WHERE c.generation_id=:id AND c.workspace_id=:ws"""),
                {"id": generation_id, "ws": workspace_id},
            )
        )
        .scalars()
        .all()
    )
    state = (
        "provisional"
        if current.input_revision > expected_revision
        else "needs_review"
        if needs_review
        else "partial"
        if any(s in ("failed", "needs_review") for s in statuses)
        else "provisional"
        if any(s != "completed" for s in statuses)
        else "reconciled"
    )
    await conn.execute(
        text("""UPDATE arv2_account_research_generation SET reconciled_revision=:revision,
        state=:state,updated_at=clock_timestamp() WHERE generation_id=:id"""),
        {"id": generation_id, "revision": expected_revision, "state": state},
    )
    log.info(
        "arv2.quality.generation_reconciled",
        generation_id=str(generation_id),
        revision=expected_revision,
        state=state,
    )
    return True
