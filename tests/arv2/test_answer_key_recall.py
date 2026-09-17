"""The answer-key recall measurement, graded offline against hand-written pairs.

These tests pin the grading rules themselves — what counts as an exact hit, what counts as a
partial one, and what a key the run never wrote looks like in the report. The measurement is only
worth its baseline if the rules cannot drift underneath it.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from pydantic import JsonValue

from clue_api.arv2.answer_key_recall import (
    KeyClaim,
    as_number,
    leaf_values,
    match_claims,
    normalise_value,
    person_report,
    probook_keys,
    values_agree,
)
from clue_core import (
    Claim,
    EntityId,
    EntityType,
    ExtractionMethod,
    IdentityBinding,
    ResearchMode,
    ReuseScope,
    RunId,
    UseClass,
)

REPO = Path(__file__).resolve().parents[2]
ACCOUNT_ID = EntityId(UUID("11111111-1111-4111-8111-111111111111"))
CONTACT_ID = EntityId(UUID("33333333-3333-4333-8333-333333333333"))
RUN_ID = RunId(UUID("22222222-2222-4222-8222-222222222222"))


def _claim(field_key: str, value: object) -> Claim:
    return Claim(
        entity_id=ACCOUNT_ID,
        entity_type=EntityType.ACCOUNT,
        field_key=field_key,
        value_json=value,  # type: ignore[arg-type]
        source_tier=4,
        extraction_method=ExtractionMethod.LLM_SYNTHESIS,
        run_id=RUN_ID,
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        confidence=0.6,
        reuse_scope=ReuseScope.TENANT_PRIVATE,
        workspace_id="ws_arv2_answer_key",
    )


def _contact_claim(
    field_key: str, value: object, *, markers: dict[str, JsonValue] | None = None
) -> Claim:
    """One claim a person job wrote — personal provenance is mandatory on a facet field."""
    return Claim(
        entity_id=CONTACT_ID,
        entity_type=EntityType.CONTACT,
        field_key=field_key,
        value_json=value,  # type: ignore[arg-type]
        source_tier=4,
        extraction_method=ExtractionMethod.LLM_SYNTHESIS,
        run_id=RUN_ID,
        research_mode=ResearchMode.CONTACT_PROFILING,
        confidence=0.6,
        reuse_scope=ReuseScope.TENANT_PRIVATE,
        workspace_id="ws_arv2_answer_key",
        identity_binding=IdentityBinding.STRONG,
        use_class=UseClass.PROFESSIONAL_PUBLIC,
        write_markers=markers,
    )


def test_values_agree_exact_partial_and_no() -> None:
    assert values_agree("Zafran Security", "Zafran Security") == "exact"
    assert values_agree("New York", {"city": "New York", "state": "NY"}) == "exact"
    assert values_agree(60_000_000, 60000000.0) == "exact"
    assert values_agree(60_000_000, 63_000_000) == "partial"
    assert (
        values_agree(
            "Series C led by Menlo Ventures, $60M, Dec 2025", "$60M Series C, Menlo Ventures"
        )
        == "partial"
    )
    assert values_agree("HubSpot", "Salesforce") == "no"


def test_normalise_value_folds_case_urls_and_shape() -> None:
    assert normalise_value("  Zafran   Security,  Inc. ") == "zafran security inc."
    assert normalise_value("https://www.zafran.io/platform") == "zafran.io platform"
    assert normalise_value({"b": 2, "a": "New York"}) == "a new york b 2"


def test_leaf_values_drops_key_names_and_keeps_every_scalar() -> None:
    assert leaf_values({"b": 2, "a": "New York"}) == ["New York", 2]
    assert leaf_values([{"x": [1, "two"]}, None]) == [1, "two", None]
    assert leaf_values("plain") == ["plain"]


def test_a_structured_value_is_graded_by_its_leaves_not_its_key_names() -> None:
    """The R2 baseline's clearest false miss: the same $40M, filed under different key names."""
    key_value = {"amount_usd": 40000000.0, "estimate_kind": "reported"}
    run_value = {
        "amount_usd": 40000000,
        "as_of": "June 23, 2026",
        "semantics": "reported_total_after_round",
    }
    assert values_agree(key_value, run_value) == "exact"


def test_half_the_leaves_found_is_partial_and_a_wrong_number_is_still_no() -> None:
    key_value = {"round": "Series C", "amount_usd": 60000000}
    assert values_agree(key_value, {"round": "Series C"}) == "partial"
    # A scalar key keeps its own rules, and the run's key names never rescue a wrong number.
    assert values_agree(52, {"count": 36, "semantics": "linkedin_estimate"}) == "no"
    assert values_agree({"headcount": 52}, {"count": 36}) == "no"


