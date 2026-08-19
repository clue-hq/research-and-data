"""R10 production promotion, subject routing, and historical replay boundaries."""

from __future__ import annotations

import asyncio
import inspect
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from clue_agents.account_entity_research import DiscoverBuyingCommitteeInput
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


def test_account_agent_parallel_provider_instructions_require_disjoint_fields() -> None:
    resource_root = _ROOT / "platform/agents/catalog/entity-research/account/v1"
    prompt = (resource_root / "prompt.md").read_text()
    skill = (resource_root / "skill.md").read_text()

    assert "no field may appear in both calls" in prompt
    assert "Parallel provider calls must own disjoint fields" in skill
    assert "sequential corroboration" in prompt


def test_account_agent_committee_and_finalization_instructions_are_machine_visible() -> None:
    resource_root = _ROOT / "platform/agents/catalog/entity-research/account/v1"
    prompt = (resource_root / "prompt.md").read_text()
    skill = (resource_root / "skill.md").read_text()
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
