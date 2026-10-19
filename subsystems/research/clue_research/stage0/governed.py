"""Durable governed Stage-0 records and the post-confirmation run-entry proof.

This is storage-oriented orchestration, not an agent. It owns C4's append-only inputs,
statements, product manifests, readiness evidence, and the mutable two-lane recon cursor.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_config import ReadinessSpec
from clue_core import (
    CostCents,
    EntityId,
    OnboardingInputId,
    OnboardingInputKind,
    OnboardingInputRef,
    ProductContextRef,
    ProductContextVersionId,
    ReadinessDecisionId,
    ReadinessGate,
    ReadinessOverrideId,
    ReadinessSnapshotRef,
    ReadinessVerdict,
    ReconRunId,
    RunId,
    UtcDatetime,
    VolunteeredStatementId,
    decode_jsonb,
    new_onboarding_input_id,
    new_product_context_version_id,
    new_readiness_decision_id,
    new_readiness_override_id,
    new_recon_run_id,
    serialize_value_json,
)
from clue_research.stage0.readiness_policy import get_workspace_client_kb_readiness_policy


class ReconLaneStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


class StatementRoute(StrEnum):
    CLAIM = "claim"
    MEMORY = "memory"
    PROJECT_STATE = "project_state"
    FIELD_PROPOSAL = "field_proposal"
    SOURCE_PROPOSAL = "source_proposal"
    UNMAPPED = "unmapped"


class OnboardingInputRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: OnboardingInputId
    workspace_id: str
    brand_id: str
    product_id: str | None
    project_id: str | None
    client_entity_id: EntityId | None
    kind: OnboardingInputKind
    artifact_key: str
    content_sha256: str
    source_ref: str | None
    actor: str
    created_at: UtcDatetime


class ReconRunRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: ReconRunId
    workspace_id: str
    brand_id: str
    product_id: str | None
    project_id: str | None
    client_entity_id: EntityId | None
    dedupe_hash: str
    onboarding_input_ids: tuple[OnboardingInputId, ...]
    fast_run_id: RunId
    background_run_id: RunId
    fast_status: ReconLaneStatus
    background_status: ReconLaneStatus
    fast_budget_cents: CostCents
    background_budget_cents: CostCents
    fast_cost_cents: CostCents
    background_cost_cents: CostCents
    fast_client_kb_version: int | None
    client_kb_version: int | None
    recipe_version: str
    skill_version: str
    failure_code: str | None
    created_at: UtcDatetime
    updated_at: UtcDatetime


class VolunteeredStatementRow(BaseModel):
    """One durable interview statement plus the captured artifact its quote is proven against.

    The quote text itself is deliberately **not** stored — only its offsets and sha256 into the
    ``onboarding_input`` artifact body — so a reader that wants the words must fetch the captured
    artifact and can verify the span it sliced."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: VolunteeredStatementId
    onboarding_input_id: OnboardingInputId
    artifact_key: str
    workspace_id: str
    project_id: str | None
    route_kind: StatementRoute
    route_key: str
    route_ref: str | None
    quote_start: int
    quote_end: int
    quote_sha256: str
    correction_of_id: VolunteeredStatementId | None
    created_at: UtcDatetime
    entity_id: EntityId | None
    # The capture's actor is distinct from the agent/human that classified it.
    input_kind: OnboardingInputKind
    input_actor: str
    input_created_at: UtcDatetime
    input_source_ref: str | None
    recorded_by_actor: str


