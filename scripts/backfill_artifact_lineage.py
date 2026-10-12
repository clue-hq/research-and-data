#!/usr/bin/env python3
"""Convert research steps saved before 2026-10-12 to lineage watermarks, in batches.

    set -a; source .env; set +a
    uv run python scripts/backfill_artifact_lineage.py            # count only, writes nothing
    uv run python scripts/backfill_artifact_lineage.py --apply    # convert, one commit per batch

Before migration ``ecc5f641c0d9`` every saved research step (model request and reply, tool
result, plan, dossier: everything ``ResearchArtifacts.persist_body`` writes) had one
``artifact_derivation`` row per evidence source of its run and account, plus its context items:
~460,000 rows per account run. New saves write one ``artifact_evidence_watermark`` row and one
``artifact_context_lineage`` row instead. This converts the old ones.

For each step (marked by ``persist_body``'s project binding or retention reference) it derives the
watermark from the step's own links (the highest linked revision per run and account; the person
when exactly one person besides the account is linked, else the account), records the contexts
it linked, and deletes **only** links those rows cover: erasing the parent still erases the step
through the ``erase_derived_artifacts`` trigger. A link the rows do not cover stays. Old links keep
working until converted, so this runs on a live database, in any order, any number of times.

**Dry run by default.** Without ``--apply`` it counts what is left to convert and writes nothing.
Specification: docs/superpowers/specs/2026-10-12-research-storage-linear-growth-design.md §4.1.
"""

from __future__ import annotations

import argparse
import asyncio
import time
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_db import db_lifespan, transaction

#: Artifacts ``persist_body`` wrote. Only these become watermark rows; claims, pages and other
#: precise writers keep their links (they cite exactly what they used).
_STEPS = """
    SELECT workspace_id, artifact_key AS child_key FROM agent_artifact_project
      WHERE binding_kind='research_execution'
    UNION SELECT workspace_id, storage_key FROM artifact_reference
      WHERE reference_kind='research_execution_output'
"""


def _contexts_of(workspace: str, key: str) -> str:
    """The contexts an artifact is a context item of (document, pin or claim support), looked up
    by that one artifact through indexes, never by joining every context item."""
    return f"""
      SELECT context_id FROM arv2_context_document
        WHERE workspace_id={workspace} AND artifact_key={key}
      UNION SELECT context_id FROM arv2_research_context_pin
        WHERE workspace_id={workspace} AND manifest_key={key}
      UNION SELECT q.context_id FROM claim_quality_support sup
        JOIN claim_quality_current q ON q.assessment_id=sup.assessment_id
        WHERE sup.workspace_id={workspace} AND sup.artifact_key={key}
          AND q.context_id IS NOT NULL"""


#: The next children (any artifact with links) after the cursor, in key order.
NEXT_CHILDREN = """
    SELECT DISTINCT child_key FROM artifact_derivation
    WHERE child_key > :after ORDER BY child_key LIMIT :size
"""

#: One watermark per step and (run, account) in the batch, from the step's own links.
BACKFILL_WATERMARKS = f"""
    INSERT INTO artifact_evidence_watermark
      (workspace_id, child_key, run_id, account_id, subject_key, evidence_revision)
    SELECT d.workspace_id, d.child_key, s.run_id, s.account_id,
      CASE WHEN count(DISTINCT s.subject_id) FILTER (WHERE s.subject_id<>s.account_id) = 1
           THEN (array_agg(DISTINCT s.subject_id)
                 FILTER (WHERE s.subject_id<>s.account_id))[1]
           ELSE s.account_id END,
      max(s.revision)
    FROM artifact_derivation d
    JOIN ({_STEPS}) step ON step.workspace_id=d.workspace_id AND step.child_key=d.child_key
    JOIN arv2_evidence_source s ON s.workspace_id=d.workspace_id AND s.artifact_key=d.parent_key
    WHERE d.child_key = ANY(:keys)
    GROUP BY d.workspace_id, d.child_key, s.run_id, s.account_id
    ON CONFLICT ON CONSTRAINT artifact_evidence_watermark_pk DO UPDATE
    SET evidence_revision=GREATEST(artifact_evidence_watermark.evidence_revision,
                                   EXCLUDED.evidence_revision)
"""

