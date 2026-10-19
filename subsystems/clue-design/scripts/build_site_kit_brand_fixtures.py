"""Write site-kit's test kits from real values (Wave 2 A9, Task X5).

Run from subsystems/clue-design (offline: no browser, no model, no database):
  PYTHONPATH=.:apps/api:apps/agent_runtime ../../.venv/bin/python scripts/build_site_kit_brand_fixtures.py
It writes apps/frontend/packages/site-kit/test/fixtures/kits/<name>.json and the Brand page's
apps/frontend/src/features/brand-context/data/__fixtures__/brand-kit.measured.json (Task X6), and
test_measured_components.test_site_kit_fixture_kits_are_current fails when a committed file differs.

* garner / conduit / altcarbon — the spike's copies of the three real kits, unchanged: kits made
  before measurement (no minted tokens, no measured_components). site-kit's fallback tests run on them.
* garner.minted / conduit.minted — the same kits with the tokens the REAL minting code makes from
  values already measured on those sites: each hero button as the spike measured it at 1440
  (trials/puck-spike/data/brands/<brand>/measured.json; rest only, states were never captured
  there) and the section backgrounds of each kit's stored ingestion evidence
  (design_ingestion_job.evidence_json, ingest_9808f81d655c44e4b037284b4e01b2b9 for Garner and
  ingest_3e85c884c7c5457285874e8c1d6f016b for Conduit, read 2026-10-12).
* probe.minted — Garner's kit with every style, state, transition, icon, animation, reveal and band
  the real probe measured on apps/api/tests/fixtures/capture/style_states.html (its committed
  harvest), and brief recipes naming those button and card variants — written here, not by a model;
  the kit's name says it is a fixture.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from lumen_ingestion.brief import kit_token_names
from lumen_ingestion.capture.geometry import parse_geometry, variant_base
from lumen_ingestion.capture.motion import attach_keyframes
from lumen_ingestion.capture.snapshot import Stylesheet
from lumen_ingestion.evidence import EvidencePointer, MeasuredStyle, MotionEvidence, SectionBackground, StyleLook
from lumen_ingestion.measured_components import validate_measured_components
from lumen_ingestion.normalizer.bands import BandSurface, build_band_surfaces, opaque_hex, readable_ink
from lumen_ingestion.normalizer.component_tokens import mint_component_tokens
from lumen_ingestion.normalizer.emit import _color_role, _color_value, _mode_value, _provenance
from lumen_ingestion.normalizer.geometry import MEASURED_CONFIDENCE

DESIGN = Path(__file__).resolve().parents[1]
REPO = DESIGN.parents[1]
BRANDS = REPO / "trials" / "puck-spike" / "data" / "brands"
KITS_DIR = REPO / "apps" / "frontend" / "packages" / "site-kit" / "test" / "fixtures" / "kits"
#: The probe kit as `GET /brand-kits/{id}` serves it, for the Brand page's tests (Task X6).
BRAND_PAGE_FIXTURE = (
    REPO / "apps" / "frontend" / "src" / "features" / "brand-context" / "data" / "__fixtures__" / "brand-kit.measured.json"
)
CAPTURE = DESIGN / "apps" / "api" / "tests" / "fixtures" / "capture"

#: (index, background, height px) per band, from each kit's stored ingestion evidence.
BANDS = {
    "garner": ("https://garnerhealth.com/", [
        (0, "#FFFFFF", 1048), (1, "#F9FAF8", 645), (2, "#FFFFFF", 1127), (3, "#FFFFFF", 2009), (4, "#014036", 733),
        (5, "#FFFFFF", 224), (6, "#FFFFFF", 776), (7, "#FFFFFF", 675), (8, "#FFFFFF", 522),
    ]),
    "conduit": ("https://www.conduit.ai/", [
        (0, "#FFFFFF", 419), (1, "#FFFFFF", 580), (2, "#FFFFFF", 223), (3, "#FFFFFF", 821), (4, "#FFFFFF", 1167),
        (5, "#28241E", 887), (6, "#FFFFFF", 741), (7, "#FFFFFF", 584), (8, "#FFFFFF", 440),
    ]),
}

#: Each hero button as measured.json records it, against the stored brief recipe it is (Garner's
#: brief calls it solid.1: "light pills on photo and forest grounds"; Conduit's solid.2: "Primary demo
#: CTA"). Those are the old frequency names; the minted twin renames that recipe to the look-keyed
#: name a re-extraction would give it (founder Q-A9-6), so the two join as they will in production.
HERO_BUTTONS = {
    "garner": ("solid.1", 2, StyleLook(
        background="#FFFFFF", color="#0D2B25", border_color="#FFFFFF", border_width=[1, 1, 1, 1], border_style="solid",
        radius=[999.01, 999.01, 999.01, 999.01], pill=True, padding=[8, 24, 8, 24], height=42,
        font_family="Open Sans", font_size=14, font_weight=500, letter_spacing=0,
    )),
    "conduit": ("solid.2", 4, StyleLook(
        background="#28241E", color="#FFFFFF", border_width=[1, 1, 1, 1], border_style="solid",
        radius=[8, 8, 8, 8], pill=False, padding=[0, 10, 0, 10], height=32,
        font_family="bodyFont", font_size=16, font_weight=500, letter_spacing=0,
    )),
}


def _kit(brand: str) -> dict:
    return json.loads((BRANDS / brand / "kit.json").read_text())


def _measured_color(path: str, hex_value: str, description: str, provenance: str) -> dict:
    """The entry `KitBuilder.add_color` writes for a measured colour (no dark mode, MEASURED_CONFIDENCE)."""
    return {"value": _mode_value(_color_value(hex_value), {}), "role": _color_role(path),
            "description": description, "provenance": _provenance(provenance, MEASURED_CONFIDENCE)}


def _band_ink(colors: dict, band: BandSurface, *, measured: bool = True) -> str:
    """`normalizer._band_ink` over a kit's colours: the token holding the band's ink exactly, alpha
    included (an ink first), else `text.band.<hex of the band>`, minted here — described as measured,
    or as chosen to read (S6-1)."""
    matches = sorted(
        (
            path for path, entry in colors.items()
            if entry["value"]["default"].get("kind") == "hex"
            and opaque_hex(str(entry["value"]["default"].get("value") or "")) == band.ink_hex
        ),
        key=lambda path: (not path.startswith("text."), path),
    )
    if matches:
        return matches[0]
    path = "text.band." + band.path.rsplit(".", 1)[1]
    description = ("text measured on that section background" if measured
                   else "text chosen to read on that section background (the measured text did not)")
    colors[path] = _measured_color(path, band.ink_hex, description,
                                   band.provenance.replace("section background", "text on section background"))
    return path


def _add_bands(kit: dict, sequence: list[SectionBackground]) -> None:
    """The band surfaces, band inks and pairs `normalize_evidence` adds, applied to an existing kit:
    its band block and `_band_ink`, step for step (test_measured_components holds the two equal)."""
    colors = kit["tokens"]["colors"]
    surface_colors = {p: str(e["value"]["default"].get("value") or "") for p, e in colors.items()
                      if p.startswith("surface.") and e["value"]["default"].get("kind") == "hex"}
    bands, _ = build_band_surfaces(sequence, surface_colors)
    for band in bands:
        colors[band.path] = _measured_color(band.path, band.hex, band.description, band.provenance)
        if band.ink_hex:
            candidates = [str(colors[path]["value"]["default"].get("value") or "")
                          for path in ("text.primary", "text.inverse") if path in colors]
            ink, measured = readable_ink(band, candidates)
            kit["constraints"]["contrast_pairs"].append({
                "foreground": _band_ink(colors, replace(band, ink_hex=ink), measured=measured),
                "background": band.path, "min_ratio": 4.5,
            })


def _finish(kit: dict, section: dict | None) -> dict:
    if section is not None:
        kit["measured_components"] = validate_measured_components(section, token_names=kit_token_names(kit))
    return kit


def _measured_real(brand: str) -> dict:
    kit = _kit(brand)
    url, rows = BANDS[brand]
    _add_bands(kit, [
        SectionBackground(index=i, background=hex_value, height_px=height,
                          pointer=EvidencePointer(source="website", locator=f"{url} :: section {i} (section)"))
        for i, hex_value, height in rows
    ])
    old_name, count, look = HERO_BUTTONS[brand]
    # A re-extraction names this style by its fill (`solid.ffffff`, `solid.28241e`) and its brief
    # agent copies the name; the stored brief still says `solid.1`/`solid.2`, so that one recipe is
    # renamed here. The kit's other recipes keep their old names, like any kit made before measurement.
    variant = variant_base("solid", look.background)
    for recipe in kit["brief"]["component_recipes"]:
        if recipe["component"] == "button" and recipe["variant"] == old_name:
            recipe["variant"] = variant
    style = MeasuredStyle(surface="button", variant=variant, count=count, probed="rest-only", rest=look,
                          pointer=EvidencePointer(source="website", locator=f"{url} :: button {variant}"))
    return _finish(kit, mint_component_tokens(kit, [style], MotionEvidence()).section)


def _probe() -> dict:
    kit = _kit("garner")
    kit["name"] = "Probe fixture (style_states.html)"
    harvest = json.loads((CAPTURE / "style_states.harvest.json").read_text())
    parsed = parse_geometry(harvest, page_url="https://fixture.test/")
    css = (CAPTURE / "style_states.html").read_text().split("<style>", 1)[1].split("</style>", 1)[0]
    motion = attach_keyframes(parsed.motion, [Stylesheet(url="https://fixture.test/", text=css)])
    _add_bands(kit, parsed.background_sequence)
    result = mint_component_tokens(kit, parsed.styles, motion)
    kit["brief"]["component_recipes"] = [
        {"component": s["component"], "variant": s["variant"], "radius": None, "padding": None, "border": None,
         "shadow": None, "background": None, "text": None, "unmapped": ["Probe fixture style."], "confidence": "high"}
        for s in result.section["styles"] if s["component"] in ("button", "card")
    ]
    return _finish(kit, result.section)


def build_all() -> dict[str, str]:
    kits = {
        "garner.json": _kit("garner"), "conduit.json": _kit("conduit"), "altcarbon.json": _kit("altcarbon"),
        "garner.minted.json": _measured_real("garner"), "conduit.minted.json": _measured_real("conduit"),
        "probe.minted.json": _probe(),
    }
    return {name: json.dumps(kit, indent=1, sort_keys=True, ensure_ascii=False) + "\n" for name, kit in kits.items()}


def build_brand_page(kits: dict[str, str]) -> str:
    """The probe kit through the design API's own detail DTO — the exact body the Brand page reads."""
    from lumen_api.dto import brand_kit_detail_dto

    kit = json.loads(kits["probe.minted.json"])
    record = {
        "brand_kit_id": kit["id"], "version": kit["version"], "name": kit["name"], "approval_status": "draft",
        "product_ready": False, "source": "website", "brand_kit": kit, "brand_summary": {}, "diagnostics": [],
        "created_at": None, "updated_at": None,
    }
    return json.dumps(brand_kit_detail_dto(record), indent=1, sort_keys=True, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    KITS_DIR.mkdir(parents=True, exist_ok=True)
    texts = build_all()
    for name, text in texts.items():
        (KITS_DIR / name).write_text(text)
        print(f"wrote {KITS_DIR / name}")
    BRAND_PAGE_FIXTURE.write_text(build_brand_page(texts))
    print(f"wrote {BRAND_PAGE_FIXTURE}")
