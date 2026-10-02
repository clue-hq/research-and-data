"""Resolve contextual research reads explicitly; never select an arbitrary seller/project."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.account_research_claims import JobScope
from clue_api.arv2.quality_relationships import read_committee
from clue_core import EntityId


@dataclass(frozen=True)
class QualitySelection:
    scope: JobScope | None
    context_id: UUID | None
    metadata: dict[str, Any]


async def select_quality_context(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    subject_id: UUID,
    subject_kind: str = "account",
    account_id: UUID | None = None,
    project_id: str | None = None,
    context_id: UUID | None = None,
) -> QualitySelection | None:
    rows = (
        (
            await conn.execute(
                text("""SELECT DISTINCT ON (r.project_id,j.account_entity_id)
        r.*, j.job_id,j.account_entity_id,j.profile_sha256 AS job_profile_sha256,
        a.canonical_name,a.primary_domain,
        g.generation_id,g.state AS quality_state,p.name AS project_name
        FROM arv2_research_run r JOIN arv2_research_job j ON j.run_id=r.run_id
        JOIN project p ON p.project_id=r.project_id AND p.workspace_id=r.workspace_id
        JOIN account_entity a ON a.id=j.account_entity_id AND a.workspace_id=r.workspace_id
        LEFT JOIN arv2_account_research_generation g ON g.run_id=j.run_id
          AND g.account_id=j.account_entity_id AND (g.initial_job_id=j.job_id
            OR g.initial_job_id::text=j.input_refs->>'parent_job_id')
        WHERE r.workspace_id=:ws AND r.context_id IS NOT NULL
          AND ((:kind='account' AND j.subject_type='account' AND j.account_entity_id=:subject)
            OR (:kind='contact' AND j.subject_type='person' AND j.subject_entity_id=:subject))
          AND (CAST(:account AS uuid) IS NULL OR j.account_entity_id=CAST(:account AS uuid))
          AND (CAST(:context AS uuid) IS NULL OR r.context_id=CAST(:context AS uuid))
        ORDER BY r.project_id,j.account_entity_id,r.created_at DESC,r.run_id DESC"""),
                {
                    "ws": workspace_id,
                    "subject": subject_id,
                    "kind": subject_kind,
                    "account": account_id,
                    "context": context_id,
                },
            )
        )
        .mappings()
        .all()
    )
    if not rows:
        if context_id is not None:
            return QualitySelection(
                None,
                None,
                {
                    "qualityState": "context_required",
                    "contexts": [],
                    "refreshPending": False,
                    "gaps": ["Requested research context is unavailable."],
                },
            )
        return None
    choices = [
        {
            "projectId": r["project_id"],
            "projectName": r["project_name"],
            "contextId": str(r["context_id"]),
            "accountId": str(r["account_entity_id"]),
        }
        for r in rows
    ]
    selected = [r for r in rows if project_id is None or r["project_id"] == project_id]
    if len(selected) != 1:
        return QualitySelection(
            None,
            None,
            {
                "qualityState": "context_required",
                "contexts": choices,
                "refreshPending": False,
                "gaps": ["Choose a project to view its research argument."],
            },
        )
    r = selected[0]
    from clue_api.arv2.quality_catalog import load_quality_resources

    bundle = (
        load_quality_resources(
            "arv2-person" if subject_kind == "contact" else "arv2-account",
            expected_pin=(r["job_profile_sha256"] or r["profile_sha256"])
            if subject_kind == "contact"
            else r["profile_sha256"],
        )
        if r["profile_ref"].endswith(":v4")
        else None
    )
    scope = JobScope(
        workspace_id=workspace_id,
        project_id=r["project_id"],
        project_run_id=r["project_run_id"],
        run_id=r["run_id"],
        job_id=r["job_id"],
        account_id=EntityId(r["account_entity_id"]),
        account_name=r["canonical_name"],
        account_domain=r["primary_domain"] or "",
        icp_markdown="",
        persona_markdown="",
        already_established="",
        effort=r["effort"],
        committee_cap=r["committee_cap"],
        today=datetime.now(UTC).date(),
        subject_kind="person" if subject_kind == "contact" else "account",
        contact_id=EntityId(subject_id) if subject_kind == "contact" else None,
        catalog_version="v4",
        input_refs={
            "quality_recipe_version": json.loads(bundle.profile.body)["recipe_version"]
            if bundle
            else 5
        },
    )
    members = await read_committee(
        conn, workspace_id=workspace_id, account_id=scope.account_id, context_id=r["context_id"]
    )
    return QualitySelection(
        scope,
        r["context_id"],
        {
            "projectId": r["project_id"],
            "projectName": r["project_name"],
            "contextId": str(r["context_id"]),
            "generationId": str(r["generation_id"]) if r["generation_id"] else None,
            "qualityState": r["quality_state"] or "researching",
            "refreshPending": True,
            "gaps": [],
            "contexts": choices,
            "committee": [m.model_dump(mode="json") for m in members],
        },
    )
