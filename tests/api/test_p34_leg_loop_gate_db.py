"""P3.4 slice gate (PD-part3 §4): the full leg loop on durable rows.

Strategy turn → ``open_design_leg`` (the delegation entry) opens the leg → N direct design
turns, each carrying canvas ``design_document`` focus refs, executed by the REAL worker
runner (:class:`ProjectConversationTurnRunner`) through the P3.4 routing rule → head-of-abm
untouched throughout: its engine never executes, no C5 recipe starts, and its history never
ingests the leg transcript.

The design lane is faked (P3.2's gate proved the real runtime on the real provider); this
gate proves the *loop* — routing, attribution, leg state, history scoping — end to end.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import AgentExecutionStatus, DomainObjectRef
from clue_api.agent_registry_wiring import build_agent_profile_registry
from clue_api.agent_turn_fleet_wiring import ProjectConversationTurnRunner
from clue_api.agent_turn_submission import insert_submission
from clue_api.agent_turn_wiring import (
    DbAgentHistoryStore,
    DbAgentTurnJournal,
    DurableAgentArtifactStore,
)
from clue_api.conversation_capture import persist_user_turn
from clue_api.design_leg_wiring import (
    DesignLegTurnRunner,
    load_design_leg_history,
    load_head_of_abm_history,
)
from clue_api.toolbelt_wiring import build_toolbelt
from clue_api.turn_action import derive_turn_action_ref
from clue_core import new_operation_id
from clue_design import legs as design_legs
from clue_design import runs as design_runs
from clue_design.documents import create_document
from clue_storage import FsStorage
from clue_toolbelt import ToolContext, ToolRegistry, invoke_tool
from tests._identity import seed_principal
from tests._workspace import seed_project
from tests.api.conftest import hermetic_flag_env
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)

USER_ID = "usr_p34_gate"
NOW_UTC = datetime(2026, 8, 14, 14, 0, tzinfo=UTC)


class _HeadOfAbmMustNotRun:
    """The gate's central sentinel: while the leg is open, this engine never executes."""

    def __init__(self, turns: DbAgentTurnJournal) -> None:
        self.calls = 0
        # The watched wrapper's exception paths read `components.turns`; giving it the real
        # journal keeps the sentinel honest without widening what it fakes.
        self.components = type("_C", (), {"turns": turns})()

    async def execute(self, **kwargs: Any) -> Any:
        del kwargs
        self.calls += 1
        raise AssertionError("head-of-abm must stay untouched while a design leg is open")


class _FakeLane:
    def __init__(self, *, conn_factory: Any) -> None:
        self._conn_factory = conn_factory
        self.envelopes: list[Any] = []

    async def drive(self, *, envelope: Any) -> None:
        self.envelopes.append(envelope)
        async with self._conn_factory() as conn:
            await design_runs.set_run_result(
                conn,
                workspace_id=envelope.workspace_id,
                run_id=envelope.run_id,
                status="succeeded",
                result={
                    "schema_version": 1,
                    "status": "accepted",
                    "stop_reason": f"Proposal {len(self.envelopes)} ready for review.",
                },
            )


async def _submit(
    conn: AsyncConnection,
    *,
    seeds: dict[str, Any],
    label: str,
    message: str,
    focus_refs: tuple[DomainObjectRef, ...] = (),
) -> Any:
    turn_id = uuid5(NAMESPACE_URL, f"p34gate:{label}")
    captured = await persist_user_turn(
        conn,
        artifacts=seeds["artifacts"],
        workspace_id=seeds["workspace_id"],
        brand_id=seeds["project"].brand_id,
        product_id=seeds["project"].product_id,
        project_id=seeds["project"].project_id,
        turn_id=turn_id,
        message=message,
    )
    submission, _ = await insert_submission(
        conn,
        turn_id=turn_id,
        workspace_id=seeds["workspace_id"],
        project_id=seeds["project"].project_id,
        thread_id=seeds["thread_id"],
        submitted_by_user_id=USER_ID,
        submitted_via_membership_id=f"wsm_p34g_{seeds['workspace_id']}",
        onboarding_input_id=captured.onboarding_input_id,
        message_artifact_key=captured.artifact_ref.artifact_key,
        message_sha256=captured.artifact_ref.sha256,
        idempotency_key=f"p34gate-{label}",
        context_refs=focus_refs,
    )
    return submission


