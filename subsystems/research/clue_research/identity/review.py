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
from sqlalchemy import ARRAY, Text, bindparam, text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    AccountStatus,
    Claim,
    CurrentValue,
    EntityId,
    EntityType,
    EqualityMode,
    serialize_value_json,
)
from clue_locks import multi_lock
from clue_research.claimstore import (
    DEFAULT_MERGE_POLICY,
    MergePolicy,
    WorkspaceScope,
    claims_for,
    merge_claims,
)
from clue_research.identity.canonicalize import plan_merge
from clue_research.identity.embedding import DEFAULT_EMBEDDER, Embedder, embed_account
from clue_research.identity.entities import (
    enrich_account,
    get_account,
    insert_account_entity,
    mark_merged,
    set_status,
    surviving_id,
    update_account,
)
from clue_research.identity.policy import DEFAULT_DISPOSITION_POLICY, DispositionPolicy
from clue_research.identity.resolve import Observation, ResolutionResult
from clue_research.membership import ensure_project_account


class MergeConflictError(ValueError):
    """Raised when an auto-merge would re-point a loser already merged into a *different* survivor
    (identity corruption) — the prior merge must be ``split`` first."""


class ReviewTaskUnscopedError(ValueError):
    """Raised when a review task carries no ``workspace_id`` but a new account entity must be
    admitted from it (accounts are workspace-local; founder ruling 2026-07-22). A legacy
    NULL-workspace task cannot mint a workspace-anchored account — fail loud, never guess a
    scope."""


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
    workspace_id: str | None
    # FI-2 P1: the project the admitting caller was discovering for. NULL = a projectless
    # (workspace-level) admission, or a task enqueued before the column existed.
    project_id: str | None = None
    status: ReviewStatus
    resolution: ReviewResolution | None
    resolved_by: str | None
    config_version: int


