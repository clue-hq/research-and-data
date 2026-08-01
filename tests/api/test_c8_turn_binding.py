"""PC-C8 §6a / AC-6: the engine owns the turn's identity and its captured bytes.

The model classifies a turn — route kind/key, quote offsets, correction lineage, proposed typed
values. Everything that *identifies* the turn (``onboarding_input_id``, ``artifact_key``) and the
captured body itself (``answer``) is stripped from the model surface and served at the execution
seam from a binding compiled off the turn's own artifact and its capture record
(:mod:`clue_api.turn_binding`).

What each test here pins:

* the binding is derived, never accepted — the id comes from the ``onboarding_input`` row that
  cites this turn's artifact, so a forged or foreign id has no path into the call;
* a governed call carrying only offsets lands the statement against the **engine-loaded** bytes;
* an out-of-range offset and a non-entailing quote are refused fail-closed, with nothing written;
* the stripped fields cannot be smuggled back — the model-facing schema refuses them
  (``extra='forbid'``) and the seam refuses them again in plan arguments;
* a step that needs turn authority on an execution with no binding is refused rather than run
  unbound;
* the sha/offset semantics survive the move engine-side: offsets are **character** positions into
  the decoded capture while the digest and byte count are over the raw bytes, so multi-byte text
  behaves identically to ASCII.

The absence of the three fields from the model-facing schema is guarded next door, in
``test_c8_slice0_evidence.py::
test_record_interview_answer_no_longer_lets_the_model_author_the_answer_or_trusted_ids``.

DB-backed tests follow the ``tests/api`` conventions: a per-branch ``CLUE_DATABASE_URL``, one
rollback-only transaction per scenario, and ``pytest.skip`` when no database is reachable.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import AgentTurnRequest, ArtifactRef
from clue_agents.contracts import AgentConstitution, ExecutionId
from clue_api import turn_binding as turn_binding_module
from clue_api.agent_execution_wiring import _trusted_tool_arguments
from clue_api.agent_runtime_wiring import _with_trusted_runtime
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.stage0_tools import RecordInterviewAnswerInput, RecordInterviewAnswerTool
from clue_api.turn_binding import (
    CAPTURE_NOT_FOUND,
    CapturedTurn,
    CapturedTurnBinder,
    CapturedTurnUnavailable,
    RequestCapturedTurn,
    trusted_turn_fields,
)
from clue_config import DEFAULT_STAGE0_POLICY
from clue_core import AccountStatus, EntityId, OnboardingInputId, OnboardingInputKind, OperationId
from clue_db import db_lifespan
from clue_research.identity import insert_account_entity
from clue_research.stage0 import load_client_knowledge_pack, submit_onboarding_input
from clue_spine import create_brand, create_product, create_project, create_workspace
from clue_storage import FsStorage
from clue_toolbelt import ToolContext
from tests.agents.conftest import artifact, constitution, domain_ref
from tests.db.conftest import _db_available, run_async

# One plausible captured turn. The unicode is deliberate: "café" and the emoji are multi-byte, so
# any implementation that confuses byte offsets with character offsets slices the wrong span.
ANSWER = (
    "We sell an AI-native ABM platform to neurosurgery practices — the café conversations "
    "matter more than the ads 🎯 and the administrators own the scheduling pain."
)
QUOTE_START = 37
QUOTE_END = 59  # "neurosurgery practices"


@pytest.fixture
def db_available() -> bool:
    return _db_available()


class _Scope:
    """The workspace/brand/product/project/client one Stage-0 turn is scoped to."""

    def __init__(self) -> None:
        token = uuid4().hex[:8]
        self.workspace_id = f"c8-turn-{token}"
        self.brand_id = f"brand_{token}"
        self.product_id = f"product_{token}"
        self.project_id = f"project_{token}"
        self.client_entity_id: EntityId | None = None


def _constitution(
    *,
    workspace_id: str = "ws-1",
    project_id: str = "project-1",
    brand_id: str = "brand-1",
    product_id: str = "product-1",
    client_entity_id: str = "00000000-0000-0000-0000-0000000000a2",
    execution_id: ExecutionId | None = None,
) -> AgentConstitution:
    """The shared conftest constitution, re-scoped to a per-scenario workspace."""

    return constitution(
        workspace_id=workspace_id,
        project_id=project_id,
        brand_id=brand_id,
        product_id=product_id,
        client_entity_id=client_entity_id,
        execution_id=execution_id or ExecutionId(uuid4()),
        project_card_ref=artifact("project-card.json", workspace_id=workspace_id),
        budget_envelope_ref=artifact("budget.json", workspace_id=workspace_id),
        resource_manifest_ref=artifact("resource-manifest.json", workspace_id=workspace_id),
        focus_refs=(domain_ref("account-1", workspace_id=workspace_id),),
    )


def _request(
    scope: _Scope,
    ref: ArtifactRef,
    *,
    project_id: str | None = None,
    turn: str | None = None,
) -> AgentTurnRequest:
    """A turn request shaped exactly like the one the Stage-0 trial builds.

    ``turn`` names a second (third, …) turn of the *same* project, which is how a trial actually
    runs: one binder, many turns.
    """

    project = project_id or scope.project_id
    suffix = f":{turn}" if turn else ""
    turn_id = uuid5(NAMESPACE_URL, f"c8-turn-binding:{scope.workspace_id}:{project}{suffix}")
    return AgentTurnRequest(
        turn_id=turn_id,
        thread_id=f"thread-{project}",
        constitution=_constitution(
            workspace_id=scope.workspace_id,
            project_id=project,
            brand_id=scope.brand_id,
            product_id=scope.product_id,
            client_entity_id=str(scope.client_entity_id),
            execution_id=ExecutionId(uuid5(turn_id, "execution")),
        ),
        user_message_artifact_ref=ref,
        requested_at=datetime.now(UTC),
    )


async def _scenario(
    tmp_path: Path,
    *,
    body: Callable[..., Any],
    answer: str = ANSWER,
    capture: bool = True,
) -> None:
    """One rollback-only transaction holding a captured Stage-0 turn."""

    scope = _Scope()
    async with db_lifespan() as engine:
        conn = await engine.connect()
        outer = await conn.begin()

        @asynccontextmanager
        async def connection_factory() -> AsyncIterator[AsyncConnection]:
            yield conn

        try:
            await create_workspace(conn, workspace_id=scope.workspace_id, name="C8 turn binding")
            brand = await create_brand(
                conn, workspace_id=scope.workspace_id, name="Aura", brand_id=scope.brand_id
            )
            product = await create_product(
                conn,
                workspace_id=scope.workspace_id,
                brand_id=brand.brand_id,
                name="Aura ABM",
                product_id=scope.product_id,
            )
            await create_project(
                conn,
                workspace_id=scope.workspace_id,
                brand_id=brand.brand_id,
                product_id=product.product_id,
                name="Aura Stage 0",
                project_id=scope.project_id,
            )
            scope.client_entity_id = await insert_account_entity(
                conn,
                canonical_name="Aura AI",
                primary_domain="aura.invalid",
                workspace_id=scope.workspace_id,
                status=AccountStatus.ACTIVE,
            )
            artifacts = DurableAgentArtifactStore(
                storage=FsStorage(tmp_path / "artifacts"),
                conn_factory=connection_factory,
            )
            ref = await artifacts.persist_body(
                workspace_id=scope.workspace_id,
                data=answer.encode(),
                media_type="text/plain",
            )
            captured_id: OnboardingInputId | None = None
            if capture:
                captured = await submit_onboarding_input(
                    conn,
                    workspace_id=scope.workspace_id,
                    brand_id=scope.brand_id,
                    product_id=scope.product_id,
                    project_id=scope.project_id,
                    client_entity_id=scope.client_entity_id,
                    kind=OnboardingInputKind.USER_TURN,
                    artifact_key=ref.artifact_key,
                    content_sha256=ref.sha256,
                    actor="human",
                    onboarding_input_id=OnboardingInputId(
                        uuid5(NAMESPACE_URL, f"c8-turn-binding:{scope.workspace_id}:input")
                    ),
                )
                captured_id = captured.onboarding_input_id
            await body(
                scope=scope,
                conn=conn,
                artifacts=artifacts,
                connection_factory=connection_factory,
                ref=ref,
                captured_id=captured_id,
            )
        finally:
            await outer.rollback()
            await conn.close()


def _tool(connection_factory: Any) -> RecordInterviewAnswerTool:
    return RecordInterviewAnswerTool(
        conn_factory=connection_factory,
        policy=DEFAULT_STAGE0_POLICY,
        pre_spend_gate=cast(Any, object()),
    )


def _ctx(scope: _Scope, connection_factory: Any, *, label: str) -> ToolContext:
    return ToolContext(
        workspace_id=scope.workspace_id,
        actor="agent",
        conn_factory=connection_factory,
        operation_id=OperationId(uuid5(NAMESPACE_URL, f"c8-turn-binding:{label}")),
    )


def _model_arguments(scope: _Scope, *, statements: list[dict[str, Any]]) -> dict[str, Any]:
    """Exactly what the model may author: the classified statements (and the candidate product).

    ``brand_id`` and ``client_entity_id`` left this set with the PC-C8 §10 contract delta — they
    are whole-execution authority served from the constitution, like ``project_id`` before them.
    """

    return {
        "product_id": scope.product_id,
        "statements": statements,
    }


# --- the binding itself ---------------------------------------------------------------------


def test_the_engine_derives_the_turn_binding_from_the_artifact_and_its_capture_record(
    tmp_path: Path,
    db_available: bool,
) -> None:
    """No caller hands the engine a turn id: it joins the capture record to this turn's artifact."""

    if not db_available:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def body(
        *,
        scope: _Scope,
        artifacts: DurableAgentArtifactStore,
        connection_factory: Any,
        ref: ArtifactRef,
        captured_id: OnboardingInputId | None,
        **_: Any,
    ) -> None:
        binder = CapturedTurnBinder(artifacts=artifacts, conn_factory=connection_factory)
        binding = await binder.bind(_request(scope, ref))

        assert binding.onboarding_input_id == str(captured_id)
        assert binding.artifact_key == ref.artifact_key
        assert binding.sha256 == ref.sha256 == hashlib.sha256(ANSWER.encode()).hexdigest()
        # The digest and count are over the raw bytes; the answer is the decoded text.
        assert binding.byte_count == len(ANSWER.encode()) > len(ANSWER)
        assert binding.answer == ANSWER

    run_async(_scenario(tmp_path, body=body))


