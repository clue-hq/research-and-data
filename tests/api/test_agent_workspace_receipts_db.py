"""F3 Phase 2, plan Task 4: a saved file's receipt, read from the rows the turn already wrote.

Spec ``docs/superpowers/specs/agent-workspace/2026-10-21-agent-workspace-durability-design.md``
(rulings AW-22, AW-24). A raw input's bytes expire; the receipt is what the agent is left with, so
it has to name what the file held and how to get the same thing again. Everything here is read
from durable rows — ``execution_node`` for the call, ``agent_tool_result`` and its result artifact
for how much came back — and every lookup degrades to the unknown receipt rather than failing a
save.

Rollback-only, per the ``tests/api`` convention.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.execution import operation_id_for_plan_node
from clue_agents.workspace_snapshot import UNKNOWN_RECEIPT
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.agent_workspace_receipts import READ_AGAIN, DbReceiptSource
from clue_core import ExecutionId, operation_id_from_key
from clue_execution import execution_node_id
from clue_storage import FsStorage
from tests._workspace import seed_project
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory, rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

NOW = datetime(2026, 10, 22, 9, 30, tzinfo=UTC)
THREAD = "thr-receipts"


class _NoDatabase:
    """A connection factory for the paths that must answer from their shape alone.

    It counts every call, and the tests assert the count is zero. Raising alone proved nothing
    (review area 2, M5): ``receipt_for`` turns any exception into :data:`UNKNOWN_RECEIPT`, which is
    exactly what some of these paths are expected to answer, so a path that wrongly went to the
    database still came out "unknown" and passed.
    """

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> Any:
        self.calls += 1
        raise AssertionError("this path must answer from its shape, with no database round trip")


async def _artifact(conn: AsyncConnection, ws: str, sha: str) -> str:
    """A bare ``artifact`` row, for the keys a plan's foreign keys insist on."""

    key = f"{ws}/{sha}"
    await conn.execute(
        text(
            "INSERT INTO artifact (storage_key, workspace_id, content_sha256, media_type, "
            " size_bytes) VALUES (:key, :ws, :sha, 'application/json', 2) "
            "ON CONFLICT (storage_key) DO NOTHING"
        ),
        {"key": key, "ws": ws, "sha": sha},
    )
    return key


