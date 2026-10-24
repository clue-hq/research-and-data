"""Composition-root two-phase erasure for tenant-local dynamic Client-KB state."""

from __future__ import annotations

from clue_db import ConnFactory
from clue_research.compliance import (
    WorkspaceDynamicClientKbErasureResult,
    erase_workspace_dynamic_client_kb,
)
from clue_storage import StorageBackend, purge_erased_artifacts


class DynamicClientKbWorkspaceEraser:
    """Commit DB tombstones/marks first, then physically purge evidence blobs."""

    def __init__(self, *, conn_factory: ConnFactory, storage: StorageBackend) -> None:
        self._conn_factory = conn_factory
        self._storage = storage

    async def erase(
        self,
        *,
        workspace_id: str,
        erased_by: str,
    ) -> WorkspaceDynamicClientKbErasureResult:
        async with self._conn_factory() as conn:
            result = await erase_workspace_dynamic_client_kb(
                conn,
                workspace_id=workspace_id,
                erased_by=erased_by,
            )

        # A separate connection/transaction is load-bearing: external storage deletion must never
        # happen while the DB erasure could still roll back. Replays recover the same key set from
        # durable artifact tombstones, so a crash between these phases converges.
        async with self._conn_factory() as conn:
            purged = await purge_erased_artifacts(
                conn,
                self._storage,
                keys=result.marked_artifact_keys,
                # The marks this erasure just committed, and nothing else: tombstoning every
                # expired row fleet-wide belongs to the keyless sweep (review I7).
                sweep_expired=False,
            )
        if purged.resurrected_keys:
            raise RuntimeError(
                "workspace erasure artifact gained a live claim reference during purge"
            )
        return result


__all__ = ["DynamicClientKbWorkspaceEraser"]
