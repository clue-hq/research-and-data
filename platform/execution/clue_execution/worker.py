"""Fleet work handler for durable recipe executions."""

from __future__ import annotations

from clue_core import ExecutionId
from clue_execution.executor import RecipeExecutor
from clue_fleet.enums import FleetTaskKind
from clue_fleet.lease import WorkId
from clue_fleet.queue import WorkQueue
from clue_fleet.work_worker import WorkContext, WorkResult, enqueue_work


class RecipeExecutionHandler:
    kind = FleetTaskKind.EXECUTE_GRAPH

    def __init__(self, executor: RecipeExecutor) -> None:
        self._executor = executor

    async def handle(self, context: WorkContext) -> WorkResult:
        result = await self._executor.execute(
            ExecutionId(context.work_id),
            worker_id=context.worker_id,
            lease_generation=context.lease_generation,
            stop_requested=context.stop_requested,
        )
        return WorkResult(
            outcome=result.status.value,
            references={
                "execution_id": str(result.execution_id),
                "completed_nodes": len(result.completed_node_keys),
            },
        )


async def enqueue_recipe_execution(
    queue: WorkQueue,
    execution_id: ExecutionId,
    *,
    priority: int = 0,
) -> bool:
    return await enqueue_work(
        queue,
        kind=FleetTaskKind.EXECUTE_GRAPH,
        work_id=WorkId(execution_id),
        priority=priority,
        payload={"execution_id": str(execution_id)},
    )


__all__ = ["RecipeExecutionHandler", "enqueue_recipe_execution"]
