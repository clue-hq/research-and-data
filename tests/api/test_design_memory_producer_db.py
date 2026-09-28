"""Scene memory producer: trusted scope, body-free dispatch, dependencies and retry identity."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_api.agent_turn_scope_pin import (
    AgentTurnScopePinConflict,
    load_or_create_agent_turn_scope_pin,
)
from clue_api.agent_turn_submission import message_artifact_ref
from clue_api.agent_turn_wiring import (
    DbAgentContextReceiptStore,
    DbAgentHistoryStore,
    DbAgentTurnJournal,
)
from clue_api.design_leg_wiring import DesignLegTurnRunner, design_leg_execution_id
from clue_core import (
    AssemblyRequest,
    MemoryBundle,
    MemoryBundleEntry,
    MemoryLabel,
    MemoryProvenanceClass,
    MemoryScopeType,
    MemorySelectionPin,
    MemorySelectionUnavailable,
    MemoryType,
)
from clue_design import brand as design_brand
from clue_design import legs as design_legs
from clue_spine import create_brand, create_product
from tests.api.test_p34_design_leg_engine_db import (
    _card_payload,
    _FakeLane,
    _pin_document,
    _seed_leg_conversation,
    _submit_message,
    registry,  # noqa: F401 -- shared profile fixture
)
from tests.db.conftest import run_async
from tests.profiling.conftest import migrated_db, rollback_conn  # noqa: F401 -- DB fixture

BODY = "Memory body sentinel that must never enter the platform envelope."
TRIGGER = "Trigger sentinel that must never enter durable platform artifacts."


class _Memory:
    def __init__(self, *, state: str = "selected") -> None:
        self.state = state
        self.requests: list[AssemblyRequest] = []

    async def select(
        self, request: AssemblyRequest
    ) -> MemorySelectionPin | MemorySelectionUnavailable:
        self.requests.append(request)
        if self.state == "off":
            return MemorySelectionUnavailable(reason="memory_disabled")
        if self.state == "must_not_select":
            raise AssertionError("this turn must not select memory")
        bundle = MemoryBundle(
            workspace_id=request.scope_stack.workspace_id,
            recipe=request.recipe,
            entries=()
            if self.state == "empty"
            else (
                MemoryBundleEntry(
                    memory_id="mem_selected",
                    body=BODY,
                    label=MemoryLabel(
                        scope_type=MemoryScopeType.BRAND,
                        scope_id=request.scope_stack.brand_id,
                        type=MemoryType.PREFERENCE,
                        trigger=TRIGGER,
                        provenance_class=MemoryProvenanceClass.USER_STATED,
                        trust_grade=3,
                        cycles_since_confirmed=0,
                        confirmation_count=0,
                    ),
                ),
            ),
        )
        return MemorySelectionPin(
            request=request,
            journal_id=uuid4(),
            selected_ids=tuple(e.memory_id for e in bundle.entries),
            bundle_hash=bundle.bundle_hash(),
        )

    async def assemble(self, request: AssemblyRequest) -> None:
        raise AssertionError("the platform producer may not read memory bodies")

    async def resolve(self, request: AssemblyRequest, pin: MemorySelectionPin) -> None:
        raise AssertionError("only the runtime consumer resolves memory")


async def _kit(conn: Any, seeds: dict[str, Any], *, brand_id: str | None = None) -> None:
    kit_id = f"kit_{uuid4().hex}"
    await design_brand.create_brand_kit(
        conn,
        workspace_id=seeds["workspace_id"],
        brand_kit={"id": kit_id, "version": 1, "name": "Test kit", "approval_status": "approved"},
        brand_summary={},
        diagnostics=[],
        source="manual",
        brand_id=brand_id or seeds["project"].brand_id,
    )
    await conn.execute(
        text("UPDATE design_leg SET brand_kit_id=:kit, brand_kit_version=1 WHERE id=:leg"),
        {"kit": kit_id, "leg": seeds["leg"]["id"]},
    )


async def _run(
    conn: Any,
    seeds: dict[str, Any],
    profiles: Any,
    lane: Any,
    submission: Any,
    memory: Any,
    scope_pin: Any,
) -> Any:
    leg = await design_legs.get_open_leg_for_thread(
        conn, workspace_id=seeds["workspace_id"], thread_id=seeds["thread_id"]
    )
    return await DesignLegTurnRunner(
        profiles=profiles,
        artifacts=seeds["artifacts"],
        turns=DbAgentTurnJournal(conn_factory=seeds["conn_factory"]),
        history=DbAgentHistoryStore(conn_factory=seeds["conn_factory"]),
        lane=lane,
        memory=memory,
        conn_factory=seeds["conn_factory"],
    ).run_leg_turn(
        submission=submission,
        leg=leg,
        user_message_ref=await message_artifact_ref(conn, submission),
        focus_refs=(),
        card_payload=_card_payload(seeds),
        stream=None,
        scope_pin=scope_pin,
    )


@pytest.mark.parametrize("state", ["selected", "empty", "off"])
def test_scene_freezes_preference_selection_and_dependency_refs(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811 -- shared DB fixture
    registry: Any,  # noqa: F811 -- shared profile fixture
    state: str,
) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label=state)
            await _kit(conn, seeds)
            submission = await _submit_message(conn, seeds, label=state, message="Create an ad.")
            scope_pin, _ = await load_or_create_agent_turn_scope_pin(conn, submission=submission)
            # A later project edit must not retarget the already-pinned turn's authority.
            other = await create_product(
                conn,
                workspace_id=seeds["workspace_id"],
                brand_id=scope_pin.brand_id,
                name="Later product",
            )
            await conn.execute(
                text("UPDATE project SET product_id=:product WHERE project_id=:project"),
                {"product": other.product_id, "project": submission.project_id},
            )
            memory = _Memory(state=state)
            lane = _FakeLane(conn_factory=seeds["conn_factory"])
            await _run(conn, seeds, registry, lane, submission, memory, scope_pin)
            envelope = lane.envelopes[0]
            frozen = envelope.config["design_memory"]
            assert frozen["version"] == 1
            assert frozen["turn_id"] == str(submission.turn_id)
            assert frozen["execution_id"] == str(design_leg_execution_id(submission.turn_id))
            request = AssemblyRequest.model_validate(frozen["request"])
            assert request.recipe == "scene-preferences-v1"
            assert request.requested_types == (MemoryType.PREFERENCE,)
            assert request.scope_stack.brand_id == scope_pin.brand_id
            assert request.scope_stack.product_id == scope_pin.product_id
            assert memory.requests == [request]
            assert (
                BODY not in envelope.model_dump_json() and TRIGGER not in envelope.model_dump_json()
            )
            refs = (
                (
                    await conn.execute(
                        text(
                            "SELECT r.object_type, r.object_id, r.token_count "
                            "FROM agent_context_ref r JOIN agent_context_bundle b "
                            "ON b.id=r.context_bundle_id WHERE b.turn_id=:turn"
                        ),
                        {"turn": submission.turn_id},
                    )
                )
                .mappings()
                .all()
            )
            if state == "off":
                assert frozen["selection"] == {"status": "unavailable", "reason": "memory_disabled"}
                assert refs == []
            else:
                assert [r["object_id"] for r in refs if r["object_type"] == "scoped_memory"] == (
                    ["mem_selected"] if state == "selected" else []
                )
                assert any(r["object_type"] == "memory_bundle_journal" for r in refs)
                assert all(r["token_count"] == 0 for r in refs)
            for path in (tmp_path / "artifacts").rglob("*"):
                if path.is_file():
                    assert BODY.encode() not in path.read_bytes()
                    assert TRIGGER.encode() not in path.read_bytes()

    run_async(scenario())


@pytest.mark.parametrize("mode", ["no_pin", "web"])
def test_legacy_and_web_turns_have_no_memory_payload_or_selection(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811 -- shared DB fixture
    registry: Any,  # noqa: F811 -- shared profile fixture
    mode: str,
) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label=mode)
            if mode == "web":
                await _pin_document(conn, seeds, doc_kind="web", version=1)
            submission = await _submit_message(conn, seeds, label=mode, message="Create an ad.")
            scope_pin, _ = await load_or_create_agent_turn_scope_pin(conn, submission=submission)
            memory = _Memory(state="must_not_select")
            lane = _FakeLane(conn_factory=seeds["conn_factory"])
            await _run(
                conn,
                seeds,
                registry,
                lane,
                submission,
                memory,
                None if mode == "no_pin" else scope_pin,
            )
            assert "design_memory" not in lane.envelopes[0].config
            assert memory.requests == []

    run_async(scenario())


@pytest.mark.parametrize("kit_state", ["mismatch", "absent", "unresolved"])
def test_canonical_kit_mismatch_refuses_before_selection(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811 -- shared DB fixture
    registry: Any,  # noqa: F811 -- shared profile fixture
    kit_state: str,
) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="mismatch")
            other = await create_brand(conn, workspace_id=seeds["workspace_id"], name="Other")
            if kit_state != "absent":
                await _kit(conn, seeds, brand_id=other.brand_id)
            if kit_state == "unresolved":
                await conn.execute(
                    text("UPDATE design_brand_kit SET brand_id=NULL WHERE workspace_id=:ws"),
                    {"ws": seeds["workspace_id"]},
                )
            submission = await _submit_message(
                conn, seeds, label="mismatch", message="Create an ad."
            )
            scope_pin, _ = await load_or_create_agent_turn_scope_pin(conn, submission=submission)
            memory = _Memory(state="must_not_select")
            lane = _FakeLane(conn_factory=seeds["conn_factory"])
            result = await _run(conn, seeds, registry, lane, submission, memory, scope_pin)
            assert result.outcome.failure_code == "design_leg_memory_scope_unresolved"
            assert lane.envelopes == [] and memory.requests == []

    run_async(scenario())


@pytest.mark.parametrize("field", ["turn_id", "workspace_id", "project_id"])
def test_wrong_scope_pin_identity_is_rejected_before_dispatch(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811 -- shared DB fixture
    registry: Any,  # noqa: F811 -- shared profile fixture
    field: str,
) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label=field)
            submission = await _submit_message(conn, seeds, label=field, message="Create an ad.")
            pin, _ = await load_or_create_agent_turn_scope_pin(conn, submission=submission)
            pin = pin.model_copy(update={field: uuid4() if field == "turn_id" else "foreign"})
            with pytest.raises(AgentTurnScopePinConflict):
                await _run(
                    conn,
                    seeds,
                    registry,
                    _FakeLane(conn_factory=seeds["conn_factory"]),
                    submission,
                    _Memory(state="must_not_select"),
                    pin,
                )

    run_async(scenario())


@pytest.mark.parametrize("crash_at", ["lane", "receipt", "terminal_before_receipt"])
def test_stranded_run_reuses_frozen_envelope_without_selecting_again(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811 -- shared DB fixture
    registry: Any,  # noqa: F811 -- shared profile fixture
    monkeypatch: pytest.MonkeyPatch,
    crash_at: str,
) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="retry")
            await _kit(conn, seeds)
            submission = await _submit_message(conn, seeds, label="retry", message="Create an ad.")
            pin, _ = await load_or_create_agent_turn_scope_pin(conn, submission=submission)
            memory = _Memory()

            class CrashLane:
                async def drive(self, *, envelope: Any) -> None:
                    raise RuntimeError("crash after run and selection were frozen")

            with monkeypatch.context() as patch:
                if crash_at != "lane":

                    async def fail_receipt(*args: Any, **kwargs: Any) -> None:
                        if crash_at == "terminal_before_receipt":
                            # Another worker may complete a durably queued run before the
                            # producer repairs its missing privacy receipt on retry.
                            await conn.execute(
                                text(
                                    "UPDATE design_agent_run SET status='succeeded', "
                                    "result_json='{}'::jsonb WHERE execution_id=:execution"
                                ),
                                {"execution": design_leg_execution_id(submission.turn_id)},
                            )
                        raise RuntimeError("crash after run before receipt write")

                    patch.setattr(DbAgentContextReceiptStore, "record", fail_receipt)
                with pytest.raises(RuntimeError, match="crash after"):
                    await _run(conn, seeds, registry, CrashLane(), submission, memory, pin)
            frozen = (
                await conn.execute(
                    text("SELECT payload FROM design_agent_run WHERE execution_id=:id"),
                    {"id": design_leg_execution_id(submission.turn_id)},
                )
            ).scalar_one()
            memory.state = "must_not_select"
            lane = _FakeLane(conn_factory=seeds["conn_factory"])
            await _run(conn, seeds, registry, lane, submission, memory, pin)
            if crash_at == "terminal_before_receipt":
                assert lane.envelopes == []
            else:
                assert lane.envelopes[0].model_dump(mode="json") == frozen
            assert len(memory.requests) == 1
            count = (
                await conn.execute(
                    text("SELECT count(*) FROM agent_context_bundle WHERE turn_id=:turn"),
                    {"turn": submission.turn_id},
                )
            ).scalar_one()
            assert count == 1

    run_async(scenario())
