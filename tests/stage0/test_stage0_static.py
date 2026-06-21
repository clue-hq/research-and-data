"""Pure (no-DB) tests for M5.1 — the field set, reuse policy, surface taxonomy, and helpers.

These run in the default ``make check`` (no database required) and pin the invariants the DB-backed
reverse-profiling tests rely on.
"""

from __future__ import annotations

from clue_research.core import ExtractionMethod, ReuseScope, can_be_promoted, new_campaign_run_id
from clue_research.core.field import classify_field_key, is_valid_field_key
from clue_research.identity import DEFAULT_REUSE_POLICY, classify_reuse_scope
from clue_research.stage0 import (
    CLIENT_KB_VERSION,
    CLIENT_KNOWLEDGE_FIELDS,
    CLIENT_KNOWLEDGE_PACK,
    CLIENT_KNOWLEDGE_REUSE_POLICY,
    SURFACE_CLASS_FIELDS,
    ClientInput,
    SurfaceClass,
    VolunteeredMaterial,
    reverse_profiling_run_id,
)
from clue_research.stage0.reverse_profiling_handler import _client_input_from_params
from tests.stage0._fakes import make_tier4_claim


def test_client_field_keys_are_wellformed_and_packed() -> None:
    pack_keys = {sf.field_def.field_key for sf in CLIENT_KNOWLEDGE_PACK}
    # every client.* field is a valid namespaced key, classifies as PACK, declares pack=client
    for sf in CLIENT_KNOWLEDGE_PACK:
        key = sf.field_def.field_key
        assert is_valid_field_key(key), key
        assert key.startswith("client.")
        assert sf.pack == "client", key
    # the marker is registered but excluded from the substantive knowledge field set
    assert CLIENT_KB_VERSION in pack_keys
    assert CLIENT_KB_VERSION not in CLIENT_KNOWLEDGE_FIELDS
    assert set(CLIENT_KNOWLEDGE_FIELDS) | {CLIENT_KB_VERSION} == pack_keys


def test_client_field_class_is_pack() -> None:
    # `client` is not a canonical namespace, so it classifies as a vertical pack field-class.
    assert classify_field_key("client.value_prop").value == "pack"


def test_client_knowledge_is_tenant_private_under_stage0_policy() -> None:
    # The whole point of CLIENT_KNOWLEDGE_REUSE_POLICY: client.* is private (client-knowledge),
    # whereas the M2 default would leak it public.
    for field_key in CLIENT_KNOWLEDGE_FIELDS:
        assert (
            classify_reuse_scope(
                field_key, ExtractionMethod.SCRAPE, 2, policy=CLIENT_KNOWLEDGE_REUSE_POLICY
            )
            is ReuseScope.TENANT_PRIVATE
        )
        assert (
            classify_reuse_scope(field_key, ExtractionMethod.SCRAPE, 2, policy=DEFAULT_REUSE_POLICY)
            is ReuseScope.PUBLIC_FOOTPRINT
        )


def test_client_fields_declare_tenant_private_scope() -> None:
    # ENG-165: a <pack>.* field has NO safe default reuse_scope, and the claim-write boundary is
    # fail-closed — so every client-knowledge field must DECLARE tenant_private or no client claim
    # could be written at all. Guards against an undeclared field silently failing closed.
    from clue_research.core.field import resolve_reuse_scope

    for sf in CLIENT_KNOWLEDGE_PACK:
        assert sf.field_def.reuse_scope is ReuseScope.TENANT_PRIVATE, sf.field_def.field_key
        assert resolve_reuse_scope(sf.field_def) is ReuseScope.TENANT_PRIVATE


def test_surface_taxonomy_covers_all_four_surfaces_and_all_fields() -> None:
    assert set(SURFACE_CLASS_FIELDS) == set(SurfaceClass)
    mapped = {f for fields in SURFACE_CLASS_FIELDS.values() for f in fields}
    # every substantive client field is attributed to exactly one surface class
    assert mapped == set(CLIENT_KNOWLEDGE_FIELDS)
    counts = [f for fields in SURFACE_CLASS_FIELDS.values() for f in fields]
    assert len(counts) == len(set(counts)), "a field is double-mapped across surfaces"


def test_reverse_profiling_run_id_is_deterministic() -> None:
    crid = new_campaign_run_id()
    assert reverse_profiling_run_id(crid) == reverse_profiling_run_id(crid)
    assert reverse_profiling_run_id(crid) != reverse_profiling_run_id(new_campaign_run_id())


def test_client_input_from_params_nested_and_flat() -> None:
    nested = _client_input_from_params(
        {"client_input": {"name": "Acme", "website": "https://acme.example"}}
    )
    assert nested == ClientInput(name="Acme", website="https://acme.example")

    flat = _client_input_from_params(
        {
            "name": "Acme",
            "website": "https://acme.example",
            "materials": [{"kind": "deck", "asserted_fields": {"client.value_prop": "x"}}],
        }
    )
    assert flat.name == "Acme"
    assert flat.materials[0].asserted_fields == {"client.value_prop": "x"}


def test_volunteered_material_defaults() -> None:
    m = VolunteeredMaterial(asserted_fields={"client.value_prop": "we sell X"})
    assert m.kind == "document"
    assert m.content is None


def test_tier4_promotion_predicate() -> None:
    # A span-less tier-4 claim can never be promoted (the structural fabrication kill-switch);
    # with a span it becomes structurally eligible (M9 still decides the actual transition).
    assert not can_be_promoted(
        make_tier4_claim(_an_id(), "account.operational_pain", with_span=False)
    )
    assert can_be_promoted(make_tier4_claim(_an_id(), "account.operational_pain", with_span=True))


def _an_id() -> object:
    from clue_research.core import new_entity_id

    return new_entity_id()
