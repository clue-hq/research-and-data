import pytest
from pydantic import ValidationError

from clue_api.arv2.discovery_request import (
    DiscoveryBrief2,
    apply_roles,
    excluded_domains,
    verifier_gates,
)
from clue_api.arv2.discovery_verifier import GateVerdict


def _brief(**over):
    base = {
        "source": "websets",
        "query": "Companies of <kind> that run <activity>.",
        "criteria": ["The company runs <activity>."],
        "gates": [
            {
                "key": "is_buyer",
                "rule": "The company runs <activity>.",
                "test": "Its site describes it.",
                "role": "must",
            },
            {
                "key": "sells_product",
                "rule": "The company sells <product> to <buyers>.",
                "test": "Its product pages.",
                "role": "must_not",
            },
            {
                "key": "uses_stack",
                "rule": "A <system> is in use within the last 24 months.",
                "test": "A job post names one.",
                "role": "prefer",
            },
        ],
    }
    return DiscoveryBrief2.model_validate({**base, **over})


def _v(key, verdict):
    return GateVerdict(
        gate_key=key,
        verdict=verdict,
        reasoning="",
        evidence_quote="",
        evidence_url="",
        evidence_date="",
        guard="ok",
        model_verdict=verdict,
    )


def test_structural_limits_are_enforced():
    with pytest.raises(ValidationError):
        _brief(criteria=[f"c{i}" for i in range(6)])
    with pytest.raises(ValidationError):
        _brief(gates=_brief().model_dump()["gates"][:1])
    with pytest.raises(ValidationError):
        dup = _brief().model_dump()["gates"]
        dup[1]["key"] = "is_buyer"
        _brief(gates=dup)
    with pytest.raises(ValidationError):
        _brief(source="linkedin")


def test_verifier_gates_carry_the_window():
    gates = verifier_gates(_brief())
    assert [g.key for g in gates] == ["is_buyer", "sells_product", "uses_stack"]
    assert gates[2].window_months == 24


def test_only_a_must_not_gate_is_asked_about_the_main_business():
    """Founder ruling 2026-10-01: a gate that excludes on a pass asks about the main business."""
    gates = verifier_gates(_brief())
    assert [(g.key, g.main_business) for g in gates] == [
        ("is_buyer", False),
        ("sells_product", True),
        ("uses_stack", False),
    ]


def test_a_failed_must_excludes():
    out = apply_roles(
        _brief(),
        [_v("is_buyer", "fail"), _v("sells_product", "fail"), _v("uses_stack", "pass")],
    )
    assert out.excluded_by == "is_buyer" and out.fit is None


def test_a_passed_must_not_excludes():
    out = apply_roles(
        _brief(),
        [_v("is_buyer", "pass"), _v("sells_product", "pass"), _v("uses_stack", "pass")],
    )
    assert out.excluded_by == "sells_product"


def test_unclear_never_excludes_and_fit_counts_must_and_prefer_only():
    out = apply_roles(
        _brief(),
        [_v("is_buyer", "unclear"), _v("sells_product", "unclear"), _v("uses_stack", "pass")],
    )
    assert out.excluded_by is None
    assert out.fit == pytest.approx(0.75)  # (0.5 + 1) / 2 — the must_not gate is not scored
    assert out.shown_disposition == "unclear"


def test_a_failed_prefer_is_shown_as_partial():
    out = apply_roles(
        _brief(),
        [_v("is_buyer", "pass"), _v("sells_product", "fail"), _v("uses_stack", "fail")],
    )
    assert out.excluded_by is None and out.shown_disposition == "partial"
    assert out.fit == pytest.approx(0.5)


def _entry(name, *domains):
    return {"name": name, "domains": list(domains)}


def test_exclude_entries_are_bounded_and_need_a_real_domain():
    assert _brief(exclude=[_entry("Marriott", "marriott.com")]).exclude[0].name == "Marriott"
    with pytest.raises(ValidationError):
        _brief(exclude=[_entry(f"Co {i}", f"co{i}.com") for i in range(501)])
    with pytest.raises(ValidationError):
        _brief(exclude=[_entry("Acme", "not a domain")])
    with pytest.raises(ValidationError):
        _brief(exclude=[_entry("A" * 201, "acme.com")])
    with pytest.raises(ValidationError):
        _brief(exclude=[_entry("Acme")])
    with pytest.raises(ValidationError):
        _brief(exclude=[_entry("Acme", *[f"acme{i}.com" for i in range(11)])])


def test_excluded_domains_fold_spellings_and_keep_the_first_name():
    brief = _brief(
        exclude=[_entry("Acme", "https://www.Acme.com/"), _entry("Acme Inc", "acme.com")]
    )
    assert excluded_domains(brief) == {"acme.com": "Acme"}


def test_a_shared_host_entry_names_only_that_site():
    found = excluded_domains(_brief(exclude=[_entry("Acme Shop", "acme.myshopify.com")]))
    assert found == {"acme.myshopify.com": "Acme Shop"}
    assert "other.myshopify.com" not in found


def test_a_subdomain_is_matched_as_written():
    found = excluded_domains(_brief(exclude=[_entry("Marriott", "marriott.com")]))
    assert "blog.marriott.com" not in found


def test_a_brief_without_exclusions_serializes_exactly_as_before():
    """Old run rows and ``@2`` calls keep their stored brief and request hash byte for byte."""
    dumped = _brief().model_dump(mode="json")
    assert "exclude" not in dumped
    assert DiscoveryBrief2.model_validate(dumped) == _brief()
    with_list = _brief(exclude=[_entry("Marriott", "marriott.com")]).model_dump(mode="json")
    assert with_list["exclude"] == [{"name": "Marriott", "domains": ["marriott.com"]}]
