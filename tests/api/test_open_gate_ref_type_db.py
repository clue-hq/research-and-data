"""A card link must say ``agent_gate``.

Live check of the CRM write permission card, 2026-10-22: the Head of ABM opened a card with
``propose_crm_changes@1`` and then finalized with ``open_gate_refs`` carrying
``{object_type: "crm_write_permission", object_id: <the right gate id>}``. The chat recognises a
card only by ``object_type == "agent_gate"``, so the human saw "This review request is incomplete"
and could not answer. Finalization now refuses that link, in words the agent can act on, before
anything is frozen — and leaves every other kind of link (a server-written ``design_leg``, any id
that is not a gate) alone.

These run the real ``finalize_turn`` tool over the real :class:`C5AgentExecutionAdapter` against a
real ``agent_gate`` row. DB-backed and rollback-only.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from clue_agents import AgentRole, AgentTurnRequest, ArtifactRef, FinalizeStatus
from clue_api.agent_execution_wiring import C5AgentExecutionAdapter
from clue_api.agent_gate import (
    GATE_OBJECT_TYPE,
    KIND_CRM_WRITE_PERMISSION,
    KIND_DIRECTIVE_CONFIRMATION,
    insert_gate_answer,
)
from clue_api.agent_registry_wiring import build_agent_profile_registry
from clue_api.agent_runtime_wiring import GovernedAgentToolFactory
from clue_api.toolbelt_wiring import build_toolbelt
from clue_api.turn_action import derive_turn_action_ref
from tests.agents.conftest import NOW, artifact, constitution, domain_ref
from tests.agents.test_runtime import _DelegationArtifacts, _EmptyOutputBackend
from tests.api.test_crm_write_answer_db import _propose as _crm_propose
from tests.api.test_crm_write_answer_db import _run as _crm_run
from tests.api.test_crm_write_answer_db import _set_tier
from tests.api.test_lane_d4_agent_gate_db import USER_ID, _present, _seed
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)


@pytest.fixture
def require_gate_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


pytestmark = pytest.mark.usefixtures("require_gate_db")


class _RecordingAuthority:
    def __init__(self) -> None:
        self.envelopes: list[Any] = []

    async def finalize(self, *, turn_id: UUID, workspace_id: str, envelope: Any) -> ArtifactRef:
        del turn_id, workspace_id
        self.envelopes.append(envelope)
        return artifact("finalization-envelope.json")


def _finalizer(seeded: Any, *, execution_id: Any = None) -> tuple[Any, _RecordingAuthority]:
    registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
    resolved = registry.resolve(AgentRole.HEAD_OF_ABM)
    ws = seeded.workspace_id
    trusted = constitution(
        workspace_id=ws,
        project_card_ref=artifact("project-card.json", workspace_id=ws),
        budget_envelope_ref=artifact("budget.json", workspace_id=ws),
        resource_manifest_ref=artifact("resource-manifest.json", workspace_id=ws),
        focus_refs=(domain_ref("account-1", workspace_id=ws),),
        profile_ref=resolved.profile_ref,
        resource_manifest_sha256=resolved.resource_manifest.aggregate_sha256,
        **({} if execution_id is None else {"execution_id": execution_id}),
    )
    request = AgentTurnRequest(
        turn_id=seeded.turn_id,
        thread_id=seeded.thread_id,
        constitution=trusted,
        user_message_artifact_ref=artifact("user-message.json", workspace_id=ws),
        requested_at=NOW,
    )
    unused = cast(Any, object())
    adapter = C5AgentExecutionAdapter(
        turn_id=seeded.turn_id,
        constitution=trusted,
        resolved_profile=resolved,
        policy=unused,
        slot_key="agent_slot",
        tools=unused,
        tool_invoker=unused,
        executor=unused,
        artifacts=unused,
        journal=unused,
        checkpointer_factory=unused,
        conn_factory=seeded.conn_factory,
    )
    authority = _RecordingAuthority()
    adapter.bind_finalization_authority(authority)
    factory = GovernedAgentToolFactory(
        request=request,
        resolved_profile=resolved,
        registry=build_toolbelt(storage=None, gateway=None),
        execution=adapter,
        lease=cast(Any, SimpleNamespace(backend=_EmptyOutputBackend())),
        artifacts=cast(Any, _DelegationArtifacts()),
    )
    finalize_turn = factory.build()[-1]
    assert finalize_turn.name == "finalize_turn"
    coroutine = cast(Any, finalize_turn).coroutine
    assert coroutine is not None
    return coroutine, authority


def _awaiting(workspace_id: str, object_type: str, object_id: str) -> dict[str, Any]:
    return {
        "status": "awaiting_input",
        "user_message": "Please review the changes on the card.",
        "open_gate_refs": [
            {"workspace_id": workspace_id, "object_type": object_type, "object_id": object_id}
        ],
    }


def test_a_card_linked_under_its_kind_is_refused_with_the_spelling_to_use(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-gate-link-bad", label="gl_bad")
            gate, _created = await _present(conn, seeded)
            finalize, authority = _finalizer(seeded)

            with pytest.raises(ValueError) as refused:
                await finalize(
                    runtime=cast(Any, object()),
                    **_awaiting(seeded.workspace_id, "crm_write_permission", str(gate.gate_id)),
                )

            message = str(refused.value)
            assert f"{gate.gate_id} is a card" in message
            assert f'{{object_type: "agent_gate", object_id: "{gate.gate_id}"}}' in message
            assert authority.envelopes == []

    run_async(scenario())


def test_a_card_linked_as_agent_gate_finalizes(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-gate-link-ok", label="gl_ok")
            gate, _created = await _present(conn, seeded)
            finalize, authority = _finalizer(seeded)

            await finalize(
                runtime=cast(Any, object()),
                **_awaiting(seeded.workspace_id, GATE_OBJECT_TYPE, str(gate.gate_id)),
            )

            [envelope] = authority.envelopes
            assert envelope.status is FinalizeStatus.AWAITING_INPUT
            assert [(r.object_type, r.object_id) for r in envelope.open_gate_refs] == [
                (GATE_OBJECT_TYPE, str(gate.gate_id))
            ]

    run_async(scenario())


@pytest.mark.parametrize(
    "object_type",
    ["design_leg", "crm_write_permission"],
)
def test_a_link_whose_id_is_no_gate_passes_untouched(tmp_path: Path, object_type: str) -> None:
    """A design leg ref (written by the server on purpose), or any id that is not a gate row."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(
                conn, tmp_path, workspace_id="ws-gate-link-other", label="gl_other"
            )
            await _present(conn, seeded)
            finalize, authority = _finalizer(seeded)

            await finalize(
                runtime=cast(Any, object()),
                **_awaiting(seeded.workspace_id, object_type, str(uuid4())),
            )
            await finalize(
                runtime=cast(Any, object()),
                **_awaiting(seeded.workspace_id, object_type, "not-a-uuid"),
            )

            assert len(authority.envelopes) == 2

    run_async(scenario())


