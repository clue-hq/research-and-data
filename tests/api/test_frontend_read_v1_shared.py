"""ARV2 D3 Task 2 — the shared contract-v1 rules every accounts endpoint composes through.

Two halves in one file, deliberately: the pure half (the display predicate, the label maps, the
bands, the renderers) needs no database and runs everywhere; the database half (owners, custom
fields, last-modified, activity, evidence) runs on the worktree's throwaway Postgres through
``rollback_conn`` and is skipped when there is none. Splitting them across two files would let the
label a band computes drift from the label a route serves without a single test going red.

The inputs are the real Zafran shapes the D1/D2 lanes actually stored — ``"VP of Marketing"``, a
career-history list whose current position carries ``date.start`` and a null ``date.end``, an
alma-mater object, a ``work_email`` value with a ``verified_smtp`` status — because the whole point
of this module is that no endpoint invents a display string from a shape it guessed at.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any, get_args

import pytest
from sqlalchemy import bindparam, event, text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.account_research_claims import (
    JobScope,
    ai_ark_person_claims,
    email_export_claim,
)
from clue_api.arv2.account_research_store import JobStatus, create_job
from clue_api.arv2.ai_ark_client import email_export_from_record, person_from_record
from clue_api.arv2.catalog_seed import load_arv2_pack
from clue_api.arv2.claim_writer import ClaimDraft, LenientClaimWriter
from clue_api.frontend_read.contract_v1 import (
    AccountCustomField,
    AccountOwner,
    AccountSocial,
    ClueActor,
    PersonActor,
    ResearchStatus,
)
from clue_api.frontend_read.v1_shared import (
    EMPTY_BAND,
    INFLUENCE_DEFAULTS,
    PERSONA_RANK,
    PERSONA_TONES,
    PROVIDER_LABELS,
    RESEARCH_STATUS_LABELS,
    activity_for,
    arv2_display_allowed,
    arv2_research_status_for,
    band_for_headcount,
    contact_last_modified,
    current_position_start,
    custom_fields_for,
    education_label,
    email_facts,
    fit_band,
    fit_score_100,
    format_money,
    funding_label,
    headcount_label,
    industry_labels,
    last_modified_for,
    linkedin_label,
    owners_for,
    persona_display,
    research_evidence_for,
    revenue_band_label,
    revenue_label,
    socials,
    tenure,
    time_label,
    website_label,
    website_url,
)
from clue_config import Settings
from clue_core import (
    Claim,
    Confidence,
    EntityId,
    EntityType,
    ExtractionMethod,
    IdentityBinding,
    ResearchMode,
    SourceTier,
    UseClass,
    new_run_id,
)
from clue_research.claimstore.packs import load_core_pack
from clue_research.compliance import WorkspacePolicy
from clue_research.discovery_scoring.discovery import REVENUE_BAND_OPTIONS
from clue_research.identity import insert_account_entity, insert_contact_entity
from clue_spine import Project
from tests._workspace import seed_project, seed_workspace
from tests.arv2.account_research_job_helpers import seed_arv2_job
from tests.db.conftest import run_async
from tests.profiling.conftest import rollback_conn

_NOW = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)

#: One person job's scope, and the AI Ark record it researches. They exist here so the two W1/W3
#: tests below can assert the *pair* — the mapper's real output read by the real reader — instead
#: of a hand-written value that could drift away from what the mapper writes.
_PERSON_SCOPE = JobScope(
    workspace_id="ws-v1-shared",
    project_id="prj-v1-shared",
    project_run_id=uuid.uuid4(),
    run_id=uuid.uuid4(),
    job_id=uuid.uuid4(),
    account_id=EntityId(uuid.uuid4()),
    account_name="Zafran Security",
    account_domain="zafran.io",
    icp_markdown="",
    persona_markdown="",
    already_established="",
    effort="full",
    committee_cap=1,
    today=date(2026, 9, 9),
    subject_kind="person",
    contact_id=EntityId(uuid.uuid4()),
    person_name="Nick Fisher",
)

_AI_ARK_PERSON: dict[str, Any] = {
    "profile": {"full_name": "Nick Fisher", "title": "VP of Marketing"},
    "position_groups": [
        {
            "company": {"name": "Zafran Security"},
            "profile_positions": [
                {
                    "company": "Zafran Security",
                    "title": "VP of Marketing",
                    "date": {"start": "2024-04-01", "end": None},
                }
            ],
        }
    ],
}


def _settings() -> Settings:
    return Settings(_env_file=None)


def _account_claim(**overrides: Any) -> Claim:
    values: dict[str, Any] = {
        "entity_id": EntityId(uuid.uuid4()),
        "entity_type": EntityType.ACCOUNT,
        "field_key": "core.employee_count",
        "value_json": 400,
        "source_tier": SourceTier(2),
        "extraction_method": ExtractionMethod.API,
        "confidence": Confidence(0.9),
        "run_id": new_run_id(),
        "research_mode": ResearchMode.ACCOUNT_PROFILING,
    }
    values.update(overrides)
    return Claim(**values)


def _contact_claim(**overrides: Any) -> Claim:
    values: dict[str, Any] = {
        "entity_id": EntityId(uuid.uuid4()),
        "entity_type": EntityType.CONTACT,
        "field_key": "contact.current_title",
        "value_json": "VP of Marketing",
        "source_tier": SourceTier(3),
        "extraction_method": ExtractionMethod.SCRAPE,
        "confidence": Confidence(0.8),
        "run_id": new_run_id(),
        "research_mode": ResearchMode.CONTACT_PROFILING,
        "identity_binding": IdentityBinding.STRONG,
        "use_class": UseClass.PROFESSIONAL_PUBLIC,
    }
    values.update(overrides)
    return Claim(**values)


# --- the display predicate --------------------------------------------------------------------


def test_an_account_claim_is_always_displayable() -> None:
    """Governance here is personal-data governance; an account fact has no data subject."""
    locked = WorkspacePolicy(
        display_professional_public=False,
        display_personal_public_non_sensitive=False,
        display_sensitive=False,
    )
    assert arv2_display_allowed(_account_claim(), locked) is True


def test_a_sensitive_claim_follows_the_sensitive_switch_only() -> None:
    claim = _contact_claim(use_class=UseClass.SENSITIVE, outreach_safe=False)
    assert arv2_display_allowed(claim, WorkspacePolicy()) is False
    assert arv2_display_allowed(claim, WorkspacePolicy(display_sensitive=True)) is True


def test_a_weak_binding_does_not_hide_a_displayable_contact_fact() -> None:
    """Ruling S10: identity binding is never consulted by the v1 display predicate."""
    weak = _contact_claim(identity_binding=IdentityBinding.WEAK)
    assert arv2_display_allowed(weak, WorkspacePolicy()) is True
    assert arv2_display_allowed(weak, WorkspacePolicy(display_requires_strong_contact_binding=True))


def test_an_outreach_unsafe_contact_claim_is_refused() -> None:
    """It may appear only inside a restricted section, which the display module routes itself."""
    claim = _contact_claim(outreach_safe=False)
    assert arv2_display_allowed(claim, WorkspacePolicy()) is False


def test_the_professional_switch_hides_professional_contact_facts() -> None:
    claim = _contact_claim()
    assert arv2_display_allowed(claim, WorkspacePolicy()) is True
    assert arv2_display_allowed(claim, WorkspacePolicy(display_professional_public=False)) is False


def test_a_personal_non_sensitive_claim_follows_its_own_switch() -> None:
    claim = _contact_claim(
        field_key="contact.facet.hobbies",
        value_json="cocktail making",
        use_class=UseClass.PERSONAL_PUBLIC_NON_SENSITIVE,
    )
    assert arv2_display_allowed(claim, WorkspacePolicy()) is True
    assert (
        arv2_display_allowed(claim, WorkspacePolicy(display_personal_public_non_sensitive=False))
        is False
    )


def test_a_contact_claim_with_no_use_class_is_treated_as_professional_public() -> None:
    """The lenient writer leaves ``use_class`` NULL on non-facet contact fields such as
    ``contact.current_title``; hiding every title would empty the contacts screens."""
    claim = _contact_claim(use_class=None, identity_binding=None)
    assert arv2_display_allowed(claim, WorkspacePolicy()) is True
    assert arv2_display_allowed(claim, WorkspacePolicy(display_professional_public=False)) is False


# --- the label maps ---------------------------------------------------------------------------


def test_the_arv2_job_statuses_are_the_wire_statuses_verbatim() -> None:
    """Why :func:`arv2_research_status_for` may serve ``arv2_research_job.status`` unmapped.

    The R2 store's ``JobStatus`` is the code's source of truth for that column (the migration's
    CHECK mirrors it); ``ResearchStatus`` is the contract's. They are the same five strings, so the
    read layer has no lifecycle to reinterpret — and if either side ever grows a sixth state, this
    is where it is noticed, rather than in a payload that fails Zod at the browser.
    """
    assert set(get_args(JobStatus)) == set(get_args(ResearchStatus))
    assert set(get_args(JobStatus)) == set(RESEARCH_STATUS_LABELS)


def test_the_research_status_labels_cover_the_five_states() -> None:
    assert RESEARCH_STATUS_LABELS == {
        "not_started": "Not started",
        "in_progress": "In progress",
        "needs_review": "Needs review",
        "completed": "Researched",
        "suspended": "Paused",
    }


def test_persona_tones_influence_and_rank_agree_on_the_vocabulary() -> None:
    assert PERSONA_TONES["economic_buyer"] == "olive"
    assert PERSONA_TONES["blocker"] == "red"
    assert PERSONA_TONES.get("cfo_whisperer", "green") == "green"
    assert INFLUENCE_DEFAULTS["champion"] == "High"
    assert INFLUENCE_DEFAULTS.get("cfo_whisperer", "Medium") == "Medium"
    assert PERSONA_RANK == (
        "economic_buyer",
        "champion",
        "technical_evaluator",
        "user",
        "blocker",
    )
    assert set(PERSONA_TONES) == set(INFLUENCE_DEFAULTS) == set(PERSONA_RANK)


def test_provider_labels_map_the_lane_sources_and_pass_an_unknown_through() -> None:
    assert PROVIDER_LABELS["ai_ark"] == "AI Ark"
    assert PROVIDER_LABELS["exa_contents"] == "Exa"
    assert PROVIDER_LABELS["exa_search"] == "Exa"
    assert PROVIDER_LABELS["exa_deep"] == "Exa"
    assert PROVIDER_LABELS["ashby_posting_api"] == "Ashby"
    assert PROVIDER_LABELS["gemini"] == "Gemini transcript"
    assert PROVIDER_LABELS["client_interview"] == "Interview"
    assert PROVIDER_LABELS["client_interview_judged"] == "Interview"
    assert PROVIDER_LABELS.get("firecrawl", "firecrawl") == "firecrawl"


def test_the_empty_band_is_the_documented_placeholder() -> None:
    assert EMPTY_BAND == "Unknown"


# --- fit ----------------------------------------------------------------------------------------


def test_fit_band_reads_the_two_configured_thresholds() -> None:
    settings = _settings()
    assert fit_band(0.70, settings=settings) == "High"
    assert fit_band(0.69, settings=settings) == "Medium"
    assert fit_band(0.40, settings=settings) == "Medium"
    assert fit_band(0.39, settings=settings) == "Low"
    assert fit_band(None, settings=settings) is None


def test_fit_score_100_rounds_and_clamps() -> None:
    assert fit_score_100(0.7) == 70
    assert fit_score_100(0.695) == 70
    assert fit_score_100(None) is None
    assert fit_score_100(-0.5) == 0
    assert fit_score_100(1.4) == 100


# --- account rail labels ------------------------------------------------------------------------


def test_band_for_headcount_walks_the_documented_bands() -> None:
    assert band_for_headcount(1) == "1-10"
    assert band_for_headcount(10) == "1-10"
    assert band_for_headcount(11) == "11-50"
    assert band_for_headcount(200) == "51-200"
    assert band_for_headcount(500) == "201-500"
    assert band_for_headcount(1000) == "501-1000"
    assert band_for_headcount(5000) == "1001-5000"
    assert band_for_headcount(10000) == "5001-10000"
    assert band_for_headcount(10001) == "10001+"
    assert band_for_headcount(0) is None
    assert band_for_headcount(None) is None


def test_headcount_label_serves_whichever_half_exists() -> None:
    assert headcount_label(400, "201-500") == "400 (201-500)"
    assert headcount_label(400, None) == "400"
    assert headcount_label(None, "201-500") == "201-500"
    assert headcount_label(None, None) == "Unknown"


def test_format_money_is_compact_with_at_most_one_decimal() -> None:
    assert format_money(10_000_000, "USD") == "$10M"
    assert format_money(130_500_000, "USD") == "$130.5M"
    assert format_money(1_200_000_000, "USD") == "$1.2B"
    assert format_money(750_000, "USD") == "$750K"
    assert format_money(900, "USD") == "$900"
    # A numeric string is a number: the lenient writer does not enforce the value schema.
    assert format_money("60000000", "USD") == "$60M"


def test_format_money_names_the_currency_it_was_given_and_nothing_else() -> None:
    assert format_money(12_000_000, "EUR") == "€12M"
    assert format_money(12_000_000, "GBP") == "£12M"
    # A code with no symbol we can vouch for is written out, not guessed at.
    assert format_money(12_000_000, "INR") == "INR 12M"
    # And an amount nobody denominated gets NO symbol: defaulting to "$" would turn an
    # undenominated figure into a dollar figure on a card a marketer quotes.
    assert format_money(60_000_000, None) == "60M"


def test_format_money_refuses_everything_that_is_not_a_positive_number() -> None:
    assert format_money(None, "USD") is None
    assert format_money("private", "USD") is None
    assert format_money({"amount": 5}, "USD") is None
    assert format_money(0, "USD") is None
    assert format_money(-5_000_000, "USD") is None
    # ``True`` is an ``int`` in Python; it is not one dollar.
    assert format_money(True, "USD") is None


def test_revenue_label_reads_the_registry_object_never_renders_it() -> None:
    # The exact ``core.annual_revenue`` value the D1 answer key stores for Zafran Security.
    zafran = {
        "amount_min": 10_000_000,
        "amount_max": 25_000_000,
        "currency": "USD",
        "as_of": "2026-08-22",
        "estimate_kind": "provider_estimate",
    }
    assert revenue_label(zafran, "10m_50m") == "$10M–25M"
    # The symbol once, the unit on each side — so a range that crosses a unit still reads.
    assert revenue_label({"amount_min": 750_000, "amount_max": 1_200_000}, None) == "750K–1.2M"
    assert revenue_label({"amount_min": 10_000_000, "currency": "USD"}, None) == "$10M+"
    assert revenue_label({"amount_max": 25_000_000, "currency": "USD"}, None) == "up to $25M"
    assert revenue_label({"amount": 30_000_000, "currency": "USD"}, None) == "$30M"


def test_revenue_label_falls_through_to_the_band_then_unknown() -> None:
    assert revenue_label("$30M ARR", None) == "$30M ARR"
    assert revenue_label(None, "$10M-$50M") == "$10M-$50M"
    assert revenue_label(None, None) == "Unknown"
    assert revenue_label("", "$10M-$50M") == "$10M-$50M"
    # An object whose numbers do not parse falls through exactly like a missing claim.
    assert revenue_label({"estimate_kind": "provider_estimate"}, "$10M-$50M") == "$10M-$50M"
    assert revenue_label({"amount": "undisclosed"}, None) == "Unknown"


def test_funding_label_joins_the_round_and_the_total() -> None:
    assert funding_label({"round": "Series B"}, "$50M") == "Series B · $50M"
    assert funding_label({"round": "Series B"}, None) == "Series B"
    assert funding_label(None, "$50M") == "$50M"
    assert funding_label(None, None) is None
    # ``"$30M"`` is not a number, so the round says nothing and the label is empty.
    assert funding_label({"amount": "$30M"}, None) is None
    # A prose value is the sentence it is — the synthesis lane writes these.
    assert funding_label("Series B closed in 2024", None) == "Series B closed in 2024"


def test_funding_label_reads_the_registry_objects_never_renders_them() -> None:
    recent = {
        "round": "Series C",
        "amount": 60_000_000,
        "currency": "USD",
        "date": "2025-12-02",
        "investors": ["Menlo Ventures"],
    }
    total = {"amount": 130_500_000, "currency": "USD", "rounds": 4, "investors": 9}
    assert funding_label(recent, None) == "Series C · $60M"
    assert funding_label(None, total) == "$130.5M"
    assert funding_label(recent, total) == "Series C · $60M · $130.5M"
    # The synthesis lane's own shape names its currency in its key — on either half.
    assert funding_label(None, {"amount_usd": 130_000_000, "semantics": "reported"}) == "$130M"
    assert funding_label({"round": "Series C", "amount_usd": 60_000_000}, None) == "Series C · $60M"


#: The shape the answer key actually stores for Zafran: a list, keyed the provider's way —
#: ``type``/``raised_amount``/``announced_at`` rather than the registry sketch's
#: ``round``/``amount``/``date``, and no ``currency`` on any round.
_ZAFRAN_ROUNDS = [
    {"type": "SERIES_B", "announced_at": "2024-09-08", "raised_amount": 40_000_000},
    {"type": "SERIES_C", "announced_at": "2025-12-02", "raised_amount": 60_000_000},
    {"type": "SEED_ROUND", "announced_at": "2024-03-28", "raised_amount": 5_500_000},
]


def test_funding_label_takes_the_latest_round_from_the_providers_list() -> None:
    assert funding_label(_ZAFRAN_ROUNDS, None) == "Series C · 60M"
    # A list that states no dates keeps its own order rather than inventing one.
    assert funding_label([{"type": "SERIES_A"}, {"type": "SEED_ROUND"}], None) == "Series A"
    assert funding_label([], None) is None
    # A round already named in words is served exactly as written, never re-title-cased.
    assert funding_label([{"round": "Series C extension"}], None) == "Series C extension"


def test_a_round_with_no_currency_borrows_the_totals() -> None:
    """Same account, same provider record: the total's denomination *is* the round's.

    The provider's rounds carry an amount and no currency while the sibling total carries both, so
    reading one off the other is a fact about that record rather than a guess — and it is what
    stops the label reading "Series C · 60M · $130.5M".
    """
    total = {"amount": 130_500_000, "currency": "USD", "rounds": 4, "investors": 9}
    assert funding_label(_ZAFRAN_ROUNDS, total) == "Series C · $60M · $130.5M"
    # ``amount_usd`` names its own denomination, so a total carrying only that one lends USD too.
    assert funding_label(_ZAFRAN_ROUNDS, {"amount_usd": 130_000_000}) == "Series C · $60M · $130M"
    # A euro total lends euros.
    assert (
        funding_label(
            [{"type": "SERIES_C", "raised_amount": 60_000_000}],
            {"amount": 130_500_000, "currency": "EUR"},
        )
        == "Series C · €60M · €130.5M"
    )
    # The round's own currency always wins over the total's.
    assert (
        funding_label(
            [{"type": "SERIES_C", "raised_amount": 60_000_000, "currency": "GBP"}],
            {"amount": 130_500_000, "currency": "USD"},
        )
        == "Series C · £60M · $130.5M"
    )
    # And when NEITHER half names one there is nothing to read it off, so the amount stays bare.
    assert funding_label(_ZAFRAN_ROUNDS, {"amount": 130_500_000}) == "Series C · 60M · 130.5M"
    assert (
        funding_label(_ZAFRAN_ROUNDS, "reported over $130M")
        == "Series C · 60M · reported over $130M"
    )


def test_every_registered_revenue_band_is_served_as_words() -> None:
    """The closed vocabulary, member by member — and no member may reach a screen as its token.

    ``REVENUE_BAND_OPTIONS`` is imported rather than retyped so that adding a band to the registry
    without teaching this parser about it fails here instead of printing ``"2b_5b"`` at a marketer.
    """
    assert revenue_band_label("under_1m") == "under $1M"
    assert revenue_band_label("1m_10m") == "$1M–10M"
    assert revenue_band_label("10m_50m") == "$10M–50M"
    assert revenue_band_label("50m_100m") == "$50M–100M"
    assert revenue_band_label("100m_500m") == "$100M–500M"
    assert revenue_band_label("500m_1b") == "$500M–1B"
    assert revenue_band_label("1b_plus") == "$1B+"
    for band in REVENUE_BAND_OPTIONS:
        assert revenue_band_label(band) != band, band


def test_revenue_band_label_never_invents_a_range_it_cannot_read() -> None:
    # An unregistered token is still the row's own value: served as written, not guessed at.
    assert revenue_band_label("mid_market") == "mid_market"
    assert revenue_band_label("enterprise") == "enterprise"
    assert revenue_band_label("10m_") == "10m_"
    assert revenue_band_label(None) == "Unknown"
    assert revenue_band_label("  ") == "Unknown"
    # Bare dollar bounds and a thousands unit are read too.
    assert revenue_band_label("250k_1m") == "$250K–1M"
    assert revenue_band_label("under_500000") == "under $500K"


def test_revenue_label_falls_back_to_the_band_as_a_label_not_a_token() -> None:
    assert revenue_label(None, "10m_50m") == "$10M–50M"
    assert revenue_label({"estimate_kind": "provider_estimate"}, "1b_plus") == "$1B+"


def test_persona_display_serves_words_and_is_idempotent() -> None:
    assert persona_display("economic_buyer") == "Economic buyer"
    assert persona_display("technical_evaluator") == "Technical evaluator"
    # A value outside the vocabulary is still served — spelled, not invented.
    assert persona_display("weird_value") == "Weird value"
    # Its own output maps to itself: this is what makes the one-shot rewrite safe to run twice.
    assert persona_display("Economic buyer") == "Economic buyer"
    assert persona_display(None) is None
    assert persona_display("  ") is None


def test_website_url_and_label_come_from_the_primary_domain() -> None:
    assert website_url("zafran.io") == "https://zafran.io"
    assert website_url(None) is None
    assert website_label("www.zafran.io") == "zafran.io"
    assert website_label("zafran.io") == "zafran.io"
    assert website_label(None) is None


def test_industry_labels_lead_with_the_primary_industry_and_dedupe() -> None:
    assert industry_labels("Cybersecurity", ["Cybersecurity", "Software", "Software"]) == [
        "Cybersecurity",
        "Software",
    ]
    assert industry_labels(None, ["Software"]) == ["Software"]
    assert industry_labels("Cybersecurity", None) == ["Cybersecurity"]
    assert industry_labels(None, None) == []
    assert industry_labels(None, [{"name": "Software"}]) == []


def test_socials_only_serve_safe_public_urls() -> None:
    assert socials("https://www.linkedin.com/company/zafran", "https://x.com/zafran") == [
        AccountSocial(
            id="linkedin", label="LinkedIn", url="https://www.linkedin.com/company/zafran"
        ),
        AccountSocial(id="twitter", label="Twitter", url="https://x.com/zafran"),
    ]
    assert socials("javascript:alert(1)", None) == []
    assert socials({"url": "https://linkedin.com/company/zafran"}, None) == []


# --- contact rail labels ------------------------------------------------------------------------


def test_tenure_reports_whole_years_and_months_with_singular_forms() -> None:
    assert tenure(date(2024, 4, 1), now=date(2026, 9, 8)) == ("2 years 5 months", "2024-04-01")
    assert tenure(date(2025, 9, 8), now=date(2026, 9, 8)) == ("1 year", "2025-09-08")
    assert tenure(date(2026, 8, 8), now=date(2026, 9, 8)) == ("1 month", "2026-08-08")
    assert tenure(date(2026, 6, 8), now=date(2026, 9, 8)) == ("3 months", "2026-06-08")
    assert tenure(date(2025, 8, 8), now=date(2026, 9, 8)) == ("1 year 1 month", "2025-08-08")
    assert tenure(date(2027, 1, 1), now=date(2026, 9, 8)) == ("0 months", "2027-01-01")


def test_current_position_start_picks_the_latest_open_entry() -> None:
    history = [
        {"title": "VP of Marketing", "date": {"start": "2024-04-01", "end": None}},
        {"title": "Advisor", "date": {"start": "2025-01-15"}},
        {"title": "Director", "date": {"start": "2019-02-01", "end": "2024-03-31"}},
    ]
    assert current_position_start(history) == date(2025, 1, 15)
    assert current_position_start([{"date": {"start": "2019-02-01", "end": "2024-03-31"}}]) is None
    assert current_position_start(["VP of Marketing at Zafran"]) is None
    assert current_position_start(None) is None


def test_the_tenure_reads_what_the_ai_ark_mapper_actually_writes() -> None:
    """The two halves of walk finding W3, pinned against each other: this reader looks for
    ``date.start`` on the entry with no ``date.end``, and the ARV2 person mapper now writes exactly
    that. It wrote ``start``/``end`` flat, so every mapped person's tenure was empty."""
    (career_history,) = [
        draft.value_json
        for draft in ai_ark_person_claims(person_from_record(_AI_ARK_PERSON), _PERSON_SCOPE)
        if draft.field_key == "contact.facet.career_history"
    ]

    assert current_position_start(career_history) == date(2024, 4, 1)


