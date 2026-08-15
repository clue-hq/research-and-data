"""Reproducible Insight Health/Aura Stage-0 handoff for discovery acceptance.

This module seeds the *output* of Stage 0, not a shortcut around its contracts. Public Insight
Health pages are captured as tenant-bound artifacts; the official-site facts are then written
through ``reverse_profile`` as tier-2, unverified scrape claims. The fixture also creates the
workspace/brand/product/project spine, a confirmed ICP with full Client-KB/product lineage, an
immutable product-context version, a discovery-spend readiness decision, and a durable project run
whose phase is exactly ``discovery``.

The input pages come from a prior, explicit Firecrawl harvest. This builder performs no network
I/O, which makes replay deterministic and prevents a fixture rerun from silently spending again.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, ConfigDict, JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.stage0_tools import start_confirmed_project_run
from clue_config import DEFAULT_STAGE0_POLICY
from clue_core import (
    Entity,
    EntityId,
    ExtractionMethod,
    FieldDef,
    ICPCreatedFrom,
    OnboardingInputId,
    OnboardingInputKind,
    ProjectPhase,
    ProjectRunId,
    RawArtifact,
    ReadinessDecisionId,
    ReadinessGate,
    ReadinessVerdict,
    ResearchMode,
    RunId,
    account_claim,
    revalidate_with,
)
from clue_research.claimstore import load_core_pack
from clue_research.durable import get_project_run
from clue_research.icp import (
    RubricEntry,
    ScoringRubric,
    ScoringTransform,
    SubRubric,
    TierBand,
    TierCutoffs,
    create_icp_spec,
    get_active_icp,
    load_starter_packs,
    rubric_to_slot,
)
from clue_research.sources import (
    bind_resolver,
    get_resolver,
    is_resolver_bound,
    seed_source_manifests,
    unbind_resolver,
)
from clue_research.stage0 import (
    ClientInput,
    client_kb_readiness_metrics,
    compile_product_context,
    evaluate_readiness,
    get_onboarding_input,
    get_readiness_decision,
    get_workspace_client_kb_readiness_policy,
    load_client_knowledge_pack,
    load_icp_feedback_pack,
    load_import_pack,
    read_client_kb_claims,
    reverse_profile,
    submit_onboarding_input,
)
from clue_research.stage0.fields import (
    CLIENT_CUSTOMER,
    CLIENT_DIFFERENTIATOR,
    CLIENT_ICP_EVIDENCE,
    CLIENT_PRICING_POSTURE,
    CLIENT_PRODUCT,
    CLIENT_PROOF_POINT,
    CLIENT_VALUE_PROP,
)
from clue_spine import (
    Brand,
    Product,
    Project,
    Workspace,
    create_brand,
    create_product,
    create_project,
    create_workspace,
    get_brand,
    get_product,
    get_project,
    get_workspace,
)
from clue_storage import SnapshotSink, StorageBackend, flush_snapshots

WORKSPACE_ID = "ws_fixture_insight_health_aura"
BRAND_ID = "brd_fixture_insight_health"
PRODUCT_ID = "prd_fixture_aura_ai"
PROJECT_ID = "prj_fixture_aura_neurosurgery_discovery"
ICP_KEY = "independent_neurosurgery_spine_practices_us"

WORKSPACE_NAME = "Insight Health AI discovery fixture"
BRAND_NAME = "Insight Health AI"
PRODUCT_NAME = "Aura AI"
PROJECT_NAME = "Aura AI - U.S. independent neurosurgery discovery"

HOME_URL = "https://www.insighthealth.ai/"
AMBIENT_URL = "https://www.insighthealth.ai/ambient"
AURA_ANYWHERE_URL = "https://www.insighthealth.ai/aura-anywhere"
NEUROSURGERY_URL = "https://www.insighthealth.ai/use-cases/neurosurgery-referral-management"
REQUIRED_URLS = (HOME_URL, AMBIENT_URL, AURA_ANYWHERE_URL, NEUROSURGERY_URL)

SOURCE_KEY = "firecrawl_site"
HARVESTED_AT = datetime(2026, 8, 2, tzinfo=UTC)
FIXTURE_COMPILER_VERSION = "insight-health-aura-stage0-fixture@2"


def _stable_uuid(label: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"clue://fixtures/insight-health-aura/{label}")


STAGE0_RUN_ID = RunId(_stable_uuid("stage0-run"))
ONBOARDING_INPUT_ID = OnboardingInputId(_stable_uuid("onboarding-input"))
READINESS_DECISION_ID = ReadinessDecisionId(_stable_uuid("readiness-decision"))
PROJECT_RUN_ID = ProjectRunId(_stable_uuid("project-run"))


class OfficialSitePage(BaseModel):
    """One already-fetched official page used by the fixture."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    url: str
    title: str
    markdown: str


