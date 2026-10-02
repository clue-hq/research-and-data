"""Pinned person investigation requests for quality revision 11 and later."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from clue_api.arv2.account_research_claims import JobScope

RESOURCE_ROOT = (
    Path(__file__).parents[3] / "agents/catalog/research-quality/provider-requests/person-deep/v1"
)


def uses_person_exa_brief(scope: JobScope) -> bool:
    return (
        scope.subject_kind == "person"
        and scope.catalog_version == "v4"
        and int((scope.input_refs or {}).get("quality_recipe_version", 5)) >= 11
    )


def person_search_contents() -> dict[str, Any]:
    """Use the tested full-text/link settings for ordinary searches and page reads too."""
    contents: dict[str, Any] = json.loads((RESOURCE_ROOT / "request-config.json").read_text())[
        "contents"
    ]
    return contents


def person_exa_arguments(
    *,
    charter: str,
    additional_queries: list[str],
    num_results: int,
    highlights_query: str = "",
    same_name_exclusions: list[str] | None = None,
) -> dict[str, Any]:
    """The agent authors the assignment; code only applies the versioned provider settings."""
    settings = json.loads((RESOURCE_ROOT / "request-config.json").read_text())
    contents = settings["contents"]
    if highlights_query:
        contents["highlights"]["query"] = highlights_query
    query = charter
    if same_name_exclusions:
        query += "\n\nKNOWN SAME-NAME EXCLUSIONS\n" + "\n".join(same_name_exclusions)
    return {
        "system_prompt": (RESOURCE_ROOT / "exa-system.md").read_text(),
        "query": query,
        "additional_queries": additional_queries or None,
        "num_results": num_results,
        "output_schema": settings["outputSchema"],
        "contents": contents,
    }
