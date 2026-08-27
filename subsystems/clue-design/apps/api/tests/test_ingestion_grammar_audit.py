"""The Brand Grammar Audit (clone-fidelity F2.4) — deterministic extraction.

Cloned sections carry fidelity for the bands a human released; this artifact
governs the ~30% of a page the agent still COMPOSES. It is read off evidence the
ingestion already holds — the measured type samples, the band sequence, the
measured surfaces, the kit's own geometry tokens — with no model call and no
network, and it rides `brand_kit_json.grammar_audit` exactly as `BrandBrief@1`
rides `brand_kit_json.brief`.

Three laws are tested here rather than trusted:

* **determinism** — the same evidence extracts a byte-identical audit, every time.
* **honest absence** — a field with no evidence behind it says so; it never
  invents a rule, and a field can never carry both rules and an absence reason.
* **exclusions are findings too** — "no extra dark sections" is derived from the
  measured band count, not from taste, and it must NOT appear on a brand whose
  own site is dark-dominant.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from conftest import make_client, wait_for_ingestion_job

from lumen_ingestion.capture.geometry import parse_geometry
from lumen_ingestion.evidence import (
    BrandEvidence,
    EvidencePointer,
    GeometryEvidence,
    SectionBackground,
    SurfaceShape,
)
from lumen_ingestion.grammar_audit import (
    GRAMMAR_AUDIT_SCHEMA_VERSION,
    BrandGrammarAudit,
    GrammarField,
    extract_grammar_audit,
)
from lumen_ingestion.normalizer import normalize_evidence

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ingestion"
EXPECTED = FIXTURES / "expected"
REPO_ROOT = Path(__file__).resolve().parents[3]
LOGO_PNG_PATH = REPO_ROOT / "crates/lumen-export/fixtures/assets/acme-logo-8x8-red.png"


# --- fixtures ---------------------------------------------------------------------


def _evidence() -> BrandEvidence:
    """The committed website evidence bundle (Insight Health): four measured
    type samples, no geometry at all."""
    return BrandEvidence.model_validate(
        json.loads((FIXTURES / "evidence_website_insight.json").read_text())
    )


def _kit_for(evidence: BrandEvidence, kit_id: str = "brand_kit_audit") -> dict:
    return normalize_evidence(
        evidence,
        brand_kit_id=kit_id,
        version=1,
        name="Audit",
        created_at="2026-08-27",
    ).brand_kit


def _measured_evidence() -> BrandEvidence:
    """The website bundle wearing the REAL Stripe geometry harvest.

    Eight measured bands (six light, two navy), a purple that only ever fills a
    button, 4px controls and 6px cards. Everything this audit claims about a
    real brand is claimed about this one.
    """
    harvest = json.loads((FIXTURES / "geometry" / "stripe_home.json").read_text())
    parsed = parse_geometry(harvest, page_url="https://stripe.com/")
    base = _evidence()
    # The real pipeline folds the harvest's numbers and shadows into the bundle
    # alongside its geometry; without that the kit carries no measured shape.
    return base.model_copy(
        update={
            "geometry": parsed.evidence(),
            "numbers": base.numbers + parsed.numbers,
            "shadows": base.shadows + parsed.shadows,
        }
    )


def _pointer() -> EvidencePointer:
    return EvidencePointer(source="website", locator="https://dark.example :: section 0")


def _band(index: int, background: str, height: float = 800.0, **overrides) -> SectionBackground:
    return SectionBackground(
        index=index,
        background=background,
        height_px=height,
        pointer=_pointer(),
        **overrides,
    )


def _dark_dominant_evidence() -> BrandEvidence:
    """A brand whose own site is mostly dark — the discrimination case for the
    "no extra dark sections" exclusion."""
    bands = [
        _band(0, "#0B0B10"),
        _band(1, "#0B0B10"),
        _band(2, "#FFFFFF"),
        _band(3, "#0B0B10"),
        _band(4, "#0B0B10"),
    ]
    return _evidence().model_copy(
        update={"geometry": GeometryEvidence(background_sequence=bands, surfaces=[])}
    )


def _bare_evidence() -> BrandEvidence:
    """A brand the capture learned almost nothing about: no type samples, no
    fonts, no geometry. Every honest answer here is "not known"."""
    return BrandEvidence(
        source={"kind": "website", "url": "https://bare.example"},
        colors=_evidence().colors,
    )


def _rules_text(field) -> str:
    return " ".join(f"{rule.rule} {rule.evidence}" for rule in field.rules)


def _audit_text(audit: BrandGrammarAudit) -> str:
    return " ".join(
        _rules_text(getattr(audit, name)) for name in BrandGrammarAudit.FIELD_NAMES
    )


# --- the shape ---------------------------------------------------------------------


def test_a_field_may_carry_rules_or_an_absence_but_never_both() -> None:
    with pytest.raises(ValidationError):
        GrammarField(
            rules=[{"rule": "a rule", "evidence": "measured", "basis": "measured"}],
            absent="and also nothing is known",
        )


def test_a_field_with_no_rules_must_say_why() -> None:
    with pytest.raises(ValidationError):
        GrammarField(rules=[], absent=None)


def test_every_field_of_an_extracted_audit_is_either_ruled_or_honestly_empty() -> None:
    audit = extract_grammar_audit(_bare_evidence(), _kit_for(_bare_evidence()))
    assert audit.schema_version == GRAMMAR_AUDIT_SCHEMA_VERSION
    for name in BrandGrammarAudit.FIELD_NAMES:
        field = getattr(audit, name)
        assert bool(field.rules) != bool(field.absent), name


def test_the_same_evidence_extracts_an_identical_audit_twice() -> None:
    evidence, kit = _measured_evidence(), _kit_for(_measured_evidence())
    first = extract_grammar_audit(evidence, kit)
    second = extract_grammar_audit(evidence, kit)
    assert first.model_dump() == second.model_dump()


def test_the_audit_is_json_serializable_as_a_kit_section() -> None:
    audit = extract_grammar_audit(_measured_evidence(), _kit_for(_measured_evidence()))
    payload = json.loads(json.dumps(audit.model_dump()))
    assert BrandGrammarAudit.model_validate(payload).model_dump() == audit.model_dump()


# --- 1. type treatment -------------------------------------------------------------


def test_type_treatment_quotes_the_measured_role_with_its_concrete_values() -> None:
    evidence = _evidence()
    audit = extract_grammar_audit(evidence, _kit_for(evidence))
    text = _rules_text(audit.type_treatment)
    # The site's own h1: Aeonik 48px / 600 / 1.1 / -0.01em.
    assert "type.headline" in text
    assert "48" in text and "600" in text and "1.1" in text and "-0.01" in text


def test_a_role_nothing_anchored_is_marked_as_the_engine_ramp_not_a_brand_fact() -> None:
    """The Insight bundle anchors h1/h2/body/button and nothing else, so
    `type.display` is computed. It must never read as something the brand does."""
    evidence = _evidence()
    audit = extract_grammar_audit(evidence, _kit_for(evidence))
    by_role = {rule.rule.split("`")[1]: rule for rule in audit.type_treatment.rules if "`" in rule.rule}
    assert by_role["type.headline"].basis == "measured"
    assert by_role["type.display"].basis == "derived"


def test_a_brand_with_no_type_evidence_reports_no_measured_type_treatment() -> None:
    evidence = _bare_evidence()
    audit = extract_grammar_audit(evidence, _kit_for(evidence))
    bases = {rule.basis for rule in audit.type_treatment.rules}
    assert "measured" not in bases


def test_an_absurd_font_family_cannot_blow_the_rule_length_bound() -> None:
    """The one place unbounded captured text reaches a length-capped field: a
    site declaring a whole CSS stack as its family must not cost the WHOLE audit
    (the schema would refuse it, and the kit would publish auditless)."""
    stack = ", ".join(f"Family{index}" for index in range(60))
    evidence = _evidence()
    evidence = evidence.model_copy(
        update={
            "type_samples": [
                sample.model_copy(update={"family": stack})
                for sample in evidence.type_samples
            ]
        }
    )
    audit = extract_grammar_audit(evidence, _kit_for(evidence))
    assert audit.type_treatment.rules
    assert all(len(rule.rule) <= 400 for rule in audit.type_treatment.rules)


def test_the_type_law_forbids_restating_the_ramp_on_a_heading() -> None:
    evidence = _evidence()
    audit = extract_grammar_audit(evidence, _kit_for(evidence))
    text = _rules_text(audit.type_treatment)
    assert "ramp" in text.lower()


# --- 2. cadence --------------------------------------------------------------------


def test_the_cadence_reads_the_measured_band_sequence_in_order() -> None:
    evidence = _measured_evidence()
    audit = extract_grammar_audit(evidence, _kit_for(evidence))
    text = _rules_text(audit.cadence)
    # six light bands, two dark, in the order the page paints them
    assert "light, light, light, dark, light, dark, light, light" in text


def test_a_rare_dark_band_is_reported_as_an_interval() -> None:
    evidence = _measured_evidence()
    audit = extract_grammar_audit(evidence, _kit_for(evidence))
    text = _rules_text(audit.cadence).lower()
    assert "2 of 8" in text
    assert "exception" in text


def test_a_dark_dominant_site_is_not_told_dark_is_exceptional() -> None:
    evidence = _dark_dominant_evidence()
    audit = extract_grammar_audit(evidence, _kit_for(evidence))
    cadence = _rules_text(audit.cadence).lower()
    exclusions = _rules_text(audit.anti_patterns).lower()
    assert "exception" not in cadence
    assert "no extra dark" not in exclusions
    assert "4 of 5" in cadence


def test_a_capture_with_no_measured_bands_says_the_cadence_is_not_known() -> None:
    evidence = _evidence()  # the Insight bundle carries no geometry at all
    audit = extract_grammar_audit(evidence, _kit_for(evidence))
    assert audit.cadence.rules == []
    assert audit.cadence.absent
    assert "band" in audit.cadence.absent.lower()


def test_the_section_rhythm_is_named_by_its_kit_token() -> None:
    """The token law: the audit speaks `space.section`; the web class beside it
    is the agent-side renderer's business (`lumen_agent.brand_brief`)."""
    evidence = _measured_evidence()
    audit = extract_grammar_audit(evidence, _kit_for(evidence))
    text = _rules_text(audit.cadence)
    assert "space.section" in text and "96px" in text
    assert "py-section" not in text