def test_the_email_chip_reads_what_the_ai_ark_export_mapper_actually_writes() -> None:
    """The two halves of walk finding W1: the export mapper writes ``{address, status}`` and this
    reader shows the address only for a graded verdict. It wrote a bare string, so the chip read
    ``lookup`` for everybody."""
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
    draft = email_export_claim(export, _PERSON_SCOPE)
    assert draft is not None

    facts = email_facts(
        _contact_claim(
            field_key="core.work_email",
            value_json=draft.value_json,
            observed_at=datetime(2026, 9, 2, 9, 0, tzinfo=UTC),
        )
    )

    assert facts.status == "available"
    assert facts.label == "nick@zafran.io"
    # The date on the screen is the provider's own ``checked_at`` day when the value carries one.
    assert facts.verified_at == "2026-09-02"


def test_a_catch_all_export_is_shown_without_a_verification_date() -> None:
    export = email_export_from_record(
        {
            "email": {
                "output": [
                    {
                        "address": "kate@probook.ai",
                        "status": "VALID",
                        "domainType": "CATCH_ALL",
                        "found": True,
                    }
                ]
            }
        }
    )
    draft = email_export_claim(export, _PERSON_SCOPE)
    assert draft is not None

    facts = email_facts(_contact_claim(field_key="core.work_email", value_json=draft.value_json))

    assert facts.status == "available" and facts.label == "kate@probook.ai"
    assert facts.verified_at is None


