"""P3.7 delta 8 — the leg lifecycle rides the chat turn stream.

PD-part3 §3-8 (amended: ``closing`` dropped — the close is one atomic journal+flip —
``reopened`` added, the §2.2 mis-exit re-delegation being a real durable transition). Every
frame is emitted in the SAME transaction as the durable leg transition it announces, so a
consumer can never see a frame without its row or a row without its frame surviving a crash:

* ``leg.opened`` on the delegating head-of-abm turn (the ``open_design_leg`` invocation);
* ``leg.awaiting_user`` on each design turn as the leg returns to the user;
* ``leg.closed`` (payload carries the exit ``reason``) on the closing turn;
* ``leg.reopened`` on the re-delegating turn (``open_design_leg`` with ``reopen_leg_id``).

Replays emit nothing: a frame announces a transition, and a replayed invocation performs
none.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.agent_registry_wiring import build_agent_profile_registry
from clue_api.chat.turn_events import list_turn_events
from clue_api.design_leg_tools import FinishDesignLegTool, OpenDesignLegTool
from clue_api.toolbelt_wiring import build_toolbelt
from clue_api.turn_action import derive_turn_action_ref
from clue_core import new_operation_id
from clue_design import legs as design_legs
from clue_toolbelt import ToolContext, ToolRegistry, invoke_tool
from tests.api.conftest import hermetic_flag_env
from tests.api.test_genweb_leg_document_birth_db import engine_web_doc
from tests.api.test_p34_design_leg_engine_db import (
    _FakeLane,
    _run_turn,
    _seed_leg_conversation,
    _submit_message,
)
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)


async def _leg_frames(conn: AsyncConnection, workspace_id: str) -> list[tuple[str, Any]]:
    """Every leg frame in this workspace, in stream order, as (type, payload)."""

    events = await list_turn_events(conn, workspace_id=workspace_id)
    return [(e.event_type, e.payload) for e in events if e.event_type.startswith("leg.")]


async def _seed_delegating_turn(conn: AsyncConnection, seeds: dict[str, Any], label: str) -> Any:
    """A durable head-of-abm turn to anchor the tool's TRUSTED source_turn_ref."""

    submission = await _submit_message(conn, seeds, label=label, message="Design something.")
    manifest = await seeds["artifacts"].persist_body(
        workspace_id=seeds["workspace_id"],
        data=json.dumps({"resources": []}).encode(),
        media_type="application/json",
    )
    execution_id = uuid5(NAMESPACE_URL, f"p37:{label}:execution")
    await conn.execute(
        text(
            "INSERT INTO execution "
            "(id, workspace_id, project_id, started_by, parameter_manifest_hash, "
            " pin_manifest_hash) VALUES (:id, :ws, :project, 'human', :hash, :hash)"
        ),
        {
            "id": execution_id,
            "ws": seeds["workspace_id"],
            "project": seeds["project"].project_id,
            "hash": "0" * 64,
        },
    )
    await conn.execute(
        text(
            "INSERT INTO agent_turn "
            "(id, execution_id, workspace_id, project_id, thread_id, actor_id, role, "
            " workspace_root_id, profile_name, profile_version, profile_sha256, "
            " resource_manifest_key, resource_manifest_artifact_sha256, "
            " resource_manifest_sha256, retention_class, requested_at) "
            "VALUES (:id, :execution, :ws, :project, :thread, 'usr_p34_engine', "
            " 'head_of_abm', 'root-p37', 'head-of-abm', 'v24', :sha, :key, :sha256, "
            " :sha256, 'test', now())"
        ),
        {
            "id": submission.turn_id,
            "execution": execution_id,
            "ws": seeds["workspace_id"],
            "project": seeds["project"].project_id,
            "thread": seeds["thread_id"],
            "sha": "0" * 64,
            "key": manifest.artifact_key,
            "sha256": manifest.sha256,
        },
    )
    return submission


def _context(seeds: dict[str, Any]) -> ToolContext:
    return ToolContext(
        workspace_id=seeds["workspace_id"],
        actor="agent",
        conn_factory=seeds["conn_factory"],
        operation_id=new_operation_id(),
    )


