"""Seam 1's toolbelt face: the three ARV2 research tools (launch account, launch people, read).

Offline by design — the tools are a thin, typed skin over :class:`Arv2LaunchService`, and what is
worth pinning here is exactly the skin: an uncomposed lane refuses before it touches anything, a
launch with no captured human action refuses, the mapped request carries the ambient workspace and
actor rather than model-authored ones, and a domain refusal arrives as a *typed* precondition
failure (seam 1 §1.3) instead of a stack trace.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from clue_api.arv2.account_research_launch import (
    Arv2LaunchReceipt,
    Arv2LaunchRefused,
    Arv2LaunchRequest,
    Arv2PersonLaunchRequest,
    Arv2RunView,
    LaunchArv2AccountResearchInput,
    LaunchArv2AccountResearchTool,
    LaunchArv2PersonResearchInput,
    LaunchArv2PersonResearchTool,
    ReadArv2AccountResearchRunInput,
    ReadArv2AccountResearchRunTool,
    build_arv2_launch_tools,
)
from clue_api.arv2.account_research_store import JobRow, RunRow
from clue_api.arv2.discovery_launch import (
    Arv2DiscoveryReceipt,
    Arv2DiscoveryRefused,
    Arv2DiscoveryRequest,
    LaunchArv2DiscoveryInput,
    LaunchArv2DiscoveryTool,
    LaunchArv2DiscoveryV2Input,
    LaunchArv2DiscoveryV2Tool,
    build_arv2_discovery_tools,
)
from clue_core import new_operation_id
from clue_db import transaction
from clue_toolbelt import PreconditionFailed, ReplayPolicy, ToolContext, ToolEffectClass
from tests.db.conftest import run_async

WORKSPACE = "ws_arv2_answer_key"
PROJECT = "prj_arv2_answer_key"
RUN_ID = UUID("11111111-1111-5111-8111-111111111111")
JOB_ID = UUID("22222222-2222-5222-8222-222222222222")
ACCOUNT_ID = UUID("33333333-3333-5333-8333-333333333333")
CONTACT_ID = UUID("44444444-4444-5444-8444-444444444444")
SHA = "a" * 64


def _context(*, action_ref: str | None = "turn:arv2-launch-confirmed") -> ToolContext:
    return ToolContext(
        workspace_id=WORKSPACE,
        actor="human",
        principal_kind="human",
        actor_id="usr_founder",
        membership_id="wsm_founder",
        action_ref=action_ref,
        conn_factory=transaction,
        operation_id=new_operation_id(),
    )


def _inputs(**overrides: object) -> LaunchArv2AccountResearchInput:
    payload: dict[str, object] = {
        "project_id": PROJECT,
        "account_entity_ids": (str(ACCOUNT_ID),),
        "icp_artifact_key": f"{WORKSPACE}/{SHA}",
        "icp_artifact_sha256": SHA,
        "product_selection_version": 1,
        "effort": "full",
        "committee_cap": 5,
        "directive_text": "focus on the hiring signals",
    }
    payload.update(overrides)
    return LaunchArv2AccountResearchInput.model_validate(payload)


def _run_row() -> RunRow:
    return RunRow(
        run_id=RUN_ID,
        workspace_id=WORKSPACE,
        project_id=PROJECT,
        brand_id="brd_arv2",
        project_run_id=uuid4(),
        icp_artifact_key=f"{WORKSPACE}/{SHA}",
        icp_artifact_sha256=SHA,
        icp_key="clue-abm-buyers",
        icp_version=1,
        product_selection_version=1,
        effort="full",
        committee_cap=5,
        directive_text="focus on the hiring signals",
        profile_ref="agent-profile:arv2-account:v1",
        profile_sha256="b" * 64,
        requested_by_user_id="usr_founder",
        request_sha256="c" * 64,
        status="in_progress",
    )


def _job_row() -> JobRow:
    return JobRow(
        job_id=JOB_ID,
        run_id=RUN_ID,
        workspace_id=WORKSPACE,
        account_entity_id=ACCOUNT_ID,
        subject_type="account",
        subject_entity_id=None,
        profile_sha256="b" * 64,
        status="needs_review",
        attempt=1,
        started_at=None,
        finished_at=None,
        finalization=None,
        failure_code="profile_pin_mismatch",
        failure_message="the profile bytes moved",
        model_rounds=3,
        tool_calls=7,
        cost_usd=Decimal("1.5"),
        credits=Decimal(0),
        media_seconds=0,
    )


@dataclass
class _FakeService:
    """Records what the tool asked for, and answers with whatever the test wants."""

    receipt: Arv2LaunchReceipt | None = None
    refusal: Arv2LaunchRefused | None = None
    view: Arv2RunView | None = None
    requests: list[Arv2LaunchRequest] = field(default_factory=list)
    person_requests: list[Arv2PersonLaunchRequest] = field(default_factory=list)
    reads: list[tuple[str, UUID]] = field(default_factory=list)

    async def launch(self, request: Arv2LaunchRequest) -> Arv2LaunchReceipt:
        self.requests.append(request)
        if self.refusal is not None:
            raise self.refusal
        assert self.receipt is not None
        return self.receipt

    async def launch_person(self, request: Arv2PersonLaunchRequest) -> Arv2LaunchReceipt:
        self.person_requests.append(request)
        if self.refusal is not None:
            raise self.refusal
        assert self.receipt is not None
        return self.receipt

    async def read_run(self, *, workspace_id: str, run_id: UUID) -> Arv2RunView | None:
        self.reads.append((workspace_id, run_id))
        return self.view


def test_an_uncomposed_lane_and_an_unwitnessed_launch_both_refuse_before_anything() -> None:
    async def scenario() -> None:
        uncomposed = LaunchArv2AccountResearchTool(None)
        failures = await uncomposed.preconditions(_inputs(), _context())
        assert [failure.reason_code for failure in failures] == [
            "arv2_account_research_not_composed"
        ]

        read = ReadArv2AccountResearchRunTool(None)
        read_failures = await read.preconditions(
            ReadArv2AccountResearchRunInput(run_id=str(RUN_ID)), _context()
        )
        assert [failure.reason_code for failure in read_failures] == [
            "arv2_account_research_not_composed"
        ]

        service = _FakeService(receipt=Arv2LaunchReceipt(RUN_ID, (JOB_ID,), False, uuid4()))
        composed = LaunchArv2AccountResearchTool(service)
        assert await composed.preconditions(_inputs(), _context()) == ()
        unwitnessed = await composed.preconditions(_inputs(), _context(action_ref=None))
        assert [failure.reason_code for failure in unwitnessed] == ["launch_action_ref_missing"]
        # Nothing reached the service on either refusal.
        assert service.requests == []

    run_async(scenario())


def test_invoke_maps_the_ambient_context_into_the_request_and_returns_the_receipt() -> None:
    async def scenario() -> None:
        project_run_id = uuid4()
        service = _FakeService(receipt=Arv2LaunchReceipt(RUN_ID, (JOB_ID,), True, project_run_id))
        tool = LaunchArv2AccountResearchTool(service)

        result = await tool.invoke(_inputs(), _context())

        request = service.requests[0]
        # The workspace and the requesting human are AMBIENT, never model-authored inputs.
        assert request.workspace_id == WORKSPACE
        assert request.requested_by_user_id == "usr_founder"
        assert request.project_id == PROJECT
        assert request.account_entity_ids == (ACCOUNT_ID,)
        assert request.icp_artifact_sha256 == SHA
        assert request.product_selection_version == 1
        assert request.effort == "full" and request.committee_cap == 5
        assert result.references == {
            "run_id": str(RUN_ID),
            "job_ids": [str(JOB_ID)],
            "replayed": True,
        }
        assert result.replayed is True

    run_async(scenario())


def test_a_domain_refusal_arrives_as_a_typed_precondition_failure() -> None:
    async def scenario() -> None:
        service = _FakeService(
            refusal=Arv2LaunchRefused("icp_digest_mismatch", "the ICP artifact bytes moved")
        )
        tool = LaunchArv2AccountResearchTool(service)

        with pytest.raises(PreconditionFailed) as refused:
            await tool.invoke(_inputs(), _context())

        assert refused.value.reason_codes == ("icp_digest_mismatch",)
        assert "bytes moved" in refused.value.failures[0].message

    run_async(scenario())


def test_the_read_tool_serves_the_run_row_and_its_job_states() -> None:
    async def scenario() -> None:
        service = _FakeService(view=Arv2RunView(run=_run_row(), jobs=(_job_row(),)))
        tool = ReadArv2AccountResearchRunTool(service)

        result = await tool.invoke(ReadArv2AccountResearchRunInput(run_id=str(RUN_ID)), _context())

        assert service.reads == [(WORKSPACE, RUN_ID)]
        assert result.references["run_id"] == str(RUN_ID)
        assert result.references["status"] == "in_progress"
        assert result.references["jobs"] == [
            {
                "job_id": str(JOB_ID),
                "account_entity_id": str(ACCOUNT_ID),
                "status": "needs_review",
                "failure_code": "profile_pin_mismatch",
            }
        ]

    run_async(scenario())


def test_a_run_this_workspace_cannot_see_is_a_typed_refusal_not_an_empty_success() -> None:
    async def scenario() -> None:
        tool = ReadArv2AccountResearchRunTool(_FakeService(view=None))
        with pytest.raises(PreconditionFailed) as missing:
            await tool.invoke(ReadArv2AccountResearchRunInput(run_id=str(RUN_ID)), _context())
        assert missing.value.reason_codes == ("arv2_account_research_run_not_found",)

    run_async(scenario())


def test_the_three_tools_declare_the_effect_and_replay_classes_the_registry_admits() -> None:
    launch, launch_person, read = build_arv2_launch_tools(_FakeService())

    assert launch.name == "launch_arv2_account_research" and launch.version == "1"
    assert launch.effect_class is ToolEffectClass.SPEND
    assert launch.replay.policy is ReplayPolicy.DOMAIN_IDEMPOTENT
    assert launch_person.name == "launch_arv2_person_research" and launch_person.version == "1"
    assert launch_person.effect_class is ToolEffectClass.SPEND
    assert launch_person.replay.policy is ReplayPolicy.DOMAIN_IDEMPOTENT
    assert read.name == "read_arv2_account_research_run" and read.version == "1"
    assert read.effect_class is ToolEffectClass.READ
    assert read.replay.policy is ReplayPolicy.EFFECT_FREE
    # Standing rule item 5: none of the three requires a *Stage-0* pin — the launches pin their
    # subjects + ICP artifact + selection version, and a Stage-0 pin here would resurrect the old
    # machinery. ``project`` is not that: it is the spine row the execution is bound to, a replay
    # identity, and the recipe-safety audit refuses a standing address with no pin at all.
    assert launch.pin_requirements == ("project",)
    assert launch_person.pin_requirements == ("project",)
    assert read.pin_requirements == ("project",)
    assert launch.descriptor.recipe_safe and read.descriptor.recipe_safe
    assert launch_person.descriptor.recipe_safe


# -- the person launch (R3 task 6) -----------------------------------------------------------------


def _person_inputs(**overrides: object) -> LaunchArv2PersonResearchInput:
    payload: dict[str, object] = {
        "project_id": PROJECT,
        "contact_entity_ids": (str(CONTACT_ID),),
        "directive_text": "open with the podcast",
    }
    payload.update(overrides)
    return LaunchArv2PersonResearchInput.model_validate(payload)


def test_the_person_launch_refuses_uncomposed_and_unwitnessed_before_anything() -> None:
    async def scenario() -> None:
        uncomposed = LaunchArv2PersonResearchTool(None)
        failures = await uncomposed.preconditions(_person_inputs(), _context())
        assert [failure.reason_code for failure in failures] == [
            "arv2_account_research_not_composed"
        ]

        service = _FakeService(receipt=Arv2LaunchReceipt(RUN_ID, (JOB_ID,), False, uuid4()))
        composed = LaunchArv2PersonResearchTool(service)
        assert await composed.preconditions(_person_inputs(), _context()) == ()
        unwitnessed = await composed.preconditions(_person_inputs(), _context(action_ref=None))
        assert [failure.reason_code for failure in unwitnessed] == ["launch_action_ref_missing"]
        # Researching a named person is a SPEND on that person: nothing reached the service.
        assert service.person_requests == []

    run_async(scenario())


def test_the_person_launch_maps_the_ambient_context_and_returns_the_receipt() -> None:
    async def scenario() -> None:
        service = _FakeService(receipt=Arv2LaunchReceipt(RUN_ID, (JOB_ID,), True, uuid4()))
        tool = LaunchArv2PersonResearchTool(service)

        result = await tool.invoke(_person_inputs(), _context())

        request = service.person_requests[0]
        assert request.workspace_id == WORKSPACE
        assert request.requested_by_user_id == "usr_founder"
        assert request.project_id == PROJECT
        assert request.contact_entity_ids == (CONTACT_ID,)
        assert request.directive_text == "open with the podcast"
        assert result.references == {
            "run_id": str(RUN_ID),
            "job_ids": [str(JOB_ID)],
            "replayed": True,
        }
        assert result.replayed is True

    run_async(scenario())


def test_a_person_launch_refusal_arrives_as_a_typed_precondition_failure() -> None:
    async def scenario() -> None:
        service = _FakeService(
            refusal=Arv2LaunchRefused(
                f"contact_not_found:{CONTACT_ID}", "no such contact in this workspace"
            )
        )
        tool = LaunchArv2PersonResearchTool(service)

        with pytest.raises(PreconditionFailed) as refused:
            await tool.invoke(_person_inputs(), _context())

        assert refused.value.reason_codes == (f"contact_not_found:{CONTACT_ID}",)
        assert "no such contact" in refused.value.failures[0].message

    run_async(scenario())


# -- the discovery launch (R4 task 5) -------------------------------------------------------------


@dataclass
class _FakeDiscoveryService:
    """Records what the discovery tool asked for, and answers with whatever the test wants."""

    receipt: Arv2DiscoveryReceipt | None = None
    refusal: Arv2DiscoveryRefused | None = None
    requests: list[Arv2DiscoveryRequest] = field(default_factory=list)

    async def launch(self, request: Arv2DiscoveryRequest) -> Arv2DiscoveryReceipt:
        self.requests.append(request)
        if self.refusal is not None:
            raise self.refusal
        assert self.receipt is not None
        return self.receipt


#: The brief the Head of ABM writes (spec 2026-09-30 §3), as the tool's inputs carry it.
_BRIEF: dict[str, object] = {
    "source": "websets",
    "query": "Companies of <kind> that run <activity>.",
    "criteria": ["The company runs <activity>."],
    "gates": [
        {"key": "is_buyer", "rule": "Runs <activity>.", "test": "Its site.", "role": "must"},
        {"key": "sells_it", "rule": "Sells <product>.", "test": "Its pages.", "role": "must_not"},
    ],
}


def _discovery_inputs(**overrides: object) -> LaunchArv2DiscoveryV2Input:
    payload: dict[str, object] = {"project_id": PROJECT, "target_count": 20, **_BRIEF}
    payload.update(overrides)
    return LaunchArv2DiscoveryV2Input.model_validate(payload)


def _discovery_receipt(*, replayed: bool = False) -> Arv2DiscoveryReceipt:
    return Arv2DiscoveryReceipt(
        run_id=RUN_ID,
        replayed=replayed,
        project_run_id=uuid4(),
        workspace_id=WORKSPACE,
        to_enqueue=not replayed,
    )


def test_the_retired_discovery_launch_refuses_every_call_toward_v2() -> None:
    """``@1`` stays registered for replay and refuses by name, composed or not."""

    async def scenario() -> None:
        service = _FakeDiscoveryService(receipt=_discovery_receipt())
        v1_inputs = LaunchArv2DiscoveryInput.model_validate({"project_id": PROJECT})
        for tool in (LaunchArv2DiscoveryTool(None), LaunchArv2DiscoveryTool(service)):
            failures = await tool.preconditions(v1_inputs, _context())
            assert [failure.reason_code for failure in failures] == ["discovery_tool_retired"]
            assert "launch_arv2_discovery@2" in failures[0].message
        with pytest.raises(PreconditionFailed) as refused:
            await LaunchArv2DiscoveryTool(service).invoke(v1_inputs, _context())
        assert refused.value.reason_codes == ("discovery_tool_retired",)
        assert service.requests == []

    run_async(scenario())


def test_the_discovery_launch_refuses_uncomposed_and_unwitnessed_before_anything() -> None:
    async def scenario() -> None:
        uncomposed = LaunchArv2DiscoveryV2Tool(None)
        failures = await uncomposed.preconditions(_discovery_inputs(), _context())
        assert [failure.reason_code for failure in failures] == ["arv2_discovery_not_composed"]

        service = _FakeDiscoveryService(receipt=_discovery_receipt())
        composed = LaunchArv2DiscoveryV2Tool(service)
        assert await composed.preconditions(_discovery_inputs(), _context()) == ()
        unwitnessed = await composed.preconditions(_discovery_inputs(), _context(action_ref=None))
        assert [failure.reason_code for failure in unwitnessed] == ["launch_action_ref_missing"]
        # Discovery buys a long list: nothing reached the service on either refusal.
        assert service.requests == []

    run_async(scenario())


def test_the_discovery_launch_maps_the_ambient_context_and_returns_the_receipt() -> None:
    async def scenario() -> None:
        service = _FakeDiscoveryService(receipt=_discovery_receipt(replayed=True))
        tool = LaunchArv2DiscoveryV2Tool(service)

        result = await tool.invoke(_discovery_inputs(target_count=40), _context())

        request = service.requests[0]
        # The workspace and the requesting human are AMBIENT, never model-authored inputs.
        assert request.workspace_id == WORKSPACE
        assert request.requested_by_user_id == "usr_founder"
        assert request.project_id == PROJECT
        assert request.target_count == 40
        # The search IS model-authored: the brief the Head of ABM wrote rides the request whole.
        assert request.brief is not None
        assert request.brief.model_dump(mode="json") == _BRIEF
        # The approving user action IS the ask's identity (ruling 2026-09-28): a new action is a
        # new discovery, the same action retried is the same one.
        assert request.request_key == "turn:arv2-launch-confirmed"
        assert result.version == "2"
        assert result.references == {"run_id": str(RUN_ID), "replayed": True}
        assert result.replayed is True

    run_async(scenario())


def test_a_brief_that_breaks_the_structure_is_refused_by_name_before_the_launch() -> None:
    async def scenario() -> None:
        service = _FakeDiscoveryService(receipt=_discovery_receipt())
        tool = LaunchArv2DiscoveryV2Tool(service)
        gate = _BRIEF["gates"][0]  # type: ignore[index]
        with pytest.raises(PreconditionFailed) as refused:
            await tool.invoke(_discovery_inputs(gates=[gate, gate]), _context())
        assert refused.value.reason_codes == ("brief_invalid",)
        assert "unique" in refused.value.failures[0].message
        assert service.requests == []

    run_async(scenario())


def test_a_discovery_refusal_arrives_as_a_typed_precondition_failure() -> None:
    async def scenario() -> None:
        service = _FakeDiscoveryService(
            refusal=Arv2DiscoveryRefused(
                "discovery_in_progress", "discovery run r is already running in conversation thr_1"
            )
        )
        tool = LaunchArv2DiscoveryV2Tool(service)

        with pytest.raises(PreconditionFailed) as refused:
            await tool.invoke(_discovery_inputs(), _context())

        assert refused.value.reason_codes == ("discovery_in_progress",)
        assert "thr_1" in refused.value.failures[0].message

    run_async(scenario())


def test_the_discovery_tool_declares_the_effect_and_replay_classes_the_registry_admits() -> None:
    retired, launch = build_arv2_discovery_tools(_FakeDiscoveryService())

    assert (retired.name, retired.version) == ("launch_arv2_discovery", "1")
    assert launch.name == "launch_arv2_discovery" and launch.version == "2"
    for tool in (retired, launch):
        assert tool.effect_class is ToolEffectClass.SPEND
        assert tool.replay.policy is ReplayPolicy.DOMAIN_IDEMPOTENT
        # ``project`` is the spine row the execution is bound to — a replay identity, not a
        # Stage-0 pin (standing rule item 5) — and the recipe-safety audit refuses a standing
        # address with no pin at all.
        assert tool.pin_requirements == ("project",)
        assert tool.descriptor.recipe_safe
    # The input model bounds the ask; the launch refuses `target_count_invalid` for callers with
    # no model in front of them (the CLI, a direct call).
    with pytest.raises(ValidationError):
        _discovery_inputs(target_count=0)
    with pytest.raises(ValidationError):
        _discovery_inputs(target_count=501)
    with pytest.raises(ValidationError):
        _discovery_inputs(source="google")


# -- the operator's CLI (R2-close task 5) ---------------------------------------------------------


def _cli_module() -> Any:
    """The launcher script, imported by path — ``scripts/`` is not an importable package."""
    path = Path(__file__).resolve().parents[2] / "scripts" / "launch_arv2_account_research.py"
    spec = importlib.util.spec_from_file_location("arv2_launch_cli", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_cli_prints_a_launch_refusal_as_a_refusal_rather_than_a_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An operator whose ICP is malformed reads one line, not a stack trace."""
    module = _cli_module()

    async def refuse(args: Any) -> dict[str, Any]:
        del args
        raise Arv2LaunchRefused("icp_front_matter_invalid", "the ICP names no version")

    monkeypatch.setattr(module, "_args", lambda: object())
    monkeypatch.setattr(module, "_run", refuse)

    with pytest.raises(SystemExit) as exited:
        module.main()

    assert str(exited.value) == ("refused: icp_front_matter_invalid: the ICP names no version")


