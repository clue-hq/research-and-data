"""The kit's `styles` token group survives the real engine round trip (Wave 2 A9, Task X1).

`validate_brand_kit` re-serializes a kit through the typed Rust `TokenCatalog`, and the pipeline
persists what comes back — a group the engine did not know used to vanish here.
"""

from __future__ import annotations

import json
from pathlib import Path

from lumen_api.core import CoreClient

ACME = Path(__file__).resolve().parents[3] / "crates" / "lumen-core" / "fixtures" / "brand_kits" / "acme_full.json"


def _token(value: dict) -> dict:
    return {
        "value": {"default": value, "modes": {}},
        "description": None,
        "provenance": {"source": "website:https://example.test/ :: button solid.047464 rest case", "confidence": 0.8},
    }


def _kit() -> dict:
    kit = json.loads(ACME.read_text())
    kit["tokens"]["styles"] = {
        "button.solid-047464.case": _token({"kind": "keyword", "property": "text-transform", "value": "uppercase"}),
        "motion.button.solid-047464.duration-1": _token({"kind": "duration", "ms": 200.0}),
    }
    return kit


def test_style_tokens_come_back_from_the_engine_unchanged() -> None:
    kit = _kit()
    validation = CoreClient().validate_brand_kit(kit, product_ready=False, raise_on_error=False)
    assert validation["ok"] is True
    assert validation["brand_kit"]["tokens"]["styles"] == kit["tokens"]["styles"]


def test_a_kit_without_style_tokens_comes_back_without_the_group() -> None:
    kit = _kit()
    del kit["tokens"]["styles"]
    validation = CoreClient().validate_brand_kit(kit, product_ready=False, raise_on_error=False)
    assert "styles" not in validation["brand_kit"]["tokens"]


def test_the_engine_refuses_a_style_token_ingestion_would_never_mint() -> None:
    kit = _kit()
    kit["tokens"]["styles"]["button.solid-047464.case"]["value"]["default"] = {
        "kind": "keyword",
        "property": "background-image",
        "value": "url(x)",
    }
    validation = CoreClient().validate_brand_kit(kit, product_ready=False, raise_on_error=False)
    errors = {d["code"] for d in validation["diagnostics"] if d["severity"] == "error"}
    assert "LUMB0260" in errors
