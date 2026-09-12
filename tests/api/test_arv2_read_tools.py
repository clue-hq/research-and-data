"""The ARV2 read tools' toolbelt face: the skin, and what it may not do.

Offline by design — the rows themselves are proven in ``tests/arv2/test_read_tools_db.py``. What is
worth pinning here is exactly the skin: an uncomposed deployment refuses before it touches
anything, the workspace the service is asked about is the *ambient* one rather than anything the
model wrote, a domain refusal arrives typed instead of as a stack trace, and the descriptors carry
the effect/replay/pin classification a standing recipe admits.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from clue_api.arv2.read_tools import (
    Arv2ReadRefused,
    ProjectAccountsPage,
    ProjectAccountView,
    ReadProjectAccountsInput,
    ReadProjectAccountsTool,
)
from clue_core import new_operation_id
from clue_db import transaction
from clue_toolbelt import PreconditionFailed, ReplayPolicy, ToolContext, ToolEffectClass
from tests.db.conftest import run_async

WORKSPACE = "ws_arv2_read_tools"
PROJECT = "prj_arv2_read_tools"
ACCOUNT_ID = "33333333-3333-5333-8333-333333333333"


def _context() -> ToolContext:
    return ToolContext(
        workspace_id=WORKSPACE,
        actor="human",
        principal_kind="human",
        actor_id="usr_founder",
        membership_id="wsm_founder",
        action_ref=None,
        conn_factory=transaction,
        operation_id=new_operation_id(),
    )


def _page() -> ProjectAccountsPage:
    return ProjectAccountsPage(
        project_id=PROJECT,
        total=2,
        accounts=(
            ProjectAccountView(
                account_entity_id=ACCOUNT_ID,
                name="Alpha Health",
                domain="alpha.example",
                research_status="in_progress",
                refreshing=True,
                added_via="discovered",
                added_at="2026-09-12T12:00:00+00:00",
            ),
        ),
    )


@dataclass
class _FakeService:
    """Records what the tool asked for, and answers with whatever the test wants."""

    page: ProjectAccountsPage | None = None
    refusal: Arv2ReadRefused | None = None
    account_reads: list[tuple[str, str, int]] = field(default_factory=list)

    async def list_project_accounts(
        self, *, workspace_id: str, project_id: str, limit: int
    ) -> ProjectAccountsPage:
        self.account_reads.append((workspace_id, project_id, limit))
        if self.refusal is not None:
            raise self.refusal
        assert self.page is not None
        return self.page


def test_an_uncomposed_read_surface_refuses_before_it_touches_anything() -> None:
    async def scenario() -> None:
        tool = ReadProjectAccountsTool(None)
        failures = await tool.preconditions(
            ReadProjectAccountsInput(project_id=PROJECT), _context()
        )
        assert [failure.reason_code for failure in failures] == ["arv2_reads_not_composed"]

        composed = ReadProjectAccountsTool(_FakeService(page=_page()))
        assert (
            await composed.preconditions(ReadProjectAccountsInput(project_id=PROJECT), _context())
            == ()
        )

    run_async(scenario())


def test_the_read_asks_about_the_ambient_workspace_and_serves_the_page() -> None:
    async def scenario() -> None:
        service = _FakeService(page=_page())
        tool = ReadProjectAccountsTool(service)

        result = await tool.invoke(
            ReadProjectAccountsInput(project_id=PROJECT, limit=25), _context()
        )

        # The tenant is AMBIENT, never a model-authored input.
        assert service.account_reads == [(WORKSPACE, PROJECT, 25)]
        assert result.references["project_id"] == PROJECT
        assert result.references["total"] == 2
        assert result.references["accounts"] == (
            {
                "account_entity_id": ACCOUNT_ID,
                "name": "Alpha Health",
                "domain": "alpha.example",
                "research_status": "in_progress",
                "refreshing": True,
                "added_via": "discovered",
                "added_at": "2026-09-12T12:00:00+00:00",
            },
        )

    run_async(scenario())


def test_a_project_this_workspace_cannot_see_is_a_typed_refusal_not_an_empty_success() -> None:
    async def scenario() -> None:
        service = _FakeService(
            refusal=Arv2ReadRefused("project_not_found", "no project prj_x in this workspace")
        )
        tool = ReadProjectAccountsTool(service)

        with pytest.raises(PreconditionFailed) as refused:
            await tool.invoke(ReadProjectAccountsInput(project_id=PROJECT), _context())

        assert refused.value.reason_codes == ("project_not_found",)
        assert "this workspace" in refused.value.failures[0].message

    run_async(scenario())


def test_the_page_size_is_bounded_by_the_schema() -> None:
    ReadProjectAccountsInput(project_id=PROJECT, limit=200)
    with pytest.raises(ValueError):
        ReadProjectAccountsInput(project_id=PROJECT, limit=201)
    with pytest.raises(ValueError):
        ReadProjectAccountsInput(project_id=PROJECT, limit=0)
    assert ReadProjectAccountsInput(project_id=PROJECT).limit == 100


def test_the_read_declares_the_effect_and_replay_classes_the_registry_admits() -> None:
    tool = ReadProjectAccountsTool(_FakeService())

    assert tool.name == "read_project_accounts" and tool.version == "1"
    assert tool.effect_class is ToolEffectClass.READ
    assert tool.replay.policy is ReplayPolicy.EFFECT_FREE
    # ``project`` is the spine row the execution is bound to — a replay identity, not a Stage-0
    # pin (standing rule item 5); the recipe-safety audit refuses a standing address with no pin.
    assert tool.pin_requirements == ("project",)
    assert tool.descriptor.recipe_safe
