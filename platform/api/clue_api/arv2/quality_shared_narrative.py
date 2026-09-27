"""Project existing owner blocks into account Insights without another writer/model."""

from dataclasses import replace
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.account_research_claims import JobScope


async def shared_sections(
    conn: AsyncConnection,
    scope: JobScope,
    context_id: UUID,
    generation_id: UUID,
    block: dict[str, Any],
) -> tuple[set[str], set[str], list[str]]:
    from clue_api.arv2.quality_pages import read_page

    ready, stale, cited = set(), set(), []
    overview = await read_page(conn, scope, context_id=context_id, page="overview")
    notes = next(
        (
            s
            for s in overview["display_block"]["sections"]
            if s["key"] in ("watch-outs", "research-notes")
        ),
        None,
    )
    target = next(s for s in block["sections"] if s["key"] == "context-only")
    if notes:
        target.update({k: v for k, v in notes.items() if k not in {"key", "h1", "defaultOpen"}})
        ready.add("context-only")
        if notes.get("pending"):
            stale.add("context-only")
        for item in [
            *notes.get("intro", []),
            *(s for i in notes.get("items", []) for s in i["body"]),
        ]:
            cited.extend(item.get("claimIds", []))
    rows = (
        (
            await conn.execute(
                text("""SELECT c.contact_id,c.job_id,e.full_name,j.input_refs
        FROM arv2_generation_child c
        JOIN arv2_research_job j ON j.job_id=c.job_id AND j.workspace_id=c.workspace_id
        JOIN contact_entity e ON e.id=c.contact_id AND e.workspace_id=c.workspace_id
        WHERE c.generation_id=:generation AND c.workspace_id=:ws AND j.run_id=:run
          AND j.account_entity_id=:account AND j.subject_type='person'
          AND j.subject_entity_id=c.contact_id AND e.merged_into IS NULL
          AND COALESCE(j.input_refs->>'privacy_stopped','false')<>'true'
        ORDER BY c.contact_id"""),
                {
                    "generation": generation_id,
                    "ws": scope.workspace_id,
                    "run": scope.run_id,
                    "account": scope.account_id,
                },
            )
        )
        .mappings()
        .all()
    )
    contact_section = next(s for s in block["sections"] if s["key"] == "contact-insights")
    items, pending = [], False
    for row in rows:
        child_scope = replace(
            scope,
            job_id=row["job_id"],
            subject_kind="person",
            contact_id=row["contact_id"],
            input_refs=row["input_refs"],
        )
        child = await read_page(conn, child_scope, context_id=context_id, page="contact")
        section = next(
            s for s in child["display_block"]["sections"] if s["key"] == "why-this-person"
        )
        pending |= section.get("pending", False)
        subject = {
            "accountId": str(scope.account_id),
            "contactId": str(row["contact_id"]),
            "name": row["full_name"],
        }
        if section.get("intro"):
            items.append(
                {
                    "id": f"{row['contact_id']}-intro",
                    "h2": row["full_name"],
                    "body": section["intro"],
                    "priority": 2,
                    "subject": subject,
                    "contactRefs": [subject],
                    "sendLine": None,
                }
            )
        for item in section["items"]:
            items.append({**item, "id": f"{row['contact_id']}-{item['id']}", "subject": subject})
    contact_section.update(items=items, intro=[], empty=not items, pending=pending)
    for item in items:
        for sentence in [*item["body"], *([item["sendLine"]] if item.get("sendLine") else [])]:
            cited.extend(sentence.get("claimIds", []))
    ready.add("contact-insights")
    if pending:
        stale.add("contact-insights")
        contact_section["emptyMessage"] = "Person research narrative is in progress."
    elif not items:
        contact_section["emptyMessage"] = "No person research narrative is available yet."
    return ready, stale, cited