#: A capture id chosen to sort *after* any ``uuid5``-derived id, so these tests fail if the
#: selection ever falls back to "newest row wins". Rows written inside one transaction share a
#: ``created_at`` (``now()`` is transaction-scoped), so ``id DESC`` is the live tie-break.
HIGHEST_ID = UUID("ffffffff-ffff-4fff-8fff-ffffffffffff")


def test_a_row_the_model_could_write_cannot_become_this_turns_capture_record(
    tmp_path: Path,
    db_available: bool,
) -> None:
    """The agent holds ``submit_onboarding_input``, so selection must not be "newest row wins".

    The artifact key is content-addressed and L7 hands the model that exact key and digest, so an
    agent-written ``user_turn`` row citing this turn's artifact is trivial to produce. If the
    binder selected it, the model would choose its own turn's attribution — and every statement it
    then routes would land against a capture record ``Stage0RoutingReceiptGuard`` is not counting,
    producing an unrepairable repair loop. ``actor='human'`` is what forecloses it.
    """

    if not db_available:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def body(
        *,
        scope: _Scope,
        conn: AsyncConnection,
        artifacts: DurableAgentArtifactStore,
        connection_factory: Any,
        ref: ArtifactRef,
        captured_id: OnboardingInputId | None,
        **_: Any,
    ) -> None:
        forged = await submit_onboarding_input(
            conn,
            workspace_id=scope.workspace_id,
            brand_id=scope.brand_id,
            product_id=scope.product_id,
            project_id=scope.project_id,
            client_entity_id=scope.client_entity_id,
            kind=OnboardingInputKind.USER_TURN,
            artifact_key=ref.artifact_key,
            content_sha256=ref.sha256,
            actor="agent",
            onboarding_input_id=OnboardingInputId(HIGHEST_ID),
        )
        # The forged row really would win a newest-first race: same scope, same artifact, and an
        # id that outranks the human capture on the tie-break.
        assert forged.onboarding_input_id > cast(UUID, captured_id)

        binder = CapturedTurnBinder(artifacts=artifacts, conn_factory=connection_factory)
        binding = await binder.bind(_request(scope, ref))

        assert binding.onboarding_input_id == str(captured_id)
        assert binding.onboarding_input_id != str(forged.onboarding_input_id)

    run_async(_scenario(tmp_path, body=body))


