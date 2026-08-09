"""Lane D slice D4: the durable gate substrate and its receipt.

What this suite pins (charter `docs/specs/FI-lane-D-production-chat-and-launch.md` §3-P5(a),
ratified §6-D3):

* **the gate is immutable and the answer is insert-once** — both by database constraint, not by a
  code path anybody could forget: the append-only trigger refuses an UPDATE/DELETE of either row,
  and ``agent_gate_answer``'s primary key makes a second answer impossible;
* **open vs answered is derived** — there is no status column, so "is this gate still waiting?" is
  the absence of an answer row and can never disagree with the record of what was decided;
* **scope is structural** — a gate of another workspace is *not found* rather than forbidden, and a
  gate can only be anchored to a turn of its own thread;
* **one act has one name** — the answer's ``action_ref`` is CHECK-locked to the canonical
  ``turn-action:<turn_id>`` spelling of the turn that answered it;
* **the gate-answer receipt is strictly stronger than a turn receipt** — an ordinary turn, however
  well proved, refuses where gate authority is required.

DB-backed and rollback-only, per ``tests/api`` conventions. Every user identity is a real
``platform_user`` + ``workspace_membership`` seeded through ``clue_auth`` (``tests/_identity``),
because the gate's addressee and the answer's actor are real foreign keys onto them.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from clue_api.agent_gate import (
    DEFAULT_GATE_CURRENCY,
    KIND_DIRECTIVE_CONFIRMATION,
    GateAlreadyAnswered,
    directive_confirmation_gate_id,
    get_gate,
    insert_gate,
    insert_gate_answer,
    money_text,
    open_gates_for_thread,
)
from clue_api.agent_turn_submission import insert_submission
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.conversation_capture import persist_user_turn
from clue_api.turn_action import (
    GATE_ADDRESSEE_MISMATCH,
    GATE_ANSWER_NOT_FOUND,
    GATE_ANSWER_TURN_MISMATCH,
    TurnActionUnresolvable,
    derive_turn_action_ref,
    load_turn_identity,
    resolve_gate_answer_action,
    resolve_turn_action,
)
from clue_projections import open_gate_kinds_for_threads, thread_gates
from clue_storage import FsStorage
from tests._identity import seed_principal
from tests._workspace import seed_project as _seed_project_row
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)

USER_ID = "usr_d4_gate"
OTHER_USER_ID = "usr_d4_other"
NOW_UTC = datetime(2026, 8, 9, 9, 0, tzinfo=UTC)
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


@pytest.fixture
def require_gate_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


pytestmark = pytest.mark.usefixtures("require_gate_db")


class _Seeded:
    def __init__(self, **values: Any) -> None:
        self.__dict__.update(values)


async def _seed(
    conn: Any,
    tmp_path: Path,
    *,
    workspace_id: str,
    label: str,
) -> Any:
    """A workspace with a project, a thread, one human turn, and its submission record.

    The turn is seeded in **both** halves D2 split a turn's identity into — the ``agent_turn`` row
    the gate's presenting FK needs, and the ``agent_turn_submission`` row the answer's FK needs —
    because a production gate is presented in a turn the route had already recorded.
    """

    project = await _seed_project_row(conn, workspace_id, name=f"D4 {label}")
    for user_id in (USER_ID, OTHER_USER_ID):
        await seed_principal(
            conn,
            workspace_id=workspace_id,
            user_id=user_id,
            membership_id=f"wsm_d4_{label}_{user_id}",
        )
    thread_id = f"thr_d4_{label}"
    await conn.execute(
        text(
            "INSERT INTO agent_thread (id, workspace_id, project_id, created_by_user_id) "
            "VALUES (:id, :workspace, :project, :user) ON CONFLICT (id) DO NOTHING"
        ),
        {
            "id": thread_id,
            "workspace": workspace_id,
            "project": project.project_id,
            "user": USER_ID,
        },
    )
    artifacts = DurableAgentArtifactStore(
        storage=FsStorage(tmp_path / f"gate-artifacts-{label}"),
        conn_factory=conn_session_factory(conn),
    )
    turn_id = uuid5(NAMESPACE_URL, f"lane-d4:{label}:turn")
    captured = await persist_user_turn(
        conn,
        artifacts=artifacts,
        workspace_id=workspace_id,
        brand_id=project.brand_id,
        product_id=project.product_id,
        project_id=project.project_id,
        turn_id=turn_id,
        message="Start the research on those two accounts.",
    )
    await insert_submission(
        conn,
        turn_id=turn_id,
        workspace_id=workspace_id,
        project_id=project.project_id,
        thread_id=thread_id,
        submitted_by_user_id=USER_ID,
        submitted_via_membership_id=f"wsm_d4_{label}_{USER_ID}",
        onboarding_input_id=captured.onboarding_input_id,
        message_artifact_key=captured.artifact_ref.artifact_key,
        message_sha256=captured.artifact_ref.sha256,
        idempotency_key=f"key-{label}",
    )
    execution_id = uuid5(NAMESPACE_URL, f"lane-d4:{label}:execution")
    await conn.execute(
        text(
            "INSERT INTO execution "
            "(id, workspace_id, project_id, started_by, parameter_manifest_hash, "
            " pin_manifest_hash) "
            "VALUES (:id, :workspace, :project, 'human', :hash, :hash) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {
            "id": execution_id,
            "workspace": workspace_id,
            "project": project.project_id,
            "hash": "0" * 64,
        },
    )
    manifest = await artifacts.persist_body(
        workspace_id=workspace_id,
        data=json.dumps({"resources": []}).encode(),
        media_type="application/json",
    )
    await conn.execute(
        text(
            "INSERT INTO agent_turn "
            "(id, execution_id, workspace_id, project_id, thread_id, actor_id, role, "
            " workspace_root_id, profile_name, profile_version, profile_sha256, "
            " resource_manifest_key, resource_manifest_artifact_sha256, resource_manifest_sha256, "
            " retention_class, requested_at, submitted_by_user_id, submitted_via_membership_id) "
            "VALUES (:id, :execution, :workspace, :project, :thread, :actor_id, 'head_of_abm', "
            " :root, 'head-of-abm', 'v23', :sha, :key, :sha256, :sha256, "
            " 'test', :requested_at, :user, :membership)"
        ),
        {
            "id": turn_id,
            "execution": execution_id,
            "workspace": workspace_id,
            "project": project.project_id,
            "thread": thread_id,
            "actor_id": USER_ID,
            "root": f"root-{label}",
            "sha": "0" * 64,
            "key": manifest.artifact_key,
            "sha256": manifest.sha256,
            "requested_at": NOW_UTC,
            "user": USER_ID,
            "membership": f"wsm_d4_{label}_{USER_ID}",
        },
    )
    await conn.execute(
        text(
            "INSERT INTO agent_artifact_ref "
            "(id, turn_id, workspace_id, owner_kind, owner_id, ref_role, ordinal, "
            " artifact_key, artifact_sha256, retention_class) "
            "VALUES (:id, :turn, :workspace, 'turn', :turn, 'user_message', 0, :key, :sha, 'test')"
        ),
        {
            "id": uuid5(NAMESPACE_URL, f"lane-d4:{label}:user-message-ref"),
            "turn": turn_id,
            "workspace": workspace_id,
            "key": captured.artifact_ref.artifact_key,
            "sha": captured.artifact_ref.sha256,
        },
    )
    return _Seeded(
        workspace_id=workspace_id,
        project_id=project.project_id,
        thread_id=thread_id,
        turn_id=turn_id,
        membership_id=f"wsm_d4_{label}_{USER_ID}",
        conn_factory=conn_session_factory(conn),
    )


async def _present(
    conn: Any,
    seeded: Any,
    *,
    digest: str = DIGEST_A,
    amount: Decimal = Decimal("600"),
    kind: str = KIND_DIRECTIVE_CONFIRMATION,
    subject_ref: str = "research-directive:11111111-1111-4111-8111-111111111111:v1",
) -> Any:
    gate_id = directive_confirmation_gate_id(
        workspace_id=seeded.workspace_id,
        turn_id=seeded.turn_id,
        subject_ref=subject_ref,
        expected_subject_sha256=digest,
    )
    row, created = await insert_gate(
        conn,
        gate_id=gate_id,
        workspace_id=seeded.workspace_id,
        project_id=seeded.project_id,
        thread_id=seeded.thread_id,
        turn_id=seeded.turn_id,
        kind=kind,
        subject_ref=subject_ref,
        subject_revision=1,
        expected_subject_sha256=digest,
        subject_snapshot={"research_directive_id": str(uuid4()), "account_count": 2},
        max_spend_cents=amount,
        currency=DEFAULT_GATE_CURRENCY,
        addressee_user_id=USER_ID,
    )
    return row, created


# --- the immutable gate --------------------------------------------------------------------


def test_a_presented_gate_cannot_be_edited_or_deleted(tmp_path: Path) -> None:
    """A gate is a receipt of what somebody was shown. Nothing may rewrite it afterwards."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-d4-immutable", label="immutable")
            gate, created = await _present(conn, seeded)
            assert created is True

            for statement in (
                "UPDATE agent_gate SET max_spend_cents = 1 WHERE gate_id = :id",
                "DELETE FROM agent_gate WHERE gate_id = :id",
            ):
                with pytest.raises(DBAPIError):
                    async with conn.begin_nested():
                        await conn.execute(text(statement), {"id": gate.gate_id})

            stored = await get_gate(conn, workspace_id=seeded.workspace_id, gate_id=gate.gate_id)
            assert stored is not None
            assert stored.gate.max_spend_cents == Decimal("600")

    run_async(scenario())


