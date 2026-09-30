"""The checks code makes on a verifier answer, and the arithmetic the model got wrong (spec §3).

What is left after the founder ruling of 2026-10-01 removed the quote-on-page and right-company
guards: a 2023 round the model called "within 24 months" is code's to fail, "no source found"
answered as `fail` is `unclear`, and an answer that is not one is `malformed`.

Everything here is offline: an Answer payload goes in, a verdict comes out. No provider, no
database.
"""

from __future__ import annotations

from datetime import date

from clue_api.arv2.discovery_brief import Gate
from clue_api.arv2.discovery_verifier import (
    MAIN_BUSINESS_CLAUSE,
    GateVerdict,
    apply_guards,
    disposition,
    fit_score,
    gate_question,
    system_prompt,
    website_question,
)

STAGE = Gate(
    key="stage",
    rule="most recent round is a Series A within 24 months",
    test="A dated announcement…",
    window_months=24,
)
TODAY = date(2026, 9, 10)


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
        today=TODAY,
    )
    assert (v.verdict, v.guard, v.model_verdict) == ("pass", "ok", "pass")


def test_a_sourced_verdict_is_kept_whatever_page_it_cites() -> None:
    """Founder ruling 2026-10-01: no quote-on-page or right-company check. A sourced pass on a
    page about a renamed company, a job board or a news article is the model's verdict, kept."""
    answer = {
        "verdict": "pass",
        "reasoning": "r",
        "evidence_quote": "Guest Experience Manager, San Antonio",
        "evidence_url": "https://jobboard.example/jobs/1",
        "evidence_date": "2026-09-01",
    }
    v = apply_guards(gate=Gate("guest_experience", "…", "…", None), answer=answer, today=TODAY)
    assert (v.verdict, v.guard, v.model_verdict) == ("pass", "ok", "pass")


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
        today=TODAY,
    )
    assert (absent.verdict, absent.guard) == ("unclear", "no_source")
    assert (
        apply_guards(
            gate=STAGE,
            answer="not json",
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


def test_an_exclusion_gate_asks_about_the_main_business_and_no_other_gate_does() -> None:
    plain = gate_question("Avoca", "https://avoca.ai", STAGE)
    assert "main business" not in plain
    exclusion = Gate(
        "sells_product", "The company sells X.", "Its site sells X.", None, main_business=True
    )
    q = gate_question("Avoca", "https://avoca.ai", exclusion)
    assert MAIN_BUSINESS_CLAUSE in q and exclusion.rule in q and exclusion.test in q
    # The clause sits before the closing instruction, so the question still ends the same way.
    assert q.endswith("citing the freshest relevant source.")


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
    v = apply_guards(
        gate=STAGE,
        answer=answer,
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
    v = apply_guards(
        gate=STAGE,
        answer=answer,
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
        today=TODAY,
    )
    assert (v.verdict, v.guard, v.model_verdict) == ("unclear", "ok", "unclear")


def test_a_verdict_word_the_schema_does_not_allow_is_malformed() -> None:
    v = apply_guards(
        gate=STAGE,
        answer={"verdict": "maybe", "reasoning": "r", "evidence_quote": "q"},
        today=TODAY,
    )
    assert (v.verdict, v.guard, v.model_verdict) == ("unclear", "malformed", "maybe")


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
