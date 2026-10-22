"""The account-research turn opens on the same file card the chat does (F3 Phase 2, WS-28).

A research run is an agent turn over its own thread workspace, and its rough work expires on the
same schedule. Driving a whole research turn needs the model plane, the recipe chain, the
coverage engine and a live account run, so what is proven here is the composition itself: the
runner persists the card and hands it to its turn as an L3 project-context artifact named
``workspace_files``, against the real artifact store and the real database.
"""

from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest

from clue_agents.workspace_snapshot import Receipt, SnapshotEntry, SnapshotManifest, tier_for
from clue_api.account_research_turn_wiring import PreparedAccountResearchTurnRunner
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_core import AccountStatus, RunId
from clue_research.identity import insert_account_entity
from clue_storage import FsStorage
from tests._workspace import seed_project
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

NOW = datetime(2026, 10, 23, 9, 0, tzinfo=UTC)


def _runner(*, artifacts: DurableAgentArtifactStore, conn_factory: Any) -> Any:
    """The production runner with only the two collaborators this composition touches."""

    unused = cast(Any, None)
    return PreparedAccountResearchTurnRunner(
        settings=unused,
        runtime=unused,
        profiles=unused,
        workspaces=unused,
        artifacts=artifacts,
        turns=unused,
        history=unused,
        contexts=unused,
        tools=unused,
        tool_invoker=unused,
        executor=unused,
        compatibility=unused,
        plans=unused,
        recipes=unused,
        starter=unused,
        parameters=unused,
        conn_factory=conn_factory,
    )


def test_a_research_turn_materializes_the_card(tmp_path: Path) -> None:
    """The card is persisted and constituted under the research thread's own domain ref."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            workspace_id = f"ws28r-{uuid4().hex[:8]}"
            project = await seed_project(conn, workspace_id, name="WS28 research project")
            account_entity_id = await insert_account_entity(
                conn,
                canonical_name="Card account",
                primary_domain="card.example",
                status=AccountStatus.ACTIVE,
                workspace_id=workspace_id,
            )
            factory = conn_session_factory(conn)
            artifacts = DurableAgentArtifactStore(
                storage=FsStorage(tmp_path / "artifacts"),
                conn_factory=factory,
            )
            runner = _runner(artifacts=artifacts, conn_factory=factory)
            account_run_id = RunId(uuid4())
            manifest = SnapshotManifest(
                entries=(
                    SnapshotEntry(
                        path="outputs/findings.md",
                        sha256="b" * 64,
                        size=11,
                        media_type="text/markdown",
                        tier=tier_for("outputs/findings.md"),
                        written_at=NOW - timedelta(hours=5),
                    ),
                    SnapshotEntry(
                        path="reads/op-9.json",
                        sha256="c" * 64,
                        size=40,
                        media_type="application/json",
                        tier=tier_for("reads/op-9.json"),
                        written_at=NOW - timedelta(days=4),
                        receipt=Receipt(source="tool", operation_id="op-9", read_again="Call it."),
                        expired_at=NOW - timedelta(days=2),
                    ),
                )
            )

            artifact = await runner._workspace_files_context_artifact(
                workspace_id=workspace_id,
                project_id=project.project_id,
                account_entity_id=account_entity_id,
                account_run_id=account_run_id,
                manifest=manifest,
                now=NOW,
            )

            assert artifact.name == "workspace_files"
            assert artifact.domain_ref.object_type == "thread"
            assert artifact.domain_ref.object_id == f"account-research-{account_run_id}"
            assert artifact.domain_ref.workspace_id == workspace_id
            assert artifact.artifact_ref.workspace_id == workspace_id
            body = json.loads(await artifacts.read(artifact.artifact_ref))
            assert [item["path"] for item in body["live"]] == ["outputs/findings.md"]
            assert body["live"][0]["age_hours"] == 5
            assert body["expired"][0]["path"] == "reads/op-9.json"
            assert body["expired"][0]["receipt"]["operation_id"] == "op-9"
            # Task 8 fills the founder-approved sentence; the key is in the contract already.
            assert "note" in body

    run_async(scenario())


def test_a_research_turn_hands_the_card_to_its_constitution() -> None:
    """The composition above is wired into ``run``, not only available to it.

    ``run`` needs a live account run, the coverage engine and the model plane, so it is not
    driven here. What is checked is that the one tuple the constitution is built from gains the
    card right where the lease's restored file list becomes available.
    """

    source = inspect.getsource(PreparedAccountResearchTurnRunner.run)
    assert "_workspace_files_context_artifact(" in source
    assert "project_context_artifacts = (" in source
    assert "lease.snapshot_base" in source
