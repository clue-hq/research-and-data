"""The thread stream: an open chat hears about every turn in its thread (CRM trial 1, F2; R-10.1).

``GET …/threads/{thread_id}/events`` sends the lifecycle frames (``turn.*``) of any turn in the
thread, so a chat follows turns it did not start — a server-queued wake turn, a second tab, a
teammate. The route tests run replay-then-close (``live_tail=False``); the live tail, the
keep-alive and the start-at-the-tail rule are driven through :func:`thread_event_frames`, the
generator the route serves, because an in-process client buffers a whole response body.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.chat.stream import thread_event_frames
from clue_api.chat.turn_events import LIFECYCLE_EVENT_TYPES, list_turn_events
from clue_api.crm.connections import ConnectRequest
from clue_api.crm.wake import queue_crm_connected_turns
from clue_storage import FsStorage
from tests.api.test_lane_d3_turn_stream_db import (
    _app,
    _client,
    _emitter,
    _parse_sse,
    _seed,
    _settings,
    _submit_turn,
    _thread,
)
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)


@pytest.fixture
def require_chat_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


pytestmark = pytest.mark.usefixtures("require_chat_db")


async def _mint_thread_token(
    client: Any, *, workspace_id: str, project_id: str, thread_id: str
) -> str:
    minted = await client.post(
        f"/api/v1/projects/{project_id}/threads/{thread_id}/stream_token",
        headers={"X-Workspace-Id": workspace_id},
    )
    assert minted.status_code == 200, minted.text
    assert minted.json()["data"]["thread_id"] == thread_id
    return str(minted.json()["data"]["stream_token"])


async def _open_thread(
    client: Any,
    *,
    workspace_id: str,
    project_id: str,
    thread_id: str,
    token: str,
    last_event_id: int | None = None,
) -> Any:
    params: dict[str, Any] = {"stream_token": token}
    if last_event_id is not None:
        params["last_event_id"] = last_event_id
    return await client.get(
        f"/api/v1/projects/{project_id}/threads/{thread_id}/events",
        params=params,
        headers={"X-Workspace-Id": workspace_id},
    )


async def _a_turn(conn: Any, *, project: Any, thread_id: str, key: str, storage: Any) -> UUID:
    """One turn's frames the way the worker writes them: accepted, started, text, completed."""

    turn_id = await _submit_turn(
        conn,
        project=project,
        thread_id=thread_id,
        message=key,
        key=key,
        storage=storage,
        dispatch=False,
    )
    emitter = await _emitter(conn, project=project, thread_id=thread_id, turn_id=turn_id)
    await emitter.turn_started()
    await emitter.text_delta(round_ordinal=1, call_index=0, delta="hi")
    await emitter.turn_finished(status="completed")
    return turn_id


async def _tail(conn: Any, *, workspace_id: str, thread_id: str) -> int:
    rows = await list_turn_events(conn, workspace_id=workspace_id, thread_id=thread_id)
    return rows[-1].event_id if rows else 0


def _frame(raw: str) -> tuple[int | None, str, dict[str, Any]]:
    parsed = _parse_sse(raw)
    assert len(parsed) == 1, raw
    return parsed[0]


