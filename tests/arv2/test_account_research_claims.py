"""The deterministic claim mappers: provider records and model output → typed claim drafts.

Every function under test is **pure** (Global Constraint 3 is satisfied trivially: no provider is
reachable from here). What is asserted is the part a model or a provider must never be trusted to
decide for itself — which key a record lands on, which raw path it came from, what a negative is
born as, and that a `fail` verdict with nothing behind it is downgraded rather than believed.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from clue_api.arv2.account_research_claims import (
    ClaimInput,
    JobScope,
    agent_claims,
    ai_ark_company_claims,
    ats_posting_claims,
    committee_candidate_claims,
    fit_verdict_claims,
    media_index_claim,
    negative_claims,
    structured_claims,
    unconfirmed_candidates,
)
from clue_api.arv2.ai_ark_client import AiArkCompany
from clue_api.arv2.ats_client import AtsBoard, BoardPostings, JobPosting
from clue_api.arv2.calls import CallCost
from clue_api.arv2.structuring_client import (
    NegativeOrRisk,
    ProposedField,
    StructuredClaim,
    StructuredOutput,
)
from clue_core import EntityId, EntityType, ExtractionMethod, ResearchMode

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
        revenue="$10M-$25M",
        technologies=("HubSpot",),
        location={"country": "US", "city": "New York"},
        raw={},
        cost=None,
    )

    drafts = {d.field_key: d for d in ai_ark_company_claims(company, SCOPE)}

    assert set(drafts) == {
        "core.company_linkedin_url",
        "core.industry",
        "core.employee_count",
        "core.revenue_band",
        "core.hq_location",
    }
    assert drafts["core.employee_count"].value_json == 180
    # The path is read off ``company_from_record``, not invented: the record nests the count
    # under ``summary.staff.total``, which is what a replay has to look at.
    assert drafts["core.employee_count"].markers["json_path"] == "summary.staff.total"
    assert drafts["core.revenue_band"].markers["json_path"] == "financial.revenue.annual.amount"
    assert drafts["core.hq_location"].markers["json_path"] == "location.headquarter"
    assert all(
        d.extraction_method is ExtractionMethod.API
        and d.source_key == "ai_ark:company"
        and d.source_url is None
        and d.markers["provider_record"] == "ai_ark"
        for d in drafts.values()
    )


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
    assert ai_ark_company_claims(company, SCOPE) == []


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
    assert draft.value_json == {
        "what": "Calcalist reported acquisition talks with Cisco",
        "status": "refuted",
        "source_note": None,
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
        for d in structured_claims(output, scope=SCOPE, subject_url_hint="https://probook.ai")
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