def test_education_label_renders_an_object_or_a_bare_string() -> None:
    assert education_label({"institution": "Columbia", "degree": "MBA"}) == "Columbia, MBA"
    assert education_label({"institution": "Columbia"}) == "Columbia"
    assert education_label("Columbia") == "Columbia"
    assert education_label({}) is None
    assert education_label(None) is None


def test_education_label_reads_the_providers_list_shapes() -> None:
    """The answer key stores ``alma_mater`` as the provider's list (D3 close-out finding)."""
    strings = ["MBA at Columbia Business School (2011 - 2013)", "BA at Somewhere (2005 - 2009)"]
    assert education_label(strings) == "MBA at Columbia Business School (2011 - 2013)"
    objects = [
        {"school": "Columbia Business School", "degree": "MBA", "field": None},
        {"school": "Somewhere", "degree": "BA"},
    ]
    assert education_label(objects) == "Columbia Business School, MBA"
    assert education_label([None, {}, {"school": "Later"}]) == "Later"
    assert education_label([]) is None


def test_linkedin_label_is_the_last_path_segment() -> None:
    assert linkedin_label("https://www.linkedin.com/in/nicholastfisher") == "nicholastfisher"
    assert linkedin_label("https://www.linkedin.com/in/nicholastfisher/") == "nicholastfisher"
    assert linkedin_label("https://www.linkedin.com") is None
    assert linkedin_label(None) is None


