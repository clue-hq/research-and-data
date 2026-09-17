"""A design run's collected model calls become agent_model_call rows on the design leg's turn."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from clue_agents import AgentTurnRequest
from clue_agents.contracts import AgentRole, ResourceKind
from clue_api.design_leg_wiring import receipts_from_design_run
from tests.agents.conftest import artifact, constitution, resource
from tests.claimstore.conftest import migrated_db, require_claimstore_db  # noqa: F401

pytestmark = pytest.mark.usefixtures("require_claimstore_db")


@pytest.fixture
def design_turn_request() -> AgentTurnRequest:
    """One design-leg turn request, built the way ``design_leg_wiring._request`` builds it.

    Placeholder ids: ``receipts_from_design_run`` reads only the turn, execution and workspace off
    it, so nothing here needs to exist in a database.
    """
    leg_id = "leg-receipts-1"
    return AgentTurnRequest(
        turn_id=uuid4(),
        thread_id="thr-design-receipts",
        constitution=constitution(
            role=AgentRole.DESIGN,
            workspace_root_id=f"design-leg:{leg_id}",
            profile_ref=resource(ResourceKind.PROFILE, "design"),
        ),
        user_message_artifact_ref=artifact("user-message.txt"),
        requested_at=datetime.now(UTC),
    )


def _collected(sequence: int, *, status: str = "completed", role: str = "design_author") -> dict:
    now = datetime.now(UTC).isoformat()
    return {
        "run_id": str(uuid4()),
        "sequence": sequence,
        "requested_model": "x-ai/grok-4.6",
        "answering_model": "x-ai/grok-4.6" if status == "completed" else None,
        "status": status,
        "role": role,
        "input_tokens": 120,
        "output_tokens": 9,
        "cache_read_input_tokens": 40,
        "cost_cents": "0.87" if status == "completed" else None,
        "cost_source": "metered" if status == "completed" else None,
        "langfuse_trace_id": "t1",
        "langfuse_observation_id": f"o{sequence}",
        "latency_ms": 812.5,
        "error_code": None if status == "completed" else "timeout_error",
        "started_at": now,
        "completed_at": now,
    }


def test_receipts_carry_the_design_role_and_the_gateway_cost(
    design_turn_request: AgentTurnRequest,
) -> None:
    receipts = receipts_from_design_run(
        {"model_calls": [_collected(1), _collected(2, status="failed")]},
        request=design_turn_request,
    )
    assert [r.sequence for r in receipts] == [1, 2]
    assert all(r.role is AgentRole.DESIGN for r in receipts)
    assert receipts[0].cost_usd == Decimal("0.008700") and receipts[0].cost_source == "metered"
    assert receipts[0].langfuse_observation_id == "o1"
    assert receipts[1].status == "failed" and receipts[1].error_code == "timeout_error"
    assert receipts[1].cost_usd is None


def test_a_run_without_model_calls_yields_no_receipts(
    design_turn_request: AgentTurnRequest,
) -> None:
    assert receipts_from_design_run({}, request=design_turn_request) == ()