def test_a_gate_of_another_workspace_is_not_this_turns_card(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            other = await _seed(conn, tmp_path, workspace_id="ws-gate-link-x1", label="gl_x1")
            foreign_gate, _created = await _present(conn, other)
            seeded = await _seed(conn, tmp_path, workspace_id="ws-gate-link-x2", label="gl_x2")
            finalize, authority = _finalizer(seeded)

            await finalize(
                runtime=cast(Any, object()),
                **_awaiting(seeded.workspace_id, "design_leg", str(foreign_gate.gate_id)),
            )

            assert len(authority.envelopes) == 1

    run_async(scenario())


# --- R-12.16: a card the turn created cannot go missing ------------------------------------------


def _message_only(status: str = "awaiting_input") -> dict[str, Any]:
    return {"status": status, "user_message": "I've put the changes on a card for you."}


def _gate_links(envelope: Any) -> list[tuple[str, str]]:
    return [(r.object_type, r.object_id) for r in envelope.open_gate_refs]


@pytest.mark.parametrize("kind", [KIND_CRM_WRITE_PERMISSION, KIND_DIRECTIVE_CONFIRMATION])
def test_an_open_card_the_turn_created_is_linked_when_the_agent_leaves_it_out(
    tmp_path: Path, kind: str
) -> None:
    """Live check L-13: the agent proposed CRM changes, then finalized ``awaiting_input`` with
    only a message. The card must still be linked, so the chat emits its gate part."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-gate-own", label="gl_own")
            gate, _created = await _present(conn, seeded, kind=kind)
            finalize, authority = _finalizer(seeded)

            await finalize(runtime=cast(Any, object()), **_message_only())

            [envelope] = authority.envelopes
            assert _gate_links(envelope) == [(GATE_OBJECT_TYPE, str(gate.gate_id))]
            assert envelope.open_gate_refs[0].workspace_id == seeded.workspace_id

    run_async(scenario())


async def _age(conn: Any, gate_id: Any, *, seconds: int) -> None:
    """Move a gate's ``created_at`` back: every gate of one test shares the transaction's
    ``now()``, while in production a redraft is a later tool call. The append-only trigger is
    lifted only for this one update, inside the test's rolled-back transaction."""
    await conn.execute(text("ALTER TABLE agent_gate DISABLE TRIGGER agent_gate_append_only"))
    await conn.execute(
        text(
            "UPDATE agent_gate SET created_at = created_at - make_interval(secs => :s) "
            "WHERE gate_id = :id"
        ),
        {"s": seconds, "id": gate_id},
    )
    await conn.execute(text("ALTER TABLE agent_gate ENABLE TRIGGER agent_gate_append_only"))


async def _redraft(conn: Any, seeded: Any) -> tuple[Any, Any]:
    """Two drafts of one directive in one turn: same kind and subject, a new digest."""
    older, _created = await _present(conn, seeded)
    newer, _created = await _present(conn, seeded, digest="b" * 64)
    await _age(conn, older.gate_id, seconds=60)
    return older, newer


def test_a_card_the_agent_linked_is_not_linked_twice(tmp_path: Path) -> None:
    """Two drafts of one directive in one turn: the agent linked the newer one. It stays linked
    once, and the older, superseded draft is not added."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-gate-twice", label="gl_twice")
            _older, newer = await _redraft(conn, seeded)
            finalize, authority = _finalizer(seeded)

            await finalize(
                runtime=cast(Any, object()),
                **_awaiting(seeded.workspace_id, GATE_OBJECT_TYPE, str(newer.gate_id)),
            )

            [envelope] = authority.envelopes
            assert _gate_links(envelope) == [(GATE_OBJECT_TYPE, str(newer.gate_id))]

    run_async(scenario())


def test_only_the_newer_draft_is_linked_when_the_agent_links_neither(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-gate-redraft", label="gl_redr")
            _older, newer = await _redraft(conn, seeded)
            finalize, authority = _finalizer(seeded)

            await finalize(runtime=cast(Any, object()), **_message_only())

            [envelope] = authority.envelopes
            assert _gate_links(envelope) == [(GATE_OBJECT_TYPE, str(newer.gate_id))]

    run_async(scenario())


def test_open_cards_of_different_subjects_are_each_linked_once(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-gate-subj", label="gl_subj")
            first, _created = await _present(conn, seeded)
            second, _created = await _present(
                conn,
                seeded,
                subject_ref="research-directive:22222222-2222-4222-8222-222222222222:v1",
            )
            finalize, authority = _finalizer(seeded)

            await finalize(
                runtime=cast(Any, object()),
                **_awaiting(seeded.workspace_id, GATE_OBJECT_TYPE, str(second.gate_id)),
            )

            [envelope] = authority.envelopes
            # The agent's own link first, then the one it left out — each once.
            assert _gate_links(envelope) == [
                (GATE_OBJECT_TYPE, str(second.gate_id)),
                (GATE_OBJECT_TYPE, str(first.gate_id)),
            ]

    run_async(scenario())


def test_a_retried_finalize_reuses_the_gate_links_already_recorded(tmp_path: Path) -> None:
    """The first finalize recorded its links, then the process died before the turn closed; the
    card was answered in between. The retry must produce the recorded envelope again (the
    finalization record refuses a different one), not re-read the now-answered gate."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-gate-retry", label="gl_retry")
            gate, _created = await _present(conn, seeded)
            execution_id = await conn.scalar(
                text("SELECT execution_id FROM agent_turn WHERE id = :id"), {"id": seeded.turn_id}
            )
            finalize, authority = _finalizer(seeded, execution_id=execution_id)
            await finalize(runtime=cast(Any, object()), **_message_only())
            [first] = authority.envelopes
            assert _gate_links(first) == [(GATE_OBJECT_TYPE, str(gate.gate_id))]
            await _record(conn, seeded, first)
            await insert_gate_answer(
                conn,
                gate_id=gate.gate_id,
                workspace_id=seeded.workspace_id,
                turn_id=seeded.turn_id,
                action_ref=derive_turn_action_ref(seeded.turn_id),
                decision="approved",
                expected_subject_sha256=gate.expected_subject_sha256,
                answered_by_user_id=USER_ID,
            )

            retry, authority = _finalizer(seeded, execution_id=execution_id)
            await retry(runtime=cast(Any, object()), **_message_only())

            [second] = authority.envelopes
            assert second.finalization_id == first.finalization_id
            assert second.open_gate_refs == first.open_gate_refs

    run_async(scenario())


