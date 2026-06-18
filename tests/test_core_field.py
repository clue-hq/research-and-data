"""M0.2 acceptance: the field-key namespace helper (open registry) and FieldDef."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from clue_research.core import (
    FieldClass,
    FieldDef,
    PassKind,
    classify_field_key,
    field_key,
    field_namespace,
    is_pack_registered,
    is_valid_field_key,
    register_pack,
)


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("core.employee_count", FieldClass.CORE),
        ("account.recent_funding", FieldClass.ACCOUNT),
        ("account.resonance.culture", FieldClass.ACCOUNT_RESONANCE),
        ("contact.role_on_committee", FieldClass.CONTACT),
        ("contact.facet.recent_post", FieldClass.CONTACT_FACET),
        ("healthcare.npi", FieldClass.PACK),
        ("frontier_ai.arxiv_activity", FieldClass.PACK),
    ],
)
def test_classify_field_key(key: str, expected: FieldClass) -> None:
    assert is_valid_field_key(key)
    assert classify_field_key(key) is expected


def test_resonance_and_facet_classify_before_their_parents() -> None:
    # longest-prefix wins: account.resonance.* is NOT plain account.*
    assert classify_field_key("account.resonance.sentiment") is FieldClass.ACCOUNT_RESONANCE
    assert classify_field_key("contact.facet.hobby") is FieldClass.CONTACT_FACET


@pytest.mark.parametrize(
    "bad", ["", "core", "Acme Corp", "Account.Funding", "core..x", ".core.x", "core.x.", "1core.x"]
)
def test_malformed_keys_are_rejected(bad: str) -> None:
    assert not is_valid_field_key(bad)


def test_field_namespace() -> None:
    assert field_namespace("account.resonance.culture") == "account.resonance"
    assert field_namespace("account.recent_funding") == "account"
    assert field_namespace("healthcare.npi") == "healthcare"


def test_field_key_builder_validates() -> None:
    assert field_key("account", "recent_funding") == "account.recent_funding"
    assert field_key("account", "resonance", "culture") == "account.resonance.culture"
    with pytest.raises(ValueError, match="invalid field_key"):
        field_key("Bad Namespace", "x")


def test_pack_registration_is_open() -> None:
    assert not is_pack_registered("logistics")
    register_pack("logistics")
    assert is_pack_registered("logistics")
    # registering does not change classification — packs are open
    assert classify_field_key("logistics.fleet_size") is FieldClass.PACK
    with pytest.raises(ValueError, match="invalid pack"):
        register_pack("Bad Pack")


def test_field_def_round_trips_and_rejects_bad_key() -> None:
    fd = FieldDef(
        field_key="account.hiring_velocity_eng",
        value_type="int",
        tier_plan=("jobs_api", "site_scrape", "llm"),
        pass_kind=PassKind.DEEP,
        gate="tier>=1",
    )
    assert fd.field_class is FieldClass.ACCOUNT
    assert FieldDef.model_validate(fd.model_dump()) == fd
    with pytest.raises(ValidationError):
        FieldDef(field_key="not a key", value_type="int", pass_kind=PassKind.SCORING)
