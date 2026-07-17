"""M4.4 — per-provider normalization (DB-free; the response → typed-claim mapping per resolver).

These exercise the *normalization* deliverable directly with representative response fixtures (the
"recorded fixtures / doubles" the spec calls for): each provider's own response shape → provider-
agnostic :class:`ResolvedField`\\s, a hard miss → ``[]`` (never fabricated), and the span +
citing url. No DB, no network — pure functions, so they run on every ``make check``.
"""

from __future__ import annotations

import pytest

from clue_core import FieldDef, PassKind, UseClass
from clue_research.resolvers import apollo, builtwith, clay, zoominfo
from clue_research.resolvers.registries import CIK, DUNS, LEI, NPI, registry_normalize


def _field(field_key: str, value_type: str = "str") -> FieldDef:
    return FieldDef(field_key=field_key, value_type=value_type, pass_kind=PassKind.SCORING)


# --- Clay ----------------------------------------------------------------------------------------

_CLAY = {
    "employee_count": 1200,
    "work_email": "jordan@acme.com",
    "technologies": ["snowflake", "dbt"],
    "match_confidence": 0.93,
    "record_url": "https://app.clay.com/r/abc",
}


def test_clay_normalizes_served_field() -> None:
    (rf,) = clay.normalize(_CLAY, _field("core.employee_count", "int"))
    assert rf.field_key == "core.employee_count"
    assert rf.value == 1200
    assert rf.confidence == pytest.approx(0.93)
    assert rf.source_url == "https://app.clay.com/r/abc"
    assert rf.evidence_span and "core.employee_count" in rf.evidence_span  # grounded, non-empty


def test_clay_unserved_field_is_empty() -> None:
    assert clay.normalize(_CLAY, _field("account.recent_funding")) == []


def test_clay_absent_value_is_a_hard_miss() -> None:
    assert clay.normalize({"match_confidence": 0.9}, _field("core.employee_count", "int")) == []


def test_clay_falls_back_to_default_confidence() -> None:
    (rf,) = clay.normalize({"work_email": "a@b.com"}, _field("core.work_email"))
    assert rf.confidence == pytest.approx(clay._DEFAULT_CONFIDENCE)


# --- Apollo (distinct response shape — proves normalization differs per provider) -----------------


def test_apollo_normalizes_its_own_shape() -> None:
    payload = {"estimated_num_employees": 500, "confidence": 0.95, "apollo_url": "https://x"}
    (rf,) = apollo.normalize(payload, _field("core.employee_count", "int"))
    assert rf.value == 500 and rf.confidence == pytest.approx(0.95)


def test_apollo_funding_builds_the_registered_object_shape() -> None:
    # account.recent_funding's value_schema is an object (required amount_usd) — a string would be
    # rejected by insert_claim, so the resolver must emit the object shape.
    payload = {"funding_total_usd": 50_000_000, "latest_funding_stage": "Series B"}
    (rf,) = apollo.normalize(payload, _field("account.recent_funding", "object"))
    assert rf.value == {"amount_usd": 50_000_000, "round": "Series B"}


def test_apollo_funding_without_amount_is_a_miss() -> None:
    # Only a stage, no amount → cannot satisfy the required-amount_usd schema → hard miss, not a
    # malformed claim (it falls through to a deeper source).
    assert (
        apollo.normalize({"latest_funding_stage": "Series B"}, _field("account.recent_funding"))
        == []
    )


def test_normalize_coerces_malformed_provider_confidence() -> None:
    # A present-but-bad confidence must not crash the bounded Confidence type outside the fault
    # taxonomy: out-of-range clamps, non-numeric falls back to the provider default.
    (over,) = clay.normalize(
        {"employee_count": 5, "match_confidence": 1.5}, _field("core.employee_count", "int")
    )
    assert over.confidence == 1.0
    (bad,) = clay.normalize(
        {"employee_count": 5, "match_confidence": "n/a"}, _field("core.employee_count", "int")
    )
    assert bad.confidence == pytest.approx(clay._DEFAULT_CONFIDENCE)


# --- ZoomInfo ------------------------------------------------------------------------------------


def test_zoominfo_normalizes_work_email() -> None:
    payload = {"email": "j@acme.com", "match_score": 0.9}
    (email,) = zoominfo.normalize(payload, _field("core.work_email"))
    assert email.value == "j@acme.com" and email.use_class is UseClass.PROFESSIONAL_PUBLIC


def test_zoominfo_only_maps_registered_fields() -> None:
    # contact.title is not a registered field — ZoomInfo must not emit a claim a write would reject.
    assert zoominfo.normalize({"jobTitle": "VP Eng"}, _field("contact.title")) == []


# --- BuiltWith ------------------------------------------------------------------------------------


def test_builtwith_normalizes_tech_stack() -> None:
    payload = {"technologies": ["snowflake", "dbt"], "confidence": 0.92}
    (rf,) = builtwith.normalize(payload, _field("core.primary_tech_stack", "list"))
    assert rf.value == ["snowflake", "dbt"]


def test_builtwith_empty_stack_is_a_hard_miss() -> None:
    assert (
        builtwith.normalize({"technologies": []}, _field("core.primary_tech_stack", "list")) == []
    )


# --- Registries (id extraction; served-field gating; vertical-specific) ---------------------------


@pytest.mark.parametrize(
    ("spec", "payload", "field_key"),
    [
        (NPI, {"npi": "1234567890"}, "healthcare.npi"),
        (DUNS, {"duns_number": "123456789"}, "account.duns_number"),
        (CIK, {"cik": "0000320193"}, "account.cik"),
        (LEI, {"lei": "5493001KJTIIGC8Y1R12"}, "account.lei"),
    ],
)
def test_registry_returns_id_for_its_served_field(
    spec: object, payload: dict[str, str], field_key: str
) -> None:
    (rf,) = registry_normalize(payload, _field(field_key), spec=spec)  # type: ignore[arg-type]
    assert rf.value == next(iter(payload.values()))
    assert rf.confidence == pytest.approx(0.97)  # authoritative → high


def test_registry_ignores_a_non_served_field() -> None:
    assert registry_normalize({"npi": "1234567890"}, _field("core.employee_count"), spec=NPI) == []


def test_registry_missing_id_is_a_hard_miss() -> None:
    assert registry_normalize({}, _field("healthcare.npi"), spec=NPI) == []
