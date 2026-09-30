"""Offline tests for the target-discovery trial (no provider is called)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from clue_api.arv2.knowledge_frontmatter import parse_front_matter
from scripts import trial_target_discovery as trial

# The shape the ICP-synthesis skill's inline YAML (`- {key: …, rule: …, test: …}`) leaves behind
# once a comma inside a value has split it, as stored after normalisation (2026-09-30).
BROKEN_ICP = """---
kind: icp-definition
icp_key: widget-makers
version: 1
status: confirmed
hard_gates:
- key: industry_widgets
  rule: The company manufactures widgets (not a widget reseller).
  test: Brand site
  product pages: null
  or press describe widget plants.: null
- key: guest_function
  rule: There is a named plant-operations
  quality: null
  or maintenance function that owns uptime.: null
  test: Careers pages list Plant Operations
  Quality: null
  or Maintenance.: null
- key: stack
  rule: An MES is in use.
  test: Public mention of an MES.
exclusions:
- Widget resellers.
- Software vendors that sell to widget makers.
---

# Widget makers

Priority definition: a widget manufacturer that needs plant uptime software and would
otherwise buy an MES suite.

## Who this is

- More text.
"""


def test_the_stored_icp_really_is_truncated_by_the_production_parser() -> None:
    front, _ = parse_front_matter(BROKEN_ICP)
    assert front["hard_gates"][1]["rule"] == "There is a named plant-operations"
    assert front["hard_gates"][0]["test"] == "Brand site"


def test_repair_rejoins_every_fragment_in_document_order() -> None:
    front, _ = parse_front_matter(BROKEN_ICP)
    repaired = trial.repair_front_matter(front)
    gates = repaired["hard_gates"]
    assert gates[0]["test"] == ("Brand site, product pages, or press describe widget plants.")
    assert gates[1]["rule"] == (
        "There is a named plant-operations, quality, or maintenance function that owns uptime."
    )
    assert gates[1]["test"] == "Careers pages list Plant Operations, Quality, or Maintenance."
    assert gates[2] == {
        "key": "stack",
        "rule": "An MES is in use.",
        "test": "Public mention of an MES.",
    }
    assert trial.fragment_count(front) == 6
    assert trial.fragment_count(repaired) == 0


def test_arm_a_is_production_exactly_and_arm_b_restores_the_criteria() -> None:
    icp = trial.load_icp_text(BROKEN_ICP)
    a = trial.build_brief("A", icp, overrides={})
    b = trial.build_brief("B", icp, overrides={})
    assert a.criteria[1] == "There is a named plant-operations"
    assert a.query.startswith("Priority definition: a widget manufacturer")
    assert b.criteria[1].endswith("function that owns uptime.")
    assert b.query == a.query


def test_arm_c_swaps_the_query_and_d_adds_the_exclusion_criterion() -> None:
    icp = trial.load_icp_text(BROKEN_ICP)
    overrides = {
        "company_query": "Companies that manufacture widgets in their own plants.",
        "exclusion_criterion": "The company is not a software vendor selling to widget makers.",
    }
    c = trial.build_brief("C", icp, overrides=overrides)
    d = trial.build_brief("D", icp, overrides=overrides)
    assert c.query == overrides["company_query"]
    assert c.criteria == trial.build_brief("B", icp, overrides={}).criteria
    assert d.criteria[-1] == overrides["exclusion_criterion"]
    assert len(d.criteria) == len(c.criteria) + 1


def test_an_arm_that_needs_an_override_refuses_without_one() -> None:
    icp = trial.load_icp_text(BROKEN_ICP)
    with pytest.raises(trial.TrialError, match="company_query"):
        trial.build_brief("C", icp, overrides={})
    with pytest.raises(trial.TrialError, match="exclusion_criterion"):
        trial.build_brief("D", icp, overrides={"company_query": "x"})


def test_the_budget_refuses_a_call_that_would_cross_the_cap() -> None:
    budget = trial.Budget(cap_usd=Decimal("1.00"))
    budget.spend(Decimal("0.70"))
    budget.check(Decimal("0.30"))
    with pytest.raises(trial.TrialError, match="budget"):
        budget.check(Decimal("0.31"))


def test_candidates_dedupe_on_registrable_domain_and_respect_the_count() -> None:
    rows = [
        trial.Candidate(name="Acme", url="https://www.acme.com/about", source="websets"),
        trial.Candidate(name="Acme Inc", url="https://acme.com", source="websets"),
        trial.Candidate(name="Beta", url="https://beta.io", source="websets"),
        trial.Candidate(name="Gamma", url="https://gamma.co", source="websets"),
    ]
    kept = trial.dedupe(rows, count=2)
    assert [c.domain for c in kept] == ["acme.com", "beta.io"]


def test_the_report_counts_precision_per_arm() -> None:
    grades = {
        "A": {"acme.com": "target", "beta.io": "not_target", "gamma.co": "not_target"},
        "B": {"acme.com": "target", "delta.com": "target", "eps.com": "unclear"},
    }
    table = trial.precision_table(grades)
    assert table["A"] == {
        "graded": 3,
        "target": 1,
        "not_target": 2,
        "unclear": 0,
        "precision": 1 / 3,
    }
    assert table["B"]["precision"] == pytest.approx(2 / 3)


AGENT_ANSWER = {
    "query": "Companies that manufacture widgets in their own plants.",
    "criteria": [
        "The company manufactures widgets in plants it operates.",
        "The company is not a software vendor that sells to widget makers.",
    ],
    "gates": [
        {
            "key": "makes_widgets",
            "rule": "The company manufactures widgets.",
            "test": "Its site describes its own plants within the last 24 months.",
            "disqualifying": True,
        },
        {
            "key": "has_mes",
            "rule": "An MES is in use.",
            "test": "A job post names one.",
            "disqualifying": False,
        },
    ],
    "reasoning": "Identity first; vendors ruled out.",
}


def test_an_agent_answer_becomes_the_brief_the_search_sends() -> None:
    brief, disqualifying = trial.brief_from_agent(AGENT_ANSWER)
    assert brief.query == AGENT_ANSWER["query"]
    assert brief.criteria == tuple(AGENT_ANSWER["criteria"])
    assert [g.key for g in brief.gates] == ["makes_widgets", "has_mes"]
    assert brief.gates[0].window_months == 24
    assert disqualifying == frozenset({"makes_widgets"})


def test_an_agent_answer_outside_the_limits_is_refused() -> None:
    too_many = {**AGENT_ANSWER, "criteria": [f"c{i}" for i in range(6)]}
    with pytest.raises(trial.TrialError, match="criteria"):
        trial.brief_from_agent(too_many)
    with pytest.raises(trial.TrialError, match="query"):
        trial.brief_from_agent({**AGENT_ANSWER, "query": ""})


def test_a_failed_disqualifying_gate_excludes_the_company() -> None:
    verdicts = [
        {"gate_key": "makes_widgets", "verdict": "fail"},
        {"gate_key": "has_mes", "verdict": "pass"},
    ]
    assert trial.excluded_by(verdicts, frozenset({"makes_widgets"})) == ["makes_widgets"]
    assert trial.excluded_by(verdicts, frozenset({"has_mes"})) == []
    unclear = [{"gate_key": "makes_widgets", "verdict": "unclear"}]
    assert trial.excluded_by(unclear, frozenset({"makes_widgets"})) == []
