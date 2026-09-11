"""The ICP document is the program: the brief compiler reads gates, query and criteria out of it.

R4's rule is that no gate logic lives in code. These tests hold the compiler to it by running it
over the real Clue ICP document's front matter — the same ``hard_gates``/``exclusions`` YAML the
answer-key workspace confirmed — and asserting that everything the discovery run will ask came out
of that document: the four gates in document order, the 36-month window read from the stage gate's
own words, the buyer sentence lifted from the body, and the ≤3 webset criteria.
"""

# ruff: noqa: E501 — ``ICP_TEXT`` is the confirmed document copied verbatim; rewrapping its YAML
# would make the fixture something other than the thing under test.
from __future__ import annotations

import pytest

from clue_api.arv2.discovery_brief import BriefError, compile_brief, parse_window_months
from clue_api.arv2.knowledge_frontmatter import parse_front_matter

#: The confirmed Clue ICP document, front matter copied verbatim from
#: ``.context/arv2-answer-key-knowledge/icp-clue-abm-buyers.md``.
ICP_TEXT = """---
kind: icp-definition
icp_key: clue-abm-buyers
version: 1
status: confirmed
hard_gates:
  - key: geography
    rule: "US-headquartered"
    test: "The HQ city and state on the company's own site, its LinkedIn page, or its funding announcement dateline is in the United States."
  - key: stage
    rule: "A named, priced round of Series A or later, announced within the last 36 months"
    test: "A dated announcement (press release, lead investor's post, or the company's own newsroom) that names the round and at least one investor. A seed-only, bootstrapped, public or PE-owned company is recorded as outside the stated stage — a verdict for the human, never a reason to stop researching. A self-funded operator is recorded as unclear pending master plan D9's equivalence clause."
  - key: hiring
    rule: "Actively hiring now, with at least one open go-to-market role"
    test: "At least one requisition listed today on the company's own careers page or ATS board with a GTM title: sales, marketing, growth, ABM, demand generation, SDR or BDR, partnerships, revenue operations."
  - key: intent
    rule: "At least one citable, dated buying-intent signal"
    test: "One Tier-1 signal (Q1 to Q4 below) or two Tier-2 signals (Q5 to Q10 below), each with a verbatim quote and the URL it came from."
exclusions:
  - "Sells to consumers (B2C)"
  - "Pure self-serve product-led growth: public signup, published low-tier pricing, no talk-to-sales path"
  - "An enterprise ABM or personalization platform already installed: 6sense, Demandbase, Terminus, RollWorks, Mutiny, Folloze, Influ2, Madison Logic"
  - "A direct competitor: sells ABM orchestration, AI SDR or GTM agents, personalized-microsite or intent tooling"
  - "Public, PE-owned, or more than 800 employees"
  - "Non-US headquarters"
  - "Below Series A: pre-seed, seed, bootstrapped, grant-funded"
  - "Clue itself and any Clue-affiliated entity"
---

# Who we sell to

US B2B vertical SaaS companies with a priced round behind them, thirty to three hundred people,
selling to a named list of accounts rather than a funnel, whose go-to-market team is hiring
humans to solve throughput.

## How they buy

A small team runs the motion: the marketer who owns the list is the champion, and the round that
was earmarked for expansion is why the economic buyer signs.
"""


#: An ICP the onboarding synthesis agent wrote for another seller: its own gate vocabulary, five
#: gates, nothing called ``geography`` or ``stage``. Discovery must launch on it with no
#: configuration at all — the document decides its own criteria (founder ruling 2026-09-11).
SYNTHESISED_ICP_TEXT = """---
kind: icp-definition
icp_key: specialty-ambulatory-groups
version: 2
status: confirmed
hard_gates:
  - key: industry_specialty_ambulatory
    rule: "A specialty ambulatory group (GI, ortho, cardiology) with two or more sites"
    test: "The company's own site lists at least two locations under one specialty."
  - key: geography_us
    rule: "US-headquartered"
    test: "The HQ city and state on the company's own site is in the United States."
  - key: referral_or_document_front_door
    rule: "Referrals or faxed documents are the front door to the practice"
    test: "The site names a referral form, a fax line or a document intake step."
  - key: ehr_in_supported_set
    rule: "Runs an EHR in the supported set"
    test: "A careers page, a case study or a partner page names athenahealth, Epic or eCW."
  - key: hipaa_covered_entity
    rule: "A HIPAA covered entity"
    test: "A notice of privacy practices is published on the company's own site."
---

# Who we sell to

Specialty ambulatory groups in the United States whose front door is a referral or a faxed
document, running an EHR we integrate with.
"""


def _with_criteria(text: str, *keys: str) -> tuple[dict, str]:
    """The document with ``criterion: true`` set on the named gates — what the synthesis skill
    will write once it marks the page-answerable gates itself."""
    front, body = parse_front_matter(text)
    gates = [dict(gate) for gate in front["hard_gates"]]
    for gate in gates:
        if gate["key"] in keys:
            gate["criterion"] = True
    return {**front, "hard_gates": gates}, body


