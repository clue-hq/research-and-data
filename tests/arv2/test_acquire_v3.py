"""acquire_research_evidence version 3: new footprint jobs; versions 1 and 2 stay exactly as pinned."""

from __future__ import annotations

from pathlib import Path

import yaml

from clue_api.arv2.quality_provider_tools import (
    ACQUISITIONS,
    ACQUISITIONS_V3,
    AcquireResearchToolV2,
    AcquireResearchToolV3,
)
from clue_api.quality_research_wiring import CATALOG_ROOT, quality_tools

FOOTPRINT_JOBS = {
    "find_podcasts",
    "find_videos",
    "find_handles",
    "linkedin_activity",
    "x_posts",
    "instagram_posts",
    "facebook_posts",
    "company_linkedin_posts",
}


def test_v2_schema_fingerprint_unchanged():
    profile = yaml.safe_load(
        (
            Path(CATALOG_ROOT) / "profiles/quality-person-research/v30-person/profile.yaml"
        ).read_text()
    )
    pin = next(t for t in profile["tools"] if t["name"] == "acquire_research_evidence")
    descriptor = quality_tools(None, None, purge=False).descriptor("acquire_research_evidence", "2")
    assert pin["version"] == "2"
    assert descriptor.input_schema_sha256 == pin["input_schema_sha256"]
    assert descriptor.output_schema_sha256 == pin["output_schema_sha256"]


def test_v3_job_names():
    assert (ACQUISITIONS - {"discover_media"}) | FOOTPRINT_JOBS == ACQUISITIONS_V3
    assert AcquireResearchToolV3.version == "3" and AcquireResearchToolV2.version == "2"


def test_v3_registered_beside_v1_and_v2():
    registry = quality_tools(None, None, purge=False)
    assert {"1", "2", "3"} <= set(registry.versions("acquire_research_evidence"))
