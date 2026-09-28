"""The deterministic claim mappers: provider records and model output → typed claim drafts.

Every function under test is **pure** (Global Constraint 3 is satisfied trivially: no provider is
reachable from here). What is asserted is the part a model or a provider must never be trusted to
decide for itself — which key a record lands on, which raw path it came from, what a negative is
born as, and that a `fail` verdict with nothing behind it is downgraded rather than believed.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest

from clue_api.arv2.account_research_claims import (
    ClaimInput,
    JobScope,
    _hq_location,
    agent_claims,
    ai_ark_company_claims,
    ai_ark_person_claims,
    ats_posting_claims,
    coerce_scalar,
    committee_candidate_claims,
    committee_member_claims,
    email_export_claim,
    fit_verdict_claims,
    media_index_claim,
    negative_claims,
    normalise_proposed_key,
    revenue_band_bucket,
    structured_claims,
    unconfirmed_candidates,
)
from clue_api.arv2.ai_ark_client import (
    AiArkCompany,
    AiArkPerson,
    email_export_from_record,
    person_from_record,
)
from clue_api.arv2.ats_client import AtsBoard, BoardPostings, JobPosting
from clue_api.arv2.calls import CallCost
from clue_api.arv2.structuring_client import (
    FieldCatalog,
    FieldSpec,
    NegativeOrRisk,
    ProposedField,
    StructuredClaim,
    StructuredOutput,
    check_value_schema,
)
from clue_core import (
    EntityId,
    EntityType,
    ExtractionMethod,
    IdentityBinding,
    ResearchMode,
    UseClass,
    is_valid_field_key,
)
from clue_research.claimstore.packs import CORE_PACK
from clue_research.profiling.fields import DEEP_PROFILING_PACK, FACET_CAREER_HISTORY

SCOPE = JobScope(
    workspace_id="ws-1",
    project_id="prj-1",
    project_run_id=uuid4(),
    run_id=uuid4(),
    job_id=uuid4(),
    account_id=EntityId(uuid4()),
    account_name="Zafran Security",
    account_domain="zafran.io",
    icp_markdown="# icp",
    persona_markdown="# personas",
    already_established="nothing yet",
    effort="high",
    committee_cap=4,
    today=date(2026, 9, 8),
)


_STR = {"type": "string"}
_INT = {"type": "integer"}
_STR_LIST = {"type": "array", "items": _STR}

#: The registry rows the mappers are checked against, copied from ``packs.py`` / ``catalog_seed``
#: exactly as ``read_account_catalog`` serves them: a widened provider value is claimed only when
#: the field is registered here *and* the value fits the registered schema.
CATALOG = FieldCatalog(
    account=(
        FieldSpec("core.account_name", "Canonical account name.", _STR),
        FieldSpec("core.primary_domain", "Primary web domain.", _STR),
        FieldSpec("core.legal_name", "Registered legal entity name.", _STR),
        FieldSpec("core.company_about", "Public company description.", _STR),
        FieldSpec("core.company_linkedin_url", "LinkedIn company page.", _STR),
        FieldSpec("core.company_crunchbase_url", "Crunchbase profile.", _STR),
        FieldSpec("core.company_twitter_url", "X/Twitter profile.", _STR),
        FieldSpec("core.company_email", "Public company contact email.", _STR),
        FieldSpec("core.company_type", "Provider company type label.", _STR),
        FieldSpec("core.industry", "Primary industry.", _STR),
        FieldSpec("core.industries_all", "Every industry label.", _STR_LIST),
        FieldSpec("core.company_languages", "Languages the company publishes in.", _STR_LIST),
        FieldSpec("core.founded_year", "Year founded.", _INT),
        FieldSpec("core.employee_count", "Total headcount.", _INT),
        FieldSpec(
            "core.employee_range",
            "Employee range.",
            {
                "type": "object",
                "required": ["label"],
                "properties": {"label": _STR, "min": _INT, "max": _INT},
            },
        ),
        FieldSpec(
            "core.hq_location",
            "Headquarters.",
            {
                "type": "object",
                "required": ["raw"],
                "properties": {
                    "raw": _STR,
                    "city": _STR,
                    "region": _STR,
                    "country": _STR,
                    "country_code": _STR,
                },
            },
        ),
        FieldSpec(
            "account.recent_funding",
            "Most recent funding round.",
            {
                "type": "object",
                "required": ["amount_usd"],
                "properties": {"amount_usd": {"type": "number"}, "round": _STR},
            },
        ),
        FieldSpec(
            "account.total_funding",
            "Total funding in USD with explicit estimate semantics.",
            {
                "type": "object",
                "required": ["amount_usd", "estimate_kind"],
                "properties": {
                    "amount_usd": {"type": "number"},
                    "estimate_kind": {
                        "type": "string",
                        "enum": ["reported", "provider_estimate", "third_party_estimate"],
                    },
                },
            },
        ),
        FieldSpec(
            "core.annual_revenue",
            "Annual revenue with currency and semantics.",
            {
                "type": "object",
                "required": ["amount", "currency", "as_of", "estimate_kind"],
                "properties": {"amount": {"type": "number"}, "currency": _STR},
            },
        ),
        FieldSpec(
            "core.revenue_band",
            "Bounded revenue band.",
            {"type": "string", "enum": ["under_1m", "1m_10m", "10m_50m", "50m_100m"]},
        ),
        FieldSpec("core.primary_tech_stack", "Detected primary technologies.", _STR_LIST),
        FieldSpec(
            "core.tech_stack_categorised",
            "Technology stack grouped by category.",
            {"type": "array", "items": {"type": "object"}},
        ),
        FieldSpec("account.named_customers", "Customers the company names.", _STR_LIST),
        FieldSpec("account.gtm_tooling_stack", "GTM tools present and absent.", {"type": "object"}),
    )
)


def _cost() -> CallCost:
    return CallCost(
        cost_usd=Decimal("0"),
        credits=None,
        media_seconds=None,
        cost_source="free",
        ledger_row_id="r",
        raw_ref="raw:x",
        provider="ashby",
        operation="board",
    )


def test_ats_postings_become_one_tier1_claim_each_with_the_json_path() -> None:
    postings = BoardPostings(
        board=AtsBoard(
            kind="ashby", slug="zafran-security", source_url="https://www.zafran.io/careers"
        ),
        url="https://api.ashbyhq.com/posting-api/job-board/zafran-security",
        postings=(
            JobPosting(
                title="Senior Manager, ABM",
                department="Marketing",
                team=None,
                location="USA",
                published_at=date(2026, 6, 17),
                days_open=83,
                is_listed=True,
                compensation=None,
                description_plain="Own ABM…",
                url="https://jobs.ashbyhq.com/zafran-security/abc",
                apply_url=None,
            ),
        ),
        raw_ref="raw:x",
        ledger_row_id="r",
        cost=_cost(),
    )

    [draft] = ats_posting_claims(postings, SCOPE)

    assert draft.field_key == "account.open_requisitions"
    assert draft.value_json == [
        {
            "title": "Senior Manager, ABM",
            "dept": "Marketing",
            "published": "2026-06-17",
            "days_open": 83,
            "still_listed": True,
            "url": "https://jobs.ashbyhq.com/zafran-security/abc",
        }
    ]
    assert draft.extraction_method is ExtractionMethod.API and draft.signal_priority == 1
    assert draft.source_url == "https://jobs.ashbyhq.com/zafran-security/abc"
    assert draft.evidence_span == "Senior Manager, ABM — Marketing — published 2026-06-17"
    assert draft.markers["json_path"] == "jobs[0]" and draft.source_key == "ats:ashby"
    assert draft.entity_id == SCOPE.account_id and draft.entity_type is EntityType.ACCOUNT
    assert draft.research_mode is ResearchMode.ACCOUNT_PROFILING


def test_ai_ark_company_maps_only_registered_keys_at_their_real_raw_paths() -> None:
    company = AiArkCompany(
        name="Zafran Security",
        domain="zafran.io",
        linkedin="https://www.linkedin.com/company/zafran",
        industry="Computer & Network Security",
        employee_count=180,
        revenue="10000000-25000000",
        technologies=("HubSpot",),
        location={
            "continent": "North America",
            "country": "US",
            "city": "New York",
            "state": "New York",
            "raw_address": "New York, New York, United States",
        },
        raw={
            "financial": {
                "revenue": {
                    "annual": {
                        "start": 10_000_000,
                        "end": 25_000_000,
                        "amount": "10000000-25000000",
                    }
                }
            }
        },
        cost=None,
    )

    drafts = {d.field_key: d for d in ai_ark_company_claims(company, SCOPE, catalog=CATALOG)}

    assert set(drafts) == {
        "core.company_linkedin_url",
        "core.industry",
        "core.employee_count",
        "core.revenue_band",
        "core.hq_location",
        "core.primary_tech_stack",
    }
    assert drafts["core.employee_count"].value_json == 180
    # The path is read off ``company_from_record``, not invented: the record nests the count
    # under ``summary.staff.total``, which is what a replay has to look at.
    assert drafts["core.employee_count"].markers["json_path"] == "summary.staff.total"
    # ``core.revenue_band`` is an enum field, so the provider's numeric range is translated into
    # a registered bucket in code; the string it came from stays on the claim as a marker.
    assert drafts["core.revenue_band"].value_json == "10m_50m"
    assert drafts["core.revenue_band"].markers["json_path"] == "financial.revenue.annual"
    assert drafts["core.revenue_band"].markers["provider_value"] == "10000000-25000000"
    # The provider's own object is translated into the shape the registry declares: ``raw`` is its
    # ``raw_address``, and its ``continent``/``position`` have no registered home.
    assert drafts["core.hq_location"].value_json == {
        "raw": "New York, New York, United States",
        "city": "New York",
        "region": "New York",
        "country": "US",
    }
    assert drafts["core.hq_location"].markers["json_path"] == "location.headquarter"
    assert all(
        d.extraction_method is ExtractionMethod.API
        and d.source_key == "ai_ark:company"
        and d.source_url is None
        and d.markers["provider_record"] == "ai_ark"
        for d in drafts.values()
    )


def test_hq_location_emits_country_code_only_when_the_record_carries_one() -> None:
    """``region`` is the provider's ``state`` and ``country_code`` is only ever the provider's own
    ISO code: no name-to-code table lives here, because the mapper does not decide what a value
    means. ``raw`` stays required — half a location is not a location this field can hold."""
    assert _hq_location(
        {
            "raw_address": "Tel Aviv, Israel",
            "city": "Tel Aviv",
            "country": "Israel",
            "country_code": "IL",
        }
    ) == {"raw": "Tel Aviv, Israel", "city": "Tel Aviv", "country": "Israel", "country_code": "IL"}
    assert _hq_location({"raw_address": "Tel Aviv, Israel", "state": None}) == {
        "raw": "Tel Aviv, Israel"
    }
    assert _hq_location({"city": "Tel Aviv"}) is None


def test_ai_ark_company_omits_the_fields_the_record_did_not_carry() -> None:
    company = AiArkCompany(
        name="Probook",
        domain="probook.ai",
        linkedin=None,
        industry=None,
        employee_count=None,
        revenue=None,
        technologies=(),
        location=None,
        raw={},
    )
    assert ai_ark_company_claims(company, SCOPE, catalog=CATALOG) == []


def test_a_revenue_range_that_straddles_two_buckets_is_not_claimed_at_all() -> None:
    """The other fields still land: one untranslatable field is not a failed record."""
    company = AiArkCompany(
        name="Zafran Security",
        domain="zafran.io",
        linkedin="https://www.linkedin.com/company/zafran",
        industry="Computer & Network Security",
        employee_count=180,
        revenue="25000000-75000000",
        technologies=(),
        location={"country": "US"},
        raw={"financial": {"revenue": {"annual": {"start": 25_000_000, "end": 75_000_000}}}},
    )

    keys = {d.field_key for d in ai_ark_company_claims(company, SCOPE, catalog=CATALOG)}

    assert "core.revenue_band" not in keys, "10m_50m and 50m_100m: there is no honest single answer"
    # linkedin, industry and headcount; the HQ names no ``raw_address``, so it is not claimed.
    assert len(keys) == 3


def test_the_revenue_band_is_parsed_from_the_amount_string_when_the_record_omits_the_pair() -> None:
    company = AiArkCompany(
        name="Probook",
        domain="probook.ai",
        linkedin=None,
        industry=None,
        employee_count=None,
        revenue="1000000-5000000",
        technologies=(),
        location=None,
        raw={"financial": {"revenue": {"annual": {"amount": "1000000-5000000"}}}},
    )

    drafts = {d.field_key: d for d in ai_ark_company_claims(company, SCOPE, catalog=CATALOG)}

    assert drafts["core.revenue_band"].value_json == "1m_10m"


def test_revenue_band_buckets_are_half_open_and_refuse_to_guess() -> None:
    assert revenue_band_bucket(10_000_000, 25_000_000) == "10m_50m"
    assert revenue_band_bucket(9_999_999, 9_999_999) == "1m_10m"
    assert revenue_band_bucket(10_000_000, 10_000_000) == "10m_50m"
    assert revenue_band_bucket(0, 999_999) == "under_1m"
    assert revenue_band_bucket(2_000_000_000, 5_000_000_000) == "1b_plus"
    assert revenue_band_bucket(999_999_999, 1_000_000_000) is None  # straddles 500m_1b / 1b_plus
    assert revenue_band_bucket(25_000_000, 75_000_000) is None  # straddles two buckets
    assert revenue_band_bucket(None, 25_000_000) is None
    assert revenue_band_bucket(10_000_000, None) is None
    assert revenue_band_bucket(None, None) is None
    assert revenue_band_bucket(25_000_000, 10_000_000) is None  # inverted: a malformed range


def test_negatives_are_reputation_risk_claims_born_unsafe_priority_two() -> None:
    [draft] = negative_claims(
        [
            NegativeOrRisk(
                what="Calcalist reported acquisition talks with Cisco",
                status="REFUTED",
                evidence_span="Zafran denied…",
                source_url="https://example.com/calcalist",
                outreach_safe=True,
            )
        ],
        SCOPE,
    )

    assert draft.field_key == "account.reputation_risk"
    assert draft.outreach_safe is False and draft.signal_priority == 2
    # No ``"source_note": None``: an explicit null in a string-typed property would make this
    # correctly-mapped claim land ``schema_valid=False``.
    assert draft.value_json == {
        "what": "Calcalist reported acquisition talks with Cisco",
        "status": "refuted",
    }
    assert draft.evidence_span == "Zafran denied…"
    assert draft.extraction_method is ExtractionMethod.LLM_SYNTHESIS


def test_structured_claims_carry_the_annotations_and_the_mode_and_propose_unregistered_keys() -> (
    None
):
    output = StructuredOutput(
        claims=(
            StructuredClaim(
                field_key="account.gtm_tooling_stack",
                value={"present": ["HubSpot"]},
                evidence_span="we run everything on HubSpot",
                source_url=None,
                source_kind="company_primary",
                confidence="high",
                use_class="business_public",
                outreach_safe=True,
                priority=1,
                media_timestamp=None,
                evidence_verbatim="EXACT",
                schema_valid=True,
            ),
        ),
        proposed=(
            ProposedField(
                suggested_key="account.pricing_page_shape",
                why="the pricing page names three tiers",
                value={"tiers": 3},
                evidence_span="Starter, Growth, Scale",
                source_url="https://probook.ai/pricing",
            ),
        ),
        negatives=(),
        model="m",
        mode="intent_sweep",
    )

    drafts = {
        d.field_key: d
        for d in structured_claims(
            output, scope=SCOPE, subject_url_hint="https://probook.ai", catalog=CATALOG
        )
    }

    kept = drafts["account.gtm_tooling_stack"]
    assert (
        kept.extraction_method is ExtractionMethod.LLM_SYNTHESIS
        and kept.source_key == "structuring"
    )
    assert kept.confidence == 0.8 and kept.signal_priority == 1
    assert kept.source_url == "https://probook.ai"  # the hint fills a claim with no url of its own
    assert kept.markers == {
        "evidence_verbatim": "EXACT",
        "schema_valid": True,
        "source_kind": "company_primary",
        "media_timestamp": None,
        "structuring_mode": "intent_sweep",
    }
    proposed = drafts["account.pricing_page_shape"]
    assert proposed.field_description == "the pricing page names three tiers"
    assert proposed.source_url == "https://probook.ai/pricing"


def test_fit_verdicts_are_claims_born_unsafe_and_never_fail_without_contrary_evidence() -> None:
    drafts = fit_verdict_claims(
        [{"gate": "stage", "verdict": "fail", "rationale": "not found", "claim_ids": []}], SCOPE
    )

    assert drafts[0].field_key == "account.icp_fit_verdict"
    assert drafts[0].value_json["verdict"] == "unclear"
    assert drafts[0].value_json["rationale"].endswith(" (downgraded: no contrary evidence cited)")
    assert drafts[0].outreach_safe is False and drafts[0].signal_priority == 2


def test_a_fail_verdict_with_cited_evidence_stands() -> None:
    [draft] = fit_verdict_claims(
        [
            {
                "gate": "hq",
                "verdict": "fail",
                "rationale": "HQ evidenced in Tel Aviv",
                "claim_ids": [str(uuid4())],
            }
        ],
        SCOPE,
    )
    assert draft.value_json["verdict"] == "fail"
    assert draft.value_json["rationale"] == "HQ evidenced in Tel Aviv"


def test_a_named_committee_candidate_without_a_confirming_url_is_never_written() -> None:
    candidates = [
        {
            "name": "Nick Fisher",
            "title": "VP Marketing",
            "persona": "champion",
            "confirmed_by": "https://probook.ai/about",
        },
        {"name": "Someone Unconfirmed", "title": "CFO", "persona": "economic_buyer"},
    ]

    drafts = committee_candidate_claims(candidates, SCOPE)

    assert [d.value_json["name"] for d in drafts] == ["Nick Fisher"]
    assert drafts[0].source_url == "https://probook.ai/about"
    assert drafts[0].field_key == "account.committee_candidate"
    assert [c["name"] for c in unconfirmed_candidates(candidates)] == ["Someone Unconfirmed"]


def test_a_committee_candidate_carries_the_rationale_and_influence_when_the_agent_gave_them() -> (
    None
):
    """The why behind the seat rides the account claim as well as the member's role claim, so the
    two surfaces read the same reasoning. Both keys are optional and neither is ever invented."""
    [draft] = committee_candidate_claims(
        [
            {
                "name": "Nick Fisher",
                "title": "VP Marketing",
                "persona": "champion",
                "confirmed_by": "https://probook.ai/about",
                "rationale": "owns the ABM programme and the agency budget",
                "influence": "High",
            }
        ],
        SCOPE,
    )

    assert draft.value_json["rationale"] == "owns the ABM programme and the agency budget"
    assert draft.value_json["influence"] == "High"


def test_agent_claims_force_the_two_never_outreach_safe_fields() -> None:
    drafts = agent_claims(
        [
            ClaimInput(
                field_key="account.reputation_risk",
                value={"what": "a layoff round"},
                evidence_span="laid off 20%",
                source_url="https://example.com/news",
                priority=2,
                outreach_safe=True,
            ),
            ClaimInput(
                field_key="account.named_customers",
                value=["Acme"],
                evidence_span="Acme trusts us",
                source_url="https://example.com/customers",
                priority=2,
                outreach_safe=True,
                corrects_claim_id="c-1",
            ),
        ],
        SCOPE,
        catalog=CATALOG,
    )

    assert drafts[0].outreach_safe is False
    assert drafts[1].outreach_safe is True
    assert drafts[1].markers == {"corrects_claim_id": "c-1"}
    assert all(d.source_key == "agent" for d in drafts)


def test_media_index_claim_records_the_item_and_whether_the_speaker_was_verified() -> None:
    draft = media_index_claim(
        person="Nick Fisher",
        item_url="https://example.com/ep/42.mp3",
        kind="podcast",
        duration_s=1800,
        transcript_model="gemini-3.5-transcribe",
        speaker_verified=False,
        scope=SCOPE,
    )

    assert draft.field_key == "account.media_layer_index"
    assert draft.value_json == [
        {
            "person": "Nick Fisher",
            "url": "https://example.com/ep/42.mp3",
            "kind": "podcast",
            "duration_s": 1800,
            "transcript_model": "gemini-3.5-transcribe",
            "speaker_verified": False,
        }
    ]
    assert draft.source_url == "https://example.com/ep/42.mp3"
    assert draft.extraction_method is ExtractionMethod.API
    assert draft.observed_at is None


# -- no explicit nulls in a mapped value (the ``schema_valid`` truthfulness rule) -----------------
#
# A registered optional property is typed (``{"type": "string"}``) and the writer's schema gate is
# an ``isinstance`` check, so an explicit ``null`` for something the record simply did not carry
# lands a correct, deterministically-mapped claim with ``schema_valid=False`` — the one marker the
# audit skill reads as "the extraction did not fit the field". Absent, not null.


def _nulls(value: Any) -> list[str]:
    """Every key path under ``value`` whose value is ``None``."""
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            found.extend([key] if item is None else [f"{key}.{p}" for p in _nulls(item)])
    elif isinstance(value, list):
        for item in value:
            found.extend(_nulls(item))
    return found


def test_an_ats_posting_that_carries_nothing_optional_writes_no_null_properties() -> None:
    postings = BoardPostings(
        board=AtsBoard(kind="greenhouse", slug="probook", source_url="https://probook.ai/careers"),
        url="https://boards-api.greenhouse.io/v1/boards/probook/jobs",
        postings=(
            JobPosting(
                title="Head of Growth",
                department=None,
                team=None,
                location=None,
                published_at=None,
                days_open=None,
                is_listed=True,
                compensation=None,
                description_plain=None,
                url=None,
                apply_url=None,
            ),
        ),
        raw_ref="raw:x",
        ledger_row_id="r",
        cost=_cost(),
    )

    [draft] = ats_posting_claims(postings, SCOPE)

    assert draft.value_json == [{"title": "Head of Growth", "still_listed": True}]
    assert _nulls(draft.value_json) == []


def test_a_negative_with_no_status_writes_no_null_properties() -> None:
    [draft] = negative_claims(
        [
            NegativeOrRisk(
                what="Two Glassdoor reviews describe a layoff round",
                status=None,
                evidence_span="laid off 20%",
                source_url=None,
                outreach_safe=True,
            )
        ],
        SCOPE,
    )

    assert draft.value_json == {"what": "Two Glassdoor reviews describe a layoff round"}
    assert _nulls(draft.value_json) == []


def test_a_committee_candidate_writes_no_null_properties_at_all() -> None:
    thin, vacant = committee_candidate_claims(
        [
            {
                "name": "Nick Fisher",
                "persona": "champion",
                "confirmed_by": "https://probook.ai/about",
            },
            {"persona": "economic_buyer", "vacant_seat": True},
        ],
        SCOPE,
    )

    assert thin.value_json == {
        "name": "Nick Fisher",
        "persona": "champion",
        "confirmed_by": "https://probook.ai/about",
        "vacant_seat": False,
    }
    assert _nulls(thin.value_json) == []
    # Only ``persona`` is required (``catalog_seed``), so a vacant seat carries no ``name`` key at
    # all: "nobody holds this role" is a finding about the account, not a null person.
    assert vacant.value_json == {"persona": "economic_buyer", "vacant_seat": True}
    assert _nulls(vacant.value_json) == []


def test_a_media_item_with_no_duration_or_transcript_writes_no_null_properties() -> None:
    draft = media_index_claim(
        person="Nick Fisher",
        item_url="https://example.com/ep/43",
        kind="video",
        duration_s=None,
        transcript_model=None,
        speaker_verified=False,
        scope=SCOPE,
    )

    assert draft.value_json == [
        {
            "person": "Nick Fisher",
            "url": "https://example.com/ep/43",
            "kind": "video",
            "speaker_verified": False,
        }
    ]
    assert _nulls(draft.value_json) == []


def test_a_fit_verdict_value_carries_no_null_properties() -> None:
    [draft] = fit_verdict_claims([{"gate": "hq", "verdict": "pass"}], SCOPE)

    assert _nulls(draft.value_json) == []


def test_an_ai_ark_object_value_drops_the_keys_the_provider_answered_null() -> None:
    company = AiArkCompany(
        name="Probook",
        domain="probook.ai",
        linkedin=None,
        industry=None,
        employee_count=None,
        revenue=None,
        technologies=(),
        location={"country": "US", "city": None, "raw_address": "US"},
        raw={},
    )

    drafts = {d.field_key: d for d in ai_ark_company_claims(company, SCOPE, catalog=CATALOG)}
    draft = drafts["core.hq_location"]

    assert draft.field_key == "core.hq_location"
    assert draft.value_json == {"raw": "US", "country": "US"}
    assert _nulls(draft.value_json) == []


# -- the widened AI Ark mapper -------------------------------------------------------------------


def _zafran_record() -> AiArkCompany:
    """A company record shaped like the proof-of-concept's field inventory (§1 A).

    The paths are the inventory's own — ``summary.legal_name``, ``summary.staff.range``,
    ``industries``, ``languages``, ``link.crunchbase``, ``contact.email``, ``technologies`` — so a
    mapping that drifts off a real record path fails here rather than in a live run.
    """
    raw: dict[str, Any] = {
        "summary": {
            "name": "Zafran Security",
            "legal_name": "Zafran Security Ltd.",
            "description": "Zafran is an AI-native exposure management platform.",
            "founded_year": 2022,
            "type": "PRIVATELY_HELD",
            "industry": "computer and network security",
            "staff": {"total": 167, "range": {"start": 51, "end": 200}},
        },
        "link": {
            "website": "https://www.zafran.io",
            "domain": "zafran.io",
            "linkedin": "https://www.linkedin.com/company/zafran-security",
            "twitter": "https://x.com/Zafran_io",
            "crunchbase": "https://www.crunchbase.com/organization/zafran",
        },
        "contact": {"email": "info@zafran.io"},
        "financial": {
            "revenue": {
                "annual": {"start": 10_000_000, "end": 25_000_000, "amount": "10000000-25000000"}
            },
            "funding": {
                "type": "SERIES_C",
                "total_amount": 130_500_000,
                "last_amount": 60_000_000,
                "num_investor": 9,
                "num_funding_rounds": 4,
                "date": "2025-12-02",
                "rounds": [
                    {
                        "announced_at": "2025-12-02",
                        "raised_amount": 60_000_000,
                        "type": "SERIES_C",
                        "investors": ["Menlo Ventures", "Sequoia Capital"],
                    },
                    {
                        "announced_at": "2024-05-14",
                        "raised_amount": 30_000_000,
                        "type": "SERIES_B",
                        "investors": ["Cyberstarts"],
                    },
                ],
            },
        },
        "location": {
            "headquarter": {
                "country": "United States",
                "city": "New York, New York",
                "raw_address": "New York, New York, United States, North America",
            }
        },
        "technologies": [
            {"name": "dnssec", "category": "ns"},
            {"name": "google cloud", "category": "hosting"},
        ],
        "industries": ["risk management", "cyber security"],
        "languages": ["english"],
        "last_updated": "2026-08-22",
    }
    return AiArkCompany(
        name="Zafran Security",
        domain="zafran.io",
        linkedin="https://www.linkedin.com/company/zafran-security",
        industry="computer and network security",
        employee_count=167,
        revenue="10000000-25000000",
        technologies=("dnssec", "google cloud"),
        location=raw["location"]["headquarter"],
        raw=raw,
        cost=None,
    )


def test_company_maps_typed_facts_without_promoting_provider_description() -> None:
    company = _zafran_record()
    drafts = {d.field_key: d for d in ai_ark_company_claims(company, SCOPE, catalog=CATALOG)}

    assert drafts["core.legal_name"].value_json == "Zafran Security Ltd."
    assert drafts["core.legal_name"].markers["json_path"] == "summary.legal_name"
    assert "core.company_about" not in drafts
    assert company.raw["summary"]["description"] == (
        "Zafran is an AI-native exposure management platform."
    )
    assert drafts["core.founded_year"].value_json == 2022
    assert drafts["core.company_type"].value_json == "PRIVATELY_HELD"
    assert drafts["core.employee_range"].value_json == {"label": "51-200", "min": 51, "max": 200}
    assert drafts["core.employee_range"].markers["json_path"] == "summary.staff.range"
    assert drafts["core.industries_all"].value_json == ["risk management", "cyber security"]
    assert drafts["core.company_languages"].value_json == ["english"]
    assert drafts["core.company_crunchbase_url"].value_json == (
        "https://www.crunchbase.com/organization/zafran"
    )
    assert drafts["core.company_twitter_url"].value_json == "https://x.com/Zafran_io"
    assert drafts["core.company_email"].value_json == "info@zafran.io"
    assert drafts["core.account_name"].value_json == "Zafran Security"
    assert drafts["core.primary_domain"].value_json == "zafran.io"
    assert all(
        d.extraction_method is ExtractionMethod.API
        and d.source_key == "ai_ark:company"
        and d.source_url is None
        and d.markers["provider_record"] == "ai_ark"
        for d in drafts.values()
    )


def test_researched_company_description_keeps_its_evidence_and_source_url() -> None:
    # Descriptions remain writable from research; excluding Ark's automatic prose mapping
    # must not remove the field or strip the original page reference carried by research.
    output = StructuredOutput(
        claims=(
            StructuredClaim(
                field_key="core.company_about",
                value="A fixture company that builds scheduling software.",
                evidence_span="We build scheduling software.",
                source_url="https://example.test/company",
                source_kind="company_primary",
                confidence="high",
                use_class="business_public",
                outreach_safe=True,
                priority=1,
                media_timestamp=None,
                evidence_verbatim="EXACT",
                schema_valid=True,
            ),
        ),
        proposed=(),
        negatives=(),
        model="fixture",
    )
    [draft] = structured_claims(output, scope=SCOPE, subject_url_hint=None, catalog=CATALOG)
    assert draft.field_key == "core.company_about"
    assert draft.source_url == "https://example.test/company"
    assert draft.evidence_span == "We build scheduling software."
    assert draft.extraction_method is ExtractionMethod.LLM_SYNTHESIS


def test_the_technologies_the_record_returned_become_claims_rather_than_context() -> None:
    """The R2 run returned technologies to the model and claimed none: both keys read ``missing``
    against the answer keys. They are deterministic provider values, so they are mapped in code."""
    drafts = {
        d.field_key: d for d in ai_ark_company_claims(_zafran_record(), SCOPE, catalog=CATALOG)
    }

    assert drafts["core.primary_tech_stack"].value_json == ["dnssec", "google cloud"]
    assert drafts["core.primary_tech_stack"].markers["json_path"] == "technologies[].name"
    assert drafts["core.tech_stack_categorised"].value_json == [
        {"name": "dnssec", "category": "ns"},
        {"name": "google cloud", "category": "hosting"},
    ]
    assert drafts["core.tech_stack_categorised"].markers["json_path"] == "technologies"


def test_the_provider_revenue_range_is_never_forced_into_the_registered_revenue_shape() -> None:
    """``core.annual_revenue`` requires one amount, a currency, an as-of date and an estimate kind;
    the record answers a range and names no currency. The band claim is the honest translation."""
    keys = {d.field_key for d in ai_ark_company_claims(_zafran_record(), SCOPE, catalog=CATALOG)}

    assert "core.annual_revenue" not in keys
    assert "core.revenue_band" in keys


def test_the_hq_is_translated_into_the_registered_shape_rather_than_written_through() -> None:
    """The old mapping wrote the provider's own ``continent/city/raw_address/position`` object into
    a field whose schema requires ``raw``: right value, foreign shape, ``schema_valid=false`` on
    both live accounts."""
    drafts = {
        d.field_key: d for d in ai_ark_company_claims(_zafran_record(), SCOPE, catalog=CATALOG)
    }

    assert drafts["core.hq_location"].value_json == {
        "raw": "New York, New York, United States, North America",
        "city": "New York, New York",
        "country": "United States",
    }
    assert drafts["core.hq_location"].markers["json_path"] == "location.headquarter"


def test_a_headquarter_with_no_raw_address_is_not_claimed_at_all() -> None:
    """``raw`` is the required key: a location the provider never spelled out is not a location
    this field can hold, and half a location is not better than none."""
    company = _zafran_record()
    without_raw = {key: value for key, value in company.location.items() if key != "raw_address"}

    keys = {
        d.field_key
        for d in ai_ark_company_claims(
            AiArkCompany(**{**company.__dict__, "location": without_raw}), SCOPE, catalog=CATALOG
        )
    }

    assert "core.hq_location" not in keys
    assert "core.legal_name" in keys, "one unmappable value is not a failed record"


def test_the_funding_amounts_are_claimed_in_usd_with_the_assumption_recorded() -> None:
    """Founder ruling 2026-09-08: the provider's funding integers are USD. The assumption is on
    every claim as a marker, so a record that ever contradicts it is a query, not an archaeology."""
    drafts = {
        d.field_key: d for d in ai_ark_company_claims(_zafran_record(), SCOPE, catalog=CATALOG)
    }

    total = drafts["account.total_funding"]
    assert total.value_json == {"amount_usd": 130_500_000, "estimate_kind": "reported"}
    assert total.markers["json_path"] == "financial.funding.total_amount"
    assert total.markers["currency_assumed"] == "USD"

    recent = drafts["account.recent_funding"]
    assert recent.value_json == {"amount_usd": 60_000_000, "round": "SERIES_C"}
    assert recent.markers["json_path"] == "financial.funding.rounds[0]"
    assert recent.markers["currency_assumed"] == "USD"
    assert recent.markers["provider_record"] == "ai_ark"
    assert recent.extraction_method is ExtractionMethod.API and recent.source_url is None


def test_the_recent_round_is_the_newest_by_date_not_the_first_in_the_record() -> None:
    company = _zafran_record()
    reordered = dict(company.raw)
    funding = dict(reordered["financial"]["funding"])
    funding["rounds"] = list(reversed(funding["rounds"]))  # oldest first, as some records arrive
    reordered["financial"] = {**reordered["financial"], "funding": funding}

    drafts = {
        d.field_key: d
        for d in ai_ark_company_claims(
            AiArkCompany(**{**company.__dict__, "raw": reordered}), SCOPE, catalog=CATALOG
        )
    }

    assert drafts["account.recent_funding"].value_json["amount_usd"] == 60_000_000
    assert drafts["account.recent_funding"].markers["json_path"] == "financial.funding.rounds[1]"


def test_a_record_with_no_funding_amounts_writes_no_funding_claim() -> None:
    """An undisclosed round is a real answer: the amount is absent, so the claim is absent —
    never an older round's figure wearing the newest round's date."""
    company = _zafran_record()
    undisclosed = dict(company.raw)
    undisclosed["financial"] = {
        "funding": {
            "num_funding_rounds": 1,
            "rounds": [{"announced_at": "2026-07-22", "type": "STRATEGIC"}],
        }
    }

    keys = {
        d.field_key
        for d in ai_ark_company_claims(
            AiArkCompany(**{**company.__dict__, "raw": undisclosed}), SCOPE, catalog=CATALOG
        )
    }

    assert not keys & {"account.total_funding", "account.recent_funding"}


def test_a_widened_value_that_does_not_fit_its_registered_schema_is_not_claimed() -> None:
    company = _zafran_record()
    broken = dict(company.raw)
    broken["summary"] = {**company.raw["summary"], "founded_year": "two thousand twenty two"}

    keys = {
        d.field_key
        for d in ai_ark_company_claims(
            AiArkCompany(**{**company.__dict__, "raw": broken}), SCOPE, catalog=CATALOG
        )
    }

    assert "core.founded_year" not in keys
    assert "core.legal_name" in keys, "one unusable value is not a failed record"


def test_a_widened_field_this_deployment_has_not_registered_is_not_claimed() -> None:
    """The registry is the menu: a widened value has a home only where the field exists. (The four
    mapped attributes and the revenue band are the shipped mapping and are not gated by it.)"""
    narrow = FieldCatalog(account=(FieldSpec("core.legal_name", "Legal name.", _STR),))

    keys = {d.field_key for d in ai_ark_company_claims(_zafran_record(), SCOPE, catalog=narrow)}

    assert "core.legal_name" in keys
    assert not keys & {"core.founded_year", "core.industries_all", "core.company_email"}


# -- proposed keys, normalised -------------------------------------------------------------------


def test_normalise_proposed_key_makes_a_writable_key_out_of_what_the_model_said() -> None:
    assert normalise_proposed_key("recent_funding", "account") == "account.recent_funding"
    assert normalise_proposed_key("Recent Funding", "account") == "account.recent_funding"
    assert normalise_proposed_key("recent-funding", "account") == "account.recent_funding"
    assert normalise_proposed_key("core_founded", "account") == "core.founded"
    assert normalise_proposed_key("account.named_customers", "account") == "account.named_customers"
    assert normalise_proposed_key("hobby", "contact") == "contact.hobby"
    assert normalise_proposed_key("!!!", "account").startswith("account.proposed_")


def test_a_normalised_key_is_always_a_valid_field_key() -> None:
    for key in ("!!!", "", "2024", "Some Model Idea??", "..", "ACCOUNT..X"):
        assert is_valid_field_key(normalise_proposed_key(key, "account")), key


def test_structured_claims_normalise_the_key_a_proposed_field_arrived_under() -> None:
    output = StructuredOutput(
        claims=(),
        proposed=(
            ProposedField(
                suggested_key="Recent Funding",
                why="a Series C",
                value={"round": "series_c"},
                evidence_span="raised $60M",
                source_url="https://zafran.io/news",
            ),
        ),
        negatives=(),
        model="m",
    )

    [draft] = structured_claims(output, scope=SCOPE, subject_url_hint=None, catalog=CATALOG)

    assert draft.field_key == "account.recent_funding"
    assert draft.markers["proposed_key_raw"] == "Recent Funding"


# -- scalar coercion ------------------------------------------------------------------------------


def test_coerce_scalar_unwraps_a_single_carrier_key_for_a_scalar_field() -> None:
    wrapped = {"count": 36, "semantics": "estimate"}
    assert coerce_scalar("core.employee_count", wrapped, CATALOG) == 36
    assert coerce_scalar("core.founded_year", {"year": 2022}, CATALOG) == 2022
    assert coerce_scalar("core.legal_name", {"name": "Zafran Security Ltd."}, CATALOG) == (
        "Zafran Security Ltd."
    )


def test_coerce_scalar_reads_a_digit_string_as_the_number_the_field_declares() -> None:
    assert coerce_scalar("core.founded_year", "2024", CATALOG) == 2024
    assert coerce_scalar("core.employee_count", "167", CATALOG) == 167


def test_coerce_scalar_leaves_everything_it_cannot_read_alone() -> None:
    # a year-like digit string on a string field stays a string
    assert coerce_scalar("core.company_type", "2024", CATALOG) == "2024"
    # a list on a list field is untouched
    assert coerce_scalar("core.industries_all", ["cyber security"], CATALOG) == ["cyber security"]
    # an object with no single obvious carrier is untouched
    two_carriers = {"count": 36, "total": 40}
    assert coerce_scalar("core.employee_count", two_carriers, CATALOG) == two_carriers
    # an unregistered key is untouched
    assert coerce_scalar("account.proposed_x", {"count": 36}, CATALOG) == {"count": 36}
    # an object field keeps its object
    assert coerce_scalar("account.gtm_tooling_stack", {"present": ["HubSpot"]}, CATALOG) == {
        "present": ["HubSpot"]
    }


def test_structured_claims_coerce_a_wrapped_scalar_and_record_what_it_was() -> None:
    output = StructuredOutput(
        claims=(
            StructuredClaim(
                field_key="core.employee_count",
                value={"count": 36, "semantics": "linkedin_estimate"},
                evidence_span="36 employees on LinkedIn",
                source_url="https://www.linkedin.com/company/probook",
                source_kind="third_party_press",
                confidence="medium",
                use_class="business_public",
                outreach_safe=True,
                priority=2,
                media_timestamp=None,
                evidence_verbatim="EXACT",
                schema_valid=False,
            ),
        ),
        proposed=(),
        negatives=(),
        model="m",
    )

    [draft] = structured_claims(output, scope=SCOPE, subject_url_hint=None, catalog=CATALOG)

    assert draft.value_json == 36
    assert draft.markers["coerced_from"] == {"count": 36, "semantics": "linkedin_estimate"}


def test_agent_claims_coerce_the_same_way() -> None:
    [draft] = agent_claims(
        [
            ClaimInput(
                field_key="core.founded_year",
                value="2022",
                evidence_span="founded in 2022",
                source_url="https://zafran.io/about",
                priority=2,
            )
        ],
        SCOPE,
        catalog=CATALOG,
    )

    assert draft.value_json == 2022
    assert draft.markers["coerced_from"] == "2022"


def test_agent_claims_drop_null_optional_keys_on_an_object_field_and_keep_required_ones() -> None:
    items = [
        ClaimInput(
            field_key="core.employee_range",
            value={"label": "51-200", "min": None, "max": 200},
            evidence_span="51-200 employees",
            source_url="https://example.test/about",
            priority=2,
        ),
        ClaimInput(
            field_key="core.employee_range",
            value={"label": None, "min": 51, "max": 200},
            evidence_span="51-200 employees",
            source_url="https://example.test/about",
            priority=2,
        ),
    ]

    first, second = agent_claims(items, SCOPE, catalog=CATALOG)

    assert first.value_json == {"label": "51-200", "max": 200}
    assert first.markers["dropped_null_keys"] == ["min"]
    # A required key nothing answered stays, so the schema marker can say the value does not fit.
    assert second.value_json == {"label": None, "min": 51, "max": 200}
    assert "dropped_null_keys" not in second.markers


def test_agent_claims_leave_non_object_values_and_unschemad_fields_alone() -> None:
    items = [
        ClaimInput(
            field_key="core.industries_all",
            value=["saas", None],
            evidence_span="saas",
            source_url="https://example.test/about",
            priority=3,
        ),
    ]

    (draft,) = agent_claims(items, SCOPE, catalog=CATALOG)

    assert draft.value_json == ["saas", None]
    assert "dropped_null_keys" not in draft.markers


# -- vacant seats ---------------------------------------------------------------------------------


def test_a_vacant_seat_carries_no_name_key_at_all() -> None:
    [draft] = committee_candidate_claims(
        [{"persona": "economic_buyer", "title": "CFO", "vacant_seat": True}], SCOPE
    )

    assert "name" not in draft.value_json
    assert draft.value_json["vacant_seat"] is True
    assert draft.value_json["persona"] == "economic_buyer"


# -- a person subject in the claim path -----------------------------------------------------------

CONTACT_ID = EntityId(uuid4())

PERSON_SCOPE = replace(
    SCOPE,
    subject_kind="person",
    contact_id=CONTACT_ID,
    person_name="Nick Fisher",
    person_title="VP of Marketing",
    person_linkedin_url="https://www.linkedin.com/in/nicholastfisher",
    employment_history=("VP of Marketing @ Zafran Security (2024-04-01–)",),
)

#: The person-side menu as ``read_person_catalog`` serves it: the contact fields carry the
#: ``use_class_hint`` the registry declares, and a facet's hint is what the claim is born with.
PERSON_CATALOG = FieldCatalog(
    contact=(
        FieldSpec("contact.current_title", "Current professional title.", _STR),
        FieldSpec("contact.headline", "LinkedIn headline.", _STR),
    ),
    facet=(
        FieldSpec(
            "contact.facet.hobby",
            "Hobbies the person states publicly.",
            _STR_LIST,
            use_class_hint="personal-public-non-sensitive",
        ),
        FieldSpec(
            "contact.facet.certifications",
            "Certifications the person lists.",
            _STR_LIST,
            use_class_hint="professional-public",
        ),
    ),
)

#: One ``/v1/people`` record, at the paths the provider actually uses (recorded walk, Nick Fisher).
PERSON_RECORD: Mapping[str, Any] = {
    "id": "5669ed27-2388-effa-30a8-53bf21dee7d3",
    "profile": {
        "full_name": "Nick Fisher",
        "title": "VP of Marketing",
        "headline": "VP Marketing at Zafran Security",
    },
    "link": {"linkedin": "https://www.linkedin.com/in/nicholastfisher"},
    "location": {
        "default": "New York, New York, United States, North America",
        "short": "New York, New York",
        "country": "United States",
        "state": "New York",
        "city": "New York",
        "position": None,
    },
    "member_badges": {"premium": True, "creator": True, "hiring": False, "influencer": None},
    "statistics": {"network": {"followers_count": 6808, "connections_count": 4776}},
    "position_groups": [
        {
            "company": {"name": "Zafran Security", "url": "https://www.linkedin.com/company/zaf"},
            "date": {"start": "2024-04-01", "end": None},
            "profile_positions": [
                {
                    "company": "Zafran Security",
                    "title": "VP of Marketing",
                    "date": {"start": "2024-04-01", "end": None},
                }
            ],
        },
        {
            "company": {"name": "Sysdig"},
            "date": {"start": "2021-09-01", "end": "2024-04-30"},
            "profile_positions": [
                {
                    "company": "Sysdig",
                    "title": "Senior Director, Product Marketing",
                    "date": {"start": "2023-01-01", "end": "2024-04-30"},
                },
                {
                    "company": "Sysdig",
                    "title": "Director, Product Marketing",
                    "date": {"start": "2021-09-01", "end": "2022-12-31"},
                },
            ],
        },
        {"company": {"url": "https://www.linkedin.com/company/nameless"}, "profile_positions": []},
    ],
    "department": {"seniority": "vp"},
}


def _person(record: Mapping[str, Any] = PERSON_RECORD) -> AiArkPerson:
    return person_from_record(record)


def test_a_person_scoped_draft_is_stamped_to_the_contact_not_the_account() -> None:
    """The subject of the job decides the entity, the mode and the personal-data provenance."""
    items = [
        ClaimInput(
            field_key="contact.facet.hobby",
            value=["surfing"],
            evidence_span="I surf every Sunday",
            source_url="https://li.test/nick",
            priority=2,
        )
    ]

    (draft,) = agent_claims(items, PERSON_SCOPE, catalog=PERSON_CATALOG)

    assert draft.entity_id == CONTACT_ID and draft.entity_type is EntityType.CONTACT
    assert draft.research_mode is ResearchMode.CONTACT_PROFILING
    assert draft.identity_binding is IdentityBinding.STRONG
    assert draft.use_class is UseClass.PERSONAL_PUBLIC_NON_SENSITIVE


def test_a_person_claim_on_a_field_with_no_hint_is_born_professional_public() -> None:
    items = [
        ClaimInput(
            field_key="contact.current_title",
            value="VP of Marketing",
            evidence_span="VP of Marketing",
            source_url="https://li.test/nick",
            priority=2,
        )
    ]

    (draft,) = agent_claims(items, PERSON_SCOPE, catalog=PERSON_CATALOG)

    assert draft.use_class is UseClass.PROFESSIONAL_PUBLIC
    assert draft.identity_binding is IdentityBinding.STRONG


def test_an_account_scoped_draft_is_unchanged_by_the_person_subject() -> None:
    """The account path stamps no binding and no use class: the writer's defaults still decide."""
    items = [
        ClaimInput(
            field_key="core.industry",
            value="Computer & Network Security",
            evidence_span="Computer & Network Security",
            source_url="https://zafran.io/about",
            priority=2,
        )
    ]

    (draft,) = agent_claims(items, SCOPE, catalog=CATALOG)

    assert draft.entity_id == SCOPE.account_id and draft.entity_type is EntityType.ACCOUNT
    assert draft.research_mode is ResearchMode.ACCOUNT_PROFILING
    assert draft.identity_binding is None and draft.use_class is None


