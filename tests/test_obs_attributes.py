"""M0.5: attribute coercion + redaction (UUID ids stay native; secrets are masked)."""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

from clue_research.core import EntityType
from clue_research.obs import safe_attributes, to_otel_value


def test_to_otel_value_coercions() -> None:
    assert to_otel_value(None) is None
    assert to_otel_value(True) is True
    assert to_otel_value(3) == 3
    assert to_otel_value(1.5) == 1.5
    assert to_otel_value(EntityType.ACCOUNT) == "account"  # StrEnum -> value
    some_uuid = uuid4()
    assert to_otel_value(some_uuid) == str(some_uuid)
    assert to_otel_value(Decimal("1.50")) == "1.50"


def test_safe_attributes_keeps_standard_native_and_redacts_secrets() -> None:
    eid = uuid4()
    out = safe_attributes(
        {
            "entity_id": eid,  # standard UUID -> str, NOT masked
            "source_tier": 1,  # standard int -> native
            "entity_type": EntityType.CONTACT,  # standard enum -> "contact"
            "api_key": "whatever",  # secret-named key -> masked regardless of value
            "note": "sk-live-aaaaaaaaaaaaaaaaaaaa",  # extra, value looks secret -> masked
            "label": "north-america",  # extra, benign -> kept
            "skip": None,  # dropped
        }
    )
    assert out["entity_id"] == str(eid)
    assert out["source_tier"] == 1
    assert out["entity_type"] == "contact"
    assert out["api_key"] == "***REDACTED***"
    assert out["note"] == "***REDACTED***"
    assert out["label"] == "north-america"
    assert "skip" not in out
