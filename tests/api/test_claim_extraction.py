"""The production LLM claim extractor (slice 3, task 4) — pure, no DB.

The guarantee under test is the *anti-lane-failure* one: ``run_pipeline._extract`` raises
``AdaptError`` for any draft whose ``evidence_span`` is not a substring of the normalized text, and
an escaped ``AdaptError`` fails the whole Stage-0 recon lane. So an ungrounded, wrongly-shaped,
low-confidence or unparseable model answer must be **dropped**, never raised — and a gateway outage
must yield an honest empty list, not a failed lane.
"""

from __future__ import annotations

import json

import pytest

from clue_api.claim_extraction import (
    EXTRACTION_PROMPT_VERSION,
    EXTRACTION_PROMPTS,
    ExtractionPolicy,
    LlmClaimExtractor,
    build_extraction_messages,
    parse_extraction_response,
)
from clue_config.gateway import GatewayConfig
from clue_core import Entity, EntityType, FieldDef, NormalizedText, PassKind, new_entity_id
from clue_core.gateway import Completion, EmbeddingResult, Message, Role
from clue_gateway.stub import StubGateway
from clue_research.adapters import ClaimExtractor
from clue_research.stage0.fields import (
    CLIENT_CUSTOMER,
    CLIENT_ICP_EVIDENCE,
    CLIENT_VALUE_PROP,
)

PAGE = "Acme automates repetitive operational work for finance teams. Trusted by Globex."


class FakeGateway:
    """A :class:`~clue_core.gateway.LLMGateway` returning a canned completion.

    Copied (deliberately, per the task brief) from ``tests/stage0/_fakes.py`` so this suite stays a
    pure unit test with no cross-suite fixture import. ``raise_exc`` makes ``complete`` raise so the
    honest-empty degradation path is exercised; ``calls`` records ``(model, messages)``.
    """

    def __init__(self, text: str = "", *, raise_exc: bool = False) -> None:
        self._text = text
        self._raise = raise_exc
        self.calls: list[tuple[str, list[Message]]] = []

    def complete(self, *, model: str, messages: list[Message], **opts: object) -> Completion:
        self.calls.append((model, messages))
        if self._raise:
            raise RuntimeError("synthetic gateway failure")
        return Completion(model=model, text=self._text)

    def embed(self, *, model: str, inputs: list[str]) -> EmbeddingResult:
        return EmbeddingResult(model=model)


def _normalized(text: str = PAGE) -> NormalizedText:
    return NormalizedText(text=text)


def _entity() -> Entity:
    return Entity(entity_id=new_entity_id(), entity_type=EntityType.ACCOUNT)


def _field(key: str = CLIENT_VALUE_PROP, value_type: str = "str") -> FieldDef:
    return FieldDef(field_key=key, value_type=value_type, pass_kind=PassKind.SCORING)


def _response(*claims: dict[str, object]) -> str:
    return json.dumps({"claims": list(claims)})


def _policy() -> ExtractionPolicy:
    """A policy with a pinned model id (never reads deploy settings from a unit test)."""
    return ExtractionPolicy(extraction_model="test/model")


def _extractor(gateway: object, policy: ExtractionPolicy | None = None) -> LlmClaimExtractor:
    return LlmClaimExtractor(gateway=gateway, policy=policy or _policy())  # type: ignore[arg-type]


# --- the happy path ---------------------------------------------------------


def test_grounded_claim_is_extracted_with_exact_span() -> None:
    quote = "Acme automates repetitive operational work"
    gateway = FakeGateway(
        text=_response(
            {
                "value": "Acme automates repetitive operational work for finance teams",
                "quote": quote,
                "source_url": None,
                "confidence": 0.9,
            }
        )
    )

    drafts = _extractor(gateway).extract(_normalized(), _entity(), _field())

    assert len(drafts) == 1
    draft = drafts[0]
    assert draft.field_key == CLIENT_VALUE_PROP
    assert draft.evidence_span == quote
    # the pipeline's grounding assertion, restated: this is what must never raise AdaptError
    assert draft.evidence_span in _normalized().text
    assert draft.confidence == pytest.approx(0.9)
    assert draft.source_url is None


def test_source_url_from_a_result_header_is_carried() -> None:
    """Forward compat for the Exa resolver: the url is parsed and carried, never invented."""
    text = "### RESULT 1 | url: https://acme.example/about\nAcme automates repetitive work."
    gateway = FakeGateway(
        text=_response(
            {
                "value": "Acme automates repetitive work",
                "quote": "Acme automates repetitive work.",
                "source_url": "https://acme.example/about",
                "confidence": 0.8,
            }
        )
    )

    drafts = _extractor(gateway).extract(_normalized(text), _entity(), _field())

    assert [d.source_url for d in drafts] == ["https://acme.example/about"]


