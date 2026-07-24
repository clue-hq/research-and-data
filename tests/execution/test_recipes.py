"""C5.2 immutable recipe lifecycle and system-seed integration."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.recipe_wiring import (
    load_system_recipe_definitions,
    seed_system_recipes,
)
from clue_db import ConnFactory
from clue_execution import (
    CompatibilityContext,
    CompatibilityLoader,
    CompatibilityManifest,
    DbRecipeRepository,
    InvalidRecipeTransition,
    PinResolverRegistry,
    RecipeDefinition,
    RecipeGraph,
    RecipeLifecycle,
    RecipeRevisionEventType,
    RecipeScopeType,
    RecipeVersionConflict,
    ToolNode,
)
from clue_toolbelt import ToolRegistry
from tests.db.conftest import run_async
from tests.profiling.conftest import rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")


def _savepoint_factory(conn: AsyncConnection) -> ConnFactory:
    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncConnection]:
        nested = await conn.begin_nested()
        try:
            yield conn
        except BaseException:
            await nested.rollback()
            raise
        else:
            await nested.commit()

    return factory


def _lifecycle(
    conn: AsyncConnection,
) -> tuple[DbRecipeRepository, RecipeLifecycle]:
    repository = DbRecipeRepository(conn_factory=_savepoint_factory(conn))
    lifecycle = RecipeLifecycle(
        repository=repository,
        tool_catalog=ToolRegistry(),
        compatibility_loader=CompatibilityLoader(PinResolverRegistry()),
    )
    return repository, lifecycle


def test_system_seed_is_promoted_digest_exact_and_replay_safe() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            repository, lifecycle = _lifecycle(conn)
            definitions = load_system_recipe_definitions()

            first = await seed_system_recipes(
                repository=repository,
                lifecycle=lifecycle,
                definitions=definitions,
            )
            replay = await seed_system_recipes(
                repository=repository,
                lifecycle=lifecycle,
                definitions=definitions,
            )

            assert [item.recipe_revision_id for item in replay] == [
                item.recipe_revision_id for item in first
            ]
            assert [item.definition_sha256 for item in first] == [
                item.definition_sha256 for item in definitions
            ]
            events = (
                await conn.execute(
                    text(
                        """
                        SELECT event_type, count(*) AS count
                        FROM recipe_revision_event
                        WHERE recipe_revision_id = ANY(CAST(:revision_ids AS uuid[]))
                        GROUP BY event_type ORDER BY event_type
                        """
                    ),
                    {"revision_ids": [item.recipe_revision_id for item in first]},
                )
            ).mappings()
            assert {row["event_type"]: row["count"] for row in events} == {
                "promoted": 2,
                "proposed": 2,
            }

            mismatch = definitions[0].model_copy(update={"max_nodes": 129})
            with pytest.raises(RecipeVersionConflict, match="bump the recipe version"):
                await repository.propose(mismatch)

    run_async(scenario())


def test_promoted_revision_is_database_immutable_and_retirement_is_append_only() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            repository, lifecycle = _lifecycle(conn)
            definition = load_system_recipe_definitions()[0]
            revision = (
                await seed_system_recipes(
                    repository=repository,
                    lifecycle=lifecycle,
                    definitions=(definition,),
                )
            )[0]

            nested = await conn.begin_nested()
            with pytest.raises(DBAPIError):
                await conn.execute(
                    text("UPDATE recipe_revision SET max_nodes = max_nodes + 1 WHERE id = :id"),
                    {"id": revision.recipe_revision_id},
                )
            await nested.rollback()

            retired = await lifecycle.retire(
                recipe_revision_id=revision.recipe_revision_id,
                actor="human",
                reason_code="operator_retired",
            )
            replay = await lifecycle.retire(
                recipe_revision_id=revision.recipe_revision_id,
                actor="human",
                reason_code="operator_retired",
            )
            assert retired.seq == replay.seq
            assert retired.event_type is RecipeRevisionEventType.RETIRED

            with pytest.raises(InvalidRecipeTransition):
                await lifecycle.promote(
                    revision,
                    context=CompatibilityContext(workspace_id="__system__"),
                    actor="system",
                )
            effective = await repository.effective_event(
                recipe_revision_id=revision.recipe_revision_id
            )
            assert effective is not None
            assert effective.event_type is RecipeRevisionEventType.RETIRED

    run_async(scenario())


def test_invalid_graph_collects_errors_and_never_appends_promoted_event() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            repository, lifecycle = _lifecycle(conn)
            definition = RecipeDefinition(
                recipe_key="invalid",
                scope_type=RecipeScopeType.SYSTEM,
                version=1,
                executor_protocol=1,
                parameter_schema={"type": "object", "properties": {}},
                graph=RecipeGraph(
                    nodes=(
                        ToolNode(
                            node_key="unknown",
                            ordinal=0,
                            tool_name="absent",
                            tool_version="1",
                            input_schema_sha256="0" * 64,
                            output_schema_sha256="0" * 64,
                        ),
                    ),
                    tool_allowlist=("absent@1",),
                ),
                compatibility=CompatibilityManifest(),
                max_nodes=2,
                max_depth=1,
                max_fanout=1,
                created_by="system",
            )
            revision = await repository.propose(definition)
            result = await lifecycle.promote(
                revision,
                context=CompatibilityContext(workspace_id="__system__"),
                actor="system",
            )
            assert result.promoted is False
            assert any(issue.code == "unknown_tool" for issue in result.graph_validation.issues)
            effective = await repository.effective_event(
                recipe_revision_id=revision.recipe_revision_id
            )
            assert effective is not None
            assert effective.event_type is RecipeRevisionEventType.PROPOSED

    run_async(scenario())


def test_newer_promoted_revision_can_supersede_old_revision() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            repository, lifecycle = _lifecycle(conn)
            first_definition = load_system_recipe_definitions()[0]
            first = (
                await seed_system_recipes(
                    repository=repository,
                    lifecycle=lifecycle,
                    definitions=(first_definition,),
                )
            )[0]
            second_definition = first_definition.model_copy(update={"version": 2})
            second = (
                await seed_system_recipes(
                    repository=repository,
                    lifecycle=lifecycle,
                    definitions=(second_definition,),
                )
            )[0]

            event = await lifecycle.supersede(
                recipe_revision_id=first.recipe_revision_id,
                replacement=second,
                actor="system",
            )
            assert event.event_type is RecipeRevisionEventType.SUPERSEDED
            assert event.reason_code == f"superseded_by:{second.recipe_revision_id}"

    run_async(scenario())
