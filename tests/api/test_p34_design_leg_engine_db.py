"""P3.4 acceptance — the design-leg turn engine (PD-part3 §1-D1/D3, §2.4).

The worker-side half of the routing rule: a user message on a thread with an open leg
becomes a **design turn** — an ``agent_turn`` row (role=``design``, execution parented
under the delegating platform execution), a leg-scoped history append, a deterministic
``design_agent_run`` dispatched through the design lane seam, and an honest committed
finalization (``awaiting_input`` with the leg as the open interaction). Head-of-abm's
machinery is never touched while the leg is open, and its thread history never ingests
the leg's transcript (§2.4).

The lane driver is faked here — the *real* driver is the design fleet handler
(P3.2 proved the runtime itself end-to-end); what this suite pins is the platform
substrate around it: journaling, attribution, replay convergence, leg state, scoping.

All writes run in rolled-back transactions against the session-migrated DB.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import AgentExecutionStatus, DomainObjectRef
from clue_api.agent_registry_wiring import build_agent_profile_registry
from clue_api.agent_turn_submission import (
    AgentTurnSubmissionRow,
    insert_submission,
    message_artifact_ref,
    submission_context_refs,
)
from clue_api.agent_turn_wiring import (
    DbAgentHistoryStore,
    DbAgentTurnJournal,
    DurableAgentArtifactStore,
)
from clue_api.chat.turn_events import list_turn_events
from clue_api.chat.turn_stream import TurnStreamEmitter, TurnStreamPolicy
from clue_api.conversation_capture import persist_user_turn
from clue_api.design_leg_tools import DESIGN_DELEGATION_BUNDLE_MEDIA_TYPE
from clue_api.design_leg_wiring import (
    DesignLegTurnRunner,
    _assistant_summary,
    clarification_sentence,
    design_leg_run_id,
    load_design_leg_history,
    load_head_of_abm_history,
)
from clue_api.toolbelt_wiring import build_toolbelt
from clue_design import accounts as design_accounts
from clue_design import legs as design_legs
from clue_design import runs as design_runs
from clue_design.documents import create_document, set_document_account
from clue_design.exit_judgment import ExitJudgment
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

USER_ID = "usr_p34_engine"
NOW_UTC = datetime(2026, 8, 14, 13, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def registry() -> Any:
    with hermetic_flag_env():
        return build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))


class _FakeLane:
    """Completes the dispatched run terminally, capturing the envelope for assertions."""

    def __init__(self, *, conn_factory: Any, status: str = "succeeded") -> None:
        self._conn_factory = conn_factory
        self._status = status
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
                    {
                        "schema_version": 1,
                        "status": "accepted",
                        "stop_reason": "Visual reviewer accepted the artboard.",
                    }
                    if self._status == "succeeded"
                    else {
                        "schema_version": 1,
                        "status": "failed",
                        "error": {"code": "agent_runtime.failed", "message": "boom"},
                    }
                ),
            )


class _BatchFakeLane(_FakeLane):
    """A fake lane that also answers the multi-document seam (§3.3's ``drive_batch``),
    completing every sibling the turn dispatched in the order it was handed them."""

    async def drive_batch(self, *, envelopes: Any) -> None:
        for envelope in envelopes:
            await self.drive(envelope=envelope)


#: The one question the clarifying fake lane asks, reused by the assertions below.
CLARIFYING_QUESTION = "Which proof point should lead the ad?"


class _ClarifyingFakeLane(_FakeLane):
    """A lane whose run stops to ASK instead of designing (spec 2026-09-20 §2.1).

    Only the FIRST dispatch clarifies: the follow-up turn of the test answers the question,
    and a lane that asked again forever could never prove the guard is armed.
    """

    async def drive(self, *, envelope: Any) -> None:
        self.envelopes.append(envelope)
        if len(self.envelopes) > 1:
            async with self._conn_factory() as conn:
                await design_runs.set_run_result(
                    conn,
                    workspace_id=envelope.workspace_id,
                    run_id=envelope.run_id,
                    status="succeeded",
                    result={
                        "schema_version": 1,
                        "status": "accepted",
                        "stop_reason": "Visual reviewer accepted the artboard.",
                    },
                )
            return
        async with self._conn_factory() as conn:
            await design_runs.set_run_result(
                conn,
                workspace_id=envelope.workspace_id,
                run_id=envelope.run_id,
                status="succeeded",
                result={
                    "schema_version": 1,
                    "status": "clarification_requested",
                    "stop_reason": "clarification_requested",
                    "summary": "Asked before designing.",
                    "clarification": {
                        "questions": [
                            {
                                "id": "proof",
                                "question": CLARIFYING_QUESTION,
                                "why_it_matters": "It decides the headline.",
                                "options": ["The 40% stat", "The logo wall"],
                                "default": "The 40% stat",
                            }
                        ]
                    },
                },
            )


class _LaneThatMustNotRun:
    async def drive(self, *, envelope: Any) -> None:
        raise AssertionError("a committed design turn must never be re-dispatched")


async def _seed_leg_conversation(
    conn: AsyncConnection,
    *,
    storage_root: Path,
    label: str,
    user_id: str = USER_ID,
) -> dict[str, Any]:
    """Workspace + project + thread + delegating execution + an OPEN design leg.

    ``user_id`` is parameterized for the P3.6 cross-thread concurrency test, whose two
    conversations live on two uncommitted transactions: a shared ``platform_user`` PK
    would make the second seed block on the first's uncommitted insert.
    """

    workspace_id = f"ws_p34e_{label}_{uuid4().hex[:8]}"
    project = await seed_project(conn, workspace_id, name=f"P3.4 engine {label}")
    await seed_principal(
        conn,
        workspace_id=workspace_id,
        user_id=user_id,
        membership_id=f"wsm_p34e_{workspace_id}",
    )
    thread_id = f"thr_p34e_{label}"
    await conn.execute(
        text("INSERT INTO agent_thread (id, workspace_id, project_id) VALUES (:id, :ws, :project)"),
        {"id": thread_id, "ws": workspace_id, "project": project.project_id},
    )
    parent_execution_id = uuid5(NAMESPACE_URL, f"p34e:{label}:delegating-execution")
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
                "brief": "A launch artboard.",
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
        "user_id": user_id,
    }


async def _submit_message(
    conn: AsyncConnection,
    seeds: dict[str, Any],
    *,
    label: str,
    message: str,
    previous_turn_outcome: str | None = None,
    focus_refs: tuple[DomainObjectRef, ...] = (),
    derivation: str | None = None,
    derived_from_turn_id: UUID | None = None,
) -> AgentTurnSubmissionRow:
    turn_id = uuid5(NAMESPACE_URL, f"p34e:{label}:turn")
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
        submitted_by_user_id=seeds.get("user_id", USER_ID),
        submitted_via_membership_id=f"wsm_p34e_{seeds['workspace_id']}",
        onboarding_input_id=captured.onboarding_input_id,
        message_artifact_key=captured.artifact_ref.artifact_key,
        message_sha256=captured.artifact_ref.sha256,
        idempotency_key=f"p34e-{label}",
        context_refs=focus_refs,
        previous_turn_outcome=previous_turn_outcome,
        derivation=derivation,
        derived_from_turn_id=derived_from_turn_id,
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
    stream: Any = None,
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
        stream=stream,
    )


def test_a_design_leg_turn_lands_attribution_history_and_the_stamped_run(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """One user message on an open leg = one design turn, end to end on durable rows."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="land")
            lane = _FakeLane(conn_factory=seeds["conn_factory"])
            registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            focus = DomainObjectRef(
                workspace_id=seeds["workspace_id"],
                object_type="design_document",
                object_id="doc_focus",
                version=None,
            )
            submission = await _submit_message(
                conn,
                seeds,
                label="land",
                message="Make the headline two lines.",
                previous_turn_outcome="clarification_requested",
                focus_refs=(),
            )
            result = await _run_turn(conn, seeds, registry, lane, submission, (focus,))

            # The turn ends awaiting the user's next message — D1's shape — with an honest
            # committed finalization naming the leg as the open interaction.
            assert result.outcome.status is AgentExecutionStatus.AWAITING_INPUT
            assert result.replayed is False
            # Review finding A: the summary must carry the run's OWN terminal result — its
            # status and stop reason — not a generic fallback (the `result_json`-vs-`result`
            # DTO-key bug silently degraded every summary to "Design turn succeeded.").
            assert result.assistant_message == (
                "Design turn accepted: Visual reviewer accepted the artboard."
            )

            turn_row = (
                (
                    await conn.execute(
                        text(
                            "SELECT role, parent_execution_id, submitted_by_user_id, "
                            "workspace_root_id FROM agent_turn WHERE id = :turn"
                        ),
                        {"turn": submission.turn_id},
                    )
                )
                .mappings()
                .one()
            )
            assert turn_row["role"] == "design"
            assert turn_row["parent_execution_id"] == seeds["parent_execution_id"]
            assert turn_row["submitted_by_user_id"] == USER_ID

            run_id = design_leg_run_id(submission.turn_id)
            run = await design_runs.get_run(conn, workspace_id=seeds["workspace_id"], run_id=run_id)
            assert run is not None and run["status"] == "succeeded"
            stamped = (
                (
                    await conn.execute(
                        text(
                            "SELECT leg_id, execution_id FROM design_agent_run "
                            "WHERE run_id = :run AND workspace_id = :ws"
                        ),
                        {"run": run_id, "ws": seeds["workspace_id"]},
                    )
                )
                .mappings()
                .one()
            )
            assert str(stamped["leg_id"]) == seeds["leg"]["id"]
            assert stamped["execution_id"] is not None

            # The envelope carried the §2.3 material by value: bundle, message, leg identity,
            # canvas focus refs, and the clarification echo.
            envelope = lane.envelopes[0]
            assert envelope.kind == "agent_turn"
            config = envelope.config
            assert config["delegation_bundle"]["bundle_kind"] == "design_delegation"
            assert config["request"]["prompt"] == "Make the headline two lines."
            assert config["request"]["previous_turn_outcome"] == "clarification_requested"
            assert config["leg"]["leg_id"] == seeds["leg"]["id"]
            assert config["leg"]["focus_refs"] == [
                {"object_type": "design_document", "object_id": "doc_focus", "version": None}
            ]

            # History: the leg's exchange landed; the leg cycled running -> open_awaiting_user.
            messages = (
                await conn.execute(
                    text(
                        "SELECT role FROM agent_thread_message "
                        "WHERE workspace_id = :ws AND thread_id = :thread ORDER BY sequence"
                    ),
                    {"ws": seeds["workspace_id"], "thread": seeds["thread_id"]},
                )
            ).scalars()
            assert list(messages) == ["user", "assistant"]
            leg_after = await design_legs.get_leg(
                conn, workspace_id=seeds["workspace_id"], leg_id=seeds["leg"]["id"]
            )
            assert leg_after["state"] == "open_awaiting_user"

    run_async(scenario())


async def _pin_document(
    conn: AsyncConnection,
    seeds: dict[str, Any],
    *,
    doc_kind: str,
    version: int,
) -> dict[str, Any]:
    """Create a real design document of ``doc_kind`` at ``version`` and pin the leg to it."""

    document_id = f"doc_p34e_{doc_kind}_{uuid4().hex[:8]}"
    scene: dict[str, Any] = (
        {
            "schema_version": 1,
            "id": document_id,
            "title": "Harbor & Sage",
            "theme": {},
            "pages": [{"id": "home", "nodes": {"root": {"kind": "root"}}}],
        }
        if doc_kind == "web"
        else {
            "schema_version": 1,
            "meta": {"id": document_id, "title": "Launch artboard"},
            "pages": {
                "page_ad": {
                    "id": "page_ad",
                    "name": "Ad",
                    "children": ["frame"],
                }
            },
            "nodes": {
                "frame": {"id": "frame", "children": ["headline"]},
                "headline": {"id": "headline", "children": []},
            },
            "slots": {},
            "assets": {},
            "export_profiles": [],
        }
    )
    document = await create_document(
        conn, workspace_id=seeds["workspace_id"], scene=scene, doc_kind=doc_kind
    )
    await conn.execute(
        text(
            "UPDATE design_document SET current_version = :v WHERE id = :id AND workspace_id = :w"
        ),
        {"v": version, "id": document["id"], "w": seeds["workspace_id"]},
    )
    await conn.execute(
        text("UPDATE design_leg SET document_id = :doc WHERE id = CAST(:leg AS uuid)"),
        {"doc": document["id"], "leg": seeds["leg"]["id"]},
    )
    seeds["leg"] = await design_legs.get_leg(
        conn, workspace_id=seeds["workspace_id"], leg_id=seeds["leg"]["id"]
    )
    return document


@pytest.mark.parametrize(
    ("scope", "expected_outcome"),
    [
        ("design", "accepted by the design review"),
        ("edit", "whole design has not been accepted"),
        (None, "saved as a draft; it has not been accepted"),
    ],
)
def test_scene_summary_distinguishes_acceptance_from_execution_success(
    scope: str | None, expected_outcome: str
) -> None:
    """The four-brand controls shared status/reason despite different verdicts."""
    summary = _assistant_summary(
        {
            "status": "succeeded",
            "result": {
                "status": "proposed",
                "acceptance_scope": scope,
                "stop_reason": "target_exceeded",
                "summary": "Supporting copy still needs a readability check.",
            },
        }
    )
    assert expected_outcome in summary
    assert "time target" in summary
    assert "Supporting copy still needs a readability check." in summary


def test_clarification_sentence_reads_back_the_questions_the_agent_asked() -> None:
    """Spec 2026-09-20 §2.2: the durable thread record of a run that stopped to ask is the
    agent's own questions, verbatim and in order — nothing about drafts or acceptance."""

    assert (
        clarification_sentence(
            {
                "status": "clarification_requested",
                "clarification": {
                    "questions": [{"question": "Which proof point?"}, {"question": "Which tone?"}],
                },
            }
        )
        == "Asked you 2 questions before designing: Which proof point?; Which tone?."
    )


def test_clarification_sentence_says_question_in_the_singular() -> None:
    assert (
        clarification_sentence(
            {
                "status": "clarification_requested",
                "clarification": {"questions": [{"question": "Which proof point?"}]},
            }
        )
        == "Asked you 1 question before designing: Which proof point?."
    )


def test_clarification_sentence_is_none_for_a_run_that_actually_designed() -> None:
    """The branch must not claim a question was asked on an ordinary proposal."""

    assert clarification_sentence({"status": "proposed", "acceptance_scope": "design"}) is None


def test_scene_summary_of_a_clarification_run_asks_rather_than_claiming_a_draft() -> None:
    """A clarification run's design-runtime status is ``clarification_requested`` while the RUN
    row succeeded, so the summarizer must branch on the result — otherwise the thread would
    record "Design saved as a draft" for a turn that saved nothing."""

    summary = _assistant_summary(
        {
            "status": "succeeded",
            "result": {
                "status": "clarification_requested",
                "clarification": {
                    "questions": [
                        {"question": "Which proof point?"},
                        {"question": "Which tone?"},
                    ],
                },
            },
        }
    )
    assert summary == "Asked you 2 questions before designing: Which proof point?; Which tone?."
    assert "draft" not in summary


@pytest.mark.parametrize(
    ("reason", "limit"),
    [
        ("budget_exhausted_wall_clock", "time limit"),
        ("budget_exhausted_llm_calls", "model-call limit"),
        ("cancelled_by_request", "stopped at your request"),
    ],
)
def test_scene_summary_preserves_unaccepted_draft_when_generation_stops(
    reason: str, limit: str
) -> None:
    summary = _assistant_summary(
        {
            "status": "succeeded",
            "result": {
                "status": "proposed",
                "acceptance_scope": None,
                "stop_reason": reason,
                "summary": "Current draft awaits review.",
            },
        }
    )
    assert "saved as a draft; it has not been accepted" in summary
    assert limit in summary
    assert "Current draft awaits review." in summary


def test_scene_acceptance_summary_does_not_change_website_summary() -> None:
    summary = _assistant_summary(
        {
            "status": "succeeded",
            "document_id": "doc_website",
            "result": {
                "doc_kind": "web",
                "status": "completed",
                "current_version": 3,
                "summary": "Updated the hero copy.",
            },
        }
    )
    assert summary == (
        "Design turn completed on website document doc_website (now version 3): "
        "Updated the hero copy."
    )


def test_a_conflicted_scene_result_summarizes_with_the_versions_it_names() -> None:
    """The consuming half of the design side's ``conflicted_agent_turn_response``.

    A scene result's ``stop_reason`` is the ONLY prose ``_assistant_summary`` renders, so this
    pins that a CAS-loss result arrives legible rather than as a bare "Design turn conflicted."

    Honest scope note: today this summarizer is NOT reached for a conflict. The design executor
    reports a conflicted turn with design-run status ``failed``, and ``run_leg_turn`` short-
    circuits any non-``succeeded`` run into ``_fail_turn``, which deliberately manufactures NO
    assistant message — so the thread currently records nothing at all for a lost race. That is
    a real gap, and it is the visible-loop owner's (Task 6/7) to close, by routing a conflicted
    run to a rendered message instead of the generic failure. This test pins the renderer's end
    of the contract so that change is a routing change and not a re-derivation."""

    summary = _assistant_summary(
        {
            "status": "failed",
            "run_id": "run_conflicted",
            "result": {
                "schema_version": 1,
                "status": "conflicted",
                "summary": "This design moved from version 3 to version 4 …",
                "stop_reason": (
                    "This design moved from version 3 to version 4 while the AI turn was "
                    "running, so the turn's changes were not applied. Your newer edits were "
                    "preserved — send the instruction again to design against the current "
                    "version."
                ),
                "base_version": 3,
                "current_version": 4,
            },
        }
    )
    assert summary != "Design turn conflicted."
    assert summary.startswith("Design turn conflicted: ")
    assert "version 3" in summary and "version 4" in summary
    assert "preserved" in summary


def test_a_scene_leg_envelope_carries_the_documents_base_version(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """genad Task 5: the scene executor OWNS the persist, so it needs a CAS base.

    The leg block carries ``document_base_version`` read ONCE here, at freeze time — the same
    posture as the web request's ``base_version`` (which is why a web-pinned leg's block must
    NOT carry the key: web already pins the version inside its own request, and two copies of
    one CAS base is exactly the drift this freeze exists to prevent).
    """

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="casbase")
            registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            document = await _pin_document(conn, seeds, doc_kind="scene", version=3)
            lane = _FakeLane(conn_factory=seeds["conn_factory"])
            submission = await _submit_message(
                conn, seeds, label="casbase", message="Make the headline two lines."
            )
            await _run_turn(conn, seeds, registry, lane, submission)

            envelope = lane.envelopes[0]
            assert envelope.kind == "agent_turn"
            assert envelope.config["leg"]["document_base_version"] == 3
            assert envelope.config["request"]["document_id"] == document["id"]

    run_async(scenario())


def test_a_scene_leg_translates_durable_node_refs_into_the_frozen_request(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """Focused targets are submission receipts first and runtime fields second."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="targets")
            registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            document = await _pin_document(conn, seeds, doc_kind="scene", version=5)
            refs = (
                DomainObjectRef(
                    workspace_id=seeds["workspace_id"],
                    object_type="design_document",
                    object_id=document["id"],
                    version=5,
                ),
                DomainObjectRef(
                    workspace_id=seeds["workspace_id"],
                    object_type="design_node",
                    object_id="headline",
                    version=5,
                ),
            )
            submission = await _submit_message(
                conn,
                seeds,
                label="targets",
                message="Make this bolder.",
                focus_refs=refs,
            )
            durable_refs = await submission_context_refs(
                conn,
                workspace_id=seeds["workspace_id"],
                turn_id=submission.turn_id,
            )
            assert durable_refs == refs

            lane = _FakeLane(conn_factory=seeds["conn_factory"])
            await _run_turn(conn, seeds, registry, lane, submission, durable_refs)

            request = lane.envelopes[0].config["request"]
            assert request["target_node_ids"] == ["headline"]
            assert request["active_page_id"] == "page_ad"
            assert lane.envelopes[0].config["leg"]["focus_refs"] == [
                {
                    "object_type": "design_document",
                    "object_id": document["id"],
                    "version": 5,
                },
                {"object_type": "design_node", "object_id": "headline", "version": 5},
            ]

    run_async(scenario())


def test_a_target_deleted_after_acceptance_fails_the_turn_typed_and_keeps_the_leg_open(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """A durable node target the CURRENT scene no longer carries is a typed refusal.

    Acceptance validated the target against the version the user saw; a manual edit (or an
    earlier queued turn) may delete that node before dispatch. The envelope build re-resolves
    against the current scene and must fail the turn through ``_fail_turn`` with
    ``design_leg_target_unresolved`` — never the ``design_leg_turn_crashed`` containment path —
    and the leg stays open for the user to restate the edit.
    """

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="staletgt")
            registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            document = await _pin_document(conn, seeds, doc_kind="scene", version=5)
            refs = (
                DomainObjectRef(
                    workspace_id=seeds["workspace_id"],
                    object_type="design_document",
                    object_id=document["id"],
                    version=5,
                ),
                DomainObjectRef(
                    workspace_id=seeds["workspace_id"],
                    object_type="design_node",
                    object_id="headline",
                    version=5,
                ),
            )
            submission = await _submit_message(
                conn,
                seeds,
                label="staletgt",
                message="Make this bolder.",
                focus_refs=refs,
            )
            # The interleaved manual edit: the targeted node is gone from the
            # current scene by the time the turn dispatches.
            pruned_scene = dict(document["scene"])
            pruned_scene["nodes"] = {"frame": {"id": "frame", "children": []}}
            await conn.execute(
                text(
                    "UPDATE design_document SET current_scene_json = CAST(:scene AS jsonb) "
                    "WHERE id = :id AND workspace_id = :w"
                ),
                {
                    "scene": json.dumps(pruned_scene),
                    "id": document["id"],
                    "w": seeds["workspace_id"],
                },
            )

            lane = _FakeLane(conn_factory=seeds["conn_factory"])
            result = await _run_turn(conn, seeds, registry, lane, submission, refs)

            assert result.outcome.status is AgentExecutionStatus.FAILED
            assert result.outcome.failure_code == "design_leg_target_unresolved"
            # Nothing was dispatched and no run row was born of the refusal.
            assert lane.envelopes == []
            leg_after = await design_legs.get_leg(
                conn, workspace_id=seeds["workspace_id"], leg_id=seeds["leg"]["id"]
            )
            assert leg_after["state"] == "open_awaiting_user"

    run_async(scenario())


def test_a_web_leg_envelope_carries_no_document_base_version_on_its_leg_block(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """A web-pinned leg's CAS base lives in its request, and nowhere else."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="webbase")
            registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            await _pin_document(conn, seeds, doc_kind="web", version=4)
            lane = _FakeLane(conn_factory=seeds["conn_factory"])
            submission = await _submit_message(
                conn, seeds, label="webbase", message="Warmer palette."
            )
            await _run_turn(conn, seeds, registry, lane, submission)

            envelope = lane.envelopes[0]
            assert envelope.kind == "web_turn"
            assert "document_base_version" not in envelope.config["leg"]
            assert envelope.config["request"]["base_version"] == 4

    run_async(scenario())


def test_a_document_less_leg_envelope_carries_no_document_base_version(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """Legacy (AD4.R-era) legs pin no document at all; the executor must read that as
    'preview-only', so the key is absent rather than a fabricated zero."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="nodoc")
            registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            lane = _FakeLane(conn_factory=seeds["conn_factory"])
            submission = await _submit_message(conn, seeds, label="nodoc", message="Bolder.")
            await _run_turn(conn, seeds, registry, lane, submission)

            assert "document_base_version" not in lane.envelopes[0].config["leg"]

    run_async(scenario())


def test_a_committed_design_turn_replays_and_never_redispatches(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """The convergence guarantee, design edition: replay reads the commit, drives nothing."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="replay")
            registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            submission = await _submit_message(
                conn, seeds, label="replay", message="Try a darker navy."
            )
            first = await _run_turn(
                conn,
                seeds,
                registry,
                _FakeLane(conn_factory=seeds["conn_factory"]),
                submission,
            )
            assert first.replayed is False
            second = await _run_turn(conn, seeds, registry, _LaneThatMustNotRun(), submission)
            assert second.replayed is True
            assert second.outcome.status is AgentExecutionStatus.AWAITING_INPUT
            assert second.assistant_message == first.assistant_message
            messages = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM agent_thread_message "
                        "WHERE workspace_id = :ws AND thread_id = :thread"
                    ),
                    {"ws": seeds["workspace_id"], "thread": seeds["thread_id"]},
                )
            ).scalar_one()
            assert int(messages) == 2

    run_async(scenario())


