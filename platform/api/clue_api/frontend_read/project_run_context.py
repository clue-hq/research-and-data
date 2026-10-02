"""The latest-run-wins ``(project_run, product)`` scope rule, in one place.

A project can hold many ``project_run`` rows; anything that needs "the run this project is
currently working under" must pick the same one, so the rule lives here and is imported rather
than re-queried. Its one consumer today is the agent-turn fleet wiring.

(This module is what is left of the FI-2 ``committee`` seam. The governed-committee reader that
lived beside it resolved members through the old research lane's ``account_run``/coverage rows and
was deleted with the rest of the FI-2 read surface on 2026-09-09; the ARV2 committee rule is
:func:`clue_api.arv2.display.gather.committee_members`.)
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.frontend_read.accounts_list import WireModel
from clue_core import ProjectRunId


class ProjectRunContext(WireModel):
    """The ``(project_run, product)`` pair a project's governed reads run under."""

    project_run_id: ProjectRunId
    product_id: str | None = None


_LATEST_PROJECT_RUN = text(
    """
    SELECT id, product_id
    FROM project_run
    WHERE workspace_id = :workspace_id AND project_id = :project_id
    ORDER BY created_at DESC, id DESC
    LIMIT 1
    """
)


async def latest_project_run_context(
    conn: AsyncConnection, *, workspace_id: str, project_id: str
) -> ProjectRunContext | None:
    """Return the latest run's governed ``(project_run, product)`` scope for a project.

    ``None`` means the project has never started a run. This is the only implementation of the
    latest-run-wins rule; every consumer imports it rather than ordering ``project_run`` itself.
    """
    row = (
        await conn.execute(
            _LATEST_PROJECT_RUN, {"workspace_id": workspace_id, "project_id": project_id}
        )
    ).first()
    if row is None:
        return None
    return ProjectRunContext(project_run_id=ProjectRunId(row[0]), product_id=row[1])


__all__ = ["ProjectRunContext", "latest_project_run_context"]
