from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import pytest

from clue_agents import DomainObjectRef
from clue_api import entity_research_launch_tools as subject
from clue_api.entity_research_launch_tools import (
    LaunchSelectedAccountResearchInput,
    LaunchSelectedAccountResearchTool,
)
from clue_core import OperationId, ResearchDirectiveStatus
from clue_toolbelt import ToolContext

_TURN = UUID("10000000-0000-0000-0000-000000000001")
_RUN = UUID("10000000-0000-0000-0000-000000000002")
_DIRECTIVE = UUID("10000000-0000-0000-0000-000000000003")
_ACCOUNT_A = UUID("10000000-0000-0000-0000-000000000004")
_ACCOUNT_B = UUID("10000000-0000-0000-0000-000000000005")
_ACTION = f"turn-action:{_TURN}"


@asynccontextmanager
async def _connection():
    yield object()


class _Launcher:
    def __init__(self) -> None:
        self.calls: list[tuple[object, dict[str, object]]] = []

    async def launch(self, request: object, **kwargs: object):
        self.calls.append((request, kwargs))
        return SimpleNamespace(
            research_run_id=UUID("10000000-0000-0000-0000-000000000006"),
            fleet_state=SimpleNamespace(value="queued"),
            selected_accounts=2,
            budget_cap_cents=Decimal("50"),
            contact_research_started=False,
        )


def _context() -> ToolContext:
    return ToolContext(
        workspace_id="workspace-1",
        actor="agent",
        conn_factory=_connection,
        operation_id=OperationId(UUID("10000000-0000-0000-0000-000000000007")),
        principal_kind="service",
        actor_id="svc_execution_worker",
        action_ref=_ACTION,
    )


def _inputs(*account_ids: UUID) -> LaunchSelectedAccountResearchInput:
    return LaunchSelectedAccountResearchInput(
        project_run_id=str(_RUN),
        research_directive_id=str(_DIRECTIVE),
        account_entity_ids=tuple(str(value) for value in account_ids),
        source_turn_ref=_ACTION,
    )


def _wire_resolution(
    monkeypatch: pytest.MonkeyPatch,
    *,
    ref_type: str = "account",
    discovery_ready: bool = True,
) -> SimpleNamespace:
    directive = SimpleNamespace(
        directive_id=_DIRECTIVE,
        canonical_json_sha256="a" * 64,
        status=ResearchDirectiveStatus.DRAFT,
    )

    async def load_turn_identity(*_args: object, **_kwargs: object):
        return SimpleNamespace(
            project_id="project-1",
            submitted_by_user_id="user-1",
            submitted_via_membership_id="membership-1",
        )

    async def get_membership(*_args: object, **_kwargs: object):
        return SimpleNamespace(
            status="active",
            user_id="user-1",
            role_key="operator",
        )

    async def submission_context_refs(*_args: object, **_kwargs: object):
        return tuple(
            DomainObjectRef(
                workspace_id="workspace-1",
                object_type=ref_type,
                object_id=str(account_id),
                version=1,
            )
            for account_id in (_ACCOUNT_A, _ACCOUNT_B)
        )

    async def get_project_run(*_args: object, **_kwargs: object):
        return SimpleNamespace(
            workspace_id="workspace-1",
            project_id="project-1",
            product_id="product-1",
            icp_key="icp-1",
            icp_version=1,
        )

    async def get_directive(*_args: object, **_kwargs: object):
        return directive

    async def directive_ids(*_args: object, **_kwargs: object):
        return (_ACCOUNT_A, _ACCOUNT_B)

    async def estimate(*_args: object, **_kwargs: object):
        return SimpleNamespace(total_cents=Decimal("50"))

    async def require_discovery(*_args: object, **_kwargs: object):
        if not discovery_ready:
            raise subject.AccountResearchDiscoveryNotReady(
                "Account discovery is still in progress. Please wait and try account profiling "
                "again after discovery finishes.",
                reason_code="account_discovery_in_progress",
            )
        return SimpleNamespace(discovery_seal_sha256="b" * 64)

    monkeypatch.setattr(subject, "load_turn_identity", load_turn_identity)
    monkeypatch.setattr(subject, "get_membership", get_membership)
    monkeypatch.setattr(subject, "submission_context_refs", submission_context_refs)
    monkeypatch.setattr(subject, "get_project_run", get_project_run)
    monkeypatch.setattr(subject, "get_research_directive", get_directive)
    monkeypatch.setattr(subject, "get_latest_research_directive", get_directive)
    monkeypatch.setattr(subject, "research_directive_account_ids", directive_ids)
    monkeypatch.setattr(subject, "compute_account_research_estimate", estimate)
    monkeypatch.setattr(subject, "require_sealed_account_discovery", require_discovery)
    return directive


