"""Project the overview's Watch-outs into account Insights' restricted Context only block.

Context only is a restricted recipe, so the page shows it behind "Internal notes" and never as a
body section. (Contact insights was removed 2026-09-29: person narratives live on contact pages.)
"""

from typing import Any
from uuid import UUID

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
    return ready, stale, cited
