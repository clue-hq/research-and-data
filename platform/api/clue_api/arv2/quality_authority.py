"""Resolve trusted execution identity to a pinned research context and revocable grant."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.account_research_claims import JobScope
from clue_api.arv2.quality_evidence import (
    EvidenceGrant,
    EvidenceUnavailable,
    authorize_grant,
    grant_manifest,
)
from clue_api.arv2.research_operations import OperationScope


@dataclass(frozen=True)
class ResearchAuthority:
    scope: JobScope
    execution_id: UUID
    role: str
    context_id: UUID
    grant: EvidenceGrant

    @property
    def actor_ref(self) -> str:
        return f"{self.role}:{self.execution_id}"


async def resolve_authority(
    conn: AsyncConnection,
    scope: JobScope,
    execution_id: UUID,
) -> ResearchAuthority:
    # NO KEY UPDATE, never plain UPDATE: concurrent authority checks still queue on this row, but
    # foreign-key checks (an activity row or a specialist's child execution naming it) take a
    # key-share lock that plain FOR UPDATE blocks. Those writers already hold the job's allowance
    # row, which ``reserve`` wants next, so FOR UPDATE here deadlocked them (production 40P01,
    # 2026-10-13). No key column of this row is ever updated.
    row = (
        (
            await conn.execute(
                text("""
      SELECT e.context_id,e.role,e.evidence_grant_id,e.parent_execution_id,
        r.context_id AS run_context
      FROM arv2_quality_execution e JOIN arv2_research_job j
        ON j.job_id=e.job_id AND j.workspace_id=e.workspace_id
      JOIN arv2_research_run r ON r.run_id=j.run_id AND r.workspace_id=j.workspace_id
      WHERE e.execution_id=:execution AND e.workspace_id=:ws AND e.job_id=:job
        AND j.run_id=:run AND j.account_entity_id=:account AND r.project_id=:project
      FOR NO KEY UPDATE OF e
    """),
                {
                    "execution": execution_id,
                    "ws": scope.workspace_id,
                    "job": scope.job_id,
                    "run": scope.run_id,
                    "account": scope.account_id,
                    "project": scope.project_id,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None or row["context_id"] != row["run_context"]:
        raise EvidenceUnavailable("execution does not own this research context")
    op = OperationScope(scope.workspace_id, scope.run_id, scope.job_id, scope.account_id)
    grant = None
    if row["evidence_grant_id"]:
        grant = EvidenceGrant(op, execution_id, row["evidence_grant_id"])
        # A revoked grant is a stop; acquiring a newer revision cannot undo that decision.
        await authorize_grant(conn, grant)
    if grant is None or row["parent_execution_id"] is None:
        grant = await grant_manifest(conn, op, consumer_id=execution_id)
        await authorize_grant(conn, grant)
        await conn.execute(
            text("""UPDATE arv2_quality_execution SET evidence_grant_id=:grant
          WHERE execution_id=:execution AND workspace_id=:ws"""),
            {"grant": grant.grant_id, "execution": execution_id, "ws": scope.workspace_id},
        )
    return ResearchAuthority(scope, execution_id, row["role"], row["context_id"], grant)