def test_a_failed_design_run_fails_the_turn_honestly_and_keeps_the_leg_open(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="fail")
            registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            submission = await _submit_message(
                conn, seeds, label="fail", message="Render the impossible."
            )
            result = await _run_turn(
                conn,
                seeds,
                registry,
                _FakeLane(conn_factory=seeds["conn_factory"], status="failed"),
                submission,
            )
            assert result.outcome.status is AgentExecutionStatus.FAILED
            assert result.outcome.failure_code == "design_leg_turn_failed"
            # A failed turn does not close the leg: the user answers, the leg goes on.
            leg_after = await design_legs.get_leg(
                conn, workspace_id=seeds["workspace_id"], leg_id=seeds["leg"]["id"]
            )
            assert leg_after["state"] == "open_awaiting_user"
            commits = (
                await conn.execute(
                    text("SELECT count(*) FROM agent_finalization_commit WHERE turn_id = :turn"),
                    {"turn": submission.turn_id},
                )
            ).scalar_one()
            assert int(commits) == 0  # honest failure: no manufactured finalize authority

    run_async(scenario())


class _LaneThatCrashes:
    """Raises out of the drive — the shape of the 2026-09-20 batch crash (a receipt collision
    after every run had finished), and of any other unexpected raise past ``mark_leg_running``."""

    async def drive(self, *, envelope: Any) -> None:
        raise RuntimeError("boom: the dispatch crashed after the leg was marked running")