def test_a_person_scope_without_a_contact_is_refused_at_construction() -> None:
    with pytest.raises(ValueError, match="contact_id"):
        replace(SCOPE, subject_kind="person")


def test_the_ai_ark_person_record_maps_onto_its_registered_contact_fields() -> None:
    person = _person()
    drafts = {draft.field_key: draft for draft in ai_ark_person_claims(person, PERSON_SCOPE)}

    assert drafts["contact.current_title"].value_json == "VP of Marketing"
    assert "contact.headline" not in drafts
    assert person.headline == "VP Marketing at Zafran Security"
    assert drafts["contact.current_location"].value_json == {
        "raw": "New York, New York, United States, North America",
        "country": "United States",
    }
    assert drafts["contact.network_statistics"].value_json == {
        "followers": 6808,
        "connections": 4776,
    }
    # An explicit provider null is dropped, exactly as everywhere else: absent is not null.
    assert drafts["contact.member_badges"].value_json == {
        "premium": True,
        "creator": True,
        "hiring": False,
    }
    # The person's LinkedIn URL is the contact entity's own column — the identity strong key the
    # lock was made on — so the mapper writes no claim that could answer it a second time.
    assert "contact.linkedin_url" not in drafts


def test_every_ai_ark_person_claim_cites_its_raw_path_and_never_a_fabricated_url() -> None:
    drafts = {draft.field_key: draft for draft in ai_ark_person_claims(_person(), PERSON_SCOPE)}

    assert {key: draft.markers["json_path"] for key, draft in drafts.items()} == {
        "contact.current_title": "profile.title",
        "contact.current_location": "location",
        "contact.network_statistics": "statistics.network",
        "contact.member_badges": "member_badges",
        "contact.facet.career_history": "position_groups",
    }
    for draft in drafts.values():
        assert draft.source_url is None and draft.source_key == "ai_ark:person"
        assert draft.extraction_method is ExtractionMethod.API
        assert draft.markers["provider_record"] == "ai_ark"
        assert draft.entity_id == CONTACT_ID and draft.entity_type is EntityType.CONTACT
        assert draft.identity_binding is IdentityBinding.STRONG


