"""Release person work from a committed account import, independently of narrative completion."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.account_research_claims import JobScope
from clue_obs import get_logger
from clue_storage import StorageBackend, read_verified_artifact, retain_artifact

MIN_RECIPE = 18
#: Recipe 26+: a nominated person starts at once, while the account is still researching; their
#: contact page waits for the account's import (docs/superpowers/plans/2026-10-07-research-cost-
#: phase1.md Task 10).
RELEASE_AT_NOMINATION = 26
READY_KIND = "research_account_import_ready"
PARENT_DOSSIER_PATH = "/research/parent-account-dossier.json"
log = get_logger("arv2.person_release")


def releases_after_import(scope: JobScope) -> bool:
    return (
        scope.catalog_version == "v4"
        and int((scope.input_refs or {}).get("quality_recipe_version", 0)) >= MIN_RECIPE
    )


async def parent_dossier_ready(conn: AsyncConnection, scope: JobScope) -> bool:
    """Whether the person's parent account has a committed import to read now."""
    parent = (scope.input_refs or {}).get("parent_job_id")
    if not parent:
        return False
    return bool(
        (
            await conn.execute(
                text("""SELECT EXISTS (SELECT 1 FROM artifact_reference
        WHERE workspace_id=:ws AND reference_kind=:kind AND reference_id LIKE :parent||':%')"""),
                {"ws": scope.workspace_id, "kind": READY_KIND, "parent": str(parent)},
            )
        ).scalar_one()
    )


async def mark_account_import_ready(
    conn: AsyncConnection, scope: JobScope, saved: dict[str, Any]
) -> None:
    """Part of the import transaction. No queue/network call before commit."""
    if releases_after_import(scope) and saved["state"] == "complete":
        if not saved["receipt"]["complete"]:
            raise ValueError("Cannot announce an incomplete claim import")
        await conn.execute(
            text("""INSERT INTO arv2_research_import_ready
            (workspace_id,job_id,dossier_version,artifact_key)
            VALUES(:ws,:job,:version,:key) ON CONFLICT DO NOTHING"""),
            {
                "ws": scope.workspace_id,
                "job": scope.job_id,
                "version": saved["version"],
                "key": saved["artifact_key"],
            },
        )
    if scope.person_subject_id or not releases_after_import(scope) or saved["state"] != "complete":
        return
    if not saved["receipt"]["complete"]:
        raise ValueError("Cannot release people from an incomplete claim import")
    await retain_artifact(
        conn,
        workspace_id=scope.workspace_id,
        storage_key=saved["artifact_key"],
        reference_kind=READY_KIND,
        reference_id=f"{scope.job_id}:{saved['version']:010d}",
    )
    log.info(
        "arv2.account.person_research_ready",
        job_id=str(scope.job_id),
        dossier_version=saved["version"],
        imported_findings=len(saved["receipt"]["entries"]),
    )