def test_a_crashed_dispatch_hands_the_leg_back_instead_of_leaving_it_running(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """Crash containment covers the LEG, not only the turn. Until 2026-09-20 a raise between
    ``mark_leg_running`` and ``_leg_back_to_awaiting`` left the leg ``running`` for good: the
    turn read failed, but the thread refused every later message until a hand repair."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="crash")
            registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            submission = await _submit_message(
                conn, seeds, label="crash", message="Render it, then crash."
            )
            with pytest.raises(RuntimeError, match="boom"):
                await _run_turn(conn, seeds, registry, _LaneThatCrashes(), submission)
            # The crash still surfaces (the fleet task fails loudly) — but the leg is back where
            # the user can speak to it, with its lifecycle frame on the crashed turn.
            leg_after = await design_legs.get_leg(
                conn, workspace_id=seeds["workspace_id"], leg_id=seeds["leg"]["id"]
            )
            assert leg_after["state"] == "open_awaiting_user"
            status = (
                await conn.execute(
                    text(
                        "SELECT status, reason_code FROM agent_turn_event "
                        "WHERE turn_id = :turn ORDER BY seq DESC LIMIT 1"
                    ),
                    {"turn": submission.turn_id},
                )
            ).one()
            assert tuple(status) == ("abandoned", "design_leg_turn_crashed")
            frames = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM agent_turn_event_stream "
                        "WHERE turn_id = :turn AND event_type = 'leg.awaiting_user'"
                    ),
                    {"turn": submission.turn_id},
                )
            ).scalar_one()
            assert int(frames) == 1

    run_async(scenario())


def test_leg_history_is_leg_scoped_and_head_of_abm_never_ingests_it(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """§2.4: design assembles the full leg exchange; head-of-abm's load excludes it."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="scope")
            registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
            cf = seeds["conn_factory"]
            # A pre-leg head-of-abm exchange on the same thread.
            strategy_turn = uuid5(NAMESPACE_URL, "p34e:scope:strategy-turn")
            history = DbAgentHistoryStore(conn_factory=cf)
            strategy_body = await seeds["artifacts"].persist_body(
                workspace_id=seeds["workspace_id"],
                data=b"Let's design a launch artboard.",
                media_type="text/plain",
            )
            await conn.execute(
                text(
                    "INSERT INTO agent_turn "
                    "(id, execution_id, workspace_id, project_id, thread_id, actor_id, role, "
                    " workspace_root_id, profile_name, profile_version, profile_sha256, "
                    " resource_manifest_key, resource_manifest_artifact_sha256, "
                    " resource_manifest_sha256, retention_class, requested_at) "
                    "VALUES (:id, :execution, :workspace, :project, :thread, :actor, "
                    " 'head_of_abm', 'root-p34e', 'head-of-abm', 'v24', :sha, :key, :sha256, "
                    " :sha256, 'test', :at)"
                ),
                {
                    "id": strategy_turn,
                    "execution": seeds["parent_execution_id"],
                    "workspace": seeds["workspace_id"],
                    "project": seeds["project"].project_id,
                    "thread": seeds["thread_id"],
                    "actor": USER_ID,
                    "sha": "0" * 64,
                    "key": strategy_body.artifact_key,
                    "sha256": strategy_body.sha256,
                    "at": NOW_UTC,
                },
            )
            await history.append(
                message_id=uuid5(strategy_turn, "user"),
                turn_id=strategy_turn,
                workspace_id=seeds["workspace_id"],
                thread_id=seeds["thread_id"],
                role="user",
                body_ref=strategy_body,
            )

            submission = await _submit_message(
                conn, seeds, label="scope", message="Bigger logo, please."
            )
            await _run_turn(
                conn,
                seeds,
                registry,
                _FakeLane(conn_factory=seeds["conn_factory"]),
                submission,
            )

            leg_history = await load_design_leg_history(
                cf,
                workspace_id=seeds["workspace_id"],
                thread_id=seeds["thread_id"],
                leg_parent_execution_id=seeds["parent_execution_id"],
            )
            assert [item.role for item in leg_history] == ["user", "assistant"]
            assert all(item.turn_id == submission.turn_id for item in leg_history)

            hoabm_history = await load_head_of_abm_history(
                cf,
                workspace_id=seeds["workspace_id"],
                thread_id=seeds["thread_id"],
            )
            assert [item.turn_id for item in hoabm_history] == [strategy_turn]

    run_async(scenario())


def test_the_first_turn_of_a_leg_runs_every_document_without_the_judge(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """Spec 2026-09-20 §2.3: the leg's first turn is the ask that OPENED the leg, queued by
    ``open_design_leg`` as a derived submission. Nobody has spoken on the leg yet, so there is
    nothing to judge — the exit judge is never asked — and the turn addresses every document
    of the leg. The user row stays (ruling 2026-09-20: only the transcript hides the derived
    bubble), so the turn's thread messages read ``["user", "assistant"]`` like any other.

    The control at the end proves the skip is the DERIVATION's doing and not a dead judge:
    the very same runner, on an ordinary (non-derived) message, reaches the judge.
    """

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="firstturn")
            lane = _BatchFakeLane(conn_factory=seeds["conn_factory"])
            with hermetic_flag_env():
                registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))

            judged: list[dict[str, Any]] = []

            async def judge(**kwargs: Any) -> None:
                # P3.6's fail-safe envelope swallows anything a judge raises, so the raise alone
                # could never fail this test — the call log is what the assertions read. The raise
                # stays because a judge REACHED here is already the bug.
                judged.append(kwargs)
                raise AssertionError("the first turn is never judged")

            async def finisher(**kwargs: Any) -> dict[str, Any]:
                # A judge without a finisher is treated as absent, so the bridge needs both
                # composed for "the judge would have run" to be true at all.
                raise AssertionError("no design-leg first turn exits the leg")

            runner = DesignLegTurnRunner(
                profiles=registry,
                artifacts=seeds["artifacts"],
                turns=DbAgentTurnJournal(conn_factory=seeds["conn_factory"]),
                history=DbAgentHistoryStore(conn_factory=seeds["conn_factory"]),
                lane=lane,
                exit_judge=judge,
                finisher=finisher,
                conn_factory=seeds["conn_factory"],
            )

            async def run(submission: AgentTurnSubmissionRow) -> Any:
                leg = await design_legs.get_open_leg_for_thread(
                    conn, workspace_id=seeds["workspace_id"], thread_id=seeds["thread_id"]
                )
                assert leg is not None
                return await runner.run_leg_turn(
                    submission=submission,
                    leg=leg,
                    user_message_ref=await message_artifact_ref(conn, submission),
                    focus_refs=(),
                    card_payload=_card_payload(seeds),
                    stream=None,
                )

            # A TWO-document leg, so "every document" is a real claim: without the skip this
            # turn would reach the judge, and §3.5's many-document fail-safe would ASK and
            # dispatch nothing at all.
            extra = await _pin_document(conn, seeds, doc_kind="scene", version=1)
            pinned = await _pin_document(conn, seeds, doc_kind="scene", version=1)
            await design_legs.add_leg_documents(
                conn,
                workspace_id=seeds["workspace_id"],
                leg_id=seeds["leg"]["id"],
                documents=[
                    design_legs.LegDocumentSpec(
                        document_id=pinned["id"], position=0, note="the hero artboard"
                    ),
                    design_legs.LegDocumentSpec(
                        document_id=extra["id"], position=1, note="the square cut"
                    ),
                ],
            )

            # The head-of-abm turn whose bytes ``open_design_leg`` carried onto the leg. The
            # column carries no FK, so the seed names it rather than journaling a whole turn.
            opening_turn = uuid5(NAMESPACE_URL, "p34e:firstturn:opening-turn")
            first = await _submit_message(
                conn,
                seeds,
                label="firstturn-1",
                message="A launch artboard for the spring push.",
                derivation="design_leg_first_turn",
                derived_from_turn_id=opening_turn,
            )
            assert first.derivation == "design_leg_first_turn"

            result = await run(first)

            assert judged == []  # the judge was never asked
            assert result.outcome.status is AgentExecutionStatus.AWAITING_INPUT
            # Every document of the leg was dispatched — both of them, in position order.
            assert [str(envelope.document_id) for envelope in lane.envelopes] == [
                pinned["id"],
                extra["id"],
            ]
            roles = (
                await conn.execute(
                    text(
                        "SELECT role FROM agent_thread_message "
                        "WHERE workspace_id = :ws AND turn_id = :turn ORDER BY sequence"
                    ),
                    {"ws": seeds["workspace_id"], "turn": first.turn_id},
                )
            ).scalars()
            assert list(roles) == ["user", "assistant"]

            # Control: the SAME runner, an ordinary message — the judge is reached.
            ordinary = await _submit_message(
                conn, seeds, label="firstturn-2", message="Make the headline two lines."
            )
            await run(ordinary)
            assert [call["message"] for call in judged] == ["Make the headline two lines."]

    run_async(scenario())