def test_extractor_satisfies_the_claim_extractor_seam() -> None:
    assert isinstance(_extractor(FakeGateway(text=_response())), ClaimExtractor)


# --- drop, never raise ------------------------------------------------------


def test_paraphrased_quote_is_dropped_never_raised() -> None:
    """The anti-AdaptError guarantee: an ungrounded span never reaches the pipeline."""
    gateway = FakeGateway(
        text=_response({"value": "x", "quote": "a paraphrase not in the page", "confidence": 0.9})
    )

    assert _extractor(gateway).extract(_normalized("real page text"), _entity(), _field()) == []


def test_empty_or_blank_quote_is_dropped() -> None:
    gateway = FakeGateway(
        text=_response(
            {"value": "x", "quote": "", "confidence": 0.9},
            {"value": "y", "quote": "   ", "confidence": 0.9},
            {"value": "z", "confidence": 0.9},
        )
    )

    assert _extractor(gateway).extract(_normalized("   real page text"), _entity(), _field()) == []


def test_malformed_json_and_stub_gateway_yield_empty() -> None:
    for text in ("", "not json at all", "{oops", '{"claims": "not-a-list"}', "[]"):
        assert _extractor(FakeGateway(text=text)).extract(_normalized(), _entity(), _field()) == []

    # The deterministic CI gateway answers ``stub:<sha>`` — unparseable, so honestly empty.
    stub = StubGateway(GatewayConfig())
    assert _extractor(stub).extract(_normalized(), _entity(), _field()) == []


def test_wrong_value_shape_is_dropped() -> None:
    """``client.customer`` is an array of ``{"name", "domain"?}`` objects — nothing else."""
    quote = "Trusted by Globex."
    field = _field(CLIENT_CUSTOMER, value_type="list")
    bad = FakeGateway(
        text=_response(
            {"value": "Globex", "quote": quote, "confidence": 0.9},
            {"value": ["Globex"], "quote": quote, "confidence": 0.9},
            {"value": [{"domain": "globex.example"}], "quote": quote, "confidence": 0.9},
        )
    )
    assert _extractor(bad).extract(_normalized(), _entity(), field) == []

    good = FakeGateway(
        text=_response(
            {
                "value": [{"name": "Globex", "domain": "globex.example"}],
                "quote": quote,
                "confidence": 0.9,
            }
        )
    )
    assert [d.value for d in _extractor(good).extract(_normalized(), _entity(), field)] == [
        [{"name": "Globex", "domain": "globex.example"}]
    ]


def test_icp_evidence_object_shape_is_enforced() -> None:
    quote = "Trusted by Globex."
    field = _field(CLIENT_ICP_EVIDENCE, value_type="object")
    bad = FakeGateway(
        text=_response(
            {"value": {"unrelated": ["x"]}, "quote": quote, "confidence": 0.9},
            {"value": {"industries": "finance"}, "quote": quote, "confidence": 0.9},
        )
    )
    assert _extractor(bad).extract(_normalized(), _entity(), field) == []

    good = FakeGateway(
        text=_response({"value": {"industries": ["finance"]}, "quote": quote, "confidence": 0.9})
    )
    assert len(_extractor(good).extract(_normalized(), _entity(), field)) == 1


def test_icp_evidence_tolerates_a_null_for_an_unevidenced_key() -> None:
    """A model spelling "not stated" as ``null`` must not cost the whole claim."""
    quote = "Trusted by Globex."
    field = _field(CLIENT_ICP_EVIDENCE, value_type="object")
    gateway = FakeGateway(
        text=_response(
            {
                "value": {"industries": ["finance"], "sizes": None, "geos": None},
                "quote": quote,
                "confidence": 0.9,
            },
            # ...but an object with nothing evidenced at all is not a claim.
            {"value": {"industries": None}, "quote": quote, "confidence": 0.9},
        )
    )

    drafts = _extractor(gateway).extract(_normalized(), _entity(), field)

    assert [d.value for d in drafts] == [{"industries": ["finance"], "sizes": None, "geos": None}]


def test_repeated_claims_are_emitted_once() -> None:
    quote = "Trusted by Globex."
    field = _field("client.competitor", value_type="object")
    gateway = FakeGateway(
        text=_response(
            {"value": {"name": "Rival"}, "quote": quote, "confidence": 0.9},
            {"value": {"name": "Rival"}, "quote": quote, "confidence": 0.7},
            {"value": {"name": "Other"}, "quote": quote, "confidence": 0.9},
        )
    )

    drafts = _extractor(gateway).extract(_normalized(), _entity(), field)

    assert [d.value for d in drafts] == [{"name": "Rival"}, {"name": "Other"}]