async def ready_person_jobs(
    conn: AsyncConnection, *, generation_id: UUID | None = None
) -> list[dict[str, Any]]:
    """Shared settlement/recovery selection. Old pinned jobs retain their settlement policy."""
    rows = (
        (
            await conn.execute(
                text("""SELECT c.workspace_id,c.job_id,j.run_id,r.project_run_id,
        g.initial_job_id AS parent_job_id
        FROM arv2_generation_child c
        JOIN arv2_research_job j ON j.job_id=c.job_id AND j.workspace_id=c.workspace_id
        JOIN arv2_account_research_generation g ON g.generation_id=c.generation_id
          AND g.workspace_id=c.workspace_id
        JOIN arv2_research_job parent ON parent.job_id=g.initial_job_id
          AND parent.workspace_id=g.workspace_id
        JOIN arv2_research_run r ON r.run_id=j.run_id AND r.workspace_id=j.workspace_id
        WHERE j.status='not_started' AND j.subject_type='person'
          AND j.input_refs->>'parent_job_id'=CAST(parent.job_id AS text)
          AND j.run_id=parent.run_id AND j.account_entity_id=parent.account_entity_id
          AND g.state NOT IN ('suspended','privacy_stopped') AND parent.status<>'suspended'
          AND COALESCE(j.input_refs->>'privacy_stopped','false')<>'true'
          AND COALESCE(parent.input_refs->>'privacy_stopped','false')<>'true'
          AND (CAST(:generation AS uuid) IS NULL OR g.generation_id=:generation)
          AND CASE WHEN COALESCE((j.input_refs->>'quality_recipe_version')::int,0)>=:nomination
            THEN parent.status<>'not_started'
            WHEN COALESCE((j.input_refs->>'quality_recipe_version')::int,0)>=:minimum
            THEN EXISTS (SELECT 1 FROM artifact_reference a WHERE a.workspace_id=g.workspace_id
              AND a.reference_kind=:kind AND a.reference_id LIKE CAST(parent.job_id AS text)||':%')
            ELSE g.initial_settled_at IS NOT NULL END
        ORDER BY j.created_at,c.job_id LIMIT 200"""),
                {
                    "generation": generation_id,
                    "minimum": MIN_RECIPE,
                    "nomination": RELEASE_AT_NOMINATION,
                    "kind": READY_KIND,
                },
            )
        )
        .mappings()
        .all()
    )
    return [dict(row) for row in rows]


async def read_parent_dossier(
    conn: AsyncConnection,
    storage: StorageBackend,
    scope: JobScope,
    context_id: UUID,
) -> dict[str, Any]:
    """Only the child's actual parent in the same account/run/context can be inspected."""
    if not scope.person_subject_id or not releases_after_import(scope):
        raise ValueError("Parent dossier unavailable for this task")
    row = (
        (
            await conn.execute(
                text("""SELECT parent.job_id,a.storage_key
        FROM arv2_research_job child
        JOIN arv2_research_job parent
          ON CAST(parent.job_id AS text)=child.input_refs->>'parent_job_id'
          AND parent.workspace_id=child.workspace_id AND parent.run_id=child.run_id
          AND parent.account_entity_id=child.account_entity_id AND parent.subject_type='account'
        JOIN arv2_research_run r ON r.run_id=child.run_id AND r.workspace_id=child.workspace_id
        JOIN artifact_reference a ON a.workspace_id=parent.workspace_id AND a.reference_kind=:kind
          AND a.reference_id LIKE CAST(parent.job_id AS text)||':%'
        WHERE child.job_id=:child AND child.workspace_id=:ws AND child.run_id=:run
          AND child.subject_entity_id=:person AND child.account_entity_id=:account
          AND r.context_id=:context AND r.project_id=:project
          AND COALESCE(parent.input_refs->>'privacy_stopped','false')<>'true'
        ORDER BY a.reference_id DESC LIMIT 1"""),
                {
                    "child": scope.job_id,
                    "ws": scope.workspace_id,
                    "run": scope.run_id,
                    "person": scope.person_subject_id,
                    "account": scope.account_id,
                    "context": context_id,
                    "project": scope.project_id,
                    "kind": READY_KIND,
                },
            )
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise ValueError("Parent account has no available completed dossier import")
    _, raw = await read_verified_artifact(
        conn, storage, workspace_id=scope.workspace_id, storage_key=row["storage_key"]
    )
    saved = json.loads(raw)
    if (
        saved.get("job_id") != str(row["job_id"])
        or saved.get("context_id") != str(context_id)
        or saved.get("subject_id") != str(scope.account_id)
        or saved.get("state") != "complete"
        or not saved.get("receipt", {}).get("complete")
    ):
        raise ValueError("Parent dossier does not match this research assignment")
    return {
        "path": PARENT_DOSSIER_PATH,
        "parent_job_id": str(row["job_id"]),
        "version": saved["version"],
        "document": saved["document"],
        "receipt": saved["receipt"],
        "artifact_key": row["storage_key"],
        "read_only": True,
    }