def test_a_clarifying_run_rides_the_turn_as_a_part_and_arms_the_next_turns_guard(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """Spec 2026-09-20 §2.1/§2.4: a run that stopped to ASK hands back honestly.

    Three claims on one journey. (1) The durable assistant message says what actually
    happened — the questions, not a draft-saved sentence. (2) The turn carries ONE
    ``clarification`` part for the asking document, landed BEFORE the rehydrate frame so the
    card is on the turn by the time the client refetches the canonical message. (3) The
    one-round guard is DERIVED per document on the next turn: the follow-up envelope carries
    ``previous_turn_outcome == "clarification_requested"`` although the submission echoed
    nothing at all.
    """

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="clarify")
            pinned = await _pin_document(conn, seeds, doc_kind="scene", version=1)
            lane = _ClarifyingFakeLane(conn_factory=seeds["conn_factory"])
            with hermetic_flag_env():
                registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))

            asked = await _submit_message(
                conn,
                seeds,
                label="clarify-1",
                message="Design the launch ad.",
            )
            emitter = await TurnStreamEmitter.open(
                workspace_id=seeds["workspace_id"],
                project_id=seeds["project"].project_id,
                thread_id=seeds["thread_id"],
                turn_id=asked.turn_id,
                conn_factory=seeds["conn_factory"],
                # Zero-length batching: every frame stands alone, so the ordering assertion
                # is about the emission order and not about a buffer's timing.
                policy=TurnStreamPolicy(batch_max_chars=1, batch_interval_s=0.0),
            )
            result = await _run_turn(conn, seeds, registry, lane, asked, stream=emitter)

            assert result.outcome.status is AgentExecutionStatus.AWAITING_INPUT
            assert result.assistant_message == (
                f"Asked you 1 question before designing: {CLARIFYING_QUESTION}."
            )

            frames = list(
                await list_turn_events(
                    conn, workspace_id=seeds["workspace_id"], turn_id=asked.turn_id
                )
            )
            cards = [
                frame
                for frame in frames
                if frame.event_type == "part.created" and frame.part_kind == "clarification"
            ]
            assert len(cards) == 1
            assert cards[0].part_id == f"clarification:{pinned['id']}"
            part = cards[0].payload["part"]
            assert part["document_id"] == pinned["id"]
            assert [q["question"] for q in part["questions"]] == [CLARIFYING_QUESTION]
            assert part["questions"][0]["default"] == "The 40% stat"
            # This document carries no account, so the header has no name to show: the key is
            # ABSENT from the wire rather than present and null (``exclude_none``).
            assert "account_name" not in part
            resets = [frame for frame in frames if frame.event_type == "stream.reset"]
            assert resets, "the design hand-back always rehydrates"
            terminals = [frame for frame in frames if frame.event_type == "turn.awaiting_input"]
            assert terminals, "the design hand-back always closes the turn"
            # The card lands AFTER the reset that would otherwise drop it — the client clears
            # the turn's parts on a reset — and before the terminal frame, so the turn closes
            # with the card already in hand.
            assert cards[0].sequence > resets[-1].sequence
            assert cards[0].sequence < terminals[-1].sequence

            # --- the next turn: the guard is derived, never echoed ---------------------------
            async def judge(**kwargs: Any) -> ExitJudgment:
                return ExitJudgment(
                    close_this_session=False,
                    addressed_artifacts=[1],
                    reasoning="The answer is work on this artifact.",
                )

            async def finisher(**kwargs: Any) -> dict[str, Any]:
                raise AssertionError("a staying judgment never closes the leg")

            runner = DesignLegTurnRunner(
                profiles=registry,
                artifacts=seeds["artifacts"],
                turns=DbAgentTurnJournal(conn_factory=seeds["conn_factory"]),
                history=DbAgentHistoryStore(conn_factory=seeds["conn_factory"]),
                lane=lane,
                exit_judge=judge,
                finisher=finisher,
                conn_factory=seeds["conn_factory"],
            )
            answer = await _submit_message(
                conn,
                seeds,
                label="clarify-2",
                message="The 40% stat.",
            )
            assert answer.previous_turn_outcome is None  # the client echoed nothing
            leg = await design_legs.get_open_leg_for_thread(
                conn, workspace_id=seeds["workspace_id"], thread_id=seeds["thread_id"]
            )
            assert leg is not None
            await runner.run_leg_turn(
                submission=answer,
                leg=leg,
                user_message_ref=await message_artifact_ref(conn, answer),
                focus_refs=(),
                card_payload=_card_payload(seeds),
                stream=None,
            )

            assert len(lane.envelopes) == 2
            assert (
                lane.envelopes[1].config["request"]["previous_turn_outcome"]
                == "clarification_requested"
            )
            # The first turn had nothing behind it to derive from — the guard is armed by the
            # ASKING run, not by every turn on a leg.
            assert lane.envelopes[0].config["request"]["previous_turn_outcome"] is None

    run_async(scenario())


