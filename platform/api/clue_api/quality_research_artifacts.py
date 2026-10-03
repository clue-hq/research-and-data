"""Governed research artifact binding on the existing durable agent artifact store.

Model inputs/outputs, task briefs, context bundles and finalizations use this same sink. Originals
stay in their source store; derivation links make source erasure invalidate copied research text.
A save records the artifact row, uploads, then takes the shared project lock for the bindings, and
writes all derivation edges in one statement (research slowness fix 2026-10-03).
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import text

from clue_agents import ArtifactRef
from clue_api.agent_turn_wiring import DurableAgentArtifactStore, _artifact_ref
from clue_api.arv2.account_research_claims import JobScope
from clue_api.execution_wiring import StorageParameterArtifactStore
from clue_obs import critical_section
from clue_storage import ArtifactIntegrityError, artifact_key, content_address, retain_artifact


class ResearchArtifacts(DurableAgentArtifactStore):
    scope: JobScope
    context_id: UUID

    async def persist_body(
        self,
        *,
        workspace_id: str,
        data: bytes,
        media_type: str,
        subject_bindings: Sequence[tuple[UUID, str]] = (),
        project_bindings: Sequence[tuple[str, str]] = (),
    ) -> ArtifactRef:
        if workspace_id != self.scope.workspace_id:
            raise ValueError("research artifacts belong to one workspace")
        scope = self.scope
        digest = content_address(data)
        key = artifact_key(workspace_id, digest)
        async with self._conn_factory() as conn:
            with critical_section(
                "research_artifacts.persist_body",
                job_id=str(scope.job_id),
                project_id=scope.project_id,
            ):
                params = {
                    "ws": workspace_id,
                    "run": scope.run_id,
                    "account": scope.account_id,
                    "context": self.context_id,
                    "subject": scope.person_subject_id,
                }
                subjects = set(
                    (
                        await conn.execute(
                            text("""SELECT subject_entity_id
                    FROM arv2_research_job WHERE workspace_id=:ws AND run_id=:run
                      AND account_entity_id=:account AND subject_entity_id IS NOT NULL
                      AND (CAST(:subject AS uuid) IS NULL
                        OR subject_entity_id=CAST(:subject AS uuid))"""),
                            params,
                        )
                    ).scalars()
                ) | {scope.account_id}
                sources = (
                    (
                        await conn.execute(
                            text("""SELECT artifact_key FROM arv2_evidence_source
                    WHERE workspace_id=:ws AND run_id=:run AND account_id=:account
                      AND (CAST(:subject AS uuid) IS NULL
                        OR subject_id IN (:account,CAST(:subject AS uuid)))
                    UNION SELECT artifact_key FROM arv2_context_document
                    WHERE workspace_id=:ws AND context_id=:context
                    UNION SELECT manifest_key FROM arv2_research_context_pin
                    WHERE workspace_id=:ws AND context_id=:context
                    UNION SELECT s.artifact_key FROM claim_quality_support s
                    JOIN claim_quality_current q ON q.assessment_id=s.assessment_id
                    JOIN claim c ON c.id=q.claim_id
                    WHERE c.workspace_id=:ws AND q.context_id=:context
                      AND c.entity_id IN (SELECT COALESCE(subject_entity_id,account_entity_id)
                        FROM arv2_research_job WHERE workspace_id=:ws AND run_id=:run
                        AND account_entity_id=:account)
                    ORDER BY artifact_key"""),
                            params,
                        )
                    )
                    .scalars()
                    .all()
                )
                parents = sorted(set(sources) - {key})
                # Sources/context are already retained by their durable owners. Shared metadata
                # locks close the erase/copy window without downloading every original per model
                # hop.
                live = (
                    (
                        await conn.execute(
                            text("""SELECT storage_key FROM artifact
                    WHERE workspace_id=:ws AND storage_key=ANY(:keys)
                      AND erased_at IS NULL AND NOT privacy_erased
                      AND (expires_at IS NULL OR expires_at>now())
                    ORDER BY storage_key FOR SHARE"""),
                            {"ws": workspace_id, "keys": parents},
                        )
                    )
                    .scalars()
                    .all()
                )
                if len(live) != len(parents):
                    raise ArtifactIntegrityError(
                        "research context or evidence has been erased or expired"
                    )

                # The row first (the storage rule), then the upload, and only then the shared
                # project lock — it is held for the few statements below, never across R2.
                record = await self._record_body(
                    conn,
                    workspace_id=workspace_id,
                    key=key,
                    digest=digest,
                    size=len(data),
                    media_type=media_type,
                    subject_bindings=tuple(
                        set(subject_bindings) | {(s, "derived") for s in subjects}
                    ),
                )
                await self._storage.put(key, data, media_type=record.media_type)
                await self._bind_projects(
                    conn,
                    workspace_id=workspace_id,
                    key=key,
                    project_bindings=tuple(
                        set(project_bindings) | {(scope.project_id, "research_execution")}
                    ),
                )
                if parents:
                    await conn.execute(
                        text(
                            "INSERT INTO artifact_derivation(workspace_id,parent_key,child_key) "
                            "SELECT :ws, parent, :key FROM unnest(CAST(:parents AS text[])) "
                            "AS parent ON CONFLICT DO NOTHING"
                        ),
                        {"ws": workspace_id, "parents": parents, "key": key},
                    )
                await retain_artifact(
                    conn,
                    workspace_id=workspace_id,
                    storage_key=key,
                    reference_kind="research_execution_output",
                    reference_id=str(scope.job_id),
                )
                return _artifact_ref(workspace_id, key, record)


class ResearchParameterArtifacts(StorageParameterArtifactStore):
    """Tool parameter snapshots have the same privacy lineage as agent messages."""

    def __init__(self, artifacts: ResearchArtifacts) -> None:
        super().__init__(storage=artifacts._storage, conn_factory=artifacts._conn_factory)
        self.artifacts = artifacts

    async def persist(
        self,
        *,
        workspace_id: str,
        artifact_key: str,
        content_sha256: str,
        data: bytes,
        media_type: str,
    ) -> None:
        if artifact_key != f"{workspace_id}/{content_sha256}":
            raise ValueError("parameter artifact key does not encode its workspace and hash")
        if content_address(data) != content_sha256:
            raise ValueError("parameter artifact hash does not match its content")
        await self.artifacts.persist_body(
            workspace_id=workspace_id, data=data, media_type=media_type
        )
