"""Production workspace-client inheritance and fail-closed binding tests."""

from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from clue_api.client_context_binding import (
    WorkspaceClientBinding,
    WorkspaceClientBindingConflict,
    bind_workspace_client,
    get_workspace_client_binding,
)
from clue_api.conversation_capture import project_client_entity_id
from clue_core import AccountStatus, EntityId
from clue_db import db_lifespan
from clue_research.identity import insert_account_entity
from clue_spine import create_brand, create_project
from tests._workspace import seed_workspace
from tests.stage0.conftest import (
    migrated_db as migrated_db,  # noqa: F401 -- re-export fixture into api scope
)
from tests.stage0.conftest import (
    require_stage0_db as require_stage0_db,  # noqa: F401 -- re-export fixture
)
from tests.stage0.conftest import rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_stage0_db")


def test_binding_schema_reuses_existing_workspace_scope_anchors() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed=False) as conn:
            constraints = set(
                (
                    await conn.execute(
                        text(
                            "SELECT conname FROM pg_constraint WHERE conname IN ("
                            "'recon_run_scope_anchor', 'recon_run_workspace_anchor', "
                            "'workspace_client_binding_client_fk', "
                            "'workspace_client_binding_recon_fk')"
                        )
                    )
                ).scalars()
            )
            assert constraints == {
                "recon_run_scope_anchor",
                "workspace_client_binding_client_fk",
                "workspace_client_binding_recon_fk",
            }
            index = (
                (
                    await conn.execute(
                        text(
                            "SELECT indexdef FROM pg_indexes "
                            "WHERE indexname = 'workspace_client_binding_client_lookup'"
                        )
                    )
                )
                .scalars()
                .one()
            )
            assert "UNIQUE" not in index
            assert "(client_entity_id, workspace_id)" in index

    run_async(scenario())


def test_every_project_inherits_one_canonical_workspace_client() -> None:
    async def scenario() -> None:
        async with rollback_conn(workspace_id="context-binding") as conn:
            brand = await create_brand(
                conn, workspace_id="context-binding", name="Context Binding Brand"
            )
            project_a = await create_project(
                conn,
                workspace_id="context-binding",
                brand_id=brand.brand_id,
                name="Project A",
            )
            project_b = await create_project(
                conn,
                workspace_id="context-binding",
                brand_id=brand.brand_id,
                name="Project B",
            )
            client = await insert_account_entity(
                conn,
                canonical_name="Customer Company",
                primary_domain="customer.example",
                workspace_id="context-binding",
                status=AccountStatus.ACTIVE,
            )
            first = await bind_workspace_client(
                conn, workspace_id="context-binding", client_entity_id=client
            )
            replay = await bind_workspace_client(
                conn, workspace_id="context-binding", client_entity_id=client
            )
            assert first == replay
            assert (
                await project_client_entity_id(
                    conn, workspace_id="context-binding", project_id=project_a.project_id
                )
                == client
            )
            assert (
                await project_client_entity_id(
                    conn, workspace_id="context-binding", project_id=project_b.project_id
                )
                == client
            )

    run_async(scenario())


