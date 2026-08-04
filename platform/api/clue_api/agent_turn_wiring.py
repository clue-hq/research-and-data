"""C6.3 durable agent turns, context/history receipts, cold replay and DSAR wiring."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Literal
from uuid import UUID, uuid5

from sqlalchemy import text
from sqlalchemy.engine import RowMapping

from clue_agents import (
    AgentExecutionStatus,
    AgentTurnOutcome,
    AgentWorkspaceFactory,
    WorkspaceUsageSnapshot,
)
from clue_agents.context import (
    ContextAssemblyReceipt,
    ContextReceiptStore,
)
from clue_agents.contracts import (
    AgentFinalizeEnvelope,
    AgentProfile,
    AgentResourceRef,
    AgentRole,
    AgentTurnRequest,
    ArtifactRef,
    ContextBundleManifest,
    ContextLayer,
    ContextLayerManifest,
    DomainObjectRef,
    ResourceKind,
    normalize_virtual_path,
)
from clue_agents.ports import (
    AgentArtifactReader,
    AgentArtifactSink,
    AgentHistoryStore,
    HistoryMessageRef,
)
from clue_agents.turns import (
    AgentArtifactState,
    AgentColdReplayReceipt,
    AgentContextReplayReceipt,
    AgentModelCallReceipt,
    AgentReplayUnavailable,
    AgentTurnReceipt,
    AgentTurnStatus,
    PrivacyEraseResult,
    ReplayArtifactRef,
)
from clue_core import ExecutionId
from clue_db import ConnFactory, transaction
from clue_storage import StorageBackend, artifact_key, content_address
from clue_storage.artifacts import mark_erased, purge_erased_artifacts, record_artifact
from clue_storage.protocol import ArtifactNotFound

__all__ = [
    "DbAgentContextReceiptStore",
    "DbAgentHistoryStore",
    "DbAgentReplayReader",
    "DbAgentTurnJournal",
    "DurableAgentArtifactStore",
    "AgentPrivacyService",
]

_EVENT_NAMESPACE = UUID("f16bca96-c8c9-5fad-9f42-35ad7873f021")
_REF_NAMESPACE = UUID("9431adab-a359-59ee-b2f3-af522f93016b")
_PRIVACY_NAMESPACE = UUID("f4d51cff-a92e-5ed6-a07f-826cb2348241")
_PROJECT_PRIVACY_NAMESPACE = UUID("cd318be1-c3cf-50c1-9ddd-826cd63fa5b3")


def _event_id(turn_id: UUID, status: str) -> UUID:
    return uuid5(_EVENT_NAMESPACE, f"{turn_id}:{status}")


def _ref_id(owner_id: UUID, role: str, ordinal: int) -> UUID:
    return uuid5(_REF_NAMESPACE, f"{owner_id}:{role}:{ordinal}")


def _thread_lock_key(workspace_id: str, thread_id: str) -> str:
    framed = f"{len(workspace_id)}:{workspace_id}{len(thread_id)}:{thread_id}".encode()
    return hashlib.sha256(framed).hexdigest()


async def _append_turn_event(
    conn: object,
    *,
    turn_id: UUID,
    workspace_id: str,
    status: AgentTurnStatus,
    reason_code: str | None = None,
) -> None:
    await conn.execute(  # type: ignore[attr-defined]
        text(
            "INSERT INTO agent_turn_event "
            "(event_id, turn_id, workspace_id, status, reason_code) "
            "VALUES (:event_id, :turn_id, :workspace_id, :status, :reason_code) "
            "ON CONFLICT (event_id) DO NOTHING"
        ),
        {
            "event_id": _event_id(turn_id, status.value),
            "turn_id": turn_id,
            "workspace_id": workspace_id,
            "status": status.value,
            "reason_code": reason_code,
        },
    )


async def _insert_artifact_ref(
    conn: object,
    *,
    turn_id: UUID,
    owner_kind: str,
    owner_id: UUID,
    role: str,
    ordinal: int,
    ref: ArtifactRef,
) -> None:
    inserted = await conn.execute(  # type: ignore[attr-defined]
        text(
            "INSERT INTO agent_artifact_ref "
            "(id, turn_id, workspace_id, owner_kind, owner_id, ref_role, ordinal, "
            " artifact_key, artifact_sha256, retention_class) "
            "SELECT :id, :turn_id, :workspace_id, :owner_kind, :owner_id, :role, :ordinal, "
            " :key, :sha, t.retention_class FROM agent_turn t "
            "WHERE t.id=:turn_id AND t.workspace_id=:workspace_id "
            "ON CONFLICT (owner_kind, owner_id, ref_role, ordinal) DO NOTHING "
            "RETURNING id"
        ),
        {
            "id": _ref_id(owner_id, role, ordinal),
            "turn_id": turn_id,
            "workspace_id": ref.workspace_id,
            "owner_kind": owner_kind,
            "owner_id": owner_id,
            "role": role,
            "ordinal": ordinal,
            "key": ref.artifact_key,
            "sha": ref.sha256,
        },
    )
    if inserted.first() is None:
        existing = await conn.execute(  # type: ignore[attr-defined]
            text(
                "SELECT turn_id, workspace_id, artifact_key, artifact_sha256 "
                "FROM agent_artifact_ref "
                "WHERE owner_kind=:owner_kind AND owner_id=:owner_id "
                "AND ref_role=:role AND ordinal=:ordinal"
            ),
            {
                "owner_kind": owner_kind,
                "owner_id": owner_id,
                "role": role,
                "ordinal": ordinal,
            },
        )
        row = existing.mappings().one()
        if (
            row["turn_id"] != turn_id
            or row["workspace_id"] != ref.workspace_id
            or row["artifact_key"] != ref.artifact_key
            or row["artifact_sha256"] != ref.sha256
        ):
            raise ValueError("artifact ref identity already has a different immutable target")


class DurableAgentArtifactStore(AgentArtifactSink, AgentArtifactReader):
    """Workspace CAS with artifact-row durability and no-resurrection tombstones."""

    def __init__(
        self,
        *,
        storage: StorageBackend,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._storage = storage
        self._conn_factory = conn_factory

    async def persist(
        self,
        *,
        workspace_id: str,
        logical_path: str,
        data: bytes,
        media_type: str,
    ) -> ArtifactRef:
        normalized = normalize_virtual_path(logical_path)
        if normalized != logical_path or not normalized.startswith("outputs/"):
            raise ValueError("only normalized outputs may use the workspace artifact sink")
        return await self.persist_body(
            workspace_id=workspace_id,
            data=data,
            media_type=media_type,
        )

    async def persist_body(
        self,
        *,
        workspace_id: str,
        data: bytes,
        media_type: str,
        subject_bindings: Sequence[tuple[UUID, str]] = (),
        project_bindings: Sequence[tuple[str, str]] = (),
    ) -> ArtifactRef:
        digest = content_address(data)
        key = artifact_key(workspace_id, digest)
        async with self._conn_factory() as conn:
            await conn.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": key},
            )
            tombstone = await conn.execute(
                text(
                    "SELECT 1 FROM agent_artifact_tombstone "
                    "WHERE workspace_id = :workspace_id AND artifact_key = :key LIMIT 1"
                ),
                {"workspace_id": workspace_id, "key": key},
            )
            if tombstone.first() is not None:
                raise ValueError("erased agent artifact bytes cannot be resurrected")
            record = await record_artifact(
                conn,
                storage_key=key,
                workspace_id=workspace_id,
                content_sha256=digest,
                media_type=media_type,
                size_bytes=len(data),
            )
            for subject_entity_id, binding_kind in sorted(
                subject_bindings,
                key=lambda item: (str(item[0]), item[1]),
            ):
                await conn.execute(
                    text(
                        "INSERT INTO agent_artifact_subject "
                        "(workspace_id, artifact_key, subject_entity_id, binding_kind) "
                        "VALUES (:workspace_id, :key, :subject, :kind) "
                        "ON CONFLICT DO NOTHING"
                    ),
                    {
                        "workspace_id": workspace_id,
                        "key": key,
                        "subject": subject_entity_id,
                        "kind": binding_kind,
                    },
                )
            for project_id, binding_kind in sorted(set(project_bindings)):
                await conn.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
                    {"scope": f"agent-project-artifacts:{workspace_id}:{project_id}"},
                )
                inserted = await conn.execute(
                    text(
                        "INSERT INTO agent_artifact_project "
                        "(workspace_id, project_id, artifact_key, binding_kind) "
                        "SELECT :workspace_id, :project_id, :key, :kind FROM project "
                        "WHERE project_id=:project_id AND workspace_id=:workspace_id "
                        "ON CONFLICT DO NOTHING RETURNING artifact_key"
                    ),
                    {
                        "workspace_id": workspace_id,
                        "project_id": project_id,
                        "key": key,
                        "kind": binding_kind,
                    },
                )
                if inserted.first() is None:
                    existing = await conn.execute(
                        text(
                            "SELECT 1 FROM agent_artifact_project "
                            "WHERE workspace_id=:workspace_id AND project_id=:project_id "
                            "AND artifact_key=:key AND binding_kind=:kind"
                        ),
                        {
                            "workspace_id": workspace_id,
                            "project_id": project_id,
                            "key": key,
                            "kind": binding_kind,
                        },
                    )
                    if existing.first() is None:
                        raise ValueError(
                            "agent artifact project binding is absent or cross-workspace"
                        )
        # The row is committed before external storage mutation. A crash here is body-unavailable
        # and therefore fail-closed; retry converges on this same content-addressed key.
        await self._storage.put(key, data, media_type=record.media_type)
        return ArtifactRef(
            workspace_id=workspace_id,
            artifact_key=key,
            sha256=record.content_sha256,
            media_type=record.media_type,
            byte_count=record.size_bytes,
        )

    async def bind_subject(
        self,
        *,
        ref: ArtifactRef,
        subject_entity_id: UUID,
        binding_kind: str,
    ) -> None:
        async with self._conn_factory() as conn:
            result = await conn.execute(
                text(
                    "INSERT INTO agent_artifact_subject "
                    "(workspace_id, artifact_key, subject_entity_id, binding_kind) "
                    "SELECT :workspace_id, :key, :subject, :kind "
                    "FROM artifact WHERE storage_key = :key AND workspace_id = :workspace_id "
                    "AND content_sha256=:sha AND media_type=:media AND size_bytes=:size "
                    "AND erased_at IS NULL "
                    "ON CONFLICT DO NOTHING RETURNING artifact_key"
                ),
                {
                    "workspace_id": ref.workspace_id,
                    "key": ref.artifact_key,
                    "subject": subject_entity_id,
                    "kind": binding_kind,
                    "sha": ref.sha256,
                    "media": ref.media_type,
                    "size": ref.byte_count,
                },
            )
            if result.first() is None:
                existing = await conn.execute(
                    text(
                        "SELECT 1 FROM agent_artifact_subject s "
                        "JOIN artifact a ON a.storage_key=s.artifact_key "
                        "WHERE s.workspace_id=:workspace_id AND s.artifact_key=:key "
                        "AND s.subject_entity_id=:subject "
                        "AND a.content_sha256=:sha AND a.media_type=:media "
                        "AND a.size_bytes=:size"
                    ),
                    {
                        "workspace_id": ref.workspace_id,
                        "key": ref.artifact_key,
                        "subject": subject_entity_id,
                        "sha": ref.sha256,
                        "media": ref.media_type,
                        "size": ref.byte_count,
                    },
                )
                if existing.first() is None:
                    raise ArtifactNotFound(ref.artifact_key)

    async def read(self, ref: ArtifactRef) -> bytes:
        async with self._conn_factory() as conn:
            result = await conn.execute(
                text(
                    "SELECT content_sha256, media_type, size_bytes, erased_at, purged_at "
                    "FROM artifact a WHERE storage_key=:key AND workspace_id=:workspace_id "
                    "AND NOT EXISTS (SELECT 1 FROM agent_artifact_tombstone t "
                    " WHERE t.workspace_id=a.workspace_id AND t.artifact_key=a.storage_key)"
                ),
                {"key": ref.artifact_key, "workspace_id": ref.workspace_id},
            )
            row = result.mappings().first()
        if row is None or row["erased_at"] is not None or row["purged_at"] is not None:
            raise ArtifactNotFound(ref.artifact_key)
        if (
            row["content_sha256"] != ref.sha256
            or row["media_type"] != ref.media_type
            or int(row["size_bytes"]) != ref.byte_count
        ):
            raise ValueError("artifact reference metadata differs from the durable row")
        data = await self._storage.get(ref.artifact_key)
        if len(data) != ref.byte_count or content_address(data) != ref.sha256:
            raise ValueError("artifact bytes differ from the exact durable reference")
        return data


class DbAgentTurnJournal:
    def __init__(self, *, conn_factory: ConnFactory = transaction) -> None:
        self._conn_factory = conn_factory

    async def create(
        self,
        *,
        request: AgentTurnRequest,
        profile: AgentProfile,
    ) -> AgentTurnReceipt:
        constitution = request.constitution
        if constitution.profile_ref.name != profile.name or (
            constitution.profile_ref.version != profile.version
        ):
            raise ValueError("turn constitution does not pin the supplied profile")
        async with self._conn_factory() as conn:
            inserted = await conn.execute(
                text(
                    "INSERT INTO agent_turn "
                    "(id, execution_id, parent_execution_id, workspace_id, project_id, thread_id, "
                    " actor_id, role, workspace_root_id, profile_name, profile_version, "
                    " profile_sha256, resource_manifest_key, "
                    " resource_manifest_artifact_sha256, resource_manifest_sha256, "
                    " retention_class, requested_at) "
                    "SELECT :id, e.id, e.parent_execution_id, :workspace_id, :project_id, "
                    " :thread_id, :actor_id, :role, :root, :profile_name, :profile_version, "
                    " :profile_sha, :manifest_key, :manifest_artifact_sha, :manifest_sha, "
                    " :retention, :requested_at FROM execution e "
                    "WHERE e.id=:execution_id AND e.workspace_id=:workspace_id "
                    "ON CONFLICT (id) DO NOTHING RETURNING id"
                ),
                {
                    "id": request.turn_id,
                    "execution_id": constitution.execution_id,
                    "workspace_id": constitution.workspace_id,
                    "project_id": constitution.project_id,
                    "thread_id": request.thread_id,
                    "actor_id": constitution.actor_id,
                    "role": constitution.role.value,
                    "root": constitution.workspace_root_id,
                    "profile_name": constitution.profile_ref.name,
                    "profile_version": constitution.profile_ref.version,
                    "profile_sha": constitution.profile_ref.sha256,
                    "manifest_key": constitution.resource_manifest_ref.artifact_key,
                    "manifest_artifact_sha": constitution.resource_manifest_ref.sha256,
                    "manifest_sha": constitution.resource_manifest_sha256,
                    "retention": profile.workspace.retention_class,
                    "requested_at": request.requested_at,
                },
            )
            if inserted.first() is None:
                existing = await self._read_turn(conn, constitution.workspace_id, request.turn_id)
                if (
                    existing is None
                    or existing.execution_id != constitution.execution_id
                    or existing.thread_id != request.thread_id
                    or existing.profile_ref != constitution.profile_ref
                    or existing.resource_manifest_ref != constitution.resource_manifest_ref
                    or existing.resource_manifest_sha256 != constitution.resource_manifest_sha256
                ):
                    raise ValueError("turn id already exists with different immutable inputs")
                return existing

            await _append_turn_event(
                conn,
                turn_id=request.turn_id,
                workspace_id=constitution.workspace_id,
                status=AgentTurnStatus.REQUESTED,
            )
            turn_refs = (
                ("project_card", 0, constitution.project_card_ref),
                ("budget_envelope", 0, constitution.budget_envelope_ref),
                ("resource_manifest", 0, constitution.resource_manifest_ref),
                ("user_message", 0, request.user_message_artifact_ref),
                *(("attachment", index, ref) for index, ref in enumerate(request.attachment_refs)),
            )
            for role, ordinal, ref in turn_refs:
                await _insert_artifact_ref(
                    conn,
                    turn_id=request.turn_id,
                    owner_kind="turn",
                    owner_id=request.turn_id,
                    role=role,
                    ordinal=ordinal,
                    ref=ref,
                )
            receipt = await self._read_turn(conn, constitution.workspace_id, request.turn_id)
            if receipt is None:  # pragma: no cover - same transaction invariant
                raise RuntimeError("inserted agent turn vanished")
            return receipt

    async def load_committed_outcome(
        self,
        *,
        turn_id: UUID,
        workspace_id: str,
    ) -> AgentTurnOutcome | None:
        """Return an authoritative terminal outcome without reopening a completed turn.

        This is the cold process-restart path for an API-root runner.  A finalization row alone is
        not authoritative; only the immutable commit joined to its live artifact may be replayed.
        Unfinalized failed/abandoned turns deliberately return ``None`` so an explicit retry can
        resume their durable model checkpoint instead of manufacturing success.
        """

        async with self._conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT f.execution_id, f.status, f.failure_code,
                                   c.envelope_artifact_key, c.envelope_sha256,
                                   a.media_type, a.size_bytes
                            FROM agent_finalization_commit c
                            JOIN agent_finalization f ON f.id=c.finalization_id
                            JOIN artifact a ON a.storage_key=c.envelope_artifact_key
                            WHERE c.turn_id=:turn AND c.workspace_id=:workspace
                              AND a.workspace_id=:workspace
                              AND a.erased_at IS NULL
                            """
                        ),
                        {"turn": turn_id, "workspace": workspace_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        return AgentTurnOutcome(
            turn_id=turn_id,
            execution_id=ExecutionId(row["execution_id"]),
            status=AgentExecutionStatus(row["status"]),
            finalization_ref=ArtifactRef(
                workspace_id=workspace_id,
                artifact_key=row["envelope_artifact_key"],
                sha256=row["envelope_sha256"],
                media_type=row["media_type"],
                byte_count=int(row["size_bytes"]),
            ),
            failure_code=row["failure_code"],
        )

    async def record_model_call(
        self,
        *,
        receipt: AgentModelCallReceipt,
        input_ref: ArtifactRef | None = None,
        output_ref: ArtifactRef | None = None,
    ) -> None:
        async with self._conn_factory() as conn:
            inserted = await conn.execute(
                text(
                    "INSERT INTO agent_model_call "
                    "(id, turn_id, execution_id, workspace_id, sequence, requested_model, "
                    " answering_model, status, input_tokens, cache_read_input_tokens, "
                    " cache_creation_input_tokens, output_tokens, cost_millicredits, latency_ms, "
                    " error_code, started_at, completed_at) "
                    "VALUES (:id, :turn, :execution, :workspace, :sequence, :requested, "
                    " :answering, :status, :input_tokens, :cache_read, :cache_creation, "
                    " :output_tokens, :cost, :latency, :error, :started, :completed) "
                    "ON CONFLICT (id) DO NOTHING RETURNING id"
                ),
                {
                    "id": receipt.model_call_id,
                    "turn": receipt.turn_id,
                    "execution": receipt.execution_id,
                    "workspace": receipt.workspace_id,
                    "sequence": receipt.sequence,
                    "requested": receipt.requested_model,
                    "answering": receipt.answering_model,
                    "status": receipt.status.value,
                    "input_tokens": receipt.input_tokens,
                    "cache_read": receipt.cache_read_input_tokens,
                    "cache_creation": receipt.cache_creation_input_tokens,
                    "output_tokens": receipt.output_tokens,
                    "cost": receipt.cost_millicredits,
                    "latency": receipt.latency_ms,
                    "error": receipt.error_code,
                    "started": receipt.started_at,
                    "completed": receipt.completed_at,
                },
            )
            if inserted.first() is None:
                existing = await conn.execute(
                    text(
                        "SELECT turn_id, execution_id, workspace_id, sequence, requested_model, "
                        "answering_model, status, input_tokens, cache_read_input_tokens, "
                        "cache_creation_input_tokens, output_tokens, cost_millicredits, "
                        "latency_ms, error_code, started_at, completed_at "
                        "FROM agent_model_call WHERE id=:id"
                    ),
                    {"id": receipt.model_call_id},
                )
                row = existing.mappings().one()
                actual = (
                    row["turn_id"],
                    row["execution_id"],
                    row["workspace_id"],
                    int(row["sequence"]),
                    row["requested_model"],
                    row["answering_model"],
                    row["status"],
                    int(row["input_tokens"]),
                    int(row["cache_read_input_tokens"]),
                    int(row["cache_creation_input_tokens"]),
                    int(row["output_tokens"]),
                    int(row["cost_millicredits"]),
                    float(row["latency_ms"]),
                    row["error_code"],
                    row["started_at"],
                    row["completed_at"],
                )
                expected = (
                    receipt.turn_id,
                    receipt.execution_id,
                    receipt.workspace_id,
                    receipt.sequence,
                    receipt.requested_model,
                    receipt.answering_model,
                    receipt.status.value,
                    receipt.input_tokens,
                    receipt.cache_read_input_tokens,
                    receipt.cache_creation_input_tokens,
                    receipt.output_tokens,
                    receipt.cost_millicredits,
                    receipt.latency_ms,
                    receipt.error_code,
                    receipt.started_at,
                    receipt.completed_at,
                )
                if actual != expected:
                    raise ValueError(
                        "model call id already exists with a different immutable receipt"
                    )
            for role, ordinal, ref in (
                ("model_input", 0, input_ref),
                ("model_output", 0, output_ref),
            ):
                if ref is not None:
                    await _insert_artifact_ref(
                        conn,
                        turn_id=receipt.turn_id,
                        owner_kind="model_call",
                        owner_id=receipt.model_call_id,
                        role=role,
                        ordinal=ordinal,
                        ref=ref,
                    )

    async def record_workspace_usage(
        self,
        *,
        turn_id: UUID,
        workspace_id: str,
        usage: WorkspaceUsageSnapshot,
    ) -> None:
        """Persist the final quota snapshot exactly once without exposing host paths."""

        async with self._conn_factory() as conn:
            inserted = await conn.execute(
                text(
                    "INSERT INTO agent_workspace_usage "
                    "(turn_id, workspace_id, file_count, total_bytes, output_file_count, "
                    " output_bytes, max_file_count, max_total_bytes) "
                    "VALUES (:turn, :workspace, :files, :bytes, :output_files, :output_bytes, "
                    " :max_files, :max_bytes) ON CONFLICT (turn_id) DO NOTHING RETURNING turn_id"
                ),
                {
                    "turn": turn_id,
                    "workspace": workspace_id,
                    "files": usage.file_count,
                    "bytes": usage.total_bytes,
                    "output_files": usage.output_file_count,
                    "output_bytes": usage.output_bytes,
                    "max_files": usage.max_file_count,
                    "max_bytes": usage.max_total_bytes,
                },
            )
            if inserted.first() is not None:
                return
            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT workspace_id, file_count, total_bytes, output_file_count, "
                            "output_bytes, max_file_count, max_total_bytes "
                            "FROM agent_workspace_usage WHERE turn_id=:turn"
                        ),
                        {"turn": turn_id},
                    )
                )
                .mappings()
                .one()
            )
            actual = (
                row["workspace_id"],
                int(row["file_count"]),
                int(row["total_bytes"]),
                int(row["output_file_count"]),
                int(row["output_bytes"]),
                int(row["max_file_count"]),
                int(row["max_total_bytes"]),
            )
            expected = (
                workspace_id,
                usage.file_count,
                usage.total_bytes,
                usage.output_file_count,
                usage.output_bytes,
                usage.max_file_count,
                usage.max_total_bytes,
            )
            if actual != expected:
                raise ValueError("turn already has a different immutable workspace usage receipt")

    async def next_model_call_sequence(self, *, turn_id: UUID) -> int:
        """Return the next durable call ordinal for a sequential agent turn."""

        async with self._conn_factory() as conn:
            result = await conn.execute(
                text(
                    "SELECT COALESCE(MAX(sequence), 0) + 1 "
                    "FROM agent_model_call WHERE turn_id=:turn"
                ),
                {"turn": turn_id},
            )
            return int(result.scalar_one())

    async def record_finalization(
        self,
        *,
        turn_id: UUID,
        workspace_id: str,
        envelope: AgentFinalizeEnvelope,
    ) -> None:
        """Record the envelope only; C6.4 owns validating and applying finalization authority."""

        scoped_refs = (
            *((envelope.user_message_artifact_ref,) if envelope.user_message_artifact_ref else ()),
            *envelope.output_refs,
            *envelope.assumption_refs,
            *envelope.next_action_refs,
            *envelope.domain_refs,
            *envelope.open_gate_refs,
        )
        if any(ref.workspace_id != workspace_id for ref in scoped_refs):
            raise ValueError("finalization refs cross the supplied workspace boundary")
        async with self._conn_factory() as conn:
            inserted = await conn.execute(
                text(
                    "INSERT INTO agent_finalization "
                    "(id, turn_id, execution_id, workspace_id, status, failure_code, finalized_at) "
                    "VALUES (:id, :turn, :execution, :workspace, :status, :failure, :at) "
                    "ON CONFLICT (id) DO NOTHING RETURNING id"
                ),
                {
                    "id": envelope.finalization_id,
                    "turn": turn_id,
                    "execution": envelope.execution_id,
                    "workspace": workspace_id,
                    "status": envelope.status.value,
                    "failure": envelope.failure_code,
                    "at": envelope.finalized_at,
                },
            )
            if inserted.first() is None:
                existing = await conn.execute(
                    text(
                        "SELECT turn_id, execution_id, workspace_id, status, failure_code, "
                        "finalized_at FROM agent_finalization WHERE id=:id"
                    ),
                    {"id": envelope.finalization_id},
                )
                row = existing.mappings().one()
                actual = (
                    row["turn_id"],
                    row["execution_id"],
                    row["workspace_id"],
                    row["status"],
                    row["failure_code"],
                    row["finalized_at"],
                )
                expected = (
                    turn_id,
                    envelope.execution_id,
                    workspace_id,
                    envelope.status.value,
                    envelope.failure_code,
                    envelope.finalized_at,
                )
                if actual != expected:
                    raise ValueError(
                        "finalization id already exists with a different immutable envelope"
                    )
            final_message_refs: tuple[ArtifactRef, ...] = (
                (envelope.user_message_artifact_ref,) if envelope.user_message_artifact_ref else ()
            )
            artifact_groups: tuple[tuple[str, tuple[ArtifactRef, ...]], ...] = (
                (
                    "final_message",
                    final_message_refs,
                ),
                ("output", envelope.output_refs),
                ("assumption", envelope.assumption_refs),
                ("next_action", envelope.next_action_refs),
            )
            for role, refs in artifact_groups:
                for ordinal, ref in enumerate(refs):
                    await _insert_artifact_ref(
                        conn,
                        turn_id=turn_id,
                        owner_kind="finalization",
                        owner_id=envelope.finalization_id,
                        role=role,
                        ordinal=ordinal,
                        ref=ref,
                    )
            domain_groups: tuple[tuple[str, tuple[DomainObjectRef, ...]], ...] = (
                ("output", envelope.domain_refs),
                ("open_gate", envelope.open_gate_refs),
            )
            for role, domain_refs in domain_groups:
                for ordinal, domain_ref in enumerate(domain_refs):
                    inserted_ref = await conn.execute(
                        text(
                            "INSERT INTO agent_finalization_domain_ref "
                            "(finalization_id, workspace_id, ref_role, ordinal, object_type, "
                            " object_id, object_version) "
                            "VALUES (:finalization, :workspace, :role, :ordinal, :type, :id, "
                            " :version) ON CONFLICT DO NOTHING RETURNING finalization_id"
                        ),
                        {
                            "finalization": envelope.finalization_id,
                            "workspace": workspace_id,
                            "role": role,
                            "ordinal": ordinal,
                            "type": domain_ref.object_type,
                            "id": domain_ref.object_id,
                            "version": domain_ref.version,
                        },
                    )
                    if inserted_ref.first() is None:
                        existing_ref = await conn.execute(
                            text(
                                "SELECT workspace_id, object_type, object_id, object_version "
                                "FROM agent_finalization_domain_ref "
                                "WHERE finalization_id=:finalization AND ref_role=:role "
                                "AND ordinal=:ordinal"
                            ),
                            {
                                "finalization": envelope.finalization_id,
                                "role": role,
                                "ordinal": ordinal,
                            },
                        )
                        row = existing_ref.mappings().one()
                        if (
                            row["workspace_id"] != workspace_id
                            or row["object_type"] != domain_ref.object_type
                            or row["object_id"] != domain_ref.object_id
                            or row["object_version"] != domain_ref.version
                        ):
                            raise ValueError(
                                "finalization domain-ref position already has a different target"
                            )
            counts = await conn.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM agent_artifact_ref "
                    " WHERE owner_kind='finalization' AND owner_id=:id) AS artifact_count, "
                    "(SELECT count(*) FROM agent_finalization_domain_ref "
                    " WHERE finalization_id=:id) AS domain_count"
                ),
                {"id": envelope.finalization_id},
            )
            count_row = counts.mappings().one()
            expected_artifact_count = sum(len(refs) for _, refs in artifact_groups)
            expected_domain_count = sum(len(refs) for _, refs in domain_groups)
            if (
                int(count_row["artifact_count"]) != expected_artifact_count
                or int(count_row["domain_count"]) != expected_domain_count
            ):
                raise ValueError("finalization id already has a different immutable ref set")

    async def commit_finalization_authority(
        self,
        *,
        turn_id: UUID,
        workspace_id: str,
        envelope: AgentFinalizeEnvelope,
        envelope_ref: ArtifactRef,
    ) -> None:
        """Atomically make a previously recorded envelope authoritative for turn state."""

        if envelope_ref.workspace_id != workspace_id:
            raise ValueError("finalization envelope artifact crosses the turn workspace")
        status = {
            "completed": AgentTurnStatus.COMPLETED,
            "awaiting_input": AgentTurnStatus.AWAITING_INPUT,
            "blocked": AgentTurnStatus.AWAITING_INPUT,
            "failed": AgentTurnStatus.FAILED,
        }[envelope.status.value]
        async with self._conn_factory() as conn:
            inserted = await conn.execute(
                text(
                    """
                    INSERT INTO agent_finalization_commit (
                        finalization_id, turn_id, execution_id, workspace_id,
                        envelope_artifact_key, envelope_sha256
                    )
                    SELECT :finalization, :turn, :execution, :workspace, :key, :sha
                    FROM agent_finalization f
                    WHERE f.id=:finalization AND f.turn_id=:turn
                      AND f.execution_id=:execution AND f.workspace_id=:workspace
                    ON CONFLICT (finalization_id) DO NOTHING
                    RETURNING finalization_id
                    """
                ),
                {
                    "finalization": envelope.finalization_id,
                    "turn": turn_id,
                    "execution": envelope.execution_id,
                    "workspace": workspace_id,
                    "key": envelope_ref.artifact_key,
                    "sha": envelope_ref.sha256,
                },
            )
            if inserted.first() is None:
                existing = (
                    (
                        await conn.execute(
                            text(
                                "SELECT turn_id, execution_id, workspace_id, "
                                "envelope_artifact_key, envelope_sha256 "
                                "FROM agent_finalization_commit "
                                "WHERE finalization_id=:finalization"
                            ),
                            {"finalization": envelope.finalization_id},
                        )
                    )
                    .mappings()
                    .one_or_none()
                )
                if existing is None:
                    raise ValueError("finalization receipt is absent or outside the turn")
                if (
                    existing["turn_id"] != turn_id
                    or existing["execution_id"] != envelope.execution_id
                    or existing["workspace_id"] != workspace_id
                    or existing["envelope_artifact_key"] != envelope_ref.artifact_key
                    or existing["envelope_sha256"] != envelope_ref.sha256
                ):
                    raise ValueError("turn already has a different finalization authority")
            await _append_turn_event(
                conn,
                turn_id=turn_id,
                workspace_id=workspace_id,
                status=status,
                reason_code=envelope.failure_code,
            )

    async def mark_unfinalized(
        self,
        *,
        turn_id: UUID,
        workspace_id: str,
        reason_code: str,
        abandoned: bool,
    ) -> None:
        """Make timeout/cancellation/crash visible without manufacturing a finalize record."""

        await self._mark_status(
            turn_id=turn_id,
            workspace_id=workspace_id,
            status=(AgentTurnStatus.ABANDONED if abandoned else AgentTurnStatus.FAILED),
            reason_code=reason_code,
        )

    async def mark_running(self, *, turn_id: UUID, workspace_id: str) -> None:
        await self._mark_status(
            turn_id=turn_id,
            workspace_id=workspace_id,
            status=AgentTurnStatus.RUNNING,
            reason_code=None,
        )

    async def _mark_status(
        self,
        *,
        turn_id: UUID,
        workspace_id: str,
        status: AgentTurnStatus,
        reason_code: str | None,
    ) -> None:
        async with self._conn_factory() as conn:
            exists = await conn.execute(
                text("SELECT 1 FROM agent_turn WHERE id=:turn AND workspace_id=:workspace"),
                {"turn": turn_id, "workspace": workspace_id},
            )
            if exists.first() is None:
                raise KeyError("agent turn is absent from the requested workspace")
            committed = await conn.execute(
                text(
                    "SELECT 1 FROM agent_finalization_commit "
                    "WHERE turn_id=:turn AND workspace_id=:workspace"
                ),
                {"turn": turn_id, "workspace": workspace_id},
            )
            if committed.first() is not None:
                return
            await _append_turn_event(
                conn,
                turn_id=turn_id,
                workspace_id=workspace_id,
                status=status,
                reason_code=reason_code,
            )

    async def _read_turn(
        self,
        conn: object,
        workspace_id: str,
        turn_id: UUID,
    ) -> AgentTurnReceipt | None:
        result = await conn.execute(  # type: ignore[attr-defined]
            text(
                "SELECT t.*, e.status AS current_status, a.media_type, a.size_bytes "
                "FROM agent_turn t "
                "JOIN LATERAL (SELECT status FROM agent_turn_event "
                " WHERE turn_id=t.id ORDER BY seq DESC LIMIT 1) e ON true "
                "JOIN artifact a ON a.storage_key=t.resource_manifest_key "
                "WHERE t.workspace_id=:workspace AND t.id=:turn"
            ),
            {"workspace": workspace_id, "turn": turn_id},
        )
        row = result.mappings().first()
        if row is None:
            return None
        return AgentTurnReceipt(
            turn_id=row["id"],
            execution_id=ExecutionId(row["execution_id"]),
            parent_execution_id=(
                ExecutionId(row["parent_execution_id"])
                if row["parent_execution_id"] is not None
                else None
            ),
            workspace_id=row["workspace_id"],
            project_id=row["project_id"],
            thread_id=row["thread_id"],
            actor_id=row["actor_id"],
            role=AgentRole(row["role"]),
            workspace_root_id=row["workspace_root_id"],
            profile_ref=AgentResourceRef(
                kind=ResourceKind.PROFILE,
                name=row["profile_name"],
                version=row["profile_version"],
                sha256=row["profile_sha256"],
            ),
            resource_manifest_ref=ArtifactRef(
                workspace_id=row["workspace_id"],
                artifact_key=row["resource_manifest_key"],
                sha256=row["resource_manifest_artifact_sha256"],
                media_type=row["media_type"],
                byte_count=int(row["size_bytes"]),
            ),
            resource_manifest_sha256=row["resource_manifest_sha256"],
            retention_class=row["retention_class"],
            requested_at=row["requested_at"],
            current_status=AgentTurnStatus(row["current_status"]),
        )