def test_the_full_leg_loop_routes_design_and_leaves_head_of_abm_untouched(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            # --- the stage: workspace, project, thread, design targets --------------------
            workspace_id = f"ws_p34gate_{uuid4().hex[:8]}"
            project = await seed_project(conn, workspace_id, name="P3.4 gate")
            await seed_principal(
                conn,
                workspace_id=workspace_id,
                user_id=USER_ID,
                membership_id=f"wsm_p34g_{workspace_id}",
            )
            thread_id = "thr_p34gate"
            await conn.execute(
                text(
                    "INSERT INTO agent_thread (id, workspace_id, project_id) "
                    "VALUES (:id, :ws, :project)"
                ),
                {"id": thread_id, "ws": workspace_id, "project": project.project_id},
            )
            cf = conn_session_factory(conn)
            storage = FsStorage(tmp_path / "artifacts")
            artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=cf)
            document = await create_document(
                conn,
                workspace_id=workspace_id,
                scene={"meta": {"id": "doc_p34gate", "title": "Launch artboard"}},
            )
            seeds = {
                "workspace_id": workspace_id,
                "project": project,
                "thread_id": thread_id,
                "artifacts": artifacts,
            }

            # --- 1. the strategy turn (head-of-abm's own, durable) ------------------------
            strategy = await _submit(
                conn, seeds=seeds, label="strategy", message="Let's make launch assets."
            )
            manifest = await artifacts.persist_body(
                workspace_id=workspace_id,
                data=json.dumps({"resources": []}).encode(),
                media_type="application/json",
            )
            strategy_execution = uuid5(NAMESPACE_URL, "p34gate:strategy-execution")
            await conn.execute(
                text(
                    "INSERT INTO execution "
                    "(id, workspace_id, project_id, started_by, parameter_manifest_hash, "
                    " pin_manifest_hash) "
                    "VALUES (:id, :workspace, :project, 'human', :hash, :hash)"
                ),
                {
                    "id": strategy_execution,
                    "workspace": workspace_id,
                    "project": project.project_id,
                    "hash": "0" * 64,
                },
            )
            await conn.execute(
                text(
                    "INSERT INTO agent_turn "
                    "(id, execution_id, workspace_id, project_id, thread_id, actor_id, role, "
                    " workspace_root_id, profile_name, profile_version, profile_sha256, "
                    " resource_manifest_key, resource_manifest_artifact_sha256, "
                    " resource_manifest_sha256, retention_class, requested_at, "
                    " submitted_by_user_id, submitted_via_membership_id) "
                    "VALUES (:id, :execution, :workspace, :project, :thread, :actor, "
                    " 'head_of_abm', 'root-p34g', 'head-of-abm', 'v24', :sha, :key, :sha256, "
                    " :sha256, 'test', :at, :user, :membership)"
                ),
                {
                    "id": strategy.turn_id,
                    "execution": strategy_execution,
                    "workspace": workspace_id,
                    "project": project.project_id,
                    "thread": thread_id,
                    "actor": USER_ID,
                    "sha": "0" * 64,
                    "key": manifest.artifact_key,
                    "sha256": manifest.sha256,
                    "at": NOW_UTC,
                    "user": USER_ID,
                    "membership": f"wsm_p34g_{workspace_id}",
                },
            )
            history = DbAgentHistoryStore(conn_factory=cf)
            await history.append(
                message_id=uuid5(strategy.turn_id, "user"),
                turn_id=strategy.turn_id,
                workspace_id=workspace_id,
                thread_id=thread_id,
                role="user",
                body_ref=(
                    await artifacts.persist_body(
                        workspace_id=workspace_id,
                        data=b"Let's make launch assets.",
                        media_type="text/plain",
                    )
                ),
            )

            # --- 2. the delegation: open_design_leg on the strategy turn ------------------
            with hermetic_flag_env():
                registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            from clue_api.design_leg_tools import OpenDesignLegTool

            tool_registry = ToolRegistry()
            tool_registry.register(
                OpenDesignLegTool(conn_factory=cf, storage=storage), make_default=True
            )
            opened = await invoke_tool(
                tool_registry,
                "open_design_leg",
                {
                    "source_turn_ref": derive_turn_action_ref(strategy.turn_id),
                    "brief": "Launch-day artboard for Acme.",
                    "document_id": document["id"],
                },
                ToolContext(
                    workspace_id=workspace_id,
                    actor="agent",
                    conn_factory=cf,
                    operation_id=new_operation_id(),
                ),
                idempotency_ttl_s=60,
            )
            leg_id = opened.references["leg_id"]

            # --- 3. N direct design turns through the REAL worker runner ------------------
            turns_journal = DbAgentTurnJournal(conn_factory=cf)
            sentinel = _HeadOfAbmMustNotRun(turns_journal)
            lane = _FakeLane(conn_factory=cf)
            runner = ProjectConversationTurnRunner(
                engine=sentinel,  # type: ignore[arg-type]
                executor=None,  # type: ignore[arg-type] -- never reached on the design path
                recipes=None,  # type: ignore[arg-type]
                starter=None,  # type: ignore[arg-type]
                parameters=None,  # type: ignore[arg-type]
                design_legs=DesignLegTurnRunner(
                    profiles=registry,
                    artifacts=artifacts,
                    turns=turns_journal,
                    history=history,
                    lane=lane,
                    conn_factory=cf,
                ),
                conn_factory=cf,
                streaming=False,
            )
            focus = DomainObjectRef(
                workspace_id=workspace_id,
                object_type="design_document",
                object_id=document["id"],
                version=None,
            )
            for ordinal, message in enumerate(
                ("Make the headline bolder.", "Now try the navy background."), start=1
            ):
                submission = await _submit(
                    conn,
                    seeds=seeds,
                    label=f"design-{ordinal}",
                    message=message,
                    focus_refs=(focus,),
                )
                result = await runner.run(turn_id=submission.turn_id, workspace_id=workspace_id)
                assert result.outcome.status is AgentExecutionStatus.AWAITING_INPUT
                assert result.replayed is False

            # --- the gate's assertions ----------------------------------------------------
            assert sentinel.calls == 0  # head-of-abm untouched throughout
            recipe_executions = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM execution "
                        "WHERE workspace_id = :ws AND parameter_artifact_key IS NULL "
                        "AND id <> :strategy"
                    ),
                    {"ws": workspace_id, "strategy": strategy_execution},
                )
            ).scalar_one()
            assert int(recipe_executions) == 0  # no C5 recipe execution started

            roles = (
                await conn.execute(
                    text(
                        "SELECT t.role, count(*) FROM agent_turn t "
                        "WHERE t.workspace_id = :ws AND t.thread_id = :thread "
                        "GROUP BY t.role ORDER BY t.role"
                    ),
                    {"ws": workspace_id, "thread": thread_id},
                )
            ).all()
            assert [(row[0], int(row[1])) for row in roles] == [
                ("design", 2),
                ("head_of_abm", 1),
            ]

            # Both design turns carried the canvas focus ref into the lane envelope.
            assert len(lane.envelopes) == 2
            for envelope in lane.envelopes:
                assert envelope.config["leg"]["focus_refs"] == [
                    {
                        "object_type": "design_document",
                        "object_id": document["id"],
                        "version": None,
                    }
                ]
                assert envelope.config["request"]["scene"] == {
                    "meta": {"id": document["id"], "title": "Launch artboard"}
                }
            # The second turn's envelope carried the first exchange as leg history (§2.4).
            assert [item["role"] for item in lane.envelopes[1].config["history"]] == [
                "user",
                "assistant",
            ]

            # The leg is back awaiting the user; §2.4 scoping holds on both sides.
            leg_after = await design_legs.get_leg(conn, workspace_id=workspace_id, leg_id=leg_id)
            assert leg_after["state"] == "open_awaiting_user"
            leg_history = await load_design_leg_history(
                cf,
                workspace_id=workspace_id,
                thread_id=thread_id,
                leg_parent_execution_id=leg_after["parent_execution_id"],
            )
            assert [item.role for item in leg_history] == [
                "user",
                "assistant",
                "user",
                "assistant",
            ]
            hoabm_history = await load_head_of_abm_history(
                cf, workspace_id=workspace_id, thread_id=thread_id
            )
            assert [item.turn_id for item in hoabm_history] == [strategy.turn_id]

    run_async(scenario())
