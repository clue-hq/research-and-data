"""Files attached to a chat message reach the design session on every route (2026-10-30).

Spec ``docs/superpowers/specs/2026-10-30-design-agent-attachments-design.md`` §3.1: an attachment
belongs to the message, so a session's first turn and an out-of-scope hand-back — both submissions
the server derives from the person's own message — carry that message's files, and a design run
can list every file sent in its chat thread.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from clue_api.agent_turn_submission import (
    submission_attachment_refs,
    submissions_for_thread,
    thread_attachment_refs,
    turn_id_for_submission,
)
from clue_api.chat.attachments import ValidatedAttachment
from clue_api.chat.uploads import record_chat_upload
from clue_api.design_leg_tools import OpenDesignLegTool
from clue_api.turn_action import TurnIdentity
from clue_core import new_operation_id
from clue_toolbelt import ToolContext
from tests.api.test_p34_design_leg_engine_db import _seed_leg_conversation, _submit_message
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)

pytestmark = pytest.mark.usefixtures("require_profiling_db")


async def attach(
    conn: Any, seeds: dict[str, Any], files: tuple[tuple[str, str, bytes], ...]
) -> tuple[ValidatedAttachment, ...]:
    """Upload each ``(filename, media_type, bytes)`` the way the upload route does."""

    attached = []
    for filename, media_type, data in files:
        ref = await seeds["artifacts"].persist_body(
            workspace_id=seeds["workspace_id"], data=data, media_type=media_type
        )
        upload = await record_chat_upload(
            conn,
            workspace_id=seeds["workspace_id"],
            user_id=seeds["user_id"],
            filename=filename,
            media_type=media_type,
            ref=ref,
        )
        family = "image" if media_type.startswith("image/") else "document"
        attached.append(
            ValidatedAttachment(
                upload_id=upload.upload_id, ref=ref, filename=filename, family=family
            )
        )
    return tuple(attached)


def _context(seeds: dict[str, Any]) -> ToolContext:
    return ToolContext(
        workspace_id=seeds["workspace_id"],
        actor="agent",
        conn_factory=seeds["conn_factory"],
        operation_id=new_operation_id(),
    )


def test_a_sessions_first_turn_carries_the_opening_messages_files(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="att-first")
            files = await attach(conn, seeds, (("pallet ad 3.jpg", "image/jpeg", b"\xff\xd8jp"),))
            opening = await _submit_message(
                conn, seeds, label="att-first-open", message="Use this.", attachment_refs=files
            )
            tool = OpenDesignLegTool(conn_factory=seeds["conn_factory"], storage=seeds["storage"])
            leg_id = str(seeds["leg"]["id"])
            await tool._queue_first_turn(
                conn,
                ctx=_context(seeds),
                turn=TurnIdentity(
                    turn_id=opening.turn_id,
                    workspace_id=seeds["workspace_id"],
                    project_id=seeds["project"].project_id,
                    thread_id=seeds["thread_id"],
                    submitted_by_user_id=seeds["user_id"],
                    submitted_via_membership_id=opening.submitted_via_membership_id,
                ),
                leg_id=leg_id,
            )
            first_turn_id = turn_id_for_submission(
                workspace_id=seeds["workspace_id"],
                thread_id=seeds["thread_id"],
                idempotency_key=f"design-leg-first-turn:{leg_id}:{opening.turn_id}",
            )
            carried = await submission_attachment_refs(
                conn, workspace_id=seeds["workspace_id"], turn_id=first_turn_id
            )
            assert [(row.upload_id, row.filename) for row in carried] == [
                (files[0].upload_id, "pallet ad 3.jpg")
            ]

    run_async(scenario())


def test_an_out_of_scope_hand_back_carries_the_messages_files(tmp_path: Path) -> None:
    from clue_api.agent_registry_wiring import build_agent_profile_registry
    from clue_api.toolbelt_wiring import build_toolbelt
    from clue_api.turn_action import derive_turn_action_ref
    from clue_toolbelt import invoke_tool
    from tests.api.conftest import hermetic_flag_env
    from tests.api.test_p35_finish_design_leg_db import _finish_registry, _one_design_turn

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="att-oos")
            with hermetic_flag_env():
                catalog = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            files = await attach(
                conn,
                seeds,
                (
                    (
                        "q3.xlsx",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        b"PK\x03\x04xl",
                    ),
                    ("logo.png", "image/png", b"\x89PNG\r\n"),
                ),
            )
            closing = await _one_design_turn(
                conn,
                seeds,
                catalog,
                label="att-oos-t1",
                message="Calculate the ROI from this Excel.",
                attachment_refs=files,
            )
            result = await invoke_tool(
                _finish_registry(seeds),
                "finish_design_leg",
                {
                    "source_turn_ref": derive_turn_action_ref(closing.turn_id),
                    "reason": "out_of_scope",
                    "summary": "An ROI calculation is not design work.",
                },
                _context(seeds),
                idempotency_ttl_s=60,
            )
            redelivered = await submission_attachment_refs(
                conn,
                workspace_id=seeds["workspace_id"],
                turn_id=UUID(result.references["redelivered_turn_id"]),
            )
            assert [(row.upload_id, row.filename) for row in redelivered] == [
                (files[0].upload_id, "q3.xlsx"),
                (files[1].upload_id, "logo.png"),
            ]

    run_async(scenario())


def test_thread_attachments_list_every_message_in_order_without_derived_copies(
    tmp_path: Path,
) -> None:
    from clue_api.agent_turn_submission import DERIVATION_DESIGN_LEG_FIRST_TURN

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="att-thread")
            first = await attach(
                conn, seeds, (("a.png", "image/png", b"\x89PNGa"), ("b.md", "text/markdown", b"b"))
            )
            one = await _submit_message(
                conn, seeds, label="att-thread-1", message="one", attachment_refs=first
            )
            await _submit_message(
                conn,
                seeds,
                label="att-thread-copy",
                message="one",
                attachment_refs=first,
                derivation=DERIVATION_DESIGN_LEG_FIRST_TURN,
                derived_from_turn_id=one.turn_id,
            )
            second = await attach(conn, seeds, (("c.pdf", "application/pdf", b"%PDF-c"),))
            two = await _submit_message(
                conn, seeds, label="att-thread-2", message="two", attachment_refs=second
            )

            rows = await thread_attachment_refs(
                conn, workspace_id=seeds["workspace_id"], thread_id=seeds["thread_id"]
            )
            assert [(row.turn_id, row.filename) for row in rows] == [
                (one.turn_id, "a.png"),
                (one.turn_id, "b.md"),
                (two.turn_id, "c.pdf"),
            ]
            assert (
                len(
                    await submissions_for_thread(
                        conn, workspace_id=seeds["workspace_id"], thread_id=seeds["thread_id"]
                    )
                )
                == 3
            )

    run_async(scenario())