def recorded_insight_health_pages() -> dict[str, OfficialSitePage]:
    """Return the bounded official-page snapshots used by local Insight Health fixtures.

    The excerpts are the already-harvested evidence inputs for the fixture, not a live fetch. They
    intentionally contain only the spans needed to support the seven Client-KB claims below.
    """

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
            title="Aura AI scribe for clinical notes",
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
            title="Neurosurgery Referral Management",
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


class InsightHealthDiscoveryFixtureResult(BaseModel):
    """Stable references emitted for the subsequent discovery acceptance run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fixture_version: str
    workspace_id: str
    brand_id: str
    product_id: str
    project_id: str
    client_entity_id: str
    client_kb_version: int
    stage0_run_id: str
    onboarding_input_id: str
    icp_key: str
    icp_version: int
    product_context_version_id: str
    readiness_decision_id: str
    readiness_verdict: str
    project_run_id: str
    project_phase: str
    client_kb_fields: tuple[str, ...]
    client_claim_ids: dict[str, str]
    artifact_keys_by_url: dict[str, str]
    source_urls: tuple[str, ...]


class FixtureInputError(ValueError):
    """The harvested pages cannot support the promised fixture claims."""


class FixtureStateConflict(RuntimeError):
    """A deterministic fixture id already names different persisted state."""


def load_firecrawl_search_pages(paths: Sequence[str | Path]) -> dict[str, OfficialSitePage]:
    """Load required pages from Firecrawl CLI ``search --scrape --json`` outputs.

    The loader accepts several search outputs because the Aura product pages and the neurosurgery
    case study may come from separate searches. Duplicate URLs must carry identical markdown; a
    conflicting snapshot fails closed instead of picking one silently.
    """

    pages: dict[str, OfficialSitePage] = {}
    for raw_path in paths:
        path = Path(raw_path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise FixtureInputError(f"could not read Firecrawl result {path}: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise FixtureInputError(f"Firecrawl result {path} is not a successful search payload")
        data = payload.get("data")
        web = data.get("web") if isinstance(data, dict) else None
        if not isinstance(web, list):
            raise FixtureInputError(f"Firecrawl result {path} has no data.web list")
        for raw_item in web:
            if not isinstance(raw_item, dict):
                continue
            url = raw_item.get("url")
            markdown = raw_item.get("markdown")
            title = raw_item.get("title")
            if not isinstance(url, str) or not isinstance(markdown, str) or not markdown.strip():
                continue
            page = OfficialSitePage(
                url=url,
                title=title if isinstance(title, str) else url,
                markdown=markdown,
            )
            prior = pages.get(url)
            if prior is not None and prior.markdown != page.markdown:
                raise FixtureInputError(f"conflicting harvested snapshots for {url}")
            pages[url] = page

    missing = [url for url in REQUIRED_URLS if url not in pages]
    if missing:
        raise FixtureInputError(f"required Insight Health pages are missing: {missing}")
    return {url: pages[url] for url in REQUIRED_URLS}


def _exact_span(markdown: str, start: str, end: str) -> str:
    """Return a bounded exact substring, failing before any database mutation."""

    try:
        start_index = markdown.index(start)
        end_index = markdown.index(end, start_index) + len(end)
    except ValueError as exc:
        raise FixtureInputError(
            f"official-site evidence markers were not found: start={start!r}, end={end!r}"
        ) from exc
    span = markdown[start_index:end_index]
    if len(span) > 2_000:
        raise FixtureInputError(f"official-site evidence span is too large ({len(span)} chars)")
    return span


@dataclass(frozen=True)
class _ClaimSource:
    field_key: str
    value: JsonValue
    source_url: str
    evidence_span: str
    confidence: float = 0.92


def claim_sources_for_pages(
    pages: Mapping[str, OfficialSitePage],
) -> dict[str, _ClaimSource]:
    """Compile the seven supported Client-KB facts and validate their exact evidence spans."""

    home = pages[HOME_URL].markdown
    ambient = pages[AMBIENT_URL].markdown
    anywhere = pages[AURA_ANYWHERE_URL].markdown
    neuro = pages[NEUROSURGERY_URL].markdown
    sources = (
        _ClaimSource(
            field_key=CLIENT_VALUE_PROP,
            value=(
                "Insight Health AI positions itself as an AI referral coordinator for specialty "
                "practices, routing inbound clinical and administrative documents into the EHR "
                "and following open actions."
            ),
            source_url=HOME_URL,
            evidence_span=_exact_span(
                home,
                "# The AI referral coordinator for specialty practices.",
                "so nothing stalls on the fax machine.",
            ),
        ),
        _ClaimSource(
            field_key=CLIENT_PRODUCT,
            value=(
                "Aura AI Scribe listens to patient-provider conversations and generates structured "
                "clinical notes in real time while the provider focuses on the patient."
            ),
            source_url=AURA_ANYWHERE_URL,
            evidence_span=_exact_span(
                anywhere,
                "### Ambient Documentation",
                "documentation happens in the background.",
            ),
        ),
        _ClaimSource(
            field_key=CLIENT_DIFFERENTIATOR,
            value=(
                "Aura supports specialty-specific customizable documentation, ICD-10/CPT coding "
                "suggestions, and browser/EHR workflows through an iOS app and Chrome extension."
            ),
            source_url=AMBIENT_URL,
            evidence_span=_exact_span(
                ambient,
                "## Fully Customizable Note Format",
                "without disruptive switching between applications.",
            ),
        ),
        _ClaimSource(
            field_key=CLIENT_PRICING_POSTURE,
            value=(
                "Aura advertises a free-forever entry tier, monthly or annual per-clinician paid "
                "plans, and custom enterprise pricing, with cancellation at any time."
            ),
            source_url=HOME_URL,
            evidence_span=_exact_span(
                home,
                "## Pricing",
                "Includes Virtual Care Assistant (VCA) + AuraTM AI Scribe.",
            ),
        ),
        _ClaimSource(
            field_key=CLIENT_PROOF_POINT,
            value=(
                "Insight Health publishes a 15-provider neurosurgery case study claiming $350k "
                "annual overhead savings, 15 minutes saved per consultation, and 12x+ ROI. These "
                "are vendor-published claims, not independently verified results."
            ),
            source_url=NEUROSURGERY_URL,
            evidence_span=_exact_span(
                neuro,
                "Results\n\n$350k",
                "Return on Investment",
            ),
        ),
        _ClaimSource(
            field_key=CLIENT_CUSTOMER,
            value=[
                {
                    "name": "The Oregon Clinic",
                    "relationship_evidence": "named organization in an official-site testimonial",
                    "verification_note": (
                        "The testimonial attribution is preserved; customer status is not "
                        "independently verified."
                    ),
                }
            ],
            source_url=NEUROSURGERY_URL,
            evidence_span=_exact_span(
                neuro,
                '"For the first time my notes are actually done',
                "\\- Neurosurgeon, The Oregon Clinic",
            ),
            confidence=0.85,
        ),
        _ClaimSource(
            field_key=CLIENT_ICP_EVIDENCE,
            value={
                "segment": "independent neurosurgery and spine practices",
                "specialty": "neurosurgery",
                "practice_provider_count": 15,
                "monthly_referrals_lower_bound": 500,
                "weekly_phone_screening_hours_lower_bound": 20,
                "reported_no_show_rate_percent": 20,
                "observed_need": "referral screening and intake workflow automation",
                "verification_note": (
                    "vendor-published case-study inputs; not independently verified"
                ),
            },
            source_url=NEUROSURGERY_URL,
            evidence_span=_exact_span(
                neuro,
                "## Case Study: 15-Provider Neurosurgery Practice",
                "20% no-show rate causing scheduling inefficiency",
            ),
        ),
    )
    return {source.field_key: source for source in sources}


class OfficialSiteFixtureResolver:
    """Tier-2 resolver over immutable harvested pages; it performs no network call."""

    tier = 2

    def __init__(
        self,
        *,
        sources: Mapping[str, _ClaimSource],
        artifact_keys_by_url: Mapping[str, str],
        run_id: RunId = STAGE0_RUN_ID,
    ) -> None:
        self._sources = sources
        self._artifact_keys_by_url = artifact_keys_by_url
        self._run_id = run_id

    def resolve(self, entity: Entity, field: FieldDef) -> list[Any]:
        source = self._sources.get(field.field_key)
        if source is None:
            return []
        claim = account_claim(
            entity_id=entity.entity_id,
            field_key=field.field_key,
            value_json=source.value,
            source_tier=2,
            extraction_method=ExtractionMethod.SCRAPE,
            confidence=source.confidence,
            run_id=self._run_id,
            research_mode=ResearchMode.ACCOUNT_PROFILING,
            source_url=source.source_url,
            evidence_span=source.evidence_span,
            observed_at=HARVESTED_AT,
            cost_cents=Decimal("1"),
        )
        return [
            revalidate_with(
                claim,
                artifact_key=self._artifact_keys_by_url[source.source_url],
            )
        ]


async def _ensure_spine(conn: AsyncConnection) -> tuple[Workspace, Brand, Product, Project]:
    workspace = await get_workspace(conn, WORKSPACE_ID)
    if workspace is None:
        workspace = await create_workspace(
            conn,
            workspace_id=WORKSPACE_ID,
            name=WORKSPACE_NAME,
        )
    elif workspace.name != WORKSPACE_NAME:
        raise FixtureStateConflict(f"{WORKSPACE_ID} already names another workspace")

    brand = await get_brand(conn, workspace_id=WORKSPACE_ID, brand_id=BRAND_ID)
    if brand is None:
        brand = await create_brand(
            conn,
            workspace_id=WORKSPACE_ID,
            brand_id=BRAND_ID,
            name=BRAND_NAME,
        )
    elif brand.name != BRAND_NAME:
        raise FixtureStateConflict(f"{BRAND_ID} already names another brand")

    product = await get_product(conn, PRODUCT_ID)
    expected_aliases = ("Aura", "Aura AI Scribe", "Aura Anywhere")
    if product is None:
        product = await create_product(
            conn,
            workspace_id=WORKSPACE_ID,
            brand_id=BRAND_ID,
            product_id=PRODUCT_ID,
            name=PRODUCT_NAME,
            aliases=expected_aliases,
        )
    elif (
        product.workspace_id,
        product.brand_id,
        product.name,
        product.aliases,
    ) != (WORKSPACE_ID, BRAND_ID, PRODUCT_NAME, expected_aliases):
        raise FixtureStateConflict(f"{PRODUCT_ID} already names another product")

    project = await get_project(conn, PROJECT_ID)
    if project is None:
        project = await create_project(
            conn,
            workspace_id=WORKSPACE_ID,
            brand_id=BRAND_ID,
            product_id=PRODUCT_ID,
            project_id=PROJECT_ID,
            name=PROJECT_NAME,
        )
    elif (
        project.workspace_id,
        project.brand_id,
        project.product_id,
        project.name,
    ) != (WORKSPACE_ID, BRAND_ID, PRODUCT_ID, PROJECT_NAME):
        raise FixtureStateConflict(f"{PROJECT_ID} already names another project")
    return workspace, brand, product, project


async def _load_fixture_registries(conn: AsyncConnection) -> None:
    await load_core_pack(conn)
    await load_client_knowledge_pack(conn)
    await load_starter_packs(conn)
    await load_icp_feedback_pack(conn)
    await load_import_pack(conn)
    await seed_source_manifests(conn)


async def capture_insight_health_pages(
    conn: AsyncConnection,
    *,
    pages: Mapping[str, OfficialSitePage],
    storage: StorageBackend,
    workspace_id: str = WORKSPACE_ID,
    fixture_version: str = FIXTURE_COMPILER_VERSION,
) -> dict[str, str]:
    """Persist the four recorded official-site pages under one fixture workspace."""

    sink = SnapshotSink(workspace_id=workspace_id)
    keys: dict[str, str] = {}
    for url in REQUIRED_URLS:
        page = pages[url]
        keys[url] = sink.capture(
            RawArtifact(
                ref=url,
                media_type="text/markdown",
                content=page.markdown.encode("utf-8"),
                metadata={
                    "title": page.title,
                    "fixture": fixture_version,
                    "harvested_at": HARVESTED_AT.isoformat(),
                },
            ),
            source_key=SOURCE_KEY,
        )
    await flush_snapshots(conn, storage, sink)
    return keys


def _discovery_strategy() -> dict[str, JsonValue]:
    return {
        "mode": "platform_led",
        "channels": ["exa_websets"],
        "requested_count": 2,
        "entity_type": "company",
        "query": (
            "Independent neurosurgery and spine specialty practices in the United States with "
            "multiple providers and public evidence of referral intake or scheduling workflows"
        ),
        "geographies": ["US"],
        "must_have_criteria": [
            "U.S.-based independent neurosurgery or spine specialty practice",
            "Not a general hospital, health system, or hospital-employed department",
            "Multiple providers and public evidence of referral or intake workflow",
        ],
        "scoring_mode": "disabled",
        "selection_mode": "discovery_criteria",
        "approved_tier": "high",
        "required_account_fields": [
            "account_name",
            "primary_domain",
            "company_linkedin_url",
            "employee_count_or_range",
            "revenue_or_band",
            "headquarters_location",
            "industry",
        ],
        "optional_account_fields": ["company_email", "company_phone"],
        "discovery_completion_policy": "closed_durable_batch",
        "advance_only_after": "immutable_discovery_batch_seal",
    }


def _source_profile_ref() -> dict[str, JsonValue]:
    return {
        "account_discovery": ["exa_websets"],
        "account_gap_enrichment": ["sumble_organizations"],
        "committee_after_tier_checkpoint": ["sumble_people", "sumble_teams", "sumble_jobs"],
        "deferred": ["sumble_signals", "sumble_priority_signals", "sumble_intelligence_briefs"],
    }


def _scoring_rubric() -> ScoringRubric:
    return ScoringRubric(
        fit=SubRubric(
            entries=(
                RubricEntry(
                    field_key="core.primary_domain",
                    weight=0.2,
                    transform=ScoringTransform.BOOLEAN,
                    label="Grounded public domain",
                ),
                RubricEntry(
                    field_key="core.employee_count",
                    weight=0.4,
                    transform=ScoringTransform.LINEAR,
                    params={"lo": 5, "hi": 200},
                    label="Multi-provider practice-size proxy",
                ),
                RubricEntry(
                    field_key="healthcare.npi",
                    weight=0.4,
                    transform=ScoringTransform.BOOLEAN,
                    label="Healthcare registry identity",
                ),
            )
        ),
        intent=SubRubric(entries=()),
        tier_cutoffs=TierCutoffs(
            bands=(
                TierBand(tier="top", min_fit=0.75, min_intent=0.0),
                TierBand(tier="high", min_fit=0.55, min_intent=0.0),
            ),
            fallback_tier="low",
        ),
        fit_floor=0.35,
        version=1,
        label="Aura independent neurosurgery discovery rubric",
        notes=(
            "Initial Pass-A rubric. Buying-committee work remains gated to approved top/high "
            "accounts that pass every must-have criterion."
        ),
    )


async def _ensure_icp(
    conn: AsyncConnection,
    *,
    client_entity_id: EntityId,
    client_kb_version: int,
) -> Any:
    field_keys = ("core.primary_domain", "core.employee_count", "healthcare.npi")
    strategy = _discovery_strategy()
    source_profile = _source_profile_ref()
    rubric = rubric_to_slot(_scoring_rubric())
    existing = await get_active_icp(conn, WORKSPACE_ID, ICP_KEY)
    if existing is None:
        return await create_icp_spec(
            conn,
            workspace_id=WORKSPACE_ID,
            icp_key=ICP_KEY,
            created_from=ICPCreatedFrom.SYNTHESIS,
            field_keys=field_keys,
            enabled_packs=("healthcare_practice",),
            discovery_strategy=strategy,
            source_profile_ref=source_profile,
            scoring_rubric=rubric,
            created_by="system:insight-health-discovery-fixture",
            label="U.S. independent neurosurgery and spine practices",
            description=(
                "Independent U.S. neurosurgery and spine specialty practices with multiple "
                "providers and referral-intake or scheduling workflow pain. Excludes general "
                "hospitals, health systems, and hospital-employed departments."
            ),
            activate=True,
            client_entity_id=client_entity_id,
            client_kb_version=client_kb_version,
            product_id=PRODUCT_ID,
        )

    expected = {
        "created_from": ICPCreatedFrom.SYNTHESIS,
        "field_keys": field_keys,
        "enabled_packs": ("healthcare_practice",),
        "discovery_strategy": strategy,
        "source_profile_ref": source_profile,
        "scoring_rubric": rubric,
        "client_entity_id": client_entity_id,
        "client_kb_version": client_kb_version,
        "product_id": PRODUCT_ID,
    }
    mismatched = [key for key, value in expected.items() if getattr(existing, key) != value]
    if mismatched:
        raise FixtureStateConflict(f"active fixture ICP differs in fields: {mismatched}")
    return existing


async def seed_insight_health_discovery_fixture(
    conn: AsyncConnection,
    *,
    pages: Mapping[str, OfficialSitePage],
    storage: StorageBackend,
) -> InsightHealthDiscoveryFixtureResult:
    """Seed and return one replay-safe Stage-0 handoff for account discovery testing.

    The caller owns the surrounding transaction. Calling this twice against unchanged inputs
    reuses the same client claims, ICP version, product context, readiness decision, and project
    run; it performs no network I/O and writes no duplicate claims.
    """

    missing = [url for url in REQUIRED_URLS if url not in pages]
    if missing:
        raise FixtureInputError(f"required Insight Health pages are missing: {missing}")
    claim_sources = claim_sources_for_pages(
        pages
    )  # validate every evidence marker before mutating state

    _, brand, product, project = await _ensure_spine(conn)
    await _load_fixture_registries(conn)
    artifact_keys = await capture_insight_health_pages(conn, pages=pages, storage=storage)

    prior_resolver = get_resolver(SOURCE_KEY) if is_resolver_bound(SOURCE_KEY) else None
    bind_resolver(
        SOURCE_KEY,
        OfficialSiteFixtureResolver(
            sources=claim_sources,
            artifact_keys_by_url=artifact_keys,
        ),
    )
    try:
        profile = await reverse_profile(
            conn,
            ClientInput(name=BRAND_NAME, website=HOME_URL),
            workspace_id=WORKSPACE_ID,
            run_id=STAGE0_RUN_ID,
            budget_cap_cents=Decimal("20"),
            max_source_tier=2,
        )
    finally:
        if prior_resolver is None:
            unbind_resolver(SOURCE_KEY)
        else:
            bind_resolver(SOURCE_KEY, prior_resolver)

    client_entity_id = profile.ref.client_entity_id
    client_kb_version = profile.ref.client_kb_version
    home_sha256 = hashlib.sha256(pages[HOME_URL].markdown.encode("utf-8")).hexdigest()
    onboarding = await submit_onboarding_input(
        conn,
        workspace_id=WORKSPACE_ID,
        brand_id=BRAND_ID,
        product_id=PRODUCT_ID,
        project_id=PROJECT_ID,
        client_entity_id=client_entity_id,
        kind=OnboardingInputKind.WEBSITE,
        artifact_key=artifact_keys[HOME_URL],
        content_sha256=home_sha256,
        source_ref=HOME_URL,
        actor="human",
        onboarding_input_id=ONBOARDING_INPUT_ID,
    )
    stored_onboarding = await get_onboarding_input(
        conn,
        onboarding.onboarding_input_id,
        workspace_id=WORKSPACE_ID,
    )
    if stored_onboarding is None or (
        stored_onboarding.client_entity_id,
        stored_onboarding.source_ref,
        stored_onboarding.actor,
    ) != (client_entity_id, HOME_URL, "human"):
        raise FixtureStateConflict("fixture onboarding input replayed with different context")

    spec = await _ensure_icp(
        conn,
        client_entity_id=client_entity_id,
        client_kb_version=client_kb_version,
    )
    kb_claims = await read_client_kb_claims(
        conn,
        client_entity_id,
        workspace_id=WORKSPACE_ID,
        version=client_kb_version,
        product_id=None,
    )
    expected_fields = set(claim_sources)
    if set(kb_claims) != expected_fields:
        raise FixtureStateConflict(
            "fixture Client KB does not match supported official-site fields: "
            f"expected={sorted(expected_fields)}, actual={sorted(kb_claims)}"
        )
    for field_key, claim in kb_claims.items():
        source = claim_sources[field_key]
        page = pages[source.source_url]
        if (
            claim.source_tier != 2
            or claim.extraction_method is not ExtractionMethod.SCRAPE
            or claim.source_key != SOURCE_KEY
            or claim.source_url != source.source_url
            or claim.artifact_key != artifact_keys[source.source_url]
            or claim.evidence_span is None
            or claim.evidence_span not in page.markdown
        ):
            raise FixtureStateConflict(f"fixture claim {field_key} lost official-site provenance")

    ordered_fields = tuple(sorted(kb_claims))
    context = await compile_product_context(
        conn,
        workspace_id=WORKSPACE_ID,
        brand_id=BRAND_ID,
        product_id=PRODUCT_ID,
        client_entity_id=client_entity_id,
        client_kb_version=client_kb_version,
        claim_refs=tuple(str(kb_claims[key].id) for key in ordered_fields),
        artifact_refs=tuple(sorted(set(artifact_keys.values()))),
        freshness_snapshot={
            "official_site_observed_at": HARVESTED_AT.isoformat(),
            "source_key": SOURCE_KEY,
        },
        compiler_version=FIXTURE_COMPILER_VERSION,
    )
    readiness_metrics = client_kb_readiness_metrics(kb_claims)
    readiness_metrics["open_policy_blocks"] = 0
    readiness = await evaluate_readiness(
        conn,
        workspace_id=WORKSPACE_ID,
        brand_id=BRAND_ID,
        product_id=PRODUCT_ID,
        project_id=PROJECT_ID,
        client_entity_id=client_entity_id,
        client_kb_version=client_kb_version,
        icp_key=spec.icp_key,
        icp_version=spec.version,
        product_context_version_id=context.version_id,
        gate=ReadinessGate.DISCOVERY_SPEND,
        spec=DEFAULT_STAGE0_POLICY.readiness,
        metrics=readiness_metrics,
        created_by_actor="system",
        readiness_decision_id=READINESS_DECISION_ID,
    )
    if readiness.verdict is not ReadinessVerdict.READY:
        raise FixtureStateConflict(f"fixture is not ready for discovery: {readiness.verdict}")
    stored_readiness = await get_readiness_decision(
        conn,
        readiness.readiness_decision_id,
        workspace_id=WORKSPACE_ID,
    )
    # ``evaluate_readiness`` augments the caller metrics with the resolved workspace readiness
    # policy.  Compare against that persisted contract, not only the caller-owned base metrics;
    # otherwise the fixture rejects its own first write after tenant-local readiness policy landed.
    workspace_policy = await get_workspace_client_kb_readiness_policy(
        conn, workspace_id=WORKSPACE_ID
    )
    workspace_required = (
        workspace_policy.required_field_keys if workspace_policy is not None else ()
    )
    raw_available_fields = readiness_metrics.get("available_field_keys", [])
    available_fields = (
        {item for item in raw_available_fields if isinstance(item, str)}
        if isinstance(raw_available_fields, list)
        else set()
    )
    expected_readiness_metrics = {
        **readiness_metrics,
        "workspace_readiness_policy_version": workspace_policy.version if workspace_policy else 0,
        "workspace_required_field_keys": list(workspace_required),
        "workspace_required_missing_field_keys": sorted(set(workspace_required) - available_fields),
    }
    if stored_readiness is None or stored_readiness.metrics != expected_readiness_metrics:
        raise FixtureStateConflict("fixture readiness replayed with different metrics")

    await start_confirmed_project_run(
        conn,
        project_run_id=PROJECT_RUN_ID,
        workspace_id=WORKSPACE_ID,
        project_id=PROJECT_ID,
        client_entity_id=client_entity_id,
        client_kb_version=client_kb_version,
        product_id=PRODUCT_ID,
        product_context_version_id=context.version_id,
        readiness_decision_id=readiness.readiness_decision_id,
        icp_key=spec.icp_key,
        icp_version=spec.version,
        budget_cap_cents=Decimal("1000"),
    )
    project_run = await get_project_run(conn, PROJECT_RUN_ID)
    if project_run is None or project_run.phase is not ProjectPhase.DISCOVERY:
        raise FixtureStateConflict("fixture project run is not stopped at discovery")

    return InsightHealthDiscoveryFixtureResult(
        fixture_version=FIXTURE_COMPILER_VERSION,
        workspace_id=WORKSPACE_ID,
        brand_id=brand.brand_id,
        product_id=product.product_id,
        project_id=project.project_id,
        client_entity_id=str(client_entity_id),
        client_kb_version=client_kb_version,
        stage0_run_id=str(profile.run_id),
        onboarding_input_id=str(onboarding.onboarding_input_id),
        icp_key=spec.icp_key,
        icp_version=spec.version,
        product_context_version_id=str(context.version_id),
        readiness_decision_id=str(readiness.readiness_decision_id),
        readiness_verdict=readiness.verdict.value,
        project_run_id=str(PROJECT_RUN_ID),
        project_phase=project_run.phase.value,
        client_kb_fields=ordered_fields,
        client_claim_ids={key: str(kb_claims[key].id) for key in ordered_fields},
        artifact_keys_by_url=dict(artifact_keys),
        source_urls=REQUIRED_URLS,
    )


async def load_insight_health_discovery_fixture(
    conn: AsyncConnection,
) -> InsightHealthDiscoveryFixtureResult:
    """Reconstruct the frozen Stage-0 handoff from an already-seeded development database.

    Unlike :func:`seed_insight_health_discovery_fixture`, this path performs no artifact capture,
    resolver binding, or writes.  It exists for later-slice acceptance databases whose original
    harvested page bodies are intentionally outside the checkout but whose durable Stage-0 lineage
    remains complete.
    """

    project_run = await get_project_run(conn, PROJECT_RUN_ID)
    if project_run is None or (
        project_run.workspace_id,
        project_run.project_id,
        project_run.product_id,
        project_run.icp_key,
        project_run.icp_version,
    ) != (WORKSPACE_ID, PROJECT_ID, PRODUCT_ID, ICP_KEY, 1):
        raise FixtureStateConflict("persisted Stage-0 project-run lineage differs")
    if project_run.client_entity_id is None or project_run.client_kb_version is None:
        raise FixtureStateConflict("persisted Stage-0 project run lacks Client-KB lineage")
    if project_run.product_context_version_id is None:
        raise FixtureStateConflict("persisted Stage-0 project run lacks product context")

    onboarding = await get_onboarding_input(
        conn,
        ONBOARDING_INPUT_ID,
        workspace_id=WORKSPACE_ID,
    )
    if onboarding is None or onboarding.source_ref != HOME_URL:
        raise FixtureStateConflict("persisted Stage-0 onboarding input is absent or different")
    readiness = await get_readiness_decision(
        conn,
        READINESS_DECISION_ID,
        workspace_id=WORKSPACE_ID,
    )
    if readiness is None or readiness.verdict is not ReadinessVerdict.READY:
        raise FixtureStateConflict("persisted Stage-0 readiness decision is absent or not ready")
    spec = await get_active_icp(conn, WORKSPACE_ID, ICP_KEY)
    if spec is None or spec.version != project_run.icp_version:
        raise FixtureStateConflict("persisted Stage-0 ICP is absent or no longer active")

    kb_claims = await read_client_kb_claims(
        conn,
        project_run.client_entity_id,
        workspace_id=WORKSPACE_ID,
        version=project_run.client_kb_version,
        product_id=None,
    )
    if not kb_claims:
        raise FixtureStateConflict("persisted Stage-0 Client KB is empty")
    ordered_fields = tuple(sorted(kb_claims))
    artifact_keys_by_url: dict[str, str] = {}
    for claim in kb_claims.values():
        if claim.source_url in REQUIRED_URLS and claim.artifact_key is not None:
            artifact_keys_by_url[claim.source_url] = claim.artifact_key
    if set(artifact_keys_by_url) != set(REQUIRED_URLS):
        raise FixtureStateConflict("persisted Stage-0 official-page artifacts are incomplete")

    return InsightHealthDiscoveryFixtureResult(
        fixture_version=FIXTURE_COMPILER_VERSION,
        workspace_id=WORKSPACE_ID,
        brand_id=BRAND_ID,
        product_id=PRODUCT_ID,
        project_id=PROJECT_ID,
        client_entity_id=str(project_run.client_entity_id),
        client_kb_version=project_run.client_kb_version,
        stage0_run_id=str(STAGE0_RUN_ID),
        onboarding_input_id=str(ONBOARDING_INPUT_ID),
        icp_key=spec.icp_key,
        icp_version=spec.version,
        product_context_version_id=str(project_run.product_context_version_id),
        readiness_decision_id=str(readiness.id),
        readiness_verdict=readiness.verdict.value,
        project_run_id=str(PROJECT_RUN_ID),
        project_phase=project_run.phase.value,
        client_kb_fields=ordered_fields,
        client_claim_ids={key: str(kb_claims[key].id) for key in ordered_fields},
        artifact_keys_by_url=artifact_keys_by_url,
        source_urls=REQUIRED_URLS,
    )


__all__ = [
    "AMBIENT_URL",
    "AURA_ANYWHERE_URL",
    "BRAND_ID",
    "FIXTURE_COMPILER_VERSION",
    "FixtureInputError",
    "FixtureStateConflict",
    "HOME_URL",
    "ICP_KEY",
    "InsightHealthDiscoveryFixtureResult",
    "NEUROSURGERY_URL",
    "OfficialSiteFixtureResolver",
    "OfficialSitePage",
    "PRODUCT_ID",
    "PROJECT_ID",
    "PROJECT_RUN_ID",
    "REQUIRED_URLS",
    "WORKSPACE_ID",
    "capture_insight_health_pages",
    "claim_sources_for_pages",
    "load_firecrawl_search_pages",
    "load_insight_health_discovery_fixture",
    "recorded_insight_health_pages",
    "seed_insight_health_discovery_fixture",
]