def test_time_label_walks_the_relative_buckets() -> None:
    assert time_label(_NOW - timedelta(seconds=5), now=_NOW) == "just now"
    assert time_label(_NOW - timedelta(minutes=1), now=_NOW) == "1 minute ago"
    assert time_label(_NOW - timedelta(minutes=42), now=_NOW) == "42 minutes ago"
    assert time_label(_NOW - timedelta(hours=1), now=_NOW) == "1 hour ago"
    assert time_label(_NOW - timedelta(hours=5), now=_NOW) == "5 hours ago"
    assert time_label(_NOW - timedelta(hours=30), now=_NOW) == "yesterday"
    assert time_label(_NOW - timedelta(days=3), now=_NOW) == "3 days ago"
    assert time_label(_NOW - timedelta(days=45), now=_NOW) == "2026-07-25"


# --- email --------------------------------------------------------------------------------------


def test_email_facts_reads_the_status_and_the_address() -> None:
    claim = _contact_claim(
        field_key="core.work_email",
        value_json={"address": "nick@zafran.io", "status": "verified_smtp"},
        observed_at=datetime(2026, 9, 2, 9, 0, tzinfo=UTC),
    )
    facts = email_facts(claim)
    assert facts.status == "available"
    assert facts.label == "nick@zafran.io"
    assert facts.verified_at == "2026-09-02"
    assert facts.claim_id == str(claim.id)


