"""FI-2 P2 — ``run_lineage``, the claim→project join spine (spec §3).

Every claim carries ``run_id``; this table is the back-join from a run to the project that
produced it, and :func:`project_run_ids` is the project-lens read predicate's input.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from clue_core import new_run_id
from clue_research.claimstore import (
    RUN_LINEAGE_KINDS,
    project_run_ids,
    record_run_lineage,
)

from .conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


def test_recorded_lineage_is_readable_by_project() -> None:
    """A registered run is attributed to its project and readable through the lens predicate."""

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            run_id = new_run_id()
            await record_run_lineage(
                conn,
                run_id=run_id,
                workspace_id="ws-1",
                kind="discovery",
                project_id="proj-1",
            )
            assert await project_run_ids(conn, workspace_id="ws-1", project_id="proj-1") == (
                run_id,
            )

    run_async(_run())


def test_recording_the_same_run_twice_is_a_no_op() -> None:
    """Registration is idempotent (replays are safe): second call neither raises nor duplicates."""

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            run_id = new_run_id()
            for kind in ("discovery", "import"):
                await record_run_lineage(
                    conn,
                    run_id=run_id,
                    workspace_id="ws-1",
                    kind=kind,
                    project_id="proj-1",
                )
            rows = (
                await conn.execute(
                    text("SELECT kind FROM run_lineage WHERE run_id = :run_id"),
                    {"run_id": run_id},
                )
            ).scalars()
            # First write wins — the conflicting replay is dropped, not merged.
            assert list(rows) == ["discovery"]

    run_async(_run())


def test_unknown_kind_raises_before_touching_the_database() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            with pytest.raises(ValueError):
                await record_run_lineage(
                    conn,
                    run_id=new_run_id(),
                    workspace_id="ws-1",
                    kind="teleportation",
                    project_id="proj-1",
                )
            assert await project_run_ids(conn, workspace_id="ws-1", project_id="proj-1") == ()

    run_async(_run())


def test_project_lens_excludes_other_workspaces_and_other_projects() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            mine = new_run_id()
            other_project = new_run_id()
            other_workspace = new_run_id()
            await record_run_lineage(
                conn, run_id=mine, workspace_id="ws-1", kind="scoring", project_id="proj-1"
            )
            await record_run_lineage(
                conn,
                run_id=other_project,
                workspace_id="ws-1",
                kind="scoring",
                project_id="proj-2",
            )
            await record_run_lineage(
                conn,
                run_id=other_workspace,
                workspace_id="ws-2",
                kind="scoring",
                project_id="proj-1",
            )
            assert await project_run_ids(conn, workspace_id="ws-1", project_id="proj-1") == (mine,)

    run_async(_run())


def test_workspace_level_run_belongs_to_no_project() -> None:
    """A NULL-``project_id`` run (stage 0, seeds, client-KB) is in no project's lens."""

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            await record_run_lineage(conn, run_id=new_run_id(), workspace_id="ws-1", kind="stage0")
            project = new_run_id()
            await record_run_lineage(
                conn, run_id=project, workspace_id="ws-1", kind="discovery", project_id="proj-1"
            )
            assert await project_run_ids(conn, workspace_id="ws-1", project_id="proj-1") == (
                project,
            )

    run_async(_run())


def test_every_declared_kind_is_accepted_by_the_check_constraint() -> None:
    """``RUN_LINEAGE_KINDS`` mirrors the DB CHECK — drift on either side fails here."""

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            for kind in RUN_LINEAGE_KINDS:
                await record_run_lineage(
                    conn,
                    run_id=new_run_id(),
                    workspace_id="ws-1",
                    kind=kind,
                    project_id="proj-1",
                )
            assert len(
                await project_run_ids(conn, workspace_id="ws-1", project_id="proj-1")
            ) == len(RUN_LINEAGE_KINDS)

    run_async(_run())
