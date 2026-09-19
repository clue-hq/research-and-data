"""Lane 3 slice 1, Task 3: the durable model-call receipt carries the gateway-measured cost.

Pins: the receipt→row round trip for a priced and an unpriced call; the replay compare treating
cost as part of the immutable receipt; a pre-migration-shaped receipt (no cost) still lands as
NULL/NULL rather than as zero.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.contracts import AgentRole
from clue_agents.turns import AgentModelCallReceipt, AgentModelCallStatus
from clue_api.agent_turn_wiring import DbAgentTurnJournal
from clue_core import ExecutionId
from tests._workspace import seed_project
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

NOW = datetime.now(UTC)


async def _seed_turn(conn: AsyncConnection) -> dict[str, Any]:
    ws = f"ws_cost_{uuid4().hex[:12]}"
    project = await seed_project(conn, ws, name="cost receipt")
    thread_id = f"thread-{ws}"
    await conn.execute(
        text("INSERT INTO agent_thread (id, workspace_id, project_id) VALUES (:id, :ws, :p)"),
        {"id": thread_id, "ws": ws, "p": project.project_id},
    )
    execution_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO execution (id, workspace_id, project_id, started_by, "
            " parameter_manifest_hash, pin_manifest_hash) "
            "VALUES (:id, :ws, :p, 'agent', :hash, :hash)"
        ),
        {"id": execution_id, "ws": ws, "p": project.project_id, "hash": "0" * 64},
    )
    sha = "d" * 64
    manifest_key = f"{ws}/{sha}"
    await conn.execute(
        text(
            "INSERT INTO artifact (storage_key, workspace_id, content_sha256, media_type, "
            " size_bytes) VALUES (:key, :ws, :sha, 'application/json', :size)"
        ),
        {"key": manifest_key, "ws": ws, "sha": sha, "size": len(json.dumps({"resources": []}))},
    )
    turn_id = uuid4()
    await conn.execute(
        text(
            "INSERT INTO agent_turn "
            "(id, execution_id, workspace_id, project_id, thread_id, actor_id, role, "
            " workspace_root_id, profile_name, profile_version, profile_sha256, "
            " resource_manifest_key, resource_manifest_artifact_sha256, "
            " resource_manifest_sha256, retention_class, requested_at) "
            "VALUES (:id, :execution, :ws, :p, :thread, 'actor-cost', 'head_of_abm', "
            " 'root-cost', 'head-of-abm', 'v1', :sha, :key, :sha, :sha, 'test', :requested)"
        ),
        {
            "id": turn_id,
            "execution": execution_id,
            "ws": ws,
            "p": project.project_id,
            "thread": thread_id,
            "sha": sha,
            "key": manifest_key,
            "requested": NOW,
        },
    )
    return {"ws": ws, "turn_id": turn_id, "execution_id": execution_id}


def _receipt(
    seeds: dict[str, Any],
    *,
    sequence: int,
    cost_usd: Decimal | None,
    cost_source: str | None,
    langfuse_trace_id: str | None = None,
    langfuse_observation_id: str | None = None,
) -> AgentModelCallReceipt:
    return AgentModelCallReceipt(
        model_call_id=uuid5(NAMESPACE_URL, f"cost:{seeds['ws']}:call:{sequence}"),
        turn_id=seeds["turn_id"],
        execution_id=ExecutionId(seeds["execution_id"]),
        workspace_id=seeds["ws"],
        sequence=sequence,
        requested_model="x-ai/grok-4.6",
        answering_model="x-ai/grok-4.6",
        status=AgentModelCallStatus.COMPLETED,
        input_tokens=100,
        output_tokens=10,
        cost_millicredits=0,
        cost_usd=cost_usd,
        cost_source=cost_source,  # type: ignore[arg-type]
        langfuse_trace_id=langfuse_trace_id,
        langfuse_observation_id=langfuse_observation_id,
        latency_ms=12.5,
        role=AgentRole.HEAD_OF_ABM,
        started_at=NOW,
        completed_at=NOW,
    )


async def _row(
    conn: AsyncConnection, seeds: dict[str, Any], sequence: int
) -> tuple[Any, Any, Any, Any]:
    got = await conn.execute(
        text(
            "SELECT cost_usd, cost_source, langfuse_trace_id, langfuse_observation_id "
            "FROM agent_model_call WHERE turn_id = :turn AND sequence = :sequence"
        ),
        {"turn": seeds["turn_id"], "sequence": sequence},
    )
    row = got.one()
    return row[0], row[1], row[2], row[3]


def test_priced_unpriced_and_legacy_receipts_round_trip() -> None:
    async def scenario() -> list[tuple[Any, Any, Any, Any]]:
        async with rollback_conn(seed_pack=False) as conn:
            seeds = await _seed_turn(conn)
            journal = DbAgentTurnJournal(conn_factory=conn_session_factory(conn))
            await journal.record_model_call(
                receipt=_receipt(
                    seeds, sequence=1, cost_usd=Decimal("0.012345"), cost_source="metered"
                )
            )
            await journal.record_model_call(
                receipt=_receipt(seeds, sequence=2, cost_usd=None, cost_source="unpriced")
            )
            await journal.record_model_call(
                receipt=_receipt(seeds, sequence=3, cost_usd=None, cost_source=None)
            )
            return [await _row(conn, seeds, s) for s in (1, 2, 3)]

    assert run_async(scenario()) == [
        (Decimal("0.012345"), "metered", None, None),
        (None, "unpriced", None, None),
        (None, None, None, None),
    ]


def test_replay_with_a_different_cost_is_refused() -> None:
    async def scenario() -> str:
        async with rollback_conn(seed_pack=False) as conn:
            seeds = await _seed_turn(conn)
            journal = DbAgentTurnJournal(conn_factory=conn_session_factory(conn))
            first = _receipt(seeds, sequence=1, cost_usd=Decimal("0.01"), cost_source="metered")
            await journal.record_model_call(receipt=first)
            await journal.record_model_call(receipt=first)  # identical replay: fine
            changed = _receipt(seeds, sequence=1, cost_usd=Decimal("0.02"), cost_source="metered")
            try:
                await journal.record_model_call(receipt=changed)
            except ValueError as error:
                return str(error)
            return "no error"

    assert "different immutable receipt" in run_async(scenario())


def test_langfuse_ids_round_trip_and_are_part_of_the_immutable_receipt() -> None:
    async def scenario() -> tuple[tuple[Any, ...], str]:
        async with rollback_conn(seed_pack=False) as conn:
            seeds = await _seed_turn(conn)
            journal = DbAgentTurnJournal(conn_factory=conn_session_factory(conn))
            receipt = _receipt(
                seeds,
                sequence=1,
                cost_usd=Decimal("0.01"),
                cost_source="metered",
                langfuse_trace_id="a" * 32,
                langfuse_observation_id="b" * 16,
            )
            await journal.record_model_call(receipt=receipt)
            await journal.record_model_call(receipt=receipt)  # identical replay: accepted
            drifted = receipt.model_copy(update={"langfuse_observation_id": "c" * 16})
            try:
                await journal.record_model_call(receipt=drifted)
            except ValueError as exc:
                refused = str(exc)
            else:
                refused = ""
            return await _row(conn, seeds, 1), refused

    row, refused = run_async(scenario())
    assert row[2:] == ("a" * 32, "b" * 16)
    assert "different immutable receipt" in refused