def test_a_catch_all_address_is_available_but_never_stamped_verified() -> None:
    claim = _contact_claim(
        field_key="core.work_email",
        value_json={"address": "nick@zafran.io", "status": "catch_all_valid"},
    )
    facts = email_facts(claim)
    assert facts.status == "available"
    assert facts.label == "nick@zafran.io"
    assert facts.verified_at is None


def test_the_verification_date_is_the_providers_check_not_the_write() -> None:
    """D4-b decision 6: ``checked_at`` is when the mailbox answered, not when we wrote the row."""
    claim = _contact_claim(
        field_key="core.work_email",
        value_json={
            "address": "nick@zafran.io",
            "status": "verified_smtp",
            "checked_at": "2026-08-31T07:52:05.000725",
        },
        observed_at=datetime(2026, 9, 2, 9, 0, tzinfo=UTC),
    )
    assert email_facts(claim).verified_at == "2026-08-31"

    unparseable = _contact_claim(
        field_key="core.work_email",
        value_json={"address": "nick@zafran.io", "status": "verified_smtp", "checked_at": "soon"},
        observed_at=datetime(2026, 9, 2, 9, 0, tzinfo=UTC),
    )
    assert email_facts(unparseable).verified_at == "2026-09-02"


def test_every_unusable_verdict_reads_as_lookup_and_keeps_its_claim_id() -> None:
    """The three graded-not-usable verdicts, plus the shape that predates the verdict entirely."""
    for status in ("invalid", "unknown", "unverified"):
        claim = _contact_claim(
            field_key="core.work_email",
            value_json={"address": "nick@zafran.io", "status": status},
        )
        facts = email_facts(claim)
        assert facts.status == "lookup", status
        assert facts.label is None and facts.verified_at is None, status
        assert facts.claim_id == str(claim.id), status

    # A bare address string is every row written before D4-b: an address nobody graded, so the
    # screen offers a lookup rather than showing it as verified. The reader never upgrades it.
    legacy = _contact_claim(field_key="core.work_email", value_json="nick@zafran.io")
    assert email_facts(legacy).status == "lookup"
    assert email_facts(legacy).label is None
    assert email_facts(legacy).claim_id == str(legacy.id)


def test_a_malformed_or_missing_address_degrades_to_lookup() -> None:
    malformed = _contact_claim(
        field_key="core.work_email",
        value_json={"address": "nick-at-zafran", "status": "verified_smtp"},
    )
    facts = email_facts(malformed)
    assert facts.status == "lookup"
    assert facts.label is None
    assert facts.verified_at is None
    assert facts.claim_id == str(malformed.id)

    not_found = _contact_claim(
        field_key="core.work_email",
        value_json={"address": "nick@zafran.io", "status": "not_found"},
    )
    assert email_facts(not_found).status == "lookup"
    assert email_facts(not_found).label is None

    absent = email_facts(None)
    assert absent.status == "lookup"
    assert absent.label is None
    assert absent.claim_id is None


# --- the database half ---------------------------------------------------------------------------

_WS = "d3-v1-shared"
_OTHER_WS = "d3-v1-shared-other"

pytest_db = pytest.mark.usefixtures("require_profiling_db")


async def _seed_user(
    conn: AsyncConnection,
    user_id: str,
    *,
    display_name: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
) -> str:
    await conn.execute(
        text(
            "INSERT INTO platform_user (user_id, display_name, first_name, last_name) "
            "VALUES (:u, :d, :f, :l) ON CONFLICT (user_id) DO NOTHING"
        ),
        {"u": user_id, "d": display_name, "f": first_name, "l": last_name},
    )
    return user_id


async def _seed_workspace_field(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    field_key: str,
    description: str | None,
    presentation: str = "text",
) -> None:
    """One tenant-local ``client.*`` registry row, planted the way the promotion service leaves it.

    The proposal row is inserted directly: the D3 read layer only ever *reads* this table, and the
    C8 proposal machinery would drag an agent turn into a label test.
    """
    brand = f"b_{workspace_id}"
    await conn.execute(
        text(
            "INSERT INTO brand (brand_id, workspace_id, name) VALUES (:b, :w, 'Clue') "
            "ON CONFLICT DO NOTHING"
        ),
        {"b": brand, "w": workspace_id},
    )
    proposal_id = uuid.uuid4()
    await conn.execute(
        text(
            """
            INSERT INTO field_definition_revision (
                id, workspace_id, brand_id, field_key, payload_hash, payload_json,
                proposed_by_actor, required_authority
            ) VALUES (
                :id, :w, :b, :k, :hash, CAST('{}' AS jsonb), 'human', 'human'
            )
            """
        ),
        {
            "id": proposal_id,
            "w": workspace_id,
            "b": brand,
            "k": field_key,
            "hash": f"{abs(hash(field_key)):064x}"[:64],
        },
    )
    await conn.execute(
        text(
            """
            INSERT INTO workspace_field_definition (
                workspace_id, field_key, value_type, tier_plan, pass_kind, reuse_scope,
                field_class, description, pack, client_kb_role, active, definition_version,
                promoted_from_proposal_id, promotion_policy_version, promoted_by, presentation
            ) VALUES (
                :w, :k, 'str', CAST('[]' AS jsonb), CAST('deep' AS field_pass),
                CAST('tenant_private' AS reuse_scope), CAST('pack' AS field_class), :d,
                'client', 'extended', TRUE, 1, :p, 'test', 'tester', :pres
            )
            """
        ),
        {
            "w": workspace_id,
            "k": field_key,
            "d": description,
            "p": proposal_id,
            "pres": presentation,
        },
    )


async def _write_claim(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    entity_id: EntityId,
    entity_type: EntityType,
    field_key: str,
    value_json: Any,
    **overrides: Any,
) -> str:
    receipt = await LenientClaimWriter(lenient=True).write(
        conn,
        ClaimDraft(
            entity_id=entity_id,
            entity_type=entity_type,
            field_key=field_key,
            value_json=value_json,
            extraction_method=overrides.pop("extraction_method", ExtractionMethod.SCRAPE),
            run_id=new_run_id(),
            research_mode=ResearchMode.ACCOUNT_PROFILING,
            workspace_id=workspace_id,
            source_url=overrides.pop("source_url", "https://zafran.io/newsroom"),
            **overrides,
        ),
    )
    return str(receipt.claim_id)


async def _base(conn: AsyncConnection, workspace_id: str = _WS) -> str:
    ws = await seed_workspace(conn, workspace_id)
    await load_core_pack(conn)
    await load_arv2_pack(conn)
    return ws