def test_two_projects_answering_identically_each_bind_their_own_capture_record(
    tmp_path: Path,
    db_available: bool,
) -> None:
    """Byte-identical answers share one artifact key; they must not share a capture record.

    "confirm", "yes", "go ahead" — short answers collide across projects by construction, because
    the artifact is content-addressed. Without the project scope the two turns cross-select, and
    one project's statements are attributed to the other's capture (and can be silently dropped by
    the ``uuid5`` ``ON CONFLICT DO NOTHING`` statement ids).
    """

    if not db_available:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def body(
        *,
        scope: _Scope,
        conn: AsyncConnection,
        artifacts: DurableAgentArtifactStore,
        connection_factory: Any,
        ref: ArtifactRef,
        captured_id: OnboardingInputId | None,
        **_: Any,
    ) -> None:
        other_project = f"{scope.project_id}-second"
        await create_project(
            conn,
            workspace_id=scope.workspace_id,
            brand_id=scope.brand_id,
            product_id=scope.product_id,
            name="Aura Stage 0 (second project)",
            project_id=other_project,
        )
        # The same bytes, so the same content-addressed artifact — and an id that would win a
        # workspace-wide newest-first selection.
        other = await submit_onboarding_input(
            conn,
            workspace_id=scope.workspace_id,
            brand_id=scope.brand_id,
            product_id=scope.product_id,
            project_id=other_project,
            client_entity_id=scope.client_entity_id,
            kind=OnboardingInputKind.USER_TURN,
            artifact_key=ref.artifact_key,
            content_sha256=ref.sha256,
            actor="human",
            onboarding_input_id=OnboardingInputId(HIGHEST_ID),
        )
        assert other.artifact_key == ref.artifact_key
        assert other.onboarding_input_id > cast(UUID, captured_id)

        binder = CapturedTurnBinder(artifacts=artifacts, conn_factory=connection_factory)
        first = await binder.bind(_request(scope, ref))
        second = await binder.bind(_request(scope, ref, project_id=other_project))

        assert first.onboarding_input_id == str(captured_id)
        assert second.onboarding_input_id == str(other.onboarding_input_id)
        # Same bytes on both sides; only the attribution differs.
        assert first.answer == second.answer == ANSWER

    run_async(_scenario(tmp_path, body=body))


