"""Recipe fleet-worker recovery at non-human project-phase waits."""

from __future__ import annotations

import asyncio
from typing import Any, cast
from uuid import uuid4

from clue_core import ExecutionId
from clue_execution import (
    PROJECT_PHASE_EXTERNAL_WAIT_REASON,
    ExecutionRunResult,
    ExecutionStatus,
    RecipeExecutionHandler,
)
from clue_fleet import LeaseGeneration, WorkContext, WorkId
from tests.db.conftest import run_async


class _Executor:
    def __init__(self, execution_id: ExecutionId) -> None:
        self.execution_id = execution_id
        self.calls: list[tuple[str, object]] = []

    async def resume_if_paused_for(self, **kwargs: object) -> bool:
        self.calls.append(("resume", kwargs))
        return True

    async def execute(self, execution_id: ExecutionId, **kwargs: object) -> ExecutionRunResult:
        self.calls.append(("execute", {"execution_id": execution_id, **kwargs}))
        return ExecutionRunResult(
            execution_id=execution_id,
            status=ExecutionStatus.PAUSED,
            completed_node_keys=("reverse_profiling", "icp_confirmed"),
        )


def test_recipe_worker_resumes_only_the_named_external_phase_pause_before_drive() -> None:
    async def scenario() -> None:
        execution_id = ExecutionId(uuid4())
        executor = _Executor(execution_id)
        handler = RecipeExecutionHandler(cast(Any, executor))
        stop_requested = asyncio.Event()
        result = await handler.handle(
            WorkContext(
                task_id=uuid4(),
                work_id=WorkId(execution_id),
                worker_id="worker",
                lease_generation=LeaseGeneration(1),
                payload={"execution_id": str(execution_id)},
                stop_requested=stop_requested,
                lease_lost=asyncio.Event(),
            )
        )

        assert [call[0] for call in executor.calls] == ["resume", "execute"]
        assert executor.calls[0][1] == {
            "execution_id": execution_id,
            "actor": "system",
            "reason_code": PROJECT_PHASE_EXTERNAL_WAIT_REASON,
        }
        assert result.outcome == "paused"
        assert result.references == {
            "execution_id": str(execution_id),
            "completed_nodes": 2,
        }

    run_async(scenario())
