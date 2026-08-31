#!/usr/bin/env python3
"""Retained C6 Firecrawl fast/background lifecycle canary.

Run only against a dedicated migrated database and artifact root. The script seeds a fresh
self-serve workspace/recon, executes the production C6 work handler for ``insighthealth.ai``, then
replays it and proves the durable attempt count is unchanged. Output contains IDs, hashes, states,
and aggregate counters only—never credentials, raw receipts, page bytes, or user identifiers.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
from time import monotonic
from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.official_site_crawl_wiring import build_official_site_crawl_fleet
from clue_auth import provision_self_serve_workspace
from clue_config import Secrets, Settings
from clue_db import db_lifespan
from clue_fleet import LeaseGeneration, WorkContext, WorkId
from clue_storage import FsStorage

_TARGET_URL = "https://insighthealth.ai/"


async def _seed_recon(conn: AsyncConnection) -> tuple[str, UUID]:
    marker = uuid4()
    provisioned = await provision_self_serve_workspace(
        conn,
        provider_key="c6-live-fixture",
        provider_subject=f"c6-live-{marker}",
        first_name="C6",
        last_name="Canary",
        job_role="Verification",
        company_name="Insight Health",
        company_website=_TARGET_URL,
    )
    workspace_id = provisioned.workspace.workspace_id
    recon_run_id = uuid4()
    await conn.execute(
        text(
            """
            INSERT INTO recon_run (
                id, workspace_id, brand_id, dedupe_hash, dedupe_expires_at,
                fast_run_id, background_run_id, fast_status, background_status,
                fast_budget_cents, background_budget_cents, fast_client_kb_version,
                recipe_version, skill_version
            ) VALUES (
                :id, :workspace_id, :brand_id, :dedupe_hash, now() + interval '1 day',
                :fast_run_id, :background_run_id, 'completed', 'queued',
                100, 100, 1, 'c6-live-v1', 'c6-live-v1'
            )
            """
        ),
        {
            "id": recon_run_id,
            "workspace_id": workspace_id,
            "brand_id": provisioned.brand.brand_id,
            "dedupe_hash": hashlib.sha256(str(recon_run_id).encode()).hexdigest(),
            "fast_run_id": uuid4(),
            "background_run_id": uuid4(),
        },
    )
    return workspace_id, recon_run_id


async def _run() -> dict[str, object]:
    artifact_root_value = os.environ.get("CLUE_C6_ARTIFACT_ROOT")
    replay_workspace_id = os.environ.get("CLUE_C6_REPLAY_WORKSPACE_ID")
    replay_recon_run_id = os.environ.get("CLUE_C6_REPLAY_RECON_RUN_ID")
    if os.environ.get("CLUE_C6_LIVE_CONFIRM") != "1":
        raise RuntimeError("set CLUE_C6_LIVE_CONFIRM=1 to authorize this bounded live canary")
    if not artifact_root_value:
        raise RuntimeError("CLUE_C6_ARTIFACT_ROOT is required")
    secrets = Secrets()
    if secrets.firecrawl_api_key is None:
        raise RuntimeError("CLUE_FIRECRAWL_API_KEY is required")
    artifact_root = Path(artifact_root_value).resolve()
    artifact_root.mkdir(parents=True, exist_ok=True)
    if bool(replay_workspace_id) != bool(replay_recon_run_id):
        raise RuntimeError("both C6 replay workspace and recon run IDs must be supplied together")

    async with db_lifespan() as engine:
        database_name = str(engine.url.database)  # engine URL only; no credential is emitted
        if "c6" not in database_name.casefold():
            raise RuntimeError("C6 live canary refuses a database whose name does not contain c6")
        if replay_workspace_id and replay_recon_run_id:
            workspace_id = replay_workspace_id
            recon_run_id = UUID(replay_recon_run_id)
        else:
            async with engine.begin() as conn:
                workspace_id, recon_run_id = await _seed_recon(conn)
        settings = Settings(
            stage0_official_site_crawl_mode="shadow",
            stage0_official_site_crawl_workspace_allowlist=(workspace_id,),
            stage0_page_fetcher="firecrawl",
            stage0_crawl_fast_deadline_seconds=40,
            stage0_crawl_fast_page_ceiling=8,
            stage0_crawl_total_page_ceiling=16,
            stage0_crawl_worker_concurrency=4,
            stage0_crawl_per_host_concurrency=2,
            stage0_crawl_request_timeout_seconds=30,
            stage0_crawl_max_response_bytes=5_000_000,
            stage0_crawl_allow_subdomains=True,
            storage_backend="fs",
            storage_fs_root=str(artifact_root),
        )
        composition = build_official_site_crawl_fleet(
            settings=settings,
            secrets=secrets,
            storage=FsStorage(artifact_root),
        )
        if composition.handler is None:
            raise RuntimeError("shadow C6 composition produced no work handler")
        work_id = WorkId(uuid5(NAMESPACE_URL, f"official-site-crawl:{recon_run_id}"))
        context = WorkContext(
            task_id=uuid4(),
            work_id=work_id,
            worker_id="c6-live-worker",
            lease_generation=LeaseGeneration(1),
            payload={"workspace_id": workspace_id, "recon_run_id": str(recon_run_id)},
            stop_requested=asyncio.Event(),
            lease_lost=asyncio.Event(),
        )
        started = monotonic()
        first = await composition.handler.handle(context)
        duration_seconds = round(monotonic() - started, 3)
        async with engine.connect() as conn:
            before = await _evidence(conn, workspace_id, recon_run_id)
        replay_started = monotonic()
        replay = await composition.handler.handle(context)
        replay_duration_seconds = round(monotonic() - replay_started, 3)
        async with engine.connect() as conn:
            after = await _evidence(conn, workspace_id, recon_run_id)

    if before["attempt_count"] != after["attempt_count"]:
        raise RuntimeError("cold replay unexpectedly created a provider attempt")
    if before["crawl_run_id"] != after["crawl_run_id"]:
        raise RuntimeError("cold replay created a second crawl run")
    return {
        "artifact_root": str(artifact_root),
        "background_checkpoint_id": first.references.get("background_checkpoint_id"),
        "crawl_run_id": first.references.get("crawl_run_id"),
        "database": database_name,
        "duration_seconds": duration_seconds,
        "evidence": after,
        "fast_checkpoint_id": first.references.get("fast_checkpoint_id"),
        "first_outcome": first.outcome,
        "recon_run_id": str(recon_run_id),
        "replay_attempt_delta": cast(int, after["attempt_count"])
        - cast(int, before["attempt_count"]),
        "replay_duration_seconds": replay_duration_seconds,
        "replay_outcome": replay.outcome,
        "target_domain": "insighthealth.ai",
        "workspace_id": workspace_id,
    }


async def _evidence(
    conn: AsyncConnection, workspace_id: str, recon_run_id: UUID
) -> dict[str, object]:
    run = (
        (
            await conn.execute(
                text(
                    """
                    SELECT crawl.id, crawl.status, crawl.fast_claim_deadline_at,
                           count(*) OVER () AS runs_for_recon
                    FROM official_site_crawl_run AS crawl
                    WHERE crawl.workspace_id = :workspace_id
                      AND crawl.recon_run_id = :recon_run_id
                    """
                ),
                {"workspace_id": workspace_id, "recon_run_id": recon_run_id},
            )
        )
        .mappings()
        .one()
    )
    crawl_run_id = run["id"]
    counts = (
        (
            await conn.execute(
                text(
                    """
                    SELECT
                      (SELECT count(*) FROM official_site_crawl_page
                       WHERE crawl_run_id = :crawl_run_id) AS page_count,
                      (SELECT count(*) FROM official_site_crawl_page
                       WHERE crawl_run_id = :crawl_run_id AND state = 'fetched') AS fetched_count,
                      (SELECT count(*) FROM official_site_fetch_attempt
                       WHERE crawl_run_id = :crawl_run_id) AS attempt_count,
                      (SELECT count(DISTINCT content_sha256) FROM official_site_page_snapshot
                       WHERE crawl_run_id = :crawl_run_id) AS unique_blob_count,
                      (SELECT count(*) FROM official_site_corpus_checkpoint
                       WHERE crawl_run_id = :crawl_run_id) AS checkpoint_count,
                      (SELECT count(*) FROM official_site_fetch_attempt
                       WHERE crawl_run_id = :crawl_run_id
                         AND spend_status = 'spend_unknown') AS spend_unknown_count
                    """
                ),
                {"crawl_run_id": crawl_run_id},
            )
        )
        .mappings()
        .one()
    )
    checkpoints = (
        (
            await conn.execute(
                text(
                    """
                    SELECT phase, version, jsonb_array_length(snapshot_ids_json) AS snapshots,
                           snapshot_set_sha256
                    FROM official_site_corpus_checkpoint
                    WHERE crawl_run_id = :crawl_run_id ORDER BY phase
                    """
                ),
                {"crawl_run_id": crawl_run_id},
            )
        )
        .mappings()
        .all()
    )
    return {
        "attempt_count": counts["attempt_count"],
        "checkpoint_count": counts["checkpoint_count"],
        "checkpoints": [dict(item) for item in checkpoints],
        "crawl_run_id": str(crawl_run_id),
        "fetched_count": counts["fetched_count"],
        "page_count": counts["page_count"],
        "runs_for_recon": run["runs_for_recon"],
        "spend_unknown_count": counts["spend_unknown_count"],
        "status": run["status"],
        "unique_blob_count": counts["unique_blob_count"],
    }


def main() -> None:
    print(json.dumps(asyncio.run(_run()), indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