async def _seed_tool_call(
    conn: AsyncConnection,
    storage: FsStorage,
    *,
    tool_name: str = "run_crm_action",
    display_params: dict[str, Any] | None = None,
    references: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """One governed tool call, with the rows and the ids production writes for it.

    A governed call has **two** operation ids, and the receipt must answer for a file named by
    either. The plan operation (``agent_plan_operation``, which ``agent_tool_result`` is keyed on)
    is ``operation_id_for_plan_node(execution, node_key)``; the executor's node
    (``execution_node``) is ``operation_id_from_key(execution, node_key)``. A spilled governed
    result is named after the first (``_receipt_reference_values``); anything a tool writes
    itself through its ``ToolContext`` — a CRM read, a sandbox stream — after the second.

    Both ids are derived here with the functions production uses, never chosen: an earlier copy
    of this seed gave both tables one ``uuid4()``, and every receipt test passed while every
    spilled governed result in production read "No record of what made this file" (2026-10-24).
    The plan rows are written whether or not the call has a result yet, as the plan is validated
    and journalled before the tool runs; ``references`` adds the result row.
    """

    ws = f"ws_receipt_{uuid4().hex[:12]}"
    project = await seed_project(conn, ws, name="receipts")
    await conn.execute(
        text("INSERT INTO agent_thread (id, workspace_id, project_id) VALUES (:id, :ws, :p)"),
        {"id": THREAD, "ws": ws, "p": project.project_id},
    )
    execution_id = ExecutionId(uuid4())
    node_key = f"agent_{tool_name}_{uuid4().hex[:24]}"
    node_operation = operation_id_from_key(str(execution_id), node_key)
    plan_operation = operation_id_for_plan_node(execution_id, node_key)
    assert node_operation != plan_operation
    await conn.execute(
        text(
            "INSERT INTO execution (id, workspace_id, project_id, started_by, "
            " parameter_manifest_hash, pin_manifest_hash) "
            "VALUES (:id, :ws, :p, 'agent', :hash, :hash)"
        ),
        {"id": execution_id, "ws": ws, "p": project.project_id, "hash": "0" * 64},
    )
    await conn.execute(
        text(
            "INSERT INTO execution_node (id, execution_id, node_key, kind, tool_name, "
            " tool_version, operation_id, input_schema_sha256, output_schema_sha256, "
            " display_params_json, created_at) "
            "VALUES (:id, :execution, :node, 'tool', :tool, '1', :operation, :sha, :sha, "
            " CAST(:display AS jsonb), :at)"
        ),
        {
            "id": execution_node_id(execution_id, node_key),
            "execution": execution_id,
            "node": node_key,
            "tool": tool_name,
            "operation": node_operation,
            "sha": "f" * 64,
            "display": json.dumps(display_params or {}),
            "at": NOW,
        },
    )
    seeds: dict[str, Any] = {
        "ws": ws,
        "plan_operation_id": plan_operation,
        "node_operation_id": node_operation,
        # A governed result spill (``_receipt_reference_values``) and a tool's own spill
        # (``run_crm_action``'s ``write_spill(str(ctx.operation_id), …)``) respectively.
        "plan_path": f"reads/{plan_operation}.json",
        "node_path": f"reads/{node_operation}.json",
    }

    manifest_key = await _artifact(conn, ws, "d" * 64)
    turn_id, plan_id = uuid4(), uuid4()
    await conn.execute(
        text(
            "INSERT INTO agent_turn "
            "(id, execution_id, workspace_id, project_id, thread_id, actor_id, role, "
            " workspace_root_id, profile_name, profile_version, profile_sha256, "
            " resource_manifest_key, resource_manifest_artifact_sha256, "
            " resource_manifest_sha256, retention_class, requested_at) "
            "VALUES (:id, :execution, :ws, :p, :thread, 'actor-receipt', 'head_of_abm', "
            " 'root-receipt', 'head-of-abm', 'v1', :sha, :key, :sha, :sha, 'test', :at)"
        ),
        {
            "id": turn_id,
            "execution": execution_id,
            "ws": ws,
            "p": project.project_id,
            "thread": THREAD,
            "sha": "d" * 64,
            "key": manifest_key,
            "at": NOW,
        },
    )
    proposal_key = await _artifact(conn, ws, "a" * 64)
    validated_key = await _artifact(conn, ws, "b" * 64)
    parameter_key = await _artifact(conn, ws, "c" * 64)
    await conn.execute(
        text(
            "INSERT INTO agent_plan "
            "(id, turn_id, execution_id, workspace_id, role, proposal_artifact_key, "
            " proposal_sha256, validated_artifact_key, validated_sha256, "
            " resource_manifest_sha256, max_parallelism, estimated_cost_millicents, "
            " budget_limit_millicents, validated_at) "
            "VALUES (:id, :turn, :execution, :ws, 'head_of_abm', :proposal, :proposal_sha, "
            " :validated, :validated_sha, :manifest_sha, 1, 0, 100, :at)"
        ),
        {
            "id": plan_id,
            "turn": turn_id,
            "execution": execution_id,
            "ws": ws,
            "proposal": proposal_key,
            "proposal_sha": "a" * 64,
            "validated": validated_key,
            "validated_sha": "b" * 64,
            "manifest_sha": "d" * 64,
            "at": NOW,
        },
    )
    await conn.execute(
        text(
            "INSERT INTO agent_plan_operation "
            "(plan_id, workspace_id, ordinal, node_key, operation_id, kind, address, "
            " parameter_artifact_key, parameter_sha256, estimated_cost_millicents, "
            " authority_sha256) "
            "VALUES (:plan, :ws, 0, :node, :operation, 'tool', :address, :key, :sha, 0, :auth)"
        ),
        {
            "plan": plan_id,
            "ws": ws,
            "node": node_key,
            "operation": plan_operation,
            "address": f"{tool_name}@1",
            "key": parameter_key,
            "sha": "c" * 64,
            "auth": "e" * 64,
        },
    )
    if references is None:
        return seeds

    artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=conn_session_factory(conn))
    result_ref = await artifacts.persist_body(
        workspace_id=ws,
        data=json.dumps(
            {"tool": tool_name, "version": "1", "references": references},
            sort_keys=True,
            separators=(",", ":"),
        ).encode(),
        media_type="application/vnd.clue.agent-tool-result+json",
    )
    await conn.execute(
        text(
            "INSERT INTO agent_tool_result (operation_id, plan_id, node_key, workspace_id, "
            " tool_address, result_artifact_key, result_sha256, replayed, reference_count) "
            "VALUES (:operation, :plan, :node, :ws, :address, :key, :sha, false, :count)"
        ),
        {
            "operation": plan_operation,
            "plan": plan_id,
            "node": node_key,
            "ws": ws,
            "address": f"{tool_name}@1",
            "key": result_ref.artifact_key,
            "sha": result_ref.sha256,
            "count": len(references),
        },
    )
    seeds["result_key"] = result_ref.artifact_key
    return seeds


