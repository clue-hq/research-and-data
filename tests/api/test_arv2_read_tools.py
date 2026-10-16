"""The ARV2 read tools' toolbelt face: the skin, and what it may not do.

Offline by design — the rows themselves are proven in ``tests/arv2/test_read_tools_db.py``. What is
worth pinning here is exactly the skin: an uncomposed deployment refuses before it touches
anything, the workspace the service is asked about is the *ambient* one rather than anything the
model wrote, a domain refusal arrives typed instead of as a stack trace, and the descriptors carry
the effect/replay/pin classification a standing recipe admits.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import pytest

from clue_agents.manual import tool_manual_link
from clue_api.arv2.read_tools import (
    MAX_CANDIDATES,
    MAX_CITED_CLAIMS,
    MAX_CLAIMS,
    READ_REFERENCES_BUDGET_BYTES,
    AccountClaimView,
    AccountOverviewSection,
    AccountResearch,
    Arv2ReadRefused,
    CitedClaimsPage,
    ClaimsQueryPage,
    DiscoveryCandidateV3View,
    DiscoveryCandidateView,
    DiscoveryRunView,
    ProjectAccountsPage,
    ProjectAccountView,
    ReadAccountResearchInput,
    ReadAccountResearchOutput,
    ReadAccountResearchTool,
    ReadAccountResearchV2Input,
    ReadAccountResearchV2Tool,
    ReadCitedClaimsInput,
    ReadCitedClaimsOutput,
    ReadCitedClaimsTool,
    ReadClaimsInput,
    ReadClaimsOutput,
    ReadClaimsTool,
    ReadDiscoveryRunInput,
    ReadDiscoveryRunOutput,
    ReadDiscoveryRunTool,
    ReadDiscoveryRunV2Input,
    ReadDiscoveryRunV2Output,
    ReadDiscoveryRunV2Tool,
    ReadDiscoveryRunV3Input,
    ReadDiscoveryRunV3Output,
    ReadDiscoveryRunV3Tool,
    ReadProjectAccountsInput,
    ReadProjectAccountsTool,
    build_arv2_paged_read_tools,
    build_arv2_read_tools,
    receipt_bytes,
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
from clue_toolbelt.runner import validate_tool_output_references
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
    #: ``(workspace, account, section, prefix, offset, limit)`` — the window is recorded because
    #: it is the whole difference between the two registered versions of this read.
    research_reads: list[tuple[str, str, str, str | None, int, int]] = field(default_factory=list)
    #: ``(workspace, project, run, offset, limit)``, for the same reason.
    discovery_reads: list[tuple[str, str, str | None, int, int]] = field(default_factory=list)
    #: Whether each discovery read asked for the excluded companies apart (``@3``) or inline.
    discovery_excluded_apart: list[bool] = field(default_factory=list)
    claims: ClaimsQueryPage | None = None
    #: ``(workspace, entity, prefix, tier, status, since, offset, limit)`` — the filters are the
    #: whole point of this read, so the fake records every one of them.
    claims_reads: list[
        tuple[str, str, str | None, int | None, str | None, str | None, int, int]
    ] = field(default_factory=list)
    cited: CitedClaimsPage | None = None
    #: ``(workspace, entity, claim ids)`` — the ambient workspace and the exact ids asked for.
    cited_reads: list[tuple[str, str, tuple[str, ...]]] = field(default_factory=list)

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
        offset: int,
        limit: int,
        project_id: str | None = None,
    ) -> AccountResearch:
        del project_id
        self.research_reads.append(
            (workspace_id, account_entity_id, section, field_prefix, offset, limit)
        )
        if self.refusal is not None:
            raise self.refusal
        assert self.research is not None
        return self.research

    async def read_discovery_run(
        self,
        *,
        workspace_id: str,
        project_id: str,
        run_id: str | None,
        offset: int,
        limit: int,
        excluded_apart: bool,
    ) -> DiscoveryRunView:
        self.discovery_reads.append((workspace_id, project_id, run_id, offset, limit))
        self.discovery_excluded_apart.append(excluded_apart)
        if self.refusal is not None:
            raise self.refusal
        assert self.discovery is not None
        return self.discovery

    async def read_claims(
        self,
        *,
        workspace_id: str,
        entity_id: str,
        field_prefix: str | None,
        tier: int | None,
        verification_status: str | None,
        since: str | None,
        offset: int,
        limit: int,
    ) -> ClaimsQueryPage:
        self.claims_reads.append(
            (
                workspace_id,
                entity_id,
                field_prefix,
                tier,
                verification_status,
                since,
                offset,
                limit,
            )
        )
        if self.refusal is not None:
            raise self.refusal
        assert self.claims is not None
        return self.claims

    async def read_cited_claims(
        self, *, workspace_id: str, entity_id: str, claim_ids: Sequence[str]
    ) -> CitedClaimsPage:
        self.cited_reads.append((workspace_id, entity_id, tuple(claim_ids)))
        if self.refusal is not None:
            raise self.refusal
        assert self.cited is not None
        return self.cited


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
        offset=0,
        next_offset=1,
        prefixes={},
    )


def test_the_account_read_asks_about_the_ambient_workspace_and_serves_both_shapes() -> None:
    async def scenario() -> None:
        service = _FakeService(research=_research("claims"))
        tool = ReadAccountResearchTool(service)

        result = await tool.invoke(
            ReadAccountResearchInput(
                account_entity_id=ACCOUNT_ID,
                section="claims",
                field_prefix="account.resonance",
                offset=40,
            ),
            _context(),
        )

        # The tenant is AMBIENT, never a model-authored input; the prefix and the page the model
        # asked to continue from are the model's, and both reach the service.
        # ``@1`` has no ``limit`` of its own, so it asks the seam for the substrate's ceiling and
        # is bounded by the receipt's byte budget alone — what it did before ``@2`` existed.
        assert service.research_reads == [
            (WORKSPACE, ACCOUNT_ID, "claims", "account.resonance", 40, MAX_CLAIMS)
        ]
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


def test_the_account_read_s_result_fits_the_governed_receipt() -> None:
    """The bound is measured where the runtime measures it: on the canonical references."""

    async def scenario() -> None:
        claims = tuple(
            AccountClaimView(
                claim_id=f"{index:08d}-4444-5444-8444-444444444444",
                field_key="account.open_requisitions",
                value={"title": f"Role {index}"},
                source_url="https://alpha.example/jobs",
                evidence="x" * 240,
                evidence_truncated=True,
                tier=3,
                verification_status="unverified",
                outreach_safe=True,
                collected_at="2026-09-12T08:00:00+00:00",
            )
            for index in range(40)
        )
        # The page the service would serve out of those forty: every leading claim that fits the
        # budget. Stated as "the largest prefix within the budget" rather than by calling the
        # service's own helper, so the test is a second opinion about the bound and not an echo.
        fitted = max(
            count
            for count in range(1, len(claims) + 1)
            if receipt_bytes([claim.model_dump() for claim in claims[:count]])
            <= READ_REFERENCES_BUDGET_BYTES
        )
        assert fitted < len(claims)  # the fixture is the over-budget account, as intended
        big = AccountResearch(
            account_entity_id=ACCOUNT_ID,
            account_name="Alpha Health",
            section="claims",
            overview=(),
            claims=claims[:fitted],
            truncated=True,
            excluded={"sensitive": 0, "unverified": 0, "outreach_unsafe": 0},
            offset=0,
            next_offset=fitted,
            prefixes={"account.open_requisitions": 40},
        )
        tool = ReadAccountResearchTool(_FakeService(research=big))
        result = await tool.invoke(
            ReadAccountResearchInput(account_entity_id=ACCOUNT_ID, section="claims"), _context()
        )
        canonical = validate_tool_output_references(ReadAccountResearchOutput, result.references)
        # The service is trusted to have bounded the page; the tool adds < 1 KiB of envelope.
        assert receipt_bytes(canonical) < 16_384

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


def test_the_paged_account_read_asks_for_the_page_the_model_chose() -> None:
    """``@2``'s whole difference from ``@1``: the model says how many claims it wants."""

    async def scenario() -> None:
        service = _FakeService(research=_research("claims"))
        tool = ReadAccountResearchV2Tool(service)

        result = await tool.invoke(
            ReadAccountResearchV2Input(
                account_entity_id=ACCOUNT_ID,
                section="claims",
                field_prefix="account.resonance",
                offset=40,
                limit=5,
            ),
            _context(),
        )

        assert service.research_reads == [
            (WORKSPACE, ACCOUNT_ID, "claims", "account.resonance", 40, 5)
        ]
        # The answer is ``@1``'s answer: the output shape did not move, only the ask.
        assert result.references["section"] == "claims"
        assert (result.references["offset"], result.references["next_offset"]) == (0, 1)
        assert result.references["excluded"] == {
            "sensitive": 1,
            "unverified": 2,
            "outreach_unsafe": 0,
        }

    run_async(scenario())


