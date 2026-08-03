"""M8B A2 acceptance: durable direction, human gate, fresh context, and frozen run pins."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.memory_wiring import memory_assembly_factory
from clue_api.research_directive_tools import build_research_directive_tools
from clue_api.trial.account_deep_fixture import (
    DEEP_FIELD_KEYS,
    PROJECT_RUN_ID,
    seed_insight_health_account_deep_fixture,
)
from clue_api.trial.discovery_fixture import BRAND_ID, PRODUCT_ID, PROJECT_ID, WORKSPACE_ID
from clue_config import MemoryCaps
from clue_core import (
    AssemblyRequest,
    EntityId,
    MemoryType,
    ResearchAccountScope,
    ResearchCommitteePlan,
    ResearchDirectiveAccountOverrideBody,
    ResearchDirectiveBody,
    ResearchDirectiveId,
    ResearchDirectiveStatus,
    ResearchEffortPolicy,
    ResearchPrivacyPolicy,
    ResearchQuestion,
    ResearchSourcePolicy,
    ScopeStack,
    new_operation_id,
    new_run_id,
)
from clue_memory import WriteSeam
from clue_research.directives import (
    confirmed_directive_account_specs,
    effective_account_research_directive,
    get_research_directive,
)
from clue_research.durable import DbAccountRunStore, get_account_run
from clue_storage import FsStorage
from clue_toolbelt import PreconditionFailed, ToolContext, ToolRegistry, invoke_tool
from tests.api.test_account_deep_fixture_a1 import _pages
from tests.db.conftest import run_async
from tests.memory.conftest import add_judge, make_settings
from tests.profiling.conftest import conn_session_factory
from tests.stage0.conftest import rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

TTL = 60.0
USER_DIRECTION = (
    "For this project, investigate grounded fax, referral, phone, and administrative coordination "
    "friction; treat each as a hypothesis and do not assert it without account-locked evidence."
)


def _body(account_id: EntityId, *, successor: bool = False) -> ResearchDirectiveBody:
    return ResearchDirectiveBody(
        account_scope=ResearchAccountScope(explicit_account_ids=(account_id,)),
        field_keys=(DEEP_FIELD_KEYS[2], DEEP_FIELD_KEYS[3]),
        questions=(
            ResearchQuestion(
                question_id="fax-and-referral-friction",
                text=(
                    "Is there grounded account-level evidence of fax or referral coordination "
                    "friction?"
                ),
                target_field_key=DEEP_FIELD_KEYS[2],
                source_family_hints=("employee_reviews", "official_pages"),
            ),
            *(
                (
                    ResearchQuestion(
                        question_id="phone-intake-friction",
                        text="Is there grounded evidence of phone intake friction?",
                        target_field_key=DEEP_FIELD_KEYS[3],
                    ),
                )
                if successor
                else ()
            ),
        ),
        committee_plan=ResearchCommitteePlan(
            functions=("Operations", "Information Technology"),
            levels=("Director", "VP"),
            teams=("Administration",),
            personas=("champion", "technical_evaluator"),
            candidate_cap=12,
        ),
        source_policy=ResearchSourcePolicy(
            allowed_source_keys=("sumble_jobs", "sumble_people", "exa_deep"),
            preferred_source_keys=("sumble_people", "exa_deep"),
        ),
        privacy_policy=ResearchPrivacyPolicy(
            contact_profiling_allowed=False,
            contact_reveals_allowed=False,
        ),
        effort_policy=ResearchEffortPolicy(
            tier="tier_1",
            max_depth=2,
            max_fanout=8,
            budget_cap_cents=Decimal("300"),
            budget_envelope_ref="budget:account-deep-a2-v1",
            recursion_policy_ref="recursion:account-deep-a2-v1",
            freshness_policy_ref="freshness:account-deep-a2-v1",
        ),
        exclusions=("no patient-level facts",),
    )


def test_a2_draft_confirm_memory_override_pin_and_supersession(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path / "artifacts")
            fixture = await seed_insight_health_account_deep_fixture(
                conn,
                pages=_pages(),
                storage=storage,
            )
            cf = conn_session_factory(conn)

            def memory_factory(write_conn: AsyncConnection) -> WriteSeam:
                return WriteSeam(
                    write_conn,
                    add_judge(),
                    settings=make_settings(),
                    caps=MemoryCaps(),
                )

            registry = ToolRegistry()
            for tool in build_research_directive_tools(
                memory_write_factory=memory_factory,
                conn_factory=cf,
            ):
                registry.register(tool, make_default=True)

            override = ResearchDirectiveAccountOverrideBody(
                include_field_keys=(DEEP_FIELD_KEYS[4],),
                exclude_field_keys=(DEEP_FIELD_KEYS[3],),
                additional_questions=(
                    ResearchQuestion(
                        question_id="culture-friction",
                        text="What account-locked evidence describes administrative culture?",
                        target_field_key=DEEP_FIELD_KEYS[4],
                    ),
                ),
                exclusions=("do not infer employee sentiment from one anonymous review",),
            )
            draft_operation = new_operation_id()
            draft_ctx = ToolContext(
                workspace_id=WORKSPACE_ID,
                actor="agent",
                conn_factory=cf,
                operation_id=draft_operation,
            )
            draft_body = {
                "project_id": PROJECT_ID,
                "product_id": PRODUCT_ID,
                "icp_key": fixture.deep_icp_key,
                "icp_version": fixture.deep_icp_version,
                "body": _body(fixture.selected_account_id).model_dump(mode="json"),
                "account_overrides": [
                    {
                        "account_id": str(fixture.selected_account_id),
                        "body": override.model_dump(mode="json"),
                    }
                ],
                "user_instruction": USER_DIRECTION,
                "source_turn_ref": "agent-turn:deep-direction-1",
            }
            drafted = await invoke_tool(
                registry,
                "draft_account_research_directive",
                draft_body,
                draft_ctx,
                idempotency_ttl_s=TTL,
            )
            assert drafted.references["status"] == "draft"
            assert drafted.references["preview_hypothesis_count"] == 1
            directive_id = ResearchDirectiveId(draft_operation)

            replay = await invoke_tool(
                registry,
                "draft_account_research_directive",
                draft_body,
                draft_ctx,
                idempotency_ttl_s=TTL,
            )
            assert replay.references == drafted.references
            changed_replay_body = {
                **draft_body,
                "user_instruction": USER_DIRECTION + " Changed under the same operation id.",
            }
            with pytest.raises(PreconditionFailed) as changed_draft_replay:
                await invoke_tool(
                    registry,
                    "draft_account_research_directive",
                    changed_replay_body,
                    draft_ctx,
                    idempotency_ttl_s=TTL,
                )
            assert changed_draft_replay.value.reason_codes == (
                "research_directive_replay_conflict",
            )
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM account_research_directive "
                        "WHERE directive_id=:directive_id"
                    ),
                    {"directive_id": directive_id},
                )
            ).scalar_one() == 1

            bundle = await memory_assembly_factory(make_settings(), cf).assemble(
                AssemblyRequest(
                    scope_stack=ScopeStack(
                        workspace_id=WORKSPACE_ID,
                        brand_id=BRAND_ID,
                        product_id=PRODUCT_ID,
                        project_id=PROJECT_ID,
                        account_entity_id=fixture.selected_account_id,
                    ),
                    recipe="account-research-unit@1",
                    requested_types=(MemoryType.PREFERENCE,),
                )
            )
            assert bundle is not None
            assert USER_DIRECTION in {entry.body for entry in bundle.entries}

            confirm_body = {
                "directive_id": str(directive_id),
                "expected_sha256": drafted.references["canonical_json_sha256"],
                "confirmed_by": "human:user-a2",
                "confirming_turn_ref": "human-turn:deep-direction-confirm-1",
            }
            with pytest.raises(PreconditionFailed) as agent_confirmation:
                await invoke_tool(
                    registry,
                    "confirm_account_research_directive",
                    confirm_body,
                    ToolContext(
                        workspace_id=WORKSPACE_ID,
                        actor="agent",
                        conn_factory=cf,
                        operation_id=new_operation_id(),
                    ),
                    idempotency_ttl_s=TTL,
                )
            assert agent_confirmation.value.reason_codes == ("human_required",)

            confirm_operation = new_operation_id()
            confirm_ctx = ToolContext(
                workspace_id=WORKSPACE_ID,
                actor="human",
                conn_factory=cf,
                operation_id=confirm_operation,
            )
            confirmed = await invoke_tool(
                registry,
                "confirm_account_research_directive",
                confirm_body,
                confirm_ctx,
                idempotency_ttl_s=TTL,
            )
            assert confirmed.references["status"] == "confirmed"
            durable_confirmation_replay = await invoke_tool(
                registry,
                "confirm_account_research_directive",
                confirm_body,
                confirm_ctx,
                idempotency_ttl_s=TTL,
            )
            assert durable_confirmation_replay.references == confirmed.references
            with pytest.raises(PreconditionFailed) as changed_confirmation_replay:
                await invoke_tool(
                    registry,
                    "confirm_account_research_directive",
                    {
                        **confirm_body,
                        "confirming_turn_ref": "human-turn:different-confirmation",
                    },
                    confirm_ctx,
                    idempotency_ttl_s=TTL,
                )
            assert changed_confirmation_replay.value.reason_codes == (
                "research_directive_not_draft",
            )
            specs = await confirmed_directive_account_specs(
                conn,
                workspace_id=WORKSPACE_ID,
                directive_id=directive_id,
            )
            assert len(specs) == 1
            assert specs[0].research_directive is not None
            assert specs[0].field_keys == (DEEP_FIELD_KEYS[2], DEEP_FIELD_KEYS[4])

            plan = await DbAccountRunStore(conn_factory=cf).begin(
                account_run_id=fixture.expected_account_run_id,
                project_run_id=PROJECT_RUN_ID,
                entity_id=fixture.selected_account_id,
                tier=specs[0].tier,
                workspace_id=WORKSPACE_ID,
                field_keys=specs[0].field_keys,
                research_directive=specs[0].research_directive,
            )
            assert plan.research_directive == specs[0].research_directive
            account_run = await get_account_run(conn, fixture.expected_account_run_id)
            assert account_run is not None
            original_pin = account_run.research_directive
            assert original_pin == specs[0].research_directive

            legacy_run_id = new_run_id()
            await conn.execute(
                text(
                    "INSERT INTO account_run (id, project_run_id, entity_id, tier, status, "
                    "plan_json) VALUES (:id, :project_run_id, :entity_id, 'tier_1', "
                    "'running', '{}'::jsonb)"
                ),
                {
                    "id": legacy_run_id,
                    "project_run_id": PROJECT_RUN_ID,
                    "entity_id": fixture.selected_account_id,
                },
            )
            assert original_pin is not None
            with pytest.raises(Exception, match="must be pinned before an account run begins"):
                async with conn.begin_nested():
                    await conn.execute(
                        text(
                            "UPDATE account_run SET research_directive_id=:directive_id, "
                            "research_directive_version=:version, "
                            "research_directive_ref=:directive_ref, "
                            "research_directive_sha256=:sha256, "
                            "research_directive_override_id=:override_id, "
                            "research_directive_override_ref=:override_ref, "
                            "research_directive_override_sha256=:override_sha256 WHERE id=:id"
                        ),
                        {
                            "id": legacy_run_id,
                            "directive_id": original_pin.directive_id,
                            "version": original_pin.version,
                            "directive_ref": original_pin.directive_ref,
                            "sha256": original_pin.canonical_json_sha256,
                            "override_id": original_pin.override_id,
                            "override_ref": original_pin.override_ref,
                            "override_sha256": original_pin.override_sha256,
                        },
                    )

            successor_ctx = ToolContext(
                workspace_id=WORKSPACE_ID,
                actor="agent",
                conn_factory=cf,
                operation_id=new_operation_id(),
            )
            successor_body = {
                **draft_body,
                "body": _body(fixture.selected_account_id, successor=True).model_dump(mode="json"),
                "account_overrides": [],
                "predecessor_id": str(directive_id),
                "user_instruction": USER_DIRECTION + " Also investigate phone intake friction.",
                "source_turn_ref": "agent-turn:deep-direction-2",
            }
            successor_draft = await invoke_tool(
                registry,
                "draft_account_research_directive",
                successor_body,
                successor_ctx,
                idempotency_ttl_s=TTL,
            )
            successor_id = ResearchDirectiveId(successor_ctx.operation_id)
            await invoke_tool(
                registry,
                "confirm_account_research_directive",
                {
                    "directive_id": str(successor_id),
                    "expected_sha256": successor_draft.references["canonical_json_sha256"],
                    "confirmed_by": "human:user-a2",
                    "confirming_turn_ref": "human-turn:deep-direction-confirm-2",
                },
                ToolContext(
                    workspace_id=WORKSPACE_ID,
                    actor="human",
                    conn_factory=cf,
                    operation_id=new_operation_id(),
                ),
                idempotency_ttl_s=TTL,
            )
            original = await get_research_directive(
                conn,
                directive_id,
                workspace_id=WORKSPACE_ID,
            )
            successor = await get_research_directive(
                conn,
                successor_id,
                workspace_id=WORKSPACE_ID,
            )
            assert original is not None and original.status is ResearchDirectiveStatus.SUPERSEDED
            assert successor is not None and successor.status is ResearchDirectiveStatus.CONFIRMED

            unchanged_run = await get_account_run(conn, fixture.expected_account_run_id)
            assert unchanged_run is not None and unchanged_run.research_directive == original_pin
            rehydrated = await effective_account_research_directive(
                conn,
                workspace_id=WORKSPACE_ID,
                directive_id=directive_id,
                account_id=fixture.selected_account_id,
                expected_pin=original_pin,
            )
            assert rehydrated.pin == original_pin

            with pytest.raises(Exception, match="cannot change its pinned research directive"):
                async with conn.begin_nested():
                    await conn.execute(
                        text("UPDATE account_run SET research_directive_sha256=:sha WHERE id=:id"),
                        {
                            "sha": "0" * 64,
                            "id": fixture.expected_account_run_id,
                        },
                    )

            event_types = (
                (
                    await conn.execute(
                        text(
                            "SELECT event_type::text FROM account_research_directive_event "
                            "ORDER BY occurred_at, event_id"
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert event_types.count("drafted") == 2
            assert event_types.count("confirmed") == 2
            assert event_types.count("superseded") == 1

    run_async(scenario())