def _source(conn: AsyncConnection, storage: FsStorage) -> DbReceiptSource:
    factory = conn_session_factory(conn)
    return DbReceiptSource(
        conn_factory=factory,
        artifacts=DurableAgentArtifactStore(storage=storage, conn_factory=factory),
    )


def test_a_crm_read_receipt_names_the_action_and_its_count(tmp_path: Path) -> None:
    """``run_crm_action`` names its spill after its ``ToolContext`` — the executor node's id.

    Its count and its CRM live on the result row, which is keyed on the *plan* operation's id, so
    the receipt has to cross from one id to the other to say "12 records from hubspot". Joining
    the result on the node's id found nothing, and the sentence fell back to the generic one.

    The node's ``display_params_json`` is ``{}``, as a governed call in a live turn writes it (the
    live check of 2026-10-25): only a direct toolbelt call journals display parameters, so the
    action's slug has to come off the result row. Seeding the slug as a display parameter made
    this test pass while every live CRM read got the generic sentence.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path / "store")
            seeds = await _seed_tool_call(
                conn,
                storage,
                references={
                    "provider": "hubspot",
                    "slug": "HUBSPOT_SEARCH_DEALS",
                    "path": "reads/x.json",
                    "record_count": 12,
                    "total": 12,
                    "done": True,
                },
            )
            receipt = await _source(conn, storage).receipt_for(
                workspace_id=seeds["ws"], thread_id=THREAD, path=seeds["node_path"]
            )
        assert receipt.source == "run_crm_action"
        assert receipt.operation_id == str(seeds["node_operation_id"])
        assert receipt.produced_at == NOW
        assert receipt.details["slug"] == "HUBSPOT_SEARCH_DEALS"
        assert receipt.details["record_count"] == 12
        assert receipt.details["total"] == 12
        assert receipt.details["done"] is True
        # The founder-approved sentence (Task 8, text (d)), written out rather than read from
        # READ_AGAIN, so a change to the constant fails here too. Asserting only that it named
        # run_crm_action passed with the generic spill sentence (review area 2, M6).
        assert receipt.read_again == (
            "Run run_crm_action again with the same action and arguments: "
            "HUBSPOT_SEARCH_DEALS on hubspot."
        )

    run_async(scenario())


@pytest.mark.parametrize("named_by", ["plan_path", "node_path"])
def test_a_tool_read_with_no_result_row_still_names_the_call(tmp_path: Path, named_by: str) -> None:
    """Degrade, never fail: the tool name and the time are useful on their own."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path / "store")
            seeds = await _seed_tool_call(
                conn, storage, display_params={"slug": "HUBSPOT_SEARCH_DEALS"}
            )
            receipt = await _source(conn, storage).receipt_for(
                workspace_id=seeds["ws"], thread_id=THREAD, path=seeds[named_by]
            )
        assert receipt.source == "run_crm_action"
        assert receipt.produced_at == NOW
        assert receipt.details == {"slug": "HUBSPOT_SEARCH_DEALS"}

    run_async(scenario())


