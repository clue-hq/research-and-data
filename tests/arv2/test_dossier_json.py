"""Transport checks do not summarize, merge, reclassify or hide authored findings."""

import json

import pytest

from clue_api.arv2.dossier_json import import_groups, parse_json_dossier


def finding(identifier="F001", **updates):
    return {
        "id": identifier,
        "topic": "Public statement",
        "claim_type": "reported_statement",
        "finding": {"statement": "“No — keep A | B.”\nA second line.", "context": "Interview"},
        "source_paths": ["/evidence/001-interview.json"],
        "attribution": "Maya",
        "time_context": "Publication date unknown",
        "qualifications": ["Reported"],
        "review": {"status": "supported", "reason": "Source says this"},
        "agent_interpretation": "Possible seller relevance; not evidence",
        **updates,
    }


def document(*findings):
    return json.dumps(
        {
            "sections": [
                {"section": "Public voices", "findings": list(findings)},
                {"section": "Uncovered section", "findings": []},
            ]
        },
        ensure_ascii=False,
    ).encode()


def test_exact_values_empty_sections_and_forward_references():
    original = finding()
    linked = finding(
        "F002",
        review={
            "status": "potential_conflict",
            "reason": "Dates unclear",
            "conflicts_with": ["F001"],
        },
    )
    parsed = parse_json_dossier(document(linked, original))
    assert not parsed.errors and parsed.finding_count == 2 and parsed.section_count == 2
    assert [r.entry.id for r in parsed.records] == ["F001", "F002"]
    assert parsed.records[0].original == original
    assert parsed.records[0].entry.finding == original["finding"]
    assert parsed.records[0].location == "$.sections[0].findings[1]"


@pytest.mark.parametrize(
    "body",
    [
        b'{"sections": [], "sections": []}',
        b'{"sections":[],"discard_me":true}',
        b'{"sections":null}',
        b"[]",
        b"not json",
        b"\xff",
        b'{"sections":[{"section":"A","findings":[{"finding":NaN}]}]}',
    ],
)
def test_invalid_document_never_silently_selects_or_drops_content(body):
    parsed = parse_json_dossier(body)
    assert parsed.errors and not parsed.records


def test_bad_entry_duplicate_ids_and_dependent_records_do_not_hide_independent_findings():
    parsed = parse_json_dossier(
        document(
            finding(),
            finding(claim_type="invalid"),
            finding(
                "F002", review={"status": "duplicate", "reason": "Same", "duplicate_of": "F001"}
            ),
            finding("F003", extra_field="Must not be discarded"),
            finding("F004"),
        )
    )
    assert parsed.finding_count == 5
    assert [r.entry.id for r in parsed.records] == ["F004"]
    assert len(parsed.errors) == 4


def test_reciprocal_conflicts_preserve_judgment_and_import_as_one_group():
    a = finding(
        review={"status": "potential_conflict", "reason": "Unclear", "conflicts_with": ["F002"]}
    )
    b = finding(
        "F002",
        review={"status": "potential_conflict", "reason": "Unclear", "conflicts_with": ["F001"]},
    )
    parsed = parse_json_dossier(document(a, b, finding("F003")))
    assert not parsed.errors
    assert [{r.entry.id for r in group} for group in import_groups(parsed.records)] == [
        {"F001", "F002"},
        {"F003"},
    ]
    assert a["review"]["status"] == b["review"]["status"] == "potential_conflict"


def test_invalid_reference_propagates_through_conflict_component():
    a = finding(
        review={"status": "potential_conflict", "reason": "Unclear", "conflicts_with": ["F002"]}
    )
    b = finding(
        "F002",
        review={
            "status": "potential_conflict",
            "reason": "Unclear",
            "conflicts_with": ["F001", "F999"],
        },
    )
    parsed = parse_json_dossier(document(a, b, finding("F003")))
    assert [r.entry.id for r in parsed.records] == ["F003"]
    assert {e["id"] for e in parsed.errors} == {"F001", "F002"}
