"""One seam every writer of a project's settled state calls when it has committed.

The project library (:mod:`clue_api.project_library`) is *lazily* correct: a turn takes the cheap
digest over the rows the tree is compiled from, and rebuilds the tree when it has moved. Nothing
here is needed for that to hold. What is needed is freshness for the readers that are **not**
turns — the frontend reads the same settled state, and the human's project-document PUT round-trips
through it — and for the one thing the digest cannot see at all: a DSAR erasure takes a quote out
of ``decisions.md`` without moving a single row the digest hashes, which is why that one refresh is
forced.

Three properties make this safe to call from inside a writer:

* **It never raises.** A refresh failure is logged as ``project_library.refresh_failed`` and
  answered with ``None``. A plan must not fail to save because a markdown tree could not be
  written, and because the digest is lazy the cost of a lost refresh is bounded by one turn.
* **It opens its own connection.** The compile takes the project's row lock
  (:func:`~clue_api.arv2.project_documents.lock_project`), so it must run *after* the writer's
  transaction commits, never inside it.
* **Absent means off.** Every hook site takes the refresher as an optional constructor/parameter
  defaulting to ``None``; a deployment with no agent-workspace root composes no refresher and every
  hook is a no-op, exactly as it behaved before this seam existed.
"""

from __future__ import annotations

from clue_agents import AgentArtifactReader, AgentWorkspaceFactory
from clue_api.project_library import ensure_project_library
from clue_db import ConnFactory, transaction
from clue_obs import get_logger
from clue_storage import StorageBackend

__all__ = ["ProjectLibraryRefresher"]

log = get_logger("clue_api.project_library_refresh")


class ProjectLibraryRefresher:
    """Rebuild one project's library, on its own connection, best-effort."""

    def __init__(
        self,
        *,
        storage: StorageBackend,
        artifacts: AgentArtifactReader,
        workspaces: AgentWorkspaceFactory,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._storage = storage
        self._artifacts = artifacts
        self._workspaces = workspaces
        self._conn_factory = conn_factory

    async def refresh(
        self,
        *,
        workspace_id: str,
        project_id: str,
        force: bool = False,
    ) -> str | None:
        """The installed generation's digest, or ``None`` when nothing was installed.

        ``force`` is for a caller whose *content* moved while the digest did not — the DSAR
        erasure. Ordinary writers leave it alone: their row change moves the digest, and an
        unmoved digest means there is genuinely nothing to rewrite.
        """

        try:
            async with self._conn_factory() as conn:
                snapshot = await ensure_project_library(
                    conn,
                    self._storage,
                    self._artifacts,
                    self._workspaces,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    force=force,
                )
        # Deliberately broad: every failure mode here — a compile, a fetch, a filesystem write —
        # is a *rendering* failure, and a rendering may never fail the write that preceded it.
        except Exception as exc:
            log.warning(
                "project_library.refresh_failed",
                workspace_id=workspace_id,
                project_id=project_id,
                forced=force,
                error=type(exc).__name__,
            )
            return None
        return snapshot.digest
