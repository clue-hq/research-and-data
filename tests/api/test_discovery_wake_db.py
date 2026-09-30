"""A discovery run holds the thread that launched it; its wake turn goes first; Stop is recorded.

Spec ``docs/superpowers/specs/2026-09-30-agent-authored-account-discovery-design.md`` §4 "The
wake" and §5 "Locks": while a discovery run is unreleased, the launching thread is busy — a user
message is accepted but held, not refused. When the run ends the platform queues a derived
Head-of-ABM turn carrying the summary, which runs before any held message; when that turn finishes
the run is released and the queue moves on to the first held message.

DB-backed and rollback-only, per ``tests/api`` conventions: the submitter is a real
``platform_user`` + ``workspace_membership``, the turns are real submissions through the real
route, and the post-terminal path is the real ``AGENT_TURN`` handler's.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from httpx import ASGITransport
from sqlalchemy import text

from clue_agents import AgentExecutionStatus
from clue_api.agent_turn_fleet_wiring import AgentTurnWorkHandler
from clue_api.agent_turn_submission import (
    DERIVATION_DISCOVERY_FINISHED,
    agent_turn_dedup_key,
    dispatch_next_thread_turn,
    get_submission,
    message_artifact_ref,
    thread_work_id,
)
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.arv2.discovery_store import (
    DiscoveryRunRow,
    create_discovery_run,
    end_discovery_run,
    read_discovery_run,
)
from clue_api.chat import CHAT_PERMISSIONS, RequestPrincipal
from clue_api.discovery_wake import DbDiscoveryWake
from clue_api.execution_wiring import build_tool_invoker
from clue_api.projections_app import create_projections_app
from clue_config import Settings, load_settings
from clue_core import ProjectPhase, ProjectRunId
from clue_fleet import FleetTaskKind, FleetTaskStatus, claim_next_task, finish_task
from clue_fleet.work_worker import WorkContext
from clue_projections import threads_running
from clue_research.durable.project_run import ensure_project_run
from clue_spine import Project
from clue_storage import FsStorage
from clue_toolbelt import DbIdempotencyStore, ToolRegistry
from tests._identity import seed_principal
from tests._workspace import seed_project
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)
from tests.projections._helpers import build_surface

USER_ID = "usr_discovery_wake"
MEMBERSHIP_ID = "wsm_discovery_wake"
_AUTHENTICATED_AT = datetime(2026, 9, 30, 9, 0, tzinfo=UTC)


@pytest.fixture
def require_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


pytestmark = pytest.mark.usefixtures("require_db")


class _MemoryStorage:
    """The parameter-snapshot sink the journaled invoker writes through."""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        del media_type
        self.blobs[key] = data

    async def get(self, key: str) -> bytes:
        return self.blobs[key]

    async def delete(self, key: str) -> None:
        self.blobs.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self.blobs

    async def presign(self, key: str, *, expires_in: int = 3600) -> str:
        del expires_in
        return f"memory://{key}"

    async def list_blobs(self) -> Any:
        return
        yield


def _settings() -> Settings:
    return load_settings(_env_file=None, chat_enabled=True)


def _principal(workspace_id: str) -> RequestPrincipal:
    return RequestPrincipal(
        user_id=USER_ID,
        membership_id=f"{MEMBERSHIP_ID}-{workspace_id}",
        workspace_id=workspace_id,
        role_key="owner",
        permissions=CHAT_PERMISSIONS,
        authenticated_at=_AUTHENTICATED_AT,
    )


def _app(conn: Any, *, storage: Any) -> Any:
    from clue_api.thread_wiring import register_thread_tools

    cf = conn_session_factory(conn)
    registry = ToolRegistry()
    register_thread_tools(registry, conn_factory=cf)
    settings = _settings()
    return create_projections_app(
        surface=build_surface(conn),
        tool_invoker=build_tool_invoker(
            registry=registry,
            idempotency_store=DbIdempotencyStore(conn_factory=cf),
            storage=_MemoryStorage(),
            settings=settings,
            conn_factory=cf,
        ),
        settings=settings,
        conn_factory=cf,
        manage_db_lifespan=False,
        ingestion_storage=storage,
        chat_principal_resolver=_principal,
    )


def _client(app: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def _seed(conn: Any, workspace_id: str, *, name: str) -> tuple[Project, str, UUID]:
    """A project with its submitter, one thread, and the project run a discovery hangs off."""

    project = await seed_project(conn, workspace_id, name=name)
    await seed_principal(
        conn,
        workspace_id=workspace_id,
        user_id=USER_ID,
        membership_id=f"{MEMBERSHIP_ID}-{workspace_id}",
    )
    thread_id = f"thr_wake_{workspace_id}"
    await conn.execute(
        text(
            "INSERT INTO agent_thread (id, workspace_id, project_id, created_by_user_id) "
            "VALUES (:id, :workspace, :project, :user)"
        ),
        {
            "id": thread_id,
            "workspace": workspace_id,
            "project": project.project_id,
            "user": USER_ID,
        },
    )
    project_run_id = uuid4()
    await ensure_project_run(
        conn,
        project_run_id=ProjectRunId(project_run_id),
        project_id=project.project_id,
        workspace_id=project.workspace_id,
        icp_key="clue-abm-buyers",
        icp_version=1,
        phase=ProjectPhase.DEEP,
    )
    return project, thread_id, project_run_id


async def _launch(
    conn: Any,
    project: Project,
    *,
    project_run_id: UUID,
    thread_id: str | None,
    launching_turn_id: UUID | None,
) -> DiscoveryRunRow:
    row = DiscoveryRunRow(
        run_id=uuid4(),
        workspace_id=project.workspace_id,
        project_id=project.project_id,
        brand_id=str(project.brand_id),
        project_run_id=project_run_id,
        icp_artifact_key="ws/abc",
        icp_artifact_sha256="b" * 64,
        icp_key="clue-abm-buyers",
        icp_version=1,
        requested_by_user_id=USER_ID,
        request_sha256=uuid4().hex * 2,
        target_count=20,
        relaxed_enabled=False,
        criteria_gate_keys=(),
        launched_thread_id=thread_id,
        launching_turn_id=launching_turn_id,
    )
    assert await create_discovery_run(conn, row)
    return row


async def _submit(client: httpx.AsyncClient, project: Project, thread_id: str, *, key: str) -> UUID:
    response = await client.post(
        f"/api/v1/projects/{project.project_id}/threads/{thread_id}/turns",
        json={"message": f"Message {key}."},
        headers={"X-Workspace-Id": project.workspace_id, "Idempotency-Key": key},
    )
    assert response.status_code == 202, response.text
    return UUID(response.json()["data"]["turn_id"])


async def _tasks(conn: Any, *, workspace_id: str, thread_id: str) -> list[tuple[str, str]]:
    rows = (
        await conn.execute(
            text(
                "SELECT dedup_key, status FROM fleet_task WHERE kind = 'agent_turn' "
                "AND work_id = :work_id ORDER BY enqueue_seq"
            ),
            {"work_id": thread_work_id(workspace_id=workspace_id, thread_id=thread_id)},
        )
    ).all()
    return [(str(row[0]), str(row[1])) for row in rows]


async def _claim(conn: Any, *, workspace_id: str, thread_id: str) -> Any:
    work_id = thread_work_id(workspace_id=workspace_id, thread_id=thread_id)
    claimed = await claim_next_task(
        conn,
        kind=FleetTaskKind.AGENT_TURN,
        worker_id="worker-1",
        project_run_id=ProjectRunId(work_id),
    )
    assert claimed is not None
    return claimed


async def _finish_offered(conn: Any, *, workspace_id: str, thread_id: str) -> UUID:
    """Claim this thread's offered task and finish it DONE, without the handler's dispatch."""

    claimed = await _claim(conn, workspace_id=workspace_id, thread_id=thread_id)
    assert await finish_task(
        conn, task_id=claimed.task_id, worker_id="worker-1", status=FleetTaskStatus.DONE
    )
    return UUID(str(claimed.payload["turn_id"]))


class _ConnWorkQueue:
    """The two ``WorkQueue`` calls the handler makes, over the test's rolled-back connection."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    async def finish(
        self,
        *,
        task_id: UUID,
        worker_id: str,
        status: FleetTaskStatus,
        result_ref: dict[str, Any] | None = None,
    ) -> bool:
        return await finish_task(
            self._conn, task_id=task_id, worker_id=worker_id, status=status, result_ref=result_ref
        )

    async def touch(self, *, task_id: UUID, worker_id: str) -> bool:
        del task_id, worker_id
        return True

    async def requeue(self, *, task_id: UUID, worker_id: str) -> bool:
        del task_id, worker_id
        return True