class ReviewDecision(BaseModel):
    """Current durable human-decision state plus the resulting survivor, when one exists."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    task_id: EntityId
    workspace_id: str | None
    status: ReviewStatus
    resolution: ReviewResolution | None
    survivor_id: EntityId | None


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
    payload: dict[str, JsonValue] | None = None,
) -> EntityId:
    """Append one disposition audit row (every merge / admission / resolution is recorded).

    ``payload`` stores an arbitrary jsonb provenance blob in ``observation_json`` (used by an
    auto-merge to record the loser's relinquished strong keys, so a later ``split`` can restore
    them); it takes precedence over ``observation``."""
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
                serialize_value_json(payload)
                if payload is not None
                else serialize_value_json(observation.model_dump(mode="json"))
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
    workspace_id: str | None = None,
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
        # Idempotency / safety: where does the loser already resolve?
        current = await surviving_id(conn, loser_id, entity_type)
        if current == survivor_id:
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
                return survivor_id  # no-op: the loser is already merged into this survivor
        elif current != loser_id:
            # The loser is already merged into a DIFFERENT survivor. Silently re-pointing it would
            # corrupt identity history; a genuine re-merge must `split` the prior merge first.
            raise MergeConflictError(
                f"{entity_type.value} {loser_id} is already merged into {current}, "
                f"not {survivor_id}; split the prior merge before re-merging"
            )
        # Record the loser's relinquished strong keys so a later `split` can restore them.
        relinquished: dict[str, JsonValue] = {}
        if entity_type is EntityType.ACCOUNT:
            survivor = await get_account(conn, survivor_id)
            loser = await get_account(conn, loser_id)
            if survivor is not None and loser is not None:
                relinquished = {
                    "primary_domain": loser.primary_domain,
                    "registry_ids": dict(loser.registry_ids),
                    "domain_absorbed": survivor.primary_domain is None
                    and loser.primary_domain is not None,
                }
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
            payload={"relinquished_strong_keys": relinquished} if relinquished else None,
        )
        return survivor_id

    if redis is not None:
        async with multi_lock(
            redis, [(entity_type, loser_id), (entity_type, survivor_id)], tenant=workspace_id
        ):
            return await _do()
    return await _do()


# --- enrichment on a strong-key match ---------------------------------------
async def enrich_survivor(
    conn: AsyncConnection,
    *,
    survivor_id: EntityId,
    observation: Observation,
    workspace_id: str,
) -> bool:
    """Fold what a new sighting knows into the account it auto-merged onto (FI-2 §8.2-H2).

    An auto-merge with no ``subject_entity_id`` has no loser entity to canonicalize from — the
    observation *is* the loser — so before this the whole sighting was thrown away: an import row
    matching an existing account by domain contributed neither its alias nor a registry id the
    account lacked, and the same row re-imported forever re-learned nothing.

    This is the deliberately conservative counterpart to :func:`auto_merge`'s ``plan_merge``: the
    survivor gains aliases / registry namespaces it lacks and fills an empty
    ``primary_domain`` / ``hq_geo``, and never gives up a value it already asserts (including its
    ``canonical_name`` — a merge may rename, an observation may not). Accounts only: a contact
    sighting has no equivalent gap-fill contract yet (committee canonicalization is M8).

    Returns whether the survivor changed. Runs in the caller's transaction, so the enrichment
    commits with the disposition audit row that justifies it, or not at all.
    """
    if observation.entity_type is not EntityType.ACCOUNT:
        return False
    return await enrich_account(
        conn,
        survivor_id,
        workspace_id=workspace_id,
        primary_domain=observation.domain,
        # The observation's own name is an alias of the account it resolved to — that is exactly
        # what a future name-only sighting needs to hit (the ``alias_overlap`` arm, FI-2 §1.2-H1).
        add_aliases=(observation.name, *observation.aliases),
        add_registry_ids=observation.registry_ids,
        hq_geo=observation.geo,
    )


# --- the disposition band policy --------------------------------------------
async def disposition(
    conn: AsyncConnection,
    observation: Observation,
    result: ResolutionResult,
    *,
    policy: DispositionPolicy = DEFAULT_DISPOSITION_POLICY,
    redis: Redis | None = None,
    workspace_id: str,
    project_id: str | None = None,
    decided_by: str = "auto",
    subject_entity_id: EntityId | None = None,
    embedder: Embedder | None = None,
) -> Disposition:
    """Decide what to do with a resolution result (the seam callers use).

    * ``top_score ≥ auto_merge_threshold`` → **auto-merge**: the observation resolves to the top
      candidate; if a ``subject_entity_id`` was pre-admitted (e.g. an import row), it is merged into
      the survivor. With no pre-admitted subject the observation itself is the loser, so
      :func:`enrich_survivor` folds its aliases / registry ids / gap-filling domain+geo into the
      survivor (FI-2 §8.2-H2) — a sighting is evidence, not a discard. Returns the survivor id.
    * mid-band → **review**: exactly one ``open`` task is enqueued; **no entity is mutated**. The
      caller's ``project_id`` (FI-2 P1) rides the task, so the human resolution can join the
      resulting account to the project this admission was serving.
    * below ``review_low_threshold`` (or no candidate) → **new entity**: a fresh ``candidate`` is
      admitted from the observation (or the pre-admitted ``subject`` is kept). Returns the new id.

    ``embedder`` (FI-2 §1.2-H1) embeds a *newly minted* account so the next encounter of the same
    company can find it through the resolver's ANN arm. It is **optional**: passed ``None`` this
    behaves exactly as it did before — the caller either embeds the entity itself (M5's import
    pipeline does, right after this returns) or accepts that it stays unembedded. An entity this
    call did not mint (an auto-merge survivor, a pre-admitted ``subject``) is never re-embedded
    here — re-embedding is an explicit act (see :func:`~clue_research.identity.embed_account`).
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
                workspace_id=workspace_id,
            )
        else:
            # No loser entity exists (the observation is the loser), so ``auto_merge``'s
            # canonicalization has nothing to run on — FI-2 §8.2-H2 folds the sighting's own
            # identifiers into the survivor instead, in this same transaction. Conservative and
            # gap-filling: see :func:`enrich_survivor`.
            await enrich_survivor(
                conn,
                survivor_id=survivor,
                observation=observation,
                workspace_id=workspace_id,
            )
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
            workspace_id=workspace_id,
            project_id=project_id,
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
            workspace_id=workspace_id,
        )
        if embedder is not None:
            # FI-2 §1.2-H1: embed at creation, or the next name-only encounter of this company
            # scores with the cosine arm zeroed, falls below the review floor, and duplicates it.
            await embed_account(conn, new_id, embedder=embedder)
    if new_id is None:
        # A contact resolves *under* an account (M2.1), so it cannot be admitted standalone here;
        # the caller must pre-admit it (pass subject_entity_id). Fail loudly, never return None.
        raise NotImplementedError(
            "cannot admit a new contact entity without an account_entity_id — pass "
            "subject_entity_id (committee contact creation is M8)"
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
    workspace_id: str | None = None,
    project_id: str | None = None,
    subject_entity_id: EntityId | None = None,
    proposed_action: str = "merge_into",
) -> EntityId:
    """Enqueue one ``open`` review task for an ambiguous match (mutates no entity).

    ``project_id`` (FI-2 P1) records which project the admitting caller was discovering for, so the
    resolution can join the resulting account to it. It is the *same* value that caller would have
    written the membership with had the candidate been admitted outright, which is why the two can
    never disagree. Optional: a projectless admission leaves it ``NULL`` and its resolution writes
    no membership. A named composite FK anchors ``(project_id, workspace_id)`` to one project, and
    a named CHECK refuses a project without a workspace (migration ``9c8cbd79a0e7``).
    """
    row = await conn.execute(
        text(
            """
            INSERT INTO identity_review_task (
                entity_type, observation_json, candidates_json, proposed_action,
                subject_entity_id, workspace_id, project_id, config_version
            ) VALUES (
                CAST(:entity_type AS entity_type), CAST(:observation_json AS jsonb),
                CAST(:candidates_json AS jsonb), :proposed_action, :subject_entity_id,
                :workspace_id, :project_id, :config_version
            ) RETURNING id
            """
        ),
        {
            "entity_type": observation.entity_type.value,
            "observation_json": serialize_value_json(observation.model_dump(mode="json")),
            "candidates_json": _candidates_json(result),
            "proposed_action": proposed_action,
            "subject_entity_id": subject_entity_id,
            "workspace_id": workspace_id,
            "project_id": project_id,
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
    "workspace_id, project_id, status, resolution, resolved_by, config_version"
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
            "workspace_id": row["workspace_id"],
            "project_id": row["project_id"],
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
    conn: AsyncConnection, *, workspace_id: str | None = None, limit: int = 100
) -> list[ReviewTask]:
    """Open review tasks (optionally tenant-scoped) — the queue the human surface reads."""
    rows = (
        (
            await conn.execute(
                text(
                    f"SELECT {_TASK_COLUMNS} FROM identity_review_task "
                    "WHERE status = 'open' "
                    "AND (CAST(:tenant AS text) IS NULL OR workspace_id = :tenant) "
                    "ORDER BY created_at, id LIMIT :limit"
                ),
                {"tenant": workspace_id, "limit": limit},
            )
        )
        .mappings()
        .all()
    )
    return [_row_to_task(dict(r)) for r in rows]


async def get_review_decision(conn: AsyncConnection, task_id: EntityId) -> ReviewDecision:
    """Read the latest review outcome without making identity policy decisions at the caller.

    ``resolve_*`` appends the authoritative ``review_resolved`` disposition. Keeping this lookup
    in M2 prevents discovery materializers from reaching into identity audit tables directly.
    """

    task = await get_task(conn, task_id)
    if task is None:
        raise ValueError(f"review task {task_id} not found")
    survivor_id = None
    if task.status is ReviewStatus.RESOLVED:
        row = (
            await conn.execute(
                text(
                    "SELECT survivor_id FROM identity_disposition "
                    "WHERE review_task_id = :task_id AND kind = 'review_resolved' "
                    "ORDER BY created_at DESC, id DESC LIMIT 1"
                ),
                {"task_id": task_id},
            )
        ).one_or_none()
        if row is None:
            raise RuntimeError(f"resolved review task {task_id} has no disposition")
        survivor_id = EntityId(row[0]) if row[0] is not None else None
        if (
            task.resolution
            in {
                ReviewResolution.MERGE_INTO,
                ReviewResolution.CREATE_NEW_ENTITY,
            }
            and survivor_id is None
        ):
            raise RuntimeError(f"resolved review task {task_id} has no survivor")
    return ReviewDecision(
        task_id=task.id,
        workspace_id=task.workspace_id,
        status=task.status,
        resolution=task.resolution,
        survivor_id=survivor_id,
    )


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


async def _join_enqueuing_project(
    conn: AsyncConnection, task: ReviewTask, entity_id: EntityId
) -> None:
    """Join a review-resolved account to the project whose admission enqueued the task (FI-2 P1).

    The mid-band admission admitted nothing, so it could not record the membership itself; the
    project rode the task instead, and this closes the loop in the resolution's own transaction.
    Idempotent (first add wins), so a caller that *also* re-joins the account by another route —
    the Exa D4 materializer re-runs its own ensure when it resumes a resolved batch — writes a
    harmless no-op rather than a second, later add.

    Degrades on a task with no project (a projectless admission, or one predating migration
    ``9c8cbd79a0e7``): resolution then behaves exactly as it did before FI-2. Contact tasks are
    skipped — ``project_account`` keys on accounts, and a contact resolves *under* one.

    ``added_via='discovered'``: reaching the mid-band is the identity gate's discovery path. A
    caller whose join provenance differs (``admit(added_via=...)``) does not survive into the task,
    which records no channel — a known, deliberate narrowing, not an oversight.
    """
    if task.project_id is None or task.workspace_id is None:
        return
    if task.entity_type is not EntityType.ACCOUNT:
        return
    await ensure_project_account(
        conn,
        workspace_id=task.workspace_id,
        project_id=task.project_id,
        account_entity_id=entity_id,
        added_via="discovered",
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
            workspace_id=task.workspace_id,
        )
    await _join_enqueuing_project(conn, task, survivor_id)
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
    conn: AsyncConnection,
    task_id: EntityId,
    *,
    resolved_by: str,
    embedder: Embedder = DEFAULT_EMBEDDER,
) -> EntityId:
    """Human decision: none of the candidates match → admit a new ``candidate`` entity from the
    observation (or keep the pre-admitted subject) and close the task.

    ``embedder`` embeds the account this resolution mints (FI-2 §1.2-H1). Unlike :func:`disposition`
    — whose callers include M5's import pipeline, which embeds the entity itself right afterwards —
    this path has **no** caller that embeds on its behalf, so the dependency is *defaulted, not
    optional*: an unembedded human-minted account is invisible to the resolver's ANN arm, so the
    next name-only encounter of that company duplicates it, re-opening the very ambiguity this
    resolution just settled. Making the M2.4 review surface remember to pass one would be a
    silent-by-default trap; the default embedder is deterministic and offline, so always embedding
    here costs one upsert. Pass an explicit embedder only to swap the model.
    """
    task = await get_task(conn, task_id)
    if task is None:
        raise ValueError(f"review task {task_id} not found")
    new_id = task.subject_entity_id
    if new_id is None and task.entity_type is EntityType.ACCOUNT:
        if task.workspace_id is None:
            raise ReviewTaskUnscopedError(
                f"review task {task_id} has no workspace_id; cannot admit a new account entity "
                "([B3×research] accounts are workspace-local)"
            )
        obs = Observation.model_validate(task.observation)
        new_id = await insert_account_entity(
            conn,
            canonical_name=obs.name or "(unnamed)",
            primary_domain=obs.domain,
            aliases=obs.aliases,
            registry_ids=obs.registry_ids,
            workspace_id=task.workspace_id,
        )
        await embed_account(conn, new_id, embedder=embedder)
    if new_id is None:
        raise NotImplementedError(
            "cannot admit a new contact entity without an account_entity_id — the task must carry "
            "a subject_entity_id (committee contact creation is M8)"
        )
    await _join_enqueuing_project(conn, task, new_id)
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
    return new_id


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


