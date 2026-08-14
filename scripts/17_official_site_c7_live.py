#!/usr/bin/env python3
"""Retained C7 Firecrawl + OpenRouter grounded-materialization canary.

Run only against a dedicated migrated C7 database and artifact root. The canary creates a fresh
self-serve scope, uses the production authoritative composition to crawl ``insighthealth.ai``,
materializes checkpoint-grounded ``official_site`` claims, then cold-replays the same work. Output
contains aggregate states, IDs, hashes, and model names only—never credentials, page bytes, model
responses, receipts, user identifiers, or claim values.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from decimal import Decimal
from pathlib import Path
from time import monotonic
from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.official_site_crawl_wiring import build_official_site_crawl_fleet
from clue_auth import provision_self_serve_workspace
from clue_config import GatewayConfig, Secrets, Settings
from clue_core import Claim, EntityType, ExtractionMethod, ResearchMode, ReuseScope, RunId
from clue_db import db_lifespan
from clue_fleet import LeaseGeneration, WorkContext, WorkId, WorkResult
from clue_gateway import build_gateway
from clue_research.claimstore import insert_claim, load_core_pack, record_run_lineage
from clue_research.identity import insert_account_entity
from clue_research.sources import seed_source_manifests
from clue_research.stage0.fields import load_client_knowledge_pack
from clue_storage import FsStorage

_TARGET_URL = "https://insighthealth.ai/"
_ALLOWED_MODELS = {"openai/gpt-5.6-luna", "openai/gpt-5.6-terra"}


async def _drive_to_terminal(handler: object, context: WorkContext) -> tuple[WorkResult, int]:
    """Model the fleet's bounded requeue loop without bypassing durable recovery semantics."""

    for attempt in range(1, 25):
        result = await handler.handle(context)  # type: ignore[attr-defined]
        if not result.requeue:
            return result, attempt
        await asyncio.sleep(5)
    raise RuntimeError("C7 live canary remained requeue-pending after 24 bounded attempts")


async def _marker(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    client_entity_id: UUID,
    claim_run_id: UUID,
) -> None:
    await record_run_lineage(
        conn,
        run_id=RunId(claim_run_id),
        workspace_id=workspace_id,
        kind="stage0",
    )
    await insert_claim(
        conn,
        Claim(
            entity_id=client_entity_id,  # type: ignore[arg-type]
            entity_type=EntityType.ACCOUNT,
            field_key="client.kb_version",
            value_json={"version": 1, "run_id": str(claim_run_id)},
            source_tier=1,
            extraction_method=ExtractionMethod.HUMAN,
            confidence=1.0,
            cost_cents=Decimal(0),
            run_id=RunId(claim_run_id),
            research_mode=ResearchMode.ACCOUNT_PROFILING,
            reuse_scope=ReuseScope.TENANT_PRIVATE,
            workspace_id=workspace_id,
        ),
    )


async def _seed_recon(conn: AsyncConnection) -> tuple[str, UUID]:
    marker = uuid4()
    provisioned = await provision_self_serve_workspace(
        conn,
        provider_key="c7-live-fixture",
        provider_subject=f"c7-live-{marker}",
        first_name="C7",
        last_name="Canary",
        job_role="Verification",
        company_name="Insight Health",
        company_website=_TARGET_URL,
    )
    workspace_id = provisioned.workspace.workspace_id
    client_entity_id = UUID(
        str(
            await insert_account_entity(
                conn,
                canonical_name="Insight Health",
                primary_domain="insighthealth.ai",
                workspace_id=workspace_id,
            )
        )
    )
    fast_run_id = uuid4()
    background_run_id = uuid4()
    await load_core_pack(conn)
    await load_client_knowledge_pack(conn)
    await seed_source_manifests(conn)
    await _marker(
        conn,
        workspace_id=workspace_id,
        client_entity_id=client_entity_id,
        claim_run_id=fast_run_id,
    )
    await _marker(
        conn,
        workspace_id=workspace_id,
        client_entity_id=client_entity_id,
        claim_run_id=background_run_id,
    )
    recon_run_id = uuid4()
    await conn.execute(
        text(
            """
            INSERT INTO recon_run (
                id, workspace_id, brand_id, client_entity_id, dedupe_hash,
                dedupe_expires_at, fast_run_id, background_run_id, fast_status,
                background_status, fast_budget_cents, background_budget_cents,
                fast_client_kb_version, recipe_version, skill_version
            ) VALUES (
                :id, :workspace_id, :brand_id, :client_entity_id, :dedupe_hash,
                now() + interval '1 day', :fast_run_id, :background_run_id, 'completed',
                'queued', 100, 100, 1, 'c7-live-v1', 'c7-live-v1'
            )
            """
        ),
        {
            "id": recon_run_id,
            "workspace_id": workspace_id,
            "brand_id": provisioned.brand.brand_id,
            "client_entity_id": client_entity_id,
            "dedupe_hash": hashlib.sha256(str(recon_run_id).encode()).hexdigest(),
            "fast_run_id": fast_run_id,
            "background_run_id": background_run_id,
        },
    )
    return workspace_id, recon_run_id


