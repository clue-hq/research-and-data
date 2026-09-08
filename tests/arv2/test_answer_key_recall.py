"""The answer-key recall measurement, graded offline against hand-written pairs.

These tests pin the grading rules themselves — what counts as an exact hit, what counts as a
partial one, and what a key the run never wrote looks like in the report. The measurement is only
worth its baseline if the rules cannot drift underneath it.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from clue_api.arv2.answer_key_recall import (
    KeyClaim,
    match_claims,
    normalise_value,
    probook_keys,
    values_agree,
)
from clue_core import (
    Claim,
    EntityId,
    EntityType,
    ExtractionMethod,
    ResearchMode,
    ReuseScope,
    RunId,
)

REPO = Path(__file__).resolve().parents[2]
ACCOUNT_ID = EntityId(UUID("11111111-1111-4111-8111-111111111111"))
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
