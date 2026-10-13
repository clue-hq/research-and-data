#!/usr/bin/env python3
"""Print one research run's media line: found, attempted, transcribed by method, and why not.

    set -a; source .env; set +a
    uv run python scripts/arv2_media_report.py <workspace_id> <run_id>

Read-only. Spec: docs/superpowers/specs/2026-10-13-legitimate-media-sources-design.md §4.
"""

from __future__ import annotations

import asyncio
import json
import sys
from uuid import UUID

from clue_api.arv2.media_store import run_media_summary
from clue_db import db_lifespan, transaction


async def main(workspace_id: str, run_id: UUID) -> None:
    async with db_lifespan(), transaction() as conn:
        summary = await run_media_summary(conn, workspace_id=workspace_id, run_id=run_id)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    asyncio.run(main(sys.argv[1], UUID(sys.argv[2])))