def test_representing_the_same_subject_in_the_same_turn_replays_one_gate(tmp_path: Path) -> None:
    """A retried plan step presents the same gate, not a second one addressed to the same person.

    And a *different* subject digest is a different question: it earns its own gate, because a
    redrafted directive is genuinely a new thing to approve.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-d4-replay", label="replay")
            first, created_first = await _present(conn, seeded)
            # The replay recomputes a *different* amount; the stored one wins, because it is the
            # number the human is looking at.
            second, created_second = await _present(conn, seeded, amount=Decimal("999"))

            assert created_first is True
            assert created_second is False
            assert second.gate_id == first.gate_id
            assert second.max_spend_cents == Decimal("600")

            redrafted, created_redrafted = await _present(conn, seeded, digest=DIGEST_B)
            assert created_redrafted is True
            assert redrafted.gate_id != first.gate_id

    run_async(scenario())


def test_a_gate_is_invisible_outside_its_own_workspace(tmp_path: Path) -> None:
    """Existence is not leaked: a cross-workspace read is a miss, never a refusal."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-d4-scope", label="scope")
            await _seed(conn, tmp_path, workspace_id="ws-d4-scope-other", label="scopeother")
            gate, _ = await _present(conn, seeded)

            assert (
                await get_gate(conn, workspace_id="ws-d4-scope-other", gate_id=gate.gate_id) is None
            )
            assert (
                await get_gate(conn, workspace_id=seeded.workspace_id, gate_id=gate.gate_id)
                is not None
            )

    run_async(scenario())