class StatementCounts(BaseModel):
    """How many durable routing receipts one captured input produced.

    ``total`` is every statement written for the input — the structural answer to "did this turn
    route the human's words anywhere at all?". ``non_unmapped`` excludes the
    :attr:`StatementRoute.UNMAPPED` escape hatch, which is an honest "nothing here is material" and
    therefore is *not* new evidence for a readiness recompute."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    total: int
    non_unmapped: int


class ReadinessDecisionRow(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: ReadinessDecisionId
    workspace_id: str
    brand_id: str
    product_id: str | None
    project_id: str | None
    client_entity_id: EntityId | None
    client_kb_version: int | None
    icp_key: str | None
    icp_version: int | None
    product_context_version_id: ProductContextVersionId | None
    gate: ReadinessGate
    verdict: ReadinessVerdict
    spec_version: int
    gap_refs: tuple[dict[str, JsonValue], ...]
    field_proposal_refs: tuple[str, ...]
    source_proposal_refs: tuple[str, ...]
    ingestion_refs: tuple[str, ...]
    metrics: dict[str, JsonValue]
    reason_codes: tuple[str, ...]
    agent_sufficiency_status: str
    agent_sufficiency_ref: str | None
    created_by_actor: str
    created_at: UtcDatetime


_ONBOARDING_COLUMNS = (
    "id, workspace_id, brand_id, product_id, project_id, client_entity_id, kind, artifact_key, "
    "content_sha256, source_ref, actor, created_at"
)
_RECON_COLUMNS = (
    "id, workspace_id, brand_id, product_id, project_id, client_entity_id, dedupe_hash, "
    "onboarding_input_ids, fast_run_id, background_run_id, fast_status, background_status, "
    "fast_budget_cents, background_budget_cents, fast_cost_cents, background_cost_cents, "
    "fast_client_kb_version, client_kb_version, recipe_version, skill_version, failure_code, "
    "created_at, updated_at"
)
_READINESS_COLUMNS = (
    "id, workspace_id, brand_id, product_id, project_id, client_entity_id, client_kb_version, "
    "icp_key, icp_version, product_context_version_id, gate, verdict, spec_version, gap_refs, "
    "field_proposal_refs, source_proposal_refs, ingestion_refs, metrics, reason_codes, "
    "agent_sufficiency_status, agent_sufficiency_ref, created_by_actor, created_at"
)


async def submit_onboarding_input(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    brand_id: str,
    kind: OnboardingInputKind,
    artifact_key: str,
    content_sha256: str,
    actor: str,
    product_id: str | None = None,
    project_id: str | None = None,
    client_entity_id: EntityId | None = None,
    source_ref: str | None = None,
    onboarding_input_id: OnboardingInputId | None = None,
) -> OnboardingInputRef:
    """Capture one already-snapshotted input; the artifact FK proves capture-before-use."""
    input_id = onboarding_input_id or new_onboarding_input_id()
    await conn.execute(
        text(
            """
            INSERT INTO onboarding_input (
                id, workspace_id, brand_id, product_id, project_id, client_entity_id, kind,
                artifact_key, content_sha256, source_ref, actor
            )
            VALUES (
                :id, :workspace_id, :brand_id, :product_id, :project_id, :client_entity_id,
                :kind, :artifact_key, :content_sha256, :source_ref, :actor
            )
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {
            "id": input_id,
            "workspace_id": workspace_id,
            "brand_id": brand_id,
            "product_id": product_id,
            "project_id": project_id,
            "client_entity_id": client_entity_id,
            "kind": kind.value,
            "artifact_key": artifact_key,
            "content_sha256": content_sha256,
            "source_ref": source_ref,
            "actor": actor,
        },
    )
    row = await get_onboarding_input(conn, input_id, workspace_id=workspace_id)
    if row is None:
        raise ValueError("onboarding input id is already owned by another workspace")
    expected = (brand_id, product_id, project_id, artifact_key, content_sha256)
    actual = (
        row.brand_id,
        row.product_id,
        row.project_id,
        row.artifact_key,
        row.content_sha256,
    )
    if actual != expected:
        raise ValueError("onboarding input id replayed with different immutable content")
    return OnboardingInputRef(
        onboarding_input_id=row.id,
        artifact_key=row.artifact_key,
        kind=row.kind,
    )


