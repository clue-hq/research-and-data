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
    app = create_app(tmp_path / f"api_{name}.sqlite3")
    client = TestClient(app)
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
