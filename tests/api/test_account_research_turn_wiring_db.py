"""The account-research turn opens on the same file card the chat does (F3 Phase 2, WS-28).

A research run is an agent turn over its own thread workspace, and its rough work expires on the
same schedule. Driving a whole research turn needs the model plane, the recipe chain, the
coverage engine and a live account run, so what is proven here is the composition itself: the
runner persists the card and hands it to its turn as an L3 project-context artifact named
``workspace_files``, against the real artifact store and the real database.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest

from clue_agents import AgentExecutionStatus, AgentResourceRef, ResourceKind
from clue_agents.workspace_snapshot import Receipt, SnapshotEntry, SnapshotManifest, tier_for
from clue_api.account_research_turn_wiring import PreparedAccountResearchTurnRunner
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_core import AccountStatus, RunId
from clue_research.durable import ResearchPlan
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


class _ScopedRunner(PreparedAccountResearchTurnRunner):
    """The production runner with its two database-scope reads answered from the test.

    Everything from the lease onwards — the card, the tuple, the constitution, the request — is
    the real code path. ``_load_scope`` would otherwise need a live project run and account run,
    and ``_drive_execution`` the recipe executor; neither has anything to do with WS-28.
    """

    def __init__(self, *, scope: Any, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._scope = scope

    async def _load_scope(self, **_: Any) -> Any:
        return self._scope

    async def _drive_execution(self, execution_id: Any) -> Any:
        return None


class _RecordingTurns:
    """The turn journal, capturing the request and short-circuiting the rest of ``run``."""

    def __init__(self) -> None:
        self.request: Any = None

    async def create(self, *, request: Any, profile: Any) -> None:
        del profile
        self.request = request

    async def load_committed_outcome(self, *, turn_id: Any, workspace_id: str) -> Any:
        del turn_id, workspace_id
        # Not COMPLETED, so ``run`` returns it without touching the model plane.
        return SimpleNamespace(status=AgentExecutionStatus.FAILED)


def test_a_research_turn_hands_the_card_to_its_constitution(tmp_path: Path) -> None:
    """``run`` puts the card in the constitution it builds — proven by driving ``run``.

    This was an ``inspect.getsource`` string match, which would have passed with the call in a
    dead branch, the tuple discarded or the card built from the wrong file list (review I8).
    WS-28 names two delivery paths and this is the second one, so a regression that drops the
    card from research runs must fail here.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            workspace_id = f"ws28w-{uuid4().hex[:8]}"
            project = await seed_project(conn, workspace_id, name="WS28 wiring project")
            account_entity_id = await insert_account_entity(
                conn,
                canonical_name="Wiring account",
                primary_domain="wiring.example",
                status=AccountStatus.ACTIVE,
                workspace_id=workspace_id,
            )
            factory = conn_session_factory(conn)
            artifacts = DurableAgentArtifactStore(
                storage=FsStorage(tmp_path / "artifacts"), conn_factory=factory
            )
            manifest = SnapshotManifest(
                entries=(
                    SnapshotEntry(
                        path="outputs/findings.md",
                        sha256="b" * 64,
                        size=11,
                        media_type="text/markdown",
                        tier=tier_for("outputs/findings.md"),
                        written_at=NOW - timedelta(hours=2),
                    ),
                    SnapshotEntry(
                        path="reads/op-9.json",
                        sha256="c" * 64,
                        size=40,
                        media_type="application/json",
                        tier=tier_for("reads/op-9.json"),
                        written_at=NOW - timedelta(days=4),
                        receipt=Receipt(
                            source="run_crm_action", operation_id="op-9", read_again="Call it."
                        ),
                        expired_at=NOW - timedelta(days=2),
                    ),
                )
            )
            lease = SimpleNamespace(
                snapshot_base=SimpleNamespace(manifest=manifest),
                identity=SimpleNamespace(workspace_root_id="root-ws28"),
            )
            turns = _RecordingTurns()
            account_run_id = RunId(uuid4())
            runner = _ScopedRunner(
                scope=(
                    SimpleNamespace(budget_cap_cents=None),
                    SimpleNamespace(
                        research_directive=None,
                        status=SimpleNamespace(value="running"),
                        started_at=NOW,
                    ),
                    object(),
                    project,
                ),
                settings=cast(Any, SimpleNamespace(agent_account_plan_budget_limit_millicents=10)),
                runtime=cast(Any, None),
                profiles=cast(Any, _StubProfiles()),
                workspaces=cast(Any, _StubWorkspaces(lease)),
                artifacts=artifacts,
                turns=cast(Any, turns),
                history=cast(Any, None),
                contexts=cast(Any, None),
                tools=cast(Any, None),
                tool_invoker=cast(Any, None),
                executor=cast(Any, None),
                compatibility=cast(Any, None),
                plans=cast(Any, None),
                recipes=cast(Any, _StubRecipes()),
                starter=cast(Any, _StubStarter()),
                parameters=cast(Any, _StubParameters()),
                conn_factory=factory,
            )

            await runner.run(
                workspace_id=workspace_id,
                project_run_id=cast(Any, uuid4()),
                account_entity_id=account_entity_id,
                account_run_id=account_run_id,
                tier="tier_1",
                plan=ResearchPlan(tier="tier_1"),
                budget_cap_cents=None,
                completion_guard=cast(Any, None),
            )

            assert turns.request is not None
            cards = {
                item.name: item for item in turns.request.constitution.project_context_artifacts
            }
            assert "workspace_files" in cards, "the research turn's constitution has no file card"
            body = json.loads(await artifacts.read(cards["workspace_files"].artifact_ref))
            # Built from the file list THIS lease restored, not from an empty or stale one.
            assert [item["path"] for item in body["live"]] == ["outputs/findings.md"]
            assert [item["path"] for item in body["expired"]] == ["reads/op-9.json"]

    run_async(scenario())


class _StubProfiles:
    def resolve(self, role: Any, *, surface: Any) -> Any:
        del role, surface
        return SimpleNamespace(
            profile=SimpleNamespace(workspace=None),
            profile_ref=AgentResourceRef(
                kind=ResourceKind.PROFILE, name="account-research", version="v1", sha256="a" * 64
            ),
            resource_manifest=SimpleNamespace(
                model_dump=lambda mode="json": {"schema_version": "1"},
                aggregate_sha256="d" * 64,
            ),
        )


class _StubWorkspaces:
    def __init__(self, lease: Any) -> None:
        self._lease = lease

    async def acquire_restored(self, **_: Any) -> Any:
        return self._lease

    async def release_saved(self, lease: Any) -> None:
        del lease


class _StubRecipes:
    async def get_by_identity(self, **_: Any) -> Any:
        return SimpleNamespace(recipe_revision_id=uuid4())


class _StubParameters:
    async def snapshot(self, *, workspace_id: str, parameters: Any) -> tuple[str, str]:
        del workspace_id, parameters
        return "parameters-key", "e" * 64


class _StubStarter:
    async def start(self, **_: Any) -> None:
        return None
