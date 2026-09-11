"""Backfill one discovery run's accounts with the two rulings of 2026-09-11.

For every candidate of the run that has an account row: stamp the run's requester as the
account's creator and owner (creator is the owner by default), and write a ``core.logo_url``
claim by the same rule the driver now applies — Websets' LinkedIn company mark from the
candidate's stored snapshot, else Brandfetch's icon, else nothing. Accounts that already carry a
logo claim are left alone, so the script is safe to re-run.

Usage (from the repo root, the lane's .env sourced for the DSN and keys):

    set -a; source .env; set +a
    uv run python scripts/backfill_discovery_run_logos_and_owners.py --run-id <uuid> [--dry-run]

Every Brandfetch hop goes through the lane's provider caller, so it is ledgered and raw-sunk like
a discovery run's own calls, under the run's project run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from datetime import UTC, datetime

from pydantic import SecretStr
from sqlalchemy import text

from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.arv2.calls import ProviderCaller
from clue_api.arv2.claim_writer import ClaimDraft, LenientClaimWriter
from clue_api.arv2.logo_resolution import BrandfetchClient, websets_mark_url
from clue_api.arv2.provider_ledger import (
    BufferedLedger,
    BufferedRawSink,
    LedgerStamp,
    drain_provider_calls,
)
from clue_api.arv2.transport import HttpxTransport
from clue_api.storage_wiring import build_storage_backend
from clue_config import Secrets, load_settings
from clue_core import EntityId, EntityType, ExtractionMethod, ResearchMode, RunId
from clue_db import db_lifespan, transaction

_CANDIDATES = text(
    """
    SELECT c.candidate_id, c.domain, c.account_entity_id, c.provider_snapshot_json,
           r.workspace_id, r.project_id, r.project_run_id, r.requested_by_user_id, r.run_id
    FROM arv2_discovery_candidate c JOIN arv2_discovery_run r ON r.run_id = c.run_id
    WHERE c.run_id = :run_id AND c.account_entity_id IS NOT NULL
    ORDER BY c.domain
    """
)
_HAS_LOGO = text(
    "SELECT 1 FROM claim WHERE entity_id = :entity_id AND field_key = 'core.logo_url' "
    "AND superseded_by IS NULL LIMIT 1"
)
_STAMP_OWNER = text(
    "UPDATE account_entity SET owner_user_id = COALESCE(owner_user_id, :user_id), "
    "created_by_user_id = COALESCE(created_by_user_id, :user_id) WHERE id = :id"
)


_IS_USER = text("SELECT 1 FROM platform_user WHERE user_id = :user_id")


async def _main(run_id: uuid.UUID, *, dry_run: bool, owner_user_id: str | None) -> None:
    settings = load_settings()
    secrets = Secrets()
    key = secrets.brandfetch_api_key
    async with db_lifespan():
        async with transaction() as conn:
            rows = (await conn.execute(_CANDIDATES, {"run_id": run_id})).mappings().all()
            if not rows:
                print("no candidates with accounts for that run")
                return
            # The owner: the human named on the command line, else the run's requester — but
            # only when that id is a platform user. A deepagent-launched run records the fleet's
            # service principal as its requester, which owns nothing; name the human explicitly.
            owner = owner_user_id or rows[0]["requested_by_user_id"]
            if (await conn.execute(_IS_USER, {"user_id": owner})).first() is None:
                raise SystemExit(
                    f"{owner!r} is not a platform user; pass --owner-user-id <the human who "
                    "launched this run> (the turn's submitted_by_user_id)"
                )
        raw_sink, ledger = BufferedRawSink(), BufferedLedger()
        caller = ProviderCaller(
            transport=HttpxTransport(),
            raw_sink=raw_sink,
            ledger=ledger,
            now=lambda: datetime.now(UTC),
        )
        artifacts = DurableAgentArtifactStore(
            storage=build_storage_backend(settings), conn_factory=transaction
        )
        brandfetch = (
            None
            if key is None or not key.get_secret_value().strip()
            else BrandfetchClient(
                caller,
                api_key=SecretStr(key.get_secret_value()),
                base_url=settings.brandfetch_api_base_url,
                timeout_s=settings.brandfetch_timeout_s,
            )
        )
        writer = LenientClaimWriter(lenient=settings.claim_write_lenient)
        stamped = logos = skipped = 0
        for row in rows:
            entity_id = EntityId(uuid.UUID(str(row["account_entity_id"])))
            snapshot = row["provider_snapshot_json"]
            if isinstance(snapshot, str):
                snapshot = json.loads(snapshot)
            websets_logo = (
                ((snapshot or {}).get("item") or {}).get("properties", {}).get("company", {})
            ).get("logoUrl")
            async with transaction() as conn:
                if not dry_run:
                    await conn.execute(_STAMP_OWNER, {"user_id": owner, "id": entity_id})
                stamped += 1
                if (await conn.execute(_HAS_LOGO, {"entity_id": entity_id})).first():
                    skipped += 1
                    continue
                mark, source = websets_mark_url(websets_logo), "exa_websets"
                if mark is None and brandfetch is not None:
                    icon = await asyncio.to_thread(
                        brandfetch.icon_url, row["domain"], label=f"logo:{row['domain']}"
                    )
                    mark, source = icon, "brandfetch"
                print(f"{row['domain']:34} {'-' if mark is None else source:12} {mark or ''}")
                if mark is None or dry_run:
                    continue
                await writer.write(
                    conn,
                    ClaimDraft(
                        entity_id=entity_id,
                        entity_type=EntityType.ACCOUNT,
                        field_key="core.logo_url",
                        value_json=mark,
                        extraction_method=ExtractionMethod.API,
                        run_id=RunId(uuid.UUID(str(row["run_id"]))),
                        research_mode=ResearchMode.ACCOUNT_DISCOVERY,
                        workspace_id=row["workspace_id"],
                        source_url=mark,
                        source_key=source,
                        evidence_span=None,
                        confidence=0.5,
                        markers={
                            "discovery_run_id": str(row["run_id"]),
                            "logo_kind": "mark",
                            "backfill": "2026-09-11",
                        },
                    ),
                )
                logos += 1
        # The Brandfetch hops are ledgered under the run's own project run, like the run's calls.
        first = rows[0]
        if not dry_run:
            async with transaction() as conn:
                report = await drain_provider_calls(
                    conn,
                    raw=raw_sink,
                    ledger=ledger,
                    artifacts=artifacts,
                    stamp=LedgerStamp(
                        workspace_id=first["workspace_id"],
                        project_id=first["project_id"],
                        project_run_id=str(first["project_run_id"]),
                        job_id=uuid.UUID(str(first["run_id"])),
                    ),
                )
            print(f"ledgered {report}")
        print(
            f"owner/creator stamped: {stamped}; logos written: {logos}; already had one: {skipped}"
            + (" (dry run: nothing written)" if dry_run else "")
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True, type=uuid.UUID)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--owner-user-id",
        help=(
            "The human who launched the run (defaults to the run's requester when that is a user)."
        ),
    )
    args = parser.parse_args()
    asyncio.run(_main(args.run_id, dry_run=args.dry_run, owner_user_id=args.owner_user_id))
