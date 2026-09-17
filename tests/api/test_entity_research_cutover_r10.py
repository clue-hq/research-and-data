"""R10 production promotion, subject routing, and historical replay boundaries."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from clue_agents.account_entity_research import DiscoverBuyingCommitteeInput
from clue_agents.entity_research_runtime import _ACTIVE_TOOL_EXECUTION
from clue_api import account_entity_research_composition as composition
from clue_api.entity_research_fleet_composition import (
    EntityResearchSubjectResolver,
    SubjectNeutralEntityResearchWorkHandler,
)
from clue_api.entity_research_provider_wiring import build_production_entity_research_fleet
from clue_api.entity_research_quarantine import (
    QUARANTINED_ENTITY_RESEARCH_TOOL_ADDRESSES,
    ReplayOnlyEntityResearchTool,
)
from clue_api.entity_research_tools import EntityResearchResultStore
from clue_api.toolbelt_wiring import build_toolbelt
from clue_config import Secrets, Settings
from clue_core import LLMGateway, PreSpendGate
from clue_core.entity_research import ResearchSubjectType
from clue_fleet import EntityResearchJobError, FleetTaskKind, LeaseGeneration, WorkId
from clue_fleet.work_worker import WorkContext, WorkResult
from clue_research.claimstore.packs import CORE_PACK

_ROOT = Path(__file__).parents[2]


@dataclass
class _Subjects(EntityResearchSubjectResolver):
    subject: ResearchSubjectType
    observed: list[UUID]

    async def subject_for_job(self, job_id: UUID) -> ResearchSubjectType:
        self.observed.append(job_id)
        return self.subject


class _Handler:
    kind = FleetTaskKind.ENTITY_RESEARCH_JOB

    def __init__(self, outcome: str) -> None:
        self.outcome = outcome
        self.calls = 0

    async def handle(self, context: WorkContext) -> WorkResult:
        self.calls += 1
        return WorkResult(outcome=self.outcome, references={"work_id": str(context.work_id)})


def _context(job_id: UUID, *, work_id: UUID | None = None) -> WorkContext:
    return WorkContext(
        task_id=uuid4(),
        work_id=WorkId(work_id or job_id),
        worker_id="worker:r10",
        lease_generation=LeaseGeneration(1),
        payload={"job_id": str(job_id)},
        stop_requested=asyncio.Event(),
        lease_lost=asyncio.Event(),
    )


@pytest.mark.parametrize(
    ("subject", "expected"),
    (
        (ResearchSubjectType.ACCOUNT, "account"),
        (ResearchSubjectType.CONTACT, "contact"),
    ),
)
def test_one_worker_kind_routes_only_by_immutable_subject(
    subject: ResearchSubjectType,
    expected: str,
) -> None:
    async def scenario() -> None:
        job_id = uuid4()
        accounts = _Handler("account")
        contacts = _Handler("contact")
        subjects = _Subjects(subject=subject, observed=[])
        router = SubjectNeutralEntityResearchWorkHandler(
            accounts=accounts,
            contacts=contacts,
            subjects=subjects,
        )
        result = await router.handle(_context(job_id))
        assert result.outcome == expected
        assert subjects.observed == [job_id]
        assert accounts.calls == (1 if subject is ResearchSubjectType.ACCOUNT else 0)
        assert contacts.calls == (1 if subject is ResearchSubjectType.CONTACT else 0)

    asyncio.run(scenario())


def test_subject_router_refuses_payload_lease_widening_before_delegate() -> None:
    async def scenario() -> None:
        job_id = uuid4()
        accounts = _Handler("account")
        contacts = _Handler("contact")
        subjects = _Subjects(subject=ResearchSubjectType.ACCOUNT, observed=[])
        router = SubjectNeutralEntityResearchWorkHandler(
            accounts=accounts,
            contacts=contacts,
            subjects=subjects,
        )
        with pytest.raises(EntityResearchJobError, match="widens"):
            await router.handle(_context(job_id, work_id=uuid4()))
        assert subjects.observed == []
        assert accounts.calls == contacts.calls == 0

    asyncio.run(scenario())


def test_active_toolbelt_promotes_new_launches_and_retains_old_exact_replay_only() -> None:
    registry = build_toolbelt(storage=None)
    promoted = {
        "launch_account_research@1",
        "read_account_research_run@1",
        "approve_contact_research_selection@2",
        "launch_contact_research@1",
        "read_contact_research_run@1",
    }
    addresses = {item.address for item in registry.all_descriptors()}
    assert promoted.issubset(addresses)
    for address in QUARANTINED_ENTITY_RESEARCH_TOOL_ADDRESSES:
        name, version = address.split("@", maxsplit=1)
        assert isinstance(registry.get(name, version), ReplayOnlyEntityResearchTool)


def test_r10_runtime_is_independently_default_off_and_composition_does_no_eager_io() -> None:
    settings = Settings(_env_file=None)
    assert not settings.entity_research_runtime_enabled
    assert settings.entity_research_unpriced_reservation_cents > 0
    assert settings.entity_research_provider_concurrency_limit == 30
    assert (
        build_production_entity_research_fleet(
            settings=settings,
            secrets=Secrets(_env_file=None),
            storage=cast(Any, object()),
            models=object(),
            gateway=cast(LLMGateway, object()),
            gateway_config=cast(Any, object()),
            pre_spend_gate=cast(PreSpendGate, object()),
        )
        is None
    )


def test_production_worker_composes_promoted_launches_and_one_entity_handler() -> None:
    from clue_api import fleet_main

    source = inspect.getsource(fleet_main._serve)
    assert "build_production_entity_research_fleet(" in source
    assert "entity_research_launches=entity_research_launches" in source
    assert "entity_research_handler=(" in source
    assert "entity_research.handler" in source
    assert "account_deep_preparer" not in source
    assert "contact_research_preparer" not in source
    assert not hasattr(fleet_main, "_account_agent_runtime_required")


def test_release_matrix_covers_every_numbered_section_16_gate_with_real_evidence() -> None:
    matrix_path = _ROOT / "tests/fixtures/entity_research/r10_release_matrix.json"
    matrix = json.loads(matrix_path.read_text())
    criteria = matrix["criteria"]
    assert [item["criterion"] for item in criteria] == list(range(1, 25))
    for item in criteria:
        evidence = item["evidence"]
        assert evidence
        for relative in evidence:
            assert (_ROOT / relative).is_file(), (
                f"R10 criterion {item['criterion']} names missing evidence {relative}"
            )
    assert criteria[-1]["live_required"] is True


def test_promoted_deep_field_pack_names_the_real_exa_deep_source() -> None:
    by_field = {str(item.field_def.field_key): item.field_def for item in CORE_PACK}
    assert by_field["account.hiring_velocity_eng"].tier_plan == (
        "sumble_jobs",
        "linkedin_jobs",
        "exa_deep",
    )
    assert by_field["contact.facet.recent_post"].tier_plan == (
        "exa_deep",
        "firecrawl",
    )


#: The steering bundle the production resolver actually composes. These assertions guarded the
#: live prompt until the v1→v2 bump left them pointing at a frozen historical directory, where
#: they could no longer catch a regression; they now follow the live version.
_ACCOUNT_STEERING_ROOT = _ROOT / "platform/agents/catalog/entity-research/account/v3"


def _steering_text(name: str) -> str:
    """Read one live steering resource with its hard wrapping flattened.

    The bodies are hand-wrapped prose, so a sentence the agent reads as one instruction can hold a
    newline anywhere. Asserting on the raw text made these guards depend on the wrap column — the
    finalization guard silently stopped matching the moment v2 rewrapped it.
    """

    return " ".join((_ACCOUNT_STEERING_ROOT / name).read_text().split())


def test_account_agent_parallel_provider_instructions_require_disjoint_fields() -> None:
    prompt = _steering_text("prompt.md")
    skill = _steering_text("skill.md")

    assert "no field may appear in both calls" in prompt
    assert "Parallel provider calls must own disjoint fields" in skill
    assert "sequential corroboration" in prompt


def test_account_agent_committee_and_finalization_instructions_are_machine_visible() -> None:
    prompt = _steering_text("prompt.md")
    skill = _steering_text("skill.md")
    properties = DiscoverBuyingCommitteeInput.model_json_schema()["properties"]

    assert properties["field_keys"]["maxItems"] == 0
    assert properties["parent_operation_ref"]["type"] == "null"
    assert properties["parent_observation_ref"]["type"] == "null"
    assert properties["follow_up_reason"]["type"] == "null"
    assert "copy the exact confirmed committee question" in prompt
    assert "Committee enumeration uses no `field_keys`" in skill
    assert "ResearchFinalizationProposal" in prompt
    assert "call `finalize_account_research` again" in prompt


def test_result_projection_distinguishes_own_source_from_independent_corroboration() -> None:
    assert not EntityResearchResultStore._has_independent_corroboration(  # noqa: SLF001
        ({"corroborations": 1},)
    )
    assert EntityResearchResultStore._has_independent_corroboration(  # noqa: SLF001
        ({"corroborations": 2},)
    )


def test_live_canary_uses_the_accepted_fifty_result_exa_contract() -> None:
    source = (_ROOT / "scripts/13_m8d_r10_live_acceptance.py").read_text()

    # Account side: the harness must exercise the accepted production cap of 50. A smaller
    # canary-only cap made Exa ground an answer in more URLs than it retained in ``results[]``,
    # which is an internal settlement failure, not a provider fault.
    assert re.search(r"\"?exa_account_deep_max_results\"?\s*[:=]\s*50", source)
    assert not re.search(r"\"?exa_account_deep_max_results\"?\s*[:=]\s*(?!50\b)\d+", source)
    # Contact side: the durable selection policy already caps at the accepted 50
    # (clue_core.contact_research); the harness must never clamp it back down.
    assert "min(target.exa_max_results" not in source


#: Every tool the production account surface can bind, plus the facet tool the runtime admits when
#: delegation is enabled. The operations manual must speak about all of them by name.
_ACCOUNT_MANUAL_TOOLS = (
    "read_account_research_state",
    "research_account_deep",
    "enrich_account",
    "inspect_account_evidence",
    "discover_buying_committee",
    "record_committee_role_inferences",
    "assess_account_coverage",
    "read_research_result",
    "read_evidence",
    "finalize_account_research",
    "delegate_account_facet",
)

#: The refusal codes and engine refusal texts the live run actually produced. The manual exists so
#: the agent's next move after each of them is stated, not improvised.
_ACCOUNT_MANUAL_REFUSALS = (
    "provider_terminally_unproductive",
    "provider_rejected",
    "provider_spend_unreconciled",
    "committee_provider_organization_unmatched",
    "committee_provider_identity_absent",
    "engine_authority_rejection",
    "reference_type_rejected",
    "evidence_page_rejected",
    "request_authority_violation",
    "research_request_shape_rejected",
    "identical_read_loop",
    "empty_model_turn",
    "parallel_round_shape_rejected",
    "finalization_already_proposed",
)


def test_account_operations_manual_covers_every_tool_and_live_refusal() -> None:
    manual = _steering_text("manual.md")

    for tool_name in _ACCOUNT_MANUAL_TOOLS:
        assert f"## {tool_name}" in manual, tool_name
    for code in _ACCOUNT_MANUAL_REFUSALS:
        assert code in manual, code
    # The settlement contract and the loop rule are the manual's two global obligations.
    assert "exhausted" in manual
    assert "honest gap" in manual
    assert "Never send an identical call after a refusal." in manual
    # Reference shapes the live run got wrong.
    assert "research-result:<uuid>" in manual
    assert "research-evidence:<uuid>" in manual
    assert "account-coverage:<uuid>" in manual
    assert "sumble-account-operation" in manual
    # The prompt must point at the manual, or it is inert context.
    assert "account tool operations manual" in _steering_text("prompt.md")


def test_account_steering_version_moves_without_repinning_the_authorization_profile() -> None:
    """Steering may evolve under already-launched jobs; the authorization pin may not.

    ``AccountResearchDefinitionResolver.resolve`` refuses any job whose authorization names
    another profile ref, and every launched job carries its ref at rest — so the profile pin is
    bumped only for a genuine role-identity change, while prompt/skill/manual (replay-pinned by
    the R3 journal, not by the authorization) carry the version of the day.
    """

    assert composition.ACCOUNT_RESEARCH_PROFILE_REF == "agent-profile:account-research:v2"
    assert composition._ACCOUNT_PROFILE_VERSION == "v2"
    assert composition._ACCOUNT_STEERING_VERSION == "v3"
    assert composition._ACCOUNT_PROMPT_REF == "agent-prompt:account-research:v3"
    assert composition._ACCOUNT_SKILL_REF == "agent-skill:governed-account-research:v3"
    assert composition._ACCOUNT_MANUAL_REF == "agent-skill:account-tool-operations-manual:v3"
    profile_root = _ROOT / "platform/agents/catalog/entity-research/account/v2"
    expected_sha = hashlib.sha256((profile_root / "profile.md").read_bytes()).hexdigest()
    assert composition.account_research_profile_sha256() == expected_sha
    # Historical steering stays frozen and self-contained; the live root carries the manual.
    for version in ("v1", "v2"):
        historical = _ROOT / "platform/agents/catalog/entity-research/account" / version
        assert (historical / "prompt.md").exists()
        assert not (historical / "manual.md").exists()
    assert (_ACCOUNT_STEERING_ROOT / "manual.md").exists()
    assert not (_ACCOUNT_STEERING_ROOT / "profile.md").exists()


class _RaisingChannelActions:
    """A channel surface that fails exactly once per species, so the tool wiring is observable."""

    def __init__(self, error: BaseException) -> None:
        self._error = error

    def admission(self, *, stage: str) -> None:
        del stage
        return None

    async def reveal(self, *, active: object, request: object) -> object:
        del active, request
        raise self._error

    async def validate(self, *, active: object, request: object) -> object:
        del active, request
        raise self._error


class _NeverFacetDelegate:
    async def delegate(self, *, active: object, request: object) -> object:
        del active, request
        raise AssertionError("the channel wiring test must not delegate a facet")


def _contact_bindings(error: BaseException) -> dict[str, Any]:
    from clue_api.contact_entity_research import (
        ContactResearchStateStore,
        contact_engine_tool_bindings,
    )

    return dict(
        contact_engine_tool_bindings(
            ContactResearchStateStore(conn_factory=cast(Any, None)),
            facets=cast(Any, _NeverFacetDelegate()),
            channels=cast(Any, _RaisingChannelActions(error)),
        )
    )


def test_every_contact_engine_tool_repairs_a_malformed_model_argument() -> None:
    """A wrong-shaped tool argument is species 1 on both axes — the contact axis had no handler.

    Every account engine tool binds ``handle_validation_error``/``handle_tool_error``; not one
    contact tool did, so a model that mistyped an argument raised a raw ``ValidationError`` out of
    LangChain's own argument parsing and failed the whole contact execution. The two channel tools
    additionally carried no ``handle_tool_error``, so nothing they raised could ever be rendered.
    """

    bindings = _contact_bindings(RuntimeError("unreachable"))
    assert set(bindings) == {
        "read_contact_research_state",
        "inspect_contact_evidence",
        "assess_contact_coverage",
        "delegate_contact_facet",
        "reveal_contact_channel",
        "validate_contact_channel",
        "finalize_contact_research",
    }
    for name, binding in bindings.items():
        assert binding.tool.handle_validation_error, name
        assert binding.tool.handle_tool_error, name


def test_a_channel_tool_renders_a_model_input_refusal_and_still_suspends_on_integrity() -> None:
    """The channel pair splits the two species instead of failing the job for both.

    ``reveal``/``validate`` refuse a channel outside the selected permissions, and a validation
    with no preceding acquisition, on model input — repairable. Their causation, cost-fold and
    post-settlement reads are money and truth, and must keep suspending.
    """

    from clue_api.contact_entity_research import ContactResearchAuthorityError
    from clue_api.entity_research_tools import EntityResearchResultIntegrityError

    async def scenario() -> None:
        token = _ACTIVE_TOOL_EXECUTION.set(cast(Any, object()))
        try:
            repairable = _contact_bindings(
                ContactResearchAuthorityError(
                    "channel action differs from the exact selected contact authority"
                )
            )
            rendered = await repairable["reveal_contact_channel"].tool.ainvoke({"channel": "email"})
            payload = json.loads(str(rendered))
            assert payload["error"] == "governed_research_rejection"
            assert payload["recoverable"] is True

            suspending = _contact_bindings(
                EntityResearchResultIntegrityError("channel cost fold replay changed settlement")
            )
            with pytest.raises(EntityResearchResultIntegrityError):
                await suspending["validate_contact_channel"].tool.ainvoke({"channel": "email"})
        finally:
            _ACTIVE_TOOL_EXECUTION.reset(token)

    asyncio.run(scenario())


def test_the_contact_guard_refuses_a_bad_channel_and_a_zero_field_buy_recoverably() -> None:
    """Two model-argument mistakes the contact guard turned into whole-job failures.

    A ``channel`` the model invented reached ``ContactChannel(...)`` and raised a bare
    ``ValueError`` — not an ``EntityResearchGovernedToolRefusal``, so the middleware could not
    render it. And a zero-``field_keys`` provider call had no contact-lane equivalent of the
    account guard's check, so it reached the provider action and died on the *suspending*
    ``EntityResearchResultIntegrityError``. Both are R10 species 1.
    """

    from clue_agents.entity_research_contracts import (
        EntityAgentRole,
        EntityResearchToolCall,
        canonical_sha256,
    )
    from clue_api.contact_entity_research import (
        ContactResearchAuthorityError,
        ContactResearchExecutionGuard,
    )
    from tests.agents.test_entity_research_runtime_r3 import _context

    def call(name: str, arguments: dict[str, Any]) -> EntityResearchToolCall:
        return EntityResearchToolCall(
            tool_call_id=f"guard-{name}",
            tool_name=name,
            tool_version=1,
            tool_input_sha256=canonical_sha256(arguments),
            arguments=arguments,
        )

    async def scenario() -> None:
        context = _context(ResearchSubjectType.CONTACT, EntityAgentRole.CONTACT)
        # The conn factory is never reached: both refusals precede the coverage read.
        guard = ContactResearchExecutionGuard(conn_factory=cast(Any, None))
        with pytest.raises(ContactResearchAuthorityError, match="unknown channel"):
            await guard.authorize_tool(
                context=context,
                call=call("reveal_contact_channel", {"channel": "carrier-pigeon"}),
                journal_event_ref=f"entity-agent-event:{uuid4()}",
            )
        with pytest.raises(ContactResearchAuthorityError, match="at least one field"):
            await guard.authorize_tool(
                context=context,
                call=call(
                    "research_contact_deep",
                    {"field_keys": [], "source_keys": ["exa_deep"]},
                ),
                journal_event_ref=f"entity-agent-event:{uuid4()}",
            )

    asyncio.run(scenario())
