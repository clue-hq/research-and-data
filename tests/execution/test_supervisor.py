"""C5.5 deterministic supervisor policy and bounded-triage contracts."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError
from sqlalchemy import text

from clue_api import ExecutionRunEventWriter
from clue_config import SupervisorPolicy
from clue_core import (
    Completion,
    ExecutionId,
    ProjectRunId,
    new_execution_id,
    new_project_run_id,
)
from clue_execution import (
    ControlKind,
    DbExecutionJournal,
    RunAggregateSnapshot,
    SupervisorEngine,
    TriageResponse,
    deterministic_triggers,
)
from clue_research.durable import ensure_project_run
from tests._workspace import seed_project
from tests.db.conftest import run_async
from tests.execution.test_executor import _factory
from tests.profiling.conftest import rollback_conn


def _snapshot(
    *,
    counts: dict[str, int] | None = None,
    rates: dict[str, float] | None = None,
    source_counts: dict[str, dict[str, int]] | None = None,
    source_rates: dict[str, dict[str, float]] | None = None,
) -> RunAggregateSnapshot:
    return RunAggregateSnapshot(
        execution_id=new_execution_id(),
        project_run_id=new_project_run_id(),
        policy_version="supervisor-test-v1",
        counts=counts or {"canary_accounts_terminal": 3},
        rates=rates or {},
        source_counts=source_counts or {},
        source_rates=source_rates or {},
    )


def test_low_sample_source_health_does_not_trip_a_breaker() -> None:
    policy = SupervisorPolicy(minimum_source_samples=3)
    triggers = deterministic_triggers(
        _snapshot(
            source_counts={"bad": {"attempts": 2, "failures": 2, "empty": 0}},
            source_rates={"bad": {"error_rate": 1.0, "empty_rate": 0.0}},
        ),
        policy,
    )
    assert all(not trigger.startswith("source_") for trigger in triggers)


def test_deterministic_source_and_verification_floors_trip_without_model_judgment() -> None:
    policy = SupervisorPolicy(
        minimum_source_samples=3,
        minimum_verification_samples=3,
        source_error_rate_max=0.25,
        faithfulness_pass_floor=0.7,
    )
    triggers = deterministic_triggers(
        _snapshot(
            counts={"canary_accounts_terminal": 3, "faithfulness_total": 4},
            rates={"faithfulness_pass_share": 0.5},
            source_counts={"provider-a": {"attempts": 4, "failures": 2}},
            source_rates={"provider-a": {"error_rate": 0.5}},
        ),
        policy,
    )
    assert "faithfulness_below_floor" in triggers
    assert "source_error_rate:provider-a" in triggers


def test_no_canary_sample_is_fail_closed() -> None:
    triggers = deterministic_triggers(
        _snapshot(counts={"canary_accounts_terminal": 0}),
        SupervisorPolicy(minimum_canary_accounts=1),
    )
    assert triggers == ("insufficient_signal",)


def test_triage_output_is_closed_and_cannot_invent_control_kinds() -> None:
    with pytest.raises(ValidationError):
        TriageResponse.model_validate_json(
            json.dumps(
                {
                    "diagnosis_codes": ["source_fault"],
                    "affected_refs": ["provider-a"],
                    "confidence": 0.9,
                    "action_candidates": [
                        {
                            "control_kind": "delete_source",
                            "subject_ref": "provider-a",
                            "reason_code": "bad",
                        }
                    ],
                }
            )
        )
    parsed = TriageResponse.model_validate_json(
        json.dumps(
            {
                "diagnosis_codes": ["source_fault"],
                "affected_refs": ["provider-a"],
                "confidence": 0.9,
                "action_candidates": [
                    {
                        "control_kind": ControlKind.SOURCE_BREAKER.value,
                        "subject_ref": "provider-a",
                        "reason_code": "error_rate",
                    }
                ],
            }
        )
    )
    assert parsed.action_candidates[0].control_kind is ControlKind.SOURCE_BREAKER


def test_supervisor_policy_rejects_an_impossible_canary_floor() -> None:
    with pytest.raises(ValidationError, match="minimum_canary_accounts"):
        SupervisorPolicy(canary_size=2, minimum_canary_accounts=3)


class _AggregateReader:
    def __init__(self, snapshot: RunAggregateSnapshot) -> None:
        self._snapshot = snapshot

    async def snapshot(self, request: object) -> RunAggregateSnapshot:
        del request
        return self._snapshot


class _Gateway:
    def __init__(self, text: str, *, model: str = "answering-model") -> None:
        self.text = text
        self.model = model
        self.calls = 0

    def complete(self, **kwargs: object) -> Completion:
        del kwargs
        self.calls += 1
        return Completion(model=self.model, text=self.text)


async def _seed_supervised_execution(conn: object) -> tuple[str, ExecutionId, ProjectRunId]:
    project = await seed_project(conn, "ws-c5-supervisor", name="C5.5 supervisor")
    project_run_id = new_project_run_id()
    await ensure_project_run(
        conn,
        project_run_id=project_run_id,
        project_id=project.project_id,
        workspace_id=project.workspace_id,
        icp_key="icp-supervisor",
        icp_version=1,
    )
    execution_id = new_execution_id()
    await conn.execute(
        text(
            """
            INSERT INTO execution (
                id, workspace_id, project_id, project_run_id, started_by,
                parameter_manifest_hash, pin_manifest_hash
            ) VALUES (
                :id, :workspace_id, :project_id, :project_run_id, 'system', :hash, :hash
            )
            """
        ),
        {
            "id": execution_id,
            "workspace_id": project.workspace_id,
            "project_id": project.project_id,
            "project_run_id": project_run_id,
            "hash": "0" * 64,
        },
    )
    await conn.execute(
        text("INSERT INTO execution_cursor (execution_id, status) VALUES (:id, 'running')"),
        {"id": execution_id},
    )
    await conn.execute(
        text(
            """
            INSERT INTO project_run_execution_owner (
                project_run_id, execution_id, workspace_id, project_id, routing_mode
            )
            VALUES (
                :project_run_id, :execution_id, :workspace_id, :project_id, 'recipe'
            )
            """
        ),
        {
            "project_run_id": project_run_id,
            "execution_id": execution_id,
            "workspace_id": project.workspace_id,
            "project_id": project.project_id,
        },
    )
    return project.workspace_id, execution_id, project_run_id


def test_invalid_triage_is_journaled_once_and_never_gains_control_authority(
    require_profiling_db: None,
) -> None:
    del require_profiling_db

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            workspace_id, execution_id, project_run_id = await _seed_supervised_execution(conn)
            snapshot = RunAggregateSnapshot(
                execution_id=execution_id,
                project_run_id=project_run_id,
                policy_version="supervisor-v-test",
                counts={"canary_accounts_terminal": 3},
                source_counts={"provider-a": {"attempts": 3, "failures": 3}},
                source_rates={"provider-a": {"error_rate": 1.0}},
                affected_refs=("provider-a",),
            )
            gateway = _Gateway("not-json", model="fallback-answering-model")
            engine = SupervisorEngine(
                aggregates=_AggregateReader(snapshot),
                policy=SupervisorPolicy(
                    version="supervisor-v-test",
                    minimum_source_samples=3,
                    triage_model="requested-model",
                ),
                conn_factory=_factory(conn),
                journal=DbExecutionJournal(transport=ExecutionRunEventWriter()),
                gateway=gateway,
            )
            observation = await engine.observe(
                workspace_id=workspace_id,
                execution_id=execution_id,
                project_run_id=project_run_id,
            )
            first = await engine.diagnose(observation)
            replay = await engine.diagnose(observation)
            assert first is not None
            assert replay is not None and replay.id == first.id
            assert gateway.calls == 1
            assert first.diagnosis_codes == ("invalid_triage_output",)
            assert first.action_candidates == ()
            assert first.requested_model == "requested-model"
            assert first.answering_model == "fallback-answering-model"
            counts = (
                await conn.execute(
                    text(
                        """
                        SELECT
                            (SELECT count(*) FROM supervisor_observation
                             WHERE execution_id = :id) AS observations,
                            (SELECT count(*) FROM supervisor_diagnosis d
                             JOIN supervisor_observation o ON o.id = d.observation_id
                             WHERE o.execution_id = :id) AS diagnoses,
                            (SELECT count(*) FROM run_control_event
                             WHERE execution_id = :id) AS controls
                        """
                    ),
                    {"id": execution_id},
                )
            ).one()
            assert tuple(counts) == (1, 1, 0)

    run_async(scenario())