@pytest_db
def test_owners_resolve_display_name_then_first_last_then_the_id() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await _base(conn)
            await _seed_user(conn, "u_named", display_name="Ada Lovelace")
            await _seed_user(conn, "u_parts", first_name="Grace", last_name="Hopper")
            await _seed_user(conn, "u_bare")

            owners = await owners_for(conn, user_ids=["u_named", "u_parts", "u_bare", "u_absent"])

            assert owners["u_named"] == AccountOwner(id="u_named", name="Ada Lovelace")
            assert owners["u_parts"] == AccountOwner(id="u_parts", name="Grace Hopper")
            assert owners["u_bare"] == AccountOwner(id="u_bare", name="u_bare")
            assert "u_absent" not in owners
            assert await owners_for(conn, user_ids=[]) == {}

    run_async(scenario())


@pytest_db
def test_custom_fields_are_the_client_pack_registry_rows_the_account_holds() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = await _base(conn)
            account = await insert_account_entity(
                conn, canonical_name="Zafran", primary_domain="zafran.io", workspace_id=ws
            )
            other = await insert_account_entity(
                conn, canonical_name="Acme", primary_domain="acme.test", workspace_id=ws
            )
            keys = [f"client.custom_{i}" for i in range(6)]
            for index, key in enumerate(keys):
                await _seed_workspace_field(
                    conn,
                    workspace_id=ws,
                    field_key=key,
                    description=None if index == 5 else f"Custom {index}",
                    presentation="badge" if index == 1 else "text",
                )
            # A registry row this account holds no claim for: it must not appear at all.
            await _seed_workspace_field(
                conn, workspace_id=ws, field_key="client.unheld", description="Unheld"
            )
            # A retired row: retirement is how a workspace field stops being active (the table's
            # own CHECK forbids active = false), so this is the "inactive" case.
            await _seed_workspace_field(
                conn, workspace_id=ws, field_key="client.retired", description="Retired"
            )

            for key in keys:
                await _write_claim(
                    conn,
                    workspace_id=ws,
                    entity_id=account,
                    entity_type=EntityType.ACCOUNT,
                    field_key=key,
                    value_json=f"value of {key}",
                )
            await _write_claim(
                conn,
                workspace_id=ws,
                entity_id=account,
                entity_type=EntityType.ACCOUNT,
                field_key="client.retired",
                value_json="retired value",
            )
            await _write_claim(
                conn,
                workspace_id=ws,
                entity_id=other,
                entity_type=EntityType.ACCOUNT,
                field_key=keys[0],
                value_json="acme value",
            )

            await conn.execute(
                text(
                    "INSERT INTO workspace_field_retirement (workspace_id, field_key, "
                    "retired_by, reason) VALUES (:w, 'client.retired', 'tester', 'test')"
                ),
                {"w": ws},
            )

            fields = await custom_fields_for(conn, workspace_id=ws, account_ids=[account, other])

            served = fields[account]
            assert [f.id for f in served] == keys
            assert served[0] == AccountCustomField(
                id="client.custom_0",
                claim_id=served[0].claim_id,
                label="Custom 0",
                value="value of client.custom_0",
                presentation="text",
                primary=True,
            )
            assert served[0].claim_id is not None
            assert served[1].presentation == "badge"
            assert [f.primary for f in served] == [True, True, True, True, False, False]
            # A description-less row labels itself with its key rather than an empty string.
            assert served[5].label == "client.custom_5"
            assert [f.id for f in fields[other]] == [keys[0]]

    run_async(scenario())


@pytest_db
def test_a_superseded_custom_field_claim_is_replaced_by_the_latest_live_one() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = await _base(conn)
            account = await insert_account_entity(
                conn, canonical_name="Zafran", primary_domain="zafran.io", workspace_id=ws
            )
            await _seed_workspace_field(
                conn, workspace_id=ws, field_key="client.segment", description="Segment"
            )
            old = await _write_claim(
                conn,
                workspace_id=ws,
                entity_id=account,
                entity_type=EntityType.ACCOUNT,
                field_key="client.segment",
                value_json="Mid-market",
            )
            new = await _write_claim(
                conn,
                workspace_id=ws,
                entity_id=account,
                entity_type=EntityType.ACCOUNT,
                field_key="client.segment",
                value_json="Enterprise",
            )
            await conn.execute(
                text("UPDATE claim SET superseded_by = :new WHERE id = :old"),
                {"new": uuid.UUID(new), "old": uuid.UUID(old)},
            )

            fields = await custom_fields_for(conn, workspace_id=ws, account_ids=[account])
            assert [f.value for f in fields[account]] == ["Enterprise"]

    run_async(scenario())


@pytest_db
def test_last_modified_is_the_max_of_the_entity_the_claims_and_the_display_blocks() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = await _base(conn)
            quiet = await insert_account_entity(
                conn, canonical_name="Quiet", primary_domain="quiet.test", workspace_id=ws
            )
            claimy = await insert_account_entity(
                conn, canonical_name="Claimy", primary_domain="claimy.test", workspace_id=ws
            )
            blocky = await insert_account_entity(
                conn, canonical_name="Blocky", primary_domain="blocky.test", workspace_id=ws
            )
            entity_stamp = datetime(2026, 1, 1, tzinfo=UTC)
            await conn.execute(
                text("UPDATE account_entity SET updated_at = :t WHERE id IN :ids").bindparams(
                    bindparam("ids", expanding=True)
                ),
                {"t": entity_stamp, "ids": [quiet, claimy, blocky]},
            )

            # ``claim.collected_at`` is immutable (the append-only trigger), so the claim's stamp
            # is whatever the writer wrote: it is read back rather than dictated.
            claim_id = await _write_claim(
                conn,
                workspace_id=ws,
                entity_id=claimy,
                entity_type=EntityType.ACCOUNT,
                field_key="core.industry",
                value_json="Cybersecurity",
            )
            claim_stamp = (
                await conn.execute(
                    text("SELECT collected_at FROM claim WHERE id = :id"),
                    {"id": uuid.UUID(claim_id)},
                )
            ).scalar_one()

            # ``blocky`` carries a claim *and* a later block, so the block has to win on its own
            # merits rather than by being the only source present.
            await _write_claim(
                conn,
                workspace_id=ws,
                entity_id=blocky,
                entity_type=EntityType.ACCOUNT,
                field_key="core.industry",
                value_json="Cybersecurity",
            )
            block_stamp = claim_stamp + timedelta(days=30)
            await conn.execute(
                text(
                    """
                    INSERT INTO display_block (
                        workspace_id, subject_kind, subject_id, page, section_key, body_json,
                        cited_claim_ids, model, prompt_version, recipe_version, generated_at
                    ) VALUES (
                        :w, 'account', :s, 'overview', 'summary', CAST('{}' AS jsonb),
                        CAST(ARRAY[]::uuid[] AS uuid[]), 'm', 'p', 1, :t
                    )
                    """
                ),
                {"w": ws, "s": blocky, "t": block_stamp},
            )
            # A superseded block never counts, however recent it is.
            await conn.execute(
                text(
                    """
                    INSERT INTO display_block (
                        workspace_id, subject_kind, subject_id, page, section_key, body_json,
                        cited_claim_ids, model, prompt_version, recipe_version, generated_at,
                        superseded_at
                    ) VALUES (
                        :w, 'account', :s, 'insights', 'signals', CAST('{}' AS jsonb),
                        CAST(ARRAY[]::uuid[] AS uuid[]), 'm', 'p', 1, :t, :t
                    )
                    """
                ),
                {"w": ws, "s": quiet, "t": block_stamp + timedelta(days=1)},
            )

            stamps = await last_modified_for(
                conn, workspace_id=ws, account_ids=[quiet, claimy, blocky]
            )
            assert stamps[quiet] == entity_stamp
            assert stamps[claimy] == claim_stamp
            assert stamps[blocky] == block_stamp

    run_async(scenario())


