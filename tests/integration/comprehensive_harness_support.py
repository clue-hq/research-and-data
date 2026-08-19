"""Seeding support for the comprehensive account-research proof harness.

The founder's ratified success criterion for comprehensive Account research is mechanical: **five
Accounts end to end, three times consecutively, with zero manual database intervention**. Proving
it needs a sealed discovery generation containing *five* accounts, which the single-account A1
fixture (``clue_api.trial.account_deep_fixture``) cannot produce: its batch id, plan id, operation
id and item id are module constants and its sealed-manifest check asserts exactly one account.

This module therefore reuses the A1 fixture for everything above discovery — the Stage-0 client
knowledge base, the healthcare deep ICP and its source override, the product context, and the
``DISCOVERY_SPEND`` readiness decision — and then seeds, per cycle, a **fresh project run with its
own first-generation discovery batch holding five accounts**, sealed through the same durable
repository calls the fixture uses. A fresh run per cycle is the only shape the substrate admits:
``create_discovery_batch`` refuses to replace a sealed generation
(``clue_research/durable/discovery.py:541``), so a second five-account seal cannot live on the
same run.

Nothing here fakes a provider. Discovery membership, required-field resolutions, manifests and the
seal are all written through the production durable API, so the launcher's receipt-pinning path
validates real immutable state.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

from pydantic import JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.discovery_seal import build_discovery_batch_manifest
from clue_api.research_directive_tools import build_research_directive_tools
from clue_api.stage0_tools import start_confirmed_project_run
from clue_api.trial.account_deep_fixture import (
    READINESS_DECISION_ID,
    InsightHealthAccountDeepFixtureResult,
)
from clue_api.trial.discovery_fixture import PRODUCT_ID, PROJECT_ID, WORKSPACE_ID
from clue_core import (
    ClaimId,
    DiscoveryBatchId,
    DiscoveryBatchState,
    DiscoveryCandidateAdmissionState,
    DiscoveryCriterionPlan,
    DiscoveryEntityKind,
    DiscoveryFieldResolution,
    DiscoveryFieldResolutionState,
    DiscoveryItemSnapshot,
    DiscoveryItemSnapshotId,
    DiscoveryOperation,
    DiscoveryOperationId,
    DiscoveryOperationState,
    DiscoveryPageReceipt,
    DiscoveryPageResource,
    DiscoveryPlan,
    DiscoveryPlanId,
    DiscoverySearchPlan,
    DiscoverySpendOutcome,
    EntityId,
    EntityType,
    ExtractionMethod,
    MemoryDisabled,
    MemorySubmission,
    ProductContextVersionId,
    ProjectPhase,
    ProjectRunId,
    ResearchAccountScope,
    ResearchCommitteePlan,
    ResearchDirectiveBody,
    ResearchDirectiveId,
    ResearchEffortPolicy,
    ResearchMode,
    ResearchPrivacyPolicy,
    ResearchQuestion,
    ResearchSourcePolicy,
    RunId,
    account_claim,
    discovery_claim,
    discovery_provider_external_id,
    new_operation_id,
    new_run_id,
    revalidate_with,
)
from clue_research.claimstore import insert_claim
from clue_research.directives import confirmed_directive_account_specs
from clue_research.discovery_scoring import DISCOVERY_ENVELOPE_POLICY_V1
from clue_research.durable import (
    PhaseCheckpointStatus,
    ProjectRunStatus,
    capture_discovery_artifact,
    create_discovery_batch,
    index_account_discovery_artifacts,
    link_discovery_page_item,
    lock_discovery_batch_for_materialization,
    mark_discovery_operation_reconciled,
    normalize_discovery_item,
    put_discovery_candidate_link,
    put_discovery_field_resolution,
    put_discovery_item,
    put_discovery_operation,
    put_discovery_page,
    put_discovery_plan,
    reconcile_discovery_batch_costs,
    seal_discovery_batch,
    update_discovery_batch_state,
    update_discovery_operation,
    upsert_checkpoint,
)
from clue_research.durable.project_run import set_phase
from clue_research.identity import insert_account_entity
from clue_research.narrative.prose import PROSE_ACCOUNT_FIELDS
from clue_storage import StorageBackend, content_address
from clue_toolbelt import ToolContext, ToolRegistry, invoke_tool
from tests.profiling.conftest import conn_session_factory

#: The five synthetic gastroenterology practices one harness cycle discovers. Each is a distinct
#: workspace-local account with its own domain, so a cycle's accounts never collide with another
#: cycle's (account strong keys are ``(workspace_id, domain)`` — the [B3×research] scoping).
ACCOUNT_PROFILES: tuple[Mapping[str, Any], ...] = (
    {
        "slug": "cascade",
        "name": "Cascade Gastroenterology Associates",
        "industry": "Gastroenterology specialty practice",
        "employee_count": 42,
        "revenue_band": "10m_50m",
        "city": "Portland",
        "region": "Oregon",
    },
    {
        "slug": "puget",
        "name": "Puget Sound Digestive Health",
        "industry": "Gastroenterology specialty practice",
        "employee_count": 118,
        "revenue_band": "10m_50m",
        "city": "Seattle",
        "region": "Washington",
    },
    {
        "slug": "willamette",
        "name": "Willamette Valley GI Partners",
        "industry": "Gastroenterology specialty practice",
        "employee_count": 64,
        "revenue_band": "10m_50m",
        "city": "Eugene",
        "region": "Oregon",
    },
    {
        "slug": "sierra",
        "name": "Sierra Digestive Care Group",
        "industry": "Gastroenterology specialty practice",
        "employee_count": 210,
        "revenue_band": "50m_100m",
        "city": "Sacramento",
        "region": "California",
    },
    {
        "slug": "front-range",
        "name": "Front Range Gastroenterology Institute",
        "industry": "Gastroenterology specialty practice",
        "employee_count": 87,
        "revenue_band": "10m_50m",
        "city": "Denver",
        "region": "Colorado",
    },
)

MUST_HAVE_CRITERIA: tuple[str, ...] = (
    "U.S.-based independent gastroenterology specialty practice",
    "Not a general hospital, health system, or hospital-employed department",
    "Multiple providers and public evidence of referral or intake workflow",
)

DISCOVERY_QUERY = (
    "Independent gastroenterology specialty practices in the United States with multiple "
    "providers and evidence of referral, fax, patient-access, or scheduling workflows"
)


@dataclass(frozen=True, slots=True)
class SeededAccount:
    """One admitted, discovery-materialized account inside the cycle's sealed generation."""

    slug: str
    account_id: EntityId
    canonical_name: str
    primary_domain: str