class DbAgentContextReceiptStore(ContextReceiptStore):
    def __init__(self, *, conn_factory: ConnFactory = transaction) -> None:
        self._conn_factory = conn_factory

    async def record(
        self,
        *,
        request: AgentTurnRequest,
        receipt: ContextAssemblyReceipt,
    ) -> None:
        manifest = receipt.manifest
        workspace_id = request.constitution.workspace_id
        async with self._conn_factory() as conn:
            inserted = await conn.execute(
                text(
                    "INSERT INTO agent_context_bundle "
                    "(id, turn_id, execution_id, workspace_id, schema_version, policy_version, "
                    " token_counter_version, aggregate_sha256, assembled_at) "
                    "VALUES (:id, :turn, :execution, :workspace, :schema, :policy, :counter, "
                    " :aggregate, :assembled) "
                    "ON CONFLICT (turn_id) DO NOTHING RETURNING id"
                ),
                {
                    "id": manifest.context_bundle_id,
                    "turn": request.turn_id,
                    "execution": manifest.execution_id,
                    "workspace": workspace_id,
                    "schema": manifest.schema_version,
                    "policy": receipt.policy_version,
                    "counter": receipt.token_counter_version,
                    "aggregate": manifest.aggregate_sha256,
                    "assembled": manifest.assembled_at,
                },
            )
            if inserted.first() is None:
                existing = await conn.execute(
                    text(
                        "SELECT id, aggregate_sha256 FROM agent_context_bundle WHERE turn_id=:turn"
                    ),
                    {"turn": request.turn_id},
                )
                row = existing.first()
                if (
                    row is None
                    or row[0] != manifest.context_bundle_id
                    or row[1] != manifest.aggregate_sha256
                ):
                    raise ValueError("turn already has a different opening context receipt")
                return

            refs_by_layer = {
                layer: tuple(item for item in receipt.refs if item.layer is layer)
                for layer in ContextLayer
            }
            budgets = {item.layer: item.max_tokens for item in receipt.budgets}
            for layer_ordinal, layer_manifest in enumerate(manifest.layers, start=1):
                layer_refs = refs_by_layer[layer_manifest.layer]
                included_count = sum(item.disposition == "included" for item in layer_refs)
                excluded_count = sum(item.disposition == "excluded" for item in layer_refs)
                await conn.execute(
                    text(
                        "INSERT INTO agent_context_layer "
                        "(context_bundle_id, workspace_id, ordinal, layer, token_budget, "
                        " token_count, included_count, excluded_count) "
                        "VALUES (:bundle, :workspace, :ordinal, :layer, :budget, :tokens, "
                        " :included, :excluded)"
                    ),
                    {
                        "bundle": manifest.context_bundle_id,
                        "workspace": workspace_id,
                        "ordinal": layer_ordinal,
                        "layer": layer_manifest.layer.value,
                        "budget": budgets[layer_manifest.layer],
                        "tokens": layer_manifest.token_count,
                        "included": included_count,
                        "excluded": excluded_count,
                    },
                )
                for item in layer_refs:
                    ref = item.ref
                    if isinstance(ref, ArtifactRef):
                        artifact_key_value = ref.artifact_key
                        artifact_sha_value = ref.sha256
                        object_type_value = None
                        object_id_value = None
                        object_version_value = None
                        ref_kind = "artifact"
                    else:
                        artifact_key_value = None
                        artifact_sha_value = None
                        object_type_value = ref.object_type
                        object_id_value = ref.object_id
                        object_version_value = ref.version
                        ref_kind = "domain"
                    await conn.execute(
                        text(
                            "INSERT INTO agent_context_ref "
                            "(id, context_bundle_id, workspace_id, layer_ordinal, disposition, "
                            " ordinal, ref_kind, artifact_key, artifact_sha256, object_type, "
                            " object_id, object_version, content_sha256, materialized_path, "
                            " token_count, exclusion_reason_code) "
                            "VALUES (:id, :bundle, :workspace, :layer_ordinal, :disposition, "
                            " :ordinal, :kind, :artifact_key, :artifact_sha, :object_type, "
                            " :object_id, :object_version, :content_sha, :path, :tokens, :reason)"
                        ),
                        {
                            "id": uuid5(
                                manifest.context_bundle_id,
                                f"{layer_ordinal}:{item.disposition}:{item.ordinal}",
                            ),
                            "bundle": manifest.context_bundle_id,
                            "workspace": workspace_id,
                            "layer_ordinal": layer_ordinal,
                            "disposition": item.disposition,
                            "ordinal": item.ordinal,
                            "kind": ref_kind,
                            "artifact_key": artifact_key_value,
                            "artifact_sha": artifact_sha_value,
                            "object_type": object_type_value,
                            "object_id": object_id_value,
                            "object_version": object_version_value,
                            "content_sha": item.content_sha256,
                            "path": item.materialized_path,
                            "tokens": item.token_count,
                            "reason": item.exclusion_reason_code,
                        },
                    )
            await _append_turn_event(
                conn,
                turn_id=request.turn_id,
                workspace_id=workspace_id,
                status=AgentTurnStatus.CONTEXT_READY,
            )


