"""S3: every field the answer keys and the display recipes use is a registered row."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from clue_api.arv2.catalog_seed import ARV2_FIELD_KEYS, ARV2_PACK, load_arv2_pack
from clue_core import FieldClass, classify_field_key
from clue_research.claimstore.packs import CORE_PACK
from clue_research.claimstore.registry import validate_value_against_schema
from clue_research.profiling.committee.fields import COMMITTEE_PACK
from clue_research.profiling.fields import DEEP_PROFILING_PACK

# The claim-store harness lives in a sibling test package; a fixture is only visible to a module
# that imports it, so re-export both (``require_claimstore_db`` depends on ``migrated_db``).
from tests.claimstore.conftest import (  # noqa: F401
    migrated_db,
    require_claimstore_db,
)

REPO = Path(__file__).resolve().parents[2]
ZAFRAN = REPO / ".context/arv2-one-account-aiark/claims_zafran.json"
PEOPLE = REPO / ".context/arv2-person-depth/claims_people.json"

_REGISTERED_ELSEWHERE = {
    str(seed.field_def.field_key) for seed in (*CORE_PACK, *DEEP_PROFILING_PACK, *COMMITTEE_PACK)
}


def _answer_key_field_keys() -> set[str]:
    keys: set[str] = set()
    for row in json.loads(ZAFRAN.read_text())["claims"]:
        key = row["field_key"].removeprefix("PROPOSED::")
        keys.update(key.split("|"))
    for person in json.loads(PEOPLE.read_text())["people"].values():
        for row in person["claims"]:
            keys.update(row["field_key"].split("|"))
    return keys


def test_pack_covers_every_answer_key_field_not_registered_elsewhere() -> None:
    missing = _answer_key_field_keys() - _REGISTERED_ELSEWHERE - ARV2_FIELD_KEYS
    assert not missing, sorted(missing)


def test_r2_account_keys_are_registered_in_the_pack() -> None:
    """R2 writes the committee candidates and the fit verdict as ordinary registered fields."""
    assert {
        "account.committee_candidate",
        "account.icp_fit_verdict",
        "account.committee_search_assessment",
    } <= ARV2_FIELD_KEYS
    assert len(ARV2_FIELD_KEYS) == 41


def test_a_vacant_committee_seat_is_a_valid_committee_candidate() -> None:
    """A vacant seat carries no name and needs no URL: "nobody holds this role" is a finding about
    the account, not an assertion about a person. Only ``persona`` identifies the row."""
    seed = next(s for s in ARV2_PACK if str(s.field_def.field_key) == "account.committee_candidate")
    assert seed.value_schema is not None
    assert seed.value_schema["required"] == ["persona"]

    validate_value_against_schema(
        {"persona": "economic_buyer", "title": "CFO", "vacant_seat": True}, seed.value_schema
    )
    validate_value_against_schema(
        {
            "name": "Nick Fisher",
            "persona": "champion",
            "confirmed_by": "https://probook.ai/about",
            "vacant_seat": False,
        },
        seed.value_schema,
    )


def test_pack_does_not_redefine_an_existing_key() -> None:
    assert not (ARV2_FIELD_KEYS & _REGISTERED_ELSEWHERE)


def test_every_row_is_canonical_optional_and_facets_are_governed() -> None:
    for seed in ARV2_PACK:
        key = str(seed.field_def.field_key)
        assert classify_field_key(key) is not FieldClass.PACK, key
        assert seed.pack is None, key
        assert seed.description, key
        schema = seed.value_schema
        assert schema is not None, key
        assert isinstance(schema["type"], str), key  # never a list-valued type
        if classify_field_key(key) is FieldClass.CONTACT_FACET:
            assert seed.field_def.validation is not None, key
            assert "use_class_hint" in seed.field_def.validation, key
            assert seed.field_def.freshness_ttl is not None, key
            assert seed.field_def.freshness_ttl < timedelta(days=90), key


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("account.open_requisitions", [{"title": "Senior Manager, ABM", "days_open": 105}]),
        ("account.gtm_tooling_stack", {"present": ["HubSpot"], "absent": ["6sense"]}),
        ("account.named_customers", ["OpenAI"]),
        ("account.reputation_risk", {"what": "Cisco acquisition rumor", "status": "REFUTED"}),
        ("core.founded_year", 2022),
        ("core.legal_name", "Zafran Security Ltd."),
        (
            "contact.facet.voice_quote",
            {"text": "…", "media_url": "https://x", "media_timestamp": "05:14"},
        ),
        ("contact.facet.hooks", ["Congrats on the raise"]),
        ("contact.facet.openers", ["Saw your post"]),
        ("contact.facet.certifications", ["6sense certified"]),
        ("contact.facet.education_highschool", "Oregon Episcopal School"),
        ("contact.facet.self_summary", "Marketer by title, builder at heart"),
        (
            "contact.facet.excluded_lookalike",
            {"discarded_media": "https://y", "title": "Not him"},
        ),
        ("contact.facet.best_channel", "email"),
        ("contact.reports_to", {"contact_id": "0b8a3e2c-0000-0000-0000-000000000000"}),
    ],
)
def test_sample_values_pass_their_schemas(key: str, value: object) -> None:
    seed = next(s for s in ARV2_PACK if str(s.field_def.field_key) == key)
    assert seed.value_schema is not None
    validate_value_against_schema(value, seed.value_schema)


def test_register_arv2_wiring_appends_the_pack_idempotently() -> None:
    """Both production entrypoints call this; a second call must not duplicate the loader."""
    from clue_api import composition
    from clue_api.arv2_wiring import register_arv2_wiring

    saved = list(composition.RESEARCH_PACK_LOADERS)
    try:
        composition.RESEARCH_PACK_LOADERS[:] = [
            loader for loader in saved if loader is not load_arv2_pack
        ]
        register_arv2_wiring()
        register_arv2_wiring()
        assert composition.RESEARCH_PACK_LOADERS.count(load_arv2_pack) == 1
    finally:
        composition.RESEARCH_PACK_LOADERS[:] = saved  # never leak global state to sibling tests


@pytest.mark.usefixtures("require_claimstore_db")
def test_pack_loads_idempotently() -> None:
    from tests.claimstore.conftest import rollback_conn
    from tests.db.conftest import run_async

    async def _run() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            await load_arv2_pack(conn)
            await load_arv2_pack(conn)  # second load is a no-op, never a redefinition

    run_async(_run())