# --- 3. color frequency ------------------------------------------------------------


def test_color_frequency_counts_the_surfaces_the_page_actually_stands_on() -> None:
    evidence = _measured_evidence()
    audit = extract_grammar_audit(evidence, _kit_for(evidence))
    text = _rules_text(audit.color_frequency)
    assert "#FFFFFF" in text and "5 of 8" in text
    assert "#0D1738" in text and "2 of 8" in text


def test_a_band_colour_the_kit_named_is_reported_under_its_token() -> None:
    evidence = _measured_evidence()
    kit = _kit_for(evidence)
    audit = extract_grammar_audit(evidence, kit)
    text = _rules_text(audit.color_frequency)
    assert "surface.band.statement" in text


def test_an_accent_that_only_ever_fills_a_control_is_stated_as_control_scale() -> None:
    evidence = _measured_evidence()
    audit = extract_grammar_audit(evidence, _kit_for(evidence))
    text = _rules_text(audit.color_frequency)
    assert "#533AFD" in text
    assert "control" in text.lower()


def test_a_brand_with_no_measured_surfaces_or_bands_states_no_frequency_law() -> None:
    evidence = _bare_evidence()
    audit = extract_grammar_audit(evidence, _kit_for(evidence))
    assert audit.color_frequency.rules == []
    assert audit.color_frequency.absent


