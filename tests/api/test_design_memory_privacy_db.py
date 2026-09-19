"""Erase actual echoed design-memory copies, not only the original selection pin."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_api.agent_turn_scope_pin import load_or_create_agent_turn_scope_pin
from clue_api.agent_turn_wiring import (
    AgentPrivacyService,
    DbAgentReplayReader,
    is_agent_turn_privacy_tombstoned,
)
from clue_design import runs as design_runs
from clue_design.errors import DesignRunFencedError
from clue_execution.run_events import emit_design_run_event
from clue_memory import erase_subject
from tests.agents.workspace_helpers import make_workspace
from tests.api.test_client_knowledge_privacy_s4e_db import _checkpoint_tables
from tests.api.test_design_memory_producer_db import BODY, _kit, _Memory, _run
from tests.api.test_p34_design_leg_engine_db import (
    _seed_leg_conversation,
    _submit_message,
    registry,  # noqa: F401 -- shared profile fixture
)
from tests.db.conftest import run_async
from tests.memory.conftest import make_caps, seed_contact
from tests.profiling.conftest import migrated_db, rollback_conn  # noqa: F401 -- DB fixture


class _EchoingLane:
    """Only the model/runtime is a double; it reads and echoes the selected real DB body."""

    def __init__(self, conn: Any, root: Path) -> None:
        self.conn = conn
        self.root = root
        self.inner = f"run_{uuid4().hex}"
        self.outer = ""

    async def drive(self, *, envelope: Any) -> None:
        self.outer = envelope.run_id
        selected = envelope.config["design_memory"]["selection"]["selected_ids"]
        body = (
            await self.conn.execute(
                text("SELECT body FROM memory WHERE memory_id=:memory AND workspace_id=:ws"),
                {"memory": selected[0], "ws": envelope.workspace_id},
            )
        ).scalar_one()
        # These are the persisted echo surfaces of an actual runtime response. Absence of the
        # body from the input envelope alone would prove nothing about these outputs.
        for name in ("logs/run.jsonl", "workspace/plan.md", "final.json"):
            path = self.root / self.inner / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body)
        result = {
            "status": "proposed",
            "acceptance_scope": "design",
            "summary": body,
            "run_id": self.inner,
            "trace_dir": str(self.root / self.inner),
        }
        await design_runs.set_run_result(
            self.conn,
            workspace_id=envelope.workspace_id,
            run_id=envelope.run_id,
            status="succeeded",
            result=result,
        )
        await self.conn.execute(
            text(
                "UPDATE design_agent_run SET lease_generation=7, leased_by='test-worker', "
                "leased_at=now() WHERE run_id=:run"
            ),
            {"run": envelope.run_id},
        )
        await emit_design_run_event(
            self.conn,
            workspace_id=envelope.workspace_id,
            design_run_id=envelope.run_id,
            topic="design.run.completed",
            payload={"event_type": "run_completed", "result": result},
        )


async def _prepare(conn: Any, tmp_path: Path, profiles: Any) -> tuple[Any, ...]:
    seeds = await _seed_leg_conversation(conn, storage_root=tmp_path, label="memory-privacy")
    subject = await seed_contact(conn)
    await conn.execute(
        text(
            "INSERT INTO memory (memory_id, workspace_id, scope_type, type, trigger, body, "
            "provenance_class, trust_grade, status, subject_entity_id, retention_class) "
            "VALUES ('mem_selected', :ws, 'workspace', 'preference', 'For ads', :body, "
            "'user_stated', 3, 'active', :subject, 'person_adjacent')"
        ),
        {"ws": seeds["workspace_id"], "body": BODY, "subject": subject},
    )
    await _kit(conn, seeds)
    submission = await _submit_message(conn, seeds, label="memory-privacy", message="Create an ad.")
    pin, _ = await load_or_create_agent_turn_scope_pin(conn, submission=submission)
    lane = _EchoingLane(conn, tmp_path / "design-runtime")
    await _run(conn, seeds, profiles, lane, submission, _Memory(), pin)
    await _checkpoint_tables(conn)
    for namespace in ("", "design:child"):
        await conn.execute(
            text(
                "INSERT INTO checkpoints (thread_id, checkpoint_ns, checkpoint_id, checkpoint) "
                "VALUES (:run, :ns, '1', CAST(:body AS jsonb))"
            ),
            {"run": lane.outer, "ns": namespace, "body": json.dumps({"model_echo": BODY})},
        )
        await conn.execute(
            text(
                "INSERT INTO checkpoint_blobs "
                "(thread_id, checkpoint_ns, channel, version, type, blob) "
                "VALUES (:run, :ns, 'messages', '1', 'bytes', :body)"
            ),
            {"run": lane.outer, "ns": namespace, "body": BODY.encode()},
        )
        await conn.execute(
            text(
                "INSERT INTO checkpoint_writes (thread_id, checkpoint_ns, checkpoint_id, task_id, "
                "idx, channel, type, blob) "
                "VALUES (:run, :ns, '1', 'task', 0, 'messages', 'bytes', :body)"
            ),
            {"run": lane.outer, "ns": namespace, "body": BODY.encode()},
        )
    unrelated = f"run_{uuid4().hex}"
    await design_runs.create_run(
        conn,
        workspace_id=seeds["workspace_id"],
        run_id=unrelated,
        document_id=None,
        payload={"unrelated": "preserve"},
    )
    await conn.execute(
        text(
            "INSERT INTO checkpoints (thread_id, checkpoint_id, checkpoint) "
            "VALUES (:run, '1', CAST(:body AS jsonb))"
        ),
        {"run": unrelated, "body": '{"unrelated":true}'},
    )
    (lane.root / unrelated).mkdir()
    (lane.root / unrelated / "preserve.md").write_text("Shared runtime, unrelated run")
    assert any(
        BODY.encode() in p.read_bytes() for p in (tmp_path / "artifacts").rglob("*") if p.is_file()
    ), "The lane must actually echo memory into durable platform artifacts before erasure."
    await erase_subject(
        conn, workspace_id=seeds["workspace_id"], subject_entity_id=subject, caps=make_caps()
    )
    harness = make_workspace(
        tmp_path / "platform",
        workspace_id=seeds["workspace_id"],
        project_id=seeds["project"].project_id,
    )
    return seeds, subject, submission, lane, unrelated, harness


def test_design_dependency_erasure_refuses_to_succeed_without_runtime_purge(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
    registry: Any,  # noqa: F811
) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeds, subject, _, lane, _, harness = await _prepare(conn, tmp_path, registry)
            try:
                with pytest.raises(RuntimeError, match="design runtime privacy purge"):
                    await AgentPrivacyService(
                        storage=seeds["storage"],
                        workspaces=harness.factory,
                        conn_factory=seeds["conn_factory"],
                    ).erase_subject(workspace_id=seeds["workspace_id"], subject_entity_id=subject)
                assert BODY in (lane.root / lane.inner / "workspace/plan.md").read_text()
            finally:
                harness.close()

    run_async(scenario())


@pytest.mark.parametrize("partial_failure", [False, True])
def test_design_memory_echo_erasure_closes_checkpoints_files_and_retry(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
    registry: Any,  # noqa: F811
    partial_failure: bool,
) -> None:
    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            seeds, subject, submission, lane, unrelated, harness = await _prepare(
                conn, tmp_path, registry
            )
            first = True

            async def purge(*, workspace_id: str, runs: Any) -> None:
                nonlocal first
                assert workspace_id == seeds["workspace_id"]
                assert [r.run_id for r in runs] == [lane.outer]
                target = runs[0]
                # The locator must remain available after the DB phase and a partial FS failure.
                assert target.result_json["run_id"] == lane.inner
                assert target.events[0]["result"]["summary"] == BODY
                assert target.checkpoint_thread_id == lane.outer
                path = lane.root / target.result_json["run_id"]
                if partial_failure and first:
                    first = False
                    (path / "logs/run.jsonl").unlink()
                    raise OSError("injected partial filesystem failure")
                shutil.rmtree(path, ignore_errors=False)

            privacy = AgentPrivacyService(
                storage=seeds["storage"],
                workspaces=harness.factory,
                conn_factory=seeds["conn_factory"],
                design_run_purger=purge,
            )
            try:
                if partial_failure:
                    with pytest.raises(OSError, match="partial filesystem failure"):
                        await privacy.erase_subject(
                            workspace_id=seeds["workspace_id"], subject_entity_id=subject
                        )
                    assert (lane.root / lane.inner / "workspace/plan.md").exists()
                result = await privacy.erase_subject(
                    workspace_id=seeds["workspace_id"], subject_entity_id=subject
                )
                assert result.affected_turn_ids == (submission.turn_id,)
                assert not (lane.root / lane.inner).exists()
                assert (
                    lane.root / unrelated / "preserve.md"
                ).read_text() == "Shared runtime, unrelated run"
                for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
                    assert (
                        await conn.execute(
                            text(f"SELECT count(*) FROM {table} WHERE thread_id=:run"),
                            {"run": lane.outer},
                        )
                    ).scalar_one() == 0
                assert (
                    await conn.execute(
                        text("SELECT count(*) FROM checkpoints WHERE thread_id=:run"),
                        {"run": unrelated},
                    )
                ).scalar_one() == 1
                run = await design_runs.get_run(
                    conn, workspace_id=seeds["workspace_id"], run_id=lane.outer
                )
                assert run["status"] == "failed"
                assert BODY not in json.dumps(run)
                retained = (
                    (
                        await conn.execute(
                            text("SELECT payload::text FROM run_event WHERE subject_id=:run"),
                            {"run": lane.outer},
                        )
                    )
                    .scalars()
                    .all()
                )
                assert retained and all(BODY not in p for p in retained)
                with pytest.raises(DesignRunFencedError):
                    await design_runs.set_run_result(
                        conn,
                        workspace_id=seeds["workspace_id"],
                        run_id=lane.outer,
                        status="succeeded",
                        result={"summary": BODY},
                        expected_generation=7,
                    )
                blocked = await DbAgentReplayReader(
                    storage=seeds["storage"], conn_factory=seeds["conn_factory"]
                ).inspect(workspace_id=seeds["workspace_id"], turn_id=submission.turn_id)
                assert not blocked.replayable
                assert "turn_privacy_tombstoned" in blocked.blocker_codes
                # An in-flight platform writer may still append a later status. The permanent
                # tombstone, rather than the latest event, must govern every retry reader.
                await conn.execute(
                    text(
                        "INSERT INTO agent_turn_event "
                        "(event_id, workspace_id, turn_id, status, reason_code) "
                        "VALUES (:id, :ws, :turn, 'failed', 'late_worker')"
                    ),
                    {"id": uuid4(), "ws": seeds["workspace_id"], "turn": submission.turn_id},
                )
                assert await is_agent_turn_privacy_tombstoned(
                    conn, workspace_id=seeds["workspace_id"], turn_id=submission.turn_id
                )
                assert not await is_agent_turn_privacy_tombstoned(
                    conn, workspace_id="different-workspace", turn_id=submission.turn_id
                )
                # Completed erasure is idempotent: no callback needs vanished locator bodies.
                await privacy.erase_subject(
                    workspace_id=seeds["workspace_id"], subject_entity_id=subject
                )
                assert not any(
                    BODY.encode() in p.read_bytes()
                    for p in (tmp_path / "artifacts").rglob("*")
                    if p.is_file()
                )
            finally:
                harness.close()

    run_async(scenario())
