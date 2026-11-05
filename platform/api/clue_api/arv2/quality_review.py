"""Recipe 40: what the account agent reads when it reviews its people's research.

This reports what happened to each person and what was found. What that means for the verdict, who
to nominate next and which seats stay open are the agent's decisions (the ``account-review`` skill).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.account_research_claims import CURRENT_TITLE_FIELD, JobScope
from clue_api.arv2.quality_json_dossier import read_json_dossier
from clue_core import EntityId, decode_jsonb
from clue_research.claimstore import WorkspaceScope, claims_for
from clue_storage import StorageBackend

#: What the review needs of a finding; bookkeeping such as its review status stays in the dossier.
_FINDING_FIELDS = (
    "id",
    "topic",
    "finding",
    "attribution",
    "time_context",
    "qualifications",
    "agent_interpretation",
    "source_paths",
)
_SETTLED = frozenset({"completed", "needs_review", "failed"})


async def _title(conn: AsyncConnection, workspace_id: str, contact: UUID) -> str:
    from clue_api.arv2.account_research_driver import _newest_string

    claims = await claims_for(
        conn, EntityId(contact), scope=WorkspaceScope.for_workspace(workspace_id)
    )
    return _newest_string(claims, CURRENT_TITLE_FIELD)


async def _findings(
    conn: AsyncConnection,
    storage: StorageBackend,
    scope: JobScope,
    context_id: UUID,
    *,
    job_id: UUID,
    contact: UUID,
    input_refs: dict[str, Any],
) -> list[dict[str, Any]]:
    person = replace(
        scope,
        job_id=job_id,
        subject_kind="person",
        contact_id=EntityId(contact),
        input_refs=input_refs,
    )
    saved = await read_json_dossier(conn, storage, person, context_id)
    return [
        {key: finding[key] for key in _FINDING_FIELDS if finding.get(key) not in (None, [])}
        for section in saved.get("document", {}).get("sections", [])
        for finding in section.get("findings", [])
    ]


async def review_input(
    conn: AsyncConnection, storage: StorageBackend, scope: JobScope, context_id: UUID
) -> dict[str, JsonValue]:
    """Each person of this account job's generation, as they stand now."""
    rows = (
        (
            await conn.execute(
                text("""SELECT j.job_id,j.status,j.failure_code,j.subject_entity_id,
                    j.finalization_json,j.input_refs,e.full_name
                FROM arv2_account_research_generation g
                JOIN arv2_generation_child c ON c.generation_id=g.generation_id
                JOIN arv2_research_job j ON j.job_id=c.job_id AND j.workspace_id=c.workspace_id
                JOIN contact_entity e ON e.id=j.subject_entity_id
                WHERE g.initial_job_id=:job AND g.workspace_id=:ws
                ORDER BY j.created_at,j.job_id"""),
                {"job": scope.job_id, "ws": scope.workspace_id},
            )
        )
        .mappings()
        .all()
    )
    people: list[JsonValue] = []
    for row in rows:
        contact = row["subject_entity_id"]
        input_refs = decode_jsonb(row["input_refs"]) or {}
        if input_refs.get("privacy_stopped"):
            people.append({"contact_id": str(contact), "status": "privacy_stopped"})
            continue
        final = decode_jsonb(row["finalization_json"]) or {}
        people.append(
            {
                "contact_id": str(contact),
                "name": row["full_name"] or "",
                "title": await _title(conn, scope.workspace_id, contact),
                "status": row["status"],
                "still_running": row["status"] not in _SETTLED,
                "failure_code": row["failure_code"],
                "summary": final.get("summary"),
                "gaps": final.get("gaps") or [],
                "findings": await _findings(
                    conn,
                    storage,
                    scope,
                    context_id,
                    job_id=row["job_id"],
                    contact=contact,
                    input_refs=input_refs,
                ),
            }
        )
    return {"research_date": scope.today.isoformat(), "people": people}
