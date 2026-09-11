"""The three guards, and the arithmetic the model got wrong (spec §3).

Every case below is one of the errors the proof-of-concept run actually produced: a quote the
cited page does not contain, a job posting from a same-name company on another domain (INFI →
infinIT), a 2023 round the model called "within 24 months", and "no source found" answered as
`fail` instead of `unclear`. The guards exist for those four and nothing else, so these tests are
the guards' whole specification.

Everything here is offline: an Answer payload and its citations go in, a guarded verdict comes
out. No provider, no database.
"""

from __future__ import annotations

from datetime import date

from clue_api.arv2.discovery_brief import Gate
from clue_api.arv2.discovery_verifier import (
    GateVerdict,
    apply_guards,
    disposition,
    fit_score,
    gate_question,
    normalise,
    system_prompt,
    website_question,
)
from clue_api.arv2.exa_client import ExaCitation

STAGE = Gate(
    key="stage",
    rule="most recent round is a Series A within 24 months",
    test="A dated announcement…",
    window_months=24,
)
TODAY = date(2026, 9, 10)


def _cit(url: str, text: str, date_: str | None) -> ExaCitation:
    return ExaCitation(url=url, title=None, published_date=date_, text=text)


def test_a_grounded_pass_keeps_its_verdict_and_quote() -> None:
    answer = {
        "verdict": "pass",
        "reasoning": "r",
        "evidence_quote": "Probook Raises $40M in Seed and Series A Financing",
        "evidence_url": "https://finsmes.com/x",
        "evidence_date": "2026-06-23",
    }
    v = apply_guards(
        gate=STAGE,
        answer=answer,
        citations=[
            _cit(
                "https://finsmes.com/x",
                "FinSMEs: Probook Raises $40M in Seed and Series A Financing today",
                "2026-06-23",
            )
        ],
        company_domain="probook.ai",
        company_name="Probook",
        today=TODAY,
    )
    assert (v.verdict, v.guard, v.model_verdict) == ("pass", "ok", "pass")


def test_a_quote_not_on_the_cited_page_becomes_unclear() -> None:
    answer = {
        "verdict": "fail",
        "reasoning": "r",
        "evidence_quote": "closed a $2.8M seed round",
        "evidence_url": "https://signalbase.com/p",
        "evidence_date": "2026-04-28",
    }
    v = apply_guards(
        gate=STAGE,
        answer=answer,
        citations=[_cit("https://signalbase.com/p", "unrelated text about dentists", "2026-04-28")],
        company_domain="patientdesk.ai",
        company_name="Patientdesk",
        today=TODAY,
    )
    assert (v.verdict, v.guard) == ("unclear", "quote_not_on_page")


def test_a_page_about_another_company_on_another_domain_becomes_unclear() -> None:
    answer = {
        "verdict": "pass",
        "reasoning": "r",
        "evidence_quote": "As an Account Executive at infinIT, you will prospect",
        "evidence_url": "https://jobera.com/infinit",
        "evidence_date": "2026-04-03",
    }
    v = apply_guards(
        gate=Gate("intent", "…", "…", None),
        answer=answer,
        citations=[
            _cit(
                "https://jobera.com/infinit",
                "As an Account Executive at infinIT, you will prospect daily",
                None,
            )
        ],
        company_domain="infi.us",
        company_name="INFI",
        today=TODAY,
    )
    assert (v.verdict, v.guard) == ("unclear", "wrong_company")


def test_a_news_page_that_names_the_company_is_accepted_off_domain() -> None:
    answer = {
        "verdict": "pass",
        "reasoning": "r",
        "evidence_quote": "Lassie raised $35 million in Series A financing",
        "evidence_url": "https://businesswire.com/l",
        "evidence_date": "2026-06-03",
    }
    v = apply_guards(
        gate=STAGE,
        answer=answer,
        citations=[
            _cit(
                "https://businesswire.com/l",
                "SAN FRANCISCO — Lassie raised $35 million in Series A financing led by a16z",
                "2026-06-03",
            )
        ],
        company_domain="lassie.ai",
        company_name="Lassie",
        today=TODAY,
    )
    assert (v.verdict, v.guard) == ("pass", "ok")


def test_arithmetic_is_codes_a_pass_outside_the_window_fails() -> None:
    answer = {
        "verdict": "pass",
        "reasoning": "within 24 months",
        "evidence_quote": "Superorder today announced that it raised $10 million",
        "evidence_url": "https://techcrunch.com/s",
        "evidence_date": "2023-09-15",
    }
    v = apply_guards(
        gate=STAGE,
        answer=answer,
        citations=[
            _cit(
                "https://techcrunch.com/s",
                "Superorder today announced that it raised $10 million in a Series A",
                "2023-09-15",
            )
        ],
        company_domain="superorder.com",
        company_name="Superorder",
        today=TODAY,
    )
    assert (v.verdict, v.guard) == ("fail", "outside_window")