def test_with_no_keys_named_the_document_decides_its_own_criteria() -> None:
    """No configuration anywhere: the first three gates in document order are the criteria, and
    with all three slots taken the buyer sentence stays out of the webset."""
    front, body = parse_front_matter(SYNTHESISED_ICP_TEXT)
    brief = compile_brief(front, body)
    assert brief.criteria_gate_keys == (
        "industry_specialty_ambulatory",
        "geography_us",
        "referral_or_document_front_door",
    )
    assert brief.criteria == tuple(gate.rule for gate in brief.gates[:3])
    assert (
        brief.query.startswith("Specialty ambulatory groups") and brief.query not in brief.criteria
    )
    assert [gate.key for gate in brief.gates] == [
        "industry_specialty_ambulatory",
        "geography_us",
        "referral_or_document_front_door",
        "ehr_in_supported_set",
        "hipaa_covered_entity",
    ]


def test_gates_the_document_marks_as_criteria_win_over_document_order() -> None:
    front, body = _with_criteria(SYNTHESISED_ICP_TEXT, "geography_us", "hipaa_covered_entity")
    brief = compile_brief(front, body)
    assert brief.criteria_gate_keys == ("geography_us", "hipaa_covered_entity")
    # Two marked gates leave one slot, which the buyer sentence fills.
    assert brief.criteria == (brief.gates[1].rule, brief.gates[4].rule, brief.query)
    assert brief.gates[1].criterion is True and brief.gates[0].criterion is False


def test_a_document_marking_four_criteria_is_refused_not_truncated() -> None:
    front, body = _with_criteria(
        SYNTHESISED_ICP_TEXT,
        "industry_specialty_ambulatory",
        "geography_us",
        "ehr_in_supported_set",
        "hipaa_covered_entity",
    )
    with pytest.raises(BriefError, match="marks 4 gates as criteria"):
        compile_brief(front, body)


def test_a_document_with_fewer_than_three_gates_uses_them_all() -> None:
    front, body = parse_front_matter(SYNTHESISED_ICP_TEXT)
    front = {**front, "hard_gates": front["hard_gates"][:2]}
    brief = compile_brief(front, body)
    assert brief.criteria_gate_keys == ("industry_specialty_ambulatory", "geography_us")
    assert brief.criteria[-1] == brief.query


def test_named_keys_still_override_whatever_the_document_marks() -> None:
    """The operator escape hatch: keys named on the request win, and are validated as before."""
    front, body = _with_criteria(SYNTHESISED_ICP_TEXT, "hipaa_covered_entity")
    brief = compile_brief(front, body, criteria_gate_keys=["ehr_in_supported_set"])
    assert brief.criteria_gate_keys == ("ehr_in_supported_set",)


def test_compile_brief_reads_gates_query_and_windows_from_the_document() -> None:
    front, body = parse_front_matter(ICP_TEXT)
    brief = compile_brief(front, body, criteria_gate_keys=["geography", "stage"])
    assert [g.key for g in brief.gates] == ["geography", "stage", "hiring", "intent"]
    assert brief.gates[1].window_months == 36 and brief.gates[0].window_months is None
    assert brief.query.startswith("US B2B vertical SaaS")
    assert brief.criteria == (brief.gates[0].rule, brief.gates[1].rule, brief.query)
    assert brief.criteria_gate_keys == ("geography", "stage")
    assert "Sells to consumers (B2C)" in brief.exclusions


def test_three_named_gates_leave_no_slot_for_the_buyer_sentence() -> None:
    front, body = parse_front_matter(ICP_TEXT)
    brief = compile_brief(front, body, criteria_gate_keys=["geography", "stage", "hiring"])
    assert len(brief.criteria) == 3 and brief.query not in brief.criteria


def test_unknown_gate_key_and_missing_gates_refuse_by_name() -> None:
    front, body = parse_front_matter(ICP_TEXT)
    with pytest.raises(BriefError, match="unknown criteria gate key 'vertical'"):
        compile_brief(front, body, criteria_gate_keys=["vertical"])
    with pytest.raises(BriefError, match="no hard_gates"):
        compile_brief({"kind": "icp-definition"}, body, criteria_gate_keys=[])


def test_a_fourth_criterion_is_refused_rather_than_silently_dropped() -> None:
    """Websets takes three criteria. A fourth is a mistake the human must see, not a truncation."""
    front, body = parse_front_matter(ICP_TEXT)
    with pytest.raises(BriefError, match="at most 3 criteria"):
        compile_brief(front, body, criteria_gate_keys=["geography", "stage", "hiring", "intent"])


def test_the_window_is_the_first_month_count_across_a_gates_own_words() -> None:
    assert parse_window_months("no window here", "dated within the last 18 months") == 18
    assert parse_window_months("announced within 24months of today") == 24
    assert parse_window_months("listed today on the company's own board") is None
