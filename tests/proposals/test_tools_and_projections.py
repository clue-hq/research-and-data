"""C2 lane-local tool envelopes and workspace-scoped projection cards."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.proposal_tools import (
    DecideFieldProposalInput,
    DecideFieldProposalTool,
    DecideSourceProposalInput,
    DecideSourceProposalTool,
    ProposalScopeInput,
    ProposeFieldInput,
    ProposeFieldTool,
    ProposeSourceInput,
    ProposeSourceTool,
)
from clue_core import new_operation_id
from clue_core.proposals import ProposalStatus
from clue_db import ConnFactory
from clue_projections.proposals import field_proposals, source_proposals
from clue_research.proposals import ProposalDecision
from clue_spine import create_brand
from clue_toolbelt import ToolContext
from tests._workspace import seed_workspace
from tests.proposals.conftest import rollback_conn, run_async
from tests.proposals.test_proposals import _field_payload, _source_payload

pytestmark = pytest.mark.usefixtures("require_proposals_db")


def _factory(conn: AsyncConnection) -> ConnFactory:
    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncConnection]:
        yield conn

    return factory


def test_four_tools_return_refs_and_enforce_human_decisions() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            workspace_id = await seed_workspace(conn, "proposal-tools")
            brand = await create_brand(conn, workspace_id=workspace_id, name="Tools brand")
            # PC-C8 task 1.4: `brand_id`/`project_id` are trusted top-level authority; the
            # nested scope is the model-authored narrowing only.
            scope = ProposalScopeInput()
            factory = _factory(conn)
            agent = ToolContext(
                workspace_id=workspace_id,
                actor="agent",
                conn_factory=factory,
                operation_id=new_operation_id(),
            )
            human = ToolContext(
                workspace_id=workspace_id,
                actor="human",
                conn_factory=factory,
                operation_id=new_operation_id(),
            )

            propose_field_tool = ProposeFieldTool()
            propose_field_input = ProposeFieldInput(
                brand_id=brand.brand_id,
                scope=scope,
                payload=_field_payload("account.partner_density"),
                proposed_by_ref="thread:tools",
            )
            assert await propose_field_tool.preconditions(propose_field_input, agent) == ()
            field_result = await propose_field_tool.invoke(propose_field_input, agent)
            field_id = str(field_result.references["field_proposal_id"])
            assert set(field_result.references) == {
                "field_proposal_id",
                "field_key",
                "status",
            }

            decide_field_tool = DecideFieldProposalTool()
            decide_field_input = DecideFieldProposalInput(
                field_proposal_id=field_id,
                decision=ProposalDecision.REJECT,
                reason="Not required in the shared registry.",
            )
            failures = await decide_field_tool.preconditions(decide_field_input, agent)
            assert tuple(item.reason_code for item in failures) == (
                "insufficient_proposal_authority",
            )
            assert await decide_field_tool.preconditions(decide_field_input, human) == ()
            field_decision = await decide_field_tool.invoke(decide_field_input, human)
            assert field_decision.references["status"] == ProposalStatus.REJECTED.value

            source_payload = _source_payload("credentialed_registry").model_copy(
                update={
                    "manifest": _source_payload("credentialed_registry").manifest.model_copy(
                        update={
                            "auth_ref": "CLUE_CREDENTIAL_REGISTRY_TOKEN",
                            "rate_limit": {"requests_per_minute": 5},
                        }
                    )
                }
            )
            propose_source_tool = ProposeSourceTool()
            propose_source_input = ProposeSourceInput(
                brand_id=brand.brand_id, scope=scope, payload=source_payload
            )
            assert await propose_source_tool.preconditions(propose_source_input, agent) == ()
            source_result = await propose_source_tool.invoke(propose_source_input, agent)
            source_id = str(source_result.references["source_proposal_id"])

            decide_source_tool = DecideSourceProposalTool()
            decide_source_input = DecideSourceProposalInput(
                source_proposal_id=source_id,
                decision=ProposalDecision.PROMOTE,
                reason="Credential handling and provenance reviewed.",
                assigned_tier=3,
            )
            failures = await decide_source_tool.preconditions(decide_source_input, agent)
            assert tuple(item.reason_code for item in failures) == (
                "insufficient_proposal_authority",
            )
            failures = await decide_source_tool.preconditions(decide_source_input, human)
            assert tuple(item.reason_code for item in failures) == ("credential_setup_required",)
            ready_source_tool = DecideSourceProposalTool(
                credential_ready=lambda auth_ref: auth_ref == "CLUE_CREDENTIAL_REGISTRY_TOKEN"
            )
            assert await ready_source_tool.preconditions(decide_source_input, human) == ()
            source_decision = await ready_source_tool.invoke(decide_source_input, human)
            assert source_decision.references["status"] == ProposalStatus.PROMOTED.value

            field_cards = await field_proposals(conn_factory=factory, workspace_id=workspace_id)
            source_cards = await source_proposals(conn_factory=factory, workspace_id=workspace_id)
            assert len(field_cards) == 1
            assert field_cards[0].field_proposal_id == field_id
            assert field_cards[0].status is ProposalStatus.REJECTED
            assert len(source_cards) == 1
            assert source_cards[0].source_proposal_id == source_id
            assert source_cards[0].requires_credentials
            assert source_cards[0].assigned_tier == 3
            serialized = source_cards[0].model_dump()
            assert "auth_ref" not in serialized
            assert "rate_limit" not in serialized

            # Another workspace gets an empty projection, not an existence leak.
            assert await field_proposals(conn_factory=factory, workspace_id="other-workspace") == ()
            assert (
                await source_proposals(conn_factory=factory, workspace_id="other-workspace") == ()
            )

    run_async(scenario())
