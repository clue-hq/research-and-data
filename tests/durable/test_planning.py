"""Pure tests for the orchestrator/lead's plan-building (M7.1) — no DB.

``build_plan`` clusters gap fields into aspect plans; these assert the clustering rule (one cluster
per field-class, packs by namespace), determinism (stable ``plan_json`` across retries), and the
effort-scaling defaults the issue exposes.
"""

from __future__ import annotations

from clue_core import PassKind
from clue_core.field import FieldDef
from clue_research.durable.planning import build_plan


def _field(key: str) -> FieldDef:
    return FieldDef(field_key=key, value_type="str", pass_kind=PassKind.DEEP)


def test_build_plan_clusters_by_field_class() -> None:
    gaps = [
        _field("account.recent_funding"),
        _field("account.strategic_moves"),
        _field("account.resonance.culture"),
        _field("contact.facet.recent_post"),
        _field("healthcare.npi"),
    ]
    plan = build_plan(gaps, tier="top")

    by_aspect = {a.aspect: a for a in plan.aspects}
    # account.resonance wins over account (longest-prefix), packs cluster by namespace.
    assert set(by_aspect) == {"account", "account.resonance", "contact.facet", "healthcare"}
    assert by_aspect["account"].field_keys == (
        "account.recent_funding",
        "account.strategic_moves",
    )
    assert by_aspect["account.resonance"].field_keys == ("account.resonance.culture",)
    assert by_aspect["healthcare"].field_keys == ("healthcare.npi",)
    assert plan.gap_field_count == 5
    assert plan.tier == "top"


def test_build_plan_is_deterministic() -> None:
    a = [_field("account.b"), _field("account.a"), _field("contact.role_on_committee")]
    b = [_field("contact.role_on_committee"), _field("account.a"), _field("account.b")]
    # Aspects ordered by key, field keys sorted within an aspect → identical regardless of order.
    assert build_plan(a, tier="t").model_dump() == build_plan(b, tier="t").model_dump()
    assert [asp.aspect for asp in build_plan(a, tier="t").aspects] == ["account", "contact"]
    assert build_plan(a, tier="t").aspects[0].field_keys == ("account.a", "account.b")


def test_build_plan_effort_scaling_defaults_and_overrides() -> None:
    gaps = [_field("account.recent_funding")]
    default = build_plan(gaps, tier="low")
    assert default.aspects[0].worker_count == 1
    assert default.aspects[0].depth == 0  # depth-0 default: no facet recursion (M7.2 raises it)
    assert default.aspects[0].budget_envelope_cents is None  # M7.5 fills the envelope

    scaled = build_plan(gaps, tier="top", worker_count=3, depth=2)
    assert scaled.aspects[0].worker_count == 3
    assert scaled.aspects[0].depth == 2


def test_build_plan_empty_gaps_is_empty() -> None:
    plan = build_plan([], tier="top")
    assert plan.aspects == ()
    assert plan.gap_field_count == 0