def test_the_career_history_is_one_row_per_role_at_the_org_that_held_it() -> None:
    """``position_groups[].profile_positions[]`` is the record's employment list; a promotion is
    its own row, and a group naming no org is not a career-history row at all."""
    (draft,) = [
        draft
        for draft in ai_ark_person_claims(_person(), PERSON_SCOPE)
        if draft.field_key == "contact.facet.career_history"
    ]

    # W3: the dates nest under ``date`` — the shape the answer keys carry and the one the contact
    # header's tenure reads. An open stint states no ``end`` at all.
    assert draft.value_json == [
        {
            "org": "Zafran Security",
            "role": "VP of Marketing",
            "date": {"start": "2024-04-01"},
        },
        {
            "org": "Sysdig",
            "role": "Senior Director, Product Marketing",
            "date": {"start": "2023-01-01", "end": "2024-04-30"},
        },
        {
            "org": "Sysdig",
            "role": "Director, Product Marketing",
            "date": {"start": "2021-09-01", "end": "2022-12-31"},
        },
    ]
    assert draft.use_class is UseClass.PROFESSIONAL_PUBLIC


def test_a_career_history_the_record_dates_nowhere_carries_no_date_at_all() -> None:
    """An empty ``date`` would read as a current position with an unknown start; absent is not
    null, and the entry is still a real stint."""
    (draft,) = [
        draft
        for draft in ai_ark_person_claims(
            _person(
                {
                    **PERSON_RECORD,
                    "position_groups": [
                        {
                            "company": {"name": "Sysdig"},
                            "profile_positions": [{"company": "Sysdig", "title": "Director"}],
                        }
                    ],
                }
            ),
            PERSON_SCOPE,
        )
        if draft.field_key == "contact.facet.career_history"
    ]

    assert draft.value_json == [{"org": "Sysdig", "role": "Director"}]