@dataclass(frozen=True, slots=True)
class SeededCycle:
    """One cycle's fresh project run, sealed five-account generation, and confirmed directive."""

    workspace_id: str
    project_id: str
    product_id: str
    project_run_id: ProjectRunId
    icp_key: str
    icp_version: int
    discovery_batch_id: DiscoveryBatchId
    discovery_seal_sha256: str
    accounts: tuple[SeededAccount, ...]
    directive_id: ResearchDirectiveId
    research_directive: Any

    @property
    def account_ids(self) -> tuple[UUID, ...]:
        return tuple(UUID(str(account.account_id)) for account in self.accounts)

    def account(self, slug: str) -> SeededAccount:
        return next(item for item in self.accounts if item.slug == slug)


class _DisabledMemory:
    async def submit(self, _submission: MemorySubmission) -> MemoryDisabled:
        return MemoryDisabled()


def _domain(cycle: int, slug: str) -> str:
    return f"{slug}-c{cycle}.harness.test"


def _observed_at() -> datetime:
    """Two days old: fresh under every registered TTL, so discovery truth is reusable."""

    return datetime.now(UTC) - timedelta(days=2)


def _plan(
    *,
    plan_id: DiscoveryPlanId,
    project_run_id: ProjectRunId,
    icp_key: str,
    icp_version: int,
) -> DiscoveryPlan:
    return DiscoveryPlan(
        discovery_plan_id=plan_id,
        plan_version=1,
        workspace_id=WORKSPACE_ID,
        project_id=PROJECT_ID,
        project_run_id=project_run_id,
        icp_key=icp_key,
        icp_version=icp_version,
        provider_policy_version="exa-websets-company-v1",
        field_policy_version=DISCOVERY_ENVELOPE_POLICY_V1.version,
        provider_contract_version="exa-websets-v0-2026-08-02",
        channels=("exa_websets",),
        searches=(
            DiscoverySearchPlan(
                search_key="harness-five-account-search",
                channel_key="exa_websets",
                normalized_query=DISCOVERY_QUERY,
                entity_type=DiscoveryEntityKind.COMPANY,
                requested_count=len(ACCOUNT_PROFILES),
                criteria=tuple(
                    DiscoveryCriterionPlan(description=criterion)
                    for criterion in MUST_HAVE_CRITERIA
                ),
            ),
        ),
        required_account_fields=DISCOVERY_ENVELOPE_POLICY_V1.required_fields,
        optional_account_fields=DISCOVERY_ENVELOPE_POLICY_V1.optional_fields,
        provider_credit_cap=125,
        money_budget_cap_cents=Decimal("1250"),
        stopping_policy={"requested_count": len(ACCOUNT_PROFILES)},
        snapshot_reuse_policy="harness_immutable_observation",
    )