def test_a_gate_cannot_be_anchored_to_a_turn_of_another_thread(tmp_path: Path) -> None:
    """The presenting-turn FK is the three-column thread anchor, so this is a database error."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-d4-anchor", label="anchor")
            await conn.execute(
                text(
                    "INSERT INTO agent_thread (id, workspace_id, project_id) "
                    "VALUES (:id, :workspace, :project)"
                ),
                {
                    "id": "thr_d4_anchor_other",
                    "workspace": seeded.workspace_id,
                    "project": seeded.project_id,
                },
            )
            with pytest.raises(IntegrityError):
                async with conn.begin_nested():
                    await insert_gate(
                        conn,
                        gate_id=uuid4(),
                        workspace_id=seeded.workspace_id,
                        project_id=seeded.project_id,
                        thread_id="thr_d4_anchor_other",
                        turn_id=seeded.turn_id,
                        kind=KIND_DIRECTIVE_CONFIRMATION,
                        subject_ref="research-directive:x:v1",
                        subject_revision=1,
                        expected_subject_sha256=DIGEST_A,
                        subject_snapshot={},
                        max_spend_cents=Decimal("1"),
                        currency=DEFAULT_GATE_CURRENCY,
                        addressee_user_id=USER_ID,
                    )

    run_async(scenario())


# --- the insert-once answer ----------------------------------------------------------------


def test_a_gate_is_answerable_exactly_once(tmp_path: Path) -> None:
    """The once-only rule is the primary key, so a second answer cannot be written at all."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-d4-once", label="once")
            gate, _ = await _present(conn, seeded)
            answer = await insert_gate_answer(
                conn,
                gate_id=gate.gate_id,
                workspace_id=seeded.workspace_id,
                turn_id=seeded.turn_id,
                action_ref=derive_turn_action_ref(seeded.turn_id),
                decision="approved",
                answered_by_user_id=USER_ID,
            )
            assert answer.decision == "approved"

            with pytest.raises(GateAlreadyAnswered) as caught:
                async with conn.begin_nested():
                    await insert_gate_answer(
                        conn,
                        gate_id=gate.gate_id,
                        workspace_id=seeded.workspace_id,
                        turn_id=seeded.turn_id,
                        action_ref=derive_turn_action_ref(seeded.turn_id),
                        decision="rejected",
                        answered_by_user_id=USER_ID,
                    )
            # The refusal carries the standing answer, so a caller can tell a retry from a race.
            assert caught.value.existing.decision == "approved"

            # And it stays immutable afterwards.
            for statement in (
                "UPDATE agent_gate_answer SET decision = 'rejected' WHERE gate_id = :id",
                "DELETE FROM agent_gate_answer WHERE gate_id = :id",
            ):
                with pytest.raises(DBAPIError):
                    async with conn.begin_nested():
                        await conn.execute(text(statement), {"id": gate.gate_id})

    run_async(scenario())


