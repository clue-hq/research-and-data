"""Explicit recovery of delegation metadata from retained, identity-bound records.

Not an agent tool and never an automatic read-side mutation. Operators may call this in
a recovery transaction; ambiguity or missing originals fails closed rather than guessing.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.account_research_claims import JobScope
from clue_api.arv2.quality_catalog import load_quality_resources
from clue_storage import StorageBackend, read_verified_artifact


async def restore_person_delegation(
    conn: AsyncConnection, storage: StorageBackend, scope: JobScope, context_id: UUID
) -> dict[str, Any]:
    if not scope.person_subject_id:
        raise ValueError("Delegation recovery requires a person job")
    params = {
        "ws": scope.workspace_id,
        "job": scope.job_id,
        "run": scope.run_id,
        "account": scope.account_id,
        "contact": scope.person_subject_id,
        "context": context_id,
        "project": scope.project_id,
    }
    row = (
        (
            await conn.execute(
                text("""SELECT j.input_refs,j.profile_sha256,c.generation_id
            FROM arv2_research_job j
            JOIN arv2_generation_child c ON c.job_id=j.job_id AND c.workspace_id=j.workspace_id
            JOIN arv2_account_research_generation g ON g.generation_id=c.generation_id
              AND g.workspace_id=j.workspace_id AND g.account_id=j.account_entity_id
              AND g.run_id=j.run_id AND g.context_id=:context
            JOIN arv2_research_run r ON r.run_id=j.run_id AND r.workspace_id=j.workspace_id
            WHERE j.workspace_id=:ws AND j.job_id=:job AND j.run_id=:run
              AND j.account_entity_id=:account AND j.subject_entity_id=:contact
              AND j.subject_type='person' AND r.context_id=:context AND r.project_id=:project
            FOR UPDATE OF j"""),
                params,
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ValueError("No scoped child/generation record; delegation recovery refused")
    candidates = (
        (
            await conn.execute(
                text("""SELECT a.storage_key FROM artifact_reference ref
            JOIN artifact a ON a.storage_key=ref.storage_key AND a.workspace_id=ref.workspace_id
            WHERE ref.workspace_id=:ws AND ref.reference_kind='research_execution_output'
              AND ref.reference_id=:job_text
              AND a.media_type='application/vnd.clue.person-research-brief+json'"""),
                {**params, "job_text": str(scope.job_id)},
            )
        )
        .scalars()
        .all()
    )
    expected = {
        "kind": "person_research_delegation_not_evidence",
        "workspace_id": scope.workspace_id,
        "run_id": str(scope.run_id),
        "account_id": str(scope.account_id),
        "contact_id": str(scope.person_subject_id),
        "context_id": str(context_id),
        "person_job_id": str(scope.job_id),
    }
    matches = []
    for key in candidates:
        artifact, raw = await read_verified_artifact(
            conn, storage, workspace_id=scope.workspace_id, storage_key=key
        )
        body = json.loads(raw)
        if all(body.get(k) == v for k, v in expected.items()):
            matches.append((body, key, artifact.content_sha256))
    if len(matches) != 1:
        raise ValueError(
            "Need exactly one retained, scoped person brief; no delegation was changed"
        )
    body, key, sha = matches[0]
    parent_id = UUID(body["parent_job_id"])
    parent = (
        await conn.execute(
            text("""SELECT job_id FROM arv2_research_job WHERE workspace_id=:ws
            AND run_id=:run AND account_entity_id=:account AND job_id=:parent
            AND subject_type='account'"""),
            {**params, "parent": parent_id},
        )
    ).scalar_one_or_none()
    if parent is None:
        raise ValueError("Retained brief's account parent is unavailable; recovery refused")
    previous = dict(row["input_refs"] or {})
    if previous.get("parent_job_id") not in (None, str(scope.job_id), str(parent_id)):
        raise ValueError("Existing parent disagrees with retained brief; operator review required")
    bundle = load_quality_resources("arv2-person", expected_pin=row["profile_sha256"])
    restored = {
        "parent_job_id": str(parent_id),
        "generation_id": str(row["generation_id"]),
        "quality_recipe_version": json.loads(bundle.profile.body)["recipe_version"],
        "person_research_brief": {"artifact_key": key, "sha256": sha},
    }
    if previous.get("operation_id"):
        provider_job = (
            await conn.execute(
                text("""SELECT job_id FROM arv2_research_operation
                WHERE workspace_id=:ws AND run_id=:run AND account_id=:account
                  AND operation_id=:operation AND job_id IN (:job,:parent)"""),
                {**params, "parent": parent_id, "operation": UUID(previous["operation_id"])},
            )
        ).scalar_one_or_none()
        if provider_job is None:
            raise ValueError("Provider provenance is unavailable; recovery refused")
        restored["provider_job_id"] = str(provider_job)
    changed = any(previous.get(k) != v for k, v in restored.items())
    if changed:
        # Keep an explicit recovery marker; sources and authored findings are unchanged.
        restored["delegation_repair"] = {
            "version": 1,
            "previous_parent_job_id": previous.get("parent_job_id"),
            "brief_artifact_key": key,
        }
        await conn.execute(
            text("""UPDATE arv2_research_job SET input_refs=input_refs || CAST(:refs AS jsonb)
            WHERE workspace_id=:ws AND job_id=:job"""),
            {**params, "refs": json.dumps(restored)},
        )
    return {"changed": changed, "input_refs": {**previous, **restored}}
