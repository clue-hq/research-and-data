"""Where the time goes in scene (ad) design turns — read-only.

For every design run on scene documents in a workspace (or one document), prints one row:
how long the person waited, how long the run itself took, when its first scene change landed,
how much ran after that, how many model calls it made, how big the opening context was, and what
it cost. Every number comes from rows the system already writes: ``agent_turn`` (when the message
was sent), ``design_agent_run`` (the run and its per-call ``model_calls`` receipts) and
``run_event`` (``scene_checkpoint_committed``: the moment a change was committed to the document).

Run from the repo root:

    set -a; source .env; set +a
    .venv/bin/python scripts/design_followup_timings.py --workspace ws_... \
        [--since 2026-10-16T00:00Z]
    .venv/bin/python scripts/design_followup_timings.py --document doc_...

"first" is a document's first run; "follow-up" is any later run on the same document.
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime

import psycopg

QUERY = """
with runs as (
  select r.run_id, r.document_id, r.status, r.created_at, r.updated_at, r.result_json,
         (r.payload->'config'->'leg'->>'agent_turn_id')::uuid as turn_id,
         row_number() over (partition by r.document_id order by r.created_at) as n
  from design_agent_run r
  join design_document d on d.id = r.document_id and d.workspace_id = r.workspace_id
  where d.doc_kind = 'scene'
    and (%(workspace)s::text is null or r.workspace_id = %(workspace)s)
    and (%(document)s::text is null or r.document_id = %(document)s)
)
select runs.run_id, runs.document_id, runs.n, runs.status, runs.created_at, runs.updated_at,
       t.requested_at,
       (select min(e.created_at) from run_event e
         where e.subject_kind = 'design_run' and e.subject_id = runs.run_id
           and e.payload->>'event_type' = 'scene_checkpoint_committed') as first_change_at,
       runs.result_json->'model_calls' as calls,
       coalesce(runs.result_json->>'summary', '') as summary
from runs
left join agent_turn t on t.id = runs.turn_id
where (%(since)s::timestamptz is null or runs.created_at >= %(since)s)
order by runs.created_at
"""


def seconds(start: datetime | None, end: datetime | None) -> str:
    return f"{(end - start).total_seconds():.0f}" if start and end else "-"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--workspace")
    parser.add_argument("--document")
    parser.add_argument("--since", help="only runs created at or after this ISO time")
    args = parser.parse_args()
    if not (args.workspace or args.document):
        parser.error("pass --workspace or --document")

    url = os.environ["CLUE_DATABASE_URL"].replace("postgresql+asyncpg://", "postgresql://")
    with psycopg.connect(url) as conn:
        rows = conn.execute(
            QUERY, {"workspace": args.workspace, "document": args.document, "since": args.since}
        ).fetchall()

    header = (
        f"{'run':<14} {'doc':<10} {'which':<9} {'status':<9} {'wait_s':>6} {'run_s':>5} "
        f"{'change_s':>8} {'after_s':>7} {'calls':>5} {'open_ctx':>8} {'open_cached':>11} "
        f"{'total_in':>9} {'cost_$':>6}  summary"
    )
    print(header)
    print("-" * len(header))
    for run_id, doc, n, status, created, updated, requested, changed, calls, summary in rows:
        calls = calls or []
        first = calls[0] if calls else {}
        total_in = sum(int(c.get("input_tokens") or 0) for c in calls)
        cost = sum(float(c.get("cost_cents") or 0) for c in calls) / 100
        print(
            f"{run_id[4:16]:<14} {doc[4:12]:<10} {'first' if n == 1 else 'follow-up':<9} "
            f"{status:<9} {seconds(requested, updated):>6} {seconds(created, updated):>5} "
            f"{seconds(created, changed):>8} {seconds(changed, updated):>7} {len(calls):>5} "
            f"{int(first.get('input_tokens') or 0):>8} "
            f"{int(first.get('cache_read_input_tokens') or 0):>11} "
            f"{total_in:>9} {cost:>6.2f}  {summary[:70]}"
        )


if __name__ == "__main__":
    main()
