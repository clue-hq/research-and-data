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


def _photo_hero_evidence() -> BrandEvidence:
    """An ordinary photo-led brand: six bands, four of them dark under a photo.

    The four image-backed bands carry no readable color, so the audit may not
    count them — and must not then speak about "this site" as though the two it
    could read were the whole page.
    """
    bands = [
        _band(0, "#101018", has_image=True),
        _band(1, "#FFFFFF"),
        _band(2, "#0B0B10", has_image=True),
        _band(3, "#F7F7F7"),
        _band(4, "#101018", has_image=True),
        _band(5, "#0B0B10", has_image=True),
    ]
    return _evidence().model_copy(
        update={"geometry": GeometryEvidence(background_sequence=bands, surfaces=[])}
    )


def _one_unread_band_evidence() -> BrandEvidence:
    """Six readable bands (two dark) plus one gradient the capture could not read."""
    bands = [
        _band(0, "#FFFFFF"),
        _band(1, "#0D1738"),
        _band(2, "#FFFFFF"),
        _band(3, "#FFFFFF", gradient=True),
        _band(4, "#0D1738"),
        _band(5, "#FFFFFF"),
        _band(6, "#FFFFFF"),
    ]
    surfaces = [
        SurfaceShape(
            surface="button",
            variant="solid.1",
            count=6,
            fill="solid",
            radius_px=[4.0],
            background="#533AFD",
            pointer=_pointer(),
        )
    ]
    return _evidence().model_copy(
        update={"geometry": GeometryEvidence(background_sequence=bands, surfaces=surfaces)}
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


def test_the_type_law_leads_its_field_so_a_tight_budget_cannot_eat_it() -> None:
    """The field's INSTRUCTION comes before the reference data it applies to.
    The injected block drops a field's tail first, and a type-treatment section
    that keeps six role listings and loses "never restate the ramp" has kept the
    footnotes and dropped the law."""
    evidence = _evidence()
    audit = extract_grammar_audit(evidence, _kit_for(evidence))
    first = audit.type_treatment.rules[0]
    assert first.basis == "default"
    assert "ramp" in first.rule.lower()


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


def test_a_photo_led_site_is_never_told_it_has_no_dark_band() -> None:
    """The refused-band trap. Four of six bands sit under a photo, so their color
    is unreadable; counting only the two that were readable and calling the
    result "this site" invents the opposite of the truth."""
    evidence = _photo_hero_evidence()
    audit = extract_grammar_audit(evidence, _kit_for(evidence))
    cadence = _rules_text(audit.cadence)
    assert "No dark band anywhere" not in cadence
    assert "all 2 measured bands are light" not in cadence
    # It says WHY it is not counting, with the number it could not read.
    assert "NOT KNOWN" in cadence
    assert "4 of 6" in cadence
    # And the exclusion built on the same count does not fire either.
    assert "no extra dark" not in _rules_text(audit.anti_patterns).lower()


def test_a_gradient_or_translucent_band_is_unread_for_the_same_reason() -> None:
    for background, overrides in (
        ("#0B0B10", {"gradient": True}),
        ("#0B0B1080", {}),
    ):
        bands = [
            _band(0, background, **overrides),
            _band(1, background, **overrides),
            _band(2, background, **overrides),
            _band(3, background, **overrides),
            _band(4, "#FFFFFF"),
        ]
        evidence = _evidence().model_copy(
            update={"geometry": GeometryEvidence(background_sequence=bands, surfaces=[])}
        )
        audit = extract_grammar_audit(evidence, _kit_for(evidence))
        assert "NOT KNOWN" in _rules_text(audit.cadence), (background, overrides)


def test_one_unread_band_keeps_the_count_but_names_what_it_could_not_read() -> None:
    """A minority refusal does not cost the rule — it costs the rule's silence
    about the refusal, so it can never be read as a whole-site law."""
    evidence = _one_unread_band_evidence()
    audit = extract_grammar_audit(evidence, _kit_for(evidence))
    cadence = _rules_text(audit.cadence)
    assert "2 of 6" in cadence
    assert "1 of the 7" in cadence
    exclusions = _rules_text(audit.anti_patterns)
    assert "No extra dark sections" in exclusions
    assert "1 of the 7" in exclusions


def test_the_accent_claim_says_which_bands_it_could_check() -> None:
    evidence = _one_unread_band_evidence()
    audit = extract_grammar_audit(evidence, _kit_for(evidence))
    accent = next(
        rule.rule for rule in audit.color_frequency.rules if "#533AFD" in rule.rule
    )
    assert "could be read" in accent


def test_a_fully_readable_sequence_carries_no_refusal_caveat() -> None:
    """The discrimination guard: the Stripe harvest reads every band, so nothing
    about unread bands appears anywhere in its audit."""
    evidence = _measured_evidence()
    audit = extract_grammar_audit(evidence, _kit_for(evidence))
    text = _audit_text(audit)
    assert "could not be read" not in text
    assert "could be read" not in text
    assert "NOT KNOWN" not in text


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


def test_the_published_approved_kit_carries_the_grammar_audit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    job = _run_website_ingestion_through_the_route(
        client, monkeypatch, url="https://audit-rides.example", evidence=_measured_evidence()
    )
    detail = client.get(f"/brand-kits/{job['brand_kit_id']}").json()
    assert detail["brand_kit"]["approval_status"] == "approved"
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


# --- F3.4 prose round: the wording has to be true of the evidence beside it --------


def test_the_dark_exclusion_names_the_band_count_the_site_actually_has() -> None:
    """The F2 walk's stripe audit printed, one heading apart:

        The site's own band sequence, top to bottom: light, light, light, dark, light, dark, …
        No extra dark sections: 2 of 8 measured bands is dark. A SECOND dark band is a rhythm
        this brand does not have.

    The site plainly has a second dark band — the sequence above says so. An exclusion that
    contradicts the evidence printed beside it teaches an agent to discount both.
    """
    evidence = _measured_evidence()
    audit = extract_grammar_audit(evidence, _kit_for(evidence))
    exclusions = _rules_text(audit.anti_patterns)

    assert "2 of 8 measured bands are dark" in exclusions
    assert "a third dark band is a rhythm this brand does not have" in exclusions.lower()
    assert "a second dark band" not in exclusions.lower()


def test_a_site_with_exactly_one_dark_band_is_still_told_about_the_second() -> None:
    """The n=1 wording was right and stays right: there is no second band here to contradict it."""
    bands = [
        _band(0, "#FFFFFF"),
        _band(1, "#0D1738"),
        _band(2, "#FFFFFF"),
        _band(3, "#FFFFFF"),
        _band(4, "#FFFFFF"),
        _band(5, "#FFFFFF"),
    ]
    evidence = _evidence().model_copy(
        update={"geometry": GeometryEvidence(background_sequence=bands, surfaces=[])}
    )
    exclusions = _rules_text(
        extract_grammar_audit(evidence, _kit_for(evidence)).anti_patterns
    )
    assert "1 of 6 measured bands is dark" in exclusions
    assert "A second dark band is a rhythm this brand does not have." in exclusions


def test_an_implausible_leading_is_abstained_from_rather_than_legislated() -> None:
    """The F2 walk's audit told an agent this brand's `type.title` is `leading 2.2` — a number
    taken off a collapsed element. There is no honest correction available, so the line says it
    did not read one, and says what it saw instead of quietly dropping it."""
    evidence = _evidence()
    kit = _kit_for(evidence)
    typography = kit["tokens"]["typography"]
    role = next(iter(typography))
    typography[role]["value"]["default"]["line_height"] = 2.2

    treatment = _rules_text(extract_grammar_audit(evidence, kit).type_treatment)

    assert "leading 2.2" not in treatment
    assert "leading not stated" in treatment
    assert "which is not a line-height" in treatment


def test_a_plausible_leading_is_still_stated() -> None:
    evidence = _evidence()
    kit = _kit_for(evidence)
    typography = kit["tokens"]["typography"]
    role = next(iter(typography))
    typography[role]["value"]["default"]["line_height"] = 1.15

    treatment = _rules_text(extract_grammar_audit(evidence, kit).type_treatment)

    assert "leading 1.15" in treatment
    assert "leading not stated" not in treatment


def test_the_audit_says_so_when_it_legislates_in_a_font_the_kit_cannot_paint() -> None:
    """The Sohne caveat (F2 close-out). stripe.com's first walk produced an audit legislating in
    `sohne-var`, a family the kit held no binaries for. The root cause is closed; the SHAPE is
    not — the type roles come off the kit's tokens and the faces off the capture, and nothing
    made the two agree."""
    evidence = _evidence()
    kit = _kit_for(evidence)
    role = next(iter(kit["tokens"]["typography"]))
    kit["tokens"]["typography"][role]["value"]["default"]["font_family"] = (
        "sohne-var, Helvetica, sans-serif"
    )
    kit.setdefault("assets", {})["fonts"] = {
        "brand": {"family": "Aeonik", "faces": [{"asset_id": "asset_1"}]}
    }

    treatment = _rules_text(extract_grammar_audit(evidence, kit).type_treatment)

    assert "CAVEAT" in treatment
    assert "`sohne-var`" in treatment
    assert "nothing here can paint" in treatment


def test_a_font_the_kit_does_hold_binaries_for_draws_no_caveat() -> None:
    evidence = _evidence()
    kit = _kit_for(evidence)
    for entry in kit["tokens"]["typography"].values():
        entry["value"]["default"]["font_family"] = '"Sohne Var", Helvetica, sans-serif'
    kit.setdefault("assets", {})["fonts"] = {
        "brand": {"family": "sohne-var", "faces": [{"asset_id": "asset_1"}]}
    }

    assert "CAVEAT" not in _rules_text(
        extract_grammar_audit(evidence, kit).type_treatment
    )


def test_a_kit_that_declares_a_font_and_holds_no_binaries_draws_the_caveat() -> None:
    """F-5: the strongest case the caveat exists for, and it was the one being abstained on.
    This is stripe's first walk exactly — the kit KNEW about `sohne-var` and had zero faces for
    it. "Nothing paintable" and "nothing declared" were being tested with one condition; they are
    two different facts."""
    evidence = _evidence()
    kit = _kit_for(evidence)
    role = next(iter(kit["tokens"]["typography"]))
    kit["tokens"]["typography"][role]["value"]["default"]["font_family"] = "sohne-var"
    kit.setdefault("assets", {})["fonts"] = {"brand": {"family": "sohne-var", "faces": []}}

    treatment = _rules_text(extract_grammar_audit(evidence, kit).type_treatment)

    assert "CAVEAT" in treatment
    assert "`sohne-var`" in treatment


def test_a_kit_that_declares_no_fonts_at_all_draws_no_caveat_either() -> None:
    """"Nothing is known about this kit's faces" is not "this kit can paint nothing", and a
    caveat off no evidence is the confident wrongness the whole audit is written against."""
    evidence = _evidence()
    kit = _kit_for(evidence)
    kit.setdefault("assets", {})["fonts"] = {}

    assert "CAVEAT" not in _rules_text(
        extract_grammar_audit(evidence, kit).type_treatment
    )


def test_a_system_font_needs_no_binaries_and_draws_no_caveat() -> None:
    """The third case, found by the F-5 fix's own regression: the normalizer records
    `source.kind == "system"` for a family it found no webfont for — the engine's Inter default
    is the everyday one — and such a family needs no bytes from us because nothing is served.
    Caveating it would tell a brand it cannot paint the font it is already painting in."""
    evidence = _bare_evidence()
    kit = _kit_for(evidence)
    (brand,) = kit["assets"]["fonts"].values()
    assert brand["faces"] == [] and brand["source"]["kind"] == "system"

    treatment = extract_grammar_audit(evidence, kit).type_treatment
    assert "CAVEAT" not in _rules_text(treatment)
    assert "measured" not in {rule.basis for rule in treatment.rules}
