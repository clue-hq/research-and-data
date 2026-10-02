"""M8B A2 acceptance: durable direction, human gate, fresh context, and frozen run pins."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.deep import build_high_tier_resolver
from clue_api.memory_wiring import memory_assembly_factory
from clue_api.research_directive_tools import (
    DraftAccountResearchDirectiveInput,
    build_research_directive_tools,
)
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
    ICPCreatedFrom,
    MemoryDisabled,
    MemoryType,
    PhaseContext,
    ProjectPhase,
    ResearchAccountScope,
    ResearchCommitteePlan,
    ResearchDirectiveAccountOverrideBody,
    ResearchDirectiveBody,
    ResearchDirectiveId,
    ResearchDirectiveStatus,
    ResearchEffortPolicy,
    ResearchPrivacyPolicy,
    ResearchQuestion,
    ResearchSealedSelectionRef,
    ResearchSourcePolicy,
    ScopeStack,
    new_operation_id,
    new_run_id,
)
from clue_memory import WriteSeam
from clue_research.directives import (
    ResearchDirectiveInvalid,
    confirmed_directive_account_specs,
    effective_account_research_directive,
    get_research_directive,
    validate_research_directive_draft,
)
from clue_research.durable import (
    DbAccountRunStore,
    create_account_deep_launch,
    get_account_run,
    insert_account_run,
    pin_account_run_research_directive,
)
from clue_research.icp import create_icp_spec, get_icp_version
from clue_research.identity import insert_account_entity
from clue_research.membership import accounts_for_project, projects_for_accounts
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


class _DisabledMemory:
    async def submit(self, _submission: object) -> MemoryDisabled:
        return MemoryDisabled()


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
            allowed_source_keys=("sumble_teams", "sumble_people", "exa_deep"),
            preferred_source_keys=("sumble_people", "exa_deep"),
        ),
        privacy_policy=ResearchPrivacyPolicy(
            contact_profiling_allowed=False,
            contact_reveals_allowed=False,
        ),
        effort_policy=ResearchEffortPolicy(
            tier="high",
            max_depth=2,
            max_fanout=8,
            budget_cap_cents=Decimal("300"),
            budget_envelope_ref="budget:account-deep-a2-v1",
            recursion_policy_ref="recursion:account-deep-a2-v1",
            freshness_policy_ref="freshness:account-deep-a2-v1",
        ),
        exclusions=("no patient-level facts",),
    )


def test_user_instruction_limit_is_utf8_bytes_not_python_characters() -> None:
    payload = {
        "project_id": PROJECT_ID,
        "product_id": PRODUCT_ID,
        "icp_key": "deep",
        "icp_version": 1,
        "body": _body(EntityId(UUID("10000000-0000-0000-0000-000000000099"))),
        "user_instruction": "é" * 5_000,
        "source_turn_ref": "turn:multibyte",
    }
    with pytest.raises(ValidationError, match="8000-byte"):
        DraftAccountResearchDirectiveInput.model_validate(payload)


def test_unprofiled_icp_uses_only_active_registry_capabilities(tmp_path: Path) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            fixture = await seed_insight_health_account_deep_fixture(
                conn,
                pages=_pages(),
                storage=FsStorage(tmp_path / "unprofiled-source-artifacts"),
            )
            spec = await create_icp_spec(
                conn,
                workspace_id=WORKSPACE_ID,
                icp_key="unprofiled-directive",
                created_from=ICPCreatedFrom.CLIENT_EDIT,
                field_keys=(DEEP_FIELD_KEYS[2], DEEP_FIELD_KEYS[3]),
                enabled_packs=(),
                source_profile_ref={},
                activate=True,
                client_entity_id=EntityId(UUID(fixture.discovery_fixture.client_entity_id)),
                client_kb_version=fixture.discovery_fixture.client_kb_version,
                product_id=PRODUCT_ID,
            )
            body = _body(fixture.selected_account_id).model_copy(
                update={
                    "source_policy": ResearchSourcePolicy(
                        allowed_source_keys=("exa_deep",),
                        preferred_source_keys=("exa_deep",),
                    )
                }
            )

            resolved = await validate_research_directive_draft(
                conn,
                workspace_id=WORKSPACE_ID,
                project_id=PROJECT_ID,
                product_id=PRODUCT_ID,
                icp_key=spec.icp_key,
                icp_version=spec.version,
                body=body,
                overrides={},
            )

            assert resolved == (fixture.selected_account_id,)

    run_async(scenario())


def test_sealed_scope_resolves_exact_membership_and_memory_disabled_is_truthful(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path / "sealed-artifacts")
            fixture = await seed_insight_health_account_deep_fixture(
                conn,
                pages=_pages(),
                storage=storage,
            )
            cf = conn_session_factory(conn)
            registry = ToolRegistry()
            for tool in build_research_directive_tools(
                memory_write_factory=lambda _conn: _DisabledMemory(),
                conn_factory=cf,
            ):
                registry.register(tool, make_default=tool.version == "2")

            sealed_ref = ResearchSealedSelectionRef(
                discovery_batch_id=fixture.discovery_batch_id,
                discovery_seal_sha256=fixture.discovery_seal_sha256,
            ).ref
            sealed_body = _body(fixture.selected_account_id).model_copy(
                update={"account_scope": ResearchAccountScope(sealed_selection_ref=sealed_ref)}
            )
            result = await invoke_tool(
                registry,
                "draft_account_research_directive",
                {
                    "project_id": PROJECT_ID,
                    "product_id": PRODUCT_ID,
                    "icp_key": fixture.deep_icp_key,
                    "icp_version": fixture.deep_icp_version,
                    "body": sealed_body.model_dump(mode="json"),
                    "user_instruction": USER_DIRECTION,
                    "source_turn_ref": "turn:sealed-direction",
                },
                ToolContext(
                    workspace_id=WORKSPACE_ID,
                    actor="agent",
                    conn_factory=cf,
                    operation_id=new_operation_id(),
                ),
                idempotency_ttl_s=TTL,
            )
            assert result.references["memory_outcome"] == "memory_disabled"
            assert result.references["future_thread_memory_persisted"] is False
            assert result.references["preview"]["account_ids"] == [str(fixture.selected_account_id)]
            assert (
                "project_memory_disabled"
                in result.references["preview"]["unresolved_prerequisites"]
            )

            directive_id = UUID(result.references["directive_id"])
            membership = tuple(
                (
                    await conn.execute(
                        text(
                            "SELECT account_id FROM account_research_directive_account "
                            "WHERE directive_id=:directive_id"
                        ),
                        {"directive_id": directive_id},
                    )
                ).scalars()
            )
            assert membership == (UUID(str(fixture.selected_account_id)),)

            # FI-2 P1 (spec §2): directive scoping is a project claiming the account as a target,
            # so the same transaction records the project_account membership. Read it back through
            # the real reader — this is what the frontend's project target list serves.
            assert await accounts_for_project(
                conn, workspace_id=WORKSPACE_ID, project_id=PROJECT_ID
            ) == (EntityId(fixture.selected_account_id),)
            assert await projects_for_accounts(
                conn, workspace_id=WORKSPACE_ID, account_ids=[fixture.selected_account_id]
            ) == {EntityId(fixture.selected_account_id): (PROJECT_ID,)}
            assert (
                await conn.execute(
                    text(
                        "SELECT added_via FROM project_account WHERE workspace_id=:w "
                        "AND project_id=:p AND account_entity_id=:a"
                    ),
                    {
                        "w": WORKSPACE_ID,
                        "p": PROJECT_ID,
                        "a": fixture.selected_account_id,
                    },
                )
            ).scalar_one() == "directive"

            invalid_body = sealed_body.model_copy(
                update={
                    "account_scope": ResearchAccountScope(
                        sealed_selection_ref=ResearchSealedSelectionRef(
                            discovery_batch_id=fixture.discovery_batch_id,
                            discovery_seal_sha256="f" * 64,
                        ).ref
                    )
                }
            )
            with pytest.raises(PreconditionFailed) as invalid_seal:
                await invoke_tool(
                    registry,
                    "draft_account_research_directive",
                    {
                        "project_id": PROJECT_ID,
                        "product_id": PRODUCT_ID,
                        "icp_key": fixture.deep_icp_key,
                        "icp_version": fixture.deep_icp_version,
                        "body": invalid_body.model_dump(mode="json"),
                        "predecessor_id": str(directive_id),
                        "user_instruction": USER_DIRECTION,
                        "source_turn_ref": "turn:invalid-seal",
                    },
                    ToolContext(
                        workspace_id=WORKSPACE_ID,
                        actor="agent",
                        conn_factory=cf,
                        operation_id=new_operation_id(),
                    ),
                    idempotency_ttl_s=TTL,
                )
            assert invalid_seal.value.reason_codes == ("research_directive_invalid",)

            unauthorized_source_body = sealed_body.model_copy(
                update={
                    "source_policy": ResearchSourcePolicy(
                        allowed_source_keys=(
                            "sumble_teams",
                            "sumble_people",
                            "exa_deep",
                            "sumble_jobs",
                        )
                    )
                }
            )
            with pytest.raises(
                ResearchDirectiveInvalid,
                match="outside the pinned ICP field plans",
            ):
                await validate_research_directive_draft(
                    conn,
                    workspace_id=WORKSPACE_ID,
                    project_id=PROJECT_ID,
                    product_id=PRODUCT_ID,
                    icp_key=fixture.deep_icp_key,
                    icp_version=fixture.deep_icp_version,
                    body=unauthorized_source_body,
                    overrides={},
                )
            with pytest.raises(PreconditionFailed) as unauthorized_source:
                await invoke_tool(
                    registry,
                    "draft_account_research_directive",
                    {
                        "project_id": PROJECT_ID,
                        "product_id": PRODUCT_ID,
                        "icp_key": fixture.deep_icp_key,
                        "icp_version": fixture.deep_icp_version,
                        "body": unauthorized_source_body.model_dump(mode="json"),
                        "predecessor_id": str(directive_id),
                        "user_instruction": USER_DIRECTION,
                        "source_turn_ref": "turn:unauthorized-source",
                    },
                    ToolContext(
                        workspace_id=WORKSPACE_ID,
                        actor="agent",
                        conn_factory=cf,
                        operation_id=new_operation_id(),
                    ),
                    idempotency_ttl_s=TTL,
                )
            assert unauthorized_source.value.reason_codes == ("research_directive_invalid",)

    run_async(scenario())


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
                registry.register(tool, make_default=tool.version == "2")

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
            assert len(drafted.references["preview"]["hypotheses"]) == 1
            assert drafted.references["preview"]["account_overrides"][0][
                "effective_field_keys"
            ] == [DEEP_FIELD_KEYS[2], DEEP_FIELD_KEYS[4]]
            assert drafted.references["future_thread_memory_persisted"] is True
            directive_id = ResearchDirectiveId(draft_operation)

            # FI-2 P1 (spec §2): scoping the account into the directive recorded its membership of
            # the project, in the drafting transaction.
            membership_sql = text(
                "SELECT added_via, added_at FROM project_account WHERE workspace_id=:w "
                "AND project_id=:p AND account_entity_id=:a"
            )
            membership_params = {
                "w": WORKSPACE_ID,
                "p": PROJECT_ID,
                "a": fixture.selected_account_id,
            }
            first_membership = (await conn.execute(membership_sql, membership_params)).one()
            assert first_membership.added_via == "directive"

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

            with pytest.raises(PreconditionFailed) as missing_receipt:
                await invoke_tool(
                    registry,
                    "confirm_account_research_directive",
                    confirm_body,
                    ToolContext(
                        workspace_id=WORKSPACE_ID,
                        actor="human",
                        principal_kind="human",
                        actor_id="human:user-a2",
                        membership_id="wsm_user_a2",
                        conn_factory=cf,
                        operation_id=new_operation_id(),
                    ),
                    idempotency_ttl_s=TTL,
                )
            assert missing_receipt.value.reason_codes == ("trusted_human_receipt_required",)

            confirm_operation = new_operation_id()
            confirm_ctx = ToolContext(
                workspace_id=WORKSPACE_ID,
                actor="human",
                principal_kind="human",
                conn_factory=cf,
                operation_id=confirm_operation,
                actor_id="human:user-a2",
                membership_id="wsm_user_a2",
                action_ref="human-turn:deep-direction-confirm-1",
            )
            confirmed = await invoke_tool(
                registry,
                "confirm_account_research_directive",
                confirm_body,
                confirm_ctx,
                idempotency_ttl_s=TTL,
            )
            assert confirmed.references["status"] == "confirmed"
            assert confirmed.references["confirmed_by"] == "human:user-a2"
            assert confirmed.references["confirming_action_ref"] == (
                "human-turn:deep-direction-confirm-1"
            )
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
                    },
                    ToolContext(
                        workspace_id=WORKSPACE_ID,
                        actor="human",
                        principal_kind="human",
                        conn_factory=cf,
                        operation_id=confirm_operation,
                        actor_id="human:user-a2",
                        membership_id="wsm_user_a2",
                        action_ref="human-turn:different-confirmation",
                    ),
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

            deep_icp = await get_icp_version(
                conn,
                WORKSPACE_ID,
                fixture.deep_icp_key,
                fixture.deep_icp_version,
            )
            assert deep_icp is not None
            resolver = build_high_tier_resolver(spec=deep_icp, session_factory=cf)
            base_context = PhaseContext(
                project_run_id=PROJECT_RUN_ID,
                project_id=PROJECT_ID,
                brand_id=BRAND_ID,
                phase=ProjectPhase.DEEP,
                workspace_id=WORKSPACE_ID,
                icp_key=fixture.deep_icp_key,
                icp_version=fixture.deep_icp_version,
            )
            assert tuple(await resolver(base_context)) == ()
            await create_account_deep_launch(
                conn,
                workspace_id=WORKSPACE_ID,
                project_run_id=PROJECT_RUN_ID,
                directive_id=directive_id,
                account_entity_ids=(fixture.selected_account_id,),
                approved_budget_cap_cents=Decimal("300"),
                expected_estimated_cost_cents=Decimal("300"),
                created_by="human:user-a2",
                source_operation_id=new_operation_id(),
                source_action_ref="human-turn:launch-account-deep",
            )
            launched_specs = tuple(await resolver(base_context))
            assert tuple(item.entity_id for item in launched_specs) == (
                fixture.selected_account_id,
            )
            assert launched_specs[0].research_directive == specs[0].research_directive

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

            outside_account_id = await insert_account_entity(
                conn,
                canonical_name="Outside Directive Scope",
                primary_domain="outside-directive-scope.example",
                workspace_id=WORKSPACE_ID,
            )
            outside_run_id = new_run_id()
            await insert_account_run(
                conn,
                account_run_id=outside_run_id,
                project_run_id=PROJECT_RUN_ID,
                entity_id=outside_account_id,
                tier="tier_1",
            )
            outside_scope_pin = original_pin.model_copy(
                update={
                    "override_id": None,
                    "override_ref": None,
                    "override_sha256": None,
                }
            )
            with pytest.raises(Exception, match="account_run_research_directive_account_fk"):
                async with conn.begin_nested():
                    await pin_account_run_research_directive(
                        conn,
                        account_run_id=outside_run_id,
                        pin=outside_scope_pin,
                    )

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
                },
                ToolContext(
                    workspace_id=WORKSPACE_ID,
                    actor="human",
                    principal_kind="human",
                    conn_factory=cf,
                    operation_id=new_operation_id(),
                    actor_id="human:user-a2",
                    membership_id="wsm_user_a2",
                    action_ref="human-turn:deep-direction-confirm-2",
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

            # The successor re-scoped the same account: membership is first-add-wins, so the row is
            # untouched — one row, the original channel, the original added_at (not a later re-add).
            assert (await conn.execute(membership_sql, membership_params)).one() == (
                first_membership
            )

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


def test_a_fresh_draft_supersedes_an_unconfirmed_latest_draft(tmp_path: Path) -> None:
    """A draft is a proposal, not an authority — redrafting must never deadlock the lineage.

    Found live at the Slice B browser gate: a draft whose effort tier could never price its
    confirmation gate blocked every successor forever ("cannot append behind an unconfirmed
    directive"), because confirmation is the only lifecycle exit and no reject path exists. A
    fresh draft now supersedes an unconfirmed latest draft with an append-only ``superseded``
    event naming its successor; confirmed history keeps the strict predecessor rule.
    """

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
                registry.register(tool, make_default=tool.version == "2")

            def draft_request() -> dict[str, object]:
                return {
                    "project_id": PROJECT_ID,
                    "product_id": PRODUCT_ID,
                    "icp_key": fixture.deep_icp_key,
                    "icp_version": fixture.deep_icp_version,
                    "body": _body(fixture.selected_account_id).model_dump(mode="json"),
                    "account_overrides": [],
                    "user_instruction": USER_DIRECTION,
                    "source_turn_ref": "agent-turn:deep-direction-1",
                }

            first_operation = new_operation_id()
            first = await invoke_tool(
                registry,
                "draft_account_research_directive",
                draft_request(),
                ToolContext(
                    workspace_id=WORKSPACE_ID,
                    actor="agent",
                    conn_factory=cf,
                    operation_id=first_operation,
                ),
                idempotency_ttl_s=TTL,
            )
            assert first.references["status"] == "draft"

            second_operation = new_operation_id()
            second = await invoke_tool(
                registry,
                "draft_account_research_directive",
                draft_request(),
                ToolContext(
                    workspace_id=WORKSPACE_ID,
                    actor="agent",
                    conn_factory=cf,
                    operation_id=second_operation,
                ),
                idempotency_ttl_s=TTL,
            )
            assert second.references["status"] == "draft"
            assert int(second.references["version"]) == int(first.references["version"]) + 1

            rows = {
                str(row.directive_id): row
                for row in (
                    await conn.execute(
                        text(
                            "SELECT directive_id, status::text AS status, predecessor_id "
                            "FROM account_research_directive WHERE workspace_id=:w "
                            "AND project_id=:p ORDER BY version"
                        ),
                        {"w": WORKSPACE_ID, "p": PROJECT_ID},
                    )
                ).all()
            }
            first_row = rows[str(first_operation)]
            second_row = rows[str(second_operation)]
            assert first_row.status == "superseded"
            assert second_row.status == "draft"
            # The fresh draft inherits the superseded draft's own predecessor (None here, the
            # lineage's confirmed directive when one exists) — never the superseded draft itself.
            assert second_row.predecessor_id is None
            superseded_event = (
                await conn.execute(
                    text(
                        "SELECT successor_id FROM account_research_directive_event "
                        "WHERE directive_id=:d AND event_type='superseded'"
                    ),
                    {"d": first_operation},
                )
            ).one()
            assert str(superseded_event.successor_id) == str(second_operation)

    run_async(scenario())


def test_a_committee_intent_draft_without_a_capable_source_is_refused_repairably() -> None:
    """A draft stating committee intent must be executable, or committee-off must be explicit.

    Found live (directive 55c11b06 v3): a draft repair stripped ``sumble_people`` from the
    allowed sources while keeping the human's explicit cap-200/depth-2 committee plan, so the
    confirmation card showed committee discovery while the launched selection compiled zero
    committee sources and every coverage row settled ``Committee research was not selected``.
    The draft input now refuses the contradiction as an input validation error (the repairable
    species), while both honest shapes stay accepted.
    """

    from clue_api.research_directive_tools import ResearchDirectiveBodyDraftInput

    account_id = EntityId(UUID("10000000-0000-0000-0000-000000000099"))
    intent_without_source = _body(account_id).model_dump(mode="json")
    intent_without_source["source_policy"]["allowed_source_keys"] = ["exa_deep"]
    intent_without_source["source_policy"]["preferred_source_keys"] = ["exa_deep"]
    with pytest.raises(ValidationError, match="committee-capable source"):
        ResearchDirectiveBodyDraftInput.model_validate(intent_without_source)

    capable = _body(account_id).model_dump(mode="json")
    ResearchDirectiveBodyDraftInput.model_validate(capable)

    committee_off = _body(account_id).model_dump(mode="json")
    committee_off["source_policy"]["allowed_source_keys"] = ["exa_deep"]
    committee_off["source_policy"]["preferred_source_keys"] = ["exa_deep"]
    committee_off["committee_plan"] = {}
    ResearchDirectiveBodyDraftInput.model_validate(committee_off)
