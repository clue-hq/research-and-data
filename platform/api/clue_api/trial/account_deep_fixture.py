"""Synthetic Insight Health account-deep handoff for M8B Slice A1.

This module is an additive layer over :mod:`clue_api.trial.discovery_fixture`.  It creates the
database state that account-deep research is allowed to consume without changing the discovery
fixture's shallow ICP or advancing its project run:

* a separate, versioned healthcare account-deep ICP and workspace/ICP source override;
* one exact canonical account admitted through a durable Exa-Websets-shaped generation;
* terminal required-field decisions, evidence-backed must-have evaluations, manifests, and seal;
* committed discovery/scoring checkpoints and a human-approved criterion-selection tier claim;
* a confirmed fixture-only research directive plus recorded provider doubles as immutable
  artifacts; and
* a second project run stopped at ``deep`` with no pre-created ``account_run``.

The directive artifact is deliberately **not** the production A2 directive store.  It is a frozen
test input that lets A1 exercise the current account profiler and full account-deep composition;
production must continue to require A2's durable ``ResearchDirective``/authorization resolver.
Likewise the provider doubles implement the existing resolver and ``CommitteeSource`` seams but
perform no network I/O and settle no provider spend.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field, JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.composition import load_research_packs
from clue_api.deep.orchestrator import deep_account_run_id
from clue_api.discovery_seal import (
    DbSealedDiscoveryAccountManifestReader,
    build_discovery_batch_manifest,
)
from clue_api.stage0_tools import start_confirmed_project_run
from clue_api.trial.discovery_fixture import (
    BRAND_ID,
    PRODUCT_ID,
    PROJECT_ID,
    WORKSPACE_ID,
    FixtureStateConflict,
    InsightHealthDiscoveryFixtureResult,
    OfficialSitePage,
    seed_insight_health_discovery_fixture,
)
from clue_config import (
    DEFAULT_STAGE0_POLICY,
    Jurisdiction,
    JurisdictionPolicy,
    Posture,
    RecursionPolicy,
    SourcePlanPolicy,
)
from clue_core import (
    AccountEntity,
    AccountStatus,
    Claim,
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
    Entity,
    EntityId,
    EntityType,
    ExtractionMethod,
    FieldClass,
    FieldDef,
    ICPCreatedFrom,
    ICPSpec,
    ProductContextVersionId,
    ProjectPhase,
    ProjectRunId,
    RawArtifact,
    ReadinessDecisionId,
    ReadinessGate,
    ReadinessVerdict,
    ResearchMode,
    RunId,
    account_claim,
    discovery_claim,
    discovery_provider_external_id,
    revalidate_with,
)
from clue_db import ConnFactory
from clue_research.claimstore import WorkspaceScope, claims_for, insert_claim
from clue_research.discovery_scoring import DISCOVERY_ENVELOPE_POLICY_V1
from clue_research.discovery_scoring.tiering import (
    TIER_FIELD,
    DiscoverySelectionDisposition,
    DiscoverySelectionPolicy,
    load_discovery_criteria_selection,
    persist_discovery_selection_tier,
    selection_decision_version,
)
from clue_research.durable import (
    PhaseCheckpointStatus,
    ProjectRunStatus,
    create_discovery_batch,
    get_account_run,
    get_checkpoint,
    get_discovery_batch,
    get_discovery_batch_seal,
    get_project_run,
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
from clue_research.icp import (
    SourceWeight,
    WeightedSource,
    create_icp_spec,
    get_active_icp,
    register_source_profile_override,
)
from clue_research.identity import get_account, insert_account_entity, resolve_alias
from clue_research.profiling.committee import CommitteePersonCandidate
from clue_research.stage0 import (
    client_kb_readiness_metrics,
    evaluate_readiness,
    read_client_kb_claims,
)
from clue_storage import SnapshotSink, StorageBackend, content_address, flush_snapshots

FIXTURE_VERSION = "insight-health-account-deep-fixture@1"
DEEP_ICP_KEY = "independent_gastroenterology_practices_us_account_deep"
SOURCE_OVERRIDE_VERSION = 1

ACCOUNT_NAME = "Cascade Gastroenterology Associates"
ACCOUNT_DOMAIN = "cascade-gastro.example"
ACCOUNT_LINKEDIN_URL = "https://www.linkedin.com/company/cascade-gastro-fixture"
ACCOUNT_SOURCE_URL = f"https://{ACCOUNT_DOMAIN}/"
ACCOUNT_GEO: dict[str, JsonValue] = {
    "raw": "Portland, Oregon, United States",
    "city": "Portland",
    "region": "Oregon",
    "country": "United States",
    "country_code": "US",
}

DEEP_FIELD_KEYS = (
    "account.hiring_velocity_eng",
    "core.primary_tech_stack",
    "account.operational_pain",
    "account.strategic_moves",
    "account.resonance.culture",
)

MUST_HAVE_CRITERIA = (
    "U.S.-based independent gastroenterology specialty practice",
    "Not a general hospital, health system, or hospital-employed department",
    "Multiple providers and public evidence of referral or intake workflow",
)

OBSERVED_AT = datetime(2026, 8, 3, 9, 0, tzinfo=UTC)


def _stable_uuid(label: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"clue://fixtures/insight-health-account-deep/{label}")


PROJECT_RUN_ID = ProjectRunId(_stable_uuid("project-run"))
READINESS_DECISION_ID = ReadinessDecisionId(_stable_uuid("readiness-decision"))
DISCOVERY_PLAN_ID = DiscoveryPlanId(_stable_uuid("discovery-plan"))
DISCOVERY_BATCH_ID = DiscoveryBatchId(_stable_uuid("discovery-batch"))
DISCOVERY_OPERATION_ID = DiscoveryOperationId(_stable_uuid("discovery-operation"))
DISCOVERY_ITEM_ID = DiscoveryItemSnapshotId(_stable_uuid("discovery-item"))
DISCOVERY_RUN_ID = RunId(_stable_uuid("discovery-claims"))
TIER_RUN_ID = RunId(_stable_uuid("tier-approval"))
RECORDED_RESOLVER_RUN_ID = RunId(_stable_uuid("recorded-resolver"))


class RecordedAccountField(BaseModel):
    """One normalized provider-double field candidate for the resolver seam."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_key: str
    source_tier: int
    field_key: str
    value_json: JsonValue
    source_url: str
    evidence_span: str
    confidence: float = 0.92


class FixtureCommitteePlan(BaseModel):
    """The bounded no-reveal committee plan carried by the fixture directive."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    functions: tuple[str, ...]
    levels: tuple[str, ...]
    teams: tuple[str, ...]
    personas: tuple[str, ...]
    candidate_cap: int
    relationship_depth: int
    contact_reveals_allowed: bool = False


class FixtureResearchQuestion(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    question_id: str
    text: str
    target_field: str
    source_family_hints: tuple[str, ...]
    stop_rule: str = "retain only target-locked evidence; otherwise leave empty"


class FixtureResearchPolicies(BaseModel):
    """The exact non-provider policies A1 pins into its immutable directive artifact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    budget_policy_version: str = "account-deep-fixture-budget-v1"
    account_budget_cap_cents: Decimal = Decimal("500")
    jurisdiction_policy_version: str = "account-deep-fixture-us-professional-v1"
    jurisdiction_policy: JurisdictionPolicy = Field(
        default_factory=lambda: JurisdictionPolicy(
            jurisdiction=Jurisdiction.US_STATE,
            posture=Posture.PROFESSIONAL_PUBLIC_ONLY,
        )
    )
    use_class_policy_version: str = "account-deep-fixture-use-class-v1"
    freshness_policy_version: str = "account-deep-fixture-freshness-v1"
    field_freshness_days: dict[str, int] = Field(
        default_factory=lambda: {
            "account.hiring_velocity_eng": 30,
            "core.primary_tech_stack": 90,
            "account.operational_pain": 90,
            "account.strategic_moves": 90,
            "account.resonance.culture": 60,
        }
    )
    recursion_policy_version: str = "account-deep-fixture-recursion-v1"
    recursion_policy: RecursionPolicy = Field(default_factory=RecursionPolicy)
    source_plan_policy_version: str = "account-deep-fixture-source-plan-v1"
    source_plan_policy: SourcePlanPolicy = Field(
        default_factory=lambda: SourcePlanPolicy(prefer_deep_sources=True)
    )
    committee_policy_version: str = "account-deep-fixture-committee-v1"


