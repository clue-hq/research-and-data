"""Rendered type must survive earlier incomplete CSS and keep honest provenance."""

import pytest
from lumen_ingestion.evidence import BrandEvidence, TypeSample
from lumen_ingestion.grammar_audit import extract_grammar_audit
from lumen_ingestion.normalizer import normalize_evidence
from lumen_ingestion.normalizer.typography import resolve_anchors


def sample(label, *, family="Display", size=None, weight=None, rendered=False, **kw):
    return TypeSample(
        label=label,
        family=family,
        size_px=size,
        weight=weight,
        pointer={
            "source": "website",
            "locator": f"rendered :: {label}" if rendered else f"site.css :: {label}",
        },
        **kw,
    )


def evidence(samples):
    return BrandEvidence(
        source={"kind": "website", "url": "https://brand.example"},
        type_samples=samples,
        fonts=[
            {
                "family": "Display",
                "role_hint": "heading",
                "faces": [{"weight": w, "asset_id": f"font_{w}"} for w in (400, 500)],
                "pointer": {"source": "website", "locator": "fonts.css"},
            }
        ],
    )


def normalize(e):
    return normalize_evidence(
        e, brand_kit_id="kit_type_audit", name="Type audit", created_at="2026-09-29"
    )


@pytest.mark.parametrize("reverse", [False, True])
def test_rendered_heading_overrides_incomplete_or_conflicting_stylesheet(reverse):
    samples = [
        sample("h1", family="var(--font-heading)"),
        sample("h1", size=32, weight=700),
        sample("h2", family="var(--font-heading)"),
        sample("h1", size=56, weight=400, rendered=True, line_height=1, letter_spacing=-0.03),
        sample("h2", size=48, weight=400, rendered=True, line_height=1, letter_spacing=-0.03),
    ]
    e = evidence(list(reversed(samples)) if reverse else samples)
    result = normalize(e)
    typography = result.brand_kit["tokens"]["typography"]
    h1 = typography["type.headline"]["value"]["default"]
    h2 = typography["type.title"]["value"]["default"]
    assert (h1["font_size"], h1["font_weight"], h1["line_height"], h1["letter_spacing"]) == (
        56,
        400,
        1,
        -0.03,
    )
    assert (h2["font_size"], h2["font_weight"], h2["line_height"], h2["letter_spacing"]) == (
        48,
        400,
        1,
        -0.03,
    )
    assert typography["type.title"]["provenance"]["source"] == "website:rendered :: h2"
    assert not any(
        "type.headline" in d["message"] for d in result.diagnostics if d["code"] == "LUMI0232"
    )


def test_complete_declaration_survives_a_family_only_sample_without_rendered_capture():
    a = resolve_anchors(
        evidence(
            [
                sample("h1", family="var(--font-heading)"),
                sample("h1", family="Editorial", size=62, weight=400),
            ]
        )
    )
    assert (a.heading_family, a.headline_size, a.heading_weight) == ("Editorial", 62, 400)


def test_family_only_evidence_cannot_label_default_sizes_as_measured():
    e = evidence([sample("h1"), sample("h2")])
    result = normalize(e)
    for role in ("type.headline", "type.title", "type.display"):
        assert result.brand_kit["tokens"]["typography"][role]["provenance"]["source"].startswith(
            "derived:"
        )
    rules = extract_grammar_audit(e, result.brand_kit).type_treatment.rules
    for role in ("type.headline", "type.title"):
        rule = next(r for r in rules if r.rule.startswith(f"`{role}`"))
        assert rule.basis == "derived"
        assert "font_size" in rule.evidence and "font_weight" in rule.evidence
    assert not any("HEAVY" in r.rule or "LIGHT" in r.rule for r in rules)


def test_custody_substitution_is_not_presented_as_observed_weight():
    e = evidence([sample("h1", size=60, weight=700, rendered=True)])
    result = normalize(e)
    assert (
        result.brand_kit["tokens"]["typography"]["type.headline"]["value"]["default"]["font_weight"]
        == 500
    )
    rule = next(
        r
        for r in extract_grammar_audit(e, result.brand_kit).type_treatment.rules
        if r.rule.startswith("`type.headline`")
    )
    assert rule.basis == "derived"
    assert "font_weight" in rule.evidence


def test_invalid_size_does_not_displace_a_usable_heading():
    a = resolve_anchors(
        evidence(
            [
                sample("h1", size=-1, weight=400, rendered=True),
                sample("h1", size=64, weight=400, rendered=True),
            ]
        )
    )
    assert a.headline_size == 64


def test_type_guidance_keeps_captured_source_authority_ahead_of_derived_ramp():
    e = evidence([sample("h1")])
    instruction = extract_grammar_audit(e, normalize(e).brand_kit).type_treatment.rules[0]
    assert "measured source" in instruction.rule
    assert "responsive" in instruction.rule
    assert "fallback" in instruction.rule
    assert "Never restate" not in instruction.rule


def test_partial_measurement_retains_its_source_locator():
    e = evidence([sample("h1", size=60, weight=400, rendered=True)])
    token = normalize(e).brand_kit["tokens"]["typography"]["type.headline"]
    assert token["provenance"]["source"].startswith("derived:")
    assert "website:rendered :: h1" in token["provenance"]["source"]