@pytest_db
def test_contact_last_modified_falls_back_to_the_entity_stamp() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = await _base(conn)
            account = await insert_account_entity(
                conn, canonical_name="Zafran", primary_domain="zafran.io", workspace_id=ws
            )
            silent = await insert_contact_entity(
                conn, account_entity_id=account, full_name="Nobody Withoutclaims"
            )
            noisy = await insert_contact_entity(
                conn, account_entity_id=account, full_name="Nick Fisher"
            )
            updated = datetime(2026, 2, 2, tzinfo=UTC)
            claim_id = await _write_claim(
                conn,
                workspace_id=ws,
                entity_id=noisy,
                entity_type=EntityType.CONTACT,
                field_key="contact.current_title",
                value_json="VP of Marketing",
            )
            claim_stamp = (
                await conn.execute(
                    text("SELECT collected_at FROM claim WHERE id = :id"),
                    {"id": uuid.UUID(claim_id)},
                )
            ).scalar_one()

            assert (
                await contact_last_modified(conn, contact_id=silent, updated_at=updated) == updated
            )
            assert (
                await contact_last_modified(conn, contact_id=noisy, updated_at=updated)
                == claim_stamp
            )

    run_async(scenario())


@pytest_db
def test_activity_is_newest_first_with_clue_and_person_actors() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = await _base(conn)
            await _base(conn, _OTHER_WS)
            account = await insert_account_entity(
                conn, canonical_name="Zafran", primary_domain="zafran.io", workspace_id=ws
            )
            elsewhere = await insert_account_entity(
                conn,
                canonical_name="Zafran",
                primary_domain="zafran.io",
                workspace_id=_OTHER_WS,
            )
            await _seed_user(conn, "u_owner", display_name="Ada Lovelace")

            async def event(
                kind: str,
                body: str,
                *,
                when: datetime,
                actor_kind: str = "clue",
                actor: str | None = None,
                action: str | None = None,
                subject: EntityId = account,
                workspace_id: str = _WS,
            ) -> None:
                await conn.execute(
                    text(
                        "INSERT INTO account_activity_event (workspace_id, account_entity_id, "
                        "kind, actor_kind, actor_user_id, text, action, occurred_at) VALUES "
                        "(:w, :a, :k, :ak, :au, :t, :ac, :o)"
                    ),
                    {
                        "w": workspace_id,
                        "a": subject,
                        "k": kind,
                        "ak": actor_kind,
                        "au": actor,
                        "t": body,
                        "ac": action,
                        "o": when,
                    },
                )

            await event("created", "Account created", when=_NOW - timedelta(days=9))
            await event(
                "summary",
                "Summary refreshed",
                when=_NOW - timedelta(hours=3),
                action="View summary",
            )
            await event(
                "contacts",
                "Owner assigned",
                when=_NOW - timedelta(minutes=10),
                actor_kind="person",
                actor="u_owner",
            )
            await event(
                "updated",
                "Somebody else's account",
                when=_NOW,
                subject=elsewhere,
                workspace_id=_OTHER_WS,
            )

            rows = await activity_for(conn, workspace_id=ws, account_id=account, now=_NOW)

            assert [row.text for row in rows] == [
                "Owner assigned",
                "Summary refreshed",
                "Account created",
            ]
            assert rows[0].actor == PersonActor(type="person", id="u_owner", name="Ada Lovelace")
            assert rows[0].time_label == "10 minutes ago"
            assert rows[0].action is None
            assert rows[1].actor == ClueActor(type="clue")
            assert rows[1].action == "View summary"
            assert rows[1].time_label == "3 hours ago"
            assert rows[2].kind == "created"
            assert rows[2].occurred_at is not None
            assert rows[2].occurred_at.startswith("2026-08-30T")
            # The v1 dialect, not ``isoformat()``'s ``+00:00`` tail: Zod's ``datetime()`` rejects
            # an offset unless the schema opts in, and the vendored schemas do not.
            assert rows[2].occurred_at.endswith("Z")
            assert uuid.UUID(rows[0].id)

    run_async(scenario())


@pytest_db
def test_activity_honours_its_limit() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = await _base(conn)
            account = await insert_account_entity(
                conn, canonical_name="Zafran", primary_domain="zafran.io", workspace_id=ws
            )
            for index in range(5):
                await conn.execute(
                    text(
                        "INSERT INTO account_activity_event (workspace_id, account_entity_id, "
                        "kind, actor_kind, text, occurred_at) VALUES "
                        "(:w, :a, 'updated', 'clue', :t, :o)"
                    ),
                    {
                        "w": ws,
                        "a": account,
                        "t": f"event {index}",
                        "o": _NOW - timedelta(minutes=index),
                    },
                )

            rows = await activity_for(conn, workspace_id=ws, account_id=account, limit=2, now=_NOW)
            assert [row.text for row in rows] == ["event 0", "event 1"]

    run_async(scenario())


@pytest_db
def test_research_evidence_maps_the_provider_and_drops_an_unsafe_source_url() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            ws = await _base(conn)
            account = await insert_account_entity(
                conn, canonical_name="Zafran", primary_domain="zafran.io", workspace_id=ws
            )
            good = await _write_claim(
                conn,
                workspace_id=ws,
                entity_id=account,
                entity_type=EntityType.ACCOUNT,
                field_key="core.industry",
                value_json="Cybersecurity",
                source_key="exa_contents",
                source_url="https://zafran.io/about",
                evidence_span="Zafran is a cybersecurity company.",
            )
            # A credentialed URL: a legal ``HttpUrl`` on the wire, which is exactly why the read
            # layer has to refuse it rather than trusting the contract's type to.
            unsafe = await _write_claim(
                conn,
                workspace_id=ws,
                entity_id=account,
                entity_type=EntityType.ACCOUNT,
                field_key="core.employee_count",
                value_json=400,
                source_key="firecrawl",
                source_url="https://scraper:hunter2@zafran.io/team",
                evidence_span="400 people.",
            )

            refs = await research_evidence_for(conn, workspace_id=ws, claim_ids=[good, unsafe])
            by_id = {ref.claim_id: ref for ref in refs}

            assert by_id[good].provider == "Exa"
            assert by_id[good].source_url == "https://zafran.io/about"
            assert by_id[good].quote == "Zafran is a cybersecurity company."
            assert by_id[unsafe].provider == "firecrawl"
            assert by_id[unsafe].source_url is None
            assert [ref.claim_id for ref in refs] == sorted(by_id)
            assert await research_evidence_for(conn, workspace_id=ws, claim_ids=[]) == []

    run_async(scenario())


