"""Shared A1/A2/E2 confirmed-direction fixture support."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.research_directive_tools import build_research_directive_tools
from clue_core import (
    DiscoveryBatchId,
    DiscoveryPlanId,
    EntityId,
    MemoryDisabled,
    MemorySubmission,
    ProjectPhase,
    ProjectRunId,
    ResearchAccountScope,
    ResearchCommitteePlan,
    ResearchDirectiveBody,
    ResearchDirectiveId,
    ResearchEffortPolicy,
    ResearchPrivacyPolicy,
    ResearchQuestion,
    ResearchSourcePolicy,
    new_operation_id,
)
from clue_research.directives import confirmed_directive_account_specs
from clue_research.durable import (
    create_discovery_batch,
    ensure_project_run,
    get_discovery_plan,
    get_project_run,
    put_discovery_plan,
)
from clue_toolbelt import ToolContext, ToolRegistry, invoke_tool
from tests.profiling.conftest import conn_session_factory


class _DisabledMemory:
    async def submit(self, _submission: MemorySubmission) -> MemoryDisabled:
        return MemoryDisabled()


async def confirmed_account_research_direction(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
    product_id: str,
    account_id: EntityId,
    icp_key: str,
    icp_version: int,
    field_keys: Sequence[str],
    allowed_source_keys: Sequence[str] = ("sumble_teams", "sumble_people", "exa_deep"),
    questions: Sequence[ResearchQuestion] = (),
    contact_profiling_allowed: bool = False,
    contact_reveals_allowed: bool = False,
    freshness_policy_ref: str = "freshness:account-deep-test-v1",
    recursion_policy_ref: str = "recursion:account-deep-test-v1",
    predecessor_id: ResearchDirectiveId | None = None,
) -> tuple[ResearchDirectiveBody, Any]:
    """Create one real human-confirmed A2 directive on a borrowed test transaction."""

    conn_factory = conn_session_factory(conn)
    registry = ToolRegistry()
    for tool in build_research_directive_tools(
        memory_write_factory=lambda _conn: _DisabledMemory(),
        conn_factory=conn_factory,
    ):
        registry.register(tool, make_default=tool.version == "2")
    body = ResearchDirectiveBody(
        account_scope=ResearchAccountScope(explicit_account_ids=(account_id,)),
        field_keys=tuple(field_keys),
        questions=tuple(questions),
        committee_plan=ResearchCommitteePlan(
            functions=("Operations",),
            levels=("Director",),
            personas=("champion",),
            candidate_cap=4,
        ),
        source_policy=ResearchSourcePolicy(
            allowed_source_keys=tuple(allowed_source_keys),
            preferred_source_keys=("exa_deep",) if "exa_deep" in allowed_source_keys else (),
        ),
        privacy_policy=ResearchPrivacyPolicy(
            contact_profiling_allowed=contact_profiling_allowed,
            contact_reveals_allowed=contact_reveals_allowed,
        ),
        effort_policy=ResearchEffortPolicy(
            tier="high",
            max_depth=2,
            max_fanout=6,
            budget_cap_cents=Decimal(300),
            budget_envelope_ref="budget:account-deep-test-v1",
            recursion_policy_ref=recursion_policy_ref,
            freshness_policy_ref=freshness_policy_ref,
        ),
    )
    draft_operation = new_operation_id()
    drafted = await invoke_tool(
        registry,
        "draft_account_research_directive",
        {
            "project_id": project_id,
            "product_id": product_id,
            "icp_key": icp_key,
            "icp_version": icp_version,
            "body": body.model_dump(mode="json"),
            "predecessor_id": str(predecessor_id) if predecessor_id is not None else None,
            "user_instruction": (
                "Investigate account-locked referral, fax, phone, and administrative workflow "
                "friction; leave unsupported hypotheses empty."
            ),
            "source_turn_ref": "turn:account-deep-test-direction",
        },
        ToolContext(
            workspace_id=workspace_id,
            actor="agent",
            conn_factory=conn_factory,
            operation_id=draft_operation,
        ),
        idempotency_ttl_s=60,
    )
    await invoke_tool(
        registry,
        "confirm_account_research_directive",
        {
            "directive_id": str(draft_operation),
            "expected_sha256": drafted.references["canonical_json_sha256"],
        },
        ToolContext(
            workspace_id=workspace_id,
            actor="human",
            principal_kind="human",
            actor_id="human:account-deep-test",
            membership_id="wsm_account_deep_test",
            action_ref="turn:account-deep-test-confirm",
            conn_factory=conn_factory,
            operation_id=new_operation_id(),
        ),
        idempotency_ttl_s=60,
    )
    specs = await confirmed_directive_account_specs(
        conn,
        workspace_id=workspace_id,
        directive_id=ResearchDirectiveId(draft_operation),
    )
    assert len(specs) == 1 and specs[0].research_directive is not None
    return body, specs[0]


async def in_progress_discovery_run(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    template_project_run_id: ProjectRunId,
    template_discovery_plan_id: DiscoveryPlanId,
) -> ProjectRunId:
    """Create a separate valid run whose first discovery generation is still in progress."""

    template_run = await get_project_run(conn, template_project_run_id)
    template_plan = await get_discovery_plan(
        conn,
        workspace_id=workspace_id,
        plan_id=template_discovery_plan_id,
    )
    assert template_run is not None and template_plan is not None

    project_run_id = ProjectRunId(uuid4())
    await ensure_project_run(
        conn,
        project_run_id=project_run_id,
        project_id=template_run.project_id,
        workspace_id=workspace_id,
        icp_key=template_run.icp_key,
        icp_version=template_run.icp_version,
        budget_cap_cents=template_run.budget_cap_cents,
        tier_cutoffs=template_run.tier_cutoffs,
        phase=ProjectPhase.DISCOVERY,
        client_entity_id=template_run.client_entity_id,
        client_kb_version=template_run.client_kb_version,
        product_id=template_run.product_id,
        product_context_version_id=template_run.product_context_version_id,
        readiness_decision_id=template_run.readiness_decision_id,
    )
    plan_id = DiscoveryPlanId(uuid4())
    await put_discovery_plan(
        conn,
        workspace_id=workspace_id,
        plan=template_plan.plan.model_copy(
            update={
                "discovery_plan_id": plan_id,
                "project_run_id": project_run_id,
                "plan_version": 1,
            }
        ),
    )
    await create_discovery_batch(
        conn,
        workspace_id=workspace_id,
        batch_id=DiscoveryBatchId(uuid4()),
        plan_id=plan_id,
        generation=1,
    )
    return project_run_id


__all__ = ["confirmed_account_research_direction", "in_progress_discovery_run"]