class FixtureResearchDirective(BaseModel):
    """A1's immutable execution-input double; it is not A2's production authority record."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contract: str = "account-deep-fixture-directive-v1"
    status: str = "confirmed"
    workspace_id: str = WORKSPACE_ID
    project_id: str = PROJECT_ID
    product_id: str = PRODUCT_ID
    icp_key: str = DEEP_ICP_KEY
    version: int = 1
    account_scope: tuple[str, ...] = (ACCOUNT_DOMAIN,)
    field_keys: tuple[str, ...] = DEEP_FIELD_KEYS
    questions: tuple[FixtureResearchQuestion, ...]
    committee_plan: FixtureCommitteePlan
    policies: FixtureResearchPolicies = Field(default_factory=FixtureResearchPolicies)
    allowed_sources: tuple[str, ...]
    excluded_sources: tuple[str, ...]
    expected_cost_cents: Decimal = Decimal("75")
    confirmed_by: str = "human:fixture"
    contact_reveals_allowed: bool = False


DEFAULT_RESEARCH_DIRECTIVE = FixtureResearchDirective(
    questions=(
        FixtureResearchQuestion(
            question_id="referral-coordination",
            text=(
                "Does this exact practice show evidence of referral intake, routing, or follow-up "
                "burden that an AI referral coordinator could reduce?"
            ),
            target_field="account.operational_pain",
            source_family_hints=("sumble_jobs", "official_site", "exa_deep"),
        ),
        FixtureResearchQuestion(
            question_id="fax-workflow",
            text=(
                "Is there grounded account-level evidence that faxed documents create indexing, "
                "document-processing, or administrative delays?"
            ),
            target_field="account.operational_pain",
            source_family_hints=("official_site", "public_reviews", "exa_deep"),
        ),
        FixtureResearchQuestion(
            question_id="phone-reception",
            text=(
                "Is there grounded evidence of high call volume, reception pressure, scheduling "
                "backlogs, or patient-access bottlenecks?"
            ),
            target_field="account.operational_pain",
            source_family_hints=("sumble_jobs", "public_reviews", "exa_deep"),
        ),
        FixtureResearchQuestion(
            question_id="dac-coordination",
            text=(
                "Does the practice expose account-level evidence of authorization, documentation, "
                "or patient-provider coordination burden analogous to DAC formalities?"
            ),
            target_field="account.strategic_moves",
            source_family_hints=("official_site", "exa_deep"),
        ),
    ),
    committee_plan=FixtureCommitteePlan(
        functions=("Operations", "Administration", "Information Technology", "Finance"),
        levels=("VP", "Director", "Head"),
        teams=("Patient Access", "Referral Operations", "Revenue Cycle", "Clinical Operations"),
        personas=("champion", "economic_buyer", "technical_evaluator", "blocker"),
        candidate_cap=6,
        relationship_depth=1,
    ),
    allowed_sources=(
        "sumble_jobs",
        "sumble_tech_stack",
        "sumble_teams",
        "sumble_people",
        "firecrawl_site",
        "exa_deep",
    ),
    excluded_sources=("parallel_task", "sumble_contact_reveal"),
)


DEFAULT_RECORDED_FIELDS = (
    RecordedAccountField(
        source_key="sumble_jobs",
        source_tier=1,
        field_key="account.hiring_velocity_eng",
        value_json=3,
        source_url="https://sumble.com/organizations/cascade-gastro-fixture/jobs",
        evidence_span=(
            "Cascade Gastroenterology Associates has three current operations and patient-access "
            "job postings, including Referral Coordinator and Front Desk Supervisor."
        ),
        confidence=0.96,
    ),
    RecordedAccountField(
        source_key="sumble_tech_stack",
        source_tier=1,
        field_key="core.primary_tech_stack",
        value_json=["Epic", "Microsoft 365", "RingCentral"],
        source_url="https://sumble.com/organizations/cascade-gastro-fixture/technologies",
        evidence_span="Recorded organization technologies: Epic, Microsoft 365, RingCentral.",
        confidence=0.94,
    ),
    RecordedAccountField(
        source_key="exa_deep",
        source_tier=4,
        field_key="account.operational_pain",
        value_json=(
            "Public, target-locked evidence indicates referral-document indexing and patient-call "
            "routing are recurring administrative bottlenecks; the fixture does not infer a "
            "person-level complaint."
        ),
        source_url=f"{ACCOUNT_SOURCE_URL}careers/referral-coordinator",
        evidence_span=(
            f"{ACCOUNT_DOMAIN}: the Referral Coordinator indexes incoming fax documents, follows "
            "missing records, and routes patient calls to clinical teams."
        ),
    ),
    RecordedAccountField(
        source_key="exa_deep",
        source_tier=4,
        field_key="account.strategic_moves",
        value_json=(
            "The practice is expanding centralized patient-access and referral-operations capacity "
            "while standardizing intake across locations."
        ),
        source_url=f"{ACCOUNT_SOURCE_URL}news/patient-access-expansion",
        evidence_span=(
            f"{ACCOUNT_DOMAIN}: Cascade Gastroenterology Associates announced a centralized "
            "patient-access and referral-operations program across its Oregon locations."
        ),
    ),
    RecordedAccountField(
        source_key="exa_deep",
        source_tier=4,
        field_key="account.resonance.culture",
        value_json=(
            "Public account-level materials emphasize reducing administrative friction so staff "
            "can spend more time supporting patients."
        ),
        source_url=f"{ACCOUNT_SOURCE_URL}about/culture",
        evidence_span=(
            f"{ACCOUNT_DOMAIN}: Cascade Gastroenterology Associates describes a culture of "
            "reducing "
            "administrative friction and giving care teams more time with patients."
        ),
    ),
)


DEFAULT_COMMITTEE_CANDIDATES = (
    CommitteePersonCandidate(
        source_key="sumble_people",
        source_person_id="sumble-fixture-person-1001",
        linkedin_url="https://www.linkedin.com/in/alex-rivera-cascade-gastro-fixture",
        full_name="Alex Rivera",
        title="VP of Operations",
        job_function="Operations",
        job_level="VP",
        team_names=("Patient Access", "Referral Operations"),
        relationship_labels=("provider_returned_team_membership",),
        source_url="https://sumble.com/people/sumble-fixture-person-1001",
        matched_signal="provider-returned operations leader for the exact account",
        geo={"city": "Portland", "region": "Oregon", "country": "United States"},
        discovery_confidence=0.94,
    ),
    CommitteePersonCandidate(
        source_key="sumble_people",
        source_person_id="sumble-fixture-person-1002",
        linkedin_url="https://www.linkedin.com/in/jordan-lee-cascade-gastro-fixture",
        full_name="Jordan Lee",
        title="Director of Information Technology",
        job_function="Information Technology",
        job_level="Director",
        team_names=("Information Technology",),
        relationship_labels=("provider_returned_team_membership",),
        source_url="https://sumble.com/people/sumble-fixture-person-1002",
        matched_signal="provider-returned technology evaluator for the exact account",
        geo={"city": "Portland", "region": "Oregon", "country": "United States"},
        discovery_confidence=0.91,
    ),
)


class InsightHealthAccountDeepFixtureResult(BaseModel):
    """Stable references emitted by the two-level A1 fixture."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fixture_version: str
    discovery_fixture: InsightHealthDiscoveryFixtureResult
    deep_icp_key: str
    deep_icp_version: int
    deep_field_keys: tuple[str, ...]
    source_override_version: int
    selected_account_id: EntityId
    project_run_id: ProjectRunId
    project_phase: ProjectPhase
    discovery_plan_id: DiscoveryPlanId
    discovery_batch_id: DiscoveryBatchId
    discovery_operation_id: DiscoveryOperationId
    discovery_item_id: DiscoveryItemSnapshotId
    discovery_seal_sha256: str
    tier_claim_id: UUID
    directive_ref: str
    directive_sha256: str
    committee_plan_ref: str
    provider_artifact_keys: dict[str, str]
    expected_account_run_id: RunId


