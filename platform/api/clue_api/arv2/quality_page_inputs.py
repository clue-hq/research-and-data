"""Exact dependencies for page synthesis; the same snapshot gates publication and reads."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.account_research_claims import JobScope
from clue_api.arv2.display.recipes import read_recipes
from clue_api.arv2.quality_generation import Generation, read_generation
from clue_api.arv2.quality_relationships import CommitteeMember, read_committee
from clue_api.arv2.research_operations import fingerprint
from clue_research.compliance import load_workspace_policy


@dataclass(frozen=True)
class PageInputs:
    generation: Generation
    manifest: dict[str, object]
    sha256: str
    members: tuple[CommitteeMember, ...]
    subjects: tuple[UUID, ...]


async def page_inputs(
    conn: AsyncConnection, scope: JobScope, *, context_id: UUID, page: str, lock: bool = False
) -> PageInputs:
    if page not in (("contact",) if scope.person_subject_id else ("overview", "insights")):
        raise ValueError("page does not belong to this research subject")
    gid = (
        await conn.execute(
            text("""SELECT g.generation_id
        FROM arv2_account_research_generation g
        JOIN arv2_research_job j ON j.job_id=g.initial_job_id
        WHERE g.workspace_id=:ws AND g.run_id=:run
          AND g.account_id=:account AND g.context_id=:context
          AND (j.subject_type='account' OR j.subject_entity_id=:subject)
        ORDER BY g.created_at DESC LIMIT 1"""),
            {
                "ws": scope.workspace_id,
                "run": scope.run_id,
                "account": scope.account_id,
                "context": context_id,
                "subject": scope.person_subject_id,
            },
        )
    ).scalar_one_or_none()
    if gid is None:
        raise ValueError("page has no account research generation")
    generation = await read_generation(
        conn, workspace_id=scope.workspace_id, generation_id=gid, lock=lock
    )
    if generation.state in ("suspended", "privacy_stopped"):
        raise ValueError("page generation is stopped")
    latest = (
        await conn.execute(
            text("""SELECT g.generation_id FROM arv2_account_research_generation g
        JOIN arv2_research_job j ON j.job_id=g.initial_job_id
        WHERE g.workspace_id=:ws AND g.project_id=:project AND g.account_id=:account
          AND g.context_id=:context
          AND (j.subject_type='account' OR j.subject_entity_id=:subject)
        ORDER BY g.created_at DESC,g.generation_id DESC LIMIT 1"""),
            {
                "ws": scope.workspace_id,
                "project": scope.project_id,
                "account": scope.account_id,
                "context": context_id,
                "subject": scope.person_subject_id,
            },
        )
    ).scalar_one()
    if latest != gid:
        raise ValueError("this research generation was replaced by a newer run")
    contacts = tuple(
        (
            await conn.execute(
                text("""SELECT DISTINCT contact_id FROM arv2_generation_child
        WHERE generation_id=:generation AND workspace_id=:ws ORDER BY contact_id"""),
                {"generation": gid, "ws": scope.workspace_id},
            )
        ).scalars()
    )
    subjects = tuple(
        sorted(
            {
                scope.account_id,
                *(contacts if scope.person_subject_id is None else ()),
                *([scope.person_subject_id] if scope.person_subject_id else []),
            }
        )
    )
    if lock:
        # Corrections/new assessments update these rows in the same transaction as the effect.
        # Do not lock claims afterward: that would invert the correction writer's lock order.
        for subject in subjects:
            await conn.execute(
                text(
                    "INSERT INTO claim_dependency_revision(workspace_id,entity_id) "
                    "VALUES(:ws,:subject) ON CONFLICT DO NOTHING"
                ),
                {"ws": scope.workspace_id, "subject": subject},
            )
    await conn.execute(
        text(
            "SELECT entity_id,revision FROM claim_dependency_revision "
            "WHERE workspace_id=:ws AND entity_id=ANY(:ids) ORDER BY entity_id"
            + (" FOR SHARE" if lock else "")
        ),
        {"ws": scope.workspace_id, "ids": list(subjects)},
    )
    # Locks serialize changes, but cache identity uses this context's actual inputs. A
    # correction to another project's interpretation must not stale this project's prose.
    claim_versions = (
        await conn.execute(
            text("""SELECT c.id,q.revision,q.conclusion,c.superseded_by
        FROM claim c JOIN claim_quality_current q ON q.claim_id=c.id
        WHERE c.workspace_id=:ws AND c.entity_id=ANY(:ids)
          AND (q.context_id IS NULL OR q.context_id=:context) ORDER BY c.id"""),
            {"ws": scope.workspace_id, "ids": list(subjects), "context": context_id},
        )
    ).all()
    members = await read_committee(
        conn, workspace_id=scope.workspace_id, account_id=scope.account_id, context_id=context_id
    )
    from typing import cast

    from clue_api.arv2.display.recipes import Page

    recipes = await read_recipes(conn, cast(Page, page), workspace_id=scope.workspace_id)
    context = (
        await conn.execute(
            text(
                "SELECT manifest_key FROM arv2_research_context_pin "
                "WHERE context_id=:context AND workspace_id=:ws AND project_id=:project"
            ),
            {"context": context_id, "ws": scope.workspace_id, "project": scope.project_id},
        )
    ).scalar_one()
    manifest: dict[str, object] = {
        "version": 1,
        "workspace_id": scope.workspace_id,
        "project_id": scope.project_id,
        "context_id": str(context_id),
        "context_manifest": context,
        "generation_id": str(gid),
        "input_revision": generation.input_revision,
        "subject_id": str(scope.person_subject_id or scope.account_id),
        "page": page,
        "claim_versions": [
            [
                str(row.id),
                row.revision,
                row.conclusion,
                str(row.superseded_by) if row.superseded_by else None,
            ]
            for row in claim_versions
        ],
        "membership": [m.model_dump(mode="json") for m in members],
        "recipes": [asdict(r) for r in recipes],
        "contract": "research-quality-pages-v1",
        "display_policy": (
            await load_workspace_policy(conn, workspace_id=scope.workspace_id)
        ).model_dump(mode="json"),
    }
    return PageInputs(generation, manifest, fingerprint(manifest), tuple(members), subjects)
