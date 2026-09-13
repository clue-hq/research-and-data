"""``write_project_document@1``: the skin over the plan write, and what the model may not say.

Offline by design — the write itself, its revision check and its replay identity are pinned against
the real tables in ``tests/arv2/test_project_documents_db.py``. What is worth pinning here is
exactly the skin: a deployment without the service refuses before it touches anything, a malformed
or foreign turn reference refuses by name, the derived request carries the *ambient* workspace and
the *turn's* project, brand and human rather than model-authored ones, a revision conflict arrives
as a typed precondition failure the author can act on, and ``source_turn_ref`` — platform-supplied
turn authority — never appears in the schema the model is shown.

The two durable reads of the turn binding (``load_turn_identity`` and ``get_project``) are replaced
at the module seam, so each refusal is provable without seeding a turn per case; what they return
is exactly the shape the real readers return.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import pytest
from pydantic import ValidationError

import clue_api.project_document_tools as tool_module
from clue_api.arv2.project_documents import (
    PLAN_WORKSPACE_PATH,
    ProjectDocumentRefused,
    ProjectPlanWrite,
    WrittenDocument,
)
from clue_api.project_document_tools import (
    WriteProjectDocumentInput,
    WriteProjectDocumentTool,
    build_project_document_tools,
)
from clue_api.turn_action import TurnIdentity
from clue_api.turn_binding import TRUSTED_TURN_FIELD
from clue_core import new_operation_id
from clue_toolbelt import (
    PreconditionFailed,
    ReplayPolicy,
    ToolContext,
    ToolEffectClass,
)
from tests.db.conftest import run_async

WORKSPACE = "ws_project_document_tool"
PROJECT = "prj_project_document_tool"
BRAND = "brd_project_document_tool"
USER = "usr_founder"
TURN_ID = UUID("77777777-7777-5777-8777-777777777777")
DOCUMENT_ID = UUID("88888888-8888-5888-8888-888888888888")
BODY = "# Plan\n\nOutcome: twenty qualified conversations by day ninety.\n"


class _NoConnection:
    """The connection the replaced readers never touch."""

    async def __aenter__(self) -> _NoConnection:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False


def _no_conn_factory() -> _NoConnection:
    return _NoConnection()


def _context(*, workspace_id: str = WORKSPACE) -> ToolContext:
    return ToolContext(
        workspace_id=workspace_id,
        actor="agent",
        principal_kind="service",
        actor_id="svc_execution_worker",
        membership_id=None,
        action_ref=f"turn-action:{TURN_ID}",
        conn_factory=_no_conn_factory,
        operation_id=new_operation_id(),
    )


def _inputs(**overrides: object) -> WriteProjectDocumentInput:
    payload: dict[str, object] = {
        "document": "plan",
        "body": BODY,
        "expected_version": 2,
        "source_turn_ref": f"turn-action:{TURN_ID}",
    }
    payload.update(overrides)
    return WriteProjectDocumentInput.model_validate(payload)


def _written(**overrides: Any) -> WrittenDocument:
    payload: dict[str, Any] = {
        "document_id": DOCUMENT_ID,
        "path": "project/plan.md",
        "version": 3,
        "workspace_path": PLAN_WORKSPACE_PATH,
        "replayed": False,
    }
    payload.update(overrides)
    return WrittenDocument(**payload)


def _identity(*, submitted_by: str | None = USER) -> TurnIdentity:
    return TurnIdentity(
        turn_id=TURN_ID,
        workspace_id=WORKSPACE,
        project_id=PROJECT,
        thread_id="thr_project_document",
        submitted_by_user_id=submitted_by,
        submitted_via_membership_id="wsm_founder",
    )


@dataclass
class _FakeService:
    """Records the request the tool derived, and answers with whatever the test wants."""

    written: WrittenDocument | None = None
    refusal: ProjectDocumentRefused | None = None
    requests: list[ProjectPlanWrite] = field(default_factory=list)

    async def write_plan(self, request: ProjectPlanWrite) -> WrittenDocument:
        self.requests.append(request)
        if self.refusal is not None:
            raise self.refusal
        assert self.written is not None
        return self.written


@dataclass(frozen=True)
class _FakeProject:
    workspace_id: str
    brand_id: str


#: The project a well-formed turn resolves to: this workspace's, with a brand to write against.
OWN_PROJECT = _FakeProject(WORKSPACE, BRAND)


def _bind(
    monkeypatch: pytest.MonkeyPatch,
    *,
    identity: TurnIdentity | None,
    project: _FakeProject | None = OWN_PROJECT,
) -> None:
    """Replace the tool's two durable reads with the rows a real turn would have produced."""

    async def _load(conn: Any, *, workspace_id: str, turn_id: UUID) -> TurnIdentity | None:
        del conn, workspace_id, turn_id
        return identity

    async def _project(conn: Any, project_id: str) -> _FakeProject | None:
        del conn, project_id
        return project

    monkeypatch.setattr(tool_module, "load_turn_identity", _load)
    monkeypatch.setattr(tool_module, "get_project", _project)


def _tool(service: Any) -> WriteProjectDocumentTool:
    return WriteProjectDocumentTool(service, conn_factory=_no_conn_factory)


def test_an_uncomposed_deployment_refuses_before_it_reads_anything() -> None:
    async def scenario() -> None:
        failures = await _tool(None).preconditions(_inputs(), _context())
        assert tuple(failure.reason_code for failure in failures) == (
            "project_documents_not_composed",
        )

    run_async(scenario())