def test_a_second_turn_repeating_the_first_ones_bytes_binds_its_own_capture_record(
    tmp_path: Path,
    db_available: bool,
) -> None:
    """One binder lives for the whole trial, so its cache must be keyed on the *turn*.

    A user who answers "confirm" (or re-sends any earlier message) produces byte-identical bytes,
    hence the same content-addressed artifact key — while the capture record, which is what the
    binding actually carries, is a new row per turn. A binder caching on
    ``(workspace, project, artifact_key)`` hands turn 2 turn 1's ``onboarding_input_id``: the
    preconditions still pass (same artifact, same digest), the statements land under the previous
    turn's input, ``Stage0RoutingReceiptGuard`` counts zero for *this* turn, and the turn dies in
    an unrepairable repair loop (the ``uuid5`` statement ids dedupe across the two turns as well).
    """

    if not db_available:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def body(
        *,
        scope: _Scope,
        conn: AsyncConnection,
        artifacts: DurableAgentArtifactStore,
        connection_factory: Any,
        ref: ArtifactRef,
        captured_id: OnboardingInputId | None,
        **_: Any,
    ) -> None:
        binder = CapturedTurnBinder(artifacts=artifacts, conn_factory=connection_factory)
        first = await binder.bind(_request(scope, ref, turn="1"))
        assert first.onboarding_input_id == str(captured_id)

        # Turn 2: the same bytes, so the same artifact key — captured as its own row, as the
        # trial's capture surface does on every turn.
        second_capture = await submit_onboarding_input(
            conn,
            workspace_id=scope.workspace_id,
            brand_id=scope.brand_id,
            product_id=scope.product_id,
            project_id=scope.project_id,
            client_entity_id=scope.client_entity_id,
            kind=OnboardingInputKind.USER_TURN,
            artifact_key=ref.artifact_key,
            content_sha256=ref.sha256,
            actor="human",
            onboarding_input_id=OnboardingInputId(HIGHEST_ID),
        )
        assert second_capture.artifact_key == ref.artifact_key

        second = await binder.bind(_request(scope, ref, turn="2"))

        assert second.onboarding_input_id == str(second_capture.onboarding_input_id)
        assert second.onboarding_input_id != first.onboarding_input_id
        # Only the attribution moved: the bytes really are identical on both turns.
        assert second.answer == first.answer == ANSWER
        assert second.sha256 == first.sha256 == ref.sha256

    run_async(_scenario(tmp_path, body=body))