async def _record(conn: Any, seeded: Any, envelope: Any) -> None:
    """What ``record_finalization`` writes for the envelope's gate links (the row and its
    ``open_gate`` refs), as a crash right after it would leave them."""
    await conn.execute(
        text(
            "INSERT INTO agent_finalization "
            "(id, turn_id, execution_id, workspace_id, status, failure_code, finalized_at) "
            "VALUES (:id, :turn, :execution, :workspace, :status, NULL, :at)"
        ),
        {
            "id": envelope.finalization_id,
            "turn": seeded.turn_id,
            "execution": envelope.execution_id,
            "workspace": seeded.workspace_id,
            "status": envelope.status.value,
            "at": envelope.finalized_at,
        },
    )
    for ordinal, ref in enumerate(envelope.open_gate_refs):
        await conn.execute(
            text(
                "INSERT INTO agent_finalization_domain_ref "
                "(finalization_id, workspace_id, ref_role, ordinal, object_type, object_id, "
                " object_version) "
                "VALUES (:finalization, :workspace, 'open_gate', :ordinal, :type, :id, :version)"
            ),
            {
                "finalization": envelope.finalization_id,
                "workspace": seeded.workspace_id,
                "ordinal": ordinal,
                "type": ref.object_type,
                "id": ref.object_id,
                "version": ref.version,
            },
        )


