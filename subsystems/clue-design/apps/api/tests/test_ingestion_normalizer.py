from __future__ import annotations

import json
import os
import random
from pathlib import Path

import pytest

from lumen_api.core import CoreClient
from lumen_api.main import create_app
from lumen_ingestion import BrandEvidence, normalize_evidence
from lumen_ingestion.colorspace import contrast_ratio
from lumen_ingestion.normalizer.required import (
    REQUIRED_COLOR_TOKENS,
    REQUIRED_OPACITY_TOKENS,
    REQUIRED_RADIUS_TOKENS,
    REQUIRED_SPACING_TOKENS,
    REQUIRED_STROKE_WIDTH_TOKENS,
    REQUIRED_TYPOGRAPHY_TOKENS,
)

from fastapi.testclient import TestClient

from conftest import make_client

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "ingestion"
EXPECTED_DIR = FIXTURE_DIR / "expected"

FIXTURES = ["evidence_website_insight", "evidence_pdf_insight", "evidence_minimal"]

_CREATED_AT = "2026-07-05"


def _load(name: str) -> BrandEvidence:
    return BrandEvidence.model_validate(json.loads((FIXTURE_DIR / f"{name}.json").read_text()))


def _normalize(name: str):
    return normalize_evidence(
        _load(name),
        brand_kit_id=f"brand_kit_ingest_{name}",
        version=1,
        name=f"Ingested {name}",
        created_at=_CREATED_AT,
    )


def _snapshot(name: str) -> dict:
    result = _normalize(name)
    return {
        "brand_kit": result.brand_kit,
        "ingestion_report": result.ingestion_report,
        "diagnostics": result.diagnostics,
    }


def _dumps(payload: dict) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


# --- 1. Golden snapshots ---------------------------------------------------


@pytest.mark.parametrize("name", FIXTURES)
def test_golden_snapshot(name: str) -> None:
    snapshot = _snapshot(name)
    expected_path = EXPECTED_DIR / f"{name}.json"
    if os.environ.get("UPDATE_INGESTION_SNAPSHOTS") == "1":
        EXPECTED_DIR.mkdir(parents=True, exist_ok=True)
        expected_path.write_text(_dumps(snapshot))
        pytest.skip(f"snapshot {name} regenerated")
    expected = json.loads(expected_path.read_text())
    assert snapshot == expected


# --- randomized evidence bundles ------------------------------------------

_HEX = "0123456789ABCDEF"
_ROLE_HINTS = [
    "page-bg",
    "body-text",
    "heading-text",
    "button-bg",
    "button-text",
    "link",
    "border",
    "accent",
    "custom-prop:--x",
    "named:Special",
    "shade-system",
]
_SOURCE_KINDS = [
    {"kind": "manual", "label": "random", "confidence": 0.5},
    {"kind": "website", "url": "https://random.example", "captured_at": "2026-07-05", "confidence": 0.6},
    {"kind": "agent_extract", "model": "test", "confidence": 0.5},
]


def _random_hex(rng: random.Random) -> str:
    return "#" + "".join(rng.choice(_HEX) for _ in range(6))


def _random_evidence(rng: random.Random) -> BrandEvidence:
    n_colors = rng.randint(0, 8)
    colors = []
    for i in range(n_colors):
        hints = rng.sample(_ROLE_HINTS, rng.randint(0, 3))
        colors.append(
            {
                "value": _random_hex(rng),
                "weight": round(rng.uniform(0.1, 20.0), 2),
                "theme": rng.choice(["light", "light", "light", "dark"]),
                "role_hints": hints,
                "name": rng.choice([None, None, "Swatch"]),
                "pointer": {"source": "website", "locator": f"selector-{i}"},
            }
        )
    type_samples = []
    for label in rng.sample(["h1", "h2", "body", "button", "caption"], rng.randint(0, 3)):
        type_samples.append(
            {
                "label": label,
                "family": rng.choice(["Inter", "Aeonik", None]),
                "weight": rng.choice([None, 400, 600, 700]),
                "size_px": rng.choice([None, 14.0, 16.0, 32.0, 48.0]),
                "pointer": {"source": "website", "locator": label},
            }
        )
    numbers = []
    for _ in range(rng.randint(0, 4)):
        numbers.append(
            {
                "kind": rng.choice(["spacing", "radius"]),
                "value": rng.choice([4.0, 8.0, 12.0, 16.0, 24.0, 48.0, 64.0]),
                "weight": 1.0,
                "role_hints": rng.sample(["section", "card", "button", "padding", "margin"], rng.randint(0, 2)),
                "pointer": {"source": "website", "locator": "n"},
            }
        )
    return BrandEvidence.model_validate(
        {
            "schema_version": 1,
            "source": rng.choice(_SOURCE_KINDS),
            "colors": colors,
            "type_samples": type_samples,
            "numbers": numbers,
        }
    )