def _item_payload(profile: Mapping[str, Any], *, domain: str) -> dict[str, JsonValue]:
    return {
        "id": f"harness-item-{domain}",
        "name": profile["name"],
        "url": f"https://{domain}/",
        "domain": domain,
        "linkedin_url": f"https://www.linkedin.com/company/{profile['slug']}-harness",
        "industry": profile["industry"],
        "employee_count": profile["employee_count"],
        "headquarters": {
            "raw": f"{profile['city']}, {profile['region']}, United States",
            "city": profile["city"],
            "region": profile["region"],
            "country": "United States",
            "country_code": "US",
        },
        "revenue_band": profile["revenue_band"],
        "evaluations": [
            {
                "criterion": criterion,
                "satisfied": "yes",
                "reasoning": "recorded synthetic provider evidence for the exact account",
                "references": [
                    {
                        "url": f"https://{domain}/",
                        "title": str(profile["name"]),
                        "snippet": f"{criterion} — {domain}",
                    }
                ],
            }
            for criterion in MUST_HAVE_CRITERIA
        ],
    }


async def _capture(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    ref: str,
    payload: object,
) -> tuple[str, bytes]:
    del ref
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    key = await capture_discovery_artifact(
        conn,
        storage,
        workspace_id=WORKSPACE_ID,
        content=body,
        media_type="application/json",
        source_key="exa_websets",
    )
    return key, body


