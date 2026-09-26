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
        "selectionNotes": [],
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


def test_uncited_input_is_diagnostic_not_automatic_paid_retry():
    result = trial.validate(json.dumps(response()), packet(), [])
    assert trial.diagnose(result, packet())["primary"]["not_directly_cited_claim_ids"] == [
        "claim-a"
    ]


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


def test_wrong_section_is_rejected():
    output = response()
    output["section"]["key"] = "unrequested-section"
    with pytest.raises(ValueError):
        trial.validate(json.dumps(output), packet(), [])


def test_reference_schema_constrains_ids_without_selecting_claims():
    schema = trial.reference_schema(packet(), [{"document_id": "seller-a"}])
    defs = schema["$defs"]
    assert defs["ClaimReference"]["enum"] == ["claim-a"]
    assert defs["Sentence"]["properties"]["claimIds"]["items"] == {"$ref": "#/$defs/ClaimReference"}
    assert defs["SelectionNote"]["properties"]["claimIds"]["items"] == {
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
    output["selectionNotes"] = [{"claimIds": ["other-claim"], "reason": "Incorrect ID."}]
    with pytest.raises(ValueError):
        trial.validate(json.dumps(output), packet(), [])


def test_accounting_counts_sentence_citations_once_and_notes_never_as_citations():
    p = packet()
    context = {**record(), "claim_id": "context-b", "role": "context"}
    unused = {**record(), "claim_id": "unused-c"}
    p["claims"] += [context, unused]
    sentence = {
        "text": "A qualified finding.",
        "claimIds": ["claim-a"],
        "sellerEvidenceIds": [],
        "kind": "qualified",
        "qualifications": [],
    }
    out = response()
    out["section"]["intro"] = [sentence, sentence]
    out["section"]["items"] = [
        {
            "h2": "Context",
            "body": [{**sentence, "claimIds": ["context-b"]}],
            "contactIds": [],
            "sendLine": {**sentence, "kind": "inference"},
        }
    ]
    out["selectionNotes"] = [{"claimIds": ["unused-c"], "reason": "Overlapping evidence."}]
    result = trial.validate(json.dumps(out), p, [])
    diag = trial.diagnose(result, p)
    assert diag["cited_claims"] == 2
    assert diag["primary"]["cited_claim_ids"] == ["claim-a"]
    assert diag["primary"]["not_directly_cited_claim_ids"] == ["unused-c"]
    assert diag["context"]["cited_claim_ids"] == ["context-b"]
    assert diag["context"]["not_directly_cited_claim_ids"] == []
    assert diag["selection_notes"] == out["selectionNotes"]


def test_notes_cannot_silently_replace_legacy_coverage_contract():
    out = response()
    out["coverage"] = {"primary": [], "context": []}
    with pytest.raises(ValueError):
        trial.validate(json.dumps(out), packet(), [])
    with pytest.raises(ValueError, match="Prepare a fresh directory"):
        trial.require_current_output({})
    trial.require_current_output({"output_version": 2})


def test_prompt_and_schema_remove_per_claim_ledger_but_keep_citations():
    system, user, _, _ = trial.prompts()
    schema = trial.Output.model_json_schema()
    assert "coverage" not in schema["properties"]
    assert "CoverageEntry" not in schema["$defs"]
    assert "claimIds" in schema["$defs"]["Sentence"]["properties"]
    assert '"selectionNotes": []' in user
    assert "Do not produce a ledger" in system
    assert "Account for every supplied primary claim" not in system
    assert "coverage" not in user