def test_the_paged_account_read_s_limit_is_bounded_by_the_schema() -> None:
    defaults = ReadAccountResearchV2Input(account_entity_id=ACCOUNT_ID)
    # Forty is a page a model can read and quote from, not the substrate's own ceiling.
    assert (defaults.limit, defaults.offset, defaults.section) == (40, 0, "overview")
    assert ReadAccountResearchV2Input(account_entity_id=ACCOUNT_ID, limit=MAX_CLAIMS).limit == 120
    with pytest.raises(ValueError):
        # Past the substrate's cap is a page the read could never serve.
        ReadAccountResearchV2Input(account_entity_id=ACCOUNT_ID, limit=MAX_CLAIMS + 1)
    with pytest.raises(ValueError):
        # Zero claims is not a read; the tallies-only shape belongs to the discovery run.
        ReadAccountResearchV2Input(account_entity_id=ACCOUNT_ID, limit=0)
    # And ``@1``'s own contract did NOT learn the field: a promoted profile pins its digest.
    assert "limit" not in ReadAccountResearchInput.model_fields
    assert "limit" in ReadAccountResearchV2Input.model_fields
    with pytest.raises(ValueError):
        # ``extra="forbid"``: the frozen version refuses the new key loudly rather than ignoring
        # it and serving a page the caller did not ask for.
        ReadAccountResearchInput.model_validate({"account_entity_id": ACCOUNT_ID, "limit": 5})


