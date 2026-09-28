"""Append-only quality decisions, atomic corrections and one current-read predicate.

This substrate does not judge semantics. Trusted writers resolve evidence first; a specialist's
assessment states its interpretation. Decisions and a refresh event commit with the claim effect.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import Claim, ClaimId, EntityId, ResearchScope, resolve_research_scope
from clue_obs import get_logger
from clue_research.claimstore.claims import supersede_with_existing
from clue_research.claimstore.registry import FieldRegistryScope, get_effective_field
from clue_storage import retain_artifact

log = get_logger(__name__)
Quality = Literal["supported", "qualified", "unresolved", "invalid"]
OperationKind = Literal["assessment", "withdrawal", "correction", "conflict"]


class QualityConflict(ValueError):
    """Reread the current claim/assessment; this expected revision no longer owns it."""


class QualityScopeError(ValueError):
    """A claim or its evidence is unavailable under the caller's subject authority."""


@dataclass(frozen=True)
class QualityReceipt:
    operation_id: UUID
    claim_id: UUID
    assessment_id: UUID
    revision: int
    conclusion: Quality
    replacement_id: UUID | None
    replayed: bool = False


def eligible_sql(claim_alias: str = "claim") -> str:
    """Ordinary current facts. Qualified/unresolved findings require their explicit typed reader.

    Legacy unassessed data keeps its legacy behavior. A new writer stamps quality_required so an
    omitted assessment cannot silently promote it. Raw history bypasses this predicate explicitly.
    Aliases are static module constants, never model/user input.
    """
    own = _own_eligible_sql(claim_alias)
    support = _own_eligible_sql("support")
    return f"""({own} AND (
      COALESCE({claim_alias}.write_markers->'quality_required'='true'::jsonb,false)=false OR
      NOT EXISTS (
        WITH RECURSIVE dependencies(id) AS (
          SELECT d.supporting_claim_id FROM claim_derivation d
          WHERE d.derived_claim_id={claim_alias}.id AND d.support_required
          UNION
          SELECT d.supporting_claim_id FROM claim_derivation d JOIN dependencies p
            ON d.derived_claim_id=p.id WHERE d.support_required
        )
        SELECT 1 FROM dependencies dep JOIN claim support ON support.id=dep.id
        LEFT JOIN claim_quality_current sq ON sq.claim_id=support.id
        WHERE support.superseded_by IS NOT NULL OR NOT {support}
          OR NOT COALESCE(sq.conclusion='supported',support.verification_status='verified')
      )
    ))"""


def _own_eligible_sql(claim_alias: str) -> str:
    return f"""(
      (COALESCE({claim_alias}.write_markers->'quality_required'='true'::jsonb,false)=false
       OR EXISTS(SELECT 1 FROM claim_quality_current q WHERE q.claim_id={claim_alias}.id))
      AND NOT EXISTS(SELECT 1 FROM claim_quality_current q WHERE q.claim_id={claim_alias}.id
        AND q.conclusion<>'supported')
      AND NOT EXISTS(SELECT 1 FROM claim_quality_current q
        JOIN claim_quality_support s ON s.assessment_id=q.assessment_id
        JOIN artifact a ON a.storage_key=s.artifact_key
        WHERE q.claim_id={claim_alias}.id AND
          (a.erased_at IS NOT NULL OR a.privacy_erased OR a.expires_at<=now()))
    )"""


def inspectable_sql(claim_alias: str = "claim") -> str:
    """Qualified research may be read explicitly, never invalid or erased support lineage."""
    return f"""NOT EXISTS (
      WITH RECURSIVE dependencies(id) AS (
        SELECT {claim_alias}.id UNION
        SELECT d.supporting_claim_id FROM claim_derivation d JOIN dependencies p
          ON d.derived_claim_id=p.id WHERE d.support_required
      )
      SELECT 1 FROM dependencies dep JOIN claim support ON support.id=dep.id
      LEFT JOIN claim_quality_current sq ON sq.claim_id=support.id
      WHERE support.superseded_by IS NOT NULL OR sq.conclusion='invalid'
        OR EXISTS(SELECT 1 FROM lawful_basis_record retention WHERE retention.claim_id=support.id
          AND retention.retention_until<=now())
        OR EXISTS(SELECT 1 FROM claim_quality_support s JOIN artifact a
          ON a.storage_key=s.artifact_key WHERE s.assessment_id=sq.assessment_id AND
          (a.erased_at IS NOT NULL OR a.privacy_erased OR a.expires_at<=now()))
    )"""