# --- 4. surface language -----------------------------------------------------------


def test_surface_language_quotes_the_measured_radii_under_their_token_names() -> None:
    evidence = _measured_evidence()
    audit = extract_grammar_audit(evidence, _kit_for(evidence))
    text = _rules_text(audit.surface_language)
    assert "`radius.button` 4px" in text
    assert "`radius.card` 6px" in text
    assert "`shadow.brand`" in text


def test_a_brand_that_measured_no_elevation_is_told_it_is_flat() -> None:
    flat = _evidence().model_copy(
        update={
            "shadows": [],
            "geometry": GeometryEvidence(
                background_sequence=[_band(0, "#FFFFFF")],
                surfaces=[
                    SurfaceShape(
                        surface="card",
                        variant="solid.1",
                        count=4,
                        fill="solid",
                        radius_px=[6.0],
                        background="#FFFFFF",
                        pointer=_pointer(),
                    )
                ],
            ),
        }
    )
    audit = extract_grammar_audit(flat, _kit_for(flat))
    assert "flat" in _rules_text(audit.surface_language).lower()
    assert "shadow" in _rules_text(audit.anti_patterns).lower()


def test_a_kit_with_no_measured_geometry_states_no_surface_language() -> None:
    evidence = _bare_evidence()
    audit = extract_grammar_audit(evidence, _kit_for(evidence))
    assert audit.surface_language.rules == []
    assert audit.surface_language.absent


# --- 5. anti-patterns --------------------------------------------------------------


def test_a_site_with_one_dark_interval_gets_the_no_extra_dark_sections_rule() -> None:
    evidence = _measured_evidence()
    audit = extract_grammar_audit(evidence, _kit_for(evidence))
    assert "no extra dark" in _rules_text(audit.anti_patterns).lower()


def test_the_house_slop_defaults_are_present_even_on_a_bare_brand() -> None:
    evidence = _bare_evidence()
    audit = extract_grammar_audit(evidence, _kit_for(evidence))
    rules = audit.anti_patterns.rules
    assert rules
    assert {rule.basis for rule in rules} == {"default"}
    assert "blob" in _rules_text(audit.anti_patterns).lower()


def test_a_derived_exclusion_names_the_measurement_behind_it() -> None:
    evidence = _measured_evidence()
    audit = extract_grammar_audit(evidence, _kit_for(evidence))
    derived = [rule for rule in audit.anti_patterns.rules if rule.basis == "measured"]
    assert derived
    assert all(rule.evidence for rule in derived)


