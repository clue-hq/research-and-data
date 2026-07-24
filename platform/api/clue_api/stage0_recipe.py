"""Recipe #0's narrow deterministic runner; C5 may replace it behind this shape."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from clue_core import operation_id_from_key
from clue_toolbelt import (
    IdempotencyStore,
    ToolContext,
    ToolRegistry,
    ToolResult,
    invoke_tool,
)


class RecipeStep(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    step_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    tool_version: str = Field(min_length=1)
    input_refs: dict[str, JsonValue]
    depends_on: tuple[str, ...] = ()


class RecipeRunner(Protocol):
    async def run_step(self, step: RecipeStep, *, ctx: ToolContext) -> ToolResult: ...


class ToolbeltRecipeRunner:
    """Run explicit tool steps without planning, judging sufficiency, or impersonating an agent."""

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        idempotency_store: IdempotencyStore,
        idempotency_ttl_s: float,
        recipe_id: str = "recipe0@1",
    ) -> None:
        self._registry = registry
        self._store = idempotency_store
        self._ttl = idempotency_ttl_s
        self._recipe_id = recipe_id

    async def run_step(self, step: RecipeStep, *, ctx: ToolContext) -> ToolResult:
        step_ctx = replace(
            ctx,
            operation_id=operation_id_from_key(
                ctx.workspace_id,
                f"{self._recipe_id}:{step.step_id}",
            ),
        )
        return await invoke_tool(
            self._registry,
            step.tool_name,
            dict(step.input_refs),
            step_ctx,
            version=step.tool_version,
            idempotency_key=f"{self._recipe_id}:{step.step_id}",
            store=self._store,
            idempotency_ttl_s=self._ttl,
        )

    async def run(
        self,
        steps: Sequence[RecipeStep],
        *,
        ctx: ToolContext,
    ) -> Mapping[str, ToolResult]:
        """Topologically execute explicit steps and refuse cycles/missing dependencies."""
        by_id = {step.step_id: step for step in steps}
        if len(by_id) != len(steps):
            raise ValueError("Recipe #0 step ids must be unique")
        missing = {
            dependency
            for step in steps
            for dependency in step.depends_on
            if dependency not in by_id
        }
        if missing:
            raise ValueError(f"Recipe #0 has missing dependencies: {sorted(missing)}")
        results: dict[str, ToolResult] = {}
        while len(results) < len(steps):
            ready = [
                step
                for step in steps
                if step.step_id not in results
                and all(dependency in results for dependency in step.depends_on)
            ]
            if not ready:
                raise ValueError("Recipe #0 dependency graph contains a cycle")
            for step in ready:
                results[step.step_id] = await self.run_step(step, ctx=ctx)
        return results


__all__ = ["RecipeRunner", "RecipeStep", "ToolbeltRecipeRunner"]
