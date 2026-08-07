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

HTML_MAX_BYTES = 2 * 1024 * 1024


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
