"""Shared Python-side identity rules for P6 custom components."""

from __future__ import annotations

import re


CUSTOM_COMPONENT_SLUG_PATTERN = re.compile(
    r"^[a-z0-9](?:[a-z0-9]|-(?!-)){0,62}[a-z0-9]$|^[a-z0-9]$"
)


def custom_component_slug_is_valid(slug: str) -> bool:
    return bool(CUSTOM_COMPONENT_SLUG_PATTERN.fullmatch(slug))