async def _materialize_account(
    conn: AsyncConnection,
    *,
    account_id: EntityId,
    profile: Mapping[str, Any],
    domain: str,
    item_artifact_key: str,
    discovery_run_id: RunId,
) -> dict[str, ClaimId]:
    """Write the seven required-field discovery claims plus the criterion-evaluation claim."""

    source_url = f"https://{domain}/"
    name = str(profile["name"])
    values: dict[str, tuple[str, JsonValue, str]] = {
        "identity.account_name": (
            "core.account_name",
            name,
            f"{name} is the canonical name returned for {domain}.",
        ),
        "identity.primary_domain": (
            "core.primary_domain",
            domain,
            f"The exact returned primary domain is {domain}.",
        ),
        "discovery.company_linkedin_url": (
            "core.company_linkedin_url",
            f"https://www.linkedin.com/company/{profile['slug']}-harness",
            f"The company profile for {name} is linkedin.com/company/{profile['slug']}-harness.",
        ),
        "discovery.industry": (
            "core.industry",
            profile["industry"],
            f"{name} at {domain} is classified as {profile['industry']}.",
        ),
        "discovery.employee_size": (
            "core.employee_count",
            profile["employee_count"],
            f"{name} at {domain} has {profile['employee_count']} employees on record.",
        ),
        "discovery.headquarters": (
            "core.hq_location",
            {
                "raw": f"{profile['city']}, {profile['region']}, United States",
                "city": profile["city"],
                "region": profile["region"],
                "country": "United States",
                "country_code": "US",
            },
            f"{name} at {domain} has recorded headquarters in {profile['city']}.",
        ),
        "discovery.revenue": (
            "core.revenue_band",
            profile["revenue_band"],
            f"{name} at {domain} has recorded revenue band {profile['revenue_band']}.",
        ),
    }
    claim_ids: dict[str, ClaimId] = {}
    for logical_field in DISCOVERY_ENVELOPE_POLICY_V1.required_fields:
        field_key, value, evidence = values[str(logical_field)]
        claim = revalidate_with(
            account_claim(
                entity_id=account_id,
                field_key=field_key,
                value_json=value,
                source_tier=cast(Any, 2),
                extraction_method=ExtractionMethod.API,
                confidence=cast(Any, 0.97),
                run_id=discovery_run_id,
                research_mode=ResearchMode.ACCOUNT_PROFILING,
                source_url=source_url,
                evidence_span=evidence,
                observed_at=_observed_at(),
            ),
            source_key="exa_websets",
            artifact_key=item_artifact_key,
        )
        claim_ids[str(logical_field)] = ClaimId(UUID(str(await insert_claim(conn, claim))))
    criterion_value: dict[str, JsonValue] = {
        "matched_channel": "exa_websets",
        "matched_signal": "must-have criterion evaluation",
        "discovery_confidence": 0.97,
        "evidence": {
            "evaluations": [
                {
                    "criterion": criterion,
                    "satisfied": "yes",
                    "reasoning": "recorded provider criterion evaluation for the exact account",
                    "references": [
                        {
                            "url": source_url,
                            "title": name,
                            "snippet": f"{criterion}; exact account {domain}",
                        }
                    ],
                }
                for criterion in MUST_HAVE_CRITERIA
            ]
        },
    }
    await insert_claim(
        conn,
        revalidate_with(
            discovery_claim(
                entity_id=account_id,
                entity_type=EntityType.ACCOUNT,
                field_key="core.discovery_provenance",
                value_json=criterion_value,
                source_tier=cast(Any, 2),
                extraction_method=ExtractionMethod.API,
                confidence=cast(Any, 0.97),
                run_id=discovery_run_id,
                research_mode=ResearchMode.ACCOUNT_DISCOVERY,
                found_via="exa_websets",
                matched_signal="must-have criterion evaluation",
                discovery_confidence=cast(Any, 0.97),
                source_url=source_url,
                evidence_span=f"All must-have criteria returned yes for {name} at {domain}.",
                observed_at=_observed_at(),
            ),
            source_key="exa_websets",
            artifact_key=item_artifact_key,
        ),
    )
    return claim_ids