def test_open_and_answered_are_derived_from_the_answer_record(tmp_path: Path) -> None:
    """No status column anywhere: the derivation is the anti-join, on both read surfaces."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-d4-derived", label="derived")
            gate, _ = await _present(conn, seeded)

            view = await get_gate(conn, workspace_id=seeded.workspace_id, gate_id=gate.gate_id)
            assert view is not None and view.is_open is True
            assert [
                row.gate_id
                for row in await open_gates_for_thread(
                    conn, workspace_id=seeded.workspace_id, thread_id=seeded.thread_id
                )
            ] == [gate.gate_id]
            assert await open_gate_kinds_for_threads(
                workspace_id=seeded.workspace_id,
                thread_ids=(seeded.thread_id,),
                conn_factory=seeded.conn_factory,
            ) == {seeded.thread_id: (KIND_DIRECTIVE_CONFIRMATION,)}

            await insert_gate_answer(
                conn,
                gate_id=gate.gate_id,
                workspace_id=seeded.workspace_id,
                turn_id=seeded.turn_id,
                action_ref=derive_turn_action_ref(seeded.turn_id),
                decision="revised",
                answered_by_user_id=USER_ID,
            )

            answered = await get_gate(conn, workspace_id=seeded.workspace_id, gate_id=gate.gate_id)
            assert answered is not None
            assert answered.is_open is False
            assert answered.answer is not None and answered.answer.decision == "revised"
            assert (
                await open_gates_for_thread(
                    conn, workspace_id=seeded.workspace_id, thread_id=seeded.thread_id
                )
                == ()
            )
            assert (
                await open_gate_kinds_for_threads(
                    workspace_id=seeded.workspace_id,
                    thread_ids=(seeded.thread_id,),
                    conn_factory=seeded.conn_factory,
                )
                == {}
            )

            # The transcript projection keeps the closed gate in history with its decision.
            gates = await thread_gates(
                workspace_id=seeded.workspace_id,
                thread_id=seeded.thread_id,
                conn_factory=seeded.conn_factory,
            )
            assert len(gates) == 1
            assert gates[0].is_open is False
            assert gates[0].answer is not None
            assert gates[0].answer.decision == "revised"
            assert gates[0].launches == ()

    run_async(scenario())


def test_an_answer_cannot_invent_a_name_for_the_act_it_cites(tmp_path: Path) -> None:
    """The ``action_ref`` CHECK ties the receipt to the answering turn's canonical spelling."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-d4-refname", label="refname")
            gate, _ = await _present(conn, seeded)
            with pytest.raises(IntegrityError):
                async with conn.begin_nested():
                    await insert_gate_answer(
                        conn,
                        gate_id=gate.gate_id,
                        workspace_id=seeded.workspace_id,
                        turn_id=seeded.turn_id,
                        action_ref=f"turn-action:{uuid4()}",
                        decision="approved",
                        answered_by_user_id=USER_ID,
                    )

    run_async(scenario())


