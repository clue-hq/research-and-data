"""The replayable capture bundle.

``SiteSnapshot`` is the golden-fixture format: capture records one, and tests
replay it through parse → evidence → normalize with zero network. Bytes ride
along base64-encoded so a snapshot is a single self-contained JSON file.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

# Match the page transport budget. A rendered marketing page can have more than
# 2 MiB of head markup before its first body image (observed on AWS). Capture
# preserves the entire document within this bound; it must never save a prefix.
HTML_MAX_BYTES = 5 * 1024 * 1024


class Stylesheet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    text: str


class Download(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    kind: Literal["font", "image", "logo", "screenshot", "og_image"]
    content_type: str | None = None
    bytes_b64: str
    sha256: str
    # How the page referenced this asset (clone-fidelity F0.2) — one of
    # ``candidates.ORIGINS``, or absent on a screenshot and on every pre-F0.2 fixture, which
    # is why both fields are optional with defaults rather than required.
    origin: str | None = None
    # True only when EVERY reference to this URL came from a
    # ``prefers-color-scheme: dark`` source. The signal has to survive the snapshot to be
    # worth harvesting: parse stamps it into the asset's locator, so the evidence — and the
    # human reading it — keeps knowing which rendition is the dark one.
    dark_scheme: bool = False


class SiteSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    requested_url: str
    final_url: str
    fetched_at: str
    tier: Literal["static", "rendered"]
    html: str
    stylesheets: list[Stylesheet] = []
    custom_props: dict[str, str] | None = None
    computed_samples: list[dict] | None = None
    # The rendered tier's brand-geometry harvest (design-brief slice 2). Optional
    # so every pre-slice-2 snapshot fixture still loads, and ``None`` on the
    # static tier, which has no live page to measure.
    geometry: dict | None = None
    # The render probe (Phase-1 brand-color overhaul): probe-resolved custom
    # properties, visibility-filtered element samples with absolute boxes, media
    # boxes, computed gradient stops, viewport width. Optional for the same
    # back-compat reason as ``geometry``; ``None`` on the static tier. Consumed
    # by ``lumen_ingestion.census`` together with the screenshot download.
    render_probe: dict | None = None
    downloads: list[Download] = []
    meta: dict = {}
    diagnostics: list[dict] = []

    def download_bytes(self, sha256: str) -> bytes | None:
        for entry in self.downloads:
            if entry.sha256 == sha256:
                return base64.b64decode(entry.bytes_b64)
        return None


def save_snapshot(snapshot: SiteSnapshot, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(snapshot.model_dump(), indent=2, sort_keys=True),
        encoding="utf-8",
    )


def load_snapshot(path: str | Path) -> SiteSnapshot:
    return SiteSnapshot.model_validate_json(Path(path).read_text(encoding="utf-8"))
