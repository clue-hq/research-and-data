"""Head-of-ABM continuation: which saved turn a new turn resumes, and what was said since."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.conversation_continuation import (
    continuation_config_for,
    find_resume_point,
    gap_history,
)
from clue_api.thread_store import create_thread, new_thread_id
from tests._workspace import seed_project
from tests.db.conftest import run_async
from tests.profiling.conftest import rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

_T0 = datetime(2026, 9, 29, 10, 0, tzinfo=UTC)
_PROFILE = {
    "profile_name": "head-of-abm",
    "profile_version": "v69",
    "profile_sha256": "a" * 64,
    "resource_manifest_sha256": "b" * 64,
}


async def _artifact(conn: AsyncConnection, workspace_id: str, sha: str) -> str:
    key = f"{workspace_id}/{sha}"
    await conn.execute(
        text(
            "INSERT INTO artifact (storage_key, workspace_id, content_sha256, media_type, "
            "size_bytes) VALUES (:key, :ws, :sha, 'text/plain', 11) "
            "ON CONFLICT (storage_key) DO NOTHING"
        ),
        {"key": key, "ws": workspace_id, "sha": sha},
    )
    return key


async def _turn(
    conn: AsyncConnection,
    project: object,
    thread_id: str,
    *,
    minutes: int,
    status: str = "completed",
    role: str = "head_of_abm",
    profile_version: str = "v69",
) -> tuple[UUID, UUID]:
    """One ``execution`` + ``agent_turn`` + terminal event; returns (turn id, execution id)."""
    ws, pid = project.workspace_id, project.project_id  # type: ignore[attr-defined]
    turn_id, execution_id = uuid4(), uuid4()
    await conn.execute(
        text(
            "INSERT INTO execution (id, workspace_id, project_id, started_by, "
            "parameter_manifest_hash, pin_manifest_hash) "
            "VALUES (:id, :ws, :p, 'human', :h, :h)"
        ),
        {"id": execution_id, "ws": ws, "p": pid, "h": "0" * 64},
    )
    key = await _artifact(conn, ws, "c" * 64)
    await conn.execute(
        text(
            "INSERT INTO agent_turn (id, execution_id, workspace_id, project_id, thread_id, "
            " actor_id, role, workspace_root_id, profile_name, profile_version, profile_sha256, "
            " resource_manifest_key, resource_manifest_artifact_sha256, resource_manifest_sha256, "
            " retention_class, requested_at) "
            "VALUES (:id, :e, :ws, :p, :t, 'actor-1', :role, 'root-1', 'head-of-abm', :v, :ps, "
            " :key, :cs, :ms, 'standard', :at)"
        ),
        {
            "id": turn_id,
            "e": execution_id,
            "ws": ws,
            "p": pid,
            "t": thread_id,
            "role": role,
            "v": profile_version,
            "ps": _PROFILE["profile_sha256"],
            "key": key,
            "cs": "c" * 64,
            "ms": _PROFILE["resource_manifest_sha256"],
            "at": _T0 + timedelta(minutes=minutes),
        },
    )
    await _event(conn, ws, turn_id, status)
    return turn_id, execution_id


async def _event(conn: AsyncConnection, workspace_id: str, turn_id: UUID, status: str) -> None:
    await conn.execute(
        text(
            "INSERT INTO agent_turn_event (event_id, turn_id, workspace_id, status) "
            "VALUES (:e, :t, :ws, :s)"
        ),
        {"e": uuid4(), "t": turn_id, "ws": workspace_id, "s": status},
    )


async def _message(
    conn: AsyncConnection, project: object, thread_id: str, turn_id: UUID, sequence: int, role: str
) -> None:
    ws = project.workspace_id  # type: ignore[attr-defined]
    sha = f"{sequence:064x}"
    key = await _artifact(conn, ws, sha)
    await conn.execute(
        text(
            "INSERT INTO agent_thread_message (id, workspace_id, thread_id, turn_id, sequence, "
            " role, body_artifact_key, body_sha256, retention_class) "
            "VALUES (:id, :ws, :t, :turn, :seq, :role, :key, :sha, 'standard')"
        ),
        {
            "id": uuid4(),
            "ws": ws,
            "t": thread_id,
            "turn": turn_id,
            "seq": sequence,
            "role": role,
            "key": key,
            "sha": sha,
        },
    )


async def _thread(conn: AsyncConnection, label: str) -> tuple[object, str]:
    project = await seed_project(conn, f"ws-continuation-{label}", name=f"Continuation {label}")
    thread = await create_thread(
        conn,
        thread_id=new_thread_id(),
        workspace_id=project.workspace_id,
        project_id=project.project_id,
    )
    return project, thread.id


def test_a_turn_resumes_the_last_completed_head_turn_and_gets_what_was_said_since() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project, thread_id = await _thread(conn, "gap")
            ws = project.workspace_id  # type: ignore[attr-defined]
            a, ea = await _turn(conn, project, thread_id, minutes=0)
            await _message(conn, project, thread_id, a, 1, "user")
            await _message(conn, project, thread_id, a, 2, "assistant")
            b, _ = await _turn(conn, project, thread_id, minutes=5, status="cancelled")
            await _message(conn, project, thread_id, b, 3, "user")
            await _message(conn, project, thread_id, b, 4, "assistant")
            # A design-leg exchange is the design agent's turn: never a resume point, and (as in a
            # fresh turn's history) its transcript never reaches the Head of ABM — only a
            # journaled exit summary would.
            leg, _ = await _turn(conn, project, thread_id, minutes=7, role="design")
            await _message(conn, project, thread_id, leg, 5, "user")
            await _message(conn, project, thread_id, leg, 6, "assistant")
            current, _ = await _turn(conn, project, thread_id, minutes=9, status="running")
            await _message(conn, project, thread_id, current, 7, "user")

            point = await find_resume_point(
                conn, workspace_id=ws, thread_id=thread_id, current_turn_id=current, **_PROFILE
            )
            assert point is not None
            assert (point.turn_id, point.execution_id, point.last_message_sequence) == (a, ea, 2)
            gap = await gap_history(
                conn,
                workspace_id=ws,
                thread_id=thread_id,
                after_sequence=point.last_message_sequence,
                current_turn_id=current,
            )
            assert [(m.turn_id, m.sequence) for m in gap] == [(b, 3), (b, 4)]
            assert leg not in {m.turn_id for m in gap}
            assert continuation_config_for(point) == {
                "configurable": {"thread_id": str(ea), "checkpoint_ns": ""}
            }

    run_async(scenario())


def test_a_changed_profile_or_no_completed_turn_means_no_resume_point() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project, thread_id = await _thread(conn, "none")
            ws = project.workspace_id  # type: ignore[attr-defined]
            current = uuid4()
            assert (
                await find_resume_point(
                    conn, workspace_id=ws, thread_id=thread_id, current_turn_id=current, **_PROFILE
                )
                is None
            )
            a, _ = await _turn(conn, project, thread_id, minutes=0, profile_version="v68")
            await _message(conn, project, thread_id, a, 1, "user")
            assert (
                await find_resume_point(
                    conn, workspace_id=ws, thread_id=thread_id, current_turn_id=current, **_PROFILE
                )
                is None
            )
            failed, _ = await _turn(conn, project, thread_id, minutes=1, status="failed")
            await _message(conn, project, thread_id, failed, 2, "user")
            erased, _ = await _turn(conn, project, thread_id, minutes=2, status="awaiting_input")
            await _message(conn, project, thread_id, erased, 3, "user")
            await _event(conn, ws, erased, "privacy_tombstoned")
            assert (
                await find_resume_point(
                    conn, workspace_id=ws, thread_id=thread_id, current_turn_id=current, **_PROFILE
                )
                is None
            )


def test_a_turn_that_ended_on_a_question_is_a_resume_point() -> None:
    """Most chat turns end ``awaiting_input``: they finished, and asked the human something."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            project, thread_id = await _thread(conn, "question")
            ws = project.workspace_id  # type: ignore[attr-defined]
            asked, e_asked = await _turn(
                conn, project, thread_id, minutes=0, status="awaiting_input"
            )
            await _message(conn, project, thread_id, asked, 1, "user")
            await _message(conn, project, thread_id, asked, 2, "assistant")
            point = await find_resume_point(
                conn, workspace_id=ws, thread_id=thread_id, current_turn_id=uuid4(), **_PROFILE
            )
            assert point is not None
            assert (point.turn_id, point.execution_id, point.last_message_sequence) == (
                asked,
                e_asked,
                2,
            )

    run_async(scenario())
