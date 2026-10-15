"""The v4 launch pin names the actual governed resources, not legacy prompt lookalikes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from clue_api.arv2.account_research_catalog import CatalogResource, ResourceBundle, bundle_pin

ROOT = Path(__file__).parents[3] / "agents" / "catalog" / "research-quality"


CURRENT_RECIPE_VERSION = 27


def load_quality_resources(
    agent: str, *, version: int = CURRENT_RECIPE_VERSION, expected_pin: str | None = None
) -> ResourceBundle:
    if expected_pin is not None:
        for candidate in range(CURRENT_RECIPE_VERSION, 1, -1):
            bundle = load_quality_resources(agent, version=candidate)
            if bundle_pin(bundle) == expected_pin:
                return bundle
        raise ValueError("governed research launch resource pin is unavailable")
    if version not in range(2, CURRENT_RECIPE_VERSION + 1):
        raise ValueError("unknown governed research resource revision")
    raw = (ROOT / ("launch-v4.json" if version == 2 else f"launch-v4-r{version}.json")).read_text()
    manifest = json.loads(raw)
    resources = manifest["resources"]
    result = []
    for path, expected in sorted(resources.items()):
        body = (ROOT / path).read_text()
        actual = hashlib.sha256(body.encode()).hexdigest()
        if actual != expected:
            raise ValueError(f"quality resource differs from its launch pin: {path}")
        result.append(
            CatalogResource(
                kind="skill", ref=f"research-quality:{path}", version="v4", sha256=actual, body=body
            )
        )
    return ResourceBundle(
        profile=CatalogResource(
            kind="profile",
            ref=f"agent-profile:{agent}:v4",
            version="v4",
            sha256=hashlib.sha256(raw.encode()).hexdigest(),
            body=raw,
        ),
        prompt=CatalogResource(
            kind="prompt",
            ref="research-quality:ownership:v4",
            version="v4",
            sha256=hashlib.sha256(b"governed-research-quality-v4").hexdigest(),
            body="governed-research-quality-v4",
        ),
        skills=tuple(result),
    )