def _all_bundles():
    bundles = [(name, _load(name)) for name in FIXTURES]
    rng = random.Random(0)
    for i in range(20):
        bundles.append((f"random-{i}", _random_evidence(rng)))
    return bundles


# --- 2. Required-token property -------------------------------------------


def test_required_tokens_and_gaps() -> None:
    for label, evidence in _all_bundles():
        result = normalize_evidence(
            evidence, brand_kit_id="bk", version=1, name="T", created_at=_CREATED_AT
        )
        tokens = result.brand_kit["tokens"]
        colors = tokens["colors"]

        for path in REQUIRED_COLOR_TOKENS:
            assert path in colors, f"{label}: missing color {path}"
            value = colors[path]["value"]["default"]
            assert value["kind"] == "hex"
            assert len(value["value"]) in (7, 9)
            # every required color token has a theme.dark mode value, except ramps
            if not path.startswith("palette."):
                assert "theme.dark" in colors[path]["value"]["modes"], f"{label}: {path} no dark"

        for path in REQUIRED_TYPOGRAPHY_TOKENS:
            assert path in tokens["typography"], f"{label}: missing type {path}"
        for path in REQUIRED_SPACING_TOKENS:
            assert path in tokens["spacing"], f"{label}: missing spacing {path}"
        for path in REQUIRED_RADIUS_TOKENS:
            assert path in tokens["radii"], f"{label}: missing radius {path}"
        for path in REQUIRED_STROKE_WIDTH_TOKENS:
            assert path in tokens["stroke_widths"], f"{label}: missing stroke {path}"
        for path in REQUIRED_OPACITY_TOKENS:
            assert path in tokens["opacity"], f"{label}: missing opacity {path}"

        # each gap has a matching diagnostic (asset gaps -> LUMI0220)
        codes = {d["code"] for d in result.diagnostics}
        for gap in result.ingestion_report["gaps"]:
            if gap.startswith("logo.") or gap.startswith("asset."):
                assert "LUMI0220" in codes


# --- 3. Contrast property --------------------------------------------------


def test_contrast_primary_on_page() -> None:
    for label, evidence in _all_bundles():
        result = normalize_evidence(
            evidence, brand_kit_id="bk", version=1, name="T", created_at=_CREATED_AT
        )
        colors = result.brand_kit["tokens"]["colors"]
        page = colors["surface.page"]["value"]["default"]["value"]
        text = colors["text.primary"]["value"]["default"]["value"]
        assert contrast_ratio(text, page) >= 4.5, f"{label}: light contrast {contrast_ratio(text, page)}"

        page_dark = colors["surface.page"]["value"]["modes"]["theme.dark"]["value"]
        text_dark = colors["text.primary"]["value"]["modes"]["theme.dark"]["value"]
        assert contrast_ratio(text_dark, page_dark) >= 4.5, f"{label}: dark contrast"


# --- 4. Determinism --------------------------------------------------------


@pytest.mark.parametrize("name", FIXTURES)
def test_determinism(name: str) -> None:
    a = _normalize(name)
    b = _normalize(name)
    assert json.dumps(a.brand_kit, sort_keys=True) == json.dumps(b.brand_kit, sort_keys=True)
    assert json.dumps(a.ingestion_report, sort_keys=True) == json.dumps(b.ingestion_report, sort_keys=True)


# --- 5. Engine round-trip (the DoD) ---------------------------------------


@pytest.mark.parametrize("name", FIXTURES)
def test_engine_round_trip_validates(name: str) -> None:
    result = _normalize(name)
    core = CoreClient()
    validated = core.validate_brand_kit(result.brand_kit, product_ready=False)
    assert validated["ok"] is True
    errors = [d for d in validated.get("diagnostics", []) if d.get("severity") == "error"]
    assert errors == []
    summary = core.summarize_brand_kit(result.brand_kit)
    assert summary["ok"] is True


