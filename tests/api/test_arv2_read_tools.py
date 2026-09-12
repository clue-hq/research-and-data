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
    AccountClaimView,
    AccountOverviewSection,
    AccountResearch,
    Arv2ReadRefused,
    ProjectAccountsPage,
    ProjectAccountView,
    ReadAccountResearchInput,
    ReadAccountResearchTool,
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
CLAIM_ID = "44444444-4444-5444-8444-444444444444"


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
    research: AccountResearch | None = None
    refusal: Arv2ReadRefused | None = None
    account_reads: list[tuple[str, str, int]] = field(default_factory=list)
    research_reads: list[tuple[str, str, str, str | None]] = field(default_factory=list)

    async def list_project_accounts(
        self, *, workspace_id: str, project_id: str, limit: int
    ) -> ProjectAccountsPage:
        self.account_reads.append((workspace_id, project_id, limit))
        if self.refusal is not None:
            raise self.refusal
        assert self.page is not None
        return self.page

    async def read_account_research(
        self,
        *,
        workspace_id: str,
        account_entity_id: str,
        section: str,
        field_prefix: str | None,
    ) -> AccountResearch:
        self.research_reads.append((workspace_id, account_entity_id, section, field_prefix))
        if self.refusal is not None:
            raise self.refusal
        assert self.research is not None
        return self.research


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


# -- read 2: one account's research ---------------------------------------------------------------


def _research(section: str = "overview") -> AccountResearch:
    return AccountResearch(
        account_entity_id=ACCOUNT_ID,
        account_name="Alpha Health",
        section=section,
        overview=(
            AccountOverviewSection(
                section_key="why-now",
                body={"intro": [], "items": [{"text": "They opened four ABM roles."}]},
                cited_claim_ids=(CLAIM_ID,),
                generated_at="2026-09-12T12:00:00+00:00",
            ),
        ),
        claims=(
            AccountClaimView(
                claim_id=CLAIM_ID,
                field_key="account.open_requisitions",
                value=[{"title": "ABM Manager"}],
                source_url="https://alpha.example/careers",
                evidence="ABM Manager, Marketing",
                tier=2,
                collected_at="2026-09-12T12:00:00+00:00",
            ),
        ),
        truncated=True,
    )


def test_the_account_read_asks_about_the_ambient_workspace_and_serves_both_shapes() -> None:
    async def scenario() -> None:
        service = _FakeService(research=_research("claims"))
        tool = ReadAccountResearchTool(service)

        result = await tool.invoke(
            ReadAccountResearchInput(
                account_entity_id=ACCOUNT_ID, section="claims", field_prefix="account.resonance"
            ),
            _context(),
        )

        # The tenant is AMBIENT, never a model-authored input.
        assert service.research_reads == [(WORKSPACE, ACCOUNT_ID, "claims", "account.resonance")]
        assert result.references["account_name"] == "Alpha Health"
        assert result.references["section"] == "claims"
        assert result.references["truncated"] is True
        assert result.references["claims"] == (
            {
                "claim_id": CLAIM_ID,
                "field_key": "account.open_requisitions",
                "value": [{"title": "ABM Manager"}],
                "source_url": "https://alpha.example/careers",
                "evidence": "ABM Manager, Marketing",
                "tier": 2,
                "collected_at": "2026-09-12T12:00:00+00:00",
            },
        )
        assert result.references["overview"] == (
            {
                "section_key": "why-now",
                "body": {"intro": [], "items": [{"text": "They opened four ABM roles."}]},
                "cited_claim_ids": (CLAIM_ID,),
                "generated_at": "2026-09-12T12:00:00+00:00",
            },
        )

    run_async(scenario())


def test_an_uncomposed_account_read_refuses_before_it_touches_anything() -> None:
    async def scenario() -> None:
        failures = await ReadAccountResearchTool(None).preconditions(
            ReadAccountResearchInput(account_entity_id=ACCOUNT_ID), _context()
        )
        assert [failure.reason_code for failure in failures] == ["arv2_reads_not_composed"]

    run_async(scenario())


@pytest.mark.parametrize(
    "code", ["account_not_found", "overview_not_written", "account_not_researched"]
)
def test_every_missing_prerequisite_is_typed_rather_than_an_empty_success(code: str) -> None:
    """An empty overview or an empty claim list would be a *statement* about the account."""

    async def scenario() -> None:
        service = _FakeService(refusal=Arv2ReadRefused(code, "nothing written yet"))
        tool = ReadAccountResearchTool(service)

        with pytest.raises(PreconditionFailed) as refused:
            await tool.invoke(ReadAccountResearchInput(account_entity_id=ACCOUNT_ID), _context())

        assert refused.value.reason_codes == (code,)

    run_async(scenario())


def test_the_account_read_s_inputs_are_bounded_by_the_schema() -> None:
    assert ReadAccountResearchInput(account_entity_id=ACCOUNT_ID).section == "overview"
    assert ReadAccountResearchInput(account_entity_id=ACCOUNT_ID).field_prefix is None
    with pytest.raises(ValueError):
        # A third section is not a section: the model picks from the two the read knows.
        ReadAccountResearchInput.model_validate(
            {"account_entity_id": ACCOUNT_ID, "section": "everything"}
        )
    with pytest.raises(ValueError):
        ReadAccountResearchInput(account_entity_id=ACCOUNT_ID, field_prefix="a" * 81)


def test_the_account_read_declares_the_effect_and_replay_classes_the_registry_admits() -> None:
    tool = ReadAccountResearchTool(_FakeService())

    assert tool.name == "read_account_research" and tool.version == "1"
    assert tool.effect_class is ToolEffectClass.READ
    assert tool.replay.policy is ReplayPolicy.EFFECT_FREE
    # ``project`` is the spine row the execution is bound to — a replay identity, not a Stage-0
    # pin (standing rule item 5); the recipe-safety audit refuses a standing address with no pin.
    assert tool.pin_requirements == ("project",)
    assert tool.descriptor.recipe_safe