def test_a_tagged_scene_ads_clarification_card_names_its_account(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """Spec 2026-09-20 §2.5: the card's header is "<title> · <account>" when the document
    carries an account.

    The G2 card the runner freezes into the envelope is resolved for WEB documents only, so a
    SCENE ad tagged to an ABM account would otherwise hand back a nameless card — dropping the
    one fact that says whose ad is waiting on an answer, on exactly the documents (per-account
    ads) where a leg holds several at once.
    """

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="clarifyacct")
            pinned = await _pin_document(conn, seeds, doc_kind="scene", version=1)
            account_id = f"acct_p34e_{uuid4().hex[:8]}"
            await design_accounts.create_web_account(
                conn,
                workspace_id=seeds["workspace_id"],
                account_id=account_id,
                name="Northwind Logistics",
                domain="northwind.example",
                logo_asset_id=None,
                data={},
                notes=None,
            )
            await set_document_account(
                conn,
                workspace_id=seeds["workspace_id"],
                document_id=pinned["id"],
                account_id=account_id,
            )
            lane = _ClarifyingFakeLane(conn_factory=seeds["conn_factory"])
            with hermetic_flag_env():
                registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))

            asked = await _submit_message(
                conn,
                seeds,
                label="clarify-acct",
                message="Design the launch ad.",
            )
            emitter = await TurnStreamEmitter.open(
                workspace_id=seeds["workspace_id"],
                project_id=seeds["project"].project_id,
                thread_id=seeds["thread_id"],
                turn_id=asked.turn_id,
                conn_factory=seeds["conn_factory"],
                policy=TurnStreamPolicy(batch_max_chars=1, batch_interval_s=0.0),
            )
            result = await _run_turn(conn, seeds, registry, lane, asked, stream=emitter)

            assert result.outcome.status is AgentExecutionStatus.AWAITING_INPUT
            cards = [
                frame
                for frame in await list_turn_events(
                    conn, workspace_id=seeds["workspace_id"], turn_id=asked.turn_id
                )
                if frame.event_type == "part.created" and frame.part_kind == "clarification"
            ]
            assert len(cards) == 1
            assert cards[0].payload["part"]["account_name"] == "Northwind Logistics"

    run_async(scenario())
