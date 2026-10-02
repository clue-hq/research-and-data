"""Real producer/read-seam authorization across the platform-loop/design-thread boundary."""

# ruff: noqa: F811 -- imported pytest fixtures are intentionally function arguments

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_api.agent_turn_scope_pin import load_or_create_agent_turn_scope_pin
from clue_api.memory_wiring import memory_assembly_factory
from clue_core import MemoryBundle, MemorySelectionUnavailable
from clue_design.sessions import design_session_id
from clue_memory import WriteSeam, set_memory_enabled
from tests.api.test_design_memory_producer_db import _kit, _run
from tests.api.test_p34_design_leg_engine_db import (
    _pin_document,
    _seed_leg_conversation,
    _submit_message,
    registry,  # noqa: F401 -- shared profile fixture
)
from tests.db.conftest import run_async
from tests.memory.conftest import (
    add_judge,
    make_caps,
    make_settings,
)
from tests.memory.conftest import (
    submission as memory_submission,
)
from tests.profiling.conftest import migrated_db, rollback_conn  # noqa: F401 -- DB fixture

BODY = "Prefer restrained colors for this campaign."


class _ObservedMemory:
    def __init__(self, memory: Any) -> None:
        self.memory = memory
        self.reads = 0

    async def resolve(self, *args: Any) -> Any:
        self.reads += 1
        return await self.memory.resolve(*args)


async def _prepared(
    conn: Any, tmp_path: Path, registry: Any, *, off: bool = False, pin_document: bool = False
) -> tuple[Any, ...]:
    seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label=uuid4().hex)
    await _kit(conn, seeds)
    if pin_document:
        # Session continuity (2026-09-18): a pinned leg's turn names the DOCUMENT's session as
        # its checkpoint thread, so the authorization below must accept that naming.
        await _pin_document(conn, seeds, doc_kind="scene", version=1)
    outcome = await WriteSeam(conn, add_judge(), settings=make_settings(), caps=make_caps()).submit(
        memory_submission(seeds["workspace_id"], scope_id=seeds["project"].brand_id, body=BODY)
    )
    if off:
        await set_memory_enabled(conn, seeds["workspace_id"], False, actor="test")
    submitted = await _submit_message(conn, seeds, label=uuid4().hex, message="Create an ad.")
    pin, _ = await load_or_create_agent_turn_scope_pin(conn, submission=submitted)
    memory = memory_assembly_factory(make_settings(), seeds["conn_factory"])
    envelopes: list[Any] = []

    class PausedLane:
        async def drive(self, *, envelope: Any) -> None:
            envelopes.append(envelope)
            raise RuntimeError("pause before the design worker")

    with pytest.raises(RuntimeError, match="pause before"):
        await _run(conn, seeds, registry, PausedLane(), submitted, memory, pin)
    return seeds, submitted, memory, envelopes[0], outcome.memory_id


def test_thread_resolver_reads_current_eligibility_on_the_captured_loop(
    tmp_path: Path,
    migrated_db: bool,
    registry: Any,  # noqa: F811 -- shared fixtures
) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")
    from clue_api import design_memory_runtime

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds, _, memory, envelope, _ = await _prepared(conn, tmp_path, registry)
            observed = _ObservedMemory(memory)
            factory = design_memory_runtime.build_design_preference_resolver_factory(
                memory=observed,
                conn_factory=seeds["conn_factory"],
            )
            resolver = await asyncio.to_thread(factory, envelope)
            assert resolver is not None
            bundle = await asyncio.to_thread(resolver)
            assert isinstance(bundle, MemoryBundle)
            assert [entry.body for entry in bundle.entries] == [BODY]
            assert observed.reads == 1
            await set_memory_enabled(conn, seeds["workspace_id"], False, actor="test")
            disabled = await asyncio.to_thread(resolver)
            assert isinstance(disabled, MemorySelectionUnavailable)
            assert disabled.reason == "memory_disabled"
            assert observed.reads == 2

    run_async(scenario())