class _CompletingRunner:
    def __init__(self) -> None:
        self.calls: list[UUID] = []

    async def run(self, *, turn_id: UUID, workspace_id: str) -> Any:
        del workspace_id
        self.calls.append(turn_id)
        return SimpleNamespace(
            outcome=SimpleNamespace(status=AgentExecutionStatus.COMPLETED), replayed=False
        )


async def _handle_offered(conn: Any, *, workspace_id: str, thread_id: str) -> UUID:
    """Claim this thread's offered task and run the real ``AGENT_TURN`` handler over it."""

    claimed = await _claim(conn, workspace_id=workspace_id, thread_id=thread_id)
    runner = _CompletingRunner()
    handler = AgentTurnWorkHandler(
        runner=runner,  # type: ignore[arg-type]
        queue=_ConnWorkQueue(conn),  # type: ignore[arg-type]
        conn_factory=conn_session_factory(conn),
    )
    await handler.handle(
        WorkContext(
            task_id=claimed.task_id,
            work_id=thread_work_id(workspace_id=workspace_id, thread_id=thread_id),
            worker_id="worker-1",
            lease_generation=claimed.attempts,
            payload=claimed.payload,
            stop_requested=asyncio.Event(),
            lease_lost=asyncio.Event(),
        )
    )
    (ran,) = runner.calls
    return ran


