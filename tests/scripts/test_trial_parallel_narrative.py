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
    trial.require_current_output({"output_version": trial.OUTPUT_VERSION})


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


def alias_request(p=None, request_id="request-one"):
    p = p or packet()
    view, mapping = trial.localize_claims(p, request_id)
    return {"packet": p, "model_packet": view, "request_id": request_id}, mapping


def test_aliases_preserve_text_and_remap_links_without_mutating_original():
    p = packet()
    p["claims"].append({**record(), "claim_id": "claim-b"})
    p["claims"][0]["superseded_by"] = "claim-b"
    p["claims"][0]["value_json"]["review"].update(
        duplicate_of="claim-b", conflicts_with=["claim-b"]
    )
    frozen = json.dumps(p)
    req, mapping = alias_request(p)
    a = req["model_packet"]["claims"][0]
    assert json.dumps(p) == frozen
    assert a["claim_id"] == "C1"
    assert a["superseded_by"] == "C2"
    assert a["value_json"]["review"]["duplicate_of"] == "C2"
    assert a["value_json"]["review"]["conflicts_with"] == ["C2"]
    assert a["value_json"]["finding"] == p["claims"][0]["value_json"]["finding"]
    assert mapping["aliases"] == {"C1": "claim-a", "C2": "claim-b"}
    assert trial.localize_claims(p, "request-one") == (req["model_packet"], mapping)


def test_alias_response_resolves_every_citation_location_and_leaves_prose_unchanged():
    req, mapping = alias_request()
    s = {
        "text": "Exact wording.",
        "claimIds": ["C1"],
        "sellerEvidenceIds": ["seller-a"],
        "kind": "qualified",
        "qualifications": ["Uncertain."],
    }
    output = response()
    output["section"]["intro"] = [s]
    output["section"]["items"] = [
        {
            "h2": "Heading",
            "body": [s],
            "contactIds": ["person-a"],
            "sendLine": {**s, "kind": "inference"},
        }
    ]
    output["selectionNotes"] = [{"claimIds": ["C1"], "reason": "Useful distinction."}]
    resolved = trial.resolve_claim_aliases(
        json.dumps(output), req, mapping, [{"document_id": "seller-a"}]
    )
    for sentence in trial.sentences(resolved):
        assert sentence["claimIds"] == ["claim-a"]
        assert sentence["text"] == s["text"]
        assert sentence["sellerEvidenceIds"] == ["seller-a"]
    assert resolved["section"]["items"][0]["contactIds"] == ["person-a"]
    assert resolved["selectionNotes"][0]["claimIds"] == ["claim-a"]
    assert trial.diagnose(resolved, req["packet"])["primary"]["cited_claim_ids"] == ["claim-a"]


def test_cross_request_mapping_and_modified_packet_are_rejected():
    req, mapping = alias_request()
    other, other_map = alias_request(request_id="request-two")
    assert mapping["aliases"] == other_map["aliases"]
    with pytest.raises(ValueError, match="does not belong"):
        trial.resolve_claim_aliases(json.dumps(response()), req, other_map, [])
    other["packet"]["claims"][0]["value_json"]["finding"] = "Changed evidence."
    with pytest.raises(ValueError, match="does not belong"):
        trial.check_alias_binding(other, other_map)


def test_unknown_alias_is_not_guessed_or_resolved_as_uuid():
    req, mapping = alias_request()
    for invalid in ["C999", "claim-a"]:
        output = response()
        output["selectionNotes"] = [{"claimIds": [invalid], "reason": "Invalid reference."}]
        with pytest.raises(ValueError, match="invalid_claim_ids"):
            trial.resolve_claim_aliases(json.dumps(output), req, mapping, [])
    schema = trial.reference_schema(req["model_packet"], [{"document_id": "seller-a"}])
    assert schema["$defs"]["ClaimReference"]["enum"] == ["C1"]


def test_duplicate_or_missing_linked_claim_is_reported_during_preparation():
    p = packet()
    p["claims"].append(record())
    with pytest.raises(ValueError, match="Duplicate claim IDs"):
        trial.localize_claims(p, "request")
    p = packet()
    p["claims"][0]["superseded_by"] = "missing"
    with pytest.raises(ValueError, match="include its context first"):
        trial.localize_claims(p, "request")


def test_recovery_preserves_frozen_alias_mapping_and_reference_schema(tmp_path):
    source = tmp_path / "original"
    destination = tmp_path / "recovery"
    req, mapping = alias_request()
    req.update(system="Writer instructions", user="Frozen packet request")
    name = "overview--why-now.json"
    docs = [{"document_id": "seller-a"}]
    trial.save(source / "inputs" / name, req)
    trial.save(source / "reference-maps" / name, mapping)
    trial.save(source / "schema.json", trial.Output.model_json_schema())
    trial.save(source / "shared-context.json", {"seller_documents": docs})
    (source / "repair-prompt.txt").write_text("{{validation_errors_json}}\n{{previous_response}}")
    (source / "system-prompt.txt").write_text("Writer instructions")
    item = {
        "file": name,
        "section": "overview/why-now",
        "input_sha256": trial.sha(source / "inputs" / name),
        "reference_map_sha256": trial.sha(source / "reference-maps" / name),
    }
    trial.save(
        source / "prepared.json", {"output_version": trial.OUTPUT_VERSION, "packets": [item]}
    )
    trial.save(source / "summary.json", {"statuses": {"structural_failure": 1}})
    trial.save(
        source / "receipts" / name, {"status": "structural_failure", "attempts": [{"attempt": 1}]}
    )
    out = response()
    out["selectionNotes"] = [{"claimIds": ["C99"], "reason": "Bad reference."}]
    trial.save(source / "responses/overview--why-now.1.json", {"content": json.dumps(out)})
    items = trial.prepare_recovery(source, destination)
    recovered, recovered_map = trial.load_request(destination, items[0])
    assert recovered_map == mapping
    assert recovered["model_packet"] == req["model_packet"]
    assert recovered["packet"] == req["packet"]
    assert "C99" in recovered["user"]
    assert (destination / "reference-maps" / name).read_bytes() == (
        source / "reference-maps" / name
    ).read_bytes()
    schema = json.loads((destination / "schemas" / name).read_text())
    assert schema["$defs"]["ClaimReference"]["enum"] == ["C1"]