def test_the_mapped_career_history_satisfies_the_field_registry_schema() -> None:
    """The nested shape is what ``contact.facet.career_history`` declares (migration
    ``7c4f1a2b9d63``), so the claim it produces is schema-valid rather than merely tolerated."""
    (draft,) = [
        draft
        for draft in ai_ark_person_claims(_person(), PERSON_SCOPE)
        if draft.field_key == "contact.facet.career_history"
    ]
    (registered,) = [
        seed for seed in DEEP_PROFILING_PACK if seed.field_def.field_key == FACET_CAREER_HISTORY
    ]

    assert check_value_schema(draft.value_json, registered.value_schema) is True


def test_the_ai_ark_title_loses_the_company_the_record_hung_on_the_end() -> None:
    """W4: ``profile.title`` is frequently "role | employer", and the employer is a fact the
    account row already states. The raw string stays on the claim as ``title_raw``."""
    drafts = {
        draft.field_key: draft
        for draft in ai_ark_person_claims(
            _person(
                {
                    **PERSON_RECORD,
                    "profile": {**PERSON_RECORD["profile"], "title": "Head of Growth | Zafran"},
                    "position_groups": [
                        {
                            "company": {"name": "Zafran"},
                            "profile_positions": [{"company": "Zafran", "title": "Head of Growth"}],
                        }
                    ],
                }
            ),
            PERSON_SCOPE,
        )
    }

    assert drafts["contact.current_title"].value_json == "Head of Growth"
    assert drafts["contact.current_title"].markers["title_raw"] == "Head of Growth | Zafran"


