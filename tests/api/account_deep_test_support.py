"""Shared A1/A2/E2 confirmed-direction fixture support."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.research_directive_tools import build_research_directive_tools
from clue_core import (
    EntityId,
    MemoryDisabled,
    MemorySubmission,
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
            recursion_policy_ref="recursion:account-deep-test-v1",
            freshness_policy_ref="freshness:account-deep-test-v1",
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


__all__ = ["confirmed_account_research_direction"]