def test_a_non_crm_spill_is_told_to_run_its_own_tool_again(tmp_path: Path) -> None:
    """Any other governed read names the tool the execution row recorded, not the CRM sentence.

    The file is named as ``_receipt_reference_values`` names it — after the *plan* operation —
    and the receipt keeps the call's displayed parameters and the counts its result reported.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path / "store")
            seeds = await _seed_tool_call(
                conn,
                storage,
                tool_name="search_accounts",
                display_params={"query": "robotics"},
                references={"accounts": ["a"] * 3, "total": 40, "done": False},
            )
            receipt = await _source(conn, storage).receipt_for(
                workspace_id=seeds["ws"], thread_id=THREAD, path=seeds["plan_path"]
            )
        assert receipt.source == "search_accounts"
        assert receipt.operation_id == str(seeds["plan_operation_id"])
        assert receipt.produced_at == NOW
        assert receipt.details == {"query": "robotics", "total": 40, "done": False}
        assert receipt.read_again == "Run search_accounts again with the same arguments."

    run_async(scenario())


def test_a_spilled_run_python_result_is_told_to_run_run_python_again(tmp_path: Path) -> None:
    """The live failure of 2026-10-24, rebuilt with the ids production gave it.

    One ``run_python@1`` call's result was too big for its receipt and was spilled to
    ``reads/<plan operation id>.json``; its ``execution_node`` row carries the node's id (the one
    its ``reads/<id>.stdout.txt`` stream is named by). The lookup keyed only on the node's id, so
    the expired file read "No record of what made this file" instead of the approved sentence.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path / "store")
            seeds = await _seed_tool_call(
                conn,
                storage,
                tool_name="run_python",
                references={"exit_code": 0, "stdout": "x" * 64, "files_written": []},
            )
            receipt = await _source(conn, storage).receipt_for(
                workspace_id=seeds["ws"], thread_id=THREAD, path=seeds["plan_path"]
            )
        assert receipt != UNKNOWN_RECEIPT
        assert receipt.source == "run_python"
        assert receipt.operation_id == str(seeds["plan_operation_id"])
        assert receipt.produced_at == NOW
        assert receipt.read_again == "Run run_python again with the same arguments."

    run_async(scenario())


def test_a_file_with_no_row_gets_an_unknown_receipt(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path / "store")
            receipt = await _source(conn, storage).receipt_for(
                workspace_id="ws-nobody", thread_id=THREAD, path=f"reads/{uuid4()}.json"
            )
        assert receipt == UNKNOWN_RECEIPT

    run_async(scenario())