def test_an_answered_card_is_not_linked(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-gate-done", label="gl_done")
            gate, _created = await _present(conn, seeded)
            await insert_gate_answer(
                conn,
                gate_id=gate.gate_id,
                workspace_id=seeded.workspace_id,
                turn_id=seeded.turn_id,
                action_ref=derive_turn_action_ref(seeded.turn_id),
                decision="approved",
                expected_subject_sha256=gate.expected_subject_sha256,
                answered_by_user_id=USER_ID,
            )
            finalize, authority = _finalizer(seeded)

            await finalize(runtime=cast(Any, object()), **_message_only())

            [envelope] = authority.envelopes
            assert envelope.open_gate_refs == ()

    run_async(scenario())


def test_an_open_card_of_another_turn_is_not_linked(tmp_path: Path) -> None:
    """Only the cards THIS turn created: an older turn's card is not re-linked to this one."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            earlier = await _seed(conn, tmp_path, workspace_id="ws-gate-turns", label="gl_t1")
            await _present(conn, earlier)
            # A later turn of the same thread and workspace.
            seeded = SimpleNamespace(**{**vars(earlier), "turn_id": uuid4()})
            finalize, authority = _finalizer(seeded)

            await finalize(runtime=cast(Any, object()), **_message_only())

            [envelope] = authority.envelopes
            assert envelope.open_gate_refs == ()

    run_async(scenario())


def test_a_replaced_crm_card_of_this_turn_is_not_linked(tmp_path: Path) -> None:
    """A newer CRM card replaced the first one in the same turn (its proposal is `replaced`, so
    the gate is withdrawn): only the newer card is linked."""

    async def body(conn: Any, seeded: Any, connection: Any) -> None:
        del connection
        first = await _crm_propose(conn, seeded, _set_tier("101", "Tier 1"))
        second = await _crm_propose(conn, seeded, _set_tier("101", "Tier 2"))
        status = await conn.scalar(
            text("SELECT status FROM crm_write_proposal WHERE proposal_id = :id"),
            {"id": first["proposal_id"]},
        )
        assert status == "replaced"
        finalize, authority = _finalizer(seeded)

        await finalize(runtime=cast(Any, object()), **_message_only())

        [envelope] = authority.envelopes
        assert _gate_links(envelope) == [(GATE_OBJECT_TYPE, str(second["gate_id"]))]

    _crm_run(tmp_path, "gl_crm_replaced", body)
