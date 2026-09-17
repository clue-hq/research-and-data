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
from clue_design.accounts import create_web_account
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
    conn: AsyncConnection,
    *,
    storage_root: Path,
    label: str,
    account_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """A leg pinned to a real ``doc_kind='web'`` document."""

    document_id = f"doc_genweb_{label}_{uuid4().hex[:8]}"
    seeds = await _seed_leg_conversation(conn, storage_root=storage_root, label=label)
    document = await create_document(
        conn,
        workspace_id=seeds["workspace_id"],
        scene=_web_doc(document_id),
        doc_kind="web",
        account_id=account_id,
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


def test_web_annotations_ride_the_request_as_target_ids_and_notes(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """Annotated `design_node` refs become `target_node_ids` + ordered `target_notes`.

    The keys appear ONLY here — a turn the human pointed at nothing keeps the plan-F4 v1
    request byte-for-byte (pinned by the dispatch test above).
    """

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds, document = await _seed_web_leg(conn, storage_root=tmp_path, label="annot")
            registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            lane = _FakeLane(conn_factory=seeds["conn_factory"], result=APPLIED_WEB_RESULT)
            submission = await _submit_message(
                conn, seeds, label="annot", message="Two fixes, please."
            )

            def ref(object_type: str, object_id: str, note: str | None = None) -> DomainObjectRef:
                return DomainObjectRef(
                    workspace_id=seeds["workspace_id"],
                    object_type=object_type,
                    object_id=object_id,
                    note=note,
                )

            await _run_turn(
                conn,
                seeds,
                registry,
                lane,
                submission,
                focus_refs=(
                    ref("design_document", document["id"]),
                    ref(
                        "design_node", "root#:nth-child(1) > :nth-child(2)", "1. Make this shorter"
                    ),
                    ref("design_node", "root", "2. Remove this"),
                ),
            )

            request = lane.envelopes[0].config["request"]
            # The owning node is named once; the notes keep every annotation, in order.
            assert request["target_node_ids"] == ["root"]
            assert request["target_notes"] == [
                {
                    "target": "root",
                    "path": ":nth-child(1) > :nth-child(2)",
                    "note": "1. Make this shorter",
                },
                {"target": "root", "path": None, "note": "2. Remove this"},
            ]
            assert request["prompt"] == "Two fixes, please."

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


# --- G1: the finalized-document gate -------------------------------------------------------------


async def _turn_facts(conn: AsyncConnection, seeds: dict[str, Any], turn_id: Any) -> dict[str, Any]:
    """What a refused turn must leave behind: no run, no reply, no finalization, leg open."""

    runs = (
        await conn.execute(
            text("SELECT count(*) FROM design_agent_run WHERE run_id = :run"),
            {"run": design_leg_run_id(turn_id)},
        )
    ).scalar_one()
    roles = (
        await conn.execute(
            text(
                "SELECT role FROM agent_thread_message "
                "WHERE workspace_id = :ws AND thread_id = :thread ORDER BY sequence"
            ),
            {"ws": seeds["workspace_id"], "thread": seeds["thread_id"]},
        )
    ).scalars()
    commits = (
        await conn.execute(
            text("SELECT count(*) FROM agent_finalization_commit WHERE turn_id = :turn"),
            {"turn": turn_id},
        )
    ).scalar_one()
    leg = await design_legs.get_leg(
        conn, workspace_id=seeds["workspace_id"], leg_id=seeds["leg"]["id"]
    )
    return {
        "runs": int(runs),
        "roles": list(roles),
        "commits": int(commits),
        "leg_state": leg["state"],
    }


def test_a_finalized_web_document_refuses_the_turn(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """G1: a finalized document is never mutated — the turn refuses BEFORE any design run."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds, document = await _seed_web_leg(conn, storage_root=tmp_path, label="finalweb")
            await conn.execute(
                text("UPDATE design_document SET status = 'finalized' WHERE id = :d"),
                {"d": document["id"]},
            )
            registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            lane = _FakeLane(conn_factory=seeds["conn_factory"], result=APPLIED_WEB_RESULT)
            submission = await _submit_message(
                conn, seeds, label="finalweb", message="Change the hero copy."
            )
            result = await _run_turn(conn, seeds, registry, lane, submission)

            assert result.outcome.status is AgentExecutionStatus.FAILED
            assert result.outcome.failure_code == "design_leg_document_finalized"
            assert result.assistant_message is None
            assert lane.envelopes == []  # nothing was dispatched
            facts = await _turn_facts(conn, seeds, submission.turn_id)
            assert facts == {
                "runs": 0,
                "roles": ["user"],
                "commits": 0,
                "leg_state": "open_awaiting_user",
            }

    run_async(scenario())


def test_a_finalized_scene_document_refuses_the_turn_the_same_way(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """G1 is about mutation, not doc kind — and the SCENE half of the substrate's own
    ``is_finalized_document`` (a draft row whose scene carries a finalized status) counts."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="finalscene")
            document = await create_document(
                conn,
                workspace_id=seeds["workspace_id"],
                scene={
                    "meta": {
                        "id": "doc_genweb_finalscene",
                        "title": "Launch artboard",
                        "status": {"kind": "finalized"},
                    }
                },
            )
            await conn.execute(
                text("UPDATE design_leg SET document_id = :doc WHERE id = CAST(:leg AS uuid)"),
                {"doc": document["id"], "leg": seeds["leg"]["id"]},
            )
            # Isolate the SCENE branch of the mirrored predicate: the row says draft, the
            # scene says finalized, and the gate must still refuse.
            await conn.execute(
                text("UPDATE design_document SET status = 'draft' WHERE id = :d"),
                {"d": document["id"]},
            )
            registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            lane = _FakeLane(conn_factory=seeds["conn_factory"])
            submission = await _submit_message(
                conn, seeds, label="finalscene", message="Make the headline two lines."
            )
            result = await _run_turn(conn, seeds, registry, lane, submission)

            assert result.outcome.status is AgentExecutionStatus.FAILED
            assert result.outcome.failure_code == "design_leg_document_finalized"
            assert lane.envelopes == []
            facts = await _turn_facts(conn, seeds, submission.turn_id)
            assert facts["runs"] == 0
            assert facts["roles"] == ["user"]
            assert facts["leg_state"] == "open_awaiting_user"

    run_async(scenario())


def test_a_published_web_document_still_dispatches(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """G1's other half: published is NOT finalized.

    Publishing a web document writes a ``design_web_publish`` row and leaves the document row
    ``draft`` (``clue_design.publishes``), so the realistic case is exercised by the plain draft
    document; the ``status = 'published'`` row below pins the ruling literally — a document
    carrying that word is still editable, exactly as the substrate's own predicate says.
    """

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds, document = await _seed_web_leg(conn, storage_root=tmp_path, label="published")
            await conn.execute(
                text("UPDATE design_document SET status = 'published' WHERE id = :d"),
                {"d": document["id"]},
            )
            registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            lane = _FakeLane(conn_factory=seeds["conn_factory"], result=APPLIED_WEB_RESULT)
            submission = await _submit_message(
                conn, seeds, label="published", message="Warm up the palette."
            )
            result = await _run_turn(conn, seeds, registry, lane, submission)

            assert result.outcome.status is AgentExecutionStatus.AWAITING_INPUT
            assert lane.envelopes[0].kind == "web_turn"

    run_async(scenario())


# --- G2: the frozen account card -----------------------------------------------------------------


async def _seed_account(
    conn: AsyncConnection, *, workspace_id: str, account_id: str
) -> dict[str, Any]:
    return await create_web_account(
        conn,
        workspace_id=workspace_id,
        account_id=account_id,
        name="Northwind Logistics",
        domain="northwind.example",
        logo_asset_id=None,
        data={"industry": "freight", "hq": "Rotterdam"},
        notes="Prefers plain language; no jargon.",
    )


def test_an_account_stamped_web_document_freezes_the_account_card(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """G2: the pinned document's account is resolved in-workspace and frozen BY VALUE."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="acctcard")
            account_id = f"acct_genweb_{uuid4().hex[:8]}"
            await _seed_account(conn, workspace_id=seeds["workspace_id"], account_id=account_id)
            document_id = f"doc_genweb_acctcard_{uuid4().hex[:8]}"
            document = await create_document(
                conn,
                workspace_id=seeds["workspace_id"],
                scene=_web_doc(document_id),
                doc_kind="web",
                account_id=account_id,
            )
            await conn.execute(
                text("UPDATE design_leg SET document_id = :doc WHERE id = CAST(:leg AS uuid)"),
                {"doc": document["id"], "leg": seeds["leg"]["id"]},
            )
            registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            lane = _FakeLane(conn_factory=seeds["conn_factory"], result=APPLIED_WEB_RESULT)
            submission = await _submit_message(
                conn, seeds, label="acctcard", message="Build the page for Northwind."
            )
            result = await _run_turn(conn, seeds, registry, lane, submission)
            assert result.outcome.status is AgentExecutionStatus.AWAITING_INPUT

            # The design route's card, key for key — the executor reads only this key.
            assert lane.envelopes[0].config["account_card"] == {
                "name": "Northwind Logistics",
                "domain": "northwind.example",
                "logo_asset_id": None,
                "data": {"industry": "freight", "hq": "Rotterdam"},
                "notes": "Prefers plain language; no jargon.",
            }

    run_async(scenario())


def test_a_web_document_naming_an_unresolvable_account_refuses_the_turn(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """G2 fail-closed: never a silent un-personalized run.

    ``design_document_account_fk`` normally makes an unresolvable stamp impossible (and
    SET-NULLs it on account deletion), so the constraint is dropped inside this rolled-back
    transaction to reach the guard the founder ruling asks for — the platform must not trust
    the FK to be the only thing standing between a stale stamp and a generic page.
    """

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds, document = await _seed_web_leg(conn, storage_root=tmp_path, label="acctgone")
            await conn.execute(
                text("ALTER TABLE design_document DROP CONSTRAINT design_document_account_fk")
            )
            await conn.execute(
                text("UPDATE design_document SET account_id = :a WHERE id = :d"),
                {"a": "acct_vanished", "d": document["id"]},
            )
            registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            lane = _FakeLane(conn_factory=seeds["conn_factory"], result=APPLIED_WEB_RESULT)
            submission = await _submit_message(
                conn, seeds, label="acctgone", message="Personalize the hero."
            )
            result = await _run_turn(conn, seeds, registry, lane, submission)

            assert result.outcome.status is AgentExecutionStatus.FAILED
            assert result.outcome.failure_code == "design_leg_account_unresolved"
            assert result.assistant_message is None
            assert lane.envelopes == []
            facts = await _turn_facts(conn, seeds, submission.turn_id)
            assert facts == {
                "runs": 0,
                "roles": ["user"],
                "commits": 0,
                "leg_state": "open_awaiting_user",
            }

    run_async(scenario())


def test_an_account_less_web_document_carries_no_account_card_key(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """G2 regression: no account stamp -> the slice-1 envelope, byte for byte."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds, document = await _seed_web_leg(conn, storage_root=tmp_path, label="noacct")
            registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            lane = _FakeLane(conn_factory=seeds["conn_factory"], result=APPLIED_WEB_RESULT)
            submission = await _submit_message(
                conn, seeds, label="noacct", message="Build the page."
            )
            await _run_turn(conn, seeds, registry, lane, submission)

            config = lane.envelopes[0].config
            assert "account_card" not in config
            assert _canonical(config) == _canonical(
                {
                    "request": {
                        "prompt": "Build the page.",
                        "base_version": document["current_version"],
                    },
                    "delegation_bundle": config["delegation_bundle"],
                    "history": [],
                    "leg": config["leg"],
                }
            )

    run_async(scenario())


def test_a_scene_leg_turn_freezes_the_ad_lane_at_offer_time(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    migrated_db: bool,  # noqa: F811
) -> None:
    """W4 offer-time freeze (Wave-C fix #1): the agent_turn envelope ALWAYS carries the
    ``ad_lane`` key — a frozen null when the offering process's flag is off, the lane by
    value when it is on — so the claiming worker's own flag can never silently strip the
    turn's auto-references (the Wave-B W-B2 failure). The web executor never consumes the
    lane, so a web_turn envelope carries no such key (pinned by the full-config assertion in
    the account-less web test above)."""

    if not migrated_db:
        pytest.skip("database not reachable")

    frozen_by_value = {
        "card": {"prose": "bold and yellow"},
        "creative_assets": {"cr_1": "asset_1"},
        "pregenerated": [],
    }

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="adlane")
            registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))

            # Offer 1: flag OFF in the offering process — the frozen decision is "no lane".
            monkeypatch.delenv("LUMEN_BRAND_AD_ASSETS", raising=False)
            lane = _FakeLane(conn_factory=seeds["conn_factory"])
            submission = await _submit_message(conn, seeds, label="adlane", message="Sketch an ad.")
            await _run_turn(conn, seeds, registry, lane, submission)
            envelope = lane.envelopes[0]
            assert envelope.kind == "agent_turn"
            assert "ad_lane" in envelope.config  # the key is the decision record
            assert envelope.config["ad_lane"] is None

            # Offer 2: flag ON — the reduced lane rides the envelope by value, through the
            # shared substrate composer (stubbed here; its reduction is pinned by the design
            # suite's round-trip tests over the same functions).
            monkeypatch.setenv("LUMEN_BRAND_AD_ASSETS", "1")

            async def fake_frozen_lane(conn: object, *, workspace_id: str) -> dict:
                assert workspace_id == seeds["workspace_id"]
                return dict(frozen_by_value)

            from clue_api import design_leg_wiring as wiring_module

            monkeypatch.setattr(wiring_module.design_ad_assets, "frozen_ad_lane", fake_frozen_lane)
            lane_on = _FakeLane(conn_factory=seeds["conn_factory"])
            submission_on = await _submit_message(
                conn, seeds, label="adlane2", message="Sketch another ad."
            )
            await _run_turn(conn, seeds, registry, lane_on, submission_on)
            assert lane_on.envelopes[0].config["ad_lane"] == frozen_by_value

    run_async(scenario())
