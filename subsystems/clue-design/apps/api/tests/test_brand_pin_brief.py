"""The leg's brand pin freezes the BRIEF, not just the tokens (slice 4, A3).

D5's design-leg pin is `(brand_kit_id, version)`, resolved fail-loud through
`load_brand_kit_by_value` at the dispatch gate. Slice 3 put the Creative Brief
*inside* the kit payload — so the pin should carry it for free, and a leg that
started against version N must keep designing against N's brief even after the
founder approves N+1 halfway through the conversation.

"Should" is the word this file removes. Nothing new is built here: the assertion
is that the brief rides the machinery that already exists, all the way into the
injected brand card the model actually reads.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import make_client

from lumen_agent.brand_card import build_brand_card

REPO_ROOT = Path(__file__).resolve().parents[3]


def _brief(*words: str) -> dict:
    """A minimal, valid `BrandBrief@1` whose characterization names the version."""
    return {
        "schema_version": 1,
        "characterization": {
            "words": list(words),
            "support": "The support line for " + " ".join(words),
            "confidence": "high",
        },
        "chromatic_moment": {"quiet": True, "confidence": "low"},
        "signature_compositions": [],
        "palette_application": [],
        "background_rhythm": {"bands": [], "confidence": "low"},
        "typographic_posture": {"signature_moves": [], "tokens": [], "confidence": "low"},
        "imagery_posture": {"slots": [], "absences": [], "confidence": "low"},
        "constraints": [
            {
                "rule": f"Only {words[0]} surfaces carry the accent",
                "scope": "sitewide",
                "confidence": "high",
            }
        ],
        "component_recipes": [],
        "diagnostics": [],
    }


def _kit_payload(version: int, brief: dict) -> dict:
    return {
        "id": "kit_pinned",
        "version": version,
        "name": "Pinned Brand",
        "approval_status": "approved",
        "description": None,
        "brief": brief,
    }


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    from lumen_api.main import create_app

    return make_client(create_app(tmp_path / "engine-cache"))


def test_the_leg_pin_freezes_the_brief_version(client: TestClient) -> None:
    """Version 1's brief survives version 2's approval, all the way to the card."""
    from lumen_api.design_store import HybridRepository
    from lumen_api.main import load_brand_kit_by_value

    from conftest import make_blob_store

    workspace_id = os.environ["LUMEN_DEV_WORKSPACE_ID"]
    repo = HybridRepository()
    repo.create_brand_kit(
        _kit_payload(1, _brief("quiet", "measured")), {"product_ready": False}, [], "website"
    )
    # ... and mid-conversation the founder approves the next extraction.
    repo.publish_next_brand_kit_version(
        _kit_payload(2, _brief("loud", "iridescent")),
        {"product_ready": False},
        [],
        "website",
        expected_base_version=1,
    )
    repo.update_brand_kit_approval("kit_pinned", "approved")

    blobs = make_blob_store(client.app)
    pinned, source, _manifest, _fonts = load_brand_kit_by_value(
        workspace_id=workspace_id,
        brand_kit_id="kit_pinned",
        version=1,
        blobs=blobs,
        source="leg_pin",
    )
    assert source == "leg_pin"
    assert pinned["version"] == 1
    assert pinned["brief"]["characterization"]["words"] == ["quiet", "measured"]

    # The whole point: what the model reads on this turn is version 1's brief.
    card = build_brand_card(pinned, source="leg_pin", include_brief=True)
    rendered = card["creative_brief"]["rendered"]
    assert "**quiet, measured**" in rendered
    assert "Only quiet surfaces carry the accent" in rendered
    assert "iridescent" not in rendered

    # And the pin is what did it — an unpinned read serves the newest version.
    latest, _, _, _ = load_brand_kit_by_value(
        workspace_id=workspace_id,
        brand_kit_id="kit_pinned",
        version=None,
        blobs=blobs,
        source="document",
    )
    assert latest["version"] == 2
    assert latest["brief"]["characterization"]["words"] == ["loud", "iridescent"]


def test_a_pre_brief_era_pinned_kit_still_resolves_and_carries_no_brief(
    client: TestClient,
) -> None:
    """Back-compat at the pin: a kit approved before briefs existed pins fine and
    yields exactly today's card."""
    from lumen_api.design_store import HybridRepository
    from lumen_api.main import load_brand_kit_by_value

    from conftest import make_blob_store

    workspace_id = os.environ["LUMEN_DEV_WORKSPACE_ID"]
    HybridRepository().create_brand_kit(
        {
            "id": "kit_pre_brief_pin",
            "version": 1,
            "name": "Legacy Brand",
            "approval_status": "approved",
            "description": None,
        },
        {"product_ready": False},
        [],
        "website",
    )
    pinned, _, _, _ = load_brand_kit_by_value(
        workspace_id=workspace_id,
        brand_kit_id="kit_pre_brief_pin",
        version=1,
        blobs=make_blob_store(client.app),
        source="leg_pin",
    )
    assert "brief" not in pinned
    card = build_brand_card(pinned, source="leg_pin", include_brief=True)
    assert "creative_brief" not in card
    assert card == build_brand_card(pinned, source="leg_pin")
