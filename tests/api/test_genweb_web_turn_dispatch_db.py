"""Slice 1 acceptance — design legs dispatch WEB turns for web documents (B1).

The chat -> website path's missing half: a leg pinned to a ``doc_kind='web'`` document
must dispatch a ``web_turn`` envelope carrying a ``WebTurnRequest``-shaped
``config.request`` (prompt + the document's CURRENT version as the CAS base), while a
scene-pinned (or document-less) leg keeps the shipped ``agent_turn`` envelope
byte-for-byte. The lane is faked here exactly as in P3.4/P3.6 — what this suite pins is
the platform substrate: which envelope is built, what the run row records, and what the
thread is told about the result.

All writes run in rolled-back transactions against the session-migrated DB.
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
from clue_api.agent_turn_submission import (
    AgentTurnSubmissionRow,
    insert_submission,
    message_artifact_ref,
)
from clue_api.agent_turn_wiring import (
    DbAgentHistoryStore,
    DbAgentTurnJournal,
    DurableAgentArtifactStore,
)
from clue_api.conversation_capture import persist_user_turn
from clue_api.design_leg_tools import DESIGN_DELEGATION_BUNDLE_MEDIA_TYPE
from clue_api.design_leg_wiring import DesignLegTurnRunner, design_leg_run_id
from clue_api.toolbelt_wiring import build_toolbelt
from clue_design import legs as design_legs
from clue_design import runs as design_runs
from clue_design.documents import create_document, update_web_document
from clue_storage import FsStorage
from tests._identity import seed_principal
from tests._workspace import seed_project
from tests.api.conftest import hermetic_flag_env
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)

USER_ID = "usr_genweb_dispatch"
NOW_UTC = datetime(2026, 8, 19, 9, 0, tzinfo=UTC)

#: What the design substrate's web executor returns for a turn it committed
#: (``run_web_agent_turn`` + ``execute_web_turn_job``: applied, with the document's
#: post-commit version stamped on). No ``stop_reason`` — the web result shape has none.
APPLIED_WEB_RESULT: dict[str, Any] = {
    "schema_version": 1,
    "status": "applied",
    "outcome": "accepted",
    "summary": "Built a three-section landing page.",
    "operations": [{"op": "author_page"}],
    "preview_paths": [],
    "doc_kind": "web",
    "current_version": 1,
}

#: ``conflicted_web_turn_response`` — the CAS loser. The design row is terminal-FAILED
#: for it (``execute_web_turn_job``: succeeded iff status == "applied").
CONFLICTED_WEB_RESULT: dict[str, Any] = {
    "schema_version": 1,
    "status": "conflicted",
    "outcome": "conflicted",
    "summary": (
        "This website changed while the AI turn was running. Your newer edits "
        "were preserved; run the instruction again from the current version."
    ),
    "base_version": 0,
    "current_version": 3,
    "operations": [],
    "preview_paths": [],
    "doc_kind": "web",
}


@pytest.fixture(scope="module")
def registry() -> Any:
    with hermetic_flag_env():
        return build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))


class _FakeLane:
    """Completes the dispatched run terminally with a canned result, capturing envelopes."""

    def __init__(
        self,
        *,
        conn_factory: Any,
        status: str = "succeeded",
        result: dict[str, Any] | None = None,
    ) -> None:
        self._conn_factory = conn_factory
        self._status = status
        self._result = result
        self.envelopes: list[Any] = []

    async def drive(self, *, envelope: Any) -> None:
        self.envelopes.append(envelope)
        async with self._conn_factory() as conn:
            await design_runs.set_run_result(
                conn,
                workspace_id=envelope.workspace_id,
                run_id=envelope.run_id,
                status=self._status,
                result=(
                    self._result
                    if self._result is not None
                    else {
                        "schema_version": 1,
                        "status": "accepted",
                        "stop_reason": "Visual reviewer accepted the artboard.",
                    }
                ),
            )


def _web_doc(document_id: str, title: str = "Harbor & Sage") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "id": document_id,
        "title": title,
        "theme": {},
        "pages": [{"id": "home", "nodes": {"root": {"kind": "root"}}}],
    }


async def _seed_leg_conversation(
    conn: AsyncConnection,
    *,
    storage_root: Path,
    label: str,
    document_id: str | None = None,
) -> dict[str, Any]:
    """Workspace + project + thread + delegating execution + an OPEN design leg.

    ``document_id`` pins the leg to a document exactly as ``open_design_leg`` does.
    """

    workspace_id = f"ws_genweb_{label}_{uuid4().hex[:8]}"
    project = await seed_project(conn, workspace_id, name=f"genweb {label}")
    await seed_principal(
        conn,
        workspace_id=workspace_id,
        user_id=USER_ID,
        membership_id=f"wsm_genweb_{workspace_id}",
    )
    thread_id = f"thr_genweb_{label}"
    await conn.execute(
        text("INSERT INTO agent_thread (id, workspace_id, project_id) VALUES (:id, :ws, :project)"),
        {"id": thread_id, "ws": workspace_id, "project": project.project_id},
    )
    parent_execution_id = uuid5(NAMESPACE_URL, f"genweb:{label}:delegating-execution")
    await conn.execute(
        text(
            "INSERT INTO execution "
            "(id, workspace_id, project_id, started_by, parameter_manifest_hash, "
            " pin_manifest_hash) "
            "VALUES (:id, :workspace, :project, 'human', :hash, :hash)"
        ),
        {
            "id": parent_execution_id,
            "workspace": workspace_id,
            "project": project.project_id,
            "hash": "0" * 64,
        },
    )
    conn_factory = conn_session_factory(conn)
    storage = FsStorage(storage_root / "artifacts")
    artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=conn_factory)
    bundle_ref = await artifacts.persist_body(
        workspace_id=workspace_id,
        data=json.dumps(
            {
                "schema_version": "1",
                "bundle_kind": "design_delegation",
                "workspace_id": workspace_id,
                "leg_id": "pending",
                "brief": "A coffee-roastery landing page.",
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode(),
        media_type=DESIGN_DELEGATION_BUNDLE_MEDIA_TYPE,
    )
    leg = await design_legs.open_leg(
        conn,
        workspace_id=workspace_id,
        thread_id=thread_id,
        parent_execution_id=parent_execution_id,
        bundle_artifact_ref=bundle_ref.artifact_key,
        document_id=document_id,
    )
    return {
        "workspace_id": workspace_id,
        "project": project,
        "thread_id": thread_id,
        "parent_execution_id": parent_execution_id,
        "leg": leg,
        "conn_factory": conn_factory,
        "storage": storage,
        "artifacts": artifacts,
    }


async def _seed_web_leg(
    conn: AsyncConnection, *, storage_root: Path, label: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    """A leg pinned to a real ``doc_kind='web'`` document."""

    document_id = f"doc_genweb_{label}_{uuid4().hex[:8]}"
    seeds = await _seed_leg_conversation(conn, storage_root=storage_root, label=label)
    document = await create_document(
        conn,
        workspace_id=seeds["workspace_id"],
        scene=_web_doc(document_id),
        doc_kind="web",
    )
    await conn.execute(
        text("UPDATE design_leg SET document_id = :doc WHERE id = CAST(:leg AS uuid)"),
        {"doc": document["id"], "leg": seeds["leg"]["id"]},
    )
    seeds["leg"] = await design_legs.get_leg(
        conn, workspace_id=seeds["workspace_id"], leg_id=seeds["leg"]["id"]
    )
    return seeds, document


async def _submit_message(
    conn: AsyncConnection,
    seeds: dict[str, Any],
    *,
    label: str,
    message: str,
    previous_turn_outcome: str | None = None,
) -> AgentTurnSubmissionRow:
    turn_id = uuid5(NAMESPACE_URL, f"genweb:{label}:turn")
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
    submission, _created = await insert_submission(
        conn,
        turn_id=turn_id,
        workspace_id=seeds["workspace_id"],
        project_id=seeds["project"].project_id,
        thread_id=seeds["thread_id"],
        submitted_by_user_id=USER_ID,
        submitted_via_membership_id=f"wsm_genweb_{seeds['workspace_id']}",
        onboarding_input_id=captured.onboarding_input_id,
        message_artifact_key=captured.artifact_ref.artifact_key,
        message_sha256=captured.artifact_ref.sha256,
        idempotency_key=f"genweb-{label}",
        previous_turn_outcome=previous_turn_outcome,
    )
    return submission


def _runner(seeds: dict[str, Any], registry: Any, lane: Any) -> DesignLegTurnRunner:
    return DesignLegTurnRunner(
        profiles=registry,
        artifacts=seeds["artifacts"],
        turns=DbAgentTurnJournal(conn_factory=seeds["conn_factory"]),
        history=DbAgentHistoryStore(conn_factory=seeds["conn_factory"]),
        lane=lane,
        conn_factory=seeds["conn_factory"],
    )


def _card_payload(seeds: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1",
        "card_kind": "project_conversation",
        "project": {
            "project_id": seeds["project"].project_id,
            "workspace_id": seeds["workspace_id"],
        },
        "thread": {"thread_id": seeds["thread_id"]},
    }


async def _run_turn(
    conn: AsyncConnection,
    seeds: dict[str, Any],
    registry: Any,
    lane: Any,
    submission: AgentTurnSubmissionRow,
    focus_refs: tuple[DomainObjectRef, ...] = (),
) -> Any:
    leg = await design_legs.get_open_leg_for_thread(
        conn, workspace_id=seeds["workspace_id"], thread_id=seeds["thread_id"]
    )
    assert leg is not None
    user_message_ref = await message_artifact_ref(conn, submission)
    return await _runner(seeds, registry, lane).run_leg_turn(
        submission=submission,
        leg=leg,
        user_message_ref=user_message_ref,
        focus_refs=focus_refs,
        card_payload=_card_payload(seeds),
        stream=None,
    )


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


# --- the web branch ----------------------------------------------------------------------------


def test_a_web_document_leg_dispatches_a_web_turn_envelope(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """B1: doc_kind='web' -> kind='web_turn' + a WebTurnRequest-shaped request."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds, document = await _seed_web_leg(conn, storage_root=tmp_path, label="webkind")
            registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            lane = _FakeLane(conn_factory=seeds["conn_factory"], result=APPLIED_WEB_RESULT)
            submission = await _submit_message(
                conn,
                seeds,
                label="webkind",
                message="Build a landing page for Harbor & Sage.",
                previous_turn_outcome="clarification_requested",
            )
            result = await _run_turn(conn, seeds, registry, lane, submission)
            assert result.outcome.status is AgentExecutionStatus.AWAITING_INPUT

            envelope = lane.envelopes[0]
            assert envelope.kind == "web_turn"
            assert envelope.document_id == document["id"]
            # §4.2: the request is WebTurnRequest-shaped — prompt + base_version only.
            # `previous_turn_outcome` is NOT a WebTurnRequest field and is dropped by design.
            assert envelope.config["request"] == {
                "prompt": "Build a landing page for Harbor & Sage.",
                "base_version": document["current_version"],
            }
            # Everything else the leg carries is untouched by the branch.
            assert envelope.config["delegation_bundle"]["bundle_kind"] == "design_delegation"
            assert envelope.config["leg"]["leg_id"] == seeds["leg"]["id"]
            assert envelope.config["history"] == []

            # The row records the real kind, so an operator (and the fleet) sees a web turn.
            run_id = design_leg_run_id(submission.turn_id)
            kind = (
                await conn.execute(
                    text(
                        "SELECT kind FROM design_agent_run "
                        "WHERE run_id = :run AND workspace_id = :ws"
                    ),
                    {"run": run_id, "ws": seeds["workspace_id"]},
                )
            ).scalar_one()
            assert str(kind) == "web_turn"

    run_async(scenario())