class DbAgentHistoryStore(AgentHistoryStore):
    def __init__(self, *, conn_factory: ConnFactory = transaction) -> None:
        self._conn_factory = conn_factory

    async def load(self, *, workspace_id: str, thread_id: str) -> Sequence[HistoryMessageRef]:
        async with self._conn_factory() as conn:
            result = await conn.execute(
                text(
                    "SELECT m.id, m.turn_id, m.sequence, m.role, m.body_artifact_key, "
                    "m.body_sha256, a.media_type, a.size_bytes "
                    "FROM agent_thread_message m "
                    "JOIN artifact a ON a.storage_key=m.body_artifact_key "
                    "WHERE m.workspace_id=:workspace AND m.thread_id=:thread "
                    "ORDER BY m.sequence"
                ),
                {"workspace": workspace_id, "thread": thread_id},
            )
            return tuple(
                HistoryMessageRef(
                    message_id=row["id"],
                    turn_id=row["turn_id"],
                    sequence=int(row["sequence"]),
                    role=row["role"],
                    body_ref=ArtifactRef(
                        workspace_id=workspace_id,
                        artifact_key=row["body_artifact_key"],
                        sha256=row["body_sha256"],
                        media_type=row["media_type"],
                        byte_count=int(row["size_bytes"]),
                    ),
                )
                for row in result.mappings()
            )

    async def append(
        self,
        *,
        message_id: UUID,
        turn_id: UUID,
        workspace_id: str,
        thread_id: str,
        role: Literal["system", "user", "assistant", "tool"],
        body_ref: ArtifactRef,
    ) -> HistoryMessageRef:
        if body_ref.workspace_id != workspace_id:
            raise ValueError("history body ref crosses the thread workspace")
        async with self._conn_factory() as conn:
            existing = await conn.execute(
                text(
                    "SELECT turn_id, sequence, role, body_artifact_key, body_sha256 "
                    "FROM agent_thread_message "
                    "WHERE workspace_id=:workspace AND id=:id"
                ),
                {"workspace": workspace_id, "id": message_id},
            )
            row = existing.mappings().first()
            if row is not None:
                if (
                    row["turn_id"] != turn_id
                    or row["role"] != role
                    or row["body_artifact_key"] != body_ref.artifact_key
                    or row["body_sha256"] != body_ref.sha256
                ):
                    raise ValueError("history message id already has different immutable content")
                return HistoryMessageRef(
                    message_id=message_id,
                    turn_id=turn_id,
                    sequence=int(row["sequence"]),
                    role=role,
                    body_ref=body_ref,
                )
            await conn.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
                {"scope": _thread_lock_key(workspace_id, thread_id)},
            )
            next_result = await conn.execute(
                text(
                    "SELECT COALESCE(max(sequence), 0) + 1 "
                    "FROM agent_thread_message "
                    "WHERE workspace_id=:workspace AND thread_id=:thread"
                ),
                {"workspace": workspace_id, "thread": thread_id},
            )
            sequence = int(next_result.scalar_one())
            await conn.execute(
                text(
                    "INSERT INTO agent_thread_message "
                    "(id, workspace_id, thread_id, turn_id, sequence, role, body_artifact_key, "
                    " body_sha256, retention_class) "
                    "SELECT :id, :workspace, :thread, :turn, :sequence, :role, :key, :sha, "
                    " t.retention_class FROM agent_turn t "
                    "WHERE t.id=:turn AND t.workspace_id=:workspace"
                ),
                {
                    "id": message_id,
                    "workspace": workspace_id,
                    "thread": thread_id,
                    "turn": turn_id,
                    "sequence": sequence,
                    "role": role,
                    "key": body_ref.artifact_key,
                    "sha": body_ref.sha256,
                },
            )
            await _insert_artifact_ref(
                conn,
                turn_id=turn_id,
                owner_kind="history",
                owner_id=message_id,
                role="history_body",
                ordinal=0,
                ref=body_ref,
            )
            return HistoryMessageRef(
                message_id=message_id,
                turn_id=turn_id,
                sequence=sequence,
                role=role,
                body_ref=body_ref,
            )