def test_a_turn_that_is_not_a_captured_input_binds_nothing(
    tmp_path: Path,
    db_available: bool,
) -> None:
    """Fail-closed: no capture record, no binding — and the L7 envelope simply stays quiet."""

    if not db_available:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def body(
        *,
        scope: _Scope,
        artifacts: DurableAgentArtifactStore,
        connection_factory: Any,
        ref: ArtifactRef,
        **_: Any,
    ) -> None:
        binder = CapturedTurnBinder(artifacts=artifacts, conn_factory=connection_factory)
        request = _request(scope, ref)
        with pytest.raises(
            CapturedTurnUnavailable, match="not a captured onboarding input"
        ) as raised:
            await binder.bind(request)
        assert raised.value.reason_code == CAPTURE_NOT_FOUND
        # Context assembly must still work: describing an unbound turn is None, not a failure —
        # and this is the one reason that is ordinary, so it is not logged as an alarm.
        assert await binder.describe(request) is None

    run_async(_scenario(tmp_path, body=body, capture=False))


class _DisagreeingArtifacts:
    """An artifact reader that returns bytes other than the ones the ref claims."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    async def read(self, ref: ArtifactRef) -> bytes:
        del ref
        return self._body


def test_bytes_that_do_not_hash_to_the_turn_ref_bind_nothing_and_never_reach_the_database() -> None:
    """The sha verification that used to run inside the tool now runs before injection.

    The production store refuses a ref whose digest disagrees with its durable row before this is
    reached, so this is the binder's own second line — asserted against a reader that lies. It runs
    *before* the capture lookup, so a mismatched turn never gets as far as a DB read: the
    connection factory here would raise if it were touched.
    """

    async def unusable_conn_factory() -> Any:  # pragma: no cover - must never be called
        raise AssertionError("digest mismatch must be refused before the capture lookup")

    scope = _Scope()
    ref = artifact("user-message.txt", workspace_id=scope.workspace_id)
    binder = CapturedTurnBinder(
        artifacts=_DisagreeingArtifacts(b"a different turn entirely"),
        conn_factory=cast(Any, unusable_conn_factory),
    )
    with pytest.raises(CapturedTurnUnavailable, match="does not hash to its own artifact"):
        run_async(binder.bind(_request(scope, ref)))


def test_an_integrity_disagreement_fails_soft_at_l7_but_never_silently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``describe`` must not turn "these two records disagree" into an absent envelope and nothing.

    Failing soft is right — L7 has to assemble either way — but only ``capture_not_found`` is
    ordinary. A digest disagreement is an integrity alarm and is logged as one.
    """

    emitted: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        turn_binding_module,
        "log",
        SimpleNamespace(warning=lambda event, **fields: emitted.append((event, fields))),
    )

    async def unusable_conn_factory() -> Any:  # pragma: no cover - must never be called
        raise AssertionError("digest mismatch must be refused before the capture lookup")

    scope = _Scope()
    ref = artifact("user-message.txt", workspace_id=scope.workspace_id)
    binder = CapturedTurnBinder(
        artifacts=_DisagreeingArtifacts(b"a different turn entirely"),
        conn_factory=cast(Any, unusable_conn_factory),
    )

    assert run_async(binder.describe(_request(scope, ref))) is None

    assert [event for event, _ in emitted] == ["stage0.captured_turn.unavailable"]
    fields = emitted[0][1]
    assert fields["reason_code"] == "artifact_digest_mismatch"
    assert fields["reason_code"] != CAPTURE_NOT_FOUND
    assert fields["workspace_id"] == scope.workspace_id
    assert fields["project_id"] == scope.project_id
    assert fields["artifact_key"] == ref.artifact_key


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param("Plain ASCII answer about scheduling pain.", id="ascii"),
        pytest.param("We sell to café and naïve clinics — mostly.", id="latin1-supplement"),
        pytest.param("Target: 神経外科 practices in 日本.", id="cjk"),
        pytest.param("Priority 🎯 is the administrator, not the surgeon.", id="astral-emoji"),
    ],
)
def test_offsets_stay_character_positions_while_the_digest_stays_over_bytes(
    tmp_path: Path,
    db_available: bool,
    answer: str,
) -> None:
    """The move engine-side must not silently re-denominate offsets.

    ``interview._exact_quote`` slices a Python ``str``, so offsets are characters; the artifact
    digest and byte count are over UTF-8 bytes. Both were true before 1.2 and both must stay true
    after it, or every multi-byte turn quotes the wrong span.
    """

    if not db_available:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def body(
        *,
        scope: _Scope,
        artifacts: DurableAgentArtifactStore,
        connection_factory: Any,
        ref: ArtifactRef,
        **_: Any,
    ) -> None:
        binder = CapturedTurnBinder(artifacts=artifacts, conn_factory=connection_factory)
        binding = await binder.bind(_request(scope, ref))

        assert binding.answer == answer
        assert binding.sha256 == hashlib.sha256(answer.encode()).hexdigest()
        assert binding.byte_count == len(answer.encode())
        # The whole-message span is the message, whatever its byte length.
        assert binding.answer[0 : len(answer)] == answer

    run_async(_scenario(tmp_path, body=body, answer=answer))


