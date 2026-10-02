"""C5.2 immutable recipe lifecycle and system-seed integration."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, cast

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.execution_tools import AdvanceProjectPhaseTool, ExecutionControlServices
from clue_api.recipe_contracts import RECIPE_0_TOOL_ADDRESSES
from clue_api.recipe_wiring import (
    HISTORICAL_REPLAY_ONLY_RECIPE_FILENAMES,
    build_recipe_pin_registry,
    load_system_recipe_definitions,
    seed_system_recipes,
    system_recipe_asset_root,
)
from clue_api.toolbelt_wiring import build_toolbelt
from clue_db import ConnFactory
from clue_execution import (
    CompatibilityContext,
    CompatibilityLoader,
    CompatibilityManifest,
    DbRecipeRepository,
    GateNode,
    InvalidRecipeTransition,
    RecipeDefinition,
    RecipeGraph,
    RecipeLifecycle,
    RecipeRevisionEventType,
    RecipeScopeType,
    RecipeVersionConflict,
    ToolNode,
    load_recipe_definition,
)
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
    factory = _savepoint_factory(conn)
    repository = DbRecipeRepository(conn_factory=factory)
    registry = build_toolbelt(storage=None)
    registry.register(
        AdvanceProjectPhaseTool(
            ExecutionControlServices(
                starter=cast(Any, None),
                executor=cast(Any, None),
                parameters=cast(Any, None),
                recipes=repository,
                run_machine=cast(Any, None),
                queue=cast(Any, None),
                conn_factory=factory,
                registry=registry,
            )
        ),
        make_default=True,
    )
    pins = build_recipe_pin_registry(
        tool_registry=registry,
        conn_factory=factory,
    )
    lifecycle = RecipeLifecycle(
        repository=repository,
        tool_catalog=registry,
        compatibility_loader=CompatibilityLoader(pins),
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
            definition_count = len(definitions)
            recipe_count = len({definition.recipe_key for definition in definitions})
            assert {row["event_type"]: row["count"] for row in events} == {
                "promoted": definition_count,
                "proposed": definition_count,
                "superseded": definition_count - recipe_count,
            }

            mismatch = definitions[0].model_copy(update={"max_nodes": 129})
            with pytest.raises(RecipeVersionConflict, match="bump the recipe version"):
                await repository.propose(mismatch)

    run_async(scenario())


def test_c67_account_unit_is_preserved_as_replay_only_not_system_seeded() -> None:
    definitions = load_system_recipe_definitions()
    assert all(item.recipe_key != "account-research-unit" for item in definitions)
    assert "account-research-unit-v1.json" in HISTORICAL_REPLAY_ONLY_RECIPE_FILENAMES
    account = load_recipe_definition(
        system_recipe_asset_root() / HISTORICAL_REPLAY_ONLY_RECIPE_FILENAMES[0]
    )
    slot = next(
        node for node in account.graph.nodes if node.node_key == "account_research_interactions"
    )

    assert isinstance(slot, GateNode)
    assert account.version == 1
    assert account.graph.tool_allowlist == ("research_account_gaps@2",)
    assert slot.dynamic_tool_allowlist == ("research_account_gaps@2",)
    assert set(slot.dynamic_pin_kinds) == {
        "project_run",
        "account",
        "field_registry",
        "source_registry",
        "coverage_policy",
    }
    assert slot.max_children == 32
    assert account.max_fanout == 1


def test_latest_recipe0_is_the_only_promoted_executable_stage0_revision() -> None:
    """The resolved latest Stage-0 recipe is promoted; every older revision remains history."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            repository, lifecycle = _lifecycle(conn)
            definitions = load_system_recipe_definitions()
            seeded = await seed_system_recipes(
                repository=repository,
                lifecycle=lifecycle,
                definitions=definitions,
            )
            recipe0 = [
                (definition, revision)
                for definition, revision in zip(definitions, seeded, strict=True)
                if definition.recipe_key == "recipe0-stage0"
            ]
            versions = [item.version for item, _ in recipe0]
            assert versions == list(range(1, max(versions) + 1))
            assert [item.graph.migration_state for item, _ in recipe0] == [
                "placeholder",
                *("executable" for _ in versions[1:]),
            ]
            effective = [
                (
                    definition.version,
                    (
                        await repository.effective_event(
                            recipe_revision_id=revision.recipe_revision_id
                        )
                    ).event_type,
                )
                for definition, revision in recipe0
            ]
            assert effective == [
                *((version, RecipeRevisionEventType.SUPERSEDED) for version in versions[:-1]),
                (versions[-1], RecipeRevisionEventType.PROMOTED),
            ]
            promoted = recipe0[-1][0]
            slot = next(
                node for node in promoted.graph.nodes if node.node_key == "stage0_interactions"
            )
            assert isinstance(slot, GateNode)
            assert set(slot.dynamic_tool_allowlist) == set(RECIPE_0_TOOL_ADDRESSES)
            assert slot.max_children == 125
            assert promoted.max_nodes == 128

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
