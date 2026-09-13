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
    DiscoveryCandidateView,
    DiscoveryRunView,
    ProjectAccountsPage,
    ProjectAccountView,
    ReadAccountResearchInput,
    ReadAccountResearchTool,
    ReadDiscoveryRunInput,
    ReadDiscoveryRunTool,
    ReadProjectAccountsInput,
    ReadProjectAccountsTool,
    build_arv2_read_tools,
)
from clue_core import new_operation_id
from clue_db import transaction
from clue_toolbelt import (
    PreconditionFailed,
    ReplayPolicy,
    ToolContext,
    ToolEffectClass,
    ToolInput,
)
from tests.db.conftest import run_async

WORKSPACE = "ws_arv2_read_tools"
PROJECT = "prj_arv2_read_tools"
ACCOUNT_ID = "33333333-3333-5333-8333-333333333333"
CLAIM_ID = "44444444-4444-5444-8444-444444444444"
DISCOVERY_RUN_ID = "55555555-5555-5555-8555-555555555555"


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
    discovery: DiscoveryRunView | None = None
    refusal: Arv2ReadRefused | None = None
    account_reads: list[tuple[str, str, int, str | None, int]] = field(default_factory=list)
    research_reads: list[tuple[str, str, str, str | None]] = field(default_factory=list)
    discovery_reads: list[tuple[str, str, str | None, int]] = field(default_factory=list)

    async def list_project_accounts(
        self,
        *,
        workspace_id: str,
        project_id: str,
        limit: int,
        query: str | None,
        offset: int,
    ) -> ProjectAccountsPage:
        self.account_reads.append((workspace_id, project_id, limit, query, offset))
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

    async def read_discovery_run(
        self, *, workspace_id: str, project_id: str, run_id: str | None, candidate_limit: int
    ) -> DiscoveryRunView:
        self.discovery_reads.append((workspace_id, project_id, run_id, candidate_limit))
        if self.refusal is not None:
            raise self.refusal
        assert self.discovery is not None
        return self.discovery


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
            ReadProjectAccountsInput(project_id=PROJECT, limit=25, query="zeta", offset=50),
            _context(),
        )

        # The tenant is AMBIENT, never a model-authored input; the filter and the offset are the
        # model's, and both reach the service.
        assert service.account_reads == [(WORKSPACE, PROJECT, 25, "zeta", 50)]
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
    # The filter is optional, bounded, and the offset cannot run backwards.
    defaults = ReadProjectAccountsInput(project_id=PROJECT)
    assert (defaults.query, defaults.offset) == (None, 0)
    ReadProjectAccountsInput(project_id=PROJECT, query="z" * 120, offset=1_000)
    with pytest.raises(ValueError):
        ReadProjectAccountsInput(project_id=PROJECT, query="z" * 121)
    with pytest.raises(ValueError):
        ReadProjectAccountsInput(project_id=PROJECT, offset=-1)


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
                body_text='{"intro": [], "items": [{"text": "They opened four ABM roles."}]}',
                body_truncated=False,
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
                evidence_truncated=False,
                tier=2,
                verification_status="verified",
                outreach_safe=True,
                collected_at="2026-09-12T12:00:00+00:00",
            ),
        ),
        truncated=True,
        excluded={"sensitive": 1, "unverified": 2, "outreach_unsafe": 0},
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
                "evidence_truncated": False,
                "tier": 2,
                "verification_status": "verified",
                "outreach_safe": True,
                "collected_at": "2026-09-12T12:00:00+00:00",
            },
        )
        # What the page's gate held back travels with the answer, so an agent reading three claims
        # of five knows two exist and are not servable.
        assert result.references["excluded"] == {
            "sensitive": 1,
            "unverified": 2,
            "outreach_unsafe": 0,
        }
        assert result.references["overview"] == (
            {
                "section_key": "why-now",
                "body_text": '{"intro": [], "items": [{"text": "They opened four ABM roles."}]}',
                "body_truncated": False,
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
    "code",
    [
        "account_not_found",
        "overview_not_written",
        "account_not_researched",
        "no_claims_under_prefix",
    ],
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


def test_the_account_read_never_calls_the_claims_it_serves_verified() -> None:
    """The word the model reads must be true of the filter: the reads mirror the page's gate."""

    description = ReadAccountResearchTool(_FakeService()).model_description

    assert "verified claims" not in description
    assert "the claims the account pages show" in description
    for reason in ("sensitive", "unverified tier-4", "outreach-unsafe"):
        assert reason in description


def test_the_account_read_declares_the_effect_and_replay_classes_the_registry_admits() -> None:
    tool = ReadAccountResearchTool(_FakeService())

    assert tool.name == "read_account_research" and tool.version == "1"
    assert tool.effect_class is ToolEffectClass.READ
    assert tool.replay.policy is ReplayPolicy.EFFECT_FREE
    # ``project`` is the spine row the execution is bound to — a replay identity, not a Stage-0
    # pin (standing rule item 5); the recipe-safety audit refuses a standing address with no pin.
    assert tool.pin_requirements == ("project",)
    assert tool.descriptor.recipe_safe


# -- read 3: one discovery run --------------------------------------------------------------------


def _discovery() -> DiscoveryRunView:
    return DiscoveryRunView(
        run_id=DISCOVERY_RUN_ID,
        status="completed",
        icp_key="gi-groups",
        icp_version=1,
        target_count=20,
        asked=35,
        found=13,
        verified=11,
        shown=8,
        approved=3,
        relaxed_requested=True,
        started_at="2026-09-12T12:00:00+00:00",
        finished_at="2026-09-12T12:30:00+00:00",
        candidates=(
            DiscoveryCandidateView(
                name="Alpha Health",
                domain="alpha.example",
                pass_="relaxed",
                disposition="pass",
                decision="approved",
                fit=0.9,
            ),
        ),
        candidate_total=42,
    )


def test_the_discovery_read_asks_about_the_ambient_workspace_and_serves_the_run() -> None:
    async def scenario() -> None:
        service = _FakeService(discovery=_discovery())
        tool = ReadDiscoveryRunTool(service)

        result = await tool.invoke(
            ReadDiscoveryRunInput(project_id=PROJECT, run_id=DISCOVERY_RUN_ID, candidate_limit=10),
            _context(),
        )

        # The tenant is AMBIENT, never a model-authored input.
        assert service.discovery_reads == [(WORKSPACE, PROJECT, DISCOVERY_RUN_ID, 10)]
        assert result.references["run_id"] == DISCOVERY_RUN_ID
        assert result.references["status"] == "completed"
        assert (result.references["asked"], result.references["found"]) == (35, 13)
        assert (
            result.references["verified"],
            result.references["shown"],
            result.references["approved"],
        ) == (11, 8, 3)
        assert result.references["relaxed_requested"] is True
        assert result.references["finished_at"] == "2026-09-12T12:30:00+00:00"
        # ``pass`` is the schema's word; the trailing underscore is Python's and stays in Python.
        assert result.references["candidates"] == (
            {
                "name": "Alpha Health",
                "domain": "alpha.example",
                "pass": "relaxed",
                "disposition": "pass",
                "decision": "approved",
                "fit": 0.9,
            },
        )
        # The bounded page and the whole run are two numbers, never one.
        assert result.references["candidate_total"] == 42

    run_async(scenario())


def test_an_uncomposed_discovery_read_refuses_before_it_touches_anything() -> None:
    async def scenario() -> None:
        failures = await ReadDiscoveryRunTool(None).preconditions(
            ReadDiscoveryRunInput(project_id=PROJECT), _context()
        )
        assert [failure.reason_code for failure in failures] == ["arv2_reads_not_composed"]

    run_async(scenario())


@pytest.mark.parametrize(
    "code", ["project_not_found", "discovery_run_not_found", "no_discovery_run"]
)
def test_a_missing_run_is_typed_rather_than_an_empty_success(code: str) -> None:
    """ "No run" and "not your run" are different answers, and neither is an empty run."""

    async def scenario() -> None:
        service = _FakeService(refusal=Arv2ReadRefused(code, "there is no such run here"))
        tool = ReadDiscoveryRunTool(service)

        with pytest.raises(PreconditionFailed) as refused:
            await tool.invoke(ReadDiscoveryRunInput(project_id=PROJECT), _context())

        assert refused.value.reason_codes == (code,)

    run_async(scenario())


def test_the_discovery_read_s_inputs_are_bounded_by_the_schema() -> None:
    defaults = ReadDiscoveryRunInput(project_id=PROJECT)
    # No run id means the latest run — the run "how did discovery go?" is about.
    assert (defaults.run_id, defaults.candidate_limit) == (None, 25)
    # Zero is a legitimate ask: the tallies without the company list.
    assert ReadDiscoveryRunInput(project_id=PROJECT, candidate_limit=0).candidate_limit == 0
    with pytest.raises(ValueError):
        ReadDiscoveryRunInput(project_id=PROJECT, candidate_limit=51)
    with pytest.raises(ValueError):
        ReadDiscoveryRunInput(project_id=PROJECT, candidate_limit=-1)


def test_the_discovery_read_declares_the_effect_and_replay_classes_the_registry_admits() -> None:
    tool = ReadDiscoveryRunTool(_FakeService())

    assert tool.name == "read_discovery_run" and tool.version == "1"
    assert tool.effect_class is ToolEffectClass.READ
    assert tool.replay.policy is ReplayPolicy.EFFECT_FREE
    # A read approves nothing, so the description says so where the model reads it.
    assert "approves nothing" in tool.model_description
    # And "verified" is said the way the tallies mean it, never as "everything not pending".
    assert "the verifier judged" in tool.model_description
    # ``project`` is the spine row the execution is bound to — a replay identity, not a Stage-0
    # pin (standing rule item 5); the recipe-safety audit refuses a standing address with no pin.
    assert tool.pin_requirements == ("project",)
    assert tool.descriptor.recipe_safe


# -- the registered surface ------------------------------------------------------------------------


def test_the_builder_yields_the_three_reads_and_an_uncomposed_one_refuses_by_name() -> None:
    """Registered on every deployment, composed where the lane is — the ARV2 registration posture.

    Uncomposed the three still register, so an agent that reaches for a read gets the named
    ``arv2_reads_not_composed`` refusal rather than an ``UnknownTool`` it cannot explain.
    """

    async def scenario() -> None:
        tools = build_arv2_read_tools(None)

        assert [tool.name for tool in tools] == [
            "read_project_accounts",
            "read_account_research",
            "read_discovery_run",
        ]
        inputs: dict[str, ToolInput] = {
            "read_project_accounts": ReadProjectAccountsInput(project_id=PROJECT),
            "read_account_research": ReadAccountResearchInput(account_entity_id=ACCOUNT_ID),
            "read_discovery_run": ReadDiscoveryRunInput(project_id=PROJECT),
        }
        for tool in tools:
            failures = await tool.preconditions(inputs[tool.name], _context())
            assert [failure.reason_code for failure in failures] == ["arv2_reads_not_composed"]

        # Composed, the same three are ready to read.
        service = _FakeService(page=_page(), research=_research(), discovery=_discovery())
        for tool in build_arv2_read_tools(service):
            assert await tool.preconditions(inputs[tool.name], _context()) == ()

    run_async(scenario())