class DbAgentReplayReader:
    def __init__(
        self,
        *,
        storage: StorageBackend,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._storage = storage
        self._conn_factory = conn_factory
        self._turns = DbAgentTurnJournal(conn_factory=conn_factory)

    async def inspect(self, *, workspace_id: str, turn_id: UUID) -> AgentColdReplayReceipt:
        async with self._conn_factory() as conn:
            turn = await self._turns._read_turn(conn, workspace_id, turn_id)
            if turn is None:
                raise KeyError("agent turn is absent from the requested workspace")
            context = await self._read_context(conn, workspace_id, turn_id)
            artifact_rows = await conn.execute(
                text(
                    "SELECT r.ref_role, r.artifact_key, r.artifact_sha256, "
                    "a.media_type, a.size_bytes, a.erased_at, a.purged_at, "
                    "EXISTS (SELECT 1 FROM agent_artifact_tombstone t "
                    " WHERE t.workspace_id=r.workspace_id "
                    " AND t.artifact_key=r.artifact_key) AS tombstoned "
                    "FROM agent_artifact_ref r "
                    "LEFT JOIN artifact a ON a.storage_key=r.artifact_key "
                    "WHERE r.workspace_id=:workspace AND r.turn_id=:turn "
                    "ORDER BY r.ref_role, r.ordinal"
                ),
                {"workspace": workspace_id, "turn": turn_id},
            )
            artifacts: list[ReplayArtifactRef] = []
            blockers: list[str] = []
            for row in artifact_rows.mappings():
                if row["media_type"] is None:
                    state = AgentArtifactState.MISSING
                    media_type = "application/octet-stream"
                    size_bytes = 0
                elif row["tombstoned"]:
                    state = AgentArtifactState.ERASED
                    media_type = row["media_type"]
                    size_bytes = int(row["size_bytes"])
                elif row["purged_at"] is not None:
                    state = AgentArtifactState.PURGED
                    media_type = row["media_type"]
                    size_bytes = int(row["size_bytes"])
                elif row["erased_at"] is not None:
                    state = AgentArtifactState.ERASED
                    media_type = row["media_type"]
                    size_bytes = int(row["size_bytes"])
                elif not await self._storage.exists(row["artifact_key"]):
                    state = AgentArtifactState.MISSING
                    media_type = row["media_type"]
                    size_bytes = int(row["size_bytes"])
                else:
                    state = AgentArtifactState.LIVE
                    media_type = row["media_type"]
                    size_bytes = int(row["size_bytes"])
                replay_ref = ReplayArtifactRef(
                    ref=ArtifactRef(
                        workspace_id=workspace_id,
                        artifact_key=row["artifact_key"],
                        sha256=row["artifact_sha256"],
                        media_type=media_type,
                        byte_count=size_bytes,
                    ),
                    state=state,
                    ref_role=row["ref_role"],
                )
                artifacts.append(replay_ref)
                if state is not AgentArtifactState.LIVE:
                    blockers.append(f"artifact_{state.value}:{row['ref_role']}")
            if context is None:
                blockers.append("context_receipt_missing")
            else:
                unavailable_memory = await conn.execute(
                    text(
                        "SELECT count(*) FROM agent_context_ref r "
                        "LEFT JOIN memory m ON m.memory_id=r.object_id "
                        "WHERE r.context_bundle_id=:bundle AND r.disposition='included' "
                        "AND r.object_type='scoped_memory' "
                        "AND (m.memory_id IS NULL OR m.workspace_id<>:workspace "
                        "OR m.status='tombstoned')"
                    ),
                    {
                        "bundle": context.manifest.context_bundle_id,
                        "workspace": workspace_id,
                    },
                )
                if int(unavailable_memory.scalar_one()) > 0:
                    blockers.append("context_domain_tombstoned:scoped_memory")
        return AgentColdReplayReceipt(
            turn=turn,
            context=context,
            artifacts=tuple(artifacts),
            blocker_codes=tuple(sorted(set(blockers))),
        )

    async def require_replayable(
        self,
        *,
        workspace_id: str,
        turn_id: UUID,
    ) -> AgentColdReplayReceipt:
        receipt = await self.inspect(workspace_id=workspace_id, turn_id=turn_id)
        if not receipt.replayable:
            raise AgentReplayUnavailable(receipt)
        return receipt

    async def _read_context(
        self,
        conn: object,
        workspace_id: str,
        turn_id: UUID,
    ) -> AgentContextReplayReceipt | None:
        bundle_result = await conn.execute(  # type: ignore[attr-defined]
            text(
                "SELECT * FROM agent_context_bundle WHERE workspace_id=:workspace AND turn_id=:turn"
            ),
            {"workspace": workspace_id, "turn": turn_id},
        )
        bundle = bundle_result.mappings().first()
        if bundle is None:
            return None
        rows_result = await conn.execute(  # type: ignore[attr-defined]
            text(
                "SELECT l.ordinal AS layer_ordinal, l.layer, l.token_budget, r.*,"
                " a.media_type, a.size_bytes "
                "FROM agent_context_layer l "
                "LEFT JOIN agent_context_ref r "
                " ON r.context_bundle_id=l.context_bundle_id AND r.layer_ordinal=l.ordinal "
                "LEFT JOIN artifact a ON a.storage_key=r.artifact_key "
                "WHERE l.context_bundle_id=:bundle "
                "ORDER BY l.ordinal, r.disposition, r.ordinal"
            ),
            {"bundle": bundle["id"]},
        )
        by_layer: dict[int, list[RowMapping]] = {index: [] for index in range(1, 8)}
        layer_names: dict[int, str] = {}
        layer_budgets: dict[int, int] = {}
        for row in rows_result.mappings():
            ordinal = int(row["layer_ordinal"])
            layer_names[ordinal] = row["layer"]
            layer_budgets[ordinal] = int(row["token_budget"])
            if row["id"] is not None:
                by_layer[ordinal].append(row)
        manifests: list[ContextLayerManifest] = []
        for ordinal in range(1, 8):
            included = [row for row in by_layer[ordinal] if row["disposition"] == "included"]
            excluded = [row for row in by_layer[ordinal] if row["disposition"] == "excluded"]
            manifests.append(
                ContextLayerManifest(
                    layer=ContextLayer(layer_names[ordinal]),
                    source_refs=tuple(self._row_ref(row, workspace_id) for row in included),
                    materialized_paths=tuple(
                        row["materialized_path"]
                        for row in included
                        if row["materialized_path"] is not None
                    ),
                    content_sha256s=tuple(row["content_sha256"] for row in included),
                    token_count=sum(int(row["token_count"]) for row in included),
                    excluded_refs=tuple(self._row_ref(row, workspace_id) for row in excluded),
                    exclusion_reason_codes=tuple(row["exclusion_reason_code"] for row in excluded),
                )
            )
        return AgentContextReplayReceipt(
            manifest=ContextBundleManifest(
                context_bundle_id=bundle["id"],
                execution_id=ExecutionId(bundle["execution_id"]),
                schema_version="1",
                layers=tuple(manifests),
                aggregate_sha256=bundle["aggregate_sha256"],
                assembled_at=bundle["assembled_at"],
            ),
            policy_version=bundle["policy_version"],
            token_counter_version=bundle["token_counter_version"],
            layer_token_budgets=(
                layer_budgets[1],
                layer_budgets[2],
                layer_budgets[3],
                layer_budgets[4],
                layer_budgets[5],
                layer_budgets[6],
                layer_budgets[7],
            ),
        )

    @staticmethod
    def _row_ref(row: RowMapping, workspace_id: str) -> ArtifactRef | DomainObjectRef:
        if row["ref_kind"] == "artifact":
            return ArtifactRef(
                workspace_id=workspace_id,
                artifact_key=row["artifact_key"],
                sha256=row["artifact_sha256"],
                media_type=row["media_type"],
                byte_count=int(row["size_bytes"]),
            )
        return DomainObjectRef(
            workspace_id=workspace_id,
            object_type=row["object_type"],
            object_id=row["object_id"],
            version=row["object_version"],
        )


class AgentPrivacyService:
    """Erase subject-bound agent artifacts and every affected isolated materialization."""

    def __init__(
        self,
        *,
        storage: StorageBackend,
        workspaces: AgentWorkspaceFactory,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._storage = storage
        self._workspaces = workspaces
        self._conn_factory = conn_factory

    async def erase_subject(
        self,
        *,
        workspace_id: str,
        subject_entity_id: UUID,
        reason_code: str = "dsar_subject_erasure",
    ) -> PrivacyEraseResult:
        """Erase every artifact bound to this subject through ``agent_artifact_subject``."""

        async with self._conn_factory() as conn:
            artifact_result = await conn.execute(
                text(
                    "SELECT artifact_key FROM agent_artifact_subject "
                    "WHERE workspace_id=:workspace AND subject_entity_id=:subject "
                    "ORDER BY artifact_key"
                ),
                {"workspace": workspace_id, "subject": subject_entity_id},
            )
            keys = tuple(artifact_result.scalars())
        return await self.erase_artifacts(
            workspace_id=workspace_id,
            subject_entity_id=subject_entity_id,
            artifact_keys=keys,
            reason_code=reason_code,
        )

    async def erase_project(
        self,
        *,
        workspace_id: str,
        project_id: str,
        reason_code: str = "project_deletion",
    ) -> PrivacyEraseResult:
        """Erase exclusively project-owned artifacts, then release the deletion interlock.

        ``agent_artifact_project`` uses ``ON DELETE RESTRICT`` so a project cannot be deleted first
        and leave untraceable CAS bytes behind. An artifact shared byte-for-byte with another
        project keeps its body and only loses this project's binding; exclusively owned artifacts
        take the normal tombstone, physical purge, affected-turn, and workspace-purge path.
        """

        project_subject = uuid5(_PROJECT_PRIVACY_NAMESPACE, f"{workspace_id}:{project_id}")
        async with self._conn_factory() as conn:
            await conn.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
                {"scope": f"agent-project-artifacts:{workspace_id}:{project_id}"},
            )
            rows = tuple(
                (
                    await conn.execute(
                        text(
                            "SELECT binding.artifact_key, NOT EXISTS ("
                            "SELECT 1 FROM agent_artifact_project other "
                            "WHERE other.workspace_id=binding.workspace_id "
                            "AND other.artifact_key=binding.artifact_key "
                            "AND other.project_id<>binding.project_id) AS exclusive "
                            "FROM agent_artifact_project binding "
                            "WHERE binding.workspace_id=:workspace_id "
                            "AND binding.project_id=:project_id ORDER BY binding.artifact_key"
                        ),
                        {"workspace_id": workspace_id, "project_id": project_id},
                    )
                ).mappings()
            )
        exclusive_keys = tuple(str(row["artifact_key"]) for row in rows if row["exclusive"])
        result = await self.erase_artifacts(
            workspace_id=workspace_id,
            subject_entity_id=project_subject,
            artifact_keys=exclusive_keys,
            reason_code=reason_code,
        )
        async with self._conn_factory() as conn:
            await conn.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
                {"scope": f"agent-project-artifacts:{workspace_id}:{project_id}"},
            )
            await conn.execute(
                text(
                    "DELETE FROM agent_artifact_project "
                    "WHERE workspace_id=:workspace_id AND project_id=:project_id"
                ),
                {"workspace_id": workspace_id, "project_id": project_id},
            )
        return result

    async def erase_artifacts(
        self,
        *,
        workspace_id: str,
        subject_entity_id: UUID,
        artifact_keys: Sequence[str],
        reason_code: str = "dsar_subject_erasure",
    ) -> PrivacyEraseResult:
        """Erase an explicit artifact-key set on behalf of one subject.

        The body :meth:`erase_subject` has always run, with the key set as a parameter rather than
        derived from the subject bindings alone. A caller that resolves its own dependency closure
        — PC-C8 §9's card erasure walks the per-statement reverse bindings *and* the captured
        evidence the quote was sliced from — reuses this whole path (tombstone → ``mark_erased`` →
        purge → turn event → isolated-workspace purge) instead of re-implementing it.

        Affected turns are found by artifact key rather than by re-joining the subject bindings;
        for ``erase_subject`` the two are the same set, and for a caller-supplied closure the key
        form is the one that is actually true. The array parameter is explicitly ``CAST(… AS
        text[])`` — the codebase's own precedent (``readiness_override_refs``) — so an **empty**
        key set stays a well-typed "matches nothing" instead of leaving Postgres to infer an
        element type it has no evidence for. An empty set is a real case: a subject with no
        artifact bindings must erase to a clean no-op, not an error.
        """

        keys = tuple(dict.fromkeys(sorted(artifact_keys)))
        async with self._conn_factory() as conn:
            affected_result = await conn.execute(
                text(
                    "SELECT DISTINCT t.id, t.execution_id, t.project_id, t.workspace_root_id "
                    "FROM agent_turn t WHERE t.workspace_id=:workspace AND ("
                    " EXISTS (SELECT 1 FROM agent_artifact_ref r "
                    "         WHERE r.turn_id=t.id AND r.workspace_id=t.workspace_id "
                    "         AND r.artifact_key = ANY(CAST(:keys AS text[])))"
                    " OR EXISTS (SELECT 1 FROM agent_context_bundle b "
                    "            JOIN agent_context_ref r ON r.context_bundle_id=b.id "
                    "            JOIN memory m ON r.object_type='scoped_memory' "
                    "             AND m.memory_id=r.object_id "
                    "            WHERE b.turn_id=t.id AND m.subject_entity_id=:subject)"
                    ") ORDER BY t.id"
                ),
                {
                    "workspace": workspace_id,
                    "subject": subject_entity_id,
                    "keys": list(keys),
                },
            )
            turns = tuple(affected_result.mappings())
            for key in keys:
                await conn.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                    {"key": key},
                )
                await conn.execute(
                    text(
                        "INSERT INTO agent_artifact_tombstone "
                        "(workspace_id, artifact_key, subject_entity_id, reason_code) "
                        "VALUES (:workspace, :key, :subject, :reason) ON CONFLICT DO NOTHING"
                    ),
                    {
                        "workspace": workspace_id,
                        "key": key,
                        "subject": subject_entity_id,
                        "reason": reason_code,
                    },
                )
                await mark_erased(conn, key)
                await conn.execute(
                    text(
                        "INSERT INTO agent_privacy_event "
                        "(event_id, workspace_id, subject_entity_id, artifact_key, action, "
                        " reason_code) "
                        "VALUES (:event, :workspace, :subject, :key, 'artifact_tombstoned', "
                        " :reason) ON CONFLICT (event_id) DO NOTHING"
                    ),
                    {
                        "event": uuid5(
                            _PRIVACY_NAMESPACE,
                            f"{workspace_id}:{subject_entity_id}:{key}",
                        ),
                        "workspace": workspace_id,
                        "subject": subject_entity_id,
                        "key": key,
                        "reason": reason_code,
                    },
                )
            for turn in turns:
                await _append_turn_event(
                    conn,
                    turn_id=turn["id"],
                    workspace_id=workspace_id,
                    status=AgentTurnStatus.PRIVACY_TOMBSTONED,
                    reason_code=reason_code,
                )

        if keys:
            async with self._conn_factory() as conn:
                result = await purge_erased_artifacts(conn, self._storage, keys=keys)
                if result.resurrected_keys:
                    raise RuntimeError(
                        "agent DSAR requires upstream live claim references to be erased first"
                    )

        purged_roots: list[str] = []
        for turn in turns:
            removed = self._workspaces.erase_for_privacy(
                workspace_id=workspace_id,
                project_id=turn["project_id"],
                execution_id=ExecutionId(turn["execution_id"]),
            )
            if removed:
                purged_roots.append(turn["workspace_root_id"])
            async with self._conn_factory() as conn:
                await conn.execute(
                    text(
                        "INSERT INTO agent_privacy_event "
                        "(event_id, workspace_id, subject_entity_id, turn_id, action, reason_code) "
                        "VALUES (:event, :workspace, :subject, :turn, 'workspace_purged', :reason) "
                        "ON CONFLICT (event_id) DO NOTHING"
                    ),
                    {
                        "event": uuid5(
                            _PRIVACY_NAMESPACE,
                            f"{workspace_id}:{subject_entity_id}:{turn['id']}:workspace",
                        ),
                        "workspace": workspace_id,
                        "subject": subject_entity_id,
                        "turn": turn["id"],
                        "reason": reason_code,
                    },
                )
        return PrivacyEraseResult(
            workspace_id=workspace_id,
            subject_entity_id=subject_entity_id,
            tombstoned_artifact_keys=keys,
            affected_turn_ids=tuple(turn["id"] for turn in turns),
            purged_workspace_root_ids=tuple(purged_roots),
        )