def test_no_source_is_unclear_never_fail_and_malformed_is_unclear() -> None:
    absent = apply_guards(
        gate=STAGE,
        answer={
            "verdict": "fail",
            "reasoning": "no roles found",
            "evidence_quote": "",
            "evidence_url": "",
            "evidence_date": "",
        },
        citations=[],
        company_domain="x.com",
        company_name="X",
        today=TODAY,
    )
    assert (absent.verdict, absent.guard) == ("unclear", "no_source")
    assert (
        apply_guards(
            gate=STAGE,
            answer="not json",
            citations=[],
            company_domain="x.com",
            company_name="X",
            today=TODAY,
        ).guard
        == "malformed"
    )


def test_fit_and_disposition_follow_the_spec_table() -> None:
    def v(verdict: str) -> GateVerdict:
        return GateVerdict("g", verdict, "", "", "", "", "ok", verdict)

    assert fit_score([v("pass")] * 4) == 1.0 and disposition([v("pass")] * 4) == "pass"
    assert (
        fit_score([v("pass")] * 3 + [v("unclear")]) == 0.875
        and disposition([v("pass")] * 3 + [v("unclear")]) == "unclear"
    )
    assert (
        fit_score([v("pass"), v("pass"), v("fail"), v("fail")]) == 0.5
        and disposition([v("pass"), v("pass"), v("fail"), v("fail")]) == "partial"
    )
    assert (
        fit_score([v("pass"), v("fail"), v("fail"), v("fail")]) == 0.25
        and disposition([v("pass"), v("fail"), v("fail"), v("fail")]) == "partial"
    )


def test_the_question_is_the_gates_own_words() -> None:
    q = gate_question("Avoca", "https://avoca.ai", STAGE)
    assert "Company: Avoca (website https://avoca.ai)" in q and STAGE.rule in q and STAGE.test in q
    assert "freshest" in system_prompt(TODAY) and "2026-09-10" in system_prompt(TODAY)


# -- the rest of the surface the driver uses ----------------------------------------------------


def test_an_unparseable_date_leaves_the_verdict_alone() -> None:
    """A window plus a date code cannot read is not a reason to overturn a grounded verdict."""
    answer = {
        "verdict": "pass",
        "reasoning": "r",
        "evidence_quote": "Lassie raised $35 million in Series A financing",
        "evidence_url": "https://businesswire.com/l",
        "evidence_date": "summer 2026",
    }
    citations = [
        _cit("https://businesswire.com/l", "Lassie raised $35 million in Series A financing", None)
    ]
    v = apply_guards(
        gate=STAGE,
        answer=answer,
        citations=citations,
        company_domain="lassie.ai",
        company_name="Lassie",
        today=TODAY,
    )
    assert (v.verdict, v.guard) == ("pass", "ok")


def test_a_year_and_month_date_is_read_as_the_first_of_that_month() -> None:
    answer = {
        "verdict": "pass",
        "reasoning": "r",
        "evidence_quote": "Lassie raised $35 million in Series A financing",
        "evidence_url": "https://lassie.ai/news",
        "evidence_date": "2024-09",
    }
    citations = [
        _cit("https://lassie.ai/news", "Lassie raised $35 million in Series A financing", None)
    ]
    v = apply_guards(
        gate=STAGE,
        answer=answer,
        citations=citations,
        company_domain="lassie.ai",
        company_name="Lassie",
        today=TODAY,
    )
    assert (v.verdict, v.guard) == ("pass", "ok")  # 2024-09 → 24 months, inside the window


def test_the_models_unclear_survives_with_no_source_at_all() -> None:
    v = apply_guards(
        gate=STAGE,
        answer={
            "verdict": "unclear",
            "reasoning": "nothing dated",
            "evidence_quote": "",
            "evidence_url": "",
            "evidence_date": "",
        },
        citations=[],
        company_domain="x.com",
        company_name="X",
        today=TODAY,
    )
    assert (v.verdict, v.guard, v.model_verdict) == ("unclear", "ok", "unclear")


def test_a_verdict_word_the_schema_does_not_allow_is_malformed() -> None:
    v = apply_guards(
        gate=STAGE,
        answer={"verdict": "maybe", "reasoning": "r", "evidence_quote": "q"},
        citations=[],
        company_domain="x.com",
        company_name="X",
        today=TODAY,
    )
    assert (v.verdict, v.guard, v.model_verdict) == ("unclear", "malformed", "maybe")


def test_normalise_folds_typography_case_and_punctuation() -> None:
    assert normalise("  Probook’s  “Series A” — $40M\n raised ") == (
        "probook's series a - 40m raised"
    )


def test_a_verdict_serialises_every_field_the_candidate_row_stores() -> None:
    v = GateVerdict(
        "stage", "fail", "why", "quote", "https://u", "2023-09-15", "outside_window", "pass"
    )
    assert v.as_json() == {
        "gate_key": "stage",
        "verdict": "fail",
        "reasoning": "why",
        "evidence_quote": "quote",
        "evidence_url": "https://u",
        "evidence_date": "2023-09-15",
        "guard": "outside_window",
        "model_verdict": "pass",
    }


def test_the_website_question_asks_for_the_domain_the_company_itself_names() -> None:
    q = website_question("Probook", "https://probook.com")
    assert "Probook" in q and "https://probook.com" in q and "domain" in q


def test_an_empty_verdict_set_scores_nothing_and_says_unclear() -> None:
    assert fit_score([]) == 0.0 and disposition([]) == "unclear"