@pytest.mark.parametrize("name", FIXTURES)
def test_post_brand_kit_persists(tmp_path: Path, name: str) -> None:
    result = _normalize(name)
    app = create_app(tmp_path / f"engine-cache-{name}")
    client = make_client(app)
    response = client.post(
        "/brand-kits",
        json={"brand_kit": result.brand_kit, "source": "api", "product_ready": False},
    )
    assert response.status_code == 200, response.text
    kit_id = result.brand_kit["id"]
    loaded = client.get(f"/brand-kits/{kit_id}")
    assert loaded.status_code == 200
    assert loaded.json()["brand_kit"]["id"] == kit_id


# --- 6. Dark synthesis marked ---------------------------------------------


def test_dark_colorway_marks() -> None:
    website = _normalize("evidence_website_insight")
    assert website.ingestion_report["dark_colorway"] == "synthesized"
    assert any(d["code"] == "LUMI0210" for d in website.diagnostics)

    pdf = _normalize("evidence_pdf_insight")
    assert pdf.ingestion_report["dark_colorway"] == "captured"
    assert not any(d["code"] == "LUMI0210" for d in pdf.diagnostics)


# --- 7. Extras -------------------------------------------------------------


def test_soft_indigo_extra_with_alias() -> None:
    result = _normalize("evidence_website_insight")
    colors = result.brand_kit["tokens"]["colors"]
    # Soft Indigo appears as a slugged palette.extra token, carrying its human
    # name on the description. A space-bearing name cannot be an alias key
    # (engine LUMB0120), so the alias lives under the path-safe slug reference.
    assert "palette.extra.soft-indigo" in colors
    assert colors["palette.extra.soft-indigo"]["description"] == "Soft Indigo"
    assert colors["palette.extra.soft-indigo"]["value"]["default"] == {
        "kind": "hex",
        "value": "#8080F9",
    }
    # A single-word named extra (Aqua) is aliasable and gets an alias entry.
    aliases = result.brand_kit["tokens"]["aliases"]
    assert aliases["Aqua"]["token"] == "palette.extra.aqua"


# --- K4 rung 2: type.size ramp + font metrics ------------------------------------


def test_normalizer_emits_the_type_size_ramp() -> None:
    """Every ingested kit carries the canonical 13-step `type.size.*` ramp —
    the vocabulary the styles compiler, knowledge docs, and DSL author share.
    Without metrics the values are the reference table verbatim."""
    kit = _normalize("evidence_website_insight").brand_kit
    numbers = kit["tokens"]["numbers"]
    ramp = {k: v for k, v in numbers.items() if k.startswith("type.size.")}
    assert len(ramp) == 13
    assert ramp["type.size.md"]["value"]["default"]["value"] == 16.0
    assert ramp["type.size.7xl"]["value"]["default"]["value"] == 80.0
    assert ramp["type.size.md"]["role"] == "font_size"
    assert "type-size-ramp" in ramp["type.size.md"]["provenance"]["source"]


# ---------------------------------------------------------------------------
# custody-honest type roles (the apollo.io D5 incident, 2026-08-26)
#
# apollo's kit declared `type.stat` as seasonMix weight 700 while custodying
# only a weight-300 seasonMix face. The engine substituted the nearest face and
# raised LUMS0104; the authoring agent read that as "this kit cannot do bold",
# abandoned the kit family, and invented `Bricolage Grotesque` to get an 800.
# A role must never declare a weight its own faces cannot paint.
# ---------------------------------------------------------------------------


def _apollo_evidence(faces: list[dict]) -> BrandEvidence:
    """Website evidence whose h1 asks for a weight the custodied faces may lack."""
    return BrandEvidence.model_validate(
        {
            "source": {"kind": "website", "reference": "https://www.apollo.io/"},
            "fonts": [
                {
                    "family": "seasonMix",
                    "role_hint": "heading",
                    "faces": faces,
                    "pointer": {
                        "source": "website",
                        "locator": "https://www.apollo.io/ :: @font-face",
                    },
                }
            ],
            "type_samples": [
                {
                    "label": "h1",
                    "family": "seasonMix",
                    "size_px": 72.0,
                    "weight": 700,
                    "pointer": {"source": "website", "locator": "h1"},
                }
            ],
        }
    )


