"""Targeted writes preserve substance without a model-authored coverage ledger."""

import copy

import pytest

from clue_api.arv2.dossier_json import dossier_coverage, update_findings
from tests.arv2.test_dossier_json import finding


def test_update_preserves_other_findings_and_sections_and_is_idempotent():
    first, second, third = finding(), finding("F002"), finding("F003")
    original = {
        "sections": [
            {"section": "Voice", "findings": [first, second]},
            {"section": "Other", "findings": [third]},
        ]
    }
    before = copy.deepcopy(original)
    corrected = {**first, "finding": "Exact corrected public wording."}
    added = finding("F004")
    paths = set(first["source_paths"])
    updated = update_findings(original, "Voice", [corrected, added], paths)
    assert original == before
    assert updated["sections"][0]["findings"] == [corrected, second, added]
    assert updated["sections"][1] == before["sections"][1]
    assert update_findings(updated, "Voice", [corrected, added], paths) == updated
    assert update_findings(updated, "Voice", [], paths) == updated
    with pytest.raises(ValueError, match="unique"):
        update_findings(original, "Voice", [corrected, corrected], paths)
    with pytest.raises(ValueError, match="unique"):
        update_findings(original, "Voice", [third], paths)
    with pytest.raises(ValueError, match="Unknown source"):
        update_findings(original, "Voice", [finding(source_paths=["/evidence/unknown"])], paths)


def test_counts_are_reference_coverage_not_semantic_or_read_coverage():
    f = finding()
    doc = update_findings({"sections": []}, "Voice", [f, finding("F002")], set(f["source_paths"]))
    counts = dossier_coverage(doc, {*f["source_paths"], "/evidence/uncited"})
    assert counts["findings"] == 2
    assert counts["referenced_source_records"] == 1
    assert counts["unreferenced_source_records"] == 1
    assert "unread" in counts["note"]
    assert "complete" not in counts