def test_the_account_the_job_is_about_also_cuts_the_suffix() -> None:
    """The record's own company is asked first, but the job already knows whose account this is —
    which is what catches the live case, where the record spelled the employer a third way."""
    (draft,) = [
        draft
        for draft in ai_ark_person_claims(
            _person(
                {
                    **PERSON_RECORD,
                    "profile": {
                        **PERSON_RECORD["profile"],
                        "title": "Head of Growth at Zafran Security ",
                    },
                }
            ),
            PERSON_SCOPE,
        )
        if draft.field_key == "contact.current_title"
    ]

    assert PERSON_SCOPE.account_name == "Zafran Security"
    assert draft.value_json == "Head of Growth"


def test_a_title_that_merely_contains_a_separator_is_passed_through_untouched() -> None:
    """ "Head of Security at Scale" is a title, not a title plus an employer, and nothing this job
    knows says otherwise. It is written exactly as the record wrote it, with no ``title_raw``."""
    (draft,) = [
        draft
        for draft in ai_ark_person_claims(
            _person(
                {
                    **PERSON_RECORD,
                    "profile": {
                        **PERSON_RECORD["profile"],
                        "title": "Head of Security at Scale",
                    },
                }
            ),
            PERSON_SCOPE,
        )
        if draft.field_key == "contact.current_title"
    ]

    assert draft.value_json == "Head of Security at Scale"
    assert "title_raw" not in draft.markers