def test_the_leg_lifecycle_lands_on_the_turn_stream_end_to_end(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """One full leg journey — open → design turn → close → reopen — leaves exactly the four
    lifecycle frames, each on the turn that performed the transition, reason included."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="stream")
            # The seeded leg is opened directly at the DAL (no tool) — close it out of the
            # way so the tool-driven journey below owns the thread's lifecycle.
            await design_legs.close_leg(
                conn,
                workspace_id=seeds["workspace_id"],
                leg_id=seeds["leg"]["id"],
                reason="abandoned",
                summary_refs={},
            )
            cf = seeds["conn_factory"]
            with hermetic_flag_env():
                registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            tools = ToolRegistry()
            tools.register(
                OpenDesignLegTool(
                    conn_factory=cf,
                    storage=seeds["storage"],
                    # @2: a document-less open births its web document — these are
                    # lifecycle-frame tests, so the engine round-trip is the recorded one.
                    web_document_minter=engine_web_doc,
                ),
                make_default=True,
            )
            tools.register(
                FinishDesignLegTool(conn_factory=cf, storage=seeds["storage"]), make_default=True
            )

            # 1. open, from a durable delegating turn.
            delegating = await _seed_delegating_turn(conn, seeds, "stream-open")
            opened = await invoke_tool(
                tools,
                "open_design_leg",
                {
                    "source_turn_ref": derive_turn_action_ref(delegating.turn_id),
                    "brief": "A streamed artboard.",
                    "doc_kind": "web",
                    "artifacts": [{"title": "A streamed artboard"}],
                },
                _context(seeds),
                idempotency_ttl_s=60,
            )
            leg_id = opened.references["leg_id"]
            frames = await _leg_frames(conn, seeds["workspace_id"])
            assert frames == [("leg.opened", {"leg_id": leg_id})]

            # 2. a design turn returns the leg to the user.
            design_submission = await _submit_message(
                conn, seeds, label="stream-design", message="Bolder."
            )
            await _run_turn(conn, seeds, registry, _FakeLane(conn_factory=cf), design_submission)
            frames = await _leg_frames(conn, seeds["workspace_id"])
            assert frames[-1] == ("leg.awaiting_user", {"leg_id": leg_id})
            awaiting = [f for f in frames if f[0] == "leg.awaiting_user"]
            assert len(awaiting) == 1

            # 3. the exit, reason on the frame.
            await invoke_tool(
                tools,
                "finish_design_leg",
                {
                    "source_turn_ref": derive_turn_action_ref(design_submission.turn_id),
                    "reason": "locked",
                    "summary": "Locked the streamed artboard.",
                },
                _context(seeds),
                idempotency_ttl_s=60,
            )
            frames = await _leg_frames(conn, seeds["workspace_id"])
            assert frames[-1] == ("leg.closed", {"leg_id": leg_id, "reason": "locked"})

            # 4. the mis-exit reopen, from a new delegating turn.
            redelegating = await _seed_delegating_turn(conn, seeds, "stream-reopen")
            await invoke_tool(
                tools,
                "open_design_leg",
                {
                    "source_turn_ref": derive_turn_action_ref(redelegating.turn_id),
                    "brief": "Back to the artboard.",
                    "reopen_leg_id": leg_id,
                },
                _context(seeds),
                idempotency_ttl_s=60,
            )
            frames = await _leg_frames(conn, seeds["workspace_id"])
            assert [f[0] for f in frames] == [
                "leg.opened",
                "leg.awaiting_user",
                "leg.closed",
                "leg.reopened",
            ]
            assert frames[-1][1] == {"leg_id": leg_id}

            # Each frame sits on the turn that performed its transition.
            events = await list_turn_events(conn, workspace_id=seeds["workspace_id"])
            by_type = {e.event_type: e for e in events if e.event_type.startswith("leg.")}
            assert by_type["leg.opened"].turn_id == delegating.turn_id
            assert by_type["leg.awaiting_user"].turn_id == design_submission.turn_id
            assert by_type["leg.closed"].turn_id == design_submission.turn_id
            assert by_type["leg.reopened"].turn_id == redelegating.turn_id

    run_async(scenario())


def test_replayed_invocations_announce_no_second_transition(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """A retried open re-lands on the same leg and a retried close on the same journal row —
    neither performed a transition, so neither may add a frame."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="replaystream")
            await design_legs.close_leg(
                conn,
                workspace_id=seeds["workspace_id"],
                leg_id=seeds["leg"]["id"],
                reason="abandoned",
                summary_refs={},
            )
            cf = seeds["conn_factory"]
            tools = ToolRegistry()
            tools.register(
                OpenDesignLegTool(
                    conn_factory=cf,
                    storage=seeds["storage"],
                    # @2: a document-less open births its web document — these are
                    # lifecycle-frame tests, so the engine round-trip is the recorded one.
                    web_document_minter=engine_web_doc,
                ),
                make_default=True,
            )
            tools.register(
                FinishDesignLegTool(conn_factory=cf, storage=seeds["storage"]), make_default=True
            )
            delegating = await _seed_delegating_turn(conn, seeds, "replaystream-open")
            open_args = {
                "source_turn_ref": derive_turn_action_ref(delegating.turn_id),
                "brief": "Once only.",
                "doc_kind": "web",
                "artifacts": [{"title": "Once only"}],
            }
            await invoke_tool(
                tools, "open_design_leg", open_args, _context(seeds), idempotency_ttl_s=60
            )
            await invoke_tool(
                tools, "open_design_leg", open_args, _context(seeds), idempotency_ttl_s=60
            )
            frames = await _leg_frames(conn, seeds["workspace_id"])
            assert [f[0] for f in frames] == ["leg.opened"]

            # The exit must come from a design turn on the leg — run one.
            with hermetic_flag_env():
                registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            design_submission = await _submit_message(
                conn, seeds, label="replaystream-design", message="Bolder."
            )
            await _run_turn(conn, seeds, registry, _FakeLane(conn_factory=cf), design_submission)
            finish_args = {
                "source_turn_ref": derive_turn_action_ref(design_submission.turn_id),
                "reason": "abandoned",
                "summary": "Dropping it.",
            }
            await invoke_tool(
                tools, "finish_design_leg", finish_args, _context(seeds), idempotency_ttl_s=60
            )
            await invoke_tool(
                tools, "finish_design_leg", finish_args, _context(seeds), idempotency_ttl_s=60
            )
            frames = await _leg_frames(conn, seeds["workspace_id"])
            assert [f[0] for f in frames] == ["leg.opened", "leg.awaiting_user", "leg.closed"]

    run_async(scenario())
