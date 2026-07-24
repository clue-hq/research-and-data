"""Immutable recipe revisions and append-only lifecycle events."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator
from sqlalchemy import text
from sqlalchemy.engine import RowMapping
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    ExecutionId,
    RecipeId,
    RecipeRevisionId,
    UtcDatetime,
    decode_jsonb,
    new_recipe_id,
    new_recipe_revision_id,
    serialize_value_json,
)
from clue_db import ConnFactory
from clue_execution.compatibility import (
    CompatibilityContext,
    CompatibilityLoader,
    CompatibilityManifest,
    CompatibilityReport,
)
from clue_execution.graph import (
    GraphValidation,
    RecipeGraph,
    ToolDescriptorCatalog,
    canonical_sha256,
    node_requirements,
    validate_graph,
)
from clue_execution.models import RecipeRevisionEventType, RecipeScopeType

Actor = Literal["human", "agent", "system"]


class RecipeError(RuntimeError):
    pass


class RecipeVersionConflict(RecipeError):
    pass


class InvalidRecipeTransition(RecipeError):
    pass


class RecipeDefinition(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    recipe_key: str = Field(min_length=1)
    scope_type: RecipeScopeType
    workspace_id: str | None = None
    version: int = Field(ge=1)
    executor_protocol: int = Field(ge=1)
    parameter_schema: dict[str, JsonValue]
    graph: RecipeGraph
    compatibility: CompatibilityManifest = Field(default_factory=CompatibilityManifest)
    requested_memory_types: tuple[str, ...] = ()
    max_nodes: int = Field(ge=1)
    max_depth: int = Field(ge=1)
    max_fanout: int = Field(ge=1)
    source_execution_id: ExecutionId | None = None
    created_by: Actor

    @model_validator(mode="after")
    def _coherent(self) -> RecipeDefinition:
        if self.scope_type is RecipeScopeType.SYSTEM and self.workspace_id is not None:
            raise ValueError("system recipes cannot carry a workspace_id")
        if self.scope_type is RecipeScopeType.WORKSPACE and not self.workspace_id:
            raise ValueError("workspace recipes require workspace_id")
        if self.parameter_schema.get("type") != "object":
            raise ValueError("parameter_schema must declare type=object")
        if len(self.requested_memory_types) != len(set(self.requested_memory_types)):
            raise ValueError("requested_memory_types must be unique")
        expected = node_requirements(self.graph)
        if self.compatibility.nodes != expected:
            raise ValueError(
                "compatibility.nodes must exactly mirror graph node-local requirements"
            )
        return self

    @property
    def definition_sha256(self) -> str:
        return canonical_sha256(self)


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
    created_by: Actor
    created_at: UtcDatetime

    def definition(self) -> RecipeDefinition:
        return RecipeDefinition.model_validate_json(
            json.dumps(
                {
                    "recipe_key": self.recipe_key,
                    "scope_type": self.scope_type,
                    "workspace_id": self.workspace_id,
                    "version": self.version,
                    "executor_protocol": self.executor_protocol,
                    "parameter_schema": self.parameter_schema,
                    "graph": self.graph,
                    "compatibility": self.compatibility,
                    "requested_memory_types": self.requested_memory_types,
                    "max_nodes": self.max_nodes,
                    "max_depth": self.max_depth,
                    "max_fanout": self.max_fanout,
                    "source_execution_id": self.source_execution_id,
                    "created_by": self.created_by,
                },
                default=str,
            )
        )


class RecipeRevisionEventView(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    seq: int
    recipe_revision_id: RecipeRevisionId
    event_type: RecipeRevisionEventType
    actor: Actor
    reason_code: str | None
    created_at: UtcDatetime


class RecipePromotionResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    revision: RecipeRevisionView
    graph_validation: GraphValidation
    compatibility: CompatibilityReport
    promoted: bool


def load_recipe_definition(path: Path) -> RecipeDefinition:
    return RecipeDefinition.model_validate_json(path.read_text(encoding="utf-8"))


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
        return _row_to_revision(row)

    async def get_by_identity(
        self,
        *,
        scope_type: RecipeScopeType,
        workspace_id: str | None,
        recipe_key: str,
        version: int,
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
                            WHERE r.scope_type = :scope_type
                              AND r.workspace_id IS NOT DISTINCT FROM :workspace_id
                              AND r.recipe_key = :recipe_key
                              AND rr.version = :version
                            """
                        ),
                        {
                            "scope_type": scope_type.value,
                            "workspace_id": workspace_id,
                            "recipe_key": recipe_key,
                            "version": version,
                        },
                    )
                )
                .mappings()
                .one_or_none()
            )
        return _row_to_revision(row)

    async def effective_event(
        self,
        *,
        recipe_revision_id: RecipeRevisionId,
    ) -> RecipeRevisionEventView | None:
        async with self._conn_factory() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT seq, recipe_revision_id, event_type, actor, reason_code,
                                   created_at
                            FROM recipe_revision_event
                            WHERE recipe_revision_id = :revision
                            ORDER BY seq DESC
                            LIMIT 1
                            """
                        ),
                        {"revision": recipe_revision_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return RecipeRevisionEventView.model_validate(dict(row)) if row is not None else None


def _row_to_revision(
    row: Mapping[str, Any] | RowMapping | None,
) -> RecipeRevisionView | None:
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


class DbRecipeRepository(DbRecipeReader):
    """Append-only recipe writer over the C5.1 schema."""

    async def propose(self, definition: RecipeDefinition) -> RecipeRevisionView:
        digest = definition.definition_sha256
        lock_key = (
            f"recipe:{definition.scope_type.value}:{definition.workspace_id or '-'}:"
            f"{definition.recipe_key}"
        )
        async with self._conn_factory() as conn:
            await conn.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_key, 0))"),
                {"lock_key": lock_key},
            )
            recipe_id = await self._ensure_identity(conn, definition)
            existing = (
                (
                    await conn.execute(
                        text(
                            """
                            SELECT id, definition_sha256
                            FROM recipe_revision
                            WHERE recipe_id = :recipe_id AND version = :version
                            """
                        ),
                        {"recipe_id": recipe_id, "version": definition.version},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                if existing["definition_sha256"] != digest:
                    raise RecipeVersionConflict(
                        f"{definition.recipe_key}@{definition.version} already exists with a "
                        "different definition; bump the recipe version"
                    )
                revision_id = RecipeRevisionId(existing["id"])
            else:
                revision_id = new_recipe_revision_id()
                await conn.execute(
                    text(
                        """
                        INSERT INTO recipe_revision (
                            id, recipe_id, version, executor_protocol, parameter_schema_json,
                            graph_json, compatibility_json, requested_memory_types, max_nodes,
                            max_depth, max_fanout, source_execution_id, definition_sha256,
                            created_by
                        )
                        VALUES (
                            :id, :recipe_id, :version, :executor_protocol,
                            CAST(:parameter_schema AS jsonb), CAST(:graph AS jsonb),
                            CAST(:compatibility AS jsonb), CAST(:memory_types AS jsonb),
                            :max_nodes, :max_depth, :max_fanout, :source_execution_id,
                            :definition_sha256, :created_by
                        )
                        """
                    ),
                    {
                        "id": revision_id,
                        "recipe_id": recipe_id,
                        "version": definition.version,
                        "executor_protocol": definition.executor_protocol,
                        "parameter_schema": serialize_value_json(definition.parameter_schema),
                        "graph": definition.graph.model_dump_json(),
                        "compatibility": definition.compatibility.model_dump_json(),
                        "memory_types": json.dumps(list(definition.requested_memory_types)),
                        "max_nodes": definition.max_nodes,
                        "max_depth": definition.max_depth,
                        "max_fanout": definition.max_fanout,
                        "source_execution_id": definition.source_execution_id,
                        "definition_sha256": digest,
                        "created_by": definition.created_by,
                    },
                )
                await self._append_event_locked(
                    conn,
                    recipe_revision_id=revision_id,
                    event_type=RecipeRevisionEventType.PROPOSED,
                    actor=definition.created_by,
                    reason_code=None,
                )
        revision = await self.get_by_identity(
            scope_type=definition.scope_type,
            workspace_id=definition.workspace_id,
            recipe_key=definition.recipe_key,
            version=definition.version,
        )
        if revision is None:  # pragma: no cover - impossible after a committed insert
            raise RuntimeError("proposed recipe revision vanished")
        return revision

    async def _ensure_identity(
        self,
        conn: AsyncConnection,
        definition: RecipeDefinition,
    ) -> RecipeId:
        result = await conn.execute(
            text(
                """
                SELECT id FROM recipe
                WHERE scope_type = :scope_type
                  AND workspace_id IS NOT DISTINCT FROM :workspace_id
                  AND recipe_key = :recipe_key
                """
            ),
            {
                "scope_type": definition.scope_type.value,
                "workspace_id": definition.workspace_id,
                "recipe_key": definition.recipe_key,
            },
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            return RecipeId(existing)
        recipe_id = new_recipe_id()
        await conn.execute(
            text(
                """
                INSERT INTO recipe (id, recipe_key, scope_type, workspace_id)
                VALUES (:id, :recipe_key, :scope_type, :workspace_id)
                """
            ),
            {
                "id": recipe_id,
                "recipe_key": definition.recipe_key,
                "scope_type": definition.scope_type.value,
                "workspace_id": definition.workspace_id,
            },
        )
        return recipe_id

    async def append_transition(
        self,
        *,
        recipe_revision_id: RecipeRevisionId,
        event_type: RecipeRevisionEventType,
        actor: Actor,
        reason_code: str | None = None,
    ) -> RecipeRevisionEventView:
        async with self._conn_factory() as conn:
            await conn.execute(
                text("SELECT id FROM recipe_revision WHERE id = :revision FOR UPDATE"),
                {"revision": recipe_revision_id},
            )
            current = await self._effective_event_locked(conn, recipe_revision_id)
            if current is None:
                raise RecipeError(f"recipe revision {recipe_revision_id} does not exist")
            if current.event_type is event_type:
                return current
            allowed = {
                RecipeRevisionEventType.PROPOSED: {RecipeRevisionEventType.PROMOTED},
                RecipeRevisionEventType.PROMOTED: {
                    RecipeRevisionEventType.RETIRED,
                    RecipeRevisionEventType.SUPERSEDED,
                },
            }
            if event_type not in allowed.get(current.event_type, set()):
                raise InvalidRecipeTransition(
                    f"cannot transition recipe revision from {current.event_type.value} "
                    f"to {event_type.value}"
                )
            if (
                event_type
                in {
                    RecipeRevisionEventType.RETIRED,
                    RecipeRevisionEventType.SUPERSEDED,
                }
                and not reason_code
            ):
                raise ValueError(f"{event_type.value} requires a reason_code")
            return await self._append_event_locked(
                conn,
                recipe_revision_id=recipe_revision_id,
                event_type=event_type,
                actor=actor,
                reason_code=reason_code,
            )

    async def _effective_event_locked(
        self,
        conn: AsyncConnection,
        recipe_revision_id: RecipeRevisionId,
    ) -> RecipeRevisionEventView | None:
        row = (
            (
                await conn.execute(
                    text(
                        """
                        SELECT seq, recipe_revision_id, event_type, actor, reason_code, created_at
                        FROM recipe_revision_event
                        WHERE recipe_revision_id = :revision
                        ORDER BY seq DESC LIMIT 1
                        """
                    ),
                    {"revision": recipe_revision_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        return RecipeRevisionEventView.model_validate(dict(row)) if row is not None else None

    async def _append_event_locked(
        self,
        conn: AsyncConnection,
        *,
        recipe_revision_id: RecipeRevisionId,
        event_type: RecipeRevisionEventType,
        actor: Actor,
        reason_code: str | None,
    ) -> RecipeRevisionEventView:
        row = (
            (
                await conn.execute(
                    text(
                        """
                        INSERT INTO recipe_revision_event (
                            recipe_revision_id, event_type, actor, reason_code
                        )
                        VALUES (:revision, :event_type, :actor, :reason_code)
                        RETURNING seq, recipe_revision_id, event_type, actor, reason_code,
                                  created_at
                        """
                    ),
                    {
                        "revision": recipe_revision_id,
                        "event_type": event_type.value,
                        "actor": actor,
                        "reason_code": reason_code,
                    },
                )
            )
            .mappings()
            .one()
        )
        return RecipeRevisionEventView.model_validate(dict(row))


class RecipeLifecycle:
    """Promotion gate: validate the entire graph and every exact pin before promotion."""

    def __init__(
        self,
        *,
        repository: DbRecipeRepository,
        tool_catalog: ToolDescriptorCatalog,
        compatibility_loader: CompatibilityLoader,
    ) -> None:
        self._repository = repository
        self._tool_catalog = tool_catalog
        self._compatibility_loader = compatibility_loader

    async def promote(
        self,
        revision: RecipeRevisionView,
        *,
        context: CompatibilityContext,
        actor: Actor,
    ) -> RecipePromotionResult:
        definition = revision.definition()
        if definition.definition_sha256 != revision.definition_sha256:
            raise RecipeError("stored recipe definition digest does not match its payload")
        graph_validation = validate_graph(
            definition.graph,
            parameter_schema=definition.parameter_schema,
            tool_catalog=self._tool_catalog,
            max_nodes=definition.max_nodes,
            max_depth=definition.max_depth,
            max_fanout=definition.max_fanout,
            execution_requirements=definition.compatibility.execution,
        )
        compatibility = await self._compatibility_loader.load(
            definition.compatibility,
            context=context,
        )
        promoted = graph_validation.valid and compatibility.compatible
        if promoted:
            await self._repository.append_transition(
                recipe_revision_id=revision.recipe_revision_id,
                event_type=RecipeRevisionEventType.PROMOTED,
                actor=actor,
            )
        return RecipePromotionResult(
            revision=revision,
            graph_validation=graph_validation,
            compatibility=compatibility,
            promoted=promoted,
        )

    async def retire(
        self,
        *,
        recipe_revision_id: RecipeRevisionId,
        actor: Actor,
        reason_code: str,
    ) -> RecipeRevisionEventView:
        return await self._repository.append_transition(
            recipe_revision_id=recipe_revision_id,
            event_type=RecipeRevisionEventType.RETIRED,
            actor=actor,
            reason_code=reason_code,
        )

    async def supersede(
        self,
        *,
        recipe_revision_id: RecipeRevisionId,
        replacement: RecipeRevisionView,
        actor: Actor,
    ) -> RecipeRevisionEventView:
        replacement_event = await self._repository.effective_event(
            recipe_revision_id=replacement.recipe_revision_id
        )
        current = await self._repository.get_revision(
            recipe_revision_id=recipe_revision_id,
            workspace_id=replacement.workspace_id or "__system__",
        )
        if current is None or current.recipe_id != replacement.recipe_id:
            raise InvalidRecipeTransition("replacement must belong to the same recipe identity")
        if replacement.version <= current.version:
            raise InvalidRecipeTransition("replacement must have a newer version")
        if (
            replacement_event is None
            or replacement_event.event_type is not RecipeRevisionEventType.PROMOTED
        ):
            raise InvalidRecipeTransition("replacement revision must already be promoted")
        return await self._repository.append_transition(
            recipe_revision_id=recipe_revision_id,
            event_type=RecipeRevisionEventType.SUPERSEDED,
            actor=actor,
            reason_code=f"superseded_by:{replacement.recipe_revision_id}",
        )


__all__ = [
    "Actor",
    "DbRecipeReader",
    "DbRecipeRepository",
    "InvalidRecipeTransition",
    "RecipeDefinition",
    "RecipeError",
    "RecipeLifecycle",
    "RecipePromotionResult",
    "RecipeRevisionEventView",
    "RecipeRevisionView",
    "RecipeVersionConflict",
    "load_recipe_definition",
]