class RecordedAccountDeepResolver:
    """Network-free fixture resolver over immutable, already-persisted provider output."""

    def __init__(
        self,
        *,
        account_id: EntityId,
        source_key: str,
        records: Sequence[RecordedAccountField],
        artifact_key: str,
    ) -> None:
        matching = tuple(record for record in records if record.source_key == source_key)
        if not matching:
            raise ValueError(f"no recorded account-deep fields for source {source_key!r}")
        tiers = {record.source_tier for record in matching}
        if len(tiers) != 1:
            raise ValueError(f"fixture source {source_key!r} has inconsistent tiers")
        self._account_id = account_id
        self._source_key = source_key
        self._records = {record.field_key: record for record in matching}
        self._artifact_key = artifact_key
        self.tier = tiers.pop()
        self.calls: list[tuple[EntityId, str]] = []

    def resolve(self, entity: Entity, field: FieldDef) -> list[Claim]:
        if entity.entity_id != self._account_id or entity.entity_type is not EntityType.ACCOUNT:
            return []
        record = self._records.get(field.field_key)
        if record is None:
            return []
        self.calls.append((entity.entity_id, field.field_key))
        method = (
            ExtractionMethod.API
            if record.source_tier == 1
            else ExtractionMethod.SCRAPE
            if record.source_tier == 2
            else ExtractionMethod.LLM_SYNTHESIS
        )
        return [
            revalidate_with(
                account_claim(
                    entity_id=entity.entity_id,
                    field_key=field.field_key,
                    value_json=record.value_json,
                    source_tier=record.source_tier,
                    extraction_method=method,
                    confidence=record.confidence,
                    run_id=RECORDED_RESOLVER_RUN_ID,
                    research_mode=ResearchMode.ACCOUNT_PROFILING,
                    source_url=record.source_url,
                    evidence_span=record.evidence_span,
                    observed_at=OBSERVED_AT,
                    cost_cents=Decimal(0),
                ),
                source_key=self._source_key,
                artifact_key=self._artifact_key,
            )
        ]


class RecordedAccountDeepCommitteeSource:
    """Exact-account, no-reveal committee enumeration double behind ``CommitteeSource``."""

    source_key = "sumble_people"
    tier = 1

    def __init__(
        self,
        *,
        account_id: EntityId,
        candidates: Sequence[CommitteePersonCandidate],
        evidence_refs: Sequence[str],
    ) -> None:
        self._account_id = account_id
        self.calls: list[tuple[EntityId, int]] = []
        self._candidates = tuple(
            candidate.model_copy(
                update={
                    "evidence_refs": tuple(
                        dict.fromkeys((*candidate.evidence_refs, *evidence_refs))
                    ),
                    "cost_cents": Decimal(0),
                }
            )
            for candidate in candidates
        )

    async def find_candidates(
        self, account: AccountEntity, *, limit: int
    ) -> Sequence[CommitteePersonCandidate]:
        if account.id != self._account_id or account.primary_domain != ACCOUNT_DOMAIN:
            return ()
        self.calls.append((account.id, limit))
        return self._candidates[:limit]


def build_recorded_account_resolvers(
    result: InsightHealthAccountDeepFixtureResult,
) -> dict[str, RecordedAccountDeepResolver]:
    """Build the fixture resolver set without registering it process-globally."""

    out: dict[str, RecordedAccountDeepResolver] = {}
    for source_key in sorted({record.source_key for record in DEFAULT_RECORDED_FIELDS}):
        artifact_key = result.provider_artifact_keys.get(source_key)
        if artifact_key is None:
            raise FixtureStateConflict(f"fixture provider artifact missing for {source_key}")
        out[source_key] = RecordedAccountDeepResolver(
            account_id=result.selected_account_id,
            source_key=source_key,
            records=DEFAULT_RECORDED_FIELDS,
            artifact_key=artifact_key,
        )
    return out


def build_recorded_committee_source(
    result: InsightHealthAccountDeepFixtureResult,
) -> RecordedAccountDeepCommitteeSource:
    """Build the exact-account Sumble committee double from A1's immutable artifact refs."""

    refs = tuple(
        result.provider_artifact_keys[key]
        for key in ("sumble_teams", "sumble_people")
        if key in result.provider_artifact_keys
    )
    return RecordedAccountDeepCommitteeSource(
        account_id=result.selected_account_id,
        candidates=DEFAULT_COMMITTEE_CANDIDATES,
        evidence_refs=refs,
    )


