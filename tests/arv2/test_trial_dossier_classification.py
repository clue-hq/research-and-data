"""Trial classification preserves findings and checks representation, not factual truth."""

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import trial_dossier_classification as trial  # noqa: E402

CATALOG = [
    {
        "entity": "accounts",
        "field_key": "core.employee_count",
        "version": 1,
        "value_schema": {"type": "integer"},
    }
]


def finding(**updates):
    return {
        "id": "F001",
        "topic": "Headcount",
        "claim_type": "reported_statement",
        "finding": {"quote": "“We have 167 employees.”", "context": "As reported"},
        "source_paths": ["/evidence/company.json"],
        "attribution": "Company",
        "review": {"status": "supported", "reason": "Explicit report"},
        "classification": {
            "field_key": "core.employee_count",
            "field_version": 1,
            "projection": {"value": 167},
            "categories": ["scale"],
            "reason": None,
        },
        **updates,
    }


def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(
        trial,
        "source_aliases",
        lambda *_: {"/evidence/company.json": {"url": "https://example.test"}},
    )
    trial.save(tmp_path / "inputs/research/field-catalog.json", {"fields": CATALOG})


def test_lossless_save_freeze_and_readable_output(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    f = finding()
    assert trial.save_section(tmp_path, [], "Scale", [f])["saved"]
    assert not trial.inspect_live(tmp_path, [])[1]
    assert trial.finish_live(tmp_path, [], "Done", [])["finished"]
    assert json.loads((tmp_path / "dossier.json").read_text())["sections"][0]["findings"][0] == f
    assert "167 employees" in (tmp_path / "dossier.readable.md").read_text()
    assert not trial.save_section(tmp_path, [], "Scale", [])["saved"]


@pytest.mark.parametrize(
    "change",
    [
        {"field_key": "contact.current_title"},
        {"field_version": 2},
        {"projection": None},
        {"projection": {"value": "100-200"}},
        {"projection": {"value": None}},
        {"categories": ["invented"]},
    ],
)
def test_wrong_subject_version_shape_and_categories_rejected_without_mutation(
    tmp_path, monkeypatch, change
):
    setup(tmp_path, monkeypatch)
    original = finding()
    assert trial.save_section(tmp_path, [], "Scale", [original])["saved"]
    path = tmp_path / "inputs/scratch/account-dossier.json"
    before = path.read_bytes()
    f = copy.deepcopy(original)
    f["classification"].update(change)
    assert not trial.save_section(tmp_path, [], "Scale", [f])["saved"]
    assert path.read_bytes() == before


def test_fallback_keeps_uncategorized_statement_without_invented_version():
    f = finding(
        classification={
            "field_key": "account.research_finding",
            "field_version": None,
            "projection": None,
            "categories": [],
            "reason": "No precise field",
        }
    )
    assert trial.check_classification(f, CATALOG).finding == f["finding"]
    assert (
        trial.base_document({"sections": [{"section": "Scale", "findings": [f]}]})["sections"][0][
            "findings"
        ][0]["finding"]
        == f["finding"]
    )


def test_duplicate_and_forward_conflict_links_remain_intact(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    a = finding(
        review={
            "status": "potential_conflict",
            "reason": "Different figures",
            "conflicts_with": ["F002"],
        }
    )
    b = finding(id="F002")
    assert trial.save_section(tmp_path, [], "One", [a])["saved"]
    assert trial.inspect_live(tmp_path, [])[1]
    assert trial.save_section(tmp_path, [], "Two", [b])["saved"]
    assert not trial.inspect_live(tmp_path, [])[1]
    assert not trial.save_section(tmp_path, [], "Three", [b])["saved"]
    assert trial.finish_live(tmp_path, [], "Done", [])["finished"]
    stored = json.loads((tmp_path / "dossier.json").read_text())
    assert stored["sections"][0]["findings"][0]["review"]["conflicts_with"] == ["F002"]