async def _run() -> dict[str, object]:
    artifact_root_value = os.environ.get("CLUE_C7_ARTIFACT_ROOT")
    replay_workspace_id = os.environ.get("CLUE_C7_REPLAY_WORKSPACE_ID")
    replay_recon_run_id = os.environ.get("CLUE_C7_REPLAY_RECON_RUN_ID")
    model = os.environ.get("CLUE_C7_MODEL", "openai/gpt-5.6-luna")
    if os.environ.get("CLUE_C7_LIVE_CONFIRM") != "1":
        raise RuntimeError("set CLUE_C7_LIVE_CONFIRM=1 to authorize this bounded live canary")
    if not artifact_root_value:
        raise RuntimeError("CLUE_C7_ARTIFACT_ROOT is required")
    if model not in _ALLOWED_MODELS:
        raise RuntimeError("CLUE_C7_MODEL must be the pinned Luna or Terra model")
    if bool(replay_workspace_id) != bool(replay_recon_run_id):
        raise RuntimeError("both C7 replay workspace and recon run IDs must be supplied together")
    secrets = Secrets()
    if secrets.firecrawl_api_key is None or secrets.openrouter_api_key is None:
        raise RuntimeError("both Firecrawl and OpenRouter credentials are required")
    artifact_root = Path(artifact_root_value).resolve()
    artifact_root.mkdir(parents=True, exist_ok=True)

    async with db_lifespan() as engine:
        database_name = str(engine.url.database)
        if "c7" not in database_name.casefold():
            raise RuntimeError("C7 live canary refuses a database whose name does not contain c7")
        if replay_workspace_id and replay_recon_run_id:
            workspace_id = replay_workspace_id
            recon_run_id = UUID(replay_recon_run_id)
        else:
            async with engine.begin() as conn:
                workspace_id, recon_run_id = await _seed_recon(conn)
        settings = Settings(
            stage0_official_site_crawl_mode="authoritative",
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
            stage0_extraction_model=model,
            stage0_extraction_concurrency=4,
            storage_backend="fs",
            storage_fs_root=str(artifact_root),
        )
        composition = build_official_site_crawl_fleet(
            settings=settings,
            secrets=secrets,
            storage=FsStorage(artifact_root),
            gateway=build_gateway(GatewayConfig(), api_key=secrets.openrouter_api_key),
        )
        if composition.handler is None:
            raise RuntimeError("authoritative C7 composition produced no work handler")
        work_id = WorkId(uuid5(NAMESPACE_URL, f"official-site-crawl:{recon_run_id}"))
        context = WorkContext(
            task_id=uuid4(),
            work_id=work_id,
            worker_id="c7-live-worker",
            lease_generation=LeaseGeneration(1),
            payload={"workspace_id": workspace_id, "recon_run_id": str(recon_run_id)},
            stop_requested=asyncio.Event(),
            lease_lost=asyncio.Event(),
        )
        started = monotonic()
        first, drive_attempts = await _drive_to_terminal(composition.handler, context)
        duration_seconds = round(monotonic() - started, 3)
        async with engine.connect() as conn:
            before = await _evidence(conn, workspace_id, recon_run_id)
        replay_started = monotonic()
        replay = await composition.handler.handle(context)
        replay_duration_seconds = round(monotonic() - replay_started, 3)
        async with engine.connect() as conn:
            after = await _evidence(conn, workspace_id, recon_run_id)

    deltas = {
        key: cast(int, after[key]) - cast(int, before[key])
        for key in ("attempt_count", "extraction_operation_count", "official_claim_count")
    }
    if any(deltas.values()):
        raise RuntimeError(f"cold replay created provider/model/claim work: {deltas}")
    if cast(int, after["materialized_operation_count"]) < 1:
        raise RuntimeError("live OpenRouter extraction produced no grounded operation")
    if cast(int, after["official_claim_count"]) < 1:
        raise RuntimeError("live C7 run produced no official-site claims")
    if cast(int, after["invalid_provenance_count"]) != 0:
        raise RuntimeError("live C7 run produced a claim outside its checkpoint")
    return {
        "artifact_root": str(artifact_root),
        "crawl_run_id": first.references.get("crawl_run_id"),
        "database": database_name,
        "duration_seconds": duration_seconds,
        "drive_attempts": drive_attempts,
        "evidence": after,
        "first_outcome": first.outcome,
        "model": model,
        "recon_run_id": str(recon_run_id),
        "replay_deltas": deltas,
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
                    SELECT id, status FROM official_site_crawl_run
                    WHERE workspace_id = :workspace_id AND recon_run_id = :recon_run_id
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
                      (SELECT count(*) FROM official_site_fetch_attempt
                       WHERE crawl_run_id = :crawl_run_id) AS attempt_count,
                      (SELECT count(*) FROM official_site_page_snapshot
                       WHERE crawl_run_id = :crawl_run_id) AS snapshot_count,
                      (SELECT count(*) FROM official_site_corpus_checkpoint
                       WHERE crawl_run_id = :crawl_run_id) AS checkpoint_count,
                      (SELECT count(*) FROM official_site_extraction_operation
                       WHERE crawl_run_id = :crawl_run_id) AS extraction_operation_count,
                      (SELECT count(*) FROM official_site_extraction_operation
                       WHERE crawl_run_id = :crawl_run_id
                         AND state = 'materialized') AS materialized_operation_count,
                      (SELECT count(*) FROM official_site_extraction_operation
                       WHERE crawl_run_id = :crawl_run_id
                         AND state = 'spend_unknown') AS extraction_spend_unknown_count,
                      (SELECT count(*) FROM claim
                       WHERE workspace_id = :workspace_id
                         AND source_key = 'official_site'
                         AND run_id IN (
                           SELECT fast_run_id FROM recon_run WHERE id = :recon_run_id
                           UNION ALL
                           SELECT background_run_id FROM recon_run WHERE id = :recon_run_id
                         )) AS official_claim_count,
                      (SELECT count(*) FROM claim AS claim_row
                       WHERE claim_row.workspace_id = :workspace_id
                         AND claim_row.source_key = 'official_site'
                         AND claim_row.run_id IN (
                           SELECT fast_run_id FROM recon_run WHERE id = :recon_run_id
                           UNION ALL
                           SELECT background_run_id FROM recon_run WHERE id = :recon_run_id
                         )
                         AND NOT EXISTS (
                           SELECT 1 FROM official_site_page_snapshot AS snapshot
                           JOIN official_site_corpus_checkpoint AS checkpoint
                             ON checkpoint.crawl_run_id = snapshot.crawl_run_id
                            AND checkpoint.snapshot_ids_json ? snapshot.id::text
                           WHERE snapshot.crawl_run_id = :crawl_run_id
                             AND claim_row.source_snapshot_ref =
                                 'official-site-page:' || snapshot.id::text
                             AND claim_row.source_url = snapshot.final_url
                             AND claim_row.artifact_key = snapshot.artifact_key
                         )) AS invalid_provenance_count
                    """
                ),
                {
                    "crawl_run_id": crawl_run_id,
                    "workspace_id": workspace_id,
                    "recon_run_id": recon_run_id,
                },
            )
        )
        .mappings()
        .one()
    )
    operations = (
        (
            await conn.execute(
                text(
                    """
                    SELECT state, model_id, answering_model_id, count(*) AS count
                    FROM official_site_extraction_operation
                    WHERE crawl_run_id = :crawl_run_id
                    GROUP BY state, model_id, answering_model_id
                    ORDER BY state, model_id, answering_model_id
                    """
                ),
                {"crawl_run_id": crawl_run_id},
            )
        )
        .mappings()
        .all()
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
        **dict(counts),
        "checkpoints": [dict(item) for item in checkpoints],
        "crawl_run_id": str(crawl_run_id),
        "operation_states": [dict(item) for item in operations],
        "status": run["status"],
    }


def main() -> None:
    print(json.dumps(asyncio.run(_run()), indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