# --- the governed call ----------------------------------------------------------------------


def test_a_governed_call_of_offsets_alone_lands_the_statement_on_engine_loaded_bytes(
    tmp_path: Path,
    db_available: bool,
) -> None:
    """AC-6: model-supplied offsets, engine-supplied body — and a durable, verbatim quote."""

    if not db_available:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def body(
        *,
        scope: _Scope,
        conn: AsyncConnection,
        artifacts: DurableAgentArtifactStore,
        connection_factory: Any,
        ref: ArtifactRef,
        captured_id: OnboardingInputId | None,
        **_: Any,
    ) -> None:
        # The ``client`` field-class is seeded, not migrated, so a freshly-migrated database has
        # no source profile for it and the write refuses before it reaches the assertions here.
        await load_client_knowledge_pack(conn)
        request = _request(scope, ref)
        source = RequestCapturedTurn(
            binder=CapturedTurnBinder(artifacts=artifacts, conn_factory=connection_factory),
            request=request,
        )
        proposed = _model_arguments(
            scope,
            statements=[
                {
                    "route": "project_state",
                    "route_key": "target_segment",
                    "quote_start": QUOTE_START,
                    "quote_end": QUOTE_END,
                }
            ],
        )
        merged = _trusted_tool_arguments(
            arguments=proposed,
            input_model=RecordInterviewAnswerInput,
            constitution=request.constitution,
            captured_turn=await source.captured_turn(),
        )
        # The three turn fields appeared out of the binding, not out of the proposal.
        assert merged["onboarding_input_id"] == str(captured_id)
        assert merged["artifact_key"] == ref.artifact_key
        assert merged["answer"] == ANSWER
        assert merged["project_id"] == scope.project_id

        inputs = RecordInterviewAnswerInput.model_validate(merged)
        tool = _tool(connection_factory)
        ctx = _ctx(scope, connection_factory, label="lands")
        assert await tool.preconditions(inputs, ctx) == ()
        result = await tool.invoke(inputs, ctx)

        statement_ids = result.references["statement_ids"]
        assert isinstance(statement_ids, list) and len(statement_ids) == 1
        stored = (
            (
                await conn.execute(
                    text(
                        "SELECT quote_sha256, quote_start, quote_end, onboarding_input_id "
                        "FROM volunteered_statement WHERE id = :id"
                    ),
                    {"id": UUID(str(statement_ids[0]))},
                )
            )
            .mappings()
            .one()
        )
        # The durable evidence hash is the hash of the slice taken from the bytes the *engine*
        # loaded — text the model never sent, at offsets the model chose.
        quote = ANSWER[QUOTE_START:QUOTE_END]
        assert quote == "neurosurgery practices"
        assert stored["quote_sha256"] == hashlib.sha256(quote.encode()).hexdigest()
        assert (stored["quote_start"], stored["quote_end"]) == (QUOTE_START, QUOTE_END)
        assert stored["onboarding_input_id"] == captured_id

    run_async(_scenario(tmp_path, body=body))