def _artifacts(conn: Any, tmp_path: Path) -> DurableAgentArtifactStore:
    return DurableAgentArtifactStore(
        storage=FsStorage(tmp_path / "artifacts"), conn_factory=conn_session_factory(conn)
    )


async def _wake(
    conn: Any, tmp_path: Path, run: DiscoveryRunRow, *, message: str = "Discovery finished."
) -> UUID | None:
    """What the driver does at the end of a threaded run: end it unreleased, then queue the wake."""

    summary = {"asked": 20, "shown": 12}
    await end_discovery_run(
        conn,
        run_id=run.run_id,
        status="completed",
        end_reason="filled",
        summary=summary,
        release=False,
    )
    wake = DbDiscoveryWake(_artifacts(conn, tmp_path))
    async with conn.begin_nested():
        return await wake.queue(conn, run, summary, message)


# --- the hold -------------------------------------------------------------------------------------


def test_user_turns_are_held_while_a_discovery_is_unreleased(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project, thread_id, project_run_id = await _seed(conn, "ws-wake-hold", name="Hold")
            async with _client(_app(conn, storage=FsStorage(tmp_path / "artifacts"))) as client:
                launching = await _submit(client, project, thread_id, key="launch")
                await _finish_offered(conn, workspace_id=project.workspace_id, thread_id=thread_id)
                await _launch(
                    conn,
                    project,
                    project_run_id=project_run_id,
                    thread_id=thread_id,
                    launching_turn_id=launching,
                )
                # Accepted — the route answers 202 — but not offered to the fleet.
                await _submit(client, project, thread_id, key="held-1")
            assert (
                await dispatch_next_thread_turn(
                    conn, workspace_id=project.workspace_id, thread_id=thread_id
                )
                is None
            )
            assert await _tasks(conn, workspace_id=project.workspace_id, thread_id=thread_id) == [
                (agent_turn_dedup_key(launching), FleetTaskStatus.DONE.value)
            ]

    run_async(scenario())


# --- the wake -------------------------------------------------------------------------------------


def test_the_wake_is_a_derived_turn_that_goes_first(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project, thread_id, project_run_id = await _seed(conn, "ws-wake-first", name="First")
            async with _client(_app(conn, storage=FsStorage(tmp_path / "artifacts"))) as client:
                launching = await _submit(client, project, thread_id, key="launch")
                await _finish_offered(conn, workspace_id=project.workspace_id, thread_id=thread_id)
                run = await _launch(
                    conn,
                    project,
                    project_run_id=project_run_id,
                    thread_id=thread_id,
                    launching_turn_id=launching,
                )
                held_1 = await _submit(client, project, thread_id, key="held-1")
                held_2 = await _submit(client, project, thread_id, key="held-2")

            wake_turn = await _wake(conn, tmp_path, run, message="Discovery finished: 12 shown.")
            assert wake_turn is not None
            assert wake_turn not in (held_1, held_2)

            submission = await get_submission(
                conn, workspace_id=project.workspace_id, turn_id=wake_turn
            )
            assert submission is not None
            assert submission.derivation == DERIVATION_DISCOVERY_FINISHED
            assert submission.derived_from_turn_id == launching
            assert submission.thread_id == thread_id
            assert submission.submitted_by_user_id == USER_ID
            # The wake, not the earlier user messages, is what the fleet was offered.
            assert await _tasks(conn, workspace_id=project.workspace_id, thread_id=thread_id) == [
                (agent_turn_dedup_key(launching), FleetTaskStatus.DONE.value),
                (agent_turn_dedup_key(wake_turn), FleetTaskStatus.QUEUED.value),
            ]
            stored = await read_discovery_run(conn, run_id=run.run_id)
            assert stored is not None and stored.wake_turn_id == wake_turn
            assert stored.released_at is None

            # The message the Head of ABM reads is the summary the driver wrote.
            ref = await message_artifact_ref(conn, submission)
            assert await _artifacts(conn, tmp_path).read(ref) == b"Discovery finished: 12 shown."

            # A second end of the same run (a replay) lands on the same wake turn.
            again = await _wake(conn, tmp_path, run, message="Discovery finished: 12 shown.")
            assert again == wake_turn

    run_async(scenario())


def test_a_run_with_no_launching_turn_queues_no_wake(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project, thread_id, project_run_id = await _seed(conn, "ws-wake-none", name="None")
            run = await _launch(
                conn,
                project,
                project_run_id=project_run_id,
                thread_id=thread_id,
                launching_turn_id=uuid4(),  # names no submission
            )
            assert await _wake(conn, tmp_path, run) is None
            assert await _tasks(conn, workspace_id=project.workspace_id, thread_id=thread_id) == []

    run_async(scenario())


def test_finishing_the_wake_turn_releases_the_run_then_the_queue_moves(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project, thread_id, project_run_id = await _seed(conn, "ws-wake-release", name="Rel")
            async with _client(_app(conn, storage=FsStorage(tmp_path / "artifacts"))) as client:
                launching = await _submit(client, project, thread_id, key="launch")
                await _finish_offered(conn, workspace_id=project.workspace_id, thread_id=thread_id)
                run = await _launch(
                    conn,
                    project,
                    project_run_id=project_run_id,
                    thread_id=thread_id,
                    launching_turn_id=launching,
                )
                held_1 = await _submit(client, project, thread_id, key="held-1")
                await _submit(client, project, thread_id, key="held-2")
            wake_turn = await _wake(conn, tmp_path, run)
            assert wake_turn is not None

            # The real AGENT_TURN handler runs the wake turn and takes its post-terminal path.
            ran = await _handle_offered(
                conn, workspace_id=project.workspace_id, thread_id=thread_id
            )
            assert ran == wake_turn
            stored = await read_discovery_run(conn, run_id=run.run_id)
            assert stored is not None and stored.released_at is not None
            # Released, the thread moves on to the first held message.
            assert await _tasks(conn, workspace_id=project.workspace_id, thread_id=thread_id) == [
                (agent_turn_dedup_key(launching), FleetTaskStatus.DONE.value),
                (agent_turn_dedup_key(wake_turn), FleetTaskStatus.DONE.value),
                (agent_turn_dedup_key(held_1), FleetTaskStatus.QUEUED.value),
            ]

    run_async(scenario())


def test_a_wake_queued_while_the_launching_turn_runs_follows_it(tmp_path: Path) -> None:
    """A run can end before the turn that launched it has: the wake waits, then goes next."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project, thread_id, project_run_id = await _seed(conn, "ws-wake-inflight", name="Fly")
            async with _client(_app(conn, storage=FsStorage(tmp_path / "artifacts"))) as client:
                launching = await _submit(client, project, thread_id, key="launch")
                run = await _launch(
                    conn,
                    project,
                    project_run_id=project_run_id,
                    thread_id=thread_id,
                    launching_turn_id=launching,
                )
                held = await _submit(client, project, thread_id, key="held-1")
            wake_turn = await _wake(conn, tmp_path, run)
            assert wake_turn is not None
            # The launching turn is still offered/running, so nothing else was.
            assert await _tasks(conn, workspace_id=project.workspace_id, thread_id=thread_id) == [
                (agent_turn_dedup_key(launching), FleetTaskStatus.QUEUED.value)
            ]
            # Finishing the launching turn releases nothing (it is not the wake) and offers the
            # wake, ahead of the held message.
            assert (
                await _handle_offered(conn, workspace_id=project.workspace_id, thread_id=thread_id)
                == launching
            )
            stored = await read_discovery_run(conn, run_id=run.run_id)
            assert stored is not None and stored.released_at is None
            assert await _tasks(conn, workspace_id=project.workspace_id, thread_id=thread_id) == [
                (agent_turn_dedup_key(launching), FleetTaskStatus.DONE.value),
                (agent_turn_dedup_key(wake_turn), FleetTaskStatus.QUEUED.value),
            ]
            assert (
                await _handle_offered(conn, workspace_id=project.workspace_id, thread_id=thread_id)
                == wake_turn
            )
            assert (await _tasks(conn, workspace_id=project.workspace_id, thread_id=thread_id))[
                -1
            ] == (agent_turn_dedup_key(held), FleetTaskStatus.QUEUED.value)

    run_async(scenario())


@pytest.mark.parametrize("wake_status", [FleetTaskStatus.DONE, FleetTaskStatus.FAILED])
def test_dispatch_repairs_a_release_the_wake_handler_never_made(
    tmp_path: Path, wake_status: FleetTaskStatus
) -> None:
    """The wake's task finished but its handler never released the run (a crash in between):
    the next dispatch releases it and offers the held message, instead of holding forever."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            workspace = f"ws-wake-repair-{wake_status.value}"
            project, thread_id, project_run_id = await _seed(conn, workspace, name="Repair")
            async with _client(_app(conn, storage=FsStorage(tmp_path / "artifacts"))) as client:
                launching = await _submit(client, project, thread_id, key="launch")
                await _finish_offered(conn, workspace_id=project.workspace_id, thread_id=thread_id)
                run = await _launch(
                    conn,
                    project,
                    project_run_id=project_run_id,
                    thread_id=thread_id,
                    launching_turn_id=launching,
                )
                held = await _submit(client, project, thread_id, key="held-1")
            wake_turn = await _wake(conn, tmp_path, run)
            assert wake_turn is not None
            # The wake's task reaches its terminal state without the handler's post-terminal path.
            claimed = await _claim(conn, workspace_id=project.workspace_id, thread_id=thread_id)
            assert UUID(str(claimed.payload["turn_id"])) == wake_turn
            assert await finish_task(
                conn, task_id=claimed.task_id, worker_id="worker-1", status=wake_status
            )
            stored = await read_discovery_run(conn, run_id=run.run_id)
            assert stored is not None and stored.released_at is None

            offered = await dispatch_next_thread_turn(
                conn, workspace_id=project.workspace_id, thread_id=thread_id
            )
            assert offered == held
            stored = await read_discovery_run(conn, run_id=run.run_id)
            assert stored is not None and stored.released_at is not None
            assert await _tasks(conn, workspace_id=project.workspace_id, thread_id=thread_id) == [
                (agent_turn_dedup_key(launching), FleetTaskStatus.DONE.value),
                (agent_turn_dedup_key(wake_turn), wake_status.value),
                (agent_turn_dedup_key(held), FleetTaskStatus.QUEUED.value),
            ]

    run_async(scenario())


# --- the running badge ----------------------------------------------------------------------------


def test_a_running_discovery_marks_its_thread_running(tmp_path: Path) -> None:
    del tmp_path

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project, thread_id, project_run_id = await _seed(conn, "ws-wake-badge", name="Badge")
            cf = conn_session_factory(conn)
            assert (
                await threads_running(
                    workspace_id=project.workspace_id, thread_ids=[thread_id], conn_factory=cf
                )
                == frozenset()
            )
            run = await _launch(
                conn,
                project,
                project_run_id=project_run_id,
                thread_id=thread_id,
                launching_turn_id=None,
            )
            assert await threads_running(
                workspace_id=project.workspace_id,
                thread_ids=[thread_id, "thr_other"],
                conn_factory=cf,
            ) == frozenset({thread_id})
            await end_discovery_run(
                conn,
                run_id=run.run_id,
                status="completed",
                end_reason="filled",
                summary={},
                release=True,
            )
            assert (
                await threads_running(
                    workspace_id=project.workspace_id, thread_ids=[thread_id], conn_factory=cf
                )
                == frozenset()
            )

    run_async(scenario())


def test_the_thread_list_names_the_discovery_a_thread_is_holding(tmp_path: Path) -> None:
    """The chat thread wire says which discovery holds the thread, and whether Stop still means
    anything: ``stoppable`` while the run searches, not once it has ended and only its wake turn is
    pending, and no ``discovery`` at all once the run is released. The brief never rides it."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project, thread_id, project_run_id = await _seed(conn, "ws-wake-wire", name="Wire")
            headers = {"X-Workspace-Id": project.workspace_id}
            path = f"/api/v1/projects/{project.project_id}/threads"
            async with _client(_app(conn, storage=FsStorage(tmp_path / "artifacts"))) as client:

                async def listed() -> dict[str, Any]:
                    response = await client.get(path, headers=headers)
                    assert response.status_code == 200, response.text
                    (thread,) = response.json()["data"]
                    assert thread["id"] == thread_id
                    return thread

                assert (await listed())["discovery"] is None

                run = await _launch(
                    conn,
                    project,
                    project_run_id=project_run_id,
                    thread_id=thread_id,
                    launching_turn_id=None,
                )
                searching = await listed()
                assert searching["discovery"] == {"run_id": str(run.run_id), "stoppable": True}
                assert searching["status"] == "running"
                assert "brief" not in str(searching)

                # Ended, its wake turn still pending: the thread is held, but there is nothing
                # left to stop.
                await end_discovery_run(
                    conn,
                    run_id=run.run_id,
                    status="completed",
                    end_reason="filled",
                    summary={},
                    release=False,
                )
                ended = await listed()
                assert ended["discovery"] == {"run_id": str(run.run_id), "stoppable": False}

                await conn.execute(
                    text("UPDATE arv2_discovery_run SET released_at = now() WHERE run_id = :r"),
                    {"r": run.run_id},
                )
                assert (await listed())["discovery"] is None

    run_async(scenario())


# --- Stop -----------------------------------------------------------------------------------------


def test_stop_route_marks_the_run(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project, thread_id, project_run_id = await _seed(conn, "ws-wake-stop", name="Stop")
            other = await seed_project(conn, project.workspace_id, name="Other")
            run = await _launch(
                conn,
                project,
                project_run_id=project_run_id,
                thread_id=thread_id,
                launching_turn_id=None,
            )
            headers = {"X-Workspace-Id": project.workspace_id}
            async with _client(_app(conn, storage=FsStorage(tmp_path / "artifacts"))) as client:
                stopped = await client.post(
                    f"/api/v1/projects/{project.project_id}/discovery-runs/{run.run_id}/stop",
                    headers=headers,
                )
                assert stopped.status_code == 200, stopped.text
                assert stopped.json()["data"] == {
                    "run_id": str(run.run_id),
                    "stop_requested": True,
                }
                stored = await read_discovery_run(conn, run_id=run.run_id)
                assert stored is not None and stored.stop_requested_at is not None

                # Another project's path does not reach this run, and neither does a made-up id.
                for project_id, run_id in (
                    (other.project_id, run.run_id),
                    (project.project_id, uuid4()),
                ):
                    missing = await client.post(
                        f"/api/v1/projects/{project_id}/discovery-runs/{run_id}/stop",
                        headers=headers,
                    )
                    assert missing.status_code == 404, missing.text
                    assert missing.json()["error"]["code"] == "DISCOVERY_RUN_NOT_FOUND"

    run_async(scenario())
