"""``author_icp_document@1``: the skin over the authoring write, and what the model may not say.

Offline by design — the write itself is pinned against the real tables in
``tests/arv2/test_icp_authoring_db.py``. What is worth pinning here is exactly the skin: a
deployment without the service refuses before it touches anything, a malformed or foreign turn
reference refuses by name, the derived request carries the *ambient* workspace and the *turn's*
project, brand and human rather than model-authored ones, a domain refusal arrives as a typed
precondition failure, and ``source_turn_ref`` — platform-supplied turn authority — never appears in
the schema the model is shown.

The two durable reads of the turn binding (``load_turn_identity`` and ``get_project``) are replaced
at the module seam, so each refusal is provable without seeding a turn per case; what they return
is exactly the shape the real readers return.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

import clue_api.icp_authoring_tools as tool_module
from clue_api.arv2.icp_authoring import AuthoredIcp, IcpAuthoringRefused, IcpAuthoringRequest
from clue_api.icp_authoring_tools import (
    AuthorIcpDocumentInput,
    AuthorIcpDocumentTool,
    build_icp_authoring_tools,
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

WORKSPACE = "ws_icp_authoring_tool"
PROJECT = "prj_icp_authoring_tool"
BRAND = "brd_icp_authoring_tool"
USER = "usr_founder"
TURN_ID = UUID("55555555-5555-5555-8555-555555555555")
DOCUMENT = "---\nkind: icp-definition\nicp_key: gi-dac\n---\n\nBody.\n"


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


def _inputs(**overrides: object) -> AuthorIcpDocumentInput:
    payload: dict[str, object] = {
        "icp_key": "gi-dac",
        "document": DOCUMENT,
        "scope": "project",
        "derived_from_icp_key": "gi",
        "source_turn_ref": f"turn-action:{TURN_ID}",
    }
    payload.update(overrides)
    return AuthorIcpDocumentInput.model_validate(payload)


def _authored(**overrides: Any) -> AuthoredIcp:
    payload: dict[str, Any] = {
        "document_id": UUID("66666666-6666-5666-8666-666666666666"),
        "icp_key": "gi-dac",
        "version": 1,
        "path": "audience/icp-gi-dac.md",
        "workspace_path": "project/audience/icp-gi-dac.md",
        "status": "proposed",
        "replayed": False,
    }
    payload.update(overrides)
    return AuthoredIcp(**payload)


def _identity(*, submitted_by: str | None = USER) -> TurnIdentity:
    return TurnIdentity(
        turn_id=TURN_ID,
        workspace_id=WORKSPACE,
        project_id=PROJECT,
        thread_id="thr_icp_authoring",
        submitted_by_user_id=submitted_by,
        submitted_via_membership_id="wsm_founder",
    )


@dataclass
class _FakeService:
    """Records the request the tool derived, and answers with whatever the test wants."""

    authored: AuthoredIcp | None = None
    refusal: IcpAuthoringRefused | None = None
    requests: list[IcpAuthoringRequest] = field(default_factory=list)

    async def author(self, request: IcpAuthoringRequest) -> AuthoredIcp:
        self.requests.append(request)
        if self.refusal is not None:
            raise self.refusal
        assert self.authored is not None
        return self.authored


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


def _tool(service: Any) -> AuthorIcpDocumentTool:
    return AuthorIcpDocumentTool(service, conn_factory=_no_conn_factory)


def test_an_uncomposed_deployment_refuses_before_it_reads_anything() -> None:
    async def scenario() -> None:
        failures = await _tool(None).preconditions(_inputs(), _context())
        assert tuple(failure.reason_code for failure in failures) == ("icp_authoring_not_composed",)

    run_async(scenario())


def test_a_malformed_turn_reference_refuses_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        _bind(monkeypatch, identity=_identity())
        failures = await _tool(_FakeService(authored=_authored())).preconditions(
            _inputs(source_turn_ref="turn:not-a-ref"), _context()
        )
        assert tuple(failure.reason_code for failure in failures) == (
            "authoring_turn_ref_malformed",
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
            failures = await _tool(_FakeService(authored=_authored())).preconditions(
                _inputs(), _context()
            )
            assert tuple(failure.reason_code for failure in failures) == (
                "authoring_turn_not_found",
            )

    run_async(scenario())


def test_a_machine_turn_has_no_author_to_credit(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        _bind(monkeypatch, identity=_identity(submitted_by=None))
        failures = await _tool(_FakeService(authored=_authored())).preconditions(
            _inputs(), _context()
        )
        assert tuple(failure.reason_code for failure in failures) == (
            "authoring_addressee_missing",
        )

    run_async(scenario())


def test_the_derived_request_carries_ambient_scope_and_the_turns_own_people(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        _bind(monkeypatch, identity=_identity())
        service = _FakeService(authored=_authored())

        result = await _tool(service).invoke(_inputs(), _context())

        assert len(service.requests) == 1
        request = service.requests[0]
        # Tenancy is the context's; project, brand and the human are the turn's. Nothing here is
        # model-authored except the document, its key, its scope and its lineage key.
        assert request.workspace_id == WORKSPACE
        assert request.project_id == PROJECT
        assert request.brand_id == BRAND
        assert request.user_id == USER
        assert request.turn_id == TURN_ID
        assert request.icp_key == "gi-dac"
        assert request.document_text == DOCUMENT
        assert request.scope == "project"
        assert request.derived_from_icp_key == "gi"
        assert result.references == {
            "document_id": "66666666-6666-5666-8666-666666666666",
            "icp_key": "gi-dac",
            "version": 1,
            "path": "audience/icp-gi-dac.md",
            "workspace_path": "project/audience/icp-gi-dac.md",
            "status": "proposed",
            "replayed": False,
        }
        assert result.replayed is False

    run_async(scenario())


def test_a_domain_refusal_arrives_typed_not_as_a_stack_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        _bind(monkeypatch, identity=_identity())
        service = _FakeService(
            refusal=IcpAuthoringRefused("icp_key_taken_by_brand", "the brand already has one")
        )
        with pytest.raises(PreconditionFailed) as excinfo:
            await _tool(service).invoke(_inputs(), _context())
        assert excinfo.value.reason_codes == ("icp_key_taken_by_brand",)

    run_async(scenario())


def test_a_replayed_authoring_is_reported_as_one(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        _bind(monkeypatch, identity=_identity())
        service = _FakeService(authored=_authored(document_id=uuid4(), version=2, replayed=True))
        result = await _tool(service).invoke(_inputs(), _context())
        assert result.replayed is True and result.references["replayed"] is True

    run_async(scenario())


def test_a_brand_level_write_still_carries_the_turns_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scope decides where the row lands; it never detaches the act from the turn that made it."""

    async def scenario() -> None:
        _bind(monkeypatch, identity=_identity())
        service = _FakeService(
            authored=_authored(workspace_path="brand/knowledge/audience/icp-gi-dac.md")
        )
        await _tool(service).invoke(_inputs(scope="brand", derived_from_icp_key=None), _context())
        request = service.requests[0]
        assert request.scope == "brand"
        assert request.project_id == PROJECT
        assert request.derived_from_icp_key is None

    run_async(scenario())


