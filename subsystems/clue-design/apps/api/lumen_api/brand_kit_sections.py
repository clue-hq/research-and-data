"""Kit sections the engine does not know survive every re-validation (Wave 2 A9).

`validate_brand_kit` re-serializes a kit through the typed Rust `BrandKit`, which has no field for
the brief, the grammar audit or the measured components, so they never come back. Ingestion attaches
them after the round trip (`lumen_ingestion/pipeline.py`); every route that re-validates a STORED kit
and publishes the result must carry them across the same way, or a logo choice silently deletes the
kit's brief. Verified 2026-10-12 by running the helper over Garner's kit.
"""

from __future__ import annotations

from typing import Any, Mapping

KIT_SECTIONS_OUTSIDE_ENGINE = ("brief", "grammar_audit", "measured_components", "responsive_type")


def carry_kit_sections(stored: Mapping[str, Any], validated: Mapping[str, Any]) -> dict:
    """`validated` (the engine's kit) with the stored kit's own sections put back."""
    carried = dict(validated)
    for key in KIT_SECTIONS_OUTSIDE_ENGINE:
        if key in stored and key not in carried:
            carried[key] = stored[key]
    return carried