def test_the_two_account_read_versions_are_two_addresses_of_one_read() -> None:
    """``@2`` inherits everything that is not the input: same effect class, same replay proof,
    same pins, same output contract — which is why the profile can move to it as a page size and
    not as a new capability."""

    first = ReadAccountResearchTool(_FakeService())
    second = ReadAccountResearchV2Tool(_FakeService())

    assert (first.name, first.version) == ("read_account_research", "1")
    assert (second.name, second.version) == ("read_account_research", "2")
    assert second.effect_class is first.effect_class
    assert second.replay == first.replay
    assert second.pin_requirements == first.pin_requirements
    assert second.descriptor.recipe_safe
    # The output schema is byte-identical; only the input moved, which is the entire reason the
    # paging could not be added at ``@1``.
    assert second.descriptor.output_schema_sha256 == first.descriptor.output_schema_sha256
    assert second.descriptor.input_schema_sha256 != first.descriptor.input_schema_sha256
    # The model is told the field exists, and told a short page can still have a next one.
    assert "limit" in second.model_description
    assert "next_offset" in second.model_description


def test_the_account_read_never_calls_the_claims_it_serves_verified() -> None:
    """The word the model reads must be true of the filter: the reads mirror the page's gate."""

    description = ReadAccountResearchTool(_FakeService()).model_description

    assert "verified claims" not in description
    assert "the claims the account pages show" in description
    # Case-folded: the sentence naming the held-back classes opens the description's third
    # sentence, so "Sensitive" is capitalised there — the word is what matters, not its case.
    for reason in ("sensitive", "unverified tier-4", "outreach-unsafe"):
        assert reason in description.lower()


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
        offset=0,
        next_offset=25,
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
        # ``@1`` reads one page from the top: that is what ``candidate_limit`` always meant.
        assert service.discovery_reads == [(WORKSPACE, PROJECT, DISCOVERY_RUN_ID, 0, 10)]
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


def test_the_discovery_read_s_result_passes_the_runner_s_own_output_validation() -> None:
    """The live defect: the tool dumped ``pass`` by alias and the runner re-validated the JSON
    against a model that only accepted ``pass_`` — every call was a ToolContractViolation."""

    async def scenario() -> None:
        tool = ReadDiscoveryRunTool(_FakeService(discovery=_discovery()))
        result = await tool.invoke(
            ReadDiscoveryRunInput(project_id=PROJECT, run_id=DISCOVERY_RUN_ID, candidate_limit=10),
            _context(),
        )

        canonical = validate_tool_output_references(ReadDiscoveryRunOutput, result.references)

        assert canonical["candidates"] == [
            {
                "name": "Alpha Health",
                "domain": "alpha.example",
                "pass": "relaxed",
                "disposition": "pass",
                "decision": "approved",
                "fit": 0.9,
            }
        ]

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


