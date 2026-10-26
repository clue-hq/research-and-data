"""C5.1 composition: governed parameter storage, execution journal, and production invoker."""

from __future__ import annotations

import hashlib
import json
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_config import Settings
from clue_core import ExecutionId, ProjectRunId
from clue_db import ConnFactory, transaction
from clue_execution import (
    CanonicalParameterSnapshotter,
    DbExecutionJournal,
    DbInvocationJournal,
    ExecutionParameterStore,
    JournalCrashHook,
    ParameterArtifactState,
    ParameterArtifactStore,
    StoredParameterArtifact,
    emit_run_event,
)
from clue_storage import (
    StorageBackend,
    get_artifact,
    mark_erased,
    purge_erased_artifacts,
    record_artifact,
)
from clue_toolbelt import IdempotencyStore, InvocationCrashHook, ToolInvoker, ToolRegistry


class ExecutionRunEventWriter:
    async def append(
        self,
        conn: AsyncConnection,
        *,
        workspace_id: str,
        run_id: UUID,
        execution_id: ExecutionId,
        topic: str,
        payload: dict[str, JsonValue],
    ) -> None:
        await emit_run_event(
            conn,
            workspace_id=workspace_id,
            run_id=ProjectRunId(run_id),
            execution_id=execution_id,
            topic=topic,
            payload=payload,
        )


class StorageParameterArtifactStore(ParameterArtifactStore):
    """Workspace-checked bridge from execution's artifact seam to ``clue_storage``."""

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
        artifact_key: str,
        content_sha256: str,
        data: bytes,
        media_type: str,
    ) -> None:
        if artifact_key != f"{workspace_id}/{content_sha256}":
            raise ValueError("parameter artifact key does not encode its workspace and hash")
        async with self._conn_factory() as conn:
            artifact = await record_artifact(
                conn,
                storage_key=artifact_key,
                workspace_id=workspace_id,
                content_sha256=content_sha256,
                media_type=media_type,
                size_bytes=len(data),
                source_key="tool_parameters",
            )
            if (
                artifact.workspace_id != workspace_id
                or artifact.content_sha256 != content_sha256
                or artifact.size_bytes != len(data)
            ):
                raise ValueError("parameter artifact key is already bound to incompatible metadata")
            await self._storage.put(artifact_key, data, media_type=media_type)

    async def resolve(
        self,
        *,
        workspace_id: str,
        artifact_key: str,
    ) -> StoredParameterArtifact:
        if not artifact_key.startswith(f"{workspace_id}/"):
            return StoredParameterArtifact(state=ParameterArtifactState.MISSING)
        async with self._conn_factory() as conn:
            artifact = await get_artifact(conn, artifact_key)
        if artifact is None or artifact.workspace_id != workspace_id:
            return StoredParameterArtifact(state=ParameterArtifactState.MISSING)
        if artifact.erased_at is not None or artifact.purged_at is not None:
            return StoredParameterArtifact(state=ParameterArtifactState.ERASED)
        if not await self._storage.exists(artifact_key):
            return StoredParameterArtifact(state=ParameterArtifactState.MISSING)
        return StoredParameterArtifact(
            state=ParameterArtifactState.LIVE,
            data=await self._storage.get(artifact_key),
        )

    async def erase_parameter(
        self,
        *,
        workspace_id: str,
        execution_id: ExecutionId,
        artifact_key: str,
    ) -> bool:
        """DSAR/retention seam: mark a referenced parameter body, then purge after commit."""
        async with self._conn_factory() as conn:
            locked = (
                await conn.execute(
                    text(
                        """
                        SELECT a.storage_key
                        FROM artifact a
                        JOIN execution_artifact_ref r ON r.artifact_key = a.storage_key
                        WHERE r.execution_id = :execution_id
                          AND r.workspace_id = :workspace_id
                          AND r.artifact_key = :artifact_key
                          AND r.role = 'parameter'
                        FOR UPDATE OF a
                        """
                    ),
                    {
                        "execution_id": execution_id,
                        "workspace_id": workspace_id,
                        "artifact_key": artifact_key,
                    },
                )
            ).one_or_none()
            if locked is None:
                return False
            await mark_erased(conn, artifact_key)
        async with self._conn_factory() as conn:
            # ``sweep_expired=False``: this purges the one key it just erased. The pass's
            # opening table-wide expiry tombstone is the keyless fleet sweep's work, and a
            # per-key caller has no business doing it on other owners' rows (review I7).
            result = await purge_erased_artifacts(
                conn, self._storage, keys=(artifact_key,), sweep_expired=False
            )
        return artifact_key in result.purged_keys


class StorageExecutionParameterStore(ExecutionParameterStore):
    """Canonical recipe-parameter manifests over the same governed artifact substrate."""

    def __init__(self, store: StorageParameterArtifactStore) -> None:
        self._store = store

    async def snapshot(
        self,
        *,
        workspace_id: str,
        parameters: dict[str, JsonValue],
    ) -> tuple[str, str]:
        data = json.dumps(
            parameters,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
        digest = hashlib.sha256(data).hexdigest()
        artifact_key = f"{workspace_id}/{digest}"
        await self._store.persist(
            workspace_id=workspace_id,
            artifact_key=artifact_key,
            content_sha256=digest,
            data=data,
            media_type="application/vnd.clue.recipe-parameters+json",
        )
        return artifact_key, digest

    async def resolve(
        self,
        *,
        workspace_id: str,
        artifact_key: str,
        content_sha256: str,
    ) -> dict[str, JsonValue]:
        artifact = await self._store.resolve(
            workspace_id=workspace_id,
            artifact_key=artifact_key,
        )
        if artifact.state is not ParameterArtifactState.LIVE or artifact.data is None:
            raise ValueError("recipe parameter artifact is erased or missing")
        if hashlib.sha256(artifact.data).hexdigest() != content_sha256:
            raise ValueError("recipe parameter artifact digest mismatch")
        value = json.loads(artifact.data)
        if not isinstance(value, dict):
            raise ValueError("recipe parameters must resolve to a JSON object")
        return value


def build_tool_invoker(
    *,
    registry: ToolRegistry,
    idempotency_store: IdempotencyStore,
    storage: StorageBackend,
    settings: Settings,
    conn_factory: ConnFactory = transaction,
    crash_hook: InvocationCrashHook | None = None,
    journal_crash_hook: JournalCrashHook | None = None,
    parameter_artifacts: ParameterArtifactStore | None = None,
) -> ToolInvoker:
    """Build the mandatory production invoker; no null journal/storage fallback exists."""
    artifact_store = parameter_artifacts or StorageParameterArtifactStore(
        storage=storage,
        conn_factory=conn_factory,
    )
    journal_repository = DbExecutionJournal(
        transport=ExecutionRunEventWriter(),
        **({"crash_hook": journal_crash_hook} if journal_crash_hook is not None else {}),
    )
    journal = DbInvocationJournal(
        conn_factory=conn_factory,
        repository=journal_repository,
    )
    kwargs = {"crash_hook": crash_hook} if crash_hook is not None else {}
    return ToolInvoker(
        registry=registry,
        snapshotter=CanonicalParameterSnapshotter(artifact_store),
        journal=journal,
        idempotency_store=idempotency_store,
        idempotency_ttl_s=settings.toolbelt_idempotency_ttl_s,
        **kwargs,
    )


__all__ = [
    "ExecutionRunEventWriter",
    "StorageParameterArtifactStore",
    "StorageExecutionParameterStore",
    "build_tool_invoker",
]
