"""Automatic targeting persists exact pins without inventing a human gate answer."""

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_api.arv2.icp_confirmation import current_project_icp_pin
from clue_api.project_targeting_tools import (
    ConfigureProjectTargetingInput,
    ConfigureProjectTargetingTool,
)
from clue_api.turn_action import derive_turn_action_ref
from clue_spine import create_product, current_project_product_set, list_project_product_sets
from tests.api.test_icp_artifact_gate_db import _ctx, _seed_icp
from tests.db.conftest import run_async
from tests.profiling.conftest import migrated_db, rollback_conn  # noqa: F401


@pytest.fixture(autouse=True)
def require_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires isolated migrated Postgres")


def _input(f, **kwargs):
    return ConfigureProjectTargetingInput(
        icp_key="clinics", source_turn_ref=derive_turn_action_ref(f.seeded.turn_id), **kwargs
    )


@pytest.mark.parametrize("status", ["ready", "proposed", "confirmed"])
def test_automatic_targeting_pins_exact_bytes_without_a_gate(tmp_path: Path, status: str) -> None:
    async def scenario():
        async with rollback_conn() as conn:
            f = await _seed_icp(
                conn,
                tmp_path,
                workspace_id=f"ws-auto-{status}",
                label=f"auto-{status}",
                status=status,
            )
            tool = ConfigureProjectTargetingTool(conn_factory=f.conn_factory, storage=f.storage)
            assert not await tool.preconditions(_input(f), _ctx(f))
            first = await tool.invoke(_input(f), _ctx(f))
            second = await tool.invoke(_input(f), _ctx(f))
            assert first.references == second.references
            pin = await current_project_icp_pin(
                conn, workspace_id=f.seeded.workspace_id, project_id=f.project.project_id
            )
            selection = await current_project_product_set(
                conn, workspace_id=f.seeded.workspace_id, project_id=f.project.project_id
            )
            assert pin and selection
            assert pin.artifact_sha256 == first.references["icp_artifact_sha256"]
            assert pin.product_selection_version == selection.selection_version == 1
            assert selection.product_ids == (f.product.product_id,)
            assert selection.gate_id is None
            assert selection.confirmation_turn_id == f.seeded.turn_id
            body = (await f.storage.get(pin.artifact_key)).decode()
            assert "confirmation_mode: automatic" in body
            assert derive_turn_action_ref(f.seeded.turn_id) in body
            assert (
                await conn.execute(
                    text("SELECT count(*) FROM agent_gate WHERE workspace_id=:ws"),
                    {"ws": f.seeded.workspace_id},
                )
            ).scalar_one() == 0
            assert (
                len(
                    await list_project_product_sets(
                        conn, workspace_id=f.seeded.workspace_id, project_id=f.project.project_id
                    )
                )
                == 1
            )

    run_async(scenario())


def test_product_correction_mints_version_and_keeps_the_choice(tmp_path: Path) -> None:
    async def scenario():
        async with rollback_conn() as conn:
            f = await _seed_icp(conn, tmp_path, workspace_id="ws-auto-correct", label="autocorrect")
            tool = ConfigureProjectTargetingTool(conn_factory=f.conn_factory, storage=f.storage)
            first = await tool.invoke(_input(f), _ctx(f))
            product = await create_product(
                conn, brand_id=f.brand_id, workspace_id=f.seeded.workspace_id, name="New product"
            )
            second = await tool.invoke(_input(f, product_ids=(product.product_id,)), _ctx(f))
            replay = await tool.invoke(_input(f), _ctx(f))
            assert second.references == replay.references
            assert second.references["product_selection_version"] == 2
            assert first.references["document_id"] != second.references["document_id"]
            assert (
                len(
                    await list_project_product_sets(
                        conn, workspace_id=f.seeded.workspace_id, project_id=f.project.project_id
                    )
                )
                == 2
            )

    run_async(scenario())


@pytest.mark.parametrize("failure", ["foreign_turn", "unknown_product", "missing_document"])
def test_refusals_leave_no_partial_selection(tmp_path: Path, failure: str) -> None:
    async def scenario():
        async with rollback_conn() as conn:
            f = await _seed_icp(
                conn,
                tmp_path,
                workspace_id=f"ws-auto-{failure}",
                label=failure,
                with_document=failure != "missing_document",
            )
            tool = ConfigureProjectTargetingTool(conn_factory=f.conn_factory, storage=f.storage)
            inputs = _input(f)
            if failure == "foreign_turn":
                inputs = inputs.model_copy(
                    update={"source_turn_ref": derive_turn_action_ref(uuid4())}
                )
            elif failure == "unknown_product":
                inputs = _input(f, product_ids=("foreign-product",))
            assert await tool.preconditions(inputs, _ctx(f))
            assert (
                await current_project_product_set(
                    conn, workspace_id=f.seeded.workspace_id, project_id=f.project.project_id
                )
                is None
            )

    run_async(scenario())