def test_the_paged_discovery_read_serves_the_window_and_names_the_next_one() -> None:
    """``@1`` cut a sixty-company run at twenty-five and named no way back to the rest."""

    async def scenario() -> None:
        service = _FakeService(discovery=_discovery())
        tool = ReadDiscoveryRunV2Tool(service)

        result = await tool.invoke(
            ReadDiscoveryRunV2Input(project_id=PROJECT, run_id=DISCOVERY_RUN_ID, limit=25),
            _context(),
        )

        assert service.discovery_reads == [(WORKSPACE, PROJECT, DISCOVERY_RUN_ID, 0, 25)]
        # Where this page sits, and where the next one starts.
        assert (result.references["offset"], result.references["next_offset"]) == (0, 25)
        # The whole run, on every page, exactly as ``@1`` reported it.
        assert result.references["candidate_total"] == 42
        assert result.references["verified"] == 11
        # ``pass`` is still the schema's word on the way out.
        assert result.references["candidates"][0]["pass"] == "relaxed"
        # And the runner's own re-validation accepts what the tool serialized.
        canonical = validate_tool_output_references(ReadDiscoveryRunV2Output, result.references)
        assert (canonical["offset"], canonical["next_offset"]) == (0, 25)

    run_async(scenario())


def test_the_paged_discovery_read_s_inputs_are_bounded_by_the_schema() -> None:
    defaults = ReadDiscoveryRunV2Input(project_id=PROJECT)
    # No run id still means the latest run; the page default is ``@1``'s own page size.
    assert (defaults.run_id, defaults.offset, defaults.limit) == (None, 0, 25)
    assert ReadDiscoveryRunV2Input(project_id=PROJECT, offset=50).offset == 50
    with pytest.raises(ValueError):
        ReadDiscoveryRunV2Input(project_id=PROJECT, limit=MAX_CANDIDATES + 1)
    with pytest.raises(ValueError):
        # A page of nothing cannot page: ``@1``'s ``candidate_limit=0`` tallies-only shape is the
        # one thing ``@2`` does not inherit, because every page already reports the tallies.
        ReadDiscoveryRunV2Input(project_id=PROJECT, limit=0)
    with pytest.raises(ValueError):
        ReadDiscoveryRunV2Input(project_id=PROJECT, offset=-1)
    # ``@1``'s frozen contract keeps its own input, and gains nothing.
    assert "candidate_limit" in ReadDiscoveryRunInput.model_fields
    assert "candidate_limit" not in ReadDiscoveryRunV2Input.model_fields
    assert {"offset", "limit"} <= set(ReadDiscoveryRunV2Input.model_fields)
    assert not {"offset", "limit"} & set(ReadDiscoveryRunInput.model_fields)
    for frozen, extra in (
        (ReadDiscoveryRunInput, {"offset": 25}),
        (ReadDiscoveryRunV2Input, {"candidate_limit": 25}),
    ):
        with pytest.raises(ValueError):
            # Neither contract quietly accepts the other's word for a page.
            frozen.model_validate({"project_id": PROJECT, **extra})


def test_the_two_discovery_read_versions_are_two_addresses_of_one_read() -> None:
    first = ReadDiscoveryRunTool(_FakeService())
    second = ReadDiscoveryRunV2Tool(_FakeService())

    assert (first.name, first.version) == ("read_discovery_run", "1")
    assert (second.name, second.version) == ("read_discovery_run", "2")
    assert second.effect_class is first.effect_class
    assert second.replay == first.replay
    assert second.pin_requirements == first.pin_requirements
    assert second.descriptor.recipe_safe
    # Both schemas moved here — ``@2`` also reports where the page sits — which is exactly why
    # this is a new address and not an edit.
    assert second.descriptor.input_schema_sha256 != first.descriptor.input_schema_sha256
    assert second.descriptor.output_schema_sha256 != first.descriptor.output_schema_sha256
    # ``@1``'s sentences survive: a read approves nothing, and "verified" keeps its meaning.
    assert "approves nothing" in second.model_description
    assert "the verifier judged" in second.model_description


def _discovery_v3() -> DiscoveryRunView:
    """A run launched from the agent's brief, ended short, with two companies a gate excluded."""

    summary = {
        "asked": 20,
        "added": 1,
        "excluded": 2,
        "unclear": 0,
        "excluded_by": [{"gate": "sells_it", "role": "must_not", "count": 2, "example": "Rival"}],
        "criteria_rates": [],
        "searches": 4,
        "end_reason": "round_cap",
        "spend_usd": "1.25",
    }
    return DiscoveryRunView(
        run_id=DISCOVERY_RUN_ID,
        status="completed",
        icp_key="gi-groups",
        icp_version=1,
        target_count=20,
        asked=40,
        found=3,
        verified=3,
        shown=1,
        approved=0,
        relaxed_requested=False,
        started_at="2026-09-30T12:00:00+00:00",
        finished_at="2026-09-30T12:30:00+00:00",
        candidates=(
            DiscoveryCandidateV3View(
                name="Alpha Health",
                domain="alpha.example",
                pass_="round",
                disposition="pass",
                decision=None,
                fit=0.9,
                excluded_by_gate=None,
            ),
        ),
        candidate_total=1,
        offset=0,
        next_offset=None,
        source="search",
        end_reason="round_cap",
        summary=summary,
        excluded=(
            DiscoveryCandidateV3View(
                name="Rival",
                domain="rival.example",
                pass_="round",
                disposition="excluded",
                decision=None,
                fit=None,
                excluded_by_gate="sells_it",
            ),
            DiscoveryCandidateV3View(
                name="Rival Two",
                domain="rival-two.example",
                pass_="round",
                disposition="excluded",
                decision=None,
                fit=None,
                excluded_by_gate="sells_it",
            ),
        ),
        excluded_total=2,
    )


