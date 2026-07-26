"""C6.1 composition root for isolated agent workspaces and durable output artifacts."""

from __future__ import annotations

from pathlib import Path

from clue_agents import (
    AgentWorkspaceFactory,
    ArtifactRef,
    WorkspaceConfigurationError,
    WorkspaceRootPolicy,
)
from clue_agents.contracts import normalize_virtual_path
from clue_config import Settings, load_settings
from clue_storage import StorageBackend, artifact_key, content_address

__all__ = [
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
) -> AgentWorkspaceFactory:
    """Build the production factory only from validated deployment configuration.

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
    return AgentWorkspaceFactory(
        prepared_root=prepared,
        artifact_sink=StorageAgentArtifactSink(storage),
    )
