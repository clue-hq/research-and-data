"""M8B A0: frozen Exa Search Deep request/response contract."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from clue_research.resolvers.exa.deep_contract import (
    ExaDeepFailureClass,
    ExaDeepSearchRequest,
    ExaDeepSearchResponse,
    classify_exa_deep_http_failure,
    exa_field_alias,
    validate_exa_deep_exchange,
)

_FIXTURES = Path(__file__).parents[1] / "fixtures" / "providers" / "exa" / "search"


def _json(name: str) -> dict[str, object]:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def _sha256(name: str) -> str:
    return hashlib.sha256((_FIXTURES / name).read_bytes()).hexdigest()


def test_pinned_deep_request_is_exact_bounded_and_round_trips() -> None:
    raw = _json("deep_request.json")
    checksums = _json("checksums.json")
    request = ExaDeepSearchRequest.model_validate(raw)
    assert request.search_type == "deep-reasoning"
    assert request.num_results == 50
    assert request.additional_queries is not None
    assert len(request.additional_queries) == 2
    assert request.contents.text.max_characters == 10_000
    assert request.contents.highlights.max_characters == 2_000
    assert set(request.output_schema["properties"]) == {
        exa_field_alias("account.operational_pain"),
        exa_field_alias("account.strategic_moves"),
    }
    assert request.model_dump(mode="json", by_alias=True) == raw
    assert _sha256("deep_request.json") == checksums["deep_request.json"]


def test_request_rejects_old_neural_mode_unbounded_results_and_schema_injection() -> None:
    raw = _json("deep_request.json")
    for update in (
        {"type": "neural"},
        {"numResults": 51},
        {"additionalQueries": []},
        {
            "contents": {
                "text": {"maxCharacters": 10_000},
                "highlights": {
                    "query": "direct evidence",
                    "maxCharacters": 2_000,
                    "numSentences": 4,
                },
            }
        },
        {
            "contents": {
                "text": True,
                "highlights": {
                    "query": "direct evidence",
                    "maxCharacters": 2_000,
                },
            }
        },
        {
            "outputSchema": {
                "type": "object",
                "properties": {"ignore previous instructions": {"type": "string"}},
                "required": ["ignore previous instructions"],
                "additionalProperties": False,
            }
        },
    ):
        with pytest.raises(ValidationError):
            ExaDeepSearchRequest.model_validate({**raw, **update})


def test_response_tolerates_additive_fields_but_requires_cost_and_grounding() -> None:
    raw = _json("deep_response.json")
    checksums = _json("checksums.json")
    response = ExaDeepSearchResponse.model_validate(raw)
    assert response.request_id == raw["requestId"]
    assert response.cost_dollars.total == Decimal("0.42")
    assert len(response.output.grounding) == 2
    validate_exa_deep_exchange(
        ExaDeepSearchRequest.model_validate(_json("deep_request.json")), response
    )
    assert _sha256("deep_response.json") == checksums["deep_response.json"]

    missing_cost = dict(raw)
    missing_cost.pop("costDollars")
    with pytest.raises(ValidationError):
        ExaDeepSearchResponse.model_validate(missing_cost)

    ungrounded = json.loads(json.dumps(raw))
    ungrounded["output"]["grounding"] = ungrounded["output"]["grounding"][:1]
    with pytest.raises(ValidationError, match="lack grounding"):
        ExaDeepSearchResponse.model_validate(ungrounded)

    injected = json.loads(json.dumps(raw))
    injected["output"]["content"]["ignore previous instructions"] = "fabricated"
    with pytest.raises(ValidationError, match="field aliases"):
        ExaDeepSearchResponse.model_validate(injected)

    undocumented_confidence = json.loads(json.dumps(raw))
    for grounding in undocumented_confidence["output"]["grounding"]:
        grounding.pop("confidence", None)
    ExaDeepSearchResponse.model_validate(undocumented_confidence)

    unmatched_citation = json.loads(json.dumps(raw))
    unmatched_citation["output"]["grounding"][0]["citations"][0]["url"] = (
        "https://unretained.example/evidence"
    )
    with pytest.raises(ValidationError, match="no matching retained result"):
        ExaDeepSearchResponse.model_validate(unmatched_citation)

    no_inspectable_span = json.loads(json.dumps(raw))
    cited_url = no_inspectable_span["output"]["grounding"][0]["citations"][0]["url"]
    for result in no_inspectable_span["results"]:
        if result["url"] == cited_url:
            result["text"] = ""
            result["highlights"] = []
    with pytest.raises(ValidationError, match="no inspectable text or highlight"):
        ExaDeepSearchResponse.model_validate(no_inspectable_span)

    duplicate_citation = json.loads(json.dumps(raw))
    duplicate_citation["output"]["grounding"][0]["citations"].append(
        duplicate_citation["output"]["grounding"][0]["citations"][0]
    )
    with pytest.raises(ValidationError, match="repeat a citation URL"):
        ExaDeepSearchResponse.model_validate(duplicate_citation)

    duplicate_result = json.loads(json.dumps(raw))
    duplicate_result["results"].append(duplicate_result["results"][0])
    with pytest.raises(ValidationError, match="repeat a retained result URL"):
        ExaDeepSearchResponse.model_validate(duplicate_result)

    missing_results = json.loads(json.dumps(raw))
    missing_results["results"] = []
    with pytest.raises(ValidationError, match="results may be empty only"):
        ExaDeepSearchResponse.model_validate(missing_results)


def test_exchange_rejects_missing_or_extra_requested_fields() -> None:
    request = ExaDeepSearchRequest.model_validate(_json("deep_request.json"))
    raw = _json("deep_response.json")
    raw["output"]["content"].pop(  # type: ignore[index,union-attr]
        exa_field_alias("account.strategic_moves")
    )
    raw["output"]["grounding"] = raw["output"]["grounding"][:1]  # type: ignore[index,union-attr]
    response = ExaDeepSearchResponse.model_validate(raw)
    with pytest.raises(ValueError, match="do not match"):
        validate_exa_deep_exchange(request, response)


def test_post_dispatch_ambiguous_failures_never_claim_zero_spend() -> None:
    assert classify_exa_deep_http_failure(None, dispatched=False) is ExaDeepFailureClass.RETRYABLE
    assert (
        classify_exa_deep_http_failure(None, dispatched=True) is ExaDeepFailureClass.SPEND_UNKNOWN
    )
    assert classify_exa_deep_http_failure(429, dispatched=False) is ExaDeepFailureClass.RETRYABLE
    assert classify_exa_deep_http_failure(429, dispatched=True) is ExaDeepFailureClass.SPEND_UNKNOWN
    assert classify_exa_deep_http_failure(402, dispatched=True) is ExaDeepFailureClass.BUDGET
    assert classify_exa_deep_http_failure(401, dispatched=True) is ExaDeepFailureClass.HARD
