"""Governed research artifact binding on the existing durable agent artifact store.

Model inputs/outputs, task briefs, context bundles and finalizations use this same sink. Originals
stay in their source store. Each save records one evidence watermark and one context row, so
erasing a source or context item erases every step that could hold its text (spec 2026-10-12
§4.1; it replaced one derivation link per source). A save records the artifact row, uploads, then
takes the shared project lock for the bindings (research slowness fix 2026-10-03).
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

# True when any parent of a step in this scope is erased or expired: the evidence of (run,
# account) up to the step's revision (an account job sees every subject, a person job the account
# and itself) and the context's documents, pin and claim supports.
_UNAVAILABLE_PARENT = """
SELECT EXISTS (
  SELECT 1 FROM (
    SELECT artifact_key FROM arv2_evidence_source
    WHERE workspace_id=:ws AND run_id=:run AND account_id=:account AND revision<=:revision
      AND (CAST(:subject AS uuid) IS NULL OR subject_id IN (:account,CAST(:subject AS uuid)))
    UNION ALL SELECT artifact_key FROM arv2_context_document
    WHERE workspace_id=:ws AND context_id=:context
    UNION ALL SELECT manifest_key FROM arv2_research_context_pin
    WHERE workspace_id=:ws AND context_id=:context
    UNION ALL SELECT s.artifact_key FROM claim_quality_support s
    JOIN claim_quality_current q ON q.assessment_id=s.assessment_id
    JOIN claim c ON c.id=q.claim_id
    WHERE c.workspace_id=:ws AND q.context_id=:context
      AND c.entity_id IN (SELECT COALESCE(subject_entity_id,account_entity_id)
        FROM arv2_research_job WHERE workspace_id=:ws AND run_id=:run
        AND account_entity_id=:account)
  ) parent
  JOIN artifact a ON a.workspace_id=:ws AND a.storage_key=parent.artifact_key
  WHERE a.erased_at IS NOT NULL OR a.privacy_erased
     OR (a.expires_at IS NOT NULL AND a.expires_at<=now())
)
"""


def lineage_lock_name(workspace_id: str, run_id: object, account_id: object) -> str:
    """The advisory lock (``hashtextextended(name, 0)``) a step save takes shared and evidence
    erasure takes exclusively. The ``erase_derived_artifacts`` trigger (migration
    ``ecc5f641c0d9``) builds the same name; the two must stay identical."""
    return f"artifact-lineage:{workspace_id}:{run_id}:{account_id}"


def context_lock_name(workspace_id: str, context_id: object) -> str:
    """The same lock for a context: its documents, pin and claim supports."""
    return f"artifact-lineage-context:{workspace_id}:{context_id}"


#: Per-step audit files: what the model was sent and returned, tool results and plans. Founder
#: ruling 2026-10-12: they may expire (``step_retention_days``); evidence, dossiers, claims and
#: pages never do.
STEP_AUDIT_MEDIA_TYPES = frozenset(
    {
        "application/vnd.clue.agent-model-input+json",
        "application/vnd.clue.agent-model-output+json",
        "application/vnd.clue.agent-tool-result+json",
        "application/vnd.clue.agent-plan-proposal+json",
        "application/vnd.clue.validated-agent-plan+json",
        "application/vnd.clue.agent-operation-parameters+json",
        # One message of a model request, saved once and named by every later call's manifest.
        "application/vnd.clue.agent-message+json",
    }
)


class ResearchArtifacts(DurableAgentArtifactStore):
    scope: JobScope
    context_id: UUID
    #: Days a step audit file is kept; 0 keeps it forever. The storage sweep purges expired rows.
    step_retention_days: int = 0

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
                # One watermark row replaces a link per source (spec 2026-10-12 §4.1). The shared
                # lineage locks close the erase/save window: erasure takes them exclusively before
                # erasing the steps a source or context item reached.
                await conn.execute(
                    text(
                        "SELECT pg_advisory_xact_lock_shared(hashtextextended(:evidence,0)), "
                        "pg_advisory_xact_lock_shared(hashtextextended(:context,0))"
                    ),
                    {
                        "evidence": lineage_lock_name(workspace_id, scope.run_id, scope.account_id),
                        "context": context_lock_name(workspace_id, self.context_id),
                    },
                )
                await conn.execute(
                    text(
                        "INSERT INTO arv2_evidence_manifest(workspace_id,run_id,account_id) "
                        "VALUES(:ws,:run,:account) ON CONFLICT DO NOTHING"
                    ),
                    params,
                )
                # Publication bumps the revision and inserts the source in one transaction under
                # the manifest row lock, so every source up to the committed revision is visible.
                revision = (
                    await conn.execute(
                        text(
                            "SELECT revision FROM arv2_evidence_manifest WHERE workspace_id=:ws "
                            "AND run_id=:run AND account_id=:account"
                        ),
                        params,
                    )
                ).scalar_one()
                if (
                    await conn.execute(text(_UNAVAILABLE_PARENT), {**params, "revision": revision})
                ).scalar_one():
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
                # The row's media type, not the caller's: storage is content-addressed, so bytes
                # first stored as evidence keep that row and never expire with a step. Saving it
                # again (a message every later call still names) moves the expiry out again.
                if self.step_retention_days > 0 and record.media_type in STEP_AUDIT_MEDIA_TYPES:
                    await conn.execute(
                        text(
                            "UPDATE artifact SET expires_at=now()+make_interval(days=>:days) "
                            "WHERE workspace_id=:ws AND storage_key=:key"
                        ),
                        {"ws": workspace_id, "key": key, "days": self.step_retention_days},
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
                await conn.execute(
                    text(
                        "INSERT INTO artifact_evidence_watermark(workspace_id,child_key,run_id,"
                        "account_id,subject_key,evidence_revision) "
                        "VALUES(:ws,:key,:run,:account,:subject_key,:revision) "
                        "ON CONFLICT ON CONSTRAINT artifact_evidence_watermark_pk DO UPDATE "
                        "SET evidence_revision=GREATEST(artifact_evidence_watermark"
                        ".evidence_revision, EXCLUDED.evidence_revision)"
                    ),
                    {
                        **params,
                        "key": key,
                        "subject_key": scope.person_subject_id or scope.account_id,
                        "revision": revision,
                    },
                )
                await conn.execute(
                    text(
                        "INSERT INTO artifact_context_lineage(workspace_id,child_key,context_id) "
                        "VALUES(:ws,:key,:context) ON CONFLICT DO NOTHING"
                    ),
                    {**params, "key": key},
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
