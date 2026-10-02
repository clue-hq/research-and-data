"""M8B A0: frozen Exa Search Deep request/response contract."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from clue_research.resolvers.exa import deep_contract, normalize_exa_deep_snapshot
from clue_research.resolvers.exa.deep_contract import (
    EXA_FIELD_ALIAS_CHARACTERS,
    ExaDeepFailureClass,
    ExaDeepSearchRequest,
    ExaDeepSearchResponse,
    classify_exa_deep_http_failure,
    exa_field_alias,
    exa_field_aliases,
    field_key_from_exa_alias,
    legacy_exa_field_alias,
    validate_exa_deep_exchange,
    validate_exa_field_alias,
)

_SHORT_ALIAS = deep_contract._SHORT_FIELD_ALIAS

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


def test_short_field_aliases_are_deterministic_bounded_and_collision_free() -> None:
    """Alias length no longer tracks the field name, and a bundle assignment is reproducible.

    The provider must copy the property name into its answer verbatim. Under the v1 encoding the
    live resonance bundle asked it to copy 52, 66 and 74 characters of hex and it lost characters
    out of two of them, so the paid exchange could not be settled at all. Ten characters is the
    whole fix; determinism is what lets a persisted request be revalidated later.
    """

    keys = (
        "account.resonance.buying_culture",
        "account.resonance.culture",
        "account.resonance.employee_sentiment",
    )
    assert [len(legacy_exa_field_alias(key)) for key in keys] == [66, 52, 74]

    aliases = exa_field_aliases(keys)
    assert set(aliases) == set(keys)
    assert all(len(alias) == EXA_FIELD_ALIAS_CHARACTERS == 10 for alias in aliases.values())
    assert len(set(aliases.values())) == len(keys)
    assert all(_SHORT_ALIAS.fullmatch(alias) for alias in aliases.values())
    # Membership decides the table, never the caller's ordering, and never the process.
    assert exa_field_aliases(reversed(keys)) == aliases
    assert {key: exa_field_alias(key) for key in keys} == aliases

    with pytest.raises(ValueError, match="unique"):
        exa_field_aliases((*keys, keys[0]))
    with pytest.raises(ValueError, match="at least one field key"):
        exa_field_aliases(())


def test_a_bundle_digest_collision_is_resolved_deterministically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A same-digest draw bumps a salt instead of failing; sorted order decides who moves."""

    collide = {"account.alpha_field", "account.beta_field"}
    original = deep_contract._short_field_alias

    def _colliding(field_key: str, *, salt: int) -> str:
        if field_key in collide and salt == 0:
            return "k_00000000"
        return original(field_key, salt=salt)

    monkeypatch.setattr(deep_contract, "_short_field_alias", _colliding)
    aliases = exa_field_aliases(sorted(collide))

    assert aliases["account.alpha_field"] == "k_00000000"
    assert aliases["account.beta_field"] == original("account.beta_field", salt=1)
    assert exa_field_aliases(sorted(collide, reverse=True)) == aliases


def test_a_legacy_alias_request_and_response_still_parse_after_the_cutover() -> None:
    """The pre-cutover wire pair is retained byte-identically and must keep resolving.

    Retained responses, snapshot replay and the quarantined-response recovery path all read a
    *stored* request, so resolution follows the generation that request actually asked for rather
    than the one the compiler emits today.
    """

    checksums = _json("checksums.json")
    assert _sha256("legacy_alias_deep_request.json") == checksums["legacy_alias_deep_request.json"]
    assert (
        _sha256("legacy_alias_deep_response.json") == checksums["legacy_alias_deep_response.json"]
    )

    request = ExaDeepSearchRequest.model_validate(_json("legacy_alias_deep_request.json"))
    properties = request.output_schema["properties"]
    assert isinstance(properties, dict)
    assert set(properties) == {
        legacy_exa_field_alias("account.operational_pain"),
        legacy_exa_field_alias("account.strategic_moves"),
    }
    assert set(request.field_key_by_alias.values()) == {
        "account.operational_pain",
        "account.strategic_moves",
    }
    assert all(len(alias) > EXA_FIELD_ALIAS_CHARACTERS for alias in properties)

    response = ExaDeepSearchResponse.model_validate(_json("legacy_alias_deep_response.json"))
    validate_exa_deep_exchange(request, response)
    normalized = normalize_exa_deep_snapshot(request, response)
    assert {field.field_key for field in normalized.synthesis.fields} == {
        "account.operational_pain",
        "account.strategic_moves",
    }


def test_the_two_alias_generations_cannot_be_mixed_or_cross_resolved() -> None:
    legacy = legacy_exa_field_alias("account.operational_pain")
    short = exa_field_alias("account.operational_pain")

    assert field_key_from_exa_alias(legacy) == "account.operational_pain"
    with pytest.raises(ValueError, match="short bundle alias"):
        field_key_from_exa_alias(short)
    validate_exa_field_alias(legacy)
    validate_exa_field_alias(short)
    with pytest.raises(ValueError, match="field alias"):
        validate_exa_field_alias("account.operational_pain")

    # A schema-and-prompt-consistent third member in the *other* generation is still refused: one
    # request states one generation, so nothing has to guess which decoder a property belongs to.
    third = legacy_exa_field_alias("account.total_funding")
    raw = _json("deep_request.json")
    schema = raw["outputSchema"]
    assert isinstance(schema, dict)
    properties = schema["properties"]
    assert isinstance(properties, dict)
    schema["properties"] = {third: {"type": ["string", "null"]}, **properties}
    schema["required"] = list(schema["properties"])
    prompt = raw["systemPrompt"]
    assert isinstance(prompt, str)
    raw["systemPrompt"] = f"{prompt} {third}=account.total_funding."
    with pytest.raises(ValidationError, match="mix provider alias generations"):
        ExaDeepSearchRequest.model_validate(raw)


def test_a_repeated_prompt_pin_is_tolerated_but_a_conflicting_one_is_not() -> None:
    """The frozen v1 validator compared a *set* of pins; that acceptance is preserved exactly.

    A contact prompt embeds untrusted prior research context, so the same ``alias=field.key`` text
    can legitimately appear twice. Only a second field key for one alias is a real contradiction.
    """

    raw = _json("deep_request.json")
    prompt = raw["systemPrompt"]
    assert isinstance(prompt, str)
    pain = exa_field_alias("account.operational_pain")

    repeated = dict(raw)
    repeated["systemPrompt"] = f"{prompt} Repeated pin: {pain}=account.operational_pain."
    ExaDeepSearchRequest.model_validate(repeated)

    conflicting = dict(raw)
    conflicting["systemPrompt"] = f"{prompt} Conflicting pin: {pain}=account.strategic_moves."
    with pytest.raises(ValidationError, match="two field keys"):
        ExaDeepSearchRequest.model_validate(conflicting)
