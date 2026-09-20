"""P3.5 acceptance — ``finish_design_leg@1`` and the mis-exit reopen (PD-part3 §2.2).

The leg-level exit, engine-validated: only the design orchestrator's own turn may close its
leg; the reason vocabulary is closed; ``out_of_scope`` carries the **user's own captured
message** back to head-of-abm as a fresh submission (derived, never model-authored — the user
never repeats themselves); every exit is journaled append-only; the lock-in summary becomes
the one design artifact head-of-abm's §2.4 history gains (transcripts stay excluded). The
mis-exit reopen is the delegation entry naming the closed leg (``reopen_leg_id``): the same
leg returns ``open_awaiting_user``, the original bundle and history resume, and the exit
record survives.

``final.json`` / ``finalize_run`` remain the design harness's TURN-level outcome contract —
nothing here touches them; ``finish_design_leg`` is the only path to ``closed``.

All writes run in rolled-back transactions against the session-migrated DB.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import pytest
from sqlalchemy import text

from clue_agents import AgentExecutionStatus
from clue_api.agent_registry_wiring import build_agent_profile_registry
from clue_api.agent_turn_submission import message_artifact_ref, submissions_for_thread
from clue_api.design_leg_tools import (
    FinishDesignLegTool,
    OpenDesignLegTool,
    design_leg_ref,
)
from clue_api.design_leg_wiring import (
    design_leg_run_id,
    load_design_leg_history,
    load_head_of_abm_history,
)
from clue_api.toolbelt_wiring import build_toolbelt
from clue_api.turn_action import derive_turn_action_ref
from clue_core import new_operation_id
from clue_design import legs as design_legs
from clue_toolbelt import (
    PreconditionFailed,
    ToolContext,
    ToolRegistry,
    invoke_tool,
)
from tests.api.conftest import hermetic_flag_env
from tests.api.test_p34_design_leg_engine_db import (
    _card_payload,
    _FakeLane,
    _seed_leg_conversation,
    _submit_message,
)
from tests.api.test_p34_design_leg_engine_db import _runner as _leg_runner
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,  # noqa: F401 -- re-exported for the P3.4 helpers
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)


def _finish_registry(seeds: dict[str, Any]) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        FinishDesignLegTool(
            conn_factory=seeds["conn_factory"],
            storage=seeds["storage"],
        ),
        make_default=True,
    )
    registry.register(
        OpenDesignLegTool(
            conn_factory=seeds["conn_factory"],
            storage=seeds["storage"],
        ),
        make_default=True,
    )
    return registry


def _context(seeds: dict[str, Any]) -> ToolContext:
    return ToolContext(
        workspace_id=seeds["workspace_id"],
        actor="agent",
        conn_factory=seeds["conn_factory"],
        operation_id=new_operation_id(),
    )


async def _one_design_turn(
    conn: Any,
    seeds: dict[str, Any],
    registry_catalog: Any,
    *,
    label: str,
    message: str,
) -> Any:
    """Run one real leg turn (fake lane) so a genuine closing design turn exists."""

    submission = await _submit_message(conn, seeds, label=label, message=message)
    leg = await design_legs.get_open_leg_for_thread(
        conn, workspace_id=seeds["workspace_id"], thread_id=seeds["thread_id"]
    )
    assert leg is not None
    user_message_ref = await message_artifact_ref(conn, submission)
    lane = _FakeLane(conn_factory=seeds["conn_factory"])
    result = await _leg_runner(seeds, registry_catalog, lane).run_leg_turn(
        submission=submission,
        leg=leg,
        user_message_ref=user_message_ref,
        focus_refs=(),
        card_payload=_card_payload(seeds),
        stream=None,
    )
    assert result.outcome.status is AgentExecutionStatus.AWAITING_INPUT
    return submission


def test_locked_close_journals_summarizes_and_returns_the_thread(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """The lock-in: journal + summary + closed leg, and §2.4's other half — head-of-abm's
    history gains the summary while still excluding every leg transcript."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="lock")
            with hermetic_flag_env():
                catalog = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            closing = await _one_design_turn(
                conn, seeds, catalog, label="lock-t1", message="Bolder headline."
            )
            result = await invoke_tool(
                _finish_registry(seeds),
                "finish_design_leg",
                {
                    "source_turn_ref": derive_turn_action_ref(closing.turn_id),
                    "reason": "locked",
                    "summary": "Locked the launch artboard: bold two-line headline on navy.",
                },
                _context(seeds),
                idempotency_ttl_s=60,
            )
            refs = result.references
            assert refs["leg_id"] == seeds["leg"]["id"]
            assert refs["leg_ref"] == design_leg_ref(seeds["leg"]["id"])
            assert refs["reason"] == "locked"
            assert refs["created"] is True
            assert refs["redelivered_turn_id"] is None

            leg = await design_legs.get_leg(
                conn, workspace_id=seeds["workspace_id"], leg_id=seeds["leg"]["id"]
            )
            assert leg["state"] == "closed" and leg["close_reason"] == "locked"
            assert (
                await design_legs.get_open_leg_for_thread(
                    conn,
                    workspace_id=seeds["workspace_id"],
                    thread_id=seeds["thread_id"],
                )
                is None
            )

            journal = (
                (
                    await conn.execute(
                        text(
                            "SELECT reason, summary_refs, pending_user_message_ref, "
                            "decided_by_run_id FROM design_leg_exit_journal "
                            "WHERE leg_id = :leg"
                        ),
                        {"leg": seeds["leg"]["id"]},
                    )
                )
                .mappings()
                .all()
            )
            assert len(journal) == 1
            summary_refs = journal[0]["summary_refs"]
            if isinstance(summary_refs, str):  # driver-dependent jsonb decode
                summary_refs = json.loads(summary_refs)
            assert summary_refs["closing_turn_id"] == str(closing.turn_id)
            assert summary_refs["summary_artifact_key"] == refs["summary_artifact_key"]
            assert journal[0]["pending_user_message_ref"] is None
            assert journal[0]["decided_by_run_id"] == design_leg_run_id(closing.turn_id)

            # §2.4, the missing half: head-of-abm's load now carries the summary — and ONLY
            # the summary — of the closed leg. The transcript stays design's.
            hoabm = await load_head_of_abm_history(
                seeds["conn_factory"],
                workspace_id=seeds["workspace_id"],
                thread_id=seeds["thread_id"],
            )
            bodies = []
            for item in hoabm:
                bodies.append((await seeds["artifacts"].read(item.body_ref)).decode())
            assert bodies == ["Locked the launch artboard: bold two-line headline on navy."]
            # The design-side load still sees the whole leg, summary included.
            leg_history = await load_design_leg_history(
                seeds["conn_factory"],
                workspace_id=seeds["workspace_id"],
                thread_id=seeds["thread_id"],
                leg_parent_execution_id=seeds["parent_execution_id"],
            )
            assert [item.role for item in leg_history] == ["user", "assistant", "assistant"]

            # Replay: finishing an already-closed leg from the same turn converges.
            replay = await invoke_tool(
                _finish_registry(seeds),
                "finish_design_leg",
                {
                    "source_turn_ref": derive_turn_action_ref(closing.turn_id),
                    "reason": "locked",
                    "summary": "Locked the launch artboard: bold two-line headline on navy.",
                },
                _context(seeds),
                idempotency_ttl_s=60,
            )
            assert replay.references["created"] is False
            assert replay.references["leg_id"] == seeds["leg"]["id"]
            count = (
                await conn.execute(
                    text("SELECT count(*) FROM design_leg_exit_journal WHERE leg_id = :leg"),
                    {"leg": seeds["leg"]["id"]},
                )
            ).scalar_one()
            assert int(count) == 1

    run_async(scenario())


