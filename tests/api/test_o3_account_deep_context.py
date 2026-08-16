"""M8B O3 real-Postgres steering-card and L3 materialization acceptance."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text

from clue_api.account_deep_steering_context import (
    _approved_tiers,
    compile_account_deep_steering_context,
    prepare_account_deep_steering_context,
)
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.trial.account_deep_fixture import (
    DEEP_FIELD_KEYS,
    seed_insight_health_account_deep_fixture,
)
from clue_api.trial.discovery_fixture import PRODUCT_ID, PROJECT_ID, WORKSPACE_ID
from clue_core import new_operation_id
from clue_research.durable import create_account_deep_launch
from clue_storage import FsStorage
from tests.api.account_deep_test_support import confirmed_account_research_direction
from tests.api.test_account_deep_fixture_a1 import _pages
from tests.db.conftest import run_async
from tests.profiling.conftest import conn_session_factory
from tests.stage0.conftest import rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")


def test_numeric_checkpoint_accounts_retain_their_exact_approved_tiers() -> None:
    first = "10000000-0000-0000-0000-000000000001"
    second = "10000000-0000-0000-0000-000000000002"

    approved = _approved_tiers(
        {
            "checkpoint_status": "resumed",
            "review": {
                "accounts": [
                    {"account_id": first, "tier": "high"},
                    {"account_id": second, "tier": "low"},
                ]
            },
        }
    )

    assert {str(account_id): tier for account_id, tier in approved.items()} == {
        first: "high",
        second: "low",
    }


def test_current_card_and_materialized_directive_remain_non_authoritative(tmp_path) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed=False) as conn:
            storage = FsStorage(tmp_path / "artifacts")
            fixture = await seed_insight_health_account_deep_fixture(
                conn,
                pages=_pages(),
                storage=storage,
            )
            _, account_spec = await confirmed_account_research_direction(
                conn,
                workspace_id=WORKSPACE_ID,
                project_id=PROJECT_ID,
                product_id=PRODUCT_ID,
                account_id=fixture.selected_account_id,
                icp_key=fixture.deep_icp_key,
                icp_version=fixture.deep_icp_version,
                field_keys=(DEEP_FIELD_KEYS[2], DEEP_FIELD_KEYS[3]),
            )
            pin = account_spec.research_directive
            assert pin is not None
            cf = conn_session_factory(conn)

            before = await compile_account_deep_steering_context(
                workspace_id=WORKSPACE_ID,
                project_run_id=fixture.project_run_id,
                conn_factory=cf,
            )
            assert before is not None
            before_card, before_directive = before
            assert before_directive is not None
            assert before_card.approved_account_count == 1
            assert before_card.accounts[0].canonical_name
            assert before_card.accounts[0].tier_approved is True
            assert before_card.accounts[0].in_latest_directive is True
            assert before_card.accounts[0].in_launch is False
            assert before_card.latest_directive is not None
            assert before_card.latest_directive.field_keys == (
                DEEP_FIELD_KEYS[2],
                DEEP_FIELD_KEYS[3],
            )
            assert before_card.latest_directive.privacy_policy.contact_reveals_allowed is False
            assert before_card.launch_state == "not_launched"
            assert before_card.launch is None

            await create_account_deep_launch(
                conn,
                workspace_id=WORKSPACE_ID,
                project_run_id=fixture.project_run_id,
                directive_id=pin.directive_id,
                account_entity_ids=(fixture.selected_account_id,),
                approved_budget_cap_cents=account_spec.budget_cap_cents,
                expected_estimated_cost_cents=account_spec.budget_cap_cents,
                created_by="human:o3-context",
                source_operation_id=new_operation_id(),
                source_action_ref="turn:o3-explicit-launch",
            )
            after = await compile_account_deep_steering_context(
                workspace_id=WORKSPACE_ID,
                project_run_id=fixture.project_run_id,
                conn_factory=cf,
            )
            assert after is not None
            after_card, _ = after
            assert after_card.launch_state == "receipt_created"
            assert after_card.launch is not None
            assert after_card.launch.launch_ref.startswith("account-deep-launch:")
            assert after_card.accounts[0].in_launch is True
            assert after_card.accounts[0].account_run_status is None

            artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=cf)
            context = await prepare_account_deep_steering_context(
                artifacts=artifacts,
                workspace_id=WORKSPACE_ID,
                project_run_id=fixture.project_run_id,
                conn_factory=cf,
            )
            assert [item.name for item in context] == [
                "account-deep-steering",
                "research-directive",
            ]
            card_payload = json.loads(await artifacts.read(context[0].artifact_ref))
            directive_payload = json.loads(await artifacts.read(context[1].artifact_ref))
            assert card_payload["launch_state"] == "receipt_created"
            assert card_payload["accounts"][0].get("account_run_status") is None
            assert directive_payload["directive_id"] == str(pin.directive_id)
            assert context[1].domain_ref.object_type == "research_directive"
            assert context[1].domain_ref.version == pin.version
            directive_subjects = (
                await conn.execute(
                    text(
                        "SELECT subject_entity_id FROM agent_artifact_subject "
                        "WHERE workspace_id=:workspace_id AND artifact_key=:artifact_key "
                        "ORDER BY subject_entity_id"
                    ),
                    {
                        "workspace_id": WORKSPACE_ID,
                        "artifact_key": context[1].artifact_ref.artifact_key,
                    },
                )
            ).scalars()
            assert tuple(str(value) for value in directive_subjects) == (
                str(fixture.selected_account_id),
            )

    run_async(scenario())