async def _latest_auto_merge(
    conn: AsyncConnection, loser_id: EntityId
) -> tuple[EntityId, dict[str, JsonValue]] | None:
    """Survivor + recorded relinquished strong keys of the most recent auto-merge of ``loser``."""
    row = (
        (
            await conn.execute(
                text(
                    "SELECT survivor_id, observation_json FROM identity_disposition "
                    "WHERE loser_id = :loser AND kind = 'auto_merge' "
                    "ORDER BY created_at DESC, id DESC LIMIT 1"
                ),
                {"loser": loser_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None or row["survivor_id"] is None:
        return None
    payload = row["observation_json"] or {}
    relinquished = payload.get("relinquished_strong_keys", {}) if isinstance(payload, dict) else {}
    return EntityId(row["survivor_id"]), relinquished


async def split_merge(
    conn: AsyncConnection,
    loser_id: EntityId,
    *,
    entity_type: EntityType = EntityType.ACCOUNT,
    resolved_by: str,
    config_version: int = 1,
) -> None:
    """Reverse an erroneous prior merge: un-point ``loser``'s ``merged_into``, re-activate it, and
    **restore the strong keys it relinquished** to the survivor at merge time — so the un-merged
    entity is whole again, not a domain-less husk. Append-only claims are untouched; only the entity
    rows' merge pointer + strong keys change (a true inverse of the auto-merge canonicalization).

    Restoration is for the common case (a single merge, reversed before the survivor changed); it
    clears the absorbed keys from the survivor first so the partial-unique constraints permit the
    loser to take them back. If no auto-merge audit is found, only the pointer is un-set.

    **Known gap — FI-2 ``project_account`` membership is NOT restored.** ``mark_merged`` re-points
    the loser's project memberships onto the survivor (``membership.repoint_project_accounts``), and
    this split does not move them back: the revived loser comes back with zero memberships and the
    survivor keeps the absorbed ones. Restoring them needs the moved ``project_id``s recorded in the
    merge's disposition payload (the way ``relinquished_strong_keys`` already is), which is real
    scope for the **M2.4 review-surface composition** — uncomposed today, so the gap is accepted and
    deferred rather than half-built here."""
    table = _entity_table(entity_type)
    prior = await _latest_auto_merge(conn, loser_id)

    if prior is not None and entity_type is EntityType.ACCOUNT:
        survivor_id, relinquished = prior
        domain = relinquished.get("primary_domain")
        registry = relinquished.get("registry_ids") or {}
        absorbed = bool(relinquished.get("domain_absorbed"))
        # Free the absorbed keys from the survivor so the loser can take them back (no clash).
        if absorbed and isinstance(domain, str):
            await conn.execute(
                text(
                    "UPDATE account_entity SET primary_domain = NULL, updated_at = now() "
                    "WHERE id = :s AND primary_domain = :d"
                ),
                {"s": survivor_id, "d": domain},
            )
        if isinstance(registry, dict) and registry:
            # Remove the loser-originated registry ids from the survivor (only where they match).
            await conn.execute(
                text(
                    "UPDATE account_entity "
                    "SET registry_ids = registry_ids - CAST(:keys AS text[]), updated_at = now() "
                    "WHERE id = :s"
                ).bindparams(bindparam("keys", type_=ARRAY(Text()))),
                {"s": survivor_id, "keys": list(registry.keys())},
            )
        # Restore the loser's strong keys and re-activate it.
        await conn.execute(
            text(
                "UPDATE account_entity SET status = 'active', merged_into = NULL, "
                "primary_domain = :d, registry_ids = CAST(:r AS jsonb), updated_at = now() "
                "WHERE id = :id"
            ),
            {
                "id": loser_id,
                "d": domain if isinstance(domain, str) else None,
                "r": serialize_value_json(registry if isinstance(registry, dict) else {}),
            },
        )
    else:
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


async def _field_ttl(conn: AsyncConnection, field_key: str) -> tuple[object, EqualityMode]:
    """The field's freshness TTL **and** equality mode, so the merge-resolved read is mode-aware
    (the conflict check agrees with :func:`claimstore.current_value` and the M9.2 corroborator)."""
    row = (
        await conn.execute(
            text("SELECT freshness_ttl, equality_mode FROM field_definition WHERE field_key = :k"),
            {"k": field_key},
        )
    ).first()
    if row is None:
        return None, EqualityMode.EXACT
    try:
        mode = EqualityMode(row[1]) if row[1] is not None else EqualityMode.EXACT
    except ValueError:
        mode = EqualityMode.EXACT
    return row[0], mode


async def current_value_resolved(
    conn: AsyncConnection,
    entity_id: EntityId,
    field_key: str,
    *,
    scope: WorkspaceScope,
    entity_type: EntityType = EntityType.ACCOUNT,
    policy: MergePolicy = DEFAULT_MERGE_POLICY,
) -> CurrentValue | None:
    """The current truth for a field, **resolved across a merge**: claims attached to any entity
    that merged into the survivor are read under the survivor (substrate §2). Reuses M1's pure
    ``merge_claims`` over the combined live-claim set; **no claim row is UPDATEd** (append-only).

    ``scope`` is **required** (M2.5 — fail-closed), exactly like :func:`current_value`: the
    merge-resolved read crosses *entities*, not *tenants*, so the tenant filter is applied to every
    member's claims — a tenant scope never surfaces another tenant's private claim under the merge.
    """
    survivor = await surviving_id(conn, entity_id, entity_type)
    members = await merged_member_ids(conn, survivor, entity_type)
    claims: list[Claim] = []
    for member in members:
        claims.extend(await claims_for(conn, member, field_key, scope=scope))
    ttl, equality_mode = await _field_ttl(conn, field_key)
    return merge_claims(claims, ttl, policy, _now(), equality_mode)  # type: ignore[arg-type]