def test_the_person_cli_prints_a_launch_refusal_as_a_refusal_rather_than_a_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An operator who named somebody this workspace does not hold reads one line."""
    path = Path(__file__).resolve().parents[2] / "scripts" / "launch_arv2_person_research.py"
    spec = importlib.util.spec_from_file_location("arv2_person_launch_cli", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    async def refuse(args: Any) -> dict[str, Any]:
        del args
        raise Arv2LaunchRefused(f"contact_not_found:{CONTACT_ID}", "resolve the person first")

    monkeypatch.setattr(module, "_args", lambda: object())
    monkeypatch.setattr(module, "_run", refuse)

    with pytest.raises(SystemExit) as exited:
        module.main()

    assert str(exited.value) == (
        f"refused: contact_not_found:{CONTACT_ID}: resolve the person first"
    )


def test_the_discovery_cli_prints_a_launch_refusal_as_a_refusal_rather_than_a_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An operator whose project pinned no ICP reads one line, not a stack trace."""
    path = Path(__file__).resolve().parents[2] / "scripts" / "launch_arv2_discovery.py"
    spec = importlib.util.spec_from_file_location("arv2_discovery_cli", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    async def refuse(args: Any) -> dict[str, Any]:
        del args
        raise Arv2DiscoveryRefused("project_icp_not_pinned", "confirm an ICP at the gate first")

    monkeypatch.setattr(module, "_args", lambda: object())
    monkeypatch.setattr(module, "_run", refuse)

    with pytest.raises(SystemExit) as exited:
        module.main()

    assert str(exited.value) == "refused: project_icp_not_pinned: confirm an ICP at the gate first"
