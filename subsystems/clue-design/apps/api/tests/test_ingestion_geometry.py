"""Measured brand geometry (design-brief plan, slice 2).

The gate for the slice: the kit's `radii` / `stroke_widths` / `shadows` /
`spacing` groups are read off the brand's live page instead of being fabricated
from a base scale — and every surface that measures nothing keeps today's
`derived:` token, provenance intact.

`geometry/stripe_home.json` is a REAL harvest: the shipped `GEOMETRY_JS` probe
run against https://stripe.com at the capture's own 1440 viewport, 2026-08-20.
`geometry/flat_brand.json` is hand-authored: square corners, no elevation — the
honest-empty case.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from lumen_api.core import CoreClient
from lumen_ingestion import BrandEvidence, normalize_evidence
from lumen_ingestion.capture import build_evidence
from lumen_ingestion.capture import CaptureOutcome
from lumen_ingestion.capture.geometry import GEOMETRY_JS, normalize_transform, parse_geometry
from lumen_ingestion.capture.snapshot import SiteSnapshot, load_snapshot
from lumen_ingestion.evidence import EvidencePointer, SectionBackground
from lumen_ingestion.normalizer import _band_ink
from lumen_ingestion.normalizer.bands import BandSurface, build_band_surfaces
from lumen_ingestion.normalizer.emit import KitBuilder
from lumen_ingestion.normalizer.geometry import MEASURED_CONFIDENCE, cluster_numbers

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "ingestion"
GEOMETRY = FIXTURES / "geometry"
SNAPSHOTS = FIXTURES / "snapshots"
EXPECTED = FIXTURES / "expected"

_CREATED_AT = "2026-07-05"

_MEASURED_GROUPS = ("spacing", "radii", "stroke_widths", "shadows")


def _harvest(name: str) -> dict:
    return json.loads((GEOMETRY / f"{name}.json").read_text())


def _evidence(name: str) -> BrandEvidence:
    return BrandEvidence.model_validate(json.loads((FIXTURES / f"{name}.json").read_text()))


def _with_geometry(name: str, harvest: dict | None) -> BrandEvidence:
    """A real evidence bundle whose geometry comes from one measured harvest."""
    evidence = _evidence(name)
    parsed = parse_geometry(harvest, page_url="https://stripe.com/")
    return evidence.model_copy(
        update={
            "numbers": parsed.numbers,
            "shadows": parsed.shadows,
            "geometry": parsed.evidence(),
        }
    )


def _section(index: int, bg: str, height: float, *, gradient: bool = False,
             image: bool = False) -> dict:
    """One band as the live `GEOMETRY_JS` probe reports it."""
    return {
        "index": index,
        "tag": "section",
        "bg": bg,
        "bgImage": "url(hero.jpg)" if image else None,
        "gradient": gradient,
        "height": height,
        "padding": [0, 16, 0, 16],
    }


def _synthetic(sections: list[dict]) -> BrandEvidence:
    """A real evidence bundle wearing a hand-authored background rhythm.

    Real harvests cannot exhibit every band shape on demand (a gradient band
    next to its flat twin, a single band at exactly 28% of the scroll), so the
    threshold and exclusion rules are proven on sequences built through the same
    `parse_geometry` seam the browser probe feeds.
    """
    parsed = parse_geometry(
        {"url": "https://synthetic.example/", "sections": sections},
        page_url="https://synthetic.example/",
    )
    return _evidence("evidence_website_insight").model_copy(
        update={"geometry": parsed.evidence()}
    )


def _normalize(evidence: BrandEvidence) -> dict:
    return normalize_evidence(
        evidence,
        brand_kit_id="brand_kit_geometry",
        version=1,
        name="Geometry",
        created_at=_CREATED_AT,
    ).brand_kit


def _sources(tokens: dict) -> list[str]:
    return [entry["provenance"]["source"] for entry in tokens.values()]


# --------------------------------------------------------------------------- #
# The probe is wired into the live capture
# --------------------------------------------------------------------------- #


def test_the_probe_is_wired_into_the_rendered_capture() -> None:
    # The JS itself can only be proven in a browser; what a unit test CAN hold is
    # that the rendered tier runs it, records it on the snapshot, and treats a
    # throwing probe as a diagnostic rather than a failed capture.
    source = (
        Path(__file__).resolve().parents[1]
        / "lumen_ingestion"
        / "capture"
        / "rendered.py"
    ).read_text()
    assert "GEOMETRY_JS" in source
    assert "geometry=geometry" in source
    assert "LUMI0509" in source
    # Measured after the screenshot: the probe focuses elements to read the
    # focus ring and must not be able to change the captured pixels.
    assert source.index("page.screenshot") < source.index("page.evaluate(GEOMETRY_JS)")
    assert "() =>" in GEOMETRY_JS


def test_snapshot_round_trips_the_harvest_and_older_snapshots_still_load() -> None:
    older = load_snapshot(SNAPSHOTS / "insight_rendered.json")
    assert older.geometry is None

    harvest = _harvest("flat_brand")
    snapshot = older.model_copy(update={"geometry": harvest})
    restored = SiteSnapshot.model_validate_json(snapshot.model_dump_json())
    assert restored.geometry == harvest


# --------------------------------------------------------------------------- #
# Fail-soft parsing
# --------------------------------------------------------------------------- #


def test_a_missing_harvest_measures_nothing() -> None:
    harvest = parse_geometry(None, page_url="https://example.test/")
    assert not harvest.measured
    assert harvest.numbers == [] and harvest.shadows == []
    assert harvest.diagnostics == []


def test_a_malformed_harvest_degrades_with_a_diagnostic() -> None:
    harvest = parse_geometry("not an object", page_url="https://example.test/")
    assert not harvest.measured
    assert [d["severity"] for d in harvest.diagnostics] == ["warning"]


def test_garbage_inside_a_harvest_is_skipped_not_fatal() -> None:
    harvest = parse_geometry(
        {
            "url": "https://example.test/",
            "surfaces": ["nonsense", {"cls": "button", "radius": ["x", None, 8]}],
            "sections": [{"index": 0, "bg": "not-a-color"}],
            "gaps": ["nope", 48],
            "focus": [{"outlineWidth": "wide"}],
        },
        page_url="https://example.test/",
    )
    assert [s.value for s in harvest.numbers if s.kind == "radius"] == [8.0]
    assert [s.value for s in harvest.numbers if s.kind == "spacing"] == [48.0]
    assert harvest.background_sequence[0].background is None


# --------------------------------------------------------------------------- #
# The real Stripe harvest
# --------------------------------------------------------------------------- #


def test_the_stripe_harvest_measures_radii_strokes_shadows_and_spacing() -> None:
    harvest = parse_geometry(_harvest("stripe_home"), page_url="https://stripe.com/")

    kinds = {kind: [s.value for s in harvest.numbers if s.kind == kind] for kind in
             ("radius", "stroke_width", "spacing")}
    assert kinds["radius"], "stripe.com draws rounded surfaces"
    assert kinds["stroke_width"], "stripe.com draws 1px borders"
    assert kinds["spacing"], "stripe.com has a vertical rhythm"
    assert harvest.shadows, "stripe.com uses box-shadows"

    # Every sample is attributable to the measured page.
    for sample in harvest.numbers + harvest.shadows:
        assert sample.pointer.source == "website"
        assert sample.pointer.locator.startswith("https://stripe.com")
        assert " :: " in sample.pointer.locator


def test_background_sequence_is_recorded_in_dom_order() -> None:
    harvest = parse_geometry(_harvest("stripe_home"), page_url="https://stripe.com/")
    sequence = harvest.background_sequence
    assert [band.index for band in sequence] == list(range(len(sequence)))
    assert len(sequence) >= 4
    # Stripe alternates light bands with its deep navy — the rhythm, not a token.
    assert len({band.background for band in sequence}) >= 2
    assert sequence[0].background == "#FFFFFF"


def test_button_shape_evidence_survives_for_the_brief_agent() -> None:
    harvest = parse_geometry(_harvest("stripe_home"), page_url="https://stripe.com/")
    buttons = [shape for shape in harvest.surfaces if shape.surface == "button"]
    assert len(buttons) >= 2, "several visual button variants exist on the page"
    assert len({shape.variant for shape in buttons}) == len(buttons), "variant keys are unique per surface"
    for shape in buttons:
        assert shape.fill in ("solid", "outline", "ghost")
        assert len(shape.radius_px) == 4
        assert len(shape.padding_px) == 4
        assert shape.count >= 1
    assert any(shape.fill == "solid" and shape.background for shape in buttons)
    # Cards are captured too — slice 3's recipes need both.
    assert any(shape.surface == "card" for shape in harvest.surfaces)


def test_focus_ring_is_measured_where_reachable() -> None:
    harvest = parse_geometry(_harvest("stripe_home"), page_url="https://stripe.com/")
    assert any("focus" in s.role_hints for s in harvest.numbers if s.kind == "stroke_width")
    assert any(shape.surface == "focus_ring" for shape in harvest.surfaces)


# --------------------------------------------------------------------------- #
# Clustering
# --------------------------------------------------------------------------- #


def test_clustering_keeps_the_heaviest_members_exact_value() -> None:
    harvest = parse_geometry(_harvest("stripe_home"), page_url="https://stripe.com/")
    clusters = cluster_numbers(harvest.numbers, "radius", abs_tolerance=1.0)
    assert clusters
    assert clusters == sorted(clusters, key=lambda c: (-c.weight, c.value))
    # The representative is an observed value, never a drifted mean.
    observed = {s.value for s in harvest.numbers if s.kind == "radius"}
    assert all(cluster.value in observed for cluster in clusters)


# --------------------------------------------------------------------------- #
# Emission: measured tokens
# --------------------------------------------------------------------------- #


def test_measured_geometry_emits_website_provenanced_tokens() -> None:
    kit = _normalize(_with_geometry("evidence_website_insight", _harvest("stripe_home")))
    tokens = kit["tokens"]

    for group in ("radii", "stroke_widths", "spacing"):
        measured = [
            path
            for path, entry in tokens[group].items()
            if entry["provenance"]["source"].startswith("website:")
        ]
        assert measured, f"{group} took nothing from the measured site"
        for path in measured:
            entry = tokens[group][path]
            assert entry["provenance"]["confidence"] == MEASURED_CONFIDENCE
            assert " :: " in entry["provenance"]["source"]
            assert entry["provenance"]["source"].startswith("website:https://stripe.com")

    assert tokens["shadows"], "stripe.com's elevation language reached the kit"
    for path, entry in tokens["shadows"].items():
        assert path.startswith("shadow.")
        assert entry["provenance"]["source"].startswith("website:")
        assert entry["provenance"]["confidence"] == MEASURED_CONFIDENCE
        value = entry["value"]["default"]
        assert set(value) == {"x", "y", "blur", "spread", "color"}
        assert value["color"].startswith("#")
        # ShadowToken has no `role` field in the engine's serde shape.
        assert "role" not in entry


def test_a_measured_ladder_stays_monotonic() -> None:
    kit = _normalize(_with_geometry("evidence_website_insight", _harvest("stripe_home")))
    ladder = ["space.1", "space.2", "space.3", "space.4", "space.5", "space.6",
              "space.8", "space.10", "space.12", "space.16"]
    values = [kit["tokens"]["spacing"][path]["value"]["default"]["value"] for path in ladder]
    assert values == sorted(values), values

    radii = ["radius.xs", "radius.sm", "radius.md", "radius.lg", "radius.xl"]
    radius_values = [kit["tokens"]["radii"][p]["value"]["default"]["value"] for p in radii]
    assert radius_values == sorted(radius_values), radius_values


def test_a_flat_brand_keeps_shadows_empty_and_corners_square() -> None:
    kit = _normalize(_with_geometry("evidence_website_insight", _harvest("flat_brand")))
    assert kit["tokens"]["shadows"] == {}, "no box-shadow anywhere IS the finding"
    # Square corners measure nothing (a 0px radius is not a scale step), so the
    # radius ladder stays honestly derived.
    assert all(
        entry["provenance"]["source"].startswith("derived:")
        for entry in kit["tokens"]["radii"].values()
    )
    # …while its 1px card border and 64px rhythm ARE measured.
    assert kit["tokens"]["stroke_widths"]["stroke.width.card"]["provenance"][
        "source"
    ].startswith("website:")
    assert any(s.startswith("website:") for s in _sources(kit["tokens"]["spacing"]))


def test_an_unmeasured_kit_keeps_every_derived_token() -> None:
    kit = _normalize(_evidence("evidence_minimal"))
    for group, scale in (
        ("spacing", "derived:spacing-scale"),
        ("radii", "derived:radius-scale"),
        ("stroke_widths", "derived:stroke-scale"),
    ):
        assert set(_sources(kit["tokens"][group])) == {scale}
        for entry in kit["tokens"][group].values():
            assert entry["provenance"]["confidence"] == 0.6
    assert kit["tokens"]["shadows"] == {}


def test_partial_measurement_leaves_the_rest_derived() -> None:
    """One measured surface class must not silently re-label the whole group."""
    evidence = _evidence("evidence_minimal").model_copy(
        update={
            "numbers": parse_geometry(
                {
                    "url": "https://partial.example/",
                    "surfaces": [
                        {
                            "cls": "button",
                            "radius": [10, 10, 10, 10],
                            "borderStyle": "none",
                            "border": [0, 0, 0, 0],
                            "padding": [0, 0, 0, 0],
                        }
                    ],
                },
                page_url="https://partial.example/",
            ).numbers
        }
    )
    kit = _normalize(evidence)
    radii = kit["tokens"]["radii"]
    assert radii["radius.button"]["provenance"]["source"].startswith("website:")
    assert radii["radius.button"]["value"]["default"]["value"] == 10.0
    assert radii["radius.none"]["provenance"]["source"] == "derived:radius-scale"
    assert set(_sources(kit["tokens"]["stroke_widths"])) == {"derived:stroke-scale"}
    assert kit["tokens"]["shadows"] == {}


# --------------------------------------------------------------------------- #
# Emission: section background surfaces (surface.band.<hex>), Wave 2 A9
# --------------------------------------------------------------------------- #


def _bands(kit: dict) -> dict[str, dict]:
    return {path: entry for path, entry in kit["tokens"]["colors"].items() if path.startswith("surface.band")}


def _band_values(kit: dict) -> dict[str, str]:
    return {path: entry["value"]["default"]["value"] for path, entry in _bands(kit).items()}


def test_every_flat_band_colour_no_surface_token_holds_exactly_is_minted_by_its_value() -> None:
    """Stripe: white (only `text.inverse` holds #FFFFFF, an ink), navy, and the 380px footer tint."""
    kit = _normalize(_with_geometry("evidence_website_insight", _harvest("stripe_home")))
    assert _band_values(kit) == {
        "surface.band.ffffff": "#FFFFFF", "surface.band.0d1738": "#0D1738", "surface.band.f8fafd": "#F8FAFD",
    }
    navy = kit["tokens"]["colors"]["surface.band.0d1738"]
    assert navy["role"] == "surface" and navy["value"]["modes"] == {}
    assert navy["provenance"]["source"].startswith("website:https://stripe.com")
    assert "section background (sections 3, 5)" in navy["provenance"]["source"]
    assert navy["provenance"]["confidence"] == MEASURED_CONFIDENCE
    assert navy["description"] == "section background (2 bands, 3318px)"
    assert kit["tokens"]["colors"]["surface.band.f8fafd"]["description"] == "section background (1 band, 380px)"


def test_a_band_an_existing_surface_token_holds_exactly_mints_nothing() -> None:
    kit = _normalize(_synthetic([_section(0, "rgb(245, 245, 245)", 900), _section(1, "rgb(20, 40, 120)", 900)]))
    assert set(_bands(kit)) == {"surface.band.142878"}, "#F5F5F5 is this kit's surface.page exactly"


def test_near_misses_are_minted_never_merged() -> None:
    """flat_brand's #111111 is within merge distance of surface.inverse #121212 — and not equal."""
    kit = _normalize(_with_geometry("evidence_website_insight", _harvest("flat_brand")))
    assert set(_bands(kit)) == {"surface.band.ffffff", "surface.band.111111"}


def test_band_names_do_not_move_when_the_band_order_does() -> None:
    forward = _normalize(_synthetic([
        _section(0, "rgb(255, 255, 255)", 900), _section(1, "rgb(1, 64, 54)", 700), _section(2, "rgb(255, 233, 196)", 600),
    ]))
    backward = _normalize(_synthetic([
        _section(0, "rgb(255, 233, 196)", 600), _section(1, "rgb(1, 64, 54)", 700), _section(2, "rgb(255, 255, 255)", 900),
    ]))
    assert set(_bands(forward)) == set(_bands(backward)) == {
        "surface.band.ffffff", "surface.band.014036", "surface.band.ffe9c4",
    }


def test_gradient_image_and_translucent_bands_name_nothing() -> None:
    kit = _normalize(_synthetic([
        _section(0, "rgb(255, 255, 255)", 900),
        _section(1, "rgb(200, 10, 10)", 900, gradient=True),
        _section(2, "rgb(200, 10, 10)", 900, image=True),
        _section(3, "rgba(20, 40, 120, 0.04)", 900),
    ]))
    assert set(_bands(kit)) == {"surface.band.ffffff"}
    flat = _normalize(_synthetic([_section(0, "rgb(200, 10, 10)", 900)]))
    assert _band_values(flat) == {"surface.band.c80a0a": "#C80A0A"}


def test_a_band_with_measured_text_gets_it_as_its_contrast_pair() -> None:
    kit = _normalize(_synthetic([
        _section(0, "rgb(255, 255, 255)", 900),
        {**_section(1, "rgb(1, 64, 54)", 700), "ink": "rgb(255, 255, 255)"},
        {**_section(2, "rgb(40, 36, 30)", 600), "ink": "rgb(250, 245, 230)"},
    ]))
    pairs = kit["constraints"]["contrast_pairs"]
    assert {"foreground": "text.inverse", "background": "surface.band.014036", "min_ratio": 4.5} in pairs
    assert {"foreground": "text.band.28241e", "background": "surface.band.28241e", "min_ratio": 4.5} in pairs
    assert kit["tokens"]["colors"]["text.band.28241e"]["value"]["default"]["value"] == "#FAF5E6"


def test_a_translucent_token_holds_no_opaque_band_or_ink_colour() -> None:
    """Band matches are exact, alpha included: `#F5F5F580` is not the colour of a flat `#F5F5F5` band."""
    pointer = EvidencePointer(source="website", locator="https://synthetic.example/ :: section 0 (section)")
    band = SectionBackground(index=0, background="#F5F5F5", height_px=900, pointer=pointer)
    minted, skipped = build_band_surfaces([band], {"surface.page": "#F5F5F580"})
    assert [surface.path for surface in minted] == ["surface.band.f5f5f5"] and skipped == 0
    assert build_band_surfaces([band], {"surface.page": "#F5F5F5"}) == ([], 0)
    assert build_band_surfaces([band], {"surface.page": "#F5F5F5FF"}) == ([], 0)
    # …and the text on a band: a translucent token never holds the opaque ink measured there.
    surface = BandSurface(
        path="surface.band.28241e", hex="#28241E", description="section background (1 band, 600px)",
        provenance="website:https://synthetic.example/ :: section background (sections 0)", ink_hex="#FAF5E6",
    )

    def builder_holding(value: str) -> KitBuilder:
        builder = KitBuilder(_evidence("evidence_website_insight"), brand_kit_id="b", version=1, name="B", created_at=_CREATED_AT)
        builder.colors["text.cream"] = {"value": {"default": {"kind": "hex", "value": value}, "modes": {}}}
        return builder

    assert _band_ink(builder_holding("#FAF5E680"), surface) == "text.band.28241e"
    assert _band_ink(builder_holding("#FAF5E6"), surface) == "text.cream"


def test_band_minting_is_deterministic() -> None:
    evidence = _with_geometry("evidence_website_insight", _harvest("stripe_home"))
    assert json.dumps(_normalize(evidence), sort_keys=True) == json.dumps(_normalize(evidence), sort_keys=True)


def test_a_kit_carrying_band_surfaces_still_validates_through_the_engine() -> None:
    kit = _normalize(_with_geometry("evidence_website_insight", _harvest("stripe_home")))
    assert "surface.band.0d1738" in kit["tokens"]["colors"]
    core = CoreClient()
    validated = core.validate_brand_kit(kit, product_ready=False)
    assert validated["ok"] is True
    assert [d for d in validated.get("diagnostics", []) if d.get("severity") == "error"] == []
    assert core.summarize_brand_kit(kit)["ok"] is True


# --------------------------------------------------------------------------- #
# The capture seam
# --------------------------------------------------------------------------- #


class _StubCore:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def ingest_asset(self, **kwargs):
        self.calls.append(kwargs)
        return {"asset": {"record": {"id": kwargs["asset_id"]}}}


def test_build_evidence_attaches_the_measured_geometry() -> None:
    snapshot = load_snapshot(SNAPSHOTS / "insight_rendered.json").model_copy(
        update={"geometry": _harvest("flat_brand")}
    )
    outcome = CaptureOutcome(
        snapshot=snapshot,
        tier="rendered",
        escalated=False,
        escalation_reason=None,
        diagnostics=[],
    )
    with tempfile.TemporaryDirectory() as store:
        evidence = build_evidence(
            outcome, core=_StubCore(), store_root=store, reporter=lambda *_: None
        )

    assert evidence.numbers, "the harvest reached the evidence bundle"
    assert [band.index for band in evidence.geometry.background_sequence] == [0, 1]
    assert any(shape.surface == "button" for shape in evidence.geometry.surfaces)
    # The evidence bundle is what rides the job row into slice 3's brief stage.
    assert "background_sequence" in evidence.model_dump()["geometry"]


def test_a_capture_without_a_harvest_still_builds_evidence() -> None:
    outcome = CaptureOutcome(
        snapshot=load_snapshot(SNAPSHOTS / "insight_rendered.json"),
        tier="rendered",
        escalated=False,
        escalation_reason=None,
        diagnostics=[],
    )
    with tempfile.TemporaryDirectory() as store:
        evidence = build_evidence(
            outcome, core=_StubCore(), store_root=store, reporter=lambda *_: None
        )
    assert evidence.numbers == [] and evidence.shadows == []
    assert evidence.geometry.surfaces == []
    assert evidence.colors and evidence.type_samples  # untouched


# --------------------------------------------------------------------------- #
# Byte-stability: nothing outside the four measured groups may move
# --------------------------------------------------------------------------- #


def test_colour_type_and_asset_extraction_are_byte_stable() -> None:
    for name in ("evidence_website_insight", "evidence_pdf_insight", "evidence_minimal"):
        expected = json.loads((EXPECTED / f"{name}.json").read_text())
        produced = normalize_evidence(
            _evidence(name),
            brand_kit_id=f"brand_kit_ingest_{name}",
            version=1,
            name=f"Ingested {name}",
            created_at=_CREATED_AT,
        )
        kit = json.loads(json.dumps(produced.brand_kit, sort_keys=True))
        golden = expected["brand_kit"]
        for group in _MEASURED_GROUPS:
            kit["tokens"].pop(group)
            golden["tokens"].pop(group)
        assert kit == golden, name
        assert produced.ingestion_report == expected["ingestion_report"], name


# --------------------------------------------------------------------------- #
# Transforms as evidence (Wave 2 A9 FX-C2 fix round 1)
# --------------------------------------------------------------------------- #


def test_a_transform_leftover_is_no_transform() -> None:
    """An entrance held one millisecond before its end reads a sub-pixel leftover; rounded, it is the
    identity, and the identity is no transform."""
    assert normalize_transform("matrix(1, 0, 0, 1, 0, 1.88911e-06)") == "none"
    assert normalize_transform("matrix(1, 0, 0, 1, 0, 0.000334674)") == "none"
    assert normalize_transform("matrix(1.0000003, 0, 0, 1.0000003, 0, 0)") == "none"
    assert normalize_transform("matrix(1, -1e-07, 1e-07, 1, 0, 0)") == "none"
    assert normalize_transform("matrix(1, 0, 0, 1, 0, 0)") == "none"
    identity_3d = "matrix3d(1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)"
    assert normalize_transform(identity_3d) == "none"
    assert normalize_transform("matrix3d(1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0.001, 0, 0.004, 1)") == "none"


def test_a_real_transform_is_kept_as_the_browser_writes_it() -> None:
    for value in ("matrix(1, 0, 0, 1, 0, -2)", "matrix(0.98, 0, 0, 0.98, 0, 0)", "matrix(1, 0, 0, 1, 4, 0)",
                  "matrix(1, 0, 0, 1, 0, 24)", "matrix(-1, 0, 0, -1, 0, 0)"):
        assert normalize_transform(value) == value, value
    # Precision beyond the rounding goes; no "-0" and no trailing zeros are written.
    assert normalize_transform("matrix(0.707107, 0.707107, -0.707107, 0.707107, 0, 0)") == (
        "matrix(0.7071, 0.7071, -0.7071, 0.7071, 0, 0)"
    )
    assert normalize_transform("matrix(1.02996, 0, 0, 1.02996, 0, 0)") == "matrix(1.03, 0, 0, 1.03, 0, 0)"
    assert normalize_transform("matrix(0.5, -0.00001, 0, 0.5, 12.3456, -0.001)") == "matrix(0.5, 0, 0, 0.5, 12.35, 0)"
    assert normalize_transform(
        "matrix3d(1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, -0.00416667, 0, 4.0000001, -12.345678, 1)"
    ) == "matrix3d(1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, -0.0042, 0, 4, -12.35, 1)"


def test_anything_else_passes_through_unchanged() -> None:
    for value in (None, "none", "", "translateY(4px)", "matrix(1, 0, 0, 1, 0)", "matrix(1, 0, 0, 1, 0, nan)",
                  "matrix(a, b, c, d, e, f)", 3):
        assert normalize_transform(value) == value, value



def _normalized(evidence):
    return normalize_evidence(evidence, brand_kit_id="brand_kit_geometry", version=1, name="Geometry", created_at=_CREATED_AT)


def test_s6_1_a_band_text_colour_that_does_not_read_is_replaced_by_one_that_does() -> None:
    result = _normalized(_synthetic([
        _section(0, "rgb(255, 255, 255)", 900),
        {**_section(1, "rgb(243, 240, 232)", 700), "ink": "rgb(245, 166, 35)"},   # orange on cream, 1.78:1
        {**_section(2, "rgb(11, 37, 69)", 600), "ink": "rgb(34, 34, 34)"},        # dark grey on navy, 1.03:1
    ]))
    kit, diagnostics = result.brand_kit, result.diagnostics
    colors, pairs = kit["tokens"]["colors"], kit["constraints"]["contrast_pairs"]
    by_band = {p["background"]: p["foreground"] for p in pairs if p["background"].startswith("surface.band.")}
    from lumen_ingestion.colorspace import contrast_ratio
    for band, ink in by_band.items():
        ratio = contrast_ratio(colors[ink]["value"]["default"]["value"], colors[band]["value"]["default"]["value"])
        assert ratio >= 4.5, (band, ink, ratio)
    assert [d["code"] for d in diagnostics if d["code"] == "LUMI0609"] == ["LUMI0609", "LUMI0609"]
    assert "#F5A623" in next(d["message"] for d in diagnostics if d["code"] == "LUMI0609")
    # The brand's own text colour beats a generic one whenever it reads (D4): the kit's text.primary
    # reads on cream, so the cream band's pair names it and no text.band.f3f0e8 is minted.
    assert contrast_ratio(colors["text.primary"]["value"]["default"]["value"], "#F3F0E8") >= 4.5
    assert by_band["surface.band.f3f0e8"] == "text.primary"
    assert "text.band.f3f0e8" not in colors


def test_s6_1_a_band_text_colour_that_reads_is_kept_as_measured() -> None:
    result = _normalized(_synthetic([
        _section(0, "rgb(255, 255, 255)", 900),
        {**_section(1, "rgb(40, 36, 30)", 600), "ink": "rgb(250, 245, 230)"},
    ]))
    assert result.brand_kit["tokens"]["colors"]["text.band.28241e"]["value"]["default"]["value"] == "#FAF5E6"
    assert not [d for d in result.diagnostics if d["code"] == "LUMI0609"]


def test_s6_1_readable_ink_prefers_the_measured_ink_then_the_kits_own_then_black_or_white() -> None:
    from lumen_ingestion.colorspace import contrast_ratio
    from lumen_ingestion.normalizer.bands import readable_ink

    def band(hex_value: str, ink: str) -> BandSurface:
        return BandSurface(path=f"surface.band.{hex_value[1:].lower()}", hex=hex_value,
                           provenance="website:https://x.example/ :: section background (sections 1)",
                           description="section background (1 band, 600px)", ink_hex=ink)

    # (a) the measured ink reads: it is kept.
    assert readable_ink(band("#28241E", "#FAF5E6"), ["#111111", "#FFFFFF"]) == ("#FAF5E6", True)
    # (b) the measured ink fails; the kit's text.primary reads: it wins over black and white.
    assert readable_ink(band("#F3F0E8", "#F5A623"), ["#1F2937", "#FFFFFF"]) == ("#1F2937", False)
    # (c) the measured ink and both kit candidates fail: the better of black and white.
    grey = band("#777777", "#7A7A7A")
    ink, measured = readable_ink(grey, ["#6A6A6A", "#8A8A8A"])
    best = max(("#0B0F14", "#FFFFFF"), key=lambda option: contrast_ratio(option, "#777777"))
    assert (ink, measured) == (best, False)
    if max(contrast_ratio("#0B0F14", "#777777"), contrast_ratio("#FFFFFF", "#777777")) >= 4.5:
        assert contrast_ratio(ink, "#777777") >= 4.5