def test_the_descriptor_is_a_recipe_safe_governed_write() -> None:
    (tool,) = build_icp_authoring_tools(None)
    descriptor = tool.descriptor
    assert descriptor.address == "author_icp_document@1"
    assert descriptor.effect_class is ToolEffectClass.WRITE
    assert descriptor.replay.policy is ReplayPolicy.DOMAIN_IDEMPOTENT
    assert descriptor.pin_requirements == ("project",)
    assert descriptor.recipe_safe is True
    assert descriptor.parameter_policy.safe_display_fields == (
        "icp_key",
        "scope",
        "derived_from_icp_key",
    )


def test_the_turn_reference_is_platform_supplied_and_invisible_to_the_model() -> None:
    """The model may decide *that* an ICP is ready to write; never which turn wrote it."""

    schema = AuthorIcpDocumentInput.model_json_schema()
    assert schema["properties"]["source_turn_ref"][TRUSTED_TURN_FIELD] is True, (
        "source_turn_ref must be marked engine-injected so the runtime strips it"
    )
    assert "source_turn_ref" in schema["required"]


def test_a_key_that_is_not_a_key_is_refused_by_the_schema() -> None:
    for bad in ("GI-DAC", "gi dac", "gi--dac", "", "g" * 61):
        with pytest.raises(ValidationError):
            _inputs(icp_key=bad)
    with pytest.raises(ValidationError):
        _inputs(scope="workspace")
    with pytest.raises(ValidationError):
        _inputs(document="")
