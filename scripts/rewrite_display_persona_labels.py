#!/usr/bin/env python3
"""One-shot: rewrite the personas stored inside generated display blocks as display text (D4-b).

Until the D4-b ruling, ``clue_api.arv2.display.runner`` wrote a contact chip's persona into
``display_block.body_json`` as the pipeline's vocabulary value — ``"economic_buyer"``. The read
surface serves that body verbatim, so every block written before the ruling puts an enum value in
front of a marketer for as long as it lives. The generator is fixed; this repairs what is at rest.

Two paths are walked, and only those two: ``body_json.items[].contactRefs[].persona`` and
``body_json.items[].subject.persona``. They are the only places a persona is stored inside a block
— the sentences themselves are model prose and are never touched.

**This is a display-copy correction, not a claim.** A block is its own row: nothing cites it, no
provenance hangs off its wording, and the personas it names are re-derived from the same
``contact.persona`` claims the read surface reads. So the row is UPDATEd in place rather than
superseded — superseding would mint a new "generation" that no model produced and would move
``generated_at`` away from the moment the prose was actually written.

Idempotent: :func:`~clue_api.arv2.display.personas.persona_display` maps its own output to itself,
and a value that is already display text is left byte-identical, so a second pass reports zero
rewritten blocks. Live blocks only (``superseded_at IS NULL``) — a superseded block is history.

    uv run python scripts/rewrite_display_persona_labels.py \
        --database-url postgresql+asyncpg://clue:clue@localhost:55060/clue [--dry-run]

Add ``--workspace-id`` to repair one tenant. Prints one line per block it would change (workspace,
subject, page, section, and how many personas), then a JSON summary.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.arv2.display.personas import persona_display
from clue_db import db_lifespan, transaction

#: Every live block, oldest first so the printed log reads in the order the pages were written.
#: ``:workspace_id`` is NULL for the whole database — one statement, so the scoped and unscoped
#: passes cannot drift into two different ideas of which blocks are live.
_LIVE_BLOCKS = text(
    """
    SELECT display_block_id, workspace_id, subject_kind, subject_id, page, section_key, body_json
    FROM display_block
    WHERE superseded_at IS NULL
      AND (CAST(:workspace_id AS text) IS NULL OR workspace_id = :workspace_id)
    ORDER BY generated_at, display_block_id
    """
)

_UPDATE_BODY = text(
    """
    UPDATE display_block SET body_json = CAST(:body AS jsonb)
    WHERE display_block_id = :display_block_id
    """
)


def rewrite_body(body: Mapping[str, Any]) -> tuple[dict[str, Any], int]:
    """``body`` with every stored persona as display text, and how many strings actually changed.

    Pure and total: a body of any shape comes back unharmed. Anything that is not the exact
    ``items[] -> {contactRefs[], subject}`` structure is copied through untouched rather than
    guessed at — a repair script that reshapes a block it did not understand is worse than one that
    skips it.
    """
    rewritten = dict(body)
    items = body.get("items")
    if not isinstance(items, list):
        return rewritten, 0

    changed = 0
    new_items: list[Any] = []
    for item in items:
        if not isinstance(item, Mapping):
            new_items.append(item)
            continue
        new_item = dict(item)

        refs = item.get("contactRefs")
        if isinstance(refs, list):
            new_refs: list[Any] = []
            for ref in refs:
                new_ref, hits = _rewrite_ref(ref)
                changed += hits
                new_refs.append(new_ref)
            new_item["contactRefs"] = new_refs

        if "subject" in item:
            new_subject, hits = _rewrite_ref(item.get("subject"))
            changed += hits
            new_item["subject"] = new_subject

        new_items.append(new_item)

    rewritten["items"] = new_items
    return rewritten, changed


def _rewrite_ref(ref: Any) -> tuple[Any, int]:
    """One reference with its persona spelled as words; ``(ref, 1)`` when that changed anything."""
    if not isinstance(ref, Mapping):
        return ref, 0
    persona = ref.get("persona")
    if not isinstance(persona, str):
        return ref, 0
    label = persona_display(persona)
    if label is None or label == persona:
        return ref, 0
    updated = dict(ref)
    updated["persona"] = label
    return updated, 1


async def rewrite_display_persona_labels(
    conn: AsyncConnection, *, workspace_id: str | None = None, dry_run: bool = False
) -> dict[str, object]:
    """Walk every live block, rewrite the personas at rest, and report what happened."""
    rows = (await conn.execute(_LIVE_BLOCKS, {"workspace_id": workspace_id})).mappings().all()
    blocks: list[dict[str, object]] = []
    personas_rewritten = 0

    for row in rows:
        body = row["body_json"]
        if not isinstance(body, Mapping):
            continue
        new_body, changed = rewrite_body(body)
        if changed == 0:
            continue
        personas_rewritten += changed
        blocks.append(
            {
                "display_block_id": str(row["display_block_id"]),
                "workspace_id": row["workspace_id"],
                "subject": f"{row['subject_kind']}:{row['subject_id']}",
                "page": row["page"],
                "section_key": row["section_key"],
                "personas_rewritten": changed,
            }
        )
        if not dry_run:
            await conn.execute(
                _UPDATE_BODY,
                {
                    "display_block_id": row["display_block_id"],
                    "body": json.dumps(new_body),
                },
            )

    return {
        "dry_run": dry_run,
        "workspace_id": workspace_id,
        "blocks_scanned": len(rows),
        "blocks_rewritten": len(blocks),
        "personas_rewritten": personas_rewritten,
        "blocks": blocks,
    }


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Rewrite the personas stored in live display_block bodies as display text "
            "(ARV2 D4-b one-shot). Idempotent."
        )
    )
    parser.add_argument(
        "--database-url",
        required=True,
        help=(
            "SQLAlchemy async Postgres URL for the database to repair. Required — this command "
            "writes, so it must never fall through to whatever CLUE_DATABASE_URL happens to point "
            "at (the same rule scripts/backfill_fi2_slice0.py follows)."
        ),
    )
    parser.add_argument(
        "--workspace-id",
        default=None,
        help="Repair only this workspace (default: every workspace).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what a real pass would rewrite, and write nothing.",
    )
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> dict[str, object]:
    # One transaction: the whole repair commits or rolls back together, so a failure halfway
    # through cannot leave half the screens speaking the vocabulary and half speaking English.
    async with db_lifespan(args.database_url), transaction() as conn:
        return await rewrite_display_persona_labels(
            conn, workspace_id=args.workspace_id, dry_run=args.dry_run
        )


def main() -> None:
    report = asyncio.run(_run(_args()))
    blocks = report["blocks"]
    assert isinstance(blocks, Sequence)
    for block in blocks:
        assert isinstance(block, Mapping)
        print(
            f"{block['personas_rewritten']:>3}  {block['page']}/{block['section_key']}"
            f"  {block['subject']}  ({block['workspace_id']})"
        )
    print(json.dumps({key: value for key, value in report.items() if key != "blocks"}, indent=2))


if __name__ == "__main__":
    main()