def test_a_person_record_that_answers_nothing_yields_no_claims() -> None:
    assert ai_ark_person_claims(_person({"profile": {}}), PERSON_SCOPE) == []


def test_an_email_export_that_found_nothing_is_no_claim_at_all() -> None:
    export = email_export_from_record({"profile": {"full_name": "Kate"}, "email": {"output": []}})

    assert export.found is False
    assert email_export_claim(export, PERSON_SCOPE) is None


def test_a_found_email_is_a_tier1_claim_carrying_its_verdict() -> None:
    export = email_export_from_record(
        {
            "profile": {"full_name": "Kate Blumberg"},
            "email": {
                "output": [
                    {
                        "address": "kate@probook.ai",
                        "status": "VALID",
                        "domainType": "CATCH_ALL",
                        "found": True,
                    }
                ]
            },
        }
    )

    draft = email_export_claim(export, PERSON_SCOPE)

    assert draft is not None
    # W1: the value is the address **with the verdict that graded it** — the pair the field
    # declares and the contact header's email chip reads. The record stated no check date, so the
    # key is absent rather than null.
    assert draft.field_key == "core.work_email"
    assert draft.value_json == {"address": "kate@probook.ai", "status": "catch_all_valid"}
    assert draft.entity_id == CONTACT_ID and draft.entity_type is EntityType.CONTACT
    assert draft.extraction_method is ExtractionMethod.API
    assert draft.source_key == "ai_ark:email_export"
    assert draft.markers["verdict"] == "catch_all_valid"
    # The domain accepts every address, so the mailbox itself is unproven.
    assert draft.markers["provider_verified"] is False
    assert draft.markers["json_path"] == "email.output[0].address"