def _directive_bytes(directive: FixtureResearchDirective) -> bytes:
    return json.dumps(
        directive.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _provider_payload(source_key: str) -> dict[str, JsonValue]:
    fields: list[JsonValue] = [
        cast(JsonValue, record.model_dump(mode="json"))
        for record in DEFAULT_RECORDED_FIELDS
        if record.source_key == source_key
    ]
    people: list[JsonValue] = (
        [
            # The no-reveal fixture must omit contact fields entirely, not serialize them as
            # provider-looking nulls.  The provider-neutral candidate model still owns the
            # optional identity field, but the recorded Sumble response never selected it.
            cast(JsonValue, candidate.model_dump(mode="json", exclude_none=True))
            for candidate in DEFAULT_COMMITTEE_CANDIDATES
        ]
        if source_key == "sumble_people"
        else []
    )
    teams: list[JsonValue] = (
        [
            {
                "team_id": "team-patient-access-fixture",
                "name": "Patient Access",
                "functions": ["Operations", "Administration"],
                "related_person_ids": ["sumble-fixture-person-1001"],
                "relationship_label": "provider_returned_team_membership",
            },
            {
                "team_id": "team-it-fixture",
                "name": "Information Technology",
                "functions": ["Information Technology"],
                "related_person_ids": ["sumble-fixture-person-1002"],
                "relationship_label": "provider_returned_team_membership",
            },
        ]
        if source_key == "sumble_teams"
        else []
    )
    return {
        "contract": "account-deep-normalized-provider-double-v1",
        "fixture": FIXTURE_VERSION,
        "source_key": source_key,
        "account": {
            "canonical_name": ACCOUNT_NAME,
            "primary_domain": ACCOUNT_DOMAIN,
        },
        "fields": fields,
        "people": people,
        "teams": teams,
        "contains_contact_reveals": False,
    }


async def _capture_fixture_artifacts(
    conn: AsyncConnection,
    *,
    storage: StorageBackend,
) -> tuple[str, str, dict[str, str]]:
    sink = SnapshotSink(workspace_id=WORKSPACE_ID)
    directive_body = _directive_bytes(DEFAULT_RESEARCH_DIRECTIVE)
    directive_ref = sink.capture(
        RawArtifact(
            ref="fixture://insight-health/account-deep/research-directive/v1",
            media_type="application/json",
            content=directive_body,
            metadata={
                "fixture": FIXTURE_VERSION,
                "authority": "fixture_only_not_a2_production_authority",
                "confirmed": True,
            },
        ),
        source_key="fixture_research_directive",
    )
    provider_keys: dict[str, str] = {}
    for source_key in (
        "sumble_jobs",
        "sumble_tech_stack",
        "sumble_teams",
        "sumble_people",
        "exa_deep",
    ):
        body = json.dumps(
            _provider_payload(source_key), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        provider_keys[source_key] = sink.capture(
            RawArtifact(
                ref=f"fixture://insight-health/account-deep/providers/{source_key}/v1",
                media_type="application/json",
                content=body,
                metadata={
                    "fixture": FIXTURE_VERSION,
                    "provider_double": True,
                    "network_io": False,
                    "contains_contact_reveals": False,
                },
            ),
            source_key=source_key,
        )
    await flush_snapshots(conn, storage, sink)
    return directive_ref, content_address(directive_body), provider_keys


def _deep_discovery_strategy() -> dict[str, JsonValue]:
    return {
        "mode": "platform_led",
        "channels": ["exa_websets"],
        "requested_count": 1,
        "entity_type": "company",
        "query": (
            "Independent gastroenterology specialty practices in the United States with multiple "
            "providers and evidence of referral, fax, patient-access, or scheduling workflows"
        ),
        "geographies": ["US"],
        "must_have_criteria": list(MUST_HAVE_CRITERIA),
        "scoring_mode": "disabled",
        "selection_mode": "discovery_criteria",
        "approved_tier": "high",
        "required_account_fields": list(DISCOVERY_ENVELOPE_POLICY_V1.required_fields),
        "optional_account_fields": list(DISCOVERY_ENVELOPE_POLICY_V1.optional_fields),
        "discovery_completion_policy": "closed_durable_batch",
        "advance_only_after": "immutable_discovery_batch_seal",
    }


def _deep_source_profile_ref() -> dict[str, JsonValue]:
    return {
        "contract": "account-deep-healthcare-source-override-v1",
        "pack_key": "healthcare_practice",
        "workspace_id": WORKSPACE_ID,
        "icp_key": DEEP_ICP_KEY,
        "override_version": SOURCE_OVERRIDE_VERSION,
        "official_page_source": "firecrawl_site",
        "allowed": [
            "sumble_jobs",
            "sumble_tech_stack",
            "firecrawl_site",
            "exa_deep",
            "sumble_teams",
            "sumble_people",
        ],
        "excluded": ["parallel_task", "sumble_contact_reveal"],
    }


async def _ensure_source_override(conn: AsyncConnection) -> None:
    await register_source_profile_override(
        conn,
        "healthcare_practice",
        WORKSPACE_ID,
        (
            WeightedSource(source_key="sumble_jobs", weight=SourceWeight.HIGH, rank=1),
            WeightedSource(source_key="firecrawl_site", weight=SourceWeight.HIGH, rank=2),
            WeightedSource(source_key="exa_deep", weight=SourceWeight.MEDIUM, rank=3),
        ),
        field_class=FieldClass.ACCOUNT,
        icp_key=DEEP_ICP_KEY,
        version=SOURCE_OVERRIDE_VERSION,
    )
    await register_source_profile_override(
        conn,
        "healthcare_practice",
        WORKSPACE_ID,
        (
            WeightedSource(source_key="sumble_tech_stack", weight=SourceWeight.HIGH, rank=1),
            WeightedSource(source_key="firecrawl_site", weight=SourceWeight.HIGH, rank=2),
            WeightedSource(source_key="exa_deep", weight=SourceWeight.MEDIUM, rank=3),
        ),
        field_class=FieldClass.CORE,
        icp_key=DEEP_ICP_KEY,
        version=SOURCE_OVERRIDE_VERSION,
    )
    await register_source_profile_override(
        conn,
        "healthcare_practice",
        WORKSPACE_ID,
        (
            WeightedSource(source_key="firecrawl_site", weight=SourceWeight.HIGH, rank=1),
            WeightedSource(source_key="exa_deep", weight=SourceWeight.MEDIUM, rank=2),
        ),
        field_class=FieldClass.ACCOUNT_RESONANCE,
        icp_key=DEEP_ICP_KEY,
        version=SOURCE_OVERRIDE_VERSION,
    )


async def _ensure_deep_icp(
    conn: AsyncConnection,
    *,
    discovery: InsightHealthDiscoveryFixtureResult,
) -> ICPSpec:
    await _ensure_source_override(conn)
    existing = await get_active_icp(conn, WORKSPACE_ID, DEEP_ICP_KEY)
    expected = {
        "created_from": ICPCreatedFrom.CLIENT_EDIT,
        "field_keys": DEEP_FIELD_KEYS,
        "enabled_packs": ("healthcare_practice",),
        "discovery_strategy": _deep_discovery_strategy(),
        "source_profile_ref": _deep_source_profile_ref(),
        "client_entity_id": EntityId(UUID(discovery.client_entity_id)),
        "client_kb_version": discovery.client_kb_version,
        "product_id": PRODUCT_ID,
    }
    if existing is None:
        return await create_icp_spec(
            conn,
            workspace_id=WORKSPACE_ID,
            icp_key=DEEP_ICP_KEY,
            created_from=ICPCreatedFrom.CLIENT_EDIT,
            field_keys=DEEP_FIELD_KEYS,
            enabled_packs=("healthcare_practice",),
            discovery_strategy=_deep_discovery_strategy(),
            source_profile_ref=_deep_source_profile_ref(),
            created_by="human:insight-health-account-deep-fixture",
            label="U.S. independent gastroenterology practices — account deep",
            description=(
                "Synthetic deep-eligible ICP for target-locked account profiling and bounded "
                "buying-committee discovery. It does not replace the discovery fixture ICP."
            ),
            activate=True,
            client_entity_id=EntityId(UUID(discovery.client_entity_id)),
            client_kb_version=discovery.client_kb_version,
            product_id=PRODUCT_ID,
        )
    mismatched = [key for key, value in expected.items() if getattr(existing, key) != value]
    if mismatched:
        raise FixtureStateConflict(f"account-deep fixture ICP differs in fields: {mismatched}")
    return existing


async def _ensure_deep_project_run(
    conn: AsyncConnection,
    *,
    discovery: InsightHealthDiscoveryFixtureResult,
    deep_icp: ICPSpec,
) -> None:
    client_entity_id = EntityId(UUID(discovery.client_entity_id))
    claims = await read_client_kb_claims(
        conn,
        client_entity_id,
        workspace_id=WORKSPACE_ID,
        version=discovery.client_kb_version,
        product_id=PRODUCT_ID,
    )
    metrics = client_kb_readiness_metrics(claims)
    metrics["open_policy_blocks"] = 0
    readiness = await evaluate_readiness(
        conn,
        workspace_id=WORKSPACE_ID,
        brand_id=BRAND_ID,
        product_id=PRODUCT_ID,
        project_id=PROJECT_ID,
        client_entity_id=client_entity_id,
        client_kb_version=discovery.client_kb_version,
        icp_key=deep_icp.icp_key,
        icp_version=deep_icp.version,
        product_context_version_id=ProductContextVersionId(
            UUID(discovery.product_context_version_id)
        ),
        gate=ReadinessGate.DISCOVERY_SPEND,
        spec=DEFAULT_STAGE0_POLICY.readiness,
        metrics=metrics,
        created_by_actor="system",
        readiness_decision_id=READINESS_DECISION_ID,
    )
    if readiness.verdict is not ReadinessVerdict.READY:
        raise FixtureStateConflict("account-deep fixture did not clear discovery readiness")
    existing = await get_project_run(conn, PROJECT_RUN_ID)
    if existing is None:
        await start_confirmed_project_run(
            conn,
            project_run_id=PROJECT_RUN_ID,
            workspace_id=WORKSPACE_ID,
            project_id=PROJECT_ID,
            client_entity_id=client_entity_id,
            client_kb_version=discovery.client_kb_version,
            product_id=PRODUCT_ID,
            product_context_version_id=ProductContextVersionId(
                UUID(discovery.product_context_version_id)
            ),
            readiness_decision_id=READINESS_DECISION_ID,
            icp_key=deep_icp.icp_key,
            icp_version=deep_icp.version,
            budget_cap_cents=Decimal("1000"),
        )
        return
    expected = (
        WORKSPACE_ID,
        PROJECT_ID,
        PRODUCT_ID,
        deep_icp.icp_key,
        deep_icp.version,
        client_entity_id,
        discovery.client_kb_version,
        READINESS_DECISION_ID,
    )
    actual = (
        existing.workspace_id,
        existing.project_id,
        existing.product_id,
        existing.icp_key,
        existing.icp_version,
        existing.client_entity_id,
        existing.client_kb_version,
        existing.readiness_decision_id,
    )
    if actual != expected:
        raise FixtureStateConflict("account-deep fixture project run has incompatible lineage")


def _discovery_plan(deep_icp: ICPSpec) -> DiscoveryPlan:
    return DiscoveryPlan(
        discovery_plan_id=DISCOVERY_PLAN_ID,
        plan_version=1,
        workspace_id=WORKSPACE_ID,
        project_id=PROJECT_ID,
        project_run_id=PROJECT_RUN_ID,
        icp_key=deep_icp.icp_key,
        icp_version=deep_icp.version,
        provider_policy_version="exa-websets-company-v1",
        field_policy_version=DISCOVERY_ENVELOPE_POLICY_V1.version,
        provider_contract_version="exa-websets-v0-2026-08-02",
        channels=("exa_websets",),
        searches=(
            DiscoverySearchPlan(
                search_key="gastro-account-deep-fixture-search",
                channel_key="exa_websets",
                normalized_query=str(_deep_discovery_strategy()["query"]),
                entity_type=DiscoveryEntityKind.COMPANY,
                requested_count=1,
                criteria=tuple(
                    DiscoveryCriterionPlan(description=criterion)
                    for criterion in MUST_HAVE_CRITERIA
                ),
            ),
        ),
        required_account_fields=DISCOVERY_ENVELOPE_POLICY_V1.required_fields,
        optional_account_fields=DISCOVERY_ENVELOPE_POLICY_V1.optional_fields,
        provider_credit_cap=25,
        money_budget_cap_cents=Decimal("250"),
        stopping_policy={"requested_count": 1},
        snapshot_reuse_policy="fixture_immutable_observation",
    )


async def _capture_discovery_payloads(
    conn: AsyncConnection,
    *,
    storage: StorageBackend,
) -> dict[str, tuple[str, bytes]]:
    payloads: dict[str, object] = {
        "request": {
            "query": _deep_discovery_strategy()["query"],
            "criteria": list(MUST_HAVE_CRITERIA),
            "count": 1,
        },
        "submit": {"id": "exa-webset-account-deep-fixture", "status": "running"},
        "response": {
            "id": "exa-webset-account-deep-fixture",
            "status": "completed",
            "items": ["exa-account-deep-item-1"],
        },
        "page": {"items": ["exa-account-deep-item-1"], "has_more": False},
        "item": {
            "id": "exa-account-deep-item-1",
            "name": ACCOUNT_NAME,
            "url": ACCOUNT_SOURCE_URL,
            "domain": ACCOUNT_DOMAIN,
            "linkedin_url": ACCOUNT_LINKEDIN_URL,
            "industry": "Gastroenterology specialty practice",
            "employee_count": 42,
            "headquarters": ACCOUNT_GEO,
            "revenue_band": "10m_50m",
            "evaluations": [
                {
                    "criterion": criterion,
                    "satisfied": "yes",
                    "reasoning": "recorded synthetic provider evidence for the exact account",
                    "references": [
                        {
                            "url": ACCOUNT_SOURCE_URL,
                            "title": ACCOUNT_NAME,
                            "snippet": f"{criterion} — {ACCOUNT_DOMAIN}",
                        }
                    ],
                }
                for criterion in MUST_HAVE_CRITERIA
            ],
        },
    }
    sink = SnapshotSink(workspace_id=WORKSPACE_ID)
    captured: dict[str, tuple[str, bytes]] = {}
    for name, payload in payloads.items():
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        key = sink.capture(
            RawArtifact(
                ref=f"fixture://insight-health/account-deep/discovery/{name}/v1",
                media_type="application/json",
                content=body,
                metadata={"fixture": FIXTURE_VERSION, "network_io": False},
            ),
            source_key="exa_websets",
        )
        captured[name] = (key, body)
    await flush_snapshots(conn, storage, sink)
    return captured


async def _ensure_account(conn: AsyncConnection) -> EntityId:
    existing = await resolve_alias(
        conn, ACCOUNT_DOMAIN, EntityType.ACCOUNT, workspace_id=WORKSPACE_ID
    )
    if existing is None:
        existing = await insert_account_entity(
            conn,
            workspace_id=WORKSPACE_ID,
            canonical_name=ACCOUNT_NAME,
            primary_domain=ACCOUNT_DOMAIN,
            aliases=("Cascade Gastro",),
            hq_geo=ACCOUNT_GEO,
            registry_ids={"fixture": "cascade-gastro-001"},
            status=AccountStatus.ACTIVE,
        )
    account = await get_account(conn, existing)
    if account is None or (
        account.canonical_name,
        account.primary_domain,
        account.status,
        account.workspace_id,
    ) != (ACCOUNT_NAME, ACCOUNT_DOMAIN, AccountStatus.ACTIVE, WORKSPACE_ID):
        raise FixtureStateConflict("account-deep fixture account identity differs")
    return existing


async def _ensure_discovery_claim(
    conn: AsyncConnection,
    *,
    account_id: EntityId,
    field_key: str,
    value: JsonValue,
    source_url: str,
    evidence_span: str,
    artifact_key: str,
    discovery: bool = False,
) -> Claim:
    scope = WorkspaceScope.for_workspace(WORKSPACE_ID)
    existing = [
        claim
        for claim in await claims_for(conn, account_id, field_key, scope=scope)
        if claim.run_id == DISCOVERY_RUN_ID and claim.source_key == "exa_websets"
    ]
    if len(existing) > 1:
        raise FixtureStateConflict(f"duplicate fixture discovery claims for {field_key}")
    if existing:
        claim = existing[0]
        if (
            claim.value_json,
            claim.source_url,
            claim.evidence_span,
            claim.artifact_key,
        ) != (value, source_url, evidence_span, artifact_key):
            raise FixtureStateConflict(f"fixture discovery claim differs for {field_key}")
        return claim
    if discovery:
        built = discovery_claim(
            entity_id=account_id,
            entity_type=EntityType.ACCOUNT,
            field_key=field_key,
            value_json=value,
            source_tier=2,
            extraction_method=ExtractionMethod.API,
            confidence=0.97,
            run_id=DISCOVERY_RUN_ID,
            research_mode=ResearchMode.ACCOUNT_DISCOVERY,
            found_via="exa_websets",
            matched_signal="must-have criterion evaluation",
            discovery_confidence=0.97,
            source_url=source_url,
            evidence_span=evidence_span,
            observed_at=OBSERVED_AT,
        )
    else:
        built = account_claim(
            entity_id=account_id,
            field_key=field_key,
            value_json=value,
            source_tier=2,
            extraction_method=ExtractionMethod.API,
            confidence=0.97,
            run_id=DISCOVERY_RUN_ID,
            research_mode=ResearchMode.ACCOUNT_PROFILING,
            source_url=source_url,
            evidence_span=evidence_span,
            observed_at=OBSERVED_AT,
        )
    built = revalidate_with(built, source_key="exa_websets", artifact_key=artifact_key)
    await insert_claim(conn, built)
    return built


async def _materialize_fixture_account(
    conn: AsyncConnection,
    *,
    account_id: EntityId,
    item_artifact_key: str,
) -> tuple[dict[str, Claim], Claim]:
    values: dict[str, tuple[str, JsonValue, str]] = {
        "identity.account_name": (
            "core.account_name",
            ACCOUNT_NAME,
            f"{ACCOUNT_NAME} is the canonical name returned for {ACCOUNT_DOMAIN}.",
        ),
        "identity.primary_domain": (
            "core.primary_domain",
            ACCOUNT_DOMAIN,
            f"The exact returned primary domain is {ACCOUNT_DOMAIN}.",
        ),
        "discovery.company_linkedin_url": (
            "core.company_linkedin_url",
            ACCOUNT_LINKEDIN_URL,
            f"The company profile for {ACCOUNT_NAME} is {ACCOUNT_LINKEDIN_URL}.",
        ),
        "discovery.industry": (
            "core.industry",
            "Gastroenterology specialty practice",
            f"{ACCOUNT_NAME} at {ACCOUNT_DOMAIN} is a gastroenterology specialty practice.",
        ),
        "discovery.employee_size": (
            "core.employee_count",
            42,
            f"{ACCOUNT_NAME} at {ACCOUNT_DOMAIN} has 42 employees in the recorded fixture.",
        ),
        "discovery.headquarters": (
            "core.hq_location",
            ACCOUNT_GEO,
            f"{ACCOUNT_NAME} at {ACCOUNT_DOMAIN} is headquartered in Portland, Oregon.",
        ),
        "discovery.revenue": (
            "core.revenue_band",
            "10m_50m",
            f"{ACCOUNT_NAME} at {ACCOUNT_DOMAIN} has recorded revenue band 10m_50m.",
        ),
    }
    claims: dict[str, Claim] = {}
    for logical_field in DISCOVERY_ENVELOPE_POLICY_V1.required_fields:
        key = str(logical_field)
        field_key, value, evidence = values[key]
        claims[key] = await _ensure_discovery_claim(
            conn,
            account_id=account_id,
            field_key=field_key,
            value=value,
            source_url=ACCOUNT_SOURCE_URL,
            evidence_span=evidence,
            artifact_key=item_artifact_key,
        )
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
                            "url": ACCOUNT_SOURCE_URL,
                            "title": ACCOUNT_NAME,
                            "snippet": f"{criterion}; exact account {ACCOUNT_DOMAIN}",
                        }
                    ],
                }
                for criterion in MUST_HAVE_CRITERIA
            ]
        },
    }
    criterion = await _ensure_discovery_claim(
        conn,
        account_id=account_id,
        field_key="core.discovery_provenance",
        value=criterion_value,
        source_url=ACCOUNT_SOURCE_URL,
        evidence_span=(
            f"All three must-have criteria returned yes for {ACCOUNT_NAME} at {ACCOUNT_DOMAIN}."
        ),
        artifact_key=item_artifact_key,
        discovery=True,
    )
    return claims, criterion