BACKFILL_CONTEXTS = f"""
    INSERT INTO artifact_context_lineage (workspace_id, child_key, context_id)
    SELECT DISTINCT d.workspace_id, d.child_key, i.context_id
    FROM artifact_derivation d
    JOIN ({_STEPS}) step ON step.workspace_id=d.workspace_id AND step.child_key=d.child_key
    JOIN LATERAL ({_contexts_of("d.workspace_id", "d.parent_key")}) i ON true
    WHERE d.child_key = ANY(:keys)
    ON CONFLICT DO NOTHING
"""

#: Delete only links the rows cover: erasing that parent still erases that child.
DELETE_COVERED_EVIDENCE_LINKS = """
    DELETE FROM artifact_derivation d
    USING arv2_evidence_source s, artifact_evidence_watermark w
    WHERE d.child_key = ANY(:keys)
      AND s.workspace_id=d.workspace_id AND s.artifact_key=d.parent_key
      AND w.workspace_id=d.workspace_id AND w.child_key=d.child_key
      AND w.run_id=s.run_id AND w.account_id=s.account_id
      AND w.evidence_revision>=s.revision
      AND (s.subject_id=s.account_id OR w.subject_key IN (w.account_id, s.subject_id))
"""

DELETE_COVERED_CONTEXT_LINKS = f"""
    DELETE FROM artifact_derivation d
    USING artifact_context_lineage l
    WHERE d.child_key = ANY(:keys)
      AND l.workspace_id=d.workspace_id AND l.child_key=d.child_key
      AND l.context_id IN ({_contexts_of("d.workspace_id", "d.parent_key")})
"""

_PLAN = f"""
    SELECT count(DISTINCT d.child_key), count(*)
    FROM artifact_derivation d
    JOIN ({_STEPS}) step ON step.workspace_id=d.workspace_id AND step.child_key=d.child_key
"""


@dataclass(frozen=True)
class BatchResult:
    """What one batch did, for the progress line and the tests."""

    children: int
    watermarks: int
    contexts: int
    links_deleted: int


async def convert(conn: AsyncConnection, keys: list[str]) -> BatchResult:
    """Convert these children's step links (non-steps in ``keys`` are left as they are)."""
    params = {"keys": keys}
    watermarks = (await conn.execute(text(BACKFILL_WATERMARKS), params)).rowcount
    contexts = (await conn.execute(text(BACKFILL_CONTEXTS), params)).rowcount
    deleted = (await conn.execute(text(DELETE_COVERED_EVIDENCE_LINKS), params)).rowcount
    deleted += (await conn.execute(text(DELETE_COVERED_CONTEXT_LINKS), params)).rowcount
    return BatchResult(len(keys), watermarks, contexts, deleted)


async def next_children(conn: AsyncConnection, after: str, size: int) -> list[str]:
    rows = await conn.execute(text(NEXT_CHILDREN), {"after": after, "size": size})
    return [str(key) for key in rows.scalars()]


async def run(*, apply: bool, batch_size: int) -> None:
    async with transaction() as conn:
        steps, links = (await conn.execute(text(_PLAN))).one()
    print(f"steps with links: {steps}; their links: {links}")
    if not apply:
        print("dry run: nothing written (pass --apply to convert)")
        return
    after, total_deleted, batches, started = "", 0, 0, time.monotonic()
    while True:
        async with transaction() as conn:
            keys = await next_children(conn, after, batch_size)
            if not keys:
                break
            result = await convert(conn, keys)
        after, batches = keys[-1], batches + 1
        total_deleted += result.links_deleted
        if batches % 10 == 0:
            print(
                f"batch {batches}: {total_deleted} links deleted, {time.monotonic() - started:.0f}s"
            )
    print(f"done: {batches} batches, {total_deleted} links deleted")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--apply", action="store_true", help="convert (default: count only)")
    parser.add_argument("--batch-size", type=int, default=500, help="children per commit")
    args = parser.parse_args()

    async def go() -> None:
        async with db_lifespan():
            await run(apply=args.apply, batch_size=args.batch_size)

    asyncio.run(go())


if __name__ == "__main__":
    main()
