"""D1 contract-delta on clue_core.Claim (master plan §4) and Persona.USER (D8)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from clue_core import (
    Claim,
    EntityType,
    ExtractionMethod,
    Persona,
    ResearchMode,
    ReuseScope,
    can_be_promoted,
    new_entity_id,
    new_run_id,
)


def _claim(**overrides: object) -> Claim:
    base: dict[str, object] = {
        "entity_id": new_entity_id(),
        "entity_type": EntityType.ACCOUNT,
        "field_key": "core.account_name",
        "value_json": "Zafran Security",
        "source_url": "https://zafran.io/about",
        "source_tier": 1,
        "extraction_method": ExtractionMethod.API,
        "confidence": 0.9,
        "run_id": new_run_id(),
        "research_mode": ResearchMode.ACCOUNT_PROFILING,
        "reuse_scope": ReuseScope.TENANT_PRIVATE,
        "workspace_id": "ws_test",
    }
    base.update(overrides)
    return Claim(**base)  # type: ignore[arg-type]


def test_persona_has_user() -> None:
    assert Persona("user") is Persona.USER
    assert [p.value for p in Persona] == [
        "champion",
        "economic_buyer",
        "technical_evaluator",
        "blocker",
        "user",
    ]


def test_new_fields_default_and_validate() -> None:
    claim = _claim()
    assert claim.signal_priority == 3
    assert claim.outreach_safe is True
    assert claim.write_markers is None
    stamped = _claim(signal_priority=1, outreach_safe=False, write_markers={"source_missing": True})
    assert stamped.signal_priority == 1
    assert stamped.outreach_safe is False
    assert stamped.write_markers == {"source_missing": True}
    with pytest.raises(ValidationError):
        _claim(signal_priority=0)
    with pytest.raises(ValidationError):
        _claim(signal_priority=4)


def test_an_api_claim_may_exist_without_a_url_but_cannot_be_promoted() -> None:
    claim = _claim(source_url=None, write_markers={"source_missing": True})
    assert claim.source_url is None
    assert can_be_promoted(claim) is False
    assert can_be_promoted(_claim(source_url="https://api.example.com/v1/companies")) is True


def test_a_synthesis_claim_without_a_url_cannot_be_promoted() -> None:
    claim = _claim(
        source_tier=4,
        extraction_method=ExtractionMethod.LLM_SYNTHESIS,
        evidence_span="Zafran Security, a Tel Aviv vulnerability-management vendor",
        source_url=None,
    )
    assert can_be_promoted(claim) is False


def test_a_human_claim_needs_no_url_and_is_promotable() -> None:
    claim = _claim(extraction_method=ExtractionMethod.HUMAN, source_url=None)
    assert can_be_promoted(claim) is True
