from datetime import UTC, datetime

import pytest

from clue_api.auth_tool_context import (
    require_human_authority,
    tool_context_for_principal,
    tool_context_for_service,
)
from clue_auth import RequestPrincipal, ServicePrincipal
from clue_core import new_operation_id
from clue_db import transaction
from clue_toolbelt import ToolContext, ToolInput


class _DomainToolInput(ToolInput):
    value: int


def _human() -> RequestPrincipal:
    return RequestPrincipal(
        user_id="usr_internal",
        membership_id="wsm_internal",
        workspace_id="ws_internal",
        role_key="operator",
        permissions=frozenset({"thread.write"}),
        authenticated_at=datetime.now(UTC),
    )


def _service() -> ServicePrincipal:
    return ServicePrincipal(
        service_id="svc_agent_turn_worker",
        workspace_id="ws_internal",
        permissions=frozenset({"thread.write"}),
        authenticated_at=datetime.now(UTC),
    )


def test_human_principal_becomes_internal_ambient_tool_authority() -> None:
    context = tool_context_for_principal(
        _human(),
        conn_factory=transaction,
        operation_id=new_operation_id(),
        action_ref="turn-action:turn_internal",
    )

    assert context.actor == "human"
    assert context.principal_kind == "human"
    assert context.actor_id == "usr_internal"
    assert context.membership_id == "wsm_internal"
    assert context.workspace_id == "ws_internal"
    assert context.action_ref == "turn-action:turn_internal"


def test_service_principal_cannot_impersonate_a_human_membership() -> None:
    context = tool_context_for_service(
        _service(),
        conn_factory=transaction,
        operation_id=new_operation_id(),
        action_ref="turn-action:approved_turn",
    )

    assert context.actor == "agent"
    assert context.principal_kind == "service"
    assert context.actor_id == "svc_agent_turn_worker"
    assert context.membership_id is None
    assert context.action_ref == "turn-action:approved_turn"

    with pytest.raises(ValueError, match="service tool context cannot carry"):
        ToolContext(
            workspace_id="ws_internal",
            actor="agent",
            conn_factory=transaction,
            operation_id=new_operation_id(),
            principal_kind="service",
            actor_id="svc_agent_turn_worker",
            membership_id="wsm_internal",
        )


def test_authenticated_service_action_ref_cannot_pass_a_human_only_gate() -> None:
    service = tool_context_for_service(
        _service(),
        conn_factory=transaction,
        operation_id=new_operation_id(),
        action_ref="turn-action:approved_turn",
    )
    human = tool_context_for_principal(
        _human(),
        conn_factory=transaction,
        operation_id=new_operation_id(),
        action_ref="turn-action:approved_turn",
    )

    assert require_human_authority(service, action_ref_required=True)[0].reason_code == (
        "trusted_human_receipt_required"
    )
    assert require_human_authority(human, action_ref_required=True) == ()


def test_human_and_service_principal_actor_classes_are_not_interchangeable() -> None:
    with pytest.raises(ValueError, match="human principal may only invoke"):
        ToolContext(
            workspace_id="ws_internal",
            actor="agent",
            conn_factory=transaction,
            operation_id=new_operation_id(),
            principal_kind="human",
            actor_id="usr_internal",
            membership_id="wsm_internal",
        )
    with pytest.raises(ValueError, match="service principal may only invoke"):
        ToolContext(
            workspace_id="ws_internal",
            actor="human",
            conn_factory=transaction,
            operation_id=new_operation_id(),
            principal_kind="service",
            actor_id="svc_agent_turn_worker",
        )


@pytest.mark.parametrize("field", ["actor_id", "membership_id", "action_ref"])
def test_authority_cannot_be_added_to_model_visible_tool_inputs(field: str) -> None:
    with pytest.raises(ValueError):
        _DomainToolInput.model_validate({"value": 1, field: "client-controlled"})