async def dependency_revision(conn: AsyncConnection, *, workspace_id: str, entity_id: UUID) -> int:
    value = (
        await conn.execute(
            text(
                "SELECT revision FROM claim_dependency_revision "
                "WHERE workspace_id=:ws AND entity_id=:entity"
            ),
            {"ws": workspace_id, "entity": entity_id},
        )
    ).scalar_one_or_none()
    return int(value or 0)


async def _lock_claims(
    conn: AsyncConnection,
    workspace_id: str,
    entity_id: UUID,
    ids: Sequence[UUID],
) -> dict[UUID, dict[str, Any]]:
    rows = (
        (
            await conn.execute(
                text(
                    "SELECT id,entity_id,field_key,superseded_by,run_id "
                    "FROM claim WHERE workspace_id=:ws AND entity_id=:entity "
                    "AND id=ANY(:ids) ORDER BY id FOR UPDATE"
                ),
                {"ws": workspace_id, "entity": entity_id, "ids": sorted(set(ids))},
            )
        )
        .mappings()
        .all()
    )
    if len(rows) != len(set(ids)):
        raise QualityScopeError("claim outside authorized subject")
    return {r["id"]: dict(r) for r in rows}


async def assess_claim(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    entity_id: UUID,
    claim_id: UUID,
    operation_id: UUID,
    expected_revision: int,
    conclusion: Quality,
    rationale_key: str,
    actor_ref: str,
    support_artifacts: tuple[str, ...],
    context_id: UUID | None = None,
    kind: OperationKind = "assessment",
    replacement_id: UUID | None = None,
    policy_version: str = "research-quality-v1",
) -> QualityReceipt:
    """Atomic transaction participant. No network/model calls under the correction locks.

    Callers commit after this returns. Idempotent replay requires identical inputs and returns the
    original decision even when a later correction advanced the current revision. No replacement
    is fabricated for a withdrawal; historical values and evidence remain untouched.
    """
    if expected_revision < 0 or not actor_ref:
        raise ValueError("quality assessment requires actor and nonnegative expected revision")
    if conclusion not in ("supported", "qualified", "unresolved", "invalid"):
        raise ValueError("unknown quality conclusion")
    if kind in ("withdrawal", "correction") and conclusion != "invalid":
        raise ValueError("withdrawal/correction invalidates the old observation")
    if kind == "conflict" and conclusion != "unresolved":
        raise ValueError("a conflict must retain uncertainty")
    if (kind == "correction") != (replacement_id is not None):
        raise ValueError("only correction accepts a replacement")
    if conclusion in ("supported", "qualified") and not support_artifacts:
        raise ValueError("supported findings require resolved evidence")
    canonical = json.dumps(
        [
            workspace_id,
            str(entity_id),
            str(claim_id),
            expected_revision,
            conclusion,
            rationale_key,
            actor_ref,
            sorted(set(support_artifacts)),
            str(context_id),
            kind,
            str(replacement_id),
            policy_version,
        ],
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    # Serialize all spellings of one replay key, even if a caller accidentally changes subject.
    await conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
        {"key": f"claim-quality:{operation_id}"},
    )
    old = (
        (
            await conn.execute(
                text(
                    "SELECT o.*,q.revision,q.conclusion FROM claim_quality_operation o "
                    "JOIN claim_quality_assessment q ON q.assessment_id=o.assessment_id "
                    "WHERE o.operation_id=:id"
                ),
                {"id": operation_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    if old is not None:
        if old["workspace_id"] != workspace_id or old["request_sha256"] != digest:
            raise QualityConflict("operation key already belongs to different input")
        return QualityReceipt(
            operation_id,
            claim_id,
            old["assessment_id"],
            old["revision"],
            old["conclusion"],
            old["replacement_id"],
            True,
        )
    ids = [claim_id, *([replacement_id] if replacement_id else [])]
    claims = await _lock_claims(conn, workspace_id, entity_id, ids)
    current = claims[claim_id]
    quality = (
        (
            await conn.execute(
                text("SELECT revision,context_id FROM claim_quality_current WHERE claim_id=:id"),
                {"id": claim_id},
            )
        )
        .mappings()
        .one_or_none()
    )
    revision = int(quality["revision"]) if quality else 0
    if revision != expected_revision or current["superseded_by"] is not None:
        raise QualityConflict("revision_conflict: reread current claim and assessment")
    definition = await get_effective_field(
        conn, scope=FieldRegistryScope.for_workspace(workspace_id), field_key=current["field_key"]
    )
    if definition is None:
        raise QualityScopeError("claim field is unavailable")
    if resolve_research_scope(definition.field_def) is ResearchScope.PROJECT_RELATIVE and (
        context_id is None or (quality and context_id != quality["context_id"])
    ):
        raise QualityScopeError("project-relative correction requires the same pinned context")
    for key in sorted({rationale_key, *support_artifacts}):
        await retain_artifact(
            conn,
            workspace_id=workspace_id,
            storage_key=key,
            reference_kind="claim_assessment",
            reference_id=str(operation_id),
        )
    if replacement_id:
        replacement = claims[replacement_id]
        usable = (
            await conn.execute(
                text("SELECT id FROM claim WHERE id=:id AND " + eligible_sql()),
                {"id": replacement_id},
            )
        ).scalar_one_or_none()
        has_assessment = (
            await conn.execute(
                text(
                    "SELECT 1 FROM claim_quality_current WHERE "
                    "claim_id=:id AND conclusion='supported'"
                ),
                {"id": replacement_id},
            )
        ).scalar_one_or_none()
        if (
            replacement_id == claim_id
            or replacement["superseded_by"]
            or not usable
            or not has_assessment
        ):
            raise QualityConflict("replacement must be a different live supported claim")
        if replacement["field_key"] == current["field_key"]:
            await supersede_with_existing(
                conn,
                ClaimId(claim_id),
                ClaimId(replacement_id),
                workspace_id=workspace_id,
                entity_id=EntityId(entity_id),
            )
        # Different-field reclassification leaves the historical row intact, invalidated below.
    assessment_id = uuid5(NAMESPACE_URL, f"quality-assessment:{operation_id}")
    await conn.execute(
        text(
            "INSERT INTO claim_quality_assessment(assessment_id,claim_id,"
            "workspace_id,revision,conclusion,rationale_key,actor_ref,policy_version,context_id) "
            "VALUES(:aid,:id,:ws,:rev,:conclusion,:rationale,:actor,:policy,:context)"
        ),
        {
            "aid": assessment_id,
            "id": claim_id,
            "ws": workspace_id,
            "rev": revision + 1,
            "conclusion": conclusion,
            "rationale": rationale_key,
            "actor": actor_ref,
            "policy": policy_version,
            "context": context_id,
        },
    )
    for ordinal, key in enumerate(sorted(set(support_artifacts))):
        await conn.execute(
            text(
                "INSERT INTO claim_quality_support(assessment_id,workspace_id,"
                "ordinal,artifact_key) VALUES(:id,:ws,:ordinal,:key)"
            ),
            {"id": assessment_id, "ws": workspace_id, "ordinal": ordinal, "key": key},
        )
    await conn.execute(
        text(
            "INSERT INTO claim_quality_operation(operation_id,workspace_id,"
            "claim_id,replacement_id,assessment_id,request_sha256,kind) "
            "VALUES(:op,:ws,:id,:replacement,:aid,:sha,:kind)"
        ),
        {
            "op": operation_id,
            "ws": workspace_id,
            "id": claim_id,
            "replacement": replacement_id,
            "aid": assessment_id,
            "sha": digest,
            "kind": kind,
        },
    )
    await conn.execute(
        text(
            "INSERT INTO claim_dependency_revision(workspace_id,entity_id) "
            "VALUES(:ws,:entity) ON CONFLICT DO NOTHING"
        ),
        {"ws": workspace_id, "entity": entity_id},
    )
    dependency = (
        await conn.execute(
            text(
                "UPDATE claim_dependency_revision SET revision=revision+1 "
                "WHERE workspace_id=:ws AND entity_id=:entity RETURNING revision"
            ),
            {"ws": workspace_id, "entity": entity_id},
        )
    ).scalar_one()
    await conn.execute(
        text(
            "INSERT INTO claim_quality_event(event_id,workspace_id,entity_id,"
            "claim_id,revision) VALUES(:op,:ws,:entity,:id,:rev)"
        ),
        {
            "op": operation_id,
            "ws": workspace_id,
            "entity": entity_id,
            "id": claim_id,
            "rev": dependency,
        },
    )
    log.info(
        "claimstore.quality_assessed",
        operation_id=str(operation_id),
        claim_id=str(claim_id),
        assessment_id=str(assessment_id),
        conclusion=conclusion,
        revision=revision + 1,
        replacement_id=str(replacement_id) if replacement_id else None,
    )
    return QualityReceipt(
        operation_id, claim_id, assessment_id, revision + 1, conclusion, replacement_id
    )


async def uncertain_findings(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    entity_id: UUID,
) -> tuple[dict[str, object], ...]:
    """Qualified/unresolved observations, never invalid factual prose."""
    rows = (
        (
            await conn.execute(
                text("""
      SELECT q.claim_id,q.assessment_id,q.conclusion,q.revision,q.rationale_key,q.context_id,
             c.field_key FROM claim_quality_current q JOIN claim c ON c.id=q.claim_id
      WHERE c.workspace_id=:ws AND c.entity_id=:entity AND c.superseded_by IS NULL
        AND q.conclusion IN ('qualified','unresolved')
      ORDER BY c.field_key,q.claim_id
    """),
                {"ws": workspace_id, "entity": entity_id},
            )
        )
        .mappings()
        .all()
    )
    return tuple(dict(r) for r in rows)


async def inspectable_claims_by_ids(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    claim_ids: Sequence[UUID],
) -> dict[ClaimId, Claim]:
    """Explicit cited-evidence reads include qualified observations, never retired/invalid rows."""
    from clue_research.claimstore.claims import claims_by_ids
    from clue_research.claimstore.tenancy import WorkspaceScope

    ids = (
        (
            await conn.execute(
                text(
                    "SELECT c.id FROM claim c WHERE c.workspace_id=:ws AND c.id=ANY(:ids) "
                    "AND c.superseded_by IS NULL AND " + inspectable_sql("c")
                ),
                {"ws": workspace_id, "ids": list(claim_ids)},
            )
        )
        .scalars()
        .all()
    )
    return await claims_by_ids(
        conn,
        [ClaimId(id) for id in ids],
        scope=WorkspaceScope.for_workspace(workspace_id),
        include_superseded=True,
        include_expired=False,
    )


async def deliver_invalidations(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    apply: Callable[[AsyncConnection, dict[str, Any]], Awaitable[None]],
    limit: int = 100,
) -> int:
    """Apply DB effects and acknowledge events in one caller-owned transaction.

    The callback invalidates projections/offers durable refresh work; it must not publish an
    external side effect. Competing workers skip locked events. A crash before commit leaves
    both the event and the projection unchanged, so a fresh worker retries the whole unit.
    """
    if not 1 <= limit <= 1000:
        raise ValueError("invalid invalidation batch size")
    events = (
        (
            await conn.execute(
                text(
                    "SELECT * FROM claim_quality_event WHERE workspace_id=:ws "
                    "AND delivered_at IS NULL "
                    "ORDER BY created_at,event_id LIMIT :limit FOR UPDATE SKIP LOCKED"
                ),
                {"ws": workspace_id, "limit": limit},
            )
        )
        .mappings()
        .all()
    )
    for row in events:
        await apply(conn, dict(row))
        await conn.execute(
            text(
                "UPDATE claim_quality_event SET delivered_at=now() "
                "WHERE event_id=:id AND workspace_id=:ws"
            ),
            {"id": row["event_id"], "ws": workspace_id},
        )
        log.info(
            "claimstore.quality_invalidation_delivered",
            event_id=str(row["event_id"]),
            revision=row["revision"],
        )
    return len(events)
