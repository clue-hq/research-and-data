"""Account-only Exa assignment for quality revision 7; older and person jobs stay pinned."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from clue_api.arv2.account_research_claims import JobScope

RESOURCE_ROOT = (
    Path(__file__).parents[3] / "agents/catalog/research-quality/provider-requests/account-deep/v1"
)


def uses_account_exa_brief(scope: JobScope) -> bool:
    return (
        scope.subject_kind == "account"
        and scope.catalog_version == "v4"
        and int((scope.input_refs or {}).get("quality_recipe_version", 5)) >= 7
    )


def uses_account_discovery(scope: JobScope) -> bool:
    """The discovery-first account instructions and full-result handoff are revision-pinned."""
    return (
        uses_account_exa_brief(scope)
        and int((scope.input_refs or {}).get("quality_recipe_version", 5)) >= 12
    )


def account_exa_arguments(
    *,
    charter: str,
    additional_queries: list[str],
    num_results: int,
    same_name_exclusions: list[str] | None = None,
) -> dict[str, Any]:
    """Build the same assignment for dispatch and prompt-only capture, without compiling context.

    The agent owns its complete charter, including its investigative probes.
    Fixed files are included in the quality launch resource manifest.
    """
    query = charter
    if same_name_exclusions:
        query += "\n\nEXCLUDE SAME-NAME ENTITIES\n" + "\n".join(same_name_exclusions)
    settings = json.loads((RESOURCE_ROOT / "request-config.json").read_text())
    return {
        "system_prompt": (RESOURCE_ROOT / "exa-system.md").read_text(),
        "query": query,
        "additional_queries": additional_queries or None,
        "num_results": num_results,
        "output_schema": settings["outputSchema"],
        "contents": settings["contents"],
    }