def test_out_of_scope_re_delivers_the_users_own_message(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """The user never repeats themselves: the presenting turn's captured bytes become a
    fresh head-of-abm submission on the same thread, submitter and context refs intact."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="oos")
            with hermetic_flag_env():
                catalog = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            closing = await _one_design_turn(
                conn,
                seeds,
                catalog,
                label="oos-t1",
                message="Actually, which accounts should get this campaign?",
            )
            result = await invoke_tool(
                _finish_registry(seeds),
                "finish_design_leg",
                {
                    "source_turn_ref": derive_turn_action_ref(closing.turn_id),
                    "reason": "out_of_scope",
                    "summary": "The ask is account strategy, not design.",
                },
                _context(seeds),
                idempotency_ttl_s=60,
            )
            redelivered_id = result.references["redelivered_turn_id"]
            assert redelivered_id is not None

            leg = await design_legs.get_leg(
                conn, workspace_id=seeds["workspace_id"], leg_id=seeds["leg"]["id"]
            )
            assert leg["state"] == "closed" and leg["close_reason"] == "out_of_scope"
            journal_pending = (
                await conn.execute(
                    text(
                        "SELECT pending_user_message_ref FROM design_leg_exit_journal "
                        "WHERE leg_id = :leg"
                    ),
                    {"leg": seeds["leg"]["id"]},
                )
            ).scalar_one()
            assert journal_pending == closing.message_artifact_key

            thread_submissions = await submissions_for_thread(
                conn,
                workspace_id=seeds["workspace_id"],
                thread_id=seeds["thread_id"],
            )
            redelivered = next(
                item for item in thread_submissions if str(item.turn_id) == redelivered_id
            )
            # Same bytes, same human, never the model's words.
            assert redelivered.message_sha256 == closing.message_sha256
            assert redelivered.message_artifact_key == closing.message_artifact_key
            assert redelivered.submitted_by_user_id == closing.submitted_by_user_id
            assert redelivered.turn_id != closing.turn_id
            assert redelivered.derivation == "design_leg_redelivery"
            assert redelivered.derived_from_turn_id == closing.turn_id
            # The user's own submission is not derived from anything.
            assert closing.derivation is None and closing.derived_from_turn_id is None
            # The leg is closed, so the redelivered turn routes to head-of-abm.
            assert (
                await design_legs.get_open_leg_for_thread(
                    conn,
                    workspace_id=seeds["workspace_id"],
                    thread_id=seeds["thread_id"],
                )
                is None
            )

            # Replay converges on the same redelivered turn — no second submission.
            replay = await invoke_tool(
                _finish_registry(seeds),
                "finish_design_leg",
                {
                    "source_turn_ref": derive_turn_action_ref(closing.turn_id),
                    "reason": "out_of_scope",
                    "summary": "The ask is account strategy, not design.",
                },
                _context(seeds),
                idempotency_ttl_s=60,
            )
            assert replay.references["redelivered_turn_id"] == redelivered_id

    run_async(scenario())


def test_finish_refuses_a_turn_that_is_not_this_legs_own(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """Only the leg's own design turn may close it — a head-of-abm turn is refused, and a
    thread with no open leg has nothing to close."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="wrong")
            # A head-of-abm turn on the same thread (the strategy shape).
            hoabm_turn = uuid5(NAMESPACE_URL, "p35:wrong:hoabm-turn")
            manifest = await seeds["artifacts"].persist_body(
                workspace_id=seeds["workspace_id"],
                data=json.dumps({"resources": []}).encode(),
                media_type="application/json",
            )
            await conn.execute(
                text(
                    "INSERT INTO agent_turn "
                    "(id, execution_id, workspace_id, project_id, thread_id, actor_id, role, "
                    " workspace_root_id, profile_name, profile_version, profile_sha256, "
                    " resource_manifest_key, resource_manifest_artifact_sha256, "
                    " resource_manifest_sha256, retention_class, requested_at) "
                    "VALUES (:id, :execution, :workspace, :project, :thread, 'usr', "
                    " 'head_of_abm', 'root-p35', 'head-of-abm', 'v24', :sha, :key, :sha256, "
                    " :sha256, 'test', now())"
                ),
                {
                    "id": hoabm_turn,
                    "execution": seeds["parent_execution_id"],
                    "workspace": seeds["workspace_id"],
                    "project": seeds["project"].project_id,
                    "thread": seeds["thread_id"],
                    "sha": "0" * 64,
                    "key": manifest.artifact_key,
                    "sha256": manifest.sha256,
                },
            )
            with pytest.raises(PreconditionFailed) as wrong:
                await invoke_tool(
                    _finish_registry(seeds),
                    "finish_design_leg",
                    {
                        "source_turn_ref": derive_turn_action_ref(hoabm_turn),
                        "reason": "abandoned",
                        "summary": "n/a",
                    },
                    _context(seeds),
                    idempotency_ttl_s=60,
                )
            assert "design_leg_exit_wrong_turn" in str(wrong.value)
            # Close the leg, then try to finish again from a fresh (nonexistent) design turn.
            await design_legs.close_leg(
                conn,
                workspace_id=seeds["workspace_id"],
                leg_id=seeds["leg"]["id"],
                reason="abandoned",
                summary_refs={},
            )
            with pytest.raises(PreconditionFailed) as gone:
                await invoke_tool(
                    _finish_registry(seeds),
                    "finish_design_leg",
                    {
                        "source_turn_ref": derive_turn_action_ref(hoabm_turn),
                        "reason": "abandoned",
                        "summary": "n/a",
                    },
                    _context(seeds),
                    idempotency_ttl_s=60,
                )
            assert "design_leg_not_open" in str(gone.value)

    run_async(scenario())


def test_reopen_restores_the_same_leg_its_bundle_and_its_context(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """The mis-exit recovery (§2.2): re-delegation names the closed leg; the SAME leg
    reopens with its original bundle, its history resumes, and the exit record survives."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="reopen")
            with hermetic_flag_env():
                catalog = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            first = await _one_design_turn(
                conn, seeds, catalog, label="reopen-t1", message="Try a serif face."
            )
            await invoke_tool(
                _finish_registry(seeds),
                "finish_design_leg",
                {
                    "source_turn_ref": derive_turn_action_ref(first.turn_id),
                    "reason": "locked",
                    "summary": "Locked with the serif face.",
                },
                _context(seeds),
                idempotency_ttl_s=60,
            )

            # The re-delegation: a NEW head-of-abm turn names the closed leg.
            redelegating = await _submit_message(
                conn, seeds, label="reopen-redelegate", message="Keep designing, actually."
            )
            manifest = await seeds["artifacts"].persist_body(
                workspace_id=seeds["workspace_id"],
                data=json.dumps({"resources": []}).encode(),
                media_type="application/json",
            )
            await conn.execute(
                text(
                    "INSERT INTO agent_turn "
                    "(id, execution_id, workspace_id, project_id, thread_id, actor_id, role, "
                    " workspace_root_id, profile_name, profile_version, profile_sha256, "
                    " resource_manifest_key, resource_manifest_artifact_sha256, "
                    " resource_manifest_sha256, retention_class, requested_at) "
                    "VALUES (:id, :execution, :workspace, :project, :thread, 'usr', "
                    " 'head_of_abm', 'root-p35', 'head-of-abm', 'v24', :sha, :key, :sha256, "
                    " :sha256, 'test', now())"
                ),
                {
                    "id": redelegating.turn_id,
                    "execution": seeds["parent_execution_id"],
                    "workspace": seeds["workspace_id"],
                    "project": seeds["project"].project_id,
                    "thread": seeds["thread_id"],
                    "sha": "0" * 64,
                    "key": manifest.artifact_key,
                    "sha256": manifest.sha256,
                },
            )
            reopened = await invoke_tool(
                _finish_registry(seeds),
                "open_design_leg",
                {
                    "source_turn_ref": derive_turn_action_ref(redelegating.turn_id),
                    "brief": "The lock was premature; keep iterating on the artboard.",
                    "reopen_leg_id": seeds["leg"]["id"],
                },
                _context(seeds),
                idempotency_ttl_s=60,
            )
            assert reopened.references["leg_id"] == seeds["leg"]["id"]
            assert reopened.references["created"] is False
            assert reopened.references["reopened"] is True

            leg = await design_legs.get_leg(
                conn, workspace_id=seeds["workspace_id"], leg_id=seeds["leg"]["id"]
            )
            assert leg["state"] == "open_awaiting_user"
            assert leg["close_reason"] is None
            # The original bundle survives the reopen — context, not a fresh delegation.
            assert leg["bundle_artifact_ref"] == seeds["leg"]["bundle_artifact_ref"]
            journal_count = (
                await conn.execute(
                    text("SELECT count(*) FROM design_leg_exit_journal WHERE leg_id = :leg"),
                    {"leg": seeds["leg"]["id"]},
                )
            ).scalar_one()
            assert int(journal_count) == 1  # the mis-exit record survives

            # Context resumes: the next design turn's leg history carries the whole prior
            # exchange (user, assistant, and the lock-in summary).
            second = await _one_design_turn(
                conn, seeds, catalog, label="reopen-t2", message="Make it italic too."
            )
            del second
            history = await load_design_leg_history(
                seeds["conn_factory"],
                workspace_id=seeds["workspace_id"],
                thread_id=seeds["thread_id"],
                leg_parent_execution_id=seeds["parent_execution_id"],
            )
            assert [item.role for item in history] == [
                "user",
                "assistant",
                "assistant",  # the lock-in summary
                "user",
                "assistant",
            ]

    run_async(scenario())


def test_reopen_refuses_what_it_must(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """Reopen is for CLOSED legs of THIS thread only; an open leg cannot be 're-opened'."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="badre")
            submission = await _submit_message(
                conn, seeds, label="badre-turn", message="Design things."
            )
            manifest = await seeds["artifacts"].persist_body(
                workspace_id=seeds["workspace_id"],
                data=json.dumps({"resources": []}).encode(),
                media_type="application/json",
            )
            await conn.execute(
                text(
                    "INSERT INTO agent_turn "
                    "(id, execution_id, workspace_id, project_id, thread_id, actor_id, role, "
                    " workspace_root_id, profile_name, profile_version, profile_sha256, "
                    " resource_manifest_key, resource_manifest_artifact_sha256, "
                    " resource_manifest_sha256, retention_class, requested_at) "
                    "VALUES (:id, :execution, :workspace, :project, :thread, 'usr', "
                    " 'head_of_abm', 'root-p35', 'head-of-abm', 'v24', :sha, :key, :sha256, "
                    " :sha256, 'test', now())"
                ),
                {
                    "id": submission.turn_id,
                    "execution": seeds["parent_execution_id"],
                    "workspace": seeds["workspace_id"],
                    "project": seeds["project"].project_id,
                    "thread": seeds["thread_id"],
                    "sha": "0" * 64,
                    "key": manifest.artifact_key,
                    "sha256": manifest.sha256,
                },
            )
            with pytest.raises(PreconditionFailed) as still_open:
                await invoke_tool(
                    _finish_registry(seeds),
                    "open_design_leg",
                    {
                        "source_turn_ref": derive_turn_action_ref(submission.turn_id),
                        "brief": "Reopen it.",
                        "reopen_leg_id": seeds["leg"]["id"],
                    },
                    _context(seeds),
                    idempotency_ttl_s=60,
                )
            assert "design_leg_reopen_not_closed" in str(still_open.value)
            with pytest.raises(PreconditionFailed) as unknown:
                await invoke_tool(
                    _finish_registry(seeds),
                    "open_design_leg",
                    {
                        "source_turn_ref": derive_turn_action_ref(submission.turn_id),
                        "brief": "Reopen something else.",
                        "reopen_leg_id": str(uuid5(NAMESPACE_URL, "p35:no-such-leg")),
                    },
                    _context(seeds),
                    idempotency_ttl_s=60,
                )
            assert "design_leg_reopen_not_found" in str(unknown.value)

    run_async(scenario())


def test_closing_a_two_document_leg_journals_every_documents_version(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """Spec §3.2: the close records the version of EVERY document the leg worked on.

    ``document_id``/``document_version`` keep meaning position 0 — every single-document
    reader of the journal is unchanged — and ``document_versions`` carries the whole set,
    so a two-artboard leg's lock-in is a complete record instead of one artboard's.

    The documents are attached after the turn: what this test owns is the close journal,
    not the runner's fan-out (pinned by the multi-artifact engine suite).
    """

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="versions")
            with hermetic_flag_env():
                catalog = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            closing = await _one_design_turn(
                conn, seeds, catalog, label="versions-t1", message="Two artboards, bolder."
            )

            workspace_id = seeds["workspace_id"]
            leg_id = seeds["leg"]["id"]
            for position, (document_id, version) in enumerate(
                (("doc_versions_a", 2), ("doc_versions_b", 5))
            ):
                await conn.execute(
                    text(
                        "INSERT INTO design_document (id, workspace_id, title, status, doc_kind,"
                        " current_scene_json, current_version)"
                        " VALUES (:id, :ws, :title, 'draft', 'scene', CAST('{}' AS jsonb), :v)"
                    ),
                    {
                        "id": document_id,
                        "ws": workspace_id,
                        "title": f"Artboard {position}",
                        "v": version,
                    },
                )
            await design_legs.add_leg_documents(
                conn,
                workspace_id=workspace_id,
                leg_id=leg_id,
                documents=[
                    design_legs.LegDocumentSpec(document_id="doc_versions_a", position=0),
                    design_legs.LegDocumentSpec(document_id="doc_versions_b", position=1),
                ],
            )
            # The shipped tool pins position 0 on the leg itself; the DAL seed opens a
            # document-less leg, so this reproduces the shape the close reads.
            await conn.execute(
                text(
                    "UPDATE design_leg SET document_id = 'doc_versions_a'"
                    " WHERE id = :leg AND workspace_id = :ws"
                ),
                {"leg": leg_id, "ws": workspace_id},
            )

            await invoke_tool(
                _finish_registry(seeds),
                "finish_design_leg",
                {
                    "source_turn_ref": derive_turn_action_ref(closing.turn_id),
                    "reason": "locked",
                    "summary": "Locked both artboards.",
                },
                _context(seeds),
                idempotency_ttl_s=60,
            )

            summary_refs = (
                await conn.execute(
                    text("SELECT summary_refs FROM design_leg_exit_journal WHERE leg_id = :leg"),
                    {"leg": leg_id},
                )
            ).scalar_one()
            if isinstance(summary_refs, str):  # driver-dependent jsonb decode
                summary_refs = json.loads(summary_refs)
            assert summary_refs["document_id"] == "doc_versions_a"
            assert summary_refs["document_version"] == 2
            assert summary_refs["document_versions"] == {
                "doc_versions_a": 2,
                "doc_versions_b": 5,
            }

    run_async(scenario())