def test_selected_launch_refuses_widening_contacts_and_budget_gated_deployments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launcher = _Launcher()
    _wire_resolution(monkeypatch)
    tool = LaunchSelectedAccountResearchTool(
        launcher,
        budget_controls_enabled=False,
        conn_factory=_connection,
    )
    assert asyncio.run(tool.preconditions(_inputs(_ACCOUNT_A, _ACCOUNT_B), _context())) == ()

    widened = asyncio.run(
        tool.preconditions(
            _inputs(_ACCOUNT_A, _ACCOUNT_B, UUID("10000000-0000-0000-0000-000000000009")),
            _context(),
        )
    )
    assert widened[0].reason_code == "selected_launch_scope_mismatch"

    _wire_resolution(monkeypatch, ref_type="contact")
    contacts = asyncio.run(tool.preconditions(_inputs(_ACCOUNT_A, _ACCOUNT_B), _context()))
    assert contacts[0].reason_code == "selected_launch_accounts_required"

    gated = LaunchSelectedAccountResearchTool(
        launcher,
        budget_controls_enabled=True,
        conn_factory=_connection,
    )
    refused = asyncio.run(gated.preconditions(_inputs(_ACCOUNT_A, _ACCOUNT_B), _context()))
    assert refused[0].reason_code == "direct_launch_requires_budget_controls_disabled"


def test_selected_launch_confirms_as_the_human_then_launches_the_exact_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launcher = _Launcher()
    directive = _wire_resolution(monkeypatch)
    confirmations: list[dict[str, object]] = []

    async def confirm(_conn: object, **kwargs: object):
        confirmations.append(kwargs)
        directive.status = ResearchDirectiveStatus.CONFIRMED
        return directive

    monkeypatch.setattr(subject, "confirm_research_directive", confirm)
    result = asyncio.run(
        LaunchSelectedAccountResearchTool(
            launcher,
            budget_controls_enabled=False,
            conn_factory=_connection,
        ).invoke(_inputs(_ACCOUNT_A, _ACCOUNT_B), _context())
    )

    assert confirmations[0]["confirmed_by"] == "user-1"
    assert confirmations[0]["confirming_turn_ref"] == _ACTION
    request, authority = launcher.calls[0]
    assert request.account_entity_ids == (_ACCOUNT_A, _ACCOUNT_B)
    assert request.expected_estimated_cost_cents == Decimal("50")
    assert authority["actor"] == "user-1"
    assert authority["source_action_ref"] == _ACTION
    assert result.references["selected_accounts"] == 2


def test_selected_launch_tells_the_agent_to_wait_for_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launcher = _Launcher()
    _wire_resolution(monkeypatch, discovery_ready=False)

    refused = asyncio.run(
        LaunchSelectedAccountResearchTool(
            launcher,
            budget_controls_enabled=False,
            conn_factory=_connection,
        ).preconditions(_inputs(_ACCOUNT_A, _ACCOUNT_B), _context())
    )

    assert refused[0].reason_code == "account_discovery_in_progress"
    assert refused[0].message == (
        "Account discovery is still in progress. Please wait and try account profiling again "
        "after discovery finishes."
    )
    assert launcher.calls == []


def test_selected_launch_can_retry_an_already_confirmed_exact_directive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launcher = _Launcher()
    directive = _wire_resolution(monkeypatch)
    directive.status = ResearchDirectiveStatus.CONFIRMED

    async def unexpected_confirmation(*_args: object, **_kwargs: object):
        raise AssertionError("a confirmed directive must not be confirmed again")

    monkeypatch.setattr(subject, "confirm_research_directive", unexpected_confirmation)
    result = asyncio.run(
        LaunchSelectedAccountResearchTool(
            launcher,
            budget_controls_enabled=False,
            conn_factory=_connection,
        ).invoke(_inputs(_ACCOUNT_A, _ACCOUNT_B), _context())
    )

    request, authority = launcher.calls[0]
    assert request.research_directive_id == _DIRECTIVE
    assert authority["source_action_ref"] == _ACTION
    assert result.references["selected_accounts"] == 2
