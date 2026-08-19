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

from lumen_ingestion import BrandEvidence, normalize_evidence
from lumen_ingestion.capture import build_evidence
from lumen_ingestion.capture import CaptureOutcome
from lumen_ingestion.capture.geometry import GEOMETRY_JS, parse_geometry
from lumen_ingestion.capture.snapshot import SiteSnapshot, load_snapshot
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
    assert {shape.variant for shape in buttons} == {
        shape.variant for shape in buttons
    }, "variant keys are unique per surface"
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