async def _ensure_sealed_batch(
    conn: AsyncConnection,
    *,
    storage: StorageBackend,
    deep_icp: ICPSpec,
) -> tuple[EntityId, str]:
    existing_seal = await get_discovery_batch_seal(
        conn, workspace_id=WORKSPACE_ID, batch_id=DISCOVERY_BATCH_ID
    )
    if existing_seal is not None:
        batch = await get_discovery_batch(
            conn, workspace_id=WORKSPACE_ID, batch_id=DISCOVERY_BATCH_ID
        )
        if batch is None or batch.state is not DiscoveryBatchState.SEALED:
            raise FixtureStateConflict("fixture discovery seal exists without a sealed batch")
        reader = DbSealedDiscoveryAccountManifestReader(
            storage=storage, conn_factory=_same_connection(conn)
        )
        sealed = await reader.read(
            workspace_id=WORKSPACE_ID,
            project_run_id=PROJECT_RUN_ID,
            icp_key=deep_icp.icp_key,
            icp_version=deep_icp.version,
        )
        if sealed is None or len(sealed.account_ids) != 1:
            raise FixtureStateConflict("fixture sealed account manifest differs")
        return sealed.account_ids[0], existing_seal.seal_sha256

    payloads = await _capture_discovery_payloads(conn, storage=storage)
    plan = _discovery_plan(deep_icp)
    await put_discovery_plan(conn, workspace_id=WORKSPACE_ID, plan=plan)
    await create_discovery_batch(
        conn,
        workspace_id=WORKSPACE_ID,
        batch_id=DISCOVERY_BATCH_ID,
        plan_id=DISCOVERY_PLAN_ID,
        generation=1,
    )
    fingerprint = hashlib.sha256(
        json.dumps(
            {
                "fixture": FIXTURE_VERSION,
                "plan_id": str(DISCOVERY_PLAN_ID),
                "account_domain": ACCOUNT_DOMAIN,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    planned = DiscoveryOperation(
        operation_id=DISCOVERY_OPERATION_ID,
        batch_id=DISCOVERY_BATCH_ID,
        workspace_id=WORKSPACE_ID,
        source_key="exa_websets",
        provider_api_version="v0",
        request_fingerprint=fingerprint,
        observation_window="fixture:2026-08-03",
        provider_external_id=discovery_provider_external_id(fingerprint),
        state=DiscoveryOperationState.PLANNED,
        spend_outcome=DiscoverySpendOutcome.NOT_DISPATCHED,
        provider_units_reserved=Decimal("10"),
        cost_cents_reserved=Decimal("100"),
    )
    await put_discovery_operation(conn, workspace_id=WORKSPACE_ID, operation=planned)

    page_key, page_body = payloads["page"]
    page = DiscoveryPageReceipt(
        operation_id=DISCOVERY_OPERATION_ID,
        resource_kind=DiscoveryPageResource.ITEMS,
        has_more=False,
        payload_artifact_key=page_key,
        payload_sha256=content_address(page_body),
        item_count=1,
        fetched_at=OBSERVED_AT + timedelta(seconds=2),
    )
    page_id = await put_discovery_page(conn, workspace_id=WORKSPACE_ID, page=page)

    item_key, item_body = payloads["item"]
    item = DiscoveryItemSnapshot(
        item_snapshot_id=DISCOVERY_ITEM_ID,
        operation_id=DISCOVERY_OPERATION_ID,
        provider_item_id="exa-account-deep-item-1",
        source_kind="webset_item",
        source_id="gastro-account-deep-fixture-search",
        raw_artifact_key=item_key,
        item_sha256=content_address(item_body),
        observed_at=OBSERVED_AT,
    )
    await put_discovery_item(conn, workspace_id=WORKSPACE_ID, item=item)
    await link_discovery_page_item(
        conn,
        workspace_id=WORKSPACE_ID,
        operation_id=DISCOVERY_OPERATION_ID,
        page_receipt_id=page_id,
        item_snapshot_id=DISCOVERY_ITEM_ID,
        ordinal=0,
    )
    await normalize_discovery_item(
        conn, workspace_id=WORKSPACE_ID, item_snapshot_id=DISCOVERY_ITEM_ID
    )

    request_key, _ = payloads["request"]
    submit_key, _ = payloads["submit"]
    response_key, _ = payloads["response"]
    terminal = planned.model_copy(
        update={
            "provider_operation_id": "exa-webset-account-deep-fixture",
            "state": DiscoveryOperationState.SUCCEEDED,
            "spend_outcome": DiscoverySpendOutcome.CHARGED,
            "submitted_receipt_ref": submit_key,
            "final_receipt_ref": response_key,
            "raw_request_artifact_key": request_key,
            "raw_response_manifest_key": response_key,
            "provider_units_charged": Decimal("10"),
            "cost_cents_charged": Decimal("100"),
            "started_at": OBSERVED_AT,
            "terminal_at": OBSERVED_AT + timedelta(seconds=3),
        }
    )
    await update_discovery_operation(conn, workspace_id=WORKSPACE_ID, operation=terminal)
    await mark_discovery_operation_reconciled(
        conn,
        workspace_id=WORKSPACE_ID,
        operation_id=DISCOVERY_OPERATION_ID,
        final_reconciliation=True,
        pagination_exhausted=True,
    )
    await reconcile_discovery_batch_costs(
        conn, workspace_id=WORKSPACE_ID, batch_id=DISCOVERY_BATCH_ID
    )
    await update_discovery_batch_state(
        conn,
        workspace_id=WORKSPACE_ID,
        batch_id=DISCOVERY_BATCH_ID,
        state=DiscoveryBatchState.IDENTITY_RESOLUTION,
    )
    await lock_discovery_batch_for_materialization(
        conn, workspace_id=WORKSPACE_ID, batch_id=DISCOVERY_BATCH_ID
    )

    account_id = await _ensure_account(conn)
    await put_discovery_candidate_link(
        conn,
        workspace_id=WORKSPACE_ID,
        batch_id=DISCOVERY_BATCH_ID,
        item_snapshot_id=DISCOVERY_ITEM_ID,
        admission_status=DiscoveryCandidateAdmissionState.ADMITTED,
        raw_name=ACCOUNT_NAME,
        candidate_domain=ACCOUNT_DOMAIN,
        source_url=ACCOUNT_SOURCE_URL,
        account_entity_id=account_id,
        survivor_entity_id=account_id,
    )
    claims, _criterion = await _materialize_fixture_account(
        conn, account_id=account_id, item_artifact_key=item_key
    )
    for logical_field, claim in claims.items():
        await put_discovery_field_resolution(
            conn,
            workspace_id=WORKSPACE_ID,
            resolution=DiscoveryFieldResolution(
                batch_id=DISCOVERY_BATCH_ID,
                account_entity_id=account_id,
                logical_field_key=logical_field,
                state=DiscoveryFieldResolutionState.RESOLVED,
                claim_ids=(claim.id,),
                winning_claim_id=claim.id,
                source_item_ids=(DISCOVERY_ITEM_ID,),
                updated_at=OBSERVED_AT + timedelta(seconds=4),
            ),
        )
    await index_account_discovery_artifacts(
        conn,
        workspace_id=WORKSPACE_ID,
        batch_id=DISCOVERY_BATCH_ID,
        account_entity_id=account_id,
    )
    await update_discovery_batch_state(
        conn,
        workspace_id=WORKSPACE_ID,
        batch_id=DISCOVERY_BATCH_ID,
        state=DiscoveryBatchState.SEAL_PENDING,
    )
    bundle = await build_discovery_batch_manifest(
        conn,
        storage,
        workspace_id=WORKSPACE_ID,
        batch_id=DISCOVERY_BATCH_ID,
    )
    seal = await seal_discovery_batch(
        conn,
        workspace_id=WORKSPACE_ID,
        batch_id=DISCOVERY_BATCH_ID,
        draft=bundle.seal_draft,
    )
    return account_id, seal.seal_sha256


def _same_connection(conn: AsyncConnection) -> ConnFactory:
    @asynccontextmanager
    async def _factory() -> AsyncIterator[AsyncConnection]:
        yield conn

    return _factory


async def _commit_handoff(
    conn: AsyncConnection,
    *,
    storage: StorageBackend,
    deep_icp: ICPSpec,
    account_id: EntityId,
    seal_sha256: str,
    directive_ref: str,
    directive_sha256: str,
) -> Claim:
    reader = DbSealedDiscoveryAccountManifestReader(
        storage=storage, conn_factory=_same_connection(conn)
    )
    sealed = await reader.read(
        workspace_id=WORKSPACE_ID,
        project_run_id=PROJECT_RUN_ID,
        icp_key=deep_icp.icp_key,
        icp_version=deep_icp.version,
    )
    if sealed is None or sealed.discovery_batch_id != DISCOVERY_BATCH_ID:
        raise FixtureStateConflict("account-deep fixture cannot read its sealed generation")
    policy = DiscoverySelectionPolicy.from_slot(deep_icp.discovery_strategy)
    selection = await load_discovery_criteria_selection(
        conn, sealed=sealed, workspace_id=WORKSPACE_ID, policy=policy
    )
    selected = next(
        (row for row in selection.accounts if row.account_id == account_id),
        None,
    )
    if selected is None or selected.disposition is not DiscoverySelectionDisposition.SELECTED:
        raise FixtureStateConflict(
            "fixture account did not pass every must-have and required field"
        )
    decision_version = selection_decision_version(
        policy_version=selection.policy_version,
        seal_sha256=seal_sha256,
        approved_account_ids=(account_id,),
    )

    # A true replay is read-only.  The generic checkpoint upsert and phase transition helpers are
    # intentionally mutable execution-state operations, so calling them again would move
    # ``updated_at``/``committed_at`` despite every immutable input being identical.  Recognize the
    # already-committed handoff, verify its exact lineage, and return the existing human tier claim.
    run = await get_project_run(conn, PROJECT_RUN_ID)
    checkpoints = {
        phase: await get_checkpoint(conn, PROJECT_RUN_ID, phase)
        for phase in (
            ProjectPhase.DISCOVERY,
            ProjectPhase.SCORING,
            ProjectPhase.TIER_CHECKPOINT,
        )
    }
    tier_checkpoint = checkpoints[ProjectPhase.TIER_CHECKPOINT]
    if (
        run is not None
        and run.phase is ProjectPhase.DEEP
        and run.status is ProjectRunStatus.ACTIVE
        and all(
            checkpoint is not None and checkpoint.status is PhaseCheckpointStatus.COMMITTED
            for checkpoint in checkpoints.values()
        )
        and tier_checkpoint is not None
    ):
        payload = tier_checkpoint.payload
        expected_payload = {
            "decision_action": "approve",
            "discovery_batch_id": str(DISCOVERY_BATCH_ID),
            "discovery_seal_sha256": seal_sha256,
            "approved_account_ids": [str(account_id)],
            "approved_tier": policy.approved_tier,
            "fixture_research_directive_ref": directive_ref,
            "fixture_research_directive_sha256": directive_sha256,
            "contact_reveals_allowed": False,
        }
        if any(payload.get(key) != value for key, value in expected_payload.items()):
            raise FixtureStateConflict("account-deep fixture committed handoff lineage differs")
        raw_claim_id = payload.get("tier_claim_id")
        existing_claims = [
            claim
            for claim in await claims_for(
                conn,
                account_id,
                TIER_FIELD,
                scope=WorkspaceScope.for_workspace(WORKSPACE_ID),
            )
            if str(claim.id) == raw_claim_id
        ]
        if len(existing_claims) != 1:
            raise FixtureStateConflict("fixture committed tier claim is absent or duplicated")
        return existing_claims[0]

    await upsert_checkpoint(
        conn,
        project_run_id=PROJECT_RUN_ID,
        phase=ProjectPhase.DISCOVERY,
        idempotency_key=f"a1-discovery-seal:{PROJECT_RUN_ID}",
        status=PhaseCheckpointStatus.COMMITTED,
        payload={
            "discovery_batch_id": str(DISCOVERY_BATCH_ID),
            "discovery_batch_seal_ref": seal_sha256,
            "account_manifest_ref": sealed.account_manifest_ref,
            "claim_manifest_ref": sealed.claim_manifest_ref,
        },
    )
    await set_phase(
        conn, PROJECT_RUN_ID, phase=ProjectPhase.SCORING, status=ProjectRunStatus.ACTIVE
    )
    await upsert_checkpoint(
        conn,
        project_run_id=PROJECT_RUN_ID,
        phase=ProjectPhase.SCORING,
        idempotency_key=f"a1-scoring-selection:{PROJECT_RUN_ID}",
        status=PhaseCheckpointStatus.COMMITTED,
        payload={
            "scoring_mode": "disabled",
            "selection_mode": "discovery_criteria",
            "selection_policy_version": selection.policy_version,
            "numeric_scores_written": 0,
            "selected_account_ids": [str(account_id)],
        },
    )
    await set_phase(
        conn,
        PROJECT_RUN_ID,
        phase=ProjectPhase.TIER_CHECKPOINT,
        status=ProjectRunStatus.ACTIVE,
    )
    tier_claim_id, _ = await persist_discovery_selection_tier(
        conn,
        view=selected,
        tier=policy.approved_tier,
        selection_policy_version=selection.policy_version,
        decision_version=decision_version,
        discovery_batch_id=str(DISCOVERY_BATCH_ID),
        discovery_seal_sha256=seal_sha256,
        project_run_id=PROJECT_RUN_ID,
        run_id=TIER_RUN_ID,
        workspace_id=WORKSPACE_ID,
        icp_key=deep_icp.icp_key,
        icp_version=deep_icp.version,
    )
    committee_plan_bytes = json.dumps(
        DEFAULT_RESEARCH_DIRECTIVE.committee_plan.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    committee_plan_ref = "committee-plan:" + hashlib.sha256(committee_plan_bytes).hexdigest()
    await upsert_checkpoint(
        conn,
        project_run_id=PROJECT_RUN_ID,
        phase=ProjectPhase.TIER_CHECKPOINT,
        idempotency_key=f"a1-tier-approval:{PROJECT_RUN_ID}",
        status=PhaseCheckpointStatus.COMMITTED,
        payload={
            "checkpoint_status": "resumed",
            "decision_action": "approve",
            "decision_basis": "discovery_criteria",
            "selection_policy_version": selection.policy_version,
            "decision_version": decision_version,
            "discovery_batch_id": str(DISCOVERY_BATCH_ID),
            "discovery_seal_sha256": seal_sha256,
            "approved_account_count": 1,
            "approved_account_ids": [str(account_id)],
            "approved_tier": policy.approved_tier,
            "tier_claim_id": str(tier_claim_id),
            "fixture_research_directive_ref": directive_ref,
            "fixture_research_directive_sha256": directive_sha256,
            "fixture_committee_plan_ref": committee_plan_ref,
            "human_confirmation_ref": "human:fixture:account-deep-a1",
            "contact_reveals_allowed": False,
        },
    )
    await set_phase(conn, PROJECT_RUN_ID, phase=ProjectPhase.DEEP, status=ProjectRunStatus.ACTIVE)
    matches = [
        claim
        for claim in await claims_for(
            conn,
            account_id,
            TIER_FIELD,
            scope=WorkspaceScope.for_workspace(WORKSPACE_ID),
        )
        if claim.id == tier_claim_id
    ]
    if len(matches) != 1:
        raise FixtureStateConflict("fixture human tier claim was not persisted exactly once")
    return matches[0]


async def seed_insight_health_account_deep_fixture(
    conn: AsyncConnection,
    *,
    pages: Mapping[str, OfficialSitePage],
    storage: StorageBackend,
) -> InsightHealthAccountDeepFixtureResult:
    """Seed A1 Level A + B without provider I/O or an already-created ``account_run``.

    The caller owns the surrounding transaction. Replaying unchanged inputs returns the same
    references and adds no equivalent account, claim, operation, manifest, seal, checkpoint, or
    tier decision. The original discovery fixture's ICP and project run remain untouched.
    """

    discovery = await seed_insight_health_discovery_fixture(conn, pages=pages, storage=storage)
    original_icp = await get_active_icp(conn, WORKSPACE_ID, discovery.icp_key)
    if original_icp is None or original_icp.version != discovery.icp_version:
        raise FixtureStateConflict("the upstream discovery fixture ICP is absent")

    await load_research_packs(conn)
    deep_icp = await _ensure_deep_icp(conn, discovery=discovery)
    preserved_icp = await get_active_icp(conn, WORKSPACE_ID, discovery.icp_key)
    if preserved_icp != original_icp:
        raise FixtureStateConflict("account-deep fixture mutated the discovery fixture ICP")

    directive_ref, directive_sha256, provider_keys = await _capture_fixture_artifacts(
        conn, storage=storage
    )
    await _ensure_deep_project_run(conn, discovery=discovery, deep_icp=deep_icp)
    account_id, seal_sha256 = await _ensure_sealed_batch(conn, storage=storage, deep_icp=deep_icp)
    tier_claim = await _commit_handoff(
        conn,
        storage=storage,
        deep_icp=deep_icp,
        account_id=account_id,
        seal_sha256=seal_sha256,
        directive_ref=directive_ref,
        directive_sha256=directive_sha256,
    )
    run = await get_project_run(conn, PROJECT_RUN_ID)
    if (
        run is None
        or run.phase is not ProjectPhase.DEEP
        or run.status is not ProjectRunStatus.ACTIVE
    ):
        raise FixtureStateConflict("account-deep fixture project run is not ready at DEEP")
    for phase in (
        ProjectPhase.DISCOVERY,
        ProjectPhase.SCORING,
        ProjectPhase.TIER_CHECKPOINT,
    ):
        checkpoint = await get_checkpoint(conn, PROJECT_RUN_ID, phase)
        if checkpoint is None or checkpoint.status is not PhaseCheckpointStatus.COMMITTED:
            raise FixtureStateConflict(f"fixture checkpoint {phase.value} is not committed")

    expected_account_run = deep_account_run_id(PROJECT_RUN_ID, account_id)
    if await get_account_run(conn, expected_account_run) is not None:
        raise FixtureStateConflict("A1 must not pre-create the orchestrator-owned account_run")
    committee_plan_bytes = json.dumps(
        DEFAULT_RESEARCH_DIRECTIVE.committee_plan.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return InsightHealthAccountDeepFixtureResult(
        fixture_version=FIXTURE_VERSION,
        discovery_fixture=discovery,
        deep_icp_key=deep_icp.icp_key,
        deep_icp_version=deep_icp.version,
        deep_field_keys=DEEP_FIELD_KEYS,
        source_override_version=SOURCE_OVERRIDE_VERSION,
        selected_account_id=account_id,
        project_run_id=PROJECT_RUN_ID,
        project_phase=run.phase,
        discovery_plan_id=DISCOVERY_PLAN_ID,
        discovery_batch_id=DISCOVERY_BATCH_ID,
        discovery_operation_id=DISCOVERY_OPERATION_ID,
        discovery_item_id=DISCOVERY_ITEM_ID,
        discovery_seal_sha256=seal_sha256,
        tier_claim_id=UUID(str(tier_claim.id)),
        directive_ref=directive_ref,
        directive_sha256=directive_sha256,
        committee_plan_ref="committee-plan:" + hashlib.sha256(committee_plan_bytes).hexdigest(),
        provider_artifact_keys=provider_keys,
        expected_account_run_id=expected_account_run,
    )


__all__ = [
    "ACCOUNT_DOMAIN",
    "ACCOUNT_NAME",
    "ACCOUNT_SOURCE_URL",
    "DEEP_FIELD_KEYS",
    "DEEP_ICP_KEY",
    "DEFAULT_COMMITTEE_CANDIDATES",
    "DEFAULT_RECORDED_FIELDS",
    "DEFAULT_RESEARCH_DIRECTIVE",
    "DISCOVERY_BATCH_ID",
    "DISCOVERY_ITEM_ID",
    "DISCOVERY_OPERATION_ID",
    "DISCOVERY_PLAN_ID",
    "FIXTURE_VERSION",
    "FixtureCommitteePlan",
    "FixtureResearchDirective",
    "FixtureResearchQuestion",
    "InsightHealthAccountDeepFixtureResult",
    "MUST_HAVE_CRITERIA",
    "PROJECT_RUN_ID",
    "RecordedAccountDeepCommitteeSource",
    "RecordedAccountDeepResolver",
    "RecordedAccountField",
    "build_recorded_account_resolvers",
    "build_recorded_committee_source",
    "seed_insight_health_account_deep_fixture",
]