def test_the_audit_never_legislates_about_cloned_sections() -> None:
    """The reuse ladder (F2.3) owns what may happen to a cloned band. This
    artifact governs NEW sections and must not say a second, different thing."""
    audit = extract_grammar_audit(_measured_evidence(), _kit_for(_measured_evidence()))
    text = _audit_text(audit).lower()
    for word in ("cloned section", "fragment", "reuse ladder", "insert_cloned_section"):
        assert word not in text


# --- the pipeline ride-along ---------------------------------------------------------


def _run_website_ingestion_through_the_route(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    *,
    url: str,
    evidence: BrandEvidence,
) -> dict:
    """Drive the real website route with a stubbed capture and given evidence."""
    from lumen_api import main as main_module
    from lumen_ingestion.pipeline import run_website_ingestion

    png_bytes = LOGO_PNG_PATH.read_bytes()

    async def fake_capture(url, *, reporter, force_render=False, page_urls=None):
        class Outcome:
            tier = "rendered"
            escalated = False
            escalation_reason = None
            diagnostics: list[dict] = []

        return Outcome()

    def fake_build_evidence(outcome, *, core, store_root, reporter):
        core.ingest_asset(
            store_root=store_root,
            bytes_base64=base64.b64encode(png_bytes).decode("ascii"),
            asset_id="asset_ing_audit01",
            label="audit logo",
            declared_mime_type="image/png",
            filename="audit.png",
            kind="raster_image",
            tags=["brand-ingestion", "image"],
            raise_on_error=False,
        )
        return evidence

    async def passthrough(target: str) -> str:
        return target

    monkeypatch.setattr(main_module, "_resolve_guard_url", lambda: passthrough)
    monkeypatch.setattr(
        main_module,
        "run_website_ingestion",
        lambda cache_dir, job_id, *, workspace_id, storage=None, expected_generation=None: (
            run_website_ingestion(
                cache_dir,
                job_id,
                capture=fake_capture,
                build_evidence=fake_build_evidence,
                workspace_id=workspace_id,
                storage=storage,
                expected_generation=expected_generation,
            )
        ),
    )

    post = client.post("/brand-kits/ingest/website", json={"url": url})
    assert post.status_code == 200, post.text
    job_id = post.json()["job"]["job_id"]
    wait_for_ingestion_job(client, job_id)
    job = client.get(f"/brand-kits/ingest/{job_id}").json()["job"]
    assert job["status"] == "succeeded", job
    return job


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    from lumen_api.main import create_app

    return make_client(create_app(tmp_path / "engine-cache"))


def test_the_published_draft_kit_carries_the_grammar_audit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = _run_website_ingestion_through_the_route(
        client, monkeypatch, url="https://audit-rides.example", evidence=_measured_evidence()
    )
    detail = client.get(f"/brand-kits/{job['brand_kit_id']}").json()
    assert detail["brand_kit"]["approval_status"] == "draft"
    audit = detail["brand_kit_json"]["grammar_audit"]
    assert audit["schema_version"] == GRAMMAR_AUDIT_SCHEMA_VERSION
    assert audit["cadence"]["rules"]


def test_approval_does_not_mutate_the_grammar_audit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = _run_website_ingestion_through_the_route(
        client, monkeypatch, url="https://audit-approved.example", evidence=_measured_evidence()
    )
    kit_id = job["brand_kit_id"]
    before = client.get(f"/brand-kits/{kit_id}").json()["brand_kit_json"]["grammar_audit"]

    approved = client.post(
        f"/brand-kits/{kit_id}/approval", json={"approval_status": "approved"}
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["brand_kit_json"]["grammar_audit"] == before
    row = client.get(f"/brand-kits/{kit_id}").json()
    assert row["brand_kit_json"]["grammar_audit"] == before
    assert row["brand_kit"]["approval_status"] == "approved"


def test_an_extraction_failure_leaves_the_kit_auditless_and_says_so(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The audit is never a gate: a kit publishes without it, loudly."""
    from lumen_ingestion import pipeline as pipeline_module

    def explode(evidence, brand_kit):
        raise RuntimeError("the audit blew up")

    monkeypatch.setattr(pipeline_module, "extract_grammar_audit", explode)
    job = _run_website_ingestion_through_the_route(
        client, monkeypatch, url="https://audit-broken.example", evidence=_measured_evidence()
    )
    detail = client.get(f"/brand-kits/{job['brand_kit_id']}").json()
    assert "grammar_audit" not in detail["brand_kit_json"]
    codes = {d.get("code") for d in detail["diagnostics"]["audit"]}
    assert "LUMI0910" in codes