def test_binding_refuses_repoint_and_cross_workspace_entity() -> None:
    async def scenario() -> None:
        async with rollback_conn(workspace_id="binding-owner") as conn:
            await seed_workspace(conn, "binding-foreign")
            owner = await insert_account_entity(
                conn,
                canonical_name="Owner",
                primary_domain="owner.example",
                workspace_id="binding-owner",
                status=AccountStatus.ACTIVE,
            )
            other = await insert_account_entity(
                conn,
                canonical_name="Other",
                primary_domain="other.example",
                workspace_id="binding-owner",
                status=AccountStatus.ACTIVE,
            )
            foreign = await insert_account_entity(
                conn,
                canonical_name="Foreign",
                primary_domain="foreign.example",
                workspace_id="binding-foreign",
                status=AccountStatus.ACTIVE,
            )
            foreign_brand = await create_brand(
                conn,
                workspace_id="binding-foreign",
                name="Foreign Brand",
            )
            foreign_project = await create_project(
                conn,
                workspace_id="binding-foreign",
                brand_id=foreign_brand.brand_id,
                name="Foreign Project",
            )
            await bind_workspace_client(conn, workspace_id="binding-owner", client_entity_id=owner)
            with pytest.raises(WorkspaceClientBindingConflict):
                await bind_workspace_client(
                    conn, workspace_id="binding-owner", client_entity_id=other
                )

            nested = await conn.begin_nested()
            with pytest.raises(IntegrityError):
                await bind_workspace_client(
                    conn, workspace_id="binding-foreign", client_entity_id=owner
                )
            await nested.rollback()
            assert await get_workspace_client_binding(conn, workspace_id="binding-foreign") is None
            assert (
                await project_client_entity_id(
                    conn,
                    workspace_id="binding-owner",
                    project_id=foreign_project.project_id,
                )
                is None
            )
            assert (
                await project_client_entity_id(
                    conn,
                    workspace_id="binding-owner",
                    project_id="prj_unknown",
                )
                is None
            )
            assert foreign != owner

    run_async(scenario())


def test_concurrent_binding_is_single_winner_and_same_client_replays() -> None:
    async def scenario() -> None:
        replay_workspace = f"binding-replay-{uuid4()}"
        conflict_workspace = f"binding-conflict-{uuid4()}"
        async with db_lifespan() as engine:
            async with engine.begin() as conn:
                await seed_workspace(conn, replay_workspace)
                await seed_workspace(conn, conflict_workspace)
                replay_client = await insert_account_entity(
                    conn,
                    canonical_name="Concurrent Replay Client",
                    workspace_id=replay_workspace,
                    status=AccountStatus.ACTIVE,
                )
                first_candidate = await insert_account_entity(
                    conn,
                    canonical_name="Concurrent Candidate One",
                    workspace_id=conflict_workspace,
                    status=AccountStatus.ACTIVE,
                )
                second_candidate = await insert_account_entity(
                    conn,
                    canonical_name="Concurrent Candidate Two",
                    workspace_id=conflict_workspace,
                    status=AccountStatus.ACTIVE,
                )

            async def bind(workspace_id: str, client_entity_id: EntityId) -> WorkspaceClientBinding:
                async with engine.begin() as conn:
                    return await bind_workspace_client(
                        conn,
                        workspace_id=workspace_id,
                        client_entity_id=client_entity_id,
                    )

            try:
                replays = await asyncio.gather(
                    *(bind(replay_workspace, replay_client) for _ in range(10))
                )
                assert {item.client_entity_id for item in replays} == {replay_client}

                outcomes = await asyncio.gather(
                    bind(conflict_workspace, first_candidate),
                    bind(conflict_workspace, second_candidate),
                    return_exceptions=True,
                )
                winners = [item for item in outcomes if not isinstance(item, BaseException)]
                conflicts = [
                    item for item in outcomes if isinstance(item, WorkspaceClientBindingConflict)
                ]
                assert len(winners) == 1
                assert len(conflicts) == 1
                async with engine.begin() as conn:
                    binding = await get_workspace_client_binding(
                        conn, workspace_id=conflict_workspace
                    )
                assert binding is not None
                assert binding.client_entity_id in {first_candidate, second_candidate}
            finally:
                async with engine.begin() as conn:
                    await conn.execute(
                        text(
                            "DELETE FROM workspace_client_binding "
                            "WHERE workspace_id IN (:replay, :conflict)"
                        ),
                        {"replay": replay_workspace, "conflict": conflict_workspace},
                    )
                    await conn.execute(
                        text(
                            "DELETE FROM account_entity WHERE workspace_id IN (:replay, :conflict)"
                        ),
                        {"replay": replay_workspace, "conflict": conflict_workspace},
                    )
                    await conn.execute(
                        text("DELETE FROM workspace WHERE workspace_id IN (:replay, :conflict)"),
                        {"replay": replay_workspace, "conflict": conflict_workspace},
                    )

    run_async(scenario())