def test_a_zero_fraction_number_is_the_same_number() -> None:
    assert as_number("40000000.0") == as_number(40_000_000) == 40000000.0
    assert normalise_value(40000000.0) == "40000000"
    assert normalise_value({"amount_usd": 40000000.0}) == "amount_usd 40000000"
    assert values_agree(40000000.0, 40_000_000) == "exact"


def test_match_claims_grades_each_key_once() -> None:
    keys = [
        KeyClaim("core.hq_location", (), "New York", "zaf-001"),
        KeyClaim("account.total_funding", ("account.recent_funding",), 130_000_000, "zaf-002"),
        KeyClaim("core.legal_name", (), "Zafran Security, Inc.", "zaf-003"),
        KeyClaim("core.company_email", (), "info@zafran.io", "zaf-004"),
    ]
    run = [
        _claim("core.hq_location", {"city": "New York", "country": "US"}),
        _claim("account.recent_funding", {"round": "Series C", "total_raised_usd": 130000000}),
        _claim("core.legal_name", "Zafran Security"),
    ]
    report = match_claims(keys, run)
    assert [m.verdict for m in report.matches] == ["exact", "exact", "partial", "missing"]
    assert report.recall() == 0.75 and report.by_section()["core"] == (2, 3)


def test_a_written_field_whose_value_disagrees_is_field_only() -> None:
    keys = [KeyClaim("account.named_customers", (), ["TurnPoint Services"], "zaf-050")]
    run = [_claim("account.named_customers", ["Acme", "Globex"])]
    report = match_claims(keys, run, account="zafran")
    assert [m.verdict for m in report.matches] == ["field_only"]
    assert report.matches[0].run_value == ["Acme", "Globex"]
    assert report.recall() == 0.0
    assert "field_only" in report.markdown() and "zafran" in report.markdown()


def test_by_section_keeps_the_two_part_resonance_prefix() -> None:
    keys = [
        KeyClaim("account.resonance.culture", (), "builder culture", None),
        KeyClaim("account.total_funding", (), 1, None),
    ]
    report = match_claims(keys, [])
    assert report.by_section() == {"account.resonance": (0, 1), "account": (0, 1)}


def test_probook_keys_reads_only_account_rows() -> None:
    keys = probook_keys(REPO / ".context/arv2-clue-sample-v3/claims.json")
    assert len(keys) == 24 and all(k.field_key.startswith(("core.", "account.")) for k in keys)


def test_an_account_report_says_account_and_claims_no_insight() -> None:
    """The two R3 fields default to the R2 reading: an account, with no one-question pass."""
    keys = [KeyClaim("core.hq_location", (), "New York", None)]
    report = match_claims(keys, [], account="zafran")
    assert report.subject_kind == "account" and report.insight_found is False
    assert report.as_dict()["subject_kind"] == "account"
    assert report.as_dict()["insight_found"] is False
    assert "account **zafran**" in report.markdown()


def test_a_person_report_is_graded_as_a_person_and_reads_the_insight_marker() -> None:
    """R3's per-person grade: the same verdicts, plus whether the one-question pass landed."""
    keys = [
        KeyClaim("contact.facet.hobby", (), "cocktail chemistry", "nick_fisher-001"),
        KeyClaim("contact.facet.recent_award", (), "Marketer of the Year", "nick_fisher-002"),
    ]
    run = [
        _contact_claim("contact.facet.hobby", "makes cocktails on YouTube"),
        _contact_claim(
            "contact.facet.voice_quote", "why I joined Zafran", markers={"unique_insight": True}
        ),
    ]
    report = person_report(keys, run, person="nick-fisher")
    assert report.subject_kind == "person" and report.insight_found is True
    assert [m.verdict for m in report.matches] == ["field_only", "missing"]
    assert report.account == "nick-fisher"
    markdown = report.markdown()
    assert "person **Nick Fisher**" in markdown and "unique insight **found**" in markdown
    payload = report.as_dict()
    assert payload["account"] == "nick-fisher"
    assert payload["subject_kind"] == "person" and payload["insight_found"] is True


def test_a_person_whose_job_never_landed_an_insight_says_so() -> None:
    run = [_contact_claim("contact.facet.hobby", "cocktail chemistry", markers={"schema_valid": 1})]
    report = person_report(
        [KeyClaim("contact.facet.hobby", (), "cocktail chemistry", "nick_fisher-001")],
        run,
        person="nick-fisher",
    )
    assert report.insight_found is False and report.recall() == 1.0
    assert "unique insight **not found**" in report.markdown()