_CUSTODIED_300 = [
    {
        "weight": 300,
        "style": "normal",
        "asset_id": "asset_ing_seasonmix300",
        "source_url": "https://www.apollo.io/fonts/seasonmix-light.woff2",
        "format": "woff2",
    }
]


def test_a_type_role_never_declares_a_weight_the_kit_cannot_paint() -> None:
    """THE red case: 700 asked of a family that ships only 300."""
    result = normalize_evidence(
        _apollo_evidence(_CUSTODIED_300),
        brand_kit_id="brand_kit_apollo_d5",
        version=1,
        name="Apollo",
        created_at=_CREATED_AT,
    )
    typography = result.brand_kit["tokens"]["typography"]

    for role in ("type.stat", "type.display", "type.headline"):
        weight = typography[role]["value"]["default"]["font_weight"]
        assert weight == 300, f"{role} declared {weight}, which seasonMix cannot paint"

    snapped = [d for d in result.diagnostics if d.get("code") == "LUMI0232"]
    assert snapped, "the moved declaration must be recorded, not silent"
    assert any("type.stat" in d["message"] for d in snapped)
    assert all("seasonMix" in d["message"] for d in snapped)


def test_a_role_whose_weight_is_custodied_is_left_exactly_alone() -> None:
    """The happy path: ship the 700 and `type.stat` keeps its 700, unremarked.

    Roles the kit still cannot serve (a 500 subtitle against a {300, 700} kit)
    do snap, and should — this pins that the snap is per-role, not per-kit.
    """
    faces = _CUSTODIED_300 + [
        {
            "weight": 700,
            "style": "normal",
            "asset_id": "asset_ing_seasonmix700",
            "source_url": "https://www.apollo.io/fonts/seasonmix-bold.woff2",
            "format": "woff2",
        }
    ]
    result = normalize_evidence(
        _apollo_evidence(faces),
        brand_kit_id="brand_kit_apollo_d5_ok",
        version=1,
        name="Apollo",
        created_at=_CREATED_AT,
    )
    typography = result.brand_kit["tokens"]["typography"]

    assert typography["type.stat"]["value"]["default"]["font_weight"] == 700
    snapped = [d for d in result.diagnostics if d.get("code") == "LUMI0232"]
    assert not any("type.stat" in d["message"] for d in snapped)
    # ...while a role this kit genuinely cannot serve is still moved and said.
    assert typography["type.subtitle"]["value"]["default"]["font_weight"] in (300, 700)
    assert any("type.subtitle" in d["message"] for d in snapped)


def test_an_uncustodied_family_is_not_snapped_against_faces_it_cannot_load() -> None:
    """A face declared with a URL and no asset_id is one we cannot paint AT ALL.
    That is the LUMI0230/0231 story, not this one — snapping a role onto a
    weight whose bytes we also lack would only invent a second falsehood."""
    declared_only = [
        {
            "weight": 300,
            "style": "normal",
            "asset_id": None,
            "source_url": "https://www.apollo.io/fonts/seasonmix-light.woff2",
            "format": "woff2",
        }
    ]
    result = normalize_evidence(
        _apollo_evidence(declared_only),
        brand_kit_id="brand_kit_apollo_d5_uncustodied",
        version=1,
        name="Apollo",
        created_at=_CREATED_AT,
    )
    typography = result.brand_kit["tokens"]["typography"]

    assert typography["type.stat"]["value"]["default"]["font_weight"] == 700
    assert "LUMI0232" not in [d.get("code") for d in result.diagnostics]


def test_the_nearest_custodied_weight_breaks_ties_toward_the_heavier_face() -> None:
    from lumen_ingestion.normalizer.typography import _nearest_custodied

    assert _nearest_custodied(700, [300]) == 300
    assert _nearest_custodied(700, [400, 600]) == 600
    assert _nearest_custodied(400, [300, 500]) == 500  # exact tie -> heavier
    assert _nearest_custodied(500, [100, 900]) == 900  # tie at 400 -> heavier


