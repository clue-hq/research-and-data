#!/usr/bin/env python3
"""Bounded live M8D R10 account/contact canary on one fresh PostgreSQL database.

The script deliberately starts from the synthetic Stage-0/discovery handoff and then uses the
promoted production entity-fleet composition.  It does not test a transport in isolation: a live
model must select governed tools, those tools must cause real Exa/Sumble operations, and the
engine must persist results, claims, costs, coverage, finalization, and an exact replay receipt.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text

from clue_api.account_research_fleet import AccountResearchFleetPolicy
from clue_api.account_research_fleet_launch import AccountResearchFleetLaunchRequest
from clue_api.agent_model_wiring import build_agent_model_provider
from clue_api.composition import build_pre_spend_gate
from clue_api.contact_research_fleet_launch import (
    ContactResearchFleetLaunchRequest,
    ContactResearchSelectionApprovalRequest,
    ContactResearchSelectionApprover,
    ContactResearchTargetApproval,
)
from clue_api.contact_research_selection import ContactResearchSelectionMaterializer
from clue_api.entity_research_parallel import EntityResearchBatchWakeService
from clue_api.entity_research_provider_wiring import build_production_entity_research_fleet
from clue_api.external_research_wake import (
    ExternalResearchWakeDispatcher,
    registered_entity_research_wait_sources,
)
from clue_api.research_directive_tools import build_research_directive_tools
from clue_api.run_composition import build_platform_gateway
from clue_api.trial.account_deep_fixture import (
    PROJECT_RUN_ID,
    AccountDeepFixtureTarget,
    seed_insight_health_account_deep_fixture,
)
from clue_api.trial.discovery_fixture import (
    AMBIENT_URL,
    AURA_ANYWHERE_URL,
    HOME_URL,
    NEUROSURGERY_URL,
    OfficialSitePage,
)
from clue_config import Secrets, Settings, default_gateway_config
from clue_core import (
    ClaimId,
    EntityId,
    MemoryDisabled,
    MemorySubmission,
    ResearchAccountScope,
    ResearchCommitteePlan,
    ResearchDirectiveBody,
    ResearchDirectiveId,
    ResearchEffortPolicy,
    ResearchPrivacyPolicy,
    ResearchQuestion,
    ResearchSourcePolicy,
    new_operation_id,
)
from clue_core.entity_research import FieldSourceAuthority, ResearchSelectionBasis
from clue_db import DATABASE_URL_ENV, db_lifespan, transaction
from clue_fleet import DbWorkQueue, LeasedWorkWorker
from clue_research.directives import (
    confirmed_directive_account_specs,
    get_latest_research_directive,
)
from clue_research.durable.enums import ProjectRunStatus
from clue_storage import FsStorage
from clue_toolbelt import ToolContext, ToolRegistry, invoke_tool

_ACCOUNT_FIELDS = (
    "account.operational_pain",
    "account.strategic_moves",
    "account.hiring_velocity_eng",
)
_CONTACT_FACET = "contact.facet.recent_post"
_ALL_FIELDS = (*_ACCOUNT_FIELDS, _CONTACT_FACET)
_ACCOUNT_BUDGET_CENTS = Decimal("700")
_CONTACT_BUDGET_CENTS = Decimal("100")
_TOTAL_BUDGET_CENTS = Decimal("1000")
_LIVE_ACTOR = "human:m8d-r10-live-owner"
_ACCOUNT_LAUNCH_ACTION_REF = "turn:m8d-r10-live-account-launch"
_CONTACT_LAUNCH_ACTION_REF = "turn:m8d-r10-live-contact-launch"
# The only environment values this harness consumes on purpose.
_NAMED_SECRET_ENV = (
    "CLUE_DATABASE_URL",
    "CLUE_OPENROUTER_API_KEY",
    "CLUE_EXA_API_KEY",
    "CLUE_SUMBLE_API_KEY",
)


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--storage-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=1200)
    parser.add_argument(
        "--resume-seeded",
        action="store_true",
        help=(
            "Reuse only a prerequisite fixture that has zero entity jobs and provider "
            "operations. This never resumes a partially spent canary."
        ),
    )
    parser.add_argument(
        "--resume-account-run",
        type=UUID,
        help=(
            "Resume one nonterminal suspended account canary from its durable checkpoint, then "
            "continue through contact selection, contact research, and replay acceptance."
        ),
    )
    parser.add_argument(
        "--resume-contact-run",
        type=UUID,
        help=(
            "Resume one nonterminal suspended contact canary from its durable checkpoint. The "
            "account canary must already be terminal; nothing is reseeded, no new selection is "
            "approved, and the exact durable launch authorization is replayed rather than "
            "reissued."
        ),
    )
    parser.add_argument(
        "--allow-live-provider-calls",
        action="store_true",
        help="Required acknowledgement for real Exa, Sumble, and model traffic.",
    )
    return parser.parse_args()


class _DisabledMemory:
    async def submit(self, _submission: MemorySubmission) -> MemoryDisabled:
        return MemoryDisabled()


def _pages() -> dict[str, OfficialSitePage]:
    """Small, provenance-complete Stage-0 fixture; these are not provider results."""

    return {
        HOME_URL: OfficialSitePage(
            url=HOME_URL,
            title="Insight Health AI",
            markdown=(
                "# The AI referral coordinator for specialty practices.\n\n"
                "MagicDocs reads inbound referrals and routes each to the right EHR work queue "
                "so nothing stalls on the fax machine.\n\n"
                "## Pricing\n\n"
                "Pay by the month or the year, and cancel at any time\n\n"
                "Free Forever\n\n"
                "Save 2+ hours every day. The quickest and easiest way to try AuraTM Scribe.\n\n"
                "Pro\n\n$49.99\n\nPer clinician\n\nEnterprise\n\nCustom\n\n"
                "Includes Virtual Care Assistant (VCA) + AuraTM AI Scribe."
            ),
        ),
        AMBIENT_URL: OfficialSitePage(
            url=AMBIENT_URL,
            title="Aura ambient documentation",
            markdown=(
                "## Fully Customizable Note Format\n\n"
                "AuraTM AI Scribe offers unlimited customization beyond APSO, SOAP, and H&P "
                "formats.\n\n"
                "## Integrated ICD-10 and CPT Coding\n\n"
                "AuraTM AI Scribe recommends appropriate ICD-10 diagnosis codes and CPT "
                "procedure codes.\n\n"
                "## iOS App and Chrome Extension\n\n"
                "The Chrome extension stays within the same browser window as your EHR, "
                "providing an integrated view between your AI scribe notes and web-based EHR "
                "system without disruptive switching between applications."
            ),
        ),
        AURA_ANYWHERE_URL: OfficialSitePage(
            url=AURA_ANYWHERE_URL,
            title="Aura Anywhere",
            markdown=(
                "### Ambient Documentation\n\n"
                "AuraTM listens to patient-provider conversations and generates structured "
                "clinical notes in real time. Providers focus on the patient while documentation "
                "happens in the background.\n\n"
                "### Multi-Tenant Architecture\n\n"
                "Each organization operates in isolation with their own configurations, "
                "templates, and data boundaries."
            ),
        ),
        NEUROSURGERY_URL: OfficialSitePage(
            url=NEUROSURGERY_URL,
            title="Neurosurgery referral management",
            markdown=(
                "## Case Study: 15-Provider Neurosurgery Practice\n\n"
                "Key Challenges\n\n"
                "High volume of patient referrals (500+/month)\n\n"
                "Staff spending 20+ hours/week on phone screenings\n\n"
                "Inappropriate referrals consuming surgeon time\n\n"
                "20% no-show rate causing scheduling inefficiency\n\n"
                "Solution Implementation\n\n"
                "Results\n\n$350k\n\nAnnual Overhead Savings\n\n15 min\n\n"
                "Saved Per Consultation\n\n12x+\n\nReturn on Investment\n\n"
                '"For the first time my notes are actually done by the time my clinic is done. '
                'The Virtual Care Assistant has transformed our referral process."\n\n'
                "\\- Neurosurgeon, The Oregon Clinic"
            ),
        ),
    }


def _target() -> AccountDeepFixtureTarget:
    return AccountDeepFixtureTarget(
        canonical_name="New Jersey Brain and Spine",
        primary_domain="njbrainspine.com",
        linkedin_url="https://www.linkedin.com/company/new-jersey-brain-spine",
        source_url="https://njbrainspine.com/",
        hq_geo={
            "raw": "Paramus, New Jersey, United States",
            "city": "Paramus",
            "region": "New Jersey",
            "country": "United States",
            "country_code": "US",
        },
        aliases=("NJ Brain and Spine",),
        industry="Neurosurgery specialty practice",
        employee_count=36,
        revenue_band="10m_50m",
        icp_key="us_independent_neurosurgery_practices_r10_live",
        discovery_query=(
            "Independent U.S. neurosurgery practices with multiple providers and public "
            "referral, fax, scheduling, or patient-access workflows"
        ),
        must_have_criteria=(
            "U.S.-based independent neurosurgery specialty practice",
            "Not a general hospital or hospital-employed department",
            "Multiple providers and public evidence of referral or intake workflow",
        ),
    )


async def _confirm_direction(*, fixture: Any) -> Any:
    registry = ToolRegistry()
    for tool in build_research_directive_tools(
        memory_write_factory=lambda _conn: _DisabledMemory()
    ):
        registry.register(tool, make_default=tool.version == "2")
    body = ResearchDirectiveBody(
        account_scope=ResearchAccountScope(explicit_account_ids=(fixture.selected_account_id,)),
        field_keys=_ALL_FIELDS,
        questions=(
            ResearchQuestion(
                question_id="r10-operational-pain",
                text=(
                    "What attributable evidence shows referral, fax, phone, scheduling, "
                    "document-processing, or patient-access friction at this exact practice?"
                ),
                target_field_key="account.operational_pain",
                source_family_hints=("exa_deep",),
                priority=1,
            ),
            ResearchQuestion(
                question_id="r10-strategic-moves",
                text=(
                    "What recent services, locations, partnerships, hiring, or operational "
                    "changes are publicly attributable to this exact practice?"
                ),
                target_field_key="account.strategic_moves",
                source_family_hints=("exa_deep",),
                priority=2,
            ),
            ResearchQuestion(
                question_id="r10-hiring",
                text="What current hiring evidence indicates operational or technical workload?",
                target_field_key="account.hiring_velocity_eng",
                source_family_hints=("sumble_jobs", "exa_deep"),
                priority=2,
            ),
            ResearchQuestion(
                question_id="r10-buying-committee",
                text=(
                    "Which strongly identity-resolved people form the organization-wide buying "
                    "committee for this exact small practice across executive leadership, "
                    "operations, marketing, administration, technology, and finance?"
                ),
                target_facet="committee.buying_unit",
                source_family_hints=("sumble_people", "sumble_teams"),
                priority=1,
            ),
            ResearchQuestion(
                question_id="r10-contact-public-interest",
                text=(
                    "What recent attributable public post, publication, talk, professional "
                    "interest, or non-sensitive personal interest could support respectful "
                    "one-to-one messaging? Leave the field null if identity or attribution is weak."
                ),
                target_field_key=_CONTACT_FACET,
                source_family_hints=("exa_deep",),
                priority=1,
            ),
        ),
        committee_plan=ResearchCommitteePlan(
            functions=(
                "Executive",
                "Operations",
                "Marketing",
                "Administration",
                "Technology",
                "Finance",
            ),
            teams=(
                "New Patient Intake",
                "Billing",
                "Operations",
                "Administration",
                "Technology",
                "Finance",
            ),
            personas=("champion", "economic_buyer", "technical_evaluator", "blocker"),
            candidate_cap=3,
            relationship_depth=1,
        ),
        source_policy=ResearchSourcePolicy(
            allowed_source_keys=(
                "exa_deep",
                "sumble_jobs",
                "sumble_teams",
                "sumble_people",
            ),
            preferred_source_keys=("exa_deep", "sumble_people"),
        ),
        privacy_policy=ResearchPrivacyPolicy(
            contact_profiling_allowed=True,
            contact_reveals_allowed=False,
            exclusions=(
                "no patient-level facts",
                "no sensitive or inferred private personal attributes",
            ),
        ),
        effort_policy=ResearchEffortPolicy(
            tier="high",
            max_depth=2,
            max_fanout=6,
            budget_cap_cents=_ACCOUNT_BUDGET_CENTS,
            budget_envelope_ref="budget:m8d-r10-live-account",
            recursion_policy_ref="recursion:m8d-r10-live-v1",
            freshness_policy_ref="freshness:m8d-r10-live-v1",
        ),
    )
    draft_operation = new_operation_id()
    async with transaction() as conn:
        predecessor = await get_latest_research_directive(
            conn,
            workspace_id=fixture.discovery_fixture.workspace_id,
            project_id=fixture.discovery_fixture.project_id,
            product_id=fixture.discovery_fixture.product_id,
            icp_key=fixture.deep_icp_key,
            icp_version=fixture.deep_icp_version,
        )
    drafted = await invoke_tool(
        registry,
        "draft_account_research_directive",
        {
            "project_id": fixture.discovery_fixture.project_id,
            "product_id": fixture.discovery_fixture.product_id,
            "icp_key": fixture.deep_icp_key,
            "icp_version": fixture.deep_icp_version,
            "body": body.model_dump(mode="json"),
            "predecessor_id": (str(predecessor.directive_id) if predecessor is not None else None),
            "user_instruction": (
                "Research account workflow pain and strategic change first, then form a "
                "coherent buying committee for the exact small-practice organization. Treat "
                "the exact current employer as the organization-wide buying unit unless "
                "retained evidence proves a narrower office assignment; never guess office "
                "assignment from a person's profile metro. Do not start contact research "
                "automatically. "
                "After the separate contact approval, research only the selected people and "
                "retain only attributable public, non-sensitive personal facets."
            ),
            "source_turn_ref": "turn:m8d-r10-live-direction",
        },
        ToolContext(
            workspace_id=fixture.discovery_fixture.workspace_id,
            actor="agent",
            conn_factory=transaction,
            operation_id=draft_operation,
        ),
        idempotency_ttl_s=60,
    )
    await invoke_tool(
        registry,
        "confirm_account_research_directive",
        {
            "directive_id": str(draft_operation),
            "expected_sha256": drafted.references["canonical_json_sha256"],
        },
        ToolContext(
            workspace_id=fixture.discovery_fixture.workspace_id,
            actor="human",
            actor_id="human:m8d-r10-live-owner",
            action_ref="turn:m8d-r10-live-confirm",
            conn_factory=transaction,
            operation_id=new_operation_id(),
        ),
        idempotency_ttl_s=60,
    )
    async with transaction() as conn:
        specs = await confirmed_directive_account_specs(
            conn,
            workspace_id=fixture.discovery_fixture.workspace_id,
            directive_id=ResearchDirectiveId(draft_operation),
        )
    if len(specs) != 1 or specs[0].research_directive is None:
        raise RuntimeError("live direction did not produce one confirmed account directive")
    return specs[0]


def _pinned_settings(storage_root: Path) -> dict[str, Any]:
    """Every deployment knob this canary depends on, stated here rather than inherited."""

    return {
        "entity_research_runtime_enabled": True,
        "exa_account_deep_acquisition_enabled": True,
        "exa_contact_deep_acquisition_enabled": True,
        # The accepted Exa wire contract permits and defaults to 50.  A smaller cap can make a
        # structured deep response internally un-settleable when Exa grounds an answer in more
        # URLs than it retains in ``results[]``.  The live acceptance must exercise the actual
        # production cap rather than introduce a canary-only truncation failure.
        "exa_account_deep_max_results": 50,
        "sumble_account_gap_enrichment_enabled": True,
        "sumble_committee_acquisition_enabled": True,
        "sumble_committee_poll_after_s": 1,
        "contact_channel_enrichment_enabled": False,
        "storage_backend": "fs",
        "storage_fs_root": str(storage_root),
    }


def _environment_report(pinned: Mapping[str, Any]) -> dict[str, list[str]]:
    """Classify every ``CLUE_*`` variable this process offers the run.

    ``secrets`` are the named credentials the harness consumes on purpose; ``pinned`` are stated by
    :func:`_pinned_settings` and therefore not taken from the environment; ``suppressed`` are other
    real ``Settings`` fields the environment would otherwise have set for the canary; ``ignored``
    are neither (another component's variable — most often a provider key this run never uses).
    """

    report: dict[str, list[str]] = {"secrets": [], "pinned": [], "suppressed": [], "ignored": []}
    for name in sorted(value for value in os.environ if value.startswith("CLUE_")):
        field = name.removeprefix("CLUE_").lower()
        if name in _NAMED_SECRET_ENV:
            report["secrets"].append(name)
        elif field in pinned:
            report["pinned"].append(name)
        elif field in Settings.model_fields:
            report["suppressed"].append(name)
        else:
            report["ignored"].append(name)
    return report


def _settings(storage_root: Path) -> tuple[Settings, dict[str, list[str]]]:
    """Construct the canary's settings explicitly, and record what the environment offered.

    The harness states the knobs it depends on and takes everything else from library defaults: the
    repo ``.env`` is not read (``_env_file=None``) and every other ``CLUE_*`` settings variable in
    the process environment is withheld for the duration of the construction. Two failures motivate
    this. A malformed unrelated variable used to abort the whole ``Settings`` object before a single
    call was made, and an ambient knob left over from an unrelated session silently changed what the
    "production composition" under test actually was.

    Credentials are the deliberate exception: :class:`Secrets` still reads the environment/``.env``,
    which is where the named live keys are supposed to live. A library that re-reads the environment
    on its own (``default_gateway_config`` and its model ids) is likewise outside this seam — the
    returned report names every variable so neither exception is invisible.
    """

    pinned = _pinned_settings(storage_root)
    report = _environment_report(pinned)
    withheld = {name: os.environ.pop(name) for name in (*report["pinned"], *report["suppressed"])}
    try:
        return Settings(_env_file=None, **pinned), report
    finally:
        os.environ.update(withheld)


def _composition(*, settings: Settings, secrets: Secrets, storage: FsStorage) -> Any:
    gateway_config = default_gateway_config()
    composition = build_production_entity_research_fleet(
        settings=settings,
        secrets=secrets,
        storage=storage,
        models=build_agent_model_provider(config=gateway_config, secrets=secrets),
        gateway=build_platform_gateway(settings),
        gateway_config=gateway_config,
        pre_spend_gate=build_pre_spend_gate(),
    )
    if composition is None:
        raise RuntimeError("R10 production entity research composition is disabled")
    return composition


def _wake_dispatcher(settings: Settings) -> ExternalResearchWakeDispatcher:
    wakes = EntityResearchBatchWakeService()

    async def wake_member(wait_ref: str) -> int:
        return await wakes.notify_member_ready(wait_ref, actor="m8d-r10-live-due")

    async def no_project_widening(_project_run_id: Any) -> bool:
        return False

    return ExternalResearchWakeDispatcher(
        project_run_waker=no_project_widening,
        sources=(),
        entity_member_waker=wake_member,
        entity_wait_sources=registered_entity_research_wait_sources(
            committee_enabled=settings.sumble_committee_acquisition_enabled,
            contact_external_enabled=settings.exa_contact_deep_acquisition_enabled,
            contact_channel_enabled=False,
        ),
    )


async def _task_counts(run_id: UUID) -> dict[str, int]:
    async with transaction() as conn:
        row = (
            (
                await conn.execute(
                    text(
                        "SELECT count(*) FILTER (WHERE status='queued') AS queued, "
                        "count(*) FILTER (WHERE status='claimed') AS claimed, "
                        "count(*) FILTER (WHERE status='failed') AS failed FROM fleet_task "
                        "WHERE kind='entity_research_job' AND work_id IN "
                        "(SELECT job_id FROM entity_research_job WHERE research_run_id=:run_id)"
                    ),
                    {"run_id": run_id},
                )
            )
            .mappings()
            .one()
        )
    return {key: int(row[key] or 0) for key in ("queued", "claimed", "failed")}


async def _drive(
    *,
    settings: Settings,
    secrets: Secrets,
    storage: FsStorage,
    run_id: UUID,
    workspace_id: str,
    kind: str,
    timeout_seconds: float,
) -> tuple[Any, int]:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout_seconds
    cold_restarts = 0
    idle_rounds = 0
    composition = _composition(settings=settings, secrets=secrets, storage=storage)
    worker = LeasedWorkWorker(
        handlers=(composition.handler,),
        queue=DbWorkQueue(),
        worker_id=f"m8d-r10-live:{kind}:{uuid4()}",
        poll_interval=0.1,
    )
    wake = _wake_dispatcher(settings)
    while loop.time() < deadline:
        projection = (
            await composition.accounts.fleets.read(run_id, workspace_id=workspace_id)
            if kind == "account"
            else await composition.contacts.fleets.read(run_id, workspace_id=workspace_id)
        )
        if projection is None:
            raise RuntimeError(f"{kind} research projection disappeared")
        terminal = (
            projection.terminal_accounts == projection.selected_accounts
            if kind == "account"
            else projection.terminal_count == len(projection.selected_contact_ids)
        )
        if terminal:
            return projection, cold_restarts
        drained = await worker.drain_once()
        woken = await wake.run_due()
        if drained or woken:
            idle_rounds = 0
        else:
            idle_rounds += 1
        waiting = (
            projection.waiting_accounts > 0 if kind == "account" else projection.waiting_count > 0
        )
        if waiting:
            # Exercise the promised fresh-process resume boundary instead of retaining in-memory
            # provider bindings across an external wait.
            composition = _composition(settings=settings, secrets=secrets, storage=storage)
            worker = LeasedWorkWorker(
                handlers=(composition.handler,),
                queue=DbWorkQueue(),
                worker_id=f"m8d-r10-live:{kind}:restart:{uuid4()}",
                poll_interval=0.1,
            )
            cold_restarts += 1
        if idle_rounds >= 10:
            counts = await _task_counts(run_id)
            if counts["queued"] == 0 and not waiting:
                raise RuntimeError(
                    f"{kind} fleet has no runnable task before terminal state: "
                    f"tasks={counts}, projection={projection.model_dump(mode='json')}"
                )
        await asyncio.sleep(0.5)
    raise TimeoutError(f"{kind} live fleet exceeded {timeout_seconds}s")


async def _committee_selection(
    *,
    account_projection: Any,
    fixture: Any,
) -> Any:
    job = account_projection.jobs[0]
    contact_ids = tuple(EntityId(value) for value in job.committee_member_ids[:3])
    if not contact_ids:
        raise RuntimeError("live account agent returned no identity-resolved committee member")
    async with transaction() as conn:
        claim_ids = tuple(
            ClaimId(value)
            for value in (
                await conn.execute(
                    text(
                        "SELECT id FROM claim WHERE run_id=:account_run_id "
                        "AND research_mode='committee_discovery' AND entity_id=ANY(:contacts) "
                        "ORDER BY observed_at, id"
                    ),
                    {
                        "account_run_id": job.account_run_id,
                        "contacts": [UUID(str(value)) for value in contact_ids],
                    },
                )
            ).scalars()
        )
    initial = await ContactResearchSelectionMaterializer().materialize(
        workspace_id=fixture.discovery_fixture.workspace_id,
        project_run_id=fixture.project_run_id,
        account_run_id=job.account_run_id,
        account_entity_id=fixture.selected_account_id,
        contact_entity_ids=contact_ids,
        committee_claim_ids=claim_ids,
    )
    if initial is None or not initial.body.targets:
        raise RuntimeError(
            "live committee did not yield a strongly bound plausible persona eligible for "
            "separate contact selection"
        )
    targets = tuple(
        ContactResearchTargetApproval(
            contact_entity_id=UUID(str(target.contact_entity_id)),
            selection_basis=ResearchSelectionBasis.COMMITTEE_MEMBER,
            strong_identity_claim_ids=tuple(
                UUID(str(value)) for value in target.strong_identity_claim_ids
            ),
            association_evidence_claim_ids=tuple(
                UUID(str(value)) for value in target.effective_association_evidence_claim_ids
            ),
            committee_claim_ids=tuple(UUID(str(value)) for value in target.committee_claim_ids),
            field_keys=tuple(str(value) for value in target.field_keys),
            field_source_authority=tuple(
                FieldSourceAuthority.model_validate(value)
                for value in target.field_source_authority
            ),
            directional_question_ids=target.directional_question_ids,
            facet_keys=tuple(str(value) for value in target.effective_facet_keys),
            # The accepted contact wire contract is 50 (clue_core.contact_research caps it); a
            # canary-only truncation cap reproduced the account-side "citations outside retained
            # results[]" settlement failure and must never be reintroduced.
            exa_max_results=target.exa_max_results,
            budget_cap_cents=_CONTACT_BUDGET_CENTS,
        )
        for target in initial.body.targets[:3]
    )
    approved_at = datetime.now(UTC)
    approved = await ContactResearchSelectionApprover().approve(
        ContactResearchSelectionApprovalRequest(
            workspace_id=fixture.discovery_fixture.workspace_id,
            project_run_id=UUID(str(fixture.project_run_id)),
            account_run_id=UUID(str(job.account_run_id)),
            account_entity_id=UUID(str(fixture.selected_account_id)),
            targets=targets,
        ),
        approved_by="human:m8d-r10-live-owner",
        action_ref="turn:m8d-r10-live-contact-selection",
        approval_operation_id=uuid4(),
        approved_at=approved_at,
    )
    return approved, approved_at


async def _ledger(*, account_run_id: UUID, contact_run_id: UUID) -> dict[str, Any]:
    async with transaction() as conn:
        row = (
            (
                await conn.execute(
                    text(
                        """
                        SELECT
                          (SELECT count(*) FROM entity_research_tool_request
                           WHERE research_run_id IN (:account_run_id, :contact_run_id))
                            tool_requests,
                          (SELECT count(DISTINCT operation.operation_ref)
                           FROM entity_research_provider_operation operation
                           JOIN entity_research_provider_observation observation
                             ON observation.provider_operation_ref=operation.operation_ref
                           JOIN entity_research_tool_request request_row
                             ON request_row.tool_request_id=observation.tool_request_id
                           WHERE request_row.research_run_id IN
                             (:account_run_id, :contact_run_id)) provider_operations,
                          (SELECT count(DISTINCT observation.provider_operation_ref)
                           FROM entity_research_provider_observation observation
                           JOIN entity_research_tool_request request_row
                             ON request_row.tool_request_id=observation.tool_request_id
                           WHERE request_row.research_run_id IN
                             (:account_run_id, :contact_run_id)
                             AND observation.disposition='caused') caused_operations,
                          (SELECT count(*) FROM entity_research_result result
                           JOIN entity_research_tool_request request_row
                             ON request_row.tool_request_id=result.tool_request_id
                           WHERE request_row.research_run_id IN
                             (:account_run_id, :contact_run_id)) results,
                          (SELECT count(*) FROM entity_research_result_field field_row
                           JOIN entity_research_result result USING (result_id)
                           JOIN entity_research_tool_request request_row
                             ON request_row.tool_request_id=result.tool_request_id
                           WHERE request_row.research_run_id IN
                             (:account_run_id, :contact_run_id)) result_fields,
                          (SELECT count(*) FROM entity_research_result_evidence evidence
                           JOIN entity_research_result_field field_row
                             ON field_row.result_id=evidence.result_id
                            AND field_row.ordinal=evidence.field_ordinal
                           JOIN entity_research_result result USING (result_id)
                           JOIN entity_research_tool_request request_row
                             ON request_row.tool_request_id=result.tool_request_id
                           WHERE request_row.research_run_id IN
                             (:account_run_id, :contact_run_id)) evidence_rows,
                          (SELECT count(*) FROM entity_research_agent_event event_row
                           JOIN entity_research_agent_turn turn_row USING (agent_turn_id)
                           WHERE turn_row.research_run_id IN
                             (:account_run_id, :contact_run_id)) agent_events,
                          (SELECT count(DISTINCT operation.operation_ref)
                           FROM entity_research_provider_operation operation
                           JOIN entity_research_provider_observation observation
                             ON observation.provider_operation_ref=operation.operation_ref
                           JOIN entity_research_tool_request request_row
                             ON request_row.tool_request_id=observation.tool_request_id
                           WHERE request_row.research_run_id IN
                             (:account_run_id, :contact_run_id)
                             AND operation.provider_kind='external_research') exa_operations,
                          (SELECT count(DISTINCT operation.operation_ref)
                           FROM entity_research_provider_operation operation
                           JOIN entity_research_provider_observation observation
                             ON observation.provider_operation_ref=operation.operation_ref
                           JOIN entity_research_tool_request request_row
                             ON request_row.tool_request_id=observation.tool_request_id
                           WHERE request_row.research_run_id=:account_run_id
                             AND operation.provider_kind='sumble_account')
                            sumble_account_operations,
                          (SELECT count(DISTINCT operation.operation_ref)
                           FROM entity_research_provider_operation operation
                           JOIN entity_research_provider_observation observation
                             ON observation.provider_operation_ref=operation.operation_ref
                           JOIN entity_research_tool_request request_row
                             ON request_row.tool_request_id=observation.tool_request_id
                           WHERE request_row.research_run_id=:account_run_id
                             AND operation.provider_kind='sumble_committee')
                            sumble_committee_operations,
                          (SELECT COALESCE(sum(spent_cents), 0) FROM entity_research_run
                           WHERE research_run_id IN
                             (:account_run_id, :contact_run_id)) entity_spent_cents
                        """
                    ),
                    {"account_run_id": account_run_id, "contact_run_id": contact_run_id},
                )
            )
            .mappings()
            .one()
        )
        provider_usage = (
            (
                await conn.execute(
                    text(
                        "SELECT 'exa_reported_cost_cents' meter, "
                        "COALESCE(sum(receipt.provider_reported_cost_cents), 0) value "
                        "FROM external_research_receipt receipt "
                        "WHERE EXISTS (SELECT 1 "
                        "FROM entity_research_provider_observation observation "
                        "JOIN entity_research_tool_request request_row "
                        "ON request_row.tool_request_id=observation.tool_request_id "
                        "WHERE observation.provider_operation_ref="
                        "'external-research-operation:'||receipt.operation_id::text "
                        "AND request_row.research_run_id IN "
                        "(:account_run_id, :contact_run_id)) UNION ALL "
                        "SELECT 'sumble_account_units', "
                        "COALESCE(sum(source_operation.provider_units_charged), 0) "
                        "FROM account_gap_operation source_operation "
                        "WHERE EXISTS (SELECT 1 "
                        "FROM entity_research_provider_observation observation "
                        "JOIN entity_research_tool_request request_row "
                        "ON request_row.tool_request_id=observation.tool_request_id "
                        "WHERE observation.provider_operation_ref="
                        "'sumble-account-operation:'||source_operation.id::text "
                        "AND request_row.research_run_id=:account_run_id) UNION ALL "
                        "SELECT 'sumble_committee_units', "
                        "COALESCE(sum(source_operation.provider_units_charged), 0) "
                        "FROM committee_acquisition_operation source_operation "
                        "WHERE EXISTS (SELECT 1 "
                        "FROM entity_research_provider_observation observation "
                        "JOIN entity_research_tool_request request_row "
                        "ON request_row.tool_request_id=observation.tool_request_id "
                        "WHERE observation.provider_operation_ref="
                        "'committee-operation:'||source_operation.id::text "
                        "AND request_row.research_run_id=:account_run_id)"
                    ),
                    {"account_run_id": account_run_id, "contact_run_id": contact_run_id},
                )
            )
            .mappings()
            .all()
        )
    return {
        **{
            key: str(value) if key == "entity_spent_cents" else int(value)
            for key, value in row.items()
        },
        "provider_usage": {str(item["meter"]): str(item["value"]) for item in provider_usage},
    }


async def _account_resume_context(
    research_run_id: UUID,
) -> tuple[SimpleNamespace, AccountResearchFleetLaunchRequest, UUID, UUID]:
    """Rebuild one exact account canary's durable launch authority.

    Nothing is reseeded and no new authorization is issued: the fixture identity, the launch
    request, its originating operation id, and the single job id all come from the rows the first
    launch already committed.
    """

    async with transaction() as conn:
        row = (
            (
                await conn.execute(
                    text(
                        "SELECT fleet.source_operation_id, fleet.source_action_ref, "
                        "fleet.workspace_id, fleet.project_id, fleet.product_id, "
                        "fleet.project_run_id, fleet.supervisor_policy_json, "
                        "run.budget_cap_cents, job.job_id, job.subject_entity_id, "
                        "job.authorization_json FROM entity_research_account_fleet fleet "
                        "JOIN entity_research_run run USING (research_run_id) JOIN "
                        "entity_research_job job USING (research_run_id) WHERE "
                        "fleet.research_run_id=:run_id"
                    ),
                    {"run_id": research_run_id},
                )
            )
            .mappings()
            .one_or_none()
        )
    if row is None:
        raise RuntimeError("resume account run is absent or is not an exact one-job canary")
    selection = dict(row["authorization_json"])["selection"]
    directive_ref = str(selection["directive_ref"])
    directive_parts = directive_ref.split(":")
    if len(directive_parts) != 3 or directive_parts[0] != "research-directive":
        raise RuntimeError("resume account run has a malformed directive reference")
    if Decimal(str(row["budget_cap_cents"])) != _ACCOUNT_BUDGET_CENTS:
        raise RuntimeError("resume account run differs from the bounded live budget")
    fixture = SimpleNamespace(
        discovery_fixture=SimpleNamespace(
            workspace_id=str(row["workspace_id"]),
            project_id=str(row["project_id"]),
            product_id=str(row["product_id"]),
        ),
        project_run_id=UUID(str(row["project_run_id"])),
        selected_account_id=UUID(str(row["subject_entity_id"])),
    )
    launch_request = AccountResearchFleetLaunchRequest(
        workspace_id=fixture.discovery_fixture.workspace_id,
        project_run_id=fixture.project_run_id,
        research_directive_id=UUID(directive_parts[1]),
        account_entity_ids=(fixture.selected_account_id,),
        approved_budget_cap_cents=_ACCOUNT_BUDGET_CENTS,
        expected_estimated_cost_cents=_ACCOUNT_BUDGET_CENTS,
        concurrency_limit=1,
        supervisor_policy=AccountResearchFleetPolicy.model_validate(row["supervisor_policy_json"]),
    )
    return (
        fixture,
        launch_request,
        UUID(str(row["source_operation_id"])),
        UUID(str(row["job_id"])),
    )


async def _contact_resume_context(research_run_id: UUID) -> tuple[Any, UUID]:
    """Read one contact canary's durable launch row and the account run that authorized it.

    The contact fleet has no admission-control surface to un-pause (unlike the account fleet), so
    resuming is exactly this: replay the committed launch action verbatim — same request, same
    operation id, same confirmation instant — which re-admits the run without approving a new
    selection or authorizing new spend, then drive the still-open jobs.
    """

    async with transaction() as conn:
        launch = (
            (
                await conn.execute(
                    text(
                        "SELECT workspace_id, project_run_id, account_entity_id, "
                        "contact_selection_id, source_operation_id, source_action_ref, "
                        "launched_by, confirmed_at, request_json FROM "
                        "entity_research_contact_launch WHERE research_run_id=:run_id"
                    ),
                    {"run_id": research_run_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if launch is None:
            raise RuntimeError("resume contact run has no durable launch authorization")
        account_run_ids = (
            (
                await conn.execute(
                    text(
                        "SELECT fleet.research_run_id FROM entity_research_account_fleet fleet "
                        "JOIN entity_research_job job USING (research_run_id) WHERE "
                        "fleet.workspace_id=:workspace_id "
                        "AND fleet.project_run_id=:project_run_id "
                        "AND job.subject_entity_id=:account_entity_id"
                    ),
                    {
                        "workspace_id": launch["workspace_id"],
                        "project_run_id": launch["project_run_id"],
                        "account_entity_id": launch["account_entity_id"],
                    },
                )
            )
            .scalars()
            .all()
        )
    if len(set(account_run_ids)) != 1:
        raise RuntimeError("resume contact run does not map to exactly one account canary")
    return launch, UUID(str(account_run_ids[0]))


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    if not args.allow_live_provider_calls:
        raise RuntimeError("live provider acknowledgement is required")
    secrets = Secrets()
    missing = [
        name
        for name, value in (
            ("CLUE_OPENROUTER_API_KEY", secrets.openrouter_api_key),
            ("CLUE_EXA_API_KEY", secrets.exa_api_key),
            ("CLUE_SUMBLE_API_KEY", secrets.sumble_api_key),
        )
        if value is None
    ]
    if missing:
        raise RuntimeError("missing live credentials: " + ", ".join(missing))
    async with transaction() as conn:
        project_count_value = (
            await conn.execute(text("SELECT count(*) FROM project_run"))
        ).scalar_one()
        project_count = int(project_count_value)
    resume_modes = [
        name
        for name, selected in (
            ("--resume-seeded", args.resume_seeded),
            ("--resume-account-run", args.resume_account_run is not None),
            ("--resume-contact-run", args.resume_contact_run is not None),
        )
        if selected
    ]
    if len(resume_modes) > 1:
        raise RuntimeError("resume modes are mutually exclusive: " + ", ".join(resume_modes))
    if project_count and not resume_modes:
        raise RuntimeError("R10 live acceptance requires a fresh isolated database")
    if project_count and args.resume_account_run is None and args.resume_contact_run is None:
        async with transaction() as conn:
            unsafe = (
                await conn.execute(
                    text(
                        "SELECT (SELECT count(*) FROM entity_research_job) + "
                        "(SELECT count(*) FROM entity_research_provider_operation) + "
                        "(SELECT count(*) FROM external_research_operation) + "
                        "(SELECT count(*) FROM account_gap_operation) + "
                        "(SELECT count(*) FROM committee_acquisition_operation)"
                    )
                )
            ).scalar_one()
            if int(unsafe):
                raise RuntimeError(
                    "--resume-seeded refuses a database with entity work or provider operations"
                )
            phase = (
                await conn.execute(
                    text("SELECT phase::text FROM project_run WHERE id=:project_run_id"),
                    {"project_run_id": PROJECT_RUN_ID},
                )
            ).scalar_one()
            if str(phase) == "scoring":
                await conn.execute(
                    text("UPDATE project_run SET phase='tier_checkpoint' WHERE id=:project_run_id"),
                    {"project_run_id": PROJECT_RUN_ID},
                )
            await conn.execute(
                text("UPDATE project_run SET phase='deep' WHERE id=:project_run_id"),
                {"project_run_id": PROJECT_RUN_ID},
            )

    settings, environment = _settings(args.storage_root)
    print(json.dumps({"clue_environment": environment}, indent=2, sort_keys=True))
    if environment["suppressed"]:
        print(
            "warning: these CLUE settings variables were withheld from the canary composition: "
            + ", ".join(environment["suppressed"])
        )
    storage = FsStorage(args.storage_root)
    composition = _composition(settings=settings, secrets=secrets, storage=storage)
    account_restarts = 0
    # Either the seeded fixture result or its durable reconstruction; both are read structurally.
    fixture: Any
    if args.resume_contact_run is not None:
        launch_row, account_research_run_id = await _contact_resume_context(args.resume_contact_run)
        fixture, launch_request, account_launch_operation, _ = await _account_resume_context(
            account_research_run_id
        )
        account_launch = SimpleNamespace(research_run_id=account_research_run_id)
        resumed_account = await composition.accounts.fleets.read(
            account_research_run_id,
            workspace_id=fixture.discovery_fixture.workspace_id,
        )
        if (
            resumed_account is None
            or resumed_account.terminal_accounts != resumed_account.selected_accounts
        ):
            raise RuntimeError("contact resume requires an already terminal account canary")
        account_projection = resumed_account
        contact_request = ContactResearchFleetLaunchRequest.model_validate(
            launch_row["request_json"]
        )
        contact_launch_operation = UUID(str(launch_row["source_operation_id"]))
        contact_action_ref = str(launch_row["source_action_ref"])
        contact_actor = str(launch_row["launched_by"])
        contact_confirmed_at = launch_row["confirmed_at"]
        contact_budget = contact_request.approved_budget_cap_cents
    else:
        if args.resume_account_run is not None:
            (
                fixture,
                launch_request,
                account_launch_operation,
                account_job_id,
            ) = await _account_resume_context(args.resume_account_run)
            await composition.accounts.fleets.resume_job(
                account_job_id,
                workspace_id=fixture.discovery_fixture.workspace_id,
                actor=_LIVE_ACTOR,
            )
            account_launch = SimpleNamespace(research_run_id=args.resume_account_run)
            account_restarts = 1
        else:
            async with transaction() as conn:
                fixture = await seed_insight_health_account_deep_fixture(
                    conn,
                    pages=(None if args.resume_seeded else _pages()),
                    storage=storage,
                    target=_target(),
                    deep_field_keys=_ALL_FIELDS,
                    reuse_existing_stage0=args.resume_seeded,
                )
            account_spec = await _confirm_direction(fixture=fixture)
            pin = account_spec.research_directive
            assert pin is not None
            # Prove the entity run is independently action-authorized: the outer project is not
            # left at the superseded mechanical DEEP pipeline phase.
            async with transaction() as conn:
                await conn.execute(
                    text("UPDATE project_run SET phase='scoring' WHERE id=:project_run_id"),
                    {"project_run_id": fixture.project_run_id},
                )
                run = (
                    await conn.execute(
                        text("SELECT status::text FROM project_run WHERE id=:project_run_id"),
                        {"project_run_id": fixture.project_run_id},
                    )
                ).scalar_one()
                if str(run) != ProjectRunStatus.ACTIVE.value:
                    raise RuntimeError("synthetic project run is not active")
            account_launch_operation = uuid4()
            launch_request = AccountResearchFleetLaunchRequest(
                workspace_id=fixture.discovery_fixture.workspace_id,
                project_run_id=UUID(str(fixture.project_run_id)),
                research_directive_id=UUID(str(pin.directive_id)),
                account_entity_ids=(UUID(str(fixture.selected_account_id)),),
                approved_budget_cap_cents=_ACCOUNT_BUDGET_CENTS,
                expected_estimated_cost_cents=_ACCOUNT_BUDGET_CENTS,
                concurrency_limit=1,
                supervisor_policy=AccountResearchFleetPolicy(canary_size=1),
            )
            account_launch = await composition.accounts.launcher.launch(
                launch_request,
                actor=_LIVE_ACTOR,
                source_action_ref=_ACCOUNT_LAUNCH_ACTION_REF,
                source_operation_id=account_launch_operation,
            )
        account_projection, account_restarts = await _drive(
            settings=settings,
            secrets=secrets,
            storage=storage,
            run_id=account_launch.research_run_id,
            workspace_id=fixture.discovery_fixture.workspace_id,
            kind="account",
            timeout_seconds=args.timeout_seconds,
        )
        account_restarts += 1 if args.resume_account_run is not None else 0
        if account_projection.contact_research_request_count != 0:
            raise RuntimeError("account fleet started contact research")
        if not account_projection.jobs[0].finalization_receipt_ref:
            raise RuntimeError("account job ended without an engine finalization receipt")

        selection, selected_at = await _committee_selection(
            account_projection=account_projection,
            fixture=fixture,
        )
        contact_budget = selection.body.execution_budget_cap_cents
        contact_launch_operation = uuid4()
        contact_action_ref = _CONTACT_LAUNCH_ACTION_REF
        contact_actor = _LIVE_ACTOR
        contact_confirmed_at = max(datetime.now(UTC), selected_at)
        contact_request = ContactResearchFleetLaunchRequest(
            workspace_id=fixture.discovery_fixture.workspace_id,
            selection_id=UUID(str(selection.selection_id)),
            selection_sha256=selection.selection_sha256,
            approved_budget_cap_cents=contact_budget,
            expected_estimated_cost_cents=contact_budget,
            concurrency_limit=min(3, len(selection.body.targets)),
        )

    if _ACCOUNT_BUDGET_CENTS + contact_budget > _TOTAL_BUDGET_CENTS:
        raise RuntimeError("combined live entity budget exceeds the authorized $20 cap")
    contact_launch = await composition.contacts.launcher.launch(
        contact_request,
        actor=contact_actor,
        source_action_ref=contact_action_ref,
        source_operation_id=contact_launch_operation,
        confirmed_at=contact_confirmed_at,
    )
    if (
        args.resume_contact_run is not None
        and contact_launch.research_run_id != args.resume_contact_run
    ):
        raise RuntimeError("contact resume replayed its launch into a different run")
    contact_projection, contact_restarts = await _drive(
        settings=settings,
        secrets=secrets,
        storage=storage,
        run_id=contact_launch.research_run_id,
        workspace_id=fixture.discovery_fixture.workspace_id,
        kind="contact",
        timeout_seconds=args.timeout_seconds,
    )
    if contact_projection.unselected_contact_request_count:
        raise RuntimeError("contact fleet widened beyond the exact selected set")
    if any(not job.finalization_receipt_ref for job in contact_projection.jobs):
        raise RuntimeError("a contact job ended without an engine finalization receipt")

    ledger_before = await _ledger(
        account_run_id=account_launch.research_run_id,
        contact_run_id=contact_launch.research_run_id,
    )
    # Reconstruct the full production composition as a fresh process would, replay both exact
    # launch actions, and prove the provider/cost ledger is unchanged.
    replay_composition = _composition(settings=settings, secrets=secrets, storage=storage)
    account_replay = await replay_composition.accounts.launcher.launch(
        launch_request,
        actor=_LIVE_ACTOR,
        source_action_ref=_ACCOUNT_LAUNCH_ACTION_REF,
        source_operation_id=account_launch_operation,
    )
    contact_replay = await replay_composition.contacts.launcher.launch(
        contact_request,
        actor=contact_actor,
        source_action_ref=contact_action_ref,
        source_operation_id=contact_launch_operation,
        confirmed_at=contact_confirmed_at,
    )
    ledger_after = await _ledger(
        account_run_id=account_launch.research_run_id,
        contact_run_id=contact_launch.research_run_id,
    )
    if account_replay.research_run_id != account_launch.research_run_id:
        raise RuntimeError("account launch replay created a new run")
    if contact_replay.research_run_id != contact_launch.research_run_id:
        raise RuntimeError("contact launch replay created a new run")
    if ledger_after != ledger_before:
        raise RuntimeError("fresh-composition replay changed provider or spend ledgers")
    if ledger_before["provider_operations"] < 3 or ledger_before["caused_operations"] < 3:
        raise RuntimeError("live canary did not cause both Exa and Sumble provider work")
    if ledger_before["results"] < 3 or ledger_before["evidence_rows"] < 1:
        raise RuntimeError("live canary did not persist structured results and evidence")

    return {
        "contract": "m8d-r10-live-acceptance-v1",
        "completed_at": datetime.now(UTC).isoformat(),
        "database": {
            "fresh_isolated": not resume_modes,
            "resume_mode": resume_modes[0] if resume_modes else None,
            "project_run_id": str(fixture.project_run_id),
        },
        "environment": environment,
        "target": {
            "account_entity_id": str(fixture.selected_account_id),
            "domain": _target().primary_domain,
        },
        "account": account_projection.model_dump(mode="json"),
        "contact": contact_projection.model_dump(mode="json"),
        "separate_contact_selection": {
            "selection_id": str(contact_request.selection_id),
            "selected_contact_count": len(contact_projection.selected_contact_ids),
            "channels_requested": False,
            "validator_bypass_used": False,
        },
        "cold_resume": {
            "account_recompositions": account_restarts,
            "contact_recompositions": contact_restarts,
        },
        "ledger": ledger_before,
        "replay": {
            "fresh_composition": True,
            "same_account_run": True,
            "same_contact_run": True,
            "provider_and_spend_ledger_unchanged": True,
        },
        "authorized_budget_cents": {
            "account": str(_ACCOUNT_BUDGET_CENTS),
            "contact": str(contact_budget),
            "combined": str(_ACCOUNT_BUDGET_CENTS + contact_budget),
            "hard_cap": str(_TOTAL_BUDGET_CENTS),
        },
        "channel_validation": {
            "status": "not_run_no_independent_validator_composed",
            "fail_closed": True,
        },
    }


async def _entry(args: argparse.Namespace) -> dict[str, Any]:
    os.environ[DATABASE_URL_ENV] = args.database_url
    async with db_lifespan(args.database_url):
        return await _run(args)


def main() -> None:
    args = _args()
    report = asyncio.run(_entry(args))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