def test_a_thread_token_opens_only_its_thread(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-thread-stream-auth", name="Thread stream auth")
            ws, pid = project.workspace_id, project.project_id
            thread_a = await _thread(conn, workspace_id=ws, project_id=pid, label="ts-auth-a")
            thread_b = await _thread(conn, workspace_id=ws, project_id=pid, label="ts-auth-b")
            storage = FsStorage(tmp_path / "artifacts")
            turn_id = await _a_turn(
                conn, project=project, thread_id=thread_a, key="k-a", storage=storage
            )
            app = _app(conn, settings=_settings(), storage=storage)
            async with _client(app) as client:
                token = await _mint_thread_token(
                    client, workspace_id=ws, project_id=pid, thread_id=thread_a
                )
                wrong = await _open_thread(
                    client, workspace_id=ws, project_id=pid, thread_id=thread_b, token=token
                )
                assert wrong.status_code == 401

                token = await _mint_thread_token(
                    client, workspace_id=ws, project_id=pid, thread_id=thread_a
                )
                first = await _open_thread(
                    client, workspace_id=ws, project_id=pid, thread_id=thread_a, token=token
                )
                assert first.status_code == 200, first.text
                again = await _open_thread(
                    client, workspace_id=ws, project_id=pid, thread_id=thread_a, token=token
                )
                assert again.status_code == 401

                minted = await client.post(
                    f"/api/v1/projects/{pid}/threads/{thread_a}/turns/{turn_id}/stream_token",
                    headers={"X-Workspace-Id": ws},
                )
                turn_token = minted.json()["data"]["stream_token"]
                borrowed = await _open_thread(
                    client, workspace_id=ws, project_id=pid, thread_id=thread_a, token=turn_token
                )
                assert borrowed.status_code == 401

    run_async(scenario())


def test_only_lifecycle_frames_of_any_turn_in_the_thread_are_sent(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-thread-stream-filter", name="Thread stream filter")
            ws, pid = project.workspace_id, project.project_id
            thread_a = await _thread(conn, workspace_id=ws, project_id=pid, label="ts-filter-a")
            thread_b = await _thread(conn, workspace_id=ws, project_id=pid, label="ts-filter-b")
            storage = FsStorage(tmp_path / "artifacts")
            first = await _a_turn(
                conn, project=project, thread_id=thread_a, key="k-1", storage=storage
            )
            await _a_turn(conn, project=project, thread_id=thread_b, key="k-b", storage=storage)
            second = await _a_turn(
                conn, project=project, thread_id=thread_a, key="k-2", storage=storage
            )

            stored = await list_turn_events(conn, workspace_id=ws, thread_id=thread_a)
            assert any(row.event_type.startswith("text.") for row in stored)
            expected = [
                (row.event_id, row.event_type, str(row.turn_id))
                for row in stored
                if row.event_type.startswith("turn.")
            ]
            assert {turn for *_, turn in expected} == {str(first), str(second)}

            app = _app(conn, settings=_settings(), storage=storage)
            async with _client(app) as client:
                token = await _mint_thread_token(
                    client, workspace_id=ws, project_id=pid, thread_id=thread_a
                )
                response = await _open_thread(
                    client,
                    workspace_id=ws,
                    project_id=pid,
                    thread_id=thread_a,
                    token=token,
                    last_event_id=0,
                )
            frames = _parse_sse(response.text)
            assert frames[0][1] == "stream.hello"
            assert frames[0][2]["thread_id"] == thread_a
            assert "turn_id" not in frames[0][2]
            sent = [(event_id, event, data["turn_id"]) for event_id, event, data in frames[1:]]
            assert sent == expected

    run_async(scenario())


def test_no_cursor_starts_at_the_tail(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-thread-stream-tail", name="Thread stream tail")
            ws, pid = project.workspace_id, project.project_id
            thread_id = await _thread(conn, workspace_id=ws, project_id=pid, label="ts-tail")
            storage = FsStorage(tmp_path / "artifacts")
            await _a_turn(conn, project=project, thread_id=thread_id, key="k-old", storage=storage)

            frames = thread_event_frames(
                conn_factory=conn_session_factory(conn),
                settings=_settings(chat_thread_stream_poll_interval_s=0.01),
                workspace_id=ws,
                project_id=pid,
                thread_id=thread_id,
                cursor=None,
            )
            assert _frame(await anext(frames))[1] == "stream.hello"
            turn_id = await _submit_turn(
                conn,
                project=project,
                thread_id=thread_id,
                message="new",
                key="k-new",
                storage=storage,
                dispatch=False,
            )
            await _emitter(conn, project=project, thread_id=thread_id, turn_id=turn_id)
            event_id, event, data = _frame(await asyncio.wait_for(anext(frames), timeout=2.0))
            assert (event, data["turn_id"]) == ("turn.accepted", str(turn_id))
            assert event_id == await _tail(conn, workspace_id=ws, thread_id=thread_id)
            await frames.aclose()

    run_async(scenario())


def test_a_cursor_older_than_the_horizon_resets(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-thread-stream-reset", name="Thread stream reset")
            ws, pid = project.workspace_id, project.project_id
            thread_id = await _thread(conn, workspace_id=ws, project_id=pid, label="ts-reset")
            storage = FsStorage(tmp_path / "artifacts")
            await _a_turn(conn, project=project, thread_id=thread_id, key="k-r", storage=storage)
            cursor = await _tail(conn, workspace_id=ws, thread_id=thread_id)

            app = _app(conn, settings=_settings(sse_replay_horizon_s=0.0), storage=storage)
            async with _client(app) as client:
                token = await _mint_thread_token(
                    client, workspace_id=ws, project_id=pid, thread_id=thread_id
                )
                response = await _open_thread(
                    client,
                    workspace_id=ws,
                    project_id=pid,
                    thread_id=thread_id,
                    token=token,
                    last_event_id=cursor,
                )
            frames = _parse_sse(response.text)
            assert [event for _, event, _ in frames] == ["stream.hello", "stream.reset"]
            assert frames[1][2] == {
                "schema_version": "1",
                "type": "stream.reset",
                "thread_id": thread_id,
                "project_id": pid,
                "reason": "cursor_older_than_horizon",
                "rehydrate": "transcript",
            }

    run_async(scenario())


def test_an_idle_stream_sends_keepalive_comments(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-thread-stream-idle", name="Thread stream idle")
            ws, pid = project.workspace_id, project.project_id
            thread_id = await _thread(conn, workspace_id=ws, project_id=pid, label="ts-idle")
            frames = thread_event_frames(
                conn_factory=conn_session_factory(conn),
                settings=_settings(
                    chat_thread_stream_poll_interval_s=0.01, chat_thread_stream_keepalive_s=0.05
                ),
                workspace_id=ws,
                project_id=pid,
                thread_id=thread_id,
                cursor=None,
            )
            assert _frame(await anext(frames))[1] == "stream.hello"
            assert await asyncio.wait_for(anext(frames), timeout=2.0) == ": keepalive\n\n"
            await frames.aclose()

    run_async(scenario())


def test_a_server_queued_wake_turn_is_announced(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await _seed(conn, "ws-thread-stream-wake", name="Thread stream wake")
            ws, pid = project.workspace_id, project.project_id
            thread_id = await _thread(conn, workspace_id=ws, project_id=pid, label="ts-wake")
            storage = FsStorage(tmp_path / "artifacts")
            asking = await _a_turn(
                conn, project=project, thread_id=thread_id, key="k-ask", storage=storage
            )
            cursor = await _tail(conn, workspace_id=ws, thread_id=thread_id)
            frames = thread_event_frames(
                conn_factory=conn_session_factory(conn),
                settings=_settings(chat_thread_stream_poll_interval_s=0.01),
                workspace_id=ws,
                project_id=pid,
                thread_id=thread_id,
                cursor=cursor,
            )
            assert _frame(await anext(frames))[1] == "stream.hello"

            request = ConnectRequest(
                request_id=uuid4(),
                workspace_id=ws,
                project_id=pid,
                thread_id=thread_id,
                turn_id=asking,
                requested_by_user_id="usr_d3_test",
                mode="connect",
                status="fulfilled",
                pending_connected_account_id=None,
                pending_provider=None,
            )
            artifacts = DurableAgentArtifactStore(
                storage=storage, conn_factory=conn_session_factory(conn)
            )
            woken = await queue_crm_connected_turns(
                conn, artifacts, requests=[request], provider="hubspot"
            )
            assert len(woken) == 1
            # The worker announces a turn nobody accepted on the route (a derived wake turn).
            await _emitter(conn, project=project, thread_id=thread_id, turn_id=woken[0])

            _, event, data = _frame(await asyncio.wait_for(anext(frames), timeout=2.0))
            assert (event, data["turn_id"]) == ("turn.accepted", str(woken[0]))
            await frames.aclose()

    run_async(scenario())


def test_the_lifecycle_vocabulary_is_the_turn_events() -> None:
    assert (
        frozenset(
            {
                "turn.accepted",
                "turn.started",
                "turn.awaiting_input",
                "turn.completed",
                "turn.failed",
                "turn.cancelled",
                "turn.retrying",
            }
        )
        == LIFECYCLE_EVENT_TYPES
    )
    assert json.dumps(sorted(LIFECYCLE_EVENT_TYPES))