# --- research status ------------------------------------------------------------------------------


async def _researched(
    conn: AsyncConnection, workspace_id: str = _WS
) -> tuple[Project, dict[str, EntityId]]:
    """A project and five accounts, one per R2 job status, plus one that was never researched."""
    await _base(conn, workspace_id)
    project = await seed_project(conn, workspace_id, name="Research project")
    accounts = {
        name: await insert_account_entity(
            conn, canonical_name=name, primary_domain=f"{name}.test", workspace_id=workspace_id
        )
        for name in ("queued", "running", "flagged", "done", "paused", "untouched")
    }
    planted: tuple[tuple[str, JobStatus], ...] = (
        ("queued", "not_started"),
        ("running", "in_progress"),
        ("flagged", "needs_review"),
        ("done", "completed"),
        ("paused", "suspended"),
    )
    for name, status in planted:
        await seed_arv2_job(conn, project=project, account_id=accounts[name], status=status)
    return project, accounts


@pytest_db
def test_every_arv2_job_status_is_served_verbatim_and_no_job_is_absent() -> None:
    """The five states come back unmapped, and an account with no job does not appear at all —
    the callers spell "never researched" once, at the row."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            _project, accounts = await _researched(conn)

            served = await arv2_research_status_for(
                conn, workspace_id=_WS, account_ids=list(accounts.values())
            )

            assert served[accounts["queued"]] == ("not_started", False)
            assert served[accounts["running"]] == ("in_progress", False)
            assert served[accounts["flagged"]] == ("needs_review", False)
            assert served[accounts["done"]] == ("completed", False)
            assert served[accounts["paused"]] == ("suspended", False)
            assert accounts["untouched"] not in served

    run_async(scenario())


@pytest_db
def test_a_job_newer_than_a_completed_one_is_a_refresh() -> None:
    """``refreshing`` is "researched, and being re-researched right now": a non-terminal job newer
    than a ``completed`` one. The status itself is the newer job's."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            await _base(conn)
            project = await seed_project(conn, _WS, name="Research project")
            account = await insert_account_entity(
                conn, canonical_name="Zafran", primary_domain="zafran.io", workspace_id=_WS
            )
            await seed_arv2_job(
                conn,
                project=project,
                account_id=account,
                status="completed",
                created_at=_NOW - timedelta(hours=1),
            )
            await seed_arv2_job(
                conn, project=project, account_id=account, status="in_progress", created_at=_NOW
            )

            served = await arv2_research_status_for(conn, workspace_id=_WS, account_ids=[account])
            assert served[account] == ("in_progress", True)

    run_async(scenario())


@pytest_db
def test_a_completed_job_after_an_older_in_flight_one_is_not_a_refresh() -> None:
    """The reverse order: the finished job is the latest, so the account is researched and still,
    not refreshing. A stale in-flight row older than the result must not light the spinner."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            await _base(conn)
            project = await seed_project(conn, _WS, name="Research project")
            account = await insert_account_entity(
                conn, canonical_name="Zafran", primary_domain="zafran.io", workspace_id=_WS
            )
            await seed_arv2_job(
                conn,
                project=project,
                account_id=account,
                status="in_progress",
                created_at=_NOW - timedelta(hours=1),
            )
            await seed_arv2_job(
                conn, project=project, account_id=account, status="completed", created_at=_NOW
            )

            served = await arv2_research_status_for(conn, workspace_id=_WS, account_ids=[account])
            assert served[account] == ("completed", False)

    run_async(scenario())


@pytest_db
def test_a_person_job_newer_than_the_completed_account_job_leaves_the_account_researched() -> None:
    """R3's person jobs share the table and the account column. Zafran's account job finished and
    fanned four committee members out into person jobs that are queued and newer; the account is
    researched, not ``not_started``, and not refreshing — a person being researched is not the
    account being re-researched."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            await _base(conn)
            project = await seed_project(conn, _WS, name="Research project")
            account = await insert_account_entity(
                conn, canonical_name="Zafran", primary_domain="zafran.io", workspace_id=_WS
            )
            account_job = await seed_arv2_job(
                conn,
                project=project,
                account_id=account,
                status="completed",
                created_at=_NOW - timedelta(hours=1),
            )
            run_id = (
                await conn.execute(
                    text("SELECT run_id FROM arv2_research_job WHERE job_id = :job_id"),
                    {"job_id": account_job},
                )
            ).scalar_one()
            member = await insert_contact_entity(
                conn, account_entity_id=account, full_name="Nick Fisher"
            )
            assert await create_job(
                conn,
                job_id=uuid.uuid4(),
                run_id=run_id,
                workspace_id=_WS,
                account_entity_id=account,
                subject_type="person",
                subject_entity_id=uuid.UUID(str(member)),
            )
            await conn.execute(
                text(
                    "UPDATE arv2_research_job SET created_at = :now "
                    "WHERE run_id = :run_id AND subject_type = 'person'"
                ),
                {"now": _NOW, "run_id": run_id},
            )

            served = await arv2_research_status_for(conn, workspace_id=_WS, account_ids=[account])
            assert served[account] == ("completed", False)

    run_async(scenario())


@pytest_db
def test_another_workspaces_job_is_never_served() -> None:
    """The job row carries its own ``workspace_id`` and the read is scoped by it — which is why the
    helper needs no join to ``arv2_research_run`` to stay tenant-safe.

    This is the *only* place the cross-tenant case can be put: ``arv2_research_job``'s composite FK
    pins ``(account_entity_id, workspace_id)`` to ``account_entity``, so another workspace's job is
    necessarily another workspace's account — which the endpoints' own page scan never lists.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            await _base(conn)
            await _base(conn, _OTHER_WS)
            project = await seed_project(conn, _OTHER_WS, name="Their project")
            theirs = await insert_account_entity(
                conn, canonical_name="Theirs", primary_domain="theirs.test", workspace_id=_OTHER_WS
            )
            await seed_arv2_job(conn, project=project, account_id=theirs, status="completed")

            assert (
                await arv2_research_status_for(conn, workspace_id=_WS, account_ids=[theirs]) == {}
            )
            assert await arv2_research_status_for(
                conn, workspace_id=_OTHER_WS, account_ids=[theirs]
            ) == {theirs: ("completed", False)}

    run_async(scenario())


@pytest_db
def test_the_whole_page_costs_two_batched_statements() -> None:
    """N accounts: one job read and one delivery read, never a lookup per account, which is
    the defect the endpoints' own statement-count guards exist to catch."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            _project, accounts = await _researched(conn)
            statements = 0

            def count(*_args: object) -> None:
                nonlocal statements
                statements += 1

            event.listen(conn.sync_connection, "before_cursor_execute", count)
            try:
                served = await arv2_research_status_for(
                    conn, workspace_id=_WS, account_ids=list(accounts.values())
                )
            finally:
                event.remove(conn.sync_connection, "before_cursor_execute", count)

            assert len(served) == 5, "the six accounts really were read"
            assert statements == 2

    run_async(scenario())


@pytest_db
def test_an_empty_page_reads_nothing_at_all() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await _base(conn)
            assert await arv2_research_status_for(conn, workspace_id=_WS, account_ids=[]) == {}

    run_async(scenario())
