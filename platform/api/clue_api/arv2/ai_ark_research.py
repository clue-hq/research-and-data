"""AI Ark's research projection, separate from the untouched provider audit response.

Preserve record paths, IDs and typed enrichment for deterministic mappers and profile
reuse. Free-form provider prose is not a research source, including when nested inside
an employer, employment entry, technology or funding record. Never apply this projection
to Exa, website, job-board or media evidence.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

_PROSE_KEYS = frozenset(
    {
        "description",
        "shortdescription",
        "longdescription",
        "companydescription",
        "headline",
        "about",
        "aboutus",
        "bio",
        "biography",
        "overview",
        "tagline",
        "slogan",
    }
)


def enrichment_only(value: Any) -> Any:
    """Copy JSON, dropping AI Ark's descriptive fields without changing typed values.

    ``summary`` is a structured company container, not prose: retain its name, industry,
    staff and other factual fields. Likewise retain title, dated positions, financial
    records, technology names, email verification, pagination and metering metadata.
    """
    if isinstance(value, Mapping):
        return {
            key: enrichment_only(item)
            for key, item in value.items()
            if str(key).lower().replace("_", "").replace("-", "") not in _PROSE_KEYS
        }
    if isinstance(value, list):
        return [enrichment_only(item) for item in value]
    return value
