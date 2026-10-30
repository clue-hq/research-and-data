"""An attached file's name on disk (spec 2026-10-30 §3.3; review M-11).

One rule for both sides of the seam: the platform read that hands a design run the chat's files,
and the design agents' folder writer. A person's filename becomes one path segment that can never
climb out of its folder, with no leading dots, and short enough for any disk: uploads allow 255
characters, disks allow 255 bytes, so the stem is cut on a character boundary and the extension
kept.
"""

from __future__ import annotations

from pathlib import PurePosixPath

__all__ = ["ATTACHMENT_NAME_MAX_BYTES", "safe_attachment_name"]

#: Room left under the disk's 255 bytes for a "-2" clash suffix.
ATTACHMENT_NAME_MAX_BYTES = 240


def safe_attachment_name(name: str, *, max_bytes: int = ATTACHMENT_NAME_MAX_BYTES) -> str:
    segment = PurePosixPath(name.replace("\\", "/")).name.strip().lstrip(".") or "attachment"
    stem, suffix = PurePosixPath(segment).stem, PurePosixPath(segment).suffix
    budget = max_bytes - len(suffix.encode("utf-8"))
    stem = stem.encode("utf-8")[: max(budget, 0)].decode("utf-8", errors="ignore") or "attachment"
    return stem + suffix
