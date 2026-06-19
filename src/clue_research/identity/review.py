"""Confidence-thresholded auto-merge + the human review queue (M2.3).

The seam between *scoring* (M2.2) and *committing identity* — the only place merges are written.
Substrate §2: high-confidence (≈≥0.95) auto-merges; the mid-band routes to a human review queue
rather than guessing; **never silently collapse two real companies.** A wrong merge is a fabrication
of identity, so routing the ambiguous case to a human is the correct, conservative output, not a
failure (conventions §5, applied to identity).

This module owns:

* :func:`disposition` — the band policy over a :class:`ResolutionResult`:
  ``auto_merged(id) | enqueued(task_id) | new_entity(id)`` (the seam M5/M6/M8 call).
* :func:`auto_merge` — the executor: lock both candidates (M2.4 ``multi_lock``, deadlock-free),
  canonicalize the survivor (M2.2 ``plan_merge``), set the loser ``status=merged`` + the pointer,
  and record the audit. **Claims are never UPDATEd** (append-only — M1); reads resolve through
  ``surviving_id`` / :func:`current_value_resolved`. Idempotent on the candidate pair.
* the **review queue** — :func:`enqueue_review_task`, :func:`get_task`, :func:`list_open_tasks`, and
  the resolve API (:func:`resolve_merge_into`, :func:`resolve_create_new_entity`,
  :func:`resolve_not_a_match`, :func:`split_merge`).
* the **audit / labelled capture** — :func:`record_disposition`, :func:`get_dispositions`.

The threshold band is config (:class:`DispositionPolicy`), so tuning auto-merge aggressiveness, or
later swapping the queue transport for a workflow engine, stays behind this seam. M2.3 *enqueues*;
the durable-execution layer (M7) schedules the human task — degrading gracefully (the queue is fully
resolvable via this API before M7 lands).
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, JsonValue
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_research.claimstore import (
    DEFAULT_MERGE_POLICY,
    MergePolicy,
    claims_for,
    merge_claims,
)
from clue_research.core import (
    AccountStatus,
    Claim,
    CurrentValue,
    EntityId,
    EntityType,
    serialize_value_json,
)
from clue_research.identity.canonicalize import plan_merge
from clue_research.identity.entities import (
    get_account,
    insert_account_entity,
    mark_merged,
    set_status,
    surviving_id,
    update_account,
)
from clue_research.identity.policy import DEFAULT_DISPOSITION_POLICY, DispositionPolicy
from clue_research.identity.resolve import Observation, ResolutionResult
from clue_research.locks import multi_lock


# --- enums (mirrored by migration 0007; parity-tested) ----------------------
class ReviewStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class ReviewResolution(StrEnum):
    MERGE_INTO = "merge_into"
    CREATE_NEW_ENTITY = "create_new_entity"
    NOT_A_MATCH = "not_a_match"
    SPLIT = "split"


class DispositionKind(StrEnum):
    """The audit-record kind (DB ``disposition_kind``)."""

    AUTO_MERGE = "auto_merge"
    NEW_ENTITY = "new_entity"
    REVIEW_ENQUEUED = "review_enqueued"
    REVIEW_RESOLVED = "review_resolved"


class DispositionOutcome(StrEnum):
    """The return outcome of :func:`disposition` (the seam's three-way result)."""

    AUTO_MERGED = "auto_merged"
    ENQUEUED = "enqueued"
    NEW_ENTITY = "new_entity"


# --- models -----------------------------------------------------------------
class Disposition(BaseModel):
    """The result of :func:`disposition`: an outcome plus the resulting entity / task id."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: DispositionOutcome
    entity_id: EntityId | None = None  # the survivor (auto_merged) or new candidate (new_entity)
    task_id: EntityId | None = None  # the review task (enqueued)
    top_score: float = 0.0


class ReviewTask(BaseModel):
    """One row of the human review queue."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: EntityId
    entity_type: EntityType
    observation: dict[str, JsonValue]
    candidates: tuple[dict[str, JsonValue], ...]
    proposed_action: str
    subject_entity_id: EntityId | None
    tenant_id: str | None
    status: ReviewStatus
    resolution: ReviewResolution | None
    resolved_by: str | None
    config_version: int


def _now() -> datetime:
    return datetime.now(UTC)


def _candidates_json(result: ResolutionResult) -> str:
    return serialize_value_json([c.model_dump(mode="json") for c in result.candidates])


def _entity_table(entity_type: EntityType) -> str:
    return "account_entity" if entity_type is EntityType.ACCOUNT else "contact_entity"


async def _relinquish_strong_keys(
    conn: AsyncConnection, entity_type: EntityType, entity_id: EntityId
) -> None:
    """Clear a merged loser's strong keys so the survivor can own them without a partial-unique
    clash (a merged entity is a redirect, not a second holder of a domain / registry id / email)."""
    if entity_type is EntityType.ACCOUNT:
        sql = (
            "UPDATE account_entity SET primary_domain = NULL, registry_ids = '{}'::jsonb "
            "WHERE id = :id"
        )
    else:
        sql = "UPDATE contact_entity SET linkedin_url = NULL, verified_email = NULL WHERE id = :id"
    await conn.execute(text(sql), {"id": entity_id})


# --- audit ------------------------------------------------------------------
async def record_disposition(
    conn: AsyncConnection,
    *,
    entity_type: EntityType,
    kind: DispositionKind,
    decided_by: str,
    config_version: int,
    survivor_id: EntityId | None = None,
    loser_id: EntityId | None = None,
    review_task_id: EntityId | None = None,
    top_score: float | None = None,
    observation: Observation | None = None,
    result: ResolutionResult | None = None,
) -> EntityId:
    """Append one disposition audit row (every merge / admission / resolution is recorded)."""
    row = await conn.execute(
        text(
            """
            INSERT INTO identity_disposition (
                entity_type, kind, survivor_id, loser_id, review_task_id, top_score,
                decided_by, config_version, observation_json, candidates_json
            ) VALUES (
                CAST(:entity_type AS entity_type), CAST(:kind AS disposition_kind), :survivor_id,
                :loser_id, :review_task_id, :top_score, :decided_by, :config_version,
                CAST(:observation_json AS jsonb), CAST(:candidates_json AS jsonb)
            ) RETURNING id
            """
        ),
        {
            "entity_type": entity_type.value,
            "kind": kind.value,
            "survivor_id": survivor_id,
            "loser_id": loser_id,
            "review_task_id": review_task_id,
            "top_score": top_score,
            "decided_by": decided_by,
            "config_version": config_version,
            "observation_json": (
                serialize_value_json(observation.model_dump(mode="json"))
                if observation is not None
                else None
            ),
            "candidates_json": _candidates_json(result) if result is not None else None,
        },
    )
    return EntityId(row.scalar_one())


async def get_dispositions(
    conn: AsyncConnection, entity_id: EntityId
) -> list[dict[str, JsonValue]]:
    """The disposition history touching an entity (as survivor or loser) — the queryable identity
    audit trail. Returned newest-first."""
    rows = (
        (
            await conn.execute(
                text(
                    "SELECT id, kind, survivor_id, loser_id, top_score, decided_by, "
                    "config_version, created_at FROM identity_disposition "
                    "WHERE survivor_id = :e OR loser_id = :e ORDER BY created_at DESC, id"
                ),
                {"e": entity_id},
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


# --- the auto-merge executor ------------------------------------------------
async def auto_merge(
    conn: AsyncConnection,
    loser_id: EntityId,
    survivor_id: EntityId,
    *,
    entity_type: EntityType = EntityType.ACCOUNT,
    redis: Redis | None = None,
    top_score: float = 1.0,
    decided_by: str = "auto",
    config_version: int = 1,
    tenant_id: str | None = None,
) -> EntityId:
    """Merge ``loser`` into ``survivor`` and return the survivor id. Idempotent on the pair.

    Locks both candidates in deterministic order (M2.4 ``multi_lock``) when a ``redis`` client is
    given — so two concurrent merges of the same pair never race or deadlock; without Redis it runs
    degraded (single-flight is advisory, correctness still rests on this being idempotent). For an
    account it canonicalizes the survivor (M2.2 ``plan_merge`` — union aliases/registry, fill gaps);
    a contact merge just re-points (committee canonicalization is M8). Claims are **never UPDATEd**.
    """
    if loser_id == survivor_id:
        return survivor_id  # nothing to do

    async def _do() -> EntityId:
        # Idempotency: if the loser already resolves to this survivor, this is a no-op.
        if await surviving_id(conn, loser_id, entity_type) == survivor_id:
            already_merged = (
                await conn.execute(
                    text(
                        f"SELECT 1 FROM {_entity_table(entity_type)} "
                        "WHERE id = :loser AND status = 'merged'"
                    ),
                    {"loser": loser_id},
                )
            ).first()
            if already_merged is not None:
                return survivor_id
        if entity_type is EntityType.ACCOUNT:
            survivor = await get_account(conn, survivor_id)
            loser = await get_account(conn, loser_id)
            if survivor is not None and loser is not None:
                plan = plan_merge(survivor, loser)
                # The loser relinquishes its strong keys BEFORE the survivor absorbs them, so the
                # transfer never trips the partial-unique constraints (two rows can't hold one
                # domain / registry id). The loser becomes a pure redirect (id + merged_into).
                await _relinquish_strong_keys(conn, entity_type, loser_id)
                await update_account(
                    conn,
                    survivor_id,
                    canonical_name=plan.canonical_name,
                    primary_domain=plan.primary_domain,
                    add_aliases=plan.add_aliases,
                    add_registry_ids=plan.add_registry_ids,
                )
        else:
            await _relinquish_strong_keys(conn, entity_type, loser_id)
        await set_status(conn, entity_type, survivor_id, AccountStatus.ACTIVE)
        await mark_merged(conn, entity_type, loser_id, survivor_id)
        await record_disposition(
            conn,
            entity_type=entity_type,
            kind=DispositionKind.AUTO_MERGE,
            decided_by=decided_by,
            config_version=config_version,
            survivor_id=survivor_id,
            loser_id=loser_id,
            top_score=top_score,
        )
        return survivor_id

    if redis is not None:
        async with multi_lock(
            redis, [(entity_type, loser_id), (entity_type, survivor_id)], tenant=tenant_id
        ):
            return await _do()
    return await _do()


# --- the disposition band policy --------------------------------------------
async def disposition(
    conn: AsyncConnection,
    observation: Observation,
    result: ResolutionResult,
    *,
    policy: DispositionPolicy = DEFAULT_DISPOSITION_POLICY,
    redis: Redis | None = None,
    tenant_id: str | None = None,
    decided_by: str = "auto",
    subject_entity_id: EntityId | None = None,
) -> Disposition:
    """Decide what to do with a resolution result (the seam callers use).

    * ``top_score ≥ auto_merge_threshold`` → **auto-merge**: the observation resolves to the top
      candidate; if a ``subject_entity_id`` was pre-admitted (e.g. an import row), it is merged into
      the survivor. Returns the survivor id.
    * mid-band → **review**: exactly one ``open`` task is enqueued; **no entity is mutated**.
    * below ``review_low_threshold`` (or no candidate) → **new entity**: a fresh ``candidate`` is
      admitted from the observation (or the pre-admitted ``subject`` is kept). Returns the new id.
    """
    top = result.top
    entity_type = observation.entity_type

    if top is not None and result.top_score >= policy.auto_merge_threshold:
        survivor = top.entity_id
        if subject_entity_id is not None and subject_entity_id != survivor:
            await auto_merge(
                conn,
                subject_entity_id,
                survivor,
                entity_type=entity_type,
                redis=redis,
                top_score=result.top_score,
                decided_by=decided_by,
                config_version=policy.version,
                tenant_id=tenant_id,
            )
        else:
            await record_disposition(
                conn,
                entity_type=entity_type,
                kind=DispositionKind.AUTO_MERGE,
                decided_by=decided_by,
                config_version=policy.version,
                survivor_id=survivor,
                top_score=result.top_score,
                observation=observation,
                result=result,
            )
        return Disposition(
            outcome=DispositionOutcome.AUTO_MERGED, entity_id=survivor, top_score=result.top_score
        )

    if top is not None and result.top_score >= policy.review_low_threshold:
        task_id = await enqueue_review_task(
            conn,
            observation,
            result,
            tenant_id=tenant_id,
            config_version=policy.version,
            subject_entity_id=subject_entity_id,
            proposed_action="merge_into",
        )
        return Disposition(
            outcome=DispositionOutcome.ENQUEUED, task_id=task_id, top_score=result.top_score
        )

    # Below the low threshold (or no candidate): admit a fresh candidate entity.
    new_id = subject_entity_id
    if new_id is None and entity_type is EntityType.ACCOUNT:
        new_id = await insert_account_entity(
            conn,
            canonical_name=observation.name or "(unnamed)",
            primary_domain=observation.domain,
            aliases=observation.aliases,
            registry_ids=observation.registry_ids,
        )
    await record_disposition(
        conn,
        entity_type=entity_type,
        kind=DispositionKind.NEW_ENTITY,
        decided_by=decided_by,
        config_version=policy.version,
        survivor_id=new_id,
        top_score=result.top_score,
        observation=observation,
        result=result,
    )
    return Disposition(
        outcome=DispositionOutcome.NEW_ENTITY, entity_id=new_id, top_score=result.top_score
    )


# --- the review queue -------------------------------------------------------
async def enqueue_review_task(
    conn: AsyncConnection,
    observation: Observation,
    result: ResolutionResult,
    *,
    config_version: int,
    tenant_id: str | None = None,
    subject_entity_id: EntityId | None = None,
    proposed_action: str = "merge_into",
) -> EntityId:
    """Enqueue one ``open`` review task for an ambiguous match (mutates no entity)."""
    row = await conn.execute(
        text(
            """
            INSERT INTO identity_review_task (
                entity_type, observation_json, candidates_json, proposed_action,
                subject_entity_id, tenant_id, config_version
            ) VALUES (
                CAST(:entity_type AS entity_type), CAST(:observation_json AS jsonb),
                CAST(:candidates_json AS jsonb), :proposed_action, :subject_entity_id,
                :tenant_id, :config_version
            ) RETURNING id
            """
        ),
        {
            "entity_type": observation.entity_type.value,
            "observation_json": serialize_value_json(observation.model_dump(mode="json")),
            "candidates_json": _candidates_json(result),
            "proposed_action": proposed_action,
            "subject_entity_id": subject_entity_id,
            "tenant_id": tenant_id,
            "config_version": config_version,
        },
    )
    task_id = EntityId(row.scalar_one())
    await record_disposition(
        conn,
        entity_type=observation.entity_type,
        kind=DispositionKind.REVIEW_ENQUEUED,
        decided_by="auto",
        config_version=config_version,
        review_task_id=task_id,
        top_score=result.top_score,
        observation=observation,
        result=result,
    )
    return task_id


_TASK_COLUMNS = (
    "id, entity_type, observation_json, candidates_json, proposed_action, subject_entity_id, "
    "tenant_id, status, resolution, resolved_by, config_version"
)


def _row_to_task(row: dict[str, object]) -> ReviewTask:
    return ReviewTask.model_validate(
        {
            "id": row["id"],
            "entity_type": row["entity_type"],
            "observation": row["observation_json"],
            "candidates": tuple(row["candidates_json"] or ()),  # type: ignore[arg-type]
            "proposed_action": row["proposed_action"],
            "subject_entity_id": row["subject_entity_id"],
            "tenant_id": row["tenant_id"],
            "status": row["status"],
            "resolution": row["resolution"],
            "resolved_by": row["resolved_by"],
            "config_version": row["config_version"],
        }
    )


async def get_task(conn: AsyncConnection, task_id: EntityId) -> ReviewTask | None:
    row = (
        (
            await conn.execute(
                text(f"SELECT {_TASK_COLUMNS} FROM identity_review_task WHERE id = :id"),
                {"id": task_id},
            )
        )
        .mappings()
        .first()
    )
    return _row_to_task(dict(row)) if row is not None else None


async def list_open_tasks(
    conn: AsyncConnection, *, tenant_id: str | None = None, limit: int = 100
) -> list[ReviewTask]:
    """Open review tasks (optionally tenant-scoped) — the queue the human surface reads."""
    rows = (
        (
            await conn.execute(
                text(
                    f"SELECT {_TASK_COLUMNS} FROM identity_review_task "
                    "WHERE status = 'open' "
                    "AND (CAST(:tenant AS text) IS NULL OR tenant_id = :tenant) "
                    "ORDER BY created_at, id LIMIT :limit"
                ),
                {"tenant": tenant_id, "limit": limit},
            )
        )
        .mappings()
        .all()
    )
    return [_row_to_task(dict(r)) for r in rows]


async def _close_task(
    conn: AsyncConnection,
    task_id: EntityId,
    *,
    status: ReviewStatus,
    resolution: ReviewResolution | None,
    resolved_by: str,
) -> None:
    await conn.execute(
        text(
            "UPDATE identity_review_task SET status = CAST(:status AS review_status), "
            "resolution = CAST(:resolution AS review_resolution), resolved_by = :by, "
            "resolved_at = now() WHERE id = :id AND status = 'open'"
        ),
        {
            "status": status.value,
            "resolution": resolution.value if resolution is not None else None,
            "by": resolved_by,
            "id": task_id,
        },
    )


# --- the review resolve API -------------------------------------------------
async def resolve_merge_into(
    conn: AsyncConnection,
    task_id: EntityId,
    survivor_id: EntityId,
    *,
    resolved_by: str,
    redis: Redis | None = None,
) -> EntityId:
    """Human decision: the observation **is** ``survivor_id``. Merge the task's subject into it
    (when one was pre-admitted) and close the task ``resolved``. Returns the survivor."""
    task = await get_task(conn, task_id)
    if task is None:
        raise ValueError(f"review task {task_id} not found")
    if task.subject_entity_id is not None:
        await auto_merge(
            conn,
            task.subject_entity_id,
            survivor_id,
            entity_type=task.entity_type,
            redis=redis,
            decided_by=resolved_by,
            config_version=task.config_version,
            tenant_id=task.tenant_id,
        )
    await _close_task(
        conn,
        task_id,
        status=ReviewStatus.RESOLVED,
        resolution=ReviewResolution.MERGE_INTO,
        resolved_by=resolved_by,
    )
    await record_disposition(
        conn,
        entity_type=task.entity_type,
        kind=DispositionKind.REVIEW_RESOLVED,
        decided_by=resolved_by,
        config_version=task.config_version,
        survivor_id=survivor_id,
        loser_id=task.subject_entity_id,
        review_task_id=task_id,
    )
    return survivor_id


async def resolve_create_new_entity(
    conn: AsyncConnection, task_id: EntityId, *, resolved_by: str
) -> EntityId:
    """Human decision: none of the candidates match → admit a new ``candidate`` entity from the
    observation (or keep the pre-admitted subject) and close the task."""
    task = await get_task(conn, task_id)
    if task is None:
        raise ValueError(f"review task {task_id} not found")
    new_id = task.subject_entity_id
    if new_id is None and task.entity_type is EntityType.ACCOUNT:
        obs = Observation.model_validate(task.observation)
        new_id = await insert_account_entity(
            conn,
            canonical_name=obs.name or "(unnamed)",
            primary_domain=obs.domain,
            aliases=obs.aliases,
            registry_ids=obs.registry_ids,
        )
    await _close_task(
        conn,
        task_id,
        status=ReviewStatus.RESOLVED,
        resolution=ReviewResolution.CREATE_NEW_ENTITY,
        resolved_by=resolved_by,
    )
    await record_disposition(
        conn,
        entity_type=task.entity_type,
        kind=DispositionKind.REVIEW_RESOLVED,
        decided_by=resolved_by,
        config_version=task.config_version,
        survivor_id=new_id,
        review_task_id=task_id,
    )
    return new_id  # type: ignore[return-value]


async def resolve_not_a_match(
    conn: AsyncConnection, task_id: EntityId, *, resolved_by: str
) -> None:
    """Human decision: keep the candidates as distinct entities (no merge); close the task. The
    subject, if any, stays a separate entity — nothing is mutated."""
    task = await get_task(conn, task_id)
    if task is None:
        raise ValueError(f"review task {task_id} not found")
    await _close_task(
        conn,
        task_id,
        status=ReviewStatus.RESOLVED,
        resolution=ReviewResolution.NOT_A_MATCH,
        resolved_by=resolved_by,
    )
    await record_disposition(
        conn,
        entity_type=task.entity_type,
        kind=DispositionKind.REVIEW_RESOLVED,
        decided_by=resolved_by,
        config_version=task.config_version,
        survivor_id=task.subject_entity_id,
        review_task_id=task_id,
    )


async def split_merge(
    conn: AsyncConnection,
    loser_id: EntityId,
    *,
    entity_type: EntityType = EntityType.ACCOUNT,
    resolved_by: str,
    config_version: int = 1,
) -> None:
    """Reverse an erroneous prior merge: un-point ``loser``'s ``merged_into`` and re-activate it, so
    its claims resolve to the corrected (its own) entity again. Append-only claims are untouched —
    only the entity's merge pointer changes."""
    table = _entity_table(entity_type)
    await conn.execute(
        text(
            f"UPDATE {table} SET status = 'active', merged_into = NULL, updated_at = now() "
            "WHERE id = :id"
        ),
        {"id": loser_id},
    )
    await record_disposition(
        conn,
        entity_type=entity_type,
        kind=DispositionKind.REVIEW_RESOLVED,
        decided_by=resolved_by,
        config_version=config_version,
        survivor_id=loser_id,
    )


# --- merge-resolved claim read ----------------------------------------------
async def merged_member_ids(
    conn: AsyncConnection, survivor_id: EntityId, entity_type: EntityType
) -> list[EntityId]:
    """All entity ids whose ``merged_into`` chain resolves to ``survivor`` (the survivor + every
    transitive loser) — a recursive-CTE union-find read."""
    table = _entity_table(entity_type)
    rows = (
        (
            await conn.execute(
                text(
                    f"""
                WITH RECURSIVE members AS (
                    SELECT id FROM {table} WHERE id = :survivor
                    UNION
                    SELECT a.id FROM {table} a JOIN members m ON a.merged_into = m.id
                )
                SELECT id FROM members
                """
                ),
                {"survivor": survivor_id},
            )
        )
        .scalars()
        .all()
    )
    return [EntityId(r) for r in rows]


async def _field_ttl(conn: AsyncConnection, field_key: str) -> object:
    row = (
        await conn.execute(
            text("SELECT freshness_ttl FROM field_definition WHERE field_key = :k"),
            {"k": field_key},
        )
    ).first()
    return row[0] if row is not None else None


async def current_value_resolved(
    conn: AsyncConnection,
    entity_id: EntityId,
    field_key: str,
    *,
    entity_type: EntityType = EntityType.ACCOUNT,
    policy: MergePolicy = DEFAULT_MERGE_POLICY,
) -> CurrentValue | None:
    """The current truth for a field, **resolved across a merge**: claims attached to any entity
    that merged into the survivor are read under the survivor (substrate §2). Reuses M1's pure
    ``merge_claims`` over the combined live-claim set; **no claim row is UPDATEd** (append-only)."""
    survivor = await surviving_id(conn, entity_id, entity_type)
    members = await merged_member_ids(conn, survivor, entity_type)
    claims: list[Claim] = []
    for member in members:
        claims.extend(await claims_for(conn, member, field_key))
    ttl = await _field_ttl(conn, field_key)
    return merge_claims(claims, ttl, policy, _now())  # type: ignore[arg-type]