def test_the_brief_discovery_read_serves_the_summary_the_end_and_the_exclusions_apart() -> None:
    """``@3``: the run's summary and why it ended, and the companies a gate excluded in their own
    list — never among the candidates, which stay the companies the human may be shown."""

    async def scenario() -> None:
        service = _FakeService(discovery=_discovery_v3())
        tool = ReadDiscoveryRunV3Tool(service)

        result = await tool.invoke(
            ReadDiscoveryRunV3Input(project_id=PROJECT, run_id=DISCOVERY_RUN_ID, limit=25),
            _context(),
        )

        assert service.discovery_reads == [(WORKSPACE, PROJECT, DISCOVERY_RUN_ID, 0, 25)]
        # ``@3`` asks the substrate for the exclusions apart; nothing else does.
        assert service.discovery_excluded_apart == [True]
        refs = result.references
        assert (refs["source"], refs["end_reason"]) == ("search", "round_cap")
        assert refs["summary"]["excluded_by"][0]["gate"] == "sells_it"
        assert refs["summary"]["spend_usd"] == "1.25"
        assert [c["name"] for c in refs["candidates"]] == ["Alpha Health"]
        assert refs["candidates"][0]["excluded_by_gate"] is None
        assert [(c["name"], c["excluded_by_gate"]) for c in refs["excluded"]] == [
            ("Rival", "sells_it"),
            ("Rival Two", "sells_it"),
        ]
        assert refs["excluded_total"] == 2
        # ``pass`` stays the schema's word in both lists.
        assert refs["excluded"][0]["pass"] == "round"
        # The brief the agent wrote is its own input, not something the read serves back.
        assert "brief" not in refs and "brief_json" not in refs
        canonical = validate_tool_output_references(ReadDiscoveryRunV3Output, refs)
        assert canonical["excluded"][1]["excluded_by_gate"] == "sells_it"

    run_async(scenario())


def test_the_frozen_discovery_reads_still_ask_for_the_exclusions_inline() -> None:
    """``@1``/``@2`` keep their pinned contract: excluded companies are listed where they always
    were (with their disposition), because their output schema has nowhere else to put them."""

    async def scenario() -> None:
        service = _FakeService(discovery=_discovery())
        await ReadDiscoveryRunTool(service).invoke(
            ReadDiscoveryRunInput(project_id=PROJECT), _context()
        )
        await ReadDiscoveryRunV2Tool(service).invoke(
            ReadDiscoveryRunV2Input(project_id=PROJECT), _context()
        )
        assert service.discovery_excluded_apart == [False, False]

    run_async(scenario())


def test_the_brief_discovery_read_is_a_third_address_of_the_same_read() -> None:
    second = ReadDiscoveryRunV2Tool(_FakeService())
    third = ReadDiscoveryRunV3Tool(_FakeService())

    assert (third.name, third.version) == ("read_discovery_run", "3")
    assert third.effect_class is second.effect_class
    assert third.replay == second.replay
    assert third.pin_requirements == second.pin_requirements
    assert third.descriptor.recipe_safe
    # Same paging input; a new output — which is why it is a new address.
    assert third.descriptor.input_schema_sha256 == second.descriptor.input_schema_sha256
    assert third.descriptor.output_schema_sha256 != second.descriptor.output_schema_sha256
    # ``@2``'s pinned output schema did not move underneath the profile that pins it.
    assert "excluded_by_gate" not in DiscoveryCandidateView.model_fields
    assert "excluded" not in ReadDiscoveryRunV2Output.model_fields
    assert "approves nothing" in third.model_description
    assert "excluded" in third.model_description


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


# -- read 4: the claims about one account or contact ----------------------------------------------

CONTACT_ID = "66666666-6666-5666-8666-666666666666"


