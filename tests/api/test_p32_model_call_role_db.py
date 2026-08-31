"""P3.2 checkpoint 2: per-role attribution in the durable model-call ledger.

PD-part3 delta 6 — ONE durable per-role usage authority. `agent_model_call` gains a
nullable `role` column: stamped from the governed model's per-call `clue_role` metadata
when present (the design trio runs three roles inside ONE turn), else the turn's
constitution role; historical rows stay NULL. These pin: the receipt→row round trip for
both shapes, the replay-compare treating role as part of the immutable receipt, the DB
CHECK bounding the vocabulary, and — via the seeded turn — a live `role='design'`
agent_turn row through the P3.1-widened CHECK.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.contracts import AgentRole
from clue_agents.turns import AgentModelCallReceipt, AgentModelCallStatus
from clue_api.agent_turn_wiring import DbAgentTurnJournal
from clue_core import ExecutionId
from clue_db import db_lifespan
from tests._workspace import seed_project
from tests.api.conftest import migrated_db  # noqa: F401 -- fixture re-export
from tests.design.conftest import run_async

NOW = datetime.now(UTC)


async def _seed_turn(conn: AsyncConnection, *, turn_role: str = "design") -> dict[str, Any]:
    ws = f"ws_test_p32_{uuid4().hex[:12]}"
    project = await seed_project(conn, ws, name="P32 ledger")
    thread_id = f"thr_p32_{uuid4().hex[:10]}"
    await conn.execute(
        text("INSERT INTO agent_thread (id, workspace_id, project_id) VALUES (:id, :ws, :p)"),
        {"id": thread_id, "ws": ws, "p": project.project_id},
    )
    execution_id = uuid5(NAMESPACE_URL, f"p32:{ws}:execution")
    await conn.execute(
        text(
            "INSERT INTO execution (id, workspace_id, project_id, started_by, "
            " parameter_manifest_hash, pin_manifest_hash) "
            "VALUES (:id, :ws, :p, 'agent', :hash, :hash)"
        ),
        {"id": execution_id, "ws": ws, "p": project.project_id, "hash": "0" * 64},
    )
    sha = "c" * 64
    manifest_key = f"{ws}/{sha}"
    await conn.execute(
        text(
            "INSERT INTO artifact (storage_key, workspace_id, content_sha256, media_type, "
            " size_bytes) VALUES (:key, :ws, :sha, 'application/json', :size)"
        ),
        {"key": manifest_key, "ws": ws, "sha": sha, "size": len(json.dumps({"resources": []}))},
    )
    turn_id = uuid5(NAMESPACE_URL, f"p32:{ws}:turn")
    await conn.execute(
        text(
            "INSERT INTO agent_turn "
            "(id, execution_id, workspace_id, project_id, thread_id, actor_id, role, "
            " workspace_root_id, profile_name, profile_version, profile_sha256, "
            " resource_manifest_key, resource_manifest_artifact_sha256, "
            " resource_manifest_sha256, retention_class, requested_at) "
            "VALUES (:id, :execution, :ws, :p, :thread, 'actor-p32', :role, "
            " 'root-p32', 'design', 'v1', :sha, :key, :sha, :sha, 'test', :requested)"
        ),
        {
            "id": turn_id,
            "execution": execution_id,
            "ws": ws,
            "p": project.project_id,
            "thread": thread_id,
            "role": turn_role,
            "sha": sha,
            "key": manifest_key,
            "requested": NOW,
        },
    )
    return {"ws": ws, "turn_id": turn_id, "execution_id": execution_id}


def _receipt(seeds: dict[str, Any], *, role: AgentRole | None, sequence: int = 1) -> Any:
    return AgentModelCallReceipt(
        model_call_id=uuid5(NAMESPACE_URL, f"p32:{seeds['ws']}:call:{sequence}"),
        turn_id=seeds["turn_id"],
        execution_id=ExecutionId(seeds["execution_id"]),
        workspace_id=seeds["ws"],
        sequence=sequence,
        requested_model="openai/gpt-5.6-terra",
        answering_model="openai/gpt-5.6-terra",
        status=AgentModelCallStatus.COMPLETED,
        input_tokens=100,
        cache_read_input_tokens=90,
        output_tokens=10,
        cost_millicredits=0,
        latency_ms=12.5,
        role=role,
        started_at=NOW,
        completed_at=NOW,
    )


def _conn_factory(conn: AsyncConnection):
    class _Held:
        async def __aenter__(self) -> AsyncConnection:
            return conn

        async def __aexit__(self, *exc: object) -> None:
            return None

    return _Held


def test_role_persists_and_replay_treats_it_as_immutable(migrated_db: bool) -> None:  # noqa: F811
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin() as txn:
            seeds = await _seed_turn(conn)
            journal = DbAgentTurnJournal(conn_factory=_conn_factory(conn))

            labelled = _receipt(seeds, role=AgentRole.DESIGN, sequence=1)
            await journal.record_model_call(receipt=labelled)
            stored = (
                await conn.execute(
                    text("SELECT role FROM agent_model_call WHERE id = :id"),
                    {"id": labelled.model_call_id},
                )
            ).scalar_one()
            assert stored == "design"

            unlabelled = _receipt(seeds, role=None, sequence=2)
            await journal.record_model_call(receipt=unlabelled)
            stored_null = (
                await conn.execute(
                    text("SELECT role FROM agent_model_call WHERE id = :id"),
                    {"id": unlabelled.model_call_id},
                )
            ).scalar_one()
            assert stored_null is None

            # Replay with the SAME receipt is idempotent…
            await journal.record_model_call(receipt=labelled)
            # …but a different role under the same id is a different immutable receipt.
            mutated = labelled.model_copy(update={"role": AgentRole.HEAD_OF_ABM})
            with pytest.raises(ValueError, match="different immutable receipt"):
                await journal.record_model_call(receipt=mutated)
            await txn.rollback()

    run_async(scenario())


def test_role_vocabulary_is_check_bounded(migrated_db: bool) -> None:  # noqa: F811
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn, conn.begin():
            seeds = await _seed_turn(conn)
            with pytest.raises(IntegrityError):
                await conn.execute(
                    text(
                        "INSERT INTO agent_model_call "
                        "(id, turn_id, execution_id, workspace_id, sequence, requested_model, "
                        " answering_model, status, role, started_at, completed_at) "
                        "VALUES (:id, :turn, :execution, :ws, 9, 'm', 'm', 'completed', "
                        " 'not_a_role', :now, :now)"
                    ),
                    {
                        "id": uuid4(),
                        "turn": seeds["turn_id"],
                        "execution": seeds["execution_id"],
                        "ws": seeds["ws"],
                        "now": NOW,
                    },
                )

    run_async(scenario())


def test_resolve_model_call_role_prefers_per_call_label() -> None:
    from clue_api.agent_runtime_wiring import resolve_model_call_role

    head = AgentRole.HEAD_OF_ABM
    # The design trio's case: a role-labelled governed instance answered inside the turn.
    assert (
        resolve_model_call_role({"clue_role": "design"}, constitution_role=head) is AgentRole.DESIGN
    )
    # Unlabelled platform models: the turn's constitution role is the truth.
    assert resolve_model_call_role({}, constitution_role=head) is head
    # An unknown label must never fail the recording path.
    assert resolve_model_call_role({"clue_role": "martian"}, constitution_role=head) is head
