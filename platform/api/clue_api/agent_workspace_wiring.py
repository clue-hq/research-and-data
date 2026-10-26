"""C6.1 composition root for isolated agent workspaces and durable output artifacts."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from clue_agents import (
    AgentWorkspaceFactory,
    ArtifactRef,
    WorkspaceConfigurationError,
    WorkspaceRootPolicy,
)
from clue_agents.contracts import normalize_virtual_path
from clue_agents.ports import TurnBinding
from clue_agents.worker_area import LOCAL_DIR, process_local_area, process_worker_area
from clue_agents.workspace_policy import PreparedWorkspaceRoot
from clue_agents.workspace_snapshotter import WorkspaceSnapshotter
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.agent_workspace_receipts import DbReceiptSource
from clue_api.agent_workspace_snapshots import DbWorkspaceSnapshotStore
from clue_config import Settings, load_settings
from clue_db import ConnFactory, transaction
from clue_storage import StorageBackend, artifact_key, content_address

__all__ = [
    "LOCAL_DIR",
    "StorageAgentArtifactSink",
    "build_agent_workspace_factory",
]


class StorageAgentArtifactSink:
    """Persist finalized output bytes under the existing workspace-scoped CAS contract."""

    def __init__(self, storage: StorageBackend) -> None:
        self._storage = storage

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
            raise WorkspaceConfigurationError(
                "only normalized output files may enter durable artifact storage"
            )
        digest = content_address(data)
        key = artifact_key(workspace_id, digest)
        await self._storage.put(key, data, media_type=media_type)
        return ArtifactRef(
            workspace_id=workspace_id,
            artifact_key=key,
            sha256=digest,
            media_type=media_type,
            byte_count=len(data),
        )


def build_agent_workspace_factory(
    *,
    storage: StorageBackend,
    settings: Settings | None = None,
    source_root: Path | None = None,
    home_root: Path | None = None,
    turn_bindings: Sequence[TurnBinding] = (),
    conn_factory: ConnFactory = transaction,
) -> AgentWorkspaceFactory:
    """Build the production factory only from validated deployment configuration.

    F3 (WS-15, WS-21; AW-19): with snapshots on (the default), the factory's root is this
    process's own worker area under the configured root, claimed by lock and wiped at claim, and
    every lease is restored from and saved to the chat's snapshot. With snapshots off — the
    emergency switch only — the root is ``<root>/local``, shared by every process on the machine,
    and folders are local only; this process holds a shared lock on ``<root>/workers/local.lock``
    for its whole life, so no snapshots-on worker removes the folder while it runs.

    The returned backend exposes opaque relative paths. These host paths remain confined to the
    trusted composition root and never enter agent state, prompts, or tool results.
    """

    resolved_settings = settings or load_settings()
    if resolved_settings.agent_workspace_root is None:
        raise WorkspaceConfigurationError("CLUE_AGENT_WORKSPACE_ROOT is required")
    repository_root = source_root or Path(__file__).resolve().parents[3]
    service_home = home_root or Path.home()
    prepared = WorkspaceRootPolicy(
        configured_root=Path(resolved_settings.agent_workspace_root),
        source_root=repository_root,
        home_root=service_home,
    ).prepare()
    if not resolved_settings.agent_workspace_snapshots_enabled:
        # Shared with every other snapshots-off process; the area lets the cache sweep skip the
        # chats this process is using, and holds the shared lock that keeps ``local`` in place.
        local = process_local_area(prepared.path)
        return AgentWorkspaceFactory(
            prepared_root=PreparedWorkspaceRoot(path=local.path),
            artifact_sink=DurableAgentArtifactStore(storage=storage),
            area=local,
            turn_bindings=turn_bindings,
        )
    area = process_worker_area(prepared.path)
    return AgentWorkspaceFactory(
        prepared_root=PreparedWorkspaceRoot(path=area.path),
        artifact_sink=DurableAgentArtifactStore(storage=storage),
        area=area,
        snapshotter=WorkspaceSnapshotter(
            store=DbWorkspaceSnapshotStore(
                storage=storage,
                conn_factory=conn_factory,
                concurrency=resolved_settings.agent_workspace_transfer_concurrency,
            ),
            concurrency=resolved_settings.agent_workspace_transfer_concurrency,
            legacy_root=prepared.path,
            # What a file was and how to get it again, for after Phase 2 expires its bytes
            # (AW-22, AW-24). Read from the rows the turn already wrote; never a blocker.
            receipts=DbReceiptSource(
                conn_factory=conn_factory,
                artifacts=DurableAgentArtifactStore(storage=storage, conn_factory=conn_factory),
            ),
        ),
        turn_bindings=turn_bindings,
    )