def _claims_page(entity_type: str = "account") -> ClaimsQueryPage:
    return ClaimsQueryPage(
        entity_id=ACCOUNT_ID if entity_type == "account" else CONTACT_ID,
        entity_type=entity_type,
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
        excluded={"sensitive": 1, "unverified": 0, "outreach_unsafe": 2},
        prefixes={"account.open_requisitions": 4, "core": 1},
        offset=40,
        next_offset=41,
        truncated=True,
    )


def test_the_claims_query_asks_about_the_ambient_workspace_and_carries_every_filter() -> None:
    """The filters ARE this read: one that quietly dropped ``tier`` would answer a narrowed
    question with the unnarrowed list, and the model would quote a tier-4 guess as tier-1 fact."""

    async def scenario() -> None:
        service = _FakeService(claims=_claims_page())
        tool = ReadClaimsTool(service)

        result = await tool.invoke(
            ReadClaimsInput(
                entity_id=ACCOUNT_ID,
                field_prefix="account.resonance",
                tier=2,
                verification_status="verified",
                since="2026-09-01",
                offset=40,
                limit=5,
            ),
            _context(),
        )

        # The tenant is AMBIENT, never a model-authored input; every filter is the model's, and
        # all of them reach the service unaltered.
        assert service.claims_reads == [
            (WORKSPACE, ACCOUNT_ID, "account.resonance", 2, "verified", "2026-09-01", 40, 5)
        ]
        assert result.references["entity_id"] == ACCOUNT_ID
        # The read says what it read: an account and a contact are answered in one shape, and the
        # shape names which one it was.
        assert result.references["entity_type"] == "account"
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
        # Held back, counted, and said out loud — the same three reasons the account page counts.
        assert result.references["excluded"] == {
            "sensitive": 1,
            "unverified": 0,
            "outreach_unsafe": 2,
        }
        # The families the subject actually has, so a wrong prefix costs one call, not a series.
        assert result.references["prefixes"] == {"account.open_requisitions": 4, "core": 1}
        assert (result.references["offset"], result.references["next_offset"]) == (40, 41)
        assert result.references["truncated"] is True
        # And the runner's own re-validation accepts what the tool serialized.
        canonical = validate_tool_output_references(ReadClaimsOutput, result.references)
        assert canonical["entity_type"] == "account"

    run_async(scenario())


def test_the_claims_query_reads_a_contact_under_the_same_contract() -> None:
    """One read, two kinds of subject: the store keys claims on an entity id, not on a table."""

    async def scenario() -> None:
        service = _FakeService(claims=_claims_page("contact"))
        tool = ReadClaimsTool(service)

        result = await tool.invoke(ReadClaimsInput(entity_id=CONTACT_ID), _context())

        assert service.claims_reads == [(WORKSPACE, CONTACT_ID, None, None, None, None, 0, 40)]
        assert result.references["entity_type"] == "contact"
        assert result.references["entity_id"] == CONTACT_ID

    run_async(scenario())


def test_the_claims_query_s_inputs_are_bounded_by_the_schema() -> None:
    defaults = ReadClaimsInput(entity_id=ACCOUNT_ID)
    assert (defaults.field_prefix, defaults.tier, defaults.verification_status) == (
        None,
        None,
        None,
    )
    assert (defaults.since, defaults.offset, defaults.limit) == (None, 0, 40)
    # The page: at least one claim, never more than the substrate's own ceiling.
    ReadClaimsInput(entity_id=ACCOUNT_ID, limit=MAX_CLAIMS)
    with pytest.raises(ValueError):
        ReadClaimsInput(entity_id=ACCOUNT_ID, limit=MAX_CLAIMS + 1)
    with pytest.raises(ValueError):
        ReadClaimsInput(entity_id=ACCOUNT_ID, limit=0)
    with pytest.raises(ValueError):
        ReadClaimsInput(entity_id=ACCOUNT_ID, offset=-1)
    # The tiers are the platform's four, and nothing else: a "tier 5" ask is a misunderstanding
    # the schema refuses rather than an empty answer the model reads as "nothing there".
    for tier in (1, 2, 3, 4):
        assert ReadClaimsInput(entity_id=ACCOUNT_ID, tier=tier).tier == tier
    for bad in (0, 5):
        with pytest.raises(ValueError):
            ReadClaimsInput(entity_id=ACCOUNT_ID, tier=bad)
    # The status vocabulary is the column's own.
    for status in ("unverified", "verified", "rejected"):
        assert ReadClaimsInput(entity_id=ACCOUNT_ID, verification_status=status)
    with pytest.raises(ValueError):
        ReadClaimsInput(entity_id=ACCOUNT_ID, verification_status="probably")
    ReadClaimsInput(entity_id=ACCOUNT_ID, field_prefix="z" * 80)
    with pytest.raises(ValueError):
        ReadClaimsInput(entity_id=ACCOUNT_ID, field_prefix="z" * 81)
    with pytest.raises(ValueError):
        # The account read's word for a subject is not this one's, and the contract says so
        # rather than reading an id it was never given.
        ReadClaimsInput.model_validate({"account_entity_id": ACCOUNT_ID})