# --- the gate-answer receipt ----------------------------------------------------------------


def test_an_ordinary_turn_receipt_is_not_gate_authority(tmp_path: Path) -> None:
    """The whole point of the second resolver: a proved human turn is still not a gate answer."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-d4-receipt", label="receipt")
            ref = derive_turn_action_ref(seeded.turn_id)

            # The plain receipt resolves — this turn really is a human act of this workspace.
            resolved = await resolve_turn_action(
                ref,
                workspace_id=seeded.workspace_id,
                actor_id=USER_ID,
                conn_factory=seeded.conn_factory,
            )
            assert resolved.turn_id == str(seeded.turn_id)

            # The gate resolver refuses it, because it answered no gate.
            with pytest.raises(TurnActionUnresolvable) as caught:
                await resolve_gate_answer_action(
                    ref,
                    workspace_id=seeded.workspace_id,
                    actor_id=USER_ID,
                    conn_factory=seeded.conn_factory,
                )
            assert caught.value.reason_code == GATE_ANSWER_NOT_FOUND

    run_async(scenario())


def test_a_gate_answer_receipt_names_its_own_gate_and_its_own_addressee(tmp_path: Path) -> None:
    """It resolves for the addressee and the right gate, and refuses everything else."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-d4-answer", label="answer")
            gate, _ = await _present(conn, seeded)
            other_gate, _ = await _present(conn, seeded, digest=DIGEST_B)
            ref = derive_turn_action_ref(seeded.turn_id)
            await insert_gate_answer(
                conn,
                gate_id=gate.gate_id,
                workspace_id=seeded.workspace_id,
                turn_id=seeded.turn_id,
                action_ref=ref,
                decision="approved",
                answered_by_user_id=USER_ID,
            )

            proved = await resolve_gate_answer_action(
                ref,
                workspace_id=seeded.workspace_id,
                actor_id=USER_ID,
                gate_id=gate.gate_id,
                conn_factory=seeded.conn_factory,
            )
            assert proved.gate_id == gate.gate_id
            assert proved.decision == "approved"
            assert proved.action.action_ref == ref

            # A receipt for gate A does not satisfy gate B.
            with pytest.raises(TurnActionUnresolvable) as wrong_gate:
                await resolve_gate_answer_action(
                    ref,
                    workspace_id=seeded.workspace_id,
                    actor_id=USER_ID,
                    gate_id=other_gate.gate_id,
                    conn_factory=seeded.conn_factory,
                )
            assert wrong_gate.value.reason_code == GATE_ANSWER_TURN_MISMATCH

            # And a colleague of the same workspace cannot spend it.
            with pytest.raises(TurnActionUnresolvable) as wrong_actor:
                await resolve_gate_answer_action(
                    ref,
                    workspace_id=seeded.workspace_id,
                    actor_id=OTHER_USER_ID,
                    conn_factory=seeded.conn_factory,
                )
            # The turn half refuses first — the colleague did not submit this turn either — which
            # is the same deny-by-default answer arrived at one step earlier.
            assert wrong_actor.value.reason_code in {
                "turn_action_actor_mismatch",
                GATE_ADDRESSEE_MISMATCH,
            }

    run_async(scenario())