async def seed_five_account_sealed_generation(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    fixture: InsightHealthAccountDeepFixtureResult,
    cycle: int,
) -> tuple[ProjectRunId, DiscoveryBatchId, str, tuple[SeededAccount, ...]]:
    """Seal one fresh generation-1 discovery batch containing five distinct accounts."""

    discovery = fixture.discovery_fixture
    project_run_id = ProjectRunId(uuid4())
    await start_confirmed_project_run(
        conn,
        project_run_id=project_run_id,
        workspace_id=WORKSPACE_ID,
        project_id=PROJECT_ID,
        client_entity_id=EntityId(UUID(discovery.client_entity_id)),
        client_kb_version=discovery.client_kb_version,
        product_id=PRODUCT_ID,
        product_context_version_id=ProductContextVersionId(
            UUID(discovery.product_context_version_id)
        ),
        readiness_decision_id=READINESS_DECISION_ID,
        icp_key=fixture.deep_icp_key,
        icp_version=fixture.deep_icp_version,
        budget_cap_cents=Decimal("50000"),
    )

    plan_id = DiscoveryPlanId(uuid4())
    await put_discovery_plan(
        conn,
        workspace_id=WORKSPACE_ID,
        plan=_plan(
            plan_id=plan_id,
            project_run_id=project_run_id,
            icp_key=fixture.deep_icp_key,
            icp_version=fixture.deep_icp_version,
        ),
    )
    batch_id = DiscoveryBatchId(uuid4())
    await create_discovery_batch(
        conn,
        workspace_id=WORKSPACE_ID,
        batch_id=batch_id,
        plan_id=plan_id,
        generation=1,
    )

    operation_id = DiscoveryOperationId(uuid4())
    fingerprint = hashlib.sha256(
        json.dumps(
            {"harness": "comprehensive-five-account", "batch": str(batch_id)},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    planned = DiscoveryOperation(
        operation_id=operation_id,
        batch_id=batch_id,
        workspace_id=WORKSPACE_ID,
        source_key="exa_websets",
        provider_api_version="v0",
        request_fingerprint=fingerprint,
        observation_window=f"harness:cycle-{cycle}",
        provider_external_id=discovery_provider_external_id(fingerprint),
        state=DiscoveryOperationState.PLANNED,
        spend_outcome=DiscoverySpendOutcome.NOT_DISPATCHED,
        provider_units_reserved=Decimal("50"),
        cost_cents_reserved=Decimal("500"),
    )
    await put_discovery_operation(conn, workspace_id=WORKSPACE_ID, operation=planned)

    domains = {
        str(profile["slug"]): _domain(cycle, str(profile["slug"])) for profile in ACCOUNT_PROFILES
    }
    item_payloads = {
        str(profile["slug"]): _item_payload(profile, domain=domains[str(profile["slug"])])
        for profile in ACCOUNT_PROFILES
    }
    page_key, page_body = await _capture(
        conn,
        storage,
        ref=f"harness://discovery/{batch_id}/page",
        payload={
            "items": [payload["id"] for payload in item_payloads.values()],
            "has_more": False,
        },
    )
    page_id = await put_discovery_page(
        conn,
        workspace_id=WORKSPACE_ID,
        page=DiscoveryPageReceipt(
            operation_id=operation_id,
            resource_kind=DiscoveryPageResource.ITEMS,
            has_more=False,
            payload_artifact_key=page_key,
            payload_sha256=content_address(page_body),
            item_count=len(ACCOUNT_PROFILES),
            fetched_at=_observed_at() + timedelta(seconds=2),
        ),
    )

    item_keys: dict[str, str] = {}
    item_ids: dict[str, DiscoveryItemSnapshotId] = {}
    for ordinal, profile in enumerate(ACCOUNT_PROFILES):
        slug = str(profile["slug"])
        item_key, item_body = await _capture(
            conn,
            storage,
            ref=f"harness://discovery/{batch_id}/item/{slug}",
            payload=item_payloads[slug],
        )
        item_keys[slug] = item_key
        item_id = DiscoveryItemSnapshotId(uuid4())
        item_ids[slug] = item_id
        await put_discovery_item(
            conn,
            workspace_id=WORKSPACE_ID,
            item=DiscoveryItemSnapshot(
                item_snapshot_id=item_id,
                operation_id=operation_id,
                provider_item_id=str(item_payloads[slug]["id"]),
                source_kind="webset_item",
                source_id="harness-five-account-search",
                raw_artifact_key=item_key,
                item_sha256=content_address(item_body),
                observed_at=_observed_at(),
            ),
        )
        await link_discovery_page_item(
            conn,
            workspace_id=WORKSPACE_ID,
            operation_id=operation_id,
            page_receipt_id=page_id,
            item_snapshot_id=item_id,
            ordinal=ordinal,
        )
        await normalize_discovery_item(conn, workspace_id=WORKSPACE_ID, item_snapshot_id=item_id)

    request_key, _ = await _capture(
        conn,
        storage,
        ref=f"harness://discovery/{batch_id}/request",
        payload={
            "query": DISCOVERY_QUERY,
            "criteria": list(MUST_HAVE_CRITERIA),
            "count": len(ACCOUNT_PROFILES),
        },
    )
    submit_key, _ = await _capture(
        conn,
        storage,
        ref=f"harness://discovery/{batch_id}/submit",
        payload={"id": f"harness-webset-{batch_id}", "status": "running"},
    )
    response_key, _ = await _capture(
        conn,
        storage,
        ref=f"harness://discovery/{batch_id}/response",
        payload={
            "id": f"harness-webset-{batch_id}",
            "status": "completed",
            "items": [payload["id"] for payload in item_payloads.values()],
        },
    )
    await update_discovery_operation(
        conn,
        workspace_id=WORKSPACE_ID,
        operation=planned.model_copy(
            update={
                "provider_operation_id": f"harness-webset-{batch_id}",
                "state": DiscoveryOperationState.SUCCEEDED,
                "spend_outcome": DiscoverySpendOutcome.CHARGED,
                "submitted_receipt_ref": submit_key,
                "final_receipt_ref": response_key,
                "raw_request_artifact_key": request_key,
                "raw_response_manifest_key": response_key,
                "provider_units_charged": Decimal("50"),
                "cost_cents_charged": Decimal("500"),
                "started_at": _observed_at(),
                "terminal_at": _observed_at() + timedelta(seconds=3),
            }
        ),
    )
    await mark_discovery_operation_reconciled(
        conn,
        workspace_id=WORKSPACE_ID,
        operation_id=operation_id,
        final_reconciliation=True,
        pagination_exhausted=True,
    )
    await reconcile_discovery_batch_costs(conn, workspace_id=WORKSPACE_ID, batch_id=batch_id)
    await update_discovery_batch_state(
        conn,
        workspace_id=WORKSPACE_ID,
        batch_id=batch_id,
        state=DiscoveryBatchState.IDENTITY_RESOLUTION,
    )
    await lock_discovery_batch_for_materialization(
        conn, workspace_id=WORKSPACE_ID, batch_id=batch_id
    )

    discovery_run_id = new_run_id()
    accounts: list[SeededAccount] = []
    for profile in ACCOUNT_PROFILES:
        slug = str(profile["slug"])
        domain = domains[slug]
        account_id = await insert_account_entity(
            conn,
            workspace_id=WORKSPACE_ID,
            canonical_name=str(profile["name"]),
            primary_domain=domain,
            hq_geo={
                "raw": f"{profile['city']}, {profile['region']}, United States",
                "city": profile["city"],
                "region": profile["region"],
                "country": "United States",
                "country_code": "US",
            },
        )
        await put_discovery_candidate_link(
            conn,
            workspace_id=WORKSPACE_ID,
            batch_id=batch_id,
            item_snapshot_id=item_ids[slug],
            admission_status=DiscoveryCandidateAdmissionState.ADMITTED,
            raw_name=str(profile["name"]),
            candidate_domain=domain,
            source_url=f"https://{domain}/",
            account_entity_id=account_id,
            survivor_entity_id=account_id,
        )
        claim_ids = await _materialize_account(
            conn,
            account_id=account_id,
            profile=profile,
            domain=domain,
            item_artifact_key=item_keys[slug],
            discovery_run_id=discovery_run_id,
        )
        for logical_field in DISCOVERY_ENVELOPE_POLICY_V1.required_fields:
            claim_id = claim_ids[str(logical_field)]
            await put_discovery_field_resolution(
                conn,
                workspace_id=WORKSPACE_ID,
                resolution=DiscoveryFieldResolution(
                    batch_id=batch_id,
                    account_entity_id=account_id,
                    logical_field_key=logical_field,
                    state=DiscoveryFieldResolutionState.RESOLVED,
                    claim_ids=(claim_id,),
                    winning_claim_id=claim_id,
                    source_item_ids=(item_ids[slug],),
                    updated_at=_observed_at() + timedelta(seconds=4),
                ),
            )
        await index_account_discovery_artifacts(
            conn,
            workspace_id=WORKSPACE_ID,
            batch_id=batch_id,
            account_entity_id=account_id,
        )
        accounts.append(
            SeededAccount(
                slug=slug,
                account_id=account_id,
                canonical_name=str(profile["name"]),
                primary_domain=domain,
            )
        )

    await update_discovery_batch_state(
        conn,
        workspace_id=WORKSPACE_ID,
        batch_id=batch_id,
        state=DiscoveryBatchState.SEAL_PENDING,
    )
    bundle = await build_discovery_batch_manifest(
        conn, storage, workspace_id=WORKSPACE_ID, batch_id=batch_id
    )
    seal = await seal_discovery_batch(
        conn,
        workspace_id=WORKSPACE_ID,
        batch_id=batch_id,
        draft=bundle.seal_draft,
    )
    # Discovery really did finish and seal, so its phase checkpoint is committed with the exact
    # immutable refs; the state machine refuses to leave DISCOVERY without one.
    await upsert_checkpoint(
        conn,
        project_run_id=project_run_id,
        phase=ProjectPhase.DISCOVERY,
        idempotency_key=f"harness-discovery-seal:{project_run_id}",
        status=PhaseCheckpointStatus.COMMITTED,
        payload={
            "discovery_batch_id": str(batch_id),
            "discovery_batch_seal_ref": seal.seal_sha256,
            "account_manifest_ref": bundle.account_manifest_artifact_key,
            "claim_manifest_ref": bundle.claim_manifest_artifact_key,
        },
    )
    # The launcher is action-scoped: it must not require the outer project state machine to sit in
    # its DEEP phase (the r6 ruling). Leave the run where a real post-discovery run would be.
    await set_phase(
        conn, project_run_id, phase=ProjectPhase.SCORING, status=ProjectRunStatus.ACTIVE
    )
    return project_run_id, batch_id, seal.seal_sha256, tuple(accounts)


async def confirm_multi_account_directive(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    project_id: str,
    product_id: str,
    account_ids: Sequence[EntityId],
    icp_key: str,
    icp_version: int,
    field_keys: Sequence[str] = PROSE_ACCOUNT_FIELDS,
    allowed_source_keys: Sequence[str] = (
        "exa_deep",
        "sumble_jobs",
        "sumble_organizations",
        "sumble_tech_stack",
        "sumble_people",
    ),
    questions: Sequence[ResearchQuestion] = (),
    predecessor_id: ResearchDirectiveId | None = None,
) -> tuple[ResearchDirectiveId, Mapping[EntityId, Any]]:
    """One human-confirmed A2 directive whose explicit account scope carries every account.

    ``tests.api.account_deep_test_support.confirmed_account_research_direction`` is deliberately
    single-account (it asserts one compiled spec); the harness needs the same real draft/confirm
    tool pair over an N-account scope, so the shape is repeated here rather than widened there.
    """

    conn_factory = conn_session_factory(conn)
    registry = ToolRegistry()
    for tool in build_research_directive_tools(
        memory_write_factory=lambda _conn: _DisabledMemory(),
        conn_factory=conn_factory,
    ):
        registry.register(tool, make_default=tool.version == "2")
    body = ResearchDirectiveBody(
        account_scope=ResearchAccountScope(explicit_account_ids=tuple(account_ids)),
        field_keys=tuple(field_keys),
        questions=tuple(questions),
        committee_plan=ResearchCommitteePlan(
            functions=("Operations",),
            levels=("Director",),
            personas=("champion",),
            candidate_cap=4,
        ),
        source_policy=ResearchSourcePolicy(
            allowed_source_keys=tuple(allowed_source_keys),
            preferred_source_keys=("exa_deep",),
        ),
        privacy_policy=ResearchPrivacyPolicy(
            contact_profiling_allowed=False,
            contact_reveals_allowed=False,
        ),
        effort_policy=ResearchEffortPolicy(
            tier="high",
            max_depth=2,
            max_fanout=6,
            budget_cap_cents=Decimal(2000),
            budget_envelope_ref="budget:comprehensive-harness-v1",
            recursion_policy_ref="default",
            freshness_policy_ref="default",
        ),
    )
    draft_operation = new_operation_id()
    drafted = await invoke_tool(
        registry,
        "draft_account_research_directive",
        {
            "project_id": project_id,
            "product_id": product_id,
            "icp_key": icp_key,
            "icp_version": icp_version,
            "body": body.model_dump(mode="json"),
            "predecessor_id": (str(predecessor_id) if predecessor_id is not None else None),
            "user_instruction": (
                "Research the full comprehensive account profile for every selected practice and "
                "resolve its buying committee; leave unsupported hypotheses empty."
            ),
            "source_turn_ref": "turn:comprehensive-harness-direction",
        },
        ToolContext(
            workspace_id=workspace_id,
            actor="agent",
            conn_factory=conn_factory,
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
            workspace_id=workspace_id,
            actor="human",
            principal_kind="human",
            actor_id="human:comprehensive-harness",
            membership_id="wsm_comprehensive_harness",
            action_ref="turn:comprehensive-harness-confirm",
            conn_factory=conn_factory,
            operation_id=new_operation_id(),
        ),
        idempotency_ttl_s=60,
    )
    directive_id = ResearchDirectiveId(draft_operation)
    specs = await confirmed_directive_account_specs(
        conn,
        workspace_id=workspace_id,
        directive_id=directive_id,
    )
    return directive_id, {spec.entity_id: spec for spec in specs}


async def seed_cycle(
    conn: AsyncConnection,
    storage: StorageBackend,
    *,
    fixture: InsightHealthAccountDeepFixtureResult,
    cycle: int,
    questions: Sequence[ResearchQuestion] = (),
    predecessor_id: ResearchDirectiveId | None = None,
) -> SeededCycle:
    """One complete, launch-ready cycle: fresh run, sealed five, confirmed 21-field directive."""

    project_run_id, batch_id, seal_sha256, accounts = await seed_five_account_sealed_generation(
        conn, storage, fixture=fixture, cycle=cycle
    )
    directive_id, specs = await confirm_multi_account_directive(
        conn,
        workspace_id=WORKSPACE_ID,
        project_id=PROJECT_ID,
        product_id=PRODUCT_ID,
        account_ids=[account.account_id for account in accounts],
        icp_key=fixture.deep_icp_key,
        icp_version=fixture.deep_icp_version,
        questions=questions,
        predecessor_id=predecessor_id,
    )
    if set(specs) != {account.account_id for account in accounts}:
        raise AssertionError("confirmed directive did not compile every selected account")
    pin = next(iter(specs.values())).research_directive
    if pin is None:
        raise AssertionError("confirmed directive carries no pin")
    return SeededCycle(
        workspace_id=WORKSPACE_ID,
        project_id=PROJECT_ID,
        product_id=PRODUCT_ID,
        project_run_id=project_run_id,
        icp_key=fixture.deep_icp_key,
        icp_version=fixture.deep_icp_version,
        discovery_batch_id=batch_id,
        discovery_seal_sha256=seal_sha256,
        accounts=accounts,
        directive_id=directive_id,
        research_directive=pin,
    )


__all__ = [
    "ACCOUNT_PROFILES",
    "SeededAccount",
    "SeededCycle",
    "confirm_multi_account_directive",
    "seed_cycle",
    "seed_five_account_sealed_generation",
]