def test_only_an_smtp_verified_mailbox_is_recorded_as_provider_verified() -> None:
    export = email_export_from_record(
        {
            "email": {
                "output": [
                    {
                        "address": "nick@zafran.io",
                        "status": "VALID",
                        "domainType": "SMTP",
                        "found": True,
                        "date": "2026-09-02T09:00:00",
                    }
                ]
            }
        }
    )

    draft = email_export_claim(export, PERSON_SCOPE)

    assert draft is not None
    assert draft.markers["verdict"] == "verified_smtp"
    assert draft.markers["provider_verified"] is True
    assert draft.value_json == {
        "address": "nick@zafran.io",
        "status": "verified_smtp",
        "checked_at": "2026-09-02T09:00:00",
    }


def test_the_mapped_work_email_satisfies_the_field_registry_schema() -> None:
    """``core.work_email`` declares the object (migration ``7c4f1a2b9d63``), so what the export
    mapper writes is schema-valid rather than stored under a ``schema_valid=false`` marker."""
    export = email_export_from_record(
        {
            "email": {
                "output": [
                    {
                        "address": "nick@zafran.io",
                        "status": "VALID",
                        "domainType": "SMTP",
                        "found": True,
                        "date": "2026-09-02T09:00:00",
                    }
                ]
            }
        }
    )
    draft = email_export_claim(export, PERSON_SCOPE)
    (registered,) = [seed for seed in CORE_PACK if seed.field_def.field_key == "core.work_email"]

    assert draft is not None
    assert check_value_schema(draft.value_json, registered.value_schema) is True