def test_a_governed_quote_after_a_multi_byte_character_lands_the_characters_not_the_bytes(
    tmp_path: Path,
    db_available: bool,
) -> None:
    """The discriminating case: a span whose character and byte offsets disagree.

    ``QUOTE_START``/``QUOTE_END`` above sit entirely before the first multi-byte character, so a
    byte-offset implementation would pass that test unnoticed. This span starts after the astral
    emoji, where the two denominations have drifted by five bytes: reading it as bytes yields
    ``"d the administ"`` instead of ``"administrators"``, and the durable evidence hash says so.
    """

    if not db_available:
        pytest.skip("requires a migrated per-branch Postgres database")

    start = ANSWER.index("administrators")
    end = start + len("administrators")

    async def body(
        *,
        scope: _Scope,
        conn: AsyncConnection,
        artifacts: DurableAgentArtifactStore,
        connection_factory: Any,
        ref: ArtifactRef,
        **_: Any,
    ) -> None:
        # The premise: this span is past a multi-byte character, so the two readings differ.
        assert ANSWER.index("🎯") < start
        assert ANSWER.encode()[start:end] != ANSWER[start:end].encode()

        await load_client_knowledge_pack(conn)
        request = _request(scope, ref)
        binder = CapturedTurnBinder(artifacts=artifacts, conn_factory=connection_factory)
        merged = _trusted_tool_arguments(
            arguments=_model_arguments(
                scope,
                statements=[
                    {
                        "route": "project_state",
                        "route_key": "buying_committee_shape",
                        "quote_start": start,
                        "quote_end": end,
                    }
                ],
            ),
            input_model=RecordInterviewAnswerInput,
            constitution=request.constitution,
            captured_turn=await binder.bind(request),
        )
        tool = _tool(connection_factory)
        result = await tool.invoke(
            RecordInterviewAnswerInput.model_validate(merged),
            _ctx(scope, connection_factory, label="multibyte"),
        )

        statement_ids = result.references["statement_ids"]
        assert isinstance(statement_ids, list) and len(statement_ids) == 1
        stored_sha = (
            await conn.execute(
                text("SELECT quote_sha256 FROM volunteered_statement WHERE id = :id"),
                {"id": UUID(str(statement_ids[0]))},
            )
        ).scalar_one()
        assert ANSWER[start:end] == "administrators"
        assert stored_sha == hashlib.sha256(ANSWER[start:end].encode()).hexdigest()
        assert stored_sha != hashlib.sha256(ANSWER.encode()[start:end]).hexdigest()

    run_async(_scenario(tmp_path, body=body))


def test_an_offset_past_the_captured_message_is_refused_and_writes_nothing(
    tmp_path: Path,
    db_available: bool,
) -> None:
    """Fail-closed against the *engine-loaded* bytes, exactly as it used to be against the echo."""

    if not db_available:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def body(
        *,
        scope: _Scope,
        conn: AsyncConnection,
        artifacts: DurableAgentArtifactStore,
        connection_factory: Any,
        ref: ArtifactRef,
        **_: Any,
    ) -> None:
        await load_client_knowledge_pack(conn)
        request = _request(scope, ref)
        binder = CapturedTurnBinder(artifacts=artifacts, conn_factory=connection_factory)
        merged = _trusted_tool_arguments(
            arguments=_model_arguments(
                scope,
                statements=[
                    {
                        "route": "project_state",
                        "route_key": "target_segment",
                        "quote_start": QUOTE_START,
                        "quote_end": len(ANSWER) + 500,
                    }
                ],
            ),
            input_model=RecordInterviewAnswerInput,
            constitution=request.constitution,
            captured_turn=await binder.bind(request),
        )
        tool = _tool(connection_factory)
        ctx = _ctx(scope, connection_factory, label="out-of-range")
        inputs = RecordInterviewAnswerInput.model_validate(merged)
        with pytest.raises(ValueError, match="offsets fall outside the captured answer"):
            await tool.invoke(inputs, ctx)

        written = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM volunteered_statement WHERE workspace_id = :workspace_id"
                ),
                {"workspace_id": scope.workspace_id},
            )
        ).scalar_one()
        assert written == 0

    run_async(_scenario(tmp_path, body=body))


