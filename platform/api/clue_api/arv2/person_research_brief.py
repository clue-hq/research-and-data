"""Account-authored person assignments, retained as instructions rather than evidence."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.account_research_claims import JobScope
from clue_api.quality_research_artifacts import ResearchArtifacts
from clue_core import EntityId
from clue_storage import StorageBackend, read_verified_artifact

BRIEF_PATH = "/research/person-brief/0.json"


async def save_person_brief(
    conn: AsyncConnection,
    storage: StorageBackend,
    scope: JobScope,
    *,
    context_id: UUID,
    person_job_id: UUID,
    contact_id: EntityId,
    brief: str,
) -> dict[str, Any]:
    """Keep exact agent prose and existing context/source derivation and erasure bindings."""

    @asynccontextmanager
    async def connections() -> AsyncIterator[AsyncConnection]:
        yield conn

    sink = ResearchArtifacts(storage=storage, conn_factory=connections)
    sink.scope = replace(scope, job_id=person_job_id, subject_kind="person", contact_id=contact_id)
    sink.context_id = context_id
    body = {
        "kind": "person_research_delegation_not_evidence",
        "workspace_id": scope.workspace_id,
        "run_id": str(scope.run_id),
        "account_id": str(scope.account_id),
        "parent_job_id": str(scope.job_id),
        "person_job_id": str(person_job_id),
        "contact_id": str(contact_id),
        "context_id": str(context_id),
        "brief": brief,
    }
    ref = await sink.persist_body(
        workspace_id=scope.workspace_id,
        data=json.dumps(body, ensure_ascii=False, sort_keys=True).encode(),
        media_type="application/vnd.clue.person-research-brief+json",
        subject_bindings=((contact_id, "context"),),
    )
    return {"artifact_key": ref.artifact_key, "sha256": ref.sha256}


async def read_person_brief(
    conn: AsyncConnection, storage: StorageBackend, scope: JobScope, *, context_id: UUID
) -> dict[str, Any] | None:
    """Resolve from the owning persisted job; never trust an agent-supplied storage path."""
    row = (
        await conn.execute(
            text("""SELECT j.input_refs FROM arv2_research_job j
            JOIN arv2_research_run r ON r.run_id=j.run_id AND r.workspace_id=j.workspace_id
            WHERE j.job_id=:job AND j.workspace_id=:ws AND j.run_id=:run
              AND j.account_entity_id=:account AND j.subject_type='person'
              AND j.subject_entity_id=:contact AND r.context_id=:context
              AND r.project_id=:project"""),
            {
                "job": scope.job_id,
                "ws": scope.workspace_id,
                "run": scope.run_id,
                "account": scope.account_id,
                "contact": scope.person_subject_id,
                "context": context_id,
                "project": scope.project_id,
            },
        )
    ).one_or_none()
    if row is None:
        raise ValueError("person research job unavailable in this context")
    refs = row.input_refs or {}
    ref = refs.get("person_research_brief")
    if ref is None:
        return None  # Old and independently launched jobs keep their original instructions.
    artifact, raw = await read_verified_artifact(
        conn, storage, workspace_id=scope.workspace_id, storage_key=ref["artifact_key"]
    )
    if artifact.content_sha256 != ref["sha256"]:
        raise ValueError("person brief differs from its job pin")
    body: dict[str, Any] = json.loads(raw)
    expected = {
        "workspace_id": scope.workspace_id,
        "run_id": str(scope.run_id),
        "account_id": str(scope.account_id),
        "person_job_id": str(scope.job_id),
        "contact_id": str(scope.person_subject_id),
        "context_id": str(context_id),
        "parent_job_id": refs.get("parent_job_id"),
    }
    if any(body.get(key) != value for key, value in expected.items()):
        raise ValueError("person brief belongs to another job or context")
    return body


def person_task_instruction(
    brief: dict[str, Any], *, account_dossier_available: bool = False
) -> str:
    """Put the parent's exact assignment in the opening, with selective original reads."""
    assignment: str = brief["brief"]
    return (
        "Research this selected person. The account agent's delegation follows. "
        "It adds person-specific direction to your full research instructions; it is not "
        "source evidence or a request to discover a new committee.\n\n"
        + assignment
        + "\n\nRead /research/context.json for the selected person, discovery references, "
        "complete pinned seller/product/ICP/persona documents and account findings. "
        f"The original delegation is at {BRIEF_PATH}; original account reports, pages and "
        "transcripts are accessible through /evidence/index.json. Reuse acquired material "
        "and read further as useful. Relationship verification remains deferred; present "
        "uncertainty without requiring employment or location proofs."
        + (
            "\nThe account's completed JSON dossier and import receipt are available read-only at "
            "/research/parent-account-dossier.json. Read them as account context, alongside the "
            "original sources. The account agent may still be writing its narrative; your research "
            "can proceed independently. Write your own person dossier, not the account dossier."
            if account_dossier_available
            else ""
        )
    )
