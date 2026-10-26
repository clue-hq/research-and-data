"""One seam every writer of a project's settled state calls when it has committed.

Since F3 (spec WS-37; ruling AW-20) there is no shared project library on disk: each chat keeps its
own ``project/`` copy and syncs it at the start of its turn whenever the library digest has moved.
An ordinary writer's row change already moves that digest, so it has nothing to do here.

The one caller this seam still serves is the one whose *content* moves without any row the digest
reads: a DSAR erasure takes a quote out of ``decisions.md`` while the ``volunteered_statement`` row
stays as audit. Its forced refresh bumps the project's library epoch, which the digest includes,
so every chat's copy — on whichever worker holds it — resyncs on its next turn.

Two properties make it safe to call from inside a writer:

* **It never raises.** A failure is logged as ``project_library.refresh_failed`` and answered with
  ``None``: a write must not fail because its rendering could not be refreshed.
* **It opens its own connection,** so it runs *after* the writer's transaction commits.

Every hook site takes the refresher as an optional constructor/parameter defaulting to ``None``.
"""

from __future__ import annotations

from clue_api.project_library import bump_project_library_epoch
from clue_db import ConnFactory, transaction
from clue_obs import get_logger

__all__ = ["ProjectLibraryRefresher"]

log = get_logger("clue_api.project_library_refresh")


class ProjectLibraryRefresher:
    """Tell every chat of a project to resync its library copy when content moved unseen."""

    def __init__(self, *, conn_factory: ConnFactory = transaction) -> None:
        self._conn_factory = conn_factory

    async def refresh(
        self,
        *,
        workspace_id: str,
        project_id: str,
        force: bool = False,
    ) -> int | None:
        """The project's new library epoch when ``force``d, else ``None`` (nothing to do).

        ``force`` is for a caller whose *content* moved while the digest did not — the DSAR
        erasure. Ordinary writers leave it alone: their row change moves the digest, and every
        chat's copy follows it on that chat's next turn.
        """

        if not force:
            return None
        try:
            async with self._conn_factory() as conn:
                return await bump_project_library_epoch(
                    conn, workspace_id=workspace_id, project_id=project_id
                )
        # Deliberately broad: a refresh may never fail the write that preceded it.
        except Exception as exc:
            log.warning(
                "project_library.refresh_failed",
                workspace_id=workspace_id,
                project_id=project_id,
                forced=force,
                error=type(exc).__name__,
            )
            return None