@pytest.mark.parametrize("code", ["entity_not_found", "since_invalid", "offset_past_end"])
def test_the_claims_query_refuses_by_name_rather_than_answering_empty(code: str) -> None:
    """Three things are refusals and everything else is an honest empty page: a subject this
    workspace cannot see, a ``since`` that is not a date, and an offset past the end. Each would
    otherwise read as "we know nothing about them", which is a false statement, not a null one."""

    async def scenario() -> None:
        service = _FakeService(refusal=Arv2ReadRefused(code, f"{code} happened"))
        tool = ReadClaimsTool(service)

        with pytest.raises(PreconditionFailed) as refused:
            await tool.invoke(ReadClaimsInput(entity_id=ACCOUNT_ID), _context())

        assert refused.value.reason_codes == (code,)

    run_async(scenario())


def test_the_claims_query_declares_the_classification_and_the_manual_the_registry_admits() -> None:
    tool = ReadClaimsTool(_FakeService())

    assert (tool.name, tool.version) == ("read_claims", "1")
    assert tool.effect_class is ToolEffectClass.READ
    assert tool.replay.policy is ReplayPolicy.EFFECT_FREE
    # ``project`` is the spine row the execution is bound to — a replay identity, not a Stage-0
    # pin (standing rule item 5); the recipe-safety audit refuses a standing address with no pin.
    assert tool.pin_requirements == ("project",)
    assert tool.descriptor.recipe_safe
    # The description teaches the four filters, sends the written overview to its own read, and
    # points at the chapter that will teach it (minted with the grant, at v3).
    for word in ("field_prefix", "tier", "verification status", "since", "read_account_research"):
        assert word in tool.model_description
    assert tool.model_description.endswith(tool_manual_link("read_claims"))
    # Its own contract, not a second face of the account read's.
    account = ReadAccountResearchTool(_FakeService())
    assert tool.descriptor.input_schema_sha256 != account.descriptor.input_schema_sha256
    assert tool.descriptor.output_schema_sha256 != account.descriptor.output_schema_sha256


# -- the registered surface ------------------------------------------------------------------------


def test_the_builder_yields_the_five_reads_and_an_uncomposed_one_refuses_by_name() -> None:
    """Registered on every deployment, composed where the lane is — the ARV2 registration posture.

    Uncomposed the four still register, so an agent that reaches for a read gets the named
    ``arv2_reads_not_composed`` refusal rather than an ``UnknownTool`` it cannot explain.
    ``read_claims`` is the fourth: one service, one refusal code, no flag of its own — and no
    grant yet, which is a profile decision rather than a composition one.
    """

    async def scenario() -> None:
        tools = build_arv2_read_tools(None)

        assert [tool.name for tool in tools] == [
            "read_project_accounts",
            "read_account_research",
            "read_discovery_run",
            "read_claims",
            "read_cited_claims",
        ]
        inputs: dict[str, ToolInput] = {
            "read_project_accounts": ReadProjectAccountsInput(project_id=PROJECT),
            "read_account_research": ReadAccountResearchInput(account_entity_id=ACCOUNT_ID),
            "read_discovery_run": ReadDiscoveryRunInput(project_id=PROJECT),
            "read_claims": ReadClaimsInput(entity_id=ACCOUNT_ID),
            "read_cited_claims": ReadCitedClaimsInput(entity_id=ACCOUNT_ID, claim_ids=[CLAIM_ID]),
        }
        for tool in tools:
            failures = await tool.preconditions(inputs[tool.name], _context())
            assert [failure.reason_code for failure in failures] == ["arv2_reads_not_composed"]

        # Composed, the same four are ready to read.
        service = _FakeService(
            page=_page(),
            research=_research(),
            discovery=_discovery(),
            claims=_claims_page(),
            cited=_cited_page(),
        )
        for tool in build_arv2_read_tools(service):
            assert await tool.preconditions(inputs[tool.name], _context()) == ()

    run_async(scenario())