def test_the_web_envelope_pins_the_documents_current_version(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """`base_version` is read at envelope build — the CURRENT version, not the leg's guard."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds, document = await _seed_web_leg(conn, storage_root=tmp_path, label="version")
            # A human edit lands between the leg opening and this turn: v0 -> v1.
            edited = await update_web_document(
                conn,
                workspace_id=seeds["workspace_id"],
                document_id=document["id"],
                web_doc=_web_doc(document["id"], title="Harbor & Sage (edited)"),
                intent="manual",
                checkpoint_label=None,
                operations=[{"op": "set_title"}],
                inverse_operations=None,
                actor_kind="human",
                source="editor",
            )
            assert edited["current_version"] == document["current_version"] + 1

            registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            lane = _FakeLane(conn_factory=seeds["conn_factory"], result=APPLIED_WEB_RESULT)
            submission = await _submit_message(
                conn, seeds, label="version", message="Warm up the palette."
            )
            await _run_turn(conn, seeds, registry, lane, submission)

            assert lane.envelopes[0].config["request"]["base_version"] == edited["current_version"]

    run_async(scenario())


def test_an_applied_web_turn_lands_a_thread_summary_naming_the_document(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """The web result feeds the same thread-summary write — truthfully, naming the artifact."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds, document = await _seed_web_leg(conn, storage_root=tmp_path, label="summary")
            registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            lane = _FakeLane(conn_factory=seeds["conn_factory"], result=APPLIED_WEB_RESULT)
            submission = await _submit_message(
                conn, seeds, label="summary", message="Build the page."
            )
            result = await _run_turn(conn, seeds, registry, lane, submission)

            assert result.assistant_message == (
                f"Design turn applied on website document {document['id']} "
                "(now version 1): Built a three-section landing page."
            )
            roles = (
                await conn.execute(
                    text(
                        "SELECT role FROM agent_thread_message "
                        "WHERE workspace_id = :ws AND thread_id = :thread ORDER BY sequence"
                    ),
                    {"ws": seeds["workspace_id"], "thread": seeds["thread_id"]},
                )
            ).scalars()
            assert list(roles) == ["user", "assistant"]

    run_async(scenario())


def test_a_conflicted_web_turn_surfaces_an_honest_failed_turn(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """A lost CAS race is never a silent success: the turn fails, nothing is told to the user."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds, _document = await _seed_web_leg(conn, storage_root=tmp_path, label="conflict")
            registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            lane = _FakeLane(
                conn_factory=seeds["conn_factory"],
                status="failed",  # execute_web_turn_job: succeeded iff status == "applied"
                result=CONFLICTED_WEB_RESULT,
            )
            submission = await _submit_message(
                conn, seeds, label="conflict", message="Make the hero taller."
            )
            result = await _run_turn(conn, seeds, registry, lane, submission)

            assert result.outcome.status is AgentExecutionStatus.FAILED
            assert result.outcome.failure_code == "design_leg_turn_failed"
            assert result.assistant_message is None
            roles = (
                await conn.execute(
                    text(
                        "SELECT role FROM agent_thread_message "
                        "WHERE workspace_id = :ws AND thread_id = :thread ORDER BY sequence"
                    ),
                    {"ws": seeds["workspace_id"], "thread": seeds["thread_id"]},
                )
            ).scalars()
            assert list(roles) == ["user"]  # no manufactured assistant reply
            # No finalization authority was committed for a turn that changed nothing.
            commits = (
                await conn.execute(
                    text("SELECT count(*) FROM agent_finalization_commit WHERE turn_id = :turn"),
                    {"turn": submission.turn_id},
                )
            ).scalar_one()
            assert int(commits) == 0
            leg_after = await design_legs.get_leg(
                conn, workspace_id=seeds["workspace_id"], leg_id=seeds["leg"]["id"]
            )
            assert leg_after["state"] == "open_awaiting_user"

    run_async(scenario())


# --- the scene regression ----------------------------------------------------------------------


def test_a_scene_document_leg_keeps_the_agent_turn_envelope_byte_for_byte(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """doc_kind='scene' dispatches EXACTLY the shipped envelope — canonical bytes compared."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="scene")
            document = await create_document(
                conn,
                workspace_id=seeds["workspace_id"],
                scene={"meta": {"id": "doc_genweb_scene", "title": "Launch artboard"}},
            )
            await conn.execute(
                text("UPDATE design_leg SET document_id = :doc WHERE id = CAST(:leg AS uuid)"),
                {"doc": document["id"], "leg": seeds["leg"]["id"]},
            )
            registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            lane = _FakeLane(conn_factory=seeds["conn_factory"])
            submission = await _submit_message(
                conn,
                seeds,
                label="scene",
                message="Make the headline two lines.",
                previous_turn_outcome="clarification_requested",
            )
            result = await _run_turn(conn, seeds, registry, lane, submission)

            envelope = lane.envelopes[0]
            assert envelope.kind == "agent_turn"
            assert _canonical(envelope.config["request"]) == _canonical(
                {
                    "prompt": "Make the headline two lines.",
                    "scene": {"meta": {"id": document["id"], "title": "Launch artboard"}},
                    "document_id": document["id"],
                    "previous_turn_outcome": "clarification_requested",
                }
            )
            # …and the scene summary text is unchanged.
            assert result.assistant_message == (
                "Design turn accepted: Visual reviewer accepted the artboard."
            )
            kind = (
                await conn.execute(
                    text(
                        "SELECT kind FROM design_agent_run "
                        "WHERE run_id = :run AND workspace_id = :ws"
                    ),
                    {"run": design_leg_run_id(submission.turn_id), "ws": seeds["workspace_id"]},
                )
            ).scalar_one()
            assert str(kind) == "agent_turn"

    run_async(scenario())


def test_a_document_less_leg_still_dispatches_a_scene_agent_turn(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """No pinned document = nothing to read a kind from: the shipped scene path, unchanged."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="nodoc")
            registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            lane = _FakeLane(conn_factory=seeds["conn_factory"])
            submission = await _submit_message(
                conn, seeds, label="nodoc", message="Sketch something."
            )
            await _run_turn(conn, seeds, registry, lane, submission)

            envelope = lane.envelopes[0]
            assert envelope.kind == "agent_turn"
            assert envelope.config["request"] == {
                "prompt": "Sketch something.",
                "scene": {},
                "document_id": None,
                "previous_turn_outcome": None,
            }

    run_async(scenario())