def test_a_malformed_turn_reference_refuses_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        _bind(monkeypatch, identity=_identity())
        failures = await _tool(_FakeService(written=_written())).preconditions(
            _inputs(source_turn_ref="turn:not-a-ref"), _context()
        )
        assert tuple(failure.reason_code for failure in failures) == (
            "project_document_turn_ref_malformed",
        )

    run_async(scenario())


def test_a_turn_this_workspace_cannot_see_refuses_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """Absent and foreign are one answer: a turn whose row, or whose project, this workspace
    cannot see is indistinguishable from a turn that does not exist — no existence is leaked."""

    async def scenario() -> None:
        cases: tuple[tuple[TurnIdentity | None, _FakeProject | None], ...] = (
            (None, OWN_PROJECT),
            (_identity(), None),
            (_identity(), _FakeProject("ws_somebody_else", BRAND)),
        )
        for identity, project in cases:
            _bind(monkeypatch, identity=identity, project=project)
            failures = await _tool(_FakeService(written=_written())).preconditions(
                _inputs(), _context()
            )
            assert tuple(failure.reason_code for failure in failures) == (
                "project_document_turn_not_found",
            )

    run_async(scenario())


def test_a_machine_turn_has_no_author_to_credit(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        _bind(monkeypatch, identity=_identity(submitted_by=None))
        failures = await _tool(_FakeService(written=_written())).preconditions(
            _inputs(), _context()
        )
        assert tuple(failure.reason_code for failure in failures) == (
            "project_document_addressee_missing",
        )

    run_async(scenario())


def test_the_derived_request_carries_ambient_scope_and_the_turns_own_people(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        _bind(monkeypatch, identity=_identity())
        service = _FakeService(written=_written())

        result = await _tool(service).invoke(_inputs(), _context())

        assert len(service.requests) == 1
        request = service.requests[0]
        # Tenancy is the context's; project, brand and the human are the turn's. The only things
        # the model authored are the body and the version it says it read.
        assert request.workspace_id == WORKSPACE
        assert request.project_id == PROJECT
        assert request.brand_id == BRAND
        assert request.user_id == USER
        assert request.turn_id == TURN_ID
        assert request.body == BODY
        assert request.expected_version == 2
        assert result.references == {
            "document_id": str(DOCUMENT_ID),
            "path": "project/plan.md",
            "version": 3,
            "workspace_path": "project/plan.md",
            "replayed": False,
        }
        assert result.replayed is False

    run_async(scenario())


def test_a_first_plan_says_there_is_no_version_yet(monkeypatch: pytest.MonkeyPatch) -> None:
    """An omitted ``expected_version`` is a statement, not a missing field: *no plan exists*."""

    async def scenario() -> None:
        _bind(monkeypatch, identity=_identity())
        service = _FakeService(written=_written(version=1))
        payload = {
            "document": "plan",
            "body": BODY,
            "source_turn_ref": f"turn-action:{TURN_ID}",
        }
        await _tool(service).invoke(WriteProjectDocumentInput.model_validate(payload), _context())
        assert service.requests[0].expected_version is None

    run_async(scenario())


def test_a_revision_conflict_arrives_typed_not_as_a_stack_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The refusal the human's edit causes is the one the model must be able to act on."""

    async def scenario() -> None:
        _bind(monkeypatch, identity=_identity())
        service = _FakeService(
            refusal=ProjectDocumentRefused(
                "project_document_revision_conflict",
                "plan.md is at version 4; you expected 2.",
            )
        )
        with pytest.raises(PreconditionFailed) as excinfo:
            await _tool(service).invoke(_inputs(), _context())
        assert excinfo.value.reason_codes == ("project_document_revision_conflict",)

    run_async(scenario())


def test_a_replayed_write_is_reported_as_one(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        _bind(monkeypatch, identity=_identity())
        service = _FakeService(written=_written(replayed=True))
        result = await _tool(service).invoke(_inputs(), _context())
        assert result.replayed is True and result.references["replayed"] is True

    run_async(scenario())


def test_the_descriptor_is_a_recipe_safe_governed_write() -> None:
    (tool,) = build_project_document_tools(None)
    descriptor = tool.descriptor
    assert descriptor.address == "write_project_document@1"
    assert descriptor.effect_class is ToolEffectClass.WRITE
    assert descriptor.replay.policy is ReplayPolicy.DOMAIN_IDEMPOTENT
    assert descriptor.pin_requirements == ("project",)
    assert descriptor.recipe_safe is True
    assert descriptor.parameter_policy.safe_display_fields == ("document", "expected_version")


def test_the_turn_reference_is_platform_supplied_and_invisible_to_the_model() -> None:
    """The model may decide *that* the plan is ready; never which turn wrote it."""

    schema = WriteProjectDocumentInput.model_json_schema()
    assert schema["properties"]["source_turn_ref"][TRUSTED_TURN_FIELD] is True, (
        "source_turn_ref must be marked engine-injected so the runtime strips it"
    )
    assert "source_turn_ref" in schema["required"]


def test_a_body_or_a_version_that_is_not_one_is_refused_by_the_schema() -> None:
    with pytest.raises(ValidationError):
        _inputs(body="")
    with pytest.raises(ValidationError):
        _inputs(body="x" * 200_001)
    for bad in (0, -1):
        with pytest.raises(ValidationError):
            _inputs(expected_version=bad)
    # There is exactly one project document the agent writes, and it is named.
    with pytest.raises(ValidationError):
        _inputs(document="brief")
