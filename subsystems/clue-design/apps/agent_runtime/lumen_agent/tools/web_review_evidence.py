"""Receipts for pixels actually returned to reviewers, never an aesthetic verdict.

The ledger is turn-local. Identity includes page, document revision, render and
image bytes, so reads from a different snapshot cannot qualify the current one.
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
from typing import Any

from PIL import Image

TILE_HEIGHT = 1200
TILE_OVERLAP = 100


def tile_count(height: int) -> int:
    stride = TILE_HEIGHT - TILE_OVERLAP
    return 1 + (max(0, height - TILE_HEIGHT) + stride - 1) // stride


def index_ranges(indexes: list[int]) -> list[list[int]]:
    ranges: list[list[int]] = []
    for index in indexes:
        if ranges and index == ranges[-1][1] + 1:
            ranges[-1][1] = index
        else:
            ranges.append([index, index])
    return ranges


def image_identity(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    with Image.open(io.BytesIO(raw)) as image:
        width, height = image.size
    return {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "pixel_width": width,
        "pixel_height": height,
        "tile_count": tile_count(height),
    }


class ReviewObservations:
    def __init__(self) -> None:
        self.images: dict[tuple[str, str], dict[str, Any]] = {}
        self.walks: dict[str, dict[str, Any]] = {}
        self.sources: dict[str, dict[str, Any]] = {}

    def shown(
        self,
        *,
        page_id: str,
        version: int | None,
        iteration: int | None,
        target: str,
        path: Path,
        index: int | None = None,
    ) -> None:
        identity = image_identity(path) | {"version": version, "iteration": iteration}
        key = (page_id, target)
        receipt = self.images.get(key)
        if not receipt or receipt["identity"] != identity:
            receipt = {"identity": identity, "overview": False, "tiles": set()}
            self.images[key] = receipt
        if index is None:
            receipt["overview"] = True
            if identity["tile_count"] == 1:
                receipt["tiles"].add(0)
        elif 0 <= index < identity["tile_count"]:
            receipt["tiles"].add(index)

    def image_report(
        self,
        *,
        page_id: str,
        version: int,
        preview_version: int | None,
        iteration: int | None,
        target: str,
        path: str | None,
    ) -> dict[str, Any]:
        empty = {
            "target": target,
            "overview_shown": False,
            "shown_tile_indexes": [],
            "readable_coverage_complete": False,
        }
        if not path:
            return empty | {"status": "missing"}
        try:
            identity = image_identity(Path(path)) | {
                "version": preview_version,
                "iteration": iteration,
            }
        except (OSError, ValueError, Image.DecompressionBombError):
            return empty | {"status": "unreadable"}
        current = preview_version == version
        receipt = self.images.get((page_id, target)) if current else None
        matches = receipt is not None and receipt["identity"] == identity
        shown = sorted(receipt["tiles"]) if matches else []
        missing = [i for i in range(identity["tile_count"]) if i not in shown]
        return empty | {
            "status": "current" if current else "stale",
            "source": identity,
            "overview_shown": bool(matches and receipt["overview"]),
            "shown_tile_indexes": shown,
            "unseen_tile_index_ranges": index_ranges(missing),
            "readable_coverage_complete": current and not missing,
            "next_target": f"{target}:tile:{missing[0]}" if current and missing else None,
        }

    def record_walk(self, page_id: str, version: int, result: dict[str, Any]) -> None:
        self.walks[page_id] = {
            "version": version,
            **{
                key: result.get(key)
                for key in (
                    "evidence_settled",
                    "reference_unavailable",
                    "comparison",
                    "broken_clones",
                    "page_findings",
                    "diagnostics",
                    "advice_available",
                )
            },
            "unobserved_capture_classes": [
                item.get("class") for item in result.get("captures", []) if not item.get("made")
            ],
        }

    def record_walk_failure(self, page_id: str, version: int, code: str) -> None:
        prior = self.walks.get(page_id)
        if prior and prior.get("failed"):
            prior = prior.get("previous_observation")
        self.walks[page_id] = {
            "version": version,
            "failed": True,
            "error_code": code,
            "previous_observation": prior,
        }

    def walk_report(self, page_id: str, version: int, has_fragments: bool) -> dict[str, Any]:
        receipt = self.walks.get(page_id)
        if receipt is None:
            return {"status": "missing" if has_fragments else "not_applicable"}
        status = "failed" if receipt.get("failed") else "current"
        return {**receipt, "status": status if receipt["version"] == version else "stale"}