def test_normalizer_bakes_x_height_adjusted_ramp_and_metrics() -> None:
    """With measured metrics for the kit's heading family, the ramp values are
    reference-normalized (small x-height → larger pt) and the metrics block
    rides the kit's font entry for downstream consumers."""
    evidence = _load("evidence_website_insight")
    heading_family = None
    for font in evidence.fonts:
        heading_family = font.family
        break
    assert heading_family, "fixture must carry a font"
    metrics = {heading_family: {"units_per_em": 1000.0, "x_height_ratio": 0.44}}
    result = normalize_evidence(
        evidence,
        brand_kit_id="brand_kit_metrics_probe",
        version=1,
        name="Metrics probe",
        created_at=_CREATED_AT,
        font_metrics=metrics,
    )
    kit = result.brand_kit
    md = kit["tokens"]["numbers"]["type.size.md"]["value"]["default"]["value"]
    assert md > 16.0  # scaled up for the small-x-height font
    assert "x-height-normalized" in kit["tokens"]["numbers"]["type.size.md"]["provenance"]["source"]
    fonts = kit["assets"]["fonts"]
    assert any(f.get("metrics", {}).get("x_height_ratio") == 0.44 for f in fonts.values())


def test_a_misparsed_line_height_is_dropped_with_a_diagnostic_naming_the_role() -> None:
    from lumen_ingestion.evidence import BrandEvidence, EvidencePointer, TypeSample
    from lumen_ingestion.normalizer.typography import build_type_styles, resolve_anchors

    evidence = BrandEvidence.model_validate(
        {
            "schema_version": 1,
            "source": {"kind": "website", "url": "https://apollo.example"},
            "type_samples": [
                {
                    "label": "h1", "family": "seasonMix", "weight": 550, "size_px": 72.0,
                    "line_height": 4.5, "letter_spacing": -0.045,
                    "pointer": {"source": "website", "locator": "rendered :: h1"},
                },
                {
                    "label": "body", "family": "soehne", "weight": 400, "size_px": 18.0,
                    "line_height": 1.6875, "letter_spacing": 0.0106,
                    "pointer": {"source": "website", "locator": "rendered :: body"},
                },
            ],
        }
    )
    styles, diagnostics = build_type_styles(resolve_anchors(evidence))
    headline = styles["type.headline"]
    assert headline["line_height"] == 1.1  # the derived default, not 4.5
    assert headline["letter_spacing"] == -0.045  # within the em limit → kept
    assert styles["type.body"]["line_height"] == 1.6875  # a sane anchor is left alone
    codes = [d for d in diagnostics if d["code"] == "LUMI0233"]
    assert len(codes) == 1
    assert "type.headline" in codes[0]["message"] and "4.5" in codes[0]["message"]
    assert "rendered :: h1" in codes[0]["message"]


def test_an_absurd_letter_spacing_is_dropped_the_same_way() -> None:
    from lumen_ingestion.evidence import BrandEvidence
    from lumen_ingestion.normalizer.typography import build_type_styles, resolve_anchors

    evidence = BrandEvidence.model_validate(
        {
            "schema_version": 1,
            "source": {"kind": "website", "url": "https://apollo.example"},
            "type_samples": [
                {
                    "label": "h1", "family": "seasonMix", "weight": 700, "size_px": 72.0,
                    "line_height": 1.0, "letter_spacing": 2.0,
                    "pointer": {"source": "website", "locator": "rendered :: h1"},
                }
            ],
        }
    )
    styles, diagnostics = build_type_styles(resolve_anchors(evidence))
    assert styles["type.headline"]["line_height"] == 1.0
    assert styles["type.headline"]["letter_spacing"] == -0.01  # spec default for headline
    assert [d["code"] for d in diagnostics] == ["LUMI0233"]


# --- 2026-10-17: the heading ink, measured from headings on light backgrounds ---------------