@pytest.mark.parametrize("named_by", ["plan_path", "node_path"])
def test_another_tenants_operation_id_is_never_read(tmp_path: Path, named_by: str) -> None:
    """Review I4: the file name is the agent's, so the lookup is scoped to its own workspace.

    ``execution_node`` carries no ``workspace_id`` of its own — it is scoped through
    ``execution`` — so without that join an agent writing ``reads/<any-uuid>.json`` has another
    tenant's tool name and displayed parameters copied into its durable file list and into the
    card it is handed at the start of its next turn. Fail closed, as every account and thread
    read in this codebase does (B3, 2026-07-23).
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path / "store")
            theirs = await _seed_tool_call(
                conn,
                storage,
                display_params={"slug": "HUBSPOT_SEARCH_DEALS"},
                references={"provider": "hubspot", "record_count": 12},
            )
            mine = f"ws_receipt_{uuid4().hex[:12]}"
            await seed_project(conn, mine, name="the other tenant")
            # My chat, their operation id: the only thing that may come back is "unknown".
            receipt = await _source(conn, storage).receipt_for(
                workspace_id=mine, thread_id=THREAD, path=theirs[named_by]
            )
        assert receipt == UNKNOWN_RECEIPT

    run_async(scenario())


def test_a_lookup_that_raises_falls_back_to_the_unknown_receipt(tmp_path: Path) -> None:
    """A receipt is a convenience, never the file: a broken lookup may not fail the save."""

    class Broken:
        async def __aenter__(self) -> None:
            raise RuntimeError("the database is unreachable")

        async def __aexit__(self, *_: object) -> bool:
            return False

    async def scenario() -> None:
        source = DbReceiptSource(
            conn_factory=Broken,  # type: ignore[arg-type]
            artifacts=DurableAgentArtifactStore(storage=FsStorage(tmp_path / "store")),
        )
        receipt = await source.receipt_for(
            workspace_id="ws-x", thread_id=THREAD, path=f"reads/{uuid4()}.json"
        )
        assert receipt == UNKNOWN_RECEIPT

    run_async(scenario())


def test_an_unreadable_result_artifact_keeps_the_call_it_can_still_name(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path / "store")
            seeds = await _seed_tool_call(
                conn,
                storage,
                display_params={"slug": "HUBSPOT_SEARCH_DEALS"},
                references={"record_count": 7},
            )
            # The bytes are gone from storage; the rows that name the call are not.
            await storage.delete(str(seeds["result_key"]))
            receipt = await _source(conn, storage).receipt_for(
                workspace_id=seeds["ws"], thread_id=THREAD, path=seeds["node_path"]
            )
        assert receipt.source == "run_crm_action"
        assert receipt.details == {"slug": "HUBSPOT_SEARCH_DEALS"}

    run_async(scenario())


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_a_sandbox_spill_is_a_run_python_receipt(tmp_path: Path, stream: str) -> None:
    async def scenario() -> None:
        operation = uuid4()
        no_database = _NoDatabase()
        source = DbReceiptSource(
            conn_factory=no_database,
            artifacts=DurableAgentArtifactStore(storage=FsStorage(tmp_path / "store")),
        )
        receipt = await source.receipt_for(
            workspace_id="ws-x", thread_id=THREAD, path=f"reads/{operation}.{stream}.txt"
        )
        assert no_database.calls == 0
        assert receipt.source == "run_python"
        assert receipt.operation_id == str(operation)
        assert receipt.details == {"stream": stream}
        assert receipt.read_again == READ_AGAIN["run_python"].format(stream=stream)

    run_async(scenario())


@pytest.mark.parametrize(
    ("path", "source", "details"),
    [
        (
            "work/conversation_history/2d6f.md",
            "conversation_history",
            {"execution_id": "2d6f"},
        ),
        ("work/conversation_history/media/0/img.png", "conversation_history", {}),
        ("work/large_tool_results/read_file_1.txt", "large_tool_results", {}),
        ("scratch/plan.md", "unknown", {}),
        ("outputs/report.md", "unknown", {}),
    ],
)
def test_the_other_paths_answer_from_their_shape(
    tmp_path: Path, path: str, source: str, details: dict[str, Any]
) -> None:
    async def scenario() -> None:
        no_database = _NoDatabase()
        receipts = DbReceiptSource(
            conn_factory=no_database,
            artifacts=DurableAgentArtifactStore(storage=FsStorage(tmp_path / "store")),
        )
        receipt = await receipts.receipt_for(workspace_id="ws-x", thread_id=THREAD, path=path)
        assert no_database.calls == 0
        assert (receipt.source, dict(receipt.details)) == (source, details)
        assert receipt.read_again == READ_AGAIN[source]

    run_async(scenario())


def test_the_uuid_rule_does_not_claim_an_ordinary_reads_file(tmp_path: Path) -> None:
    async def scenario() -> None:
        no_database = _NoDatabase()
        receipts = DbReceiptSource(
            conn_factory=no_database,
            artifacts=DurableAgentArtifactStore(storage=FsStorage(tmp_path / "store")),
        )
        receipt = await receipts.receipt_for(
            workspace_id="ws-x", thread_id=THREAD, path="reads/notes.json"
        )
        assert no_database.calls == 0
        assert receipt == UNKNOWN_RECEIPT

    run_async(scenario())