@pytest.mark.parametrize("field", ["project_id", "brand_id", "product_id", "selection"])
def test_stored_payload_alone_cannot_replace_scope_pin_or_dependency_receipt(
    tmp_path: Path, migrated_db: bool, registry: Any, field: str
) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")
    from clue_api.design_memory_runtime import (
        DesignMemoryRuntimeError,
        build_design_preference_resolver_factory,
    )

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds, _, memory, envelope, _ = await _prepared(conn, tmp_path, registry)
            payload = envelope.model_dump(mode="json")
            box = payload["config"]["design_memory"]
            if field == "selection":
                # Another valid selection in the same scope must not silently replace the
                # dependency IDs/hash already recorded for this turn.
                from clue_core import AssemblyRequest

                replacement = await memory.select(AssemblyRequest.model_validate(box["request"]))
                box["selection"] = replacement.model_dump(mode="json")
            else:
                box["request"]["scope_stack"][field] = "foreign"
                box["selection"]["request"]["scope_stack"][field] = "foreign"
            await conn.execute(
                text(
                    "UPDATE design_agent_run SET payload=CAST(:payload AS jsonb) WHERE run_id=:id"
                ),
                {"payload": json.dumps(payload), "id": envelope.run_id},
            )
            observed = _ObservedMemory(memory)
            factory = build_design_preference_resolver_factory(
                memory=observed, conn_factory=seeds["conn_factory"]
            )
            with pytest.raises(DesignMemoryRuntimeError):
                await asyncio.to_thread(factory, type(envelope).model_validate(payload))
            assert observed.reads == 0

    run_async(scenario())