def test_a_turn_identity_resolves_from_either_durable_half(tmp_path: Path) -> None:
    """D2 split a turn's identity in two; the gate path must read whichever half exists."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-d4-halves", label="halves")
            identity = await load_turn_identity(
                conn, workspace_id=seeded.workspace_id, turn_id=seeded.turn_id
            )
            assert identity is not None
            assert identity.thread_id == seeded.thread_id
            assert identity.project_id == seeded.project_id
            assert identity.submitted_by_user_id == USER_ID

            # A turn that has only the worker-side half — every turn written before D2, and every
            # machine-originated turn — still resolves its scope, and honestly reports that it has
            # no human submitter rather than inventing one (Lane B ruling 8).
            machine_turn_id = uuid5(NAMESPACE_URL, "lane-d4:halves:machine-turn")
            machine_execution_id = uuid5(NAMESPACE_URL, "lane-d4:halves:machine-execution")
            await conn.execute(
                text(
                    "INSERT INTO execution "
                    "(id, workspace_id, project_id, started_by, parameter_manifest_hash, "
                    " pin_manifest_hash) "
                    "VALUES (:id, :workspace, :project, 'agent', :hash, :hash)"
                ),
                {
                    "id": machine_execution_id,
                    "workspace": seeded.workspace_id,
                    "project": seeded.project_id,
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
                    "SELECT :id, :execution, workspace_id, project_id, thread_id, "
                    " 'agent:machine', role, workspace_root_id, profile_name, profile_version, "
                    " profile_sha256, resource_manifest_key, resource_manifest_artifact_sha256, "
                    " resource_manifest_sha256, retention_class, requested_at "
                    "FROM agent_turn WHERE id = :source"
                ),
                {
                    "id": machine_turn_id,
                    "execution": machine_execution_id,
                    "source": seeded.turn_id,
                },
            )
            from_turn_row = await load_turn_identity(
                conn, workspace_id=seeded.workspace_id, turn_id=machine_turn_id
            )
            assert from_turn_row is not None
            assert from_turn_row.thread_id == seeded.thread_id
            assert from_turn_row.submitted_by_user_id is None

            assert (
                await load_turn_identity(
                    conn, workspace_id="ws-d4-halves-other", turn_id=seeded.turn_id
                )
                is None
            )

    run_async(scenario())


# --- money -----------------------------------------------------------------------------------


def test_one_amount_has_exactly_one_spelling() -> None:
    """The canonical form is what a digest and a human both read; the column scale never leaks."""

    assert money_text(Decimal("1200")) == "1200"
    assert money_text(Decimal("1200.00")) == "1200"
    assert money_text(Decimal("1200.0000")) == "1200"
    assert money_text(Decimal("0")) == "0"
    assert money_text(Decimal("12.50")) == "12.5"


def test_the_stored_amount_compares_numerically_not_textually(tmp_path: Path) -> None:
    """``numeric(20,4)`` returns 600.0000; an approval naming 600 is the same amount."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-d4-money", label="money")
            gate, _ = await _present(conn, seeded, amount=Decimal("600"))
            view = await get_gate(conn, workspace_id=seeded.workspace_id, gate_id=gate.gate_id)
            assert view is not None
            assert view.gate.max_spend_cents == Decimal("600")
            assert str(view.gate.max_spend_cents) != "600"
            assert money_text(view.gate.max_spend_cents) == "600"

    run_async(scenario())


def test_a_gate_kind_outside_the_closed_vocabulary_is_refused(tmp_path: Path) -> None:
    """Adding a gate kind is a reviewed migration; it is not something a caller may improvise."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-d4-kind", label="kind")
            with pytest.raises(ValueError, match="unknown gate kind"):
                await _present(conn, seeded, kind="spend_whatever_you_like")

    run_async(scenario())
