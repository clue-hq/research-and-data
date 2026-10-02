"""Research findings no narrative section cites, served as plain Miscellaneous items.

Founder ruling 2026-09-29: the pages show only their designed sections. There is no separate "All
research findings" section and no per-sentence verification tags. A ``*.research_finding`` the
narrative did not cite lands in the page's Miscellaneous section; typed fields (``core.*``, fit
scores, committee selection) are never rendered as text items.
"""

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.account_research_claims import JobScope
from clue_api.arv2.quality_page_inputs import PageInputs

_UNCOVERED_FINDINGS = text(
    """
    SELECT c.id, c.value_json
    FROM claim c LEFT JOIN claim_quality_current q ON q.claim_id=c.id
    LEFT JOIN artifact a ON a.storage_key=c.artifact_key AND a.workspace_id=c.workspace_id
    WHERE c.workspace_id=:ws AND c.entity_id=:subject
      AND c.field_key LIKE '%.research_finding'
      AND c.superseded_by IS NULL
      AND COALESCE(q.conclusion, '') <> 'invalid'
      AND NOT (c.id::text = ANY(:cited))
      AND (c.write_markers->>'context_id' IS NULL OR c.write_markers->>'context_id'=:context)
      AND (c.artifact_key IS NULL OR (a.erased_at IS NULL AND NOT a.privacy_erased
           AND (a.expires_at IS NULL OR a.expires_at>now())))
      AND NOT EXISTS(SELECT 1 FROM claim_quality_support s JOIN artifact sa
        ON sa.storage_key=s.artifact_key WHERE s.assessment_id=q.assessment_id
        AND (sa.erased_at IS NOT NULL OR sa.privacy_erased OR sa.expires_at<=now()))
    ORDER BY c.collected_at, c.id
    """
)


def _plain_text(finding: object) -> str:
    """A finding as reader text: the string itself, or an object's text values as sentences."""
    if isinstance(finding, str):
        return finding.strip()
    if isinstance(finding, dict):
        parts = [
            v.strip().rstrip(".") for v in finding.values() if isinstance(v, str) and v.strip()
        ]
        return ". ".join(parts) + "." if parts else ""
    return ""


async def uncovered_findings(
    conn: AsyncConnection,
    scope: JobScope,
    inputs: PageInputs,
    *,
    subject_id: UUID,
    cited: set[str],
) -> list[dict[str, Any]]:
    """The subject's research findings no section cites, as plain served items."""
    rows = (
        (
            await conn.execute(
                _UNCOVERED_FINDINGS,
                {
                    "ws": scope.workspace_id,
                    "subject": subject_id,
                    "cited": sorted(cited),
                    "context": str(inputs.generation.context_id),
                },
            )
        )
        .mappings()
        .all()
    )
    items: list[dict[str, Any]] = []
    for row in rows:
        value = row["value_json"]
        finding = _plain_text(value.get("finding") if isinstance(value, dict) else None)
        if not finding:
            continue
        items.append(
            {
                "id": f"miscellaneous-finding-{row['id']}",
                "h2": str(value.get("topic") or "Research finding"),
                "body": [{"text": finding, "claimIds": [str(row["id"])]}],
                "priority": 3,
                "newSinceLastVisit": False,
                "contactRefs": [],
            }
        )
    return items