def test_tombstone_retry_refuses_before_receipt_reconstruction_or_terminal_rejoin(
    tmp_path: Path, migrated_db: bool, registry: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")
    from clue_api.agent_turn_wiring import DbAgentContextReceiptStore
    from clue_api.design_memory import DesignMemoryScopeError

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds, submitted, memory, envelope, _ = await _prepared(conn, tmp_path, registry)
            pin, _ = await load_or_create_agent_turn_scope_pin(conn, submission=submitted)
            await conn.execute(
                text("UPDATE design_agent_run SET status='succeeded' WHERE run_id=:id"),
                {"id": envelope.run_id},
            )
            for status in ("privacy_tombstoned", "running"):
                await conn.execute(
                    text(
                        "INSERT INTO agent_turn_event (event_id, turn_id, workspace_id, status) "
                        "VALUES (:event, :turn, :workspace, :status)"
                    ),
                    {
                        "event": uuid4(),
                        "turn": submitted.turn_id,
                        "workspace": seeds["workspace_id"],
                        "status": status,
                    },
                )
            attempts: list[str] = []

            async def forbidden_receipt(*args: Any, **kwargs: Any) -> None:
                attempts.append("receipt")

            class ForbiddenLane:
                async def drive(self, **kwargs: Any) -> None:
                    attempts.append("lane")

            monkeypatch.setattr(DbAgentContextReceiptStore, "record", forbidden_receipt)
            with pytest.raises(DesignMemoryScopeError, match="privacy_tombstoned"):
                await _run(conn, seeds, registry, ForbiddenLane(), submitted, memory, pin)
            assert attempts == []

    run_async(scenario())


def test_erasure_during_shared_resolution_cannot_release_a_body_to_the_model(
    tmp_path: Path, migrated_db: bool, registry: Any
) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")
    from clue_api.design_memory_runtime import (
        DesignMemoryRuntimeError,
        build_design_preference_resolver_factory,
    )

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds, submitted, memory, envelope, _ = await _prepared(conn, tmp_path, registry)
            calls: list[str] = []

            class ErasureDuringRead:
                async def resolve(self, *args: Any) -> Any:
                    bundle = await memory.resolve(*args)
                    assert isinstance(bundle, MemoryBundle) and bundle.entries[0].body == BODY
                    calls.append("body resolved")
                    await conn.execute(
                        text(
                            "INSERT INTO agent_turn_event "
                            "(event_id, turn_id, workspace_id, status) "
                            "VALUES (:event, :turn, :workspace, 'privacy_tombstoned')"
                        ),
                        {
                            "event": uuid4(),
                            "turn": submitted.turn_id,
                            "workspace": seeds["workspace_id"],
                        },
                    )
                    return bundle

            factory = build_design_preference_resolver_factory(
                memory=ErasureDuringRead(), conn_factory=seeds["conn_factory"]
            )
            resolver = await asyncio.to_thread(factory, envelope)
            with pytest.raises(DesignMemoryRuntimeError, match="privacy_tombstoned") as error:
                await asyncio.to_thread(resolver)
            assert BODY not in str(error.value)
            assert calls == ["body resolved"]

    run_async(scenario())


@pytest.mark.parametrize(
    "field", ["workspace", "run", "turn", "execution", "project", "brand", "pin"]
)
def test_supplied_envelope_cannot_widen_stored_authority(
    tmp_path: Path,
    migrated_db: bool,
    registry: Any,  # noqa: F811 -- shared fixtures
    field: str,
) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")
    from clue_api.design_memory_runtime import (
        DesignMemoryRuntimeError,
        build_design_preference_resolver_factory,
    )

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds, _, memory, envelope, _ = await _prepared(conn, tmp_path, registry)
            payload = envelope.model_dump(mode="json")
            if field in {"workspace", "run"}:
                payload[f"{field}_id"] = "foreign"
            elif field in {"turn", "execution"}:
                payload["config"]["design_memory"][f"{field}_id"] = str(uuid4())
            elif field in {"project", "brand"}:
                payload["config"]["design_memory"]["request"]["scope_stack"][f"{field}_id"] = (
                    "foreign"
                )
            else:
                payload["config"]["design_memory"]["selection"]["bundle_hash"] = "0" * 64
            forged = type(envelope).model_validate(payload)
            factory = build_design_preference_resolver_factory(
                memory=memory, conn_factory=seeds["conn_factory"]
            )
            with pytest.raises(DesignMemoryRuntimeError):
                await asyncio.to_thread(factory, forged)

    run_async(scenario())


@pytest.mark.parametrize("mutation", ["kit", "scope_pin", "execution", "tombstone", "cancel"])
def test_resolver_rechecks_authority_and_erasure_after_factory_creation(
    tmp_path: Path,
    migrated_db: bool,
    registry: Any,  # noqa: F811 -- shared fixtures
    mutation: str,
) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")
    from clue_api.design_memory_runtime import (
        DesignMemoryRuntimeError,
        build_design_preference_resolver_factory,
    )

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds, submitted, memory, envelope, _ = await _prepared(conn, tmp_path, registry)
            factory = build_design_preference_resolver_factory(
                memory=memory, conn_factory=seeds["conn_factory"]
            )
            resolver = await asyncio.to_thread(factory, envelope)
            assert resolver is not None
            if mutation == "kit":
                await conn.execute(
                    text("UPDATE design_brand_kit SET brand_id=NULL WHERE workspace_id=:ws"),
                    {"ws": seeds["workspace_id"]},
                )
            elif mutation == "scope_pin":
                # Immutable pin rows cannot be updated; deleting is disallowed too. An
                # authoritative envelope/request swap must still lose against the original pin.
                payload = envelope.model_dump(mode="json")
                payload["config"]["design_memory"]["request"]["scope_stack"]["project_id"] = (
                    "foreign"
                )
                await conn.execute(
                    text(
                        "UPDATE design_agent_run SET payload=CAST(:payload AS jsonb) "
                        "WHERE run_id=:run"
                    ),
                    {"payload": json.dumps(payload), "run": envelope.run_id},
                )
            elif mutation == "execution":
                await conn.execute(
                    text("UPDATE design_agent_run SET execution_id=:execution WHERE run_id=:id"),
                    {"execution": seeds["parent_execution_id"], "id": envelope.run_id},
                )
            elif mutation == "cancel":
                await conn.execute(
                    text("UPDATE design_agent_run SET cancel_requested_at=now() WHERE run_id=:id"),
                    {"id": envelope.run_id},
                )
            else:
                for status in ("privacy_tombstoned", "running"):
                    await conn.execute(
                        text(
                            "INSERT INTO agent_turn_event "
                            "(event_id, turn_id, workspace_id, status) "
                            "VALUES (:event, :turn, :ws, :status)"
                        ),
                        {
                            "event": uuid4(),
                            "turn": submitted.turn_id,
                            "ws": seeds["workspace_id"],
                            "status": status,
                        },
                    )
            with pytest.raises(DesignMemoryRuntimeError):
                await asyncio.to_thread(resolver)

    run_async(scenario())


def test_off_selection_validates_authority_but_returns_no_resolver(
    tmp_path: Path,
    migrated_db: bool,
    registry: Any,  # noqa: F811 -- shared fixtures
) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")
    from clue_api.design_memory_runtime import (
        DesignMemoryRuntimeError,
        build_design_preference_resolver_factory,
    )

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds, _, memory, envelope, _ = await _prepared(conn, tmp_path, registry, off=True)
            factory = build_design_preference_resolver_factory(
                memory=memory, conn_factory=seeds["conn_factory"]
            )
            assert await asyncio.to_thread(factory, envelope) is None
            forged = envelope.model_copy(update={"workspace_id": "foreign"})
            with pytest.raises(DesignMemoryRuntimeError):
                await asyncio.to_thread(factory, forged)
            with pytest.raises(DesignMemoryRuntimeError, match="platform_loop"):
                factory(envelope)

    run_async(scenario())


def test_a_document_pinned_turns_session_thread_is_its_own_authority(
    tmp_path: Path,
    migrated_db: bool,
    registry: Any,  # noqa: F811 -- shared fixtures
) -> None:
    """Session continuity (2026-09-18) vs the D5 run-as-thread rule this seam used to demand.

    A pinned leg turn's checkpoint thread is now ``design_session_id(workspace, document)``, so
    the read seam must authorize THAT naming — while still refusing any other thread, which is
    what the rule was protecting: the checkpoint namespace this turn's memory is scoped to.
    Both halves are exercised against the STORED row (payload and column moved together), so
    the only condition under test is the thread naming itself.
    """

    if not migrated_db:
        pytest.skip("database not reachable")
    from clue_api.design_memory_runtime import (
        DesignMemoryRuntimeError,
        build_design_preference_resolver_factory,
    )

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds, _, memory, envelope, _ = await _prepared(
                conn, tmp_path, registry, pin_document=True
            )
            assert envelope.document_id is not None
            assert envelope.checkpoint_thread_id == design_session_id(
                seeds["workspace_id"], str(envelope.document_id)
            )
            factory = build_design_preference_resolver_factory(
                memory=memory, conn_factory=seeds["conn_factory"]
            )
            resolver = await asyncio.to_thread(factory, envelope)
            assert resolver is not None
            assert isinstance(await asyncio.to_thread(resolver), MemoryBundle)

            # Some OTHER thread — here another document's session — is still refused, even
            # when the stored row agrees with it.
            foreign = design_session_id(seeds["workspace_id"], "doc_somebody_else")
            payload = envelope.model_dump(mode="json")
            payload["checkpoint_thread_id"] = foreign
            await conn.execute(
                text(
                    "UPDATE design_agent_run SET payload=CAST(:payload AS jsonb),"
                    " checkpoint_thread_id=:thread WHERE run_id=:id"
                ),
                {"payload": json.dumps(payload), "thread": foreign, "id": envelope.run_id},
            )
            with pytest.raises(DesignMemoryRuntimeError, match="turn_authority_mismatch"):
                await asyncio.to_thread(factory, type(envelope).model_validate(payload))

    run_async(scenario())