def test_a_claim_value_the_engine_loaded_quote_does_not_entail_is_refused(
    tmp_path: Path,
    db_available: bool,
) -> None:
    """The entailment check now runs against the artifact bytes; a paraphrase still cannot land."""

    if not db_available:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def body(
        *,
        scope: _Scope,
        conn: AsyncConnection,
        artifacts: DurableAgentArtifactStore,
        connection_factory: Any,
        ref: ArtifactRef,
        **_: Any,
    ) -> None:
        await load_client_knowledge_pack(conn)
        request = _request(scope, ref)
        binder = CapturedTurnBinder(artifacts=artifacts, conn_factory=connection_factory)
        merged = _trusted_tool_arguments(
            arguments=_model_arguments(
                scope,
                statements=[
                    {
                        "route": "claim",
                        "route_key": "client.product.description",
                        "quote_start": QUOTE_START,
                        "quote_end": QUOTE_END,
                        "entity_id": str(scope.client_entity_id),
                        "entity_type": "account",
                        "field_key": "client.product.description",
                        "value": "brain surgery clinics",
                    }
                ],
            ),
            input_model=RecordInterviewAnswerInput,
            constitution=request.constitution,
            captured_turn=await binder.bind(request),
        )
        tool = _tool(connection_factory)
        inputs = RecordInterviewAnswerInput.model_validate(merged)
        with pytest.raises(ValueError, match="not textually entailed"):
            await tool.invoke(inputs, _ctx(scope, connection_factory, label="entailment"))

    run_async(_scenario(tmp_path, body=body))


# --- the stripped fields cannot come back ----------------------------------------------------


def test_the_model_facing_schema_refuses_smuggled_turn_authority() -> None:
    """``extra='forbid'`` is what makes the strip a boundary rather than a suggestion."""

    args_schema = _with_trusted_runtime(
        RecordInterviewAnswerInput,
        name="RecordInterviewAnswerInputAgentRuntime",
    )
    assert set(trusted_turn_fields(RecordInterviewAnswerInput)) == {
        "onboarding_input_id",
        "artifact_key",
        "answer",
    }
    assert set(trusted_turn_fields(args_schema)) == set()

    valid = {
        "statements": [
            {
                "route": "project_state",
                "route_key": "target_segment",
                "quote_start": 0,
                "quote_end": 5,
            }
        ],
        "runtime": None,
    }
    for smuggled in (
        "answer",
        "onboarding_input_id",
        "artifact_key",
        "project_id",
        "brand_id",
        "client_entity_id",
    ):
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            args_schema.model_validate({**valid, smuggled: "forged"})


def test_the_seam_refuses_turn_authority_that_reaches_it_in_plan_arguments() -> None:
    """Defence in depth: even a plan built past the schema cannot carry a forged capture id."""

    binding = CapturedTurn(
        onboarding_input_id="00000000-0000-0000-0000-00000000beef",
        artifact_key="ws-1/real-turn",
        sha256="0" * 64,
        byte_count=4,
        answer="real",
    )
    with pytest.raises(ValueError, match="trusted turn authority"):
        _trusted_tool_arguments(
            arguments={"onboarding_input_id": "forged"},
            input_model=RecordInterviewAnswerInput,
            constitution=_constitution(),
            captured_turn=binding,
        )


def test_a_step_needing_turn_authority_without_a_binding_is_refused() -> None:
    """An unbound execution refuses the call; it never runs the tool against nothing."""

    with pytest.raises(CapturedTurnUnavailable, match="captured input, which is unavailable"):
        _trusted_tool_arguments(
            arguments={},
            input_model=RecordInterviewAnswerInput,
            constitution=_constitution(),
            captured_turn=None,
        )
