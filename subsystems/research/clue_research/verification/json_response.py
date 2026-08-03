"""Shared bounded JSON-object extraction for model judge responses."""

from __future__ import annotations

import json


def first_json_object(value: str) -> dict[str, object] | None:
    """Return the first decodable top-level JSON object, tolerating fences and prose.

    Both verification judges fail closed after this extraction if the object does not validate
    against their strict response schema.
    """

    decoder = json.JSONDecoder()
    index = value.find("{")
    while index != -1:
        try:
            parsed, end = decoder.raw_decode(value, index)
        except (json.JSONDecodeError, ValueError):
            parsed = None
        if isinstance(parsed, dict):
            next_index = value.find("{", end)
            while next_index != -1:
                try:
                    second, _ = decoder.raw_decode(value, next_index)
                except (json.JSONDecodeError, ValueError):
                    second = None
                if isinstance(second, dict):
                    return None
                next_index = value.find("{", next_index + 1)
            return parsed
        index = value.find("{", index + 1)
    return None


__all__ = ["first_json_object"]