def _heading_evidence(samples: list[tuple[str, str, str, float]]) -> BrandEvidence:
    return BrandEvidence.model_validate(
        {
            "schema_version": 1,
            "source": {"kind": "website", "url": "https://garner.example", "confidence": 0.9},
            "colors": [
                {"value": "#F9FAF8", "weight": 4.0, "role_hints": ["page-bg"],
                 "pointer": {"source": "website", "locator": "rendered :: body"}},
                {"value": "#0E1110", "weight": 3.0, "role_hints": ["body-text"],
                 "pointer": {"source": "website", "locator": "rendered :: body"}},
                {"value": "#047464", "weight": 2.0, "role_hints": ["button-bg"],
                 "pointer": {"source": "website", "locator": "rendered :: button"}},
            ],
            "type_samples": [
                {
                    "label": label, "family": "Stix Two Text", "weight": 500, "size_px": 48.0,
                    "color": color, "background": background, "area": area,
                    "pointer": {"source": "website", "locator": f"rendered :: {label}"},
                }
                for label, color, background, area in samples
            ],
        }
    )


def _normalize_evidence(evidence: BrandEvidence):
    return normalize_evidence(
        evidence, brand_kit_id="brand_kit_heading_ink", version=1, name="Heading ink",
        created_at=_CREATED_AT,
    )


def test_the_heading_ink_is_the_colour_of_headings_on_light_backgrounds() -> None:
    result = _normalize_evidence(_heading_evidence([
        ("h2", "#014036", "#F9FAF8", 20_000.0),
        ("h1", "#FFFFFF", "#014036", 60_000.0),  # a white hero heading on a dark band: ignored
        ("h3", "#014036", "#FFFFFF", 5_000.0),
    ]))
    colors = result.brand_kit["tokens"]["colors"]
    heading = colors["text.heading"]
    assert heading["value"]["default"]["value"] == "#014036"
    source = heading["provenance"]["source"]
    assert not source.startswith(("derived:", "default:"))  # measured, as site-kit reads it
    typography = result.brand_kit["tokens"]["typography"]
    for role in ("display", "headline", "title"):
        assert typography[f"type.{role}"]["value"]["default"]["color"] == "text.heading"
    assert typography["type.body"]["value"]["default"]["color"] == "text.primary"
    validated = CoreClient().validate_brand_kit(result.brand_kit, product_ready=False)
    assert validated["ok"] is True


def test_a_heading_that_cannot_be_read_on_what_the_compositor_sees_behind_it_is_over_imagery() -> None:
    """Garner's real capture (kit v4, 2026-10-17): its hero h1 is white over a video with a dark
    overlay, but the compositor sees only the page's white behind it (the video and the overlay are
    positioned children, not ancestor backgrounds), so "white on white" was counted as a heading on a
    light background and, being the largest heading, became the heading ink: white. A heading whose
    colour does not read against the backdrop the compositor found (under 3:1) sits over imagery, and
    is ignored; the forest h2s win."""
    result = _normalize_evidence(_heading_evidence([
        ("h1", "#FFFFFF", "#FFFFFF", 129_129.0),
        ("h1", "#FFFFFF", "#FFFFFF", 129_129.0),
        ("h2", "#014036", "#FFFFFF", 86_016.0),
        ("h2", "#FFFFFF", "#014036", 86_016.0),
        ("h2", "#FFFFFF", "#FFFFFF", 61_824.0),
        ("h2", "#014036", "#FFFFFF", 57_344.0),
        ("h3", "#000000", "#FFFFFF", 30_825.0),
    ]))
    assert result.brand_kit["tokens"]["colors"]["text.heading"]["value"]["default"]["value"] == "#014036"


def test_the_most_weighted_heading_colour_wins() -> None:
    result = _normalize_evidence(_heading_evidence([
        ("h2", "#014036", "#F9FAF8", 20_000.0),
        ("h3", "#333333", "#FFFFFF", 5_000.0),
        ("h3", "#333333", "#FFFFFF", 5_000.0),
    ]))
    assert result.brand_kit["tokens"]["colors"]["text.heading"]["value"]["default"]["value"] == "#014036"


def test_with_only_dark_background_headings_there_is_no_heading_ink() -> None:
    result = _normalize_evidence(_heading_evidence([
        ("h1", "#FFFFFF", "#014036", 60_000.0),
        ("h2", "#F9FAF8", "#0E1110", 20_000.0),
    ]))
    assert "text.heading" not in result.brand_kit["tokens"]["colors"]
    typography = result.brand_kit["tokens"]["typography"]
    for role in ("display", "headline", "title"):
        assert typography[f"type.{role}"]["value"]["default"]["color"] == "text.primary"