#: The three committee fields as a registry serves them. ``contact.role_on_committee``'s hint is
#: deliberately the *unusual* one: it is what proves the born use class is read off the field and
#: not the claim path's ``PROFESSIONAL_PUBLIC`` default, which the other two happen to agree with.
COMMITTEE_CATALOG = FieldCatalog(
    contact=(
        FieldSpec("contact.persona", "Buying-committee persona.", _STR),
        FieldSpec("contact.current_title", "Current professional title.", _STR),
        FieldSpec(
            "contact.role_on_committee",
            "The seat and the reasoning behind it.",
            None,
            use_class_hint="personal-public-non-sensitive",
        ),
    )
)


def test_a_committee_member_is_written_onto_their_own_contact_entity() -> None:
    """The account job resolved the committee, so the claims are about a person even though the
    job's own subject is the account: the contact id is passed, never inferred."""
    drafts = committee_member_claims(
        {
            "name": "Nick Fisher",
            "title": "VP of Marketing",
            "persona": "champion",
            "rationale": "owns the ABM programme",
            "influence": "high",
            "confirmed_by": "https://www.linkedin.com/in/nicholastfisher",
            "evidence_span": "VP Marketing at Zafran Security",
        },
        scope=SCOPE,
        contact_id=CONTACT_ID,
        catalog=COMMITTEE_CATALOG,
    )

    by_key = {draft.field_key: draft for draft in drafts}
    assert set(by_key) == {
        "contact.persona",
        "contact.role_on_committee",
        "contact.current_title",
    }
    assert by_key["contact.persona"].value_json == "champion"
    assert by_key["contact.role_on_committee"].value_json == {
        "role": "champion",
        "rationale": "owns the ABM programme",
        "influence": "high",
    }
    assert by_key["contact.current_title"].value_json == "VP of Marketing"
    for draft in drafts:
        assert draft.entity_id == CONTACT_ID and draft.entity_type is EntityType.CONTACT
        assert draft.research_mode is ResearchMode.CONTACT_PROFILING
        assert draft.identity_binding is IdentityBinding.STRONG
        assert draft.source_url == "https://www.linkedin.com/in/nicholastfisher"
        assert draft.evidence_span == "VP Marketing at Zafran Security"


def test_a_committee_member_claim_takes_its_use_class_from_the_field_not_the_default() -> None:
    """Nothing here decides a meaning the field does not declare: the two fields whose registry
    row states nothing land the claim path's default, and the one that declares a use class lands
    what it declares — even when that is not the default."""
    drafts = {
        draft.field_key: draft
        for draft in committee_member_claims(
            {
                "name": "Nick Fisher",
                "title": "VP of Marketing",
                "persona": "champion",
                "confirmed_by": "https://www.linkedin.com/in/nicholastfisher",
            },
            scope=SCOPE,
            contact_id=CONTACT_ID,
            catalog=COMMITTEE_CATALOG,
        )
    }

    assert drafts["contact.persona"].use_class is UseClass.PROFESSIONAL_PUBLIC
    assert drafts["contact.current_title"].use_class is UseClass.PROFESSIONAL_PUBLIC
    assert drafts["contact.role_on_committee"].use_class is UseClass.PERSONAL_PUBLIC_NON_SENSITIVE


def test_a_committee_member_with_no_persona_or_title_writes_only_what_it_has() -> None:
    drafts = committee_member_claims(
        {"name": "Sanaz Yashar", "confirmed_by": "https://li.test/sanaz"},
        scope=SCOPE,
        contact_id=CONTACT_ID,
        catalog=COMMITTEE_CATALOG,
    )

    assert [draft.field_key for draft in drafts] == []