def test_unknown_field_key_yields_empty_without_calling_the_gateway() -> None:
    gateway = FakeGateway(text=_response({"value": "x", "quote": PAGE[:10], "confidence": 0.9}))

    assert _extractor(gateway).extract(_normalized(), _entity(), _field("account.headcount")) == []
    assert gateway.calls == []


def test_gateway_error_yields_empty_not_lane_failure() -> None:
    assert _extractor(FakeGateway(raise_exc=True)).extract(_normalized(), _entity(), _field()) == []


def test_low_confidence_dropped_and_cap_applies() -> None:
    quote = "Acme automates repetitive operational work"
    other = "Trusted by Globex."
    gateway = FakeGateway(
        text=_response(
            {"value": "low", "quote": quote, "confidence": 0.1},
            {"value": "kept", "quote": quote, "confidence": 0.8},
            {"value": "also kept but capped", "quote": other, "confidence": 0.8},
        )
    )

    drafts = _extractor(gateway).extract(_normalized(), _entity(), _field())

    # a string field carries one value: the first surviving claim only
    assert [d.value for d in drafts] == ["kept"]


def test_a_multi_valued_field_is_capped_at_the_policy_maximum() -> None:
    quote = "Trusted by Globex."
    field = _field("client.competitor", value_type="object")
    gateway = FakeGateway(
        text=_response(
            *(
                {"value": {"name": f"Rival {n}"}, "quote": quote, "confidence": 0.9}
                for n in range(5)
            )
        )
    )

    policy = ExtractionPolicy(extraction_model="test/model", max_claims_per_field=2)
    drafts = _extractor(gateway, policy).extract(_normalized(), _entity(), field)

    assert [d.value for d in drafts] == [{"name": "Rival 0"}, {"name": "Rival 1"}]


def test_buyer_profile_shape() -> None:
    quote = "Trusted by Globex."
    field = _field("client.buyer_profile", value_type="object")
    gateway = FakeGateway(
        text=_response(
            {"value": {"segment": "mid-market"}, "quote": quote, "confidence": 0.9},
            {"value": {"persona": "Head of Finance Ops"}, "quote": quote, "confidence": 0.9},
        )
    )

    drafts = _extractor(gateway).extract(_normalized(), _entity(), field)

    assert [d.value for d in drafts] == [{"persona": "Head of Finance Ops"}]


def test_out_of_range_and_non_numeric_confidence_never_raise() -> None:
    quote = "Trusted by Globex."
    gateway = FakeGateway(
        text=_response(
            {"value": "a", "quote": quote, "confidence": "high"},
            {"value": "b", "quote": quote, "confidence": 7},
        )
    )

    drafts = _extractor(gateway).extract(_normalized(), _entity(), _field())

    # the non-numeric one is dropped; the out-of-range one is clamped into 0..1, never a raise
    assert [(d.value, d.confidence) for d in drafts] == [("b", 1.0)]


# --- the prompt -------------------------------------------------------------


def test_prompt_fences_untrusted_text_and_names_the_field() -> None:
    messages = build_extraction_messages(_normalized(), _field())

    assert [m.role for m in messages] == [Role.SYSTEM, Role.USER]
    system, user = messages[0].content, messages[1].content
    assert "SECURITY" in system
    assert "claims" in system  # the JSON contract is stated
    assert "<<<PAGE_TEXT>>>" in user and "<<<END_PAGE_TEXT>>>" in user
    assert PAGE in user
    assert CLIENT_VALUE_PROP in user
    # the registry description is the field guidance the model is given
    assert "What the client sells and the problem it solves" in user
    assert system == EXTRACTION_PROMPTS[EXTRACTION_PROMPT_VERSION]


def test_unknown_prompt_version_fails_loud() -> None:
    with pytest.raises(ValueError, match="prompt_version"):
        build_extraction_messages(_normalized(), _field(), prompt_version="v0")


def test_extraction_uses_the_policy_model() -> None:
    gateway = FakeGateway(text=_response())

    _extractor(gateway).extract(_normalized(), _entity(), _field())

    assert [model for model, _ in gateway.calls] == ["test/model"]


def test_parse_is_total_over_junk() -> None:
    """``parse_extraction_response`` never raises — the whole drop-never-raise posture in one fn."""
    junk = [
        '{"claims": [null]}',
        '{"claims": [{"value": null, "quote": null}]}',
        '{"claims": [[]]}',
        '{"claims": [{"quote": 5, "value": "x", "confidence": 0.9}]}',
        "{}",
    ]
    for text in junk:
        assert parse_extraction_response(text, PAGE, _field(), policy=_policy()) == []
