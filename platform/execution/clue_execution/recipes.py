"""C5.1 recipe persistence read shapes.

Mutation/promotion and compatibility behavior deliberately land in C5.2. These row contracts make
the C5.1 schema inspectable without prematurely shipping that later lifecycle.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy import text

from clue_core import ExecutionId, RecipeId, RecipeRevisionId, UtcDatetime, decode_jsonb
from clue_db import ConnFactory
from clue_execution.models import RecipeScopeType


class RecipeRevisionView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    recipe_id: RecipeId
    recipe_revision_id: RecipeRevisionId
    recipe_key: str
    scope_type: RecipeScopeType
    workspace_id: str | None
    version: int
    executor_protocol: int
    parameter_schema: dict[str, JsonValue]
    graph: dict[str, JsonValue]
    compatibility: dict[str, JsonValue]
    requested_memory_types: tuple[str, ...]
    max_nodes: int
    max_depth: int
    max_fanout: int
    source_execution_id: ExecutionId | None
    definition_sha256: str
    created_by: str
    created_at: UtcDatetime


class DbRecipeReader:
    def __init__(self, *, conn_factory: ConnFactory) -> None:
        self._conn_factory = conn_factory

    async def get_revision(
        self,
        *,
        recipe_revision_id: RecipeRevisionId,
        workspace_id: str,
    ) -> RecipeRevisionView | None:
        async with self._conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT r.id AS recipe_id, rr.id AS recipe_revision_id, r.recipe_key,
                                   r.scope_type, r.workspace_id, rr.version,
                                   rr.executor_protocol, rr.parameter_schema_json, rr.graph_json,
                                   rr.compatibility_json, rr.requested_memory_types,
                                   rr.max_nodes, rr.max_depth, rr.max_fanout,
                                   rr.source_execution_id, rr.definition_sha256,
                                   rr.created_by, rr.created_at
                            FROM recipe_revision rr
                            JOIN recipe r ON r.id = rr.recipe_id
                            WHERE rr.id = :revision
                              AND (r.scope_type = 'system' OR r.workspace_id = :workspace_id)
                            """
                        ),
                        {
                            "revision": recipe_revision_id,
                            "workspace_id": workspace_id,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return None
        data = dict(row)
        parameter_schema = decode_jsonb(data.pop("parameter_schema_json"))
        graph = decode_jsonb(data.pop("graph_json"))
        compatibility = decode_jsonb(data.pop("compatibility_json"))
        requested_memory_types = tuple(decode_jsonb(data["requested_memory_types"]))
        return RecipeRevisionView.model_validate(
            {
                **data,
                "parameter_schema": parameter_schema,
                "graph": graph,
                "compatibility": compatibility,
                "requested_memory_types": requested_memory_types,
            }
        )


__all__ = ["DbRecipeReader", "RecipeRevisionView"]
