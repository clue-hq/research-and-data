"""Read a knowledge document's YAML front matter — the inverse of ``render_markdown``."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import yaml

__all__ = ["document_identity", "parse_front_matter"]


def parse_front_matter(text: str, *, preserve_body: bool = False) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        raise ValueError("no front matter")
    head, sep, rest = text[4:].partition("\n---\n")
    if not sep:
        raise ValueError("no front matter")
    loaded = yaml.safe_load(head)
    if not isinstance(loaded, dict):
        raise ValueError("front matter is not a mapping")
    # The serializer inserts one separator newline; preserve user-authored whitespace after it.
    return loaded, rest.removeprefix("\n") if preserve_body else rest.lstrip("\n")


def document_identity(front: Mapping[str, Any]) -> tuple[str, str | None]:
    kind = front.get("kind")
    key = front.get("icp_key")
    return (
        (str(kind) if kind is not None else ""),
        (str(key) if isinstance(key, str) and key else None),
    )
