"""Complete research findings alongside the agent's narrative; uncertainty never hides text."""

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.account_research_claims import JobScope
from clue_api.arv2.quality_page_inputs import PageInputs


def annotate_sentences(body: dict[str, Any], claims: dict[Any, dict[str, Any]]) -> None:
    """Retain narrative text while showing changes/uncertainty in its cited findings."""
    by_id = {str(id): claim for id, claim in claims.items()}
    sentences = [*body.get("intro", [])]
    for item in body.get("items", []):
        sentences.extend(item.get("body", []))
        if item.get("sendLine"):
            sentences.append(item["sendLine"])
    for sentence in sentences:
        notes = list(sentence.get("qualifications", []))
        for id in sentence.get("claimIds", []):
            claim = by_id.get(str(id))
            if claim is None:
                notes.append("The cited finding is unavailable; this statement needs review.")
                continue
            notes.extend((claim.get("write_markers") or {}).get("qualifications", []))
            if claim.get("quality") in ("qualified", "unresolved", "invalid"):
                notes.append("Supporting finding: " + claim["quality"] + ".")
            if claim.get("superseded_by"):
                notes.append("An updated supporting finding is available.")
        if notes:
            sentence["kind"] = "qualified"
            sentence["qualifications"] = list(dict.fromkeys(notes))


async def finding_section(
    conn: AsyncConnection, scope: JobScope, inputs: PageInputs
) -> tuple[dict[str, Any], tuple[str, ...]]:
    rows = (
        (
            await conn.execute(
                text("""
        SELECT c.id,c.field_key,c.value_json,c.write_markers,c.superseded_by,
               q.conclusion,c.source_url,c.evidence_span
        FROM claim c LEFT JOIN claim_quality_current q ON q.claim_id=c.id
        LEFT JOIN artifact a ON a.storage_key=c.artifact_key AND a.workspace_id=c.workspace_id
        WHERE c.workspace_id=:ws AND c.entity_id=ANY(:subjects)
          AND (c.write_markers->>'context_id' IS NULL
               OR c.write_markers->>'context_id'=:context)
          AND (c.artifact_key IS NULL OR (a.erased_at IS NULL AND NOT a.privacy_erased
               AND (a.expires_at IS NULL OR a.expires_at>now())))
          AND NOT EXISTS(SELECT 1 FROM claim_quality_support s JOIN artifact sa
            ON sa.storage_key=s.artifact_key WHERE s.assessment_id=q.assessment_id
            AND (sa.erased_at IS NOT NULL OR sa.privacy_erased OR sa.expires_at<=now()))
        ORDER BY c.collected_at,c.id
    """),
                {
                    "ws": scope.workspace_id,
                    "subjects": list(inputs.subjects),
                    "context": str(inputs.generation.context_id),
                },
            )
        )
        .mappings()
        .all()
    )
    items = []
    for row in rows:
        value = row["value_json"]
        is_finding = row["field_key"].endswith(".research_finding") and isinstance(value, dict)
        title = str(value.get("topic", "Research finding")) if is_finding else row["field_key"]
        content = value.get("finding") if is_finding else value
        body = (
            content
            if isinstance(content, str)
            else json.dumps(content, ensure_ascii=False, indent=2)
        )
        notes = list((row["write_markers"] or {}).get("qualifications", []))
        if is_finding:
            notes.extend(value.get("notes") or [])
        if row["conclusion"] in ("qualified", "unresolved", "invalid"):
            notes.append(
                {
                    "qualified": "Qualification recorded",
                    "unresolved": "Unresolved finding",
                    "invalid": "Disputed or withdrawn finding; retained for review",
                }[row["conclusion"]]
            )
        if row["superseded_by"]:
            notes.append("An updated finding is also available; this is the earlier observation.")
        if notes:
            body += "\n\nNotes: " + " ".join(dict.fromkeys(str(n) for n in notes))
        items.append(
            {
                "id": str(row["id"]),
                "h2": title,
                "body": [
                    {
                        "text": body,
                        "claimIds": [str(row["id"])],
                        "kind": "qualified" if notes else "fact",
                        "qualifications": notes,
                    }
                ],
                "priority": 2,
                "newSinceLastVisit": False,
                "contactRefs": [],
            }
        )
    return (
        {
            "key": "research-findings",
            "h1": "All research findings",
            "intro": [],
            "items": items,
            "empty": not items,
            "restricted": False,
            "pending": False,
            "gaps": [],
        },
        tuple(str(row["id"]) for row in rows),
    )
