"""Offline packet fidelity and citation checks; no provider calls."""

import json

import pytest

from scripts import trial_parallel_narrative as trial


def record():
    finding = 'The team said: "We build it ourselves." ' * 100
    value = {
        "finding": finding,
        "topic": "Working method",
        "qualifications": ["Statement, not buying intent."],
        "agent_interpretation": "May inform a conversation.",
        "review": {"status": "insufficient_context"},
        "sources": [{"url": "https://example.test/post"}],
    }
    value["dossier_entry"] = {
        "id": "F001",
        "section": "Voice",
        "original": {**value, "source_paths": ["/evidence/post.json"]},
    }
    return {
        "claim_id": "claim-a",
        "value_json": value,
        "role": "primary",
        "evidence_span": "Exact evidence.",
        "field_key": "account.research_finding",
    }


def response():
    return {
        "section": {"key": "why-now", "intro": [], "items": [], "gaps": []},
        "coverage": {"primary": [], "context": []},
        "contextGaps": [],
    }


def packet():
    return {"section_key": "why-now", "claims": [record()], "known_contacts": {"person-a": "Acme"}}


def test_lossless_model_view_keeps_long_text_sources_and_uncertainty():
    raw = record()
    frozen = json.dumps(raw)
    view = trial.model_claim(raw)
    assert json.dumps(raw) == frozen
    for k, v in raw["value_json"].items():
        if k != "dossier_entry":
            assert view["value_json"][k] == v
    assert len(view["value_json"]["finding"]) > 1200
    assert view["original_source_paths"] == ["/evidence/post.json"]
    assert view["evidence_span"] == raw["evidence_span"]


def test_disagreeing_original_cannot_be_silently_removed():
    raw = record()
    raw["value_json"]["dossier_entry"]["original"]["finding"] = "Different finding."
    with pytest.raises(AssertionError):
        trial.model_claim(raw)


@pytest.mark.parametrize(
    "key,value", [("claimIds", ["other-claim"]), ("sellerEvidenceIds", ["other-seller"])]
)
def test_unknown_references_are_structural_errors(key, value):
    output = response()
    sentence = {
        "text": "A claim.",
        "claimIds": ["claim-a"],
        "sellerEvidenceIds": [],
        "kind": "qualified",
        "qualifications": ["Uncertain."],
    }
    sentence[key] = value
    output["section"]["intro"] = [sentence]
    with pytest.raises(ValueError):
        trial.validate(json.dumps(output), packet(), [])


def test_missing_coverage_is_diagnostic_not_automatic_paid_retry():
    result = trial.validate(json.dumps(response()), packet(), [])
    assert trial.diagnose(result, packet())["primary"]["missing"] == ["claim-a"]


def test_uncertain_claims_can_be_displayed_without_changing_review():
    output = response()
    output["section"]["intro"] = [
        {
            "text": "The available statement is incomplete.",
            "claimIds": ["claim-a"],
            "sellerEvidenceIds": [],
            "kind": "qualified",
            "qualifications": ["Insufficient context."],
        }
    ]
    assert trial.validate(json.dumps(output), packet(), []) == output


def test_wrong_section_and_coverage_reference_are_rejected():
    output = response()
    output["section"]["key"] = "unrequested-section"
    with pytest.raises(ValueError):
        trial.validate(json.dumps(output), packet(), [])


def test_reference_schema_constrains_ids_without_selecting_claims():
    schema = trial.reference_schema(packet(), [{"document_id": "seller-a"}])
    defs = schema["$defs"]
    assert defs["ClaimReference"]["enum"] == ["claim-a"]
    assert defs["Sentence"]["properties"]["claimIds"]["items"] == {"$ref": "#/$defs/ClaimReference"}
    assert defs["CoverageEntry"]["properties"]["representedBy"]["items"] == {
        "$ref": "#/$defs/ClaimReference"
    }
    assert defs["Sentence"]["properties"]["sellerEvidenceIds"]["items"]["enum"] == ["seller-a"]
    assert "minItems" not in defs["Sentence"]["properties"]["claimIds"]


def test_repair_feedback_names_each_bad_id():
    output = response()
    output["section"]["intro"] = [
        {
            "text": "Example.",
            "claimIds": ["bad-a", "bad-b"],
            "sellerEvidenceIds": ["bad-seller"],
            "kind": "qualified",
            "qualifications": [],
        }
    ]
    with pytest.raises(ValueError) as failure:
        trial.validate(json.dumps(output), packet(), [])
    detail = json.loads(str(failure.value))
    assert detail["invalid_claim_ids"] == ["bad-a", "bad-b"]
    assert detail["invalid_seller_document_ids"] == ["bad-seller"]
    output = response()
    output["coverage"]["primary"] = [
        {
            "claimId": "other-claim",
            "disposition": "used",
            "representedBy": [],
            "reason": "Incorrect ID.",
        }
    ]
    with pytest.raises(ValueError):
        trial.validate(json.dumps(output), packet(), [])
