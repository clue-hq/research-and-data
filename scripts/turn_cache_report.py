"""Per-turn prompt-cache share of Head-of-ABM turns (read-only).

For each Head-of-ABM turn: its first model call's input tokens, how many of them were served from
the provider's prompt cache, the cached share, and whether the turn could continue its thread
(an earlier finished Head-of-ABM turn on the same thread under the same profile — spec 2026-09-29
§3.1). A continued turn sent within the cache lifetime should show a high share; a fresh one
caches only the system prompt.

Run:
    set -a; source .env; set +a
    .venv/bin/python scripts/turn_cache_report.py --since 2026-09-29
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime

from sqlalchemy import text

from clue_db import db_lifespan, transaction

SQL = text(
    """
    WITH first_call AS (
        SELECT c.turn_id, c.input_tokens, COALESCE(c.cache_read_input_tokens, 0) AS cached,
               c.started_at,
               row_number() OVER (PARTITION BY c.turn_id ORDER BY c.sequence) AS rn
        FROM agent_model_call c
        WHERE c.role = 'head_of_abm' AND c.started_at >= :since
    )
    SELECT f.turn_id, t.thread_id, f.input_tokens, f.cached,
           round(100.0 * f.cached / NULLIF(f.input_tokens, 0)) AS pct,
           EXISTS (
               SELECT 1 FROM agent_turn p
               WHERE p.workspace_id = t.workspace_id AND p.thread_id = t.thread_id
                 AND p.role = 'head_of_abm' AND p.requested_at < t.requested_at
                 AND p.profile_sha256 = t.profile_sha256
                 AND p.resource_manifest_sha256 = t.resource_manifest_sha256
                 AND EXISTS (
                     SELECT 1 FROM agent_turn_event e
                     WHERE e.turn_id = p.id AND e.status IN ('completed', 'awaiting_input')
                 )
           ) AS continuable,
           f.started_at
    FROM first_call f
    JOIN agent_turn t ON t.id = f.turn_id
    WHERE f.rn = 1
    ORDER BY f.started_at
    """
)


async def main(since: datetime) -> None:
    print("turn_id\tthread_id\tinput_tokens\tcached\tpct\tcontinuable\tstarted_at")
    async with db_lifespan(), transaction() as conn:
        for row in (await conn.execute(SQL, {"since": since})).all():
            print(*row, sep="\t")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--since", default="1970-01-01", help="ISO date, e.g. 2026-09-29")
    asyncio.run(main(datetime.fromisoformat(parser.parse_args().since)))
