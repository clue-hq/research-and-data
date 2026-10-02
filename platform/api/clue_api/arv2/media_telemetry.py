"""Media outcomes on the shared logging/trace seams; Postgres remains authoritative.

Only identifiers, counts and closed outcome codes belong here. Tool payloads already reach
Langfuse through the agent callback and its redactor; do not duplicate transcripts in logs.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from clue_obs import current_ids, get_logger
from clue_obs.langfuse import event

log = get_logger(__name__)
MEDIA_TOOLS = frozenset({"discover_media", "read_media", "search_transcripts", "open_transcript"})


def scope(runtime: Any) -> dict[str, str]:
    return {
        "workspace_id": str(runtime.scope.workspace_id),
        "project_id": str(runtime.scope.project_id),
        "run_id": str(runtime.scope.run_id),
        "project_run_id": str(runtime.scope.project_run_id),
        "job_id": str(runtime.scope.job_id),
        "account_id": str(runtime.scope.account_id),
        "profile_version": runtime.scope.catalog_version,
    }


def record(runtime: Any, name: str, *, warning: bool = False, **fields: Any) -> None:
    metadata = {**scope(runtime), **fields}
    ids = current_ids()
    if ids:
        metadata.update(langfuse_trace_id=ids.trace_id, langfuse_observation_id=ids.observation_id)
    (log.warning if warning else log.info)("arv2.media." + name, **metadata)
    event("arv2.media." + name, level="WARNING" if warning else "DEFAULT", metadata=metadata)


def tool_result(runtime: Any, name: str, result: Mapping[str, Any]) -> None:
    if name not in MEDIA_TOOLS:
        return
    fields = {
        key: result[key]
        for key in (
            "state",
            "reused",
            "item_ref",
            "version_ref",
            "operation_ref",
            "discovery_ref",
            "search_ref",
            "total_saved",
            "next_offset",
        )
        if key in result
    }
    index = result.get("index", {})
    record(
        runtime,
        "tool_completed",
        tool=name,
        **fields,
        index_state=index.get("state"),
        gap_count=(
            len(result.get("gaps", []))
            + len(result.get("resolution_gaps", []))
            + len(index.get("gaps", []))
            + int(bool(result.get("gap")))
        ),
        result_count=len(result.get("results", result.get("candidates", []))),
    )