def test_the_paged_pair_registers_beside_the_frozen_ones_on_the_same_composition() -> None:
    """The two ``@2`` addresses are the same reads on the same service: one composition, one
    refusal code, no second flag. They are built separately only because ``@1`` still owns the
    name-only alias until a profile pins ``@2``."""

    async def scenario() -> None:
        paged = build_arv2_paged_read_tools(None)

        assert [(tool.name, tool.version) for tool in paged] == [
            ("read_account_research", "2"),
            ("read_discovery_run", "2"),
        ]
        inputs: dict[str, ToolInput] = {
            "read_account_research": ReadAccountResearchV2Input(account_entity_id=ACCOUNT_ID),
            "read_discovery_run": ReadDiscoveryRunV2Input(project_id=PROJECT),
        }
        for tool in paged:
            failures = await tool.preconditions(inputs[tool.name], _context())
            assert [failure.reason_code for failure in failures] == ["arv2_reads_not_composed"]

        service = _FakeService(page=_page(), research=_research(), discovery=_discovery())
        for tool in build_arv2_paged_read_tools(service):
            assert await tool.preconditions(inputs[tool.name], _context()) == ()

    run_async(scenario())


def _cited_page() -> CitedClaimsPage:
    return CitedClaimsPage(
        entity_id=ACCOUNT_ID,
        claims=(
            AccountClaimView(
                claim_id=CLAIM_ID,
                field_key="account.research_finding",
                value={"finding": "Healthcare up $4.2 million"},
                source_url="https://alpha.example/budget.pdf",
                evidence="Healthcare increase of $4.2 million",
                evidence_truncated=False,
                tier=2,
                verification_status="unverified",
                outreach_safe=False,
                collected_at="2026-09-12T12:00:00+00:00",
            ),
        ),
        dispositions={
            CLAIM_ID: "served",
            "66666666-6666-5666-8666-666666666666": "held:outreach_unsafe",
            "77777777-7777-5777-8777-777777777777": "not_found",
        },
    )


def test_the_cited_claims_read_asks_about_the_ambient_workspace_and_serves_dispositions() -> None:
    async def scenario() -> None:
        service = _FakeService(cited=_cited_page())
        tool = ReadCitedClaimsTool(service)
        ids = [
            CLAIM_ID,
            "66666666-6666-5666-8666-666666666666",
            "77777777-7777-5777-8777-777777777777",
        ]

        result = await tool.invoke(
            ReadCitedClaimsInput(entity_id=ACCOUNT_ID, claim_ids=ids), _context()
        )

        assert service.cited_reads == [(WORKSPACE, ACCOUNT_ID, tuple(ids))]
        assert result.references["entity_id"] == ACCOUNT_ID
        assert [claim["claim_id"] for claim in result.references["claims"]] == [CLAIM_ID]
        assert result.references["dispositions"] == {
            CLAIM_ID: "served",
            "66666666-6666-5666-8666-666666666666": "held:outreach_unsafe",
            "77777777-7777-5777-8777-777777777777": "not_found",
        }
        canonical = validate_tool_output_references(ReadCitedClaimsOutput, result.references)
        assert canonical["dispositions"][CLAIM_ID] == "served"

    run_async(scenario())


def test_the_cited_claims_read_is_bounded_and_refuses_by_name() -> None:
    with pytest.raises(ValueError):
        ReadCitedClaimsInput(entity_id=ACCOUNT_ID, claim_ids=[])
    with pytest.raises(ValueError):
        ReadCitedClaimsInput(entity_id=ACCOUNT_ID, claim_ids=[CLAIM_ID] * (MAX_CITED_CLAIMS + 1))

    async def scenario() -> None:
        tool = ReadCitedClaimsTool(
            _FakeService(refusal=Arv2ReadRefused("entity_not_found", "no such entity"))
        )
        with pytest.raises(PreconditionFailed) as refused:
            await tool.invoke(
                ReadCitedClaimsInput(entity_id=ACCOUNT_ID, claim_ids=[CLAIM_ID]), _context()
            )
        assert [f.reason_code for f in refused.value.failures] == ["entity_not_found"]
        uncomposed = ReadCitedClaimsTool(None)
        failures = await uncomposed.preconditions(
            ReadCitedClaimsInput(entity_id=ACCOUNT_ID, claim_ids=[CLAIM_ID]), _context()
        )
        assert [f.reason_code for f in failures] == ["arv2_reads_not_composed"]

    run_async(scenario())


def test_the_cited_claims_read_declares_its_classification() -> None:
    tool = ReadCitedClaimsTool(_FakeService())
    assert (tool.name, tool.version) == ("read_cited_claims", "1")
    assert tool.effect_class is ToolEffectClass.READ
    assert tool.replay.policy is ReplayPolicy.EFFECT_FREE
    assert tool.pin_requirements == ("project",)
    assert tool.descriptor.recipe_safe