async def get_onboarding_input(
    conn: AsyncConnection,
    input_id: OnboardingInputId,
    *,
    workspace_id: str,
) -> OnboardingInputRow | None:
    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {_ONBOARDING_COLUMNS} FROM onboarding_input "
                    "WHERE id = :id AND workspace_id = :workspace_id"
                ),
                {"id": input_id, "workspace_id": workspace_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    return OnboardingInputRow.model_validate(dict(row)) if row is not None else None


async def get_onboarding_input_for_artifact(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
    artifact_key: str,
    actor: str,
    kind: OnboardingInputKind | None = None,
) -> OnboardingInputRow | None:
    """Return the newest capture record for exactly this artifact, in this project, by this actor.

    Every part of the scope is load-bearing, because an artifact key is *content-addressed* and
    ``submit_onboarding_input`` is a writable tool: a caller who resolves "which capture is this
    artifact" on ``(workspace_id, artifact_key)`` alone lets anything that can write an
    ``onboarding_input`` row decide the answer, simply by writing a newer one.

    * ``project_id`` — two projects in one workspace whose users send a byte-identical short
      answer ("confirm") share one artifact key. Without this they cross-select, and each other's
      turns are attributed to the wrong project.
    * ``actor`` — an agent-written row (``actor='agent'``) must never out-rank the human capture
      of the turn the agent is answering. Callers resolving a *user turn* pass ``'human'``.
    * ``kind`` — a ``website``/``upload`` capture of the same bytes is not the user's turn.

    Within that scope the newest row is the one just written (capture precedes use), and every
    candidate carries the same immutable ``artifact_key``/``content_sha256`` pair, so the choice
    can never change which bytes a caller is handed. ``id`` breaks a ``created_at`` tie so the
    answer is deterministic rather than storage-order dependent.

    ``project_id`` is required, and the column is nullable — so a capture surface that omits it
    writes a row this lookup can never select, and the turn it captured is **unbindable**: a tool
    needing turn authority is refused rather than served a scope-free match. That is deliberate
    (fail-closed), and it is the one thing a future human-capture surface must not get wrong:
    capture the project, or accept that the turn cannot be bound.
    """

    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {_ONBOARDING_COLUMNS} FROM onboarding_input "
                    "WHERE workspace_id = :workspace_id AND project_id = :project_id "
                    "AND artifact_key = :artifact_key AND actor = :actor "
                    "AND (CAST(:kind AS text) IS NULL OR kind = :kind) "
                    "ORDER BY created_at DESC, id DESC LIMIT 1"
                ),
                {
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "artifact_key": artifact_key,
                    "actor": actor,
                    "kind": kind.value if kind is not None else None,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    return OnboardingInputRow.model_validate(dict(row)) if row is not None else None


def recon_dedupe_hash(
    *,
    workspace_id: str,
    brand_id: str,
    product_id: str | None,
    identity: str,
) -> str:
    canonical = "\0".join((workspace_id, brand_id, product_id or "", identity.strip().casefold()))
    return hashlib.sha256(canonical.encode()).hexdigest()


async def start_recon(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    brand_id: str,
    dedupe_hash: str,
    onboarding_input_ids: Sequence[OnboardingInputId],
    fast_budget_cents: CostCents,
    background_budget_cents: CostCents,
    dedupe_ttl_seconds: int,
    product_id: str | None = None,
    project_id: str | None = None,
    client_entity_id: EntityId | None = None,
    recipe_version: str = "recipe0@1",
    skill_version: str = "stage0-interview@1",
    recon_run_id: ReconRunId | None = None,
) -> ReconRunRow:
    """Return an exact replay/live duplicate, or create one two-lane cursor."""
    # Serialize equivalent starts before the read/create decision. A time-bounded partial UNIQUE
    # index cannot express ``expires_at > now()`` safely in Postgres; the transaction advisory
    # lock gives us one logical recon without making expired history mutable.
    await conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
        {"lock_key": f"stage0-recon:{workspace_id}:{dedupe_hash}"},
    )
    if recon_run_id is not None:
        exact = await get_recon(conn, recon_run_id, workspace_id=workspace_id)
        if exact is not None:
            expected = (
                brand_id,
                product_id,
                project_id,
                dedupe_hash,
                tuple(onboarding_input_ids),
                recipe_version,
                skill_version,
            )
            actual = (
                exact.brand_id,
                exact.product_id,
                exact.project_id,
                exact.dedupe_hash,
                exact.onboarding_input_ids,
                exact.recipe_version,
                exact.skill_version,
            )
            if actual != expected:
                raise ValueError("recon run id replayed with different immutable context")
            return exact
    existing = (
        (
            await conn.execute(
                text(
                    f"SELECT {_RECON_COLUMNS} FROM recon_run "
                    "WHERE workspace_id = :workspace_id AND dedupe_hash = :dedupe_hash "
                    "AND dedupe_expires_at > now() ORDER BY created_at DESC LIMIT 1"
                ),
                {"workspace_id": workspace_id, "dedupe_hash": dedupe_hash},
            )
        )
        .mappings()
        .one_or_none()
    )
    if existing is not None:
        return _recon_row(dict(existing))

    run_id = recon_run_id if recon_run_id is not None else new_recon_run_id()
    await conn.execute(
        text(
            """
            INSERT INTO recon_run (
                id, workspace_id, brand_id, product_id, project_id, client_entity_id,
                dedupe_hash, dedupe_expires_at, onboarding_input_ids,
                fast_run_id, background_run_id, fast_budget_cents, background_budget_cents,
                recipe_version, skill_version
            )
            VALUES (
                :id, :workspace_id, :brand_id, :product_id, :project_id, :client_entity_id,
                :dedupe_hash, now() + (:ttl_seconds * interval '1 second'),
                CAST(:input_ids AS jsonb), :fast_run_id, :background_run_id,
                :fast_budget, :background_budget, :recipe_version, :skill_version
            )
            """
        ),
        {
            "id": run_id,
            "workspace_id": workspace_id,
            "brand_id": brand_id,
            "product_id": product_id,
            "project_id": project_id,
            "client_entity_id": client_entity_id,
            "dedupe_hash": dedupe_hash,
            "ttl_seconds": dedupe_ttl_seconds,
            "input_ids": serialize_value_json([str(item) for item in onboarding_input_ids]),
            "fast_run_id": RunId(uuid5(NAMESPACE_URL, f"stage0-recon-fast:{run_id}")),
            "background_run_id": RunId(uuid5(NAMESPACE_URL, f"stage0-recon-background:{run_id}")),
            "fast_budget": fast_budget_cents,
            "background_budget": background_budget_cents,
            "recipe_version": recipe_version,
            "skill_version": skill_version,
        },
    )
    created = await get_recon(conn, run_id, workspace_id=workspace_id)
    assert created is not None
    return created


async def get_recon(
    conn: AsyncConnection, recon_run_id: ReconRunId, *, workspace_id: str
) -> ReconRunRow | None:
    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {_RECON_COLUMNS} FROM recon_run "
                    "WHERE id = :id AND workspace_id = :workspace_id"
                ),
                {"id": recon_run_id, "workspace_id": workspace_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    return _recon_row(dict(row)) if row is not None else None


async def transition_recon_lane(
    conn: AsyncConnection,
    *,
    recon_run_id: ReconRunId,
    workspace_id: str,
    lane: str,
    status: ReconLaneStatus,
    cost_cents: CostCents | None = None,
    client_kb_version: int | None = None,
    client_entity_id: EntityId | None = None,
    failure_code: str | None = None,
) -> ReconRunRow:
    """Advance one lane without letting a retry manufacture a second transition.

    A FAST-lane failure additionally releases the run's dedupe slot
    (``dedupe_expires_at = now()``): a run that produced no fast Client-KB is not a live
    equivalent worth sharing, and releasing the slot is what makes a user-initiated retry
    able to mint a fresh recon instead of replaying the failure forever (FI-4 slice-2
    review, BE-B2). The terminal-state latch on the lane itself is untouched — a failed
    lane never transitions again; retry means a NEW run.
    """
    if lane not in {"fast", "background"}:
        raise ValueError("lane must be 'fast' or 'background'")
    status_column = f"{lane}_status"
    cost_column = f"{lane}_cost_cents"
    started_column = f"{lane}_started_at"
    completed_column = f"{lane}_completed_at"
    kb_column = "fast_client_kb_version" if lane == "fast" else "client_kb_version"
    release_dedupe = lane == "fast" and status is ReconLaneStatus.FAILED
    await conn.execute(
        text(
            f"""
            UPDATE recon_run
            SET {status_column} = :status,
                {cost_column} = COALESCE(:cost_cents, {cost_column}),
                {kb_column} = COALESCE(:kb_version, {kb_column}),
                client_entity_id = COALESCE(:client_entity_id, client_entity_id),
                failure_code = COALESCE(:failure_code, failure_code),
                dedupe_expires_at = CASE
                    WHEN :release_dedupe THEN now()
                    ELSE dedupe_expires_at
                END,
                {started_column} = CASE
                    WHEN :status = 'running' THEN COALESCE({started_column}, now())
                    ELSE {started_column}
                END,
                {completed_column} = CASE
                    WHEN :status IN ('completed', 'failed') THEN
                        COALESCE({completed_column}, now())
                    ELSE {completed_column}
                END,
                updated_at = now()
            WHERE id = :id AND workspace_id = :workspace_id
              AND {status_column} <> :status
              AND NOT ({status_column} IN ('completed', 'failed'))
            """
        ),
        {
            "id": recon_run_id,
            "workspace_id": workspace_id,
            "status": status.value,
            "cost_cents": cost_cents,
            "kb_version": client_kb_version,
            "client_entity_id": client_entity_id,
            "failure_code": failure_code,
            "release_dedupe": release_dedupe,
        },
    )
    row = await get_recon(conn, recon_run_id, workspace_id=workspace_id)
    if row is None:
        raise ValueError("recon run does not exist in this workspace")
    return row


async def record_statement(
    conn: AsyncConnection,
    *,
    onboarding_input_id: OnboardingInputId,
    workspace_id: str,
    brand_id: str,
    route_kind: StatementRoute,
    route_key: str,
    quote: str,
    quote_start: int,
    quote_end: int,
    created_by_actor: str,
    route_ref: str | None = None,
    product_id: str | None = None,
    project_id: str | None = None,
    client_entity_id: EntityId | None = None,
    entity_id: EntityId | None = None,
    correction_of_id: VolunteeredStatementId | None = None,
) -> VolunteeredStatementId:
    statement_id = VolunteeredStatementId(
        uuid5(
            NAMESPACE_URL,
            f"stage0-statement:{onboarding_input_id}:{entity_id or client_entity_id}:{route_key}",
        )
    )
    quote_hash = hashlib.sha256(quote.encode()).hexdigest()
    await conn.execute(
        text(
            """
                INSERT INTO volunteered_statement (
                    id, onboarding_input_id, workspace_id, brand_id, product_id, project_id,
                    client_entity_id, entity_id, route_kind, route_key, route_ref,
                    quote_start, quote_end, quote_sha256, correction_of_id, created_by_actor
                )
                VALUES (
                    :id, :onboarding_input_id, :workspace_id, :brand_id, :product_id,
                    :project_id, :client_entity_id, :entity_id, :route_kind, :route_key,
                    :route_ref, :quote_start, :quote_end, :quote_sha256, :correction_of_id,
                    :created_by_actor
                )
                ON CONFLICT (id) DO NOTHING
            """
        ),
        {
            "id": statement_id,
            "onboarding_input_id": onboarding_input_id,
            "workspace_id": workspace_id,
            "brand_id": brand_id,
            "product_id": product_id,
            "project_id": project_id,
            "client_entity_id": client_entity_id,
            "entity_id": entity_id,
            "route_kind": route_kind.value,
            "route_key": route_key,
            "route_ref": route_ref,
            "quote_start": quote_start,
            "quote_end": quote_end,
            "quote_sha256": quote_hash,
            "correction_of_id": correction_of_id,
            "created_by_actor": created_by_actor,
        },
    )
    return statement_id


async def read_statements(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
    route_kind: StatementRoute = StatementRoute.PROJECT_STATE,
    include_superseded: bool = False,
) -> tuple[VolunteeredStatementRow, ...]:
    """The client's **live** statements of one route kind under this project, oldest first.

    This is the read side of the interview seam: ``project_state`` statements are the client's own
    targeting/strategy words, durable but *not* claim-shaped, and ICP synthesis grounds on them
    alongside the versioned Client-KB claims.

    The table is append-only, so a client who changes their mind lands a **new** statement carrying
    ``correction_of_id``. Latest-correction-wins: a statement another statement corrects is
    superseded and is excluded by default — a retracted "we target healthcare" must not keep
    steering downstream synthesis. Pass ``include_superseded=True`` for the full audit history."""
    superseded_filter = (
        ""
        if include_superseded
        else """
                      AND NOT EXISTS (
                          SELECT 1 FROM volunteered_statement c
                          WHERE c.correction_of_id = s.id
                            AND c.workspace_id = s.workspace_id
                      )"""
    )
    rows = (
        (
            await conn.execute(
                text(
                    f"""
                    SELECT s.id, s.onboarding_input_id, i.artifact_key, s.workspace_id,
                           s.project_id, s.route_kind, s.route_key, s.route_ref,
                           s.quote_start, s.quote_end, s.quote_sha256, s.correction_of_id,
                           s.created_at, s.entity_id, s.created_by_actor AS recorded_by_actor,
                           i.kind AS input_kind, i.actor AS input_actor,
                           i.created_at AS input_created_at, i.source_ref AS input_source_ref
                    FROM volunteered_statement s
                    JOIN onboarding_input i ON i.id = s.onboarding_input_id
                    WHERE s.workspace_id = :workspace_id
                      AND s.project_id = :project_id
                      AND s.route_kind = :route_kind{superseded_filter}
                    ORDER BY s.created_at, s.id
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "project_id": project_id,
                    "route_kind": route_kind.value,
                },
            )
        )
        .mappings()
        .all()
    )
    return tuple(VolunteeredStatementRow.model_validate(dict(row)) for row in rows)


async def count_statements_for_input(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    onboarding_input_id: OnboardingInputId,
) -> StatementCounts:
    """Count the routing receipts one captured onboarding input produced, by route class.

    This is the durable answer to "did this turn actually record anything?" — the question a
    caller must be able to ask *without* reading prose. It deliberately spans every route kind
    (unlike :func:`read_statements`, which serves one route kind under a project) and keys on the
    onboarding input rather than the project, because the input is what identifies a single
    captured user turn.

    Superseded statements are counted: a correction is still a receipt for the turn that made it.
    """

    row = (
        (
            await conn.execute(
                text(
                    """
                    SELECT count(*) AS total,
                           count(*) FILTER (WHERE route_kind <> :unmapped) AS non_unmapped
                    FROM volunteered_statement
                    WHERE workspace_id = :workspace_id
                      AND onboarding_input_id = :onboarding_input_id
                    """
                ),
                {
                    "workspace_id": workspace_id,
                    "onboarding_input_id": onboarding_input_id,
                    "unmapped": StatementRoute.UNMAPPED.value,
                },
            )
        )
        .mappings()
        .one()
    )
    return StatementCounts(total=int(row["total"]), non_unmapped=int(row["non_unmapped"]))


def _manifest_hash(payload: Mapping[str, JsonValue]) -> str:
    return hashlib.sha256(serialize_value_json(dict(payload)).encode()).hexdigest()


async def compile_product_context(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    brand_id: str,
    product_id: str,
    client_entity_id: EntityId,
    client_kb_version: int,
    claim_refs: Sequence[str],
    memory_refs: Sequence[str] = (),
    artifact_refs: Sequence[str] = (),
    freshness_snapshot: Mapping[str, JsonValue] | None = None,
    compiler_version: str = "product-context@1",
) -> ProductContextRef:
    """Compile an immutable reference manifest for one product context.

    The manifest may reference account-wide company claims plus claims for this exact product.
    Claims belonging to another product remain forbidden.
    """
    unique_claims = tuple(dict.fromkeys(claim_refs))
    if unique_claims:
        count = (
            await conn.execute(
                text(
                    """
                    SELECT count(*)
                    FROM claim
                        WHERE id = ANY(CAST(:claim_ids AS uuid[]))
                          AND workspace_id = :workspace_id
                          AND (product_id IS NULL OR product_id = :product_id)
                    """
                ),
                {
                    "claim_ids": list(unique_claims),
                    "workspace_id": workspace_id,
                    "product_id": product_id,
                },
            )
        ).scalar_one()
        if count != len(unique_claims):
            raise ValueError("product context contains an absent, foreign, or unscoped claim")
    unique_artifacts = tuple(dict.fromkeys(artifact_refs))
    if unique_artifacts:
        artifact_count = (
            await conn.execute(
                text(
                    """
                    SELECT count(*)
                    FROM artifact
                    WHERE storage_key = ANY(CAST(:artifact_keys AS text[]))
                      AND workspace_id = :workspace_id
                    """
                ),
                {
                    "artifact_keys": list(unique_artifacts),
                    "workspace_id": workspace_id,
                },
            )
        ).scalar_one()
        if artifact_count != len(unique_artifacts):
            raise ValueError("product context contains an absent or foreign artifact")
    payload: dict[str, JsonValue] = {
        "workspace_id": workspace_id,
        "brand_id": brand_id,
        "product_id": product_id,
        "client_entity_id": str(client_entity_id),
        "client_kb_version": client_kb_version,
        "claim_refs": list(unique_claims),
        "memory_refs": list(dict.fromkeys(memory_refs)),
        "artifact_refs": list(unique_artifacts),
        "freshness_snapshot": dict(freshness_snapshot or {}),
        "compiler_version": compiler_version,
    }
    manifest_hash = _manifest_hash(payload)
    await conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
        {"lock_key": f"stage0-context:{workspace_id}:{product_id}:{manifest_hash}"},
    )
    existing_context = (
        await conn.execute(
            text(
                "SELECT id FROM product_context_version "
                "WHERE workspace_id = :workspace_id AND product_id = :product_id "
                "AND manifest_hash = :manifest_hash"
            ),
            {
                "workspace_id": workspace_id,
                "product_id": product_id,
                "manifest_hash": manifest_hash,
            },
        )
    ).scalar_one_or_none()
    if existing_context is not None:
        return ProductContextRef(
            workspace_id=workspace_id,
            brand_id=brand_id,
            product_id=product_id,
            version_id=ProductContextVersionId(existing_context),
        )
    context_id = new_product_context_version_id()
    row = (
        await conn.execute(
            text(
                """
                INSERT INTO product_context_version (
                    id, workspace_id, brand_id, product_id, client_entity_id,
                    client_kb_version, claim_refs, memory_refs, artifact_refs,
                    freshness_snapshot, manifest_hash, compiler_version
                )
                VALUES (
                    :id, :workspace_id, :brand_id, :product_id, :client_entity_id,
                    :client_kb_version, CAST(:claim_refs AS jsonb), CAST(:memory_refs AS jsonb),
                    CAST(:artifact_refs AS jsonb), CAST(:freshness AS jsonb),
                    :manifest_hash, :compiler_version
                )
                RETURNING id
                """
            ),
            {
                "id": context_id,
                "workspace_id": workspace_id,
                "brand_id": brand_id,
                "product_id": product_id,
                "client_entity_id": client_entity_id,
                "client_kb_version": client_kb_version,
                "claim_refs": serialize_value_json(list(unique_claims)),
                "memory_refs": serialize_value_json(list(dict.fromkeys(memory_refs))),
                "artifact_refs": serialize_value_json(list(unique_artifacts)),
                "freshness": serialize_value_json(dict(freshness_snapshot or {})),
                "manifest_hash": manifest_hash,
                "compiler_version": compiler_version,
            },
        )
    ).one()
    return ProductContextRef(
        workspace_id=workspace_id,
        brand_id=brand_id,
        product_id=product_id,
        version_id=ProductContextVersionId(row[0]),
    )


async def ensure_readiness_spec(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    spec: ReadinessSpec,
    created_by: str = "system",
) -> int:
    payload = spec.model_dump(mode="json")
    policy_json = serialize_value_json(payload)
    policy_hash = hashlib.sha256(policy_json.encode()).hexdigest()
    existing = (
        await conn.execute(
            text(
                "SELECT version FROM readiness_spec_revision "
                "WHERE workspace_id = :workspace_id AND policy_hash = :policy_hash"
            ),
            {"workspace_id": workspace_id, "policy_hash": policy_hash},
        )
    ).scalar_one_or_none()
    if existing is not None:
        return int(existing)
    await conn.execute(
        text("SELECT workspace_id FROM workspace WHERE workspace_id = :id FOR UPDATE"),
        {"id": workspace_id},
    )
    existing_after_lock = (
        await conn.execute(
            text(
                "SELECT version FROM readiness_spec_revision "
                "WHERE workspace_id = :workspace_id AND policy_hash = :policy_hash"
            ),
            {"workspace_id": workspace_id, "policy_hash": policy_hash},
        )
    ).scalar_one_or_none()
    if existing_after_lock is not None:
        return int(existing_after_lock)
    version = int(
        (
            await conn.execute(
                text(
                    "SELECT COALESCE(max(version), 0) + 1 FROM readiness_spec_revision "
                    "WHERE workspace_id = :workspace_id"
                ),
                {"workspace_id": workspace_id},
            )
        ).scalar_one()
    )
    await conn.execute(
        text(
            """
            INSERT INTO readiness_spec_revision (
                workspace_id, version, policy_json, policy_hash, created_by
            )
            VALUES (
                :workspace_id, :version, CAST(:policy_json AS jsonb), :policy_hash, :created_by
            )
            """
        ),
        {
            "workspace_id": workspace_id,
            "version": version,
            "policy_json": policy_json,
            "policy_hash": policy_hash,
            "created_by": created_by,
        },
    )
    return version


async def evaluate_readiness(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    brand_id: str,
    gate: ReadinessGate,
    spec: ReadinessSpec,
    metrics: Mapping[str, JsonValue],
    created_by_actor: str,
    product_id: str | None = None,
    project_id: str | None = None,
    client_entity_id: EntityId | None = None,
    client_kb_version: int | None = None,
    icp_key: str | None = None,
    icp_version: int | None = None,
    product_context_version_id: ProductContextVersionId | None = None,
    gap_refs: Sequence[Mapping[str, JsonValue]] = (),
    field_proposal_refs: Sequence[str] = (),
    source_proposal_refs: Sequence[str] = (),
    ingestion_refs: Sequence[str] = (),
    agent_sufficiency_status: str = "not_evaluated",
    agent_sufficiency_ref: str | None = None,
    additional_reason_codes: Sequence[str] = (),
    readiness_decision_id: ReadinessDecisionId | None = None,
) -> ReadinessSnapshotRef:
    workspace_policy = await get_workspace_client_kb_readiness_policy(
        conn, workspace_id=workspace_id
    )
    floor = spec.floors[gate]
    coverage = _number(metrics.get("coverage_ratio"), default=0.0)
    verified = int(_number(metrics.get("verified_claims"), default=0.0))
    policy_blocks = int(_number(metrics.get("open_policy_blocks"), default=0.0))
    raw_available_fields = metrics.get("available_field_keys", [])
    available_fields = (
        {item for item in raw_available_fields if isinstance(item, str)}
        if isinstance(raw_available_fields, list)
        else set()
    )
    metrics_for_record: dict[str, JsonValue] = dict(metrics)
    workspace_required = (
        workspace_policy.required_field_keys if workspace_policy is not None else ()
    )
    workspace_missing = sorted(set(workspace_required) - available_fields)
    metrics_for_record.update(
        {
            "workspace_readiness_policy_version": (
                workspace_policy.version if workspace_policy is not None else 0
            ),
            "workspace_required_field_keys": cast(list[JsonValue], list(workspace_required)),
            "workspace_required_missing_field_keys": cast(list[JsonValue], workspace_missing),
        }
    )
    # Trusted callers may add deterministic scope/configuration failures which are not numeric
    # floor measurements (for example, no project-bound Client KB).  They are function arguments,
    # not a key hidden inside ``metrics``, so the v1 model-authored metric map cannot manufacture
    # or clear them.
    reasons: list[str] = list(dict.fromkeys(additional_reason_codes))
    if coverage < floor.min_coverage_ratio:
        reasons.append("coverage_below_floor")
    if verified < floor.min_verified_claims:
        reasons.append("verified_claims_below_floor")
    if policy_blocks > floor.max_open_policy_blocks:
        reasons.append("open_policy_blocks")
    if floor.require_product_id and product_id is None:
        reasons.append("product_not_confirmed")
    if floor.require_confirmed_icp and (icp_key is None or icp_version is None):
        reasons.append("icp_not_confirmed")
    if agent_sufficiency_status == "insufficient":
        reasons.append("agent_sufficiency_insufficient")
    if missing := sorted(set(floor.required_field_keys) - available_fields):
        reasons.extend(f"missing_field:{key}" for key in missing)
    reasons.extend(f"missing_workspace_field:{key}" for key in workspace_missing)
    reasons = list(dict.fromkeys(reasons))
    spec_version = await ensure_readiness_spec(conn, workspace_id=workspace_id, spec=spec)
    decision_id = (
        readiness_decision_id if readiness_decision_id is not None else new_readiness_decision_id()
    )
    verdict = ReadinessVerdict.NOT_READY if reasons else ReadinessVerdict.READY
    await conn.execute(
        text(
            """
            INSERT INTO readiness_decision (
                id, workspace_id, brand_id, product_id, project_id, client_entity_id,
                client_kb_version, icp_key, icp_version, product_context_version_id,
                gate, verdict, spec_version, gap_refs, field_proposal_refs,
                source_proposal_refs, ingestion_refs, metrics, reason_codes,
                agent_sufficiency_status, agent_sufficiency_ref, created_by_actor
            )
            VALUES (
                :id, :workspace_id, :brand_id, :product_id, :project_id, :client_entity_id,
                :client_kb_version, :icp_key, :icp_version, :product_context_version_id,
                :gate, :verdict, :spec_version, CAST(:gap_refs AS jsonb),
                CAST(:field_refs AS jsonb), CAST(:source_refs AS jsonb),
                CAST(:ingestion_refs AS jsonb), CAST(:metrics AS jsonb),
                CAST(:reasons AS jsonb), :agent_status, :agent_ref, :actor
            )
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {
            "id": decision_id,
            "workspace_id": workspace_id,
            "brand_id": brand_id,
            "product_id": product_id,
            "project_id": project_id,
            "client_entity_id": client_entity_id,
            "client_kb_version": client_kb_version,
            "icp_key": icp_key,
            "icp_version": icp_version,
            "product_context_version_id": product_context_version_id,
            "gate": gate.value,
            "verdict": verdict.value,
            "spec_version": spec_version,
            "gap_refs": serialize_value_json([dict(item) for item in gap_refs]),
            "field_refs": serialize_value_json(list(field_proposal_refs)),
            "source_refs": serialize_value_json(list(source_proposal_refs)),
            "ingestion_refs": serialize_value_json(list(ingestion_refs)),
            "metrics": serialize_value_json(metrics_for_record),
            "reasons": serialize_value_json(reasons),
            "agent_status": agent_sufficiency_status,
            "agent_ref": agent_sufficiency_ref,
            "actor": created_by_actor,
        },
    )
    stored = await get_readiness_decision(conn, decision_id, workspace_id=workspace_id)
    if stored is None:
        raise ValueError("readiness decision id is already owned by another workspace")
    expected = (
        brand_id,
        product_id,
        project_id,
        client_entity_id,
        client_kb_version,
        icp_key,
        icp_version,
        product_context_version_id,
        gate,
        verdict,
        spec_version,
    )
    actual = (
        stored.brand_id,
        stored.product_id,
        stored.project_id,
        stored.client_entity_id,
        stored.client_kb_version,
        stored.icp_key,
        stored.icp_version,
        stored.product_context_version_id,
        stored.gate,
        stored.verdict,
        stored.spec_version,
    )
    if actual != expected:
        raise ValueError("readiness decision id replayed with different immutable context")
    expected_payload = (
        tuple(dict(item) for item in gap_refs),
        tuple(field_proposal_refs),
        tuple(source_proposal_refs),
        tuple(ingestion_refs),
        metrics_for_record,
        tuple(reasons),
        agent_sufficiency_status,
        agent_sufficiency_ref,
        created_by_actor,
    )
    actual_payload = (
        stored.gap_refs,
        stored.field_proposal_refs,
        stored.source_proposal_refs,
        stored.ingestion_refs,
        stored.metrics,
        stored.reason_codes,
        stored.agent_sufficiency_status,
        stored.agent_sufficiency_ref,
        stored.created_by_actor,
    )
    if actual_payload != expected_payload:
        raise ValueError("readiness decision id replayed with different immutable payload")
    return ReadinessSnapshotRef(
        readiness_decision_id=decision_id,
        gate=gate,
        verdict=verdict,
        spec_version=spec_version,
    )


async def get_readiness_decision(
    conn: AsyncConnection,
    decision_id: ReadinessDecisionId,
    *,
    workspace_id: str,
) -> ReadinessDecisionRow | None:
    row = (
        (
            await conn.execute(
                text(
                    f"SELECT {_READINESS_COLUMNS} FROM readiness_decision "
                    "WHERE id = :id AND workspace_id = :workspace_id"
                ),
                {"id": decision_id, "workspace_id": workspace_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    return _readiness_row(dict(row)) if row is not None else None


async def read_readiness_decisions(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
) -> tuple[ReadinessDecisionRow, ...]:
    """This project's readiness ledger, oldest first — the append-only decision history.

    The read side of :func:`evaluate_readiness`. Ordered ``(created_at, id)`` so "the latest
    decision" is a deterministic choice even when two decisions share a timestamp, and so a reader
    that pages the ledger sees a stable sequence. Every gate and actor is returned: filtering to
    *authoritative* (``created_by_actor='system'``) or lineage-current rows is a policy the caller
    applies, not a truth the store hides.
    """

    rows = (
        (
            await conn.execute(
                text(
                    f"SELECT {_READINESS_COLUMNS} FROM readiness_decision "
                    "WHERE workspace_id = :workspace_id AND project_id = :project_id "
                    "ORDER BY created_at, id"
                ),
                {"workspace_id": workspace_id, "project_id": project_id},
            )
        )
        .mappings()
        .all()
    )
    return tuple(_readiness_row(dict(row)) for row in rows)


async def override_readiness(
    conn: AsyncConnection,
    *,
    decision_id: ReadinessDecisionId,
    workspace_id: str,
    gate: ReadinessGate,
    actor: str,
    reason: str,
) -> ReadinessOverrideId:
    """Record a just-go decision. The Python and DB layers both enforce human-only."""
    if actor != "human":
        raise PermissionError("only a human may override Stage-0 readiness")
    decision = await get_readiness_decision(conn, decision_id, workspace_id=workspace_id)
    if decision is None or decision.gate is not gate:
        raise ValueError("readiness decision does not exist for this workspace and gate")
    await conn.execute(
        text("SELECT id FROM readiness_decision WHERE id = :id FOR UPDATE"),
        {"id": decision_id},
    )
    existing = (
        await conn.execute(
            text("SELECT id FROM readiness_override WHERE readiness_decision_id = :decision_id"),
            {"decision_id": decision_id},
        )
    ).scalar_one_or_none()
    if existing is not None:
        return ReadinessOverrideId(existing)
    override_id = new_readiness_override_id()
    row = (
        await conn.execute(
            text(
                """
                INSERT INTO readiness_override (
                    id, readiness_decision_id, workspace_id, gate, actor, reason
                )
                VALUES (:id, :decision_id, :workspace_id, :gate, :actor, :reason)
                RETURNING id
                """
            ),
            {
                "id": override_id,
                "decision_id": decision_id,
                "workspace_id": workspace_id,
                "gate": gate.value,
                "actor": actor,
                "reason": reason,
            },
        )
    ).one()
    return ReadinessOverrideId(row[0])


def _recon_row(row: dict[str, object]) -> ReconRunRow:
    payload = dict(row)
    payload["onboarding_input_ids"] = tuple(
        OnboardingInputId(UUID(item)) for item in decode_jsonb(row["onboarding_input_ids"])
    )
    return ReconRunRow.model_validate(payload)


def _readiness_row(row: dict[str, object]) -> ReadinessDecisionRow:
    payload = dict(row)
    for key in (
        "gap_refs",
        "field_proposal_refs",
        "source_proposal_refs",
        "ingestion_refs",
        "reason_codes",
    ):
        payload[key] = tuple(decode_jsonb(row[key]))
    payload["metrics"] = decode_jsonb(row["metrics"])
    return ReadinessDecisionRow.model_validate(payload)


def _number(value: JsonValue | None, *, default: float) -> float:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float, str)):
        try:
            return float(value)
        except ValueError:
            return default
    return default


__all__ = [
    "OnboardingInputRow",
    "ReadinessDecisionRow",
    "ReconLaneStatus",
    "ReconRunRow",
    "StatementCounts",
    "StatementRoute",
    "VolunteeredStatementRow",
    "compile_product_context",
    "count_statements_for_input",
    "ensure_readiness_spec",
    "evaluate_readiness",
    "get_onboarding_input",
    "get_readiness_decision",
    "get_recon",
    "override_readiness",
    "read_readiness_decisions",
    "read_statements",
    "recon_dedupe_hash",
    "record_statement",
    "start_recon",
    "submit_onboarding_input",
    "transition_recon_lane",
]
